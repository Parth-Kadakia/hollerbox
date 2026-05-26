"""Conversation session orchestration.

The session is the bridge between chat messages and engine actions:

1. User posts a message.
2. If the conversation has a paused run waiting on the user, we
   interpret the message as approve/reject/etc.
3. Otherwise, the router decides what to do. For `run_workflow`, we
   enqueue a chat-triggered run (`trigger_kind=chat`) and respond with
   an "on it" ack. For `ask_clarifying` / `chitchat` / `agent_task`, we
   just record an assistant text reply.
4. `refresh(conv_id)` brings the message thread up to date with any
   state changes in this conversation's runs — inserting an
   `approval_request` or `result` message for runs that have just
   paused / finished since the last refresh. The API SSE endpoint calls
   this on every iteration so the chat updates without explicit pokes.

Engine-only — no HTTP, no FastAPI.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hollerbox.conversation.replies import (
    ack_message,
    approval_request,
    result_message,
)
from hollerbox.conversation.router import Router, RouterDecision, RouterError
from hollerbox.core.runner import Runner
from hollerbox.core.workflow import (
    Workflow,
    WorkflowLoadError,
    load_workflow_from_source,
)
from hollerbox.store import repo, session_scope
from hollerbox.store.models import ConversationRow, MessageRow, RunRow, StepRunRow

YES_PATTERN = re.compile(
    r"^\s*(y|yes|yep|yeah|ok|okay|approve|approved|go|do it|proceed|confirm|sure)\s*[!.]?\s*$",
    re.IGNORECASE,
)
NO_PATTERN = re.compile(
    r"^\s*(n|no|nope|cancel|stop|reject|abort|nah)\s*[!.]?\s*$",
    re.IGNORECASE,
)


@dataclass
class TurnResult:
    """Everything a single user message produced — for the API to return."""

    user_message_id: str
    assistant_message_ids: list[str]


class ConversationSession:
    """One stateful conversation, bound to engine + router + persistence."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        runner: Runner,
        router: Router,
        history_turns: int = 10,
    ) -> None:
        self._sf = session_factory
        self._runner = runner
        self._router = router
        self._history_turns = history_turns

    # --------------------------- public API ---------------------------

    def create(self, *, title: str = "") -> str:
        with session_scope(self._sf) as s:
            row = repo.create_conversation(s, title=title)
            return row.id

    def post_user_message(
        self,
        conv_id: str,
        text: str,
        *,
        attachment_paths: list[str] | None = None,
    ) -> TurnResult:
        """Record a user message and produce one or more assistant replies.

        `attachment_paths` (absolute paths inside the uploads sandbox) are
        appended to the persisted content as `[attached: ...]` lines so
        the router LLM sees them in context. The same lines are parsed
        back out at render time into `ChatMessage.attachments`.
        """
        # Build the persisted body. Trailing attachment lines are a
        # machine-readable contract — keep the format stable.
        attachments = [p for p in (attachment_paths or []) if p]
        full_content = text
        if attachments:
            tail = "\n\n" + "\n".join(f"[attached: {p}]" for p in attachments)
            full_content = full_content + tail

        # 1. Record the user message
        with session_scope(self._sf) as s:
            conv = repo.get_conversation(s, conv_id)
            if conv is None:
                raise ValueError(f"conversation {conv_id!r} not found")
            user_msg = repo.add_message(
                s,
                conversation_id=conv_id,
                role="user",
                content=full_content,
                kind="text",
            )
            user_msg_id = user_msg.id

        # 2. If there's a paused run for this conversation, interpret as approval
        #    Use the bare text (without attachment markers) for the yes/no match.
        decision_handled = self._maybe_handle_approval(conv_id, text)
        if decision_handled is not None:
            return TurnResult(
                user_message_id=user_msg_id,
                assistant_message_ids=decision_handled,
            )

        # 3. Otherwise, route the message. The router sees full_content so
        #    it knows about the attachments and can hand them to workflows.
        assistant_ids = self._route_and_respond(conv_id, full_content)
        return TurnResult(user_message_id=user_msg_id, assistant_message_ids=assistant_ids)

    def list_messages(self, conv_id: str) -> Sequence[MessageRow]:
        with session_scope(self._sf) as s:
            return repo.list_messages(s, conv_id)

    def refresh(self, conv_id: str) -> list[str]:
        """Reconcile message thread with current run state.

        Returns the ids of any newly inserted messages. Idempotent —
        safe to call repeatedly (e.g. on every SSE tick).
        """
        new_ids: list[str] = []

        with session_scope(self._sf) as s:
            # Pull every chat-triggered run this conversation spawned that
            # we haven't already terminated/approved in a message.
            ack_runs = s.scalars(
                select(MessageRow.run_id)
                .where(MessageRow.conversation_id == conv_id)
                .where(MessageRow.kind == "ack")
                .where(MessageRow.run_id.is_not(None))
            ).all()
            handled = {
                rid
                for rid in s.scalars(
                    select(MessageRow.run_id)
                    .where(MessageRow.conversation_id == conv_id)
                    .where(MessageRow.kind.in_(("result", "error")))
                    .where(MessageRow.run_id.is_not(None))
                ).all()
            }
            pending_approval = {
                rid
                for rid in s.scalars(
                    select(MessageRow.run_id)
                    .where(MessageRow.conversation_id == conv_id)
                    .where(MessageRow.kind == "approval_request")
                    .where(MessageRow.run_id.is_not(None))
                ).all()
            }

            for run_id in ack_runs:
                if run_id in handled:
                    continue
                run = repo.get_run(s, run_id)
                if run is None:
                    continue
                if run.status == "paused" and run_id not in pending_approval:
                    step = self._latest_pending_step(s, run_id)
                    body = approval_request(step) if step else (
                        "Approval needed — reply YES to proceed."
                    )
                    msg = repo.add_message(
                        s,
                        conversation_id=conv_id,
                        role="assistant",
                        content=body,
                        kind="approval_request",
                        run_id=run_id,
                    )
                    new_ids.append(msg.id)
                elif run.status in ("success", "failed", "cancelled"):
                    steps = list(repo.list_step_runs(s, run_id))
                    msg = repo.add_message(
                        s,
                        conversation_id=conv_id,
                        role="assistant",
                        content=result_message(run, steps),
                        kind=("error" if run.status == "failed" else "result"),
                        run_id=run_id,
                    )
                    new_ids.append(msg.id)

        return new_ids

    # --------------------------- internals ---------------------------

    def _maybe_handle_approval(self, conv_id: str, text: str) -> list[str] | None:
        """If the conversation has a paused run, treat the user's text as approve/reject.

        Returns the list of assistant message ids produced, or None if the
        message wasn't an approval response (caller should route as normal).
        """
        with session_scope(self._sf) as s:
            paused_run = self._find_paused_run(s, conv_id)
            if paused_run is None:
                return None

        is_yes = bool(YES_PATTERN.match(text))
        is_no = bool(NO_PATTERN.match(text))
        if not is_yes and not is_no:
            # User said something else mid-approval — treat as a clarifying
            # follow-up; record an assistant message asking them to confirm.
            with session_scope(self._sf) as s:
                msg = repo.add_message(
                    s,
                    conversation_id=conv_id,
                    role="assistant",
                    content="I'm still waiting on a yes/no — reply **YES** to proceed or **NO** to cancel.",
                    kind="text",
                    run_id=paused_run.id,
                )
                return [msg.id]

        # Resume the run synchronously (it's fast for the common case).
        wf = self._load_workflow_for_run(paused_run.id)
        result = self._runner.resume(wf, run_id=paused_run.id, approved=is_yes)

        # Reflect the resumed state in chat.
        with session_scope(self._sf) as s:
            run = repo.get_run(s, result.run_id)
            assert run is not None
            ids: list[str] = []
            if result.status in ("success", "failed", "cancelled"):
                steps = list(repo.list_step_runs(s, run.id))
                msg = repo.add_message(
                    s,
                    conversation_id=conv_id,
                    role="assistant",
                    content=result_message(run, steps),
                    kind=("error" if result.status == "failed" else "result"),
                    run_id=run.id,
                )
                ids.append(msg.id)
            elif result.status == "paused":
                # Multi-step approval — surface the next gate.
                step = self._latest_pending_step(s, run.id)
                body = approval_request(step) if step else (
                    "Another approval is needed — reply YES to proceed."
                )
                msg = repo.add_message(
                    s,
                    conversation_id=conv_id,
                    role="assistant",
                    content=body,
                    kind="approval_request",
                    run_id=run.id,
                )
                ids.append(msg.id)
            return ids

    def _route_and_respond(self, conv_id: str, text: str) -> list[str]:
        # Snapshot current workflow catalog + history before the LLM call.
        workflows = self._load_catalog()
        history = self._recent_history(conv_id)

        try:
            decision = self._router.decide(
                message=text, workflows=workflows, history=history
            )
        except RouterError as exc:
            with session_scope(self._sf) as s:
                msg = repo.add_message(
                    s,
                    conversation_id=conv_id,
                    role="assistant",
                    content=(
                        "I had trouble understanding that — could you rephrase? "
                        f"({exc})"
                    ),
                    kind="error",
                )
                return [msg.id]

        return self._apply_decision(conv_id, decision)

    def _apply_decision(self, conv_id: str, decision: RouterDecision) -> list[str]:
        if decision.action == "run_workflow":
            return self._enqueue_chat_run(
                conv_id, decision.workflow_name or "", decision.inputs
            )
        if decision.action == "ask_clarifying":
            return self._reply(conv_id, decision.text, kind="text")
        if decision.action == "chitchat":
            return self._reply(conv_id, decision.text, kind="text")
        if decision.action == "agent_task":
            placeholder = (
                f"That's an open-ended request: \"{decision.text}\". "
                "The agent fallback lands in Phase 7 — for now, try wording it "
                "as one of the registered workflows."
            )
            return self._reply(conv_id, placeholder, kind="text")
        # Unknown action — defensive
        return self._reply(conv_id, "I'm not sure how to handle that yet.", kind="error")

    def _enqueue_chat_run(
        self, conv_id: str, wf_name: str, inputs: dict[str, Any]
    ) -> list[str]:
        with session_scope(self._sf) as s:
            wf_row = repo.get_workflow_by_name(s, wf_name)
            if wf_row is None:
                msg = repo.add_message(
                    s,
                    conversation_id=conv_id,
                    role="assistant",
                    content=f"I picked `{wf_name}` but it isn't registered.",
                    kind="error",
                )
                return [msg.id]
            yaml_source = wf_row.yaml_source

        try:
            wf = load_workflow_from_source(yaml_source, name_hint=wf_name)
        except WorkflowLoadError as exc:
            with session_scope(self._sf) as s:
                msg = repo.add_message(
                    s,
                    conversation_id=conv_id,
                    role="assistant",
                    content=f"Workflow `{wf_name}` failed to load: {exc}",
                    kind="error",
                )
                return [msg.id]

        enqueued = self._runner.enqueue(
            wf,
            inputs=inputs,
            yaml_source=yaml_source,
            trigger_kind="chat",
        )

        # Attach the run to this conversation so refresh() can find it.
        with session_scope(self._sf) as s:
            run = repo.get_run(s, enqueued.run_id)
            assert run is not None
            run.conversation_id = conv_id
            ack = repo.add_message(
                s,
                conversation_id=conv_id,
                role="assistant",
                content=ack_message(wf_name),
                kind="ack",
                run_id=enqueued.run_id,
            )
            return [ack.id]

    def _reply(self, conv_id: str, text: str, *, kind: str) -> list[str]:
        with session_scope(self._sf) as s:
            msg = repo.add_message(
                s,
                conversation_id=conv_id,
                role="assistant",
                content=text,
                kind=kind,
            )
            return [msg.id]

    # --------------------------- lookups ---------------------------

    def _load_catalog(self) -> list[Workflow]:
        out: list[Workflow] = []
        with session_scope(self._sf) as s:
            rows = list(repo.list_workflows(s))
            sources = [(r.name, r.yaml_source) for r in rows if r.enabled]
        for name, src in sources:
            try:
                out.append(load_workflow_from_source(src, name_hint=name))
            except WorkflowLoadError:
                # Skip bad rows rather than poisoning the catalog. They'll
                # surface as 422s through the Editor.
                continue
        return out

    def _recent_history(self, conv_id: str) -> list[tuple[str, str]]:
        with session_scope(self._sf) as s:
            msgs = list(repo.list_messages(s, conv_id))
        # Drop the most recent user message (we pass it separately) and
        # only keep the last N turns.
        if msgs and msgs[-1].role == "user":
            msgs = msgs[:-1]
        return [(m.role, m.content) for m in msgs[-self._history_turns :]]

    def _find_paused_run(self, s: Session, conv_id: str) -> RunRow | None:
        return s.scalar(
            select(RunRow)
            .where(RunRow.conversation_id == conv_id)
            .where(RunRow.status == "paused")
            .order_by(RunRow.created_at.desc())
            .limit(1)
        )

    def _latest_pending_step(self, s: Session, run_id: str) -> StepRunRow | None:
        return s.scalar(
            select(StepRunRow)
            .where(StepRunRow.run_id == run_id)
            .where(StepRunRow.status == "pending_approval")
            .order_by(StepRunRow.created_at.desc())
            .limit(1)
        )

    def _load_workflow_for_run(self, run_id: str) -> Workflow:
        with session_scope(self._sf) as s:
            run = repo.get_run(s, run_id)
            assert run is not None
            wf_row = run.workflow
            assert wf_row is not None
            return load_workflow_from_source(wf_row.yaml_source, name_hint=wf_row.name)


def _convo_touch_via_orm(s: Session, conv: ConversationRow) -> None:
    """Kept for symmetry; current implementation updates `updated_at` in `add_message`."""
