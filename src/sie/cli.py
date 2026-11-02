"""Command-line entry point. Sub-commands are added by later tasks (see TASKS.md)."""

import typer

from sie import __version__

app = typer.Typer(help="SIE command-line tools", no_args_is_help=True)


@app.callback()
def main() -> None:
    """SIE command-line tools (policy, eval and ops commands arrive in later tasks)."""


@app.command()
def version() -> None:
    """Print the installed SIE version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
