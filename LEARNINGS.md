# Live-session learnings

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
