"""Registry mapping step `type` strings to Step implementation classes.

The Runner looks up `definition.type` here to instantiate the right Step.
Each step module registers its class at import time via `@register_step`.
Importing `hollerbox.steps` triggers registration of all built-in steps.

Note on imports: this module deliberately does NOT import `Step` at runtime.
The `hollerbox.steps` package's `__init__.py` imports every step module to
trigger registration, and each step module imports `register_step` from
here — so a runtime import of `Step` would create a circular dependency.
The TYPE_CHECKING import gives us the type hint without the cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from hollerbox.steps.base import Step

StepT = TypeVar("StepT", bound="type[Step]")

_STEPS: dict[str, type[Step]] = {}


def register_step(cls: StepT) -> StepT:
    """Decorator: register a Step subclass under its `type` key."""
    type_ = getattr(cls, "type", None)
    if not type_:
        raise ValueError(
            f"Cannot register {cls.__name__}: missing class-level `type` attribute."
        )
    if type_ in _STEPS and _STEPS[type_] is not cls:
        raise ValueError(
            f"Step type '{type_}' already registered to {_STEPS[type_].__name__}; "
            f"refusing to overwrite with {cls.__name__}."
        )
    _STEPS[type_] = cls
    return cls


def get_step_class(type_: str) -> type[Step]:
    if type_ not in _STEPS:
        raise KeyError(
            f"Unknown step type '{type_}'. Registered: {sorted(_STEPS)!r}"
        )
    return _STEPS[type_]


def registered_step_types() -> list[str]:
    return sorted(_STEPS)


def clear_registry() -> None:
    """Test helper. Do NOT call in production code."""
    _STEPS.clear()
