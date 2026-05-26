"""Ollama provider — talks to a local Ollama HTTP API via httpx.

No SDK dependency: Ollama's REST surface is small and stable enough that
a few httpx calls are simpler than an SDK wrapper. Default host
`http://localhost:11434` matches Ollama's out-of-the-box defaults.
"""

from __future__ import annotations

from typing import ClassVar

import httpx

from hollerbox.providers.base import Attachment, Completion, Provider

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
        # Cached so we don't hit /api/tags on every completion. Cleared
        # via `clear_model_cache()` if the user pulls a new model and
        # wants it picked up without a restart.
        self._installed_models: list[str] | None = None

    def _client(self) -> httpx.Client:
        kwargs: dict = {"timeout": self._timeout}
        t = type(self)._TRANSPORT
        if t is not None:
            kwargs["transport"] = t
        return httpx.Client(**kwargs)

    def list_models(self, *, force_refresh: bool = False) -> list[str]:
        """Return the names of models pulled in the local Ollama instance.

        Result is cached after the first successful call. Returns an empty
        list if Ollama isn't reachable, the response is malformed, or any
        other failure — `complete()` will then fall back to the configured
        default and let Ollama itself surface the clearest error.
        """
        if self._installed_models is not None and not force_refresh:
            return self._installed_models
        try:
            with self._client() as client:
                resp = client.get(f"{self._host}/api/tags")
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001 — listing is best-effort
            return []
        try:
            names = [
                m.get("name")
                for m in data.get("models", [])
                if isinstance(m.get("name"), str)
            ]
        except (AttributeError, TypeError):
            return []
        self._installed_models = sorted(names)
        return self._installed_models

    def clear_model_cache(self) -> None:
        self._installed_models = None

    def _pick_default_model(self) -> str:
        """Pick the model used when caller passes `model=None`.

        Preference: the configured `default_model` if it's installed,
        otherwise the first model `/api/tags` reports, otherwise the
        configured default (which will 404 — but the error from Ollama
        is clearer than a silent fallback).
        """
        installed = self.list_models()
        if not installed:
            return self._default_model
        if self._default_model in installed:
            return self._default_model
        # Strip ":tag" suffix when matching so "llama3.1" matches "llama3.1:latest"
        base = self._default_model.split(":", 1)[0]
        for m in installed:
            if m.split(":", 1)[0] == base:
                return m
        return installed[0]

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
        # Ollama can do images per-model (llava etc.) but not via the
        # text /api/generate endpoint we use; drop attachments for now
        # and let the LLM step decide whether that's acceptable.
        del attachments
        effective_model = model or self._pick_default_model()
        options: dict = {"num_predict": max_tokens}
        if temperature is not None:
            options["temperature"] = temperature
        payload: dict = {
            "model": effective_model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if system:
            payload["system"] = system

        with self._client() as client:
            response = client.post(f"{self._host}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

        return Completion(
            text=data.get("response", ""),
            model=effective_model,
            raw=data,
        )
