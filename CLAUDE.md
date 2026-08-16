# ibagent — instructions for Claude Code working in this repo

Deterministic IBKR trading engine + schema-bound Claude decision layer. Real money is at
stake once `mode: live`. Read README.md first; the "GO-LIVE (paper)" section is the setup
runbook to walk a new user through, in order.

## Hard rules — never violate these when editing or operating

1. **Money is controlled by code, not by the model.** Claude (in the agent role) only emits a
   validated `Decision`; every order must pass `risk.plan_orders`. Never add a code path that
   places orders without it, and never weaken a mandate validator (never-widen stops,
   no-averaging-down, read-only LLM tools, paper/live port checks are `Literal[True]` on purpose).
2. **Capital changes are human-only.** Only `ibagent capital init|add|withdraw` may write the
   ledger. Never write `data/capital_events.jsonl` from engine code or on a user's behalf
   without their explicit instruction.
3. **Fail closed.** Missing price, missing ATR, unreadable state, reconcile mismatch → no
   trade / freeze. Never substitute a guess for missing data.
4. **Exits are never blocked** by breakers, caps, pauses or locks. Entries are what gets gated.
5. **Secrets** live in env vars or Windows Credential Manager (`ibagent secret set NAME`,
   keyring service `ibagent`). Never print them, never commit them, never put them in the
   mandate. `data/` is gitignored and must stay so — it is the user's private trading state.
6. **Tests must stay green** (`pytest -q`, 200+). The `md` fixture in tests/conftest.py pins
   capital knobs so user tuning of mandate.yaml doesn't move test goalposts — keep it that way.
7. Paper first. `mode: live` is gated by `go_live_gate` + an ack env var; do not help a user
   bypass it.

## Setting up a NEW user (fresh clone)

Follow README "GO-LIVE (paper)" step by step. Personalize these before the first run:

| What | Where |
|---|---|
| Paper account id (`DU...`) | `mandate.yaml` → `account.ibkr_account_id` (repo ships the author's — replace it) |
| Commission plan (fixed/tiered) | `capital.commission_model`; if fixed, keep `min_position_usd` ≥ 150 so the $1 min fee clears `max_fee_pct_per_trade` |
| Seed amount | `ibagent capital init --seed N` (also sanity-check `ibagent validate --set capital.seed_usd=N`) |
| Region/entity | IBKR LLC → `universe.profile: us`; EU/UK-resident (IBIE/IBUK) → `ucits` profile and verify each instrument in TWS |
| Alerts | Telegram bot via @BotFather → `ibagent secret set TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`; or `alerts.channels: [stdout, windows_toast]` |
| Timezone note | cadence times are ET; the user's PC must be awake during US RTH |
| Claude auth | logged-in Claude Code on a Pro/Max subscription + `claude setup-token` (or `CLAUDE_CODE_OAUTH_TOKEN` user env var). NO `ANTHROPIC_API_KEY` |

Environment: Python 3.11+ (`python -m venv .venv; pip install -e .[dev,windows]`), IB Gateway
on port 4002 (paper), Windows Task Scheduler via `windows/install_tasks.ps1`.

Verification ladder (don't skip steps): `pytest -q` → `ibagent validate` → `ibagent broker
smoke` → during RTH `ibagent broker smoke --place-test` → `ibagent run daily` → install tasks.

## Layout

`src/ibagent/`: config (mandate models) · schemas (Decision contract) · book (engine-owned
state) · risk (plan_orders — the only Decision→orders path) · sleeves (protective actions,
breakers, rebalance) · execution (orders/fills/GTC stops) · data (ATR/momentum) · news/
(ingest + scoring + event gate) · agent/ (bundle + orchestrator) · supervisor · watchdog ·
broker/ (ibkr + sim) · llm/runner (claude -p sandbox). `skills/` are copied into each model
run bundle. Tests mirror modules; `tests/test_risk_property.py` is the mandate-breach
property suite — extend it when adding risk rules.
