"""End-to-end CLI test — exercises the full Phase 1 surface.

The point of this test is to prove that someone with no other context
can `validate`, `run`, `runs`, `run-detail`, and `approve` a workflow
purely through the CLI, against a fresh SQLite database, without any
of the steps phoning the network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from hollerbox.cli import main


@pytest.fixture()
def cli_env(tmp_path: Path) -> dict[str, str]:
    """Each test gets its own ephemeral SQLite db."""
    db_path = tmp_path / "hb.sqlite"
    return {"HOLLERBOX_DB_URL": f"sqlite:///{db_path}"}


@pytest.fixture()
def hello_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "hello.yaml"
    p.write_text(
        """
name: hello
version: 1
description: smoke
inputs:
  who: world
steps:
  - id: greet
    type: shell
    config:
      command: "echo 'Hello, ${inputs.who}!'"
""".strip(),
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def approval_yaml(tmp_path: Path) -> tuple[Path, Path]:
    """A workflow with a destructive write that requires_confirmation=true."""
    out = tmp_path / "out.txt"
    p = tmp_path / "approval.yaml"
    p.write_text(
        f"""
name: gated_write
version: 1
description: writes a file but only after approval
inputs:
  body: hello
steps:
  - id: greet
    type: shell
    config: {{ command: "echo greeting" }}

  - id: save
    type: write_file
    requires_confirmation: true
    config:
      path: "{out}"
      content: "${{inputs.body}}"
""".strip(),
        encoding="utf-8",
    )
    return p, out


def _run(cli: CliRunner, args: list[str], env: dict[str, str]):
    return cli.invoke(main, args, env=env, catch_exceptions=False)


def _extract_full_id(output: str) -> str:
    """run / approve commands print `full id: <32-hex>` — pull it out."""
    m = re.search(r"full id:\s+([0-9a-f]{32})", output)
    assert m, f"no full id in output:\n{output}"
    return m.group(1)


# --------------------------- basic happy path ---------------------------

def test_validate_then_run_then_runs_and_detail(cli_env, hello_yaml):
    cli = CliRunner()

    # validate
    r = _run(cli, ["validate", str(hello_yaml)], cli_env)
    assert r.exit_code == 0
    assert "hello" in r.output

    # run
    r = _run(cli, ["run", str(hello_yaml), "--input", "who=tester"], cli_env)
    assert r.exit_code == 0, r.output
    assert "success" in r.output
    run_id = _extract_full_id(r.output)

    # runs (list)
    r = _run(cli, ["runs"], cli_env)
    assert r.exit_code == 0
    assert "hello" in r.output
    assert run_id[:8] in r.output

    # run-detail (with logs)
    r = _run(cli, ["run-detail", run_id], cli_env)
    assert r.exit_code == 0
    assert "greet" in r.output
    assert "Hello, tester!" in r.output


def test_run_by_short_id_works_for_detail(cli_env, hello_yaml):
    cli = CliRunner()
    r = _run(cli, ["run", str(hello_yaml)], cli_env)
    full_id = _extract_full_id(r.output)
    short = full_id[:8]
    r = _run(cli, ["run-detail", short], cli_env)
    assert r.exit_code == 0


def test_run_unknown_workflow_arg_clean_error(cli_env):
    cli = CliRunner()
    r = _run(cli, ["run", "nonexistent_workflow"], cli_env)
    assert r.exit_code != 0
    assert "not found" in r.output


# --------------------------- dry-run ---------------------------

def test_dry_run_does_not_execute_destructive_step(cli_env, approval_yaml):
    cli = CliRunner()
    wf_path, out_file = approval_yaml
    r = _run(cli, ["run", str(wf_path), "--dry-run"], cli_env)
    assert r.exit_code == 0
    assert "success" in r.output
    assert not out_file.exists()
    # The detail view should show the destructive step as dry_run
    run_id = _extract_full_id(r.output)
    r = _run(cli, ["run-detail", run_id], cli_env)
    assert "dry_run" in r.output
    assert str(out_file) in r.output  # describe_effect line


# --------------------------- approval loop ---------------------------

def test_approval_pause_and_resume_to_success(cli_env, approval_yaml):
    cli = CliRunner()
    wf_path, out_file = approval_yaml

    r = _run(cli, ["run", str(wf_path), "--input", "body=approved-via-cli"], cli_env)
    assert r.exit_code == 0
    assert "paused" in r.output
    run_id = _extract_full_id(r.output)
    assert not out_file.exists()

    # Approve
    r = _run(cli, ["approve", run_id], cli_env)
    assert r.exit_code == 0
    assert "success" in r.output
    assert out_file.read_text() == "approved-via-cli"


def test_approval_pause_and_rejection_cancels(cli_env, approval_yaml):
    cli = CliRunner()
    wf_path, out_file = approval_yaml

    r = _run(cli, ["run", str(wf_path)], cli_env)
    run_id = _extract_full_id(r.output)

    r = _run(cli, ["reject", run_id], cli_env)
    assert r.exit_code == 0
    assert "cancelled" in r.output
    assert not out_file.exists()


def test_approve_non_paused_run_errors(cli_env, hello_yaml):
    cli = CliRunner()
    r = _run(cli, ["run", str(hello_yaml)], cli_env)
    run_id = _extract_full_id(r.output)

    r = _run(cli, ["approve", run_id], cli_env)
    assert r.exit_code != 0
    assert "not paused" in r.output


# --------------------------- packaged workflows ---------------------------

REPO_WORKFLOWS = Path(__file__).resolve().parents[2] / "workflows"


def test_packaged_hello_yaml_validates(cli_env):
    cli = CliRunner()
    r = _run(cli, ["validate", str(REPO_WORKFLOWS / "hello.yaml")], cli_env)
    assert r.exit_code == 0
    assert "hello" in r.output


def test_packaged_hello_yaml_runs_end_to_end(cli_env):
    cli = CliRunner()
    r = _run(cli, ["run", str(REPO_WORKFLOWS / "hello.yaml"), "--input", "who=test"], cli_env)
    assert r.exit_code == 0, r.output
    assert "success" in r.output
    run_id = _extract_full_id(r.output)
    r = _run(cli, ["run-detail", run_id], cli_env)
    # Both steps ran successfully, and the greet step's stdout shows up
    # via the shell-step log capture.
    assert "greet" in r.output and "stamp" in r.output
    assert "Hello, test!" in r.output


def test_packaged_file_pipeline_validates(cli_env):
    cli = CliRunner()
    r = _run(cli, ["validate", str(REPO_WORKFLOWS / "examples" / "file_pipeline.yaml")], cli_env)
    assert r.exit_code == 0
