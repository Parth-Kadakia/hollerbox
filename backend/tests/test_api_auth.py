"""Bearer-token middleware tests.

The conftest's `api_client` fixture doesn't enable auth (no HOLLERBOX_API_KEY).
For these tests we build the app fresh with the env var set so the
middleware is wired in. The dependency override pattern stays the same.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture()
def authed_client(api_surface, monkeypatch) -> Iterator:
    monkeypatch.setenv("HOLLERBOX_API_KEY", "supersecret")
    monkeypatch.setenv("HOLLERBOX_WORKER_ENABLED", "0")
    from fastapi.testclient import TestClient

    from api.main import create_app

    app = create_app()
    app.state.surface = api_surface
    with TestClient(app) as client:
        yield client


def test_unauthenticated_request_returns_401(authed_client) -> None:
    resp = authed_client.get("/workflows")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == 'Bearer realm="hollerbox"'


def test_bearer_token_unlocks_api(authed_client) -> None:
    resp = authed_client.get("/workflows", headers={"Authorization": "Bearer supersecret"})
    assert resp.status_code == 200


def test_query_param_token_works_for_sse_style_endpoints(authed_client) -> None:
    resp = authed_client.get("/workflows", params={"_token": "supersecret"})
    assert resp.status_code == 200


def test_wrong_token_rejected(authed_client) -> None:
    resp = authed_client.get(
        "/workflows", headers={"Authorization": "Bearer notrightatall"}
    )
    assert resp.status_code == 401


def test_index_route_is_public(authed_client) -> None:
    """The SPA HTML must load so the user can be prompted for the token."""
    resp = authed_client.get("/")
    # No `/` route is mounted in this test (we'd need static files); 404 is
    # acceptable here — the important thing is it's NOT 401.
    assert resp.status_code != 401


def test_auth_disabled_when_env_var_unset(api_client) -> None:
    """The default fixture has no token set — every endpoint is open."""
    assert "HOLLERBOX_API_KEY" not in os.environ
    assert api_client.get("/workflows").status_code == 200
