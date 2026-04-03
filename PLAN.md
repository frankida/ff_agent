# Fantasy Agent — Detailed Build Plan

## Goal

A terminal-based AI fantasy football assistant that acts like a knowledgeable friend sitting next to you during your draft and throughout the season. Fast, opinionated, and optimized for standard scoring.

**Platform:** ESPN first. Yahoo later if needed.

---

## Current State

Everything below has been written but **nothing has been tested against real data**.

| Component | File(s) | Status |
|---|---|---|
| Player/Roster/Draft models | `models/player.py`, `roster.py`, `draft.py`, `league.py` | Written. Player has cross-platform IDs, injury status, ADP, stats. DraftState has snake draft logic. |
| ESPN connector | `connectors/espn.py` | Written. Uses `espn-api` SDK. Has roster, free agents, matchup. Untested. |
| FantasyPros connector | `connectors/fantasypros.py` | Written. Scrapes ADP + ECR + projections. Parses `var ecrData` JS variable or falls back to HTML tables. **High risk of being broken** — FP changes their HTML regularly. |
| Sleeper connector | `connectors/sleeper.py` | Written. Hits `api.sleeper.app/v1/players/nfl` (~5MB JSON dump). Free, no auth. Likely works — stable API. |
| DataAggregator | `services/data_aggregator.py` | Written. Merges FantasyPros + Sleeper + ESPN via RapidFuzz name matching (85% threshold). Untested. |
| DraftService | `services/draft_service.py` | Written. Manages draft state, loads player pool, gets Claude recommendations. **Single-shot Claude calls — no conversation history.** |
| DraftSyncService | `services/draft_sync.py` | Written. Background thread polls ESPN `league.draft`. **CONFIRMED BROKEN** — ESPN's `league.draft` only populates after draft ends ([espn-api issue #558](https://github.com/cwendt94/espn-api/issues/558)). Will be replaced with Chrome extension bridge. |
| AI client | `ai/client.py` | Written. Wraps Anthropic SDK. Supports streaming + blocking. Single-turn only — each call is a fresh `messages=[{user: prompt}]`. |
| Context builder | `ai/context.py` | Written. Builds token-efficient prompts for draft, start/sit, waiver, trade. |
| Prompts | `ai/prompts.py` | Written. System prompt + task prompts for all features. Standard scoring focused. |
| CLI | `cli/draft.py`, `main.py`, etc. | Written. Full `typer` CLI with `draft start`, `draft board`, `draft analyze`, etc. Has auto-sync mode, mock mode, manual mode. |
| Cache | `cache/manager.py` | Written. SQLite-based with TTL decorator `@cache(ttl_seconds=300)`. |
| Config | `config/leagues.yaml`, `.env.example` | Written. League settings + env var template. |

**Known bugs:**
1. Claude has **no memory across picks** — each recommendation is a fresh single-turn call
2. No way to ask **free-form questions** during the draft ("is it too early for a TE?")
3. No validation that any connector returns real data
4. `.env` loading looks for `config/.env` but most people will put `.env` in the project root
5. `DraftState.to_dict()` doesn't serialize `all_drafted` — resume loses opponent pick history
6. `DraftState.is_my_pick()` is broken for even rounds in snake drafts — doesn't account for reversal
7. `DraftSyncService` polls `league.draft` which doesn't work during live drafts — needs full replacement

---

## Phase 1 — Validate Data Pipeline

**Goal:** Confirm each data source returns real, usable data. Fix what's broken. Build a validation script that can be re-run before each season.

### 1.1 Test Sleeper API (no auth needed)

**File:** `connectors/sleeper.py`

**Test:**
```python
sleeper = SleeperConnector()
players = sleeper.get_all_players()           # ~5MB, should return dict of ~7000+ players
injury = sleeper.get_injury_and_depth()       # filtered subset with injury/depth data
trending = sleeper.get_trending_adds(limit=10) # top 10 trending adds
```

**What to verify:**
- `get_all_players()` returns a dict with 7000+ entries
- Each player has `full_name`, `team`, `position`, `injury_status`, `depth_chart_order`
- `get_injury_and_depth()` correctly filters to relevant players
- `get_trending_adds()` returns enriched player names (not just IDs)
- Off-season: injury data will be mostly empty — that's expected. Verify structure is still correct.

