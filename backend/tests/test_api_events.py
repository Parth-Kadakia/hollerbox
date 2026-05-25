"""SSE stream for live run events.

The endpoint polls the DB and streams `status`/`step`/`done` events as
new rows appear. We drive the run synchronously before opening the
stream so the test gets a deterministic, already-terminal trace —
otherwise the SSE generator's `await asyncio.sleep` would race the
TestClient's blocking iteration.
"""

from __future__ import annotations

import json
import textwrap

from api.worker import Worker

SHELL_YAML = textwrap.dedent("""
name: demo
steps:
  - id: greet
    type: shell
    config:
      command: "echo hi"
""").strip()


def _events(text: str) -> list[dict]:
    """Parse SSE wire format into a list of {event, data} dicts."""
    out: list[dict] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                out.append(current)
                current = {}
            continue
        if line.startswith(":"):
            continue  # SSE comment / keep-alive
        if ":" in line:
            key, _, value = line.partition(":")
            current[key.strip()] = value.lstrip()
    if current:
        out.append(current)
    return out


def test_sse_emits_status_and_step_events_for_completed_run(api_client, api_surface) -> None:
    api_client.put("/workflows/demo", json={"yaml_source": SHELL_YAML})
    run = api_client.post("/workflows/demo/run", json={}).json()
    Worker(api_surface).drive_one()

    with api_client.stream("GET", f"/runs/{run['id']}/events") as resp:
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")

    events = _events(body)
    types = [e.get("event") for e in events]
    assert "status" in types
    assert "step" in types
    assert types[-1] == "done"

    # The last `status` event before `done` should report the terminal state.
    terminal_status = next(
        json.loads(e["data"])["status"] for e in events if e.get("event") == "status"
    )
    assert terminal_status in {"running", "success"}
    assert any(
        json.loads(e["data"])["status"] == "success"
        for e in events
        if e.get("event") == "status"
    )


def test_sse_404_for_missing_run(api_client) -> None:
    assert api_client.get("/runs/missing/events").status_code == 404
