"""Property tests: for ARBITRARY (adversarial) decisions and book states, plan_orders can
never emit an order that breaches the mandate. Seeded RNG — failures reproduce exactly."""
import random

import pytest

from ibagent.broker.base import Fill
from ibagent.fees import estimate_commission
from ibagent.risk import open_risk_usd, plan_orders
from ibagent.schemas import Decision, PositionIntent, StopUpdate
from tests.conftest import NOW, TODAY, make_book, make_quote

ACTIVE_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "GLD", "AAPL", "MSFT", "NVDA", "TSLA", "AMD"]
BAD_SYMBOLS = ["FAKE", "TQQQ", "UVXY", "ZZZZ"]
EPS = 0.05


def random_state(rng, mandate, tmp_path):
    cash = rng.uniform(200, 8000)
    book = make_book(tmp_path, cash)
    prices = {}
    for sym in rng.sample(ACTIVE_SYMBOLS, rng.randint(0, 4)):
        sleeve = "spec" if (sym in ("TSLA", "AMD") or rng.random() < 0.3) else "trend"
        if not mandate.universe.is_allowed(sym, sleeve):
            sleeve = "trend" if mandate.universe.is_allowed(sym, "trend") else "spec"
        price = rng.uniform(20, 500)
        qty = round(rng.uniform(0.1, min(3.0, cash * 0.2 / price)), 4)
        if qty <= 0:
            continue
        stop = round(price * rng.uniform(0.80, 0.97), 2) if rng.random() < 0.8 else None
        try:
            book.apply_fill(Fill("1", "t", sym, "BUY", qty, price, 0.35, NOW), sleeve,
                            entry_meta={"stop_price": stop, "stop_order_tag": f"stp-{sym}"},
                            counts_as_new=True)
        except Exception:
            continue
        prices[sym] = round(price * rng.uniform(0.85, 1.2), 2)
    book.week_new_positions = rng.randint(0, 4)
    book.week_turnover_usd = rng.uniform(0, 600)
    if rng.random() < 0.2:
        book.record_stop_out(rng.choice(ACTIVE_SYMBOLS), TODAY, 5)
    if rng.random() < 0.15:
        book.pause_sleeve(rng.choice(["trend", "spec"]), TODAY)
    return book, prices


def random_decision(rng, prices):
    n = rng.randint(0, 6)
    positions, used = [], set()
    for _ in range(n):
        sym = rng.choice(ACTIVE_SYMBOLS + BAD_SYMBOLS)
        if sym in used:
            continue
        used.add(sym)
        price = prices.get(sym, rng.uniform(20, 500))
        stop = round(price * rng.uniform(0.5, 1.1), 2) if rng.random() < 0.8 else None
        if stop is not None and stop <= 0:
            stop = None
        positions.append(PositionIntent(
            symbol=sym, sleeve=rng.choice(["trend", "spec"]),
            target_weight=round(rng.uniform(0.01, 0.5), 3),
            thesis="randomized adversarial thesis", invalidation="random invalidation",
            stop_price=stop, target_price=None, confidence=rng.random(),
            horizon_days=rng.randint(1, 90)))
    stops = [StopUpdate(symbol=rng.choice(ACTIVE_SYMBOLS), stop_price=round(rng.uniform(1, 600), 2),
                        reason="random stop move") for _ in range(rng.randint(0, 2))]
    try:
        return Decision(run_type="weekly", action="rebalance", market_regime="neutral",
                        risk_multiplier=round(rng.random(), 2), positions=positions,
                        stop_updates=stops, notes_for_human="prop test")
    except Exception:
        return None


