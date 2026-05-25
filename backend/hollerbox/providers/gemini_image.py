"""Gemini image-generation provider.

Uses the `google-genai` SDK. Default model is the Nano Banana image
model. The SDK returns multimodal `Part`s — we walk them, collect every
inline_data blob (image), discard text-only parts.

We loop client-side for `n > 1` so callers get a consistent semantic
across providers (Gemini's image endpoint returns one image per call).
"""

from __future__ import annotations

from hollerbox.providers.image_base import ImageProvider, ImageResult

DEFAULT_MODEL = "gemini-3.1-flash-image-preview"


class GeminiImageProvider(ImageProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        default_model: str = DEFAULT_MODEL,
        client=None,  # for tests
    ) -> None:
        if not api_key:
            raise ValueError("GeminiImageProvider requires a non-empty api_key.")
        self._default_model = default_model
        if client is not None:
            self._client = client
            return
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "GeminiImageProvider needs the `google-genai` package. "
                "Install with: uv sync --extra llm"
            ) from exc
        self._client = genai.Client(api_key=api_key)

    def generate(
        self,
        *,
        prompt: str,
        model: str | None = None,
        size: str = "1024x1024",  # Gemini's image API ignores this; kept for API parity
        n: int = 1,
    ) -> ImageResult:
        effective_model = model or self._default_model
        images: list[bytes] = []
        for _ in range(n):
            response = self._client.models.generate_content(
                model=effective_model,
                contents=[prompt],
            )
            for part in _iter_parts(response):
                inline = getattr(part, "inline_data", None)
                if inline is not None:
                    data = getattr(inline, "data", None)
                    if data is not None:
                        images.append(_as_bytes(data))
        return ImageResult(images=images, model=effective_model, raw=None)


def _iter_parts(response):
    """Walk every part of a Gemini response, accommodating both the
    top-level `.parts` shortcut and the longer `.candidates[*].content.parts`
    path — different SDK versions expose different shapes."""
    parts = getattr(response, "parts", None)
    if parts is not None:
        yield from parts
        return
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        yield from getattr(content, "parts", []) or []


def _as_bytes(data) -> bytes:
    """SDK sometimes hands back `bytes`, sometimes a base64 `str`."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        import base64

        return base64.b64decode(data)
    raise TypeError(f"unexpected inline_data type from Gemini SDK: {type(data).__name__}")
