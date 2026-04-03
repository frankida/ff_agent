import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Draft mode commands")
console = Console()


def _make_services(platform: str = "espn"):
    """Build connector + aggregator + DraftConversation from env/config."""
    import os
    from ..connectors.espn import ESPNConnector
    from ..connectors.sleeper import SleeperConnector
    from ..connectors.fantasypros import FantasyProsConnector
    from ..services.data_aggregator import DataAggregator
    from ..ai.client import DraftConversation
    from ..cli.utils import load_env

    load_env()

    sleeper = SleeperConnector()
    fps = FantasyProsConnector()
    conversation = DraftConversation(api_key=os.environ["ANTHROPIC_API_KEY"])

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
    return connector, aggregator, conversation


def _make_aggregator_only():
    """Build aggregator + DraftConversation without a league connector (for mock mode)."""
    import os
    from ..connectors.sleeper import SleeperConnector
    from ..connectors.fantasypros import FantasyProsConnector
    from ..services.data_aggregator import DataAggregator
    from ..ai.client import DraftConversation
    from ..cli.utils import load_env

    load_env()

    aggregator = DataAggregator(
        espn=None, yahoo=None,
        sleeper=SleeperConnector(),
        fps=FantasyProsConnector(),
        scoring="std",
    )
    conversation = DraftConversation(api_key=os.environ["ANTHROPIC_API_KEY"])
    return aggregator, conversation


@app.command("start")
def draft_start(
    platform: str = typer.Option("espn", help="espn or yahoo"),
    pick_position: int = typer.Option(..., prompt="Your draft position (1–12)"),
    total_teams: int = typer.Option(10, help="Total teams in your league"),
    total_rounds: int = typer.Option(15, help="Total draft rounds"),
    resume: bool = typer.Option(False, "--resume", help="Resume a saved draft session"),
    mock: bool = typer.Option(False, "--mock", help="Mock mode: simulate opponents, no ESPN needed"),
    bridge: bool = typer.Option(True, "--bridge/--no-bridge",
                                help="Use Chrome extension bridge for live pick sync"),
    bridge_port: int = typer.Option(5050, "--bridge-port", help="DraftBridge port"),
):
    """
    Launch interactive draft assistant.

    LIVE DRAFT (default, --bridge):
      Install the Chrome extension, open the ESPN draft room, then run this.
      Picks sync automatically from the browser — you only input your own.
      Free-form questions: just type anything that isn't a command.

    MOCK DRAFT (--mock):
      Simulates opponents picking in ADP order. Great for practice before draft day.

    Commands during the draft:
      [bold]next[/]           — Get Claude's pick recommendation
      [bold]pick NAME[/]      — Record your pick
      [bold]board[/]          — Show available player board
      [bold]board RB[/]       — Filter board by position
      [bold]roster[/]         — Show your current roster
      [bold]anything else[/]  — Ask Claude a free-form question
      [bold]q[/]              — Quit
    """
    from ..services.draft_service import DraftService

    if mock:
        aggregator, conversation = _make_aggregator_only()
        _run_mock_draft(aggregator, conversation, pick_position, total_teams, total_rounds)
        return

    connector, aggregator, conversation = _make_services(platform)

    if resume:
        service = DraftService.resume(aggregator=aggregator, conversation=conversation)
        if not service:
            console.print("[red]No saved draft state found.[/] Starting fresh.")
            service = None
    else:
        service = None

    if service is None:
        service = DraftService(
            aggregator=aggregator,
            conversation=conversation,
            pick_position=pick_position,
            total_teams=total_teams,
            total_rounds=total_rounds,
        )
        service.initialize()

    if bridge:
        _run_live_draft_bridge(service, connector, bridge_port)
    else:
        _run_live_draft_manual(service, platform, pick_position)


# ── Live draft with Chrome extension bridge ───────────────────────────────────

