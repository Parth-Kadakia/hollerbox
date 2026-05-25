"""RunContext — the shared state passed through every step of a single run.

Mutable during the run (each step's output is recorded into `steps`), then
snapshot to the database after each step so the run is resumable on crash
or approval pause.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from hollerbox.core import templating
from hollerbox.core.templating import ResolverScope

if TYPE_CHECKING:
    from hollerbox.providers.base import Provider


@dataclass
class RunContext:
    inputs: dict[str, Any]
    secrets: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    run: dict[str, Any] = field(default_factory=dict)
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    providers: dict[str, Provider] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        *,
        inputs: dict[str, Any] | None = None,
        secrets: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        run_id: str | None = None,
        providers: dict[str, Provider] | None = None,
    ) -> RunContext:
        now = datetime.now(UTC)
        run = {
            "id": run_id or uuid.uuid4().hex,
            "date": now.date().isoformat(),
            "timestamp": now.isoformat(),
        }
        return cls(
            inputs=dict(inputs or {}),
            secrets=dict(secrets or {}),
            settings=dict(settings or {}),
            run=run,
            providers=dict(providers or {}),
        )

    def _scope(self) -> ResolverScope:
        return ResolverScope(
            inputs=self.inputs,
            steps=self.steps,
            secrets=self.secrets,
            settings=self.settings,
            run=self.run,
        )

    def resolve(self, value: Any) -> Any:
        """Resolve templates with real values — for execution."""
        return templating.resolve(value, self._scope(), redact_secrets=False)

    def resolve_redacted(self, value: Any) -> Any:
        """Resolve templates with secrets blanked — for logs / persistence."""
        return templating.resolve(value, self._scope(), redact_secrets=True)

    def record_step(
        self,
        step_id: str,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        logs: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        self.steps[step_id] = {
            "status": status,
            "output": output or {},
            "logs": logs or [],
            "error": error,
        }

    def snapshot(self) -> dict[str, Any]:
        """Snapshot the context for persistence.

        Excludes `secrets` entirely. Anything in `inputs` / `steps` that came
        from a `${secrets.*}` template should already have been resolved with
        `resolve_redacted()` before being recorded — secrets never enter here.
        """
        return {
            "inputs": self.inputs,
            "steps": self.steps,
            "settings": self.settings,
            "run": self.run,
        }
