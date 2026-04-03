import httpx
from ..cache.manager import cache

SLEEPER_BASE = "https://api.sleeper.app/v1"


class SleeperConnector:
    """
    Sleeper API — free, no auth required.
    Used for: player universe, injury status, depth charts, trending adds.
    """

    @cache(ttl_seconds=3600)
    def get_all_players(self) -> dict:
        """
        Full NFL player map from Sleeper. ~5MB response, cache for 1 hour.
        Returns dict keyed by sleeper_player_id.
        """
        resp = httpx.get(f"{SLEEPER_BASE}/players/nfl", timeout=30)
        resp.raise_for_status()
        return resp.json()

    @cache(ttl_seconds=1800)
    def get_injury_and_depth(self) -> dict[str, dict]:
        """
        Injury status and depth chart data for all players.
        Returns dict keyed by sleeper_player_id.
        """
        players = self.get_all_players()
        result = {}
        for pid, p in players.items():
            injury = p.get("injury_status")
            depth = p.get("depth_chart_order")
            practice = p.get("practice_participation")
            body_part = p.get("injury_body_part")
            full_name = p.get("full_name", "")
            team = p.get("team", "")
            pos = p.get("position", "")
            if injury or depth or full_name:
                result[pid] = {
                    "full_name": full_name,
                    "team": team,
                    "position": pos,
                    "injury_status": injury,
                    "injury_body_part": body_part,
                    "practice_participation": practice,
                    "depth_chart_order": depth,
                    "bye_week": p.get("bye_week"),
                }
        return result

    @cache(ttl_seconds=1800)
    def get_trending_adds(
        self, lookback_hours: int = 24, limit: int = 25
    ) -> list[dict]:
        """
        Players being added most in the last N hours across all Sleeper leagues.
        Great for spotting waiver buzz before it hits the mainstream.
        """
        resp = httpx.get(
            f"{SLEEPER_BASE}/players/nfl/trending/add",
            params={"lookback_hours": lookback_hours, "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()

        # Enrich with player names from the player map
        all_players = self.get_all_players()
        enriched = []
        for item in raw:
            pid = str(item.get("player_id", ""))
            player_data = all_players.get(pid, {})
            enriched.append({
                "sleeper_id": pid,
                "name": player_data.get("full_name", pid),
                "position": player_data.get("position", ""),
                "team": player_data.get("team", ""),
                "add_count": item.get("count", 0),
            })
        return enriched

    def build_name_lookup(self) -> dict[str, dict]:
        """
        Returns a dict keyed by lowercase full name for fast fuzzy matching.
        Also indexes by 'lastname_team' as secondary key.
        """
        players = self.get_all_players()
        lookup = {}
        for pid, p in players.items():
            full = p.get("full_name", "")
            if full:
                lookup[full.lower()] = {"sleeper_id": pid, **p}
        return lookup