**Potential issues:**
- The Sleeper endpoint might return an empty dict during the deep off-season
- `get_all_players()` is 5MB — first call is slow, subsequent calls hit SQLite cache

### 1.2 Test FantasyPros scraper

**File:** `connectors/fantasypros.py`

**Test:**
```python
fps = FantasyProsConnector()
adp = fps.get_adp(scoring="std")              # ADP for all positions
rb_rankings = fps.get_rankings("rb", "std")   # RB expert consensus rankings
projections = fps.get_projections("qb", 1, "std")  # QB week 1 projections
```

**What to verify:**
- `get_adp()` returns 200+ players with `name`, `team`, `position`, `adp` (float)
- Players are sorted by ADP ascending
- `get_rankings()` returns players with `overall_rank`, `positional_rank`, `projected_points`
- `get_projections()` returns weekly projected fantasy points

**Potential issues (high risk):**
- FantasyPros may have changed their page structure. The scraper looks for `var ecrData = {...}` in a `<script>` tag. If FP switched to client-side rendering (React/Next.js), this JS variable won't exist.
- The HTML fallback parser looks for `table.player-table tbody tr` and `a.player-name` — CSS selectors may have changed.
- ADP page parser looks for `var adpData = {...}` — same risk.
- FP may rate-limit or block scraping. Current headers only set `User-Agent`.
- **If FantasyPros scraping is broken:** We need an alternative data source. Options:
  - FantasyPros has a paid API ($$)
  - Use `nfl-data-py` library (already in dependencies) — has historical ADP data but not real-time ECR
  - Scrape a different site (FantasyCalc, Harris Football)
  - Use ESPN's own projections from the ESPN connector as a fallback

### 1.3 Test ESPN connector

**File:** `connectors/espn.py`

**Requires:** Real ESPN credentials in `.env` — `ESPN_LEAGUE_ID`, `ESPN_SWID`, `ESPN_S2`, `ESPN_TEAM_ID`

**Test:**
```python
espn = ESPNConnector(league_id=..., swid=..., espn_s2=..., team_id=1)
week = espn.get_current_week()
roster = espn.get_my_roster(week)
matchup = espn.get_matchup(week)
free_agents = espn.get_free_agents(week, limit=20)
```

**What to verify:**
- `get_current_week()` returns an int (1-18)
- `get_my_roster()` returns a `Roster` with real Player objects, each having `name`, `position`, `nfl_team`, `espn_id`, `projected_points`, `injury_status`
- `get_matchup()` returns your team name, opponent name, and projected scores
- `get_free_agents()` returns available players sorted by some ranking
- Off-season: ESPN may return the previous season's data — that's fine for validation

**Potential issues:**
- `espn-api` library may not support the 2025 season yet (check library version)
- ESPN cookies (`SWID`, `espn_s2`) expire — user will need to refresh them
- `team_id` is 1-indexed; if user enters wrong team_id they'll see someone else's roster

### 1.4 Test DataAggregator merge

**File:** `services/data_aggregator.py`

**Test:**
```python
aggregator = DataAggregator(espn=None, yahoo=None, sleeper=sleeper, fps=fps, scoring="std")
pool = aggregator.get_draft_player_pool(limit=50)
```

**What to verify:**
- Returns 50 `Player` objects sorted by ADP
- Each player has data from both sources: `adp` + `adp_source` from FP, `injury_status` + `depth_chart_order` from Sleeper
- Fuzzy matching works: e.g., "Ja'Marr Chase" (FP) matches "Ja'Marr Chase" (Sleeper)
- Players who don't match across sources still appear (just with partial data)

**Potential issues:**
- RapidFuzz `token_sort_ratio` at 85% threshold might be too aggressive or too loose
- Name mismatches across sources: "Mitchell Trubisky" vs "Mitch Trubisky", suffixes like "Jr.", "III"
- D/ST names differ wildly: "Los Angeles Rams" vs "Rams D/ST" vs "LAR"

### 1.5 Deliverable

**New file:** `scripts/validate_sources.py`
- Hits each source independently
- Prints sample output (first 10 players from each)
- Prints pass/fail for each source
- Shows timing for each call
- Can be re-run before each draft season

---

