import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import init_db
from routers import alerts, watches
from scheduler import poll_changes, start_scheduler
from services.changedetection import changedetection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Notice Ping...")
    init_db()
    try:
        n = await changedetection.migrate_to_playwright()
        if n:
            logger.info(f"Migrated {n} watches to Playwright fetcher")
    except Exception as e:
        logger.warning(f"Playwright migration skipped: {e}")
    scheduler = start_scheduler()
    asyncio.create_task(poll_changes())
    logger.info("Notice Ping running.")
    yield
    scheduler.shutdown()
    logger.info("Notice Ping stopped.")


app = FastAPI(title="Notice Ping", version="1.0.0", lifespan=lifespan)

app.include_router(alerts.router)
app.include_router(watches.router)

static_path = Path(__file__).parent / "static"

# /assets — Vite build output (JS/CSS chunks).  Only mount when the directory
# exists so the server starts cleanly even before the first `npm run build`.
_assets_path = static_path / "assets"
if _assets_path.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets_path)), name="assets")

# /static — legacy mount kept for backwards compat (old bookmarks, help.html, etc.)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(static_path / "index.html")
