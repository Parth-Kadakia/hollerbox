"""File I/O steps: read_file (non-destructive) and write_file (destructive)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hollerbox.core.context import RunContext
from hollerbox.registry import register_step
from hollerbox.steps.base import Step, StepResult


def _resolve_path(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


# --------------------------- read_file ---------------------------

class ReadFileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    encoding: str = "utf-8"


@register_step
class ReadFileStep(Step):
    type = "read_file"
    ConfigModel = ReadFileConfig

    def describe_effect(self, ctx: RunContext) -> str:
        cfg = self.resolve_config(ctx)
        return f"read {cfg.path}"

    def run(self, ctx: RunContext) -> StepResult:
        cfg: ReadFileConfig = self.resolve_config(ctx)
        path = _resolve_path(cfg.path)
        if not path.exists():
            return StepResult.failed(error=f"file does not exist: {path}")
        try:
            content = path.read_text(encoding=cfg.encoding)
        except OSError as exc:
            return StepResult.failed(error=f"read failed: {exc}")
        return StepResult.success(
            output={"path": str(path), "content": content, "size": len(content)},
            logs=[f"read {path} ({len(content)} chars)"],
        )


# --------------------------- write_file ---------------------------

WriteMode = Literal["overwrite", "append", "no_overwrite"]


class WriteFileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    content: str = ""
    encoding: str = "utf-8"
    mode: WriteMode = "overwrite"
    create_parents: bool = True


@register_step
class WriteFileStep(Step):
    type = "write_file"
    ConfigModel = WriteFileConfig
    default_destructive = True

    def describe_effect(self, ctx: RunContext) -> str:
        cfg = self.resolve_config(ctx)
        path = _resolve_path(cfg.path)
        size = len(cfg.content.encode(cfg.encoding))
        return f"would {cfg.mode} {size} bytes to {path}"

    def run(self, ctx: RunContext) -> StepResult:
        cfg: WriteFileConfig = self.resolve_config(ctx)
        path = _resolve_path(cfg.path)

        if cfg.mode == "no_overwrite" and path.exists():
            return StepResult.failed(error=f"refusing to overwrite existing file: {path}")

        if cfg.create_parents:
            path.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = cfg.content.encode(cfg.encoding)
            if cfg.mode == "append":
                with path.open("ab") as fh:
                    fh.write(data)
            else:
                # overwrite OR no_overwrite (we already confirmed it doesn't exist)
                with path.open("wb") as fh:
                    fh.write(data)
        except OSError as exc:
            return StepResult.failed(error=f"write failed: {exc}")

        return StepResult.success(
            output={"path": str(path), "bytes_written": len(data)},
            logs=[f"{cfg.mode} {len(data)} bytes -> {path}"],
        )
