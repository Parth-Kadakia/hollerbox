"""Step ABC + StepResult.

Every step implementation in `hollerbox/steps/` subclasses `Step`. The
contract is small on purpose:

- declare a `type` (registry key) and a `ConfigModel` (pydantic schema for
  the step's config dict)
- implement `run(ctx)` returning a `StepResult`
- override `describe_effect(ctx)` to power dry-run / chat previews
- if the step inherently mutates the world, set `default_destructive = True`
  so the YAML doesn't have to remember to mark every instance

Template resolution against the run context happens in `resolve_config()`
(called by `run()` implementations) so the Step receives a fully-resolved,
pydantic-validated config it can act on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from hollerbox.core.context import RunContext
from hollerbox.core.workflow import StepDefinition

StepStatus = Literal["success", "failed", "skipped", "dry_run", "pending_approval"]


class StepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StepStatus
    output: dict[str, Any] = {}
    logs: list[str] = []
    error: str | None = None

    @classmethod
    def success(cls, output: dict[str, Any] | None = None, logs: list[str] | None = None) -> StepResult:
        return cls(status="success", output=output or {}, logs=logs or [])

    @classmethod
    def failed(cls, error: str, logs: list[str] | None = None) -> StepResult:
        return cls(status="failed", output={}, logs=logs or [], error=error)

    @classmethod
    def dry_run(cls, description: str) -> StepResult:
        return cls(status="dry_run", output={}, logs=[description])

    @classmethod
    def pending_approval(cls, description: str) -> StepResult:
        return cls(status="pending_approval", output={}, logs=[description])


ConfigT = TypeVar("ConfigT", bound=BaseModel)


class Step(ABC):
    """Base class for all step types."""

    type: ClassVar[str]
    ConfigModel: ClassVar[type[BaseModel]]

    # If True, this step type is always treated as destructive (skipped in
    # dry-run, requires approval in chat-triggered runs) regardless of what
    # the YAML says. The YAML `destructive: true` flag can ADD destructive
    # behavior on a per-step basis but cannot remove it.
    default_destructive: ClassVar[bool] = False

    def __init__(self, definition: StepDefinition) -> None:
        if not getattr(self, "type", None):
            raise TypeError(f"{type(self).__name__} must declare a class-level `type`.")
        if not getattr(self, "ConfigModel", None):
            raise TypeError(f"{type(self).__name__} must declare a class-level `ConfigModel`.")
        if definition.type != self.type:
            raise ValueError(
                f"Step definition type '{definition.type}' does not match "
                f"step class type '{self.type}'."
            )
        self.definition = definition

    @property
    def is_destructive(self) -> bool:
        return self.definition.destructive or type(self).default_destructive

    def resolve_config(self, ctx: RunContext) -> Any:
        """Resolve templates in the raw config dict, then validate as ConfigModel."""
        resolved = ctx.resolve(self.definition.config)
        return self.ConfigModel.model_validate(resolved)

    @abstractmethod
    def run(self, ctx: RunContext) -> StepResult:
        """Execute the step. Implementations should call resolve_config(ctx)."""

    def describe_effect(self, ctx: RunContext) -> str:
        """Human-readable preview of what the step will do (for dry-run / chat)."""
        return f"{self.definition.id} ({self.type})"
