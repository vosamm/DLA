import json

from fastapi import APIRouter

from database import get_db
from services.changedetection import changedetection

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/")
async def list_alerts(watch_uuid: str = None, limit: int = 200):
    with get_db() as conn:
        if watch_uuid:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE watch_uuid = ? ORDER BY changed_at DESC LIMIT ?",
                (watch_uuid, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY changed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    return [
        {**dict(r), "analysis": json.loads(r["analysis"])}
        for r in rows
    ]


@router.get("/stats")
async def get_stats():
    try:
        cd_watches = await changedetection.list_watches()
        watch_count = len(cd_watches)
    except Exception:
        watch_count = 0

    return {"total_watches": watch_count}
