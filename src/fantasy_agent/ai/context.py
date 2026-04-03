from ..models.player import Player, InjuryStatus
from ..models.roster import Roster
from ..models.draft import DraftState


class ContextBuilder:
    """
    Builds token-efficient context payloads for Claude.
    Goal: keep prompts under ~2,000 tokens so Claude has room to reason.
    """

    # ── Draft context ─────────────────────────────────────────────────────────

    def build_draft_context(
        self, state: DraftState, available: list[Player], top_n: int = 30
    ) -> dict:
        my_roster_lines = []
        for p in state.my_players:
            my_roster_lines.append(f"  {p.position.value}: {p.name} ({p.nfl_team})")
        my_roster_str = "\n".join(my_roster_lines) if my_roster_lines else "  (empty)"

        top_available = available[:top_n]
        avail_lines = []
        for i, p in enumerate(top_available, 1):
            avail_lines.append(f"  {i:2}. {p.to_llm_summary()}")
        avail_str = "\n".join(avail_lines)

        return {
            "round_num": state.current_round,
            "pick_num": state.pick_in_round,
            "overall_pick": state.overall_pick,
            "needs": state.needs_summary(),
            "my_roster": my_roster_str,
            "top_available": avail_str,
        }

    # ── Roster / Start-Sit context ────────────────────────────────────────────

    def build_start_sit_context(
        self,
        roster: Roster,
        matchup: dict,
        week: int,
        roster_slots: dict,
    ) -> dict:
        roster_lines = []
        for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
            pos_players = [p for p in roster.players if p.position.value == pos]
            for p in pos_players:
                roster_lines.append(f"  {p.to_llm_summary()}")

        # Identify genuine decisions (multiple players competing for same slot)
        decisions = self._identify_decisions(roster, roster_slots)
        decisions_str = "\n".join(
            f"  {pos}: {' vs '.join(names)}" for pos, names in decisions.items()
        ) if decisions else "  No contested slots — check for injuries"

        return {
            "week": week,
            "roster_summary": "\n".join(roster_lines),
            "my_team": matchup.get("my_team", "Your Team"),
            "opponent": matchup.get("opponent", "Opponent"),
            "my_projected": matchup.get("my_projected", 0.0),
            "opp_projected": matchup.get("opp_projected", 0.0),
            "decisions_needed": decisions_str,
        }

    def _identify_decisions(self, roster: Roster, slots: dict) -> dict:
        """
        Find positions where you have more players than starting slots
        — these are the actual start/sit decisions.
        """
        decisions = {}
        for pos, count in slots.items():
            if pos in ("BN", "FLEX"):
                continue
            pos_players = [p for p in roster.players if p.position.value == pos]
            if len(pos_players) > count:
                decisions[pos] = [p.name for p in pos_players]
        # FLEX
        flex_eligible = [
            p for p in roster.players
            if p.position.value in ("RB", "WR", "TE")
        ]
        flex_count = slots.get("FLEX", 0)
        if flex_count and len(flex_eligible) > (
            slots.get("RB", 0) + slots.get("WR", 0) + slots.get("TE", 0) + flex_count
        ):
            decisions["FLEX"] = [p.name for p in flex_eligible[:4]]
        return decisions

    # ── Waiver wire context ───────────────────────────────────────────────────

    def build_waiver_context(
        self,
        roster: Roster,
        free_agents: list[Player],
        trending: list[dict],
        week: int,
        waiver_priority: int = 1,
        top_fa: int = 20,
    ) -> dict:
        # Identify roster weaknesses (injured/bye starters)
        risky = [
            p for p in roster.players
            if p.injury_status in (
                InjuryStatus.OUT, InjuryStatus.IR,
                InjuryStatus.DOUBTFUL, InjuryStatus.QUESTIONABLE
            )
        ]
        weakness_lines = [f"  {p.to_llm_summary()}" for p in risky]
        weakness_str = "\n".join(weakness_lines) if weakness_lines else "  No major injury concerns"

        # Top free agents sorted by projected points
        fas = sorted(free_agents, key=lambda p: p.projected_points, reverse=True)[:top_fa]
        fa_lines = [f"  {i+1}. {p.to_llm_summary()}" for i, p in enumerate(fas)]

        # Trending adds
        trend_lines = [
            f"  {t['name']} ({t.get('position','')}, {t.get('team','')}) — {t.get('add_count',0):,} adds"
            for t in trending[:10]
        ]

        return {
            "week": week,
            "waiver_priority": waiver_priority,
            "roster_weaknesses": weakness_str,
            "available_players": "\n".join(fa_lines),
            "trending_adds": "\n".join(trend_lines) if trend_lines else "  No trending data",
        }

    # ── Trade context ─────────────────────────────────────────────────────────

    def build_trade_context(
        self,
        giving: list[Player],
        receiving: list[Player],
        roster: Roster,
        week: int,
        playoff_weeks: list[int],
    ) -> dict:
        giving_str = "\n".join(f"  {p.to_llm_summary()}" for p in giving)
        receiving_str = "\n".join(f"  {p.to_llm_summary()}" for p in receiving)

        # Simulate post-trade roster
        giving_names = {p.name for p in giving}
        post_trade = [p for p in roster.players if p.name not in giving_names] + receiving
        post_trade_lines = []
        for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
            for p in post_trade:
                if p.position.value == pos:
                    post_trade_lines.append(f"  {p.to_llm_summary()}")

        return {
            "giving": giving_str,
            "receiving": receiving_str,
            "week": week,
            "playoff_weeks": f"Weeks {playoff_weeks[0]}–{playoff_weeks[-1]}",
            "post_trade_roster": "\n".join(post_trade_lines),
        }
