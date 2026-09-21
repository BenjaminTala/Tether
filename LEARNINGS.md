# Live-session learnings

## 2026-09-21 (Monday night, engineer) — main sat out Monday frozen (4th day; the owner asked for Status at 18:08 UTC and no unfreeze followed); the history farm was dead until 16:45 UTC for the 6th time and a plain reconnect did NOT heal it; NOT deployed tonight, on purpose

- **main is still frozen** and its model does not know what that means: both the 13:48 weekly
  and the 13:54 daily wrote "portfolio.json breakers.frozen=true — not defined anywhere in the
  bundle … please confirm its meaning". Every run planned `hold: frozen`. The owner's
  `Status` at 18:08 UTC got last night's reworded watch-out (reason + steps); still frozen at
  the 20:21 report. Runbook unchanged: TWS shows SGOV 19 / VTI 7 → stop `IBAgent-Supervisor`
  → `ibagent unfreeze` → start it.
  **Fix (bundle text, not deployed):** a frozen book's `breakers` now carries `frozen_note` —
  the reason, that every run is planned as HOLD until the owner clears it, that resting
  stops still work, and "one line, no_change". Absent when not frozen. Test.
- **History farm: 6th dead morning, and two new facts.** `no historical bars` from 00:06 UTC
  until `bars_recovered` at 16:46–16:48 on all 7, right after the Gateway's 16:45 UTC
  auto-restart. (a) **A client reconnect does not heal it:** sniper, swing and turtle dropped
  on a 30-s quote timeout at 16:32–16:33, reconnected 16:33–16:34, and served stale bars
  again at 16:38–16:39; recovery came only after the Gateway restart. So "dead for this
  connection" (09-11, 09-14 entries) is wrong — it is dead inside the Gateway, and a forced
  reconnect in our code would fix nothing. (b) **Every dead morning this month followed a
  22:4x–22:5x UTC fleet redeploy whose first bars pass already failed** (post-deploy
  warnings 09-10, 09-15, 09-17, 09-20 → dead 09-11, 09-16, 09-18, 09-21; the 09-16 deploy
  had a clean first pass → 09-17 healthy). That is the 08-23 entry's hypothesis (7 clients
  re-requesting history at once) with five more samples. The restart used to be cured by
  the 04:45 UTC Gateway auto-restart before anyone traded; since that moved to 11:45 AM
  local it is cured mid-session instead.
  **Therefore no deploy tonight**: tomorrow is the first weekday in two weeks without a
  redeploy the night before. If 13:50 UTC shows fresh bars on all 7, the deploy is the
  trigger and the next deploy should start the 7 tasks staggered (60 s apart) — and tonight's
  two fixes ride along with it. If the farm is dead anyway, deploy as usual tomorrow night.
- **The 09-18 on-disk fallback is proven:** all 7 weeklies/dailies ran on `bars_stale_served
  … last_bar 2026-09-18` rows instead of `market.json = {}`. Its limit showed too: main's
  weekly had 11 of ~50 symbols, TSLA was absent in main's 15:00 event run, and scalper's
  `bars_refresh` was `fetched 0` for its first 8 scans (13:41–16:42), 22/22 at 17:12.
  Universe warm-up (report job) stays open — but NOT as written: ~40 extra requests × 7
  clients in the same minute is the very burst suspected above. Stagger it or do it on main
  only and share the file.
- **Event gate: one headline, 7 runs, 7 no_change.** "Did Elon Musk Just Drop a Big Hint About
  a Possible SpaceX-Tesla Merger?" (0.8 via "merger", TSLA +3.1–3.8%, 14:49–15:00 UTC). Every
  variant triaged Soft in one pass. **Fix (not deployed):** a title ending in "?" is halved
  like other commentary; across all 7 stores (415 unique items) it is the only gate-level
  item touched. sniper's LLY run (CEO interview, 0.65) was a correct Soft pass — left alone.
- **Both of today's entries filled at about twice the size the model meant.** twin's daily:
  "intended 1 share … target_weight 0.16 so one share still fits if the engine applies the
  0.5 multiplier" → 2 SPY. scalper's 18:13 scan: "weight 0.15 x 0.5 is about $744, 4 shares …
  without the multiplier it is 9" → 9 MRK. `risk.plan_orders` applies `risk_multiplier` to
  the TOTAL active-weight cap and scales pro-rata only above it; a single 0.15 weight is
  never touched. Both fills were inside every cap — the engine did what it is written to do;
  the models guessed at it. **Fix (prompt text, not deployed):** the shared system prompt now
  says the multiplier never shrinks an individual `target_weight` — "if you mean half size,
  write half the weight". No risk-code change. Test pins the sentence. Fleet lesson 19.
- Session: bold's XOM sim stop filled 160.40 at 13:52 UTC (−21.56, 4th loser → entry cooldown
  to 09-23). **twin bought SPY** 2 @ 766.67 in the daily (regime/breadth thesis, stop 729 →
  trailed to 757.37) and is the first variant above water. **scalper bought MRK** 9 @ 149.56
  at 18:13 UTC (first entry after its cooldown; +2.2% day on a pipeline item), stop 145.50.
  Standings: twin +11.49, turtle −2.95, swing −48.67, bold −68.26, scalper −74.93,
  sniper −82.39, main −126.87 (main is core-only and frozen; its gain today is VTI).
- Written down, not changed:
  - **twin's SPY trail was replaced 20 times in one session**, some by 2–4 cents
    (755.5983 → 755.6383). Free on the sim; on main each one is a cancel/replace at IBKR.
    A minimum trail step (e.g. 0.1 ATR) would cut it ~5×, but it touches the stop path —
    owner decision, not a nightly tweak.
  - **34 decision notes this month end with "Gmail/Calendar/Drive connectors need
    authorization in claude.ai settings"** (scalper 12; first 09-10). The owner's claude.ai
    connectors are being offered to the headless model run. `dontAsk` + the allow-list would
    refuse them, but they should not be loaded at all: **owner, do not authorize those
    connectors on this account while the fleet runs**; candidate fix is
    `--strict-mcp-config` on the runner command, to be tried with a manual `ibagent run`
    watching, not blind.
  - Zero `PermissionError` lines on any of the 7 for a second day since the
    `ScheduleState.save` retry. `positions()` dead-link guard still unexercised (main's
    16:45 drop died in `fills_since` again).

## 2026-09-20 (Sunday night, engineer) — no session; MAIN IS STILL FROZEN, 60+ h (owner unfreeze needed before Monday 09:30 ET); the Gateway sat logged out 259 min and this time the 11:45 auto-restart healed it

- **main is still frozen** (`book.json` read-only check: `frozen: true`, reason = the 09-18
  false mismatch). Third night in this file. Runbook unchanged: TWS shows SGOV 19 / VTI 7 →
  stop `IBAgent-Supervisor` → `ibagent unfreeze` → start it. If it is not done, Monday's
  daily plans as `hold: frozen` again.
- **Fix (alert clarity): the FROZEN watch-out now says what is wrong and how to clear it.**
  The owner-facing status line read "Engine is FROZEN: the book and IBKR disagree — check
  the account." for 60+ h, across two owner visits to the machine (Gateway login Sat 12:24
  local), and named neither the mismatch nor the command. It now carries `frozen_reason`
  and the stop-task → `ibagent unfreeze [--shadow NAME]` → start-task steps. Text only; the
  freeze logic, reconcile and every risk rule are untouched. Test: a forced mismatch's
  watch-out contains the symbol/qty detail and `ibagent unfreeze`.
- **Sunday Gateway outage, 259 min, self-healed.** 12:20–12:21 UTC (07:20 local): the 30-s
  timeout on all 7 (main's inside `fills_since`, shadows' on the SGOV quote), then `LOGGED
  OUT` handshake errors, `still_down` at 62/124/186/248 min, `reconnected, down_minutes: 259,
  failed_attempts: 42` on all 7 at 16:46–16:47 UTC — one minute after `launcher.log`'s
  11:45:04 local `IB GATEWAY RESTART` … 11:45:10 `Authentication complete`. So the same
  auto-restart that did NOT restore Saturday's session DID restore Sunday's: two samples,
  one each way — the restart is not a dependable healer, and at 11:45 AM local it still
  lands mid-session on weekdays (6th day; owner setting, Gateway → Configure → Lock and Exit).
- **Last night's `ScheduleState.save` retry: zero `PermissionError` lines on any of the 7
  since the 22:42 UTC deploy** (24 h, ~1 of them would have been typical). Too short to
  call, but the count has stopped for now. `positions()` dead-link guard: still unexercised —
  main's drop today died in `fills_since` again, before reconcile.
- No session, no decisions, no orders. Standings unchanged (`ibagent compare`): twin −38.21,
  turtle −55.60, bold −62.61, swing −75.00, scalper −83.50, sniper −113.98, main −163.74.
- **DEPLOYED 22:42 UTC** via `schtasks` from Bash (Sunday, market closed): end all 7 → all
  Ready → run all 7 → all Running, heartbeats 22:42:17–18, all 7 `reconnected`, bold
  `sim_stops_restored`. main came back still frozen, as expected.
- Not done, on purpose: no unfreeze (writes `data/book.json`; owner command); no
  fleet-lessons edit and no shadow knob changes (no model ran, no new results); universe
  warm-up after a restart stays the top open item.

## 2026-09-19 (Saturday night, engineer) — no session; MAIN IS STILL FROZEN (owner unfreeze needed before Monday 09:30 ET); the OneDrive PermissionError finally has an address: 46 of 46 are `schedule_state.json`

- **main is still frozen** (`book.json`: `frozen: true`, reason = the 09-18 false mismatch).
  The owner logged into the Gateway at 12:24 local today (below) but no unfreeze followed.
  Same runbook as last night: check TWS shows SGOV 19 / VTI 7 → stop `IBAgent-Supervisor` →
  `ibagent unfreeze` → start it. Until then main plans every daily as `hold: frozen`.
- **Fix (deployed): `ScheduleState.save` gets the one-shot retry `Book.save` has had since
  day 4.** Tallying every `PermissionError` trace in all 7 journals (08 + 09): 46 of 46 with
  a target are `schedule_state.tmp -> schedule_state.json` (20 via `_news_job`, 16 via
  `_protective_job`, 5 `_status_update`, 5 directly in `_jobs`); `book.json`, which retries
  once after 0.5 s, has zero. So the "noise as documented" was one unguarded `tmp.replace`,
  and it was not free: the exception kills the rest of the tick, and `_news_job` runs BEFORE
  `_protective_job` in `_jobs` — 20 times the protective check of that tick was skipped and
  ran one loop later. Latest instance: main 22:03:28 UTC tonight. A lock that outlasts the
  retry still surfaces as a tick error, as before. Test: first replace raises → saved on
  the second; a persistent lock still raises. If the count keeps growing after this, the
  retry is too short and the owner's "move data/ out of OneDrive" decision is due for real.
- **Saturday Gateway outage, 129 min, owner-healed.** 04:30–04:33 UTC: the usual 30-s quote
  timeout on all 7, back in 5 min. 15:09–15:10 UTC: timeouts again (main's inside
  `fills_since`), then `LOGGED OUT` handshake errors, `still_down` at 60 and 124 min — the
  11:45 local auto-restart (`launcher.log` head 11:45:05, "restoring session token") fired
  mid-outage and did NOT bring the session back; the owner's login at 12:24 local did
  (`reconnected, down_minutes: 129, failed_attempts: 21` on all 7 at 17:26 UTC). The
  auto-restart is still 11:45 AM local (5th day). Weekend, nothing at stake.
- **Last night's two fixes: one half-proven, one untested.** `bars_cache.json` exists on all
  7 (198–353 KB, last written 12:34–12:43 UTC), so a Monday restart or dead farm has
  Friday's bars to fall back on (3 days old Monday, inside `BARS_STALE_MAX_DAYS`). The
  `positions()` dead-link guard did not get exercised: neither of main's two drops today
  journaled a `reconcile` error (the tick died earlier, in the quote / `fills_since`).
