"""Ollama provider — talks to a local Ollama HTTP API via httpx.

No SDK dependency: Ollama's REST surface is small and stable enough that
a few httpx calls are simpler than an SDK wrapper. Default host
`http://localhost:11434` matches Ollama's out-of-the-box defaults.
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from hollerbox.providers.base import Completion, Provider

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"


class OllamaProvider(Provider):
    name = "ollama"

    # Test seam (same pattern as HttpStep) — set a MockTransport to avoid
    # any real network during the test suite.
    _TRANSPORT: ClassVar[httpx.BaseTransport | None] = None

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        default_model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
    ) -> None:
        self._host = host.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout

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
        payload: dict = {
            "model": effective_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        client_kwargs: dict = {"timeout": self._timeout}
        transport = type(self)._TRANSPORT
        if transport is not None:
            client_kwargs["transport"] = transport

        with httpx.Client(**client_kwargs) as client:
            response = client.post(f"{self._host}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

        return Completion(
            text=data.get("response", ""),
            model=effective_model,
            raw=data,
        )
