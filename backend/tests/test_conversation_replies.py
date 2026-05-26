"""Tests for `result_message` — the function that builds the chat reply
body when a workflow finishes."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from hollerbox.conversation.replies import result_message


def _run(status: str, name: str = "demo", error: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        error=error,
        workflow=SimpleNamespace(name=name),
    )


def _step(output: dict, status: str = "success") -> SimpleNamespace:
    return SimpleNamespace(status=status, output=output, started_at=datetime.now(UTC))


def test_llm_text_output_becomes_the_reply_body_verbatim():
    """An LLM step's `text` output is the chat answer the user wants to
    see — return it as-is, no "done — finished" prefix, no truncation."""
    long_text = "Here is a very detailed analysis " + "x" * 2000
    msg = result_message(
        _run("success"),
        [_step({"text": long_text, "model": "claude-opus-4-7", "provider": "anthropic"})],
    )
    assert msg == long_text
    assert len(msg) > 240  # confirms we removed the old 240-char cap


def test_file_output_still_uses_done_finished_phrasing():
    msg = result_message(
        _run("success", name="image_gen"),
        [_step({"paths": ["/tmp/out.png"], "n": 1})],
    )
    assert msg.startswith("done — `image_gen` finished.")
    assert "/tmp/out.png" in msg


def test_empty_text_falls_through_to_preview():
    """An LLM that returned empty text shouldn't produce a blank chat
    message — fall back to the file preview if any."""
    msg = result_message(
        _run("success", name="x"),
        [_step({"text": "", "paths": ["/tmp/o.txt"]})],
    )
    assert "wrote /tmp/o.txt" in msg


def test_shell_stdout_truncated_at_4k():
    huge = "out " * 5000  # 20k chars
    msg = result_message(_run("success", name="dump"), [_step({"stdout": huge})])
    assert msg.endswith("…")
    assert len(msg) < 5000  # well under the original 20k
