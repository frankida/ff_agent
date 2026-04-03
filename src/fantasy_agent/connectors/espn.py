from typing import Optional
from ..models.player import Player, PlayerStats, Position, InjuryStatus
from ..models.roster import Roster
from ..cache.manager import cache
from .base import BaseConnector

# ESPN position ID -> Position enum
_ESPN_POS_MAP = {
    "QB": Position.QB,
    "RB": Position.RB,
    "WR": Position.WR,
    "TE": Position.TE,
    "K": Position.K,
    "D/ST": Position.DST,
    "DEF": Position.DST,
}

_ESPN_INJURY_MAP = {
    "ACTIVE": InjuryStatus.ACTIVE,
    "HEALTHY": InjuryStatus.ACTIVE,
    "QUESTIONABLE": InjuryStatus.QUESTIONABLE,
    "DOUBTFUL": InjuryStatus.DOUBTFUL,
    "OUT": InjuryStatus.OUT,
    "INJURY_RESERVE": InjuryStatus.IR,
    "IR": InjuryStatus.IR,
}


class ESPNConnector(BaseConnector):
    def __init__(
        self,
        league_id: int,
        swid: str,
        espn_s2: str,
        team_id: int,
        season: int = 2025,
    ):
        self._league_id = league_id
        self._team_id = team_id
        self._swid = swid
        self._espn_s2 = espn_s2
        self._season = season
        self._league = None

    def _get_league(self):
        if self._league is None:
            from espn_api.football import League
            self._league = League(
                league_id=self._league_id,
                year=self._season,
                swid=self._swid,
                espn_s2=self._espn_s2,
            )
        return self._league

    def get_current_week(self) -> int:
        return self._get_league().currentMatchupPeriod

    @cache(ttl_seconds=300)
    def get_my_roster(self, week: int) -> Roster:
        league = self._get_league()
        team = league.teams[self._team_id - 1]
        players = [self._normalize(p) for p in team.roster]
        return Roster(
            players=players,
            team_name=team.team_name,
            platform="espn",
            week=week,
        )

    @cache(ttl_seconds=900)
    def get_free_agents(
        self,
        week: int,
        position: Optional[str] = None,
        limit: int = 50,
    ) -> list[Player]:
        league = self._get_league()
        pos_filter = position or ""
        fas = league.free_agents(week=week, size=limit, position=pos_filter)
        players = [self._normalize(p, is_free_agent=True) for p in fas]
        return players

    @cache(ttl_seconds=300)
    def get_matchup(self, week: int) -> dict:
        league = self._get_league()
        team = league.teams[self._team_id - 1]
        box_scores = league.box_scores(week=week)
        for box in box_scores:
            if box.home_team == team or box.away_team == team:
                is_home = box.home_team == team
                opp = box.away_team if is_home else box.home_team
                return {
                    "my_team": team.team_name,
                    "opponent": opp.team_name,
                    "my_projected": box.home_projected if is_home else box.away_projected,
                    "opp_projected": box.away_projected if is_home else box.home_projected,
                    "my_score": box.home_score if is_home else box.away_score,
                    "opp_score": box.away_score if is_home else box.home_score,
                    "week": week,
                }
        return {}

    def _normalize(self, espn_player, is_free_agent: bool = False) -> Player:
        pos = _ESPN_POS_MAP.get(
            getattr(espn_player, "position", ""), Position.UNKNOWN
        )
        injury_raw = getattr(espn_player, "injuryStatus", "ACTIVE") or "ACTIVE"
        injury = _ESPN_INJURY_MAP.get(injury_raw.upper(), InjuryStatus.UNKNOWN)

        # Season stats live in stats dict under key "0"
        stats_raw = getattr(espn_player, "stats", {}) or {}
        season_stat = stats_raw.get("0", {})
        season_pts = season_stat.get("applied_total", 0.0) if isinstance(season_stat, dict) else 0.0
        games = season_stat.get("breakdown", {}).get("gamesPlayed", 0) if isinstance(season_stat, dict) else 0
        avg = round(season_pts / games, 2) if games else 0.0

        return Player(
            name=espn_player.name,
            position=pos,
            nfl_team=getattr(espn_player, "proTeam", ""),
            espn_id=str(getattr(espn_player, "playerId", "")),
            injury_status=injury,
            projected_points=getattr(espn_player, "projected_total_points", 0.0) or 0.0,
            projected_points_source="espn",
            is_free_agent=is_free_agent,
            ownership_pct=getattr(espn_player, "percent_owned", 0.0) or 0.0,
            stats=PlayerStats(
                season_points=season_pts,
                avg_points_per_game=avg,
                games_played=games,
            ),
        )
