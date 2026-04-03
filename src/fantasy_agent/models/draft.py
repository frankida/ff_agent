from dataclasses import dataclass, field
from typing import Optional
from .player import Player


@dataclass
class DraftState:
    pick_position: int          # Your draft slot (1-indexed)
    total_teams: int
    total_rounds: int = 15

    # Counters
    overall_pick: int = 1
    current_round: int = 1
    pick_in_round: int = 1

    # Tracking
    my_players: list[Player] = field(default_factory=list)
    all_drafted: list[Player] = field(default_factory=list)
    drafted_ids: set[str] = field(default_factory=set)

    def is_my_pick(self) -> bool:
        """
        True when the current overall pick belongs to the user.

        advance() uses an ascending counter in odd rounds (1→N) and a
        descending counter in even rounds (N→1), so pick_in_round always
        equals pick_position when it's the user's turn regardless of direction.
        """
        return self.pick_in_round == self.pick_position

    def advance(self):
        """Move counters forward one pick."""
        self.overall_pick += 1
        if self.current_round % 2 == 1:
            # Odd round: ascending
            if self.pick_in_round < self.total_teams:
                self.pick_in_round += 1
            else:
                self.current_round += 1
                # Stay at total_teams for start of next (even) round
        else:
            # Even round: descending
            if self.pick_in_round > 1:
                self.pick_in_round -= 1
            else:
                self.current_round += 1
                self.pick_in_round = 1  # Start of next odd round

    def is_complete(self) -> bool:
        return self.current_round > self.total_rounds

    def position_counts(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(p.position.value for p in self.my_players))

    def needs_summary(self) -> str:
        """Human-readable summary of positional needs."""
        targets = {"QB": 1, "RB": 4, "WR": 4, "TE": 1, "K": 1, "DST": 1}
        counts = self.position_counts()
        needs = []
        for pos, target in targets.items():
            current = counts.get(pos, 0)
            if current < target:
                needs.append(f"{pos}({current}/{target})")
        return ", ".join(needs) if needs else "Balanced"

    def to_dict(self) -> dict:
        """Serializable dict for state persistence."""
        return {
            "pick_position": self.pick_position,
            "total_teams": self.total_teams,
            "total_rounds": self.total_rounds,
            "overall_pick": self.overall_pick,
            "current_round": self.current_round,
            "pick_in_round": self.pick_in_round,
            "my_players": [
                {"name": p.name, "position": p.position.value,
                 "nfl_team": p.nfl_team, "espn_id": p.espn_id}
                for p in self.my_players
            ],
            "drafted_ids": list(self.drafted_ids),
        }
