# Installation instruction for Claude Code

Use this text when asking Claude Code to install the runtime from a GitHub clone:

> Inspect this repository before installing it. Run `install.py` against the current project. Preserve all existing `.claude/settings.json` settings and hooks; the installer is designed to merge rather than replace them. After installation, inspect `.claude/integrity/config.json`. Determine the project's real typecheck, lint, unit-test, integration-test, and build commands from the repository itself rather than guessing. Configure the fastest meaningful verification commands. Run those commands once. If any fail before your changes, report them as pre-existing failures instead of silently weakening the checks. Confirm the installed hook entries and summarize exactly what is enforced.
