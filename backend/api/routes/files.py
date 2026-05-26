"""Sandboxed file server + user upload endpoint.

Browsers can't read absolute local paths like `/tmp/foo.png`, so when a
chat result references a file the UI hits `GET /files?path=...` to fetch
it. The path is only served if it appears in some `step_runs.output`
column **or** lives inside the uploads directory (files the user
deliberately handed us). Everything else is 403. This keeps the endpoint
useful without becoming "read any file the user account can".

User uploads land under `${HOLLERBOX_DATA_DIR or ~/.hollerbox}/uploads/`
with a uuid prefix so collisions don't matter.
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import EngineSurface, get_surface
from hollerbox.store import StepRunRow, session_scope

router = APIRouter(prefix="/files", tags=["files"])

# Cap individual uploads at a sane size so a runaway client can't fill
# the disk. 25 MB matches typical "drop a doc/image into chat" patterns.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _uploads_dir() -> Path:
    import os

    base = os.environ.get("HOLLERBOX_DATA_DIR")
    root = Path(base).expanduser() if base else Path("~/.hollerbox").expanduser()
    d = root / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


class UploadResponse(BaseModel):
    path: str
    url: str
    name: str
    size_bytes: int
    content_type: str | None = None


def _all_step_output_paths(surface: EngineSurface) -> set[str]:
    """Every file path mentioned in any persisted step output.

    SQLite + JSON columns means we can't filter at the DB layer cleanly,
    so we materialize a snapshot in Python. Fine for v1 (single-user,
    local data); a real index lands when this becomes a hot path.
    """
    from api._attachments import attachments_for_output

    seen: set[str] = set()
    with session_scope(surface.session_factory) as s:
        rows = s.scalars(select(StepRunRow)).all()
        for r in rows:
            for att in attachments_for_output(r.output):
                seen.add(att.path)
    return seen


def _normalize(path_str: str) -> str:
    """Best-effort path canonicalization — symlinks etc. resolved when possible."""
    try:
        return str(Path(path_str).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return path_str


@router.get("")
def get_file(
    path: str = Query(..., description="Absolute path produced by a step run or uploaded by the user."),
    surface: EngineSurface = Depends(get_surface),
) -> FileResponse:
    target = _normalize(path)
    p = Path(target)
    # Two sandbox rules: step outputs (`/files?path=...` from chat/run UI)
    # and uploads (chat attachments the user just sent).
    allowed = (target in _all_step_output_paths(surface)) or _is_under(p, _uploads_dir())
    if not allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "path is not associated with any recorded step output or upload",
        )
    if not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file does not exist")

    media_type, _ = mimetypes.guess_type(str(p))
    return FileResponse(path=str(p), media_type=media_type or "application/octet-stream")


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile) -> UploadResponse:
    """Accept one user-provided file. Saved under the uploads directory
    with a uuid prefix; the chat can then reference it as an attachment."""
    if not file.filename:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "missing filename"
        )

    safe_name = Path(file.filename).name  # strip any path traversal attempt
    target = _uploads_dir() / f"{uuid.uuid4().hex}-{safe_name}"
    bytes_written = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > _MAX_UPLOAD_BYTES:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        413,
                        f"upload exceeds limit of {_MAX_UPLOAD_BYTES} bytes",
                    )
                out.write(chunk)
    finally:
        await file.close()

    norm = str(target.resolve(strict=False))
    media_type, _ = mimetypes.guess_type(safe_name)
    return UploadResponse(
        path=norm,
        url=f"/files?path={norm}",
        name=safe_name,
        size_bytes=bytes_written,
        content_type=media_type,
    )
