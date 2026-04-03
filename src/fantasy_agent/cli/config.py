import os
import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .utils import load_env, get_config_dir

app = typer.Typer(help="Configuration and setup commands")
console = Console()


def _config_dir():
    return get_config_dir()


def _env_path():
    return _config_dir() / ".env"


def _yaml_path():
    return _config_dir() / "leagues.yaml"


@app.command("setup")
def setup():
    """Interactive first-run setup wizard."""
    console.print(Panel(
        "[bold cyan]Fantasy Football Agent Setup[/]\n"
        "This will configure your ESPN and Yahoo league connections.",
        border_style="cyan",
    ))

    # ── ESPN ────────────────────────────────────────────────────────────────
    console.print("\n[bold yellow]ESPN Setup[/] (your money league)")
    console.print(
        "To get your ESPN cookies:\n"
        "  1. Open [link=https://fantasy.espn.com]fantasy.espn.com[/link] and log in\n"
        "  2. Open Chrome DevTools (F12) → Application → Cookies → espn.com\n"
        "  3. Copy the values for [bold]SWID[/] and [bold]espn_s2[/]"
    )
    espn_swid = typer.prompt("\nESPN SWID (include the curly braces)")
    espn_s2 = typer.prompt("ESPN_S2 cookie value")
    espn_league_id = typer.prompt("ESPN League ID (number in the URL)")
    espn_team_id = typer.prompt("Your ESPN team number (1–12, check standings page)", default="1")

    # ── Yahoo ───────────────────────────────────────────────────────────────
    console.print("\n[bold yellow]Yahoo Setup[/]")
    setup_yahoo = typer.confirm("Do you also want to set up Yahoo?", default=True)
    yahoo_client_id = yahoo_client_secret = yahoo_league_id = yahoo_team_key = ""
    if setup_yahoo:
        console.print(
            "Create a Yahoo app at [link=https://developer.yahoo.com/apps/create/]"
            "developer.yahoo.com/apps/create/[/link]\n"
            "  - Application Name: anything (e.g. 'Fantasy Agent')\n"
            "  - API Permissions: Fantasy Sports → Read/Write"
        )
        yahoo_client_id = typer.prompt("\nYahoo Client ID")
        yahoo_client_secret = typer.prompt("Yahoo Client Secret")
        yahoo_league_id = typer.prompt("Yahoo League ID (e.g. nfl.l.1234567)")
        yahoo_team_key = typer.prompt("Yahoo Team Key (e.g. nfl.l.1234567.t.4)")

    # ── Anthropic ───────────────────────────────────────────────────────────
    console.print("\n[bold yellow]Claude API[/]")
    console.print("Get your key at [link=https://console.anthropic.com]console.anthropic.com[/link]")
    anthropic_key = typer.prompt("Anthropic API Key")

    # ── Write .env ──────────────────────────────────────────────────────────
    cfg_dir = _config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env_path = _env_path()
    yaml_path = _yaml_path()
    env_content = f"""# ESPN
ESPN_SWID={espn_swid}
ESPN_S2={espn_s2}
ESPN_LEAGUE_ID={espn_league_id}
ESPN_TEAM_ID={espn_team_id}

# Yahoo
YAHOO_CLIENT_ID={yahoo_client_id}
YAHOO_CLIENT_SECRET={yahoo_client_secret}
YAHOO_LEAGUE_ID={yahoo_league_id}
YAHOO_TEAM_KEY={yahoo_team_key}

# Claude
ANTHROPIC_API_KEY={anthropic_key}

# FantasyPros (optional)
FANTASYPROS_API_KEY=
"""
    env_path.write_text(env_content)
    console.print(f"\n[green]✓[/] Config written to {env_path}")

    # Update leagues.yaml with league/team IDs
    if yaml_path.exists():
        with open(yaml_path) as f:
            league_config = yaml.safe_load(f)
    else:
        league_config = {"espn": {}, "yahoo": {}}

    league_config["espn"]["league_id"] = int(espn_league_id)
    league_config["espn"]["team_id"] = int(espn_team_id)
    if setup_yahoo:
        league_config["yahoo"]["league_id"] = yahoo_league_id
        league_config["yahoo"]["team_key"] = yahoo_team_key

    with open(yaml_path, "w") as f:
        yaml.dump(league_config, f, default_flow_style=False)
    console.print(f"[green]✓[/] League config written to {yaml_path}")

    console.print(
        "\n[bold green]Setup complete![/] Run [bold]fantasy config verify[/] to test connections."
    )


