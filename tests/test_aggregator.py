"""Tests for the DataAggregator — the core data merge layer."""
import pytest
from unittest.mock import MagicMock, patch
from fantasy_agent.models.player import Player, Position, InjuryStatus, PlayerStats
from fantasy_agent.services.data_aggregator import DataAggregator


def _make_aggregator(sleeper_data=None, fp_rankings=None, fp_adp=None):
    sleeper = MagicMock()
    sleeper.get_injury_and_depth.return_value = sleeper_data or {}
    sleeper.get_all_players.return_value = {}

    fps = MagicMock()
    fps.get_all_rankings.return_value = fp_rankings or []
    fps.get_adp.return_value = fp_adp or []

    return DataAggregator(
        espn=None, yahoo=None, sleeper=sleeper, fps=fps, scoring="std"
    )


class TestDataAggregator:
    def test_enrich_adds_adp_from_fantasypros(self):
        aggregator = _make_aggregator(
            fp_adp=[
                {"name": "Travis Kelce", "adp": 12.3, "overall_rank": 10,
                 "positional_rank": 1, "position": "TE", "team": "KC"}
            ]
        )
        players = [Player("Travis Kelce", Position.TE, "KC")]
        enriched = aggregator.enrich_players(players)
        assert enriched[0].adp == 12.3
        assert enriched[0].overall_rank == 10
        assert enriched[0].positional_rank == 1

    def test_enrich_adds_injury_from_sleeper(self):
        aggregator = _make_aggregator(
            sleeper_data={
                "555": {
                    "full_name": "Davante Adams",
                    "team": "LV",
                    "position": "WR",
                    "injury_status": "Q",
                    "injury_body_part": "knee",
                    "practice_participation": "LP",
                    "depth_chart_order": 1,
                    "bye_week": 9,
                }
            }
        )
        players = [Player("Davante Adams", Position.WR, "LV")]
        enriched = aggregator.enrich_players(players)
        p = enriched[0]
        assert p.injury_status == InjuryStatus.QUESTIONABLE
        assert p.injury_detail == "knee"
        assert p.injury_practice_status == "LP"
        assert p.bye_week == 9
        assert p.sleeper_id == "555"

    def test_enrich_does_not_overwrite_existing_injury(self):
        """ESPN already marked player as OUT — Sleeper ACTIVE should not overwrite."""
        aggregator = _make_aggregator(
            sleeper_data={
                "1": {
                    "full_name": "Test Player",
                    "team": "KC",
                    "position": "RB",
                    "injury_status": None,  # Sleeper says healthy
                    "depth_chart_order": 1,
                    "bye_week": 7,
                }
            }
        )
        player = Player(
            "Test Player", Position.RB, "KC",
            injury_status=InjuryStatus.OUT  # ESPN said OUT
        )
        enriched = aggregator.enrich_players([player])
        assert enriched[0].injury_status == InjuryStatus.OUT  # not overwritten

    def test_fuzzy_match_handles_name_variants(self):
        aggregator = _make_aggregator(
            fp_adp=[
                {"name": "Cee Dee Lamb", "adp": 3.1, "overall_rank": 3,
                 "positional_rank": 1, "position": "WR", "team": "DAL"}
            ]
        )
        # ESPN might spell it differently
        players = [Player("CeeDee Lamb", Position.WR, "DAL")]
        enriched = aggregator.enrich_players(players)
        # Should still match via fuzzy
        assert enriched[0].adp < 999

    def test_build_draft_player_pool_returns_sorted_by_adp(self):
        aggregator = _make_aggregator(
            fp_adp=[
                {"name": "Player C", "adp": 3.0, "overall_rank": 3, "positional_rank": 3, "position": "RB", "team": "T1"},
                {"name": "Player A", "adp": 1.0, "overall_rank": 1, "positional_rank": 1, "position": "QB", "team": "T2"},
                {"name": "Player B", "adp": 2.0, "overall_rank": 2, "positional_rank": 2, "position": "WR", "team": "T3"},
            ]
        )
        pool = aggregator.get_draft_player_pool(limit=10)
        assert pool[0].name == "Player A"
        assert pool[1].name == "Player B"
        assert pool[2].name == "Player C"

    def test_no_enrichment_sources_returns_players_unchanged(self):
        aggregator = _make_aggregator()  # empty sleeper + fp data
        players = [
            Player("Josh Allen", Position.QB, "BUF", projected_points=25.0)
        ]
        enriched = aggregator.enrich_players(players)
        assert len(enriched) == 1
        assert enriched[0].name == "Josh Allen"
        assert enriched[0].projected_points == 25.0


class TestFuzzyMatching:
    """Direct tests for the fuzzy name matching logic."""

    def test_exact_match_fast_path(self):
        aggregator = _make_aggregator()
        lookup = {"patrick mahomes": {"adp": 5.0, "name": "Patrick Mahomes"}}
        result = aggregator._fuzzy_match("Patrick Mahomes", lookup)
        assert result is not None
        assert result["adp"] == 5.0

    def test_no_match_returns_none(self):
        aggregator = _make_aggregator()
        lookup = {"totally different name": {"adp": 5.0}}
        result = aggregator._fuzzy_match("Patrick Mahomes", lookup)
        assert result is None

    def test_empty_lookup_returns_none(self):
        aggregator = _make_aggregator()
        assert aggregator._fuzzy_match("Anyone", {}) is None

    def test_empty_name_returns_none(self):
        aggregator = _make_aggregator()
        assert aggregator._fuzzy_match("", {"someone": {}}) is None
