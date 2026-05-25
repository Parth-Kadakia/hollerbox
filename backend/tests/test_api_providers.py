"""Provider inventory endpoint."""

from __future__ import annotations


def test_lists_text_and_image_providers(api_client) -> None:
    resp = api_client.get("/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert "text" in body and "image" in body

    text_names = {p["name"] for p in body["text"]}
    assert {"mock", "ollama", "anthropic", "openai"}.issubset(text_names)


def test_mock_is_always_ready(api_client) -> None:
    text = api_client.get("/providers").json()["text"]
    mock = next(p for p in text if p["name"] == "mock")
    assert mock["status"] == "ready"


def test_no_key_status_for_unsecreted_providers(api_client) -> None:
    text = api_client.get("/providers").json()["text"]
    anthropic = next(p for p in text if p["name"] == "anthropic")
    assert anthropic["status"] == "no-key"


def test_secret_set_for_text_provider(api_client) -> None:
    # The api_surface fixture registers only the mock provider, so even with
    # a key set the status will be "missing-sdk" (because anthropic isn't
    # in surface.providers) — that's the correct UX for a stored key whose
    # SDK isn't installed *or* whose provider just hasn't been auto-wired.
    api_client.put("/secrets/ANTHROPIC_API_KEY", json={"value": "sk-test"})
    text = api_client.get("/providers").json()["text"]
    anthropic = next(p for p in text if p["name"] == "anthropic")
    assert anthropic["status"] == "missing-sdk"
