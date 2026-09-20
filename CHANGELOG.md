# Changelog

## 0.2.0

- Added session-start verification baselines and failure fingerprints.
- Added failure attribution for pre-existing, introduced, changed, unbaselined, resolved, and passing checks.
- Split repository health from reasoning-context health.
- Fixed untracked files inside new directories being missed by code-change detection.
- Added strict `require_verification` behavior when code changes have no verifier.
- Added configurable handling of unchanged pre-existing failures.
- Added automatic JSONL verification evidence ledger.
- Added claim/dependency ledger with transitive invalidation.
- Added Bash file-mutation heuristic while retaining Git as authoritative change evidence.
- Clarified that command/path deny lists are safety rails, not security isolation.
- Made installer upgrades preserve existing config values and update existing hook timeout/command entries.
- Added runtime unit tests and broken-repository behavioral smoke coverage during release verification.
