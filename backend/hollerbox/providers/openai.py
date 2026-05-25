"""OpenAI provider implementation.

Lazy import — see hollerbox/providers/anthropic.py for the rationale.
"""

from __future__ import annotations

from hollerbox.providers.base import Completion, Provider

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        default_model: str = DEFAULT_MODEL,
        client=None,  # for tests
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIProvider requires a non-empty api_key.")
        self._default_model = default_model
        if client is not None:
            self._client = client
            return
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIProvider needs the `openai` package. "
                "Install with: uv sync --extra llm"
            ) from exc
        self._client = OpenAI(api_key=api_key)

    def complete(
        self,
        *,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> Completion:
        effective_model = model or self._default_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._client.chat.completions.create(
            model=effective_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        return Completion(text=text, model=effective_model)
