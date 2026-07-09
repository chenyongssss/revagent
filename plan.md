# RevAgent Iteris-Style Roadmap

## Current Directive

Future tasks must begin by reading this file, then continue the roadmap below. Phase 1 is complete and committed. Phase 2 adds the durable facts / verification memory layer that external agents can use for grounded planning.

## Completed Phase 1

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

## Phase 2 Scope

- Add generated durable memory artifacts:
  - `.revagent/revision_memory.json`
  - `.revagent/revision_memory.md`
- Add `revagent memory [R001]` to refresh and show all facts or one item's facts.
- Derive facts only from existing trusted workspace files: review items, review analyses, item plans, proof workflows, experiment manifests/runs, candidates, LLM drafts, provenance, and readiness.
- Feed a compact memory summary into external-agent prompts and the static dashboard.
- Keep memory generated and deterministic; do not let it become an editable source of truth yet.

## Phase 2 Test Plan

- Verify init/migrate creates memory files.
- Verify `revagent memory` writes JSON/Markdown and supports item filtering.
- Verify memory facts include reviewer request, current status, blockers, verification gates, candidates, and next command.
- Verify external-agent prompt and dashboard include memory summary.
- Run `python -m pytest` with repo-local `TMP` and `TEMP`.

## Phase 3 Scope

- Add external-run status and recovery controls:
  - `revagent run-status [RUN_ID]`
  - `revagent run-recover [RUN_ID] [--dry-run]`
- Add a conservative detached-run foundation:
  - `revagent run --detach`
  - writes a launch script and records `status=queued` without starting a background daemon.
- Keep recovery conservative: reuse the previous run's backend, goal, and autonomy setting; dry-run recovery only regenerates a prompt.
- Surface the latest external-run status and recovery hint in `revagent monitor`.
- Defer true background process supervision until queued launch scripts are stable.

## Phase 3 Test Plan

- Verify `run-status` lists runs and shows one run with recovery hints.
- Verify `run-recover --dry-run` regenerates a prompt from the previous run without appending a completed run.
- Verify `run --detach` writes a launch script and queued run record.
- Verify monitor includes the latest external-run section.

## Phase 4 Scope

- Add explicit manual lifecycle controls for queued external runs:
  - `revagent run-mark RUN_ID --status done|failed|canceled [--note text]`
- Keep lifecycle updates append-ledger-compatible by updating only the matching JSONL record and re-rendering `external_agent_runs.md`.
- Use this as the manual completion bridge before implementing real background process supervision.

## Phase 4 Test Plan

- Verify queued runs can be marked done, failed, and canceled.
- Verify invalid statuses and unknown run ids fail.
- Verify run detail includes operator note and updated status.

## Phase 5 Scope

- Harden validation for the external-run supervisor ledger:
  - detect malformed JSONL records;
  - validate external run statuses;
  - warn when queued launch scripts or prompt paths are missing;
  - warn when marked runs have operator notes without `marked_at`;
  - warn when completed direct-run log paths point to missing files.

## Phase 5 Test Plan

- Verify `revagent validate` reports malformed external run JSONL.
- Verify queued run records with missing launch scripts generate warnings.
- Verify invalid lifecycle status and incomplete manual marks generate warnings.
