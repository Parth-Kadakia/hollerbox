"""Runs — enqueue, list, detail, worker drive, approve/reject/cancel."""

from __future__ import annotations

import textwrap

from api.worker import Worker

SHELL_YAML = textwrap.dedent("""
name: demo
description: simplest possible runnable workflow
steps:
  - id: greet
    type: shell
    config:
      command: "echo hi"
""").strip()

DESTRUCTIVE_YAML = textwrap.dedent("""
name: needs_approval
steps:
  - id: confirm
    type: shell
    destructive: true
    requires_confirmation: true
    config:
      command: "echo would-delete"
""").strip()


def _create_wf(client, name: str, yaml_text: str) -> None:
    resp = client.put(f"/workflows/{name}", json={"yaml_source": yaml_text})
    assert resp.status_code == 200, resp.text


# --------------------------- enqueue + drive ---------------------------

def test_enqueue_returns_queued_run(api_client) -> None:
    _create_wf(api_client, "demo", SHELL_YAML)
    resp = api_client.post("/workflows/demo/run", json={})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["workflow_name"] == "demo"
    assert body["trigger_kind"] == "manual"


def test_enqueue_unknown_workflow_404(api_client) -> None:
    resp = api_client.post("/workflows/ghost/run", json={})
    assert resp.status_code == 404


def test_worker_drives_queued_to_success(api_client, api_surface) -> None:
    _create_wf(api_client, "demo", SHELL_YAML)
    run = api_client.post("/workflows/demo/run", json={}).json()

    # Drive the queue one step (synchronously, no background loop).
    worker = Worker(api_surface)
    drove = worker.drive_one()
    assert drove is True

    detail = api_client.get(f"/runs/{run['id']}").json()
    assert detail["status"] == "success"
    assert len(detail["steps"]) == 1
    assert detail["steps"][0]["status"] == "success"


def test_runs_list_filters_by_workflow(api_client, api_surface) -> None:
    _create_wf(api_client, "demo", SHELL_YAML)
    _create_wf(api_client, "other", SHELL_YAML.replace("name: demo", "name: other"))

    api_client.post("/workflows/demo/run", json={})
    api_client.post("/workflows/other/run", json={})

    all_runs = api_client.get("/runs").json()
    assert len(all_runs) == 2

    demo_runs = api_client.get("/runs", params={"workflow": "demo"}).json()
    assert len(demo_runs) == 1
    assert demo_runs[0]["workflow_name"] == "demo"


def test_run_detail_404(api_client) -> None:
    assert api_client.get("/runs/missing").status_code == 404


# --------------------------- approve / reject ---------------------------

def test_approve_resumes_paused_run(api_client, api_surface) -> None:
    _create_wf(api_client, "needs_approval", DESTRUCTIVE_YAML)
    run = api_client.post("/workflows/needs_approval/run", json={}).json()

    Worker(api_surface).drive_one()
    # The destructive step needs approval — runner pauses without dry-run flag,
    # because requires_confirmation: true.
    detail = api_client.get(f"/runs/{run['id']}").json()
    assert detail["status"] == "paused"
    assert detail["steps"][0]["status"] == "pending_approval"

    approve = api_client.post(f"/runs/{run['id']}/approve")
    assert approve.status_code == 200
    body = approve.json()
    assert body["status"] == "success"

    detail = api_client.get(f"/runs/{run['id']}").json()
    assert detail["status"] == "success"


def test_reject_cancels_paused_run(api_client, api_surface) -> None:
    _create_wf(api_client, "needs_approval", DESTRUCTIVE_YAML)
    run = api_client.post("/workflows/needs_approval/run", json={}).json()
    Worker(api_surface).drive_one()

    reject = api_client.post(f"/runs/{run['id']}/reject")
    assert reject.status_code == 200
    assert reject.json()["status"] == "cancelled"


def test_approve_409_when_not_paused(api_client, api_surface) -> None:
    _create_wf(api_client, "demo", SHELL_YAML)
    run = api_client.post("/workflows/demo/run", json={}).json()
    Worker(api_surface).drive_one()  # finishes immediately, never paused

    resp = api_client.post(f"/runs/{run['id']}/approve")
    assert resp.status_code == 409


def test_approve_404_when_missing(api_client) -> None:
    assert api_client.post("/runs/missing/approve").status_code == 404


# --------------------------- cancel ---------------------------

def test_cancel_queued_run(api_client) -> None:
    _create_wf(api_client, "demo", SHELL_YAML)
    run = api_client.post("/workflows/demo/run", json={}).json()
    resp = api_client.post(f"/runs/{run['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_cancel_409_on_terminal(api_client, api_surface) -> None:
    _create_wf(api_client, "demo", SHELL_YAML)
    run = api_client.post("/workflows/demo/run", json={}).json()
    Worker(api_surface).drive_one()
    resp = api_client.post(f"/runs/{run['id']}/cancel")
    assert resp.status_code == 409


# --------------------------- worker idle ---------------------------

def test_worker_returns_false_when_idle(api_surface) -> None:
    """Empty queue → drive_one signals 'nothing to do' so the loop can sleep."""
    assert Worker(api_surface).drive_one() is False
