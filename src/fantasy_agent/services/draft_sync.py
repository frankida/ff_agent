"""
Background ESPN polling for live draft auto-sync.

Uses a daemon thread that polls league.draft every N seconds and
compares against known state to auto-detect opponent picks.
The main thread handles user input; this thread handles everything else.
"""
import threading
import time
from typing import Optional, Callable
from ..models.player import Player, Position
from ..models.draft import DraftState


class DraftSyncService:
    """
    Polls ESPN (or Yahoo) for new draft picks in the background.

    Usage:
        sync = DraftSyncService(connector, state, player_pool, poll_interval=20)
        sync.start()
        # ... user input loop ...
        sync.stop()

    Callbacks:
        on_opponent_pick(player, round_num, pick_num)  — called for each auto-detected pick
        on_your_turn(round_num, overall_pick)           — called when it becomes your pick
    """

    def __init__(
        self,
        connector,                          # ESPNConnector or YahooConnector
        state: DraftState,
        player_pool: list[Player],
        poll_interval: int = 20,            # seconds between polls
        on_opponent_pick: Optional[Callable] = None,
        on_your_turn: Optional[Callable] = None,
    ):
        self.connector = connector
        self.state = state
        self.pool = player_pool
        self.poll_interval = poll_interval
        self.on_opponent_pick = on_opponent_pick or (lambda p, r, pk: None)
        self.on_your_turn = on_your_turn or (lambda r, pk: None)

        self._stop_event = threading.Event()
        self._your_turn_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        # Track how many picks we've already seen from the API
        self._last_seen_pick_count = 0

    def start(self):
        """Start the background polling thread."""
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the polling thread to stop."""
        self._stop_event.set()

    def wait_for_your_turn(self, timeout: float = 300) -> bool:
        """
        Block until it becomes the user's pick or timeout.
        Returns True if it's your turn, False on timeout.
        """
        self._your_turn_event.clear()
        return self._your_turn_event.wait(timeout=timeout)

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                self._sync_picks()
            except Exception as e:
                # Don't crash the background thread on transient errors
                pass

            if self._stop_event.wait(timeout=self.poll_interval):
                break

    def _sync_picks(self):
        """
        Fetch current draft state from ESPN and reconcile with local state.
        Fires callbacks for any new picks detected.
        """
        api_picks = self._fetch_draft_picks()
        if api_picks is None:
            return

        with self._lock:
            new_picks = api_picks[self._last_seen_pick_count:]
            for pick_data in new_picks:
                player = self._resolve_player(pick_data)
                is_my_pick = self._is_my_pick_data(pick_data)

                if not is_my_pick:
                    # Auto-record opponent pick
                    if player.espn_id:
                        self.state.drafted_ids.add(player.espn_id)
                    self.state.all_drafted.append(player)
                    self.state.advance()
                    self.on_opponent_pick(
                        player,
                        pick_data.get("round_num", self.state.current_round),
                        pick_data.get("round_pick", self.state.pick_in_round),
                    )
                else:
                    # It's the user's pick — signal the main thread
                    self.on_your_turn(
                        self.state.current_round,
                        self.state.overall_pick,
                    )
                    self._your_turn_event.set()

            self._last_seen_pick_count = len(api_picks)

    def _fetch_draft_picks(self) -> Optional[list[dict]]:
        """
        Pull draft picks from ESPN API.
        Returns list of pick dicts or None on failure.
        """
        try:
            league = self.connector._get_league()
            raw_picks = league.draft  # list of Pick objects from espn-api
            result = []
            for pick in raw_picks:
                result.append({
                    "player_name": getattr(pick, "playerName", ""),
                    "player_id": str(getattr(pick, "playerId", "")),
                    "team_id": getattr(pick, "team", None),
                    "round_num": getattr(pick, "round_num", 0),
                    "round_pick": getattr(pick, "round_pick", 0),
                })
            return result
        except Exception:
            return None

    def _is_my_pick_data(self, pick_data: dict) -> bool:
        """Check if a pick from the API was made by our team."""
        try:
            league = self.connector._get_league()
            my_team = league.teams[self.connector._team_id - 1]
            return pick_data.get("team_id") == my_team
        except Exception:
            return False

    def _resolve_player(self, pick_data: dict) -> Player:
        """Match a pick from the API to a Player in our pool."""
        pid = pick_data.get("player_id", "")
        name = pick_data.get("player_name", "")

        # Try ID match first (fast + exact)
        if pid:
            for p in self.pool:
                if p.espn_id == pid:
                    return p

        # Fallback: fuzzy name match
        if name:
            try:
                from rapidfuzz import process, fuzz
                names_map = {p.name: p for p in self.pool}
                result = process.extractOne(
                    name, names_map.keys(),
                    scorer=fuzz.token_sort_ratio, score_cutoff=80
                )
                if result:
                    return names_map[result[0]]
            except ImportError:
                pass

        # Last resort: create a placeholder
        return Player(
            name=name or f"Unknown (ID:{pid})",
            position=Position.UNKNOWN,
            nfl_team="",
            espn_id=pid or None,
        )


class MockDraftSimulator:
    """
    Simulates a full snake draft without any ESPN/Yahoo connection.
    Opponents pick in ADP order (top available each turn).
    Used for testing the draft assistant before the real draft.
    """

    def __init__(
        self,
        state: DraftState,
        player_pool: list[Player],
        opponent_speed: float = 0.5,   # seconds between opponent auto-picks
    ):
        self.state = state
        self.pool = player_pool
        self.opponent_speed = opponent_speed

    def simulate_opponents_until_my_pick(
        self,
        on_opponent_pick: Optional[Callable] = None,
    ):
        """
        Auto-draft for opponents (top ADP available) until it's the user's turn.
        Calls on_opponent_pick(player, round, pick) for each simulated pick.
        """
        while not self.state.is_complete() and not self.state.is_my_pick():
            available = self._get_available()
            if not available:
                break

            # Opponent picks best available by ADP
            pick = available[0]
            self.state.drafted_ids.add(pick.espn_id or pick.name)
            self.state.all_drafted.append(pick)

            round_num = self.state.current_round
            pick_num = self.state.pick_in_round
            self.state.advance()

            if on_opponent_pick:
                on_opponent_pick(pick, round_num, pick_num)

            if self.opponent_speed > 0:
                time.sleep(self.opponent_speed)

    def record_user_pick(self, player: Player):
        """Record the user's pick and advance state."""
        self.state.my_players.append(player)
        self.state.drafted_ids.add(player.espn_id or player.name)
        self.state.all_drafted.append(player)
        self.state.advance()

    def _get_available(self) -> list[Player]:
        drafted = self.state.drafted_ids
        return [
            p for p in self.pool
            if (p.espn_id or p.name) not in drafted
        ]
