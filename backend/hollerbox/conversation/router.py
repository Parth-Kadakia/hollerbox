"""Message → workflow router.

Given a user message, the catalog of known workflows, and recent
conversation turns, the router asks an LLM to return one of four actions
in a strict JSON envelope:

- `run_workflow(name, inputs)` — pick a workflow + extract inputs
- `ask_clarifying(text)`         — not confident; ask the user a question
- `chitchat(text)`               — small talk or out-of-scope
- `agent_task(text)`             — request no workflow covers (Phase 7
  will dispatch to the agent; Phase 5 surfaces a placeholder reply)

The prompt is deliberately small and testable. The mock provider can
be scripted to return any JSON envelope so tests don't need network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from hollerbox.core.workflow import Workflow
from hollerbox.providers.base import Provider

RouterAction = Literal["run_workflow", "ask_clarifying", "chitchat", "agent_task"]


@dataclass
class RouterDecision:
    """The router's single typed return value."""

    action: RouterAction
    workflow_name: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    raw_response: str = ""  # the LLM's raw text, kept for trace + debugging


class RouterError(Exception):
    """Raised when the LLM response can't be parsed into a RouterDecision."""


SYSTEM_PROMPT = """\
You are HollerBox's conversational router. Your job is to map a user's
message to one of four actions, returning JSON only — no prose, no
markdown fences, no explanation.

Available actions:

1. {"action":"run_workflow","workflow":"<name>","inputs":{...}}
   Use when the user clearly wants to run one of the listed workflows.
   Fill `inputs` with values extracted from the message (only the inputs
   the workflow defines; leave the rest blank to use defaults).

2. {"action":"ask_clarifying","text":"<question>"}
   Use when a workflow seems likely but the user hasn't given enough
   information to commit. Ask a single, short follow-up.

3. {"action":"chitchat","text":"<reply>"}
   Use for greetings, thanks, and any out-of-scope chat. Keep the reply
   short and friendly.

4. {"action":"agent_task","text":"<goal restated>"}
   Use only when the user is asking for something no listed workflow
   covers, and an open-ended agent would be needed. (The agent isn't
   implemented yet — your reply restates the goal.)

Rules:
- Output a single JSON object. Nothing else.
- If unsure between "run_workflow" and "ask_clarifying", choose
  "ask_clarifying" — safe-by-default beats guessing.
- Workflow names must come from the catalog exactly.
- Never invent inputs the workflow doesn't declare.
"""


def _format_catalog(workflows: list[Workflow]) -> str:
    if not workflows:
        return "(no workflows registered)"
    lines: list[str] = []
    for w in workflows:
        lines.append(f"- name: {w.name}")
        if w.description:
            lines.append(f"  description: {w.description}")
        if w.chat_examples:
            lines.append("  chat_examples:")
            for ex in w.chat_examples:
                lines.append(f"    - {ex!r}")
        if w.inputs:
            lines.append("  inputs:")
            for k, default in w.inputs.items():
                lines.append(f"    - {k} (default: {default!r})")
    return "\n".join(lines)


def _format_history(turns: list[tuple[str, str]]) -> str:
    """`turns` is a list of (role, content) tuples, oldest first."""
    if not turns:
        return "(no prior turns)"
    return "\n".join(f"{role}: {content}" for role, content in turns)


def build_user_prompt(
    *,
    message: str,
    workflows: list[Workflow],
    history: list[tuple[str, str]],
) -> str:
    return (
        "Workflow catalog:\n"
        f"{_format_catalog(workflows)}\n\n"
        "Recent conversation (oldest first):\n"
        f"{_format_history(history)}\n\n"
        f"User: {message}\n\n"
        "Respond with one JSON object now."
    )


class Router:
    """Map a user message to a `RouterDecision` via an LLM call."""

    def __init__(
        self,
        provider: Provider,
        *,
        model: str | None = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self._provider = provider
        self._model = model
        self._system_prompt = system_prompt

    def decide(
        self,
        *,
        message: str,
        workflows: list[Workflow],
        history: list[tuple[str, str]] | None = None,
    ) -> RouterDecision:
        prompt = build_user_prompt(
            message=message,
            workflows=workflows,
            history=history or [],
        )
        completion = self._provider.complete(
            prompt=prompt,
            system=self._system_prompt,
            model=self._model,
            max_tokens=512,
        )
        return parse_decision(completion.text, workflows=workflows)


def parse_decision(
    raw: str, *, workflows: list[Workflow] | None = None
) -> RouterDecision:
    """Parse an LLM response into a RouterDecision.

    Tolerates leading/trailing whitespace and a code-fence wrapper —
    some models add them despite instructions. Anything else fails fast.
    """
    text = raw.strip()
    if text.startswith("```"):
        # strip a ```json ... ``` fence if present
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RouterError(f"router output was not valid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise RouterError(f"router output must be a JSON object, got {type(obj).__name__}")

    action = obj.get("action")
    if action not in ("run_workflow", "ask_clarifying", "chitchat", "agent_task"):
        raise RouterError(f"unknown router action {action!r}")

    if action == "run_workflow":
        wf_name = obj.get("workflow")
        if not isinstance(wf_name, str) or not wf_name:
            raise RouterError("run_workflow requires a 'workflow' string")
        # Validate against the catalog if one was supplied — refuse fabricated names.
        if workflows is not None and wf_name not in {w.name for w in workflows}:
            raise RouterError(
                f"router picked unknown workflow {wf_name!r} (not in catalog)"
            )
        inputs = obj.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise RouterError("'inputs' must be an object")
        return RouterDecision(
            action="run_workflow",
            workflow_name=wf_name,
            inputs=inputs,
            raw_response=raw,
        )

    text_field = obj.get("text")
    if not isinstance(text_field, str):
        raise RouterError(f"{action} requires a 'text' string")
    return RouterDecision(action=action, text=text_field, raw_response=raw)
