"""LlmStep — call a configured LLM provider, optionally with attachments.

The step picks a provider by name (config `provider`, falling back to
`settings.default_provider`, then `mock`). The provider dict lives on
the RunContext — the Runner populates it from its `providers=` kwarg
so the step never needs to know how the providers were constructed.

`attachments` are file paths (resolved via `${inputs.file_path}` etc.).
The step extracts each file: images/PDFs go straight to the provider
as bytes; spreadsheets / CSVs / text files get extracted locally and
folded into the prompt as quoted text so the model can read them.

Output shape: `{text, model, provider}`. Free-form provider raw data is
deliberately NOT included because it tends to contain a lot of noise
(usage stats, headers); add it later if a real consumer needs it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from hollerbox.core.context import RunContext
from hollerbox.core.file_extract import extract
from hollerbox.providers.base import Attachment
from hollerbox.registry import register_step
from hollerbox.steps.base import Step, StepResult


class LlmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = None
    system: str | None = None
    prompt: str = Field(..., min_length=1)
    # `temperature=None` (the default) tells the provider to omit it from
    # the API call so the upstream model picks its own default. Some
    # newer Claude models reject `temperature` outright, so unset > 0.0.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0, le=200_000)
    # Paths to files the LLM should see. Images go through as multimodal
    # blocks for providers that support vision; PDFs go natively to
    # providers that take them, otherwise extracted text. Spreadsheets,
    # CSVs, and plain text are merged into the prompt as quoted blobs.
    attachments: list[str] = Field(default_factory=list)


@register_step
class LlmStep(Step):
    type = "llm"
    ConfigModel = LlmConfig

    def describe_effect(self, ctx: RunContext) -> str:
        cfg = self.resolve_config(ctx)
        prov = cfg.provider or ctx.settings.get("default_provider", "mock")
        model = cfg.model or "(provider default)"
        atts = f" + {len(cfg.attachments)} file(s)" if cfg.attachments else ""
        return f"llm {prov} model={model} max_tokens={cfg.max_tokens}{atts}"

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

        # Resolve attachments → either native (image/PDF bytes) or text
        # to prepend to the prompt.
        native: list[Attachment] = []
        text_chunks: list[str] = []
        extract_logs: list[str] = []
        for raw_path in cfg.attachments:
            res = extract(raw_path)
            if res.error and res.native_attachment is None and res.extracted_text is None:
                # Surface to the model so it can say "I couldn't open X"
                text_chunks.append(f"[attachment {res.name!r} could not be read: {res.error}]")
                extract_logs.append(f"skip {res.name}: {res.error}")
                continue
            if res.native_attachment is not None:
                native.append(res.native_attachment)
                extract_logs.append(f"native {res.name} ({res.media_type})")
            if res.extracted_text:
                preview = f"\n[file: {res.name}]\n{res.extracted_text}\n[/file]"
                text_chunks.append(preview)
                extract_logs.append(
                    f"extracted {res.name}: {len(res.extracted_text)} chars"
                )

        prompt = cfg.prompt
        if text_chunks:
            prompt = prompt + "\n\n" + "\n\n".join(text_chunks)

        provider = providers[provider_name]
        try:
            completion = provider.complete(
                prompt=prompt,
                system=cfg.system,
                model=cfg.model,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                attachments=native or None,
            )
        except Exception as exc:  # noqa: BLE001 — surface provider errors as step failures
            return StepResult.failed(
                error=f"{type(exc).__name__}: {exc}",
                logs=[f"provider={provider_name} prompt_chars={len(prompt)}", *extract_logs],
            )

        return StepResult.success(
            output={
                "text": completion.text,
                "model": completion.model,
                "provider": provider_name,
            },
            logs=[
                f"{provider_name} {completion.model} -> {len(completion.text)} chars",
                *extract_logs,
            ],
        )
