"""Write-only secrets endpoints — values NEVER leave the server."""

from __future__ import annotations


def test_empty_list(api_client) -> None:
    assert api_client.get("/secrets").json() == []


def test_put_then_list_shows_presence_only(api_client) -> None:
    resp = api_client.put("/secrets/OPENAI_API_KEY", json={"value": "sk-real-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"name": "OPENAI_API_KEY", "set": True}

    listing = api_client.get("/secrets").json()
    assert listing == [{"name": "OPENAI_API_KEY", "set": True}]


def test_put_overwrites(api_client, api_surface) -> None:
    api_client.put("/secrets/K", json={"value": "v1"})
    api_client.put("/secrets/K", json={"value": "v2"})
    # The store decrypts to the latest value — the API never exposes it, but
    # we can verify via the surface that rotation worked.
    assert api_surface.secret_store.get("K") == "v2"


def test_delete(api_client) -> None:
    api_client.put("/secrets/K", json={"value": "v"})
    resp = api_client.delete("/secrets/K")
    assert resp.status_code == 204
    assert api_client.get("/secrets").json() == []


def test_delete_404(api_client) -> None:
    assert api_client.delete("/secrets/missing").status_code == 404


def test_value_never_appears_in_any_response(api_client) -> None:
    """Belt-and-suspenders: no endpoint should ever echo a value."""
    api_client.put("/secrets/SECRET_KEY", json={"value": "super-secret"})
    bodies = [
        api_client.get("/secrets").text,
        api_client.put("/secrets/SECRET_KEY", json={"value": "super-secret"}).text,
    ]
    for body in bodies:
        assert "super-secret" not in body
