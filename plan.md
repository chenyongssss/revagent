# RevAgent Iteris-Style Phase 1 Plan

## Current Directive

Future tasks must begin by reading this file, then continue the roadmap below. The first implementation phase moves RevAgent toward an Iteris-style local agent by adding:

- `revagent run` external agent execution.
- A stronger `monitor` recovery layer.
- A static HTML dashboard.

## Phase 1 Scope

- Add an external runner subsystem that can generate a RevAgent-aware prompt and launch the local Codex CLI.
- Keep the default safety model conservative: external agents should use safe RevAgent commands and must not approve proof workflows, approve/apply candidate edits, accept LLM drafts, or record experiment results unless the user explicitly opts into dangerous autonomy.
- Upgrade `monitor` so it refreshes state and prints environment checks, blockers, and one recommended next command.
- Add `revagent dashboard` to generate `.revagent/dashboard/index.html`.

## Command Contract

- `revagent run [--goal GOAL] [--backend codex] [--dry-run] [--limit N] [--dangerous-autonomy]`
  - Default backend is Codex CLI.
  - `--dry-run` writes and prints the generated prompt without launching Codex.
  - Normal runs append metadata to `.revagent/external_agent_runs.jsonl`, render `.revagent/external_agent_runs.md`, and capture stdout/stderr in `.revagent/logs/`.
- `revagent monitor`
  - Refreshes agent state, report, decisions, readiness, and dashboard.
  - Prints workspace/Codex/session checks and the highest-priority recovery command.
- `revagent dashboard`
  - Writes `.revagent/dashboard/index.html` from current agent/dashboard state.

## Implementation Notes

- Generated Codex prompts must tell the external agent to read this file first.
- External run prompts should include the dashboard summary, next task, safe commands, and default forbidden actions.
- Preserve `agent-run` as the deterministic internal safe-auto runner; `run` is an external agent supervisor.
- Static dashboard should include task summary, next action, active session, review progress, lanes, readiness blockers, manual decisions, failed/stale tasks, and recent internal/external runs.

## Test Plan

- Add parser/CLI tests for `run --dry-run`, mocked `run`, enhanced `monitor`, and `dashboard`.
- Mock subprocess execution for Codex runs.
- Verify prompt files, external run JSONL/markdown, stdout/stderr logs, and dashboard HTML.
- Run `python -m pytest` with repo-local `TMP` and `TEMP`.

## Assumptions

- `codex` is available on PATH on the primary development machine.
- First dashboard version is static HTML, not a local HTTP server.
- Iteris-style evolve/child-project generalization is out of phase 1.
