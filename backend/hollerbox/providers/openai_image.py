"""OpenAI image-generation provider.

Uses the same `openai` SDK as the text OpenAIProvider but talks to
`client.images.generate(...)`. Defaults to `gpt-image-1` because that's
the broadly-available image model; per-step `model: gpt-image-2` (or
`dall-e-3`) overrides this if your account has access.

Some OpenAI image models cap `n` at 1 per request (gpt-image-1,
dall-e-3); we loop client-side to honor the caller's `n`.
"""

from __future__ import annotations

import base64

from hollerbox.providers.image_base import ImageProvider, ImageResult

DEFAULT_MODEL = "gpt-image-1"


class OpenAIImageProvider(ImageProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        default_model: str = DEFAULT_MODEL,
        client=None,  # for tests
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIImageProvider requires a non-empty api_key.")
        self._default_model = default_model
        if client is not None:
            self._client = client
            return
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIImageProvider needs the `openai` package. "
                "Install with: uv sync --extra llm"
            ) from exc
        self._client = OpenAI(api_key=api_key)

    def generate(
        self,
        *,
        prompt: str,
        model: str | None = None,
        size: str = "1024x1024",
        n: int = 1,
    ) -> ImageResult:
        effective_model = model or self._default_model
        images: list[bytes] = []
        last_raw: dict | None = None
        # OpenAI's newer image models cap n=1 per request — loop here so
        # callers get a consistent `n` semantic across providers.
        for _ in range(n):
            response = self._client.images.generate(
                model=effective_model,
                prompt=prompt,
                size=size,
                n=1,
            )
            # response.data[0].b64_json — always base64 PNG for gpt-image-*.
            datum = response.data[0]
            b64 = getattr(datum, "b64_json", None)
            if b64 is None:
                # Some older models return URLs instead. Skip — image step
                # validates output and will fail cleanly.
                continue
            images.append(base64.b64decode(b64))
            last_raw = {
                "revised_prompt": getattr(datum, "revised_prompt", None),
            }
        return ImageResult(images=images, model=effective_model, raw=last_raw)
