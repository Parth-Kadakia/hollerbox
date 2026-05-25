"""Tests for hollerbox.registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from hollerbox import registry
from hollerbox.steps.base import Step, StepResult


class _DummyConfig(BaseModel):
    pass


def _make_step_class(type_name: str) -> type[Step]:
    class _Dummy(Step):
        type = type_name
        ConfigModel = _DummyConfig

        def run(self, ctx):
            return StepResult.success()

    _Dummy.__name__ = f"_Dummy_{type_name}"
    return _Dummy


def test_register_then_lookup():
    cls = _make_step_class("test_register_then_lookup_step")
    registry.register_step(cls)
    try:
        assert registry.get_step_class("test_register_then_lookup_step") is cls
        assert "test_register_then_lookup_step" in registry.registered_step_types()
    finally:
        registry._STEPS.pop("test_register_then_lookup_step", None)


def test_duplicate_registration_rejected():
    cls_a = _make_step_class("test_dup_step")
    cls_b = _make_step_class("test_dup_step")
    registry.register_step(cls_a)
    try:
        with pytest.raises(ValueError, match="already registered"):
            registry.register_step(cls_b)
    finally:
        registry._STEPS.pop("test_dup_step", None)


def test_same_class_re_register_is_noop():
    cls = _make_step_class("test_idempotent_step")
    registry.register_step(cls)
    try:
        # Re-registering the exact same class should not raise.
        registry.register_step(cls)
        assert registry.get_step_class("test_idempotent_step") is cls
    finally:
        registry._STEPS.pop("test_idempotent_step", None)


def test_unknown_step_lookup_raises():
    with pytest.raises(KeyError, match="Unknown step type"):
        registry.get_step_class("definitely_not_a_real_step_type")


def test_register_step_without_type_attr_rejected():
    class _NoType(Step):
        ConfigModel = _DummyConfig

        def run(self, ctx):
            return StepResult.success()

    with pytest.raises(ValueError, match="missing class-level `type`"):
        registry.register_step(_NoType)


def test_builtin_steps_registered():
    # Just confirm the side-effect import in hollerbox.steps.__init__ took.
    import hollerbox.steps  # noqa: F401

    for expected in ("shell", "python_step", "http", "read_file", "write_file"):
        assert expected in registry.registered_step_types(), expected
