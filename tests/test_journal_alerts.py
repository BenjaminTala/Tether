from datetime import datetime, timedelta, timezone

from ibagent.alerts import Alert, Alerter
from ibagent.journal import Journal


def test_journal_roundtrip_and_blob(tmp_path):
    j = Journal(tmp_path / "journal")
    t0 = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    j.record("decision", {"a": 1}, ts=t0)
    j.record("order", {"b": 2}, ts=t0 + timedelta(minutes=1))
    j.record("decision", {"c": 3}, ts=t0 + timedelta(days=20))
    (tmp_path / "journal" / "2026-08.jsonl").open("a").write("{torn\n")
    assert [e["payload"] for e in j.iter(kinds={"decision"})] == [{"a": 1}, {"c": 3}]
    assert len(list(j.iter(since=t0 + timedelta(minutes=1)))) == 2
    assert j.tail(1)[0]["payload"] == {"c": 3}
    p = j.save_blob("run:2026-08-17/weekly.txt", "raw")
    assert p.name == "run_2026-08-17_weekly.txt" and p.read_text() == "raw"


class _Sink:
    def __init__(self, fail=False): self.sent, self.fail = [], fail
    def send(self, alert: Alert):
        if self.fail: raise RuntimeError("boom")
        self.sent.append(alert)


def test_alerter_dedupe_and_sink_failure():
    ok, bad = _Sink(), _Sink(fail=True)
    a = Alerter([bad, ok], dedupe_s=600)
    assert a.warning("stale data", "x") is True
    assert a.warning("stale data", "x") is False   # deduped
    assert a.critical("halt", "y") is True
    assert a.critical("halt", "y") is True         # critical never deduped
    assert len(ok.sent) == 3 and a.failures == 3
