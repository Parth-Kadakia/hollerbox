"""ImageProvider ABC + ImageResult.

Image generation is intentionally separated from the text `Provider`
abstraction — the surfaces have almost nothing in common (returns raw
bytes vs. text, takes size / n / quality vs. temperature / max_tokens).
A single `ctx.image_providers` dict on the RunContext, populated by the
Runner from its constructor kwarg, is how the `image` step finds them.

Each concrete provider:
- declares a `name` (the registry key the workflow YAML will reference)
- implements `generate()` returning an `ImageResult` of raw PNG/JPEG bytes
- uses lazy SDK imports so the package stays importable on machines
  without the optional `[llm]` extras
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ImageResult:
    """One generation call's output. Multiple images = multiple `images` entries."""

    images: list[bytes] = field(default_factory=list)
    model: str = ""
    # Optional provider-specific extras (revised prompt, safety flags, usage).
    # Persisted into step output so a workflow author can inspect them.
    raw: dict | None = None


class ImageProvider(ABC):
    """Image-generation provider contract.

    Kept minimal on purpose: prompt + size + n. Provider-specific
    parameters (OpenAI's `quality`, Gemini's response modalities) are the
    implementations' problem, not the abstraction's.
    """

    name: str

    @abstractmethod
    def generate(
        self,
        *,
        prompt: str,
        model: str | None = None,
        size: str = "1024x1024",
        n: int = 1,
    ) -> ImageResult:
        """Generate `n` images. Returns raw bytes per image."""
