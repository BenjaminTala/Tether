"""LLM runner: invokes Claude Code headless (`claude -p`) on the Max subscription — no API key.

Safety properties enforced here (independent of the prompt):
  * cwd = a per-run bundle directory OUTSIDE the repo, containing only what the model may read
  * `--tools` restricts which tools exist (read-only set), `--allowedTools` pre-approves them,
    `--permission-mode dontAsk` refuses everything else; a `.claude/settings.json` in the bundle
    mirrors this and scopes WebFetch to an allowlist of domains
  * child environment is minimal; ANTHROPIC_* is always dropped (never bill an API key)
  * `--max-turns` + a hard timeout bound usage; the result is either a JSON object or a failure —
    the caller turns failures into HOLD
  * `--bare` is deliberately NOT used: it requires API-key auth
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

from ibagent.common import RunType
from ibagent.config import LLMCfg

_USAGE_LIMIT_RE = re.compile(
    r"(usage limit|rate limit|too many requests|out of (usage|credits)|overloaded|quota|"
    r"limit (has been )?reached|try again (later|in))", re.I)
_UNKNOWN_FLAG_RE = re.compile(r"(unknown|unrecognized|invalid) (option|argument|flag)", re.I)
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_WIN_KEEP = ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATH", "PATHEXT", "COMSPEC", "USERPROFILE",
             "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
             "PROGRAMFILES(X86)", "TEMP", "TMP", "USERNAME", "USERDOMAIN", "NUMBER_OF_PROCESSORS",
             "PROCESSOR_ARCHITECTURE", "OS")
_POSIX_KEEP = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "SHELL", "TERM")
_KEEP_PREFIXES = ("CLAUDE_",)          # Claude Code's own config vars (e.g. CLAUDE_CONFIG_DIR)
_DROP_PREFIXES = ("ANTHROPIC_",)       # never pass an API key/token: subscription only


@dataclass
class RunRequest:
    run_type: RunType
    bundle_dir: Path
    prompt: str
    system_prompt_file: Optional[Path] = None


@dataclass
class RunResult:
    ok: bool
    decision: Optional[Dict[str, Any]]
    text: str = ""
    error: Optional[str] = None
    usage_limited: bool = False
    session_id: Optional[str] = None
    duration_s: float = 0.0
    returncode: Optional[int] = None
    raw_stdout: str = ""
    raw_stderr: str = ""
    cmd: List[str] = field(default_factory=list)


class LLMRunner(Protocol):
    def run(self, req: RunRequest) -> RunResult: ...


# ----------------------------------------------------------------------------- helpers (pure, tested)


def resolve_claude_bin(name: str) -> str:
    """Absolute path to the Claude Code CLI. On Windows prefer claude.exe (native installer) over
    claude.cmd (npm shim) so no cmd.exe quoting is involved."""
    p = Path(name)
    if p.is_absolute():
        if not p.exists():
            raise FileNotFoundError(f"claude binary not found: {name}")
        return str(p)
    candidates = [name]
    if os.name == "nt" and not name.lower().endswith((".exe", ".cmd", ".bat")):
        candidates = [name + ".exe", name, name + ".cmd"]
    for c in candidates:
        found = shutil.which(c)
        if found:
            return found
    raise FileNotFoundError(f"'{name}' not on PATH; install Claude Code and run `claude` once to log in")


def build_command(claude_bin: str, cfg: LLMCfg, run_type: RunType, schema_text: Optional[str],
                  system_prompt_file: Optional[Path]) -> List[str]:
    tools = list(cfg.tools)
    allowed = _allowed_rules(tools, cfg.sandbox.webfetch_domains)
    cmd = [claude_bin, "-p", "--output-format", "json",
           "--tools", ",".join(tools), "--allowedTools", ",".join(allowed),
           "--permission-mode", cfg.permission_mode, "--max-turns", str(cfg.max_turns[run_type])]
    if schema_text:
        cmd += ["--json-schema", schema_text]
    if cfg.model:
        cmd += ["--model", cfg.model]
    if system_prompt_file:
        cmd += ["--append-system-prompt-file", str(system_prompt_file)]
    return cmd


def _allowed_rules(tools: Sequence[str], webfetch_domains: Sequence[str]) -> List[str]:
    rules: List[str] = []
    for t in tools:
        if t == "WebFetch" and webfetch_domains:
            rules += [f"WebFetch(domain:{d})" for d in webfetch_domains]
        else:
            rules.append(t)
    return rules


def sandbox_settings(cfg: LLMCfg) -> Dict[str, Any]:
    """Project-level Claude Code settings written into every bundle (defense in depth)."""
    deny = ["Bash", "Edit", "Write", "NotebookEdit", "Task"] + [f"Read({g})" for g in cfg.sandbox.deny_read_globs]
    # WebFetch is scoped to allowlisted domains via allow rules; dontAsk refuses everything else.
    return {
        "permissions": {
            "defaultMode": cfg.permission_mode,
            "allow": _allowed_rules(cfg.tools, cfg.sandbox.webfetch_domains),
            "deny": deny,
        },
        "enableAllProjectMcpServers": False,
    }


def scrubbed_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    src = dict(os.environ if base is None else base)
    keep = _WIN_KEEP if os.name == "nt" else _POSIX_KEEP
    out: Dict[str, str] = {}
    for k, v in src.items():
        ku = k.upper()
        if ku.startswith(_DROP_PREFIXES):
            continue
        if ku in keep or ku.startswith(_KEEP_PREFIXES):
            out[k] = v
    return out


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Fallback when structured_output is absent: last fenced JSON block, else outermost {...}."""
    if not text:
        return None
    for candidate in reversed(_FENCE_RE.findall(text)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_claude_output(stdout: str, stderr: str, returncode: int) -> RunResult:
    envelope: Optional[Dict[str, Any]] = None
    text = stdout.strip()
    try:
        obj = json.loads(text) if text else None
        if isinstance(obj, dict):
            envelope = obj
    except json.JSONDecodeError:
        # stream-ish or noisy stdout: keep the last JSON object line if any
        for line in reversed(text.splitlines()):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "result" in obj:
                    envelope = obj
                    break
            except json.JSONDecodeError:
                continue
    result_text = ""
    structured: Optional[Dict[str, Any]] = None
    is_error = returncode != 0
    session_id = None
    if envelope is not None:
        r = envelope.get("result")
        result_text = r if isinstance(r, str) else json.dumps(r) if r is not None else ""
        so = envelope.get("structured_output")
        structured = so if isinstance(so, dict) else None
        session_id = envelope.get("session_id")
        is_error = is_error or bool(envelope.get("is_error")) or str(envelope.get("subtype", "")).startswith("error")
    else:
        result_text = text
    decision = structured or extract_json_object(result_text)
    usage_limited = bool(_USAGE_LIMIT_RE.search(result_text + "\n" + stderr))
    ok = (not is_error) and decision is not None
    error = None
    if not ok:
        error = "usage/rate limited" if usage_limited else (
            f"exit={returncode}: {stderr.strip()[-500:] or result_text[-500:] or 'no output'}")
    return RunResult(ok=ok, decision=decision, text=result_text, error=error, usage_limited=usage_limited,
                     session_id=session_id, returncode=returncode, raw_stdout=stdout, raw_stderr=stderr)


# ----------------------------------------------------------------------------- runner


class ClaudeCodeRunner:
    def __init__(self, cfg: LLMCfg, schema_text: Optional[str], claude_bin: Optional[str] = None):
        self.cfg = cfg
        self.schema_text = schema_text
        self._bin = claude_bin or resolve_claude_bin(cfg.claude_bin)
        self._schema_supported = True

    def prepare_bundle(self, bundle_dir: Path) -> None:
        """Write the sandbox settings into the bundle. Call after the context files are written."""
        bundle_dir.mkdir(parents=True, exist_ok=True)
        cdir = bundle_dir / ".claude"
        cdir.mkdir(exist_ok=True)
        (cdir / "settings.json").write_text(json.dumps(sandbox_settings(self.cfg), indent=2), encoding="utf-8")

    def run(self, req: RunRequest) -> RunResult:
        self.prepare_bundle(req.bundle_dir)
        schema = self.schema_text if self._schema_supported else None
        result = self._invoke(req, schema)
        # Older CLIs without --json-schema: retry once without it and parse the text result.
        if not result.ok and schema and result.raw_stderr and "json-schema" in result.raw_stderr \
                and _UNKNOWN_FLAG_RE.search(result.raw_stderr):
            self._schema_supported = False
            result = self._invoke(req, None)
        return result

    def _invoke(self, req: RunRequest, schema: Optional[str]) -> RunResult:
        cmd = build_command(self._bin, self.cfg, req.run_type, schema, req.system_prompt_file)
        env = scrubbed_env() if self.cfg.sandbox.scrub_env else dict(os.environ)
        started = time.monotonic()
        try:
            proc = subprocess.run(cmd, cwd=str(req.bundle_dir), input=req.prompt, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", env=env,
                                  timeout=self.cfg.timeout_seconds[req.run_type], shell=False)
            res = parse_claude_output(proc.stdout, proc.stderr, proc.returncode)
        except subprocess.TimeoutExpired as exc:
            res = RunResult(ok=False, decision=None, error=f"timeout after {exc.timeout:.0f}s",
                            raw_stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                            raw_stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "")
        except (OSError, ValueError) as exc:  # binary vanished, bad args (e.g. cmd.exe quoting)
            res = RunResult(ok=False, decision=None, error=f"spawn failed: {exc}")
        res.duration_s = round(time.monotonic() - started, 2)
        res.cmd = cmd
        return res


class FakeRunner:
    """Deterministic runner for tests and dry runs: returns canned decisions in order."""

    def __init__(self, results: List[RunResult]):
        self._results = list(results)
        self.requests: List[RunRequest] = []

    def run(self, req: RunRequest) -> RunResult:
        self.requests.append(req)
        if not self._results:
            return RunResult(ok=False, decision=None, error="fake runner exhausted")
        return self._results.pop(0)


def default_runs_root(configured: str) -> Path:
    """Runs live OUTSIDE the repo so Claude Code discovers no CLAUDE.md/.mcp.json above the bundle."""
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ibagent" / "runs"
    return Path.home() / ".local" / "share" / "ibagent" / "runs"
