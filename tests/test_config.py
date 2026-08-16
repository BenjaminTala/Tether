import pytest

from ibagent.config import MandateError, load_mandate, mandate_from_dict, parse_override
from tests.conftest import ROOT


def test_repo_mandate_is_valid():
    m = load_mandate(ROOT / "mandate.yaml")
    assert m.mode == "paper" and m.universe.profile == "us"


def test_sizing_scales_with_capital(md):
    m = mandate_from_dict(md)
    # $1k: trend 300 -> 3 positions (cap 4), spec 150 -> 1 position (cap 3)
    assert m.max_positions("trend", 1000) == 3
    assert m.max_positions("spec", 1000) == 1
    # $10k: caps bind
    assert m.max_positions("trend", 10_000) == 4
    assert m.max_positions("spec", 10_000) == 3
    # tiny pot: nothing fits
    assert m.max_positions("spec", 300) == 0
    assert m.is_operating(399) is False and m.is_operating(400) is True


def test_position_cap_floor_and_pct(md):
    m = mandate_from_dict(md)
    # small pot: USD floor rules (spec 6% of 1000 = 60 < 100 floor), never above sleeve equity (150)
    assert m.position_cap_usd("spec", 1000) == 100
    # large pot: % rules (6% of 20k = 1200), sleeve equity 3000
    assert m.position_cap_usd("spec", 20_000) == pytest.approx(1200)
    # floor cannot exceed sleeve equity
    assert m.position_cap_usd("spec", 500) == pytest.approx(75)
    assert m.per_trade_risk_usd("trend", 1000) == pytest.approx(10.0)
    assert m.per_trade_risk_usd("trend", 1000, hard_cap=True) == pytest.approx(15.0)


def test_seed_override_and_seed_too_small(md):
    m = mandate_from_dict(md, {"capital.seed_usd": 2500})
    assert m.capital.seed_usd == 2500 and m.max_positions("spec", 2500) == 3
    with pytest.raises(MandateError, match="cannot fund one min_position_usd"):
        mandate_from_dict(md, {"capital.seed_usd": 500})  # spec sleeve 75 < 100 floor
    with pytest.raises(MandateError, match="unknown"):
        mandate_from_dict(md, {"capital.nope": 1})


def test_weights_must_sum_to_one(md):
    md["sleeves"]["cash"]["weight"] = 0.10
    with pytest.raises(MandateError, match="sleeve weights sum"):
        mandate_from_dict(md)


def test_hard_rules_cannot_be_disabled(md):
    md["risk"]["no_averaging_down"] = False
    with pytest.raises(MandateError):
        mandate_from_dict(md)
    md["risk"]["no_averaging_down"] = True
    md["risk"]["stops"]["never_widen"] = False
    with pytest.raises(MandateError):
        mandate_from_dict(md)


def test_llm_tools_must_be_read_only(md):
    md["llm"]["tools"] = ["Read", "Bash"]
    with pytest.raises(MandateError, match="non read-only"):
        mandate_from_dict(md)


def test_port_mode_mismatch(md):
    md["broker"]["port"] = 4001
    with pytest.raises(MandateError, match="LIVE port"):
        mandate_from_dict(md)
    md["broker"]["port"] = 4002
    md["mode"] = "live"
    with pytest.raises(MandateError, match="requires account.ibkr_account_id"):
        mandate_from_dict(md)


def test_never_list_blocks_active_profile(md):
    md["universe"]["never"].append("SPY")
    with pytest.raises(MandateError, match="never-list"):
        mandate_from_dict(md)


def test_universe_lookup_and_profile_switch(md):
    m = mandate_from_dict(md)
    assert m.universe.is_allowed("AAPL", "spec") and not m.universe.is_allowed("SPY", "spec")
    assert not m.universe.is_allowed("TQQQ", "trend")
    inst = m.universe.active.instrument("SPY")
    assert inst.exchange == "SMART" and inst.currency == "USD"
    m2 = mandate_from_dict(md, {"universe.profile": "ucits"})
    assert m2.universe.active.instrument("CSPX").exchange == "LSEETF"
    assert "CSPX" in m2.universe.active.symbols("core")


def test_parse_override_types():
    assert parse_override("capital.seed_usd=2500") == ("capital.seed_usd", 2500)
    assert parse_override("universe.profile=ucits") == ("universe.profile", "ucits")
    assert parse_override("broker.fractional_shares=false") == ("broker.fractional_shares", False)
