"""Shared pytest fixtures for API tests.

Each test gets an isolated in-memory SQLite + a throwaway Fernet key, so
nothing touches the user's real `~/.hollerbox/`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Side-effect import: registers built-in step types with the registry.
import hollerbox.steps  # noqa: F401
from hollerbox.core.runner import Runner
from hollerbox.providers import MockProvider
from hollerbox.secrets import SecretStore
from hollerbox.store import init_db, make_engine, make_session_factory


@pytest.fixture()
def tmp_key_path(tmp_path: Path) -> Path:
    return tmp_path / "fernet.key"


@pytest.fixture()
def api_surface(tmp_path: Path, tmp_key_path: Path):
    """Construct an EngineSurface backed by an isolated SQLite + key."""
    from api.deps import EngineSurface

    db_url = f"sqlite:///{tmp_path / 'hollerbox.sqlite'}"
    engine = make_engine(db_url)
    init_db(engine)
    sf = make_session_factory(engine)

    secret_store = SecretStore(sf, key_path=tmp_key_path)
    providers = {"mock": MockProvider()}
    runner = Runner(sf, secret_store=secret_store, providers=providers)
    return EngineSurface(
        session_factory=sf,
        secret_store=secret_store,
        runner=runner,
        providers=providers,
        image_providers={},
    )


@pytest.fixture()
def api_client(api_surface) -> Iterator:
    """FastAPI TestClient with the worker disabled + test surface pre-mounted.

    The worker is disabled via env flag because tests want to drive runs
    explicitly. We set `app.state.surface` before TestClient runs the
    lifespan, so the lifespan won't build a real surface against the
    user's `~/.hollerbox/`.
    """
    os.environ["HOLLERBOX_WORKER_ENABLED"] = "0"
    # Most tests assume an empty workflows table. Tests that want to
    # exercise the boot-time template import opt in by clearing this
    # env var themselves (see tests/test_api_bootstrap.py).
    os.environ["HOLLERBOX_AUTO_IMPORT_TEMPLATES"] = "0"
    from fastapi.testclient import TestClient

    from api.main import create_app

    app = create_app()
    app.state.surface = api_surface
    try:
        with TestClient(app) as client:
            yield client
    finally:
        os.environ.pop("HOLLERBOX_WORKER_ENABLED", None)
        os.environ.pop("HOLLERBOX_AUTO_IMPORT_TEMPLATES", None)