- No session, no decisions, no orders. Standings unchanged: twin −38.21, turtle −55.60,
  bold −62.61, swing −75.00, scalper −83.50, sniper −113.98, main −163.74. scalper's
  cooldown has ended; its first free scans are Monday.
- **DEPLOYED 22:42 UTC** via `schtasks` from Bash: end all 7 → 0 Running → run all 7 → all
  Running, heartbeats 22:42:21–22, all 7 `reconnected` 22:42:24–25, bold `sim_stops_restored`
  (XOM). main came back still frozen, as expected. No bars warnings after the restart.
- Not done, on purpose: universe warm-up after a restart (still the top open item; with
  the on-disk cache its cost is now only the symbols no pass has fetched since Friday); no
  shadow knob changes and no fleet-lessons edit (no model ran today).

## 2026-09-18 (Friday night, engineer) — MAIN IS FROZEN on a false reconcile mismatch (owner action needed before Monday); last night's deploy blinded all 7 dailies; both causes fixed and deployed

- **main froze itself at 12:23:23 UTC and is still frozen.** Sequence in its journal: VTI
  quote `IB request timed out after 30s (connection dropped, will reconnect)` at 12:23:22 →
  `freeze: SGOV book=19.0 broker=0.0 (missing); VTI book=7.0 broker=0.0 (missing)` one second
  later → `Not connected` on every watched quote → `reconnected` 12:28. `IBKRBroker.positions()`
  reads ib_async's local cache, which the disconnect empties, so the same tick's reconcile saw
  a flat account. The 13:53 daily planned as `hold: frozen` (its cooldown had expired 09-16, so
  this was main's first free daily — it was `no_change` anyway on an empty tape). The same
  30-s timeout hit turtle, swing and twin on 09-17 harmlessly: shadows reconcile against the
  sim. Only other freeze on record is bold's 08-28 stop race.
  **Fix (deployed):** `positions()` raises `BrokerError("positions: not connected")` on a dead
  link; `_reconcile` already journals that as an error and skips the tick. A mismatch on a
  live link freezes as before. **Not done by me:** the unfreeze — it writes `data/book.json`
  and is an owner command. Owner: stop `IBAgent-Supervisor` → `ibagent unfreeze` → start it
  (check TWS shows SGOV 19 / VTI 7 first). Until then main cannot trade; exits at the broker
  (none resting — core only) are unaffected.
- **All 7 dailies (13:51–13:53 UTC) got `market.json = {}`, and the deploy caused it.** After
  last night's 22:44 UTC restart every variant logged `no historical bars` at 22:45 and
  `history unavailable; rest of pass skipped` again at 00:05; `bars_recovered` came only at
  16:48–16:51, after the Gateway's 16:45 UTC auto-restart (4th day at 11:45 AM local). The
  09-11 stale-bars fallback lives in process memory, so the restart threw it away. Every
  model applied lesson 10 in one pass ("second empty market.json in a week", no re-diagnosis,
  no blind stop moves); sniper's 16:48 DIS event run (CTO hire, 0.65, −2.2%) also lacked DIS.
  **Fix (deployed):** each `_bars` pass that fetches writes `<data_dir>/bars_cache.json`
  (atomic, gitignored) and a new supervisor loads it as the fallback; age still bounded by
  `BARS_STALE_MAX_DAYS`, every pass still re-fetches, corrupt file = empty fallback.
  Honest limit: tonight's restart still started from nothing (the old code never wrote the
  file), and the full universe is only requested by a model run — if the farm is dead again
  Monday 13:50 UTC, Monday's daily is blind once more and the file fills from the first good
  pass after. Universe warm-up after a restart remains the top open item.
- Session: 8 model runs, all `no_change`, zero orders. bold trailed XOM's stop to 160.50
  (16:57). Standings: twin −38.21, turtle −55.60, bold −62.61, swing −75.00, scalper −83.50,
  sniper −113.98, main −163.74. scalper's cooldown ends today; first free scans Monday.
- Noise as documented: OneDrive PermissionError ×7 (bold 2, scalper 2, twin 2, turtle 1);
  00:05 cache-fill failures on all 7.
- **DEPLOYED 22:44 UTC** via `schtasks` from Bash: end all 7 → all Ready → run all 7 → all
  Running, heartbeats 22:44:52–53, all 7 `reconnected` 22:44:55–22:45:13, bold
  `sim_stops_restored` (XOM). main came back still frozen, as expected.
- Not done, on purpose: no shadow knob changes (nothing traded); no scorer change for the DIS
  governance headline (one run, one variant); fleet-lessons gets one line on lesson 10 only.

## 2026-09-17 (Thursday night, engineer) — a quiet session; the stall guard went untested because the Gateway never restarted at 04:45 UTC — it restarted at 11:45 AM local again, mid-session; scalper spent 13 model runs inside a cooldown

- **The Gateway's auto-restart is still set to 11:45 AM local (16:45 UTC = 12:45 ET).**
  `launcher.log` opens `2026-09-17 11:45:05 IB GATEWAY RESTART … Daily auto-restart is
  enabled`; all 7 journaled `Socket disconnect` 16:45:00–58 UTC and `reconnected`
  16:46:05–58 (main's tick error was `fills_since` → ConnectionError, recovered next tick).
  Nothing at all between 22:54 UTC 09-16 and 12:20 UTC 09-17 — no disconnect at 04:45, no
  `tick_aborted`. So the owner's 09-15 and 09-16 setting changes did not stick (third day),
  the fleet loses ~1 min of quotes at 12:45 ET every session, and **TickGuard has not had its
  live test**: last night was simply calm. The wedge of 09-16 preceded that night's restart
  by 7–14 min, so its cause may recur on any night regardless of the setting.
- **Fix (deployed): the intraday scan rests while entries are paused and only core is held.**
  scalper (5-loser cooldown, `entries_paused_until 2026-09-18` inclusive; book SGOV + VTI)
  ran 13 scans 13:39–19:44 UTC, each `no_change`, each opening with "the cooldown is binding
  … no trend/spec positions, no stops to tighten"; 9 more on 09-16 after the 15:13 XLE stop.
  `risk.plan_orders` refuses every entry under the pause, so those runs could not produce an
  order. One `intraday_skipped` journal line per day names the reason; the daily run is
  untouched and a held non-core position keeps scans on (exits never gated). The good news
  inside the waste: scalper did NOT re-propose once today — it quoted the REJECTED line and
  stood down, which is lesson 17's addendum and last night's run-summary fix working.
  Tomorrow (09-18, still paused) expect one `intraday_skipped` and a daily, nothing else.
- **Fix (deployed): "is it a buy?" columns halved** — last night's dropped dampener, narrowed
  to the three buy-advice shapes that match what fired (bold, turtle, twin on the ORCL column,
  09-16). Tonight's store has nothing at gate level it touches; listicle shapes left alone.
- Session (VTI +1.1%): 7 dailies 13:50–13:52 UTC, all `no_change`, zero orders,
  zero news-gate event runs on any variant (one item ≥ 0.6 with a whitelisted symbol in the
  whole store: "Chevron CEO sounds the alarm on global oil supplies", 0.65). Books are
  core-only except bold's XOM (stop 160.36, within 3%). Standings (all-time): twin −42.70,
  turtle −61.30, bold −62.61, swing −77.87, scalper −84.13, sniper −117.40, main −167.77
  (−148.92 vs SPY). The spread is mostly core weight on a +1% day, not skill.
- Noise as documented: 30-s quote timeouts → reconnect within 5 min on turtle 12:20 UTC and
  swing + twin 21:09 UTC (per-call timeout doing its job); OneDrive PermissionError on swing
  16:07 and twin 17:32 UTC (→ 38+); scalper's 13:38 `bars_refresh` had `today: 0` (09:38 ET,
  IB has no daily bar yet — its scan window opens at 09:35; all later refreshes 13–16/16).
  No 00:05 UTC cache-fill failures last night, for once.
- **DEPLOYED 22:44 UTC** via `schtasks`: end all 7 → 0 Running → run all 7 → all Running,
  heartbeats 22:44:19–20, all 7 `reconnected` 22:44:22–23, bold `sim_stops_restored` (XOM).
- Not done, on purpose: universe warm-up after a restart (still the top quiet-night item —
  needs more than tonight's remaining budget to do with a test); no shadow knob changes
  (every variant idle or in cooldown — no results to argue from); no fleet-lessons edit
  (no new model-behaviour evidence today).

## 2026-09-16 (Wednesday night, engineer) — a whole-tick stall guard for the 04:45 UTC wedge; the model was handed its FILL and REJECTED lines and quoted the run summary instead; the Gateway and the fleet were both restarted at 16:32 local

- **The wedge, read from every log on the machine.** Heartbeats froze 04:33–04:40 UTC on all
  7 (watchdog: `down` 04:30 "last beat 10 min ago", `recovered` 04:35, `down` 04:55 "last beat
  14 min ago", `recovered` 05:10 after the owner's restart — all 7 `reconnected` 05:05:03–04,
  `sim_stops_restored` on bold/scalper/twin). `launcher.20260915.log` puts the Gateway's
  auto-restart at **23:47:58 local = 04:47:58 UTC — 7–14 min AFTER the ticks froze**, so
  "the restart tears sockets down early" is not what the logs say; the freeze came first,
  during the slow loop's 5-minute news poll (quotes for held|watched, then `_bars` for the
  day-move reference — sniper's 02:05 `no historical bars for META` shows that path fetching
  bars pre-dawn). Not one `IB request … timed out` warning on any variant, so whatever
  blocked was not inside a `_timed` wrapper, or the event loop's timer never ran. That is
  the limit of what the journal can say — the missing fact is the stack, and tonight's fix
  is built to capture it.
- **Fix (deployed): `TickGuard`, a whole-tick stall guard.** The tick marks progress at every
  stage (telegram, connect, fill_sync, each quote / bars / bars_refresh symbol, news_poll,
  news_score, reconcile, breakers, jobs, and every 2-s fill poll inside the executor); a
  daemon thread that sees no mark for the allowance — `max(3 × loop interval, 300 s)` =
  300 s in RTH, 900 s off-hours; a model run gets `timeout × attempts + 300 s` for its own
  stage — journals **`tick_aborted` with the stage, the elapsed seconds and the tick
  thread's stack** (the evidence the 09-16 journal lacked), sends one critical alert (bounded
  to 15 s so a hung network cannot keep a wedged process alive) and `os._exit(3)`s. Task
  Scheduler's restart-on-failure (verified in the task XML: Count 999, interval 1 min on
  main, 2 min on the shadows) brings a fresh process that reconnects — the owner's 05:07
  restart, automated. Worst legitimate stages measured against the 300-s floor: connect
  3 attempts ≈ 117 s, news poll 9 feeds × 20 s = 180 s, one order 90 s + retry 90 s with a
  mark every 2 s. Tests: a wedged call is aborted once with its function name in the stack;
  marks, the model allowance and disarm suppress it. First live test: **tonight 04:45 UTC**
  — if the fleet wedges again the journals will hold seven `tick_aborted` lines with stacks
  and seven restarts within 2 min; if the auto-restart passes clean, nothing fires.
- **Fix (deployed): the run summary names the engine's refusals.** scalper's XLE sim stop
  filled 15:13:46 UTC at 64.18 (−31.37, its **5th loser → cooldown to 09-18**); at 15:41,
  16:12 and 16:42 the model wrote "XLE is gone … verify in fills log / please confirm" three
  runs running, and after its 18:43 TMO proposal was `REJECTED entry TMO: entries paused
  until 2026-09-18` it wrote at 19:44 "appears not to have filled". Rebuilding the 40-entry
  tail from the journal: the `FILL SELL 19.0 XLE @ 64.1772 realized -31.37 (protective stop
  fired)` line WAS in journal_tail.md at 15:41 and the `REJECTED` line WAS there at 19:44
  (the 09-12 fix worked on its first live use) — the model quotes the run_summary line
  ("rebalance; 0/0 orders filled") and skims the rest. That line now ends with
  `; TMO REJECTED by the engine (entries paused until …)`. Fleet lesson 17 gets the addendum.