@pytest.mark.parametrize("seed", range(40))
def test_no_order_can_breach_the_mandate(mandate, tmp_path, seed):
    rng = random.Random(seed)
    book, price_moves = random_state(rng, mandate, tmp_path)
    decision = random_decision(rng, price_moves)
    if decision is None:
        return
    quotes = {}
    for sym in set(list(book.positions) + [p.symbol for p in decision.positions]
                   + [s.symbol for s in decision.stop_updates]):
        quotes[sym] = make_quote(sym, price_moves.get(sym, round(rng.uniform(20, 500), 2)))
    atrs = {sym: quotes[sym].last * rng.uniform(0.01, 0.05) for sym in quotes if rng.random() < 0.7}

    pre_positions = {s: p.qty for s, p in book.positions.items()}
    pre_stops = {s: p.stop_price for s, p in book.positions.items()}
    deployable = book.deployable_cash(TODAY)
    marks = {s: q.mid for s, q in quotes.items()}
    pre_open_risk = open_risk_usd(book, marks)

    plan = plan_orders(mandate, book, quotes, atrs, decision, NOW)

    if plan.hold:
        assert plan.orders == [] and plan.stop_instructions == []
        return

    buys = [o for o in plan.orders if o.req.side == "BUY"]
    sells = [o for o in plan.orders if o.req.side == "SELL"]

    # exits always precede entries
    first_buy = next((i for i, o in enumerate(plan.orders) if o.req.side == "BUY"), len(plan.orders))
    assert all(o.req.side == "SELL" for o in plan.orders[:first_buy])

    seen = set()
    for o in plan.orders:
        assert o.req.qty > 0 and o.req.limit_price and o.req.limit_price > 0
        key = (o.req.symbol, o.req.side)
        assert key not in seen, "duplicate order for same symbol/side"
        seen.add(key)

    total_cost, new_count, added_risk = 0.0, 0, 0.0
    for o in buys:
        sym, sleeve = o.req.symbol, o.sleeve
        mark = marks[sym]
        # 1. whitelist, incl. never-list
        assert mandate.universe.is_allowed(sym, sleeve), f"BUY of non-whitelisted {sym}"
        # 2. sleeve pause / cooldown / averaging down
        assert not book.is_sleeve_paused(sleeve, TODAY)
        if sym not in pre_positions:
            assert not book.in_cooldown(sym, TODAY)
            new_count += 1
        else:
            assert mark > book.positions[sym].avg_cost, "averaged down"
        # 3. per-position notional cap
        assert o.req.qty * mark <= mandate.position_cap_usd(sleeve, plan.equity) + EPS
        # 4. stop exists, is below market, within mandate distance bounds or tighter
        stop = o.entry_meta["stop_price"]
        assert stop and 0 < stop < mark
        assert stop >= mark * (1 - mandate.risk.stops.max_distance_pct[sleeve]) - EPS \
            or (sym in pre_stops and pre_stops[sym] and stop >= pre_stops[sym] - EPS)
        added_risk += o.req.qty * (mark - stop)
        fee = estimate_commission(mandate.capital.commission_model, o.req.qty, mark, "BUY")
        assert 100 * fee / (o.req.qty * mark) <= mandate.capital.max_fee_pct_per_trade + 0.01
        total_cost += o.req.qty * o.req.limit_price + fee
    # 5. settled-cash: total buy cost never exceeds deployable pot cash
    assert total_cost <= deployable + EPS
    # 6. weekly new-position budget
    assert new_count <= max(0, mandate.risk.max_new_positions_per_week - book.week_new_positions)
    # 7. open-risk cap
    assert pre_open_risk + added_risk <= mandate.risk.max_total_open_risk_pct * plan.equity + EPS \
        or added_risk == 0
    # 8. turnover cap: entry notional fits the remaining weekly budget (after planned sells)
    sell_notional = sum(o.req.qty * o.req.limit_price for o in sells)
    buy_notional = sum(o.req.qty * marks[o.req.symbol] for o in buys)
    budget = mandate.risk.max_turnover_pct_per_week * plan.equity - book.week_turnover_usd - sell_notional
    assert buy_notional <= budget + EPS or not buys
    # 9. sells never exceed the book
    for o in sells:
        assert o.req.qty <= pre_positions.get(o.req.symbol, 0.0) + 1e-6
    # 10. stop instructions: tighten-only for held positions, always below market
    buy_syms = {o.req.symbol for o in buys}
    for s in plan.stop_instructions:
        assert s.stop_price > 0
        if s.symbol in pre_stops and s.symbol not in buy_syms and pre_stops[s.symbol]:
            assert s.stop_price > pre_stops[s.symbol], "stop widened"
            assert s.stop_price < marks[s.symbol]
    # 11. plan never mutates the book
    assert {s: p.qty for s, p in book.positions.items()} == pre_positions
    assert {s: p.stop_price for s, p in book.positions.items()} == pre_stops
