import json

import pytest

from ibagent.agent.orchestrator import LLMState, run_cycle
from ibagent.alerts import Alerter
from ibagent.broker.sim import SimBroker, SimConfig
from ibagent.config import mandate_from_dict
from ibagent.execution import Executor
from ibagent.journal import Journal
from ibagent.llm.runner import FakeRunner, RunResult
from tests.conftest import NOW, make_book, make_quote


@pytest.fixture
def env(md, tmp_path):
    md["llm"]["sandbox"]["runs_root"] = str(tmp_path / "runs")
    md["journal"]["dir"] = str(tmp_path / "journal")
    m = mandate_from_dict(md)
    broker = SimBroker(SimConfig(initial_cash=1000.0))
    broker.connect()
    broker.set_time(NOW)
    book = make_book(tmp_path, 1000.0)
    journal = Journal(m.journal.dir)
    executor = Executor(m, broker, book, journal, Alerter([]), sleeper=lambda s: None,
                        now_fn=lambda: NOW)
    return m, broker, book, journal, executor, tmp_path / "llm_state.json"


def decision_dict(action="no_change", positions=None, run_type="daily"):
    skills = ["market-regime", "failure-modes"]
    if positions:
        skills += ["trend-selection", "position-sizing", "trade-management"]
    return {"schema_version": 1, "run_type": run_type, "action": action,
            "market_regime": "neutral", "risk_multiplier": 1.0,
            "positions": positions or [], "stop_updates": [], "watchlist": [],
            "skills_applied": skills,
            "notes_for_human": "test decision", "journal_lessons": ""}


def ok(decision):
    return RunResult(ok=True, decision=decision, raw_stdout=json.dumps(decision))


def run(env, runner, run_type="daily", quotes=None, atrs=None):
    m, broker, book, journal, executor, state_path = env
    return run_cycle(m, book, journal, Alerter([]), runner, executor, quotes or {}, atrs or {},
                     {}, "", run_type, NOW, state_path, skills_dir=None)


def test_valid_no_change(env):
    runner = FakeRunner([ok(decision_dict())])
    res = run(env, runner)
    assert not res.held and res.decision.action == "no_change"
    state = LLMState.load(env[5])
    assert state.count == 1 and state.hold_fallbacks == 0
    kinds = [e["kind"] for e in env[3].tail(20)]
    assert "decision" in kinds and "run_summary" in kinds and "llm_run" in kinds


def test_invalid_then_retry_with_errors(env):
    bad = {"run_type": "daily", "action": "fly_to_moon"}
    runner = FakeRunner([RunResult(ok=True, decision=bad), ok(decision_dict())])
    res = run(env, runner)
    assert not res.held
    assert len(runner.requests) == 2
    assert "rejected by the validator" in runner.requests[1].prompt


def test_always_invalid_falls_back_to_hold(env):
    bad = {"nope": 1}
    runner = FakeRunner([RunResult(ok=True, decision=bad)] * 3)
    res = run(env, runner)
    assert res.held and res.decision.action == "no_change"
    assert LLMState.load(env[5]).hold_fallbacks == 1
    assert len(runner.requests) == 2                       # retries_on_invalid = 1


def test_usage_limited_holds_without_retry(env):
    runner = FakeRunner([RunResult(ok=False, decision=None, usage_limited=True,
                                   error="usage limit reached")])
    res = run(env, runner)
    assert res.held and res.reason == "usage_limited"
    assert len(runner.requests) == 1


def test_daily_invocation_cap(env):
    m, _, _, _, _, state_path = env
    LLMState(day=NOW.date().isoformat(), count=m.llm.daily_invocation_cap).save(state_path)
    runner = FakeRunner([ok(decision_dict())])
    res = run(env, runner)
    assert res.held and "cap" in res.reason
    assert runner.requests == []                           # the model was never invoked


def test_full_trade_path_on_sim(env):
    m, broker, book, journal, executor, state_path = env
    broker.set_quote("QQQ", 99.98, 100.02)
    d = decision_dict(action="rebalance", run_type="weekly", positions=[{
        "symbol": "QQQ", "sleeve": "trend", "target_weight": 0.12,
        "thesis": "momentum breakout hold", "invalidation": "close under 50d",
        "stop_price": 92.0, "confidence": 0.6, "horizon_days": 30,
        "entry_checklist": {"sized_in_window": True, "stop_within_bounds": True,
                            "not_chasing": True, "basis": "trend"}}])
    res = run(env, FakeRunner([ok(d)]), run_type="weekly", quotes={"QQQ": make_quote("QQQ", 100)})
    assert not res.held and res.report is not None and res.report.filled == 1
    assert book.positions["QQQ"].qty == pytest.approx(1.2)
    assert res.bundle_dir and (m.llm.sandbox.runs_root in res.bundle_dir)


def test_bundle_contains_context_files(env):
    res = run(env, FakeRunner([ok(decision_dict())]))
    from pathlib import Path
    files = {p.name for p in Path(res.bundle_dir).iterdir()}
    assert {"SYSTEM.md", "TASK.md", "mandate_excerpt.md", "portfolio.json", "market.json",
            "news_digest.md", "journal_tail.md", "decision_schema.json"} <= files
