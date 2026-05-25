"""Router tests — JSON parsing + the LLM-driven decide() flow with the mock provider."""

from __future__ import annotations

import json

import pytest

from hollerbox.conversation.router import (
    Router,
    RouterError,
    build_user_prompt,
    parse_decision,
)
from hollerbox.core.workflow import StepDefinition, Workflow
from hollerbox.providers import MockProvider


def _wf(name: str, inputs: dict | None = None, examples: list[str] | None = None) -> Workflow:
    return Workflow(
        name=name,
        description=f"runs {name}",
        chat_examples=examples or [],
        inputs=inputs or {},
        steps=[StepDefinition(id="x", type="shell", config={"command": "echo hi"})],
    )


# --------------------------- parse_decision ---------------------------

def test_parse_run_workflow() -> None:
    raw = json.dumps({"action": "run_workflow", "workflow": "demo", "inputs": {"who": "you"}})
    d = parse_decision(raw, workflows=[_wf("demo")])
    assert d.action == "run_workflow"
    assert d.workflow_name == "demo"
    assert d.inputs == {"who": "you"}


def test_parse_clarifying() -> None:
    raw = json.dumps({"action": "ask_clarifying", "text": "which workflow?"})
    d = parse_decision(raw)
    assert d.action == "ask_clarifying"
    assert d.text == "which workflow?"


def test_parse_strips_code_fence() -> None:
    raw = '```json\n{"action":"chitchat","text":"hello"}\n```'
    d = parse_decision(raw)
    assert d.action == "chitchat"
    assert d.text == "hello"


def test_parse_rejects_fabricated_workflow() -> None:
    raw = json.dumps({"action": "run_workflow", "workflow": "ghost", "inputs": {}})
    with pytest.raises(RouterError, match="unknown workflow"):
        parse_decision(raw, workflows=[_wf("demo")])


def test_parse_rejects_bad_json() -> None:
    with pytest.raises(RouterError, match="valid JSON"):
        parse_decision("not json at all")


def test_parse_rejects_unknown_action() -> None:
    with pytest.raises(RouterError, match="unknown router action"):
        parse_decision(json.dumps({"action": "summon_demon", "text": "x"}))


def test_parse_run_workflow_requires_inputs_object() -> None:
    raw = json.dumps({"action": "run_workflow", "workflow": "demo", "inputs": "not-a-dict"})
    with pytest.raises(RouterError, match="'inputs' must be an object"):
        parse_decision(raw, workflows=[_wf("demo")])


# --------------------------- Router.decide (via MockProvider) ---------------------------

def test_decide_returns_run_workflow_from_mock() -> None:
    payload = json.dumps({"action": "run_workflow", "workflow": "demo", "inputs": {"who": "you"}})
    router = Router(MockProvider(default_text=payload))
    d = router.decide(message="run demo", workflows=[_wf("demo")])
    assert d.action == "run_workflow"
    assert d.workflow_name == "demo"
    assert d.inputs == {"who": "you"}


def test_decide_chitchat() -> None:
    payload = json.dumps({"action": "chitchat", "text": "hi there"})
    router = Router(MockProvider(default_text=payload))
    d = router.decide(message="hi", workflows=[])
    assert d.action == "chitchat"
    assert d.text == "hi there"


def test_decide_passes_message_into_prompt() -> None:
    provider = MockProvider(
        default_text=json.dumps({"action": "chitchat", "text": "ok"}),
    )
    router = Router(provider)
    router.decide(
        message="please summarize my email",
        workflows=[_wf("email_digest")],
        history=[("user", "earlier message"), ("assistant", "earlier reply")],
    )
    assert len(provider.calls) == 1
    prompt = provider.calls[0]["prompt"]
    assert "please summarize my email" in prompt
    assert "email_digest" in prompt
    assert "earlier message" in prompt


def test_build_user_prompt_includes_examples() -> None:
    prompt = build_user_prompt(
        message="get news on AI",
        workflows=[_wf("news", inputs={"topic": "AI"}, examples=["news on {topic}"])],
        history=[],
    )
    assert "news on {topic}" in prompt
    assert "topic" in prompt
