#!/usr/bin/env python3
"""
Interactive mock draft runner.

Simulates a full snake draft against auto-picking opponents.
Requires ANTHROPIC_API_KEY in your environment or config/.env.

Usage (from project root):
    python scripts/run_mock_draft.py
    python scripts/run_mock_draft.py --pick 5 --teams 12 --rounds 15
    python scripts/run_mock_draft.py --pick 1 --teams 10 --no-stream

Commands during draft:
    next            — Get Claude's pick recommendation
    pick NAME       — Record your pick (fuzzy match supported)
    board           — Show top available players
    board RB        — Filter board by position
    roster          — Show your current roster
    <anything>      — Ask Claude a free-form question
    q               — Quit
"""
import sys
import os
import argparse
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fantasy_agent.connectors.sleeper import SleeperConnector
from fantasy_agent.connectors.fantasypros import FantasyProsConnector
from fantasy_agent.services.data_aggregator import DataAggregator
from fantasy_agent.services.draft_service import DraftService
from fantasy_agent.services.draft_sync import MockDraftSimulator
from fantasy_agent.ai.client import DraftConversation
from fantasy_agent.ai.context import build_opponent_picks_summary
from fantasy_agent.models.player import InjuryStatus


# ── Display helpers ────────────────────────────────────────────────────────────

def print_board(players, limit=20):
    print()
    for i, p in enumerate(players[:limit], 1):
        adp = f"adp:{p.adp:.0f}" if p.adp < 999 else "    "
        bye = f"bye:{p.bye_week}" if p.bye_week else "     "
        flag = ""
        if p.injury_status not in (InjuryStatus.ACTIVE, InjuryStatus.UNKNOWN):
            flag = " !" + p.injury_status.value[:3].upper()
        print(f"  {i:>2}. {p.name:<22} {p.position.value:<3} {p.nfl_team:<4} {adp}  {bye}{flag}")


def print_roster(players):
    if not players:
        print("  (empty)")
        return
    from collections import Counter
    counts = Counter(p.position.value for p in players)
    summary = "  ".join(f"{pos}:{n}" for pos, n in sorted(counts.items()))
    print(f"\n  {summary}")
    print()
    for i, p in enumerate(players, 1):
        print(f"  {i:>2}. {p.name:<22} {p.position.value:<3} {p.nfl_team}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run an interactive mock draft.")
    parser.add_argument("--pick", type=int, default=None, help="Your draft position (1-N)")
    parser.add_argument("--teams", type=int, default=12, help="Number of teams")
    parser.add_argument("--rounds", type=int, default=15, help="Number of rounds")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming (faster for tests)")
    args = parser.parse_args()

    # Load env
    from pathlib import Path
    from dotenv import load_dotenv
    project_root = Path(__file__).parents[1]
    load_dotenv(project_root / "config" / ".env", override=False)
    load_dotenv(project_root / ".env", override=False)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Add it to config/.env or export it.")
        sys.exit(1)

    # Pick position
    pick_position = args.pick
    if pick_position is None:
        while True:
            try:
                pick_position = int(input(f"Your draft position (1–{args.teams}): ").strip())
                if 1 <= pick_position <= args.teams:
                    break
                print(f"  Enter a number between 1 and {args.teams}.")
            except (ValueError, EOFError):
                print("  Invalid input.")

    print(f"\nMock Draft  {args.teams} teams · {args.rounds} rounds · pick #{pick_position} · standard")

    # Load data
    print("\nLoading...", flush=True)
    t0 = time.time()
    aggregator = DataAggregator(
        espn=None, yahoo=None,
        sleeper=SleeperConnector(),
        fps=FantasyProsConnector(),
        scoring="std",
    )
    conversation = DraftConversation(api_key=api_key)
    service = DraftService(
        aggregator=aggregator,
        conversation=conversation,
        pick_position=pick_position,
        total_teams=args.teams,
        total_rounds=args.rounds,
    )
    service.initialize()
    elapsed = time.time() - t0
    print(f"Ready in {elapsed:.1f}s. {len(service._player_pool)} players loaded.\n")

    simulator = MockDraftSimulator(
        state=service.state,
        player_pool=service._player_pool,
        opponent_speed=0.05,
    )

    use_stream = not args.no_stream
    print("Commands: next | pick NAME | board [POS] | roster | q")
    print("  or type any question to ask Claude\n")

    round_num = 0
    while not service.state.is_complete():
        # Print round header
        if service.state.current_round != round_num:
            round_num = service.state.current_round
            print(f"\n── Round {round_num} {'─'*30}")

        # Auto-pick opponents, batch inject into conversation
        opp_picks = []
        def on_opp(player, r, pk):
            opp_picks.append(player)
            print(f"  {pk:>2}. {player.name:<22} {player.position.value:<3} {player.nfl_team}")

        simulator.simulate_opponents_until_my_pick(on_opponent_pick=on_opp)

        if opp_picks:
            service.conversation.inject_context(build_opponent_picks_summary(opp_picks))

        if service.state.is_complete():
            break

        # User's turn
        print(f"\n▶ YOUR PICK  R{service.state.current_round} · #{service.state.overall_pick} overall")
        print_board(service.show_board(limit=15))
        service.get_recommendation()

        while True:
            try:
                cmd = input("\n> ").strip()
            except EOFError:
                cmd = "q"

            if not cmd:
                continue
            elif cmd.lower() == "q":
                print("\nDraft ended early.")
                print_roster(service.show_my_roster())
                return
            elif cmd.lower() == "next":
                service.get_recommendation()
            elif cmd.lower() == "board" or cmd.lower().startswith("board "):
                parts = cmd.split()
                pos = parts[1].upper() if len(parts) > 1 else None
                print_board(service.show_board(position=pos, limit=25))
            elif cmd.lower() == "roster":
                print_roster(service.show_my_roster())
            elif cmd.isdigit() or cmd.lower().startswith("pick "):
                name = cmd[5:].strip() if cmd.lower().startswith("pick ") else cmd
                # Support picking by board number (e.g. "5" or "pick 5")
                if name.isdigit():
                    idx = int(name) - 1
                    board = service.show_board(limit=25)
                    player = board[idx] if 0 <= idx < len(board) else None
                else:
                    player = service._find_player(name)
                if player:
                    simulator.record_user_pick(player)
                    service.conversation.inject_context(
                        f"I drafted {player.name} ({player.position.value}, {player.nfl_team})."
                    )
                    print(f"\n  ✓ Drafted: {player.name} ({player.position.value})")
                    break
                else:
                    print(f"  '{name}' not found. Try 'board' or a different spelling.")
            else:
                # If it looks like a player name (short, no spaces or one word), try pick first
                if len(cmd.split()) <= 3 and service._find_player(cmd):
                    player = service._find_player(cmd)
                    print(f"  (tip: use 'pick {cmd}' to draft, or ask a question)")
                    service.chat(cmd)
                else:
                    # Free-form question
                    service.chat(cmd)

    print("\n── Draft complete ──")
    print_roster(service.show_my_roster())


if __name__ == "__main__":
    main()
