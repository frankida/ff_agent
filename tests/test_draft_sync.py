"""
Tests for DraftSyncService and MockDraftSimulator.

DraftSyncService: background ESPN polling, auto-detect opponent picks.
MockDraftSimulator: simulates opponents without ESPN connection.
"""
import time
import pytest
from unittest.mock import MagicMock, patch, call
from fantasy_agent.models.player import Player, Position
from fantasy_agent.models.draft import DraftState
from fantasy_agent.services.draft_sync import DraftSyncService, MockDraftSimulator


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pool(n=20):
    """Create a pool of n players sorted by ADP."""
    positions = [Position.QB, Position.RB, Position.RB, Position.WR,
                 Position.WR, Position.TE, Position.K, Position.DST]
    players = []
    for i in range(n):
        pos = positions[i % len(positions)]
        players.append(Player(
            name=f"Player{i+1}",
            position=pos,
            nfl_team=f"T{i % 32}",
            adp=float(i + 1),
            espn_id=str(100 + i),
        ))
    return players


def _make_state(pick_position=3, total_teams=10):
    return DraftState(
        pick_position=pick_position,
        total_teams=total_teams,
        pick_in_round=1,  # draft always starts at pick 1
    )


# ── MockDraftSimulator ────────────────────────────────────────────────────────

class TestMockDraftSimulator:
    def test_simulates_opponents_before_user_pick(self):
        """With pick position 3, opponents 1 and 2 should be auto-drafted first."""
        state = _make_state(pick_position=3, total_teams=10)
        pool = _make_pool(30)
        sim = MockDraftSimulator(state, pool, opponent_speed=0)

        picks_seen = []
        sim.simulate_opponents_until_my_pick(
            on_opponent_pick=lambda p, r, pk: picks_seen.append(p.name)
        )

        # Picks 1 and 2 should be auto-drafted (positions 1 and 2)
        assert len(picks_seen) == 2
        assert picks_seen[0] == "Player1"   # highest ADP available
        assert picks_seen[1] == "Player2"
        # Now it should be user's turn (pick position 3)
        assert state.is_my_pick() is True

    def test_simulates_opponents_last_pick_pos(self):
        """With pick position 10 (last), all 9 opponents go first."""
        state = _make_state(pick_position=10, total_teams=10)
        pool = _make_pool(30)
        sim = MockDraftSimulator(state, pool, opponent_speed=0)

        picks = []
        sim.simulate_opponents_until_my_pick(
            on_opponent_pick=lambda p, r, pk: picks.append(p.name)
        )
        assert len(picks) == 9
        assert state.is_my_pick() is True

    def test_record_user_pick_adds_to_roster(self):
        state = _make_state(pick_position=1, total_teams=3)
        pool = _make_pool(10)
        sim = MockDraftSimulator(state, pool, opponent_speed=0)

        player = pool[0]
        sim.record_user_pick(player)

        assert player in state.my_players
        assert (player.espn_id or player.name) in state.drafted_ids
        assert state.overall_pick == 2

    def test_drafted_players_not_available(self):
        """After a player is drafted they should be removed from available pool."""
        state = _make_state(pick_position=3, total_teams=10)
        pool = _make_pool(20)
        sim = MockDraftSimulator(state, pool, opponent_speed=0)

        sim.simulate_opponents_until_my_pick()
        available = sim._get_available()

        # Player1 and Player2 were auto-drafted
        available_names = [p.name for p in available]
        assert "Player1" not in available_names
        assert "Player2" not in available_names
        assert "Player3" in available_names

    def test_snake_round2_opponents_pick_in_reverse(self):
        """
        After user picks at position 3 in round 1, simulate_opponents_until_my_pick
        covers ALL picks between two user turns (snake draft, fixed is_my_pick):
          - Round 1 remainder: positions 4,5,6,7,8,9,10  = 7 picks
          - Round 2 (descending): user's mirrored slot = total_teams - pick_position + 1
            = 10 - 3 + 1 = 8. Opponents pick at 10, 9 = 2 picks before user's turn.
          - Total: 9 opponent picks before user's round 2 turn
        """
        state = _make_state(pick_position=3, total_teams=10)
        pool = _make_pool(30)
        sim = MockDraftSimulator(state, pool, opponent_speed=0)

        # Simulate R1P1, R1P2 (before our round 1 pick)
        sim.simulate_opponents_until_my_pick()
        assert state.is_my_pick()

        sim.record_user_pick(pool[2])   # our round 1 pick at position 3

        # Now simulate until round 2, mirrored position (all remaining R1 + R2 up to our pick)
        opp_picks = []
        sim.simulate_opponents_until_my_pick(
            on_opponent_pick=lambda p, r, pk: opp_picks.append((r, pk))
        )

        # 7 picks left in round 1 (positions 4-10) + 2 picks in round 2 (10→9 before slot 8)
        assert len(opp_picks) == 9
        round1_picks = [pk for (r, pk) in opp_picks if r == 1]
        round2_picks = [pk for (r, pk) in opp_picks if r == 2]
        assert len(round1_picks) == 7
        assert len(round2_picks) == 2
        assert state.is_my_pick() is True
        assert state.current_round == 2

    def test_full_2_round_draft_with_3_teams(self):
        """Complete a full 2-round snake draft with 3 teams."""
        state = DraftState(
            pick_position=2, total_teams=3,
            total_rounds=2, pick_in_round=2,
        )
        pool = _make_pool(10)
        sim = MockDraftSimulator(state, pool, opponent_speed=0)

        my_picks = []

        # Round 1: P1 picks, P2 picks (us), P3 picks
        sim.simulate_opponents_until_my_pick()
        assert state.is_my_pick()
        sim.record_user_pick(pool[1])       # P1 taken by opp, we take P2
        my_picks.append(pool[1].name)

        # Round 2 (snake, reverse): P3 picks first, then P2 (us), then P1
        sim.simulate_opponents_until_my_pick()
        assert state.is_my_pick()
        available = sim._get_available()
        sim.record_user_pick(available[0])
        my_picks.append(available[0].name)

        assert len(my_picks) == 2
        assert len(state.my_players) == 2


