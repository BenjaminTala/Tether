# Live-session learnings

## 2026-08-18 — day 2: the scheduling-vs-market-hours bug family, and forcing the skills

- **Every decision maker must run while the market can act on it.** Third instance of the
  same bug class: weekly (08:00) and daily (08:45) runs decided BEFORE the open, so their
  entry orders always died on the outside-RTH gate — today's daily proposed LLY+MRK and
  filled 0/0. (Instances 1-2: core rebalance at 16:20, after the close.) All decision runs
  now execute inside RTH (weekly MON 09:45, daily 09:50, rebalance 10:00-15:30). Rule for
  the future: any component that produces orders must be scheduled inside the window where
  orders can fill; "decide at dawn, trade at open" needs an order queue we don't have.
- **Core deployed correctly under the fixed scheduler**: VTI 7 @ 379.98 + SGOV 19 @ 100.58
  (~$4,600), completion verified by fills, monthly slot consumed properly.
- **Skill application is now forced, three layers** (owner request): (1) anti-chasing from
  the original brief finally CODE-enforced (reject entries >1.5 ATR above 20d MA);
  (2) schema demands `skills_applied` naming the skill files worked through and a per-
  position `entry_checklist` of Literal[True] attestations — a position the model cannot
  attest cannot be submitted, and the engine re-verifies the objective claims by arithmetic;
  (3) runs refuse to start if skills/ is missing on disk. Honest residual: no code can force
  *depth* of reading — the caps and checks bound the damage of shallow compliance.
- **The model's own journal loop is working**: today's daily cited yesterday's unfilled LLY
  order, diagnosed the tight limit on a wide-ATR name, and re-attempted deliberately — the
  decision-journal skill behaving as designed.
- **News stream densified** (owner request): poll every 5 min, 9 feeds (added MarketWatch
  real-time, CNBC earnings+tech, Yahoo Finance), event cooldown 60 min, cap 3/day. X/Twitter
  has no free API — viral catalysts reach the wires within minutes, which at 15-min delayed
  data is the same trade. GameStop-style plays are bounded by the whitelist by DESIGN
  (prompt-injection safety): a true off-list meme squeeze is not tradable; big-name
  catalysts are. Expanding the whitelist is a human mandate edit, not an agent decision.

## 2026-08-17 — day 1 wrap-up (after the close)

- **Day 1 result: −$14.85 (−0.15%) on $10,000.** Two positions opened (SMH, BAC), both held
  into the close with trailing stops at the broker; the loss is commissions (~$4) plus small
  drift. BAC closed within 3% of its stop — tomorrow may open with an automatic exit.
- **A deposit is not profit**: the $9k capital add polluted the day-P&L anchor and the close
  report claimed "+8,985 $ (+898%) today". Fixed: capital syncs now shift the day/week/month
  anchors and the HWM by the contribution, and the live book was repaired. *Open: do the
  mirror-image adjustment when withdrawals are paid out.*
- **Anchor pollution also silently disabled the weekly/monthly drawdown breakers** (anchored
  at $1,000 while equity was $10,000 — a 90% cushion). Breakers that depend on anchors need
  the anchors to move with capital events; this class of bug is invisible until it matters.
- **OneDrive is a hostile filesystem neighbor**: one tick died with PermissionError(13) —
  almost certainly a sync lock on a data file during an atomic replace. Hardened with a
  one-shot retry + tracebacks in the journal. If it recurs, move `data/` out of the synced
  tree (or exclude it from OneDrive).