- **The Gateway and the fleet were both restarted by the owner at 16:32–16:33 local
  (21:32–21:33 UTC).** All 7 tasks show Last Run Time 16:32:47; `launcher.log` rotated and
  `jts.ini` was rewritten at 16:33; bold's `sim_stops_restored` at 21:33:19, all 7
  `connection refused` at 21:33:37, all 7 `reconnected, down_minutes: 5, failed_attempts: 1`
  at 21:38–39. Also: **the 11:45 AM auto-restart still fired today** (`launcher.log` head
  11:45:04; Socket disconnect 16:45 UTC on bold/scalper/turtle/twin, all 7 back by 16:46),
  so yesterday's 16:09 setting change had not taken; whether today's 16:33 one did is
  observable tomorrow at 16:45 UTC (should NOT fire) and tonight at 04:45 (should).
- Session (FOMC hike day, SPY −0.9%): all 7 dailies 13:51–13:53 UTC, six `no_change`; **twin
  sold XLK** (6 sh @ 185.11, −24.47) on its own written invalidation ("two closes below ma20")
  — the first model-decided exit in the fleet, done in the daily with a limit that filled at
  the open. scalper ran 12 event scans; the first four had `bars_refresh fetched 0, failed
  SGOV/VTI/XLE` (farm dead for the connection from the 00:05 fill until the 16:45 reconnect
  — 5th time; then 23/23 at 17:10). ORCL commentary fired **7 runs, 7 no_change, six days
  after the print**: "Oracle's Q1 Results Prove the AI Trade Is Going Nowhere" (0.8 — the
  09-13 `results` shape; main, scalper, sniper, swing) and "Oracle Stock Sank After Earnings
  -- Is It a Buy?" (0.7; bold, turtle, twin). Dampener candidates measured on main's 400
  stored items: `is it a buy|should you buy`, `(stocks?|chipmakers?) to buy`, `\d+ (key
  )?(metrics|reasons|things|takeaways)`, `here's why` hit 7 of 400, only the ORCL one at
  ≥ 0.7. Coded with a test (15 lines) and then **dropped to stay inside the 150-line
  budget** — top quiet-night item, next to the universe warm-up. sniper's CRM 0.65 trigger
  ("Tech's top CEOs clash … at Salesforce event") is its lower gate working; no_change.
- Noise as documented: 00:05 UTC cache fill failed its first 3 symbols on all 7; V (a new
  watchlist name) returned no bars on all 7 at 14:16–14:20; scalper and swing took a 30-s
  quote timeout at 12:19 UTC and were back at 12:24 (the 08-25 per-call timeout doing its
  job — note it DID journal, unlike the 04:33 wedge); turtle OneDrive PermissionError 12:59
  UTC → 36+. Standings: twin −69.28, bold −73.58, scalper −87.94, swing −97.22, turtle
  −100.00, sniper −140.62, main −194.88 (−65.32 vs SPY). main core-only, its 3-loser
  cooldown expired today; turtle's NVDA cooldown to 09-17; scalper's to 09-18.
- **DEPLOYED 22:53 UTC** via `schtasks` from Bash (PowerShell denied again): stop → all 7
  Ready → start → all 7 Running, heartbeats within 1 s, all 7 `reconnected` by 22:53:33,
  `sim_stops_restored` on bold (XOM — the only shadow with an active position tonight). The
  second fleet restart of the day (the owner's was 21:32 UTC), so the bars fallback held
  nothing the next news poll cannot refetch and no outage counter was mid-flight. The fleet
  runs HEAD; the guard is armed for tonight's 04:45 UTC auto-restart.

## 2026-09-16 (owner session, 05:05 UTC) — URGENT for tonight's engineer: ALL 7 ticks wedged at the Gateway's 04:45 UTC auto-restart despite the 08-25 per-call timeouts

- All 7 heartbeats froze between 04:33 and 04:40 UTC (main 04:40:48, twin 04:33:41 — the
  Gateway's nightly auto-restart is 11:45 PM local = 04:45 UTC, and it evidently starts
  tearing sockets down minutes early). Wedge held 24+ min with NO error journaled — the
  08-25 RequestTimeout fix does not cover whatever call these ticks were inside. Owner
  restarted all 7 tasks 05:07 UTC. Find the uncovered blocking path (candidates: the
  connect/handshake itself, reqAccountUpdates/portfolio subscription replays on a
  half-dead session, or anything awaited without asyncio.wait_for outside broker.*
  wrappers) and put a hard deadline on the WHOLE tick, not just per-call — a tick that
  exceeds, say, 3× tick interval should abort itself, journal `tick_aborted`, and let the
  next tick reconnect. Evidence: journal shows watchdog down 04:30→recovered 04:35→down
  04:55 with zero broker/error lines in between; same shape as 08-25 but per-call
  timeouts were live this time.
- Context: the owner moved the Gateway auto-restart from 11:45 AM (the midday 12:45 ET
  disconnect, now gone) to 11:45 PM local. The API connection did NOT need a re-login
  after tonight's auto-restart (no LOGGED OUT handshake error, unlike 09-14's) — whether
  that holds nightly or only until the weekly Sunday re-auth remains to be seen; watch
  04:40–05:00 UTC journals the next few nights.

## 2026-09-15 (Tuesday night, engineer) — two sessions, three outages: the PC rebooted mid-session Monday, the Gateway sat logged out through Tuesday's open; a drone maker fired six runs on CAT; shadow stops were filling pre-market

- **No engineer entry for Monday night: the pass did not run** (PC off/rebooting — see
  below). This entry covers 09-14 and 09-15.
- **Outage 1, closed: the Gateway the owner started Sunday 23:37 local ended the 48 h
  Friday-night outage** — all 7 `reconnected, down_minutes: 2900, failed_attempts: 546` at
  04:39 UTC Monday, 5 h before the open. Monday then opened as lesson 6 predicts: main's NVDA
  GTC stop fired at 09:30:12 ET at 211.18 (−49.32) and JPM's at 13:42 ET (−9.72) → main's
  3-losing-trades cooldown to 09-16; sniper's NVDA sim stop (−28.70) put it in the same
  cooldown; swing's XLK stop −2.39. All 7 weeklies + dailies fired 13:52–14:04 UTC, every
  one `no_change`. Realized Monday: main −59.04, all-time −171.42 → −184.46 tonight.
- **Outage 2, new shape: the PC rebooted at 14:17:51 local Monday (19:17 UTC, 15:17 ET)**,
  43 min before the close. Every journal stops at 19:08–19:13 UTC and resumes at 01:37 UTC
  (20:37 local) when the tasks came back — so the close, the 16:20 report (it fired at 01:44
  UTC instead) and the last 43 min of protective checks were unwatched, and the restart
  `sim_stops_restored` the shadows' stops from book.json (bold XOM, twin XLK; the 09-08 fix
  doing its job). No watchdog line — it sleeps with the PC, same as 09-09. The report did
  NOT lead with MISSED because the protective job had run until 15:1x ET — a partial-day
  gap, exempt by design. The 6 h 20 min between boot and the tasks starting is unexplained
  from here (logon-triggered tasks + nobody logged in is the obvious reading).
- **Outage 3, the old shape: the Gateway logged itself out at 21:09 local Monday and
  stayed out until the owner restarted it at 11:20 local Tuesday.** After the reboot the
  owner started the Gateway at 20:38:59 local (`launcher.20260914.log`), all 7 reconnected
  01:43 UTC, then at 02:09 UTC the socket dropped and every variant journaled the
  "port accepted but the API handshake timed out — LOGGED OUT" text, then **13 hourly
  `still_down` lines each (03:22 → 15:32 UTC, failed_attempts 11 → 145)** — the 09-12 change's
  first live use, and exactly the audit trail the 18-hour hole on 09-12 lacked. `launcher.log`
  shows `IB GATEWAY RESTART` at 11:20:32 local; all 7 `reconnected, down_minutes: 845–847,
  failed_attempts: 163–164` at 16:21 UTC (12:21 ET). **Tuesday's fleet missed the open by
  2 h 51 min**: the dailies fired at 12:23–12:28 ET (slots unmarked, as read on 09-13), main
  and 5 shadows `no_change`; scalper's first event run bought XLE 19 sh @ 65.72 (supply-shock
  catalyst, sector ETF for fill reliability — lesson 5 applied) and its 1.5×ATR trail
  ratcheted the stop seven times in 1 h 45 (63.22 → 64.20). The 11:45 local auto-restart hit
  again at 16:45 UTC (back in 1 min). `jts.ini` was rewritten at 16:09 local today; whether
  the auto-restart time moved is only observable tomorrow at 11:45 local (16:45 UTC).
- **BUG (fixed, deployed): the scorer matched tickers case-insensitively.** "AeroVironment
  Rises 6% as Post-Earnings Recovery Outpaces Drone Group; Ondas Ticks Up, **Red Cat** Barely
  Budges" (0.7, CAT −4% on the day) fired main, bold, scalper, swing, turtle and twin at
  17:11–17:18 UTC Monday — six runs on a drone maker; main's triage called it "a ticker
  collision (Red Cat → CAT)" outright. Same rule tagged "cost of war" as COST (3 of the 400
  stored items tonight) and would tag "Jack Ma" as MA and "Apple v. Samsung" as V. The
  ticker now has to appear in upper case; company aliases stay case-blind, and "meta" is
  added as an alias because headlines call the company Meta (without it four real META
  items lost their tag in the measurement). Exactly 3 of 400 stored items change, all the
  Pentagon "cost" ones. Regression test.
- **BUG (fixed, deployed): shadow sim stops fired on pre-market quotes.** sniper's NVDA stop
  filled at **08:18 UTC (04:18 ET) at 214.81** and swing's XLK at 08:43 UTC — quotes the
  news poll pulls around the clock — while main's real GTC stop on the same NVDA fired at
  the 09:30 open at 211.18. IBKR never triggers a stop outside RTH unless `outsideRth` is
  set, and the engine never sets it, so the sims were exiting at prices the broker would
  not have acted on: sniper's exit was $3.63/sh (≈$7) kinder than main's on the same gap,
  and every future overnight gap would have flattered the A/B the same way. The STP branch
  now rests while `is_rth(sim.now)` is false (an `outside_rth` order still fires). Test.
- **The stale-bars fallback held, but it is only as wide as the last successful pass.** At
  13:47 UTC Monday the history farm was dead for this connection again (AAPL/ABBV/AMZN
  failed, 47 skipped; scalper's `bars_refresh` `fetched 0` until 18:11 UTC — after the 16:45
  reconnect, the 4th time: 09-08, 09-11, 09-14 and the 12:45 restart is the only healer).
  The dailies got 7 rows and the weeklies 12 of ~50 — those are the held + watchlist bars
  the weekend news polls had cached, refetched fresh at 04:40 UTC Monday (hence no
  `bars_stale_served` line; nothing stale was served). The universe is only ever fetched by
  a weekly, so after the 09-11 restart there was no universe to fall back on. Every variant
  wrote a version of "under-deployment persists because market.json only carries held/
  watched rows" — for the DAILY that is by design (held | core | watchlist); for Monday's
  weekly it was the dead farm. Written down, not coded (two changes already tonight):
  **warm the universe cache in the 16:20 report job**, when the farm is reliably alive, so
  the next morning's fallback covers the whole whitelist. Top quiet-night candidate.
