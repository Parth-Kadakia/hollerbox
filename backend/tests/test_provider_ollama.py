"""Tests for hollerbox.providers.ollama.OllamaProvider via httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from hollerbox.providers.ollama import DEFAULT_MODEL, OllamaProvider


@pytest.fixture(autouse=True)
def restore_transport():
    original = OllamaProvider._TRANSPORT
    yield
    OllamaProvider._TRANSPORT = original


def _set_transport(handler, *, installed: list[str] | None = None):
    """Mount a MockTransport that routes `/api/generate` to `handler` and
    answers `/api/tags` with the (optional) installed-models list."""
    tags_payload = {
        "models": [{"name": n} for n in (installed if installed is not None else [DEFAULT_MODEL])]
    }

    def dispatch(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags_payload)
        return handler(request)

    OllamaProvider._TRANSPORT = httpx.MockTransport(dispatch)


def test_basic_generate_success():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/generate"
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ollama said hi", "done": True})

    _set_transport(handler)
    p = OllamaProvider()
    result = p.complete(prompt="hi there", temperature=0.5, max_tokens=64)

    assert result.text == "ollama said hi"
    assert result.model == DEFAULT_MODEL
    assert captured["body"]["model"] == DEFAULT_MODEL
    assert captured["body"]["prompt"] == "hi there"
    assert captured["body"]["stream"] is False
    assert captured["body"]["options"] == {"temperature": 0.5, "num_predict": 64}


def test_system_field_passed_when_provided():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    _set_transport(handler)
    OllamaProvider().complete(prompt="x", system="you are concise")
    assert captured["body"]["system"] == "you are concise"


def test_model_override_per_call():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    _set_transport(handler)
    OllamaProvider(default_model="default-m").complete(prompt="x", model="override-m")
    assert captured["body"]["model"] == "override-m"


def test_http_error_propagates_as_exception():
    def handler(request):
        return httpx.Response(500, text="boom")

    _set_transport(handler)
    p = OllamaProvider()
    with pytest.raises(httpx.HTTPStatusError):
        p.complete(prompt="x")


def test_host_trailing_slash_normalized():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"response": "ok"})

    _set_transport(handler)
    p = OllamaProvider(host="http://localhost:11434/")
    p.complete(prompt="x")
    # Must not become `//api/generate` with the trailing slash
    assert captured["url"].endswith("/api/generate")
    assert "//api" not in captured["url"]


def test_raw_completion_payload_passed_through():
    payload = {"response": "ok", "done": True, "context": [1, 2, 3], "eval_count": 42}

    def handler(request):
        return httpx.Response(200, json=payload)

    _set_transport(handler)
    p = OllamaProvider()
    result = p.complete(prompt="x")
    assert result.raw == payload


def test_temperature_omitted_when_unspecified():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    _set_transport(handler)
    OllamaProvider().complete(prompt="x")
    assert "temperature" not in captured["body"]["options"]
    # max_tokens still expressed as num_predict
    assert captured["body"]["options"]["num_predict"] == 1024


def test_provider_name():
    assert OllamaProvider().name == "ollama"


def test_default_model_falls_back_to_first_installed_when_default_missing():
    """User has qwen + granite installed but not llama3.1 → use the first one."""
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    _set_transport(handler, installed=["qwen3.5:0.8b", "granite4.1:3b"])
    OllamaProvider().complete(prompt="hi")
    # Sort is alphabetic — granite4.1:3b wins
    assert captured["body"]["model"] == "granite4.1:3b"


def test_default_model_matches_by_base_name_when_tag_differs():
    """`llama3.1` (default) matches `llama3.1:latest` installed."""
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    _set_transport(handler, installed=["llama3.1:latest", "qwen3.5:0.8b"])
    OllamaProvider().complete(prompt="hi")
    assert captured["body"]["model"] == "llama3.1:latest"


def test_default_falls_back_to_configured_when_tags_unreachable():
    """If /api/tags errors out, we still send a request with the configured default."""
    captured = {}

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(500, text="boom")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    OllamaProvider._TRANSPORT = httpx.MockTransport(handler)
    OllamaProvider().complete(prompt="hi")
    assert captured["body"]["model"] == DEFAULT_MODEL


def test_list_models_returns_installed_names():
    OllamaProvider._TRANSPORT = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"models": [{"name": "qwen3.5:0.8b"}, {"name": "granite4.1:3b"}]}
        )
    )
    assert OllamaProvider().list_models() == ["granite4.1:3b", "qwen3.5:0.8b"]


def test_list_models_caches_result():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json={"models": [{"name": "x:1"}]})

    OllamaProvider._TRANSPORT = httpx.MockTransport(handler)
    p = OllamaProvider()
    p.list_models()
    p.list_models()
    p.list_models()
    # Only one /api/tags call.
    assert calls.count("/api/tags") == 1


def test_clear_model_cache_forces_refetch():
    seen = {"count": 0}

    def handler(req):
        seen["count"] += 1
        return httpx.Response(200, json={"models": [{"name": "x:1"}]})

    OllamaProvider._TRANSPORT = httpx.MockTransport(handler)
    p = OllamaProvider()
    p.list_models()
    p.clear_model_cache()
    p.list_models()
    assert seen["count"] == 2
