"""Tests for hollerbox.steps.python_step.PythonStep."""

from __future__ import annotations

from hollerbox.core.context import RunContext
from hollerbox.core.workflow import StepDefinition
from hollerbox.steps.python_step import PythonStep


def _run(code: str, *, inputs: dict | None = None, steps: dict | None = None):
    defn = StepDefinition(id="s", type="python_step", config={"code": code})
    step = PythonStep(defn)
    ctx = RunContext.new(inputs=inputs or {})
    if steps:
        for sid, payload in steps.items():
            ctx.record_step(sid, **payload)
    return step.run(ctx)


def test_basic_output_dict():
    r = _run("output = {'value': 42}")
    assert r.status == "success"
    assert r.output == {"value": 42}


def test_missing_output_yields_empty_dict():
    r = _run("x = 1")
    assert r.status == "success"
    assert r.output == {}


def test_access_inputs_directly():
    r = _run("output = {'doubled': inputs['n'] * 2}", inputs={"n": 21})
    assert r.status == "success"
    assert r.output == {"doubled": 42}


def test_access_prior_step_outputs():
    r = _run(
        "output = {'sum': sum(steps['s1']['output']['items'])}",
        steps={"s1": {"status": "success", "output": {"items": [1, 2, 3]}}},
    )
    assert r.output == {"sum": 6}


def test_stdout_captured_into_logs():
    r = _run("print('hello'); print('world'); output = {}")
    assert r.status == "success"
    assert "hello" in r.logs
    assert "world" in r.logs


def test_exception_marks_failed_and_includes_traceback():
    r = _run("raise ValueError('boom')")
    assert r.status == "failed"
    assert "boom" in (r.error or "")
    assert any("Traceback" in line for line in r.logs)


def test_non_dict_output_is_a_failure():
    r = _run("output = [1, 2, 3]")
    assert r.status == "failed"
    assert "must be a dict" in (r.error or "")


def test_template_inside_code_is_resolved_before_exec():
    defn = StepDefinition(
        id="s",
        type="python_step",
        config={"code": "output = {'greeting': '${inputs.who}'}"},
    )
    step = PythonStep(defn)
    ctx = RunContext.new(inputs={"who": "world"})
    r = step.run(ctx)
    assert r.output == {"greeting": "world"}
