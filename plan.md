# RevAgent Iteris-Style Roadmap

## Current Directive

Future tasks must begin by reading this file, then continue the roadmap below. Phases 1-33 are complete. Future process-supervision work must preserve manual safety gates.

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

## Phase 11 Scope

- Add background-safe observation for queued workers:
  - `revagent supervisor-observe [RUN_ID]`
- Observe queued external-worker runs by checking recorded prompt, launch script, and log artifact paths.
- Write observation records without launching processes, changing run lifecycle state, or inferring process liveness.
- Recommend conservative next commands such as `run-log`, `run-mark`, or `run-recover`.

## Phase 11 Test Plan

- Verify queued worker runs produce observation JSONL/Markdown with launch-script readiness.
- Verify one-run observation fails cleanly for unknown run ids.
- Verify observation does not mutate `external_agent_runs.jsonl`.

## Phase 12 Scope

- Add read-only supervisor observation history:
  - `revagent supervisor-observation [RUN_ID]`
- Let operators retrieve recorded queued-worker artifact snapshots without opening workspace files manually.
- Extend `revagent validate` to flag malformed observation ledger records and incomplete safety declarations.
- Keep history inspection and validation read-only: neither command may launch a process, mutate external-run lifecycle state, or infer process liveness.

## Phase 12 Test Plan

- Verify `supervisor-observation` lists all records and filters a run id without mutating either ledger.
- Verify missing observation run ids fail clearly.
- Verify `revagent validate` warns for malformed or unsafe observation records.

## Phase 13 Scope

- Feed persisted worker observations into conservative supervisor planning and feedback.
- Summarize the latest observation for each external run, including health and the operator-facing next command.
- Recommend inspection or dry-run recovery for ready or blocked queued workers as advisory work only.
- Do not refresh observations, launch workers, change external-run lifecycle state, or infer process liveness while planning.

## Phase 13 Test Plan

- Verify supervisor feedback recommends recovery for a latest blocked observation.
- Verify supervisor plans and feedback render the observation summary and operator command.
- Verify planning and feedback leave external-run and observation ledgers unchanged.

## Phase 14 Scope

- Surface the latest persisted worker-observation summary in `revagent monitor` and the static dashboard.
- Show per-run health and the recorded operator-facing next command, with a clear validation hint for malformed observation ledgers.
- Keep monitor and dashboard display-only with respect to worker observations and external-run lifecycle state.

## Phase 14 Test Plan

- Verify monitor and dashboard render a blocked worker observation and its recovery command.
- Verify malformed observation ledgers render a validation hint instead of breaking monitor or dashboard generation.
- Verify monitor/dashboard generation does not mutate external-run or observation ledgers.

## Phase 15 Scope

- Cross-validate the latest worker observation for each run against the external-run ledger.
- Warn when an observation references an unknown run or records a status that is stale relative to the current lifecycle record.
- Preserve append-only observation history by validating only the latest snapshot per run.
- Keep validation advisory and read-only; it must not refresh observations or mutate either ledger.

## Phase 15 Test Plan

- Verify unknown observed run ids and stale latest statuses produce validation warnings.
- Verify superseded historical observations do not produce stale-status warnings.
- Verify validation does not mutate the external-run or observation ledger.

## Phase 16 Scope

- Extend read-only `revagent run-supervise [RUN_ID]` with the latest persisted worker observation for each external run.
- Identify whether the observation lifecycle status is current or stale relative to the external-run ledger, and retain the observation's operator-facing next command.
- Keep supervision display-only: it must not refresh observations, mutate either ledger, launch a process, or infer process liveness.

## Phase 16 Test Plan

- Verify supervision renders a matching latest observation and its next command.
- Verify stale observations are labelled without changing either ledger.
- Verify all-run and one-run supervision remain safe for runs without observations.

## Phase 17 Scope

- Surface the latest persisted worker observation in read-only `revagent run-status RUN_ID` output.
- Mark the observation as current or stale against the current external-run lifecycle status, including its recorded health and recommended command.
- Keep run detail inspection display-only: it must not refresh observations, mutate ledgers, launch a process, or infer process liveness.

