import pytest

from ibagent.fees import estimate_commission, fee_pct


def test_tiered_minimum_and_passthrough():
    # 0.25 shares of a $100 ETF: 0.35 min + 0.0032*0.25 pass-through
    assert estimate_commission("tiered", 0.25, 100, "BUY") == pytest.approx(0.35, abs=0.005)
    # 1000 shares @ $50: 3.50 + 3.20 = 6.70, sells add TAF 0.166
    assert estimate_commission("tiered", 1000, 50, "BUY") == pytest.approx(6.70, abs=0.01)
    assert estimate_commission("tiered", 1000, 50, "SELL") == pytest.approx(6.87, abs=0.01)


def test_tiered_one_percent_cap_on_per_share_component():
    # 10,000 shares @ $0.50 => 0.0035*10000 = 35 > 1% of 5000 = 50? no, 35 < 50 -> 35 + 32 pass-through
    assert estimate_commission("tiered", 10_000, 0.5, "BUY") == pytest.approx(67.0, abs=0.01)
    # 20,000 shares @ $0.20 => 70 capped at 1% of 4000 = 40, + 64 pass-through
    assert estimate_commission("tiered", 20_000, 0.2, "BUY") == pytest.approx(104.0, abs=0.01)


def test_fixed_and_lite():
    assert estimate_commission("fixed", 0.5, 100, "BUY") == 1.00      # $1 minimum bites on tiny orders
    assert estimate_commission("fixed", 400, 50, "BUY") == 2.00       # 0.005*400
    assert estimate_commission("lite", 100, 50, "BUY") == 0.0
    assert estimate_commission("lite", 100, 50, "SELL") == pytest.approx(0.02, abs=0.005)


def test_fee_pct_flags_small_orders():
    assert fee_pct("fixed", 0.5, 100, "BUY") == pytest.approx(2.0)     # 2% of a $50 order
    assert fee_pct("tiered", 1.0, 100, "BUY") == pytest.approx(0.35, abs=0.01)
    with pytest.raises(ValueError):
        estimate_commission("tiered", 0, 100, "BUY")
    with pytest.raises(ValueError):
        estimate_commission("nope", 1, 100, "BUY")  # type: ignore[arg-type]
