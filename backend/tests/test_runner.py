"""Tests for hollerbox.core.runner.Runner.

These exercise the full path: load a workflow, drive the Runner against
an in-memory SQLite store, verify every transition through the database
(so we catch persistence regressions as well as logic bugs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hollerbox.core.runner import Runner
from hollerbox.core.workflow import StepDefinition, Workflow
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


@pytest.fixture()
def runner(session_factory):
    return Runner(session_factory)


def _wf(steps: list[StepDefinition], *, name: str = "wf") -> Workflow:
    return Workflow(name=name, steps=steps, inputs={})


# --------------------------- happy path ---------------------------

def test_simple_two_step_success(runner, session_factory):
    wf = _wf([
        StepDefinition(id="a", type="shell", config={"command": "echo first"}),
        StepDefinition(id="b", type="shell", config={"command": "echo second"}),
    ])
    result = runner.execute(wf)
    assert result.status == "success"

    with session_scope(session_factory) as s:
        run = repo.get_run(s, result.run_id)
        assert run.status == "success"
        assert run.started_at is not None and run.finished_at is not None
        steps = list(repo.list_step_runs(s, result.run_id))
        assert [r.step_id for r in steps] == ["a", "b"]
        assert all(r.status == "success" for r in steps)


def test_inputs_merged_with_workflow_defaults(runner, session_factory):
    wf = Workflow(
        name="wf",
        inputs={"who": "world"},
        steps=[
            StepDefinition(
                id="greet",
                type="shell",
                config={"command": "echo ${inputs.who}"},
            )
        ],
    )
    # No `inputs` arg → uses workflow default
    result = runner.execute(wf)
    with session_scope(session_factory) as s:
        steps = list(repo.list_step_runs(s, result.run_id))
        assert "world" in steps[0].output["stdout"]

    # Override input
    result2 = runner.execute(wf, inputs={"who": "you"})
    with session_scope(session_factory) as s:
        steps = list(repo.list_step_runs(s, result2.run_id))
        assert "you" in steps[0].output["stdout"]


def test_step_output_visible_to_later_steps(runner, session_factory):
    wf = _wf([
        StepDefinition(
            id="produce",
            type="python_step",
            config={"code": "output = {'msg': 'from-step-1'}"},
        ),
        StepDefinition(
            id="consume",
            type="shell",
            config={"command": "echo ${steps.produce.output.msg}"},
        ),
    ])
    result = runner.execute(wf)
    assert result.status == "success"
    with session_scope(session_factory) as s:
        steps = list(repo.list_step_runs(s, result.run_id))
        consume = next(r for r in steps if r.step_id == "consume")
        assert "from-step-1" in consume.output["stdout"]


# --------------------------- dry-run ---------------------------

def test_dry_run_skips_destructive_steps(runner, session_factory, tmp_path: Path):
    target = tmp_path / "must_not_exist.txt"
    wf = _wf([
        StepDefinition(id="read_safe", type="read_file", config={"path": "/dev/null"}),
        StepDefinition(
            id="write_destructive",
            type="write_file",
            config={"path": str(target), "content": "hi"},
        ),
    ])
    result = runner.execute(wf, dry_run=True)
    assert result.status == "success"
    assert not target.exists()  # destructive step never executed

    with session_scope(session_factory) as s:
        steps = list(repo.list_step_runs(s, result.run_id))
        statuses = {r.step_id: r.status for r in steps}
        assert statuses["read_safe"] == "success"          # non-destructive runs
        assert statuses["write_destructive"] == "dry_run"  # destructive recorded only
        # describe_effect mentions the bytes + path
        write_row = next(r for r in steps if r.step_id == "write_destructive")
        assert any("bytes" in line and str(target.resolve()) in line for line in write_row.logs)


# --------------------------- approvals + resume ---------------------------

def _approval_workflow(target: Path) -> Workflow:
    return _wf([
        StepDefinition(
            id="first",
            type="shell",
            config={"command": "echo before-approval"},
        ),
        StepDefinition(
            id="gated",
            type="write_file",
            config={"path": str(target), "content": "approved"},
            requires_confirmation=True,
        ),
        StepDefinition(
            id="after",
            type="shell",
            config={"command": "echo after-approval"},
        ),
    ])


def test_requires_confirmation_pauses_at_step(runner, session_factory, tmp_path: Path):
    target = tmp_path / "out.txt"
    wf = _approval_workflow(target)
    result = runner.execute(wf)
    assert result.status == "paused"
    assert result.last_step_id == "gated"
    assert not target.exists()  # gated step did not actually write

    with session_scope(session_factory) as s:
        run = repo.get_run(s, result.run_id)
        assert run.status == "paused"
        assert run.context_snapshot["steps"]["first"]["status"] == "success"
        steps = list(repo.list_step_runs(s, result.run_id))
        statuses = {r.step_id: r.status for r in steps}
        assert statuses["first"] == "success"
        assert statuses["gated"] == "pending_approval"
        assert "after" not in statuses  # never reached


def test_resume_with_approval_continues_to_completion(runner, session_factory, tmp_path: Path):
    target = tmp_path / "out.txt"
    wf = _approval_workflow(target)
    paused = runner.execute(wf)
    assert paused.status == "paused"

    final = runner.resume(wf, run_id=paused.run_id, approved=True)
    assert final.status == "success"
    assert target.read_text() == "approved"

    with session_scope(session_factory) as s:
        steps = list(repo.list_step_runs(s, paused.run_id))
        # The pending_approval row stays as historical record; a fresh
        # success row should now exist alongside it for the gated step.
        gated = [r for r in steps if r.step_id == "gated"]
        assert {r.status for r in gated} == {"pending_approval", "success"}
        # `after` step ran
        after = next(r for r in steps if r.step_id == "after")
        assert after.status == "success"


def test_resume_rejected_marks_cancelled(runner, session_factory, tmp_path: Path):
    target = tmp_path / "out.txt"
    wf = _approval_workflow(target)
    paused = runner.execute(wf)
    final = runner.resume(wf, run_id=paused.run_id, approved=False)
    assert final.status == "cancelled"
    assert not target.exists()
    with session_scope(session_factory) as s:
        run = repo.get_run(s, paused.run_id)
        assert run.status == "cancelled"
        assert "rejected" in (run.error or "")


def test_chat_triggered_destructive_step_pauses(runner, session_factory, tmp_path: Path):
    """In chat-triggered runs, ANY destructive step pauses for approval —
    even without `requires_confirmation: true`."""
    target = tmp_path / "out.txt"
    wf = _wf([
        StepDefinition(
            id="gated",
            type="write_file",
            config={"path": str(target), "content": "x"},
            # NOTE: requires_confirmation not set — but destructive=True by default for write_file
        ),
    ])
    result = runner.execute(wf, chat_triggered=True, trigger_kind="chat")
    assert result.status == "paused"
    assert not target.exists()


# --------------------------- error policy ---------------------------

def test_on_error_stop_halts_pipeline(runner, session_factory):
    wf = _wf([
        StepDefinition(id="ok", type="shell", config={"command": "echo ok"}),
        StepDefinition(
            id="bad",
            type="shell",
            config={"command": "exit 5"},
            on_error="stop",
        ),
        StepDefinition(id="never", type="shell", config={"command": "echo never"}),
    ])
    result = runner.execute(wf)
    assert result.status == "failed"
    assert result.last_step_id == "bad"
    with session_scope(session_factory) as s:
        statuses = {r.step_id: r.status for r in repo.list_step_runs(s, result.run_id)}
        assert statuses == {"ok": "success", "bad": "failed"}  # "never" not recorded


def test_on_error_continue_proceeds_past_failure(runner, session_factory):
    wf = _wf([
        StepDefinition(
            id="bad",
            type="shell",
            config={"command": "exit 5"},
            on_error="continue",
        ),
        StepDefinition(id="next", type="shell", config={"command": "echo next"}),
    ])
    result = runner.execute(wf)
    assert result.status == "success"  # workflow succeeded; one step failed-and-continued
    with session_scope(session_factory) as s:
        statuses = {r.step_id: r.status for r in repo.list_step_runs(s, result.run_id)}
        assert statuses == {"bad": "failed", "next": "success"}


def test_on_error_retry_makes_multiple_attempts(runner, session_factory, tmp_path: Path):
    # Use a python_step that fails on the first 2 attempts using a sidecar file.
    counter = tmp_path / "attempts.txt"
    wf = _wf([
        StepDefinition(
            id="flaky",
            type="python_step",
            config={
                "code": f"""