## Phase 2 — Chrome Extension: ESPN Draft Room Bridge

**Goal:** Get real-time pick data from ESPN's live draft room into our Python app. This replaces the broken `DraftSyncService` that polled `league.draft`.

### Why a Chrome extension?

ESPN's `league.draft` API endpoint only populates **after** a draft is complete — confirmed by the `espn-api` library maintainer ([issue #558](https://github.com/cwendt94/espn-api/issues/558)). ESPN uses separate, undocumented APIs for their live draft room.

Every commercial draft tool (FantasyPros, DraftKick, PickPulse) solves this the same way: a Chrome extension that reads the draft room's React state from the DOM. We do the same thing, but keep it local (no Chrome Web Store publishing needed).

### 2.1 Architecture

```
┌─────────────────────────────────────────────────────┐
│  Chrome Browser                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │  ESPN Draft Room tab (React app)              │  │
│  │                                               │  │
│  │  Content Script (MAIN world)                  │  │
│  │    ├─ Reads __reactInternalInstance$ from DOM  │  │
│  │    ├─ Extracts: picks[], teams[], players[]   │  │
│  │    └─ Fires custom event every 3 seconds      │  │
│  │                                               │  │
│  │  Content Script (ISOLATED world)              │  │
│  │    └─ Listens for event → chrome.runtime msg  │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  Background Script (service worker)                 │
│    └─ Receives pick data → POST to localhost:5050   │
└─────────────────────────────────────────────────────┘
           │
           │  HTTP POST (JSON)
           ▼
┌─────────────────────────────────────────────────────┐
│  Python App (localhost:5050)                         │
│                                                     │
│  DraftBridge (lightweight HTTP server)              │
│    ├─ POST /picks → receives all picks from ext     │
│    ├─ Compares to known state                       │
│    ├─ Fires callbacks for new opponent picks        │
│    └─ Signals main thread when it's your turn       │
│                                                     │
│  DraftService + DraftConversation (same as before)  │
│    └─ Claude recommends → user picks → loop         │
└─────────────────────────────────────────────────────┘
```

### 2.2 Chrome extension files

All files live in `extension/` at the project root. User loads it via `chrome://extensions` → Developer mode → Load unpacked.

**`extension/manifest.json`**
```json
{
  "manifest_version": 3,
  "name": "Fantasy Agent Draft Sync",
  "version": "1.0",
  "description": "Syncs ESPN draft picks to Fantasy Agent",
  "permissions": ["activeTab"],
  "content_scripts": [
    {
      "matches": ["*://fantasy.espn.com/football/draft*"],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ],
  "background": {
    "service_worker": "background.js"
  }
}
```

**`extension/content.js`** (runs in ESPN draft room page)
- Injects a script into the MAIN world (needed to access React internals)
- The injected script:
  - Finds the root React element on the page
  - Traverses `__reactInternalInstance$` or `__reactFiber$` to find draft state
  - Extracts: `picks` array (player name, team, round, pick number), `currentPick`, `myTeamId`
  - Dispatches a `CustomEvent` with this data every 3 seconds
- The ISOLATED content script listens for that event and forwards via `chrome.runtime.sendMessage()`

**`extension/background.js`** (service worker)
- Receives messages from content script
- POSTs JSON to `http://localhost:5050/picks`:
  ```json
  {
    "picks": [
      {"player_name": "Saquon Barkley", "player_id": "12345", "team_id": 3, "round": 1, "pick": 1},
      {"player_name": "CeeDee Lamb", "player_id": "23456", "team_id": 7, "round": 1, "pick": 2}
    ],
    "current_pick": 5,
    "my_team_id": 5,
    "in_progress": true
  }
  ```

### 2.3 Python-side: DraftBridge server

**New file:** `services/draft_bridge.py`

Replaces the broken `DraftSyncService`. Runs a lightweight HTTP server on `localhost:5050` in a background thread.

