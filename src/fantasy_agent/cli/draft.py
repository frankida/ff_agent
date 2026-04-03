import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Draft mode commands")
console = Console()


def _make_services(platform: str = "espn"):
    """Build connector + aggregator + AI client from env/config."""
    import os
    from pathlib import Path
    from dotenv import load_dotenv
    from ..connectors.espn import ESPNConnector
    from ..connectors.sleeper import SleeperConnector
    from ..connectors.fantasypros import FantasyProsConnector
    from ..services.data_aggregator import DataAggregator
    from ..ai.client import FantasyAIClient

    config_dir = Path(__file__).parents[4] / "config"
    load_dotenv(config_dir / ".env")

    sleeper = SleeperConnector()
    fps = FantasyProsConnector()
    ai = FantasyAIClient(api_key=os.environ["ANTHROPIC_API_KEY"])

    if platform == "espn":
        connector = ESPNConnector(
            league_id=int(os.environ["ESPN_LEAGUE_ID"]),
            swid=os.environ["ESPN_SWID"],
            espn_s2=os.environ["ESPN_S2"],
            team_id=int(os.environ.get("ESPN_TEAM_ID", "1")),
        )
    else:
        from ..connectors.yahoo import YahooConnector
        connector = YahooConnector(
            client_id=os.environ["YAHOO_CLIENT_ID"],
            client_secret=os.environ["YAHOO_CLIENT_SECRET"],
            league_id=os.environ["YAHOO_LEAGUE_ID"],
            team_key=os.environ["YAHOO_TEAM_KEY"],
        )

    aggregator = DataAggregator(
        espn=connector if platform == "espn" else None,
        yahoo=connector if platform == "yahoo" else None,
        sleeper=sleeper,
        fps=fps,
        scoring="std",
    )
    return connector, aggregator, ai


@app.command("start")
def draft_start(
    platform: str = typer.Option("espn", help="espn or yahoo"),
    pick_position: int = typer.Option(..., prompt="Your draft position (1–12)"),
    total_teams: int = typer.Option(10, help="Total teams in your league"),
    total_rounds: int = typer.Option(15, help="Total draft rounds"),
    resume: bool = typer.Option(False, "--resume", help="Resume a saved draft session"),
    mock: bool = typer.Option(False, "--mock", help="Mock mode: simulate opponents, no ESPN needed"),
    auto_sync: bool = typer.Option(True, "--auto-sync/--no-auto-sync",
                                   help="Auto-detect opponent picks from ESPN (live draft only)"),
    poll_interval: int = typer.Option(20, "--poll", help="ESPN poll interval in seconds"),
):
    """
    Launch interactive draft assistant.

    LIVE DRAFT (default):
      Polls ESPN every 20s and auto-records opponent picks.
      You only need to type your own picks.

    MOCK DRAFT (--mock):
      Simulates opponents picking in ADP order. Great for practice
      and testing before your real draft day.

    Commands during the draft:
      [bold]next[/]        — Get Claude's pick recommendation
      [bold]pick NAME[/]   — Record your pick
      [bold]board[/]       — Show available player board
      [bold]board RB[/]    — Filter board by position
      [bold]roster[/]      — Show your current roster
      [bold]q[/]           — Quit
    """
    from ..services.draft_service import DraftService
    from ..services.draft_sync import DraftSyncService, MockDraftSimulator

    connector, aggregator, ai = _make_services(platform) if not mock else (None, *_make_aggregator_only())

    if mock:
        _run_mock_draft(aggregator, ai, pick_position, total_teams, total_rounds)
        return

    # ── Live draft ────────────────────────────────────────────────────────────
    if resume:
        service = DraftService.resume(aggregator=aggregator, ai=ai)
        if not service:
            console.print("[red]No saved draft state found.[/] Starting fresh.")
            service = None
    else:
        service = None

    if service is None:
        service = DraftService(
            aggregator=aggregator, ai=ai,
            pick_position=pick_position,
            total_teams=total_teams,
            total_rounds=total_rounds,
        )
        service.initialize()

    if auto_sync:
        _run_live_draft_autosync(service, connector, poll_interval)
    else:
        _run_live_draft_manual(service, platform, pick_position)


