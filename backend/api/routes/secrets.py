"""Write-only secrets endpoints (§10).

The API never returns secret values. List returns names + a presence
flag; PUT accepts a value; DELETE removes by name. Values only exist
in-memory during a `Runner` execution and are redacted from every
persisted record.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import EngineSurface, get_surface
from api.schemas import SecretPresence, SecretWriteRequest

router = APIRouter(prefix="/secrets", tags=["secrets"])


@router.get("", response_model=list[SecretPresence])
def list_secrets(surface: EngineSurface = Depends(get_surface)) -> list[SecretPresence]:
    names = surface.secret_store.list_names()
    return [SecretPresence(name=n) for n in names]


@router.put("/{name}", response_model=SecretPresence)
def set_secret(
    name: str,
    body: SecretWriteRequest,
    surface: EngineSurface = Depends(get_surface),
) -> SecretPresence:
    if not name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "secret name must be non-empty")
    surface.secret_store.set(name, body.value)
    return SecretPresence(name=name)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret(
    name: str, surface: EngineSurface = Depends(get_surface)
) -> None:
    removed = surface.secret_store.delete(name)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"secret {name!r} not found")
