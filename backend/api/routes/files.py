"""Sandboxed file server for workflow outputs.

Browsers can't read absolute local paths like `/tmp/foo.png`, so when a
chat result references a file the UI hits `GET /files?path=...` to fetch
it. The path is only served if it appears in some `step_runs.output`
column (`path`, `paths`, `out_path`) — i.e. an actual step produced it.
Everything else is 403. This keeps the endpoint useful without becoming
"read any file the user account can".
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from api.deps import EngineSurface, get_surface
from hollerbox.store import StepRunRow, session_scope

router = APIRouter(prefix="/files", tags=["files"])


def _all_step_output_paths(surface: EngineSurface) -> set[str]:
    """Every file path mentioned in any persisted step output.

    SQLite + JSON columns means we can't filter at the DB layer cleanly,
    so we materialize a snapshot in Python. Fine for v1 (single-user,
    local data); a real index lands when this becomes a hot path.
    """
    seen: set[str] = set()
    with session_scope(surface.session_factory) as s:
        rows = s.scalars(select(StepRunRow)).all()
        for r in rows:
            out = r.output or {}
            for key in ("path", "out_path", "output_path"):
                v = out.get(key)
                if isinstance(v, str):
                    seen.add(_normalize(v))
            for key in ("paths", "files", "outputs"):
                v = out.get(key)
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            seen.add(_normalize(item))
    return seen


def _normalize(path_str: str) -> str:
    """Best-effort path canonicalization — symlinks etc. resolved when possible."""
    try:
        return str(Path(path_str).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return path_str


@router.get("")
def get_file(
    path: str = Query(..., description="Absolute path produced by a step run."),
    surface: EngineSurface = Depends(get_surface),
) -> FileResponse:
    target = _normalize(path)
    allowed = _all_step_output_paths(surface)
    if target not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "path is not associated with any recorded step output",
        )
    p = Path(target)
    if not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file does not exist")

    media_type, _ = mimetypes.guess_type(str(p))
    return FileResponse(path=str(p), media_type=media_type or "application/octet-stream")
