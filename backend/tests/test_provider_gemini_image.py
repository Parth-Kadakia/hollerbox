"""Tests for GeminiImageProvider — fake client, no real SDK calls."""

from __future__ import annotations

import base64

import pytest

from hollerbox.providers.gemini_image import DEFAULT_MODEL, GeminiImageProvider


class _FakeInlineData:
    def __init__(self, data):
        self.data = data


class _FakePart:
    def __init__(self, *, text: str | None = None, data=None):
        self.text = text
        self.inline_data = _FakeInlineData(data) if data is not None else None


class _FakeResponseTopLevel:
    """Mimics the SDK shape that exposes `.parts` directly."""

    def __init__(self, parts: list[_FakePart]):
        self.parts = parts


class _FakeContent:
    def __init__(self, parts: list[_FakePart]):
        self.parts = parts


class _FakeCandidate:
    def __init__(self, parts: list[_FakePart]):
        self.content = _FakeContent(parts)


class _FakeResponseCandidates:
    """Mimics the SDK shape that exposes `.candidates[*].content.parts`."""

    def __init__(self, parts: list[_FakePart]):
        self.candidates = [_FakeCandidate(parts)]


class _FakeModels:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


class _FakeClient:
    def __init__(self, responses):
        self.models = _FakeModels(responses)


def test_single_image_from_top_level_parts():
    payload = b"PNG-bytes-from-gemini"
    response = _FakeResponseTopLevel([_FakePart(data=payload)])
    client = _FakeClient([response])
    p = GeminiImageProvider("k", client=client)
    result = p.generate(prompt="banana dish")
    assert result.images == [payload]
    assert result.model == DEFAULT_MODEL
    assert client.models.calls[0]["model"] == DEFAULT_MODEL
    assert client.models.calls[0]["contents"] == ["banana dish"]


def test_single_image_from_candidates_shape():
    """Older SDK shape: `response.candidates[0].content.parts`."""
    payload = b"older-shape-bytes"
    response = _FakeResponseCandidates([_FakePart(data=payload)])
    client = _FakeClient([response])
    p = GeminiImageProvider("k", client=client)
    result = p.generate(prompt="x")
    assert result.images == [payload]


def test_text_parts_ignored():
    payload = b"the-image"
    response = _FakeResponseTopLevel(
        [
            _FakePart(text="here is your image:"),
            _FakePart(data=payload),
            _FakePart(text="hope you like it"),
        ]
    )
    client = _FakeClient([response])
    p = GeminiImageProvider("k", client=client)
    result = p.generate(prompt="x")
    assert result.images == [payload]


def test_base64_string_data_decoded():
    payload = b"\x89PNG-real-bytes"
    response = _FakeResponseTopLevel(
        [_FakePart(data=base64.b64encode(payload).decode("ascii"))]
    )
    client = _FakeClient([response])
    p = GeminiImageProvider("k", client=client)
    result = p.generate(prompt="x")
    assert result.images == [payload]


def test_n_greater_than_1_loops():
    payloads = [b"img-0", b"img-1"]
    responses = [_FakeResponseTopLevel([_FakePart(data=p)]) for p in payloads]
    client = _FakeClient(responses)
    p = GeminiImageProvider("k", client=client)
    result = p.generate(prompt="x", n=2)
    assert result.images == payloads
    assert len(client.models.calls) == 2


def test_model_override():
    response = _FakeResponseTopLevel([_FakePart(data=b"x")])
    client = _FakeClient([response])
    p = GeminiImageProvider("k", client=client)
    p.generate(prompt="x", model="gemini-some-other-image-model")
    assert client.models.calls[0]["model"] == "gemini-some-other-image-model"


def test_empty_api_key_rejected():
    with pytest.raises(ValueError, match="non-empty api_key"):
        GeminiImageProvider("", client=_FakeClient([_FakeResponseTopLevel([])]))


def test_provider_name():
    response = _FakeResponseTopLevel([_FakePart(data=b"x")])
    assert GeminiImageProvider("k", client=_FakeClient([response])).name == "gemini"