def _run_live_draft_bridge(service, connector, bridge_port: int):
    """
    Live draft mode — receives picks via DraftBridge from Chrome extension.
    Opponent picks update silently; user only inputs their own picks + questions.
    """
    from ..services.draft_bridge import DraftBridge
    import os

    my_team_id = int(os.environ.get("ESPN_TEAM_ID", "1"))

    console.print(
        f"\n[bold green]Live Draft — Chrome Bridge ON[/] (localhost:{bridge_port})\n"
        f"Make sure the Fantasy Agent Chrome extension is active in the draft room.\n"
        f"Commands: [bold]next[/] | [bold]pick NAME[/] | [bold]board[/] | "
        f"[bold]roster[/] | [bold]opponent NAME[/] | [bold]q[/]\n"
        f"  or just [bold]ask Claude anything[/] — type any question freely.\n"
    )

    pending_picks: list = []

    def on_opponent_pick(player, round_num, pick_num):
        pending_picks.append((player, round_num, pick_num))

    def on_your_turn(round_num, overall_pick):
        console.print(
            f"\n[bold yellow blink]>>> YOUR PICK — Round {round_num}, "
            f"Overall #{overall_pick} <<<[/]"
        )

    bridge = DraftBridge(
        state=service.state,
        player_pool=service._player_pool,
        port=bridge_port,
        on_opponent_pick=on_opponent_pick,
        on_your_turn=on_your_turn,
    )
    bridge.start()
    console.print(f"[dim]Bridge listening on localhost:{bridge_port}[/]")

    try:
        while not service.state.is_complete():
            # Flush any pending opponent picks that arrived in the background
            if pending_picks:
                for player, round_num, pick_num in pending_picks:
                    console.print(
                        f"  [dim]R{round_num}P{pick_num}[/] "
                        f"[cyan]Auto:[/] {player.name} "
                        f"({player.position.value}, {player.nfl_team})"
                    )
                    # Conversation context already injected by DraftBridge callback
                pending_picks.clear()

            if service.state.is_my_pick():
                # Auto-recommend then wait for user input
                service.get_recommendation()

            cmd = typer.prompt(
                f"\nR{service.state.current_round}P{service.state.pick_in_round}"
            ).strip()

            if not cmd:
                continue
            elif cmd.lower() == "q":
                break
            elif cmd.lower() == "next":
                service.get_recommendation()
            elif cmd.lower().startswith("pick "):
                name = cmd[5:].strip()
                service.record_my_pick(name)
            elif cmd.lower().startswith("opponent "):
                # Manual override if bridge missed a pick
                name = cmd[9:].strip()
                p = service.record_opponent_pick(name)
                if p:
                    console.print(f"  Manually recorded opponent: {p.name}")
            elif cmd.lower() == "board" or cmd.lower().startswith("board "):
                parts = cmd.split()
                _show_board(service.show_board(
                    position=parts[1].upper() if len(parts) > 1 else None
                ))
            elif cmd.lower() == "roster":
                _show_my_roster(service.show_my_roster())
            else:
                # Free-form question to Claude
                service.chat(cmd)

    finally:
        bridge.stop()

    console.print("\n[bold green]Draft complete![/]")
    _show_my_roster(service.show_my_roster())


# ── Live draft manual fallback ─────────────────────────────────────────────────

def _run_live_draft_manual(service, platform: str, pick_position: int):
    """Manual mode — type all picks yourself (no Chrome extension required)."""
    console.print(
        f"\n[bold green]Draft mode active[/] | {platform.upper()} | Position #{pick_position}"
        f"\nCommands: [bold]next[/] | [bold]pick NAME[/] | [bold]draft NAME[/] | "
        f"[bold]board[/] | [bold]roster[/] | [bold]q[/]\n"
        f"  or ask Claude anything — just type freely.\n"
    )

    while not service.state.is_complete():
        if service.state.is_my_pick():
            console.print(
                f"[bold yellow]>>> YOUR PICK — Round {service.state.current_round}, "
                f"#{service.state.overall_pick}[/]"
            )
        cmd = typer.prompt(
            f"R{service.state.current_round}P{service.state.pick_in_round}"
        ).strip()

        if not cmd:
            continue
        elif cmd.lower() == "q":
            break
        elif cmd.lower() == "next":
            service.get_recommendation()
        elif cmd.lower() == "board" or cmd.lower().startswith("board "):
            parts = cmd.split()
            _show_board(service.show_board(
                position=parts[1].upper() if len(parts) > 1 else None
            ))
        elif cmd.lower() == "roster":
            _show_my_roster(service.show_my_roster())
        elif cmd.lower().startswith("pick "):
            service.record_my_pick(cmd[5:].strip())
        elif cmd.lower().startswith("draft "):
            # Record opponent pick manually
            p = service.record_opponent_pick(cmd[6:].strip())
            if p:
                console.print(f"  Recorded opponent: {p.name}")
        elif cmd.lower() == "help":
            console.print(
                "next | pick NAME | draft NAME | board [POS] | roster | q\n"
                "  or type any question to ask Claude"
            )
        else:
            # Free-form question to Claude
            service.chat(cmd)

    console.print("\n[bold]Draft complete![/]")
    _show_my_roster(service.show_my_roster())


# ── Mock draft ─────────────────────────────────────────────────────────────────

