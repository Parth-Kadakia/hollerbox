"""Tests for hollerbox.providers.anthropic.AnthropicProvider.

The real anthropic SDK is an optional extra. To keep these tests fast and
SDK-free, we pass a stub `client` to the constructor that mimics the
shape AnthropicProvider expects.
"""

from __future__ import annotations

import pytest

from hollerbox.providers.anthropic import DEFAULT_MODEL, AnthropicProvider


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeResponse:
    def __init__(self, parts: list[str]):
        self.content = [_FakeTextBlock(p) for p in parts]


class _FakeMessages:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self.messages = _FakeMessages(response)


def test_basic_completion_calls_client_with_expected_args():
    client = _FakeClient(_FakeResponse(["hello world"]))
    p = AnthropicProvider("test-key", client=client)
    result = p.complete(
        prompt="say hello",
        system="be brief",
        model="claude-opus-4-7",
        temperature=0.2,
        max_tokens=128,
    )
    assert result.text == "hello world"
    assert result.model == "claude-opus-4-7"

    kwargs = client.messages.last_kwargs
    assert kwargs["model"] == "claude-opus-4-7"
    assert kwargs["max_tokens"] == 128
    assert kwargs["temperature"] == 0.2
    assert kwargs["system"] == "be brief"
    # `content` is always a list of typed blocks now (so we can layer
    # image / document blocks alongside text for multimodal calls).
    assert kwargs["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "say hello"}]}
    ]


def test_image_attachment_encoded_as_base64_block():
    from hollerbox.providers.base import Attachment

    client = _FakeClient(_FakeResponse(["seen"]))
    p = AnthropicProvider("test-key", client=client)
    p.complete(
        prompt="what is this",
        attachments=[Attachment(data=b"\x89PNG fake", media_type="image/png", name="x.png")],
    )
    content = client.messages.last_kwargs["messages"][0]["content"]
    assert any(b.get("type") == "image" for b in content)
    img_block = next(b for b in content if b["type"] == "image")
    assert img_block["source"]["media_type"] == "image/png"
    assert img_block["source"]["type"] == "base64"
    assert "iVBORw" in img_block["source"]["data"] or img_block["source"]["data"]
    # Text block still present alongside.
    assert any(b.get("type") == "text" for b in content)


def test_pdf_attachment_encoded_as_document_block():
    from hollerbox.providers.base import Attachment

    client = _FakeClient(_FakeResponse(["read"]))
    p = AnthropicProvider("test-key", client=client)
    p.complete(
        prompt="summarize",
        attachments=[Attachment(data=b"%PDF-1.4", media_type="application/pdf", name="doc.pdf")],
    )
    content = client.messages.last_kwargs["messages"][0]["content"]
    pdf_block = next(b for b in content if b["type"] == "document")
    assert pdf_block["source"]["media_type"] == "application/pdf"


def test_default_model_used_when_not_overridden():
    client = _FakeClient(_FakeResponse(["x"]))
    p = AnthropicProvider("test-key", client=client)
    p.complete(prompt="hi")
    assert client.messages.last_kwargs["model"] == DEFAULT_MODEL


def test_no_system_key_when_unspecified():
    client = _FakeClient(_FakeResponse(["x"]))
    p = AnthropicProvider("test-key", client=client)
    p.complete(prompt="hi")
    assert "system" not in client.messages.last_kwargs


def test_temperature_omitted_when_unspecified():
    """Regression: claude-opus-4-7 rejects `temperature`. Don't send it
    unless the caller explicitly set one."""
    client = _FakeClient(_FakeResponse(["x"]))
    p = AnthropicProvider("test-key", client=client)
    p.complete(prompt="hi")
    assert "temperature" not in client.messages.last_kwargs


def test_temperature_included_when_explicitly_set():
    client = _FakeClient(_FakeResponse(["x"]))
    p = AnthropicProvider("test-key", client=client)
    p.complete(prompt="hi", temperature=0.0)
    assert client.messages.last_kwargs["temperature"] == 0.0


def test_multi_block_response_concatenated():
    client = _FakeClient(_FakeResponse(["one ", "two ", "three"]))
    p = AnthropicProvider("test-key", client=client)
    result = p.complete(prompt="x")
    assert result.text == "one two three"


def test_empty_api_key_rejected():
    with pytest.raises(ValueError, match="non-empty api_key"):
        AnthropicProvider("", client=_FakeClient(_FakeResponse(["x"])))


def test_real_sdk_path_raises_clear_error_if_missing(monkeypatch):
    """When the `anthropic` SDK isn't installed and no client is provided,
    instantiation must raise an ImportError pointing the user at the
    right `uv sync --extra llm` command."""
    import sys

    # Pretend the anthropic module is not installed for this test.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ImportError, match="anthropic"):
        AnthropicProvider("test-key")


def test_provider_name():
    p = AnthropicProvider("test-key", client=_FakeClient(_FakeResponse(["x"])))
    assert p.name == "anthropic"
