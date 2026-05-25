"""FastAPI application entry point — Phase 3.

Wraps the engine over HTTP. The engine itself never imports from `api/`
(enforced by `tests/test_engine_imports_clean.py`); this layer translates
HTTP into engine calls and back.

The app's `lifespan` builds a single `EngineSurface` (DB engine, secret
store, providers, runner) and, by default, starts the background worker
that drives `queued` runs. Set `HOLLERBOX_WORKER_ENABLED=0` to suppress
the worker (tests rely on this so they can drive runs deterministically).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.deps import EngineSurface, build_surface
from api.routes import (
    approvals,
    conversations,
    files,
    health,
    providers,
    runs,
    secrets,
    settings,
    workflows,
)
from api.worker import Worker


def _worker_enabled() -> bool:
    return os.environ.get("HOLLERBOX_WORKER_ENABLED", "1") != "0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tests pre-set `app.state.surface` before TestClient runs the lifespan,
    # so they don't have to mount a real DB/key on the user's home dir.
    surface: EngineSurface | None = getattr(app.state, "surface", None)
    if surface is None:
        surface = build_surface()
        app.state.surface = surface

    worker: Worker | None = None
    if _worker_enabled():
        worker = Worker(surface)
        await worker.start()
    app.state.worker = worker

    try:
        yield
    finally:
        if worker is not None:
            await worker.stop()


def create_app() -> FastAPI:
    """App factory — used by `uvicorn api.main:app` and by tests.

    Tests override `get_surface` after construction; production starts
    the worker as part of the lifespan.
    """
    app = FastAPI(
        title="HollerBox",
        version="0.0.1",
        description="Local-first, chat-driven AI workflow engine.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(workflows.router)
    app.include_router(runs.router)
    app.include_router(approvals.router)
    app.include_router(providers.router)
    app.include_router(secrets.router)
    app.include_router(settings.router)
    app.include_router(conversations.router)
    app.include_router(files.router)
    return app


app = create_app()