- **Event gate, Monday: 20 runs on three headlines, 20 no_change.** "Broadcom vs. Nvidia: 3
  Key Metrics Point to the Stronger AI Chipmaker to Buy After Earnings" (0.7) fired all 7
  (13:44–13:59 UTC) and "Broadcom Just Named Its Next Customer to Pass Google: Anthropic.
  Here's Why That Matters More Than the Earnings Beat." (0.7) fired all 7 (14:41–15:01) —
  both listicle/explainer commentary on the 12-day-old AVGO print — plus the Red Cat six.
  Dampener candidates written down: `\d+ key (metrics|reasons|things)`, `here's why`,
  `(stock|chipmaker) to buy`. Tuesday: sniper took "How a Costco partner's bankruptcy could
  benefit its biggest rival" at **0.95** (bankruptcy pattern on a Soft rival piece; one
  instance, noted) and the AVGO CEO reply at 0.65.
- Fleet after Tuesday's close: bold −29.47, scalper −50.44, twin −65.21, turtle −85.10,
  swing −90.53, sniper −131.68, main −184.46 (−102.47 vs SPY). Main is core-only (SGOV, VTI)
  with entries paused to 09-16. OneDrive PermissionError ×4 (main 15:37 + 17:05, scalper
  19:08, sniper 12:49 UTC Monday) → 35+.
- **DEPLOYED 22:50 UTC** via `schtasks` from Bash (PowerShell denied again): stop → all 7
  Ready → start → all 7 Running, heartbeats within 1 s, all 7 `reconnected` by 22:51:04,
  `sim_stops_restored` on the three shadows with active positions (bold XOM, scalper XLE,
  twin XLK). Restarting tonight was cheap for once: the Gateway is up, the stale fallback
  held nothing beyond what the next news poll refetches, and no outage counter was
  mid-flight. The fleet runs HEAD. sniper logged one `no historical bars for QQQ` at
  22:51:34 — the farm is flaky again tonight; watch tomorrow's 09:35 ET.

## 2026-09-13 (Sunday night, engineer) — the Gateway is still dead after 42 h; Monday's open is 11 h away; the scorer finally reads a print that does not say "earnings"

- **ONGOING at 22:40 UTC: IB Gateway has been gone since 04:13 UTC Saturday — 42 h, no
  self-heal, no restart attempt.** Port 4002 refuses (`SYN_SENT` only), `ibgateway.exe` is
  not running, and every file under `C:\Jts\ibgateway\1050` is stamped 23:13 Friday local
  (the clean-exit flush) — `launcher.log` has not rotated since the 11:45 Friday restart, so
  nothing has tried. The 08-26 and 09-07 process deaths healed in ~4 h; this one is 10× that
  and counting. The 7 supervisors are healthy (heartbeats 22:35–22:40 UTC, all tasks
  Running, watchdog `{}`) and `_ensure_connected` has been failing every tick, so the
  hourly "broker still unreachable" Telegram reminder should be on its ~42nd send — but the
  journals cannot confirm it (last night's `still_down` line is committed, not deployed):
  all 7 journals hold exactly one `connect` error each at 04:18–04:22 UTC Saturday and
  nothing since except main's `engineer` verdict line. **If nobody starts and logs into the
  Gateway before Monday 09:30 ET the fleet is blind at the open.** What the code does then
  (read tonight, not guessed): `tick()` returns at `_ensure_connected()` before any job, so
  the weekly/daily slots stay UNMARKED and fire at the first connected tick inside the
  order window (≤ 15:30 ET); the 16:05 report fires at the first connected tick after it
  and leads with the MISSED banner (09-10 fix) because `last_protective_ts` is Friday
  15:51 ET; the news poll has been dead since 04:11 UTC Saturday too (newest stored item),
  so the event gate reopens with whatever the first poll fetches. main's GTC stops at IBKR
  guard its 4 positions (lesson 6); the shadow sims' stops (bold XOM, sniper NVDA,
  swing/twin XLK) cannot fire while the process is down.
- **Monday's bars fallback is intact IF nothing restarts the fleet before the open.** The
  09-11 22:52 deploy emptied every cache; the 00:05 UTC Saturday fill ran while the Gateway
  was still alive and left NO `no historical bars` line on any variant (first silent fill in
  weeks), so each supervisor holds Friday's bars in `_bars_cache` → rolled into
  `_bars_stale` at 00:00 UTC Sunday and again (merge, not clobber — checked the rollover
  code) at 00:00 UTC Monday; Friday's last bar 09-11 ≥ Monday's 5-day floor 09-09. A
  restart tonight would throw that away and a dead history farm at 09:35 ET would mean
  `market.json = {}` again. So: **NOT deployed, third night running**, same reasons as
  last night plus this one; the three undeployed changes (still_down journal line,
  rejections in journal_tail, tonight's scorer patterns) first matter after the next
  restart, which should happen on a night when the Gateway is up and the fill can refill.
- **Fix: the scorer reads a print that is not headlined "earnings" (the 09-11 gap, written
  down twice).** Measured on main's live store tonight: "Oracle beats on top and bottom
  lines as cloud revenue surges" (Yahoo 20:22 UTC 09-10 — THE print headline) scored 0.00;
  so did "Oracle Posts Higher Profit, Revenue on Continued Cloud Infrastructure Strength"
  and "Oracle Stock Jumps as AI Demand Drives Cloud Revenues Higher"; "Adobe posts record
  quarter, lifts guidance" got its 0.75 only from "lifts guidance". Add the three 09-11
  morning reaction headlines from Friday's entry (all 0.00) and the ORCL print was invisible
  to the gate from every angle — even with a working tape the −7% could not have fired,
  because the only ORCL items at ≥ 0.7 were the two that happened to say "earnings". New
  0.70 shapes: `(posts|reports) <number|record|higher|lower|…> … (revenue|profit|sales|
  quarter|loss|income|growth|eps)`, `beats on top and bottom`, and `<quarterly|fiscal|solid|
  strong|record|…> results` (quotes tolerated: "'Solid' Results"). The qualifier is
  required on purpose so "Acquisition Reports" and "reports say iPhone demand is soft" stay
  put. Across the 400 stored items exactly 8 change, all real prints (SNOW, CRDO, MDB, RVLV,
  ADBE, ORCL ×2, DSGX). Second half: `futures (rise|fall|slip|…)` is dampened — the 09-11
  index preview fired scalper and sniper 8 min before the close. Regression test pins the
  six prints, three non-prints and the futures title. "Oracle Weakens Bear Case With
  Broader AI Customer Base and $664 Billion Backlog" stays at 0.00 — no pattern short of
  "backlog" would be honest, and that word is a preview hook as often as a print one.
- **Ellison's $7.5 B 10b5-1 sale plan scored 0.00** (CNBC 01:36 UTC Saturday, the last
  item the store fetched before the Gateway died). ~1% of ORCL's cap, Soft by lesson 16's
  denominator, and Monday's daily sees it in the digest only if the next poll re-lists it
  (36 h window ends ~13:36 UTC Monday). Not a scorer change: an insider-sale pattern with
  no denominator would fire on every Form 4 headline. Noted so Monday's ORCL read is not a
  surprise.
- No session (Sunday), no decisions, no orders, no OneDrive errors (nothing ran); standings
  unchanged since Friday: twin −17.31, swing −39.17, bold −42.63, turtle −49.90, scalper
  −51.57, sniper −102.45, main −121.17. News `seen` health: 0–9/a/b prefixes now hold ~30
  ids each and c–f ~1200 each — the legacy sorted tail aging out exactly as the 09-11 fix
  predicted. scalper's 4-loser cooldown expires 09-14; the first refusal after that will be
  the rejection-tail change's first live effect — once deployed.

## 2026-09-12 (Saturday night, engineer) — the Gateway exited Friday night and stayed dead 18 h; the 12:45 ET disconnect is the Gateway's own auto-restart clock, set to 11:45 AM local

- **ONGOING at 22:40 UTC: IB Gateway has been gone since 04:13 UTC Saturday (23:13 Friday
  local, America/Bogota).** All 7 variants logged `Socket disconnect` at 04:13–04:17 UTC,
  then exactly one `connect` error each at 04:18–04:22 — "connection refused — no Gateway
  process is listening; IB Gateway needs to be started" — and then NOTHING for 18 hours.
  `ibgateway.exe` is not in the task list and port 4002 is not listening. The Gateway's own
  files say it exited on purpose rather than crashed: `jts.ini`, `xmlopt.dat` and `Fri.rul`
  were all written at 23:13 local (the settings flush on exit), there is no application-error
  event, the PC has not rebooted since 09-09 08:35, and `launcher.log` has no entry after the
  11:45 restart — so nothing has tried to bring it back. 23:13 local is 00:13 ET Saturday,
  inside IB's Friday-night maintenance window. The two earlier process deaths (08-26
  22:55→02:59 UTC, 09-07 01:32→04:07 UTC) self-healed in ~4 h with a launcher restart on
  record (09-06 23:07 local); this one has not. **If nobody starts and logs into the
  Gateway before Monday 09:30 ET the fleet is blind at the open** — main's GTC stops at IBKR
  stand guard as on 08-24 (lesson 6), the shadow sims' stops do not. The 7 supervisors are
  fine (heartbeats fresh at 22:38 UTC, all tasks Running, watchdog state `{}` = healthy by
  its heartbeat-only definition) and have been retrying every tick; with `dedupe_minutes:
  30` the hourly "broker still unreachable" reminders should have reached Telegram ~18
  times — but see the next bullet.
- **Fix: the hourly outage reminder now leaves a journal line.** The 18-hour hole is the
  09-06 watchdog problem again: the reminder went to Telegram only, so "was the owner told,
  how many attempts, what did the latest failure say" is unanswerable from the journal after
  the fact. One `broker` / `still_down` line per hourly reminder (down_minutes,
  failed_attempts, err); the hysteresis itself is unchanged. Test extends the outage case.
- **The 12:45 ET disconnect is solved: it is the Gateway's daily auto-restart, set to 11:45
  AM local.** `jts.ini` has `AutoRestart=1`, `TimeZone=America/Bogota` (UTC−5), and
  `launcher.log` says "Daily auto-restart is enabled" and rotates at exactly 11:45 local
  every day (`launcher.20260905…0911.log` all stamped 11:45; 11:45 Bogota = 12:45 ET =
  16:45 UTC, the minute every variant has reconnected since 09-03). Before 09-03 the same
  event was the "04:45 UTC nightly blip" = 23:45 local, and the Gateway's `.trd` files from
  before 09-03 (Sat.trd 08-22, Mon.trd 09-01) are stamped 23:45. So on 09-03 the restart time moved from 11:45 PM to 11:45 AM — an AM/PM
  flip in the Gateway's Configure → Lock and Exit dialog is the whole story, exactly the
  09-08 suspicion. Owner fix (one click): set Auto restart back to 11:45 PM local (or any
  time between 17:15 ET and 09:00 ET); that takes the daily blip out of RTH. Note it will
  not revive a Gateway that has exited — today's outage needs a manual start either way.
