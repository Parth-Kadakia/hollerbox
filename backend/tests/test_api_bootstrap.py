"""On-startup template import.

The default `api_client` fixture disables auto-import so most tests
can assume an empty workflows table. The fixture below re-enables it
so we can verify the boot-time behavior.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture()
def importing_client(api_surface) -> Iterator:
    """`api_client` variant with HOLLERBOX_AUTO_IMPORT_TEMPLATES re-enabled."""
    os.environ["HOLLERBOX_WORKER_ENABLED"] = "0"
    os.environ.pop("HOLLERBOX_AUTO_IMPORT_TEMPLATES", None)
    from fastapi.testclient import TestClient

    from api.main import create_app

    app = create_app()
    app.state.surface = api_surface
    try:
        with TestClient(app) as client:
            yield client
    finally:
        os.environ.pop("HOLLERBOX_WORKER_ENABLED", None)


def test_bundled_templates_are_auto_registered(importing_client) -> None:
    """First run: every template ships to /workflows so the chat router
    can use them without a manual save step."""
    resp = importing_client.get("/workflows")
    assert resp.status_code == 200
    names = {w["name"] for w in resp.json()}
    # The repo ships several templates — check the new ones the user
    # actually cares about are present.
    assert {"analyze_file", "generate_image", "summarize_url"}.issubset(names)


def test_existing_workflow_is_not_overwritten(importing_client, api_surface) -> None:
    """If the user has edited a workflow named the same as a template,
    we must not clobber their version on next restart."""
    # First, replace the bundled `generate_image` template with a
    # user-customized version.
    custom = (
        "name: generate_image\n"
        "description: User's customized version\n"
        "steps:\n"
        "  - id: stub\n"
        "    type: shell\n"
        "    config:\n"
        "      command: 'echo customized'\n"
    )
    importing_client.put(
        "/workflows/generate_image",
        json={"yaml_source": custom},
    )

    # Now simulate another startup: build a fresh app with the same
    # surface and check the user's edits survived the second import.
    from fastapi.testclient import TestClient

    from api.main import create_app

    app2 = create_app()
    app2.state.surface = api_surface
    with TestClient(app2) as client2:
        wf = client2.get("/workflows/generate_image").json()
        assert "customized" in wf["yaml_source"]


def test_disabling_bootstrap_via_env(monkeypatch, api_surface) -> None:
    """`HOLLERBOX_AUTO_IMPORT_TEMPLATES=0` keeps the DB empty on boot."""
    monkeypatch.setenv("HOLLERBOX_AUTO_IMPORT_TEMPLATES", "0")
    monkeypatch.setenv("HOLLERBOX_WORKER_ENABLED", "0")
    from fastapi.testclient import TestClient

    from api.main import create_app

    app = create_app()
    app.state.surface = api_surface
    with TestClient(app) as client:
        resp = client.get("/workflows")
        assert resp.status_code == 200
        assert resp.json() == []