@app.command("verify")
def verify():
    """Test all API connections."""
    from ..connectors.espn import ESPNConnector
    from ..connectors.sleeper import SleeperConnector
    from ..connectors.fantasypros import FantasyProsConnector
    from ..ai.client import FantasyAIClient

    load_env()

    checks = []

    # ESPN
    try:
        espn = ESPNConnector(
            league_id=int(os.environ["ESPN_LEAGUE_ID"]),
            swid=os.environ["ESPN_SWID"],
            espn_s2=os.environ["ESPN_S2"],
            team_id=int(os.environ.get("ESPN_TEAM_ID", "1")),
        )
        league = espn._get_league()
        checks.append(("[green]OK[/]", "ESPN", f"Connected to '{league.settings.name}'"))
    except Exception as e:
        checks.append(("[red]FAIL[/]", "ESPN", str(e)[:60]))

    # Yahoo (optional)
    yahoo_id = os.environ.get("YAHOO_CLIENT_ID", "")
    if yahoo_id:
        try:
            from ..connectors.yahoo import YahooConnector
            yahoo = YahooConnector(
                client_id=yahoo_id,
                client_secret=os.environ.get("YAHOO_CLIENT_SECRET", ""),
                league_id=os.environ.get("YAHOO_LEAGUE_ID", ""),
                team_key=os.environ.get("YAHOO_TEAM_KEY", ""),
            )
            week = yahoo.get_current_week()
            checks.append(("[green]OK[/]", "Yahoo", f"Connected (week {week})"))
        except Exception as e:
            checks.append(("[red]FAIL[/]", "Yahoo", str(e)[:60]))
    else:
        checks.append(("[dim]SKIP[/]", "Yahoo", "Not configured"))

    # Claude
    try:
        ai = FantasyAIClient(api_key=os.environ["ANTHROPIC_API_KEY"])
        ok = ai.ping()
        checks.append(
            ("[green]OK[/]" if ok else "[red]FAIL[/]", "Claude", "claude-sonnet-4-6 responding")
        )
    except Exception as e:
        checks.append(("[red]FAIL[/]", "Claude", str(e)[:60]))

    # Sleeper
    try:
        sleeper = SleeperConnector()
        players = sleeper.get_all_players()
        checks.append(("[green]OK[/]", "Sleeper", f"{len(players):,} players available"))
    except Exception as e:
        checks.append(("[red]FAIL[/]", "Sleeper", str(e)[:60]))

    # FantasyPros
    try:
        fps = FantasyProsConnector()
        adp = fps.get_adp(scoring="std")
        checks.append(
            ("[green]OK[/]" if adp else "[yellow]WARN[/]",
             "FantasyPros",
             f"ADP loaded ({len(adp)} players)" if adp else "No data returned (will use scraping)")
        )
    except Exception as e:
        checks.append(("[yellow]WARN[/]", "FantasyPros", str(e)[:60]))

    console.print("\n[bold]Connection Status:[/]")
    for status, name, detail in checks:
        console.print(f"  [{status}] {name:<14} {detail}")
    console.print()


@app.command("show")
def show():
    """Print current configuration (secrets redacted)."""
    load_env()

    console.print("\n[bold]Current Configuration:[/]")
    keys_to_show = [
        "ESPN_LEAGUE_ID", "ESPN_TEAM_ID", "ESPN_SWID",
        "YAHOO_LEAGUE_ID", "YAHOO_TEAM_KEY",
        "ANTHROPIC_API_KEY",
    ]
    for key in keys_to_show:
        val = os.environ.get(key, "(not set)")
        if val and len(val) > 12 and key not in ("ESPN_LEAGUE_ID", "ESPN_TEAM_ID", "YAHOO_LEAGUE_ID"):
            val = val[:6] + "..." + val[-4:]  # Redact secrets
        console.print(f"  {key}: {val}")
