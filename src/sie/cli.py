"""Command-line entry point. Sub-commands are added by later tasks (see TASKS.md)."""

import typer

from sie import __version__
from sie.config import get_settings
from sie.logging_setup import configure_logging
from sie.storage.db import ping

app = typer.Typer(help="SIE command-line tools", no_args_is_help=True)


@app.callback()
def main() -> None:
    """SIE command-line tools (policy, eval and ops commands arrive in later tasks)."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)


@app.command()
def version() -> None:
    """Print the installed SIE version."""
    typer.echo(__version__)


@app.command("db-ping")
def db_ping() -> None:
    """Check that the configured database answers (exit code 1 if not)."""
    if ping():
        typer.echo("database: ok")
    else:
        typer.echo("database: unreachable", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
