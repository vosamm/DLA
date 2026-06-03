import json

from fastapi import APIRouter
from pydantic import BaseModel

from database import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _parse_alert_row(r) -> dict:
    row = dict(r)
    row.pop("type", None)
    try:
        row["analysis"] = json.loads(r["analysis"])
    except (json.JSONDecodeError, TypeError):
        row["analysis"] = {}
    return row


@router.get("/")
async def list_alerts(watch_uuid: str | None = None, limit: int = 200):
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

    return [_parse_alert_row(r) for r in rows]


class DeleteAlertsRequest(BaseModel):
    ids: list[int]


@router.delete("/")
async def delete_alerts(body: DeleteAlertsRequest):
    if not body.ids:
        return {"ok": True, "deleted": 0}
    placeholders = ",".join("?" * len(body.ids))
    with get_db() as conn:
        conn.execute(f"DELETE FROM alerts WHERE id IN ({placeholders})", body.ids)
    return {"ok": True, "deleted": len(body.ids)}
