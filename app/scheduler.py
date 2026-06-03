import asyncio
import html
import json
import logging
import re
import time
import unicodedata
from urllib.parse import urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import get_db
from services.crawler import crawler
from services.ai_client import ai_client

logger = logging.getLogger(__name__)

_MAX_PAGES = 5
_MAX_KNOWN_TITLES = 200
_WATCH_LOCKS: dict[str, asyncio.Lock] = {}


def _normalize(t: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", html.unescape(t))).strip()


def _is_list_url(href: str, watch_url: str) -> bool:
    """href가 목록(watch) URL과 실질적으로 동일한지 확인 — 목록 링크가 detail href로 저장되는 것을 방지.

    path만 비교하면 list.do?seq=123 같은 detail URL까지 걸러낸다.
    fragment(#)를 제거한 뒤 path + query 모두 일치할 때만 목록 URL로 판단한다.
    """
    try:
        h = urlparse(href.split('#')[0])
        l = urlparse(watch_url.split('#')[0])
        return (h.scheme == l.scheme and h.netloc == l.netloc
                and h.path == l.path and h.query == l.query)
    except Exception:
        return False


# ── DB 헬퍼 ───────────────────────────────────────────────────────────────────

def db_save_alert(
    watch_uuid: str,
    url: str,
    analysis: dict,
    changed_at: int,
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO alerts (watch_uuid, url, type, analysis, changed_at)
            VALUES (?, ?, '', ?, ?)
            """,
            (
                watch_uuid,
                url,
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
    if uuid not in _WATCH_LOCKS:
        _WATCH_LOCKS[uuid] = asyncio.Lock()
    if _WATCH_LOCKS[uuid].locked():
        logger.info(f"[{uuid}] already running, skipping")
        return
    async with _WATCH_LOCKS[uuid]:
        await _process_watch_inner(watch)


async def _process_watch_inner(watch: dict) -> None:
    uuid = watch["uuid"]
    url = watch["url"]
    css_selector = watch.get("css_selector")
    next_page_selector = watch.get("next_page_selector")

    if not css_selector:
        return

    known_titles_raw = watch.get("known_titles")
    known_titles_list: list[str] = json.loads(known_titles_raw or "[]")
    known_titles_set: set[str] = {_normalize(t) for t in known_titles_list}

    now = int(time.time())
    db_update_crawled(uuid, now)
    all_new_items: list[dict] = []
    seen_across_pages: set[str] = set()
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
                    current_url, next_sel,  # type: ignore[arg-type]
                    element_selector=css_selector,
                )
                current_url = page_info["current_url"]

            dom_titles = page_info.get("dom_titles", [])
            if dom_titles:
                dom_titles = await ai_client.filter_titles(dom_titles, image_b64=page_info.get("image"))
            if dom_titles:
                items = [{"title": t, "summary": "", "href": None} for t in dom_titles]
            else:
                raw = await ai_client.extract_titles_from_text(page_info["element_text"])
                items = [{"title": i["title"], "summary": i.get("summary", ""), "href": None} for i in raw]

            items = [
                {"title": _normalize(i["title"]), "summary": i.get("summary", ""), "href": i.get("href")}
                for i in items
            ]

            # 링크 매칭 (title → href)
            # 목록 페이지 자신을 가리키는 링크는 detail href로 쓸 수 없으므로 제외
            title_links = [
                l for l in page_info.get("title_links", [])
                if not _is_list_url(l["href"], url)
            ]
            link_map = {_normalize(l["title"]): l["href"] for l in title_links}
            for item in items:
                if not item.get("href") and item["title"] in link_map:
                    item["href"] = link_map[item["title"]]

            # AI fuzzy 매칭 폴백 (DOM 매칭 실패 항목)
            unmatched = [item for item in items if not item.get("href")]
            if unmatched and title_links:
                try:
                    ai_hrefs = await ai_client.find_href_for_titles(
                        [item["title"] for item in unmatched],
                        title_links,
                    )
                    for item in unmatched:
                        if ai_hrefs.get(item["title"]):
                            item["href"] = ai_hrefs[item["title"]]
                except Exception as e:
                    logger.warning(f"AI href matching failed for {uuid}: {e}")

            # AI javascript: 표현식 → URL 추론 (href 여전히 없는 항목)
            js_hints_raw = page_info.get("js_hints", [])
            if js_hints_raw:
                js_hints = [
                    {"title": _normalize(h["title"]), "js_attr": h["js_attr"]}
                    for h in js_hints_raw
                ]
                still_unmatched = [item for item in items if not item.get("href")]
                relevant = [h for h in js_hints if h["title"] in {i["title"] for i in still_unmatched}]
                if relevant:
                    try:
                        inferred = await ai_client.infer_hrefs_from_js(current_url, relevant)
                        for item in still_unmatched:
                            if inferred.get(item["title"]):
                                item["href"] = inferred[item["title"]]
                                logger.info(f"AI js-infer href: [{item['title'][:40]}] → {item['href']}")
                    except Exception as e:
                        logger.warning(f"AI js-href inference failed for {uuid}: {e}")

        except Exception as e:
            logger.error(f"crawl failed for {uuid} page {page_num}: {e}")
            break

        if not items:
            break

        new_items = []
        reached_known = False
        for item in items:
            if item["title"] in known_titles_set:
                reached_known = True
            else:
                new_items.append(item)

        found_new = bool(new_items)

        for item in new_items:
            if item["title"] not in seen_across_pages:
                seen_across_pages.add(item["title"])
                item["_page_url"] = current_url
                all_new_items.append(item)

        # known 항목 만나면/새 항목 없으면 중단 (최대 _MAX_PAGES 페이지)
        if reached_known or not found_new:
            break

        next_sel = (
            page_info.get("next_seq_selector")
            or next_page_selector
            or await ai_client.find_next_selector(page_info["image"], page_info["elements"])
        )
        if not next_sel:
            break
        logger.info(f"[{uuid}] page {page_num + 1} 이동 (selector: {next_sel})")

    if not all_new_items:
        return

    known_to_add = [item["title"] for item in all_new_items]
    alert_items = all_new_items

    # 상세 내용 수집
    # href 있는 항목: 직접 URL 접근 (클릭 불필요)
    # href 없는 항목: 클릭 기반 수집 (click-based로 href + text 동시 획득)
    page_groups: dict[str, list[dict]] = {}
    for item in alert_items:
        page_url = item.pop("_page_url", url)
        page_groups.setdefault(page_url, []).append(item)

    for page_url, group in page_groups.items():
        # href 있는 항목: 직접 상세 페이지 접근
        for item in [i for i in group if i.get("href")]:
            try:
                text = await crawler.get_detail_text(item["href"])
                summary = await ai_client.summarize_detail(text)
                if summary:
                    item["summary"] = summary
            except Exception as e:
                logger.warning(f"direct detail failed [{item['title'][:40]}]: {e}")

        # href 없는 항목: 클릭 기반 수집
        no_href = [i for i in group if not i.get("href")]
        if no_href:
            try:
                click_texts = await crawler.get_detail_texts_by_click(
                    page_url, css_selector, [item["title"] for item in no_href]
                )
                for item in no_href:
                    result = click_texts.get(item["title"])
                    if not result:
                        continue
                    if result.get("url") and result["url"] != page_url:
                        item["href"] = result["url"]
                    if result.get("text"):
                        summary = await ai_client.summarize_detail(result["text"])
                        if summary:
                            item["summary"] = summary
                    elif result.get("screenshot_b64"):
                        # AJAX/SPA: URL 불변 → AI가 스크린샷에서 직접 내용 추출
                        text = await ai_client.extract_detail_from_screenshot(
                            result["screenshot_b64"], item["title"]
                        )
                        if text:
                            summary = await ai_client.summarize_detail(text)
                            if summary:
                                item["summary"] = summary
            except Exception as e:
                logger.warning(f"click-based detail failed for {page_url}: {e}")

    for item in alert_items:
        db_save_alert(
            uuid, url,
            {"title": item["title"], "summary": item.get("summary", ""), "href": item.get("href")},
            now,
        )
        logger.info(f"Alert saved: [{item['title']}] {url}")

    updated = (known_to_add + known_titles_list)[:_MAX_KNOWN_TITLES]
    db_save_known_titles(uuid, updated, now)


# ── 요약 재시도 ───────────────────────────────────────────────────────────────

async def retry_missing_summaries(watch: dict) -> None:
    """summary 없는 최근 알림을 대상으로 상세 수집·요약을 재시도한다."""
    uuid = watch["uuid"]
    url = watch["url"]
    css_selector = watch.get("css_selector")

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, analysis FROM alerts WHERE watch_uuid = ? ORDER BY changed_at DESC LIMIT 20",
            (uuid,),
        ).fetchall()

    to_retry = []
    for row in rows:
        try:
            analysis = json.loads(row["analysis"] or "{}")
        except Exception:
            continue
        if not analysis.get("summary"):
            to_retry.append({"id": row["id"], "analysis": analysis})

    if not to_retry:
        return

    logger.info(f"[{uuid}] retry summary: {len(to_retry)}개 대상")

    # href 있는 항목 — 직접 상세 페이지 접근
    href_items = [i for i in to_retry if i["analysis"].get("href")]
    for item in href_items:
        try:
            text = await crawler.get_detail_text(item["analysis"]["href"])
            summary = await ai_client.summarize_detail(text)
            if summary:
                item["analysis"]["summary"] = summary
                with get_db() as conn:
                    conn.execute(
                        "UPDATE alerts SET analysis = ? WHERE id = ?",
                        (json.dumps(item["analysis"], ensure_ascii=False), item["id"]),
                    )
                logger.info(f"retry summary OK: alert {item['id']}")
        except Exception as e:
            logger.warning(f"retry summary failed (href): alert {item['id']}: {e}")

    # href 없는 항목 — css_selector로 클릭 기반 재시도
    no_href_items = [i for i in to_retry if not i["analysis"].get("href")]
    if no_href_items and css_selector:
        try:
            titles = [i["analysis"]["title"] for i in no_href_items if i["analysis"].get("title")]
            click_texts = await crawler.get_detail_texts_by_click(url, css_selector, titles)
            for item in no_href_items:
                title = item["analysis"].get("title", "")
                result = click_texts.get(title)
                if result:
                    if result.get("url") and result["url"] != url:
                        item["analysis"]["href"] = result["url"]
                    text = result.get("text") or ""
                    if not text and result.get("screenshot_b64"):
                        text = await ai_client.extract_detail_from_screenshot(
                            result["screenshot_b64"], title
                        )
                    summary = await ai_client.summarize_detail(text) if text else ""
                    if summary:
                        item["analysis"]["summary"] = summary
                        with get_db() as conn:
                            conn.execute(
                                "UPDATE alerts SET analysis = ? WHERE id = ?",
                                (json.dumps(item["analysis"], ensure_ascii=False), item["id"]),
                            )
                        logger.info(f"retry summary OK (click): alert {item['id']}")
        except Exception as e:
            logger.warning(f"retry summary failed (click): {uuid}: {e}")


# ── 폴링 메인 루프 ────────────────────────────────────────────────────────────

async def poll_changes() -> None:
    logger.info("Polling watches from DB...")
    now = int(time.time())
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT uuid, url, css_selector,
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
