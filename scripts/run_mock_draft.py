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
import re
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


def parse_recommendation(response: str) -> dict:
    """Extract PICK/PRO/CON/ALT/ALT_NOTE from Claude's 4-line formatted response."""
    pick     = re.search(r'PICK:\s+([^·•\n]+?)\s+[·•]', response)
    pro      = re.search(r'PRO:\s+(.+)', response)
    con      = re.search(r'CON:\s+(.+)', response)
    alt      = re.search(r'ALT:\s+([^·•\n←]+?)\s+[·•←]', response)
    alt_note = re.search(r'ALT:.*?[←]\s*(.+)', response)
    return {
        "pick":     pick.group(1).strip()     if pick     else None,
        "pro":      pro.group(1).strip()      if pro      else None,
        "con":      con.group(1).strip()      if con      else None,
        "alt":      alt.group(1).strip()      if alt      else None,
        "alt_note": alt_note.group(1).strip() if alt_note else None,
    }


# ── Arrow-key pick menu ─────────────────────────────────────────────────────

def _read_key():
    """Read one keypress in raw mode. Returns 'UP', 'DOWN', 'ENTER', or char."""
    import tty, termios, select
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            if select.select([sys.stdin], [], [], 0.05)[0]:
                ch2 = sys.stdin.read(1)
                if ch2 == '[' and select.select([sys.stdin], [], [], 0.05)[0]:
                    ch3 = sys.stdin.read(1)
                    if ch3 == 'A': return 'UP'
                    if ch3 == 'B': return 'DOWN'
            return 'ESC'
        if ch in ('\r', '\n'): return 'ENTER'
        if ch == '\x03': raise KeyboardInterrupt
        if ch == '\x7f': return 'BACKSPACE'
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _player_label(p):
    if p is None:
        return ""
    bye = f"  bye wk{p.bye_week}" if p.bye_week else ""
    return f"{p.name} · {p.position.value} · {p.nfl_team}{bye}"


MENU_LINES = 4  # 3 options + 1 analysis line

def pick_menu(rec_player, rec_pro, rec_con, alt_player, alt_note, service):
    """
    Arrow-key interactive menu. Returns a Player to draft, or None to quit.
    Up/down navigate. Enter confirms. Digit or name typed = board pick.
    """
    options = [rec_player, alt_player, None]
    option_labels = [
        f"r   {_player_label(rec_player) or '(no rec)'}",
        f"a   {_player_label(alt_player) or '(no alt)'}",
        f"N   choose from board  (type a number or name)",
    ]
    notes = [
        (f"PRO: {rec_pro}  |  CON: {rec_con}") if rec_pro or rec_con else "",
        alt_note or "",
        "",
    ]
    sel = 0
    typed = ""  # accumulates digits/chars when board option is selected

    def draw(first=False):
        if not first:
            sys.stdout.write(f'\033[{MENU_LINES}A\033[J')
        for i, label in enumerate(option_labels):
            arrow = '→' if i == sel else ' '
            sys.stdout.write(f'  {arrow} {label}\n')
        # Analysis line
        note = notes[sel]
        if sel == 2 and typed:
            sys.stdout.write(f'    ↳ {typed}_\n')
        elif note:
            sys.stdout.write(f'    ↳ {note}\n')
        else:
            sys.stdout.write('\n')
        sys.stdout.flush()

    print()
    draw(first=True)

    while True:
        key = _read_key()

        if key == 'UP':
            sel = (sel - 1) % 3
            typed = ""
            draw()
        elif key == 'DOWN':
            sel = (sel + 1) % 3
            typed = ""
            draw()
        elif key == 'ENTER':
            print()
            if sel in (0, 1):
                return options[sel]
            else:
                # board pick — typed may already have content
                if not typed:
                    sys.stdout.write('  Board # or name: ')
                    sys.stdout.flush()
                    import termios as _t
                    _t.tcsetattr(sys.stdin.fileno(), _t.TCSADRAIN,
                                 _t.tcgetattr(sys.stdin.fileno()))
                    typed = input('')
                if typed.isdigit():
                    board = service.show_board(limit=25)
                    idx = int(typed) - 1
                    return board[idx] if 0 <= idx < len(board) else None
                else:
                    return service._find_player(typed)
        elif key == 'q':
            return 'QUIT'
        elif key == 'BACKSPACE':
            if typed:
                typed = typed[:-1]
                draw()
        elif key.isprintable():
            # Any printable char auto-switches to board option and accumulates
            sel = 2
            typed += key
            draw()


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
    print("Arrow keys to choose · Enter to draft · type to search board · q to quit\n")

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
        rec_response = service.get_recommendation()
        rec = parse_recommendation(rec_response)

        rec_player = service._find_player(rec["pick"]) if rec["pick"] else None
        alt_player = service._find_player(rec["alt"])  if rec["alt"]  else None

        while True:
            result = pick_menu(
                rec_player=rec_player,
                rec_pro=rec["pro"],
                rec_con=rec["con"],
                alt_player=alt_player,
                alt_note=rec["alt_note"],
                service=service,
            )

            if result == 'QUIT':
                print("\nDraft ended early.")
                print_roster(service.show_my_roster())
                return
            elif result is None:
                print("  Player not found. Try again.")
                continue
            else:
                simulator.record_user_pick(result)
                service.conversation.inject_context(
                    f"I drafted {result.name} ({result.position.value}, {result.nfl_team})."
                )
                print(f"  ✓ Drafted: {result.name} ({result.position.value})")
                break

    print("\n── Draft complete ──")
    print_roster(service.show_my_roster())


if __name__ == "__main__":
    main()
