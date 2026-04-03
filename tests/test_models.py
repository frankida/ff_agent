"""Tests for data models."""
import pytest
from fantasy_agent.models.player import Player, PlayerStats, Position, InjuryStatus
from fantasy_agent.models.roster import Roster
from fantasy_agent.models.draft import DraftState
from fantasy_agent.models.league import LeagueSettings


# ── Player ────────────────────────────────────────────────────────────────────

class TestPlayer:
    def test_to_llm_summary_healthy(self):
        p = Player(
            name="Derrick Henry",
            position=Position.RB,
            nfl_team="TEN",
            projected_points=18.4,
            adp=5.2,
            positional_rank=3,
            stats=PlayerStats(avg_points_per_game=16.1),
        )
        summary = p.to_llm_summary()
        assert "Derrick Henry" in summary
        assert "RB" in summary
        assert "TEN" in summary
        assert "18.4" in summary
        assert "5.2" in summary
        assert "3" in summary
        # No injury flag for healthy player
        assert "[" not in summary.split("Derrick Henry")[1][:5]

    def test_to_llm_summary_injured(self):
        p = Player(
            name="Saquon Barkley",
            position=Position.RB,
            nfl_team="NYG",
            injury_status=InjuryStatus.QUESTIONABLE,
            injury_detail="hamstring",
        )
        summary = p.to_llm_summary()
        assert "QUESTIONABLE" in summary
        assert "hamstring" in summary

    def test_to_llm_summary_bye_week(self):
        p = Player(
            name="Patrick Mahomes",
            position=Position.QB,
            nfl_team="KC",
            is_on_bye=True,
            bye_week=10,
        )
        summary = p.to_llm_summary()
        assert "BYE 10" in summary

    def test_to_llm_summary_no_adp(self):
        p = Player(name="Unknown", position=Position.WR, nfl_team="FA")
        summary = p.to_llm_summary()
        assert "N/A" in summary


# ── Roster ────────────────────────────────────────────────────────────────────

def _make_roster():
    players = [
        Player("QB1", Position.QB, "KC", projected_points=22.0),
        Player("RB1", Position.RB, "DAL", projected_points=18.0),
        Player("RB2", Position.RB, "SF", projected_points=14.0),
        Player("RB3", Position.RB, "NE", projected_points=8.0),
        Player("WR1", Position.WR, "BUF", projected_points=16.0),
        Player("WR2", Position.WR, "PHI", projected_points=12.0),
        Player("TE1", Position.TE, "KC", projected_points=10.0),
        Player("K1", Position.K, "LAR", projected_points=8.0),
        Player("DST1", Position.DST, "SF", projected_points=9.0),
    ]
    return Roster(players=players, team_name="Test Team", platform="espn")


class TestRoster:
    def test_by_position(self):
        roster = _make_roster()
        rbs = roster.by_position(Position.RB)
        assert len(rbs) == 3
        assert all(p.position == Position.RB for p in rbs)

    def test_starters_returns_highest_projected(self):
        roster = _make_roster()
        slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1, "FLEX": 1}
        starters = roster.starters(slots)
        rb_starters = [p for p in starters if p.position == Position.RB]
        # RB1 (18.0) and RB2 (14.0) should start, not RB3 (8.0)
        starter_names = [p.name for p in rb_starters]
        assert "RB1" in starter_names
        assert "RB2" in starter_names
        assert "RB3" not in starter_names

    def test_injured_players(self):
        roster = _make_roster()
        roster.players[0].injury_status = InjuryStatus.OUT
        roster.players[1].injury_status = InjuryStatus.QUESTIONABLE
        injured = roster.injured_players()
        assert len(injured) == 2
        injured_names = [p.name for p in injured]
        assert "QB1" in injured_names
        assert "RB1" in injured_names

    def test_to_summary_contains_all_positions(self):
        roster = _make_roster()
        summary = roster.to_summary()
        for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
            assert pos in summary


# ── DraftState ────────────────────────────────────────────────────────────────