```python
class DraftBridge:
    """
    Receives live draft picks from the Chrome extension via HTTP POST.
    Runs on localhost:5050 in a daemon thread.
    """

    def __init__(
        self,
        state: DraftState,
        player_pool: list[Player],
        my_team_id: int,
        on_opponent_pick: Callable,   # (player, round, pick) → None
        on_your_turn: Callable,       # (round, overall_pick) → None
    ):
        self.state = state
        self.pool = player_pool
        self.my_team_id = my_team_id
        self.on_opponent_pick = on_opponent_pick
        self.on_your_turn = on_your_turn
        self._last_pick_count = 0
        self._server = None

    def start(self):
        """Start HTTP server on localhost:5050 in a daemon thread."""
        # Uses http.server or Flask — lightweight, no external deps
        # POST /picks handler:
        #   1. Parse incoming JSON
        #   2. Compare pick count to self._last_pick_count
        #   3. For each new pick:
        #      - Fuzzy match player name to pool
        #      - If team_id != my_team_id → on_opponent_pick()
        #      - If team_id == my_team_id → on_your_turn()
        #      - Update DraftState
        #   4. self._last_pick_count = len(picks)
        ...

    def stop(self):
        """Shutdown the HTTP server."""
        ...
```

**Key design decisions:**
- Uses `http.server` from stdlib (no Flask dependency needed)
- Only listens on `localhost` — no external access
- The extension POSTs the **full pick list** every 3 seconds — the bridge diffs against what it already knows
- Thread-safe: uses a lock when updating `DraftState`

### 2.4 How to discover ESPN's React state structure

We don't know the exact React property names yet. Need to reverse-engineer during a mock draft:

1. Open ESPN, start a mock draft
2. Open Chrome DevTools → Console
3. Run: `document.querySelector('[class*="draft"]').__reactFiber$` (or `__reactInternalInstance$`)
4. Traverse the fiber tree looking for `picks`, `currentPick`, `draftState`
5. Document the exact path to each piece of data we need

**Deliverable:** A `docs/espn_react_structure.md` file documenting the exact React state paths, updated each season if ESPN changes their draft room.

### 2.5 Fallback: manual input still works

If the Chrome extension breaks (ESPN changes their React structure), the draft loop falls back to manual:
```
draft> opp josh allen
draft> opp tyreek hill
draft> rec
```

The CLI should always support both modes. The extension just removes the tedious typing.

### 2.6 Files created/changed in Phase 2

| File | Action | Description |
|---|---|---|
| `extension/manifest.json` | **Create** | Chrome extension manifest, targets `fantasy.espn.com/football/draft*` |
| `extension/content.js` | **Create** | Content script: reads React state, dispatches events every 3s |
| `extension/background.js` | **Create** | Service worker: receives events, POSTs to localhost:5050 |
| `services/draft_bridge.py` | **Create** | HTTP server on localhost:5050, receives picks, updates DraftState |
| `services/draft_sync.py` | **Delete or gut** | Old ESPN polling approach is dead. Keep `MockDraftSimulator` only. |
| `cli/draft.py` | **Modify** | Replace `DraftSyncService` references with `DraftBridge`. Update `_run_live_draft_autosync()` to start bridge instead. |

---

## Phase 3 — Draft Assistant (Core Feature)

### 3a. Fix snake draft logic

**File:** `models/draft.py`

**Bug:** `is_my_pick()` checks `pick_in_round == pick_position` in every round. In a snake draft, if you're pick 5 in a 12-team league:
- Round 1 (ascending): you pick at slot 5 ✓
- Round 2 (descending): you pick at slot 8 (12 - 5 + 1 = 8) ✗ — current code still checks slot 5

**Fix:** `is_my_pick()` needs to account for snake reversal:
```python
def is_my_pick(self) -> bool:
    if self.current_round % 2 == 1:  # odd round, ascending
        return self.pick_in_round == self.pick_position
    else:  # even round, descending
        return self.pick_in_round == (self.total_teams - self.pick_position + 1)
```

**Also fix:** `to_dict()` doesn't serialize `all_drafted` — if the draft crashes and resumes, opponent pick history is lost. Add `all_drafted` to serialization.

### 3b. Multi-turn Claude conversation

**File:** `ai/client.py`

**Current:** Each `analyze()` call creates a fresh `messages=[{role: "user", content: prompt}]`. Claude has zero context from previous picks.

**Change:** Add a `DraftConversation` class that maintains message history:

