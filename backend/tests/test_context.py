"""Tests for hollerbox.core.context.RunContext."""

from __future__ import annotations

from hollerbox.core.context import RunContext
from hollerbox.core.templating import SECRET_REDACTION


def test_new_populates_run_metadata():
    ctx = RunContext.new(inputs={"x": 1})
    assert ctx.inputs == {"x": 1}
    assert "id" in ctx.run and len(ctx.run["id"]) > 0
    assert "date" in ctx.run
    assert "timestamp" in ctx.run


def test_resolve_uses_inputs():
    ctx = RunContext.new(inputs={"topic": "ai"})
    assert ctx.resolve("${inputs.topic}") == "ai"


def test_record_step_then_resolve_step_output():
    ctx = RunContext.new(inputs={})
    ctx.record_step("fetch", status="success", output={"body": "ok", "code": 200})
    assert ctx.resolve("${steps.fetch.output.body}") == "ok"
    assert ctx.resolve("${steps.fetch.output.code}") == 200
    assert ctx.resolve("${steps.fetch.status}") == "success"


def test_resolve_real_secret_for_execution():
    ctx = RunContext.new(inputs={}, secrets={"K": "real-value"})
    assert ctx.resolve("${secrets.K}") == "real-value"


def test_resolve_redacted_hides_secret():
    ctx = RunContext.new(inputs={}, secrets={"K": "real-value"})
    assert ctx.resolve_redacted("${secrets.K}") == SECRET_REDACTION


def test_snapshot_omits_secrets():
    ctx = RunContext.new(inputs={"x": 1}, secrets={"K": "real-value"})
    snap = ctx.snapshot()
    assert "secrets" not in snap
    assert snap["inputs"] == {"x": 1}
    assert "run" in snap and "steps" in snap


def test_snapshot_captures_recorded_steps():
    ctx = RunContext.new(inputs={})
    ctx.record_step("a", status="success", output={"v": 1}, logs=["did a"])
    snap = ctx.snapshot()
    assert snap["steps"]["a"]["status"] == "success"
    assert snap["steps"]["a"]["output"] == {"v": 1}
    assert snap["steps"]["a"]["logs"] == ["did a"]


def test_explicit_run_id_is_honored():
    ctx = RunContext.new(inputs={}, run_id="custom-id")
    assert ctx.run["id"] == "custom-id"
