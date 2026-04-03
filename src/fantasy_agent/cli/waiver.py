import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Waiver wire analysis commands")
console = Console()


def _build_services(platform: str):
    import os
    import yaml
    from ..connectors.sleeper import SleeperConnector
    from ..connectors.fantasypros import FantasyProsConnector
    from ..services.data_aggregator import DataAggregator
    from ..models.league import LeagueSettings
    from ..ai.client import FantasyAIClient
    from .utils import load_env, get_config_dir

    load_env()
    config_dir = get_config_dir()

    with open(config_dir / "leagues.yaml") as f:
        cfg = yaml.safe_load(f)

    sleeper = SleeperConnector()
    fps = FantasyProsConnector()
    ai = FantasyAIClient(api_key=os.environ["ANTHROPIC_API_KEY"])

    if platform == "espn":
        from ..connectors.espn import ESPNConnector
        connector = ESPNConnector(
            league_id=int(os.environ["ESPN_LEAGUE_ID"]),
            swid=os.environ["ESPN_SWID"],
            espn_s2=os.environ["ESPN_S2"],
            team_id=int(os.environ.get("ESPN_TEAM_ID", "1")),
        )
        settings = LeagueSettings.from_yaml(cfg.get("espn", {}), platform="espn")
    else:
        from ..connectors.yahoo import YahooConnector
        connector = YahooConnector(
            client_id=os.environ["YAHOO_CLIENT_ID"],
            client_secret=os.environ["YAHOO_CLIENT_SECRET"],
            league_id=os.environ["YAHOO_LEAGUE_ID"],
            team_key=os.environ["YAHOO_TEAM_KEY"],
        )
        settings = LeagueSettings.from_yaml(cfg.get("yahoo", {}), platform="yahoo")

    aggregator = DataAggregator(
        espn=connector if platform == "espn" else None,
        yahoo=connector if platform == "yahoo" else None,
        sleeper=sleeper,
        fps=fps,
        scoring="std",
    )
    return connector, aggregator, sleeper, ai, settings


@app.command("analyze")
def waiver_analyze(
    platform: str = typer.Option("espn", help="espn or yahoo"),
    week: int = typer.Option(None, help="Week number"),
    position: str = typer.Option(None, "--position", "-p", help="QB/RB/WR/TE/K/DST"),
    limit: int = typer.Option(20, help="Top N free agents to consider"),
    waiver_priority: int = typer.Option(1, "--priority", help="Your waiver priority number"),
):
    """
    Analyze the waiver wire and get pickup recommendations with drop targets.

    Example:
        fantasy waiver analyze
        fantasy waiver analyze --position WR --limit 15
        fantasy waiver analyze --platform yahoo --priority 4
    """
    from ..services.waiver_service import WaiverService

    connector, aggregator, sleeper, ai, settings = _build_services(platform)
    week = week or connector.get_current_week()

    console.print(f"[dim]Analyzing waiver wire — Week {week} ({platform.upper()}, Standard)...[/]\n")
    svc = WaiverService(connector, aggregator, sleeper, ai, settings)
    svc.analyze(week=week, position=position, limit=limit, waiver_priority=waiver_priority)


@app.command("trending")
def waiver_trending(
    hours: int = typer.Option(24, help="Lookback window in hours"),
    limit: int = typer.Option(20, help="Number of players to show"),
):
    """
    Show trending adds from Sleeper across all leagues (buzz indicator).

    Example:
        fantasy waiver trending
        fantasy waiver trending --hours 48 --limit 30
    """
    from ..connectors.sleeper import SleeperConnector

    sleeper = SleeperConnector()
    trending = sleeper.get_trending_adds(lookback_hours=hours, limit=limit)

    table = Table(title=f"Trending Adds — Last {hours}h (Sleeper)", show_lines=False)
    table.add_column("#", width=4, style="dim")
    table.add_column("Name", min_width=18)
    table.add_column("Pos", width=5)
    table.add_column("Team", width=6)
    table.add_column("Adds", width=8, justify="right")

    for i, p in enumerate(trending, 1):
        table.add_row(
            str(i),
            p.get("name", ""),
            p.get("position", ""),
            p.get("team", ""),
            f"{p.get('add_count', 0):,}",
        )
    console.print(table)
