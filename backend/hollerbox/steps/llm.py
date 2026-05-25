"""LlmStep — call a configured LLM provider.

The step picks a provider by name (config `provider`, falling back to
`settings.default_provider`, then `mock`). The provider dict lives on
the RunContext — the Runner populates it from its `providers=` kwarg
so the step never needs to know how the providers were constructed.

Output shape: `{text, model, provider}`. Free-form provider raw data is
deliberately NOT included because it tends to contain a lot of noise
(usage stats, headers); add it later if a real consumer needs it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from hollerbox.core.context import RunContext
from hollerbox.registry import register_step
from hollerbox.steps.base import Step, StepResult


class LlmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = None
    system: str | None = None
    prompt: str = Field(..., min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0, le=200_000)


@register_step
class LlmStep(Step):
    type = "llm"
    ConfigModel = LlmConfig

    def describe_effect(self, ctx: RunContext) -> str:
        cfg = self.resolve_config(ctx)
        prov = cfg.provider or ctx.settings.get("default_provider", "mock")
        model = cfg.model or "(provider default)"
        return f"llm {prov} model={model} max_tokens={cfg.max_tokens}"

    def run(self, ctx: RunContext) -> StepResult:
        cfg: LlmConfig = self.resolve_config(ctx)
        provider_name = cfg.provider or ctx.settings.get("default_provider", "mock")
        providers = ctx.providers or {}
        if provider_name not in providers:
            registered = sorted(providers) or "(none)"
            return StepResult.failed(
                error=(
                    f"llm step: provider {provider_name!r} not registered "
                    f"with the Runner. Registered: {registered}."
                ),
            )

        provider = providers[provider_name]
        try:
            completion = provider.complete(
                prompt=cfg.prompt,
                system=cfg.system,
                model=cfg.model,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 — surface provider errors as step failures
            return StepResult.failed(
                error=f"{type(exc).__name__}: {exc}",
                logs=[f"provider={provider_name} prompt_chars={len(cfg.prompt)}"],
            )

        return StepResult.success(
            output={
                "text": completion.text,
                "model": completion.model,
                "provider": provider_name,
            },
            logs=[
                f"{provider_name} {completion.model} -> {len(completion.text)} chars"
            ],
        )
