"""Tests for hollerbox.steps.files (ReadFileStep + WriteFileStep)."""

from __future__ import annotations

from pathlib import Path

from hollerbox.core.context import RunContext
from hollerbox.core.workflow import StepDefinition
from hollerbox.steps.files import ReadFileStep, WriteFileStep


def _run(step_cls, config: dict, *, inputs: dict | None = None):
    defn = StepDefinition(id="s", type=step_cls.type, config=config)
    step = step_cls(defn)
    ctx = RunContext.new(inputs=inputs or {})
    return step, step.run(ctx)


# --------------------------- ReadFileStep ---------------------------

def test_read_file_success(tmp_path: Path):
    f = tmp_path / "hello.txt"
    f.write_text("contents", encoding="utf-8")
    _, r = _run(ReadFileStep, {"path": str(f)})
    assert r.status == "success"
    assert r.output["content"] == "contents"
    assert r.output["size"] == len("contents")
    assert r.output["path"] == str(f.resolve())


def test_read_file_missing(tmp_path: Path):
    _, r = _run(ReadFileStep, {"path": str(tmp_path / "nope.txt")})
    assert r.status == "failed"
    assert "does not exist" in (r.error or "")


def test_read_file_template_path(tmp_path: Path):
    f = tmp_path / "templated.txt"
    f.write_text("from template", encoding="utf-8")
    _, r = _run(
        ReadFileStep, {"path": "${inputs.dir}/templated.txt"}, inputs={"dir": str(tmp_path)}
    )
    assert r.status == "success"
    assert r.output["content"] == "from template"


def test_read_file_step_not_destructive():
    defn = StepDefinition(id="r", type="read_file", config={"path": "/dev/null"})
    assert ReadFileStep(defn).is_destructive is False


# --------------------------- WriteFileStep ---------------------------

def test_write_file_overwrite_creates_file(tmp_path: Path):
    target = tmp_path / "out.md"
    _, r = _run(WriteFileStep, {"path": str(target), "content": "hello"})
    assert r.status == "success"
    assert target.read_text() == "hello"
    assert r.output["bytes_written"] == 5


def test_write_file_creates_parents(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "file.txt"
    _, r = _run(WriteFileStep, {"path": str(target), "content": "x"})
    assert r.status == "success"
    assert target.exists()


def test_write_file_append_mode(tmp_path: Path):
    target = tmp_path / "log.txt"
    target.write_text("a", encoding="utf-8")
    _, r = _run(WriteFileStep, {"path": str(target), "content": "b", "mode": "append"})
    assert r.status == "success"
    assert target.read_text() == "ab"


def test_write_file_no_overwrite_refuses_existing(tmp_path: Path):
    target = tmp_path / "exists.txt"
    target.write_text("already here", encoding="utf-8")
    _, r = _run(
        WriteFileStep, {"path": str(target), "content": "new", "mode": "no_overwrite"}
    )
    assert r.status == "failed"
    assert "refusing to overwrite" in (r.error or "")
    # Content unchanged.
    assert target.read_text() == "already here"


def test_write_file_template_content(tmp_path: Path):
    target = tmp_path / "out.txt"
    _, r = _run(
        WriteFileStep,
        {"path": str(target), "content": "topic=${inputs.topic}"},
        inputs={"topic": "ai"},
    )
    assert r.status == "success"
    assert target.read_text() == "topic=ai"


def test_write_file_step_is_destructive_by_default(tmp_path: Path):
    defn = StepDefinition(
        id="w", type="write_file", config={"path": str(tmp_path / "x"), "content": ""}
    )
    assert WriteFileStep(defn).is_destructive is True


def test_write_file_describe_effect_does_not_write(tmp_path: Path):
    target = tmp_path / "not-written.txt"
    defn = StepDefinition(
        id="w", type="write_file", config={"path": str(target), "content": "hi"}
    )
    step = WriteFileStep(defn)
    ctx = RunContext.new(inputs={})
    description = step.describe_effect(ctx)
    assert "2 bytes" in description
    assert str(target.resolve()) in description
    assert not target.exists()  # describe_effect must be side-effect-free
