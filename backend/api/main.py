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

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from api.auth import configure_auth
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

log = logging.getLogger("hollerbox.api")


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

    if _auto_import_templates_enabled():
        _bootstrap_templates(surface)

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


def _auto_import_templates_enabled() -> bool:
    return os.environ.get("HOLLERBOX_AUTO_IMPORT_TEMPLATES", "1") != "0"


def _bootstrap_templates(surface: EngineSurface) -> None:
    """Register bundled templates as real workflows on startup.

    Two cases handled:
    1. **New template**: name isn't in the DB → import it.
    2. **Upgraded template**: bundled `version:` is higher than what's
       in the DB → re-import to pick up the fix. (Bump the template's
       `version:` whenever you change one and want users to get the
       update on next restart.)

    We never overwrite a workflow whose stored version is >= the
    bundled one — that protects user edits where they bumped their own
    version.
    """
    from api.routes.workflows import _templates_dir
    from hollerbox.core.workflow import WorkflowLoadError, load_workflow_from_source
    from hollerbox.store import repo, session_scope

    d = _templates_dir()
    if not d.is_dir():
        return
    imported: list[str] = []
    upgraded: list[str] = []
    skipped: list[str] = []
    with session_scope(surface.session_factory) as s:
        by_name = {row.name: row for row in repo.list_workflows(s)}
        for path in sorted(d.glob("*.y*ml")):
            try:
                yaml_source = path.read_text(encoding="utf-8")
                wf = load_workflow_from_source(yaml_source, name_hint=path.stem)
            except (OSError, WorkflowLoadError) as exc:
                log.warning("template %s failed to load: %s", path.name, exc)
                continue
            existing = by_name.get(wf.name)
            if existing is None:
                repo.upsert_workflow(s, wf, yaml_source=yaml_source)
                imported.append(wf.name)
                continue
            if wf.version > existing.version:
                repo.upsert_workflow(s, wf, yaml_source=yaml_source)
                upgraded.append(f"{wf.name} v{existing.version}→v{wf.version}")
                continue
            skipped.append(wf.name)
    if imported:
        log.info("Imported %d template(s): %s", len(imported), ", ".join(imported))
    if upgraded:
        log.info("Upgraded %d template(s): %s", len(upgraded), ", ".join(upgraded))
    if skipped:
        log.debug("Skipped %d existing workflow(s): %s", len(skipped), ", ".join(skipped))


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

    token = configure_auth(app)
    if token:
        log.warning(
            "HollerBox API is auth-protected. Token: %s — paste this into the web app "
            "when prompted, or send `Authorization: Bearer %s` on every request.",
            token, token,
        )

    # Mount the prebuilt web UI if it's available next to the backend. This
    # is what turns the dev "two terminals" setup into a single-process app:
    # one port serves both the API at `/...` and the SPA at `/` (with
    # client-side routing fallback to index.html for unknown paths).
    _mount_web_ui(app)
    return app


def _web_dist_dir() -> Path | None:
    """Find the built SPA. Checked in order:
    1. `HOLLERBOX_WEB_DIST` env var
    2. `<repo>/web/dist` (sibling of `backend/`)
    3. Inside the packaged bundle (PyInstaller / .app), `web/dist/`
       next to the executable.
    """
    env = os.environ.get("HOLLERBOX_WEB_DIST")
    if env:
        p = Path(env).expanduser()
        return p if p.is_dir() else None
    # backend/api/main.py → ../../../web/dist
    repo_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if repo_dist.is_dir():
        return repo_dist
    import sys

    bundle_dist = Path(getattr(sys, "_MEIPASS", "")) / "web" / "dist" if hasattr(sys, "_MEIPASS") else None
    if bundle_dist and bundle_dist.is_dir():
        return bundle_dist
    return None


def _mount_web_ui(app: FastAPI) -> None:
    dist = _web_dist_dir()
    if dist is None:
        log.info("Web UI not mounted: no built `web/dist` found. Run `cd web && npm run build`.")
        return
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    index = dist / "index.html"

    # Assets at `/assets/...` (Vite's default), plus PWA artifacts.
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")
    # Other top-level files (logo, manifest, sw, workbox-*, registerSW)
    # are served by a catch-all that falls through to index.html for SPA
    # routes.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):  # noqa: ANN202
        candidate = dist / full_path
        if full_path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(str(candidate))
        # Anything else → SPA shell. React Router handles the rest.
        return FileResponse(str(index))

    log.info("Web UI mounted from %s", dist)


app = create_app()