def _make_aggregator_only():
    """Build aggregator + AI without a league connector (for mock mode)."""
    import os
    from pathlib import Path
    from dotenv import load_dotenv
    from ..connectors.sleeper import SleeperConnector
    from ..connectors.fantasypros import FantasyProsConnector
    from ..services.data_aggregator import DataAggregator
    from ..ai.client import FantasyAIClient

    config_dir = Path(__file__).parents[4] / "config"
    load_dotenv(config_dir / ".env")

    aggregator = DataAggregator(
        espn=None, yahoo=None,
        sleeper=SleeperConnector(),
        fps=FantasyProsConnector(),
        scoring="std",
    )
    ai = FantasyAIClient(api_key=os.environ["ANTHROPIC_API_KEY"])
    return aggregator, ai


# ── Live draft with auto-sync ─────────────────────────────────────────────────

def _run_live_draft_autosync(service, connector, poll_interval: int):
    """
    Live draft with background ESPN polling.
    Opponent picks are detected automatically; user only inputs their own picks.
    """
    from ..services.draft_sync import DraftSyncService

    console.print(
        f"\n[bold green]Live Draft — Auto-Sync ON[/] "
        f"(polling ESPN every {poll_interval}s)\n"
        f"You only need to type [bold]your own picks[/].\n"
        f"Commands: [bold]next[/] | [bold]pick NAME[/] | [bold]board[/] | [bold]roster[/] | [bold]q[/]\n"
    )

    def on_opponent_pick(player, round_num, pick_num):
        console.print(
            f"  [dim]R{round_num}P{pick_num}[/] "
            f"[cyan]Auto-recorded:[/] {player.name} "
            f"({player.position.value}, {player.nfl_team})"
        )

    def on_your_turn(round_num, overall_pick):
        console.print(
            f"\n[bold yellow blink]>>> YOUR PICK — Round {round_num}, "
            f"Overall #{overall_pick} <<<[/]"
        )

    sync = DraftSyncService(
        connector=connector,
        state=service.state,
        player_pool=service._player_pool,
        poll_interval=poll_interval,
        on_opponent_pick=on_opponent_pick,
        on_your_turn=on_your_turn,
    )
    sync.start()

    try:
        while not service.state.is_complete():
            if service.state.is_my_pick():
                # Auto-get recommendation then wait for input
                service.get_recommendation()
                cmd = typer.prompt("\n>").strip().lower()

                if cmd == "q":
                    break
                elif cmd == "next":
                    service.get_recommendation()
                elif cmd.startswith("pick "):
                    name = cmd[5:].strip()
                    service.record_my_pick(name)
                elif cmd == "board" or cmd.startswith("board "):
                    parts = cmd.split()
                    _show_board(service.show_board(position=parts[1].upper() if len(parts) > 1 else None))
                elif cmd == "roster":
                    _show_my_roster(service.show_my_roster())
                else:
                    console.print("  Commands: next | pick NAME | board [POS] | roster | q")
            else:
                # Waiting for opponent picks — poll loop handles it
                console.print(
                    f"  [dim]Waiting for picks... "
                    f"(R{service.state.current_round} P{service.state.pick_in_round})[/]",
                    end="\r",
                )
                # Check for manual override commands while waiting
                import select, sys
                if select.select([sys.stdin], [], [], poll_interval)[0]:
                    cmd = input().strip().lower()
                    if cmd == "q":
                        break
                    elif cmd == "board" or cmd.startswith("board "):
                        parts = cmd.split()
                        _show_board(service.show_board(
                            position=parts[1].upper() if len(parts) > 1 else None
                        ))
                    elif cmd.startswith("draft "):
                        # Manual override if auto-sync misses a pick
                        name = cmd[6:].strip()
                        p = service.record_opponent_pick(name)
                        if p:
                            console.print(f"  Manually recorded: {p.name}")
    finally:
        sync.stop()

    console.print("\n[bold green]Draft complete![/]")
    _show_my_roster(service.show_my_roster())


