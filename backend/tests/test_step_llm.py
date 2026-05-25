"""Tests for hollerbox.steps.llm.LlmStep — driven through the Runner.

These exercise the full pipe: a workflow with an llm step references a
provider via name; the Runner has that provider in its `providers` dict;
the step picks it up via ctx.providers, calls .complete(), and records
the output. MockProvider is used so the suite never makes a real LLM call.
"""

from __future__ import annotations

import pytest

from hollerbox.core.context import RunContext
from hollerbox.core.runner import Runner
from hollerbox.core.workflow import StepDefinition, Workflow
from hollerbox.providers import MockProvider
from hollerbox.steps.llm import LlmStep
from hollerbox.store import (
    init_db,
    make_engine,
    make_session_factory,
    repo,
    session_scope,
)


@pytest.fixture()
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)


# --------------------------- step-level unit tests ---------------------------

def test_llm_step_calls_provider_and_returns_completion():
    provider = MockProvider(default_text="hi from mock")
    defn = StepDefinition(
        id="ask",
        type="llm",
        config={"provider": "mock", "prompt": "say hi"},
    )
    step = LlmStep(defn)
    ctx = RunContext.new(providers={"mock": provider})
    result = step.run(ctx)
    assert result.status == "success"
    assert result.output["text"] == "hi from mock"
    assert result.output["provider"] == "mock"
    assert result.output["model"] == "mock-1"


def test_llm_step_falls_back_to_settings_default_provider():
    provider = MockProvider(default_text="from default")
    defn = StepDefinition(
        id="ask",
        type="llm",
        # No explicit provider — should read settings.default_provider
        config={"prompt": "hi"},
    )
    step = LlmStep(defn)
    ctx = RunContext.new(
        settings={"default_provider": "mock"},
        providers={"mock": provider},
    )
    result = step.run(ctx)
    assert result.status == "success"
    assert result.output["text"] == "from default"


def test_llm_step_template_resolution_in_prompt():
    provider = MockProvider(responder=lambda p, s: f"echo:{p}")
    defn = StepDefinition(
        id="ask",
        type="llm",
        config={"provider": "mock", "prompt": "topic=${inputs.topic}"},
    )
    step = LlmStep(defn)
    ctx = RunContext.new(inputs={"topic": "AI"}, providers={"mock": provider})
    result = step.run(ctx)
    assert result.status == "success"
    assert result.output["text"] == "echo:topic=AI"


def test_llm_step_unknown_provider_fails_cleanly():
    defn = StepDefinition(
        id="ask",
        type="llm",
        config={"provider": "nope", "prompt": "hi"},
    )
    step = LlmStep(defn)
    ctx = RunContext.new(providers={"mock": MockProvider()})
    result = step.run(ctx)
    assert result.status == "failed"
    assert "nope" in (result.error or "")


def test_llm_step_provider_exception_becomes_step_failure():
    class BoomProvider(MockProvider):
        def complete(self, **kwargs):
            raise RuntimeError("upstream 500")

    defn = StepDefinition(
        id="ask",
        type="llm",
        config={"provider": "mock", "prompt": "hi"},
    )
    step = LlmStep(defn)
    ctx = RunContext.new(providers={"mock": BoomProvider()})
    result = step.run(ctx)
    assert result.status == "failed"
    assert "upstream 500" in (result.error or "")


# --------------------------- Runner-driven tests ---------------------------

def test_runner_threads_providers_into_ctx(session_factory):
    """Workflow with an llm step runs end-to-end through Runner+Store."""
    provider = MockProvider(default_text="answered")
    runner = Runner(session_factory, providers={"mock": provider})
    wf = Workflow(
        name="ask",
        steps=[
            StepDefinition(
                id="ask",
                type="llm",
                config={"provider": "mock", "prompt": "what?"},
            )
        ],
    )
    result = runner.execute(wf)
    assert result.status == "success"
    with session_scope(session_factory) as s:
        rows = list(repo.list_step_runs(s, result.run_id))
        assert rows[0].output["text"] == "answered"
        assert rows[0].output["provider"] == "mock"


def test_llm_step_with_secret_does_not_leak_into_persistence(session_factory):
    """If the prompt itself contains a ${secrets.X} value, the persisted
    resolved_input must redact it (BUILD_BRIEF §10)."""
    captured = {}

    def capture_responder(prompt, system):
        # Verify the *executing* prompt got the real secret value.
        captured["prompt"] = prompt
        captured["system"] = system
        return "(seen)"

    provider = MockProvider(responder=capture_responder)
    runner = Runner(session_factory, providers={"mock": provider})

    wf = Workflow(
        name="leaky",
        steps=[
            StepDefinition(
                id="ask",
                type="llm",
                config={
                    "provider": "mock",
                    "prompt": "Bearer ${secrets.API_KEY} please",
                    "system": "you are ${secrets.PERSONA}",
                },
            )
        ],
    )
    result = runner.execute(
        wf,
        secrets={"API_KEY": "sk-real-key-12345", "PERSONA": "a-real-persona-name"},
    )
    assert result.status == "success"

    # The provider call saw the REAL values (so the call works).
    assert "sk-real-key-12345" in captured["prompt"]
    assert captured["system"] == "you are a-real-persona-name"

    # The persisted step_runs row must NOT contain the real values.
    with session_scope(session_factory) as s:
        rows = list(repo.list_step_runs(s, result.run_id))
        serialized = str(rows[0].resolved_input)
    assert "sk-real-key-12345" not in serialized
    assert "a-real-persona-name" not in serialized
    assert "••••" in serialized


def test_describe_effect_summarizes(session_factory):
    defn = StepDefinition(
        id="ask",
        type="llm",
        config={"provider": "anthropic", "model": "claude-opus-4-7", "prompt": "x"},
    )
    step = LlmStep(defn)
    ctx = RunContext.new(providers={})
    desc = step.describe_effect(ctx)
    assert "anthropic" in desc
    assert "claude-opus-4-7" in desc
