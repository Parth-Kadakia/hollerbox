"""Tests for hollerbox.providers.mock.MockProvider."""

from __future__ import annotations

from hollerbox.providers import MockProvider


def test_default_text_returned():
    p = MockProvider(default_text="hello")
    result = p.complete(prompt="anything")
    assert result.text == "hello"
    assert result.model == "mock-1"


def test_responder_callable_invoked():
    p = MockProvider(responder=lambda prompt, system: f"echo:{prompt}")
    result = p.complete(prompt="hi", system="you are a parrot")
    assert result.text == "echo:hi"


def test_calls_recorded_for_inspection():
    p = MockProvider()
    p.complete(prompt="one", temperature=0.5)
    p.complete(prompt="two", system="sys", model="custom-model")
    assert len(p.calls) == 2
    assert p.calls[0]["prompt"] == "one"
    assert p.calls[0]["temperature"] == 0.5
    assert p.calls[1]["system"] == "sys"
    assert p.calls[1]["model"] == "custom-model"


def test_call_model_overrides_provider_default():
    p = MockProvider(model="default-1")
    result = p.complete(prompt="x", model="override-1")
    assert result.model == "override-1"


def test_name_attribute():
    assert MockProvider().name == "mock"
