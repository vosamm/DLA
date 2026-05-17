import asyncio
import json
import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import get_db
from services.crawler import crawler
from services.ai_client import ai_client

logger = logging.getLogger(__name__)

_MAX_PAGES = 5
_MAX_KNOWN_TITLES = 200


# ── DB 헬퍼 ───────────────────────────────────────────────────────────────────

def db_save_alert(
    watch_uuid: str,
    url: str,
    type_: str,
    analysis: dict,
    changed_at: int,
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO alerts (watch_uuid, url, type, analysis, changed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                watch_uuid,
                url,
                type_,
                json.dumps(analysis, ensure_ascii=False),
                changed_at,
            ),
        )


def db_save_known_titles(uuid: str, titles: list[str], crawled_at: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE watches SET known_titles = ?, last_crawled = ? WHERE uuid = ?",
            (json.dumps(titles, ensure_ascii=False), crawled_at, uuid),
        )


def db_update_crawled(uuid: str, crawled_at: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE watches SET last_crawled = ? WHERE uuid = ?",
            (crawled_at, uuid),
        )


# ── 변경 처리 ─────────────────────────────────────────────────────────────────

async def process_watch(watch: dict) -> None:
    uuid = watch["uuid"]
    url = watch["url"]
    type_ = watch.get("type") or "content"
    css_selector = watch.get("css_selector")
    next_page_selector = watch.get("next_page_selector")

    if not css_selector:
        return

    known_titles_raw = watch.get("known_titles")
    first_crawl = known_titles_raw is None
    known_titles_list: list[str] = json.loads(known_titles_raw or "[]")
    known_titles_set: set[str] = set(known_titles_list)

    now = int(time.time())
    all_new_items: list[dict] = []
    current_url = url

    next_sel: str | None = None

    for page_num in range(1, _MAX_PAGES + 1):
        try:
            if page_num == 1:
                page_info = await crawler.get_page_content(
                    current_url, selector=css_selector
                )
            else:
                page_info = await crawler.navigate_and_get_content(
                    current_url, next_sel,  # type: ignore[arg-type]  # always non-None here
                    element_selector=css_selector,
                )
                current_url = page_info["current_url"]
            dom_titles = page_info.get("dom_titles", [])
            if dom_titles:
                items = [{"title": t, "summary": ""} for t in dom_titles]
            else:
                items = await ai_client.extract_titles(page_info["element_image"])
        except Exception as e:
            logger.error(f"crawl failed for {uuid} page {page_num}: {e}")
            break

        if not items:
            break

        if first_crawl:
            for item in items:
                title = item["title"]
                if title not in known_titles_set:
                    known_titles_list.append(title)
                    known_titles_set.add(title)
            break  # 첫 크롤은 1페이지만 시딩

        new_items = []
        reached_known = False
        for item in items:
            if item["title"] in known_titles_set:
                reached_known = True
                break
            new_items.append(item)

        all_new_items.extend(new_items)
        if reached_known:
            break  # 아는 항목 발견 → 이후 페이지 불필요

        next_sel = next_page_selector or await ai_client.find_next_selector(
            page_info["image"], page_info["elements"]
        )
        if not next_sel:
            break
        logger.info(f"[{uuid}] page {page_num + 1} 이동")

    if first_crawl:
        seeded = known_titles_list[:_MAX_KNOWN_TITLES]
        logger.info(f"First crawl for {uuid}: seeded {len(seeded)} titles")
        db_save_known_titles(uuid, seeded, now)
    elif all_new_items:
        for item in all_new_items:
            db_save_alert(
                uuid, url, type_,
                {"title": item["title"], "summary": item.get("summary", "")},
                now,
            )
            logger.info(f"Alert saved: [{item['title']}] {url}")
        new_titles = [item["title"] for item in all_new_items]
        updated = (new_titles + known_titles_list)[:_MAX_KNOWN_TITLES]
        db_save_known_titles(uuid, updated, now)
    else:
        db_update_crawled(uuid, now)


# ── 폴링 메인 루프 ────────────────────────────────────────────────────────────

async def poll_changes() -> None:
    logger.info("Polling watches from DB...")
    now = int(time.time())
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT uuid, url, type, css_selector,
                       crawl_interval_hours, last_crawled,
                       next_page_selector, known_titles
                FROM watches
                WHERE css_selector IS NOT NULL
                  AND (? - COALESCE(last_crawled, 0)) >= COALESCE(crawl_interval_hours, 12) * 3600
                """,
                (now,),
            ).fetchall()
        pending = [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Could not load watches from DB: {e}")
        return

    if not pending:
        return

    results = await asyncio.gather(*(process_watch(w) for w in pending), return_exceptions=True)
    for w, result in zip(pending, results):
        if isinstance(result, Exception):
            logger.error(f"process_watch failed for {w['uuid']}: {result}")


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_changes,
        "interval",
        seconds=settings.poll_interval,
        max_instances=3,
        coalesce=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started (interval: {settings.poll_interval}s)")
    return scheduler
