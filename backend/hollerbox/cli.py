"""HollerBox CLI entry point.

Phase 0 wired `--help` and `version`. Phase 1a adds `validate`. Real
execution commands (`run`, `runs`, `run-detail`) land in Phase 1e.
"""

from __future__ import annotations

from pathlib import Path

import click

from hollerbox import __version__
from hollerbox.core.templating import find_references
from hollerbox.core.workflow import (
    WorkflowLoadError,
    load_workflow,
    load_workflows_dir,
)


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


@main.command()
@click.argument(
    "path",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--show-refs",
    is_flag=True,
    help="Print every ${...} reference each workflow makes.",
)
def validate(path: Path, show_refs: bool) -> None:
    """Validate one workflow YAML file or every workflow in a directory.

    Exits non-zero if any workflow fails to load or validate.
    """
    workflows: dict[str, tuple[Path, object]] = {}
    failures: list[str] = []

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

    if failures:
        raise click.exceptions.Exit(1)


if __name__ == "__main__":
    main()
