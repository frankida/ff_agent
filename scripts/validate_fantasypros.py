#!/usr/bin/env python3
"""
Validation script for the FantasyPros connector.
Tests ADP, ECR rankings, and weekly projections scraping.

Usage:
    python scripts/validate_fantasypros.py
"""

import sys
import os
import time
import json
import re

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fantasy_agent.connectors.fantasypros import FantasyProsConnector

# ── Helpers ──────────────────────────────────────────────────────────────────

def print_header(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_sample(players: list[dict], n: int = 10):
    """Print first n players in a readable format."""
    for i, p in enumerate(players[:n], 1):
        line_parts = [f"  {i:>3}."]
        for k, v in p.items():
            line_parts.append(f"{k}={v}")
        print(" | ".join(line_parts))


def check_fields(players: list[dict], required_fields: list[str], label: str) -> list[str]:
    """Validate that required fields are present and non-empty in results."""
    issues = []
    if not players:
        issues.append(f"{label}: returned 0 players (EMPTY)")
        return issues
    sample = players[0]
    for field in required_fields:
        if field not in sample:
            issues.append(f"{label}: missing field '{field}'")
        elif sample[field] is None or sample[field] == "":
            issues.append(f"{label}: field '{field}' is None/empty in first record")
    return issues


# ── Debug: raw HTML inspection ───────────────────────────────────────────────

def inspect_html(url: str, params: dict, label: str):
    """Fetch raw HTML and inspect for embedded data patterns."""
    import httpx
    from bs4 import BeautifulSoup

    print(f"\n--- DEBUG: inspecting {label} ---")
    print(f"    URL: {url}")
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=20)
        print(f"    Status: {resp.status_code}")
        print(f"    Content-Length: {len(resp.text)} chars")

        html = resp.text
        soup = BeautifulSoup(html, "lxml")

        # Check for known JS data patterns
        for pattern_name, pattern in [
            ("ecrData", r"var ecrData\s*="),
            ("adpData", r"var adpData\s*="),
            ("__NEXT_DATA__", r"__NEXT_DATA__"),
            ("window.__data", r"window\.__data\s*="),
            ("dataLayer", r"dataLayer\s*="),
        ]:
            match = re.search(pattern, html)
            if match:
                start = max(0, match.start() - 10)
                end = min(len(html), match.end() + 200)
                print(f"    FOUND '{pattern_name}' at pos {match.start()}: ...{html[start:end]}...")

        # Check for data tables
        tables = soup.select("table")
        print(f"    Tables found: {len(tables)}")
        for i, t in enumerate(tables[:5]):
            tid = t.get("id", "no-id")
            tcls = " ".join(t.get("class", []))
            rows = t.select("tr")
            print(f"      table[{i}]: id={tid} class={tcls} rows={len(rows)}")

        # Check for script tags with large inline data
        scripts = soup.select("script")
        print(f"    Script tags: {len(scripts)}")
        for i, s in enumerate(scripts):
            if s.string and len(s.string) > 500:
                preview = s.string[:200].replace("\n", " ")
                print(f"      script[{i}]: {len(s.string)} chars -> {preview}...")

        # Look for player-name anchors (table fallback)
        player_links = soup.select("a.player-name")
        print(f"    <a class='player-name'>: {len(player_links)}")
        if player_links:
            print(f"      first 3: {[a.text.strip() for a in player_links[:3]]}")

        # Also look for fp-player-name (newer class)
        fp_links = soup.select("[class*='player']")
        fp_classes = set()
        for el in fp_links[:50]:
            for cls in el.get("class", []):
                if "player" in cls.lower():
                    fp_classes.add(cls)
        if fp_classes:
            print(f"    Player-related CSS classes: {sorted(fp_classes)}")

    except Exception as e:
        print(f"    ERROR fetching: {e}")


# ── Main validation ──────────────────────────────────────────────────────────

