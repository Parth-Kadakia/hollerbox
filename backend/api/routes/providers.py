"""Provider inventory — mirrors `hollerbox providers list` over HTTP.

Surfaces what text + image providers are configured on this install so
the UI's Settings page can show "ready / missing-sdk / no-key" the same
way the CLI does. Read-only.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import EngineSurface, get_surface

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderStatus(BaseModel):
    name: str
    kind: Literal["text", "image"]
    status: Literal["ready", "missing-sdk", "no-key"]
    detail: str


class ProvidersResponse(BaseModel):
    text: list[ProviderStatus]
    image: list[ProviderStatus]


# Each provider knows which secret it needs. `mock` and `ollama` need none.
_TEXT_PROVIDERS: list[tuple[str, str | None]] = [
    ("mock", None),
    ("ollama", None),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
]
_IMAGE_PROVIDERS: list[tuple[str, str]] = [
    ("openai", "OPENAI_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
]


def _row(
    registered: dict, secret_store, name: str, key_name: str | None, *, kind: str
) -> ProviderStatus:
    # No-key providers (mock, ollama) are always ready when registered.
    if key_name is None and name in registered:
        host = getattr(registered[name], "_host", None)
        return ProviderStatus(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            status="ready",
            detail=f"host={host}" if host else "",
        )
    if name in registered:
        return ProviderStatus(
            name=name, kind=kind, status="ready", detail=f"secret={key_name}"  # type: ignore[arg-type]
        )
    if key_name and secret_store.has(key_name):
        return ProviderStatus(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            status="missing-sdk",
            detail="secret set; install with `uv sync --extra llm`",
        )
    return ProviderStatus(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        status="no-key",
        detail=f"set {key_name} to enable" if key_name else "",
    )


@router.get("", response_model=ProvidersResponse)
def list_providers(surface: EngineSurface = Depends(get_surface)) -> ProvidersResponse:
    text = [
        _row(surface.providers, surface.secret_store, name, key, kind="text")
        for name, key in _TEXT_PROVIDERS
    ]
    image = [
        _row(surface.image_providers, surface.secret_store, name, key, kind="image")
        for name, key in _IMAGE_PROVIDERS
    ]
    return ProvidersResponse(text=text, image=image)
