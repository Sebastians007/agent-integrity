#!/usr/bin/env python3
"""Install or upgrade Agent Integrity Runtime in a Claude Code project."""
import argparse
import json
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent


def deep_merge(base, overlay):
    out = dict(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def merge_hook(settings, event, matcher, command):
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault(event, [])
    sig = "agent-integrity-runtime"
    for group in groups:
        for h in group.get("hooks", []):
            if sig in h.get("command", ""):
                # Upgrade the existing hook command/timeout without duplicating it.
                h["command"] = command
                h["timeout"] = 600
                return
    groups.append({"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 600}]})


def detect_commands(root):
    cmds = []
    pkg = root / "package.json"
    if pkg.exists():
        try:
            d = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = d.get("scripts", {})
            runner = "npm run"
            if (root / "pnpm-lock.yaml").exists():
                runner = "pnpm"
            elif (root / "yarn.lock").exists():
                runner = "yarn"
            elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
                runner = "bun run"
            for n in ("typecheck", "check", "lint", "test"):
                if n in scripts and not (n == "test" and "no test specified" in str(scripts[n]).lower()):
                    cmds.append(f"{runner} {n}")
        except Exception:
            pass
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        if (root / ".venv").exists():
            exe = ".venv/Scripts/python.exe" if sys.platform.startswith("win") else ".venv/bin/python"
            cmds.append(f'"{exe}" -m pytest -q')
        else:
            cmds.append(f'"{sys.executable}" -m pytest -q')
    if (root / "go.mod").exists():
        cmds.append("go test ./...")
    if (root / "Cargo.toml").exists():
        cmds.append("cargo test --quiet")
    return list(dict.fromkeys(cmds))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default=".")
    a = ap.parse_args()
    root = Path(a.target).resolve()
    root.mkdir(parents=True, exist_ok=True)

    dest = root / ".claude" / "integrity"
    rules = root / ".claude" / "rules"
    prior_cfg = {}
    prior_cfg_path = dest / "config.json"
    if prior_cfg_path.exists():
        try:
            prior_cfg = json.loads(prior_cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise SystemExit(f"Refusing upgrade because existing {prior_cfg_path} is invalid JSON: {e}")

    dest.mkdir(parents=True, exist_ok=True)
    rules.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC / ".claude" / "integrity", dest, dirs_exist_ok=True)
    shutil.copy2(SRC / ".claude" / "rules" / "agent-integrity.md", rules / "agent-integrity.md")

    default_cfg = json.loads((SRC / ".claude" / "integrity" / "config.json").read_text(encoding="utf-8"))
    cfg = deep_merge(default_cfg, prior_cfg)
    cfg["version"] = 2
    detected = detect_commands(root)
    if detected and not cfg.get("verification_commands"):
        cfg["verification_commands"] = detected
    (dest / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    py = Path(sys.executable).resolve()
    hook = (dest / "hooks" / "integrity.py").resolve()
    command = f'"{py}" "{hook}" # agent-integrity-runtime'
    sp = root / ".claude" / "settings.json"
    try:
        settings = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    except Exception as e:
        raise SystemExit(f"Refusing to overwrite invalid {sp}: {e}")
    for event, matcher in [
        ("SessionStart", ""),
        ("PreToolUse", "Bash|Edit|Write"),
        ("PostToolUse", "*"),
        ("PostToolUseFailure", "*"),
        ("Stop", ""),
    ]:
        merge_hook(settings, event, matcher, command)
    sp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    gi = root / ".gitignore"
    old = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if ".ai-integrity/" not in old:
        gi.write_text(old + ("\n" if old and not old.endswith("\n") else "") + ".ai-integrity/\n", encoding="utf-8")

    print("Agent Integrity Runtime v2 installed/upgraded.")
    print(f"Project: {root}")
    print("Verification commands:", ", ".join(cfg.get("verification_commands") or []) or "none auto-detected")
    print("Existing config values were preserved where possible; schema version is now 2.")
    print("Open Claude Code and run /hooks to confirm the hooks are registered.")


if __name__ == "__main__":
    main()
