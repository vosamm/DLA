import difflib
import json
import logging
import re

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import get_db
from services.changedetection import changedetection
from services.ollama import ollama

logger = logging.getLogger(__name__)


def determine_type(title: str, tags) -> str:
    return "content"


def is_trivial_change(diff_text: str) -> bool:
    """변경된 내용이 숫자(조회수·건수 등)만 바뀐 경우 True 반환."""
    added = [
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    removed = [
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]

    if not added and not removed:
        return True

    # 숫자를 모두 제거했을 때 추가·삭제 내용이 동일하면 숫자만 바뀐 것
    def strip_nums(lines):
        return [re.sub(r"[\d,]+", "", l).strip() for l in lines]

    if strip_nums(added) == strip_nums(removed):
        logger.info("Trivial numeric change detected, skipping.")
        return True

    return False


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


# ── 변경 처리 ─────────────────────────────────────────────────────────────────
async def process_watch(uuid: str, url: str, title: str, type_: str, last_changed: int):
    try:
        history = await changedetection.get_history(uuid)
        timestamps = sorted(history.keys(), key=lambda x: int(x))

        if not timestamps:
            return

        current = await changedetection.get_snapshot(uuid, timestamps[-1])

        if len(timestamps) >= 2:
            previous = await changedetection.get_snapshot(uuid, timestamps[-2])
            diff_lines = list(
                difflib.unified_diff(
                    previous.splitlines(),
                    current.splitlines(),
                    lineterm="",
                    n=2,
                )
            )
            diff_text = "\n".join(diff_lines[:200])
        else:
            diff_text = current[:2000]

        if not diff_text.strip() or is_trivial_change(diff_text):
            db_mark_processed(uuid, last_changed)
            return

        logger.info(f"[{type_.upper()}] Analyzing change: {url}")
        image_bytes = await changedetection.get_screenshot(uuid)
        analysis = await ollama.analyze(url, title, diff_text, image_bytes=image_bytes)
        db_save_alert(uuid, url, type_, analysis, diff_text, last_changed)
        db_mark_processed(uuid, last_changed)
        logger.info(f"Alert saved for: {url}")

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

    for uuid, data in watches.items():
        url = data.get("url", "")
        title = data.get("title", "")
        tags = data.get("tags", [])
        last_changed = data.get("last_changed") or 0
        type_ = determine_type(title, tags)

        db_upsert_watch(uuid, url, title, type_, last_changed)

        if last_changed and last_changed > db_get_last_processed(uuid):
            await process_watch(uuid, url, title, type_, last_changed)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(poll_changes, "interval", seconds=settings.poll_interval)
    scheduler.start()
    logger.info(f"Scheduler started (interval: {settings.poll_interval}s)")
    return scheduler
