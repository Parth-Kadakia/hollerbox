"""HTTP-level tests for /conversations.

We swap the router's mock provider into `api_surface.providers["mock"]`
so chat works without a real LLM key. Each test scripts a different
JSON envelope to drive a different code path.
"""

from __future__ import annotations

import json
import textwrap

from api.worker import Worker
from hollerbox.providers import MockProvider

SHELL_YAML = textwrap.dedent("""
name: demo
chat_examples:
  - run demo
steps:
  - id: greet
    type: shell
    config:
      command: "echo hi"
""").strip()

DESTRUCTIVE_YAML = textwrap.dedent("""
name: needs_approval
chat_examples:
  - destructive
steps:
  - id: confirm
    type: shell
    destructive: true
    requires_confirmation: true
    config:
      command: "echo would-delete"
""").strip()


def _script(api_surface, payload: dict) -> None:
    """Replace the surface's mock provider with one returning `payload` as JSON."""
    api_surface.providers["mock"] = MockProvider(default_text=json.dumps(payload))
    # The Runner caches a reference to the providers dict from construction
    # time; rebuilding the runner so `enqueue` paths pick up the new mock.
    from hollerbox.core.runner import Runner
    api_surface.runner = Runner(
        api_surface.session_factory,
        secret_store=api_surface.secret_store,
        providers=api_surface.providers,
    )


def _create_conv(client) -> str:
    resp = client.post("/conversations", json={"title": ""})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --------------------------- CRUD ---------------------------

def test_create_and_list_conversations(api_client) -> None:
    cid = _create_conv(api_client)
    listing = api_client.get("/conversations").json()
    assert len(listing) == 1
    assert listing[0]["id"] == cid


def test_messages_404_for_missing_conv(api_client) -> None:
    assert api_client.get("/conversations/ghost/messages").status_code == 404


# --------------------------- chat flow ---------------------------

def test_chitchat_records_assistant_reply(api_client, api_surface) -> None:
    _script(api_surface, {"action": "chitchat", "text": "hey friend"})
    cid = _create_conv(api_client)
    resp = api_client.post(f"/conversations/{cid}/messages", json={"content": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["content"] == "hey friend"


def test_run_workflow_chat_flow(api_client, api_surface) -> None:
    api_client.put("/workflows/demo", json={"yaml_source": SHELL_YAML})
    _script(api_surface, {"action": "run_workflow", "workflow": "demo", "inputs": {}})
    cid = _create_conv(api_client)
    resp = api_client.post(f"/conversations/{cid}/messages", json={"content": "run demo"})

    msgs = resp.json()["messages"]
    assert msgs[-1]["kind"] == "ack"
    assert msgs[-1]["run_id"]

    # Drive the worker, then GET messages — refresh() materializes the result.
    Worker(api_surface).drive_one()
    msgs2 = api_client.get(f"/conversations/{cid}/messages").json()
    # SSE endpoint calls refresh(); a direct GET doesn't, so we trigger
    # refresh by sending another message that exercises the same path…
    # Simpler: hit the SSE endpoint briefly. But the direct invariant here is
    # that after `drive_one` + a refresh, the result lands. Use the engine
    # session directly:
    from hollerbox.conversation import ConversationSession, Router
    session = ConversationSession(
        api_surface.session_factory,
        runner=api_surface.runner,
        router=Router(api_surface.providers["mock"]),
    )
    session.refresh(cid)
    msgs3 = api_client.get(f"/conversations/{cid}/messages").json()
    assert msgs3[-1]["kind"] == "result"
    assert len(msgs3) > len(msgs2)


def test_chat_destructive_approval_yes_resumes(api_client, api_surface) -> None:
    api_client.put("/workflows/needs_approval", json={"yaml_source": DESTRUCTIVE_YAML})
    _script(api_surface, {"action": "run_workflow", "workflow": "needs_approval", "inputs": {}})
    cid = _create_conv(api_client)
    api_client.post(f"/conversations/{cid}/messages", json={"content": "run it"})
    Worker(api_surface).drive_one()

    # User replies YES — session catches the approval intent before routing.
    resp = api_client.post(f"/conversations/{cid}/messages", json={"content": "yes"})
    msgs = resp.json()["messages"]
    assert msgs[-1]["kind"] == "result"


def test_send_message_404_for_missing_conv(api_client) -> None:
    resp = api_client.post("/conversations/missing/messages", json={"content": "hi"})
    assert resp.status_code == 404


def test_send_message_409_when_no_provider(api_client, api_surface) -> None:
    api_surface.providers = {}
    cid = _create_conv(api_client)
    resp = api_client.post(f"/conversations/{cid}/messages", json={"content": "hi"})
    assert resp.status_code == 409
    assert "provider" in resp.json()["detail"].lower()
