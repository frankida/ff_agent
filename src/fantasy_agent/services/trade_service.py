from typing import Optional
from ..models.player import Player, Position
from ..models.league import LeagueSettings
from ..services.data_aggregator import DataAggregator
from ..connectors.base import BaseConnector
from ..ai.client import FantasyAIClient
from ..ai.prompts import TRADE_ANALYSIS_PROMPT, PLAYER_ANALYSIS_PROMPT
from ..ai.context import ContextBuilder


class TradeService:
    def __init__(
        self,
        connector: BaseConnector,
        aggregator: DataAggregator,
        ai: FantasyAIClient,
        settings: LeagueSettings,
    ):
        self.connector = connector
        self.aggregator = aggregator
        self.ai = ai
        self.settings = settings
        self.ctx = ContextBuilder()

    def analyze_trade(
        self,
        giving_names: list[str],
        receiving_names: list[str],
        week: int,
    ) -> str:
        """Analyze a proposed trade and get Claude's verdict."""
        roster = self.connector.get_my_roster(week=week)
        roster.players = self.aggregator.enrich_players(roster.players)

        # Resolve player names to Player objects (with enriched data)
        giving = self._resolve_players(giving_names, roster.players)
        receiving = self._resolve_players_from_pool(receiving_names)

        context = self.ctx.build_trade_context(
            giving=giving,
            receiving=receiving,
            roster=roster,
            week=week,
            playoff_weeks=self.settings.playoff_weeks,
        )
        prompt = TRADE_ANALYSIS_PROMPT.format(**context)
        return self.ai.analyze(prompt, stream=True)

    def player_value(self, player_name: str, week: int) -> str:
        """Get buy/sell/hold analysis and ROS trade value for a single player."""
        # Try to find on roster first, then fall back to FA pool
        roster = self.connector.get_my_roster(week=week)
        roster.players = self.aggregator.enrich_players(roster.players)

        player = self._find_by_name(player_name, roster.players)
        if not player:
            # Search free agents
            fas = self.connector.get_free_agents(week=week, limit=100)
            fas = self.aggregator.enrich_players(fas)
            player = self._find_by_name(player_name, fas)

        if not player:
            # Build a minimal Player from FP data
            player = self._resolve_players_from_pool([player_name])[0] if player_name else None

        if not player:
            return f"Could not find player: {player_name}"

        prompt = PLAYER_ANALYSIS_PROMPT.format(
            name=player.name,
            position=player.position.value,
            nfl_team=player.nfl_team,
            week=week,
            player_summary=player.to_llm_summary(),
            schedule="(schedule data not available — check NFL.com)",
        )
        return self.ai.analyze(prompt, stream=True)

    def _resolve_players(self, names: list[str], roster_players: list[Player]) -> list[Player]:
        result = []
        for name in names:
            p = self._find_by_name(name, roster_players)
            if p:
                result.append(p)
            else:
                result.append(Player(name=name, position=Position.UNKNOWN, nfl_team=""))
        return result

    def _resolve_players_from_pool(self, names: list[str]) -> list[Player]:
        """Find players in the FantasyPros ADP pool."""
        pool = self.aggregator.get_draft_player_pool(limit=300)
        result = []
        for name in names:
            p = self._find_by_name(name, pool)
            result.append(p or Player(name=name, position=Position.UNKNOWN, nfl_team=""))
        return result

    def _find_by_name(self, name: str, players: list[Player]) -> Optional[Player]:
        name_lower = name.lower().strip()
        for p in players:
            if p.name.lower() == name_lower:
                return p
        try:
            from rapidfuzz import process, fuzz
            names_map = {p.name: p for p in players}
            result = process.extractOne(
                name, names_map.keys(), scorer=fuzz.token_sort_ratio, score_cutoff=80
            )
            if result:
                return names_map[result[0]]
        except ImportError:
            pass
        return None
