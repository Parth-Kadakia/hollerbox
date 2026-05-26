"""Workflows CRUD over HTTP."""

from __future__ import annotations

import textwrap

VALID_YAML = textwrap.dedent("""
name: demo
description: a test workflow
steps:
  - id: greet
    type: shell
    config:
      command: "echo hi"
""").strip()


def _put(client, name: str, yaml_source: str = VALID_YAML):
    return client.put(f"/workflows/{name}", json={"yaml_source": yaml_source})


def test_empty_list(api_client) -> None:
    resp = api_client.get("/workflows")
    assert resp.status_code == 200
    assert resp.json() == []


def test_upsert_then_get(api_client) -> None:
    put_resp = _put(api_client, "demo")
    assert put_resp.status_code == 200
    body = put_resp.json()
    assert body["name"] == "demo"
    assert body["version"] == 1
    assert body["yaml_source"].startswith("name: demo")

    get_resp = api_client.get("/workflows/demo")
    assert get_resp.status_code == 200
    assert get_resp.json()["yaml_source"].startswith("name: demo")


def test_list_returns_summary(api_client) -> None:
    _put(api_client, "demo")
    resp = api_client.get("/workflows")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "demo"
    # Summary shouldn't carry the heavy yaml_source field.
    assert "yaml_source" not in items[0]


def test_upsert_rejects_mismatched_name(api_client) -> None:
    resp = _put(api_client, "different", VALID_YAML)
    assert resp.status_code == 422
    assert "does not match path" in resp.json()["detail"]


def test_upsert_rejects_bad_yaml(api_client) -> None:
    resp = api_client.put(
        "/workflows/broken",
        json={"yaml_source": "name: broken\nsteps: not-a-list"},
    )
    assert resp.status_code == 422


def test_get_404(api_client) -> None:
    resp = api_client.get("/workflows/missing")
    assert resp.status_code == 404


def test_delete_when_no_runs(api_client) -> None:
    _put(api_client, "demo")
    resp = api_client.delete("/workflows/demo")
    assert resp.status_code == 204
    assert api_client.get("/workflows/demo").status_code == 404


def test_delete_blocks_when_runs_exist(api_client, api_surface) -> None:
    _put(api_client, "demo")
    # Enqueue a run so the workflow has history.
    run_resp = api_client.post("/workflows/demo/run", json={})
    assert run_resp.status_code == 202

    resp = api_client.delete("/workflows/demo")
    assert resp.status_code == 409
    assert "run history" in resp.json()["detail"]


# --------------------------- templates ---------------------------

def test_lists_bundled_templates(api_client) -> None:
    resp = api_client.get("/workflows/templates")
    assert resp.status_code == 200
    body = resp.json()
    # The repo ships at least the blank + a few examples.
    ids = {t["id"] for t in body}
    assert {"blank", "summarize_url", "generate_image"}.issubset(ids)
    blank = next(t for t in body if t["id"] == "blank")
    assert blank["step_count"] >= 1
    assert blank["yaml_source"].startswith("name:")


def test_templates_dir_env_override(api_client, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOLLERBOX_TEMPLATES_DIR", str(tmp_path))
    (tmp_path / "alpha.yaml").write_text(
        "name: alpha\nsteps:\n  - id: a\n    type: shell\n    config: {command: 'echo'}\n"
    )
    resp = api_client.get("/workflows/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert {t["id"] for t in body} == {"alpha"}


def test_templates_skip_broken_yaml(api_client, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOLLERBOX_TEMPLATES_DIR", str(tmp_path))
    (tmp_path / "good.yaml").write_text(
        "name: good\nsteps:\n  - id: a\n    type: shell\n    config: {command: 'echo'}\n"
    )
    (tmp_path / "broken.yaml").write_text("not: valid: yaml: probably")

    resp = api_client.get("/workflows/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert {t["id"] for t in body} == {"good"}
