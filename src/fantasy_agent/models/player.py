from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Position(str, Enum):
    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    K = "K"
    DST = "DST"
    UNKNOWN = "UNKNOWN"


class InjuryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUESTIONABLE = "QUESTIONABLE"
    DOUBTFUL = "DOUBTFUL"
    OUT = "OUT"
    IR = "IR"
    UNKNOWN = "UNKNOWN"


@dataclass
class PlayerStats:
    season_points: float = 0.0
    avg_points_per_game: float = 0.0
    games_played: int = 0
    last_3_avg: float = 0.0
    # Raw standard scoring stats
    passing_yards: int = 0
    passing_tds: int = 0
    rushing_yards: int = 0
    rushing_tds: int = 0
    receiving_yards: int = 0
    receiving_tds: int = 0
    receptions: int = 0
    interceptions: int = 0
    fumbles_lost: int = 0


@dataclass
class Player:
    name: str
    position: Position
    nfl_team: str

    # Cross-platform IDs for deduplication
    espn_id: Optional[str] = None
    yahoo_id: Optional[str] = None
    sleeper_id: Optional[str] = None

    # Injury info
    injury_status: InjuryStatus = InjuryStatus.ACTIVE
    injury_detail: Optional[str] = None           # e.g. "hamstring"
    injury_practice_status: Optional[str] = None  # "LP", "FP", "DNP"

    # Availability
    is_on_bye: bool = False
    bye_week: Optional[int] = None
    is_free_agent: bool = False
    ownership_pct: float = 0.0

    # Performance
    stats: PlayerStats = field(default_factory=PlayerStats)
    projected_points: float = 0.0
    projected_points_source: str = ""

    # Draft/value data
    adp: float = 999.0
    adp_source: str = ""
    positional_rank: Optional[int] = None
    overall_rank: Optional[int] = None

    # Depth chart
    depth_chart_order: Optional[int] = None  # 1 = starter, 2 = backup
    snap_count_pct: Optional[float] = None

    def to_llm_summary(self) -> str:
        """Single-line summary for Claude context. Keeps tokens low."""
        injury_flag = ""
        if self.injury_status not in (InjuryStatus.ACTIVE, InjuryStatus.UNKNOWN):
            detail = f"-{self.injury_detail}" if self.injury_detail else ""
            injury_flag = f" [{self.injury_status.value}{detail}]"

        bye_flag = f" [bye wk{self.bye_week}]" if self.bye_week else ""
        proj = f"{self.projected_points:.1f}" if self.projected_points else "N/A"
        avg = f"{self.stats.avg_points_per_game:.1f}" if self.stats.avg_points_per_game else "N/A"
        adp = f"{self.adp:.1f}" if self.adp < 999 else "N/A"
        rank = str(self.positional_rank) if self.positional_rank else "N/A"

        return (
            f"{self.name} ({self.position.value}, {self.nfl_team})"
            f"{injury_flag}{bye_flag} | "
            f"Proj:{proj} Avg:{avg} ADP:{adp} Rank:{rank}"
        )
