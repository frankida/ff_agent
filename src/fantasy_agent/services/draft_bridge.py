"""
DraftBridge — local HTTP server that receives pick data from the Chrome extension.

The Chrome extension polls ESPN's React state every 3s and POSTs the full pick
list to http://localhost:5050/picks. DraftBridge diffs against known state and
fires callbacks for any new picks detected since the last POST.

Usage:
    bridge = DraftBridge(state, player_pool,
                         on_opponent_pick=my_callback,
                         on_your_turn=my_turn_callback)
    bridge.start()
    # ... user input loop ...
    bridge.stop()
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

from ..models.player import Player, Position
from ..models.draft import DraftState


class DraftBridge:
    """
    Python-side HTTP server that receives picks from the Chrome extension.

    POST /picks  — accepts {"picks": [...], "current_pick": int, "my_team_id": int}
    GET  /status — returns current draft state as JSON
    """

    def __init__(
        self,
        state: DraftState,
        player_pool: list[Player],
        host: str = "127.0.0.1",
        port: int = 5050,
        on_opponent_pick: Optional[Callable] = None,
        on_your_turn: Optional[Callable] = None,
    ):
        self.state = state
        self.pool = player_pool
        self.host = host
        self.port = port
        self.on_opponent_pick = on_opponent_pick or (lambda p, r, pk: None)
        self.on_your_turn = on_your_turn or (lambda r, pk: None)

        self._lock = threading.Lock()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._seen_picks: list[dict] = []   # raw pick dicts we've already processed

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        """Launch the HTTP server on a daemon thread."""
        handler = self._make_handler()

        class _ReuseHTTPServer(HTTPServer):
            allow_reuse_address = True

        self._server = _ReuseHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        """Shut down the server and wait for the thread to exit."""
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=5)

    # ── Pick processing ───────────────────────────────────────────────────────

    def process_picks(self, picks: list[dict], my_team_id: int) -> int:
        """
        Diff picks list against already-seen state and fire callbacks for new picks.
        Returns number of new picks processed. Thread-safe.
        """
        with self._lock:
            new_picks = picks[len(self._seen_picks):]
            processed = 0
            for pick_data in new_picks:
                player = self._resolve_player(pick_data)
                is_mine = pick_data.get("team_id") == my_team_id

                if not is_mine:
                    uid = player.espn_id or player.name
                    self.state.drafted_ids.add(uid)
                    self.state.all_drafted.append(player)

                    round_num = self.state.current_round
                    pick_num = self.state.pick_in_round
                    self.state.advance()
                    self.on_opponent_pick(player, round_num, pick_num)
                else:
                    self.on_your_turn(self.state.current_round, self.state.overall_pick)

                processed += 1

            self._seen_picks.extend(new_picks)
            return processed

    def get_status(self) -> dict:
        """Return current draft state for the GET /status endpoint."""
        with self._lock:
            return {
                "overall_pick": self.state.overall_pick,
                "current_round": self.state.current_round,
                "pick_in_round": self.state.pick_in_round,
                "is_my_pick": self.state.is_my_pick(),
                "picks_seen": len(self._seen_picks),
                "my_players": [p.name for p in self.state.my_players],
            }

    # ── Name resolution ───────────────────────────────────────────────────────

    def _resolve_player(self, pick_data: dict) -> Player:
        """Match a pick from the extension to a Player in our pool."""
        pid = str(pick_data.get("player_id", ""))
        name = pick_data.get("player_name", "")

        # Exact ESPN ID match
        if pid:
            for p in self.pool:
                if p.espn_id == pid:
                    return p

        # Fuzzy name match
        if name:
            try:
                from rapidfuzz import process, fuzz
                names_map = {p.name: p for p in self.pool}
                result = process.extractOne(
                    name, names_map.keys(),
                    scorer=fuzz.token_sort_ratio,
                    score_cutoff=80,
                )
                if result:
                    return names_map[result[0]]
            except ImportError:
                pass

        return Player(
            name=name or f"Unknown(id:{pid})",
            position=Position.UNKNOWN,
            nfl_team="",
            espn_id=pid or None,
        )

    # ── Handler factory ───────────────────────────────────────────────────────

    def _make_handler(self):
        bridge = self  # capture self for the inner class

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/picks":
                    self._send(404, {"error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length))
                    picks = body.get("picks", [])
                    my_team_id = body.get("my_team_id", -1)
                    processed = bridge.process_picks(picks, my_team_id)
                    self._send(200, {"processed": processed})
                except Exception as exc:
                    self._send(400, {"error": str(exc)})

            def do_GET(self):
                if self.path != "/status":
                    self._send(404, {"error": "not found"})
                    return
                self._send(200, bridge.get_status())

            def _send(self, code: int, data: dict):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                pass  # suppress access log noise

        return _Handler