- **Fix (the 09-10 top quiet-night item): the model now sees the engine's rejections.**
  scalper proposed XOM/TSLA/AAPL through its 4-loser cooldown five times on 09-10/11 and
  wrote "0/0 filled, no cause visible to me" six runs running; `paused_sleeves` was in
  portfolio.json but the `rejection` line ("entries paused until 2026-09-14: 4 losing trades
  in a row (cooldown)") was journaled and never shown. `journal_tail.md` now carries
  rejection entries as `REJECTED entry AAPL: <reason> (the engine refused this — it was never
  sent to the broker; do not re-propose it until the reason has cleared)` next to the
  decision that caused them. Regression test pauses a sleeve, proposes, checks the next
  bundle. First live effect: whenever the next refusal happens (scalper's cooldown itself
  expires 09-14).
- **Last night's news-store fix has healed on all 7**: `seen` holds 5000 ids across every
  hex prefix and 400 of 400 stored items are in it (was 81/400 with b–f only at 22:40 UTC
  yesterday). The bars fallback has had no session to prove itself; its first test is the
  Monday 09:50 daily — and only if the Gateway is up.
- No session (Saturday), no decisions, no orders; standings unchanged from Friday: twin
  −17.31, swing −39.17, bold −42.63, turtle −49.90, scalper −51.57, sniper −102.45, main
  −121.17. OneDrive PermissionError ×0.
- **NOT deployed, on purpose.** Both changes are picked up by the next supervisor restart;
  restarting tonight would (a) wipe the in-memory bars cache and its `_bars_stale`
  fallback, which — with the Gateway dead — nothing could refill before Monday's open, so a
  dead farm at 09:35 ET would again mean `market.json = {}`; and (b) reset the seven
  outage counters mid-outage, firing seven fresh "broker connection down" alerts and losing
  the eventual `down_minutes` summary. Neither change buys anything before Monday.

## 2026-09-11 (Friday night, engineer) — the whole fleet decided blind on ORCL's print morning: an empty bars cache and a news store that forgot 11/16 of what it had seen

- **BUG (fixed, deployed): every daily today ran on `market.json = {}`.** All 7 dailies
  (13:53–14:07 UTC) and scalper's first seven event runs (13:43–16:44) wrote the same
  sentence — "market.json is EMPTY ({}), the tape is broken, not quiet (lesson 10)" — on the
  morning after the ORCL print. Mechanism: `_bars` wipes its cache at the UTC day rollover
  (00:00 UTC = 20:00 ET) and this connection's history requests failed from the 00:05 fill
  until the 12:45 ET reconnect (main: JPM/NVDA 13:35, AAPL 13:52, ORCL 13:58; scalper's
  `bars_refresh` said `failed: [VTI, NVDA, QQQ], fetched 0` six runs straight, then
  `fetched 20, today 20` at 17:12 — the 09-08 "sticky per connection" reading, not the
  09-10 "IB serves nothing for 35 min" one; both are real). Every pass tripped the 3-failure
  breaker over an EMPTY cache, so the 08-26 rule ("degrade to what we already know, never to
  nothing") held everywhere except at the day boundary, where we know everything from
  yesterday and threw it away. Three consequences, all visible in the journals: 14 blind
  model runs; no ATR for the protective trail until 16:47 (NVDA/XLK trails ratcheted the
  minute the reconnect returned bars); and no previous-close reference for `_day_moves`, so
  the event gate could not see ORCL's −7% and never fired on it. Fix: at rollover the
  previous day's bars are kept as a fallback (≤ 5 days old), served when the fetch fails
  or the breaker trips, still re-fetched every pass, journaled once per distinct set as
  `bars_stale_served`. Yesterday's bars are what a normal 09:50 daily sees anyway.
- **BUG (fixed, deployed): the news store's `seen` set kept the 5000 lexicographically
  LARGEST ids.** `save()` did `sorted(seen)[-5000:]`, so once 5000 ids existed every id
  hashing below ~'b' (11 of 16 prefixes) was forgotten on each save and came back as "new"
  at the next 5-minute poll. Measured tonight on main: `seen` holds only b–f prefixes; 81
  of the 400 stored items are in `seen`; 262 of 400 are re-fetches of items published 09-10
  (fetched 18:08 today); the oldest stored item was fetched 15:40 UTC. The "36 h" digest
  window was ~7 h of feed time, so CNBC's 13:34 and MarketWatch's 12:52 ORCL print
  headlines were gone from the store before the reconnect gave the gate its moves back.
  Identical on all six shadows. Since when: `seen` crossed 5000 sometime in early September
  (≈150–250 genuine items/day), so roughly a week — the "two links, one story" and "same
  story, fresh link" patterns of 09-01/09-04 predate it and were real. Fix: `seen` is
  persisted in insertion order and truncated from the front; the legacy sorted list ages
  out on its own. Neither bug placed or blocked an order — zero orders and zero fills
  fleet-wide today — but together they made the fleet's first Hard print in a fortnight
  invisible to both the daily and the event path.
- **Scorer gap, written down, not coded (two code changes already tonight):** ORCL fell 7–8%
  after a beat, and the reaction headlines scored **0.00**: "Oracle posts 30% revenue growth
  fueled by AI cloud demand as debt hits $125 billion", "Why Oracle's 'Solid' Results Aren't
  Giving Its Stock A Big Boost", "Oracle Weakens Bear Case With Broader AI Customer Base and
  $664 Billion Backlog". The earnings pattern needs the literal "earnings", "quarterly
  results" or "beats/misses estimates"; "posts N% revenue growth" and bare "results" miss.
  Meanwhile the 09-10 09:30 futures preview "U.S. Futures Rise as Markets Watch Iran
  Conflict, Oracle and Adobe Earnings" (first listed by the feed at 19:27 UTC today — a
  genuine late listing, NOT the seen-bug) scored 0.7 and fired scalper (19:52) and sniper
  (19:48) eight minutes before the close. Candidates: `(posts|reports) …
  (revenue|profit|sales|growth)` and `(quarterly|fiscal|q[1-4]|solid|strong|record) results`
  at 0.7; dampen `futures (rise|fall|slip|climb) as markets watch` and `earnings on tap`.
- **ADBE cost 18 event runs, all no_change**: "Adobe (ADBE) Q3 2026 Earnings Call Transcript"
  (0.7, +2%) fired all 7 at 17:13–17:47, "Adobe Just Reported Earnings. Here's What
  Investors Need to Know." (0.7) fired all 7 at 18:06–18:52, sniper took "Adobe Pulls Back,
  Then Recovers …" (0.65) and the futures preview hit two. Every triage agreed: beat, Q4
  guide at/below consensus, CEO handoff + interim CFO, −5% after hours → gap down 241.85 →
  recovered flat. A transcript re-post and a "here's what to know" explainer of a print that
  broke last night are lesson 13 in new clothes; deliberately not dampened tonight because
  the day-after-print reaction IS the tradable moment (lesson 12) and today the dailies that
  should have owned it were blind.
- **scalper proposed AAPL spec through its cooldown twice more** (17:15 and 18:45 UTC, both
  `rejection: entries paused until 2026-09-14: 4 losing trades in a row`) and again wrote
  "0/0 filled, no AAPL in portfolio" without reading `paused_sleeves`. Second day, five
  refusals total; the "echo today's rejection lines into the bundle" candidate from 09-10
  is now the top quiet-night item.
- Session notes: green CPI day (SPY +1.1%), main +30.09 → −121.17 all-time, −124.38 vs SPY.
  Standings: twin −17.31, swing −39.17, bold −42.63, turtle −49.90, scalper −51.57,
  sniper −102.45, main −121.17. sniper's daily hit the 900-s model timeout at 14:06 (retry
  answered in 62 s, daily landed 10:07 ET — third timeout in the series, one per ~4
  sessions). The 12:45 ET disconnect fired on all 7 (16:45–16:46 UTC, back in ~1 min;
  Gateway auto-restart check still open). The 17:00 ET reset passed silently (sniper's AAPL
  `bars_recovered` 21:07 was the only line). OneDrive PermissionError ×0 — first clean day
  since the count started. Fleet digest for the week of 09-07 written at 20:24 UTC.
- **DEPLOYED 22:52 UTC** via `schtasks` from Bash (PowerShell denied again): stop → all 7
  Ready → start → all 7 Running, heartbeats within 1 s, `sim_stops_restored` on the four
  shadows with active positions (bold XOM, sniper NVDA, swing/twin XLK). The fleet runs
  HEAD. The restart emptied the bars cache, so the fallback for Monday is whatever the
  weekend passes fetch (held + watched every poll; Friday's bars are 3 days old on Monday,
  inside the 5-day bound). Real test Monday 09:35 ET: if the farm is dead again the journals
  should show `bars_stale_served` and the dailies a populated market.json with
  `day_change: null` instead of `{}`; and `seen` should hold 0–9/a prefixes within an hour.

## 2026-09-10 (Thursday night, engineer) — a full session back; the intraday tape fills at ~10:00 ET on its own; the same three headline shapes cost 20 runs

- **The fleet ran the whole session** after Tuesday's dark day: all 7 dailies at 13:51–13:54
  UTC, all 7 heartbeats fresh at 22:37–22:40 UTC, every decision `no_change` except
  scalper's three entry proposals (XOM 13:54, TSLA 15:09, AAPL 15:41 UTC), each rejected by
  its 4-loser cooldown (to 09-14). The model then wrote "0/0 fills with no cause visible to
  me" in six consecutive runs — `paused_sleeves` IS in portfolio.json, it just did not look.
  Written down, not coded: the day's `rejection` lines could be surfaced in the bundle
  verbatim so a refused entry reads as "refused: cooldown" instead of "expired?".
- **The `bars_refresh` line answered the null-tape question on day one.** scalper's first two
  event runs (13:39 and 13:45 UTC) logged `today: 0, stale: 12, failed: []`; from 14:08 UTC
  (10:08 ET) onward every run logged `today: N == fetched`, `failed: []`, all day — with NO
  reconnect in between. So the refetch works and the farm was healthy; IB simply does not
  serve today's partial daily bar in the first ~30–40 min of the session. The 09-08 "tape
  populates only after the 12:45 reconnect" reading was a coincidence of the days sampled.
  Design consequence: the continuation playbook is blind by construction until ~10:05 ET,
  which is inside its own "avoid first-30-min whipsaw" rule anyway. Nothing to fix; the
  first two scans of the day are the cost of knowing that.
- **The 12:45 ET disconnect fired again on all 7** (16:45–16:46 UTC, back in ~1 min; main
  took it as a `tick` error inside `sync_external_fills`, one line). The 17:00 ET reset hit
  scalper/sniper/turtle at 21:08 UTC (back 21:13), twin had a lone 30-s timeout at 12:19 UTC.
  All hysteresis-quiet. Owner check on the Gateway auto-restart time still stands.
- **Fix (owner's open item from this morning): the first report after an unwatched session
  now leads with the outage.** The 02:00 UTC report for Tue 09-09 read "P&L today: −18.62 $"
  because `day_start_equity` was anchored at the 01:57 restart. The protective job runs
  every 15 min of RTH and its timestamp is persisted, so "no protective check since before
  today's open" = nobody watched the session (PC off, supervisor dead, or Gateway
  unreachable all day as on 08-24). The report now opens with `⚠️ MISSED Tue Sep 09
  ENTIRELY … last check Mon Sep 08 15:5x EDT … 'P&L today' is measured from the restart`.
  Fresh installs (no check ever) are exempt; partial-day outages are left to the connect
  alerts. Regression test replays the 22:00 ET report.
- **Fix: four more preview/roundup title shapes are halved.** Today's 23 event runs
  fleet-wide were all `no_change`, and 18 of them came from three items: "Oracle options are
  doing something curious heading into earnings" (0.7, all 7), CNBC's daily "… and more in
  Morning Squawk" roundup (0.8 on AAPL +2%, all 7 — it publishes every morning and names
  whatever moved), and "… Oracle Eases Into Earnings …" (scalper). With 09-08's "Before You
  Chase … Take a Closer Look at Its Latest Earnings Beat" (5 runs) that is 20 runs on four
  shapes, 20 no_change. Patterns: "<heading|eases|…> into earnings", "morning squawk",
  "before you chase/buy", "take a closer look". Deliberately NOT dampened: "Oracle Reports
  Earnings as It Transforms Itself…" (present-tense "reports" is also how the real print is
  headlined, and ORCL prints tonight) and the TSLA/SpaceX merger-speculation feature
  ("What It May Mean…", 4 runs) — "may mean" is too generic a hook. Test pins the four real
  headlines plus two ORCL print/reaction controls that must keep 0.7+.
- fleet-lessons housekeeping: this morning's owner session and the 09-08 engineer entry had
  both written a lesson 16 (materiality vs market cap); merged into one, numbering 16–18
  is clean again.
