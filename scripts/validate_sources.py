#!/usr/bin/env python3
"""
Validate all data sources together: Sleeper, FantasyPros, and DataAggregator merge.

Tests that each source returns data, that the aggregator merges them correctly,
and that the merged player pool is ready for draft use.

Usage (from project root):
    python scripts/validate_sources.py

Flags:
    --no-cache    Skip cache and force fresh fetches (slow, ~30-60s)
    --verbose     Print full player details for samples
"""
import sys
import os
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fantasy_agent.connectors.sleeper import SleeperConnector
from fantasy_agent.connectors.fantasypros import FantasyProsConnector
from fantasy_agent.services.data_aggregator import DataAggregator
from fantasy_agent.cache.manager import clear_cache


# ── Output helpers ─────────────────────────────────────────────────────────────

def header(title: str):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


def ok(msg: str):
    print(f"  [PASS] {msg}")


def fail(msg: str):
    print(f"  [FAIL] {msg}")


def info(msg: str):
    print(f"         {msg}")


def fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms" if seconds < 1 else f"{seconds:.1f}s"


# ── Individual source tests ────────────────────────────────────────────────────

def test_sleeper(verbose: bool) -> bool:
    """Validate Sleeper API: player fetch + injury data."""
    header("1 / 4  Sleeper API — players + injuries")
    passed = True
    connector = SleeperConnector()

    # Players
    t0 = time.time()
    try:
        players = connector.get_all_players()
        elapsed = fmt_ms(time.time() - t0)
        count = len(players)
        if count >= 7000:
            ok(f"get_all_players: {count:,} players in {elapsed}")
        else:
            fail(f"get_all_players: only {count} players (expected ≥ 7000)")
            passed = False

        # Spot-check required fields in a sample
        sample = next(iter(players.values()))
        required = {"full_name", "position", "team"}
        missing = required - set(sample.keys())
        if missing:
            fail(f"Player record missing fields: {missing}")
            passed = False
        else:
            ok(f"Player record has required fields: {sorted(required)}")

        if verbose:
            for pid, p in list(players.items())[:5]:
                info(f"  [{pid}] {p.get('full_name')} | {p.get('position')} | {p.get('team','FA')}")

    except Exception as e:
        fail(f"get_all_players raised: {e}")
        passed = False

    # Trending players (optional — don't fail on this)
    try:
        trending = connector.get_trending_players(sport="nfl", lookback_hours=24, limit=10)
        ok(f"get_trending_players: {len(trending)} trending adds")
    except Exception as e:
        info(f"get_trending_players: {e} (non-fatal)")

    return passed


def test_fantasypros(verbose: bool) -> bool:
    """Validate FantasyPros: ADP, ECR rankings, projections."""
    header("2 / 4  FantasyPros — ADP + ECR + projections")
    passed = True
    connector = FantasyProsConnector()

    # ADP
    t0 = time.time()
    try:
        adp = connector.get_adp(scoring="std")
        elapsed = fmt_ms(time.time() - t0)
        if len(adp) >= 150:
            ok(f"get_adp(std): {len(adp)} players in {elapsed}")
        else:
            fail(f"get_adp(std): only {len(adp)} players (expected ≥ 150)")
            passed = False

        if adp:
            first = adp[0]
            required = {"name", "adp", "position"}
            missing = required - set(first.keys())
            if missing:
                fail(f"ADP record missing fields: {missing}")
                passed = False
            else:
                ok(f"ADP record has required fields; top player: {first.get('name')} ADP={first.get('adp')}")

        if verbose:
            for p in adp[:5]:
                info(f"  {p.get('name')} | {p.get('position')} | ADP={p.get('adp')}")
    except Exception as e:
        fail(f"get_adp raised: {e}")
        passed = False

    # ECR rankings by position
    for pos in ("RB", "WR", "QB"):
        t0 = time.time()
        try:
            rankings = connector.get_rankings(position=pos, scoring="std")
            elapsed = fmt_ms(time.time() - t0)
            if len(rankings) >= 20:
                ok(f"get_rankings({pos}): {len(rankings)} players in {elapsed}")
            else:
                fail(f"get_rankings({pos}): only {len(rankings)} players")
                passed = False
        except Exception as e:
            fail(f"get_rankings({pos}) raised: {e}")
            passed = False

    # Projections
    t0 = time.time()
    try:
        proj = connector.get_projections(position="QB", week=1)
        elapsed = fmt_ms(time.time() - t0)
        if len(proj) >= 20:
            ok(f"get_projections(QB, week=1): {len(proj)} players in {elapsed}")
        else:
            fail(f"get_projections(QB): only {len(proj)} players")
            passed = False
    except Exception as e:
        fail(f"get_projections raised: {e}")
        passed = False

    return passed


