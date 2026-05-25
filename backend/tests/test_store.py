"""Tests for hollerbox.store — schema integrity + repo functions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hollerbox.core.workflow import StepDefinition, Workflow
from hollerbox.store import (
    ALL_TABLES,
    RunRow,
    StepRunRow,
    WorkflowRow,
    init_db,
    make_engine,
    make_session_factory,
    session_scope,
)
from hollerbox.store import repo


@pytest.fixture()
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture()
def sample_workflow() -> Workflow:
    return Workflow(
        name="hello",
        description="smoke",
        steps=[StepDefinition(id="greet", type="shell", config={"command": "echo hi"})],
    )


# --------------------------- schema integrity ---------------------------

def test_init_db_creates_all_expected_tables(session_factory):
    expected = {cls.__tablename__ for cls in ALL_TABLES}
    with session_scope(session_factory) as s:
        existing = {
            row[0]
            for row in s.execute(
                # sqlite_master.name returns table names
                __import__("sqlalchemy").text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
    assert expected <= existing, f"missing tables: {expected - existing}"


# --------------------------- workflows ---------------------------

def test_upsert_workflow_creates_then_updates(session_factory, sample_workflow):
    with session_scope(session_factory) as s:
        row = repo.upsert_workflow(s, sample_workflow, yaml_source="name: hello\n")
        assert row.id and len(row.id) == 32
        assert row.name == "hello"
        assert row.version == 1

    # Update path
    sample_workflow.version = 2
    sample_workflow.description = "v2"
    with session_scope(session_factory) as s:
        row2 = repo.upsert_workflow(s, sample_workflow, yaml_source="name: hello\nversion: 2\n")
        assert row2.id == row.id  # same row, not a new one
        assert row2.version == 2
        assert row2.description == "v2"


def test_get_workflow_by_name(session_factory, sample_workflow):
    with session_scope(session_factory) as s:
        repo.upsert_workflow(s, sample_workflow, yaml_source="x")
    with session_scope(session_factory) as s:
        wf = repo.get_workflow_by_name(s, "hello")
        assert wf is not None and wf.name == "hello"
        assert repo.get_workflow_by_name(s, "nope") is None


def test_list_workflows_sorted_by_name(session_factory):
    with session_scope(session_factory) as s:
        for name in ["zeta", "alpha", "mu"]:
            repo.upsert_workflow(
                s,
                Workflow(name=name, steps=[StepDefinition(id="a", type="shell")]),
                yaml_source=f"name: {name}\n",
            )
    with session_scope(session_factory) as s:
        names = [w.name for w in repo.list_workflows(s)]
        assert names == ["alpha", "mu", "zeta"]


# --------------------------- runs + step_runs ---------------------------

def test_create_run_and_record_steps_then_list(session_factory, sample_workflow):
    with session_scope(session_factory) as s:
        wf = repo.upsert_workflow(s, sample_workflow, yaml_source="x")
        run = repo.create_run(
            s,
            workflow_id=wf.id,
            run_id="run123",
            inputs={"a": 1},
            dry_run=False,
        )
        assert run.id == "run123"
        assert run.status == "queued"

        now = datetime.now(timezone.utc)
        repo.record_step_run(
            s,
            run_id="run123",
            step_id="greet",
            step_type="shell",
            status="success",
            resolved_input={"command": "echo hi"},
            output={"exit_code": 0},
            logs=["$ echo hi", "exit 0"],
            error=None,
            attempt=1,
            started_at=now,
            finished_at=now,
        )

    with session_scope(session_factory) as s:
        run = repo.get_run(s, "run123")
        assert run is not None
        steps = repo.list_step_runs(s, "run123")
        assert len(steps) == 1
        assert steps[0].step_id == "greet"
        assert steps[0].output == {"exit_code": 0}


def test_update_run_status_transitions(session_factory, sample_workflow):
    now = datetime.now(timezone.utc)
    with session_scope(session_factory) as s:
        wf = repo.upsert_workflow(s, sample_workflow, yaml_source="x")
        run = repo.create_run(
            s, workflow_id=wf.id, run_id="r2", inputs={}, dry_run=False
        )
        repo.update_run_status(
            s, run, status="running", started_at=now
        )
        repo.update_run_status(
            s,
            run,
            status="success",
            finished_at=now,
            context_snapshot={"inputs": {}, "steps": {}, "settings": {}, "run": {"id": "r2"}},
        )

    with session_scope(session_factory) as s:
        run = repo.get_run(s, "r2")
        assert run.status == "success"
        assert run.started_at is not None and run.finished_at is not None
        assert run.context_snapshot["run"]["id"] == "r2"


def test_list_runs_filtered_by_workflow_name(session_factory):
    with session_scope(session_factory) as s:
        wf_a = repo.upsert_workflow(
            s, Workflow(name="a", steps=[StepDefinition(id="x", type="shell")]), "y"
        )
        wf_b = repo.upsert_workflow(
            s, Workflow(name="b", steps=[StepDefinition(id="x", type="shell")]), "y"
        )
        repo.create_run(s, workflow_id=wf_a.id, run_id="ra1", inputs={}, dry_run=False)
        repo.create_run(s, workflow_id=wf_b.id, run_id="rb1", inputs={}, dry_run=False)
        repo.create_run(s, workflow_id=wf_a.id, run_id="ra2", inputs={}, dry_run=False)

    with session_scope(session_factory) as s:
        all_runs = [r.id for r in repo.list_runs(s)]
        assert set(all_runs) == {"ra1", "rb1", "ra2"}

        a_runs = [r.id for r in repo.list_runs(s, workflow_name="a")]
        assert set(a_runs) == {"ra1", "ra2"}


# --------------------------- settings ---------------------------

def test_settings_set_and_get(session_factory):
    with session_scope(session_factory) as s:
        repo.set_setting(s, "default_provider", "anthropic")
        repo.set_setting(s, "data_dir", "/tmp/x")
        repo.set_setting(s, "default_provider", "openai")  # update

    with session_scope(session_factory) as s:
        assert repo.get_setting(s, "default_provider") == "openai"
        assert repo.get_setting(s, "data_dir") == "/tmp/x"
        assert repo.get_setting(s, "missing", default="fallback") == "fallback"


def test_complex_json_round_trip(session_factory):
    payload = {
        "list": [1, 2, {"nested": True}],
        "string": "value",
        "null": None,
        "bool": False,
    }
    with session_scope(session_factory) as s:
        repo.set_setting(s, "complex", payload)
    with session_scope(session_factory) as s:
        assert repo.get_setting(s, "complex") == payload
