"""Tests for OpenAIImageProvider — fake client, no real SDK calls."""

from __future__ import annotations

import base64

import pytest

from hollerbox.providers.openai_image import DEFAULT_MODEL, OpenAIImageProvider


class _FakeImage:
    def __init__(self, b64: str | None, revised_prompt: str | None = None):
        self.b64_json = b64
        self.revised_prompt = revised_prompt


class _FakeImagesResponse:
    def __init__(self, b64s: list[str | None]):
        self.data = [_FakeImage(b) for b in b64s]


class _FakeImages:
    def __init__(self, responses: list[_FakeImagesResponse]):
        self._responses = responses
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


class _FakeClient:
    def __init__(self, responses: list[_FakeImagesResponse]):
        self.images = _FakeImages(responses)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_single_image_decoded_from_b64():
    payload = b"\x89PNG-fake-bytes"
    client = _FakeClient([_FakeImagesResponse([_b64(payload)])])
    p = OpenAIImageProvider("test-key", client=client)
    result = p.generate(prompt="otter")
    assert result.images == [payload]
    assert result.model == DEFAULT_MODEL
    assert client.images.calls[0]["model"] == DEFAULT_MODEL
    assert client.images.calls[0]["prompt"] == "otter"
    assert client.images.calls[0]["n"] == 1
    assert client.images.calls[0]["size"] == "1024x1024"


def test_n_greater_than_1_makes_n_api_calls():
    """gpt-image-1 caps n=1 per request; provider loops client-side."""
    payloads = [b"image-0", b"image-1", b"image-2"]
    responses = [_FakeImagesResponse([_b64(p)]) for p in payloads]
    client = _FakeClient(responses)
    p = OpenAIImageProvider("test-key", client=client)
    result = p.generate(prompt="x", n=3)
    assert result.images == payloads
    assert len(client.images.calls) == 3
    assert all(c["n"] == 1 for c in client.images.calls)


def test_model_override():
    client = _FakeClient([_FakeImagesResponse([_b64(b"x")])])
    p = OpenAIImageProvider("k", client=client)
    p.generate(prompt="x", model="gpt-image-2")
    assert client.images.calls[0]["model"] == "gpt-image-2"


def test_revised_prompt_captured_in_raw():
    client = _FakeClient([
        _FakeImagesResponse([_b64(b"x")]),
    ])
    client.images._responses[0].data[0].revised_prompt = "a better prompt"
    p = OpenAIImageProvider("k", client=client)
    result = p.generate(prompt="x")
    assert result.raw == {"revised_prompt": "a better prompt"}


def test_missing_b64_skipped_silently():
    """If a model returns URL-only (no b64), we skip it — caller's check
    for empty `images` will surface the problem."""
    client = _FakeClient([_FakeImagesResponse([None])])
    p = OpenAIImageProvider("k", client=client)
    result = p.generate(prompt="x")
    assert result.images == []


def test_empty_api_key_rejected():
    with pytest.raises(ValueError, match="non-empty api_key"):
        OpenAIImageProvider("", client=_FakeClient([_FakeImagesResponse([_b64(b"x")])]))


def test_provider_name():
    assert OpenAIImageProvider("k", client=_FakeClient([_FakeImagesResponse([_b64(b"x")])])).name == "openai"
