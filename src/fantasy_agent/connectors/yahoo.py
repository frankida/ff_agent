from typing import Optional
from pathlib import Path
from ..models.player import Player, PlayerStats, Position, InjuryStatus
from ..models.roster import Roster
from ..cache.manager import cache
from .base import BaseConnector

_YAHOO_POS_MAP = {
    "QB": Position.QB,
    "RB": Position.RB,
    "WR": Position.WR,
    "TE": Position.TE,
    "K": Position.K,
    "DEF": Position.DST,
    "D": Position.DST,
}

_TOKEN_PATH = Path.home() / ".fantasy_agent" / "yahoo_token.json"


class YahooConnector(BaseConnector):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        league_id: str,
        team_key: str,
        season: int = 2025,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._league_id = league_id
        self._team_key = team_key
        self._season = season
        self._league = None
        self._game = None

    def _get_league(self):
        if self._league is None:
            import yahoo_fantasy_api as yfa
            _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            sc = yfa.OAuth2(
                None,
                None,
                browser_callback=True,
                client_id=self._client_id,
                client_secret=self._client_secret,
                token_file=str(_TOKEN_PATH),
            )
            gm = yfa.Game(sc, "nfl")
            self._league = gm.to_league(self._league_id)
        return self._league

    def get_current_week(self) -> int:
        try:
            return self._get_league().current_week()
        except Exception:
            return 1

    @cache(ttl_seconds=300)
    def get_my_roster(self, week: int) -> Roster:
        league = self._get_league()
        team = league.to_team(self._team_key)
        raw_roster = team.roster(week=week)
        players = [self._normalize(p) for p in raw_roster]
        return Roster(
            players=players,
            team_name=self._team_key,
            platform="yahoo",
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
        pos_filter = position or "O"  # "O" = offense (all skill positions)
        try:
            fas = league.free_agents(pos_filter)
        except Exception:
            fas = []
        players = [self._normalize(p, is_free_agent=True) for p in fas[:limit]]
        return players

    @cache(ttl_seconds=300)
    def get_matchup(self, week: int) -> dict:
        try:
            league = self._get_league()
            matchups = league.matchups(week=week)
            for m in matchups.get("fantasy_content", {}).get("league", [{}])[1].get("scoreboard", {}).get("matchups", {}).values():
                if isinstance(m, dict):
                    teams = m.get("matchup", {}).get("teams", {})
                    for t in teams.values():
                        if isinstance(t, dict):
                            team_key = t.get("team", [{}])[0]
                            if isinstance(team_key, list) and len(team_key) > 0:
                                if str(team_key[0]) == self._team_key:
                                    return {"week": week, "raw": m}
        except Exception:
            pass
        return {"week": week}

    def _normalize(self, raw: dict, is_free_agent: bool = False) -> Player:
        name = raw.get("name", "Unknown")
        pos_raw = raw.get("eligible_positions", [""])[0] if raw.get("eligible_positions") else ""
        pos = _YAHOO_POS_MAP.get(pos_raw, Position.UNKNOWN)
        nfl_team = raw.get("editorial_team_abbr", "").upper()
        yahoo_id = str(raw.get("player_id", ""))

        status_raw = raw.get("status", "").upper()
        if status_raw == "Q":
            injury = InjuryStatus.QUESTIONABLE
        elif status_raw == "D":
            injury = InjuryStatus.DOUBTFUL
        elif status_raw == "O":
            injury = InjuryStatus.OUT
        elif status_raw == "IR":
            injury = InjuryStatus.IR
        else:
            injury = InjuryStatus.ACTIVE

        return Player(
            name=name,
            position=pos,
            nfl_team=nfl_team,
            yahoo_id=yahoo_id,
            injury_status=injury,
            is_free_agent=is_free_agent,
            stats=PlayerStats(),
        )