- **Claude usage measured (the user's month-length question):** today's 4 engine runs
  (3 weekly + 1 daily; the weeklies tripled by my bring-up re-runs) consumed ~17k output /
  ~24 input tokens plus ~118k cached reads ≈ **$2.86 API-equivalent**. A normal operating
  day is 1 daily (~$0.35) + occasional event runs; Mondays add one weekly (~$1). Projected
  steady state: **roughly $12–20/month API-equivalent — a small fraction of a Max plan**,
  which fits the design target of "a few short runs per day". Today's development
  conversation cost far more than the engine, but that was one-time build work.
- **The supervised-restart dance** (stop task → mutate → optionally manual run → start task)
  was exercised four times today without ever having two writers. It works, but each restart
  loses in-memory state like the bars cache; a `ibagent restart` command that does the dance
  atomically would remove the human-error surface.

Observations from real (paper) operation — friction, surprises, and what to change.
Newest entries at the top. Maintained by Claude during supervised sessions; facts only,
each entry actionable or explicitly closed.

## 2026-08-17 — first live paper day (continued: first fills)

- **FIRST POSITIONS: SMH 1 @ 595.72 (stop 543 GTC) and BAC 9 @ 65.13 (stop 61.89 GTC)**,
  weekly #3, $10k pot. Stops confirmed resting at the broker. LLY unfilled (see below).
- **Bundle told the model limits it could never satisfy.** Weekly #1 proposed 12%/9% weights;
  the $150 USD floor makes anything under 15% impossible at $1k, so every entry was rejected.
  The static mandate excerpt showed the % cap but not the floor's effect. Fix shipped: the
  excerpt now prints the EFFECTIVE dollar/weight window per sleeve at current equity, the max
  workable stop distance, and a whole-shares warning. Weekly #3 sized correctly first try —
  the model uses what it's told; tell it the truth.
- **Floor > cap deadlock**: trend cap 12% ($120) sat below the $150 floor — a config state
  where no entry can ever pass, and validation didn't catch it. Raised trend cap to 18%.
  *Open: add a mandate validator that rejects floor>cap at seed.*
- **Delayed quotes break tight marketable limits.** ask+15bps expired unfilled twice (XLV,
  XOM weekly #2); raised to 35bps; SMH/BAC then filled at ~1 tick inside the limit, but
  fast-moving LLY STILL expired. Delayed-data reality: high-ADR names need either wider
  offsets, a retry-at-fresh-quote loop, or live market data ($4.5/mo waiver-eligible).
  *Open: consider one automatic retry with a re-fetched quote before giving up.*
- **Benjamin authorized a $10,000 paper pot** (ledger note 2026-08-17) — at $1k + Fixed
  pricing + whole shares, the tradable set was ~6 symbols; at $10k everything fits, which
  exercises the full machine. Live seeding will re-decide size on real evidence.
- **Weekly invocation discipline held**: 4 Claude runs used today (weekly x3 incl. two
  re-runs after fixes, daily x1) — at the daily cap exactly. The persisted cap prevented any
  accidental 5th.
- **Handover pattern that worked**: session-bound supervisor for bring-up → stop it →
  mutate config/code → manual `ibagent run` (exclusive writer) → start the Task Scheduler
  supervisor. Two writers never overlapped. This should be the documented upgrade dance.

## 2026-08-17 — first live paper day

- **IBKR rejects fractional orders via API by default** (error 10243) even with fractional
  permission likely on: Gateway has its own checkbox (API settings → "Support fractional
  share size for orders"). Engine now floors to whole shares and fails closed below 1 share;
  `broker.fractional_shares: false` until both switches are confirmed. *Open: Benjamin flips
  the Gateway checkbox → retest → set true.*
- **Whole-share mode + Fixed pricing shrinks the tradable universe hard**: at a $1,000 pot
  the per-position budget (~$120–150) excludes any share priced above it (VTI 383, SPY,
  QQQ, most mega-caps). Expect the first weekly decision to be rejected in part; this is the
  risk layer working, not a bug. Resolves fully when fractional is enabled.
- **Paper accounts don't report SettledCash** — engine falls back to TotalCashValue for the
  broker-side figure; the pot's own T+1 ledger is the binding constraint anyway. Closed.
- **First real `claude -p` run: valid decision, first attempt, ~16 s** (Saturday daily run).
  Model correctly declined to deploy on a daily run with an empty book and set a watchlist.
  The discipline framing in the skills appears to transfer.
- **$1.00/side commission confirmed on fills** (Fixed plan): 2% round-trip at $100. Tiered
  switch remains the single highest-value config change available. *Open: Benjamin.*
