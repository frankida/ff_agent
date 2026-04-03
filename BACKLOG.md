# Fantasy Agent — Task Backlog

## How to use this file

Each task is a self-contained unit of work. An agent (or human) picks a task, creates the specified branch from `dev/draft-assistant`, does the work, and opens a PR back to `dev/draft-assistant`.

**Rules:**
- Check the "Blocked by" field before starting — don't start blocked tasks
- Mark status as `IN PROGRESS` when you start (edit this file)
- Mark status as `DONE` when PR is merged
- Each task specifies its branch name, files to create/modify, and acceptance criteria

---

## Dependency Graph

```
Independent (start anytime):
  #1 Validate Sleeper ──────────────┐
  #2 Validate FantasyPros ──────────┤
  #3 Fix snake draft logic          ├──→ #9 Validate all sources ──┐
  #4 Build DraftConversation        │                               │
  #5 Fix .env loading ──────────────│───────────────────────────────┤
  #6 Chrome extension skeleton      │                               │
  #7 Build DraftBridge ─────────────┤                               │
                                    │                               │
  #3 + #4 + #7 ────────────────────→ #8 Wire draft loop ──────────→ #10 E2E mock draft
```

---

## Task 1 — Validate Sleeper API connector

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/validate-sleeper` |
| Blocked by | None |
| Files | `connectors/sleeper.py`, new `scripts/validate_sleeper.py` |

**Description:**
Test the Sleeper connector against the live API (no auth needed):
1. `SleeperConnector().get_all_players()` — should return dict with 7000+ entries
2. `SleeperConnector().get_injury_and_depth()` — filtered subset with injury/depth data
3. `SleeperConnector().get_trending_adds(limit=10)` — enriched player names, not just IDs

Create `scripts/validate_sleeper.py` that:
- Hits each method, prints sample output (first 5 players)
- Prints pass/fail with counts and timing
- Handles off-season gracefully (injury data may be sparse)

Fix any issues found in the connector. Note: first call to `get_all_players()` is ~5MB, verify the SQLite cache works on subsequent calls.

**Acceptance criteria:** Script runs clean, prints real NFL player data, all 3 methods return valid results.

---

## Task 2 — Validate FantasyPros scraper

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/validate-fantasypros` |
| Blocked by | None |
| Files | `connectors/fantasypros.py`, new `scripts/validate_fantasypros.py` |

**Description:**
Test the FantasyPros scraper — HIGH RISK, FP changes their HTML often:
1. `FantasyProsConnector().get_adp(scoring="std")` — 200+ players with name, team, position, adp
2. `FantasyProsConnector().get_rankings("rb", "std")` — ECR with ranks and projected points
3. `FantasyProsConnector().get_projections("qb", 1, "std")` — weekly projected fantasy points

Create `scripts/validate_fantasypros.py` with same format as Sleeper script.

The scraper looks for `var ecrData = {...}` and `var adpData = {...}` in script tags. If FP changed to client-side rendering, these won't exist and the scraper needs to be rewritten.

If scraping is broken: investigate the current FP page structure, fix the parser, or document alternative data sources (nfl-data-py, FantasyCalc, ESPN projections).

**Acceptance criteria:** Script runs, returns real player ADP/ranking data. If broken, document why and propose a fix.

---

## Task 3 — Fix snake draft logic and state serialization

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/fix-draft-state` |
| Blocked by | None |
| Files | `models/draft.py`, `services/draft_service.py`, `tests/test_models.py` |

**Description:**
Two bugs to fix:

**Bug 1: `is_my_pick()` broken for even rounds.** In a snake draft, pick 5 in a 12-team league: Round 2 (descending) should be slot 8 (12-5+1=8), but code always checks slot 5.

Fix:
```python
def is_my_pick(self) -> bool:
    if self.current_round % 2 == 1:
        return self.pick_in_round == self.pick_position
    else:
        return self.pick_in_round == (self.total_teams - self.pick_position + 1)
```

**Bug 2: `to_dict()` doesn't serialize `all_drafted`.** Resume loses opponent pick history. Add `all_drafted` to `to_dict()` and update `DraftService.resume()` to restore it.

Add/update tests: `is_my_pick()` for rounds 1-4, `advance()` through full snake sequence, `to_dict()` roundtrip.

**Acceptance criteria:** Both bugs fixed, tests pass, snake draft logic verified for all rounds.

---

## Task 4 — Build DraftConversation multi-turn Claude class

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/draft-conversation` |
| Blocked by | None |
| Files | `ai/client.py`, `ai/context.py`, new `tests/test_draft_conversation.py` |

**Description:**
Add `DraftConversation` class to `ai/client.py` that maintains `messages: list[dict]` across the entire draft.

Methods:
- `send(content, stream=True)` — append user msg, call Claude with full history, append response
- `inject_context(content)` — silent update ("Opponent picked X") — adds user msg + "Noted." without a real API call
- `get_token_estimate()` — rough token count, warn if approaching limits

Add to `ai/context.py`:
- `build_draft_briefing(total_teams, pick_position, scoring, top_available)` — initial Claude briefing
- `build_opponent_picks_summary(picks: list[Player])` — terse batched update

Tests: mock Anthropic client, verify messages accumulate, inject_context works, token estimate grows.

**Acceptance criteria:** DraftConversation maintains history, supports streaming, handles opponent pick injection efficiently.

---

