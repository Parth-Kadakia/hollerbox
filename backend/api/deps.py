"""Engine surface + FastAPI dependency wiring.

The `EngineSurface` is a single, lifespan-scoped bundle of the engine
primitives a route handler needs: a SQLAlchemy session factory, a
`SecretStore`, a `Runner`, and the pub/sub event bus that SSE consumers
read from. Routes ask for it via `Depends(get_surface)`.

Tests construct an `EngineSurface` directly (in-memory SQLite, throwaway
key file) and override `get_surface` on the app — see `tests/test_api_*`.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from hollerbox.core.runner import Runner
from hollerbox.providers.base import Provider
from hollerbox.providers.image_base import ImageProvider
from hollerbox.secrets import DEFAULT_KEY_FILE, SecretStore
from hollerbox.store import (
    init_db,
    make_engine,
    make_session_factory,
)


@dataclass
class EngineSurface:
    """Lifespan-scoped engine handle the API hands to every request."""

    session_factory: sessionmaker[Session]
    secret_store: SecretStore
    runner: Runner
    providers: dict[str, Provider] = field(default_factory=dict)
    image_providers: dict[str, ImageProvider] = field(default_factory=dict)


def _resolved_db_url() -> str:
    return os.environ.get("HOLLERBOX_DB_URL") or _default_db_url()


def _default_db_url() -> str:
    from hollerbox.store.db import default_db_url

    return default_db_url()


def _resolved_key_path() -> Path:
    env_key = os.environ.get("HOLLERBOX_KEY_PATH")
    if env_key:
        return Path(env_key).expanduser()
    return DEFAULT_KEY_FILE


def build_surface(
    *,
    db_url: str | None = None,
    key_path: Path | None = None,
) -> EngineSurface:
    """Construct an EngineSurface using the same env conventions as the CLI.

    Providers are auto-wired the same way `hollerbox.cli` does it so a
    workflow runs the same whether invoked from `hollerbox run` or
    `POST /workflows/{name}/run`.
    """
    engine = make_engine(db_url or _resolved_db_url())
    init_db(engine)
    sf = make_session_factory(engine)
    secret_store = SecretStore(sf, key_path=key_path or _resolved_key_path())

    providers = _auto_text_providers(secret_store)
    image_providers = _auto_image_providers(secret_store)
    runner = Runner(
        sf,
        secret_store=secret_store,
        providers=providers,
        image_providers=image_providers,
    )
    return EngineSurface(
        session_factory=sf,
        secret_store=secret_store,
        runner=runner,
        providers=providers,
        image_providers=image_providers,
    )


def _auto_text_providers(secret_store: SecretStore) -> dict[str, Provider]:
    from hollerbox.providers import (
        AnthropicProvider,
        MockProvider,
        OllamaProvider,
        OpenAIProvider,
    )

    out: dict[str, Provider] = {"mock": MockProvider(), "ollama": OllamaProvider()}
    if secret_store.has("ANTHROPIC_API_KEY"):
        with contextlib.suppress(ImportError):
            out["anthropic"] = AnthropicProvider(secret_store.get("ANTHROPIC_API_KEY") or "")
    if secret_store.has("OPENAI_API_KEY"):
        with contextlib.suppress(ImportError):
            out["openai"] = OpenAIProvider(secret_store.get("OPENAI_API_KEY") or "")
    return out


def _auto_image_providers(secret_store: SecretStore) -> dict[str, ImageProvider]:
    from hollerbox.providers import GeminiImageProvider, OpenAIImageProvider

    out: dict[str, ImageProvider] = {}
    if secret_store.has("OPENAI_API_KEY"):
        with contextlib.suppress(ImportError):
            out["openai"] = OpenAIImageProvider(secret_store.get("OPENAI_API_KEY") or "")
    if secret_store.has("GEMINI_API_KEY"):
        with contextlib.suppress(ImportError):
            out["gemini"] = GeminiImageProvider(secret_store.get("GEMINI_API_KEY") or "")
    return out


def get_surface(request: Request) -> EngineSurface:
    """FastAPI dependency: returns the lifespan-scoped EngineSurface.

    Tests override this with `app.dependency_overrides[get_surface] = ...`.
    """
    surface = getattr(request.app.state, "surface", None)
    if surface is None:  # pragma: no cover — guarded by lifespan
        raise RuntimeError("EngineSurface not initialized — app lifespan did not run")
    return surface
