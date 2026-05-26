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
    """If the user has edited a workflow whose `version:` is at-or-above
    the bundled template's, we must not clobber it on next restart."""
    # Match the bundled version so the upgrade-comparison falls through
    # to "leave it alone".
    custom = (
        "name: generate_image\n"
        "version: 99\n"
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


def test_upgrades_when_bundled_version_is_higher(importing_client, api_surface) -> None:
    """When a template's `version:` is bumped in the repo, the next
    startup re-imports it. Lets us ship template fixes to users without
    asking them to delete + recreate."""
    from hollerbox.store import repo, session_scope

    # Force the DB to look like an older copy of analyze_file (v1).
    older = (
        "name: analyze_file\n"
        "version: 1\n"
        "description: outdated copy\n"
        "steps:\n"
        "  - id: x\n"
        "    type: shell\n"
        "    config:\n"
        "      command: 'echo old'\n"
    )
    importing_client.put("/workflows/analyze_file", json={"yaml_source": older})

    # Confirm v1 is in place
    with session_scope(api_surface.session_factory) as s:
        row = repo.get_workflow_by_name(s, "analyze_file")
        assert row is not None and row.version == 1

    # Re-run lifespan
    from fastapi.testclient import TestClient

    from api.main import create_app

    app2 = create_app()
    app2.state.surface = api_surface
    with TestClient(app2), session_scope(api_surface.session_factory) as s:
        row = repo.get_workflow_by_name(s, "analyze_file")
        assert row is not None
        assert row.version >= 2  # picked up the bundled upgrade
        assert "outdated copy" not in row.yaml_source


def test_user_higher_version_is_protected(importing_client, api_surface) -> None:
    """If the user bumps a workflow's `version:` past the bundled one,
    bootstrap leaves it alone."""
    from hollerbox.store import repo, session_scope

    pinned = (
        "name: analyze_file\n"
        "version: 99\n"
        "description: my customized version\n"
        "steps:\n"
        "  - id: x\n"
        "    type: shell\n"
        "    config:\n"
        "      command: 'echo mine'\n"
    )
    importing_client.put("/workflows/analyze_file", json={"yaml_source": pinned})

    from fastapi.testclient import TestClient

    from api.main import create_app

    app2 = create_app()
    app2.state.surface = api_surface
    with TestClient(app2), session_scope(api_surface.session_factory) as s:
        row = repo.get_workflow_by_name(s, "analyze_file")
        assert row is not None and row.version == 99
        assert "customized" in row.yaml_source


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
