#!/usr/bin/env python3
"""
Validate the Sleeper API connector.

Run from project root:
    python scripts/validate_sleeper.py
"""
import sys
import os
import time

# Allow running from project root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fantasy_agent.connectors.sleeper import SleeperConnector


def fmt_time(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.1f}s"


def run_tests():
    connector = SleeperConnector()
    results = []  # (test_name, passed, detail)

    # ── Test 1: get_all_players ──────────────────────────────────────────
    print("=" * 60)
    print("TEST 1: get_all_players()")
    print("=" * 60)
    t0 = time.time()
    try:
        players = connector.get_all_players()
        elapsed = time.time() - t0
        count = len(players)
        passed = isinstance(players, dict) and count >= 7000
        print(f"  Returned {count} players in {fmt_time(elapsed)}")
        print(f"  Type: {type(players).__name__}")
        print("\n  Sample (first 5):")
        for i, (pid, p) in enumerate(players.items()):
            if i >= 5:
                break
            name = p.get("full_name", "N/A")
            team = p.get("team", "FA")
            pos = p.get("position", "?")
            print(f"    [{pid}] {name} | {pos} | {team}")
        detail = f"{count} players, {fmt_time(elapsed)}"
        results.append(("get_all_players", passed, detail))
        if not passed:
            print(f"  FAIL: expected >=7000 entries, got {count}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR: {e}")
        results.append(("get_all_players", False, str(e)))

    # ── Test 2: get_injury_and_depth ─────────────────────────────────────
    print("\n" + "=" * 60)
    print("TEST 2: get_injury_and_depth()")
    print("=" * 60)
    t0 = time.time()
    try:
        injury = connector.get_injury_and_depth()
        elapsed = time.time() - t0
        count = len(injury)
        # This is a filtered subset — it includes anyone with a name, injury, or depth
        # so it should still be large (most players have full_name set)
        passed = isinstance(injury, dict) and count >= 1000
        print(f"  Returned {count} entries in {fmt_time(elapsed)}")

        # Count how many actually have injury or depth data
        with_injury = sum(1 for v in injury.values() if v.get("injury_status"))
        with_depth = sum(1 for v in injury.values() if v.get("depth_chart_order"))
        print(f"  With injury_status: {with_injury}")
        print(f"  With depth_chart_order: {with_depth}")
        print(f"  (Off-season note: injury/depth counts may be low in April)")

        print("\n  Sample (first 5):")
        for i, (pid, p) in enumerate(injury.items()):
            if i >= 5:
                break
            print(f"    [{pid}] {p.get('full_name', 'N/A')} | "
                  f"{p.get('position', '?')} | {p.get('team', 'FA')} | "
                  f"injury={p.get('injury_status')} | depth={p.get('depth_chart_order')}")
        detail = f"{count} entries ({with_injury} injured, {with_depth} w/ depth), {fmt_time(elapsed)}"
        results.append(("get_injury_and_depth", passed, detail))
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR: {e}")
        results.append(("get_injury_and_depth", False, str(e)))

    # ── Test 3: get_trending_adds ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("TEST 3: get_trending_adds(limit=10)")
    print("=" * 60)
    t0 = time.time()
    try:
        trending = connector.get_trending_adds(limit=10)
        elapsed = time.time() - t0
        count = len(trending)
        # During off-season, trending might return fewer results
        passed = isinstance(trending, list) and count >= 1
        print(f"  Returned {count} trending adds in {fmt_time(elapsed)}")

        print("\n  Sample (first 5):")
        for item in trending[:5]:
            print(f"    {item.get('name', '?')} | {item.get('position', '?')} | "
                  f"{item.get('team', 'FA')} | adds={item.get('add_count', 0)}")

        # Verify enrichment: names should not just be numeric IDs
        enriched_ok = all(
            not item.get("name", "").isdigit()
            for item in trending[:5]
            if item.get("name")
        )
        if not enriched_ok:
            print("  WARNING: some names are just numeric IDs — enrichment may have failed")

        detail = f"{count} adds, enriched={enriched_ok}, {fmt_time(elapsed)}"
        results.append(("get_trending_adds", passed, detail))
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR: {e}")
        results.append(("get_trending_adds", False, str(e)))

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    passed_count = sum(1 for _, p, _ in results if p)
    total = len(results)
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}: {detail}")
    print(f"\n  {passed_count}/{total} tests passed")
    print("=" * 60)

    return passed_count == total


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