```python
class DraftConversation:
    def __init__(self, client: FantasyAIClient):
        self.client = client
        self.messages: list[dict] = []

    def send(self, content: str, stream: bool = True) -> str:
        """Send a message and get a response. Both are appended to history."""
        self.messages.append({"role": "user", "content": content})

        if stream:
            response = self._stream()
        else:
            response = self._blocking()

        self.messages.append({"role": "assistant", "content": response})
        return response

    def inject_context(self, content: str):
        """Add a system-like context update without expecting a response.
        Used for: 'Opponent picked Josh Allen' — Claude should know but doesn't need to respond."""
        self.messages.append({"role": "user", "content": content})
        self.messages.append({"role": "assistant", "content": "Noted."})
```

**Why this matters for draft:**
- Round 1: Claude recommends Saquon Barkley. You pick him.
- Round 2: Claude already knows you have Saquon → recommends a WR to balance
- Round 5: Claude knows your full roster history → adjusts strategy for positional needs
- Free-form: "should I target Kelce here?" → Claude evaluates in context of YOUR roster

**Token management:** A 15-round draft with ~30 messages won't exceed context limits. But we should:
- Keep opponent pick updates terse ("Picks 6-11: Josh Allen, Tyreek Hill, Travis Kelce, CeeDee Lamb, Derrick Henry, Davante Adams")
- Batch opponent picks into single messages instead of one-per-pick
- Monitor total tokens and warn if approaching limits

### 3c. Free-form chat during draft

**File:** `cli/draft.py`

**Current:** The draft loop only handles fixed commands: `next`, `pick NAME`, `board`, `roster`, `q`.

**Change:** Any input that doesn't match a command gets sent to Claude as a free-form question:

```
draft> is it too early to grab a TE?
Claude: At pick 35 (Round 3), it's a bit early for TE in standard.
        The elite TEs go rounds 3-4, but you have bigger needs at RB...

draft> who are the best handcuffs still available?
Claude: Based on your roster (Saquon, Jefferson, ...):
        1. Alexander Mattison (handcuff to...)
        ...
```

**Implementation in draft loop:**
```python
if cmd in ("q", "quit", "exit"):
    break
elif cmd in ("next", "rec"):
    service.get_recommendation()
elif cmd.startswith("pick "):
    service.record_my_pick(cmd[5:].strip())
elif cmd.startswith("opp ") or cmd.startswith("draft "):
    service.record_opponent_pick(cmd.split(" ", 1)[1].strip())
elif cmd == "board" or cmd.startswith("board "):
    _show_board(...)
elif cmd == "roster":
    _show_my_roster(...)
else:
    # Free-form question → send to Claude with full draft context
    conversation.send(cmd, stream=True)
```

### 3d. Draft data flow (end-to-end)

Here's exactly what happens when a user starts a live draft:

```
User runs: fantasy draft start --pick 5 --teams 12

STARTUP (30-60 seconds, before draft begins):
1. CLI loads .env → builds SleeperConnector, FantasyProsConnector
2. DataAggregator.get_draft_player_pool(limit=300):
   a. FantasyProsConnector.get_adp("std") → HTTP scrape → 300 players with ADP
   b. SleeperConnector.get_injury_and_depth() → API call → injury/depth for all NFL players
   c. For each FP player → fuzzy match name to Sleeper data → overlay injury/depth/bye
   d. Return sorted list of 300 Player objects (cached in SQLite)
3. DraftConversation created → system prompt set with standard scoring rules
4. Claude briefed: "12-team standard scoring snake draft. You pick at position 5.
   Here are the top 30 available players by ADP: ..."
5. DraftBridge.start() → HTTP server on localhost:5050 listening for Chrome extension

DURING DRAFT (no scraping — all data is local + Claude API):
6. Chrome extension reads ESPN draft room React state every 3 seconds
7. Extension POSTs full pick list to localhost:5050
8. DraftBridge diffs against known state:
   - New opponent pick → update DraftState → inject_context() to Claude conversation
   - Your turn detected → signal main thread
9. User's turn:
   a. Build draft context: current roster, positional needs, top 30 available
   b. Send to Claude via DraftConversation.send() → streams recommendation
   c. User picks in ESPN draft room (extension picks up the pick automatically)
   d. OR user types "pick Saquon" in terminal as fallback
10. Repeat until draft complete

POST-DRAFT:
11. Final roster displayed
12. Draft state saved to ~/.fantasy_agent/draft_state.json
```

