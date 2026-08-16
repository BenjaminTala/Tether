# ibagent — autonomous IBKR agent (deterministic engine + Claude Code decision layer)

Money is controlled by Python. Claude only returns one schema-validated `Decision` per run
(target weights + thesis/stop/target/invalidation), invoked headless via `claude -p` on the Max
subscription — no API key, no per-token billing. Paper first; the same code path goes live.

## Architecture

```
Task Scheduler (Windows) ── at logon ──▶ IB Gateway (IBC auto-login)
                        └─ at logon ──▶ ibagent supervise  (ONE process, single writer)
                        └─ every 5m ─▶ ibagent watchdog    (heartbeat stale? → alert)

supervise:
  fast loop 60s (RTH)  reconcile book↔IBKR · verify server-side stops · kill switch · heartbeat
  slow loop 5m         connectivity, heartbeat off-hours
  news poll 15m        EDGAR/RSS/IBKR news → dedupe → materiality score → digest / event gate
  weekly MON 08:00 ET  bundle → claude -p (≤25 turns, read-only tools, sandbox cwd) → Decision
  daily 08:45 ET       light run (≤8 turns): stops/thesis/overnight news
  event (≤2/day)       only if score ≥ 0.7 AND |move| ≥ 3% on held/watched AND cooldown ok
  daily report 16:20   deterministic P&L / positions / risk → alert channel

Decision ─▶ risk.plan_orders (whitelist · sleeve caps · sizing · stops never widened · settled
cash T+1 · turnover caps · circuit breakers) ─▶ OrderRequest[] ─▶ IBKR (marketable limit, RTH)
                                            └─▶ journal (every prompt, output, order, fill, alert)
```

Key risk choices (all in `mandate.yaml`, all enforced in code):
* **Stops live at the broker** (GTC stop orders) — survive PC/model outages and delayed data.
* **Model failure ⇒ HOLD.** Invalid output → one retry with the errors → HOLD + alert. Usage
  limit / timeout → backoff → HOLD. Protective rules never depend on Claude.
* **Reconcile mismatch ⇒ freeze** new orders (never auto-fixed). Kill switch: `data/KILL`.
* **Read-only, sandboxed model**: `--tools Read,Grep,Glob,WebSearch,WebFetch`, `dontAsk`, cwd = a
  bundle dir outside the repo, WebFetch domain allowlist, child env scrubbed of `ANTHROPIC_*`
  and all engine secrets. Prompt injection can at worst rotate among whitelisted instruments.
* **Live gate**: `mode: live` refuses to start unless paper history meets `go_live_gate` and the
  ack env var is set.

## Capital is an input, not a constant

* `capital.seed_usd` seeds the pot at `ibagent capital init [--seed N]`. Afterwards capital only
  changes through the human-only ledger: `ibagent capital add 500` / `withdraw 300`
  (`data/capital_events.jsonl`, audited, never automatic).
* Every exposure number is a fraction of **current pot equity**; USD floors keep small pots sane:
  `max_positions(sleeve) = min(cap, floor(sleeve_equity / min_position_usd))`,
  `position_cap = min(sleeve_equity, max(pct_cap × equity, min_position_usd))`.
  `ibagent validate --set capital.seed_usd=5000` prints the derived sizing before you commit.
* Below `min_operating_equity_usd` the engine goes core-only and alerts.

## Repo map

```
mandate.yaml                 all limits/numbers (validated on load)
src/ibagent/config.py        Mandate models, sizing helpers, dotted overrides        ✅ + tests
src/ibagent/schemas.py       Decision contract, JSON schema for --json-schema, HOLD    ✅ + tests
src/ibagent/capital.py       capital ledger                                            ✅ + tests
src/ibagent/journal.py       append-only JSONL journal + blobs                         ✅ + tests
src/ibagent/alerts.py        secrets (env/keyring), Telegram/email/toast sinks, dedupe ✅ + tests
src/ibagent/llm/runner.py    ClaudeCodeRunner (claude -p), sandbox settings, parsing   ✅ + tests
src/ibagent/cli.py           validate · schema · capital · kill · secret · run/supervise ✅
src/ibagent/broker/base.py   Broker Protocol + value types                             ✅
src/ibagent/broker/ibkr.py   IBKRBroker over ib_async (quotes, bars, orders, fills)      ✅ helpers tested
src/ibagent/broker/sim.py    SimBroker: fills/stops/commissions/T+1 settled cash         ✅ + tests
src/ibagent/fees.py          IBKR commission estimator (tiered/fixed/lite)              ✅ + tests
src/ibagent/marketclock.py   NYSE calendar: rule-based holidays, early closes, RTH,
                             trading-day math, T+1 settlement dates                    ✅ + tests
src/ibagent/book.py          engine-owned book: positions/stops/HWMs, pot cash + T+1,
                             freeze/halt/pauses, reconcile (shared & dedicated)        ✅ + tests
src/ibagent/risk.py          plan_orders: Decision -> validated orders; every mandate
                             gate enforced; exits privileged; fail-closed stops        ✅ + property tests
src/ibagent/sleeves.py       protective actions, circuit breakers, core rebalance+sweep ✅ + tests
src/ibagent/{data,news/*}.py        Phase 4
src/ibagent/agent/*.py              Phase 5       src/ibagent/{supervisor,watchdog}.py Phase 6
```

