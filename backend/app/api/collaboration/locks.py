"""Soft locking — one annotator per image at a time.

Flow from the frontend:
  1. Opening an image  → POST /api/images/{id}/lock
  2. While editing     → POST /api/images/{id}/lock every ~30s (heartbeat)
  3. Leaving the image → DELETE /api/images/{id}/lock

A lock whose heartbeat has gone stale (LOCK_TIMEOUT_SECONDS) is silently taken
over, so a closed laptop never strands an image.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import current_user
from app.db.database import get_db
from app.models import Image, ImageLock, User, utcnow

router = APIRouter(prefix="/api/images", tags=["locks"])


class LockOut(BaseModel):
    locked: bool
    held_by_me: bool
    username: str = ""
    user_id: int | None = None
    expires_in: int = 0


def _is_stale(lock: ImageLock) -> bool:
    age = utcnow() - _aware(lock.heartbeat_at)
    return age > timedelta(seconds=settings.LOCK_TIMEOUT_SECONDS)


def _aware(dt):
    """SQLite hands back naive datetimes; Postgres returns aware ones."""
    from datetime import timezone

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _current_lock(db: AsyncSession, image_id: int) -> ImageLock | None:
    """Return the live lock for an image, clearing it first if it has expired."""
    lock = await db.scalar(select(ImageLock).where(ImageLock.image_id == image_id))
    if lock and _is_stale(lock):
        await db.delete(lock)
        await db.flush()
        return None
    return lock


@router.post("/{image_id}/lock", response_model=LockOut)
async def acquire_lock(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Take or refresh the lock. Idempotent — also serves as the heartbeat."""
    image = await db.get(Image, image_id)
    if not image:
        raise HTTPException(404, "Image not found")

    lock = await _current_lock(db, image_id)

    if lock and lock.user_id != user.id:
        holder = await db.get(User, lock.user_id)
        remaining = settings.LOCK_TIMEOUT_SECONDS - int(
            (utcnow() - _aware(lock.heartbeat_at)).total_seconds()
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"{holder.username if holder else 'Another user'} "
                           f"is annotating this image.",
                "username": holder.username if holder else "",
                "expires_in": max(remaining, 0),
            },
        )

    if lock:
        lock.heartbeat_at = utcnow()
    else:
        lock = ImageLock(image_id=image_id, user_id=user.id)
        db.add(lock)

    await db.commit()
    return LockOut(
        locked=True,
        held_by_me=True,
        username=user.username,
        user_id=user.id,
        expires_in=settings.LOCK_TIMEOUT_SECONDS,
    )


@router.delete("/{image_id}/lock")
async def release_lock(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    """Release a lock you hold. Admins may force-release anyone's."""
    lock = await db.scalar(select(ImageLock).where(ImageLock.image_id == image_id))
    if not lock:
        return {"ok": True, "released": False}
    if lock.user_id != user.id and not user.is_admin:
        raise HTTPException(403, "This image is locked by another user")
    await db.delete(lock)
    await db.commit()
    return {"ok": True, "released": True}


@router.get("/{image_id}/lock", response_model=LockOut)
async def get_lock(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    lock = await _current_lock(db, image_id)
    await db.commit()  # persist expiry cleanup
    if not lock:
        return LockOut(locked=False, held_by_me=False)

    holder = await db.get(User, lock.user_id)
    remaining = settings.LOCK_TIMEOUT_SECONDS - int(
        (utcnow() - _aware(lock.heartbeat_at)).total_seconds()
    )
    return LockOut(
        locked=True,
        held_by_me=lock.user_id == user.id,
        username=holder.username if holder else "",
        user_id=lock.user_id,
        expires_in=max(remaining, 0),
    )


async def assert_can_edit(db: AsyncSession, image_id: int, user: User) -> None:
    """Raise if someone else currently holds this image.

    Called by the annotation endpoints so the lock is enforced server-side —
    a client that skips the lock call still cannot write to a held image.
    """
    lock = await _current_lock(db, image_id)
    if lock and lock.user_id != user.id:
        holder = await db.get(User, lock.user_id)
        raise HTTPException(
            status_code=409,
            detail=f"{holder.username if holder else 'Another user'} is "
                   f"currently annotating this image.",
        )
