"""LLM provider abstraction + implementations.

Phase 2 adds anthropic / openai / ollama alongside the `mock` provider
from Phase 1d. The real-provider modules use lazy SDK imports so this
package stays importable on machines without the optional `[llm]`
dependencies installed.
"""

from hollerbox.providers.anthropic import AnthropicProvider
from hollerbox.providers.base import Completion, Provider
from hollerbox.providers.mock import MockProvider
from hollerbox.providers.ollama import OllamaProvider
from hollerbox.providers.openai import OpenAIProvider

__all__ = [
    "AnthropicProvider",
    "Completion",
    "MockProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "Provider",
]