### 3e. Mock draft mode (no ESPN / no extension needed)

**Already mostly implemented** in `cli/draft.py::_run_mock_draft()` and `draft_sync.py::MockDraftSimulator`.

**What needs fixing:**
- `_run_mock_draft()` calls `_make_aggregator_only()` which still needs `ANTHROPIC_API_KEY` in `.env`
- Mock mode should integrate with the new `DraftConversation` (multi-turn)
- Opponent auto-picks use pure ADP order — add slight randomness (+/- 5 ADP positions) to feel more realistic
- No Chrome extension needed for mock — `MockDraftSimulator` handles opponent picks locally

### 3f. Files changed in Phase 3

| File | Change |
|---|---|
| `models/draft.py` | Fix `is_my_pick()` for even rounds. Add `all_drafted` to `to_dict()`. |
| `ai/client.py` | Add `DraftConversation` class with message history. |
| `cli/draft.py` | Wire up `DraftConversation`. Add free-form chat fallback in draft loop. Replace `DraftSyncService` with `DraftBridge`. |
| `services/draft_service.py` | Accept `DraftConversation` instead of raw `FantasyAIClient`. Update `get_recommendation()` to use conversation. |
| `ai/context.py` | Add `build_draft_briefing()` for the initial Claude briefing message. Add `build_opponent_picks_summary()` for batched updates. |

---

## Phase 4 — In-Season: Start/Sit

**Goal:** Weekly lineup advice with matchup context.

### 4a. Data needed

| Data | Source | Method |
|---|---|---|
| Your roster (with projections) | ESPN | `espn.get_my_roster(week)` |
| Your matchup (opponent + projected scores) | ESPN | `espn.get_matchup(week)` |
| Injury overlays | Sleeper | `sleeper.get_injury_and_depth()` |
| Weekly projections (per position) | FantasyPros | `fps.get_projections(pos, week, "std")` |
| Enriched roster | DataAggregator | `aggregator.enrich_players(roster.players)` |

### 4b. Flow

```
User runs: fantasy roster start-sit

1. ESPNConnector.get_current_week() → week number
2. ESPNConnector.get_my_roster(week) → Roster with Player objects
3. DataAggregator.enrich_players(roster.players) → overlay Sleeper injuries + FP projections
4. ESPNConnector.get_matchup(week) → opponent name, projected scores
5. ContextBuilder.build_start_sit_context() → identifies contested slots (more players than starting spots)
6. Format START_SIT_PROMPT with all context
7. Claude analyzes → streams recommendation

Output:
- Table showing each player, their matchup, projection, injury status
- Claude's recommended starting lineup
- Explanation for any close calls (FLEX decisions, injured starters)
```

### 4c. What exists vs. what's missing

**Exists:**
- `RosterService` — needs verification
- `ContextBuilder.build_start_sit_context()` — identifies contested slots
- `START_SIT_PROMPT` in `prompts.py` — complete prompt template
- `Roster.starters()` and `Roster.bench()` methods

