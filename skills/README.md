# Trading Agent Knowledge Pack

Eight skills in `skills/`, each distilled into operational rules the agent can actually
execute. Drop the folders into `~/.claude/skills/` (or `.claude/skills/` in the project) for
Claude Code, or zip a folder and upload it under Settings → Skills in the web app.

Skills encode *judgement*. They never encode limits — every hard limit lives in `mandate.yaml`
and is enforced by deterministic Python. A skill the model can read is a skill the model can
talk itself out of.

## The skills

| Skill | Answers | Runs |
|---|---|---|
| `market-regime` | How much risk is allowed right now? | Start of every weekly cycle |
| `trend-selection` | Which instruments qualify? | Weekly, after regime |
| `position-sizing` | How many shares, and is there room? | Every proposed entry |
| `trade-management` | Stop, trail, partial, time stop, invalidation | Every daily check |
| `news-analysis` | Does this headline change anything? | On every triaged Hard item |
| `costs-and-frictions` | Does this trade survive its own costs? | Every proposed entry |
| `decision-journal` | What did I decide, and was the process good? | Every decision + monthly |
| `failure-modes` | Should I submit this at all? | Final gate, every cycle |
| `circuit-breaker` | Am I allowed to trade at all today? | Before every cycle (code) |
| `execution-gate` | Does this specific order pass? | Before every order (code) |
| `broker-safety` | Is the IBKR connection safe to use? | Every connection, every order |

The last three are **reframed from third-party skills** — see `REFRAME.md` for what was taken,
changed and rejected. They describe rules that live in tested Python, not in the model's
judgement; the SKILL.md exists so the model understands the constraints it is operating under
and stops proposing things that will be refused.

Order of operations in a cycle:
`circuit-breaker → market-regime → trend-selection → costs-and-frictions → position-sizing →
failure-modes → execution-gate → broker-safety → orders`
Daily: `circuit-breaker → trade-management → news-analysis → failure-modes → execution-gate`.

Model-side skills are in the middle. Code-side gates bracket them on both ends.

## Reading list, mapped

**Read first — these three carry most of the weight**
- Robert Carver, *Systematic Trading* — the closest thing to a blueprint for what you're
  building: rule-based systems, volatility targeting, position buffering, cost realism, and a
  sober treatment of how much discretion to allow. → `trend-selection`, `position-sizing`, `costs-and-frictions`
- Van K. Tharp, *Trade Your Way to Financial Freedom* — position sizing, R-multiples,
  expectancy, and why the exit strategy dominates the entry. → `position-sizing`, `decision-journal`
- Marcos López de Prado, *Advances in Financial Machine Learning* — backtest overfitting,
  multiple-testing, deflated Sharpe. The antidote to trusting your own results. → `failure-modes`

**Strategy foundations**
- Gary Antonacci, *Dual Momentum Investing* — absolute + relative momentum, simply. → `market-regime`, `trend-selection`
- Wesley Gray & Jack Vogel, *Quantitative Momentum* — how a momentum selection system is
  actually constructed and stress-tested. → `trend-selection`
- Andreas Clenow, *Stocks on the Move* — momentum on equities with ATR-based sizing. → `trend-selection`, `position-sizing`
- Perry Kaufman, *Trading Systems and Methods* — the reference encyclopedia; use it to look
  things up, not to read cover to cover.
- Ernie Chan, *Algorithmic Trading* — strategy rationale plus honest transaction-cost modelling. → `costs-and-frictions`
- Kevin Davey, *Building Winning Algorithmic Trading Systems* — the development process:
  out-of-sample, walk-forward, incubation before real money. → `decision-journal`, `failure-modes`

**Risk, exits, discipline**
- Curtis Faith, *Way of the Turtle* — N/ATR volatility units, mechanical exits, and the
  demonstration that rules beat talent. → `trade-management`, `position-sizing`
- Alexander Elder, *The New Trading for a Living* — per-trade and per-month loss constraints. → `trade-management`
- Ralph Vince, *The Mathematics of Money Management* — the maths behind fractional sizing, and
  why full Kelly is a trap. → `position-sizing`

**Judgement and market reading**
- Mark Minervini, *Trade Like a Stock Market Wizard* — buying strength, stop discipline,
  selling into strength. → `trade-management`, `news-analysis`
- William O'Neil, *How to Make Money in Stocks* — distribution days, follow-through days,
  relative strength. → `market-regime`
- Jack Schwager, *Market Wizards* — the interviews converge on risk control and journaling
  more than on any method. → `decision-journal`
- Edwin Lefèvre, *Reminiscences of a Stock Operator* — price reaction vs news, and every way
  discipline fails. → `news-analysis`

**Bias and epistemics**
- Daniel Kahneman, *Thinking, Fast and Slow* → `failure-modes`
- Nassim Taleb, *Fooled by Randomness* → `failure-modes`
- Annie Duke, *Thinking in Bets* — resulting, decision quality vs outcome quality. → `decision-journal`

**The counterweight — read at least one**
- John Bogle, *Common Sense on Mutual Funds*, or Burton Malkiel, *A Random Walk Down Wall
  Street*. The strongest case that the whole active project is a cost-drag on a buy-and-hold
  baseline. Your benchmark comes from here; if the agent can't beat it net of costs after a
  year, the honest answer is to stop.

**Papers worth having in `references/` verbatim (open access)**
- Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum" — the 12-month lookback evidence.
- Jegadeesh & Titman (1993) — cross-sectional momentum.
- Faber (2007), "A Quantitative Approach to Tactical Asset Allocation" — the 200-day filter.
- Barber & Odean (2000), "Trading Is Hazardous to Your Wealth" — turnover destroys retail returns.
- Harvey, Liu & Zhu (2016) — multiple testing in published factors.

## Existing skills worth mining (do not wire to the order path)

Your Claude skills catalog has no trading skills. Available plugins: **Bigdata.com** and
**LSEG** (financial data/analytics via MCP) — both are data sources, not strategy, and both
likely need paid entitlements.

On GitHub:
- **tradermonty/claude-trading-skills** (MIT, ~1.6k stars) — the most relevant: equity-focused
  skills for market breadth, VCP/CANSLIM screening, position sizing, trade journaling,
  postmortems, plus workflow manifests and a `launchd` scheduling pattern. Explicitly built
  for human-in-the-loop, not automated execution, and many skills require paid FMP/FINVIZ.
  Read `position-sizer`, `trader-memory-core`, `signal-postmortem`, `exposure-coach`,
  `backtest-expert` as design references.
- **staskh/trading_skills** — Claude + IBKR advisor system; useful as a reference for how
  someone else structured the IBKR integration.
- **agiprolabs/claude-trading-skills** — crypto/DeFi-first; the risk-management and
  slippage-modeling skills generalise, the rest doesn't.
- **himself65/finance-skills**, **OctagonAI/skills** — research/analysis skills tied to
  specific MCP data providers.

Treat third-party skills as untrusted code and untrusted instructions in a system that touches
money. Read them, take the ideas, write your own file. Never let an auto-updating external
skill sit in the decision path.

## What deliberately isn't here

No chart-pattern catalog, no indicator zoo, no Elliott Wave, no Wyckoff, no options
strategies, no "trading legends as personas". At $1000 with a weekly cycle, more indicators
means more ways to overfit, and persona skills produce confident-sounding text with no
falsifiable content. Add complexity only when the journal shows a specific gap that the
complexity fills.
