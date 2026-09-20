# Design

Agent Integrity Runtime v2 separates deterministic evidence collection from model judgment.

## State model

Two independent axes are persisted:

- `repository_health`: `clean`, `verification_failing`, or `unverified`.
- `context_health`: `green`, `yellow`, `orange`, or `red`.

A new session resets context counters, then captures a fresh repository baseline. This prevents unresolved repository failures from being forgotten while avoiding false blame for failures that already existed.

## Baseline attribution

At session start the runtime records Git HEAD, changed files, and verification results. Failed results receive a fingerprint built from command, return code, and normalized failure-bearing output lines.

At stop time:

- baseline pass -> current fail = `introduced_failure`
- baseline fail + same fingerprint = `preexisting_failure`
- baseline fail + changed fingerprint = `changed_failure`
- no baseline + fail = `unbaselined_failure`
- baseline fail -> current pass = `resolved`

Fingerprints are deliberately heuristic. They improve attribution but do not prove causal ownership.

## Evidence ledger

Every verification command is appended as JSON Lines to `.ai-integrity/evidence.jsonl`. Entries include session ID, phase, classification, fingerprint, Git HEAD, and changed files.

The optional claim ledger stores explicit claim dependencies. Invalidating a premise marks all transitive dependents suspect. This converts dependency invalidation from a purely verbal rule into machine-readable state.

## Change detection

Tracked changes come from `git diff HEAD --name-only`; untracked files come from `git ls-files --others --exclude-standard`. This intentionally avoids Git's directory-collapsing untracked status presentation.

Tool names are not treated as authoritative evidence of file mutation. Bash mutations are heuristically counted for pressure, while stop-time Git state is authoritative.

## Security posture

Command/path blocking is an accidental-destruction guard. It is not an adversarial security boundary. Strong security requires sandboxing and filesystem/process permissions outside the model-controlled command surface.
