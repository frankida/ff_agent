SYSTEM_PROMPT = """You are an expert fantasy football analyst specializing in STANDARD scoring (no PPR).

STANDARD SCORING RULES:
- Passing TD: 4 pts | Rush/Rec TD: 6 pts
- Passing yards: 1 pt per 25 yds | Rush/Rec yards: 1 pt per 10 yds
- INT: -2 pts | Fumble lost: -2 pts
- NO reception points (this is NOT PPR)

CRITICAL IMPLICATIONS FOR STANDARD SCORING:
- Workhorse RBs with high carry volume >> committee backs >> pass-catching specialists
- TDs matter far more than receptions (a WR with 6 catches for 60 yds and 0 TDs scores ~6 pts; same player with 1 catch for 10 yds and 1 TD scores 8 pts)
- Red zone usage (rush attempts + end zone targets) is the single most important metric
- Do NOT over-value high-catch-count TEs and slot WRs — their PPR premium doesn't apply here
- Target share matters less than TD opportunity and end zone usage
- RB scarcity is real and hits harder in standard; elite RBs are the foundation of winning rosters

Always be direct. Give a clear recommendation first, then concise reasoning.
Flag injury risks explicitly with practice status when available.
Note when data is uncertain (e.g., no projection available, new team, uncertain role).
Keep responses scannable — use short sections, not walls of text."""


DRAFT_PICK_PROMPT = """LIVE DRAFT — STANDARD SCORING

Round {round_num}, Pick {pick_num} (Overall #{overall_pick})
Positional needs: {needs}

YOUR ROSTER SO FAR:
{my_roster}

TOP AVAILABLE (FantasyPros ECR, standard scoring):
{top_available}

Recommend the single best pick right now. Consider:
1. Positional scarcity — in standard scoring, elite RBs are the hardest to replace; don't leave pick 1-4 rounds without one
2. ADP value — is anyone falling past their value?
3. Standard scoring fit (workhorse RBs > committee backs; TD-upside WRs/TEs > reception merchants)
4. Roster construction — don't stack the same position twice early unless the value gap is massive
5. Injury flags

FORMAT — exactly these 3 lines, nothing else. Keep WHY under 15 words:
▶ PICK:  [Name] · [POS] · [Team]
   WHY:  [max 15 words — value gap or positional reason]
   ALT:  [Name] · [POS] · [Team]  ← opposite position to main pick (RB↔WR)"""


START_SIT_PROMPT = """WEEK {week} START/SIT — STANDARD SCORING

YOUR ROSTER:
{roster_summary}

THIS WEEK'S MATCHUP: {my_team} vs {opponent}
My projected: {my_projected:.1f} | Opponent projected: {opp_projected:.1f}

LINEUP DECISIONS NEEDED:
{decisions_needed}

Weigh these factors (standard scoring priority order):
1. Projected points and recent form (last 3 games)
2. Opponent defensive rank vs. position (pts allowed)
3. Red zone opportunity (carries inside 20, end zone targets)
4. Injury/practice status — DNP = sit, LP = risky
5. Game environment (implied team total, over/under, Vegas line)
6. Bye weeks

Give the optimal starting lineup. Flag any genuine coin-flip decisions."""


WAIVER_WIRE_PROMPT = """WEEK {week} WAIVER WIRE — STANDARD SCORING

YOUR ROSTER WEAKNESSES:
{roster_weaknesses}

Waiver priority: #{waiver_priority}

TOP AVAILABLE FREE AGENTS (standard scoring value):
{available_players}

SLEEPER TRENDING ADDS (last 24h buzz):
{trending_adds}

For each recommendation:
1. Why this player has value in STANDARD (not just PPR buzz)
2. Specific drop candidate from your roster
3. Role outlook — starter, handcuff, or stash?

Limit to top 3 adds. Be direct about drop candidates."""


TRADE_ANALYSIS_PROMPT = """TRADE ANALYSIS — STANDARD SCORING

YOU GIVE UP:
{giving}

YOU RECEIVE:
{receiving}

Current week: {week} | Playoff weeks: {playoff_weeks}

YOUR ROSTER AFTER TRADE:
{post_trade_roster}

Analyze for STANDARD scoring:
- Immediate starter value impact
- ROS schedule strength for key players involved
- Positional balance impact
- Any injury/role risk on either side
- Buy or sell signal for each player involved

VERDICT: ACCEPT / REJECT / COUNTER
If COUNTER: suggest a specific modification."""


PLAYER_ANALYSIS_PROMPT = """PLAYER ANALYSIS — STANDARD SCORING

Player: {name} ({position}, {nfl_team})
Week: {week}

Player data:
{player_summary}

Remaining schedule: {schedule}

Provide:
1. Current role and standard scoring value
2. Upside (best-case outcome) and floor (worst-case)
3. Buy/sell/hold as a trade asset
4. Start/sit recommendation for this week
5. One-sentence verdict"""


MATCHUP_PREVIEW_PROMPT = """WEEK {week} MATCHUP PREVIEW — STANDARD SCORING

{my_team} (projected: {my_projected:.1f}) vs {opponent} (projected: {opp_projected:.1f})

MY STARTERS:
{my_starters}

OPPONENT STARTERS:
{opp_starters}

Analyze:
1. Win probability and key matchups
2. My players with favorable/unfavorable defensive matchups
3. Injury risks that could swing the outcome
4. What needs to go right for me to win

Keep it concise — actionable intel, not a recap."""
