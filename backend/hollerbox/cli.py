"""HollerBox CLI entry point.

Phase 0 wired `--help` and `version`. Phase 1a added `validate`. Phase 1e
finishes Phase 1 by wiring the execution surface: `run`, `runs`,
`run-detail`, `approve`, `reject`. These all talk to the same engine the
future API layer (Phase 3) will wrap.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import click

# Side-effect import: registers built-in step types with the registry.
import hollerbox.steps  # noqa: F401
from hollerbox import __version__
from hollerbox.core.runner import Runner, RunnerResult
from hollerbox.core.templating import find_references
from hollerbox.core.workflow import (
    Workflow,
    WorkflowLoadError,
    load_workflow,
    load_workflows_dir,
)
from hollerbox.store import (
    init_db,
    make_engine,
    make_session_factory,
    session_scope,
)
from hollerbox.store import repo


_DB_URL_ENV = "HOLLERBOX_DB_URL"


# --------------------------- helpers ---------------------------

def _resolved_db_url() -> str:
    env_url = os.environ.get(_DB_URL_ENV)
    if env_url:
        return env_url
    # Default to ~/.hollerbox/hollerbox.sqlite via default_db_url()
    from hollerbox.store.db import default_db_url

    return default_db_url()


def _build_runner() -> Runner:
    engine = make_engine(_resolved_db_url())
    init_db(engine)
    return Runner(make_session_factory(engine))


def _parse_kv_pairs(pairs: tuple[str, ...]) -> dict[str, Any]:
    """Parse `KEY=VAL` strings. Values are JSON-decoded when possible; else strings."""
    out: dict[str, Any] = {}
    for raw in pairs:
        if "=" not in raw:
            raise click.BadParameter(
                f"expected KEY=VALUE, got {raw!r}", param_hint="--input/--secret"
            )
        key, _, val = raw.partition("=")
        key = key.strip()
        if not key:
            raise click.BadParameter(f"empty key in {raw!r}")
        try:
            out[key] = json.loads(val)
        except (json.JSONDecodeError, ValueError):
            out[key] = val
    return out


def _load_workflow_arg(arg: str) -> tuple[Workflow, str]:
    """Resolve a `run` workflow argument: file path OR DB-registered name.

    Returns (workflow, yaml_source). yaml_source is the raw text so we can
    persist it against the workflow row for later resume / inspection.
    """
    p = Path(arg)
    if p.exists() and p.is_file():
        wf = load_workflow(p)
        return wf, p.read_text(encoding="utf-8")

    # Fall back to DB lookup by name.
    engine = make_engine(_resolved_db_url())
    init_db(engine)
    sf = make_session_factory(engine)
    with session_scope(sf) as s:
        row = repo.get_workflow_by_name(s, arg)
        if row is None:
            raise click.ClickException(
                f"workflow {arg!r} not found as a file path and not registered in the database."
            )
        wf = load_workflow_from_source(row.yaml_source)
        return wf, row.yaml_source


def load_workflow_from_source(yaml_source: str) -> Workflow:
    """Parse a workflow from in-memory YAML text (used on resume)."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
        tmp.write(yaml_source)
        tmp_path = Path(tmp.name)
    try:
        return load_workflow(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _short_id(full: str) -> str:
    return full[:8]


def _fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return "—"
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_duration(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "—"
    secs = (end - start).total_seconds()
    if secs < 1:
        return f"{int(secs * 1000)}ms"
    return f"{secs:.2f}s"


_STATUS_COLOR = {
    "success": "green",
    "failed": "red",
    "running": "blue",
    "paused": "yellow",
    "cancelled": "magenta",
    "queued": "white",
    "dry_run": "cyan",
    "pending_approval": "yellow",
    "skipped": "white",
}


def _color_status(status: str) -> str:
    return click.style(status, fg=_STATUS_COLOR.get(status, "white"))


def _echo_result(result: RunnerResult) -> None:
    short = _short_id(result.run_id)
    line = f"run {short}  status={_color_status(result.status)}"
    if result.last_step_id:
        line += f"  last_step={result.last_step_id}"
    if result.error:
        line += f"  error={click.style(result.error, fg='red')}"
    click.echo(line)
    click.echo(f"  full id: {result.run_id}")


# --------------------------- root group ---------------------------

@click.group(
    help="HollerBox — local-first, chat-driven AI workflow engine.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="hollerbox")
def main() -> None:
    """HollerBox command-line interface."""


@main.command()
def version() -> None:
    """Print the HollerBox version."""
    click.echo(__version__)


# --------------------------- validate ---------------------------

@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--show-refs", is_flag=True, help="Print every ${...} reference each workflow makes.")
def validate(path: Path, show_refs: bool) -> None:
    """Validate one workflow YAML file or every workflow in a directory.

    Exits non-zero if any workflow fails to load or validate.
    """
    workflows: dict[str, tuple[Path, Workflow]] = {}
    try:
        if path.is_dir():
            loaded = load_workflows_dir(path)
            for name, wf in loaded.items():
                workflows[name] = (path / f"{name}.yaml", wf)
        else:
            wf = load_workflow(path)
            workflows[wf.name] = (path, wf)
    except WorkflowLoadError as exc:
        click.echo(click.style(f"✗ {exc}", fg="red"), err=True)
        raise click.exceptions.Exit(1) from exc

    for name, (file_path, wf) in workflows.items():
        click.echo(
            click.style("✓", fg="green")
            + f" {name}  "
            + click.style(f"({file_path})", fg="bright_black")
        )
        if show_refs:
            refs = sorted(set(find_references(wf.model_dump())))
            if refs:
                for r in refs:
                    click.echo(f"    ${{{r}}}")
            else:
                click.echo("    (no references)")


# --------------------------- run ---------------------------

@main.command()
@click.argument("workflow_arg")
@click.option(
    "--input",
    "input_pairs",
    multiple=True,
    metavar="KEY=VAL",
    help="Override a workflow input (repeatable). Values JSON-decoded when possible.",
)
@click.option(
    "--secret",
    "secret_pairs",
    multiple=True,
    metavar="KEY=VAL",
    help="Provide a runtime secret (repeatable). Phase 1 only — persistent store in Phase 2.",
)
@click.option("--dry-run", is_flag=True, help="Simulate destructive steps without executing them.")
@click.option(
    "--trigger",
    type=click.Choice(["manual", "chat"], case_sensitive=False),
    default="manual",
    show_default=True,
    help="Trigger kind to record. 'chat' auto-pauses on any destructive step.",
)
def run(
    workflow_arg: str,
    input_pairs: tuple[str, ...],
    secret_pairs: tuple[str, ...],
    dry_run: bool,
    trigger: str,
) -> None:
    """Run a workflow.

    WORKFLOW_ARG is either a path to a YAML file or the name of a workflow
    already registered in the database.
    """
    wf, yaml_source = _load_workflow_arg(workflow_arg)
    inputs = _parse_kv_pairs(input_pairs)
    secrets = _parse_kv_pairs(secret_pairs)

    runner = _build_runner()
    result = runner.execute(
        wf,
        inputs=inputs,
        yaml_source=yaml_source,
        dry_run=dry_run,
        trigger_kind=trigger.lower(),
        chat_triggered=(trigger.lower() == "chat"),
        secrets=secrets,
    )
    _echo_result(result)
    if result.status == "paused":
        click.echo(
            click.style(
                f"\n→ paused at step '{result.last_step_id}'. "
                f"Approve with: hollerbox approve {result.run_id}",
                fg="yellow",
            )
        )
    if result.status == "failed":
        raise click.exceptions.Exit(1)


# --------------------------- runs (list) ---------------------------

@main.command()
@click.option("--workflow", "workflow_name", default=None, help="Filter by workflow name.")
@click.option("--limit", type=int, default=20, show_default=True)
def runs(workflow_name: str | None, limit: int) -> None:
    """List recent runs (newest first)."""
    engine = make_engine(_resolved_db_url())
    init_db(engine)
    sf = make_session_factory(engine)
    with session_scope(sf) as s:
        rows = repo.list_runs(s, workflow_name=workflow_name, limit=limit)
        if not rows:
            click.echo("(no runs yet)")
            return
        header = f"{'ID':10} {'WORKFLOW':24} {'STATUS':18} {'TRIGGER':9} {'DURATION':10} {'STARTED':19}"
        click.echo(click.style(header, fg="bright_black"))
        for r in rows:
            wf_name = (r.workflow.name if r.workflow else "?")[:24]
            click.echo(
                f"{_short_id(r.id):10} "
                f"{wf_name:24} "
                f"{_color_status(r.status):27} "  # +9 for color escape codes
                f"{r.trigger_kind:9} "
                f"{_fmt_duration(r.started_at, r.finished_at):10} "
                f"{_fmt_ts(r.started_at):19}"
            )


# --------------------------- run-detail ---------------------------

@main.command("run-detail")
@click.argument("run_id")
@click.option("--logs/--no-logs", default=True, help="Include per-step logs.")
def run_detail(run_id: str, logs: bool) -> None:
    """Show the full trace of a single run."""
    engine = make_engine(_resolved_db_url())
    init_db(engine)
    sf = make_session_factory(engine)
    with session_scope(sf) as s:
        # Allow short-id lookup if exactly one match.
        run = repo.get_run(s, run_id)
        if run is None and len(run_id) < 32:
            matches = [r for r in repo.list_runs(s, limit=200) if r.id.startswith(run_id)]
            if len(matches) == 1:
                run = matches[0]
            elif len(matches) > 1:
                raise click.ClickException(
                    f"prefix {run_id!r} matches {len(matches)} runs — use the full id"
                )
        if run is None:
            raise click.ClickException(f"run {run_id!r} not found")

        click.echo(click.style(f"Run {run.id}", bold=True))
        wf_name = run.workflow.name if run.workflow else "?"
        click.echo(
            f"  workflow: {wf_name}    "
            f"status: {_color_status(run.status)}    "
            f"trigger: {run.trigger_kind}    "
            f"dry_run: {run.dry_run}"
        )
        click.echo(
            f"  started:  {_fmt_ts(run.started_at)}    "
            f"finished: {_fmt_ts(run.finished_at)}    "
            f"duration: {_fmt_duration(run.started_at, run.finished_at)}"
        )
        if run.error:
            click.echo(f"  error: {click.style(run.error, fg='red')}")
        click.echo()

        step_rows = list(repo.list_step_runs(s, run.id))
        if not step_rows:
            click.echo("  (no steps recorded)")
            return
        for idx, row in enumerate(step_rows, start=1):
            dur = _fmt_duration(row.started_at, row.finished_at)
            click.echo(
                f"  [{idx}] {row.step_id:20} "
                f"{row.step_type:12} "
                f"{_color_status(row.status):27} "
                f"attempt {row.attempt}    {dur}"
            )
            if row.error:
                click.echo(f"        error: {click.style(row.error, fg='red')}")
            if logs and row.logs:
                for line in row.logs:
                    click.echo(click.style(f"        {line}", fg="bright_black"))


# --------------------------- approve / reject ---------------------------

def _resolve_and_load(run_id_or_prefix: str) -> tuple[Runner, str, Workflow]:
    engine = make_engine(_resolved_db_url())
    init_db(engine)
    sf = make_session_factory(engine)
    runner = Runner(sf)
    with session_scope(sf) as s:
        run = repo.get_run(s, run_id_or_prefix)
        if run is None and len(run_id_or_prefix) < 32:
            matches = [r for r in repo.list_runs(s, limit=200) if r.id.startswith(run_id_or_prefix)]
            if len(matches) == 1:
                run = matches[0]
            elif len(matches) > 1:
                raise click.ClickException(
                    f"prefix {run_id_or_prefix!r} matches {len(matches)} runs — use the full id"
                )
        if run is None:
            raise click.ClickException(f"run {run_id_or_prefix!r} not found")
        if run.status != "paused":
            raise click.ClickException(
                f"run is {run.status!r}, not paused — nothing to approve / reject"
            )
        wf_row = run.workflow
        if wf_row is None or not wf_row.yaml_source:
            raise click.ClickException("run has no associated workflow YAML — cannot resume")
        wf = load_workflow_from_source(wf_row.yaml_source)
        return runner, run.id, wf


@main.command()
@click.argument("run_id")
@click.option(
    "--secret",
    "secret_pairs",
    multiple=True,
    metavar="KEY=VAL",
    help="Provide secrets needed by remaining steps (repeatable).",
)
def approve(run_id: str, secret_pairs: tuple[str, ...]) -> None:
    """Approve a paused run and resume it."""
    runner, full_id, wf = _resolve_and_load(run_id)
    secrets = _parse_kv_pairs(secret_pairs)
    result = runner.resume(wf, run_id=full_id, approved=True, secrets=secrets)
    _echo_result(result)
    if result.status == "failed":
        raise click.exceptions.Exit(1)


@main.command()
@click.argument("run_id")
def reject(run_id: str) -> None:
    """Reject a paused run and mark it cancelled."""
    runner, full_id, wf = _resolve_and_load(run_id)
    result = runner.resume(wf, run_id=full_id, approved=False)
    _echo_result(result)


if __name__ == "__main__":
    main()
