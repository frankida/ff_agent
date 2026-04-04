import json
import re
from pathlib import Path
from typing import Optional
from ..models.draft import DraftState
from ..models.player import Player, Position
from ..services.data_aggregator import DataAggregator
from ..ai.client import DraftConversation
from ..ai.prompts import DRAFT_PICK_PROMPT
from ..ai.context import ContextBuilder, build_draft_briefing, build_opponent_picks_summary

STATE_PATH = Path.home() / ".fantasy_agent" / "draft_state.json"


class DraftService:
    def __init__(
        self,
        aggregator: DataAggregator,
        conversation: DraftConversation,
        pick_position: int,
        total_teams: int,
        total_rounds: int = 15,
        scoring: str = "std",
    ):
        self.aggregator = aggregator
        self.conversation = conversation
        self.ctx = ContextBuilder()
        self.scoring = scoring
        self.state = DraftState(
            pick_position=pick_position,
            total_teams=total_teams,
            total_rounds=total_rounds,
            pick_in_round=1,
        )
        self._player_pool: list[Player] = []

    def initialize(self):
        """Load the full draft player pool and inject opening briefing into conversation."""
        self._player_pool = self.aggregator.get_draft_player_pool(limit=300)

        # Inject the opening briefing — no API call, just seeds the conversation history
        briefing = build_draft_briefing(
            total_teams=self.state.total_teams,
            pick_position=self.state.pick_position,
            scoring=self.scoring,
            top_available=self._player_pool,
        )
        self.conversation.inject_context(briefing)

    @classmethod
    def resume(
        cls,
        aggregator: DataAggregator,
        conversation: DraftConversation,
    ) -> Optional["DraftService"]:
        """Restore a draft session from the saved state file."""
        if not STATE_PATH.exists():
            return None
        with open(STATE_PATH) as f:
            data = json.load(f)

        service = cls(
            aggregator=aggregator,
            conversation=conversation,
            pick_position=data["pick_position"],
            total_teams=data["total_teams"],
            total_rounds=data["total_rounds"],
        )
        service.state.overall_pick = data["overall_pick"]
        service.state.current_round = data["current_round"]
        service.state.pick_in_round = data["pick_in_round"]
        service.state.drafted_ids = set(data["drafted_ids"])

        _pos_map = {p.value: p for p in Position}
        for p_data in data["my_players"]:
            service.state.my_players.append(Player(
                name=p_data["name"],
                position=_pos_map.get(p_data["position"], Position.UNKNOWN),
                nfl_team=p_data["nfl_team"],
                espn_id=p_data.get("espn_id"),
            ))

        service.initialize()
        return service

    def get_recommendation(self) -> str:
        """Ask Claude to recommend a pick for the current turn (multi-turn)."""
        available = self._get_available()
        ctx = self.ctx.build_draft_context(self.state, available)
        prompt = DRAFT_PICK_PROMPT.format(**ctx)

        print()
        return self.conversation.send(prompt, stream=True)

    def chat(self, user_input: str) -> str:
        """Free-form question — sent to Claude with full draft history as context."""
        return self.conversation.send(user_input, stream=True)

    def record_my_pick(self, player_name: str) -> Optional[Player]:
        """Record that you drafted a player and inform the conversation."""
        player = self._find_player(player_name)
        if not player:
            print(f"  Warning: '{player_name}' not found. Recorded by name only.")
            player = Player(name=player_name, position=Position.UNKNOWN, nfl_team="")

        self.state.my_players.append(player)
        uid = player.espn_id or player.name
        self.state.drafted_ids.add(uid)
        self.state.all_drafted.append(player)
        self.state.advance()
        self._save_state()

        self.conversation.inject_context(
            f"I drafted {player.name} ({player.position.value}, {player.nfl_team})."
        )
        print(f"  Recorded your pick: {player.name}")
        return player

    def record_opponent_pick(self, player_name: str) -> Optional[Player]:
        """Record that another team drafted a player and update conversation context."""
        player = self._find_player(player_name)
        if not player:
            player = Player(name=player_name, position=Position.UNKNOWN, nfl_team="")

        uid = player.espn_id or player.name
        self.state.drafted_ids.add(uid)
        self.state.all_drafted.append(player)
        self.state.advance()
        self._save_state()

        self.conversation.inject_context(build_opponent_picks_summary([player]))
        return player

    def record_opponent_picks_batch(self, players: list[Player]):
        """Batch-inject multiple opponent picks into the conversation (no API call)."""
        for player in players:
            uid = player.espn_id or player.name
            self.state.drafted_ids.add(uid)
            self.state.all_drafted.append(player)
            self.state.advance()
        self._save_state()
        if players:
            self.conversation.inject_context(build_opponent_picks_summary(players))

    def show_board(self, position: Optional[str] = None, limit: int = 30) -> list[Player]:
        """Return top available players, optionally filtered by position."""
        available = self._get_available()
        if position:
            available = [p for p in available if p.position.value == position.upper()]
        return available[:limit]

    def show_my_roster(self) -> list[Player]:
        return self.state.my_players

    def _get_available(self) -> list[Player]:
        return [p for p in self._player_pool if not self._is_drafted(p)]

    def _is_drafted(self, player: Player) -> bool:
        if player.espn_id and player.espn_id in self.state.drafted_ids:
            return True
        drafted_names = {p.name.lower() for p in self.state.all_drafted}
        return player.name.lower() in drafted_names

    @staticmethod
    def _norm(s: str) -> str:
        """Strip dots/punctuation for matching: 'a.j.' → 'aj', 'D.K.' → 'dk'."""
        return re.sub(r'[^a-z0-9 ]', '', s.lower())

    def _find_player(self, name: str) -> Optional[Player]:
        name_lower = name.lower()
        name_norm = self._norm(name)
        # Exact match (raw and normalized)
        for p in self._player_pool:
            if p.name.lower() == name_lower or self._norm(p.name) == name_norm:
                return p
        # Partial: all words in query appear in player name (handles "bucky" → "Bucky Irving")
        # Require at least 3 chars total to avoid false matches on single letters
        words = name_norm.split()
        if len(name_norm.replace(' ', '')) >= 3:
            for p in self._player_pool:
                pname = self._norm(p.name)
                if all(w in pname for w in words):
                    return p
        # Fuzzy fallback
        try:
            from rapidfuzz import process, fuzz
            names = [p.name for p in self._player_pool]
            result = process.extractOne(
                name, names, scorer=fuzz.token_sort_ratio, score_cutoff=75
            )
            if result:
                matched_name = result[0]
                for p in self._player_pool:
                    if p.name == matched_name:
                        return p
        except ImportError:
            pass
        return None

    def _save_state(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2)
