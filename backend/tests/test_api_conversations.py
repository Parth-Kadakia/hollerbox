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


def test_title_derived_from_first_user_message(api_client, api_surface) -> None:
    _script(api_surface, {"action": "chitchat", "text": "hi"})
    cid = _create_conv(api_client)
    api_client.post(f"/conversations/{cid}/messages", json={"content": "summarize my email please"})
    listing = api_client.get("/conversations").json()
    assert listing[0]["title"] == "summarize my email please"


def test_title_truncated_for_long_messages(api_client, api_surface) -> None:
    _script(api_surface, {"action": "chitchat", "text": "hi"})
    cid = _create_conv(api_client)
    long_msg = "a" * 200
    api_client.post(f"/conversations/{cid}/messages", json={"content": long_msg})
    listing = api_client.get("/conversations").json()
    assert listing[0]["title"].endswith("…")
    assert len(listing[0]["title"]) <= 60


def test_title_falls_back_to_new_chat_when_empty(api_client) -> None:
    cid = _create_conv(api_client)
    listing = api_client.get("/conversations").json()
    assert listing[0]["title"] == "New chat"
    assert cid  # bind for clarity


def test_delete_conversation_removes_it_but_keeps_runs(api_client, api_surface) -> None:
    api_client.put(
        "/workflows/demo",
        json={"yaml_source": SHELL_YAML},
    )
    _script(api_surface, {"action": "run_workflow", "workflow": "demo", "inputs": {}})
    cid = _create_conv(api_client)
    api_client.post(f"/conversations/{cid}/messages", json={"content": "run demo"})
    Worker(api_surface).drive_one()

    # The chat triggered a run — confirm it exists.
    runs_before = api_client.get("/runs").json()
    assert len(runs_before) == 1

    resp = api_client.delete(f"/conversations/{cid}")
    assert resp.status_code == 204
    assert api_client.get("/conversations").json() == []
    # The run survives — chat deletion is not a destructive op for run history.
    runs_after = api_client.get("/runs").json()
    assert len(runs_after) == 1


def test_delete_404_for_missing_conv(api_client) -> None:
    assert api_client.delete("/conversations/ghost").status_code == 404


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


def test_provider_override_routes_through_chosen_provider(api_client, api_surface) -> None:
    """Two registered providers with different responses → the body's
    `provider` field decides which one the router calls."""
    from hollerbox.core.runner import Runner
    from hollerbox.providers import MockProvider

    a = MockProvider(default_text=json.dumps({"action": "chitchat", "text": "from A"}))
    b = MockProvider(default_text=json.dumps({"action": "chitchat", "text": "from B"}))
    api_surface.providers = {"mock": a, "alt": b}
    api_surface.runner = Runner(
        api_surface.session_factory,
        secret_store=api_surface.secret_store,
        providers=api_surface.providers,
    )

    cid = _create_conv(api_client)
    resp = api_client.post(
        f"/conversations/{cid}/messages",
        json={"content": "hi", "provider": "alt"},
    )
    msgs = resp.json()["messages"]
    assert msgs[-1]["content"] == "from B"
    # The non-selected provider should NOT have been called.
    assert a.calls == []
    assert len(b.calls) == 1


def test_attachment_paths_become_user_message_attachments(
    api_client, api_surface, tmp_path, monkeypatch
) -> None:
    """Upload a file, send a chat message attaching it — the user message
    should carry the file as an attachment and the visible content should
    NOT include the [attached: ...] marker."""
    monkeypatch.setenv("HOLLERBOX_DATA_DIR", str(tmp_path))
    up = api_client.post(
        "/files/upload",
        files={"file": ("notes.txt", b"hi", "text/plain")},
    ).json()

    _script(api_surface, {"action": "chitchat", "text": "got it"})
    cid = _create_conv(api_client)
    resp = api_client.post(
        f"/conversations/{cid}/messages",
        json={"content": "look at this", "attachment_paths": [up["path"]]},
    )
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    user_msg = msgs[0]
    assert user_msg["role"] == "user"
    # Marker is stripped from the visible body.
    assert "[attached" not in user_msg["content"]
    assert user_msg["content"] == "look at this"
    # The file shows up as an attachment.
    assert len(user_msg["attachments"]) == 1
    assert user_msg["attachments"][0]["name"] == "notes.txt"


