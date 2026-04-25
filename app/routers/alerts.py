import json

from fastapi import APIRouter

from database import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/")
async def list_alerts(type: str = None, watch_uuid: str = None, limit: int = 200):
    with get_db() as conn:
        if watch_uuid:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE watch_uuid = ? ORDER BY changed_at DESC LIMIT ?",
                (watch_uuid, limit),
            ).fetchall()
        elif type:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE type = ? ORDER BY changed_at DESC LIMIT ?",
                (type, limit),
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
    from services.changedetection import changedetection

    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        content = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE type = 'content'"
        ).fetchone()[0]

    try:
        cd_watches = await changedetection.list_watches()
        watch_count = len(cd_watches)
    except Exception:
        watch_count = 0

    return {
        "total_alerts": total,
        "content_alerts": content,
        "total_watches": watch_count,
    }
