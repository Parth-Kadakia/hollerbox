"""Anthropic provider implementation.

Lazy import: the `anthropic` package is an optional extra (`uv sync --extra
llm`). Importing this module never imports the SDK; only constructing an
`AnthropicProvider` does. That keeps the engine package usable on a
machine with no LLM SDKs installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hollerbox.providers.base import Completion, Provider

if TYPE_CHECKING:
    pass


# Per the project guideline: default to the latest/most capable Claude
# model. Users override per-step via the workflow `model:` field.
DEFAULT_MODEL = "claude-opus-4-7"


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        default_model: str = DEFAULT_MODEL,
        client=None,  # for tests
    ) -> None:
        if not api_key:
            raise ValueError("AnthropicProvider requires a non-empty api_key.")
        self._default_model = default_model
        if client is not None:
            self._client = client
            return
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicProvider needs the `anthropic` package. "
                "Install with: uv sync --extra llm"
            ) from exc
        self._client = Anthropic(api_key=api_key)

    def complete(
        self,
        *,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> Completion:
        effective_model = model or self._default_model
        kwargs: dict = {
            "model": effective_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Newer Claude models (e.g. claude-opus-4-7) reject temperature
        # outright with "temperature is deprecated for this model". Only
        # include it when the caller explicitly asked for one.
        if temperature is not None:
            kwargs["temperature"] = temperature
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        # Anthropic responses come back as a list of content blocks; for a
        # plain text prompt we get one TextBlock. Defensive concat handles
        # the multi-block case without crashing.
        text_parts: list[str] = []
        for block in response.content:
            block_text = getattr(block, "text", None)
            if block_text is not None:
                text_parts.append(block_text)
        return Completion(text="".join(text_parts), model=effective_model)
