"""ShellStep — run an arbitrary shell command via subprocess.

Inherently powerful; the README (§10) calls this out as one of two step
types that execute arbitrary local code. A future hosted build will hide
this behind a settings toggle.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from hollerbox.core.context import RunContext
from hollerbox.registry import register_step
from hollerbox.steps.base import Step, StepResult


class ShellConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(..., min_length=1)
    cwd: str | None = None
    timeout: float = Field(default=60.0, gt=0.0)
    env: dict[str, str] | None = None
    check: bool = Field(
        default=True,
        description="If True (default), non-zero exit code becomes a failed step.",
    )


@register_step
class ShellStep(Step):
    type = "shell"
    ConfigModel = ShellConfig

    def describe_effect(self, ctx: RunContext) -> str:
        cfg = self.resolve_config(ctx)
        return f"shell `{cfg.command}`" + (f" in {cfg.cwd}" if cfg.cwd else "")

    def run(self, ctx: RunContext) -> StepResult:
        cfg: ShellConfig = self.resolve_config(ctx)
        cwd = str(Path(cfg.cwd).expanduser().resolve()) if cfg.cwd else None
        try:
            completed = subprocess.run(  # noqa: S602 — running user-defined commands is the point
                cfg.command,
                shell=True,
                cwd=cwd,
                env=cfg.env,
                timeout=cfg.timeout,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            return StepResult.failed(
                error=f"shell command timed out after {cfg.timeout}s",
                logs=[f"$ {cfg.command}"],
            )
        except FileNotFoundError as exc:  # bad cwd, etc.
            return StepResult.failed(error=str(exc), logs=[f"$ {cfg.command}"])

        output = {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        logs = [f"$ {cfg.command}", f"exit {completed.returncode}"]
        # Bring captured streams into the logs (capped) so `run-detail`
        # surfaces real output without dumping unbounded text.
        max_lines = 40
        if completed.stdout:
            stdout_lines = completed.stdout.rstrip("\n").splitlines()
            logs.append("stdout:")
            logs.extend(stdout_lines[:max_lines])
            if len(stdout_lines) > max_lines:
                logs.append(f"  ... ({len(stdout_lines) - max_lines} more lines)")
        if completed.stderr:
            stderr_lines = completed.stderr.rstrip("\n").splitlines()
            logs.append("stderr:")
            logs.extend(stderr_lines[:max_lines])
            if len(stderr_lines) > max_lines:
                logs.append(f"  ... ({len(stderr_lines) - max_lines} more lines)")
        if cfg.check and completed.returncode != 0:
            return StepResult(
                status="failed",
                output=output,
                logs=logs,
                error=f"command exited with status {completed.returncode}",
            )
        return StepResult.success(output=output, logs=logs)
