"""Liveness probe — also doubles as smoke test for the FastAPI scaffold."""

from __future__ import annotations

from fastapi import APIRouter

from hollerbox import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
