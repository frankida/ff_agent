import typer
from rich.console import Console

app = typer.Typer(help="Trade analyzer commands")
console = Console()


def _build_services(platform: str):
    import os
    from pathlib import Path
    import yaml
    from dotenv import load_dotenv
    from ..connectors.sleeper import SleeperConnector
    from ..connectors.fantasypros import FantasyProsConnector
    from ..services.data_aggregator import DataAggregator
    from ..models.league import LeagueSettings
    from ..ai.client import FantasyAIClient

    config_dir = Path(__file__).parents[4] / "config"
    load_dotenv(config_dir / ".env")

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
    return connector, aggregator, ai, settings


@app.command("analyze")
def trade_analyze(
    give: str = typer.Option(..., "--give", "-g", help="Players you're giving (comma-separated)"),
    receive: str = typer.Option(..., "--receive", "-r", help="Players you're receiving (comma-separated)"),
    platform: str = typer.Option("espn", help="espn or yahoo"),
    week: int = typer.Option(None, help="Current week"),
):
    """
    Analyze a proposed trade — get Accept / Reject / Counter verdict.

    Examples:
        fantasy trade analyze --give "Derrick Henry" --receive "Ja'Marr Chase"

        fantasy trade analyze \\
            --give "Travis Kelce, Isiah Pacheco" \\
            --receive "Sam LaPorta, Tony Pollard"
    """
    from ..services.trade_service import TradeService

    connector, aggregator, ai, settings = _build_services(platform)
    week = week or connector.get_current_week()

    giving_names = [n.strip() for n in give.split(",")]
    receiving_names = [n.strip() for n in receive.split(",")]

    console.print(f"\n[dim]Trade Analysis — {platform.upper()} — Week {week} — Standard Scoring[/]")
    console.print(f"[red]You give:[/]    {', '.join(giving_names)}")
    console.print(f"[green]You receive:[/] {', '.join(receiving_names)}\n")

    svc = TradeService(connector, aggregator, ai, settings)
    svc.analyze_trade(
        giving_names=giving_names,
        receiving_names=receiving_names,
        week=week,
    )


@app.command("value")
def player_value(
    player: str = typer.Argument(..., help="Player name to evaluate"),
    platform: str = typer.Option("espn", help="espn or yahoo"),
    week: int = typer.Option(None, help="Current week"),
):
    """
    Get rest-of-season trade value and buy/sell/hold recommendation.

    Example:
        fantasy trade value "Davante Adams"
        fantasy trade value "Josh Allen"
    """
    from ..services.trade_service import TradeService

    connector, aggregator, ai, settings = _build_services(platform)
    week = week or connector.get_current_week()

    console.print(f"\n[dim]Player Analysis: {player} — Week {week} — Standard Scoring[/]\n")
    svc = TradeService(connector, aggregator, ai, settings)
    svc.player_value(player_name=player, week=week)
