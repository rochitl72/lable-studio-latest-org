"""Removed: live-collaboration WebSocket.

The single-user-per-project model replaced same-image multi-user co-editing, so
the live-collaboration WebSocket was removed. This stub remains only so any
stale import doesn't crash; it registers nothing. The whole
`app/api/collaboration/` folder can be deleted.
"""
from fastapi import APIRouter

router = APIRouter()
