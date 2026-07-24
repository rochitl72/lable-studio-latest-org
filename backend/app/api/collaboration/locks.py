"""Removed: image soft-locks.

Per-image locking belonged to the old multi-user model and has been removed
along with the ImageLock table. This stub remains only so a stale import can't
crash; it registers nothing. The whole `app/api/collaboration/` folder can be
deleted.
"""
from fastapi import APIRouter

router = APIRouter()
