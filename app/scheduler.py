import difflib
import json
import logging
import re

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import get_db
from services.browser import browser_service
from services.changedetection import changedetection
from services.ollama import ollama

logger = logging.getLogger(__name__)


# ── DB 헬퍼 ───────────────────────────────────────────────────────────────────
def db_get_last_processed(uuid: str) -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT last_processed FROM watches WHERE uuid = ?", (uuid,)
        ).fetchone()
        return row["last_processed"] if row else 0


def db_upsert_watch(uuid: str, url: str, title: str, type_: str, last_changed: int):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO watches (uuid, url, title, type, last_changed)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(uuid) DO UPDATE SET
                url          = excluded.url,
                title        = excluded.title,
                type         = excluded.type,
                last_changed = excluded.last_changed
            """,
            (uuid, url, title, type_, last_changed),
        )


def db_mark_processed(uuid: str, last_changed: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE watches SET last_processed = ? WHERE uuid = ?",
            (last_changed, uuid),
        )


def db_save_alert(
    watch_uuid: str,
    url: str,
    type_: str,
    analysis: dict,
    diff_text: str,
    changed_at: int,
    detail_url: str | None = None,
):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO alerts (watch_uuid, url, type, analysis, diff_text, detail_url, changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (watch_uuid, url, type_, json.dumps(analysis, ensure_ascii=False), diff_text, detail_url, changed_at),
        )


# ── 파이프라인 헬퍼 ───────────────────────────────────────────────────────────
def extract_diff_lines(previous: str, current: str, skip: int) -> tuple[list[str], list[str]]:
    diff = difflib.unified_diff(
        previous.splitlines()[skip:],
        current.splitlines()[skip:],
        lineterm="",
        n=0,
    )
    new_lines, removed_lines = [], []
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            text = line[1:].strip()
            if text:
                new_lines.append(text)
        elif line.startswith("-") and not line.startswith("---"):
            text = line[1:].strip()
            if text:
                removed_lines.append(text)
    return new_lines, removed_lines


_TRIVIAL_LINE_PATTERNS = [
    re.compile(r'^조회\s*\d+'),
    re.compile(r'^추천\s*\d+'),
    re.compile(r'^(hit|view|click)s?\s*:?\s*\d+', re.IGNORECASE),
]


def is_trivial_line(line: str) -> bool:
    return any(p.search(line) for p in _TRIVIAL_LINE_PATTERNS)


def is_trivial_change(new_lines: list[str], removed_lines: list[str]) -> bool:
    """숫자만 바뀐 경우, 또는 커뮤니티 점수·조회수 패턴이면 True."""
    if not new_lines and not removed_lines:
        return True

    if new_lines and all(is_trivial_line(l) for l in new_lines):
        return True

    def strip_nums(lines: list[str]) -> list[str]:
        return [re.sub(r"[\d,]+", "", l).strip() for l in lines]

    stripped_new = strip_nums(new_lines)
    stripped_removed = strip_nums(removed_lines)
    return stripped_new == stripped_removed and any(s for s in stripped_new)


def dedup_by_prefix(items: list[dict], min_prefix: int = 15) -> list[dict]:
    """같은 기사의 제목과 발췌가 중복 감지되지 않도록 공통 접두사 기반 중복 제거."""
    unique: list[dict] = []
    for item in items:
        title = item["title"]
        is_dup = False
        for existing in unique:
            prefix_len = 0
            for a, b in zip(title, existing["title"]):
                if a == b:
                    prefix_len += 1
                else:
                    break
            if prefix_len >= min_prefix:
                is_dup = True
                break
        if not is_dup:
            unique.append(item)
    return unique


# ── 변경 처리 ─────────────────────────────────────────────────────────────────
async def _get_diff(uuid: str, last_processed: int, skip: int) -> tuple[list[str], list[str]]:
    """현재 스냅샷과 baseline의 diff 라인을 반환."""
    history = await changedetection.get_history(uuid)
    timestamps = sorted(history.keys(), key=lambda x: int(x))
    if not timestamps:
        return [], []

    current_text = await changedetection.get_snapshot(uuid, timestamps[-1])
    baseline_ts = next(
        (ts for ts in reversed(timestamps[:-1]) if int(ts) <= last_processed),
        timestamps[-2] if len(timestamps) >= 2 else None,
    )

    if baseline_ts:
        previous_text = await changedetection.get_snapshot(uuid, baseline_ts)
        new_lines, removed_lines = extract_diff_lines(previous_text, current_text, skip)
        return new_lines[:settings.max_diff_lines], removed_lines
    else:
        new_lines = [l.strip() for l in current_text.splitlines()[skip:] if l.strip()][:settings.max_diff_lines]
        return new_lines, []


def _save_new_alerts(
    uuid: str, url: str, type_: str,
    results: list[dict], diff_text: str, last_changed: int,
) -> int:
    """중복 확인 후 새 알림 저장. 저장된 수 반환."""
    saved_count = 0
    for item in results:
        found_title = item.get("title", "")
        summary = item.get("summary", "")
        detail_url = item.get("detail_url")
        if not found_title:
            continue
        with get_db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM alerts WHERE watch_uuid = ? AND json_extract(analysis, '$.title') = ?",
                (uuid, found_title),
            ).fetchone()
        if exists:
            logger.info(f"Duplicate alert skipped: [{found_title}]")
            continue
        db_save_alert(uuid, url, type_, {"title": found_title, "summary": summary}, diff_text, last_changed, detail_url)
        logger.info(f"Alert saved: [{found_title}] {url}")
        saved_count += 1
    return saved_count


async def process_watch(uuid: str, url: str, title: str, type_: str, last_changed: int, ignore_top_lines: int | None = None) -> None:
    skip = ignore_top_lines if ignore_top_lines is not None else settings.ignore_top_lines
    try:
        last_processed = db_get_last_processed(uuid)
        new_lines, removed_lines = await _get_diff(uuid, last_processed, skip)

        if not new_lines:
            db_mark_processed(uuid, last_changed)
            return

        if is_trivial_change(new_lines, removed_lines):
            logger.info(f"Trivial change (numbers only), skipping: {url}")
            db_mark_processed(uuid, last_changed)
            return

        # LLM 분석: market 타입은 Vision, content 타입은 텍스트
        if type_ == "market":
            screenshot = await changedetection.get_screenshot(uuid)
            results = await ollama.analyze_market(new_lines, screenshot)
        else:
            results = await ollama.analyze(new_lines)

        if not results:
            db_mark_processed(uuid, last_changed)
            return

        results = dedup_by_prefix(results)

        # ── detail 보강: 상위 N개 alert만 상세 페이지 fetch 후 summary 교체 ──
        enriched = []
        for i, item in enumerate(results):
            title = item.get("title", "")
            summary = item.get("summary", "")
            detail_url = None
            if i < settings.detail_fetch_max_alerts:
                result = await browser_service.get_detail_content(url, title)
                if result:
                    detail_text, detail_url = result
                    better_summary = await ollama.summarize(title, detail_text)
                    if better_summary:
                        summary = better_summary
                        logger.info(f"Detail summary enriched: [{title}] {detail_url}")
            enriched.append({"title": title, "summary": summary, "detail_url": detail_url})
        results = enriched

        saved_count = _save_new_alerts(uuid, url, type_, results, "\n".join(new_lines), last_changed)
        db_mark_processed(uuid, last_changed)
        if saved_count == 0:
            logger.info(f"No new alerts for {url}")

    except Exception as e:
        logger.error(f"Error processing watch {uuid} ({url}): {e}")


# ── 폴링 메인 루프 ────────────────────────────────────────────────────────────
async def poll_changes():
    logger.info("Polling changedetection.io...")
    try:
        watches = await changedetection.list_watches()
    except Exception as e:
        logger.warning(f"Could not reach changedetection.io: {e}")
        return

    with get_db() as conn:
        saved_watches = {
            r["uuid"]: dict(r)
            for r in conn.execute("SELECT uuid, type, ignore_top_lines, last_processed FROM watches").fetchall()
        }

    for uuid, data in watches.items():
        url = data.get("url", "")
        title = data.get("title", "")
        last_changed = data.get("last_changed") or 0
        saved = saved_watches.get(uuid, {})
        type_ = saved.get("type") or "content"
        ignore_top_lines = saved.get("ignore_top_lines")
        last_processed = saved.get("last_processed") or 0

        db_upsert_watch(uuid, url, title, type_, last_changed)

        if last_changed and last_changed > last_processed:
            await process_watch(uuid, url, title, type_, last_changed, ignore_top_lines)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(poll_changes, "interval", seconds=settings.poll_interval)
    scheduler.start()
    logger.info(f"Scheduler started (interval: {settings.poll_interval}s)")
    return scheduler
