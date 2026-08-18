"""Agent orchestrator: one full decision cycle.

  cap check -> bundle -> claude -p -> parse -> (invalid? one retry with the errors)
  -> failure/limit? HOLD -> journal everything -> risk.plan_orders -> execute -> journal.

The invocation budget is persisted (data/llm_state.json) so restarts cannot burn the daily
cap. Every failure path degrades to HOLD: the book is never touched by a run that did not
produce a valid, validated decision.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ibagent.agent.bundle import Bundle, build_bundle, prune_bundles
from ibagent.alerts import Alerter
from ibagent.book import Book
from ibagent.broker.base import Quote
from ibagent.common import RunType
from ibagent.config import Mandate
from ibagent.data import SymbolStats
from ibagent.execution import ExecutionReport, Executor
from ibagent.journal import Journal
from ibagent.llm.runner import LLMRunner, RunRequest, RunResult, default_runs_root
from ibagent.risk import Plan, plan_orders
from ibagent.schemas import Decision, DecisionError, hold_decision, parse_decision


@dataclass
class LLMState:
    day: str = ""
    count: int = 0
    hold_fallbacks: int = 0
    runs_total: int = 0

    @classmethod
    def load(cls, path: Path) -> "LLMState":
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return cls(day=str(d.get("day", "")), count=int(d.get("count", 0)),
                       hold_fallbacks=int(d.get("hold_fallbacks", 0)), runs_total=int(d.get("runs_total", 0)))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__), encoding="utf-8")
        tmp.replace(path)


@dataclass
class CycleResult:
    run_type: RunType
    decision: Decision
    held: bool                                   # True when the engine substituted HOLD
    reason: str = ""
    plan: Optional[Plan] = None
    report: Optional[ExecutionReport] = None
    bundle_dir: str = ""


def _decision_payload(d: Decision) -> dict:
    return {"run_type": d.run_type, "action": d.action, "market_regime": d.market_regime,
            "risk_multiplier": d.risk_multiplier,
            "symbols": [f"{p.symbol}:{p.sleeve}:{p.target_weight}" for p in d.positions],
            "stop_updates": [f"{u.symbol}@{u.stop_price}" for u in d.stop_updates],
            "watchlist": d.watchlist, "notes": d.notes_for_human, "lessons": d.journal_lessons}


def obtain_decision(m: Mandate, runner: LLMRunner, bundle: Bundle, run_type: RunType,
                    journal: Journal) -> tuple[Decision, bool, str]:
    """Run the model, validate, retry once with the validation errors. Returns
    (decision, held, reason)."""
    attempts = 1 + m.llm.retries_on_invalid
    prompt = bundle.prompt
    last_err = ""
    for attempt in range(attempts):
        res: RunResult = runner.run(RunRequest(run_type=run_type, bundle_dir=bundle.dir,
                                               prompt=prompt, system_prompt_file=bundle.system_prompt_file))
        if m.journal.keep_raw_llm_output:
            stamp = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{run_type}-a{attempt}"
            journal.save_blob(f"{stamp}-stdout.txt", res.raw_stdout or res.text or "")
            if res.raw_stderr:
                journal.save_blob(f"{stamp}-stderr.txt", res.raw_stderr)
        journal.record("llm_run", {"run_type": run_type, "attempt": attempt, "ok": res.ok,
                                   "usage_limited": res.usage_limited, "duration_s": res.duration_s,
                                   "error": res.error or ""})
        if res.usage_limited:
            return hold_decision(run_type, "Claude usage-limited"), True, "usage_limited"
        if not res.ok or res.decision is None:
            last_err = res.error or "no decision produced"
            continue
        try:
            return parse_decision(res.decision, expected_run_type=run_type), False, ""
        except DecisionError as exc:
            last_err = str(exc)
            prompt = (f"{bundle.prompt}\n\nYour previous reply was rejected by the validator:\n"
                      f"{last_err}\nReply again with a corrected JSON object only.")
    return hold_decision(run_type, f"invalid after {attempts} attempts: {last_err[:300]}"), True, last_err


def run_cycle(m: Mandate, book: Book, journal: Journal, alerter: Alerter, runner: LLMRunner,
              executor: Executor, quotes: Dict[str, Quote], atrs: Dict[str, float],
              stats: Dict[str, SymbolStats], digest_md: str, run_type: RunType,
              now: datetime, state_path: Path, event_note: str = "",
              skills_dir: Optional[Path] = None, kill_switch: bool = False) -> CycleResult:
    now = now.astimezone(timezone.utc)
    state = LLMState.load(state_path)
    today = now.date().isoformat()
    if state.day != today:
        state.day, state.count = today, 0

    prices = {s: (q.mid or q.last) for s, q in quotes.items() if (q.mid or q.last)}
    try:
        snap = book.equity(prices, now)
    except Exception as exc:
        journal.record("run_summary", {"run_type": run_type, "result": f"skipped: {exc}"})
        return CycleResult(run_type=run_type, decision=hold_decision(run_type, str(exc)),
                           held=True, reason=f"cannot mark book: {exc}")

    if state.count >= m.llm.daily_invocation_cap:
        reason = f"daily invocation cap {m.llm.daily_invocation_cap} reached"
        journal.record("run_summary", {"run_type": run_type, "result": reason})
        alerter.warning("LLM cap reached", reason)
        return CycleResult(run_type=run_type, decision=hold_decision(run_type, reason),
                           held=True, reason=reason)

    runs_root = default_runs_root(m.llm.sandbox.runs_root)
    tail = journal.tail(40, kinds=("decision", "fill", "run_summary"))
    bundle = build_bundle(m, book, snap, stats, digest_md, tail, run_type, runs_root, now,
                          event_note=event_note, skills_dir=skills_dir)

    state.count += 1
    state.runs_total += 1
    state.save(state_path)                       # count the attempt BEFORE running: crash-safe cap

    decision, held, reason = obtain_decision(m, runner, bundle, run_type, journal)
    if held:
        state.hold_fallbacks += 1
        state.save(state_path)
        alerter.warning(f"{run_type} run fell back to HOLD", reason[:400])
    journal.record("decision", _decision_payload(decision))

    ma20s = {s: v.ma20 for s, v in stats.items() if v.ma20}
    plan = plan_orders(m, book, quotes, atrs, decision, now, kill_switch=kill_switch, ma20s=ma20s)
    journal.record("plan", {
        "run_type": run_type, "hold": plan.hold, "hold_reason": plan.hold_reason,
        "equity": plan.equity,
        "orders": [f"{o.req.side} {o.req.qty} {o.req.symbol} lmt {o.req.limit_price} ({o.intent})"
                   for o in plan.orders],
        "stops": [f"{s.symbol}@{s.stop_price}" for s in plan.stop_instructions],
        "rejections": [f"{r.symbol}: {r.reason}" for r in plan.rejections]})
    for r in plan.rejections:
        journal.record("rejection", {"symbol": r.symbol, "what": r.what, "reason": r.reason})

    report = executor.execute_plan(plan)
    journal.record("run_summary", {
        "run_type": run_type,
        "result": (f"held: {reason}" if held else
                   f"{decision.action}; {report.filled}/{len(plan.orders)} orders filled, "
                   f"{len(report.stops_placed)} stops placed, {len(report.stops_replaced)} replaced"),
        "realized": report.realized_pnl, "errors": report.errors})
    prune_bundles(runs_root)
    return CycleResult(run_type=run_type, decision=decision, held=held, reason=reason,
                       plan=plan, report=report, bundle_dir=str(bundle.dir))
