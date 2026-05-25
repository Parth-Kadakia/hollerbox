"""LLM provider abstraction + implementations.

Phase 1 ships `mock` only. Phase 2 adds anthropic/openai/ollama.
"""

from hollerbox.providers.base import Completion, Provider
from hollerbox.providers.mock import MockProvider

__all__ = ["Completion", "Provider", "MockProvider"]
