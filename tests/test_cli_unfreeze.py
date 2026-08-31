"""`ibagent unfreeze`: the owner's remedy for a false reconcile freeze (bold, 2026-08-28)."""
import argparse
from datetime import timedelta

import pytest

from ibagent.book import Book
from ibagent.cli import cmd_unfreeze, main
from tests.conftest import NOW


def _frozen_book(path):
    b = Book(path)
    b.freeze("reconcile mismatch: NVDA book=3.0 broker=0.0 (missing)")
    b.save()
    return b


def test_unfreeze_refuses_while_supervisor_alive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _frozen_book(tmp_path / "data" / "book.json")
    (tmp_path / "data" / "heartbeat.txt").write_text(NOW.isoformat(timespec="seconds"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="running"):
        cmd_unfreeze(argparse.Namespace(shadow=None), now=NOW + timedelta(seconds=30))
    assert Book.load(tmp_path / "data" / "book.json").frozen        # untouched


def test_unfreeze_clears_when_supervisor_stopped(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    shadow = tmp_path / "data-shadows" / "bold"
    shadow.mkdir(parents=True)
    _frozen_book(shadow / "book.json")
    (shadow / "heartbeat.txt").write_text((NOW - timedelta(minutes=10)).isoformat(timespec="seconds"),
                                          encoding="utf-8")
    assert cmd_unfreeze(argparse.Namespace(shadow="bold"), now=NOW) == 0
    assert "unfrozen" in capsys.readouterr().out
    b = Book.load(shadow / "book.json")
    assert not b.frozen and b.frozen_reason == ""
    assert cmd_unfreeze(argparse.Namespace(shadow="bold"), now=NOW) == 0     # idempotent


def test_unfreeze_via_main_without_heartbeat_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _frozen_book(tmp_path / "data" / "book.json")
    assert main(["unfreeze"]) == 0
    assert not Book.load(tmp_path / "data" / "book.json").frozen


def test_unfreeze_writes_a_journal_record(tmp_path, monkeypatch):
    """2026-08-31: bold turned up unfrozen and nothing in its journal said when or by whom.
    An owner unfreeze must leave a trace next to the freeze it clears."""
    import json
    monkeypatch.chdir(tmp_path)
    shadow = tmp_path / "data-shadows" / "bold"
    shadow.mkdir(parents=True)
    _frozen_book(shadow / "book.json")
    assert cmd_unfreeze(argparse.Namespace(shadow="bold"), now=NOW) == 0
    lines = [json.loads(l) for p in sorted((shadow / "journal").glob("*.jsonl"))
             for l in p.read_text(encoding="utf-8").splitlines()]
    rec = [l for l in lines if l["kind"] == "unfreeze"]
    assert len(rec) == 1 and "reconcile mismatch" in rec[0]["payload"]["was"]
