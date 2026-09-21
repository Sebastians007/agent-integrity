#!/usr/bin/env python3
"""Deterministic reliability hooks for Claude Code.

State is intentionally split into two axes:
- repository_health: what verification says about the working tree;
- context_health: whether the current reasoning session is accumulating failures.

A pre-existing repository failure therefore does not automatically poison a fresh
reasoning context, and a fresh session does not magically make a broken repo green.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
BASE = ROOT / ".claude" / "integrity"
CONFIG_PATH = BASE / "config.json"
STATE_DIR = ROOT / ".ai-integrity"
STATE_PATH = STATE_DIR / "state.json"
EVIDENCE_PATH = STATE_DIR / "evidence.jsonl"
HANDOFF_PATH = STATE_DIR / "HANDOFF.md"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def config():
    return load_json(CONFIG_PATH, {})


def default_state():
    return {
        "version": 2,
        "session_id": None,
        "session_started_at": None,
        "session_baseline": {},
        "tool_failures": 0,
        "failed_verification_cycles": 0,
        "edits_since_green": 0,
        "last_edit_at": None,
        "last_green_verify_at": None,
        "last_green_commands": [],
        "last_verification_results": [],
        "repository_health": "unverified",
        "context_health": "green",
        # Kept as an alias for v1 consumers.
        "health": "green",
        "events": [],
    }


def state():
    d = default_state()
    old = load_json(STATE_PATH, {})
    d.update(old)
    if "context_health" not in old and "health" in old:
        d["context_health"] = old["health"]
    d["health"] = d.get("context_health", "green")
    d["version"] = 2
    return d


def add_event(st, kind, detail=""):
    st["events"] = (st.get("events") or [])[-99:] + [{
        "time": int(time.time()), "kind": kind, "detail": str(detail)[:1000]
    }]


def _run_git(args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, timeout=10
    )


def git_head():
    try:
        p = _run_git(["rev-parse", "HEAD"])
        return p.stdout.strip() if p.returncode == 0 else None
    except Exception:
        return None


def changed_files():
    """Return actual changed file paths, including every untracked file.

    Avoids directory-collapsed `git status` output by combining diff and
    `git ls-files --others`, so a new directory full of code cannot disappear
    behind one extensionless `?? some-dir/` entry.
    """
    ignores = config().get("ignore_changed_paths", [])
    try:
        tracked = _run_git(["diff", "HEAD", "--name-only", "--relative"])
        untracked = _run_git(["ls-files", "--others", "--exclude-standard"])
        if tracked.returncode != 0:
            # Unborn repo or unusual state: fall back to porcelain with all files.
            p = _run_git(["status", "--porcelain=v1", "--untracked-files=all"])
            raw = []
            if p.returncode == 0:
                for line in p.stdout.splitlines():
                    path = line[3:] if len(line) >= 4 else line
                    if " -> " in path:
                        path = path.split(" -> ", 1)[1]
                    raw.append(path.strip().strip('"'))
        else:
            raw = tracked.stdout.splitlines()
            if untracked.returncode == 0:
                raw.extend(untracked.stdout.splitlines())

        out = []
        seen = set()
        for raw_path in raw:
            path = raw_path.replace("\\", "/").strip()
            if not path or path in seen:
                continue
            if any(path.startswith(x) or x in path for x in ignores):
                continue
            seen.add(path)
            out.append(path)
        return sorted(out)
    except Exception:
        return []


def is_code_change(paths):
    code_ext = {
        ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".rb", ".go",
        ".rs", ".java", ".kt", ".cs", ".php", ".vue", ".svelte", ".sql",
        ".graphql", ".gql", ".yaml", ".yml", ".toml", ".json", ".sh",
        ".bash", ".zsh", ".ps1", ".proto", ".tf", ".hcl",
    }
    names = {"dockerfile", "makefile", "justfile", "gemfile", "rakefile"}
    return any(Path(p).suffix.lower() in code_ext or Path(p).name.lower() in names for p in paths)


def auto_commands(cfg):
    explicit = cfg.get("verification_commands") or []
    if explicit:
        return explicit
    commands = []
    pkg = ROOT / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            runner = "npm run"
            if (ROOT / "pnpm-lock.yaml").exists():
                runner = "pnpm"
            elif (ROOT / "yarn.lock").exists():
                runner = "yarn"
            elif (ROOT / "bun.lockb").exists() or (ROOT / "bun.lock").exists():
                runner = "bun run"
            for name in ["typecheck", "check", "lint", "test"]:
                val = scripts.get(name)
                if not val:
                    continue
                if name == "test" and "no test specified" in str(val).lower():
                    continue
                commands.append(f"{runner} {name}")
        except Exception:
            pass
    if (ROOT / "pyproject.toml").exists() or (ROOT / "pytest.ini").exists():
        if (ROOT / ".venv").exists():
            exe = ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
            commands.append(f'"{exe}" -m pytest -q')
        else:
            commands.append(f'"{sys.executable}" -m pytest -q')
    if (ROOT / "go.mod").exists():
        commands.append("go test ./...")
    if (ROOT / "Cargo.toml").exists():
        commands.append("cargo test --quiet")
    return list(dict.fromkeys(commands))


def _normalize_failure_output(text):
    lines = []
    signal = re.compile(r"(fail|failed|failure|error|exception|panic|assert|traceback|not ok|×|✗)", re.I)
    for line in (text or "").splitlines():
        if signal.search(line):
            line = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds?)\b", "<time>", line, flags=re.I)
            line = re.sub(r"0x[0-9a-f]+", "<addr>", line, flags=re.I)
            lines.append(line.strip())
    if not lines:
        lines = (text or "").splitlines()[-25:]
    return "\n".join(lines[-80:])


def result_fingerprint(result):
    if result.get("ok"):
        return "green"
    material = f"{result.get('command')}\n{result.get('returncode')}\n{_normalize_failure_output(result.get('output', ''))}"
    return hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:20]


def run_verification(cfg):
    results = []
    timeout = int(cfg.get("verification_timeout_seconds", 120))
    for cmd in auto_commands(cfg):
        started = time.time()
        try:
            p = subprocess.run(
                cmd, cwd=ROOT, shell=True, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout
            )
            output = (p.stdout or "")[-12000:]
            result = {
                "command": cmd, "ok": p.returncode == 0, "returncode": p.returncode,
                "seconds": round(time.time() - started, 2), "output": output,
            }
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") if isinstance(e.stdout, str) else ""
            result = {
                "command": cmd, "ok": False, "returncode": None, "seconds": timeout,
                "output": (out + "\nTIMEOUT")[-12000:],
            }
        except Exception as e:
            result = {
                "command": cmd, "ok": False, "returncode": None,
                "seconds": round(time.time() - started, 2), "output": str(e),
            }
        result["fingerprint"] = result_fingerprint(result)
        results.append(result)
    return results


def baseline_result_map(st):
    baseline = st.get("session_baseline") or {}
    return {r.get("command"): r for r in baseline.get("verification_results", [])}


def classify_results(results, st):
    """Classify failures relative to the current session baseline."""
    baseline = baseline_result_map(st)
    classified = []
    for r in results:
        item = dict(r)
        before = baseline.get(r.get("command"))
        if r.get("ok"):
            item["classification"] = "resolved" if before and not before.get("ok") else "passing"
        elif before is None:
            item["classification"] = "unbaselined_failure"
        elif before.get("ok"):
            item["classification"] = "introduced_failure"
        elif before.get("fingerprint") == r.get("fingerprint"):
            item["classification"] = "preexisting_failure"
        else:
            item["classification"] = "changed_failure"
        classified.append(item)
    return classified


def record_verification_evidence(st, phase, results, changed):
    now = int(time.time())
    for idx, r in enumerate(results):
        append_jsonl(EVIDENCE_PATH, {
            "schema": 1,
            "evidence_id": f"ev-{now}-{os.getpid()}-{idx}",
            "time": now,
            "session_id": st.get("session_id"),
            "phase": phase,
            "kind": "verification",
            "command": r.get("command"),
            "ok": r.get("ok"),
            "classification": r.get("classification", "baseline" if phase == "baseline" else None),
            "fingerprint": r.get("fingerprint"),
            "returncode": r.get("returncode"),
            "git_head": git_head(),
            "changed_files": changed,
        })


def emit(obj):
    sys.stdout.write(json.dumps(obj))


def deny_pretool(reason):
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
          "permissionDecision": "deny", "permissionDecisionReason": reason}})


def handle_pretool(data, cfg, st):
    name = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    if name in ("Edit", "Write"):
        fp = str(inp.get("file_path", "")).replace("\\", "/").lower()
        for frag in cfg.get("protected_path_fragments", []):
            if frag.lower().replace("\\", "/") in fp:
                deny_pretool(
                    f"Agent Integrity blocked edit to protected path '{frag}'. "
                    "This deny-list is an accident-prevention rail, not a security boundary. "
                    "Use a safer path or explicitly adjust .claude/integrity/config.json."
                )
                return
    if name == "Bash":
        cmd = str(inp.get("command", "")).lower()
        for pattern in cfg.get("dangerous_command_patterns", []):
            if pattern.lower() in cmd:
                deny_pretool(
                    f"Agent Integrity blocked a command matching '{pattern}'. "
                    "The command deny-list is a safety rail, not sandbox isolation. "
                    "Prefer a reversible targeted operation or explicit project configuration change."
                )
                return


def update_context_health(st, cfg):
    t = cfg.get("thresholds", {})
    failures = st.get("tool_failures", 0)
    cycles = st.get("failed_verification_cycles", 0)
    edits = st.get("edits_since_green", 0)
    if cycles >= t.get("fresh_context_after_failed_verification_cycles", 3):
        health = "red"
    elif failures >= t.get("reground_after_tool_failures", 3) or edits >= t.get("reground_after_edits_without_green_verify", 10):
        health = "orange"
    elif failures >= t.get("warn_after_tool_failures", 2):
        health = "yellow"
    else:
        health = "green"
    st["context_health"] = health
    st["health"] = health


def note_edit(st, detail):
    st["edits_since_green"] = st.get("edits_since_green", 0) + 1
    st["last_edit_at"] = int(time.time())
    add_event(st, "edit", detail)


def bash_may_modify_files(command):
    cmd = command or ""
    # Heuristic only. Git state remains the authoritative stop-time signal.
    patterns = [r"\bsed\s+-i\b", r"\bperl\s+-i\b", r">{1,2}\s*[^&]", r"\btee\b", r"\bmv\b", r"\bcp\b", r"\btouch\b", r"\bpython\b.*\b(write|open)\b"]
    return any(re.search(p, cmd, re.I) for p in patterns)


def handle_posttool(data, cfg, st, failed=False):
    name = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    if failed:
        st["tool_failures"] = st.get("tool_failures", 0) + 1
        add_event(st, "tool_failure", name)
    else:
        if name in ("Edit", "Write"):
            note_edit(st, inp.get("file_path", ""))
        elif name == "Bash":
            cmd = str(inp.get("command", ""))
            add_event(st, "bash_success", cmd)
            if bash_may_modify_files(cmd):
                note_edit(st, f"bash:{cmd[:300]}")
    update_context_health(st, cfg)
    save_json(STATE_PATH, st)
    if st["context_health"] == "orange":
        emit({"hookSpecificOutput": {"hookEventName": data.get("hook_event_name", "PostToolUse"),
              "additionalContext": "Agent Integrity: reasoning context is ORANGE. Repeated failures or unverified edits are accumulating. Stop patch stacking. Re-read the original failure and actual repository/runtime state, invalidate unsupported hypotheses, and make the next change only after obtaining new evidence."}})


def handoff_template(st):
    changed = changed_files()
    results = st.get("last_verification_results") or []
    checks = "\n".join(
        f"- {'PASS' if r.get('ok') else 'FAIL'} [{r.get('classification', 'unknown')}]: `{r.get('command')}`"
        for r in results
    ) or "- No automated verification result recorded."
    return f"""# Verified Handoff

