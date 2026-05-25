"""Tests for hollerbox.steps.http.HttpStep — uses httpx.MockTransport (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from hollerbox.core.context import RunContext
from hollerbox.core.workflow import StepDefinition
from hollerbox.steps.http import HttpStep


@pytest.fixture(autouse=True)
def restore_transport():
    """Make sure tests don't leak a transport into each other."""
    original = HttpStep._TRANSPORT
    yield
    HttpStep._TRANSPORT = original


def _set_transport(handler):
    HttpStep._TRANSPORT = httpx.MockTransport(handler)


def _run(config: dict, *, inputs: dict | None = None):
    defn = StepDefinition(id="h", type="http", config=config)
    step = HttpStep(defn)
    ctx = RunContext.new(inputs=inputs or {})
    return step.run(ctx)


def test_basic_get_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://example.com/items?q=ai"
        return httpx.Response(200, json={"hits": [1, 2, 3]})

    _set_transport(handler)
    r = _run({"url": "https://example.com/items", "params": {"q": "ai"}})

    assert r.status == "success"
    assert r.output["status_code"] == 200
    assert r.output["json"] == {"hits": [1, 2, 3]}
    assert json.loads(r.output["body"]) == {"hits": [1, 2, 3]}


def test_post_with_json_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "abc"})

    _set_transport(handler)
    r = _run({"method": "POST", "url": "https://api/x", "json": {"a": 1}})

    assert r.status == "success"
    assert r.output["status_code"] == 201
    assert captured == {"method": "POST", "body": {"a": 1}}


def test_template_resolution_in_url_and_params():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/items"
        assert dict(request.url.params) == {"q": "templated"}
        return httpx.Response(200, text="ok")

    _set_transport(handler)
    r = _run(
        {"url": "https://example.com/items", "params": {"q": "${inputs.q}"}},
        inputs={"q": "templated"},
    )
    assert r.status == "success"


def test_headers_passed_through():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Test"] == "yes"
        return httpx.Response(200, text="")

    _set_transport(handler)
    r = _run({"url": "https://example.com", "headers": {"X-Test": "yes"}})
    assert r.status == "success"


def test_non_json_body_returns_none_for_json_field():
    def handler(request):
        return httpx.Response(200, text="<html>hi</html>")

    _set_transport(handler)
    r = _run({"url": "https://example.com"})
    assert r.output["json"] is None
    assert r.output["body"] == "<html>hi</html>"


def test_5xx_is_success_at_step_level():
    # HTTP errors are still successful step executions; the user can branch
    # on status_code if they want to treat them as failures.
    def handler(request):
        return httpx.Response(503, text="busy")

    _set_transport(handler)
    r = _run({"url": "https://example.com"})
    assert r.status == "success"
    assert r.output["status_code"] == 503


def test_body_and_json_together_rejected():
    _set_transport(lambda req: httpx.Response(200))
    r = _run({"url": "https://example.com", "body": "raw", "json": {"a": 1}})
    assert r.status == "failed"
    assert "either `body` or `json`" in (r.error or "")


def test_transport_error_becomes_step_failure():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _set_transport(handler)
    r = _run({"url": "https://example.com"})
    assert r.status == "failed"
    assert "ConnectError" in (r.error or "")
