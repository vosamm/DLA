from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
from services.changedetection import changedetection

router = APIRouter(prefix="/api/watches", tags=["watches"])


class WatchCreate(BaseModel):
    url: str
    title: str = ""
    type: str = "content"  # "content" | "market"
    ignore_top_lines: int | None = None


class WatchUpdate(BaseModel):
    title: str
    type: str | None = None
    ignore_top_lines: int | None = None


@router.get("/")
async def list_watches():
    try:
        cd_watches = await changedetection.list_watches()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    with get_db() as conn:
        local = {
            r["uuid"]: dict(r)
            for r in conn.execute("SELECT * FROM watches").fetchall()
        }

    result = []
    for uuid, data in cd_watches.items():
        title = data.get("title", "")
        local_data = local.get(uuid, {})
        type_ = local_data.get("type") or "content"
        ignore_top_lines = local_data.get("ignore_top_lines")
        result.append({
            "uuid": uuid,
            "url": data.get("url", ""),
            "title": title,
            "type": type_,
            "ignore_top_lines": ignore_top_lines,
            "last_changed": data.get("last_changed"),
        })

    return sorted(result, key=lambda x: x["last_changed"] or 0, reverse=True)


@router.post("/")
async def create_watch(body: WatchCreate):
    try:
        result = await changedetection.create_watch(body.url, body.title)
        uuid = result.get("uuid", "")
        if uuid:
            with get_db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO watches (uuid, url, title, type, ignore_top_lines) VALUES (?, ?, ?, ?, ?)",
                    (uuid, body.url, body.title, body.type, body.ignore_top_lines),
                )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{uuid}")
async def update_watch(uuid: str, body: WatchUpdate):
    try:
        await changedetection.update_watch(uuid, body.title)
        with get_db() as conn:
            updates = ["title = ?"]
            params: list = [body.title]
            if "type" in body.model_fields_set:
                updates.append("type = ?")
                params.append(body.type)
            if "ignore_top_lines" in body.model_fields_set:
                updates.append("ignore_top_lines = ?")
                params.append(body.ignore_top_lines)
            params.append(uuid)
            conn.execute(
                f"UPDATE watches SET {', '.join(updates)} WHERE uuid = ?", params
            )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{uuid}")
async def delete_watch(uuid: str):
    cd_error = None
    try:
        await changedetection.delete_watch(uuid)
    except Exception as e:
        cd_error = str(e)

    with get_db() as conn:
        conn.execute("DELETE FROM watches WHERE uuid = ?", (uuid,))
        conn.execute("DELETE FROM alerts WHERE watch_uuid = ?", (uuid,))

    if cd_error and "404" not in cd_error and "400" not in cd_error:
        raise HTTPException(status_code=500, detail=cd_error)

    return {"ok": True}