## Goal
Describe the user's original objective without adding new assumptions.

## Health snapshot
- Repository health: {st.get('repository_health', 'unverified')}
- Reasoning-context health: {st.get('context_health', 'unknown')}

## Verified facts
- Fill only with observations backed by repository state, runtime output, tests, or checked sources.

## Evidence
{checks}

## Current changed files
""" + ("\n".join(f"- `{p}`" for p in changed) or "- None detected") + """

## Invalidated assumptions
- List premises that were disproved and what evidence disproved them.

## Failed approaches
- List attempts that failed. Do not convert them into recommendations.

## Open questions
- List unresolved items explicitly.

## Next experiment
Describe the smallest falsifiable next step.
"""


def handle_session_start(data, cfg, st):
    # A fresh session gets fresh reasoning-context health, while repository health
    # is independently recomputed from the new baseline.
    st["session_id"] = data.get("session_id")
    st["session_started_at"] = int(time.time())
    st["tool_failures"] = 0
    st["failed_verification_cycles"] = 0
    st["edits_since_green"] = 0
    st["context_health"] = "green"
    st["health"] = "green"

    changed = changed_files()
    baseline_results = []
    cmds = auto_commands(cfg)
    if cfg.get("baseline_verification_on_session_start", True) and cmds:
        baseline_results = run_verification(cfg)
        for r in baseline_results:
            r["classification"] = "baseline"
        st["repository_health"] = "clean" if all(r.get("ok") for r in baseline_results) else "verification_failing"
        record_verification_evidence(st, "baseline", baseline_results, changed)
    else:
        st["repository_health"] = "unverified"

    st["session_baseline"] = {
        "captured_at": int(time.time()),
        "git_head": git_head(),
        "changed_files": changed,
        "verification_results": baseline_results,
    }
    add_event(st, "session_baseline", f"repo={st['repository_health']} changed={len(changed)}")
    save_json(STATE_PATH, st)

    text = "Agent Integrity v2 active. Verification commands: " + (
        ", ".join(cmds) if cmds else "none auto-detected; configure .claude/integrity/config.json"
    )
    text += f". Repository baseline: {st['repository_health'].upper()}; reasoning context: GREEN."
    if st["repository_health"] == "verification_failing":
        text += " Baseline failures are recorded as pre-existing unless their failure signature changes; do not attribute them to this session without evidence."
    emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})


def handle_stop(data, cfg, st):
    if data.get("background_tasks") or data.get("session_crons"):
        return
    changed = changed_files()
    if not changed or not is_code_change(changed):
        st["tool_failures"] = 0
        update_context_health(st, cfg)
        save_json(STATE_PATH, st)
        return

    results = run_verification(cfg) if cfg.get("auto_verify_on_stop", True) else []
    results = classify_results(results, st)
    st["last_verification_results"] = results

    if not results:
        st["repository_health"] = "unverified"
        update_context_health(st, cfg)
        save_json(STATE_PATH, st)
        msg = (
            "Agent Integrity found code changes but no automated verification command is configured or enabled. "
            "Verify the changed behavior using the strongest practical project-specific check and configure that check in .claude/integrity/config.json."
        )
        if cfg.get("require_verification", True) and not data.get("stop_hook_active"):
            emit({"decision": "block", "reason": msg})
        else:
            emit({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": msg}})
        return

    record_verification_evidence(st, "stop", results, changed)
    failed = [r for r in results if not r.get("ok")]
    new_failures = [r for r in failed if r.get("classification") in {"introduced_failure", "changed_failure", "unbaselined_failure"}]
    preexisting = [r for r in failed if r.get("classification") == "preexisting_failure"]
    st["repository_health"] = "clean" if not failed else "verification_failing"

    if new_failures or (preexisting and cfg.get("block_on_preexisting_failures", False)):
        attributable = new_failures or preexisting
        st["failed_verification_cycles"] = st.get("failed_verification_cycles", 0) + 1
        st["tool_failures"] = st.get("tool_failures", 0) + 1
        add_event(st, "verification_failed", ", ".join(f"{r.get('classification')}:{r.get('command')}" for r in attributable))
        update_context_health(st, cfg)
        save_json(STATE_PATH, st)
        details = "\n\n".join(
            f"CHECK [{r.get('classification')}]: {r['command']}\n{r.get('output','')[-1800:]}" for r in attributable
        )
        if st["context_health"] == "red":
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            HANDOFF_PATH.write_text(handoff_template(st), encoding="utf-8")
            reason = (
                "Agent Integrity context is RED after repeated newly introduced or changed verification failures. "
                "Do not stack another speculative patch. Re-ground from the requirement, repository state, and failing output. "
                "Populate .ai-integrity/HANDOFF.md with verified facts only. A fresh Claude session is recommended after the handoff; repository health will remain recorded independently.\n\n" + details
            )
        else:
            reason = (
                "Automatic verification found a failure introduced or changed during this session. Do not claim completion and do not patch merely to silence the check. "
                "Re-examine the hypothesis, reproduce the underlying failure, and make a minimal evidence-backed correction.\n\n" + details
            )
        if not data.get("stop_hook_active"):
            emit({"decision": "block", "reason": reason})
        else:
            emit({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}})
        return

    # No attributable failures. Preserve repository degradation if baseline failures remain,
    # but do not poison reasoning-context health for somebody else's broken test.
    st["last_green_verify_at"] = int(time.time()) if not failed else st.get("last_green_verify_at")
    st["last_green_commands"] = [r["command"] for r in results if r.get("ok")]
    st["edits_since_green"] = 0
    st["tool_failures"] = 0
    st["failed_verification_cycles"] = 0
    st["context_health"] = "green"
    st["health"] = "green"
    add_event(st, "verification_complete", f"repo={st['repository_health']} preexisting={len(preexisting)}")
    save_json(STATE_PATH, st)

    if preexisting:
        emit({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext":
              "Agent Integrity: verification still contains baseline-matching pre-existing failures. They were not attributed to this session, so reasoning-context health remains GREEN, but repository health is VERIFICATION_FAILING. Report those failures plainly rather than implying a fully green repository."}})


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw or "{}")
    except Exception:
        data = {}
    cfg = config()
    st = state()
    event = data.get("hook_event_name", "")
    if event == "PreToolUse":
        handle_pretool(data, cfg, st)
    elif event == "PostToolUse":
        handle_posttool(data, cfg, st, False)
    elif event == "PostToolUseFailure":
        handle_posttool(data, cfg, st, True)
    elif event == "SessionStart":
        handle_session_start(data, cfg, st)
    elif event == "Stop":
        handle_stop(data, cfg, st)


if __name__ == "__main__":
    main()
