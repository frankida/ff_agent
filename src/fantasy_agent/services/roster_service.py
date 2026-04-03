from ..models.roster import Roster
from ..models.league import LeagueSettings
from ..services.data_aggregator import DataAggregator
from ..ai.client import FantasyAIClient
from ..ai.prompts import START_SIT_PROMPT, MATCHUP_PREVIEW_PROMPT
from ..ai.context import ContextBuilder
from ..connectors.base import BaseConnector


class RosterService:
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

    def get_roster(self, week: int) -> Roster:
        roster = self.connector.get_my_roster(week=week)
        roster.players = self.aggregator.enrich_players(roster.players)
        return roster

    def start_sit_analysis(self, week: int, position: str = None) -> str:
        """Get Claude's optimal lineup recommendation."""
        roster = self.get_roster(week)
        matchup = self.connector.get_matchup(week=week)

        context = self.ctx.build_start_sit_context(
            roster=roster,
            matchup=matchup,
            week=week,
            roster_slots=self.settings.roster_slots,
        )
        prompt = START_SIT_PROMPT.format(**context)
        if position:
            prompt += f"\n\nFOCUS ONLY on the {position.upper()} position decisions."

        return self.ai.analyze(prompt, stream=True)

    def matchup_preview(self, week: int) -> str:
        """Preview this week's matchup with key player analysis."""
        matchup = self.connector.get_matchup(week=week)
        roster = self.get_roster(week)

        # Build starters summary
        starters = roster.starters(self.settings.roster_slots)
        starters_str = "\n".join(f"  {p.to_llm_summary()}" for p in starters)

        prompt = MATCHUP_PREVIEW_PROMPT.format(
            week=week,
            my_team=matchup.get("my_team", "Your Team"),
            opponent=matchup.get("opponent", "Opponent"),
            my_projected=matchup.get("my_projected", 0.0),
            opp_projected=matchup.get("opp_projected", 0.0),
            my_starters=starters_str,
            opp_starters="(opponent starters not available via API)",
        )
        return self.ai.analyze(prompt, stream=True)
