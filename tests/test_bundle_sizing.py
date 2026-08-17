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
