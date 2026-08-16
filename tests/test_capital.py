import json

import pytest

from ibagent.capital import CapitalLedger, LedgerError


def test_ledger_lifecycle(tmp_path):
    led = CapitalLedger(tmp_path / "cap.jsonl")
    assert not led.is_initialized() and led.net_contributions() == 0
    with pytest.raises(LedgerError, match="not initialized"):
        led.add(100)
    led.init_seed(1000, note="start")
    with pytest.raises(LedgerError, match="already initialized"):
        led.init_seed(5)
    led.add(500)
    led.withdraw(300)
    assert led.seed() == 1000
    assert led.net_contributions() == 1200
    assert [e.kind for e in led.events()] == ["seed", "add", "withdraw"]


def test_ledger_rejects_bad_input(tmp_path):
    led = CapitalLedger(tmp_path / "cap.jsonl")
    with pytest.raises(LedgerError):
        led.init_seed(0)
    with pytest.raises(LedgerError):
        led.init_seed(-5)
    led.init_seed(1000)
    with pytest.raises(LedgerError, match="only humans"):
        led.add(10, by="engine")


def test_ledger_detects_corruption(tmp_path):
    p = tmp_path / "cap.jsonl"
    p.write_text(json.dumps({"ts": "x", "kind": "add", "amount_usd": 5}) + "\n")
    with pytest.raises(LedgerError, match="start with exactly one seed"):
        CapitalLedger(p).events()
    p.write_text("not json\n")
    with pytest.raises(LedgerError, match="not JSON"):
        CapitalLedger(p).events()
