"""Tests for hollerbox.providers.openai.OpenAIProvider.

Same shape as the anthropic tests: pass a fake `client` to avoid the
real openai SDK.
"""

from __future__ import annotations

import pytest

from hollerbox.providers.openai import DEFAULT_MODEL, OpenAIProvider


class _FakeMessage:
    def __init__(self, content: str | None):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str | None):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeChat:
    def __init__(self, response: _FakeResponse):
        self.completions = _FakeCompletions(response)


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self.chat = _FakeChat(response)


def test_basic_completion():
    client = _FakeClient(_FakeResponse("answered"))
    p = OpenAIProvider("test-key", client=client)
    result = p.complete(prompt="ask", system="be terse", temperature=0.7, max_tokens=42)
    assert result.text == "answered"
    assert result.model == DEFAULT_MODEL

    kwargs = client.chat.completions.last_kwargs
    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 42
    assert kwargs["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "ask"},
    ]


def test_no_system_message_when_unspecified():
    client = _FakeClient(_FakeResponse("ok"))
    OpenAIProvider("k", client=client).complete(prompt="hi")
    msgs = client.chat.completions.last_kwargs["messages"]
    assert msgs == [{"role": "user", "content": "hi"}]


def test_temperature_omitted_when_unspecified():
    client = _FakeClient(_FakeResponse("ok"))
    OpenAIProvider("k", client=client).complete(prompt="hi")
    assert "temperature" not in client.chat.completions.last_kwargs


def test_model_override():
    client = _FakeClient(_FakeResponse("ok"))
    p = OpenAIProvider("k", client=client, default_model="default-m")
    p.complete(prompt="x", model="override-m")
    assert client.chat.completions.last_kwargs["model"] == "override-m"


def test_null_content_becomes_empty_string():
    client = _FakeClient(_FakeResponse(None))
    p = OpenAIProvider("k", client=client)
    assert p.complete(prompt="x").text == ""


def test_empty_api_key_rejected():
    with pytest.raises(ValueError, match="non-empty api_key"):
        OpenAIProvider("", client=_FakeClient(_FakeResponse("x")))


def test_real_sdk_path_raises_clear_error_if_missing(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ImportError, match="openai"):
        OpenAIProvider("test-key")


def test_provider_name():
    p = OpenAIProvider("k", client=_FakeClient(_FakeResponse("x")))
    assert p.name == "openai"