**Missing:**
- `RosterService` may not wire everything together correctly
- No defensive matchup data (ESPN/FP don't easily provide "points allowed to position")
- No Vegas lines / game environment data — the prompt references "implied team total, over/under" but we don't have a source for this

### 4d. Files changed in Phase 4

| File | Change |
|---|---|
| `services/roster_service.py` | Wire up full flow: ESPN roster → enrich → context → Claude |
| `cli/roster.py` | Wire CLI command to RosterService |
| `connectors/fantasypros.py` | Validate `get_projections()` works for weekly data |

---

## Phase 5 — Waiver Wire

**Goal:** Identify top free agent pickups each week.

### 5a. Data flow

```
1. ESPNConnector.get_my_roster(week) → your roster
2. ESPNConnector.get_free_agents(week, limit=50) → available free agents
3. SleeperConnector.get_trending_adds(24h) → buzzing players
4. DataAggregator.enrich_players() on both lists
5. ContextBuilder.build_waiver_context() → roster weaknesses + available players + trending
6. WAIVER_WIRE_PROMPT → Claude → top 3 adds with drop candidates
```

### 5b. What exists vs. what's missing

**Exists:**
- `ContextBuilder.build_waiver_context()` — complete
- `WAIVER_WIRE_PROMPT` — complete
- `SleeperConnector.get_trending_adds()` — complete
- `ESPNConnector.get_free_agents()` — written but untested

**Missing:**
- `WaiverService` needs to wire everything together
- `cli/waiver.py` needs to be connected

---

## Phase 6 — Trade Analysis

**Goal:** Evaluate proposed trades.

### 6a. Data flow

```
1. User specifies: "giving: Derrick Henry, receiving: Ja'Marr Chase + David Montgomery"
2. Look up each player in your roster / league
3. ContextBuilder.build_trade_context() → simulates post-trade roster
4. TRADE_ANALYSIS_PROMPT → Claude → ACCEPT / REJECT / COUNTER
```

### 6b. What exists vs. what's missing

**Exists:**
- `ContextBuilder.build_trade_context()` — complete, simulates post-trade roster
- `TRADE_ANALYSIS_PROMPT` — complete

**Missing:**
- Rest-of-season schedule data — no source for this yet
- `TradeService` wiring
- Player lookup by name from roster (need fuzzy matching)

---

## Key Architecture Decisions

### Claude as conversation partner, not oracle
The draft uses multi-turn conversation so Claude builds context over time. In-season features (start/sit, waivers, trades) use single-turn — the context is self-contained in one prompt.

### Data loaded once, used fast
Scraping happens at session start. During a live draft, every second counts — no HTTP calls mid-pick. Everything cached in SQLite with TTL:
- Sleeper all players: 1 hour TTL (3600s)
- FantasyPros ADP: 24 hour TTL (86400s)
- FantasyPros rankings: 1 hour TTL (3600s)
- ESPN roster/matchup: 5 min TTL (300s)
- ESPN free agents: 15 min TTL (900s)

### Chrome extension for live draft sync
ESPN's `league.draft` API only works after drafts end. The Chrome extension reads React state from ESPN's draft room and POSTs picks to a local HTTP server. This is the same approach used by every commercial draft tool (FantasyPros, DraftKick, PickPulse). The extension is local/unpacked — no Chrome Web Store publishing needed.

### Manual input as universal fallback
Every mode that uses auto-sync also supports manual input (`opp josh allen`). If the Chrome extension breaks, the draft still works.

### `.env` location
Currently `cli/draft.py` loads from `config/.env` (4 directories up from the CLI file). This is fragile and non-standard. Should load from project root `.env` as a primary, `config/.env` as fallback.

### Error handling philosophy
Connectors currently swallow all exceptions and return empty lists. This is **wrong for validation** (Phase 1) but **correct for production** (draft shouldn't crash because Sleeper is down). Solution: add a `strict: bool` parameter that raises exceptions in validation mode.

---

## Build Order

1. **Phase 1** — Validate data pipeline (can start immediately, no ESPN needed for Sleeper/FP)
2. **Phase 2** — Chrome extension + DraftBridge (need to reverse-engineer ESPN React state during a mock draft)
3. **Phase 3a** — Fix snake draft bug
4. **Phase 3b** — Add DraftConversation (multi-turn Claude)
5. **Phase 3c** — Wire free-form chat into draft loop
6. **Phase 3e** — Test end-to-end with mock draft (no ESPN / no extension needed)
7. **Phase 3d** — Test full live flow with Chrome extension + ESPN mock draft
8. **Phase 4** — Start/Sit (after draft is solid)
9. **Phase 5** — Waiver wire
10. **Phase 6** — Trade analysis

---

## Open Questions

- **FantasyPros scraping:** Does `var ecrData = {...}` still exist in their HTML? If not, what's the alternative data source?
- **ESPN React state:** What's the exact path to draft picks in ESPN's React fiber tree? Needs hands-on reverse engineering during a mock draft.
- **ESPN `espn-api` library:** Does it support 2025 season? Last PyPI release date?
- **Off-season testing:** It's April 2026. Sleeper injury data will be sparse. FantasyPros may not have 2026 ADP yet. How do we validate in the off-season?
- **Mock draft realism:** Should opponents have positional needs (smarter AI) or just pick BPA by ADP?
- **Chrome extension Manifest V3:** Service workers have a 5-minute idle timeout. Does the 3-second polling keep it alive, or do we need a keep-alive mechanism?
