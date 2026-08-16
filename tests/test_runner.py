import json
from pathlib import Path

from ibagent.config import mandate_from_dict
from ibagent.llm.runner import (FakeRunner, RunRequest, RunResult, build_command, extract_json_object,
                                parse_claude_output, sandbox_settings, scrubbed_env)


def _cfg(md):
    return mandate_from_dict(md).llm


def test_build_command_flags(md):
    cfg = _cfg(md)
    cmd = build_command("/usr/bin/claude", cfg, "weekly", '{"type":"object"}', Path("/tmp/sys.md"))
    assert cmd[:2] == ["/usr/bin/claude", "-p"]
    assert "--bare" not in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert cmd[cmd.index("--max-turns") + 1] == "25"
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob,WebSearch,WebFetch"
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "WebFetch(domain:sec.gov)" in allowed and ",WebFetch," not in f",{allowed},"
    assert "--json-schema" in cmd and "--append-system-prompt-file" in cmd


def test_sandbox_settings_deny_write_tools(md):
    md["llm"]["sandbox"]["deny_read_globs"] = ["//C:/Users/me/ibkr-agent/**"]
    s = sandbox_settings(_cfg(md))
    assert {"Bash", "Edit", "Write"} <= set(s["permissions"]["deny"])
    assert "Read(//C:/Users/me/ibkr-agent/**)" in s["permissions"]["deny"]
    assert s["permissions"]["defaultMode"] == "dontAsk"
    assert s["enableAllProjectMcpServers"] is False


def test_scrubbed_env_drops_api_keys():
    env = scrubbed_env({"PATH": "/bin", "HOME": "/h", "ANTHROPIC_API_KEY": "sk-x", "TELEGRAM_BOT_TOKEN": "t",
                        "CLAUDE_CONFIG_DIR": "/c", "USERPROFILE": "C:/u"})
    assert "ANTHROPIC_API_KEY" not in env and "TELEGRAM_BOT_TOKEN" not in env
    assert env["PATH"] == "/bin" and env["CLAUDE_CONFIG_DIR"] == "/c"


def test_parse_structured_output():
    envelope = {"type": "result", "subtype": "success", "is_error": False, "result": "done",
                "structured_output": {"action": "no_change"}, "session_id": "abc"}
    r = parse_claude_output(json.dumps(envelope), "", 0)
    assert r.ok and r.decision == {"action": "no_change"} and r.session_id == "abc"


def test_parse_fenced_fallback_and_errors():
    envelope = {"type": "result", "subtype": "success", "result": "Here:\n```json\n{\"a\": 1}\n```\nbye"}
    r = parse_claude_output(json.dumps(envelope), "", 0)
    assert r.ok and r.decision == {"a": 1}
    r2 = parse_claude_output(json.dumps({"type": "result", "subtype": "error_max_turns", "result": "{\"a\":1}"}), "", 0)
    assert not r2.ok and r2.error
    r3 = parse_claude_output("", "You have hit your usage limit. Try again later.", 1)
    assert not r3.ok and r3.usage_limited and r3.error == "usage/rate limited"


def test_extract_json_object_edge_cases():
    assert extract_json_object("") is None
    assert extract_json_object("no braces") is None
    assert extract_json_object("x {\"k\": [1,2]} y") == {"k": [1, 2]}
    assert extract_json_object("```json\n{\"a\":1}\n``` ```json\n{\"b\":2}\n```") == {"b": 2}


def test_fake_runner_records_requests(tmp_path):
    fr = FakeRunner([RunResult(ok=True, decision={"x": 1})])
    req = RunRequest(run_type="daily", bundle_dir=tmp_path, prompt="go")
    assert fr.run(req).ok and fr.requests == [req]
    assert not fr.run(req).ok
