"""Settings — JSON-typed key/value the engine reads via `${settings.*}`.

Phase 3 keeps this dirt simple: a flat map with GET (all keys) and PUT
(by key). Phase 4 will surface this in the UI as the Settings page.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from api.deps import EngineSurface, get_surface
from api.schemas import SettingValue
from hollerbox.store import SettingRow, repo, session_scope

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=dict[str, Any])
def get_all_settings(surface: EngineSurface = Depends(get_surface)) -> dict[str, Any]:
    with session_scope(surface.session_factory) as s:
        rows = s.scalars(select(SettingRow)).all()
        return {row.key: row.value for row in rows}


@router.put("/{key}", response_model=SettingValue)
def set_setting(
    key: str, body: SettingValue, surface: EngineSurface = Depends(get_surface)
) -> SettingValue:
    with session_scope(surface.session_factory) as s:
        repo.set_setting(s, key, body.value)
    return body
