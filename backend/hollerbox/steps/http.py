"""HttpStep — issue an HTTP request via httpx.

Output shape: { status_code, headers, body (text), json (parsed if JSON
content-type, else None), elapsed_ms }.

A class-level `_TRANSPORT` slot allows tests to inject an `httpx.MockTransport`
without going over the network. Production code never sets it.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from hollerbox.core.context import RunContext
from hollerbox.registry import register_step
from hollerbox.steps.base import Step, StepResult

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class HttpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: HttpMethod = "GET"
    url: str = Field(..., min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    json_body: Any = Field(default=None, alias="json")
    body: str | None = None  # raw string body (mutually exclusive with json_body)
    timeout: float = Field(default=30.0, gt=0.0)
    follow_redirects: bool = True


@register_step
class HttpStep(Step):
    type = "http"
    ConfigModel = HttpConfig

    # Test seam: when set, used as the transport for the underlying client.
    _TRANSPORT: ClassVar[httpx.BaseTransport | None] = None

    def describe_effect(self, ctx: RunContext) -> str:
        cfg = self.resolve_config(ctx)
        return f"http {cfg.method} {cfg.url}"

    def run(self, ctx: RunContext) -> StepResult:
        cfg: HttpConfig = self.resolve_config(ctx)
        if cfg.body is not None and cfg.json_body is not None:
            return StepResult.failed(
                error="http step: provide either `body` or `json`, not both."
            )

        client_kwargs: dict[str, Any] = {
            "timeout": cfg.timeout,
            "follow_redirects": cfg.follow_redirects,
        }
        if type(self)._TRANSPORT is not None:
            client_kwargs["transport"] = type(self)._TRANSPORT

        start = time.monotonic()
        try:
            with httpx.Client(**client_kwargs) as client:
                resp = client.request(
                    method=cfg.method,
                    url=cfg.url,
                    headers=cfg.headers or None,
                    params=cfg.params or None,
                    json=cfg.json_body,
                    content=cfg.body,
                )
        except httpx.HTTPError as exc:
            return StepResult.failed(error=f"{type(exc).__name__}: {exc}")
        elapsed_ms = int((time.monotonic() - start) * 1000)

        body_text = resp.text
        try:
            body_json = resp.json()
        except ValueError:
            body_json = None

        output = {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body": body_text,
            "json": body_json,
            "elapsed_ms": elapsed_ms,
        }
        logs = [f"{cfg.method} {cfg.url} -> {resp.status_code} ({elapsed_ms}ms)"]
        return StepResult.success(output=output, logs=logs)
