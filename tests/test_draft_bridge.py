"""Tests for DraftBridge — local HTTP server that receives picks from Chrome extension."""
import json
import threading
import time
import urllib.request
import urllib.error
import pytest

from fantasy_agent.services.draft_bridge import DraftBridge
from fantasy_agent.models.draft import DraftState
from fantasy_agent.models.player import Player, Position


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_player(name: str, pos: str, team: str = "KC", eid: str = None) -> Player:
    p = Player(name=name, position=Position(pos), nfl_team=team, espn_id=eid)
    return p


def _make_state() -> DraftState:
    return DraftState(pick_position=3, total_teams=12)


def _make_pool() -> list[Player]:
    return [
        _make_player("Christian McCaffrey", "RB", "SF", "16733"),
        _make_player("Justin Jefferson", "WR", "MIN", "4362628"),
        _make_player("CeeDee Lamb", "WR", "DAL", "4241479"),
        _make_player("Ja'Marr Chase", "WR", "CIN", "4361579"),
        _make_player("Tyreek Hill", "WR", "MIA", "2971618"),
    ]


@pytest.fixture
def bridge():
    """DraftBridge on a dynamic free port, started and stopped around each test."""
    import socket as _socket
    # Pick a free port by binding to port 0 and reading the assigned port
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    state = _make_state()
    pool = _make_pool()
    b = DraftBridge(state, pool, host="127.0.0.1", port=free_port)
    b.start()
    time.sleep(0.05)  # let the server thread bind
    yield b
    b.stop()


# ── process_picks unit tests (no HTTP) ───────────────────────────────────────

def test_process_picks_opponent_fires_callback():
    state = _make_state()
    pool = _make_pool()
    received = []
    b = DraftBridge(state, pool,
                    on_opponent_pick=lambda p, r, pk: received.append((p.name, r, pk)))

    picks = [{"player_id": "16733", "player_name": "Christian McCaffrey", "team_id": 7}]
    count = b.process_picks(picks, my_team_id=3)

    assert count == 1
    assert received[0][0] == "Christian McCaffrey"


def test_process_picks_my_turn_fires_callback():
    state = _make_state()
    pool = _make_pool()
    my_turns = []
    b = DraftBridge(state, pool,
                    on_your_turn=lambda r, pk: my_turns.append((r, pk)))

    picks = [{"player_id": "16733", "player_name": "Christian McCaffrey", "team_id": 3}]
    b.process_picks(picks, my_team_id=3)

    assert len(my_turns) == 1


def test_process_picks_opponent_updates_state():
    state = _make_state()
    pool = _make_pool()
    b = DraftBridge(state, pool)

    picks = [{"player_id": "16733", "player_name": "Christian McCaffrey", "team_id": 7}]
    b.process_picks(picks, my_team_id=3)

    assert "16733" in state.drafted_ids
    assert len(state.all_drafted) == 1


def test_process_picks_deduplicates():
    """Calling process_picks twice with the same list should not double-fire."""
    state = _make_state()
    pool = _make_pool()
    received = []
    b = DraftBridge(state, pool,
                    on_opponent_pick=lambda p, r, pk: received.append(p.name))

    picks = [{"player_id": "16733", "player_name": "Christian McCaffrey", "team_id": 7}]
    b.process_picks(picks, my_team_id=3)
    b.process_picks(picks, my_team_id=3)  # same list, no new entries

    assert len(received) == 1


def test_process_picks_incremental():
    """Only new picks since last call should be processed."""
    state = _make_state()
    pool = _make_pool()
    received = []
    b = DraftBridge(state, pool,
                    on_opponent_pick=lambda p, r, pk: received.append(p.name))

    pick1 = {"player_id": "16733", "player_name": "Christian McCaffrey", "team_id": 7}
    pick2 = {"player_id": "4362628", "player_name": "Justin Jefferson", "team_id": 5}

    b.process_picks([pick1], my_team_id=3)
    b.process_picks([pick1, pick2], my_team_id=3)

    assert received == ["Christian McCaffrey", "Justin Jefferson"]


def test_resolve_player_by_id():
    state = _make_state()
    pool = _make_pool()
    b = DraftBridge(state, pool)

    player = b._resolve_player({"player_id": "4362628", "player_name": "Justin Jefferson"})
    assert player.name == "Justin Jefferson"


def test_resolve_player_by_fuzzy_name():
    state = _make_state()
    pool = _make_pool()
    b = DraftBridge(state, pool)

    # Typo variant, no ID — token_sort_ratio handles transpositions well
    player = b._resolve_player({"player_id": "", "player_name": "Tyreek Hill"})
    assert player.name == "Tyreek Hill"


def test_resolve_player_unknown_fallback():
    state = _make_state()
    pool = _make_pool()
    b = DraftBridge(state, pool)

    player = b._resolve_player({"player_id": "9999", "player_name": "Ghost Player"})
    assert player.position == Position.UNKNOWN


# ── HTTP integration tests ────────────────────────────────────────────────────

def _post(url: str, data: dict) -> tuple[int, dict]:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        return resp.status, json.loads(resp.read())


def _get(url: str) -> tuple[int, dict]:
    with urllib.request.urlopen(url, timeout=3) as resp:
        return resp.status, json.loads(resp.read())


def test_http_post_picks_returns_200(bridge):
    url = f"http://{bridge.host}:{bridge.port}"
    payload = {
        "picks": [{"player_id": "16733", "player_name": "CMC", "team_id": 7}],
        "my_team_id": 3,
    }
    status, body = _post(f"{url}/picks", payload)
    assert status == 200
    assert body["processed"] == 1


def test_http_get_status_returns_state(bridge):
    url = f"http://{bridge.host}:{bridge.port}"
    status, body = _get(f"{url}/status")
    assert status == 200
    assert "overall_pick" in body
    assert "picks_seen" in body


def test_http_post_increments_picks_seen(bridge):
    url = f"http://{bridge.host}:{bridge.port}"
    payload = {
        "picks": [{"player_id": "16733", "player_name": "CMC", "team_id": 7}],
        "my_team_id": 3,
    }
    _post(f"{url}/picks", payload)
    _, status_body = _get(f"{url}/status")
    assert status_body["picks_seen"] == 1


def test_http_unknown_path_returns_404(bridge):
    url = f"http://{bridge.host}:{bridge.port}"
    try:
        _get(f"{url}/unknown")
        assert False, "Expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_http_empty_picks_returns_zero(bridge):
    url = f"http://{bridge.host}:{bridge.port}"
    payload = {"picks": [], "my_team_id": 3}
    status, body = _post(f"{url}/picks", payload)
    assert status == 200
    assert body["processed"] == 0


def test_thread_safety(bridge):
    """Fire multiple concurrent POSTs — no deadlock, final count is correct."""
    url = f"http://{bridge.host}:{bridge.port}"
    picks = [
        {"player_id": "16733", "player_name": "CMC", "team_id": 7},
        {"player_id": "4362628", "player_name": "Justin Jefferson", "team_id": 5},
    ]
    results = []

    def post_picks():
        payload = {"picks": picks, "my_team_id": 3}
        _, body = _post(f"{url}/picks", payload)
        results.append(body["processed"])

    threads = [threading.Thread(target=post_picks) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Total picks processed across all threads == len(picks) (idempotent diff)
    assert sum(results) == len(picks)
