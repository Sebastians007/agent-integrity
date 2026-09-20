# Agent Integrity Runtime v2 for Claude Code

A repository-level reliability layer that makes Claude Code verify changes automatically, distinguish pre-existing failures from newly introduced ones, resist patch stacking, and keep an auditable evidence trail.

This is not a prompt asking an agent to "be careful." Deterministic hooks decide whether verification evidence exists; model instructions govern judgment-heavy behavior.

## What changed in v2

- **Session baselines.** Verification runs at `SessionStart` by default and records the current Git state plus failure fingerprints.
- **Failure attribution.** Stop-time failures are classified as `passing`, `resolved`, `preexisting_failure`, `introduced_failure`, `changed_failure`, or `unbaselined_failure`.
- **Two health axes.** `repository_health` describes the working tree; `context_health` describes accumulated reasoning failures. Fresh context no longer magically makes a broken repo green, and a pre-existing broken test no longer poisons a fresh session by itself.
- **Robust untracked-file detection.** Git change detection enumerates untracked files individually, including files inside new directories.
- **Strict verification option.** `require_verification: true` blocks clean completion after code changes when no verifier is configured.
- **Evidence ledger.** Every verification command is appended to `.ai-integrity/evidence.jsonl` with session, Git HEAD, changed files, classification, and fingerprint.
- **Claim dependency ledger.** `.claude/integrity/ledger.py` can register claims/dependencies and automatically mark downstream claims suspect when a premise is invalidated.
- **Bash edit heuristic.** Common Bash file-mutation forms now contribute to unverified-edit pressure. Git remains the authoritative stop-time signal.
- **Upgrade-safe installer.** Existing configuration is merged into the v2 defaults instead of being blindly replaced.

## Installation / upgrade

```bash
python install.py /path/to/your-project
```

The installer copies the runtime, merges hooks into `.claude/settings.json`, preserves existing integrity config values where possible, detects common project checks, and adds `.ai-integrity/` to `.gitignore`.

After installation, run `/hooks` in Claude Code and confirm `SessionStart`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, and `Stop` contain Agent Integrity hooks.

## Core configuration

Edit `.claude/integrity/config.json`:

```json
{
  "baseline_verification_on_session_start": true,
  "require_verification": true,
  "block_on_preexisting_failures": false,
  "verification_commands": [
    "npm run typecheck",
    "npm run lint",
    "npm test"
  ]
}
```

`block_on_preexisting_failures` defaults to `false`: unchanged baseline failures are reported and keep repository health degraded, but they do not count as fresh reasoning failures or prevent unrelated completion. Set it to `true` for repositories that require an entirely green suite before any completion.

Baseline verification adds startup cost. Disable `baseline_verification_on_session_start` only when that cost is unacceptable; failures then become `unbaselined_failure` and are conservatively treated as attributable.

## Health model

**Repository health** is one of `clean`, `verification_failing`, or `unverified`.

**Context health** is `green`, `yellow`, `orange`, or `red`. Only attributable failures and tool/edit pressure escalate it. At red, the runtime regenerates `.ai-integrity/HANDOFF.md` and recommends a fresh reasoning session while preserving repository health and evidence on disk.

## Evidence and claims

Verification evidence is automatic:

```text
.ai-integrity/evidence.jsonl
```

Important reasoning can be made explicit:

```bash
python .claude/integrity/ledger.py add-claim "Parser bug is caused by CRLF normalization" --status inferred
python .claude/integrity/ledger.py show
python .claude/integrity/ledger.py invalidate cl-ab12cd34 --reason "Reproduction fails on LF and CRLF identically"
```

Invalidating a claim marks all transitive dependents `suspect` instead of pretending downstream reasoning remains intact.

## Important limits

This runtime improves process reliability; it does not prove correctness. Failure fingerprints are heuristics, not perfect semantic equivalence. A test command can contain a different underlying failure while producing a similar signature, and the reverse can happen too.

The protected-path and dangerous-command deny lists are safety rails, not security isolation. A real security boundary belongs in OS/container/tool permissions.

Passing tests may encode the wrong requirement. Official documentation may be stale. Verification and source provenance are evidence, not metaphysical truth, despite humanity's recurring desire to manufacture the latter from JSON.

## Requirements

- Claude Code with project hooks support.
- Python 3.
- Git is strongly recommended.

## Uninstall

Run `uninstall.py` from this repository, or remove installed hook entries containing `agent-integrity-runtime` and delete `.claude/integrity/` plus `.claude/rules/agent-integrity.md`. `.ai-integrity/` history is intentionally left alone.
