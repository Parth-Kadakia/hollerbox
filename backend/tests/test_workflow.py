"""Tests for hollerbox.core.workflow — pydantic models + YAML loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from hollerbox.core.workflow import (
    StepDefinition,
    Workflow,
    WorkflowLoadError,
    load_workflow,
    load_workflows_dir,
)


# ---------- Model-level tests ----------

class TestStepDefinition:
    def test_minimal_valid(self):
        s = StepDefinition(id="fetch", type="http", config={"url": "x"})
        assert s.id == "fetch"
        assert s.destructive is False
        assert s.on_error == "stop"
        assert s.max_attempts == 1

    def test_invalid_id_rejected(self):
        with pytest.raises(ValueError, match="Invalid step id"):
            StepDefinition(id="1bad", type="shell")
        with pytest.raises(ValueError, match="Invalid step id"):
            StepDefinition(id="has-dash", type="shell")

    def test_retry_requires_max_attempts_gte_2(self):
        with pytest.raises(ValueError, match="retry requires max_attempts"):
            StepDefinition(id="x", type="shell", on_error="retry", max_attempts=1)
        # ok with >=2
        StepDefinition(id="x", type="shell", on_error="retry", max_attempts=3)

    def test_unknown_step_field_rejected(self):
        with pytest.raises(ValueError, match="Extra inputs"):
            StepDefinition(id="x", type="shell", unknown_field=True)


class TestWorkflow:
    def test_minimal_valid(self):
        wf = Workflow(name="w", steps=[StepDefinition(id="s", type="shell")])
        assert wf.version == 1
        assert wf.description == ""
        assert wf.steps[0].id == "s"

    def test_duplicate_step_ids_rejected(self):
        with pytest.raises(ValueError, match="Duplicate step id"):
            Workflow(
                name="w",
                steps=[
                    StepDefinition(id="a", type="shell"),
                    StepDefinition(id="a", type="shell"),
                ],
            )

    def test_empty_steps_rejected(self):
        with pytest.raises(ValueError, match="at least one step"):
            Workflow(name="w", steps=[])

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            Workflow(name="   ", steps=[StepDefinition(id="s", type="shell")])

    def test_unknown_workflow_field_rejected(self):
        with pytest.raises(ValueError, match="Extra inputs"):
            Workflow(
                name="w",
                steps=[StepDefinition(id="s", type="shell")],
                bonus="nope",
            )


# ---------- YAML loader tests ----------

def _write(p: Path, content: str) -> Path:
    p.write_text(content, encoding="utf-8")
    return p


def test_load_workflow_happy_path(tmp_path: Path):
    f = _write(
        tmp_path / "hello.yaml",
        """
name: hello
version: 1
description: smoke test
inputs:
  who: world
steps:
  - id: greet
    type: shell
    config:
      command: echo hi
""",
    )
    wf = load_workflow(f)
    assert wf.name == "hello"
    assert wf.inputs == {"who": "world"}
    assert wf.steps[0].type == "shell"
    assert wf.steps[0].config == {"command": "echo hi"}


def test_load_workflow_missing_file(tmp_path: Path):
    with pytest.raises(WorkflowLoadError, match="does not exist"):
        load_workflow(tmp_path / "nope.yaml")


def test_load_workflow_empty(tmp_path: Path):
    f = _write(tmp_path / "empty.yaml", "")
    with pytest.raises(WorkflowLoadError, match="empty"):
        load_workflow(f)


def test_load_workflow_invalid_yaml(tmp_path: Path):
    f = _write(tmp_path / "broken.yaml", "name: foo\n  bad: : :")
    with pytest.raises(WorkflowLoadError, match="YAML parse error"):
        load_workflow(f)


def test_load_workflow_top_level_not_mapping(tmp_path: Path):
    f = _write(tmp_path / "list.yaml", "- a\n- b\n")
    with pytest.raises(WorkflowLoadError, match="must be a mapping"):
        load_workflow(f)


def test_load_workflow_schema_violation(tmp_path: Path):
    f = _write(
        tmp_path / "dup.yaml",
        """
name: w
steps:
  - id: a
    type: shell
  - id: a
    type: shell
""",
    )
    with pytest.raises(WorkflowLoadError, match="Duplicate step id"):
        load_workflow(f)


def test_load_workflows_dir(tmp_path: Path):
    _write(
        tmp_path / "one.yaml",
        "name: one\nsteps:\n  - id: a\n    type: shell\n",
    )
    _write(
        tmp_path / "two.yml",
        "name: two\nsteps:\n  - id: b\n    type: shell\n",
    )
    _write(tmp_path / "readme.txt", "ignored")  # non-YAML, skipped

    workflows = load_workflows_dir(tmp_path)
    assert sorted(workflows.keys()) == ["one", "two"]


def test_load_workflows_dir_duplicate_names(tmp_path: Path):
    _write(
        tmp_path / "a.yaml",
        "name: same\nsteps:\n  - id: a\n    type: shell\n",
    )
    _write(
        tmp_path / "b.yaml",
        "name: same\nsteps:\n  - id: b\n    type: shell\n",
    )
    with pytest.raises(WorkflowLoadError, match="duplicate workflow name"):
        load_workflows_dir(tmp_path)


def test_load_workflows_dir_not_a_directory(tmp_path: Path):
    f = _write(tmp_path / "x.yaml", "name: x\nsteps:\n  - id: a\n    type: shell\n")
    with pytest.raises(WorkflowLoadError, match="not a directory"):
        load_workflows_dir(f)