## Phase 17 Test Plan

- Verify run detail renders current and stale worker observations with their next command.
- Verify missing or malformed observation ledgers render a clear non-mutating hint.
- Verify run-status inspection leaves both ledgers unchanged.

## Phase 18 Scope

- Surface latest persisted worker-observation health and lifecycle consistency in read-only `revagent run-status` history output.
- Render a validation hint when the observation ledger cannot be parsed, without breaking external-run history inspection.
- Keep historical status inspection display-only: it must not refresh observations, mutate ledgers, launch a process, or infer process liveness.

## Phase 18 Test Plan

- Verify run history renders current and stale observation summaries for matching runs.
- Verify malformed observation ledgers render a validation hint.
- Verify history rendering leaves both ledgers unchanged.

## Phase 19 Scope

- Add an explicit worker execution control plane: `run-start`, `run-refresh`, and `run-cancel`.
- Record append-only PID/create-time-bound runtime events and wrapper completion manifests.
- Keep worker starts operator-triggered; supervisor commands must never dispatch a worker.

## Phase 19 Test Plan

- Verify queued-only startup, completion reconciliation, process identity checks, cancellation, and malformed runtime validation.

## Phase 20 Scope

- Add `worker-snapshot RUN_ID` for isolated RevAgent source-checkout snapshots.
- Run controlled workers only inside a valid snapshot and reject stale or missing snapshots.
- Preserve the parent source tree and keep snapshot isolation unavailable to ordinary manuscript workspaces.

## Phase 20 Test Plan

- Verify snapshot exclusions, source fingerprints, startup rejection without a snapshot, and parent-tree preservation.

## Phase 21 Scope

- Add explicit `worker-evaluate RUN_ID` to compare snapshot changes, generate a patch, and run the snapshot test suite.
- Permit evaluation only after successful worker completion and only for allowed source paths.

## Phase 21 Test Plan

- Verify successful evaluation, failed completion, forbidden changes, stale parent sources, malformed evaluation ledgers, and failed tests.

## Phase 22 Scope

- Add source-evolution proposals with explicit review, approval/rejection, and `evolution-apply --approved`.
- Apply only approved, fingerprint-current, evaluation-passing changes after making a backup.
- Never auto-apply, commit, push, or weaken manuscript manual gates.

## Phase 22 Test Plan

- Verify proposal creation from passing evaluations only, manual approval requirements, stale/tampered proposal rejection, backups, and no auto-apply behavior.

## Phase 23-27 Scope

- Add a SQLite-backed, loopback-only review-project runtime with durable task graphs, leases, events, author gates, and task-scoped remote authorization.
- Advance only reversible review analysis, item planning, and evidence collection with at most two local workers; retain existing proof, experiment, draft acceptance, manuscript application, and closure gates.
- Build per-item evidence records from manuscript locations, analyses, proof/experiment/candidate artifacts, and deterministic readiness evaluation.
- Provide local project lifecycle commands, a `serve` status endpoint, evidence evaluation, runtime exports, validation-compatible schema migration, and author-facing status artifacts.

## Phase 23-27 Test Plan

- Verify SQLite task import, dependency scheduling, bounded concurrency, pause/resume, retry limits, authorization storage, evidence rendering, deterministic readiness evaluation, and compatibility with existing workspace artifacts.

## Phase 28-32 Scope

- Add specialized text, proof, code, and experiment worker plans with Codex/OpenAI-compatible backend selection, complete project snapshots, result bundles, and path-conflict records.
- Add explicit sandboxed experiment command authorization with timeout, CPU, memory, and artifact budgets; worker output remains unconfirmed evidence.
- Add one-use, consent-gated semantic rubric evaluation over the complete project snapshot, with structured scores and author-only closure.
- Add loopback service health/discovery metadata, benchmark documentation, and regression coverage for worker, sandbox, experiment, and rubric paths.

## Phase 28-32 Test Plan

