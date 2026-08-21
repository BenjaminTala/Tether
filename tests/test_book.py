from datetime import date, datetime, timedelta, timezone

import pytest

from ibagent.book import Book, BookError
from ibagent.broker.base import Fill, Position
from tests.conftest import NOW, TODAY, make_book


def fill(symbol, side, qty, price, comm=0.35, ts=NOW, tag="t"):
    return Fill(broker_order_id="1", client_tag=tag, symbol=symbol, side=side,
                qty=qty, price=price, commission=comm, ts=ts)


def test_contribution_and_withdrawal_flow(tmp_path):
    b = make_book(tmp_path, 1000)
    assert b.pot_cash == 1000 and b.settled_pot_cash(TODAY) == 1000
    b.request_withdrawal(200)
    assert b.deployable_cash(TODAY) == 800
    b.payout_withdrawal(200, TODAY)
    assert b.pot_cash == 800 and b.pending_withdrawal_usd == 0
    with pytest.raises(BookError):
        b.payout_withdrawal(1, TODAY)


def test_buy_sell_realized_and_settlement(tmp_path):
    b = make_book(tmp_path, 1000)
    meta = {"stop_price": 92.0, "thesis": "t" * 10, "invalidation": "inv"}
    b.apply_fill(fill("QQQ", "BUY", 2, 100, comm=0.5), "trend", entry_meta=meta, counts_as_new=True)
    pos = b.positions["QQQ"]
    assert pos.qty == 2 and pos.avg_cost == pytest.approx(100.25)      # commission capitalised
    assert b.pot_cash == pytest.approx(1000 - 200.5)
    assert b.week_new_positions == 1 and b.week_turnover_usd == pytest.approx(200)

    realized = b.apply_fill(fill("QQQ", "SELL", 2, 110, comm=0.5), "trend")
    assert realized == pytest.approx((110 - 100.25) * 2 - 0.5)
    assert "QQQ" not in b.positions
    # proceeds in pot_cash immediately but unsettled until T+1 trading day
    assert b.pot_cash == pytest.approx(1000 - 200.5 + 219.5)
    assert b.settled_pot_cash(TODAY) == pytest.approx(1000 - 200.5)
    assert b.settled_pot_cash(TODAY + timedelta(days=1)) == pytest.approx(b.pot_cash)


def test_sell_more_than_held_raises(tmp_path):
    b = make_book(tmp_path, 1000)
    b.apply_fill(fill("SPY", "BUY", 1, 100), "trend", entry_meta={}, counts_as_new=True)
    with pytest.raises(BookError):
        b.apply_fill(fill("SPY", "SELL", 2, 100), "trend")


def test_sleeve_mismatch_raises(tmp_path):
    b = make_book(tmp_path, 1000)
    b.apply_fill(fill("AAPL", "BUY", 1, 100), "trend", entry_meta={}, counts_as_new=True)
    with pytest.raises(BookError):
        b.apply_fill(fill("AAPL", "BUY", 1, 100), "spec")


def test_spec_loser_streak_and_sweep_counter(tmp_path):
    b = make_book(tmp_path, 1000)
    for i, exit_price in enumerate([95, 90]):                          # two losers
        sym = f"S{i}"
        b.apply_fill(fill(sym, "BUY", 1, 100), "spec", entry_meta={}, counts_as_new=True)
        b.apply_fill(fill(sym, "SELL", 1, exit_price), "spec")
    assert b.consecutive_spec_losers == 2
    b.apply_fill(fill("W", "BUY", 1, 100), "spec", entry_meta={}, counts_as_new=True)
    b.apply_fill(fill("W", "SELL", 1, 130), "spec")                    # winner resets
    assert b.consecutive_spec_losers == 0
    # per trade: avg_cost = 100.35 (buy comm capitalised), sell comm 0.35
    assert b.spec_profit_since_sweep == pytest.approx(-5.70 - 10.70 + 29.30, abs=0.01)


def test_tighten_stop_never_widens(tmp_path):
    b = make_book(tmp_path, 1000)
    b.apply_fill(fill("SPY", "BUY", 1, 100), "trend",
                 entry_meta={"stop_price": 92.0}, counts_as_new=True)
    assert b.tighten_stop("SPY", 95.0)
    assert not b.tighten_stop("SPY", 93.0)                             # widening refused
    assert b.positions["SPY"].stop_price == 95.0
    assert b.positions["SPY"].initial_stop == 92.0                     # entry stop preserved


