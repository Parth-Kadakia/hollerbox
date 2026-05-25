"""ImageStep — generate one or more images via an ImageProvider and save to disk.

Always destructive: `save_to` is required and the step always writes
file(s). The Runner treats it the same as write_file — dry-run records
intent without executing; chat-triggered runs auto-pause for approval.

For `n > 1`, files get a `_0`, `_1`, ... suffix inserted before the
extension (so `out.png` becomes `out_0.png`, `out_1.png`, ...).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from hollerbox.core.context import RunContext
from hollerbox.registry import register_step
from hollerbox.steps.base import Step, StepResult


class ImageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = None  # falls back to settings.default_image_provider
    model: str | None = None      # provider's default if None
    prompt: str = Field(..., min_length=1)
    size: str = "1024x1024"       # ignored by providers that don't accept it (Gemini)
    n: int = Field(default=1, ge=1, le=10)
    save_to: str = Field(..., min_length=1)


@register_step
class ImageStep(Step):
    type = "image"
    ConfigModel = ImageConfig
    default_destructive = True

    def describe_effect(self, ctx: RunContext) -> str:
        cfg = self.resolve_config(ctx)
        prov = cfg.provider or ctx.settings.get("default_image_provider", "openai")
        target = _resolve_path(cfg.save_to)
        plural = "s" if cfg.n > 1 else ""
        return f"image {prov} → {cfg.n} file{plural} like {target}"

    def run(self, ctx: RunContext) -> StepResult:
        cfg: ImageConfig = self.resolve_config(ctx)
        provider_name = cfg.provider or ctx.settings.get("default_image_provider", "openai")
        image_providers = ctx.image_providers or {}
        if provider_name not in image_providers:
            return StepResult.failed(
                error=(
                    f"image step: image provider {provider_name!r} not registered. "
                    f"Available: {sorted(image_providers) or '(none — set an API key first)'}"
                ),
            )

        provider = image_providers[provider_name]
        try:
            result = provider.generate(
                prompt=cfg.prompt,
                model=cfg.model,
                size=cfg.size,
                n=cfg.n,
            )
        except Exception as exc:  # noqa: BLE001 — surface upstream errors as step failures
            return StepResult.failed(error=f"{type(exc).__name__}: {exc}")

        if not result.images:
            return StepResult.failed(
                error=f"image provider {provider_name!r} returned 0 images",
            )

        paths = _write_images(_resolve_path(cfg.save_to), result.images)
        total_bytes = sum(len(b) for b in result.images)

        return StepResult.success(
            output={
                "paths": [str(p) for p in paths],
                "n": len(paths),
                "model": result.model,
                "provider": provider_name,
                "bytes_total": total_bytes,
            },
            logs=[
                f"{provider_name} {result.model} -> {len(paths)} image(s), {total_bytes} bytes",
                *[f"saved {p}" for p in paths],
            ],
        )


def _resolve_path(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def _write_images(base: Path, images: list[bytes]) -> list[Path]:
    """Write each image as bytes. Single image keeps the path as-is;
    multiple get a `_N` suffix inserted before the extension."""
    base.parent.mkdir(parents=True, exist_ok=True)
    if len(images) == 1:
        base.write_bytes(images[0])
        return [base]
    out: list[Path] = []
    stem = base.stem
    suffix = base.suffix or ".png"
    parent = base.parent
    for i, data in enumerate(images):
        target = parent / f"{stem}_{i}{suffix}"
        target.write_bytes(data)
        out.append(target)
    return out
