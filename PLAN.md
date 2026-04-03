# Fantasy Agent — Build Plan

## Goal

A terminal-based AI fantasy football assistant that acts like a knowledgeable friend sitting next to you during your draft and throughout the season. Fast, opinionated, and optimized for standard scoring.

## Platform

ESPN first. Yahoo later if needed.

---

## Phase 1 — Validate Data Pipeline

Before anything else, confirm each data source actually works.

**Tasks:**
- [ ] Test `FantasyProsConnector.get_adp()` — does it return real players with ADP values?
- [ ] Test `FantasyProsConnector.get_rankings()` — does the ECR scrape still work?
- [ ] Test `SleeperConnector.get_injury_and_depth()` — does the free API return current data?
- [ ] Test `ESPNConnector` against a real league — roster, matchup, free agents
- [ ] Test `DataAggregator.get_draft_player_pool()` — does fuzzy name matching produce a clean merged list?

**Deliverable:** A `scripts/validate_sources.py` script that hits each source and prints results. Run it before each draft season to confirm nothing broke.

---

## Phase 2 — Draft Assistant (Core Feature)

### 2a. Multi-turn conversation

Replace the current single-shot Claude call with a persistent conversation that lives for the entire draft.

Current behavior:
```
Each pick → fresh prompt → Claude response (no memory)
```

Target behavior:
```
Draft start → Claude is briefed on league settings
Each pick   → Claude sees full draft history → recommendation
Free chat   → "who are the best handcuffs left?" → Claude knows your roster
```

Implementation: `FantasyAIClient` gets a `DraftSession` mode that maintains `messages: list[dict]` and appends each exchange.

### 2b. Interactive draft loop

Replace the current command-per-action CLI with a single interactive session:

```
$ fantasy draft start --pick 5 --teams 12

Loading players... 300 loaded (FantasyPros ADP + Sleeper injuries)
Briefing Claude on your league...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ROUND 1 | PICK 5 | OVERALL #5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
draft> rec

PICK: Saquon Barkley | RB | PHI
CONFIDENCE: High
REASON: Best available RB at pick 5. Workhorse role locked in...
ALTERNATIVE: Derrick Henry

draft> pick saquon
  ✓ Recorded: Saquon Barkley (RB, PHI)

draft> opp "josh allen"
  ✓ Opponent pick: Josh Allen (QB, BUF)

draft> board rb
  Top available RBs:
  1. Derrick Henry (RB5, ADP 6.2)
  ...

draft> who should i pair with saquon?
  With Saquon locked in as your RB1, you want a high-upside WR here...
```

### 2c. Draft state persistence

Draft state already saves to `~/.fantasy_agent/draft_state.json`. Keep this. Add resume flow for if the terminal crashes mid-draft.

---

## Phase 3 — In-Season: Start/Sit

Weekly lineup decisions. Needs:
- Current week's matchup from ESPN
- Roster with injury overlays from Sleeper
- FantasyPros weekly projections
- Claude with full roster context

Target flow:
```
$ fantasy roster start-sit

Fetching week 4 data...
WEEK 4 LINEUP — YOUR TEAM vs THE DESTROYERS

START  Saquon Barkley   RB  PHI  vs DAL  proj: 18.4  ✓ Active
START  Ja'Marr Chase    WR  CIN  vs PIT  proj: 16.1  ✓ Active
FLEX?  DeVonta Smith    WR  PHI  vs DAL  proj: 11.2  ✓ Active
FLEX?  Rhamondre S.     RB  NE   vs MIA  proj:  9.8  Q (knee)

Claude: Start Smith in the flex. Stevenson is questionable and limited
in practice — the injury risk isn't worth it when Smith has a plus
matchup against Dallas's soft CB2...
```

---

## Phase 4 — Waiver Wire

Post-waiver deadline analysis. Needs:
- Sleeper trending adds (last 24h buzz)
- Your current roster weaknesses
- FantasyPros projections for available players

---

## Phase 5 — Trade Analysis

Evaluate incoming trades. Needs:
- Rest-of-season schedule data
- Player value (ECR + projected points)
- Your roster balance post-trade

---

## Key Architecture Decisions

### Claude as conversation partner, not oracle
Each feature should feel like chatting with an expert, not querying a database. Multi-turn context is essential for the draft. For in-season features, single-turn is fine.

### Data is loaded once, used fast
Scraping happens at session start. During a live draft, every second counts — no HTTP calls mid-pick. Everything is cached locally (SQLite, TTL-based).

### ESPN only (for now)
Yahoo connector exists but is untested. Focus ESPN until it's solid.

### Standard scoring throughout
All prompts, ranking pulls, and ADP fetches use `scoring=std`. This is not configurable yet — add it later if needed.

---

## Current Branch

All development on `dev/draft-assistant`. Merge to `main` when a phase is complete and tested.

## Open Questions

- Does FantasyPros still embed `ecrData` as a JS variable, or did they change their page structure?
- Does ESPN's `espn-api` Python library work for the 2025 season?
- How do we handle a draft where we don't have ESPN credentials (mock draft mode)?
