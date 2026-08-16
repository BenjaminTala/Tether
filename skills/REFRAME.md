# Third-Party Skill Review & Reframe

Three repos cloned and read (all MIT):

| Repo | Skills | Verdict |
|---|---|---|
| `tradermonty/claude-trading-skills` | 72 | Best architecture available. Mined heavily. |
| `staskh/trading_skills` | 28 | Real IBKR wiring. Mined for connection patterns. |
| `agiprolabs/claude-trading-skills` | 67 | Crypto/DeFi-first. Not applicable. Skipped. |

Nothing was copied. Three skills were written from what the review surfaced, and
`position-sizing` was amended. Ideas are not copyrightable; the text here is original, and
each adapted skill carries an attribution block naming its source.

## What was worth taking

**1. Artifact-passing between deterministic stages** (tradermonty)
Each stage writes a JSON decision artifact that the next stage consumes, with a decision enum
and a `data_quality` field. This is the right shape for the system — it makes each cycle
auditable after the fact and lets the engine refuse to proceed on stale or missing inputs.
→ became the pipeline contract in `execution-gate`.

**2. Fail-closed on partial state** (tradermonty, `drawdown-circuit-breaker`)
If a P&L ledger entry is missing or non-finite, that skill halts rather than skipping the
record. This is the single most valuable idea in the whole review. Most hobby trading code
treats unreadable state as absent state, which is how a system with correct loss limits ends
up trading through one.
→ `circuit-breaker`, and a fail-closed clause added to `position-sizing`.

**3. Explicit release conditions on every halt** (tradermonty)
Not just "halted" but "halted until next Monday ET". Prevents both indefinite paralysis and
an agent deciding for itself that enough time has passed.
→ `circuit-breaker` output schema.

**4. Cooldown after losses** (tradermonty)
A losing-streak window during which no new entries are allowed. Written for revenge trading —
a human failure mode — but it maps to a real machine one: the model reasoning its way into
larger bets after drawdown because the losses "prove" the setup is now cheaper.
→ `circuit-breaker`.

**5. Four-value decision enum** (tradermonty)
`GO / NO_GO / REVIEW_REQUIRED / NO_ACTIONABLE_ORDERS`. The fourth value matters: most cycles
should legitimately produce no orders, and conflating that with failure trains you to ignore
alerts.
→ `execution-gate`.

**6. Dry-run by default, `--execute` required** (staskh)
Every order path is inert unless explicitly armed.
→ `broker-safety`.

**7. Orphan order cleanup before placement** (staskh)
Cancel stale working orders for a ticker before submitting new ones. Two live stops on one
position is a bug that only shows up when it fires.
→ `broker-safety`.

**8. `--as-of` for deterministic replay** (tradermonty)
Lets the same logic be tested and backfilled against fixed timestamps.
→ `circuit-breaker`, with the constraint that the scheduler must never set it.

## What was deliberately reversed

**The human-in-the-loop framing.** Both repos are explicit that they are advisory —
tradermonty's README states the goal is not to outsource buy/sell decisions to AI, and the
discipline gate describes itself as a pre-broker checklist, not an order router; its circuit
breaker calls itself a recommendation that does not enforce broker-side blocks. That is a
reasonable stance for their users and the wrong one here. In an unattended loop, a limit that
only advises is a limit that gets ignored on the cycle it matters. Every adapted rule is
binding, enforced in tested Python, and outside the model's reach.

**Silent failure by default.** The discipline gate exits 0 on `NO_GO` unless you pass
`--fail-on-non-go`. Inverted: non-`GO` exits non-zero always, no flag to suppress it.

**Automatic IBKR port fallback.** The staskh skills retry the other port on connection failure
and remember which one worked, across sessions. For an interactive advisor this is a
convenience. For a scheduled agent it is a silent paper-to-live failover. Rejected outright
and replaced with: explicit mode, account-ID assertion (`DU` prefix for paper), hard failure
on mismatch, and a hand-set environment variable required to arm live trading.

**Kelly criterion sizing.** Offered as a mode in tradermonty's `position-sizer`, driven by the
user's own win rate and average win/loss. Removed. With a few dozen trades those inputs are
noise, and the failure mode is a well-reasoned recommendation to increase size after a lucky
run. Fixed fractional with volatility scaling only.

**"Look up the price and suggest entry/stop from technical analysis."** Their sizing skill
does this when the user supplies only a ticker. In an automated path that is a hallucination
surface: the model invents plausible levels and the engine sizes real money against them.
Replaced with a hard rule — no fetched price, no size.

**Threshold values.** Their circuit breaker defaults (2% daily, 5% weekly, 8% monthly) assume
an account with enough positions for those numbers to be statistically meaningful. At $1000
with 3–6 positions, a 2% daily rule fires on ordinary noise and the system lives halted.
Widened the percentages; kept the consecutive-loss counts tight, since streak rules survive
small samples better than percentage rules do.

## What was left on the table

The 72-skill catalogue includes screeners (VCP, CANSLIM, PEAD), pattern trainers, options
advisors, pair trading, short-side planners and "investor persona" synthesizers. All out of
mandate: long-only, whitelisted ETFs and large caps, weekly cadence, $1000. Most also require
paid FMP or FINVIZ keys, which the brief excludes. Their `backtest-expert` is well built and
still not usable here for the reason in `failure-modes` — a model cannot honestly backtest a
period inside its own training data.

## Supply-chain note

These skills are instructions that a model reads before deciding what to do with money. Do not
install them from a live repo, and do not let anything auto-update in the decision path. Read
the source, take the idea, write your own file, pin it in your own git history. That is what
was done here.
