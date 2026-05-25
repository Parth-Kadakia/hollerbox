"""PythonStep — exec a snippet of Python with access to the run context.

The snippet runs in a controlled scope:
- `ctx` is the current RunContext (read-only by convention; we don't enforce
  it — this step type is "execute arbitrary code by design")
- `inputs`, `steps`, `settings`, `run` mirror the namespaces from the
  templating engine for ergonomic access (`inputs["topic"]` rather than
  `ctx.inputs["topic"]`)
- Set the local variable `output = {...}` to populate the step output.
  Anything else is discarded.

stdout/stderr from the snippet is captured into the step's logs.
"""

from __future__ import annotations

import contextlib
import io
import traceback
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hollerbox.core.context import RunContext
from hollerbox.registry import register_step
from hollerbox.steps.base import Step, StepResult


class PythonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, description="Inline Python source to exec.")


@register_step
class PythonStep(Step):
    type = "python_step"
    ConfigModel = PythonConfig

    def describe_effect(self, ctx: RunContext) -> str:
        cfg = self.resolve_config(ctx)
        first_line = cfg.code.strip().splitlines()[0] if cfg.code.strip() else ""
        return f"python `{first_line[:60]}`" + (" …" if len(first_line) > 60 else "")

    def run(self, ctx: RunContext) -> StepResult:
        cfg: PythonConfig = self.resolve_config(ctx)

        scope: dict[str, Any] = {
            "ctx": ctx,
            "inputs": ctx.inputs,
            "steps": ctx.steps,
            "settings": ctx.settings,
            "run": ctx.run,
            "output": {},
        }

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(cfg.code, scope)  # noqa: S102 — exec is the entire point
        except (Exception, SystemExit) as exc:
            # Catch SystemExit explicitly so user snippets that call sys.exit()
            # or raise SystemExit fail the step instead of killing the host.
            # We don't catch KeyboardInterrupt — that's a deliberate human signal.
            logs = _drain_logs(stdout_buf, stderr_buf)
            logs.append(traceback.format_exc().rstrip())
            return StepResult.failed(error=f"{type(exc).__name__}: {exc}", logs=logs)

        output = scope.get("output", {})
        if not isinstance(output, dict):
            return StepResult.failed(
                error=f"python_step `output` must be a dict, got {type(output).__name__}",
                logs=_drain_logs(stdout_buf, stderr_buf),
            )

        return StepResult.success(output=output, logs=_drain_logs(stdout_buf, stderr_buf))


def _drain_logs(stdout_buf: io.StringIO, stderr_buf: io.StringIO) -> list[str]:
    logs: list[str] = []
    out = stdout_buf.getvalue()
    err = stderr_buf.getvalue()
    if out:
        logs.append("stdout:")
        logs.extend(out.rstrip("\n").splitlines())
    if err:
        logs.append("stderr:")
        logs.extend(err.rstrip("\n").splitlines())
    return logs
