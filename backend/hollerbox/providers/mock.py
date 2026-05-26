"""Mock provider — deterministic, offline, scriptable. Used by tests."""

from __future__ import annotations

from collections.abc import Callable

from hollerbox.providers.base import Attachment, Completion, Provider


class MockProvider(Provider):
    """A provider whose `complete` returns a scripted value.

    Two modes:
    - Pass a string `default_text`: every call returns it.
    - Pass a callable `responder(prompt, system) -> str`: every call invokes
      the responder so tests can vary output by input.

    Counters and call history are exposed for test assertions.
    """

    name = "mock"

    def __init__(
        self,
        *,
        default_text: str = "(mock response)",
        responder: Callable[[str, str | None], str] | None = None,
        model: str = "mock-1",
    ) -> None:
        self._default_text = default_text
        self._responder = responder
        self._model = model
        self.calls: list[dict] = []

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
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "model": model or self._model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "attachments": list(attachments or []),
            }
        )
        text = self._responder(prompt, system) if self._responder else self._default_text
        return Completion(text=text, model=model or self._model)