import pathlib
p = pathlib.Path({str(counter)!r})
n = int(p.read_text()) if p.exists() else 0
n += 1
p.write_text(str(n))
if n < 3:
    raise RuntimeError(f'attempt {{n}} fails')
output = {{'attempts': n}}
""".strip()
            },
            on_error="retry",
            max_attempts=3,
            backoff_seconds=0.0,
        )
    ])
    result = runner.execute(wf)
    assert result.status == "success"
    with session_scope(session_factory) as s:
        rows = list(repo.list_step_runs(s, result.run_id))
        # Three rows recorded, one per attempt.
        flaky_rows = [r for r in rows if r.step_id == "flaky"]
        assert len(flaky_rows) == 3
        assert [r.attempt for r in flaky_rows] == [1, 2, 3]
        assert [r.status for r in flaky_rows] == ["failed", "failed", "success"]


def test_on_error_retry_exhausted_marks_failed(runner, session_factory):
    wf = _wf([
        StepDefinition(
            id="always_fails",
            type="shell",
            config={"command": "exit 1"},
            on_error="retry",
            max_attempts=2,
            backoff_seconds=0.0,
        )
    ])
    result = runner.execute(wf)
    assert result.status == "failed"
    with session_scope(session_factory) as s:
        rows = list(repo.list_step_runs(s, result.run_id))
        assert len(rows) == 2
        assert [r.attempt for r in rows] == [1, 2]
        assert [r.status for r in rows] == ["failed", "failed"]


# --------------------------- secret redaction ---------------------------

def test_resolved_input_persists_with_secrets_redacted(runner, session_factory):
    wf = _wf([
        StepDefinition(
            id="needs_secret",
            type="shell",
            config={"command": "echo bearer ${secrets.TOKEN}"},
        )
    ])
    result = runner.execute(wf, secrets={"TOKEN": "sk-real"})
    assert result.status == "success"
    with session_scope(session_factory) as s:
        rows = list(repo.list_step_runs(s, result.run_id))
        assert "sk-real" not in str(rows[0].resolved_input)
        # The persisted resolved_input shows redaction
        assert "••••" in rows[0].resolved_input["command"]
        # The actual command DID run with the real secret in stdout
        assert "sk-real" in rows[0].output["stdout"]


# --------------------------- robustness ---------------------------

def test_unexpected_step_exception_is_caught_as_failed(runner, session_factory):
    # A python_step whose code itself raises is recorded as failed by the
    # step. But what if a step type's run() raises something completely
    # unexpected? The runner must still produce a coherent record.
    # We simulate by writing a python_step that triggers an uncaught error
    # inside the step itself: divide by zero in template-resolved code.
    wf = _wf([
        StepDefinition(
            id="boom",
            type="python_step",
            config={"code": "raise SystemExit('hard exit')"},
        )
    ])
    result = runner.execute(wf)
    assert result.status == "failed"
    with session_scope(session_factory) as s:
        run = repo.get_run(s, result.run_id)
        assert run.status == "failed"
        rows = list(repo.list_step_runs(s, result.run_id))
        assert rows[0].status == "failed"
        assert rows[0].error  # error message captured