- Verify role selection, snapshot exclusions, result collection/conflicts, resource authorization, authorized experiment logs, one-use rubric authorization, service health metadata, and synthetic benchmark safety rules.

## Phase 33 Scope

- Add deterministic synthetic benchmark execution, metric reports, service health diagnostics, expired-lease recovery, cross-platform CI, and protected real-provider E2E evaluation using synthetic inputs only.
- Keep licensed/deidentified real review cases outside the repository until they carry data cards, permission records, redaction review, and expected labels.

## Phase 33 Test Plan

- Verify benchmark metrics, recovery retry budgets, runtime health, provider authorization consumption, CI platform coverage, and that protected E2E never uploads raw prompts or private project artifacts.

## Phase 34 Scope

- Add an explicit, append-only Planner → Actor → Reviewer revision cycle for each review item.
- Freeze each role's versioned JSON artifact into a workspace-controlled evidence bundle with a content hash and a review-input fingerprint.
- Require distinct Planner, Actor, and Reviewer identities; prohibit role self-review and preserve author-only approval as a separate gate.
- Keep cycles advisory: they never apply manuscript changes, approve proof or experiment results, or close review items.

## Phase 34 Test Plan

- Verify planner, actor, reviewer, and author-gate transitions, role separation, hash-bound handoffs, and unchanged review-item lifecycle state.
- Verify out-of-order actions, stale inputs, incomplete artifacts, and reviewer identity reuse fail closed.

## Phase 35 Scope

- Replace the generic planner payload with typed revision specification version 2 for computational mathematics.
- Require request and manuscript traceability, claim/evidence inventories, observable acceptance criteria, rebuttal mapping, risks, uncertainties, and manual gates.
- Enforce lane-specific contracts for proof, stability, convergence, and experiment work without treating a structured plan as mathematical or numerical validation.

## Phase 35 Test Plan

- Verify typed proof, stability, convergence, experiment, and text/rebuttal specifications; reject missing high-risk author gates, result assertions, invalid IDs, and incomplete evidence mappings.

## Phase 36 Scope

- Require Actor evidence bundle version 2, bound to the frozen typed Planner specification.
- Record hash-verified workspace evidence, non-conclusive claim observations, limitations, and unresolved questions without altering the manuscript or confirming mathematical or numerical results.

## Phase 36 Test Plan

- Verify claim/evidence ID binding, evidence-hash verification, non-evidentiary LLM labeling, non-conclusive experiment attempts, and rejection of unplanned or unsupported claims.

## Phase 37 Scope

- Require independent Reviewer report version 2, bound to frozen Planner and Actor artifacts.
- Require complete claim, evidence, and acceptance-criterion assessment before a low-risk pass; route proof, stability, convergence, and experiment work to escalation and author gates.

## Phase 37 Test Plan

- Verify assessment coverage, reviewer identity separation, verdict constraints, and that no review report establishes mathematical correctness, numerical validity, or item closure.

## Phase 38 Scope

- Add a read-only author decision console and dashboard section for revision-cycle status, bound hashes, author-facing next commands, and submission-risk visibility.
- Preserve current author-gate semantics: the console may not apply manuscript changes, resolve proof/experiment evidence, or close review items.

## Phase 38 Test Plan

- Verify pending author decisions make submission readiness false, display a deterministic safe next command, and disappear only after the current cycle decision is recorded.
- Verify escalation remains blocked and waiver is append-only, low-risk-only, and a persistent submission disclosure.

## Phase 39 Scope

- Maintain deterministic synthetic benchmark fixtures for computational-mathematics revision workflows and defect-detection metrics.
- Register consented historical cases only in local shadow mode: retain file hashes and aggregate structural metadata, never raw manuscript, reviewer, or response text.
- Produce a two-expert independent scoring template for plan-lane accuracy, high-risk recall, defect-detection recall, false-pass rate, and claim-provenance completeness.

## Phase 39 Test Plan

- Verify a shadow registration rejects incomplete cases, preserves source confidentiality, and emits an expert-evaluation template without copying case text into the workspace.
- Require independent human expert scores before a shadow case can support any quality or autonomy claim.
