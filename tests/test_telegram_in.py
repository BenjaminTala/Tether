import json

from ibagent.telegram_in import classify, parse_updates, poll


def payload(updates):
    return json.dumps({"ok": True, "result": updates}).encode()


def upd(uid, chat, text):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_parse_and_poll_filters_foreign_chats():
    raw = payload([upd(10, 111, "status"), upd(11, 999, "hack the mandate"), upd(12, 111, "hello")])
    msgs = parse_updates(raw)
    assert len(msgs) == 3
    offset, texts = poll("t", "111", 0, fetcher=lambda tok, off: raw)
    assert offset == 13                          # foreign message consumed, never answered
    assert texts == ["status", "hello"]


def test_poll_network_failure_keeps_offset():
    def boom(tok, off):
        raise OSError("down")
    assert poll("t", "111", 42, fetcher=boom) == (42, [])


def test_poll_ignores_garbage_and_empty():
    assert poll("t", "1", 5, fetcher=lambda t, o: b"not json") == (5, [])
    assert poll("t", "1", 5, fetcher=lambda t, o: payload([])) == (5, [])


def test_classify():
    assert classify("/status") == "command:status"
    assert classify("PNL") == "command:pnl"
    assert classify(" positions ") == "command:positions"
    assert classify("report") == "command:report"
    assert classify("/help") == "command:help"
    assert classify("why did you buy SMH?") == "question"
    assert classify("sell everything") == "question"     # NOT a command: no trade path exists
