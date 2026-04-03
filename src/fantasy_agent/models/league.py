from dataclasses import dataclass, field


@dataclass
class LeagueSettings:
    platform: str           # "espn" or "yahoo"
    league_id: str
    team_id: str
    scoring: str            # "standard", "ppr", "half_ppr"
    season: int
    total_teams: int
    total_rounds: int
    roster_slots: dict[str, int]
    playoff_weeks: list[int] = field(default_factory=lambda: [14, 15, 16])

    @property
    def is_standard(self) -> bool:
        return self.scoring == "standard"

    @property
    def scoring_label(self) -> str:
        labels = {"standard": "Standard", "ppr": "PPR", "half_ppr": "Half-PPR"}
        return labels.get(self.scoring, self.scoring)

    @classmethod
    def from_yaml(cls, data: dict, platform: str) -> "LeagueSettings":
        return cls(
            platform=platform,
            league_id=str(data.get("league_id", "")),
            team_id=str(data.get("team_id", data.get("team_key", "1"))),
            scoring=data.get("scoring", "standard"),
            season=data.get("season", 2025),
            total_teams=data.get("total_teams", 10),
            total_rounds=data.get("total_rounds", 15),
            roster_slots=data.get("roster_slots", {}),
            playoff_weeks=data.get("playoff_weeks", [14, 15, 16]),
        )
