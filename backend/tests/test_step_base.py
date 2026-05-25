"""Tests for hollerbox.steps.base (Step ABC + StepResult)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from hollerbox.core.context import RunContext
from hollerbox.core.workflow import StepDefinition
from hollerbox.steps.base import Step, StepResult


class _Cfg(BaseModel):
    value: str


class _Echo(Step):
    type = "_echo"
    ConfigModel = _Cfg

    def run(self, ctx):
        cfg: _Cfg = self.resolve_config(ctx)
        return StepResult.success(output={"value": cfg.value})


class _DestructiveEcho(Step):
    type = "_destructive_echo"
    ConfigModel = _Cfg
    default_destructive = True

    def run(self, ctx):
        return StepResult.success()


class TestStepResultHelpers:
    def test_success_default_fields(self):
        r = StepResult.success()
        assert r.status == "success"
        assert r.output == {}
        assert r.logs == []
        assert r.error is None

    def test_failed_carries_error(self):
        r = StepResult.failed("boom")
        assert r.status == "failed"
        assert r.error == "boom"

    def test_dry_run_puts_description_in_logs(self):
        r = StepResult.dry_run("would delete X")
        assert r.status == "dry_run"
        assert r.logs == ["would delete X"]

    def test_pending_approval(self):
        r = StepResult.pending_approval("about to delete X")
        assert r.status == "pending_approval"

    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError):
            StepResult(status="weird", output={}, logs=[])


class TestStepConstructor:
    def test_type_mismatch_rejected(self):
        defn = StepDefinition(id="s", type="other", config={"value": "x"})
        with pytest.raises(ValueError, match="does not match"):
            _Echo(defn)

    def test_resolve_config_uses_ctx(self):
        defn = StepDefinition(id="s", type="_echo", config={"value": "${inputs.x}"})
        step = _Echo(defn)
        ctx = RunContext.new(inputs={"x": "resolved"})
        cfg = step.resolve_config(ctx)
        assert cfg.value == "resolved"

    def test_resolve_config_validates_against_model(self):
        # _Cfg.value is `str`; pydantic v2 does NOT coerce int -> str by
        # default, so this must raise a ValidationError. That's the contract:
        # whatever the templates resolve to has to match the ConfigModel.
        defn = StepDefinition(id="s", type="_echo", config={"value": 42})
        step = _Echo(defn)
        ctx = RunContext.new(inputs={})
        with pytest.raises(Exception) as exc:
            step.resolve_config(ctx)
        assert "string_type" in str(exc.value) or "Input should be a valid string" in str(exc.value)


class TestDestructive:
    def test_default_false(self):
        defn = StepDefinition(id="s", type="_echo", config={"value": "x"})
        assert _Echo(defn).is_destructive is False

    def test_yaml_destructive_true(self):
        defn = StepDefinition(
            id="s", type="_echo", config={"value": "x"}, destructive=True
        )
        assert _Echo(defn).is_destructive is True

    def test_class_default_destructive_true(self):
        defn = StepDefinition(id="s", type="_destructive_echo", config={"value": "x"})
        assert _DestructiveEcho(defn).is_destructive is True

    def test_class_default_cannot_be_disabled_via_yaml(self):
        # YAML can elevate but not demote: a class flagged default_destructive=True
        # stays destructive even if the YAML omits the flag.
        defn = StepDefinition(
            id="s", type="_destructive_echo", config={"value": "x"}, destructive=False
        )
        assert _DestructiveEcho(defn).is_destructive is True