def test_aggregator_draft_pool(verbose: bool) -> bool:
    """Validate DataAggregator: merged draft pool with ADP/rankings/injuries."""
    header("3 / 4  DataAggregator — merged draft pool (300 players)")
    passed = True

    aggregator = DataAggregator(
        espn=None,
        yahoo=None,
        sleeper=SleeperConnector(),
        fps=FantasyProsConnector(),
        scoring="std",
    )

    t0 = time.time()
    try:
        pool = aggregator.get_draft_player_pool(limit=300)
        elapsed = fmt_ms(time.time() - t0)

        if len(pool) >= 200:
            ok(f"get_draft_player_pool: {len(pool)} players in {elapsed}")
        else:
            fail(f"get_draft_player_pool: only {len(pool)} players (expected ≥ 200)")
            passed = False

        # Check positional spread
        from collections import Counter
        pos_counts = Counter(p.position.value for p in pool)
        expected_positions = {"QB", "RB", "WR", "TE"}
        missing_positions = expected_positions - set(pos_counts.keys())
        if missing_positions:
            fail(f"Missing positions in pool: {missing_positions}")
            passed = False
        else:
            pos_summary = " | ".join(f"{pos}:{pos_counts[pos]}" for pos in sorted(pos_counts))
            ok(f"Positional spread: {pos_summary}")

        # Check that ADP was merged for top players
        top_30 = pool[:30]
        with_adp = [p for p in top_30 if p.adp < 999]
        if len(with_adp) >= 25:
            ok(f"ADP coverage: {len(with_adp)}/30 top players have ADP data")
        else:
            fail(f"ADP coverage: only {len(with_adp)}/30 top players have ADP data")
            passed = False

        # Check injury status field populated
        from fantasy_agent.models.player import InjuryStatus
        with_status = [p for p in pool if p.injury_status != InjuryStatus.UNKNOWN]
        ok(f"Injury status: {len(with_status)}/{len(pool)} players have status data")

        if verbose:
            print("\n  Top 10 players by ADP:")
            for i, p in enumerate(pool[:10], 1):
                adp_str = f"{p.adp:.1f}" if p.adp < 999 else "-"
                info(
                    f"  {i:2}. {p.name:<22} {p.position.value:<4} {p.nfl_team:<4} "
                    f"ADP={adp_str:>6}  "
                    f"inj={p.injury_status.value}"
                )

    except Exception as e:
        fail(f"get_draft_player_pool raised: {e}")
        import traceback
        traceback.print_exc()
        passed = False

    return passed


def test_name_matching(verbose: bool) -> bool:
    """Validate fuzzy name matching across sources."""
    header("4 / 4  Cross-source name matching (fuzzy merge)")
    passed = True

    aggregator = DataAggregator(
        espn=None,
        yahoo=None,
        sleeper=SleeperConnector(),
        fps=FantasyProsConnector(),
        scoring="std",
    )

    from fantasy_agent.models.player import Player, Position

    # These players have known name spelling variants across sources
    test_cases = [
        ("CeeDee Lamb", "WR", "DAL"),      # ESPN vs FantasyPros spelling
        ("D.J. Moore", "WR", "CHI"),        # punctuation variants
        ("Amon-Ra St. Brown", "WR", "DET"), # hyphenated name
        ("Patrick Mahomes", "QB", "KC"),    # clean match (sanity check)
    ]

    pool = aggregator.get_draft_player_pool(limit=300)
    pool_names_lower = {p.name.lower(): p for p in pool}

    matched = 0
    for name, pos, team in test_cases:
        # Try exact
        if name.lower() in pool_names_lower:
            p = pool_names_lower[name.lower()]
            adp_str = f"{p.adp:.1f}" if p.adp < 999 else "N/A"
            ok(f"Exact match: '{name}' → {p.name} (ADP={adp_str})")
            matched += 1
        else:
            # Try fuzzy
            try:
                from rapidfuzz import process, fuzz
                all_names = [p.name for p in pool]
                result = process.extractOne(
                    name, all_names,
                    scorer=fuzz.token_sort_ratio, score_cutoff=70
                )
                if result:
                    p = next(x for x in pool if x.name == result[0])
                    ok(f"Fuzzy match: '{name}' → '{p.name}' (score={result[1]:.0f})")
                    matched += 1
                else:
                    fail(f"No match found for '{name}'")
                    passed = False
            except Exception as e:
                info(f"Fuzzy match error for '{name}': {e}")

    ok(f"Matched {matched}/{len(test_cases)} test cases")
    if matched < len(test_cases) * 0.75:
        passed = False

    return passed


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate all fantasy data sources.")
    parser.add_argument("--no-cache", action="store_true", help="Clear cache before running")
    parser.add_argument("--verbose", action="store_true", help="Print detailed samples")
    args = parser.parse_args()

    if args.no_cache:
        print("Clearing cache...")
        clear_cache()

    total_start = time.time()

    results = {
        "Sleeper API":       test_sleeper(args.verbose),
        "FantasyPros":       test_fantasypros(args.verbose),
        "DataAggregator":    test_aggregator_draft_pool(args.verbose),
        "Name matching":     test_name_matching(args.verbose),
    }

    total_elapsed = fmt_ms(time.time() - total_start)

    header(f"SUMMARY  ({total_elapsed} total)")
    all_passed = True
    for name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All checks passed — data pipeline is ready for draft day.")
    else:
        print("Some checks FAILED — see above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