# ── DraftSyncService ──────────────────────────────────────────────────────────

class TestDraftSyncService:
    def _make_connector(self, picks: list[dict], my_team_id: int = 1):
        connector = MagicMock()
        connector._team_id = my_team_id

        # Build mock Pick objects
        mock_picks = []
        for p in picks:
            pick_obj = MagicMock()
            pick_obj.playerName = p["player_name"]
            pick_obj.playerId = p["player_id"]
            pick_obj.team = p.get("team_obj")
            pick_obj.round_num = p.get("round_num", 1)
            pick_obj.round_pick = p.get("round_pick", 1)
            mock_picks.append(pick_obj)

        league = MagicMock()
        league.draft = mock_picks
        league.teams = [MagicMock(), MagicMock()]  # index 0 = team_id 1
        connector._get_league.return_value = league
        return connector

    def test_resolve_player_by_espn_id(self):
        pool = _make_pool(5)
        state = _make_state()
        connector = self._make_connector([])

        sync = DraftSyncService(connector, state, pool)
        pick_data = {"player_id": "101", "player_name": "Player2"}
        resolved = sync._resolve_player(pick_data)
        assert resolved.name == "Player2"
        assert resolved.espn_id == "101"

    def test_resolve_player_by_fuzzy_name_fallback(self):
        pool = _make_pool(5)
        state = _make_state()
        connector = self._make_connector([])

        sync = DraftSyncService(connector, state, pool)
        # Use an ID that doesn't match, force fuzzy name path
        pick_data = {"player_id": "9999", "player_name": "Player1"}
        resolved = sync._resolve_player(pick_data)
        assert resolved.name == "Player1"

    def test_resolve_unknown_player_creates_placeholder(self):
        pool = _make_pool(5)
        state = _make_state()
        connector = self._make_connector([])

        sync = DraftSyncService(connector, state, pool)
        pick_data = {"player_id": "9999", "player_name": "Completely Unknown"}
        resolved = sync._resolve_player(pick_data)
        assert resolved.position == Position.UNKNOWN
        assert "Unknown" in resolved.name or "Completely Unknown" in resolved.name

    def test_fetch_draft_picks_returns_list(self):
        pool = _make_pool(5)
        state = _make_state()
        api_picks = [
            {"player_name": "Player1", "player_id": "101",
             "team_obj": None, "round_num": 1, "round_pick": 1},
        ]
        connector = self._make_connector(api_picks)

        sync = DraftSyncService(connector, state, pool)
        result = sync._fetch_draft_picks()
        assert result is not None
        assert len(result) == 1
        assert result[0]["player_name"] == "Player1"

    def test_fetch_draft_picks_returns_none_on_error(self):
        pool = _make_pool(5)
        state = _make_state()
        connector = MagicMock()
        connector._get_league.side_effect = Exception("ESPN down")

        sync = DraftSyncService(connector, state, pool)
        result = sync._fetch_draft_picks()
        assert result is None

    def test_sync_picks_auto_records_opponent(self):
        """New picks that aren't ours should be auto-recorded as opponent picks."""
        pool = _make_pool(10)
        state = _make_state(pick_position=3, total_teams=10)

        # Simulate 2 opponent picks already in API
        api_data = [
            {"player_name": "Player1", "player_id": "100", "team_obj": "other",
             "round_num": 1, "round_pick": 1},
            {"player_name": "Player2", "player_id": "101", "team_obj": "other",
             "round_num": 1, "round_pick": 2},
        ]
        connector = self._make_connector(api_data, my_team_id=3)

        # Make _is_my_pick_data always return False (opponent picks)
        opponent_picks_recorded = []

        sync = DraftSyncService(
            connector, state, pool,
            on_opponent_pick=lambda p, r, pk: opponent_picks_recorded.append(p.name),
        )
        # Patch _is_my_pick_data to return False
        sync._is_my_pick_data = lambda _: False

        sync._sync_picks()

        assert len(opponent_picks_recorded) == 2
        assert "Player1" in opponent_picks_recorded
        assert "Player2" in opponent_picks_recorded
        assert sync._last_seen_pick_count == 2

    def test_sync_picks_fires_your_turn_on_my_pick(self):
        """When a pick from our team is detected, your_turn callback fires."""
        pool = _make_pool(10)
        state = _make_state(pick_position=1, total_teams=3)

        api_data = [
            {"player_name": "Player1", "player_id": "101", "team_obj": "my_team",
             "round_num": 1, "round_pick": 1},
        ]
        connector = self._make_connector(api_data, my_team_id=1)

        your_turn_called = []

        sync = DraftSyncService(
            connector, state, pool,
            on_your_turn=lambda r, pk: your_turn_called.append((r, pk)),
        )
        # Patch _is_my_pick_data to return True
        sync._is_my_pick_data = lambda _: True

        sync._sync_picks()

        assert len(your_turn_called) == 1

    def test_sync_picks_skips_already_seen(self):
        """Picks already processed should not be reprocessed on next poll."""
        pool = _make_pool(10)
        state = _make_state(pick_position=3, total_teams=10)

        api_data = [
            {"player_name": "Player1", "player_id": "101", "team_obj": "other",
             "round_num": 1, "round_pick": 1},
        ]
        connector = self._make_connector(api_data, my_team_id=3)

        picks_recorded = []
        sync = DraftSyncService(
            connector, state, pool,
            on_opponent_pick=lambda p, r, pk: picks_recorded.append(p.name),
        )
        sync._is_my_pick_data = lambda _: False

        sync._sync_picks()   # First poll — records Player1
        sync._sync_picks()   # Second poll — same data, should not re-record

        assert len(picks_recorded) == 1   # not 2

    def test_stop_signals_thread(self):
        """Calling stop() should signal the background thread to exit."""
        pool = _make_pool(5)
        state = _make_state()
        connector = self._make_connector([])

        sync = DraftSyncService(connector, state, pool, poll_interval=60)
        sync.start()
        assert sync._thread.is_alive()

        sync.stop()
        sync._thread.join(timeout=2)
        assert not sync._thread.is_alive()


