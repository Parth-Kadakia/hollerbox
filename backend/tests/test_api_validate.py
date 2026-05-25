"""POST /workflows/validate — lint YAML without persisting."""

from __future__ import annotations

import textwrap

VALID = textwrap.dedent("""
name: demo
description: a test workflow
inputs:
  topic: AI
steps:
  - id: greet
    type: shell
    config:
      command: "echo ${inputs.topic}"
""").strip()


def test_valid_returns_metadata(api_client) -> None:
    resp = api_client.post("/workflows/validate", json={"yaml_source": VALID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["name"] == "demo"
    assert body["step_ids"] == ["greet"]
    assert "inputs.topic" in body["references"]
    assert body["errors"] == []


def test_invalid_yaml_returns_200_with_errors(api_client) -> None:
    resp = api_client.post("/workflows/validate", json={"yaml_source": "name: x\nsteps: oops"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["errors"]


def test_validate_does_not_persist(api_client) -> None:
    api_client.post("/workflows/validate", json={"yaml_source": VALID})
    assert api_client.get("/workflows").json() == []
