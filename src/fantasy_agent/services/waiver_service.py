from ..models.league import LeagueSettings
from ..services.data_aggregator import DataAggregator
from ..connectors.base import BaseConnector
from ..connectors.sleeper import SleeperConnector
from ..ai.client import FantasyAIClient
from ..ai.prompts import WAIVER_WIRE_PROMPT
from ..ai.context import ContextBuilder


class WaiverService:
    def __init__(
        self,
        connector: BaseConnector,
        aggregator: DataAggregator,
        sleeper: SleeperConnector,
        ai: FantasyAIClient,
        settings: LeagueSettings,
    ):
        self.connector = connector
        self.aggregator = aggregator
        self.sleeper = sleeper
        self.ai = ai
        self.settings = settings
        self.ctx = ContextBuilder()

    def analyze(
        self,
        week: int,
        position: str = None,
        limit: int = 20,
        waiver_priority: int = 1,
    ) -> str:
        """Get Claude's waiver wire recommendations with drop suggestions."""
        roster = self.connector.get_my_roster(week=week)
        roster.players = self.aggregator.enrich_players(roster.players)

        free_agents = self.connector.get_free_agents(
            week=week, position=position, limit=limit
        )
        free_agents = self.aggregator.enrich_players(free_agents)

        trending = self.sleeper.get_trending_adds(lookback_hours=24, limit=25)

        context = self.ctx.build_waiver_context(
            roster=roster,
            free_agents=free_agents,
            trending=trending,
            week=week,
            waiver_priority=waiver_priority,
        )
        prompt = WAIVER_WIRE_PROMPT.format(**context)
        return self.ai.analyze(prompt, stream=True)

    def get_trending(self, hours: int = 24) -> list[dict]:
        """Return raw trending adds data from Sleeper."""
        return self.sleeper.get_trending_adds(lookback_hours=hours, limit=30)
