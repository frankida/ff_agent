from typing import Optional
from ..models.player import Player, InjuryStatus, Position
from ..connectors.espn import ESPNConnector
from ..connectors.yahoo import YahooConnector
from ..connectors.sleeper import SleeperConnector
from ..connectors.fantasypros import FantasyProsConnector


class DataAggregator:
    """
    Merges player data from ESPN/Yahoo with enrichment from Sleeper (injury/depth)
    and FantasyPros (ADP + rankings). Uses fuzzy name matching to link records.
    """

    def __init__(
        self,
        espn: Optional[ESPNConnector],
        yahoo: Optional[YahooConnector],
        sleeper: SleeperConnector,
        fps: FantasyProsConnector,
        scoring: str = "std",
    ):
        self.espn = espn
        self.yahoo = yahoo
        self.sleeper = sleeper
        self.fps = fps
        self.scoring = scoring

    def enrich_players(self, players: list[Player]) -> list[Player]:
        """
        Takes a raw player list (from ESPN or Yahoo) and enriches each player
        with Sleeper injury/depth data and FantasyPros rankings/ADP.
        """
        sleeper_data = self.sleeper.get_injury_and_depth()
        fp_rankings = self.fps.get_all_rankings(scoring=self.scoring)
        fp_adp = self.fps.get_adp(scoring=self.scoring)

        # Build lookup maps for O(1) matching after fuzzy search
        sleeper_name_map = self._build_sleeper_name_map(sleeper_data)
        fp_name_map = self._build_fp_name_map(fp_rankings)
        fp_adp_map = self._build_fp_name_map(fp_adp)

        for player in players:
            self._enrich_from_sleeper(player, sleeper_name_map)
            self._enrich_from_fp_rankings(player, fp_name_map)
            self._enrich_from_fp_adp(player, fp_adp_map)

        return players

    def get_draft_player_pool(self, limit: int = 300) -> list[Player]:
        """
        Builds the full draft player pool from FantasyPros ADP
        (not from any specific league — represents all draftable players).
        """
        adp_list = self.fps.get_adp(scoring=self.scoring)
        sleeper_data = self.sleeper.get_injury_and_depth()
        sleeper_name_map = self._build_sleeper_name_map(sleeper_data)

        _pos_map = {"QB": Position.QB, "RB": Position.RB, "WR": Position.WR,
                    "TE": Position.TE, "K": Position.K, "DST": Position.DST,
                    "DEF": Position.DST, "D/ST": Position.DST}

        players = []
        for p in adp_list[:limit]:
            name = p.get("name", "")
            if not name:
                continue
            pos_raw = p.get("position", "")
            pos = _pos_map.get(pos_raw.upper(), Position.UNKNOWN)
            player = Player(
                name=name,
                position=pos,
                nfl_team=p.get("team", ""),
                adp=p.get("adp", 999.0),
                adp_source="fantasypros",
                overall_rank=p.get("overall_rank"),
                positional_rank=p.get("positional_rank"),
            )
            self._enrich_from_sleeper(player, sleeper_name_map)
            players.append(player)

        players.sort(key=lambda p: p.adp)
        return players

    # ── Sleeper enrichment ───────────────────────────────────────────────────

    def _enrich_from_sleeper(self, player: Player, sleeper_map: dict) -> None:
        match = self._fuzzy_match(player.name, sleeper_map, threshold=85)
        if not match:
            return
        player.sleeper_id = match.get("sleeper_id")
        player.injury_detail = match.get("injury_body_part")
        player.injury_practice_status = match.get("practice_participation")
        player.bye_week = match.get("bye_week")

        # Only update injury status from Sleeper if ESPN/Yahoo didn't set it
        if player.injury_status == InjuryStatus.ACTIVE:
            raw_status = (match.get("injury_status") or "").upper()
            _map = {
                "Q": InjuryStatus.QUESTIONABLE,
                "D": InjuryStatus.DOUBTFUL,
                "O": InjuryStatus.OUT,
                "IR": InjuryStatus.IR,
                "OUT": InjuryStatus.OUT,
                "QUESTIONABLE": InjuryStatus.QUESTIONABLE,
                "DOUBTFUL": InjuryStatus.DOUBTFUL,
            }
            if raw_status in _map:
                player.injury_status = _map[raw_status]

        depth = match.get("depth_chart_order")
        if depth:
            player.depth_chart_order = depth

    # ── FantasyPros enrichment ───────────────────────────────────────────────

    def _enrich_from_fp_rankings(self, player: Player, fp_map: dict) -> None:
        match = self._fuzzy_match(player.name, fp_map, threshold=85)
        if not match:
            return
        if match.get("overall_rank"):
            player.overall_rank = match["overall_rank"]
        if match.get("positional_rank"):
            player.positional_rank = match["positional_rank"]
        if match.get("projected_points") and not player.projected_points:
            player.projected_points = match["projected_points"]
            player.projected_points_source = "fantasypros"

    def _enrich_from_fp_adp(self, player: Player, adp_map: dict) -> None:
        match = self._fuzzy_match(player.name, adp_map, threshold=85)
        if not match:
            return
        if match.get("adp") and player.adp >= 999:
            player.adp = match["adp"]
            player.adp_source = "fantasypros"
        if match.get("overall_rank") and not player.overall_rank:
            player.overall_rank = match["overall_rank"]
        if match.get("positional_rank") and not player.positional_rank:
            player.positional_rank = match["positional_rank"]

    # ── Name matching helpers ────────────────────────────────────────────────

    def _build_sleeper_name_map(self, sleeper_data: dict) -> dict[str, dict]:
        """Map lowercase full name -> sleeper data dict."""
        result = {}
        for pid, data in sleeper_data.items():
            name = data.get("full_name", "")
            if name:
                result[name.lower()] = {"sleeper_id": pid, **data}
        return result

    def _build_fp_name_map(self, fp_list: list[dict]) -> dict[str, dict]:
        """Map lowercase player name -> fp data dict."""
        result = {}
        for p in fp_list:
            name = p.get("name", "")
            if name:
                result[name.lower()] = p
        return result

    def _fuzzy_match(
        self, name: str, lookup: dict[str, dict], threshold: int = 85
    ) -> Optional[dict]:
        """
        Fuzzy match player name against a lookup dict.
        Returns the matched data dict or None.
        """
        if not name or not lookup:
            return None
        # Exact match first (fast path)
        exact = lookup.get(name.lower())
        if exact:
            return exact
        try:
            from rapidfuzz import process, fuzz
            result = process.extractOne(
                name.lower(),
                lookup.keys(),
                scorer=fuzz.token_sort_ratio,
                score_cutoff=threshold,
            )
            if result:
                return lookup[result[0]]
        except ImportError:
            # Graceful degradation if rapidfuzz not installed
            pass
        return None
