"""Workflow / Step pydantic models + YAML loader.

The YAML format (see docs/BUILD_BRIEF.md §4) is parsed here into typed
pydantic models. Step-type-specific config is left as a free-form `dict` at
this layer — the Step class for each `type` validates its own config when
the Runner instantiates it (Phase 1b).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Step ids must be plain identifiers so they can be safely used in
# `${steps.<id>.output.*}` references.
_STEP_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class Trigger(BaseModel):
    """When a workflow runs unattended. Currently just cron; interval/etc. later."""

    model_config = ConfigDict(extra="forbid")

    cron: str | None = None


class StepDefinition(BaseModel):
    """One step in a workflow, as written in YAML.

    `config` is intentionally free-form here; each step type validates its
    own `config` shape when constructed from the registry.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)

    # Behavior flags
    destructive: bool = False
    requires_confirmation: bool = False

    # Error policy (per-step)
    on_error: Literal["stop", "continue", "retry"] = "stop"
    max_attempts: int = Field(default=1, ge=1)
    backoff_seconds: float = Field(default=0.0, ge=0.0)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not _STEP_ID_RE.match(v):
            raise ValueError(
                f"Invalid step id '{v}': must match {_STEP_ID_RE.pattern} "
                "(letters, digits, underscore; must start with letter or underscore)."
            )
        return v

    @model_validator(mode="after")
    def _retry_requires_max_attempts(self) -> StepDefinition:
        if self.on_error == "retry" and self.max_attempts < 2:
            raise ValueError(
                f"Step '{self.id}': on_error=retry requires max_attempts >= 2."
            )
        return self


class Workflow(BaseModel):
    """A complete workflow definition, validated."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: int = 1
    description: str = ""
    chat_examples: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    trigger: Trigger | None = None
    steps: list[StepDefinition]

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Workflow name must be non-empty.")
        return v

    @field_validator("steps")
    @classmethod
    def _non_empty_steps(cls, v: list[StepDefinition]) -> list[StepDefinition]:
        if not v:
            raise ValueError("Workflow must have at least one step.")
        return v

    @model_validator(mode="after")
    def _unique_step_ids(self) -> Workflow:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"Duplicate step id: '{step.id}'.")
            seen.add(step.id)
        return self


class WorkflowLoadError(Exception):
    """Raised when a workflow YAML file fails to load or validate.

    Wraps the underlying error so callers (CLI, API) can present a clean
    message without leaking pydantic/yaml internals.
    """

    def __init__(self, path: Path, message: str, cause: Exception | None = None):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message
        self.cause = cause


def load_workflow(path: str | Path) -> Workflow:
    """Load and validate a single workflow YAML file."""
    p = Path(path)
    if not p.exists():
        raise WorkflowLoadError(p, "file does not exist")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkflowLoadError(p, f"YAML parse error: {exc}", cause=exc) from exc

    if raw is None:
        raise WorkflowLoadError(p, "file is empty")
    if not isinstance(raw, dict):
        raise WorkflowLoadError(
            p, f"top-level YAML must be a mapping (got {type(raw).__name__})"
        )

    try:
        return Workflow.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError or related
        raise WorkflowLoadError(p, f"schema validation failed: {exc}", cause=exc) from exc


def load_workflows_dir(path: str | Path) -> dict[str, Workflow]:
    """Load every `*.yaml` / `*.yml` file under `path` (non-recursive).

    Returns a dict keyed by workflow name. Raises on the first failure.
    """
    p = Path(path)
    if not p.is_dir():
        raise WorkflowLoadError(p, "not a directory")
    out: dict[str, Workflow] = {}
    for entry in sorted(p.iterdir()):
        if entry.suffix.lower() not in {".yaml", ".yml"}:
            continue
        wf = load_workflow(entry)
        if wf.name in out:
            raise WorkflowLoadError(
                entry,
                f"duplicate workflow name '{wf.name}' (also defined in another file)",
            )
        out[wf.name] = wf
    return out
