import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from config import settings


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
                last_changed INTEGER DEFAULT 0,
                last_processed INTEGER DEFAULT 0,
                ignore_top_lines INTEGER DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_uuid TEXT NOT NULL,
                url TEXT NOT NULL,
                type TEXT NOT NULL,
                analysis TEXT NOT NULL,
                diff_text TEXT,
                detail_url TEXT,
                changed_at INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (watch_uuid) REFERENCES watches(uuid)
            );
        """)
        # 마이그레이션: 기존 테이블에 컬럼 추가 (이미 있으면 무시)
        try:
            conn.execute("ALTER TABLE watches ADD COLUMN ignore_top_lines INTEGER DEFAULT NULL")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE alerts ADD COLUMN detail_url TEXT")
        except Exception:
            pass
