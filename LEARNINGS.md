# Live-session learnings

## 2026-08-29 (Saturday night, engineer) — quiet tape; the weekly digest was reporting Mondays

- **No session today.** Since last night's pass the journals hold only the documented
  nightly noise: the 20:05 ET cache fill failing its first 3 symbols on every variant
  (00:01–00:06 UTC, recovered 04:51–04:53), the 04:45 UTC reset blip (Socket disconnect →
  reconnected within 5 min, one line per variant), and two extra 30-s timeouts (sniper/
  turtle 04:33, twin 02:07) that the hysteresis absorbed. Nothing traded, nothing rejected.
- **BUG (fixed): FLEET.md's weekly digest fired on MONDAY after the close.** The "Week of
  2026-08-24" section says `decisions 0` for all 7 variants — for the week that held the
  NVDA print, the first catalyst trades and 24 CRM event runs. The digest ran Monday
  evening (the outage day), covered one day, and then marked the week done; `tail(60)`
  would also have capped scalper's ~70 decisions/week. Now fires after the last close
  report of the week (Friday, or later if Friday had none) and counts the whole week.
  Regression test. First correct digest: Fri 2026-09-04. The stale Monday entry in
  FLEET.md is left as-is (it is generated, untracked output).
- **`ibagent unfreeze [--shadow NAME]` exists now** (last night's follow-up). It refuses
  while the variant's heartbeat is < 3 min old, because two writers on book.json is worse
  than a stuck freeze: stop the task → unfreeze → start. bold is still frozen; whether to
  clear it remains the owner's call, but it no longer needs a hand edit.
- **DEPLOYED 22:44 UTC**: `schtasks` is reachable from this session (PowerShell is not —
  note for future nights: `MSYS_NO_PATHCONV=1 schtasks /End|/Run /TN IBAgent-…` from
  Bash). Stop → all 7 "Ready" → start → all 7 "Running", heartbeats fresh within 60 s.
  Last night's two fixes (headline once-per-day, reconcile re-sync) and tonight's digest
  fix are live before Monday's open.

## 2026-08-28 (night, engineer) — one headline, 24 runs; the machine froze itself for its own stop

- **BUG (fixed): the event gate re-fired the same headline after every cooldown.** CNBC's
  "Benioff getting his mojo back" CRM piece (materiality 0.8, CRM +2–3.6% intraday) triggered
  main ×2, bold ×3, scalper ×4, sniper ×4, swing ×3, turtle ×3, twin ×2 between 13:34 and
  17:04 UTC — 21 symbol-triggered runs plus GOOGL's $10M-airline-data "0.95" on main/twin.
  All 24 were `no_change` on the same 4.9-ATR arithmetic; three variants wrote "consider
  deduplicating event triggers per headline" as their lesson. Root cause: the digest keeps
  items 36h, the gate only checked budget + cooldown. Fix: `EventGateState.fired_keys`
  (link, reset daily, persisted) — a headline fires once per day; a new headline on the
  same symbol still can. Regression test. Fleet lesson 13.
- **BUG (fixed): a protective stop fill races reconcile and freezes the engine.** bold's
  NVDA breakeven stop filled at 19:07:16 UTC; the tick had synced fills seconds earlier,
  `positions()` then showed NVDA 0 → `reconcile mismatch: NVDA book=3.0 broker=0.0
  (missing)` → freeze at 19:07:19 → the stop fill was applied at 19:08. Same family as the
  08-21 sleeve-breaker bug: the machine's own defence read as a disaster. Fix: when a
  missing/short mismatch is on a symbol with a resting engine stop, re-sync fills once and
  re-reconcile before freezing; a real mismatch still freezes. Regression test.
  **bold is STILL FROZEN** (`frozen: true` in data-shadows/bold/book.json, reason above) —
  the freeze is sticky by design and there is no `ibagent unfreeze`; the fix only prevents
  the next one. Owner call to clear it (entries blocked, exits unaffected). Follow-up worth
  doing: an `ibagent unfreeze` command so a false freeze doesn't need a hand-edit of book.json.
- **NOT deployed.** Both fixes affect the running supervisors; task control (PowerShell)
  was denied in tonight's session so the documented stop→verify→start dance could not be
  verified. The fleet runs the old code until the next supervisor restart — Monday's open
  will re-fire stale headlines unless restarted before 09:30 ET.
- **Fleet after 9 trading days**: twin +13.20, scalper −0.98, turtle −29.80, bold −30.41,
  swing −31.76, sniper −42.36, main −100.23. NVDA −4.5% on the day cost every holder
  (main −40.88, turtle −30.78, swing −20.48); all stops except bold's still ~3% away. main
  vs SPY since 08-24: −165. twin's SMH re-attempt was rejected again ("weekly turnover cap
  reached") — the core-fills-count-as-turnover issue from last night, resets Monday 08-31.
- **scalper: 14 runs, 14 no_change, same blocker** (intraday fields null) — the RTH
  `day_change` probe was not run tonight either (no RTH session for me); it stays the
  design-deciding question. Its 30-min scan remains pure cost.
- sniper's first CRM event fired at 13:34 UTC = 09:34 ET — inside `is_rth` but the plan
  held with "outside RTH trade window" (equity 0.0 in the plan line): the event gate and
  the order window disagree by a few minutes at the open. Cost one event slot + one run.
  Small; aligning the gate to the trade window is a candidate for a quiet night.
- OneDrive PermissionError: main 16:09 UTC → 14+ total. Nightly 04:45 blip and the 21:07
  UTC reset (turtle only, reconnected 21:12) behaved as documented.

## 2026-08-27 (night, engineer) — NVDA day: the fleet finally bought a catalyst, and the event gate slept through it

- **First catalyst trades of the forward test.** NVDA beat-and-raise (after the 08-26 close)
  → in the 09:50 daily: main 4 sh @ 223.51 + JPM 1 sh, turtle 3 sh @ 222.22, swing 2 sh
  @ 222.22 (spec) — all inside the chase gate at the gap open; all closed the day +1.7–2.1%
  from fill. bold (half-sized into the print on 08-25) held and refused to add at the cap.
  twin proposed SMH and was rejected (see turnover below). Discipline held everywhere: no
  variant chased CRM (+20%) or NVDA after the first run. Distilled as fleet lesson 12.
- **BUG (fixed): the event gate burned the whole daily budget before the open.** main 3/3,
  swing 3/3, sniper 4/4 triggers consumed at 06:17–06:45 ET on pre-market NVDA headlines;
  `_news_job` then declined to run outside RTH — but `check_event_gate` had already counted
  the trigger and armed the cooldown. Result: zero event runs for those three on the most
  material day so far (sniper, the "news specialist", never woke up). Fix: the gate takes
  `can_fire=is_rth(now)` and returns without mutating state outside RTH. Regression test.
  NOTE this is a sibling of the 08-18 bug family ("decide only when the market can act"):
  budgets, like decisions, must only be spent inside the window where they can be used.
- **Core deployment eats the model's weekly turnover budget (twin blocked).** twin's core
  buys on 08-25 (VTI+SGOV, $4,555 = 45.5% of equity) count toward `week_turnover_usd`; the
  50% cap then rejected its first trend entry (SMH ~$650) on 08-27 with "weekly turnover
  cap reached". main only escaped this in its own first week because its trend entries
  (08-17) preceded core (08-18). Every fresh account will hit it: core is code-driven and
  passes no turnover check itself, yet it charges the model's churn allowance. NOT changed
  tonight — excluding core fills from the turnover counter is a risk-semantics change on
  MAIN's mandate and the charter says write it down. Proposed one-liner:
  `book.apply_fill`: `if sleeve != "core": self.week_turnover_usd += notional`. Owner call.
  twin's budget resets Monday 08-31; the fee A/B loses one week of trend exposure.
- **scalper: 14 model runs, 13 identical no_change, one 900-s timeout** (15:08–15:23 UTC,
  the run was re-issued and answered in 48 s). Every note names the same blocker: intraday
  fields null. Its 30-min scan is pure cost until `day_change` populates; it found the
  right answer (do not chase a +10%/+20% gap) 13 times over. Not touching its cadence yet —
  the fix belongs in the data path, not in scanning less.
- **`day_change` is still null everywhere — and I could not run the RTH probe.** Tonight's
  one-off `reqHistoricalData(NVDA, 5 D, 1 day)` at 22:45 UTC from a fresh client (one
  request, so NOT pacing) timed out at 20 s, exactly the "no historical bars" the fleet saw
  for AMZN/ADBE (13:46–13:58 UTC, all 7 variants within 12 min), V (20:24–20:31, all 7) and
  COST (22:18–22:21, 4 of 7). Same symbol, same minute, every client → the history farm is
  flaky IB-side, per symbol, not per client. The scan-surface/pacing hypothesis from 08-26
  is weakened. TOMORROW during RTH, one probe decides the day_change design: does a 1-day
  bar request return today's partial bar on delayed data (market_data_type 3)? If yes, the
  refetch already does the right thing and the nulls are the farm; if no, the intraday
  fields need `reqHistoricalData(… '1 D', '1 hour')` or a quote-based day_change instead.
- The 20:05 ET cache fill fails its first 3 symbols and skips 5–11 on every variant every
  night (00:04–00:06 UTC), then recovers at 04:53 UTC after IB's reset. Harmless (bars
  are served from the previous day's cache meanwhile) but it is the same farm flakiness.
- OneDrive PermissionError: bold 17:38, scalper 16:12, turtle 15:35 UTC → 13+ total.
- Fleet after 8 trading days (equity): twin +19.77, swing +11.48, scalper +8.60, turtle
  +8.39, bold +6.02, sniper −39.41, main −58.49 (main carries the SMH stop-out −50.21 and
  a $1/side fee bill; twin, same brain on tiered, is +$78 ahead — but also one week
  behind on trend exposure, so the A/B is not yet clean).

## 2026-08-26 (night, engineer) — the timeout fix held; the circuit breaker was hiding the book

- **17:00 ET reset survived, fleet-wide.** Six variants sailed through 21:00 UTC without a
  single line; twin took one `IB request timed out after 30s (connection dropped)` at 21:08
  and was reconnected by 21:13 — 5 minutes of hysteresis-quiet outage vs 85 wedged minutes
  the day before. All 7 heartbeats fresh at 22:41 UTC. Yesterday's fix is proven.
- **Gateway itself was down 22:55→02:59 UTC (4h04, 46 attempts), right after the deploy** —
  `WinError 1225 connection refused`, i.e. the Gateway process was gone, not our socket.
  One error line + one reconnect summary per variant: hysteresis did its job. Cause unknown
  (IB nightly restart window or the Gateway's own auto-restart); nothing traded, nothing lost.
- **scalper has been BLIND all session — 13 model runs on 3 of 48 symbols.** Every bundle
  today held only AAPL/AMD/AVGO, none of its five held positions, and `close` never moved
  (AAPL 309.9 in all 13). Root cause was ours: the bars circuit breaker (added last night)
  `break`-ed out of the pass, so symbols sorting AFTER the first three failures were dropped
  from the result even when they were already cached (the protective pass had fetched
  QQQ/SPY/XLF fine at 13:32). The model's 13 identical lessons ("data problem, not
  indecision") were correct and useless. Fixed: cached symbols are always served; the
  intraday refetch loop (which silently burned ~15 × 20s per event run — bundle stamped
  13:32, model started 13:41) is now bounded by the same streak rule. Regression tests pin
  both. NOTE the design rule: a circuit breaker must degrade to "what we already know",
  never to "nothing".
- **Why scalper's history requests fail all day while the other six are fine is STILL
  open.** ABBV/ADBE/AMZN/META returned empty at exactly the 20s timeout, every tick, from
  13:36 to the close; no other variant lost a symbol after 13:55. Scalper is the only client
  requesting 48 symbols + a ~15-symbol refetch every 30 min — IB historical pacing
  (60 requests/10 min, per user) is the leading hypothesis, and it is self-inflicted. The
  bounded refetch cuts the request rate ~5×; if `no historical bars` still fires on the scan
  surface tomorrow, the next step is fetching the scan surface once pre-open, not per tick.
- **`day_change` / `day_open` have been null in EVERY bundle of EVERY variant since day 1.**
  The daily-bar cache is keyed on the UTC date, so it is filled at ~20:00 ET with bars that
  end yesterday and served all session; only the event-run refetch could ever populate the
  intraday fields, and scalper's never succeeded. Whether IB even returns today's partial
  daily bar on this delayed-data plan is untested — check tomorrow with a one-off fetch
  during RTH before building on it. Until then the "day-trader playbook" is running on
  yesterday's closes by construction.
- **Two variants (scalper, turtle) reported "skills/ contains only README.md and REFRAME.md"**
  — the bundle had all 13 skill folders; the model did a shallow listing. Prompt now says
  where the checklists live (`skills/<name>/SKILL.md`). Cheap, harmless.
- **Sniper burned 2 event runs on non-events** (NVDA earnings-preview headline at 0.8
  materiality; AAPL launch-date). Its own lesson: "calendar headlines never broke a held
  thesis". Distilled into fleet-lessons; the scorer is untouched (two data points).
- OneDrive PermissionError: sniper 19:28 + scalper 19:38 UTC → 10+ total. Owner decision
  still pending.

## 2026-08-25 (night, engineer) — a request with no timeout is a request that can last forever

- **The 85-min wedge had a one-line root cause**: ib_async's `IB.RequestTimeout` defaults
  to 0 = wait forever. At IB's 17:00 ET server reset the socket went half-dead and every
  tick on all 7 variants sat inside `reqTickers`/`reqExecutions` until the manual restart.
  Fixed: `broker.request_timeout_s` (30s default) caps every request; a timeout DROPS the
  connection so the supervisor's reconnect hysteresis (one alert per outage) takes over,
  instead of each subsequent call timing out in turn. Deployed 22:45 UTC via the restart
  dance; all 7 heartbeats fresh within 60s. Tomorrow's 17:00 ET reset is the real test.
- **The same tape hid a second, daily loss**: at 09:36 ET all 7 variants ran 48 consecutive
  history requests that each hit ib_async's 60s internal timeout and returned []. Every
  tick was blocked ~48 min; the "09:45 ET" weekly decisions actually ran 10:22–10:32 ET
  and those symbols never recovered all day. Bars have failed on 7 of the last 8 trading
  days (main: 344/71/284/584/206/1/48 warning lines) — the Friday "pacing" hypothesis
  was too narrow; it happens at every open. Fixed the COST (bars timeout 20s + skip the
  rest of the pass after 3 consecutive failures, retry next tick); the CAUSE is still
  open. WATCH tomorrow: does `history unavailable; rest of pass skipped` fire at the
  open, and do `bars_recovered` markers follow? If it never recovers intraday, the 48
  scan-surface symbols may need to be dropped or fetched once pre-open.
- **Watchdog verification is impossible after the fact**: it alerts to Telegram but
  journals nothing, and its state file resets to `{}` on recovery. Whether Benjamin got
  the 🚨 for 21:08–22:35 can only be answered by his phone. Small follow-up: journal
  watchdog transitions.
- **OneDrive PermissionError: 4 more today** (main 20:07, sniper 14:32, swing 14:35, twin
  03:13 UTC) — that is 8+ total; the day-4 "three times is a migration" threshold is long
  past. Still an owner decision (see report).
- First fee-A/B fills: twin deployed core (VTI $3k + SGOV $2k) at 14:59 UTC — the A/B clock
  starts today. sniper and swing both bought XLF (17 sh @ 58.15, stop trailing 56.39→56.70
  through the session). Too fresh to judge; nothing distilled into fleet-lessons tonight.

## 2026-08-24 (night) — the assistant lied during the outage, politely

- **Fail-closed data must not become "nothing there".** At 17:48 UTC, Gateway still down,
  Benjamin asked the Telegram assistant to "fix it". The Q&A bundle could not mark the
  book (no quotes → `book.equity` raises, correctly), so the fallback wrote
  `portfolio.json = {}` — and the model answered "portfolio.json is empty, no positions
  loaded" while VTI + SGOV sat in the book with stops resting at the broker. Fail-closed
  on ORDERS is right; fail-EMPTY on INFORMATION is a lie. Fixed: an unmarkable book now
  ships a `status: DEGRADED …` portfolio with the engine's positions, and the prompt tells
  the model to lead with "broker link is down". Regression test pins it.
- **Hysteresis held on its first real outage**: Monday's 9h Gateway outage (13:17→22:24
  UTC) produced ONE `connect` error line per variant (vs 211 over the weekend) and the
  reconnect summary; the SMH stop fill was synced retroactively on recovery. The
  weekend's 211 lines in today's counts are all pre-fix.
- **twin has still never decided**: seeded Sat 08-22, its first weekly was Monday 09:45
  ET — eaten by the outage. Its weekly + daily are unmarked, so they fire Tue morning
  under the roll-forward rule; the fee A/B starts a day late. Nothing to fix.
- **The 04:45 UTC blip is nightly**: `Socket disconnect` + "missing quotes for held
  symbols" at 04:46–04:48 UTC on 08-20, 21, 23, 24 — IB's server-side reset window.
  Self-heals within one tick; not the 9:15 ET login loss. Leave it.

## 2026-08-24 — the lost Monday, replayed: what the outage actually cost

Gateway's daily restart at ~9:15 ET logged out with nobody home; the whole session ran
without decisions. Counterfactual from today's hourly tape + Friday's journaled intentions:

- **Missed trades ≈ $0 to −$10.** The documented queue was LLY 1sh + MRK 4sh re-entries at
  ~9:50. LLY entered ~1,252 → closed 1,247.77 (−$5±); MRK entered ~150.6 → closed 150.70
  (≈ flat); +$2 fees. The day was drifting red (SPY −0.17%, QQQ −0.47%, NVDA −3.26%):
  nothing worth having was on sale.
- **The stop that fired was RIGHT.** SMH stopped out at 547.52 at 9:38 — by IBKR's servers,
  fully offline on our side — and SMH closed BELOW that (546.66, daylow 540.75). The
  protective exit beat holding. Server-side stops earned their existence in production.
- **scalper would likely have scored zero anyway**: its continuation trigger (≥1.5% from
  open, top third of range) was never met by any watchlist name (best: JPM +1.41% max).
- **Held-position P&L accrued regardless** — marks don't need our Gateway. The outage's real
  cost was not missed profit but UNPROTECTED DECISION TIME: if a crash had come, only the
  GTC stops stood guard (they did, correctly). Conclusion: morning-login fragility is a risk
  problem, not a returns problem — and it still must die (Auto restart / IBC).
- Recovery-path bug fixed the same evening: an overdue weekly now rolls to the next trading
  MORNING instead of firing into a closed market and burning the week's slot.

## 2026-08-23 — weekend outage post-mortem: the system healed itself, but shouted the whole time

- **IB Gateway was down Sat 20:01 UTC → Sun 23:29 UTC (~27.5h) and recovered by itself**
  before Monday's open — no action was needed, the machinery did its job. But each of the
  7 supervisors journaled an identical connect error every ~5 minutes (~211 lines each,
  ~1,500 fleet-wide), and main pinged Telegram "broker connection down" every 30 minutes
  all weekend — the exact alert-fatigue failure the day-2 watchdog fix identified, living
  on in the supervisor's own connect path. Fixed with the same hysteresis pattern: one
  error + one alert when an outage starts, at most one reminder/hour, one summary
  (duration + attempt count) on recovery. Regression tests pin both paths.
- **Friday 16:00–20:00 UTC: historical bars failed for ALL 14 universe symbols on every
  scan cycle, on all 7 variants, while quotes kept working.** Started at the 15:59 UTC
  fleet restart (breaker-fix deploy). Working hypothesis: 7 clients re-requesting daily
  history simultaneously trips IB's historical-data pacing/farm limits after a mass
  restart. Fail-closed held (no orders came from empty stats), but ~800 duplicate
  warnings/variant were pure noise — bars warnings are now once per symbol per day with
  a `bars_recovered` marker bracketing the window. WATCH: whether bars fail again after
  the next fleet restart; if so, stagger the shadows' startup.
- **OneDrive PermissionError hit a third time** (swing, Fri 09:30 UTC tick). Day-4 rule
  said "three times is a migration": moving `data/` + `data-shadows/` out of the OneDrive
  sync tree (or excluding them) is now due. Owner decision — flagged in tonight's report,
  not done autonomously.
- **scalper is still a day trader that has never day-traded**: 6 more intraday runs on
  Friday, zero orders, zero realized round-trips since inception — yet second-best equity
  (−$27 vs turtle's −$26). Restraint keeps outscoring activity, which is exactly what the
  backtest predicted.
- All three Friday false sleeve-pauses (main, sniper, swing) are confirmed lifted; books
  show no paused sleeves. First FLEET.md weekly digest fires Mon 08-24 after the close.

## 2026-08-22 — the backtest speaks: simple beat clever (2023-08 → 2026-08, real IBKR data)

| strategy          | CAGR  | maxDD | Sharpe | trades | fees    |
|-------------------|-------|-------|--------|--------|---------|
| SPY buy-and-hold  | 10.9% | 17.9% | 0.88   | 1      | $1      |
| core 60/40        |  7.3% | 12.3% | 0.89   | 2      | $2      |
| momentum top-3    |  8.6% | 16.2% | 0.57   | 176    | $176    |
| swing tight-stops |  4.7% | 23.1% | 0.33   | 364    | $364    |

- **Buy-and-hold beat every mechanical active variant** over this (bull-heavy, V-recovery)
  window. Trend-following's known weakness: stops eject you in dips, re-entry lags the
  rebound. One window ≠ verdict, but the bar is set: the momentum skeleton alone earns
  LESS than doing nothing, with more trades and more stress.
- **Fees compound brutally at Fixed pricing**: $176 (1.8% of the pot) for monthly momentum,
  $364 (3.6%) for weekly swing — before any adverse selection. The Tiered switch is worth
  ~2.3 percentage points of CAGR to the fast variants. (Live scalper trades ~daily: worse.)
- **Tight stops + fast rotation was the WORST of both worlds**: highest drawdown AND lowest
  return — whipsaw harvesting. Prediction sharpened: swing and scalper shadows will lag.
- **This defines the AI's job precisely**: the mechanical skeleton does not beat the market,
  so any edge must come from the judgment layer (news, fundamentals, regime timing) that
  backtests cannot measure — exactly what the 6-agent forward test exists to falsify.
- All numbers are optimistic upper bounds (survivorship-biased universe, close fills).

## 2026-08-21 — day 5: "why is everyone losing?" has a quantitative answer, and it found a bug

- **Attribution before blame.** VTI −0.91% since the fleet's entries; SMH −5.7% on the
  week. Every variant is DOWN LESS than the market (−0.45% to −0.83%): the losses are beta
  in a red week, cushioned by cash buffers and stops. Two real trading mistakes exist —
  sniper and swing each bought the HD dip and were wrong (~−$29 each) — tuition, journaled.
- **Owner questions are a test suite.** "Why are all losing?" exposed that the sleeve
  drawdown breaker measured MARKET VALUE, so BAC's protective stop-out (value → cash)
  read as a 50% sleeve crash and falsely paused main's trend sleeve for a month; sniper
  and swing got the same false pause from their HD exits. Defense was being punished as
  disaster. Fixed: sleeve breakers now track cumulative P&L give-back from the sleeve's
  P&L high-water, scaled by the sleeve's target size; exits are invisible to it. Three
  false pauses lifted; regression tests pin exit-vs-loss behavior.
- **Design rule extracted**: any breaker metric must be invariant under the system's own
  protective actions — otherwise the machine punishes itself for working.

## 2026-08-20 — day 4: first stop-out, and the day trader who wouldn't trade

- **First full defend-and-exit cycle worked end to end.** BAC hit its trailing stop at
  11:45 ET: SELL 9 @ 62.63, realized −$23.50 (0.24% of the pot). The trail had been raised
  from 61.89 → 62.63 on day 1's high, clawing back ~$7 vs the original stop. Cooldown and
  stop-out history recorded automatically. This is the risk machinery's first live kill —
  small, controlled, exactly as designed.
- **Red day across the board**: every variant lost ~0.45–0.55% (semis + yield pressure).
  turtle "leads" by losing least — consistent with its control-group role so far.
- **scalper ran ~13 intraday decisions and traded ZERO times.** The forced checklists
  (anti-chasing, failure-modes, sizing) restrained even the variant told to day trade —
  it kept its day-1 positions and passed on everything intraday. Two readings: discipline
  works, or the gates are too tight for a scalping mandate. Watch whether it EVER trades;
  a day trader that never trades is just an expensive turtle.
- **LLY has now expired unfilled on 3 consecutive days** (high price + wide ATR + delayed
  quotes at ask+35bps). A pattern, not luck. Candidate fixes: per-symbol wider offset when
  ATR% is high, or one automatic retry at a re-fetched quote before giving up. TODO.
- **OneDrive PermissionError recurred** (now with traceback) and an overnight socket
  disconnect self-healed. If the OneDrive locks keep appearing, move data/ out of the
  synced tree — twice is coincidence, three times is a migration.

## 2026-08-18 — day 2 close: alert fatigue is a failure mode too

- **Day 2 result: −$29.99 (−0.30%); fees $2.** Book at the close: VTI 7 + SGOV 19 (core),
  SMH 1 (down on the day) + BAC 9 (up slightly). LLY/MRK re-entry still queued — the make-up
  run was blocked by the AI cap, tomorrow's 09:50 in-RTH daily is their first real shot.
- **The owner mutes what spams him — then the alert channel is worthless.** The watchdog
  fired a 🚨 every 5 minutes through every restart and PC-sleep. Benjamin's reaction was
  "stop, I don't care": exactly how a real safety channel dies. Watchdog now has hysteresis:
  one 🚨 when an outage starts, one ✅ when it recovers, at most one reminder/hour between.
  Rule: an alert that repeats without new information trains the human to ignore ALL alerts.
- **The owner's usage pattern beats the design assumption.** Planned: ~4 model runs/day.
  Reality day 2: 8+ (six Q&A chats). The cap (now 40 as runaway backstop), the 2-slot
  trading reservation, and in-RTH scheduling all came from watching real use, not the spec.
- **Q&A journaling mislabeled success as failure** (`ok:false` with the answer inside the
  error field) because schema-less runs reused the decision parser's ok. The answers were
  delivered all along — with the requested bullet formatting. Fixed; forensics must
  distinguish "no JSON decision" from "failed".
- **Console-subprocess hygiene on Windows**: the watchdog's python.exe flashed a cmd window
  on the desktop every 5 minutes (owner noticed while gaming). Scheduled tasks that share a
  desktop with a human must use pythonw. Cosmetics are adoption-critical.
- **The invalid-mandate fail-safe worked in anger**: setting cap 40 against a config ceiling
  of 20 made the supervisor refuse to start (task "Ready", not "Running") — caught within a
  minute because the restart dance always ends with a state check. Keep that habit.

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

## 2026-08-25 (evening) — URGENT for tonight engineer: tick wedged 85 min at the 17:00 ET reset — DONE same night, see top entry
- All 7 supervisors heartbeats went stale 21:08-21:14 UTC (IBKR daily server-reset window);
  ticks blocked inside broker calls (quote/fills_since warnings streaming at 22:33 from a
  tick started 21:08). Manual kill+restart fixed it 22:35 UTC. ROOT CAUSE TO FIX: broker
  calls inside tick have no hard timeout on a half-dead socket - add a per-call timeout
  (ib_async reqTimeout / asyncio wait_for) so a dead connection fails a call in seconds,
  not hours, and the tick moves on. Also verify the watchdog alerted (stale >10 min - did
  Benjamin get the Telegram?). NOTE: 14 pythonw processes is NORMAL (venv launcher = 2 per
  task); do not chase that.
