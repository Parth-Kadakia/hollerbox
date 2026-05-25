"""Sandbox tests for /files — must serve only paths produced by a step run."""

from __future__ import annotations

import textwrap
from pathlib import Path

from api.worker import Worker

WRITE_FILE_YAML_TEMPLATE = textwrap.dedent("""
name: writes
steps:
  - id: write
    type: write_file
    config:
      path: {path}
      content: "hello"
""").strip()


def test_serves_a_file_produced_by_a_step(api_client, api_surface, tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    api_client.put(
        "/workflows/writes",
        json={"yaml_source": WRITE_FILE_YAML_TEMPLATE.format(path=str(target))},
    )
    run = api_client.post("/workflows/writes/run", json={}).json()
    Worker(api_surface).drive_one()

    resp = api_client.get("/files", params={"path": str(target)})
    assert resp.status_code == 200
    assert resp.content.decode("utf-8") == "hello"
    # run shouldn't matter beyond having generated the path — bind for clarity
    assert run["id"]


def test_403_for_arbitrary_path(api_client, tmp_path: Path) -> None:
    sketchy = tmp_path / "not-from-a-step.txt"
    sketchy.write_text("oops")
    resp = api_client.get("/files", params={"path": str(sketchy)})
    assert resp.status_code == 403


def test_404_when_recorded_path_missing(api_client, api_surface, tmp_path: Path) -> None:
    target = tmp_path / "vanishes.txt"
    api_client.put(
        "/workflows/writes",
        json={"yaml_source": WRITE_FILE_YAML_TEMPLATE.format(path=str(target))},
    )
    api_client.post("/workflows/writes/run", json={})
    Worker(api_surface).drive_one()
    target.unlink()  # file gone after the step recorded it

    resp = api_client.get("/files", params={"path": str(target)})
    assert resp.status_code == 404
