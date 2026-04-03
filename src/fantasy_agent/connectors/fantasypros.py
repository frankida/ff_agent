import re
import json
import httpx
from typing import Optional
from bs4 import BeautifulSoup
from ..cache.manager import cache

FP_BASE = "https://www.fantasypros.com/nfl"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


class FantasyProsConnector:
    """
    Scrapes FantasyPros for consensus rankings (ECR) and ADP.
    scoring param: 'std' for standard (no PPR), 'ppr', 'half-ppr'
    """

    @cache(ttl_seconds=3600)
    def get_rankings(self, position: str, scoring: str = "std") -> list[dict]:
        """
        Weekly expert consensus rankings (ECR) for a position.
        Returns list of player dicts with rank, name, team, pos_rank, projected pts.
        """
        pos = position.lower()
        url = f"{FP_BASE}/rankings/{pos}.php"
        params = {"scoring": scoring}
        try:
            resp = httpx.get(url, params=params, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            return self._parse_ecr(resp.text)
        except Exception as e:
            return []

    @cache(ttl_seconds=86400)
    def get_adp(self, scoring: str = "std") -> list[dict]:
        """
        Overall ADP for draft mode. Cached for 24h (changes slowly).
        Returns list sorted by ADP with player name, team, position, adp, rank.
        """
        url = f"{FP_BASE}/adp/overall.php"
        try:
            resp = httpx.get(url, params={"scoring": scoring}, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            return self._parse_adp(resp.text)
        except Exception:
            return []

    @cache(ttl_seconds=3600)
    def get_projections(self, position: str, week: int, scoring: str = "std") -> list[dict]:
        """
        Weekly projections for a position.
        Returns list of player dicts with projected fantasy points.
        """
        pos = position.lower()
        url = f"{FP_BASE}/projections/{pos}.php"
        params = {"scoring": scoring, "week": week}
        try:
            resp = httpx.get(url, params=params, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            return self._parse_projections(resp.text)
        except Exception:
            return []

    def get_all_rankings(self, scoring: str = "std") -> list[dict]:
        """Fetch rankings for all positions and return combined list."""
        all_rankings = []
        for pos in ["qb", "rb", "wr", "te", "k", "dst"]:
            try:
                ranks = self.get_rankings(pos, scoring=scoring)
                all_rankings.extend(ranks)
            except Exception:
                pass
        return all_rankings

    # ── Parsing helpers ──────────────────────────────────────────────────────

    def _parse_ecr(self, html: str) -> list[dict]:
        """FantasyPros embeds ECR data as `var ecrData = {...}` in a script tag."""
        match = re.search(r"var ecrData\s*=\s*(\{.*?\});", html, re.DOTALL)
        if not match:
            return self._parse_ecr_table(html)
        try:
            data = json.loads(match.group(1))
            players = data.get("players", [])
            result = []
            for p in players:
                result.append({
                    "name": p.get("player_name", ""),
                    "team": p.get("player_team_id", ""),
                    "position": p.get("player_position_id", ""),
                    "overall_rank": p.get("rank_ecr"),
                    "positional_rank": self._parse_pos_rank(p.get("pos_rank", "")),
                    "best_rank": p.get("rank_min"),
                    "worst_rank": p.get("rank_max"),
                    "projected_points": p.get("proj_pts"),
                })
            return result
        except (json.JSONDecodeError, KeyError):
            return self._parse_ecr_table(html)

    def _parse_ecr_table(self, html: str) -> list[dict]:
        """Fallback: parse the HTML table if JS parsing fails."""
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table.player-table tbody tr")
        result = []
        for i, row in enumerate(rows, 1):
            cols = row.select("td")
            if len(cols) < 3:
                continue
            name_el = row.select_one("a.player-name")
            team_el = row.select_one("span.player-team")
            result.append({
                "name": name_el.text.strip() if name_el else "",
                "team": team_el.text.strip() if team_el else "",
                "overall_rank": i,
                "positional_rank": i,
                "projected_points": None,
            })
        return result

    def _parse_adp(self, html: str) -> list[dict]:
        """Parse ADP table from FantasyPros ADP page."""
        # FantasyPros embeds ADP data as `var adpData = {...}`
        match = re.search(r"var adpData\s*=\s*(\{.*?\});", html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                players = data.get("players", [])
                result = []
                for p in players:
                    result.append({
                        "name": p.get("player_name", ""),
                        "team": p.get("player_team_id", ""),
                        "position": p.get("player_position_id", ""),
                        "adp": float(p.get("avg", 999)),
                        "overall_rank": p.get("rank_ecr"),
                        "positional_rank": self._parse_pos_rank(p.get("pos_rank", "")),
                    })
                return sorted(result, key=lambda x: x["adp"])
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        # Fallback: parse HTML table
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table#data tbody tr")
        result = []
        for row in rows:
            cols = row.select("td")
            if len(cols) < 5:
                continue
            name_el = row.select_one("a.player-name")
            try:
                adp_val = float(cols[-1].text.strip().replace(",", ""))
            except ValueError:
                adp_val = 999.0
            result.append({
                "name": name_el.text.strip() if name_el else "",
                "adp": adp_val,
                "overall_rank": None,
                "positional_rank": None,
            })
        return result

    def _parse_projections(self, html: str) -> list[dict]:
        """Parse weekly projection table."""
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table#data tbody tr")
        result = []
        for row in rows:
            name_el = row.select_one("a.player-name")
            cols = row.select("td")
            if not name_el or len(cols) < 2:
                continue
            try:
                pts = float(cols[-1].text.strip())
            except ValueError:
                pts = 0.0
            result.append({
                "name": name_el.text.strip(),
                "projected_points": pts,
            })
        return result

    def _parse_pos_rank(self, pos_rank_str: str) -> Optional[int]:
        """Convert 'RB12' -> 12, 'WR3' -> 3."""
        if not pos_rank_str:
            return None
        match = re.search(r"(\d+)", str(pos_rank_str))
        return int(match.group(1)) if match else None