- Red day (SPY −0.7%, NVDA −2.4%): main −43.43 (all-time −148.74, −68.84 vs SPY). All-time:
  scalper −54.91, twin −56.38, bold −61.86, swing −75.77, turtle −83.20, sniper −122.67,
  main −148.74. Realized today: sniper XLF stop −22.45, turtle NVDA breakeven −2.06,
  scalper UNH time-stop −13.84. OneDrive PermissionError ×3 (sniper 11:26, twin 14:31 and
  15:51 UTC) → 31+. ORCL prints after tonight's close; every variant has it flagged for
  tomorrow's daily per lesson 12 — tomorrow's reaction headlines are NOT dampened.
- **DEPLOYED 22:46 UTC** via `schtasks` from Bash (PowerShell denied again): stop → all 7
  Ready → start → all 7 Running, heartbeats within 1 s, `sim_stops_restored` on the four
  shadows that hold active positions (scalper and turtle are core-only tonight). The fleet
  runs HEAD; the banner first matters after the next outage, the dampeners tomorrow morning
  when Morning Squawk publishes.

## 2026-09-10 (owner session) — the fleet was dark the whole of Tue Sep 9; loss-streak cooldown proven in the engine; a $132M headline scored like a $13B one

- **Sep 9 was a full-fleet outage and nobody was told.** Journals (main AND all 6 shadows)
  are empty from 09-08 22:55 UTC (engineer) to 09-10 01:51 UTC — the PC was off/asleep for
  ~27 h spanning an entire trading session. The 01:51 entry is `connect: connection refused;
  IB Gateway needs to be started`; Gateway came up at 01:57 and the (late) EOD report went
  out 02:00. No watchdog alert fired because the watchdog sleeps with the PC — by design it
  can only catch a dead supervisor on a live machine, and there is no code fix for a machine
  that is off. What held: main's GTC stops live at IBKR and were armed the whole day
  (lesson 6 is the whole defence in this scenario). What did NOT hold: shadow sim stops
  cannot fire while the process is down — accepted for sim money, unacceptable shape for
  live. Consequences: (a) the missed-day case must be LOUD — first report after a gap that
  spans a trading session should lead with "MISSED Tue Sep 9 entirely (PC off)", not
  present a normal-looking P&L line; *open: engineer adds a journal-gap banner to the first
  daily report after an outage.* (b) For live money the PC-off failure mode argues for an
  always-on host or at minimum BIOS auto-power-on + scheduled wake. *Open: Benjamin decides
  before go-live; this is now on the go-live checklist in spirit even though the gate can't
  measure it.*
- **The loss-streak breaker passed its first live test, twice.** scalper hit 3 losers in a
  row on 09-08 (cooldown to 09-10), proposed a TSLA add anyway — engine refused. Hit its
  4th on 09-10 (UNH time-stop −13.84, cooldown to 09-14), proposed XOM in the daily —
  `rejection: entries paused until 2026-09-14: 4 losing trades in a row (cooldown)`. The
  model keeps trying to trade through its own cooldown; the engine is what actually stops
  it. That is the architecture working exactly as designed — and evidence the scalper
  mandate itself ("buy and sell all the time") is fee-and-whipsaw drag, consistent with the
  backtest (fleet lesson 3): its four losers were all no-catalyst intraday entries.
- **Materiality scoring has no denominator.** "Novartis India acquires Pfizer brands for
  $132m" scored 0.8 (Hard M&A pattern) and fired an event run; the fetch showed it was an
  India-trademark sale ~0.05% of PFE's market cap. Model triaged it correctly (no_change) —
  but the gate spent a run on it. Skill now says: divide the headline's dollar figure by
  market cap before calling it Hard (fleet lesson 16). *Open (nice-to-have): scorer could
  damp "$Nm" figures that are tiny vs a cached mega-cap list.*
- **turtle's by-the-book breakeven still got tagged.** Moved NVDA to breakeven 222.25 on
  09-08 only after +1R had held two sessions (lesson 14's own rule) and was stopped 09-10
  on a routine −0.5% morning dip for −$2.06, while main/swing sit in the same name on
  original stops. Not a mistake — flat exit, capital intact — but the honest framing is:
  breakeven converts the position into a free exit option and the first shakeout WILL
  exercise it. Evidence appended to lesson 14.
- **twin paid 0.95% of slippage to a stale plan price**: XLK planned at 187.28 (Mon-night
  quote), filled 189.07 at Tuesday's open inside the ask+35bps collar. The collar did its
  job (it filled; LLY never did), but morning gap risk on overnight-planned entries is
  ~1% on an ETF — size and stop math should use the fill, not the plan (they do; noted so
  nobody "optimizes" the collar tighter and reintroduces the LLY failure).
- Housekeeping observed: sniper's XLF GTC-style sim stop fired (−22.45) and NVDA/XLF exits
  journaled cleanly; main dropped risk multiplier 0.8 → 0.6 on the softer tape (VIX 17.7,
  SPY under ma20) — defensive posture, no action needed. ORCL prints tonight (09-10 AMC);
  the whole fleet has it flagged for tomorrow's daily per lesson 12.

## 2026-09-08 (Tuesday night, engineer) — the weekly fix held on all 7; a restart had been silently disarming shadow stops since 08-25

- **Last night's weekly-window fix passed its first live test.** All 7 rolled-forward
  weeklies fired 13:48–13:51 UTC (09:48–09:51 ET, inside the order window) with real equity
  in the plan line — on 08-25 the same setup fired at 09:30 and planned "outside RTH trade
  window" seven times. twin used its weekly to enter XLK (6 sh @ 189.07, stop 178 → trailed
  to 179.95), its first trend position in two weeks; turtle moved NVDA to breakeven 222.25
  after +1R held two sessions (lesson 14 applied by the book, not against it). bold's weekly
  hit the 1800-s model timeout (first on a weekly; scalper's 08-27 was 900 s), the retry
  answered in 163 s and the weekly landed at 10:20 ET — one slot, 30 min, once.
- **BUG (fixed, deployed): a fleet restart forgot every resting stop in the shadow sims.**
  Stops are placed only on entry, on a trail tighten, or after a partial sell; the sim is
  in-memory; `restore_sim_state` re-owned positions but NOT their stops, and the shadow.py
  comment claiming "the protective loop re-arms them" was simply false. After last night's
  22:44 UTC restart, scalper's SPY breakeven stop (769.46), sniper's XLF (56.98) and
  swing's XLK (183.77) existed only in book.json — the trails had not ratcheted, so no
  `stop_synced` fired for them this morning (the other four positions were re-armed by
  their trails at 13:31–13:33 by luck). SPY traded through 769.46 from ~13:00 ET; the model
  saw it twice ("broker stop should be filling, nothing for me to do"), then dropped SPY from
  its book at 17:41 and the engine sold it at 767.32 for −6.29 — a stop-out done by hand.
  Same exposure after every restart since 08-25 (five of them). Fix: the restore path
  re-inserts each book stop under its own tag, unmatched until the first real quote (a
  synthetic quote at avg_cost would fire a breakeven stop on the spot), journaled as
  `sim_stops_restored`. Tonight's restart proves it: all 6 shadows logged their tags at
  22:49:13, XLF and XLK included. main is unaffected — its GTC stops live at IBKR and
  survive our restarts by themselves, which is the whole point of server-side stops (lesson 6).
- **The null intraday tape correlates with the 12:45 ET reconnect, and the refetch was
  blind.** Across every scalper event run since 09-01: the tape never populated on 09-01 or
  09-02 (no midday reconnect), populated at the first run after the 16:46 UTC reconnect on
  09-03 and 09-08, and from 14:38 on 09-04 (no reconnect; the farm was healthy at that open).
  Today the `_bars` pass's failures (AVGO/ABBV/AMZN/CVX/MSFT/CRM) stayed dead from 13:26
  until `bars_recovered` at 16:48–17:09, i.e. until the reconnect — history failures look
  sticky per connection. `_refresh_bars` swallowed every exception and journaled nothing, so
  "farm dead" vs "streak abort" vs "IB returned no partial bar" was unanswerable for a week
  while scalper wrote "flagged again for the human" four times today. Now one `bars_refresh`
  line per event run (fetched / today / stale / failed / skipped / unreached) and held
  symbols are probed before the alphabet so the streak abort cannot starve the book. First
  evidence tomorrow ~09:35 ET; if `failed` names the same symbols every run until 12:45,
  the next step is a forced reconnect (or re-qualify) when the streak trips, not more scans.
- **The 12:45 ET disconnect is a schedule, not IB weather.** main's reconnect log: the nightly
  04:5x UTC blip fired 09-01, 09-02, 09-03 and never again; a 16:46–16:51 UTC reconnect
  started 09-03 and has fired every day since — 09-05 (Sat), 09-06 (Sun), 09-07 (holiday)
  included. IB does not reset at 12:45 ET on Saturdays. Something on this PC or in the
  Gateway changed on 09-03; IB Gateway's own "Auto restart" time is the obvious candidate
  (12:45 PM vs AM?). Owner check: Gateway → Configure → Lock and Exit → auto-restart time;
  pick a time after the 17:00 ET reset and before the open. Same-hour coincidence with the
  Sunday logout resolving at 12:49 ET on 09-06 supports it.
- **Event gate: 23 runs fleet-wide, all no_change, five stories.** PFE "Novartis India
  acquires Pfizer brands for $132m" (0.8) fired 6 variants — every triage said the same
  thing: a $132m trademark sale is not material to a $150B company; the scorer weights the
  verb "acquires", not the size. CRM "Before You Chase Salesforce's Rally, Take a Closer Look
  at Its Latest Earnings Beat" (0.7, −4%) fired 5 — commentary on a 13-day-old print that
  the dampener does not match ("before you …", "take a closer look"). ORCL "EU regulators
  send early warning … ahead of earnings" (0.7) fired all 7 — fourth ORCL trigger in four
  sessions, print is Thursday. NVDA/Qualcomm-Amazon warrants (0.8) fired 4 as a competitor
  read-through. ADBE's "what the stock did last time" retrospective (0.65) fired sniper.
  Candidates written down, not coded (two code changes already tonight): dampen
  "before you …"/"take a closer look"/"here's what … did" commentary titles; and a deal-size
  vs market-cap check is fuzzy without a cap table. Fleet lesson 16 covers the model side.
- **scalper's first day-trade.** UNH 2 sh @ 402.22 (continuation playbook, +2.4% from open,
  range_pos 0.92, stop 390, 1-day time stop) at 13:38 ET, once the tape was populated; the
  SPY hand-exit minutes earlier was its 3rd active loser in a row → 3-losing-trades breaker
  until 09-10, so its 14:40 ET TSLA proposal was rejected. Note the cosmetic false rejection
  "UNH: entries paused" for a symbol already held at target (the +$94 top-up delta counts as
  an entry); harmless, the model did not misread it. UNH closes 09-09 on the time stop
  unless it works.
- Soft red day (SPY −0.4%): main −36.84, bold +2.87, scalper −12.17, sniper −34.21, swing
  −6.36, turtle −33.40, twin −21.76. All-time: twin −10.35, turtle −27.36, swing −34.58,
  scalper −40.13, sniper −73.81, bold −76.02, main −87.22; main vs SPY since 08-24: −104.
  The 12:45 ET blip reconnected in 1–2 min on all 7. OneDrive PermissionError ×4 (twin
  13:51 + 18:28, scalper 16:48, sniper 18:42) → 28+.
- **DEPLOYED 22:49 UTC** via `schtasks` from Bash (PowerShell denied again): stop → all 7
  Ready → start → all 7 Running, heartbeats within 2 s, `sim_stops_restored` on all 6
  shadows. The fleet runs HEAD.

## 2026-09-07 (Labor Day, engineer) — the holiday was skipped correctly; tomorrow's roll-forward weekly would have fired into the open buffer on all 7

