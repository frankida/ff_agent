from dataclasses import dataclass, field
from typing import Optional
from .player import Player, Position


@dataclass
class Roster:
    players: list[Player]
    team_name: str
    platform: str  # "espn" or "yahoo"
    week: Optional[int] = None

    def by_position(self, position: Position) -> list[Player]:
        return [p for p in self.players if p.position == position]

    def starters(self, slots: dict) -> list[Player]:
        """Returns likely starters based on slot config. Simple greedy fill."""
        result = []
        used = set()
        for pos, count in slots.items():
            if pos in ("BN", "FLEX"):
                continue
            eligible = [
                p for p in self.players
                if p.position.value == pos and id(p) not in used
            ]
            eligible.sort(key=lambda p: p.projected_points, reverse=True)
            for p in eligible[:count]:
                result.append(p)
                used.add(id(p))
        return result

    def bench(self, slots: dict) -> list[Player]:
        starters_ids = {id(p) for p in self.starters(slots)}
        return [p for p in self.players if id(p) not in starters_ids]

    def injured_players(self) -> list[Player]:
        from .player import InjuryStatus
        risky = {InjuryStatus.QUESTIONABLE, InjuryStatus.DOUBTFUL,
                 InjuryStatus.OUT, InjuryStatus.IR}
        return [p for p in self.players if p.injury_status in risky]

    def to_summary(self) -> str:
        lines = [f"Roster: {self.team_name} ({self.platform.upper()})"]
        for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
            pos_players = [p for p in self.players if p.position.value == pos]
            for p in pos_players:
                lines.append(f"  {p.to_llm_summary()}")
        return "\n".join(lines)
