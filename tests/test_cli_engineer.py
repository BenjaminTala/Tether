"""`ibagent engineer`: the nightly Telegram carries tonight's report or says there is none
(2026-10-07..09: three runs died on a usage limit and 10-05's report was re-sent each night)."""
import os

from ibagent.cli import _engineer_report, _file_stamp


def test_untouched_report_is_not_resent(tmp_path):
    f = tmp_path / "engineer_report.txt"
    f.write_text("Engineer report - Monday 2026-10-05", encoding="utf-8")
    before = _file_stamp(f)
    assert _engineer_report(f, before) is None


def test_rewritten_report_is_sent(tmp_path):
    f = tmp_path / "engineer_report.txt"
    f.write_text("Engineer report - Monday 2026-10-05", encoding="utf-8")
    before = _file_stamp(f)
    f.write_text("Engineer report - Sunday 2026-10-11", encoding="utf-8")
    os.utime(f, ns=(before[0] + 10**9, before[0] + 10**9))
    assert _engineer_report(f, before) == "Engineer report - Sunday 2026-10-11"


def test_first_report_and_missing_file(tmp_path):
    f = tmp_path / "engineer_report.txt"
    assert _engineer_report(f, _file_stamp(f)) is None
    f.write_text("first", encoding="utf-8")
    assert _engineer_report(f, None) == "first"
