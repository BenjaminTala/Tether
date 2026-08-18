import json

import pytest

from ibagent.schemas import DecisionError, decision_json_schema, hold_decision, parse_decision

CHECKLIST = {"sized_in_window": True, "stop_within_bounds": True, "not_chasing": True,
             "basis": "trend"}
VALID = {
    "schema_version": 1, "run_type": "weekly", "action": "rebalance", "market_regime": "risk_on",
    "risk_multiplier": 1.0,
    "positions": [
        {"symbol": "aapl", "sleeve": "trend", "target_weight": 0.10, "thesis": "Momentum leader after earnings.",
         "invalidation": "Close below 50dma", "stop_price": 180.0, "target_price": 230.0, "confidence": 0.7,
         "horizon_days": 40, "entry_checklist": dict(CHECKLIST)},
        {"symbol": "XLE", "sleeve": "trend", "target_weight": 0.08, "thesis": "Energy relative strength persists.",
         "invalidation": "Oil breaks $65", "confidence": 0.6, "horizon_days": 30,
         "entry_checklist": dict(CHECKLIST, basis="both")},
    ],
    "stop_updates": [{"symbol": "msft", "stop_price": 400.0, "reason": "trail after +2R"}],
    "watchlist": ["nvda", "NVDA", "SPY"],
    "skills_applied": ["market-regime", "trend-selection", "position-sizing", "trade-management",
                       "failure-modes", "news-analysis"],
    "notes_for_human": "Two trend entries; core untouched.",
    "journal_lessons": "Cut spec losers faster.",
}


def test_valid_decision_normalises():
    d = parse_decision(json.dumps(VALID), expected_run_type="weekly")
    assert [p.symbol for p in d.positions] == ["AAPL", "XLE"]
    assert d.stop_updates[0].symbol == "MSFT"
    assert d.watchlist == ["NVDA", "SPY"]
    assert d.total_active_weight == pytest.approx(0.18)


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["positions"].append(dict(d["positions"][0])), "duplicate symbols"),
    (lambda d: d.update(action="no_change"), "must not carry positions"),
    (lambda d: d["positions"][0].update(stop_price=250.0), "stop_price must be below"),
    (lambda d: d["positions"][0].update(target_weight=0.9), "less than or equal to 0.5"),
    (lambda d: d.update(run_type="daily"), "run_type must be 'weekly'"),
    (lambda d: d.update(extra_field=1), "Extra inputs"),
    (lambda d: d.update(risk_multiplier=1.5), "less than or equal to 1"),
    (lambda d: d["positions"][0].pop("entry_checklist"), "entry_checklist"),
    (lambda d: d["positions"][0]["entry_checklist"].update(not_chasing=False), "not_chasing"),
    (lambda d: d.update(skills_applied=["market-regime"]), "skills_applied must include"),
    (lambda d: d.pop("skills_applied"), "skills_applied must include"),
])
def test_invalid_decisions(mutate, msg):
    raw = json.loads(json.dumps(VALID))
    mutate(raw)
    with pytest.raises(DecisionError, match=msg):
        parse_decision(raw, expected_run_type="weekly")


def test_non_json_and_non_object():
    with pytest.raises(DecisionError, match="not valid JSON"):
        parse_decision("{nope")
    with pytest.raises(DecisionError, match="JSON object"):
        parse_decision("[1,2]")


def test_hold_decision_is_valid():
    d = hold_decision("daily", "model unavailable")
    assert d.action == "no_change" and not d.positions and "HOLD" in d.notes_for_human


def test_json_schema_export():
    s = decision_json_schema()
    assert s["type"] == "object"
    for key in ("run_type", "action", "positions", "risk_multiplier", "notes_for_human"):
        assert key in s["properties"]
    assert "PositionIntent" in s["$defs"]
    assert "pattern" not in json.dumps(s)  # keep the schema free of regex for cmd-line safety
