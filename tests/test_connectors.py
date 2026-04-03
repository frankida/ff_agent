"""Tests for data connectors using mocked HTTP responses."""
import pytest
from unittest.mock import MagicMock, patch


class TestESPNConnector:
    def _make_espn_player(self, name, position, team, injury="ACTIVE", proj=15.0, pid="1"):
        p = MagicMock()
        p.name = name
        p.position = position
        p.proTeam = team
        p.injuryStatus = injury
        p.playerId = pid
        p.projected_total_points = proj
        p.percent_owned = 60.0
        p.stats = {"0": {"applied_total": 120.0, "breakdown": {"gamesPlayed": 8}}}
        return p

    def test_normalize_active_player(self):
        from fantasy_agent.connectors.espn import ESPNConnector
        connector = ESPNConnector(
            league_id=1, swid="{test}", espn_s2="test", team_id=1
        )
        espn_p = self._make_espn_player("Derrick Henry", "RB", "TEN", proj=18.5, pid="42")
        player = connector._normalize(espn_p)

        assert player.name == "Derrick Henry"
        assert player.position.value == "RB"
        assert player.nfl_team == "TEN"
        assert player.espn_id == "42"
        assert player.projected_points == 18.5
        assert player.stats.season_points == 120.0
        assert player.stats.games_played == 8
        assert player.stats.avg_points_per_game == 15.0

    def test_normalize_injured_player(self):
        from fantasy_agent.connectors.espn import ESPNConnector
        from fantasy_agent.models.player import InjuryStatus
        connector = ESPNConnector(
            league_id=1, swid="{test}", espn_s2="test", team_id=1
        )
        espn_p = self._make_espn_player("Someone", "WR", "DAL", injury="DOUBTFUL")
        player = connector._normalize(espn_p)
        assert player.injury_status == InjuryStatus.DOUBTFUL

    def test_normalize_dst(self):
        from fantasy_agent.connectors.espn import ESPNConnector
        from fantasy_agent.models.player import Position
        connector = ESPNConnector(
            league_id=1, swid="{test}", espn_s2="test", team_id=1
        )
        espn_p = self._make_espn_player("SF Defense", "D/ST", "SF")
        player = connector._normalize(espn_p)
        assert player.position == Position.DST

    def test_normalize_free_agent_flag(self):
        from fantasy_agent.connectors.espn import ESPNConnector
        connector = ESPNConnector(
            league_id=1, swid="{test}", espn_s2="test", team_id=1
        )
        espn_p = self._make_espn_player("FA Player", "WR", "NE")
        player = connector._normalize(espn_p, is_free_agent=True)
        assert player.is_free_agent is True


class TestSleeperConnector:
    @patch("fantasy_agent.connectors.sleeper.httpx.get")
    def test_get_all_players_calls_correct_url(self, mock_get):
        from fantasy_agent.connectors.sleeper import SleeperConnector

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "123": {"full_name": "Patrick Mahomes", "position": "QB", "team": "KC"}
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        conn = SleeperConnector()
        result = conn.get_all_players.__wrapped__(conn)  # bypass cache

        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert "sleeper.app" in call_url
        assert "players/nfl" in call_url
        assert "Mahomes" in result["123"]["full_name"]

    @patch("fantasy_agent.connectors.sleeper.httpx.get")
    def test_get_trending_adds_enriches_with_names(self, mock_get):
        from fantasy_agent.connectors.sleeper import SleeperConnector

        all_players_data = {
            "999": {"full_name": "Gus Edwards", "position": "RB", "team": "LAC"}
        }
        trending_data = [{"player_id": "999", "count": 1500}]

        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if "trending" in url:
                resp.json.return_value = trending_data
            else:
                resp.json.return_value = all_players_data
            return resp

        mock_get.side_effect = side_effect

        conn = SleeperConnector()
        # Bypass cache for both methods
        conn.get_all_players = lambda: all_players_data
        result = conn.get_trending_adds.__wrapped__(conn, lookback_hours=24, limit=25)

        assert len(result) == 1
        assert result[0]["name"] == "Gus Edwards"
        assert result[0]["add_count"] == 1500


class TestFantasyProsConnector:
    def test_parse_pos_rank(self):
        from fantasy_agent.connectors.fantasypros import FantasyProsConnector
        conn = FantasyProsConnector()
        assert conn._parse_pos_rank("RB12") == 12
        assert conn._parse_pos_rank("WR3") == 3
        assert conn._parse_pos_rank("QB1") == 1
        assert conn._parse_pos_rank("") is None
        assert conn._parse_pos_rank(None) is None

    def test_parse_ecr_from_embedded_json(self):
        from fantasy_agent.connectors.fantasypros import FantasyProsConnector
        conn = FantasyProsConnector()
        html = """
        <script>
        var ecrData = {"players": [
            {"player_name": "Josh Allen", "player_team_id": "BUF",
             "player_position_id": "QB", "rank_ecr": 1, "pos_rank": "QB1",
             "rank_min": 1, "rank_max": 3, "proj_pts": 24.5}
        ]};
        </script>
        """
        result = conn._parse_ecr(html)
        assert len(result) == 1
        assert result[0]["name"] == "Josh Allen"
        assert result[0]["overall_rank"] == 1
        assert result[0]["positional_rank"] == 1
        assert result[0]["projected_points"] == 24.5

    def test_parse_ecr_falls_back_to_table(self):
        from fantasy_agent.connectors.fantasypros import FantasyProsConnector
        conn = FantasyProsConnector()
        # No ecrData JS variable — should not raise
        result = conn._parse_ecr("<html><body>No data here</body></html>")
        assert isinstance(result, list)

    def test_parse_adp_from_embedded_json(self):
        from fantasy_agent.connectors.fantasypros import FantasyProsConnector
        conn = FantasyProsConnector()
        html = """
        <script>
        var adpData = {"players": [
            {"player_name": "Christian McCaffrey", "player_team_id": "SF",
             "player_position_id": "RB", "avg": "1.2", "rank_ecr": 1, "pos_rank": "RB1"}
        ]};
        </script>
        """
        result = conn._parse_adp(html)
        assert len(result) == 1
        assert result[0]["name"] == "Christian McCaffrey"
        assert result[0]["adp"] == 1.2
