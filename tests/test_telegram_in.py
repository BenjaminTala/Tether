import json

from ibagent.telegram_in import classify, parse_updates, poll


def payload(updates):
    return json.dumps({"ok": True, "result": updates}).encode()


def upd(uid, chat, text):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_parse_and_poll_filters_foreign_chats():
    raw = payload([upd(10, 111, "status"), upd(11, 999, "hack the mandate"), upd(12, 111, "hello")])
    msgs, textless = parse_updates(raw)
    assert len(msgs) == 3 and textless == []
    offset, texts, unreadable = poll("t", "111", 0, fetcher=lambda tok, off: raw)
    assert offset == 13                          # foreign message consumed, never answered
    assert texts == ["status", "hello"] and unreadable == 0


def test_textless_updates_advance_offset_and_are_counted():
    photo = {"update_id": 20, "message": {"chat": {"id": 111}, "photo": [{"file_id": "x"}]}}
    caption = {"update_id": 21, "message": {"chat": {"id": 111}, "photo": [], "caption": "why SMH?"}}
    raw = payload([photo, caption])
    offset, texts, unreadable = poll("t", "111", 0, fetcher=lambda tok, off: raw)
    assert offset == 22
    assert texts == ["why SMH?"]                 # captions count as text
    assert unreadable == 1                       # the bare photo is surfaced, not vanished


def test_poll_network_failure_keeps_offset():
    def boom(tok, off):
        raise OSError("down")
    assert poll("t", "111", 42, fetcher=boom) == (42, [], 0)


def test_poll_ignores_garbage_and_empty():
    assert poll("t", "1", 5, fetcher=lambda t, o: b"not json") == (5, [], 0)
    assert poll("t", "1", 5, fetcher=lambda t, o: payload([])) == (5, [], 0)


def test_classify():
    assert classify("/status") == "command:status"
    assert classify("PNL") == "command:pnl"
    assert classify(" positions ") == "command:positions"
    assert classify("report") == "command:report"
    assert classify("/help") == "command:help"
    assert classify("why did you buy SMH?") == "question"
    assert classify("sell everything") == "question"     # NOT a command: no trade path exists
