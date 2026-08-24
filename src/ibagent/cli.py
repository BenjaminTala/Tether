"""ibagent command line.

  ibagent validate [--mandate mandate.yaml] [--set capital.seed_usd=2500]
  ibagent schema                       # decision JSON schema (what the model must return)
  ibagent capital init --seed 1000 | add 500 | withdraw 300 | show
  ibagent kill | unkill                # kill switch file
  ibagent secret set NAME              # store a secret in the OS credential store (prompted)
  ibagent broker smoke [--place-test] [--symbol SGOV] [--qty 0.25]   # Phase 2 exit check
  ibagent run weekly|daily|event       # one agent cycle now
  ibagent supervise                    # the long-running engine (Task Scheduler at logon)
  ibagent watchdog                     # heartbeat check (Task Scheduler every 5 min)
  ibagent status                       # print the engine book without touching the broker
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ibagent.capital import CapitalLedger, LedgerError
from ibagent.config import Mandate, MandateError, load_mandate, parse_override
from ibagent.schemas import decision_json_schema

DEFAULT_MANDATE = "mandate.yaml"
CAPITAL_LEDGER = Path("data") / "capital_events.jsonl"


def _load(args: argparse.Namespace) -> Mandate:
    overrides: Dict[str, Any] = dict(parse_override(s) for s in (args.set or []))
    return load_mandate(args.mandate, overrides)


def cmd_validate(args: argparse.Namespace) -> int:
    m = _load(args)
    seed = m.capital.seed_usd
    print(f"OK  mode={m.mode}  profile={m.universe.profile}  seed=${seed:,.0f}")
    for s in ("trend", "spec"):
        print(f"    {s}: sleeve=${m.sleeve_equity(seed, s):,.0f}  max_positions={m.max_positions(s, seed)}  "
              f"per_position_cap=${m.position_cap_usd(s, seed):,.0f}  risk/trade=${m.per_trade_risk_usd(s, seed):,.2f}")
    print(f"    core: ${m.sleeve_equity(seed, 'core'):,.0f} -> {m.universe.active.core_holdings}")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    print(json.dumps(decision_json_schema(), indent=2))
    return 0


def cmd_capital(args: argparse.Namespace) -> int:
    ledger = CapitalLedger(args.ledger)
    if args.capital_cmd == "init":
        seed = args.seed if args.seed is not None else _load(args).capital.seed_usd
        ev = ledger.init_seed(seed, note=args.note or "initial seed")
        print(f"seeded pot with ${ev.amount_usd:,.2f}")
    elif args.capital_cmd == "add":
        ev = ledger.add(args.amount, note=args.note or "")
        print(f"added ${ev.amount_usd:,.2f}; net contributions ${ledger.net_contributions():,.2f}")
    elif args.capital_cmd == "withdraw":
        ev = ledger.withdraw(args.amount, note=args.note or "")
        print(f"withdrawal of ${ev.amount_usd:,.2f} recorded; the engine frees cash at the next window")
    else:  # show
        for e in ledger.events():
            print(f"{e.ts}  {e.kind:<8} {e.amount_usd:>10,.2f}  {e.note}")
        print(f"net contributions: ${ledger.net_contributions():,.2f}")
    return 0


def cmd_kill(args: argparse.Namespace, engage: bool) -> int:
    path = Path(_load(args).kill_switch.file)
    if engage:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("KILL requested from CLI\n", encoding="utf-8")
        print(f"kill switch ENGAGED ({path}); the supervisor cancels open orders and stops trading")
    else:
        if path.exists():
            path.unlink()
        print("kill switch cleared; restart the supervisor to resume")
    return 0


def cmd_secret(args: argparse.Namespace) -> int:
    from ibagent.alerts import set_secret
    value = getpass.getpass(f"value for {args.name}: ")
    if not value:
        print("empty value, nothing stored", file=sys.stderr)
        return 2
    set_secret(args.name, value)
    print(f"stored {args.name} in the OS credential store")
    return 0


def cmd_broker_smoke(args: argparse.Namespace) -> int:
    """Read-only checks against IB Gateway; with --place-test a tiny paper round-trip (RTH only)."""
    from datetime import datetime, timezone
    from ibagent.broker.base import Contract, OrderRequest
    from ibagent.broker.ibkr import BrokerError, IBKRBroker

    m = _load(args)
    if args.place_test and m.mode != "paper":
        print("refusing --place-test outside paper mode", file=sys.stderr)
        return 1
    symbol = (args.symbol or next(iter(m.universe.active.core_holdings))).upper()
    inst = m.universe.active.instrument(symbol)
    if inst is None:
        print(f"{symbol} is not in the active universe profile", file=sys.stderr)
        return 1
    contract = Contract(symbol=symbol, exchange=inst.exchange, currency=inst.currency)
    b = IBKRBroker(m.broker, account_id=m.account.ibkr_account_id, base_currency=m.base_currency)
    b.connect()
    try:
        a = b.account()
        print(f"account   net_liq={a.net_liquidation:,.2f} cash={a.total_cash:,.2f} settled={a.settled_cash:,.2f} {a.currency}")
        for p in b.positions():
            print(f"position  {p.symbol:<6} qty={p.qty:g} avg={p.avg_cost:.2f}")
        for o in b.open_orders():
            print(f"open      {o.symbol:<6} {o.side} {o.qty:g} state={o.state} tag={o.client_tag} id={o.broker_order_id}")
        q = b.quote(contract)
        print(f"quote     {symbol} bid={q.bid} ask={q.ask} last={q.last} delayed={q.delayed}")
        bars = b.daily_bars(contract, 30)
        print(f"bars      {symbol} n={len(bars)} last_close={bars[-1].close} ({bars[-1].ts:%Y-%m-%d})")
        if not args.place_test:
            print("OK (read-only). Add --place-test during RTH for a paper round-trip.")
            return 0
        price = q.ask or q.last
        if not price:
            print("no price for the test order", file=sys.stderr)
            return 1
        qty = args.qty or round(m.capital.min_order_usd / price, 4)
        off = m.execution.limit_offset_bps / 10_000.0
        start = datetime.now(timezone.utc)
        tag = f"smoke-{start:%Y%m%d%H%M%S}"
        for side, lim in (("BUY", round(price * (1 + off), 2)), ("SELL", round((q.bid or price) * (1 - off), 2))):
            st = b.place(OrderRequest(client_tag=f"{tag}-{side[0]}", symbol=symbol, side=side, qty=qty,
                                      order_type="LMT", limit_price=lim, tif="DAY", contract=contract))
            print(f"placed    {side} {qty:g} {symbol} @ {lim} -> {st.state} {st.reason}")
            if st.state == "rejected":
                return 1
            for _ in range(30):
                b.sleep(2.0)
                fills = [f for f in b.fills_since(start) if f.client_tag == f"{tag}-{side[0]}"]
                if fills:
                    f = fills[-1]
                    print(f"filled    {f.side} {f.qty:g} @ {f.price} commission={f.commission:.2f} id={f.broker_order_id}")
                    break
            else:
                print("not filled within 60s (market closed or non-marketable); cancelling", file=sys.stderr)
                b.cancel(st.broker_order_id)
                return 1
        print("OK round-trip complete")
        return 0
    except BrokerError as exc:
        print(f"broker error: {exc}", file=sys.stderr)
        return 1
    finally:
        b.disconnect()


def _build_supervisor(m: Mandate):
    from ibagent.broker.ibkr import IBKRBroker
    from ibagent.supervisor import Supervisor
    broker = IBKRBroker(m.broker, account_id=m.account.ibkr_account_id, base_currency=m.base_currency)
    return Supervisor(m, broker)


def _load_shadow(args: argparse.Namespace, name: str) -> Mandate:
    """Base mandate + the variant's overrides + the isolation the fleet depends on."""
    import yaml
    spec_path = Path("shadows") / f"{name}.yaml"
    if not spec_path.is_file():
        raise RuntimeError(f"unknown shadow '{name}' (no {spec_path})")
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    overrides: Dict[str, Any] = dict(parse_override(s) for s in (args.set or []))
    overrides.update(spec.get("overrides", {}))
    overrides.setdefault("journal.dir", f"data-shadows/{name}/journal")
    overrides.setdefault("alerts.channels", ["stdout"])
    return load_mandate(args.mandate, overrides)