## Build plan

| Phase | Deliverable | Exit criteria |
|---|---|---|
| 0 Workstation (you) | Paper account enabled; IB Gateway + API on (port 4002, 127.0.0.1); IBC installed; Python 3.12 venv; Claude Code native Windows install, logged in on Max, `claude setup-token`; Telegram bot; `install_tasks.ps1 -DisableSleep` | `ibagent validate` OK; `claude -p "ping" --output-format json` returns on the Max login; Gateway accepts a socket connection |
| 1 Foundation | config, schemas, capital, journal, alerts, runner, CLI | **done — 34 tests green** |
| 2 Broker | `IBKRBroker` (ib_async: contracts, delayed data, daily bars, marketable-limit + GTC stops with `orderRef`, fills, settled cash), `SimBroker`, fee estimator | **code done — 64 tests green.** Your part: `ibagent broker smoke` (read-only), then during RTH `ibagent broker smoke --place-test` (≈$25 SGOV round-trip on paper) |
| 3 Risk + sleeves + book | pure `plan_orders`, sizing/stops/targets, circuit breakers, T+1 settled cash, reconciliation freeze, HWM tracking | **done — 161 tests green** incl. 40-seed property tests (no order can breach the mandate) and golden scenarios (drawdown halt, stop-out cooldown, no averaging down) |
| 4 Data + news | ATR/momentum table, EDGAR + RSS + IBKR news ingest, materiality scoring, event gate | fixtures-based tests; digest ≤ 2k tokens; gate honours caps/cooldown |
| 5 Agent | bundle builder, system prompt, orchestrator (invocation cap, retry, HOLD), sandbox denial verified | `ibagent run daily` end-to-end on paper with `FakeRunner` and with real `claude -p`; injection test bundle cannot leave the whitelist or read the repo |
| 6 Supervisor | APScheduler jobs, heartbeat, watchdog, kill switch, daily/weekly reports, Task Scheduler wiring | 5 trading days unattended on paper, zero missed heartbeats, restart-on-failure proven |
| 7 Paper | 2–3 months on the exact live code path; tune only via mandate + journal notes | `go_live_gate` satisfied |
| 8 Live small | dedicated linked IBKR account, `mode: live`, ack env var, seed via ledger | first week: reconcile clean, orders/fills match journal |

## Phase 0/2 checklist for your existing IBKR LLC account (Panama)

1. Client Portal → Settings → Account Settings → **Paper Trading Account** → enable. You get a `DU…`
   account with its own login; put it in `account.ibkr_account_id`. Paper mirrors your live
   permissions after ~24 h. Paper cash is fake and large — irrelevant, the pot ledger sizes everything.
2. Trading Permissions → United States (Stocks) → **Fractional Shares** enabled (needed for $25–$100 orders).
3. Install **IB Gateway** (stable), log in with the *paper* user. Configure → Settings → API →
   Settings: ✔ Enable ActiveX and Socket Clients · Socket port **4002** · Trusted IP 127.0.0.1 ·
   ✘ Read-Only API · ✔ Download open orders on connection.
4. `ibagent broker smoke` (any time) → prints account, positions, a delayed SGOV quote, 30 daily bars.
   `ibagent broker smoke --place-test` during RTH → 0.25 SGOV buy + sell, prints fills and commissions.
   If IBKR rejects fractional quantities, fix step 2 (or run with `--qty 1`).
5. Later, for auto-login: IBC (`StartGateway.bat`) + `install_tasks.ps1 -IbcStartScript …`.

Region notes (Panama, IBKR LLC): US-domiciled ETFs are allowed → `universe.profile: us`. US dividend
withholding is 30 % (no US–Panama treaty); T-bill ETF distributions are largely exempt as qualified
interest income, so the core is fine. Switching the equity core to an Irish UCITS line (`CSPX`, 15 %
at fund level) is a one-line profile change if the pot grows large enough to care. Not tax advice.
Panama is UTC−5 without DST: US RTH is 08:30–15:00 (Mar–Nov) or 09:30–16:00 local — the PC must be
awake then.

## Runbook (Windows)

* Secrets: `ibagent secret set TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (Windows Credential
  Manager via keyring) — never in files. `ANTHROPIC_API_KEY` must NOT be set anywhere for this user.
* Kill: `ibagent kill` (or create `data\KILL`) → open orders cancelled, no new orders, alert.
  Resume: `ibagent unkill` then restart the `IBAgent-Supervisor` task.
* Capital: `ibagent capital add|withdraw N --note "..."`; withdrawals are satisfied from pot cash
  at the next trading window (active sleeves trimmed pro-rata first, then core).
* Change region/profile: `universe.profile: ucits` (verify each line in TWS first).
* Sanity anytime: `ibagent validate --set capital.seed_usd=N`.

## Open items I still need from you

1. Commission plan on your account (Fixed / Tiered) → `capital.commission_model` (tiered assumed).
2. Alert channel (Telegram assumed) — create a bot, `ibagent secret set TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.
3. Before live: a second linked IBKR account for the agent (Client Portal → Settings → Add an
   account), so reconciliation never sees your manual positions.

## Dev

```
python -m venv .venv && .venv\Scripts\activate
pip install -e .[dev,windows]
pytest -q
ibagent validate
```