# ── Integration: mock draft end-to-end ───────────────────────────────────────

class TestMockDraftEndToEnd:
    def test_full_draft_produces_correct_roster_size(self):
        """A full 15-round 10-team mock draft should give the user 15 picks."""
        total_rounds = 5   # keep it short for tests
        total_teams = 4
        pick_position = 2
        pool = _make_pool(total_rounds * total_teams + 10)

        state = DraftState(
            pick_position=pick_position,
            total_teams=total_teams,
            total_rounds=total_rounds,
            pick_in_round=pick_position,
        )
        sim = MockDraftSimulator(state, pool, opponent_speed=0)

        for _ in range(total_rounds):
            sim.simulate_opponents_until_my_pick()
            if state.is_complete():
                break
            available = sim._get_available()
            if not available:
                break
            sim.record_user_pick(available[0])
            # Simulate rest of round after user's pick
            sim.simulate_opponents_until_my_pick()

        assert len(state.my_players) == total_rounds

    def test_no_duplicate_picks_across_full_draft(self):
        """Every pick in the draft should be unique (no player drafted twice)."""
        total_rounds = 3
        total_teams = 3
        pool = _make_pool(total_rounds * total_teams + 5)

        state = DraftState(
            pick_position=1,
            total_teams=total_teams,
            total_rounds=total_rounds,
            pick_in_round=1,
        )
        sim = MockDraftSimulator(state, pool, opponent_speed=0)

        while not state.is_complete():
            if state.is_my_pick():
                available = sim._get_available()
                if not available:
                    break
                sim.record_user_pick(available[0])
            else:
                sim.simulate_opponents_until_my_pick()

        all_drafted = state.all_drafted
        all_names = [p.name for p in all_drafted]
        assert len(all_names) == len(set(all_names)), "Duplicate picks found!"