- **No session (Labor Day) and the scheduler knew it.** `is_trading_day` covers NYSE
  holidays: no weekly, no daily, no report, no rebalance on any variant; `last_weekly` is
  still 08-31 everywhere, so all 7 weeklies roll forward to Tuesday morning under the 08-24
  rule. Benjamin sent `Status` at 16:57 UTC (answered by the command path, no model run).
  Standings unchanged since Friday; `llm_state` shows 0 runs today.
- **BUG (fixed, deployed): the rolled-forward weekly fired on bare `is_rth`, not the order
  window.** The 08-31 fix moved the intraday scan and the news gate to `_orders_can_fill`
  but left `can_trade_now` for the weekly/daily on `is_rth(now)`. A rolled-forward weekly
  therefore fires at the FIRST RTH tick, which always lands inside the 15-min open buffer.
  The journals prove the cost: on 08-25 (the Tuesday after the lost Monday) all 7 variants'
  weeklies planned `hold_reason: "outside RTH trade window", equity: 0.0` — seven model
  runs wasted, and sniper (XLF), swing (SPY/XLK/XLF) and twin (GOOGL) proposed real
  rebalances that the plan dropped (sniper and swing re-proposed in the 09:50 daily;
  twin's GOOGL never came back). Tomorrow, 09-08, is the identical setup for all 7. The
  daily was never affected (09:50 ≥ buffer end). One-line fix + regression test at 09:35
  vs 09:46 ET. Third member of the "decide only where the market can act" family after
  08-18 and 08-31 — the lesson generalizes: every `is_rth` guard on a run that produces
  orders is a latent copy of this bug.
- **The Gateway process itself died overnight**: `Socket disconnect` at 01:32–01:39 UTC
  Monday → `connection refused - no Gateway process is listening` (the 08-30 text, first
  live use of the "start it" branch) → `reconnected, down_minutes: 142–149, failed_attempts:
  27–28` at 04:02–04:07 UTC. Second time the process vanished (08-26: 22:55→02:59 UTC);
  both healed by ~04:00 UTC without anyone logging in, so this is the Gateway's own
  restart cycle, not the Sunday logout. Hysteresis: one error + one summary per variant.
- **The 12:45 ET disconnect is now 3 of the last 4 days** (09-04, 09-05, 09-07; 09-06 was
  the logout at 08:21 ET). Today 16:46–16:54 UTC, reconnected in 5–7 min on all 7 (turtle
  twice: 16:37 and 16:53). Nothing traded; it would matter on a day with an open event
  slot at 12:45, so far it has not.
- Nightly noise as documented: 20:05 ET cache fill failed its first 3 symbols per variant
  (00:04 UTC, `rest of pass skipped` 4), `bars_recovered` on the 04:0x reconnect. One
  OneDrive `PermissionError` on main at 09:36 UTC Sunday (→ 24+).
- **DEPLOYED 22:44 UTC** via `schtasks` from Bash: stop → all 7 Ready → start → all 7
  Running, heartbeats within 1 s. The fleet now runs HEAD: tonight's weekly-window fix plus
  the 09-05 digest word-boundary fix. First live test is tomorrow 09:45 ET, when seven
  weeklies should fire in the window instead of at 09:30.

## 2026-09-06 (Sunday night, engineer) — the Sunday logout hit for the 4th weekend, and healed in 4 h, not 13

- **Weekend logout, 4 of 4 weekends — but the fastest recovery yet.** All 7 variants lost
  the socket 12:21–12:25 UTC (08:21 ET, the Gateway's weekly auto-restart), each journaled
  exactly one `connect` error at 12:27–12:31 with the new "LOGGED OUT — needs a manual
  login" text (its second live use, correct again), and all 7 `reconnected` at 16:46–16:50
  UTC: `down_minutes: 259, failed_attempts: 42` identical everywhere. 4 h 19 min blind
  versus ~13 h on 08-30 and ~27 h on 08-23; whether Benjamin logged in from the phone alert
  or the Gateway re-authenticated itself, the journal cannot tell — the outage ended at
  12:49 ET on a Sunday either way, well before Monday's open. Hysteresis held (14–16
  lines per variant for the whole episode, all in the first 10 minutes). Nothing traded, no
  decisions, no breakers; all 7 heartbeats fresh at 22:40 UTC; standings unchanged from
  Friday. swing alone took a second 30-s timeout at 21:07 UTC (the 17:00 ET reset window,
  same as turtle-only on 08-28) and was back by 21:12.
- **The watchdog now leaves a journal record** (08-25 follow-up, closed). Every transition
  — `down` (with the staleness text), hourly `reminder`, `recovered` (with `since` and
  `down_minutes`) — is appended to main's journal as a `watchdog` line, best-effort, so an
  OneDrive lock can never suppress the alert. It runs as a fresh process every 5 min, so
  the next Task Scheduler fire picks the change up with no restart. Same second-appender
  pattern as `ibagent unfreeze`. Note it guards only main's heartbeat, by design.
- **A traceback from a running process shows source text from the file on disk, not the
  code it runs.** main's 09:36 UTC OneDrive `PermissionError` (→ 23+ total; on
  `schedule_state.tmp → .json`, the one-shot retry did not save it) printed frames like
  "line 234 in tick: update_high_prices" that make no sense — because supervisor.py changed
  on 09-05 (the digest excerpt fix) after the 09-04 22:47 deploy. Cosmetic; it also
  confirms the fleet is exactly one commit behind HEAD, and that commit first matters
  Friday. Not restarting on a Sunday night for it.

## 2026-09-05 (Saturday night, engineer) — quiet weekend day; the fleet-wide disconnect moved to Saturday noon

- **No session today.** Since last night's 22:47 UTC deploy the seven journals hold only:
  the documented 20:05 ET cache fill failing its first 3 symbols per variant (22:46–22:52
  and 00:01–00:07 UTC, `rest of pass skipped` 6–10), one stray `no historical bars` on
  bold (GOOGL 15:02 UTC), and a **fleet-wide `Socket disconnect` at 16:45–16:49 UTC
  (12:45 ET)** — one warning burst + one `reconnected` line per variant within ~5 min,
  every failed symbol bracketed by `bars_recovered` on reconnect. Same clock time as
  Friday's 12:45 ET blip, so this is now two days running at that hour; distinct from the
  04:45 UTC nightly reset (which did NOT fire last night). Hysteresis absorbed it. Nothing
  traded, nothing rejected, no decisions, no breakers; all 7 heartbeats fresh at 22:42 UTC;
  `ibagent compare` unchanged from Friday's close. Last night's harness verdict is in
  main's journal as `engineer … kept + pushed` — the first time the engineer round-trip is
  auditable from the journal itself.
- **Cosmetic fix: the Friday digest cuts lessons at a word boundary now.** All 14 excerpts
  in the 09-04 FLEET.md ended mid-word ("print gets ev", "second-order s", "regardless of").
  `_excerpt()` trims to the last whole word and appends "…"; test replays main's real ORCL
  lesson. Not deployed — it first matters next Friday and any restart before then picks it
  up; not worth a Saturday restart dance on its own.
- **Tomorrow is Sunday**: the 08-30 pattern (Gateway weekly auto-restart ~12:20 UTC with
  nobody logged in, 13 h blind, self-healed 01:43 UTC Monday) has hit 3 of 3 weekends.
  Auto-restart/IBC remains the highest-value owner task; nothing code-side can log in.
- The watchdog still journals nothing (08-25 follow-up open): `watchdog_state.json` is
  `{}` again, so whether today's 5-min blip crossed its stale threshold (it should not
  have) is unknowable after the fact. Written down, not coded — a quiet-night candidate.

## 2026-09-04 (Friday night, engineer) — the model invented a ticker and the engine quoted it 237 times