def _run_mock_draft(aggregator, conversation, pick_position: int, total_teams: int, total_rounds: int):
    """
    Full mock draft simulation. Opponents auto-pick top ADP; you pick interactively.
    """
    from ..services.draft_service import DraftService
    from ..services.draft_sync import MockDraftSimulator

    service = DraftService(
        aggregator=aggregator,
        conversation=conversation,
        pick_position=pick_position,
        total_teams=total_teams,
        total_rounds=total_rounds,
    )
    service.initialize()
    simulator = MockDraftSimulator(
        state=service.state,
        player_pool=service._player_pool,
        opponent_speed=0.1,
    )

    console.print(
        f"\n[bold cyan]Mock Draft[/] | {total_teams} teams | "
        f"Position #{pick_position} | Standard Scoring\n"
        f"Opponents auto-pick in ADP order.\n"
        f"Commands: [bold]next[/] | [bold]pick NAME[/] | [bold]board[/] | "
        f"[bold]roster[/] | [bold]q[/]\n"
        f"  or ask Claude anything — just type freely.\n"
    )

    round_num = 0
    while not service.state.is_complete():
        if service.state.current_round != round_num:
            round_num = service.state.current_round
            console.print(f"\n[bold]─── Round {round_num} ───[/]")

        # Auto-pick opponents, collecting for batch inject
        opp_picks: list = []

        def print_opp_pick(player, r, pk):
            opp_picks.append(player)
            console.print(
                f"  [dim]Pick {pk:2}[/] {player.name:<22} "
                f"[dim]{player.position.value}, {player.nfl_team}[/]"
            )

        simulator.simulate_opponents_until_my_pick(on_opponent_pick=print_opp_pick)

        # Batch-inject opponent picks into conversation (no API calls)
        if opp_picks:
            service.conversation.inject_context(
                build_opponent_picks_summary_for_mock(opp_picks)
            )

        if service.state.is_complete():
            break

        # Our pick
        console.print(
            f"\n[bold yellow]>>> YOUR PICK — Round {service.state.current_round}, "
            f"Overall #{service.state.overall_pick}[/]"
        )
        service.get_recommendation()

        while True:
            cmd = typer.prompt("\n>").strip()
            if not cmd:
                continue
            elif cmd.lower() == "q":
                console.print("\n[bold green]Mock draft ended.[/]")
                _show_my_roster(service.show_my_roster())
                return
            elif cmd.lower() == "next":
                service.get_recommendation()
            elif cmd.lower().startswith("pick "):
                name = cmd[5:].strip()
                player = service._find_player(name)
                if player:
                    simulator.record_user_pick(player)
                    service.state.my_players.append(player)
                    service.conversation.inject_context(
                        f"I drafted {player.name} ({player.position.value}, {player.nfl_team})."
                    )
                    console.print(f"  [green]Drafted:[/] {player.name} ({player.position.value})")
                    break
                else:
                    console.print(f"  [red]'{name}' not found.[/] Try 'board' to see options.")
            elif cmd.lower() == "board" or cmd.lower().startswith("board "):
                parts = cmd.split()
                _show_board(service.show_board(
                    position=parts[1].upper() if len(parts) > 1 else None
                ))
            elif cmd.lower() == "roster":
                _show_my_roster(service.show_my_roster())
            else:
                service.chat(cmd)

    console.print("\n[bold green]Mock draft complete![/]")
    _show_my_roster(service.show_my_roster())


def build_opponent_picks_summary_for_mock(players):
    """Thin wrapper to avoid importing context at module level."""
    from ..ai.context import build_opponent_picks_summary
    return build_opponent_picks_summary(players)


# ── Other commands ─────────────────────────────────────────────────────────────

@app.command("board")
def draft_board(
    position: str = typer.Option(None, "--position", "-p", help="Filter: QB/RB/WR/TE/K/DST"),
    limit: int = typer.Option(30, help="Number of players to show"),
):
    """Show top available players by consensus ADP (standard scoring)."""
    from ..services.draft_service import DraftService
    aggregator, conversation = _make_aggregator_only()
    service = DraftService(
        aggregator=aggregator, conversation=conversation,
        pick_position=1, total_teams=10
    )
    service.initialize()
    _show_board(service.show_board(position=position, limit=limit))


@app.command("analyze")
def draft_analyze(
    player: str = typer.Argument(..., help="Player name to analyze"),
):
    """Deep analysis of a single player for draft consideration."""
    from ..services.trade_service import TradeService
    import yaml
    from pathlib import Path
    from ..cli.utils import find_project_root

    aggregator, conversation = _make_aggregator_only()
    config_dir = find_project_root() / "config"
    with open(config_dir / "leagues.yaml") as f:
        cfg = yaml.safe_load(f)
    from ..models.league import LeagueSettings
    settings = LeagueSettings.from_yaml(cfg.get("espn", {}), platform="espn")

    connector, _, conv = _make_services()
    trade_svc = TradeService(connector=connector, aggregator=aggregator, ai=conv, settings=settings)
    trade_svc.player_value(player_name=player, week=1)


# ── Display helpers ────────────────────────────────────────────────────────────

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
