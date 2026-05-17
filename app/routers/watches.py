import base64
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
from services.crawler import crawler
from services.ai_client import ai_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watches", tags=["watches"])


# ── 스키마 ─────────────────────────────────────────────────────────────────────

class WatchCreate(BaseModel):
    url: str
    title: str = ""
    type: str = "content"


class WatchUpdate(BaseModel):
    title: str | None = None
    crawl_interval_hours: int | None = None
    next_page_selector: str | None = None


class NavigateRequest(BaseModel):
    current_url: str
    next_selector: str


class AnalyzeRegionRequest(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    page_height: int
    viewport_width: int
    elements: list[dict] = []


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _get_watch_url(watch_uuid: str) -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT url FROM watches WHERE uuid = ?", (watch_uuid,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Watch not found")
    return row["url"]


# ── 엔드포인트 ─────────────────────────────────────────────────────────────────

@router.get("/")
async def list_watches():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT uuid, url, title, type,
                   css_selector, next_page_selector, last_crawled, crawl_interval_hours
            FROM watches
            ORDER BY last_crawled DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/")
async def create_watch(body: WatchCreate):
    new_uuid = str(uuid.uuid4())
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO watches
                    (uuid, url, title, type, crawl_interval_hours, last_crawled)
                VALUES (?, ?, ?, ?, 12, 0)
                """,
                (new_uuid, body.url, body.title or body.url, body.type),
            )
    except Exception as e:
        logger.error(f"create_watch failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    return {"uuid": new_uuid, "url": body.url, "title": body.title}


@router.put("/{uuid}")
async def update_watch(uuid: str, body: WatchUpdate):
    updates: list[str] = []
    params: list = []

    if body.title is not None:
        updates.append("title = ?")
        params.append(body.title)
    if body.crawl_interval_hours is not None:
        updates.append("crawl_interval_hours = ?")
        params.append(body.crawl_interval_hours)
    if "next_page_selector" in body.model_fields_set:
        updates.append("next_page_selector = ?")
        params.append(body.next_page_selector)

    if not updates:
        return {"ok": True}

    params.append(uuid)
    try:
        with get_db() as conn:
            conn.execute(
                f"UPDATE watches SET {', '.join(updates)} WHERE uuid = ?", params
            )
    except Exception as e:
        logger.error(f"update_watch {uuid} failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True}


@router.delete("/{uuid}")
async def delete_watch(uuid: str):
    with get_db() as conn:
        conn.execute("DELETE FROM alerts WHERE watch_uuid = ?", (uuid,))
        conn.execute("DELETE FROM watches WHERE uuid = ?", (uuid,))
    return {"ok": True}


@router.get("/{uuid}/element-map")
async def get_element_map(uuid: str):
    url = _get_watch_url(uuid)
    try:
        result = await crawler.get_element_map(url)
    except Exception as e:
        logger.error(f"get_element_map failed for watch {uuid}: {e}")
        raise HTTPException(status_code=502, detail=str(e))

    return result


@router.post("/{uuid}/analyze-region")
async def analyze_region(uuid: str, body: AnalyzeRegionRequest):
    """드래그 선택 영역을 AI로 분석해 css_selector + next_page_selector 자동 저장."""
    url = _get_watch_url(uuid)

    roi = {
        "x1": body.x1 / body.viewport_width,
        "y1": body.y1 / body.page_height,
        "x2": body.x2 / body.viewport_width,
        "y2": body.y2 / body.page_height,
    }

    css_selector = None
    next_page_selector = None
    titles: list[str] = []
    error_msg = ""

    try:
        screenshot = await crawler.screenshot_roi(url, roi)
        image_b64 = base64.b64encode(screenshot).decode()

        result = await ai_client.identify_selectors(image_b64, body.elements)
        css_selector = result.get("content_selector")
        next_page_selector = result.get("next_page_selector")

        if css_selector:
            try:
                el_shot = await crawler.screenshot_element(url, css_selector)
                items = await ai_client.extract_titles(base64.b64encode(el_shot).decode())
                titles = [item["title"] for item in items]
            except Exception as e:
                logger.warning(f"title extraction failed for watch {uuid}: {e}")

            with get_db() as conn:
                conn.execute(
                    "UPDATE watches SET css_selector = ?, next_page_selector = ?, known_titles = NULL WHERE uuid = ?",
                    (css_selector, next_page_selector, uuid),
                )
    except Exception as e:
        logger.error(f"analyze_region failed for watch {uuid}: {e}")
        error_msg = str(e)

    return {
        "css_selector": css_selector,
        "next_page_selector": next_page_selector,
        "titles": titles,
        "error": error_msg,
    }


@router.post("/{uuid}/element-map/navigate")
async def navigate_element_map(uuid: str, body: NavigateRequest):
    """next_selector 클릭 후 다음 페이지의 element map 반환."""
    url = body.current_url or _get_watch_url(uuid)
    try:
        result = await crawler.navigate_and_get_element_map(url, body.next_selector)
    except Exception as e:
        logger.error(f"navigate_element_map failed for watch {uuid}: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    return result


@router.post("/{uuid}/crawl")
async def trigger_crawl(uuid: str):
    """즉시 크롤을 트리거한다. scheduler의 process_watch를 직접 호출."""
    from scheduler import process_watch  # 순환 import 방지용 지연 import

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM watches WHERE uuid = ?", (uuid,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Watch not found")

    watch = dict(row)
    try:
        await process_watch(watch)
    except Exception as e:
        logger.error(f"trigger_crawl failed for watch {uuid}: {e}")
        raise HTTPException(status_code=502, detail=str(e))

    return {"ok": True}
