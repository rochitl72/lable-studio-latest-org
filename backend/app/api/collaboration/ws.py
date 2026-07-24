"""Live collaboration over WebSockets.

Each image is a "room". Everyone viewing the same image joins its room and
receives:
  * presence   — who else is here (broadcast on join/leave)
  * cursor      — other users' cursor positions (ephemeral)
  * changed     — someone created/edited/deleted an annotation; the receiver
                  re-fetches the image's annotations from the REST API, which
                  is the source of truth. This keeps persistence in one place
                  (the REST handlers + Postgres) and avoids a second write path.

Auth: the browser can't set an Authorization header on a WebSocket, so the
token comes in as a query parameter (?token=...). Membership is enforced on
connect, so a non-member can't even open the socket.
"""
import logging
from collections import defaultdict

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import _user_from_token
from app.db.database import AsyncSessionLocal
from app.models import Image
from app.services import membership

log = logging.getLogger("annoforge.ws")

router = APIRouter()


class RoomManager:
    """In-memory registry of who is connected to each image room.

    In-memory is the right scope here: a single-server deployment has one
    process, so one dict is the whole truth. (A multi-process deployment would
    need Redis pub/sub instead — out of scope for the single-server target.)
    """

    def __init__(self) -> None:
        # image_id → list of (websocket, {"user_id", "username"})
        self.rooms: dict[int, list[tuple[WebSocket, dict]]] = defaultdict(list)

    async def join(self, image_id: int, ws: WebSocket, who: dict) -> None:
        self.rooms[image_id].append((ws, who))
        await self.broadcast_presence(image_id)

    def leave(self, image_id: int, ws: WebSocket) -> None:
        room = self.rooms.get(image_id)
        if not room:
            return
        self.rooms[image_id] = [(w, u) for (w, u) in room if w is not ws]
        if not self.rooms[image_id]:
            del self.rooms[image_id]

    def members(self, image_id: int) -> list[dict]:
        # De-duplicate by user_id so two tabs from one person show once.
        seen: dict[int, dict] = {}
        for _ws, who in self.rooms.get(image_id, []):
            seen[who["user_id"]] = who
        return list(seen.values())

    async def broadcast(self, image_id: int, message: dict, exclude: WebSocket | None = None) -> None:
        for ws, _who in list(self.rooms.get(image_id, [])):
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                # A dead socket is cleaned up on its own disconnect handler.
                pass

    async def broadcast_presence(self, image_id: int) -> None:
        await self.broadcast(
            image_id,
            {"type": "presence", "users": self.members(image_id)},
        )


manager = RoomManager()


async def _authenticate(token: str, image_id: int):
    """Resolve the token to a user who is allowed on this image's project."""
    async with AsyncSessionLocal() as db:
        user = await _user_from_token(db, token)
        if not user:
            return None
        image = await db.scalar(select(Image).where(Image.id == image_id))
        if not image:
            return None
        if not await membership.is_member(db, image.project_id, user):
            return None
        return {"user_id": user.id, "username": user.username}


@router.websocket("/ws/images/{image_id}")
async def image_room(
    websocket: WebSocket,
    image_id: int,
    token: str = Query(""),
):
    who = await _authenticate(token, image_id)
    if not who:
        await websocket.close(code=4401)  # unauthorized
        return

    await websocket.accept()
    await manager.join(image_id, websocket, who)
    log.info("ws join image=%s user=%s", image_id, who["username"])

    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")

            if mtype == "changed":
                # Someone mutated an annotation via REST; tell everyone else to
                # re-fetch. We attach who did it for a subtle "updated by X" hint.
                await manager.broadcast(
                    image_id,
                    {
                        "type": "annotations_changed",
                        "action": msg.get("action"),
                        "annotation_id": msg.get("annotation_id"),
                        "by": who["username"],
                    },
                    exclude=websocket,
                )
            elif mtype == "cursor":
                await manager.broadcast(
                    image_id,
                    {
                        "type": "cursor",
                        "user_id": who["user_id"],
                        "username": who["username"],
                        "x": msg.get("x"),
                        "y": msg.get("y"),
                    },
                    exclude=websocket,
                )
            # Unknown message types are ignored.
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws error image=%s user=%s", image_id, who["username"])
    finally:
        manager.leave(image_id, websocket)
        await manager.broadcast_presence(image_id)
        log.info("ws leave image=%s user=%s", image_id, who["username"])
