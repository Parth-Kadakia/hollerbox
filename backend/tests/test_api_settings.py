"""Settings endpoints — JSON kv store used for `${settings.*}` references."""

from __future__ import annotations


def test_empty(api_client) -> None:
    assert api_client.get("/settings").json() == {}


def test_put_then_get(api_client) -> None:
    resp = api_client.put("/settings/default_provider", json={"value": "anthropic"})
    assert resp.status_code == 200
    assert resp.json() == {"value": "anthropic"}

    listing = api_client.get("/settings").json()
    assert listing == {"default_provider": "anthropic"}


def test_supports_arbitrary_json_values(api_client) -> None:
    api_client.put("/settings/limits", json={"value": {"max_steps": 50, "warn_above": 20}})
    listing = api_client.get("/settings").json()
    assert listing["limits"] == {"max_steps": 50, "warn_above": 20}


def test_overwrite(api_client) -> None:
    api_client.put("/settings/k", json={"value": "a"})
    api_client.put("/settings/k", json={"value": "b"})
    assert api_client.get("/settings").json()["k"] == "b"
