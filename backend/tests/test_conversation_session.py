"""End-to-end conversation tests — engine-only, no HTTP.

Each test scripts the mock provider with a JSON envelope so the router
decision is deterministic, then drives a chat-triggered workflow run
through the same Worker the API uses.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from api.worker import Worker
from hollerbox.conversation import ConversationSession, Router
from hollerbox.core.runner import Runner
from hollerbox.core.workflow import load_workflow_from_source
from hollerbox.providers import MockProvider
from hollerbox.secrets import SecretStore
from hollerbox.store import init_db, make_engine, make_session_factory, repo, session_scope

SHELL_YAML = textwrap.dedent("""
name: demo
description: simplest possible runnable workflow
chat_examples:
  - "run demo"
steps:
  - id: greet
    type: shell
    config:
      command: "echo hi"
""").strip()

DESTRUCTIVE_YAML = textwrap.dedent("""
name: needs_approval
description: a workflow that pauses for approval
chat_examples:
  - "run the destructive thing"
steps:
  - id: confirm
    type: shell
    destructive: true
    requires_confirmation: true
    config:
      command: "echo would-delete"
""").strip()


@pytest.fixture()
def env(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'hb.sqlite'}"
    engine = make_engine(db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    secret_store = SecretStore(sf, key_path=tmp_path / "key")

    # Register both workflows so the router catalog is non-empty.
    for src in (SHELL_YAML, DESTRUCTIVE_YAML):
        wf = load_workflow_from_source(src)
        with session_scope(sf) as s:
            repo.upsert_workflow(s, wf, yaml_source=src)

    return sf, secret_store


def _make_session(sf, secret_store, payload: str | dict) -> ConversationSession:
    """Build a ConversationSession with a mock router pre-loaded with `payload`."""
    text = json.dumps(payload) if isinstance(payload, dict) else payload
    provider = MockProvider(default_text=text)
    runner = Runner(sf, secret_store=secret_store, providers={"mock": provider})
    router = Router(provider)
    return ConversationSession(sf, runner=runner, router=router)


def _surface(sf, secret_store):
    from api.deps import EngineSurface
    return EngineSurface(
        session_factory=sf,
        secret_store=secret_store,
        runner=Runner(sf, secret_store=secret_store, providers={}),
        providers={},
        image_providers={},
    )


# --------------------------- chitchat ---------------------------

def test_chitchat_records_assistant_reply(env) -> None:
    sf, ss = env
    session = _make_session(sf, ss, {"action": "chitchat", "text": "hello there"})
    cid = session.create()
    turn = session.post_user_message(cid, "hi")

    msgs = session.list_messages(cid)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[1].content == "hello there"
    assert msgs[1].kind == "text"
    assert len(turn.assistant_message_ids) == 1


def test_clarifying(env) -> None:
    sf, ss = env
    session = _make_session(
        sf, ss, {"action": "ask_clarifying", "text": "which workflow do you mean?"}
    )
    cid = session.create()
    session.post_user_message(cid, "something vague")
    msgs = session.list_messages(cid)
    assert msgs[1].content == "which workflow do you mean?"


# --------------------------- run_workflow ---------------------------

def test_run_workflow_acks_then_results_after_refresh(env) -> None:
    sf, ss = env
    session = _make_session(
        sf, ss, {"action": "run_workflow", "workflow": "demo", "inputs": {}}
    )
    cid = session.create()
    session.post_user_message(cid, "run demo")

    msgs = list(session.list_messages(cid))
    assert msgs[-1].kind == "ack"
    assert "demo" in msgs[-1].content

    # Drive the worker; the queued run should complete.
    Worker(_surface(sf, ss)).drive_one()
    new_ids = session.refresh(cid)
    assert len(new_ids) == 1

    msgs = list(session.list_messages(cid))
    assert msgs[-1].kind == "result"
    assert "demo" in msgs[-1].content


def test_run_workflow_rejects_fabricated_name(env) -> None:
    sf, ss = env
    # The mock returns a workflow name not in the catalog — `decide()` should
    # raise RouterError, which the session surfaces as an error reply.
    bad_payload = json.dumps({"action": "run_workflow", "workflow": "ghost", "inputs": {}})
    session = _make_session(sf, ss, bad_payload)
    cid = session.create()
    session.post_user_message(cid, "do something")
    msgs = list(session.list_messages(cid))
    assert msgs[-1].kind == "error"
    assert "trouble" in msgs[-1].content.lower()


# --------------------------- approval flow ---------------------------

def test_chat_destructive_workflow_pauses_and_resumes_on_yes(env) -> None:
    sf, ss = env
    session = _make_session(
        sf, ss, {"action": "run_workflow", "workflow": "needs_approval", "inputs": {}}
    )
    cid = session.create()
    session.post_user_message(cid, "run the destructive thing")

    # Drive the worker — destructive step pauses.
    Worker(_surface(sf, ss)).drive_one()
    session.refresh(cid)

    msgs = list(session.list_messages(cid))
    assert msgs[-1].kind == "approval_request"
    assert "reply" in msgs[-1].content.lower()

    # User replies "YES" → run resumes synchronously, result message appended.
    session.post_user_message(cid, "YES")
    msgs = list(session.list_messages(cid))
    assert msgs[-1].kind == "result"


def test_chat_destructive_workflow_cancels_on_no(env) -> None:
    sf, ss = env
    session = _make_session(
        sf, ss, {"action": "run_workflow", "workflow": "needs_approval", "inputs": {}}
    )
    cid = session.create()
    session.post_user_message(cid, "run the destructive thing")
    Worker(_surface(sf, ss)).drive_one()
    session.refresh(cid)

    session.post_user_message(cid, "no")
    msgs = list(session.list_messages(cid))
    assert msgs[-1].kind == "result"
    assert "cancelled" in msgs[-1].content.lower()


def test_unrelated_text_mid_approval_asks_for_yes_no(env) -> None:
    sf, ss = env
    session = _make_session(
        sf, ss, {"action": "run_workflow", "workflow": "needs_approval", "inputs": {}}
    )
    cid = session.create()
    session.post_user_message(cid, "run the destructive thing")
    Worker(_surface(sf, ss)).drive_one()
    session.refresh(cid)

    session.post_user_message(cid, "actually wait what does this do?")
    msgs = list(session.list_messages(cid))
    assert msgs[-1].kind == "text"
    assert "yes" in msgs[-1].content.lower()


# --------------------------- refresh idempotency ---------------------------

def test_refresh_is_idempotent(env) -> None:
    sf, ss = env
    session = _make_session(
        sf, ss, {"action": "run_workflow", "workflow": "demo", "inputs": {}}
    )
    cid = session.create()
    session.post_user_message(cid, "run demo")
    Worker(_surface(sf, ss)).drive_one()

    first = session.refresh(cid)
    second = session.refresh(cid)
    assert len(first) == 1
    assert second == []  # no new state to materialize
