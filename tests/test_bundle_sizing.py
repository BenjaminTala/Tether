"""The mandate excerpt must give the model the EFFECTIVE sizing window at current equity —
the 2026-08-17 weekly run proposed 12% weights that the $150 floor could never accept."""
from ibagent.agent.bundle import mandate_excerpt
from ibagent.config import mandate_from_dict


def test_excerpt_shows_effective_window_at_small_equity(md):
    md["capital"]["min_position_usd"] = 150
    md["risk"]["max_position_weight_pct"] = {"core": 0.35, "trend": 0.18, "spec": 0.06}
    m = mandate_from_dict(md)
    text = mandate_excerpt(m, equity=1000.0)
    assert "SIZING AT CURRENT EQUITY" in text
    assert "$150–$180 per position" in text                 # trend: floor 150, cap max(180,150)
    assert "target_weight 0.15–0.18" in text
    assert "stop distance must be <= 10%" in text           # hard-cap 15 / floor 150


def test_excerpt_flags_unusable_sleeve(md):
    md["capital"]["min_position_usd"] = 150
    m = mandate_from_dict(md)                               # spec cap = max(60,150)=150 = floor -> ok
    text = mandate_excerpt(m, equity=1000.0)
    assert "spec: $150–$150" in text                        # razor-thin but valid window is shown


def test_excerpt_whole_share_warning(md):
    md["broker"]["fractional_shares"] = False
    m = mandate_from_dict(md)
    text = mandate_excerpt(m, equity=1000.0)
    assert "WHOLE SHARES ONLY" in text
    m2 = mandate_from_dict({**md, "broker": {**md["broker"], "fractional_shares": True}})
    assert "WHOLE SHARES" not in mandate_excerpt(m2, equity=1000.0)


def test_excerpt_without_equity_omits_dynamic_block(md):
    m = mandate_from_dict(md)
    assert "SIZING AT CURRENT EQUITY" not in mandate_excerpt(m)


def test_frozen_breaker_is_explained_to_the_model(tmp_path):
    """2026-09-21: main's weekly and daily both wrote 'breakers.frozen=true — not defined
    anywhere in the bundle ... please confirm its meaning'. A frozen book now carries the
    reason and what the engine will do; an unfrozen one carries no note."""
    from ibagent.agent.bundle import degraded_portfolio_json
    from tests.conftest import make_book
    book = make_book(tmp_path)
    assert "frozen_note" not in degraded_portfolio_json(book, "x")["breakers"]
    book.freeze("reconcile mismatch: VTI book=7.0 broker=0.0 (missing)")
    br = degraded_portfolio_json(book, "x")["breakers"]
    assert br["frozen"] is True
    assert "VTI book=7.0" in br["frozen_note"] and "no_change" in br["frozen_note"]


def test_system_prompt_says_the_multiplier_does_not_shrink_a_single_weight():
    """2026-09-21: twin wrote 'one share still fits if the engine applies the 0.5 multiplier'
    and got 2 SPY; scalper computed 4 MRK 'x 0.5' and got 9. risk.plan_orders scales only
    when the TOTAL active weight exceeds cap x multiplier; the prompt now says so."""
    from ibagent.agent.bundle import SYSTEM_MD
    assert "never shrinks an individual `target_weight`" in " ".join(SYSTEM_MD.split())
