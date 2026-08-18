import json
from pathlib import Path

from ibagent.llm.runner import register_workspace_trust


def test_creates_and_preserves_claude_json(tmp_path):
    cj = tmp_path / ".claude.json"
    cj.write_text(json.dumps({"projects": {"C:/other": {"hasTrustDialogAccepted": True}},
                              "theme": "dark"}), encoding="utf-8")
    bundle = tmp_path / "runs" / "20260818-qa"
    bundle.mkdir(parents=True)
    assert register_workspace_trust(bundle, claude_json=cj)
    data = json.loads(cj.read_text(encoding="utf-8"))
    key = str(bundle.resolve()).replace("\\", "/")
    assert data["projects"][key]["hasTrustDialogAccepted"] is True
    assert data["projects"]["C:/other"]["hasTrustDialogAccepted"] is True   # untouched
    assert data["theme"] == "dark"                                          # untouched
    assert register_workspace_trust(bundle, claude_json=cj)                 # idempotent


def test_missing_file_created(tmp_path):
    cj = tmp_path / ".claude.json"
    bundle = tmp_path / "b"
    bundle.mkdir()
    assert register_workspace_trust(bundle, claude_json=cj)
    assert json.loads(cj.read_text(encoding="utf-8"))["projects"]


def test_corrupt_file_fails_open(tmp_path):
    cj = tmp_path / ".claude.json"
    cj.write_text("{broken", encoding="utf-8")
    bundle = tmp_path / "b"
    bundle.mkdir()
    assert register_workspace_trust(bundle, claude_json=cj) is False
    assert cj.read_text(encoding="utf-8") == "{broken"                      # never clobbered
