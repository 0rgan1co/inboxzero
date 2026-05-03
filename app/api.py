"""HTTP endpoints para el sync local. Protegidos por API key (header X-Api-Key)."""
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from . import config, db

router = APIRouter()


def _check_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not config.SYNC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SYNC_API_KEY no configurado en el servidor.",
        )
    if x_api_key != config.SYNC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o ausente. Mandar header X-Api-Key.",
        )


class MarkSyncedBody(BaseModel):
    ids: list[int]


@router.get("/pending", dependencies=[Depends(_check_api_key)])
def get_pending(limit: int = 500) -> dict:
    items = db.list_pending(limit=limit)
    return {"count": len(items), "items": items}


@router.post("/mark-synced", dependencies=[Depends(_check_api_key)])
def post_mark_synced(body: MarkSyncedBody) -> dict:
    n = db.mark_synced(body.ids)
    return {"updated": n}


@router.get("/stats", dependencies=[Depends(_check_api_key)])
def get_stats() -> dict:
    return db.stats()


# --- v2: reminders ---

@router.get("/reminders/unsynced", dependencies=[Depends(_check_api_key)])
def get_reminders_unsynced(limit: int = 200) -> dict:
    items = db.list_reminders_unsynced(limit=limit)
    return {"count": len(items), "items": items}


@router.post("/reminders/mark-synced", dependencies=[Depends(_check_api_key)])
def post_reminders_mark_synced(body: MarkSyncedBody) -> dict:
    n = db.mark_reminders_synced(body.ids)
    return {"updated": n}
