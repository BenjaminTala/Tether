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
10. **If market.json is missing rows for held positions, the tape is broken, not quiet.**
   Say so in one sentence, `no_change`, and stop — do not re-diagnose the pipeline in
   every run (scalper wrote the same lesson 13 times on 2026-08-26). The engine's stops
   protect the book; your job on a broken tape is to not trade blind.
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
