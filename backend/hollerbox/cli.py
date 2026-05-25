"""HollerBox CLI entry point.

Phase 0: only `--help` and `version` are wired. Real commands (`run`, `validate`,
`runs`, `run-detail`, `chat`) land in Phase 1.
"""

from __future__ import annotations

import click

from hollerbox import __version__


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


if __name__ == "__main__":
    main()