def test_router_sees_attached_paths_in_prompt(
    api_client, api_surface, tmp_path, monkeypatch
) -> None:
    """The router LLM call must include the attached path in the prompt
    so it can hand it to a workflow."""
    monkeypatch.setenv("HOLLERBOX_DATA_DIR", str(tmp_path))
    up = api_client.post(
        "/files/upload",
        files={"file": ("doc.pdf", b"%PDF-", "application/pdf")},
    ).json()

    from hollerbox.providers import MockProvider

    mock = MockProvider(default_text=json.dumps({"action": "chitchat", "text": "ok"}))
    api_surface.providers["mock"] = mock

    cid = _create_conv(api_client)
    api_client.post(
        f"/conversations/{cid}/messages",
        json={"content": "summarize this", "attachment_paths": [up["path"]]},
    )
    last_prompt = mock.calls[-1]["prompt"]
    assert "attached" in last_prompt
    assert up["path"] in last_prompt


def test_model_override_is_passed_to_provider(api_client, api_surface) -> None:
    from hollerbox.providers import MockProvider

    p = MockProvider(default_text=json.dumps({"action": "chitchat", "text": "ok"}))
    api_surface.providers["mock"] = p

    cid = _create_conv(api_client)
    api_client.post(
        f"/conversations/{cid}/messages",
        json={"content": "hi", "model": "my-special-model"},
    )
    assert p.calls[-1]["model"] == "my-special-model"


# --------------------------- attachments ---------------------------

def test_result_message_carries_file_attachments(api_client, api_surface, tmp_path) -> None:
    """A workflow that writes a file should surface it as an attachment on the result message."""
    target = tmp_path / "report.txt"
    yaml_src = (
        "name: writes\n"
        "chat_examples: [run writes]\n"
        "steps:\n"
        "  - id: write\n"
        "    type: write_file\n"
        "    config:\n"
        f"      path: {target}\n"
        '      content: "hello"\n'
    )
    api_client.put("/workflows/writes", json={"yaml_source": yaml_src})
    _script(api_surface, {"action": "run_workflow", "workflow": "writes", "inputs": {}})

    cid = _create_conv(api_client)
    api_client.post(f"/conversations/{cid}/messages", json={"content": "run it"})
    Worker(api_surface).drive_one()
    # write_file is destructive — chat triggers pause for approval. Refresh
    # the thread, then approve via chat to drive the step to success.
    from hollerbox.conversation import ConversationSession, Router
    sess = ConversationSession(
        api_surface.session_factory,
        runner=api_surface.runner,
        router=Router(api_surface.providers["mock"]),
    )
    sess.refresh(cid)
    api_client.post(f"/conversations/{cid}/messages", json={"content": "yes"})

    msgs = api_client.get(f"/conversations/{cid}/messages").json()
    result = next(m for m in msgs if m["kind"] == "result")
    assert result["attachments"]
    att = result["attachments"][0]
    assert att["name"] == "report.txt"
    assert att["kind"] == "file"
    assert att["url"].startswith("/files?path=")


def test_image_extension_marks_attachment_as_image(api_client, api_surface, tmp_path) -> None:
    target = tmp_path / "pic.png"
    # write_file is a quick way to fake an image — we only test the
    # classifier, not the bytes.
    yaml_src = (
        "name: paints\n"
        "chat_examples: [paint]\n"
        "steps:\n"
        "  - id: write\n"
        "    type: write_file\n"
        "    config:\n"
        f"      path: {target}\n"
        '      content: "fake png"\n'
    )
    api_client.put("/workflows/paints", json={"yaml_source": yaml_src})
    _script(api_surface, {"action": "run_workflow", "workflow": "paints", "inputs": {}})
    cid = _create_conv(api_client)
    api_client.post(f"/conversations/{cid}/messages", json={"content": "paint"})
    Worker(api_surface).drive_one()
    from hollerbox.conversation import ConversationSession, Router
    ConversationSession(
        api_surface.session_factory,
        runner=api_surface.runner,
        router=Router(api_surface.providers["mock"]),
    ).refresh(cid)
    api_client.post(f"/conversations/{cid}/messages", json={"content": "yes"})

    msgs = api_client.get(f"/conversations/{cid}/messages").json()
    result = next(m for m in msgs if m["kind"] == "result")
    assert result["attachments"][0]["kind"] == "image"