def _build_shadow_supervisor(m: Mandate, name: str):
    from ibagent.broker.ibkr import IBKRBroker
    from ibagent.broker.shadow import ShadowBroker
    from ibagent.broker.sim import SimBroker, SimConfig
    from ibagent.supervisor import Supervisor
    data_dir = Path("data-shadows") / name
    ledger = CapitalLedger(data_dir / "capital_events.jsonl")
    if not ledger.is_initialized():
        ledger.init_seed(m.capital.seed_usd, note=f"shadow '{name}' auto-seed (simulated cash)")
    data = IBKRBroker(m.broker, account_id=m.account.ibkr_account_id, base_currency=m.base_currency)
    sim = SimBroker(SimConfig(initial_cash=0.0, commission_model=m.capital.commission_model))
    from datetime import datetime, timezone
    sim.set_time(datetime.now(timezone.utc))
    from ibagent.book import Book
    from ibagent.broker.shadow import restore_sim_state
    restore_sim_state(sim, Book.load(data_dir / "book.json"), ledger.net_contributions())
    return Supervisor(m, ShadowBroker(data, sim), data_dir=data_dir, variant_name=name)


def cmd_engineer(args: argparse.Namespace) -> int:
    """Nightly self-improvement pass: a headless Claude run under ENGINEER.md's charter,
    fenced by deterministic guards (tests must pass, protected files must be untouched)."""
    import subprocess
    from ibagent.journal import Journal
    from ibagent.llm.runner import resolve_claude_bin
    m = _load(args)
    repo = Path.cwd()
    journal = Journal(m.journal.dir)

    def git(*a: str) -> str:
        r = subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
        return (r.stdout or "").strip()

    pre_head = git("rev-parse", "HEAD")
    flags = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
    cmd = [resolve_claude_bin(m.llm.claude_bin), "-p", "--output-format", "text",
           "--permission-mode", "dontAsk", "--max-turns", "80",
           "--allowedTools", "Read,Edit,Write,Grep,Glob,Bash"]
    prompt = ("Read ENGINEER.md in this directory and carry out tonight's engineering pass. "
              "Follow its charter exactly - especially the MUST NOT list and the report.")
    try:
        proc = subprocess.run(cmd, cwd=repo, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=2700,
                              creationflags=flags)
        raw = (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        raw = "(engineer run timed out after 45 min)"
    journal.save_blob(f"engineer-{__import__('datetime').datetime.now():%Y%m%d}.txt", raw[-40000:])

    git("checkout", "--", ".")                                     # drop uncommitted leftovers
    post_head = git("rev-parse", "HEAD")
    verdict = "no changes"
    if post_head != pre_head:
        changed = git("diff", "--name-only", f"{pre_head}..{post_head}").splitlines()
        forbidden = [f for f in changed if f == "mandate.yaml" or f.startswith("data")]
        tests = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=repo,
                               capture_output=True, text=True, timeout=600)
        if forbidden or tests.returncode != 0:
            git("reset", "--hard", pre_head)
            verdict = (f"REVERTED {len(changed)} file(s): "
                       + ("touched protected files " + ",".join(forbidden) if forbidden
                          else "test suite went red"))
        else:
            subprocess.run(["git", "push", "origin", "main"], cwd=repo, capture_output=True,
                           timeout=120)
            verdict = f"kept + pushed: {len(changed)} file(s) ({', '.join(changed[:6])})"
    journal.record("engineer", {"pre": pre_head[:9], "post": git("rev-parse", "HEAD")[:9],
                                "verdict": verdict})
    report_file = repo / "data" / "engineer_report.txt"
    report = report_file.read_text(encoding="utf-8")[:3200] if report_file.exists() \
        else "(engineer left no report)"
    from ibagent.alerts import build_alerter
    build_alerter(m.alerts).info("🔧 Nightly engineer", f"{verdict}\n\n{report}", dedupe=False)
    print(verdict)
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    """Backtest the deterministic strategy skeletons on real IBKR daily history."""
    from ibagent.backtest import (load_history, make_momentum, run_backtest, save_history,
                                  strat_core_only, strat_spy)
    from ibagent.broker.base import Contract
    m = _load(args)
    trend_universe = [i.symbol for i in m.universe.active.instruments if "trend" in i.sleeves]
    symbols = sorted(set(trend_universe) | {"SPY", "VTI", "SGOV"})
    days = int(args.years * 365)
    bars: Dict[str, Any] = {}
    missing = []
    for s in symbols:
        h = None if args.refresh else load_history(s)
        if h and len(h) > days * 0.6:
            bars[s] = h
        else:
            missing.append(s)
    if missing:
        from ibagent.broker.ibkr import IBKRBroker
        cfg = m.broker.model_copy(update={"client_id": 25})
        b = IBKRBroker(cfg, account_id=m.account.ibkr_account_id, base_currency=m.base_currency)
        b.connect()
        try:
            for i, s in enumerate(missing):
                try:
                    h = b.daily_bars(Contract(symbol=s), days)
                    bars[s] = h
                    save_history(s, h)
                    print(f"fetched {s}: {len(h)} bars ({i + 1}/{len(missing)})")
                except Exception as exc:
                    print(f"skip {s}: {exc}")
                b.sleep(2.5)                      # stay under the historical-data pacing limit
        finally:
            b.disconnect()
    have_trend = [s for s in trend_universe if s in bars]
    runs = [
        ("spy (benchmark)", {"SPY": bars["SPY"]}, strat_spy, "monthly", None),
        ("core_only 60/40", {k: bars[k] for k in ("VTI", "SGOV") if k in bars},
         strat_core_only, "monthly", None),
        ("momentum top3", {k: bars[k] for k in set(have_trend) | {"SGOV"} if k in bars},
         make_momentum(have_trend, 3), "monthly", 2.5),
        ("swing top3 tight", {k: bars[k] for k in set(have_trend) | {"SGOV"} if k in bars},
         make_momentum(have_trend, 3), "weekly", 2.0),
    ]
    print("\nHONESTY NOTES: mechanical rules only (no AI in the loop); today's whitelist =\n"
          "survivorship bias, so treat results as OPTIMISTIC upper bounds; fills at close\n"
          f"+{5:g}bps slippage; commissions '{m.capital.commission_model}'.\n")
    print(f"{'STRATEGY':<20}{'CAGR':>8}{'MAXDD':>8}{'SHARPE':>8}{'TRADES':>8}{'FEES':>9}{'FINAL':>12}")
    for name, data, strat, cadence, trail in runs:
        if not data:
            continue
        r = run_backtest(name, data, strat, rebalance=cadence, trail_atr=trail,
                         commission=m.capital.commission_model)
        print(f"{r.name:<20}{r.cagr:>8.1%}{r.max_drawdown:>8.1%}{r.sharpe:>8.2f}"
              f"{r.trades:>8}{r.fees:>9.2f}{r.final:>12,.2f}   ({r.start} → {r.end})")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Fleet scoreboard from each variant's last daily report (equity marked by its own run)."""
    from ibagent.journal import Journal
    rows = []
    for label, jdir in [("main", Path("data") / "journal")] + \
            [(p.name, p / "journal") for p in sorted(Path("data-shadows").glob("*")) if p.is_dir()]:
        if not jdir.is_dir():
            continue
        reports = Journal(jdir).tail(1, kinds=("daily_report",))
        eq = reports[-1]["payload"].get("equity") if reports else None
        from ibagent.book import Book
        b = Book.load((jdir.parent if label != "main" else Path("data")) / "book.json")
        rows.append((label, eq, b.net_contributions, len(b.positions),
                     sum(b.realized_pnl.values())))
    print(f"{'VARIANT':<10}{'EQUITY':>12}{'PUT IN':>10}{'ALL-TIME':>10}{'POS':>5}{'REALIZED':>10}")
    for label, eq, contrib, npos, realized in rows:
        eq_s = f"{eq:,.2f}" if eq else "n/a"
        pnl_s = f"{eq - contrib:+,.2f}" if eq else "n/a"
        print(f"{label:<10}{eq_s:>12}{contrib:>10,.0f}{pnl_s:>10}{npos:>5}{realized:>+10.2f}")
    return 0


