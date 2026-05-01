import json
import logging
import re

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import get_db
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
):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO alerts (watch_uuid, url, type, analysis, diff_text, changed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (watch_uuid, url, type_, json.dumps(analysis, ensure_ascii=False), diff_text, changed_at),
        )


# ── 파이프라인 헬퍼 ───────────────────────────────────────────────────────────
def extract_diff_lines(previous: str, current: str, skip: int) -> tuple[list[str], list[str]]:
    import difflib
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
    re.compile(r'^\d+\s+points?\s+by\s+\S+', re.IGNORECASE),  # "N point(s) by username ..."
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


# 상업성 키워드 (광고/스팸 사전 필터)
_AD_KEYWORDS = [
    "공장직영", "후불결제", "후불 결제",
    "24시간배송", "24시간 배송", "페카매입", "당일배송", "무료배송",
    "공장가", "도매가", "특가판매", "할인쿠폰", "최저가보장",
    "구매문의", "판매문의", "재고문의", "A/S문의",
]


def is_commercial_spam(new_lines: list[str]) -> bool:
    """상업성 키워드가 2개 이상 포함된 경우 광고/스팸으로 판단."""
    combined = " ".join(new_lines)
    hit_count = sum(1 for kw in _AD_KEYWORDS if kw in combined)
    return hit_count >= 2


# ── 변경 처리 ─────────────────────────────────────────────────────────────────
async def process_watch(uuid: str, url: str, title: str, type_: str, last_changed: int, ignore_top_lines: int | None = None):
    skip = ignore_top_lines if ignore_top_lines is not None else settings.ignore_top_lines
    try:
        history = await changedetection.get_history(uuid)
        timestamps = sorted(history.keys(), key=lambda x: int(x))

        if not timestamps:
            return

        current_ts = timestamps[-1]
        current_text = await changedetection.get_snapshot(uuid, current_ts)

        # 마지막으로 처리한 스냅샷을 baseline으로 사용.
        # 히스토리에 남아있으면 그 스냅샷을, 없으면 바로 이전 스냅샷을 사용.
        last_processed = db_get_last_processed(uuid)
        baseline_ts = next(
            (ts for ts in reversed(timestamps[:-1]) if int(ts) <= last_processed),
            timestamps[-2] if len(timestamps) >= 2 else None,
        )

        if baseline_ts:
            previous_text = await changedetection.get_snapshot(uuid, baseline_ts)
            new_lines, removed_lines = extract_diff_lines(previous_text, current_text, skip)
        else:
            new_lines = [l.strip() for l in current_text.splitlines()[skip:] if l.strip()][:30]
            removed_lines = []

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
            if is_commercial_spam(new_lines):
                logger.info(f"Commercial spam detected, skipping: {url}")
                db_mark_processed(uuid, last_changed)
                return
            results = await ollama.analyze(new_lines)

        if not results:
            db_mark_processed(uuid, last_changed)
            return

        diff_text = "\n".join(new_lines)
        saved_count = 0
        for item in results:
            found_title = item.get("title", "")
            summary = item.get("summary", "")
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

            analysis = {"title": found_title, "summary": summary}
            db_save_alert(uuid, url, type_, analysis, diff_text, last_changed)
            logger.info(f"Alert saved: [{found_title}] {url}")
            saved_count += 1

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
            for r in conn.execute("SELECT uuid, type, ignore_top_lines FROM watches").fetchall()
        }

    for uuid, data in watches.items():
        url = data.get("url", "")
        title = data.get("title", "")
        last_changed = data.get("last_changed") or 0
        saved = saved_watches.get(uuid, {})
        type_ = saved.get("type") or "content"
        ignore_top_lines = saved.get("ignore_top_lines")

        db_upsert_watch(uuid, url, title, type_, last_changed)

        if last_changed and last_changed > db_get_last_processed(uuid):
            await process_watch(uuid, url, title, type_, last_changed, ignore_top_lines)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(poll_changes, "interval", seconds=settings.poll_interval)
    scheduler.start()
    logger.info(f"Scheduler started (interval: {settings.poll_interval}s)")
    return scheduler