def main():
    connector = FantasyProsConnector()
    results = {}
    all_issues = []

    # ── Test 1: ADP ──────────────────────────────────────────────────────
    print_header("Test 1: get_adp(scoring='std')")
    t0 = time.time()
    adp = connector.get_adp(scoring="std")
    elapsed = time.time() - t0
    count = len(adp)
    print(f"  Returned {count} players in {elapsed:.2f}s")
    results["adp"] = {"count": count, "time": elapsed}

    if count > 0:
        print("\n  Sample (first 10):")
        print_sample(adp)
        issues = check_fields(adp, ["name", "team", "position", "adp"], "ADP")
    else:
        issues = ["ADP: returned 0 players"]
        # Debug: inspect the page
        inspect_html(
            "https://www.fantasypros.com/nfl/adp/overall.php",
            {"scoring": "std"},
            "ADP page",
        )

    all_issues.extend(issues)
    passed = count >= 200 and not issues
    results["adp"]["passed"] = passed
    print(f"\n  {'PASS' if passed else 'FAIL'}: {count} players, expected >= 200")
    if issues:
        for iss in issues:
            print(f"    - {iss}")

    # ── Test 2: ECR Rankings ─────────────────────────────────────────────
    print_header("Test 2: get_rankings('rb', 'std')")
    t0 = time.time()
    rankings = connector.get_rankings("rb", "std")
    elapsed = time.time() - t0
    count = len(rankings)
    print(f"  Returned {count} players in {elapsed:.2f}s")
    results["rankings"] = {"count": count, "time": elapsed}

    if count > 0:
        print("\n  Sample (first 10):")
        print_sample(rankings)
        issues = check_fields(rankings, ["name", "overall_rank", "positional_rank"], "Rankings")
    else:
        issues = ["Rankings: returned 0 players"]
        inspect_html(
            "https://www.fantasypros.com/nfl/rankings/rb.php",
            {"scoring": "std"},
            "ECR Rankings page",
        )

    all_issues.extend(issues)
    passed = count >= 10 and not issues
    results["rankings"]["passed"] = passed
    print(f"\n  {'PASS' if passed else 'FAIL'}: {count} players, expected >= 10")
    if issues:
        for iss in issues:
            print(f"    - {iss}")

    # ── Test 3: Projections ──────────────────────────────────────────────
    print_header("Test 3: get_projections('qb', 1, 'std')")
    t0 = time.time()
    projections = connector.get_projections("qb", 1, "std")
    elapsed = time.time() - t0
    count = len(projections)
    print(f"  Returned {count} players in {elapsed:.2f}s")
    results["projections"] = {"count": count, "time": elapsed}

    if count > 0:
        print("\n  Sample (first 10):")
        print_sample(projections)
        issues = check_fields(projections, ["name", "projected_points"], "Projections")
    else:
        issues = ["Projections: returned 0 players"]
        inspect_html(
            "https://www.fantasypros.com/nfl/projections/qb.php",
            {"scoring": "std", "week": 1},
            "Projections page",
        )

    all_issues.extend(issues)
    passed = count >= 10 and not issues
    results["projections"]["passed"] = passed
    print(f"\n  {'PASS' if passed else 'FAIL'}: {count} players, expected >= 10")
    if issues:
        for iss in issues:
            print(f"    - {iss}")

    # ── Summary ──────────────────────────────────────────────────────────
    print_header("SUMMARY")
    total = len(results)
    passed_count = sum(1 for r in results.values() if r.get("passed"))
    total_time = sum(r["time"] for r in results.values())
    print(f"  Tests:  {passed_count}/{total} passed")
    print(f"  Time:   {total_time:.2f}s total")
    print()
    for name, r in results.items():
        status = "PASS" if r.get("passed") else "FAIL"
        print(f"  [{status}] {name:>15}: {r['count']} players ({r['time']:.2f}s)")
    print()

    if all_issues:
        print("  Issues found:")
        for iss in all_issues:
            print(f"    - {iss}")
        print()

    if passed_count == total:
        print("  All tests PASSED.")
    else:
        print(f"  {total - passed_count} test(s) FAILED. See details above.")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
