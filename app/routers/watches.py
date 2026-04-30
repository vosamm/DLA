from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
from services.changedetection import changedetection

router = APIRouter(prefix="/api/watches", tags=["watches"])


class WatchCreate(BaseModel):
    url: str
    title: str = ""
    type: str = "content"  # "content" | "market"


class WatchUpdate(BaseModel):
    title: str
    type: str | None = None


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
        tags = data.get("tags", [])
        type_ = local.get(uuid, {}).get("type") or "content"
        result.append({
            "uuid": uuid,
            "url": data.get("url", ""),
            "title": title,
            "type": type_,
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
                    "INSERT OR IGNORE INTO watches (uuid, url, title, type) VALUES (?, ?, ?, ?)",
                    (uuid, body.url, body.title, body.type),
                )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{uuid}")
async def update_watch(uuid: str, body: WatchUpdate):
    try:
        await changedetection.update_watch(uuid, body.title)
        with get_db() as conn:
            if body.type is not None:
                conn.execute(
                    "UPDATE watches SET title = ?, type = ? WHERE uuid = ?",
                    (body.title, body.type, uuid),
                )
            else:
                conn.execute("UPDATE watches SET title = ? WHERE uuid = ?", (body.title, uuid))
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
