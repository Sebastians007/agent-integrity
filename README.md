# Agent Integrity Runtime

[![Version](https://img.shields.io/badge/version-0.2.0-blue)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-hooks-black)](https://docs.claude.com/claude-code)

A repository-level reliability layer for Claude Code. Deterministic hooks — not prompt instructions — decide whether verification evidence exists, distinguish pre-existing failures from newly introduced ones, resist patch stacking, and keep an auditable evidence trail.

Model instructions govern judgment-heavy behavior. Hooks govern everything that must be enforced regardless of what the model decides to do.

## Why

Agents can claim work is "done" without running anything, or quietly patch around a failing test until it goes green. This runtime closes that gap at the hook level:

- **Session baselines** — verification runs at `SessionStart` and records Git state plus failure fingerprints.
- **Failure attribution** — Stop-time failures are classified as `passing`, `resolved`, `preexisting_failure`, `introduced_failure`, `changed_failure`, or `unbaselined_failure`.
- **Two health axes** — `repository_health` describes the working tree; `context_health` describes accumulated reasoning failures. A fresh context doesn't make a broken repo green, and a pre-existing broken test doesn't poison a fresh session by itself.
- **Evidence ledger** — every verification command is appended to `.ai-integrity/evidence.jsonl` with session, Git HEAD, changed files, classification, and fingerprint.
- **Claim dependency ledger** — `.claude/integrity/ledger.py` registers claims and dependencies, and automatically marks downstream claims `suspect` when a premise is invalidated.
- **Patch-stacking resistance** — repeated failing edits without new evidence trigger a rollback-and-reground signal instead of another speculative patch.

## Install

```bash
python install.py /path/to/your-project
```

The installer copies the runtime, merges hooks into `.claude/settings.json` (existing hooks and config are preserved, not replaced), auto-detects common project check commands (npm/pnpm/yarn/bun scripts, pytest, `go test`, `cargo test`), and adds `.ai-integrity/` to `.gitignore`.

After installing, run `/hooks` in Claude Code and confirm `SessionStart`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, and `Stop` each contain an Agent Integrity entry.

## Configure

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

- `require_verification: true` blocks clean completion after code changes if no verifier is configured for the repo. Set `verification_commands` before relying on this.
- `block_on_preexisting_failures` defaults to `false`: unchanged baseline failures are reported and keep repository health degraded, but don't block unrelated completion. Set `true` for repos that require an entirely green suite before any completion.
- Disabling `baseline_verification_on_session_start` saves startup cost, but failures then become `unbaselined_failure` and are conservatively treated as attributable.

See `examples/config-nextjs.json` for a framework-specific example.

## Health model

**Repository health**: `clean` · `verification_failing` · `unverified`

**Context health**: `green` · `yellow` · `orange` · `red` — only attributable failures and tool/edit pressure escalate it. At `red`, the runtime regenerates `.ai-integrity/HANDOFF.md` and recommends a fresh reasoning session while preserving repository health and evidence on disk.

## Evidence and claims

Verification evidence is automatic, written to `.ai-integrity/evidence.jsonl`.

Important reasoning can be made explicit:

```bash
python .claude/integrity/ledger.py add-claim "Parser bug is caused by CRLF normalization" --status inferred
python .claude/integrity/ledger.py show
python .claude/integrity/ledger.py invalidate cl-ab12cd34 --reason "Reproduction fails on LF and CRLF identically"
```

Invalidating a claim marks all transitive dependents `suspect` instead of pretending downstream reasoning remains intact.

## Limits

This runtime improves process reliability; it does not prove correctness.

- Failure fingerprints are heuristics, not perfect semantic equivalence — a command can fail for a different underlying reason and still match a prior signature, and the reverse can happen too.
- The protected-path and dangerous-command deny lists are safety rails, not security isolation. A real security boundary belongs in OS/container/tool permissions.
- Passing tests may encode the wrong requirement, and documentation may be stale. Verification and source provenance are evidence, not proof.

## Requirements

- Claude Code with project hooks support
- Python 3
- Git (strongly recommended)

## Uninstall

```bash
python uninstall.py /path/to/your-project
```

Or manually: remove hook entries containing `agent-integrity-runtime` from `.claude/settings.json`, then delete `.claude/integrity/` and `.claude/rules/agent-integrity.md`. `.ai-integrity/` evidence history is left alone intentionally.

## Layout

```
.claude/integrity/hooks/integrity.py   hook entrypoint (Session/Pre/Post/Stop)
.claude/integrity/ledger.py            claim/dependency ledger CLI
.claude/integrity/config.json          default config, merged on install
.claude/rules/agent-integrity.md       operating policy read by the model
docs/                                  design notes, source policy, install prompt
examples/                              framework-specific config samples
tests/                                 runtime unit tests
install.py / uninstall.py              per-project installer/uninstaller
```

## License

MIT — see [LICENSE](LICENSE).