- **BUG (fixed): a made-up watchlist entry was quoted every news poll for 22 hours.** main's
  09-03 15:50 UTC event decision (the HPE/Oracle sympathy headline) wrote
  `"HPE-VIA-ORCL:NONE"` into its watchlist — an annotation, not a ticker. The Decision
  schema only upper-cases watchlist strings, `_news_job` quotes `held | watchlist` every
  5-minute poll, and the broker answered `unknown contract` 237 times (146 today alone —
  83% of main's warning lines) until the 13:51 daily replaced the list. Harmless to the
  book, but a 22-hour warning stream from one line of model output, and the same string
  would have been quoted and bar-fetched in the daily run too. Fix: when a decision's
  watchlist is adopted, only whitelisted tickers are kept and the dropped entries are
  journaled once (`warning where=watchlist`); the weekly prompt now says plain whitelisted
  tickers only. Same design rule as 08-26's breaker: model text is untrusted input on the
  data path too, not just on the order path. Regression test replays the real entry.
- **ORCL fired all 7 variants a third time on a preview** — "Oracle Stock Climbs Ahead Of
  Earnings After OpenAI Astra Release" (0.7, +2.4%) at 16:10–16:21 UTC; 7 runs, 7
  `no_change`, every lesson field the same sentence ("third ORCL trigger in two sessions,
  sympathy/preview, only the 09-10 print is Hard"). With NVDA (0.8, a day-old deal
  explainer) and ADBE (0.8) earlier, main/bold/swing/turtle/twin were at 3/3 event slots by
  16:15 UTC — a real 3pm headline would have found nobody home. Scorer now halves a
  "<move verb> ahead of earnings/results" title (lesson 9's construction again);
  deliberately requires a move verb so "CEO Pick Lands Ahead of Earnings" — a Hard item
  that happened to be pre-print — keeps 0.8. Test uses both real headlines.
- **The two-links-one-story pattern recurred**: ADBE's CEO pick fired scalper twice (15:12
  "Adobe Sinks 7% as Internal CEO Pick Lands…" and 17:18 "Adobe Names New CEO As Earnings
  Approach…", both 0.8, different links). Second instance of the 09-01 AAPL pattern; the
  per-symbol-per-day cap stays written down, not coded — two data points, one variant.
- **First correct Friday fleet digest fired** at 20:22 UTC (the 08-29 fix): "Week of
  2026-08-31" shows real counts (scalper 81 decisions, main 16, sniper 24). Its lesson
  excerpts are cut mid-word at 400 chars — cosmetic, generated output, left alone.
- A fleet-wide `Socket disconnect` at 16:45 UTC (12:45 ET) reconnected within ~1 min on
  all 7; sniper took a second one at 21:14. One error line each — hysteresis as designed.
  NFLX returned no bars once on every variant (first appearance of that symbol failing).
  OneDrive PermissionError ×2 (scalper 16:38, sniper 16:58) → 21+.
- Soft red day (SPY −0.5%): main −10.67, bold −23.01 (XOM −1.7%, now within 3% of its
  157.09 stop), scalper −7.18, sniper −11.42, swing +0.05, turtle −9.62, twin −7.05.
  All-time: twin +11.17, turtle +3.95, scalper −29.10, swing −30.87, sniper −40.62,
  main −53.35, bold −79.45. main vs SPY since 08-24: −125. NVDA trails ratcheted to
  ~216 on main/sniper/turtle as it printed 234.6 intraday. scalper: 17 runs, 17 no_change
  — its tape stayed populated (AMD setup seen and correctly declined on a red index).
- **DEPLOYED 22:47 UTC** via `schtasks` from Bash (PowerShell denied again tonight): all 7
  tasks Ready → Running, heartbeats fresh within 2 s. Both fixes are live before Monday.

## 2026-09-03 (Thursday night, engineer) — the usage limit ate five dailies; sniper finally hunts

- **BUG (fixed): a transient Claude usage limit burned the day's decision slots.** A
  13:45–13:57 UTC rate-limit cluster (all 7 variants fire their dailies + morning events
  within the same 12 minutes — self-inflicted burst on one subscription) made 7 runs fall
  back to HOLD, including FIVE of seven daily runs (main, scalper, sniper, swing, twin).
  `last_daily` was marked before the run, so the limit — which cleared within ~50 min
  (main's 14:48 event run succeeded) — cost those variants their entire daily. Same for
  event runs: the gate's fired-key made AVGO's REAL earnings story unanalyzable all day
  for main and turtle. Fix: a `usage_limited` HOLD now un-marks the daily/weekly slot and
  sets a 30-min fleet-wide backoff (journaled as `llm_backoff`); a usage-limited event run
  refunds the gate's budget slot and fired-key (cooldown still spaces the re-fire), and
  the gate is told `can_fire=False` while backed off, so headlines wait in the digest
  instead of burning slots on guaranteed HOLDs. Same family as 08-18/08-27: spend slots
  only where they can buy a real decision. Regression tests both paths.
- **A preview slipped the dampener on day one, as predicted**: "Oracle To Face Earnings
  Test After Wild Year Riding AI Wave" (0.7) got past `faces a (critical|key) test` and
  fired scalper at 17:13. Pattern broadened to any short "face(s) … test" phrase;
  regression test uses the real headline.
- **Sympathy headlines are the new slot-waster**: "Snowflake Soars 23% … Oracle Advances
  3%" (0.75) and "HPE Earnings Top Estimates Amid Oracle AI Data Center Deal" (0.7) each
  fired ~6 variants on ORCL — 12+ runs, every one the same "the Hard catalyst belongs to
  another company" triage, all no_change. Distilled as fleet lesson 15; a scorer-side fix
  (subject-vs-mention detection) is fuzzy and written down, not coded.
- **sniper made its first event-driven entry** — NVDA 2 sh @ 228.16 (half-size trend,
  stop 209.30, 0.46% risk) on the confirmed ~$12.9B Hugging Face acquisition (0.9). Clean
  sizing, inside the chase gate. The news specialist finally hunted on a Hard catalyst.
- **scalper's intraday tape POPULATED for the first time** (~17:42 UTC): day_open/
  day_change/day_range_pos real, and the continuation playbook produced actual candidates
  (GS +2.2%, MSFT +1.6% from open) — blocked only by its risk_off regime rule (its own
  09-01 downgrade; upgrade needs two supportive cycles). The RTH probe question is half-
  answered by live behavior: the refetch CAN populate intraday fields when the farm
  cooperates. Watch whether it stays populated tomorrow.
- swing's NVDA spec time-stop exited +5.72 as designed. Green day fleet-wide (+43 main);
  all-time: twin +17.97 and turtle +9.71 are POSITIVE, scalper −21.83, sniper −28.61,
  swing −33.76, main −47.82, bold −53.43. OneDrive PermissionError ×1 (main 15:20) → 19+.

## 2026-09-02 (Wednesday night, engineer) — the storm fix held; the scorer learns lesson 9

- **Last night's rebalance-storm fix passed its first live day**: zero `core_rebalance`
  retries, zero partial-retry alerts, all 7 variants made their daily (all `no_change` on
  a recovery tape). Green day fleet-wide: main +40.76; standings improved to twin −9.87,
  turtle −41.44, scalper −49.75, bold −52.49, sniper −69.42, swing −94.51, main −96.68.
  bold's and swing's 3-losing-trades breakers expire 09-03; entries resume tomorrow.
- **The scorer now applies fleet lesson 9 itself.** Today a Cramer opinion piece ("Nvidia
  … Needs a Half Trillion Dollar Buyback") scored 0.8 (buyback+earnings keywords) and a
  Broadcom-earnings preview ("What to watch in…") scored 0.7; with NVDA +4% both cleared
  the gate on ALL 7 variants — 14 event runs, every one `no_change`. That is the 4th
  preview/commentary cluster (HD ×4 + WMT, NVDA-preview 0.8 + AAPL launch 08-26, today
  ×2) with zero trades and zero thesis changes ever. Fix: preview/commentary title
  markers (`what to watch`, `preview`, `cramer`, `upcoming earnings`, `faces a critical
  test`, …) halve the score — 0.8→0.4 stays in the digest (≥0.3, scheduled runs still see
  it) but under the gate's 0.70, so it no longer burns event slots or run budget.
  Regression test uses today's real headlines. This is a scoring-rule addition, not a
  gate-semantics change; the per-symbol-per-day cap from 09-01 stays written-down only.
- The two NVDA headlines cost ~half the fleet's daily event budget on a day NVDA was
  genuinely running +4% — if real NVDA news had broken at 3pm, most variants had slots
  left (max 3/day, 1–2 spent), but the waste pattern compounds. The dampener addresses
  the measured cases; watch whether a preview slips the title patterns.
- scalper: ~15 more intraday runs, all `no_change`, same null-intraday-fields blocker;
  the RTH `day_change` probe is STILL not run (this session started 22:42 UTC again).
  OneDrive PermissionError ×4 today (twin 14:17, bold 18:27, scalper 20:23, swing 20:26)
  → 18+ total; the migration remains an owner decision.

## 2026-09-01 (Tuesday night, engineer) — the rebalance that could never fill alerted 245 times

- **BUG (fixed): the monthly core rebalance retried an unfillable whole-share intent every
  tick, all session.** Sep-1 was rebalance day; every variant's VTI top-up came to ~$330
  while one VTI share costs ~$375. In whole-share mode that intent can never fill, but the
  retry-until-complete logic (correct for transient failures) re-ran it every ~minute from
  10:00 to 15:30 ET: 234–288 journal lines per variant, and — because the rebalance alert
  passes `dedupe=False` — **~245 identical "core rebalance (partial — will retry)" Telegram
  messages to the owner from main alone**. The 08-18 rule ("an alert that repeats without
  new information kills the channel") violated by our own code. Two fixes: `core_rebalance`
  no longer emits an intent below one share's price (the holding is as close to target as
  whole shares allow → period completes), and the partial-retry alert now dedupes (only the
  once-per-period completion skips dedupe). Regression test. Without deploy the storm
  resumes at 10:00 ET tomorrow, so tonight's restart dance matters.
- **First genuinely red day handled cleanly by the machinery**: risk-off tape (10y 4.78%,
  Brent >$92). Five protective stop fills — bold SPY −23.51, swing SPY −4.29 + XLF −16.84,
  scalper XLF −8.17 + QQQ −17.31 — and bold + swing each tripped the 3-losing-trades
  breaker (entries paused until 09-03, exits unaffected). All by design; no false freezes,
  the 08-28 stop-fill/reconcile fix held. bold also made the fleet's only entry (XOM 7 sh)
  minutes before the tape soured.
- **A multi-day story burns event slots one fresh link at a time.** The AAPL CEO transition
  (Cook → Ternus) produced three DIFFERENT headlines from three outlets 14:39–16:12 UTC;
  each passed the once-per-day headline dedup (it keys on the link) and fired sniper at
  0.65 materiality — 3 of its event slots on one already-known fact. Sniper triaged all
  three correctly (Soft/Noise, no_change), so the cost is run budget, not bad trades.
  Candidate fix written down, not coded: a per-symbol-per-day event cap, or dedup on
  (symbol, day) after the first no_change verdict — that is a news-gate semantics change
  and deserves a calm look, not a night edit.
- scalper: 13 more intraday runs, 13 no_change, still blocked on null intraday fields; the
  RTH `day_change` probe remains not-run (engineer sessions keep landing after the close).
  Standing note: whoever gets an RTH session first should run the one-off 1-day-bar probe
  from 08-27 before any day-trader design work.
- Fleet after 11 trading days (all-time): twin −20.91, scalper −49.75, bold −61.53,
  turtle −80.69, sniper −85.18, swing −94.51, main −137.39. Everyone red but within
  ordinary beta; twin (tiered fees, same brain as main) still leads the A/B by ~$116.

## 2026-08-31 (Monday night, engineer) — the weekend outage self-healed in time; runs stop firing into the open buffer

- **The Sunday logout resolved at 01:43 UTC Monday** (journal: `reconnected, down_minutes:
  178, failed_attempts: 29` — the counter only spans the handshake-timeout phase; the full
  logout ran ~13h from 12:20 UTC Sunday). Third weekend outage, third self-recovery before
  the open — but 08-24 proved it will not always land that way. Auto-restart/IBC remains
  the highest-value owner task. The new "LOGGED OUT vs process gone" alert text fired
  correctly at 22:44 UTC Sunday, its first live use.
- **Monday was a quiet, healthy session**: all 7 variants made their weekly + daily
  decisions (first weekly since the digest fix), every one `no_change` on a soft tape
  (SPY −0.43%, regime neutral everywhere). Zero orders, zero rejections, zero errors
  during RTH. main +3.70 on the day; NVDA recovered +1.4%. twin's turnover budget reset
  today and it still chose not to re-attempt SMH — its own call, not a cap.
- **The 08-28 headline-dedup fix passed its first live test**: the GOOGL "new buyer class"
  piece (0.7) fired main and twin exactly once each at 18:11 UTC — no cooldown re-fires.
- **BUG (fixed): model runs fired inside the no-trade buffers and their plans were
  guaranteed holds.** scalper's first intraday scan started ~09:31 ET Monday and planned
  against that frozen timestamp → "outside RTH trade window", equity 0.0, one model run
  wasted; sniper's 09:34 ET event run on 08-28 was the same failure via the news gate
  (which only checked `is_rth`). Both paths now gate on `_orders_can_fill` — RTH minus the
  mandate's open/close buffers, the exact predicate `risk.plan_orders` holds on. A
  buffered headline stays in the digest and fires at the first poll inside the window.
  Regression test. Same family as 08-18/08-27: spend runs and budgets only where the
  market can act on them.
- **bold is unfrozen and trading again** (weekly + daily ran normally Monday) — but its
  journal holds no record of when or how the freeze was cleared. `ibagent unfreeze` now
  writes an `unfreeze` journal line (by/was) so a freeze/unfreeze pair is auditable.
- The bars farm flaked again at 13:47 UTC (ABBV/ADBE/AMD on every variant, ~50 skipped) —
  the breaker served cached bars and decisions were unaffected; per-symbol farm flakiness
  as diagnosed 08-27. `day_change` RTH probe still not run (no RTH engineer session yet).

## 2026-08-30 (Sunday night, engineer) — the Gateway is UP, LISTENING and LOGGED OUT, and nobody could tell

- **ONGOING at 22:45 UTC: Gateway logged out since ~12:20 UTC Sunday (10+ h).** All 7
  variants dropped at 12:20–12:29 and journaled exactly one `connect` error each
  (hysteresis: correct) — but the line read `cannot connect to IB Gateway at
  127.0.0.1:4002: ` with an EMPTY reason. Diagnosis tonight: `ibgateway.exe` is running
  and port 4002 is LISTENING; the API handshake times out — the weekly auto-restart hit
  with nobody home, same failure as the lost Monday (08-24). The empty message is because
  ib_async raises a bare `TimeoutError()` for handshake-timeout, so "up but logged out"
  was indistinguishable from "process dead". **If Benjamin does not log in before Monday
  09:30 ET, the fleet is blind at the open again** (GTC stops still stand guard, as
  08-24 proved). The 08-23 weekend outage self-recovered Sun ~23:29 UTC; this one may
  too, but the pattern is now 3 outages in 3 weekends — Auto-restart/IBC remains the fix
  and remains an owner task.
- **BUG (fixed): the connect-failure alert now names the state and the required action.**
  Handshake timeout → "port accepted but the API handshake timed out — Gateway is likely
  up but LOGGED OUT; it needs a manual login". Connection refused → "no Gateway process
  is listening; IB Gateway needs to be started". Anything else keeps the raw text. The
  hourly "broker still unreachable" reminder carries the same string, so the owner can
  tell "log in" from "start it" from the phone. Regression test. Deployed tonight.
- Saturday was otherwise silent (only the 04:45 UTC reset blip, one line per variant) and
  Sunday held no market session; the 08-29 digest/unfreeze deploys have seen no traffic
  yet — first real exercise is Monday.

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
