# Fantasy Agent

An AI-powered fantasy football assistant built on Claude. Gives you real-time draft recommendations, start/sit analysis, and waiver wire advice — all from your terminal.

## What it does

- **Draft assistant** — Live pick recommendations during your draft. Knows your roster, positional needs, ADP value, and injury flags in real time.
- **Start/Sit** — Weekly lineup decisions with matchup context and standard scoring priority.
- **Waiver Wire** — Spots trending adds before the buzz hits mainstream. Explains why a player has value in standard (not just PPR noise).
- **Trade analysis** — Accept / Reject / Counter with concrete reasoning.

<img width="1307" height="553" alt="image" src="https://github.com/user-attachments/assets/46f35422-bf13-49be-b1cc-e053aaa37a5d" />

## Scoring

Optimized for **Standard Scoring** (no PPR). Workhorse RBs, red zone usage, and TD upside are weighted accordingly.

## Setup

### 1. Install

```bash
pip install -e .
```

### 2. Configure

Copy the example env file and fill in your credentials:

```bash
cp config/.env.example .env
```

Required:
```
ANTHROPIC_API_KEY=sk-ant-...

# ESPN
ESPN_LEAGUE_ID=123456
ESPN_SWID={your-swid}
ESPN_S2=your-espn-s2-cookie
ESPN_TEAM_ID=1
```

To get your ESPN cookies: log into ESPN Fantasy, open browser dev tools → Application → Cookies → copy `SWID` and `espn_s2`.

### 3. Run

```bash
fantasy --help
```

## Usage

### Draft

```bash
# Start a new draft session (pick 5 in a 12-team league)
fantasy draft start --pick 5 --teams 12

# Inside the draft loop:
# rec              → get Claude's recommendation
# pick "CMC"       → record your pick
# opp "Josh Allen" → record an opponent pick
# board --pos RB   → see available RBs
# status           → see your roster so far
```

### In-Season

```bash
fantasy roster start-sit     # weekly lineup advice
fantasy waiver scan          # top waiver adds
fantasy trade evaluate       # paste a trade offer
```

## Data Sources

| Source | What it provides | Method |
|---|---|---|
| FantasyPros | ADP, expert consensus rankings, projections | HTTP scrape |
| Sleeper | Injury status, depth charts, trending adds | Free public API |
| ESPN | Your league roster, matchups, scores | Python SDK |

## Architecture

```
CLI (typer)
  └── Services (DraftService, RosterService, WaiverService, TradeService)
        ├── DataAggregator  ← merges all sources with fuzzy name matching
        │     ├── FantasyProsConnector  (rankings, ADP)
        │     ├── SleeperConnector      (injuries, depth)
        │     └── ESPNConnector         (your league)
        └── AI Layer
              ├── FantasyAIClient  (Claude API, streaming)
              └── ContextBuilder   (token-efficient prompts)
```

## Requirements

- Python 3.9+
- Anthropic API key
- ESPN league credentials