# ── Live draft manual fallback ────────────────────────────────────────────────

def _run_live_draft_manual(service, platform: str, pick_position: int):
    """Original manual mode — type all picks yourself."""
    console.print(
        f"\n[bold green]Draft mode active[/] | {platform.upper()} | Position #{pick_position}"
        f"\nCommands: [bold]next[/] | [bold]pick NAME[/] | [bold]draft NAME[/] | "
        f"[bold]board[/] | [bold]roster[/] | [bold]q[/]\n"
    )

    while not service.state.is_complete():
        if service.state.is_my_pick():
            console.print(
                f"[bold yellow]>>> YOUR PICK — Round {service.state.current_round}, "
                f"#{service.state.overall_pick}[/]"
            )
        cmd = typer.prompt(f"R{service.state.current_round}P{service.state.pick_in_round}>").strip()

        if cmd == "q":
            break
        elif cmd == "next":
            service.get_recommendation()
        elif cmd == "board" or cmd.startswith("board "):
            parts = cmd.split()
            _show_board(service.show_board(position=parts[1].upper() if len(parts) > 1 else None))
        elif cmd == "roster":
            _show_my_roster(service.show_my_roster())
        elif cmd.lower().startswith("pick "):
            service.record_my_pick(cmd[5:].strip())
        elif cmd.lower().startswith("draft "):
            p = service.record_opponent_pick(cmd[6:].strip())
            if p:
                console.print(f"  Recorded: {p.name}")
        elif cmd == "help":
            console.print("next | pick NAME | draft NAME | board [POS] | roster | q")
        else:
            console.print(f"  Unknown: '{cmd}'. Type 'help'.")

    console.print("\n[bold]Draft complete![/]")
    _show_my_roster(service.show_my_roster())


# ── Mock draft ────────────────────────────────────────────────────────────────

def _run_mock_draft(aggregator, ai, pick_position: int, total_teams: int, total_rounds: int):
    """
    Full mock draft simulation. Opponents auto-pick top ADP; you pick interactively.
    Great for practice and testing before draft day.
    """
    from ..services.draft_service import DraftService
    from ..services.draft_sync import MockDraftSimulator

    service = DraftService(
        aggregator=aggregator, ai=ai,
        pick_position=pick_position,
        total_teams=total_teams,
        total_rounds=total_rounds,
    )
    service.initialize()
    simulator = MockDraftSimulator(
        state=service.state,
        player_pool=service._player_pool,
        opponent_speed=0.1,   # fast in mock mode
    )

    console.print(
        f"\n[bold cyan]Mock Draft[/] | {total_teams} teams | "
        f"Position #{pick_position} | Standard Scoring\n"
        f"Opponents auto-pick in ADP order.\n"
        f"Commands: [bold]next[/] | [bold]pick NAME[/] | [bold]board[/] | [bold]roster[/] | [bold]q[/]\n"
    )

    round_num = 0
    while not service.state.is_complete():
        if service.state.current_round != round_num:
            round_num = service.state.current_round
            console.print(f"\n[bold]─── Round {round_num} ───[/]")

        # Simulate opponents until it's our turn
        def print_opp_pick(player, r, pk):
            console.print(
                f"  [dim]Pick {pk:2}[/] {player.name:<22} "
                f"[dim]{player.position.value}, {player.nfl_team}[/]"
            )

        simulator.simulate_opponents_until_my_pick(on_opponent_pick=print_opp_pick)

        if service.state.is_complete():
            break

        # Our pick
        console.print(
            f"\n[bold yellow]>>> YOUR PICK — Round {service.state.current_round}, "
            f"Overall #{service.state.overall_pick}[/]"
        )
        service.get_recommendation()

        cmd = typer.prompt("\n>").strip().lower()
        if cmd == "q":
            break
        elif cmd == "next":
            service.get_recommendation()
            cmd = typer.prompt(">").strip().lower()

        if cmd.startswith("pick "):
            name = cmd[5:].strip()
            player = service._find_player(name)
            if player:
                simulator.record_user_pick(player)
                console.print(f"  [green]Drafted:[/] {player.name} ({player.position.value})")
            else:
                console.print(f"  [red]Player '{name}' not found.[/] Try again or type 'board'.")
        elif cmd == "board" or cmd.startswith("board "):
            parts = cmd.split()
            _show_board(service.show_board(position=parts[1].upper() if len(parts) > 1 else None))
        elif cmd == "roster":
            _show_my_roster(service.show_my_roster())

    console.print("\n[bold green]Mock draft complete![/]")
    _show_my_roster(service.show_my_roster())


