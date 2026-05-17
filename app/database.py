import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watches (
                uuid TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT,
                type TEXT DEFAULT 'content',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_uuid TEXT NOT NULL,
                url TEXT NOT NULL,
                type TEXT NOT NULL,
                analysis TEXT NOT NULL,
                changed_at INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (watch_uuid) REFERENCES watches(uuid)
            );
        """)
        # 마이그레이션: 기존 테이블에 컬럼 추가 (이미 있으면 무시)
        for stmt in [
            "ALTER TABLE watches ADD COLUMN css_selector TEXT",
            "ALTER TABLE watches ADD COLUMN crawl_interval_hours INTEGER DEFAULT 12",
            "ALTER TABLE watches ADD COLUMN last_crawled INTEGER DEFAULT 0",
            "ALTER TABLE watches ADD COLUMN next_page_selector TEXT",
            "ALTER TABLE watches ADD COLUMN known_titles TEXT",
        ]:
            try:
                conn.execute(stmt)
            except Exception as e:
                logger.debug(f"Migration skipped ({stmt.split()[2]}): {e}")