## Task 5 — Fix .env loading path

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/fix-env-loading` |
| Blocked by | None |
| Files | `cli/draft.py`, `cli/roster.py`, `cli/waiver.py`, `cli/trade.py`, `cli/config.py` |

**Description:**
`_make_services()` loads env from `Path(__file__).parents[4] / "config"` which is fragile.

Fix: Create shared utility that loads `.env` with priority:
1. Project root `.env` (next to `pyproject.toml`)
2. `config/.env` as fallback
3. Shell env vars (highest priority, never overwritten)

Find project root by walking up from `__file__` looking for `pyproject.toml`. Use `load_dotenv(override=False)`. Replace hardcoded paths in all CLI files.

**Acceptance criteria:** CLI commands load `.env` from project root. Works regardless of cwd.

---

## Task 6 — Build Chrome extension skeleton for ESPN draft sync

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/chrome-extension` |
| Blocked by | None |
| Files | New `extension/` directory: `manifest.json`, `content.js`, `background.js`, `injected.js` |

**Description:**
Build the Chrome extension that reads ESPN's draft room React state and forwards picks to localhost:5050.

- `manifest.json` — Manifest V3, matches `*://fantasy.espn.com/football/draft*`, minimal permissions
- `injected.js` — Runs in MAIN world, polls every 3s, reads `__reactFiber$` / `__reactInternalInstance$`, dispatches CustomEvent with pick data
- `content.js` — ISOLATED world, injects `injected.js`, listens for events, forwards via `chrome.runtime.sendMessage()`
- `background.js` — Service worker, receives messages, POSTs to `http://localhost:5050/picks`

**IMPORTANT:** The exact React state paths are UNKNOWN. Build scaffolding with placeholder traversal logic and clear TODO comments. Create `docs/espn_react_reverse_engineering.md` with Chrome DevTools instructions for discovering the paths during a mock draft.

Handle Manifest V3 service worker idle timeout (5 min) — the 3s polling should keep it alive but add a keep-alive mechanism if needed.

**Acceptance criteria:** Extension loads in Chrome without errors, attempts to read React state, POSTs to localhost. Data extraction paths documented as TODOs.

---

## Task 7 — Build DraftBridge HTTP server

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/draft-bridge` |
| Blocked by | None |
| Files | New `services/draft_bridge.py`, modify `services/draft_sync.py` |

**Description:**
Python-side HTTP server that receives picks from Chrome extension.

`DraftBridge` class:
- `start()` — launches `http.server` on `127.0.0.1:5050` in daemon thread
- `stop()` — shuts down server
- `POST /picks` — accepts JSON `{"picks": [...], "current_pick": int, "my_team_id": int}`, diffs against known state, fires callbacks for new picks, updates DraftState (thread-safe with lock)
- `GET /status` — returns current draft state for debugging

Uses stdlib `http.server` — no Flask dependency. Fuzzy matches player names to pool.

Modify `services/draft_sync.py`: delete `DraftSyncService` (confirmed broken), keep `MockDraftSimulator`.

Tests: mock HTTP requests, verify state updates, test incremental pick processing, verify thread safety.

**Acceptance criteria:** DraftBridge starts/stops cleanly, processes picks, fires correct callbacks, thread-safe.

---

## Task 8 — Wire draft CLI loop with DraftConversation + DraftBridge

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/wire-draft-loop` |
| Blocked by | #3, #4, #7 |
| Files | `cli/draft.py`, `services/draft_service.py` |

**Description:**
Integration task — wire everything together.

Changes to `cli/draft.py`:
1. Replace `DraftSyncService` with `DraftBridge` in `_run_live_draft_autosync()`
2. Wire `DraftConversation` instead of raw `FantasyAIClient`
3. Send initial briefing to Claude at draft start
4. Batch opponent picks from bridge into `conversation.inject_context()`
5. Free-form chat: any unrecognized input → `conversation.send()` → stream response

Changes to `services/draft_service.py`:
1. Accept `DraftConversation` instead of `FantasyAIClient`
2. `get_recommendation()` uses `conversation.send()`

Draft loop commands: `next/rec`, `pick NAME`, `opp NAME`, `board [POS]`, `roster`, `help`, `q` — anything else is free-form chat.

**Acceptance criteria:** Full draft loop works in mock mode with multi-turn conversation. Free-form questions work. Live mode starts DraftBridge on :5050.

---

## Task 9 — Build validation script that tests all data sources together

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/validate-all-sources` |
| Blocked by | #1, #2 |
| Files | New `scripts/validate_sources.py` |

**Description:**
Single script that validates the entire data pipeline:
1. Sleeper API → pass/fail
2. FantasyPros scraper → pass/fail
3. DataAggregator merge → verify players have data from both sources, check fuzzy match quality
4. ESPN connector (optional, if credentials in `.env`)
5. Print summary with source status, player counts, merge quality %

**Acceptance criteria:** Runs from project root with `python scripts/validate_sources.py`. Clear pass/fail output.

---

## Task 10 — End-to-end mock draft test

| Field | Value |
|---|---|
| Status | `PENDING` |
| Branch | `task/e2e-mock-draft` |
| Blocked by | #5, #8, #9 |
| Files | Various — integration test, no major new code |

**Description:**
Run a full 15-round mock draft end-to-end:
1. `pip install -e .`
2. Set `ANTHROPIC_API_KEY` in `.env`
3. `fantasy draft start --mock --pick 5 --teams 12`
4. Verify: player pool loads, Claude briefed, opponents auto-pick, multi-turn conversation works, free-form questions work, snake order correct, state saves

Document any bugs found. Fix minor issues. Create new tasks for major issues.

**Acceptance criteria:** Full 15-round mock draft completes. Claude gives contextual recommendations accounting for full roster history.