# ── Other commands ────────────────────────────────────────────────────────────

@app.command("board")
def draft_board(
    position: str = typer.Option(None, "--position", "-p", help="Filter: QB/RB/WR/TE/K/DST"),
    limit: int = typer.Option(30, help="Number of players to show"),
):
    """
    Show top available players by consensus ADP (standard scoring).

    Example:
        fantasy draft board
        fantasy draft board --position RB --limit 20
    """
    from ..services.draft_service import DraftService
    _, aggregator, ai = _make_aggregator_only()
    service = DraftService(aggregator=aggregator, ai=ai, pick_position=1, total_teams=10)
    service.initialize()
    _show_board(service.show_board(position=position, limit=limit))


@app.command("analyze")
def draft_analyze(
    player: str = typer.Argument(..., help="Player name to analyze"),
):
    """
    Deep analysis of a single player for draft consideration.

    Example:
        fantasy draft analyze "Derrick Henry"
    """
    from ..services.trade_service import TradeService
    import yaml
    from pathlib import Path

    _, aggregator, ai = _make_aggregator_only()
    config_dir = Path(__file__).parents[4] / "config"
    with open(config_dir / "leagues.yaml") as f:
        cfg = yaml.safe_load(f)
    from ..models.league import LeagueSettings
    settings = LeagueSettings.from_yaml(cfg.get("espn", {}), platform="espn")

    connector, _, _ = _make_services()
    trade_svc = TradeService(connector=connector, aggregator=aggregator, ai=ai, settings=settings)
    trade_svc.player_value(player_name=player, week=1)


# ── Display helpers ───────────────────────────────────────────────────────────

def _show_board(players):
    from ..models.player import InjuryStatus
    table = Table(title="Draft Board — Standard Scoring", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Name", min_width=18)
    table.add_column("Pos", width=5)
    table.add_column("Team", width=6)
    table.add_column("ADP", width=7)
    table.add_column("FP Rank", width=8)
    table.add_column("Status", width=14)

    for i, p in enumerate(players, 1):
        if p.injury_status == InjuryStatus.ACTIVE:
            style = ""
        elif p.injury_status in (InjuryStatus.OUT, InjuryStatus.IR, InjuryStatus.DOUBTFUL):
            style = "red"
        else:
            style = "yellow"

        table.add_row(
            str(i), p.name, p.position.value, p.nfl_team,
            f"{p.adp:.1f}" if p.adp < 999 else "-",
            str(p.positional_rank) if p.positional_rank else "-",
            p.injury_status.value,
            style=style or None,
        )
    console.print(table)


def _show_my_roster(players):
    table = Table(title="Your Draft Roster", show_lines=False)
    table.add_column("Pick", style="dim", width=5)
    table.add_column("Name", min_width=18)
    table.add_column("Pos", width=5)
    table.add_column("Team", width=6)
    for i, p in enumerate(players, 1):
        table.add_row(str(i), p.name, p.position.value, p.nfl_team)
    console.print(table)