class TestDraftState:
    def _state(self, pick_position=3, total_teams=10):
        return DraftState(
            pick_position=pick_position,
            total_teams=total_teams,
            pick_in_round=1,  # draft always starts at pick 1
        )

    def test_is_my_pick_odd_round(self):
        state = self._state(pick_position=3, total_teams=10)
        state.current_round = 1
        state.pick_in_round = 3
        assert state.is_my_pick() is True
        state.pick_in_round = 4
        assert state.is_my_pick() is False

    def test_is_my_pick_even_round_snake(self):
        # advance() uses a DESCENDING counter in even rounds (N→1),
        # so pick_in_round still equals pick_position when it's the user's turn.
        # pick_position=3 in round 2: counter descends 10→9→8→7→6→5→4→3 (our turn)
        state = self._state(pick_position=3, total_teams=10)
        state.current_round = 2
        state.pick_in_round = 3   # descending counter reaches pick_position
        assert state.is_my_pick() is True
        state.pick_in_round = 4
        assert state.is_my_pick() is False

    def test_advance_moves_pick(self):
        state = self._state(pick_position=1, total_teams=3)
        state.current_round = 1
        state.pick_in_round = 1
        state.overall_pick = 1

        state.advance()
        assert state.pick_in_round == 2
        assert state.overall_pick == 2
        assert state.current_round == 1

    def test_advance_wraps_to_next_round(self):
        state = self._state(pick_position=1, total_teams=3)
        state.current_round = 1
        state.pick_in_round = 3
        state.overall_pick = 3

        state.advance()
        assert state.current_round == 2
        assert state.overall_pick == 4

    def test_advance_snake_even_round(self):
        state = self._state(pick_position=1, total_teams=3)
        state.current_round = 2
        state.pick_in_round = 3

        state.advance()
        assert state.pick_in_round == 2
        assert state.current_round == 2

    def test_is_complete(self):
        state = self._state()
        state.total_rounds = 2
        state.current_round = 3
        assert state.is_complete() is True

        state.current_round = 2
        assert state.is_complete() is False

    def test_needs_summary_empty_roster(self):
        state = self._state()
        summary = state.needs_summary()
        assert "QB" in summary
        assert "RB" in summary

    def test_needs_summary_partial_roster(self):
        state = self._state()
        state.my_players = [
            Player("QB1", Position.QB, "KC"),
            Player("RB1", Position.RB, "DAL"),
            Player("RB2", Position.RB, "SF"),
        ]
        summary = state.needs_summary()
        # QB is filled (1/1), should not appear as needed
        assert "QB" not in summary
        # WR should still be needed
        assert "WR" in summary

    def test_to_dict_round_trip(self):
        state = self._state(pick_position=5, total_teams=12)
        state.current_round = 3
        state.overall_pick = 27
        state.my_players = [Player("Test", Position.QB, "KC", espn_id="123")]
        state.drafted_ids = {"123", "456"}

        d = state.to_dict()
        assert d["pick_position"] == 5
        assert d["total_teams"] == 12
        assert d["current_round"] == 3
        assert d["overall_pick"] == 27
        assert len(d["my_players"]) == 1
        assert "123" in d["drafted_ids"]


# ── LeagueSettings ────────────────────────────────────────────────────────────

class TestLeagueSettings:
    def test_from_yaml(self):
        data = {
            "league_id": 12345,
            "team_id": 3,
            "scoring": "standard",
            "season": 2025,
            "total_teams": 10,
            "total_rounds": 15,
            "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1, "BN": 6},
            "playoff_weeks": [14, 15, 16],
        }
        settings = LeagueSettings.from_yaml(data, platform="espn")
        assert settings.league_id == "12345"
        assert settings.team_id == "3"
        assert settings.is_standard is True
        assert settings.scoring_label == "Standard"
        assert settings.playoff_weeks == [14, 15, 16]

    def test_scoring_label(self):
        base = {"league_id": 1, "team_id": 1, "scoring": "ppr", "season": 2025,
                "total_teams": 10, "total_rounds": 15, "roster_slots": {}}
        s = LeagueSettings.from_yaml(base, "espn")
        assert s.scoring_label == "PPR"
        assert s.is_standard is False
