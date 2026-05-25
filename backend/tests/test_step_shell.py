"""Tests for hollerbox.steps.shell.ShellStep."""

from __future__ import annotations

from hollerbox.core.context import RunContext
from hollerbox.core.workflow import StepDefinition
from hollerbox.steps.shell import ShellStep


def _run(command: str, **kwargs):
    defn = StepDefinition(id="s", type="shell", config={"command": command, **kwargs})
    step = ShellStep(defn)
    ctx = RunContext.new(inputs={})
    return step, step.run(ctx)


def test_echo_succeeds():
    _, result = _run("echo hello")
    assert result.status == "success"
    assert result.output["exit_code"] == 0
    assert result.output["stdout"].strip() == "hello"


def test_template_resolution_in_command():
    defn = StepDefinition(
        id="s", type="shell", config={"command": "echo ${inputs.greeting}"}
    )
    step = ShellStep(defn)
    ctx = RunContext.new(inputs={"greeting": "hi from template"})
    result = step.run(ctx)
    assert result.status == "success"
    assert result.output["stdout"].strip() == "hi from template"


def test_nonzero_exit_marked_failed_when_check_true():
    _, result = _run("exit 7")
    assert result.status == "failed"
    assert "status 7" in (result.error or "")
    assert result.output["exit_code"] == 7


def test_nonzero_exit_succeeds_when_check_false():
    _, result = _run("exit 7", check=False)
    assert result.status == "success"
    assert result.output["exit_code"] == 7


def test_timeout_is_a_failure():
    _, result = _run("sleep 2", timeout=0.2)
    assert result.status == "failed"
    assert "timed out" in (result.error or "")


def test_stderr_captured():
    _, result = _run("echo oops >&2 && exit 1")
    assert result.status == "failed"
    assert "oops" in result.output["stderr"]


def test_describe_effect_resolves_templates():
    defn = StepDefinition(
        id="s", type="shell", config={"command": "echo ${inputs.x}"}
    )
    step = ShellStep(defn)
    ctx = RunContext.new(inputs={"x": "WORLD"})
    assert "echo WORLD" in step.describe_effect(ctx)


def test_shell_step_not_destructive_by_default():
    defn = StepDefinition(id="s", type="shell", config={"command": "echo"})
    step = ShellStep(defn)
    assert step.is_destructive is False
