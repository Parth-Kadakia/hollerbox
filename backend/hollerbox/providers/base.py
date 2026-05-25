"""LLM provider abstraction.

Phase 1 ships only the `mock` provider so steps that depend on an LLM
(coming in Phase 2: the `llm` step; in Phase 5: the chat router) have a
fake to test against without making network calls. Real providers
(Anthropic, OpenAI, Ollama) implement this same ABC in Phase 2.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Completion:
    """The minimum useful return shape from a provider call."""

    text: str
    model: str
    raw: dict | None = None  # the provider's full response, if useful


class Provider(ABC):
    """Provider contract.

    Phase 1 keeps this *very* small. Phase 2 will extend with tool-use,
    streaming, structured output, etc.
    """

    name: str

    @abstractmethod
    def complete(
        self,
        *,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> Completion:
        """Synchronous text completion.

        `temperature=None` means "use the provider/model's own default" —
        implementations must NOT pass it to the upstream API in that case.
        Some newer Anthropic models (e.g. claude-opus-4-7) reject temperature
        entirely, so the safe default is to omit it unless explicitly set.
        """
