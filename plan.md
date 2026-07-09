# RevAgent Iteris-Style Roadmap

## Current Directive

Future tasks must begin by reading this file, then continue the roadmap below. Phases 1-10 are complete. The next phase can add background process observation for queued workers, but must preserve manual safety gates.

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

## Phase 6 Scope

- Add read-only external-run artifact inspection:
  - `revagent run-log RUN_ID --artifact prompt|stdout|stderr|launch`
- Let operators inspect prompts, logs, and queued launch scripts without opening workspace files manually.
- Keep this as a supervision usability layer only; it must not mutate run records or launch background processes.

## Phase 6 Test Plan

- Verify completed direct runs expose stdout, stderr, and prompt artifacts.
- Verify queued runs expose the launch script and return a clear error for missing stdout/stderr.
- Verify unknown run ids and missing artifact paths fail cleanly.

## Phase 7 Scope

- Add read-only external-run supervision:
  - `revagent run-supervise [RUN_ID]`
- Summarize run health from the external-run ledger and recorded artifact paths.
- Recommend the next command for queued, failed, running, dry-run, completed, canceled, and invalid run records.
- Do not infer process liveness, mutate lifecycle state, or launch external commands.

## Phase 7 Test Plan

- Verify supervision reports queued runs with launch-script readiness.
- Verify supervision reports failed runs with log/recovery guidance.
- Verify one-run and all-run supervision modes fail cleanly for missing run ids.

## Phase 8 Scope

- Add automatic plan evolution and a conservative supervisor loop:
  - `revagent supervisor-plan [--update-plan]`
  - `revagent supervisor-loop [--cycles N] [--dry-run]`
- Generate the next safe supervisor plan from `plan.md`, agent state, monitor/dashboard state, external-run ledger, validation output, and test expectations.
- Execute only safe internal RevAgent commands: refresh monitor/dashboard/memory/readiness, run safe-auto tasks until blocked, and summarize external-run supervision.
- Never approve proof workflows, approve/apply candidate edits, accept LLM drafts, record experiment results, launch external agents, or run tests automatically.

## Phase 8 Test Plan

- Verify `supervisor-plan` writes JSON/Markdown from plan, ledger, dashboard, and validation context.
- Verify `supervisor-plan --update-plan` appends Phase 8 once and is idempotent.
- Verify `supervisor-loop --dry-run` records intended safe actions without executing them.
- Verify `supervisor-loop` executes safe internal actions and stops at manual gates.

## Phase 9 Scope

- Add supervisor evaluation and strategy feedback:
  - `revagent supervisor-feedback`
- Generate a read-only strategy report from supervisor runs, agent eval results, validation output, manual gates, and `plan.md`.
- Feed concise strategy feedback into `supervisor-plan` so the next loop can prioritize safe actions and surface blocked work clearly.
- Keep feedback advisory only; do not auto-approve manual gates, mutate strategy policy, launch external agents, or run tests automatically.

## Phase 9 Test Plan

- Verify `supervisor-feedback` writes JSON/Markdown from eval, validation, and supervisor run history.
- Verify failed eval checks and failed supervisor tasks become strategy recommendations.
- Verify `supervisor-plan` includes the latest feedback summary.

## Phase 10 Scope

- Add conservative multi-worker orchestration:
  - `revagent supervisor-workers [--workers N] [--queue]`
- Split safe supervisor tasks into isolated external-worker prompts.
- Default mode writes prompts and a worker plan only; it does not launch workers.
- `--queue` may create queued external run launch scripts, but must not start background processes or weaken manual gates.
- Workers must inherit the same forbidden actions as `revagent run`.

## Phase 10 Test Plan

- Verify `supervisor-workers` writes worker JSON/Markdown and prompt files without appending external runs.
- Verify `supervisor-workers --queue` records queued external runs without starting them.
- Verify worker prompts preserve manual safety gate restrictions.
