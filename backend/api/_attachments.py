"""Build `FileAttachment` lists from step outputs.

Shared between the chat (`/conversations/{id}/messages`) and the run
detail (`/runs/{id}`) routes — both want to surface files produced by
a run so the UI can render images inline and other files as download
links. The sandbox rule for actually serving these files lives in
`api/routes/files.py`; this module just classifies and packages paths.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import quote

from api.schemas import FileAttachment

# Match the upload prefix written by routes/files.py: 32 hex chars + "-".
_UPLOAD_PREFIX_RE = re.compile(r"^[0-9a-f]{32}-")


def _display_name(filename: str) -> str:
    """Strip the upload uuid prefix so the UI shows the original name."""
    return _UPLOAD_PREFIX_RE.sub("", filename)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_PATH_KEYS_SINGLE = ("path", "out_path", "output_path")
_PATH_KEYS_PLURAL = ("paths", "files", "outputs")


def _extract_path_strings(output: dict) -> list[str]:
    out: list[str] = []
    for key in _PATH_KEYS_SINGLE:
        v = output.get(key)
        if isinstance(v, str):
            out.append(v)
    for key in _PATH_KEYS_PLURAL:
        v = output.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    out.append(item)
    return out


def attachments_for_output(output: dict | None) -> list[FileAttachment]:
    """Turn one step's `output` dict into attachment records.

    De-duplicates by resolved path so a step that lists the same file
    under both `path` and `paths` only surfaces once.
    """
    if not output:
        return []
    out: list[FileAttachment] = []
    seen: set[str] = set()
    for raw in _extract_path_strings(output):
        p = Path(raw).expanduser()
        try:
            norm = str(p.resolve(strict=False))
        except (OSError, RuntimeError):
            norm = raw
        if norm in seen:
            continue
        seen.add(norm)
        is_image = p.suffix.lower() in _IMAGE_EXTS or (
            (mimetypes.guess_type(p.name)[0] or "").startswith("image/")
        )
        size = p.stat().st_size if p.is_file() else None
        out.append(
            FileAttachment(
                kind="image" if is_image else "file",
                path=norm,
                url=f"/files?path={quote(norm)}",
                name=_display_name(p.name),
                size_bytes=size,
            )
        )
    return out
