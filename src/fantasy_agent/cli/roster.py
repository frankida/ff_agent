import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Roster management commands")
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


@app.command("view")
def view_roster(
    platform: str = typer.Option("espn", help="espn or yahoo"),
    week: int = typer.Option(None, help="Week number (defaults to current)"),
):
    """
    Display your current roster with projections and injury status.

    Example:
        fantasy roster view
        fantasy roster view --platform yahoo
    """
    from ..services.roster_service import RosterService

    connector, aggregator, ai, settings = _build_services(platform)
    current_week = connector.get_current_week()
    week = week or current_week

    svc = RosterService(connector, aggregator, ai, settings)
    roster = svc.get_roster(week=week)

    _display_roster(roster, week)


@app.command("start-sit")
def start_sit(
    platform: str = typer.Option("espn", help="espn or yahoo"),
    week: int = typer.Option(None, help="Week number"),
    position: str = typer.Option(None, "--position", "-p", help="Focus on a position: QB/RB/WR/TE"),
):
    """
    Get Claude's optimal starting lineup recommendation.

    Example:
        fantasy roster start-sit
        fantasy roster start-sit --position RB
        fantasy roster start-sit --platform yahoo --week 12
    """
    from ..services.roster_service import RosterService

    connector, aggregator, ai, settings = _build_services(platform)
    current_week = connector.get_current_week()
    week = week or current_week

    console.print(f"[dim]Analyzing Week {week} lineup ({platform.upper()}, Standard Scoring)...[/]\n")
    svc = RosterService(connector, aggregator, ai, settings)
    svc.start_sit_analysis(week=week, position=position)


@app.command("matchup")
def matchup(
    platform: str = typer.Option("espn", help="espn or yahoo"),
    week: int = typer.Option(None, help="Week number"),
):
    """
    Preview this week's matchup with projected scores and key analysis.

    Example:
        fantasy roster matchup
        fantasy roster matchup --week 14
    """
    from ..services.roster_service import RosterService

    connector, aggregator, ai, settings = _build_services(platform)
    current_week = connector.get_current_week()
    week = week or current_week

    console.print(f"[dim]Loading Week {week} matchup ({platform.upper()})...[/]\n")
    svc = RosterService(connector, aggregator, ai, settings)
    svc.matchup_preview(week=week)


# ── Display helpers ───────────────────────────────────────────────────────────

def _display_roster(roster, week: int):
    from ..models.player import InjuryStatus

    table = Table(
        title=f"{roster.team_name} — Week {week} ({roster.platform.upper()}, Standard)",
        show_lines=False,
    )
    table.add_column("Pos", width=5)
    table.add_column("Name", min_width=18)
    table.add_column("Team", width=6)
    table.add_column("Proj", width=6)
    table.add_column("Avg", width=6)
    table.add_column("ADP", width=7)
    table.add_column("Status", width=16)

    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        for p in roster.players:
            if p.position.value != pos:
                continue
            injury = p.injury_status
            if injury == InjuryStatus.ACTIVE:
                status_str = "Active"
                row_style = ""
            elif injury in (InjuryStatus.OUT, InjuryStatus.IR):
                detail = f" - {p.injury_detail}" if p.injury_detail else ""
                status_str = f"{injury.value}{detail}"
                row_style = "red"
            elif injury == InjuryStatus.DOUBTFUL:
                status_str = f"Doubtful"
                row_style = "red"
            elif injury == InjuryStatus.QUESTIONABLE:
                detail = f" - {p.injury_detail}" if p.injury_detail else ""
                status_str = f"Q{detail}"
                row_style = "yellow"
            else:
                status_str = injury.value
                row_style = ""

            bye_flag = f" [BYE {p.bye_week}]" if p.is_on_bye else ""
            proj = f"{p.projected_points:.1f}" if p.projected_points else "-"
            avg = f"{p.stats.avg_points_per_game:.1f}" if p.stats.avg_points_per_game else "-"
            adp = f"{p.adp:.1f}" if p.adp < 999 else "-"

            table.add_row(
                pos, p.name + bye_flag, p.nfl_team,
                proj, avg, adp, status_str,
                style=row_style or None,
            )

    console.print(table)