def test_cooldown(tmp_path):
    b = make_book(tmp_path, 1000)
    b.record_stop_out("NVDA", TODAY, 5)
    assert b.in_cooldown("NVDA", TODAY)
    assert b.in_cooldown("NVDA", TODAY + timedelta(days=6))            # 5 trading days > 6 calendar? depends
    assert not b.in_cooldown("NVDA", TODAY + timedelta(days=30))
    b.prune_cooldowns(TODAY + timedelta(days=30))
    assert b.cooldowns == {}


def test_equity_hwm_drawdown_and_missing_price(tmp_path):
    b = make_book(tmp_path, 1000)
    b.apply_fill(fill("VTI", "BUY", 2, 100), "core", entry_meta={}, counts_as_new=False)
    snap = b.equity({"VTI": 110}, NOW)
    assert snap.equity == pytest.approx(b.pot_cash + 220, abs=0.01)
    b.update_hwm(snap)
    lower = b.equity({"VTI": 90}, NOW)
    assert b.drawdown(lower) > 0
    # sleeve give-back is P&L-based: at the 110 mark core P&L peaked at (220 - basis);
    # at 90 it fell by 2 shares x $20 -> $40 given back
    assert b.sleeve_giveback_usd(lower, "core") == pytest.approx(40.0, abs=0.1)
    # a protective EXIT must not register as sleeve drawdown
    b2 = make_book(tmp_path / "b2", 1000)
    b2.apply_fill(fill("QQQ", "BUY", 2, 100), "trend", entry_meta={}, counts_as_new=True)
    s0 = b2.equity({"QQQ": 100}, NOW)
    b2.update_hwm(s0)
    b2.apply_fill(fill("QQQ", "SELL", 2, 100.4), "trend")   # exit near flat
    s1 = b2.equity({}, NOW)
    assert b2.sleeve_giveback_usd(s1, "trend") < 5          # value halved, P&L did not
    with pytest.raises(BookError):
        b.equity({}, NOW)                                              # fail closed on missing price


def test_day_week_rollovers(tmp_path):
    b = make_book(tmp_path, 1000)
    b.week_turnover_usd, b.week_new_positions = 300.0, 2
    assert not b.ensure_week(TODAY)                                    # same week
    assert b.ensure_week(TODAY + timedelta(days=7))
    assert b.week_turnover_usd == 0.0 and b.week_new_positions == 0
    b.ensure_day(TODAY + timedelta(days=1), 950)
    assert b.daily_loss_pct(902.5) == pytest.approx(0.05)
    assert b.daily_loss_pct(960) == 0.0


def test_reconcile_shared_vs_dedicated(tmp_path):
    b = make_book(tmp_path, 1000)
    b.apply_fill(fill("SPY", "BUY", 2, 100), "trend", entry_meta={}, counts_as_new=True)
    # shared: broker holding MORE of SPY (human also owns some) is fine; other symbols ignored
    ok = b.reconcile([Position("SPY", 5, 100), Position("AAPL", 3, 50)], dedicated=False)
    assert ok == []
    # shared: broker missing our shares -> mismatch
    bad = b.reconcile([Position("SPY", 1, 100)], dedicated=False)
    assert len(bad) == 1 and bad[0].kind == "short"
    # dedicated: exact match required, extras flagged
    bad2 = b.reconcile([Position("SPY", 5, 100), Position("AAPL", 3, 50)], dedicated=True)
    kinds = sorted(m.kind for m in bad2)
    assert kinds == ["extra", "extra"]


def test_save_load_roundtrip(tmp_path):
    b = make_book(tmp_path, 1000)
    b.apply_fill(fill("SPY", "BUY", 1.5, 100), "trend",
                 entry_meta={"stop_price": 92.0, "thesis": "breakout hold"}, counts_as_new=True)
    b.record_stop_out("NVDA", TODAY, 5)
    b.pause_sleeve("spec", TODAY + timedelta(days=30))
    b.freeze("test freeze")
    b.save()
    b2 = Book.load(b.path)
    assert b2.positions["SPY"].qty == 1.5
    assert b2.positions["SPY"].stop_price == 92.0
    assert b2.frozen and b2.frozen_reason == "test freeze"
    assert b2.pot_cash == pytest.approx(b.pot_cash)
    assert b2.cooldowns == b.cooldowns and b2.paused_sleeves == b.paused_sleeves


def test_load_corrupt_file_fails_closed(tmp_path):
    p = tmp_path / "book.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(BookError):
        Book.load(p)