def _live_gate(m: Mandate) -> None:
    import os
    if m.mode == "live" and os.environ.get(m.go_live_gate.ack_env_var) != m.go_live_gate.ack_value:
        raise RuntimeError(f"live mode requires env {m.go_live_gate.ack_env_var}="
                           f"{m.go_live_gate.ack_value} (go_live_gate)")


def cmd_run(args: argparse.Namespace) -> int:
    m = _load(args)
    _live_gate(m)
    sup = _build_supervisor(m)
    try:
        sup.run_agent_once(args.run_type)
    finally:
        try:
            sup.broker.disconnect()
        except Exception:
            pass
    print(f"{args.run_type} run complete; see data/journal for the decision and orders")
    return 0


def cmd_supervise(args: argparse.Namespace) -> int:
    if getattr(args, "shadow", None):
        m = _load_shadow(args, args.shadow)
        if m.mode != "paper":
            raise RuntimeError("shadows are simulation-only; mode must be paper")
        sup = _build_shadow_supervisor(m, args.shadow)
        sup.run()
        return 0
    m = _load(args)
    _live_gate(m)
    sup = _build_supervisor(m)
    sup.run()
    return 0


def cmd_watchdog(args: argparse.Namespace) -> int:
    from ibagent.watchdog import main as watchdog_main
    return watchdog_main(_load(args))


