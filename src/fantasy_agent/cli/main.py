import typer
from rich.console import Console
from . import draft, roster, waiver, trade, config
from ..cache.manager import clear_cache, cache_status

app = typer.Typer(
    name="fantasy",
    help="Fantasy football agent — ESPN + Yahoo | Standard Scoring | Powered by Claude",
    no_args_is_help=True,
)
console = Console()

app.add_typer(draft.app, name="draft")
app.add_typer(roster.app, name="roster")
app.add_typer(waiver.app, name="waiver")
app.add_typer(trade.app, name="trade")
app.add_typer(config.app, name="config")


@app.command("cache")
def cache_cmd(
    action: str = typer.Argument("status", help="status | clear"),
):
    """
    Manage the local data cache.

    Example:
        fantasy cache status
        fantasy cache clear
    """
    if action == "clear":
        clear_cache()
        console.print("[green]Cache cleared.[/]")
    elif action == "status":
        info = cache_status()
        console.print(f"Cache: {info['path']}")
        console.print(f"  Size:    {info['size_kb']} KB")
        console.print(f"  Active:  {info['active_entries']} entries")
        console.print(f"  Expired: {info['expired_entries']} entries")
    else:
        console.print(f"[red]Unknown action '{action}'.[/] Use 'status' or 'clear'.")


if __name__ == "__main__":
    app()
