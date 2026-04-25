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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting VisualMonitor...")
    init_db()
    await asyncio.sleep(5)  # wait for dependent services
    await poll_changes()
    scheduler = start_scheduler()
    logger.info("VisualMonitor running.")
    yield
    scheduler.shutdown()
    logger.info("VisualMonitor stopped.")


app = FastAPI(title="VisualMonitor", version="1.0.0", lifespan=lifespan)

app.include_router(alerts.router)
app.include_router(watches.router)

static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(static_path / "index.html")
