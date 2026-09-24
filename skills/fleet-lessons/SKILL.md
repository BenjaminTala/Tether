---
name: fleet-lessons
description: Distilled, EVIDENCE-BASED lessons from this system's own backtests and live trading. Unlike the book-derived skills, every line here was measured on this machine with this broker, these fees and this data. Read before proposing any trade; when a book heuristic and a fleet lesson conflict, the fleet lesson wins because it priced in OUR frictions.
---

# Fleet Lessons (evidence from this system's own history)

## From the 3-year backtest on real data (2023-08 → 2026-08, real fees/slippage)

| strategy          | CAGR  | maxDD | Sharpe | fees  |
|-------------------|-------|-------|--------|-------|
| SPY buy-and-hold  | 10.9% | 17.9% | 0.88   | $1    |
| core 60/40        |  7.3% | 12.3% | 0.89   | $2    |
| momentum top-3    |  8.6% | 16.2% | 0.57   | $176  |
| swing tight-stops |  4.7% | 23.1% | 0.33   | $364  |

1. **Buy-and-hold is the bar.** The mechanical momentum skeleton UNDERPERFORMED holding
   SPY over this window. Your only justification for an active position is judgment the
   skeleton lacks: a concrete catalyst, a fundamental read, a regime call. If your thesis
   is only "momentum rank is high", the backtest says that alone is worth LESS than nothing.
2. **The fee hurdle is real and computable.** Every round-trip costs ~$2 (fixed pricing).
   On a $500 position that is 0.4% guaranteed loss before edge. Do not propose a trade
   whose realistic edge is under ~3x its round-trip cost. More trades = more certain drag;
   the swing backtest paid 3.6% of the whole pot to fees.
3. **Tight stops + fast rotation was the worst of both worlds** — lowest return AND
   deepest drawdown (whipsaw harvesting). In choppy-but-rising tape, wider stops with
   smaller size beat tight stops with bigger size at equal risk.
4. **V-shaped dips are trend-following's enemy**: stops eject you, re-entry lags the
   rebound. When regime is risk_on and a held name dips WITHOUT thesis damage, the
   backtest-informed move is patience, not a tighter leash.

## From live trading (paper, this fleet)

5. **Delayed quotes lose races on high-priced, wide-ATR names.** LLY expired unfilled on
   3 consecutive days. Prefer lower-priced, tighter-spread expressions of the same thesis
   (sector ETF vs the $1,200 stock) when both are on the whitelist.
