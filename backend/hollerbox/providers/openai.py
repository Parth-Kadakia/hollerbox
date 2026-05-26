"""OpenAI provider implementation.

Lazy import — see hollerbox/providers/anthropic.py for the rationale.
"""

from __future__ import annotations

import base64

from hollerbox.providers.base import Attachment, Completion, Provider

DEFAULT_MODEL = "gpt-4o-mini"

# Image MIME types the chat-completions API accepts as data URLs.
_VISION_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


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
        temperature: float | None = None,
        max_tokens: int = 1024,
        attachments: list[Attachment] | None = None,
    ) -> Completion:
        effective_model = model or self._default_model

        # Build the user message. When attachments are present, the
        # content becomes a list of parts (image + text). OpenAI chat
        # accepts images via data-URL `image_url`; PDFs/Excel are not
        # natively supported here — the LLM step has already extracted
        # their text into `prompt` for us.
        user_content: list[dict] | str
        image_parts: list[dict] = []
        for a in attachments or []:
            if a.media_type in _VISION_MEDIA_TYPES:
                b64 = base64.b64encode(a.data).decode("ascii")
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{a.media_type};base64,{b64}"},
                })
        user_content = (
            [*image_parts, {"type": "text", "text": prompt}] if image_parts else prompt
        )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})
        kwargs: dict = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = self._client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        return Completion(text=text, model=effective_model)
