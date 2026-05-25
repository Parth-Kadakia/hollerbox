"""Liveness check + FastAPI scaffold smoke test."""

from __future__ import annotations

from hollerbox import __version__


def test_health(api_client) -> None:
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}


def test_openapi_loads(api_client) -> None:
    resp = api_client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = set(spec["paths"].keys())
    # Spot-check a handful of routes from each module.
    assert "/health" in paths
    assert "/workflows" in paths
    assert "/runs" in paths
    assert "/secrets" in paths
    assert "/settings" in paths