6. **Stops at the broker work.** BAC's trailed GTC stop exited automatically at −0.24% of
   the pot while nobody watched. Trust the machinery: set the stop honestly at entry
   instead of proposing a tight stop you secretly expect to widen (you can't).
   Second proof (2026-08-24): SMH's GTC stop fired at 547.52 while our Gateway was
   OFFLINE for 9 hours; SMH closed below it. The broker-side stop is the only defence
   that works when we are not there — never rely on "I'll manage it intraday".
7. **Chasing stale catalysts fails.** The one live spec loss so far (HD, −$29 x2 agents)
   came from buying a day-old headline in a downtrending name. A catalyst is tradable the
   day it breaks, in the direction of the prevailing trend — or not at all.
8. **Sitting out is a respected position.** Days of headlines produced zero qualifying
   spec catalysts and the correct book was no spec at all. Every "no_change on a quiet
   day" journal entry aged well so far; every forced trade did not.
9. **Previews are not events.** Earnings-preview pieces ("faces a critical test on
   Wednesday"), launch-date announcements and other calendar headlines fired the event
   trigger at high materiality (NVDA 0.8, AAPL 0.65 on 2026-08-26; HD ×4, WMT before)
   and not one of them broke or built a thesis. If the headline describes something
   that WILL happen, the tradable information does not exist yet: `no_change`, and say
   in one line that it was a preview. Never position into a binary print on a preview.
   (2026-09-02: a Cramer opinion piece and a Broadcom preview fired 14 runs fleet-wide,
   all `no_change` — commentary counts as preview. The scorer now halves preview/
   commentary titles, so if one still triggers you, it slipped the pattern: same rule.
   2026-09-04: "Oracle Stock Climbs Ahead Of Earnings…" fired all 7 variants, all
   `no_change` — "<moves> ahead of earnings" is the same construction and is now
   dampened too. Also: the `watchlist` you return is quoted by the engine every poll;
   list plain whitelisted tickers only, never annotations like "HPE-VIA-ORCL:NONE".
   2026-09-21: "Did Elon Musk Just Drop a Big Hint About a Possible SpaceX-Tesla Merger?"
   (0.8 via "merger") fired all 7, all `no_change` — a headline that ends in a question
   mark is reporting that nothing has been announced. Now dampened; same rule if one slips.)
10. **If market.json is missing rows for held positions, the tape is broken, not quiet.**
   Say so in one sentence, `no_change`, and stop — do not re-diagnose the pipeline in
   every run (scalper wrote the same lesson 13 times on 2026-08-26). The engine's stops
   protect the book; your job on a broken tape is to not trade blind.
   (2026-09-18: all 7 dailies got an EMPTY market.json after an engine redeploy and every
   one answered in a single pass — no entries, no blind stop moves, held stops left to the
   broker. That is the whole correct response; the engine now keeps its bars across restarts.)
11. **Second-try fills work on liquid ETFs.** XLF expired unfilled once and filled on the
   next day's re-attempt at ask+35bps for two variants; LLY never did. Lesson 5 holds:
   express a thesis through the instrument that fills.
12. **A hard print is tradable in the first in-RTH run, or not at all.** NVDA's beat-and-
   raise (2026-08-27): main, turtle and swing proposed it (twin: SMH) in the 09:50 daily
   and the three filled at ~223 — inside the chase gate because the gap open
   was still ~1.5 ATR over ma20. Every later look (scalper's 13 intraday scans) found the
   move at +7% → +10% (CRM +20%) and correctly passed. Bold, which had sized half into the
   print, held and refused to add at the cap — also correct. So: on the morning after a
   real print, decide in the daily run with the gap price; do not plan to "wait for a
   pullback and re-run" — on this tape the pullback never came inside the window.
13. **A repeat headline is not a new event.** On 2026-08-28 one CRM follow-through piece
   fired 24 event runs fleet-wide (3–4 per variant); every run re-derived the same
   4.9-ATR extension and said no. The gate now fires each headline once per day, but the
   rule stands for you too: if the trigger note quotes a story you already reviewed today,
   re-check the arithmetic in one line and `no_change` — do not re-read the narrative.
14. **Breakeven on day 2 after a print is a stop-out, not protection.** bold moved its
   NVDA stop to breakeven (217.30, at ma20) the morning after entry at +~1R; NVDA gave
   back 4.5% that afternoon and the stop filled at 217.25 for −$2. main, turtle and swing
   kept their original stops (~214.6–214.8, 207) and are still in. One instance, but it
   is lesson 3/4 again from the other side: a fresh post-print position needs room for the
   day-2 shakeout; move to breakeven when +1R has HELD for a session, not when it first prints.
   (2026-09-10 addendum: turtle followed this rule exactly — breakeven 222.25 only after +1R
   held two sessions — and a routine −0.5% morning dip still tagged it for −$2 while
   original-stop holders stayed in. Breakeven is a free exit option and the first shakeout
   WILL exercise it: move to breakeven only when you accept "flat and out" as the outcome;
   if you still want the position, trail below structure instead.
   2026-09-22 addendum: **R is measured against the ENTRY stop, never the trailed one.**
   scalper's 11:36 ET scan read MRK at 153.19 as "+2.2R on the engine stop" (147.92, the
   engine's 1.5-ATR trail — the entry stop was 145.50, so the true gain was +0.85R) and
   correctly held; the 12:07 ET scan used the same arithmetic to move the stop to
   breakeven "after >+1R" on the FIRST day above +1R. A trailed stop shrinks the
   denominator every hour, so "R" against it is always inflated; the rule above needs
   +1R on the ORIGINAL risk, held for a session.
   2026-09-24, the same mistake with a stop YOU tightened: scalper moved LLY's stop from
   1146.98 to 1155 at 11:05 ET, then wrote "entry stop 1155" in the next run and at 12:36 ET
   read 1197.22 as "+1.3R -> breakeven". On the 1145 stop at the fill it was +0.84R, and
   the position faded to 1187 by the close, 1.1% over the new stop. portfolio.json now
   carries `entry_stop` on every position: R = (price − entry_price) / (entry_price −
   entry_stop), always; `stop` is where the exit sits today, never the denominator.)
15. **A sympathy move is not your catalyst.** On 2026-09-03 "Snowflake Soars 23% …
   Oracle Advances 3%" and "HPE Earnings Top Estimates Amid Oracle AI Data Center Deal"
   each fired ~6 variants on ORCL (+4–5%): 12+ runs, all no_change, all the same triage.
   If the headline's Hard catalyst (the earnings, the deal, the guidance) belongs to a
   DIFFERENT company and your symbol merely "advances"/"rises" alongside it, the move is
   second-order and already priced by the time you see it: say so in one line and
   `no_change`. Trading the sympathy name needs its OWN thesis, not a neighbor's print.
16. **Materiality is a headline score, not an economic one — a dollar figure is only Hard
   relative to the company's size.** "Novartis India acquires Pfizer brands for $132m"
   scored 0.8 (M&A pattern) on 2026-09-08 and fired six variants; every one fetched the
   article and found an India-trademark tidy-up worth ~0.05% of PFE's market cap. Same
   day, "Before You Chase … Take a Closer Look at Its Latest Earnings Beat" (0.7) fired
   five variants on a 13-day-old CRM print. The scorer rewards verbs (acquires, beat) and
   cannot size a deal against the company. Before treating an acquisition/divestiture/
   contract headline as Hard, put the dollar figure next to the market cap: under ~0.5–1%
   it is Noise whatever the tag; a piece that re-reads an old print is lesson 13 in
   different clothes. One line, `no_change`, move on.
17. **No-catalyst intraday entries are a proven loser on this tape.** scalper's four
   straight losses (through 2026-09-10: SPY breakeven day-2 tag, UNH midday knife-catch
   time-stopped −$13.84, plus two prior) all shared one shape: entry justified by price
   geometry alone (range position, "oversold intraday") with no catalyst. That is lesson 1
   at a faster clock — and the fee drag of lesson 2 compounds it. The engine's loss-streak
   cooldown is real and WILL reject your entries (it refused scalper's TSLA and XOM
   proposals mid-cooldown); when it does, the correct response is to stand down and write
   what broke, not to re-propose around it. (2026-09-16 addendum: scalper's 5th straight
   loser — XLE stopped at 64.18 on a −2.5% energy day, the ma20-anchored stop sat ~1.4 ATR
   under entry on a 2%-ATR ETF — put it in cooldown; its TMO proposal 3 h later was REJECTED
   and the next run wrote "appears not to have filled". journal_tail.md carries `FILL` and
   `REJECTED` lines verbatim: read them before writing "verify in fills log" or "did not
   fill". An order that never reaches the broker is a refusal, not a miss.
   2026-09-24 addendum: scalper's 6th straight loser (MRK and SMH stopped out 09:31 and
   09:48 ET, −11.72 and −34.04) started a cooldown to 09-28, and the 09:54 daily proposed
   JNJ into it — REJECTED, one more "do not re-propose" line. Two stop-out FILL lines in
   journal_tail on a losing streak mean the counter moved; portfolio.json `breakers` now
   names an active pause (`entries_paused_until` and a note). When it is there, the run's
   only jobs are managing what is held and saying so in one line.)
18. **After a dark day, the first run back is a fresh daily, not a catch-up.** The whole
   fleet was off for all of 2026-09-09 (PC off; GTC stops at IBKR were the only live
   defence — lesson 6). If the bundle shows a gap spanning a trading session: reconcile
   and re-check stops first, evaluate the book at TODAY's gap prices per lesson 12, and
   ignore the missed day's headlines — by lesson 7 a day-old catalyst is already untradable.
19. **The weight you write is the size you get.** `risk_multiplier` lowers the engine's cap
   on TOTAL trend+spec weight; it does not shrink an individual `target_weight`. On
   2026-09-21 twin meant 1 SPY and wrote 0.16 "if the engine applies the 0.5 multiplier"
   (got 2); scalper meant 4 MRK at "0.15 x 0.5" and got 9. Both were inside every cap, so
   nothing was rejected — the position was simply double the plan, and so is the loss at
   the stop. Do the multiplication yourself: half size at a 0.15 base is `target_weight`
   0.075 (check it still clears the sizing window's dollar floor; if not, it is no trade).
   (2026-09-23: main wrote `SPY:trend:0.08` meaning "1 whole share, half size" and got
   exactly 1 share — the rule works when you do the arithmetic yourself. Also from that
   run: the bundle's `close` is the last DAILY bar, i.e. yesterday's close during the
   morning daily; check the extension gate against the live quote, which that day moved
   SPY from 1.40 to 0.86 ATR over ma20.)
