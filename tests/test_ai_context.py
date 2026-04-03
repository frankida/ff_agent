"""Tests for the AI context builder."""
import pytest
from fantasy_agent.models.player import Player, Position, InjuryStatus, PlayerStats
from fantasy_agent.models.roster import Roster
from fantasy_agent.models.draft import DraftState
from fantasy_agent.ai.context import ContextBuilder


def _player(name, pos, team, proj=12.0, adp=50.0, rank=20, injury=InjuryStatus.ACTIVE):
    return Player(
        name=name, position=pos, nfl_team=team,
        projected_points=proj, adp=adp, positional_rank=rank,
        injury_status=injury,
        stats=PlayerStats(avg_points_per_game=11.5),
    )


class TestDraftContext:
    def test_build_draft_context_includes_round_and_pick(self):
        ctx = ContextBuilder()
        state = DraftState(pick_position=4, total_teams=10, pick_in_round=4)
        state.current_round = 2
        state.pick_in_round = 7
        state.overall_pick = 17

        available = [_player(f"Player {i}", Position.RB, "KC") for i in range(5)]
        result = ctx.build_draft_context(state, available)

        assert result["round_num"] == 2
        assert result["pick_num"] == 7
        assert result["overall_pick"] == 17

    def test_build_draft_context_limits_available(self):
        ctx = ContextBuilder()
        state = DraftState(pick_position=1, total_teams=10, pick_in_round=1)
        available = [_player(f"P{i}", Position.WR, "BUF") for i in range(50)]

        result = ctx.build_draft_context(state, available, top_n=10)
        # Should show only 10 players
        lines = result["top_available"].strip().split("\n")
        assert len(lines) == 10

    def test_build_draft_context_needs_reflects_roster(self):
        ctx = ContextBuilder()
        state = DraftState(pick_position=1, total_teams=10, pick_in_round=1)
        state.my_players = [
            Player("QB1", Position.QB, "KC"),
            Player("QB2", Position.QB, "BUF"),  # 2 QBs = need filled
        ]

        result = ctx.build_draft_context(state, [])
        # QB should not appear in needs (have 2, target is 1 — actually 2 > 1 so no)
        # RB should appear since we have 0
        assert "RB" in result["needs"]


class TestStartSitContext:
    def _make_roster(self):
        players = [
            _player("Starter QB", Position.QB, "KC", proj=22.0),
            _player("RB1", Position.RB, "DAL", proj=18.0),
            _player("RB2", Position.RB, "SF", proj=14.0),
            _player("WR1", Position.WR, "BUF", proj=16.0),
            _player("WR2", Position.WR, "PHI", proj=12.0),
            _player("WR3", Position.WR, "NE", proj=8.0),
            _player("TE1", Position.TE, "KC", proj=10.0),
            _player("K1", Position.K, "LAR", proj=8.0),
            _player("DEF", Position.DST, "SF", proj=9.0),
        ]
        return Roster(players=players, team_name="My Team", platform="espn")

    def test_build_start_sit_context_has_all_keys(self):
        ctx = ContextBuilder()
        roster = self._make_roster()
        matchup = {
            "my_team": "My Team", "opponent": "Opponent",
            "my_projected": 115.0, "opp_projected": 108.0
        }
        slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1, "FLEX": 1, "BN": 5}

        result = ctx.build_start_sit_context(roster, matchup, week=7, roster_slots=slots)

        assert result["week"] == 7
        assert result["my_team"] == "My Team"
        assert result["opponent"] == "Opponent"
        assert result["my_projected"] == 115.0
        assert "Starter QB" in result["roster_summary"]

    def test_identifies_contested_wr_slot(self):
        ctx = ContextBuilder()
        roster = self._make_roster()
        matchup = {"my_team": "T", "opponent": "O", "my_projected": 100.0, "opp_projected": 100.0}
        # Only 2 WR slots but have 3 WRs
        slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DST": 1, "BN": 5}

        result = ctx.build_start_sit_context(roster, matchup, week=7, roster_slots=slots)
        assert "WR" in result["decisions_needed"]


class TestWaiverContext:
    def test_build_waiver_context_identifies_injured_players(self):
        ctx = ContextBuilder()
        players = [
            _player("Healthy", Position.RB, "KC"),
            _player("Hurt", Position.WR, "NE", injury=InjuryStatus.OUT),
        ]
        roster = Roster(players=players, team_name="T", platform="espn")
        fas = [_player(f"FA{i}", Position.WR, "BUF") for i in range(5)]

        result = ctx.build_waiver_context(
            roster=roster, free_agents=fas, trending=[], week=8, waiver_priority=3
        )
        assert "Hurt" in result["roster_weaknesses"]
        assert "Healthy" not in result["roster_weaknesses"]
        assert result["week"] == 8
        assert result["waiver_priority"] == 3

    def test_trending_adds_appear_in_context(self):
        ctx = ContextBuilder()
        roster = Roster(players=[], team_name="T", platform="espn")
        trending = [
            {"name": "Bijan Robinson", "position": "RB", "team": "ATL", "add_count": 8500}
        ]
        result = ctx.build_waiver_context(
            roster=roster, free_agents=[], trending=trending, week=5
        )
        assert "Bijan Robinson" in result["trending_adds"]
        assert "8,500" in result["trending_adds"]


class TestTradeContext:
    def test_build_trade_context_post_trade_roster(self):
        ctx = ContextBuilder()
        roster_players = [
            _player("Davante Adams", Position.WR, "LV"),
            _player("Tyreek Hill", Position.WR, "MIA"),
        ]
        roster = Roster(players=roster_players, team_name="T", platform="espn")

        giving = [_player("Davante Adams", Position.WR, "LV")]
        receiving = [_player("CeeDee Lamb", Position.WR, "DAL")]

        result = ctx.build_trade_context(
            giving=giving, receiving=receiving, roster=roster,
            week=9, playoff_weeks=[14, 15, 16]
        )
        # Post-trade roster should have Tyreek + CeeDee but not Davante
        assert "Tyreek Hill" in result["post_trade_roster"]
        assert "CeeDee Lamb" in result["post_trade_roster"]
        assert "Davante Adams" not in result["post_trade_roster"]
        assert result["playoff_weeks"] == "Weeks 14–16"