def cmd_status(args: argparse.Namespace) -> int:
    from ibagent.book import Book
    book = Book.load(Path("data") / "book.json")
    print(f"pot cash ${book.pot_cash:,.2f}  contributions ${book.net_contributions:,.2f}  "
          f"pending withdrawal ${book.pending_withdrawal_usd:,.2f}")
    print(f"realized P&L {book.realized_pnl}  HWM {book.hwm}")
    flags = []
    if book.halted:
        flags.append(f"HALTED: {book.halted_reason}")
    if book.frozen:
        flags.append(f"FROZEN: {book.frozen_reason}")
    if book.paused_sleeves:
        flags.append(f"paused: {book.paused_sleeves}")
    if Path(_load(args).kill_switch.file).exists():
        flags.append("KILL SWITCH ENGAGED")
    print("state: " + ("; ".join(flags) if flags else "normal"))
    if not book.positions:
        print("no positions")
    for p in sorted(book.positions.values(), key=lambda x: x.symbol):
        print(f"  {p.symbol:<6} {p.sleeve:<5} qty={p.qty:g} avg={p.avg_cost:.2f} "
              f"stop={p.stop_price} entered={p.entry_date}  {p.thesis[:60]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mandate", default=DEFAULT_MANDATE, help="path to mandate.yaml")
    common.add_argument("--set", action="append", metavar="KEY=VALUE", help="override a mandate value (dotted key)")
    common.add_argument("--ledger", default=str(CAPITAL_LEDGER), help="capital ledger path")

    p = argparse.ArgumentParser(prog="ibagent", description="Deterministic IBKR engine + Claude decision layer")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = lambda name, **kw: sub.add_parser(name, parents=[common], **kw)  # noqa: E731

    sp("validate", help="validate the mandate and print derived sizing at seed")
    sp("schema", help="print the decision JSON schema")

    cap = sp("capital", help="capital ledger")
    capsub = cap.add_subparsers(dest="capital_cmd", required=True)
    ci = capsub.add_parser("init", parents=[common]); ci.add_argument("--seed", type=float); ci.add_argument("--note")
    ca = capsub.add_parser("add", parents=[common]); ca.add_argument("amount", type=float); ca.add_argument("--note")
    cw = capsub.add_parser("withdraw", parents=[common]); cw.add_argument("amount", type=float); cw.add_argument("--note")
    capsub.add_parser("show", parents=[common])

    sp("kill", help="engage the kill switch")
    sp("unkill", help="clear the kill switch")
    sec = sp("secret"); secsub = sec.add_subparsers(dest="secret_cmd", required=True)
    ss = secsub.add_parser("set", parents=[common]); ss.add_argument("name")

    br = sp("broker", help="broker checks"); brsub = br.add_subparsers(dest="broker_cmd", required=True)
    sm = brsub.add_parser("smoke", parents=[common], help="connect to IB Gateway and verify data/orders")
    sm.add_argument("--place-test", action="store_true", help="paper only: tiny marketable round-trip (RTH)")
    sm.add_argument("--symbol"); sm.add_argument("--qty", type=float)

    run = sp("run", help="run one agent cycle now")
    run.add_argument("run_type", choices=["weekly", "daily", "event"])
    sup = sp("supervise", help="start the long-running supervisor")
    sup.add_argument("--shadow", help="run a simulated-money variant from shadows/<name>.yaml")
    sp("watchdog", help="heartbeat watchdog, run by Task Scheduler")
    sp("status", help="print the engine book (no broker connection)")
    sp("compare", help="fleet scoreboard: main vs shadow variants")
    sp("engineer", help="nightly self-improvement pass (headless Claude under ENGINEER.md)")
    bt = sp("backtest", help="backtest the deterministic strategy skeletons on IBKR history")
    bt.add_argument("--years", type=float, default=3.0)
    bt.add_argument("--refresh", action="store_true", help="refetch cached history")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "validate":
            return cmd_validate(args)
        if args.cmd == "schema":
            return cmd_schema(args)
        if args.cmd == "capital":
            return cmd_capital(args)
        if args.cmd == "kill":
            return cmd_kill(args, True)
        if args.cmd == "unkill":
            return cmd_kill(args, False)
        if args.cmd == "secret":
            return cmd_secret(args)
        if args.cmd == "broker":
            return cmd_broker_smoke(args)
        if args.cmd == "run":
            return cmd_run(args)
        if args.cmd == "supervise":
            return cmd_supervise(args)
        if args.cmd == "watchdog":
            return cmd_watchdog(args)
        if args.cmd == "status":
            return cmd_status(args)
        if args.cmd == "compare":
            return cmd_compare(args)
        if args.cmd == "backtest":
            return cmd_backtest(args)
        if args.cmd == "engineer":
            return cmd_engineer(args)
    except (MandateError, LedgerError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
