# revagent

`revagent` is a local-first revision workspace CLI for computational mathematics
papers. It turns a LaTeX project and reviewer comments into structured,
reviewable artifacts: review item tracking, a manuscript index, response-letter
drafts, proof audits, experiment plans, and conservative patch notes.

The tool is intentionally narrow. It does not verify mathematical correctness,
silently rewrite manuscript sources, execute experiments, or invent numerical
results.

## Install

```powershell
python -m pip install -e .[dev]
```

## Quick Start

```powershell
cd path\to\latex-paper
revagent init --journal siam --tex-root . --main-tex paper.tex
revagent ingest-comments reviewer_comments.md
revagent plan
revagent analyze-review --all
revagent plan-item --all
revagent review-analysis R001
revagent draft
revagent llm-draft --all
revagent llm-review R003
revagent llm-accept R003
revagent llm-check R003
revagent incorporate-drafts
revagent migrate --dry-run
revagent proof-audit R001
revagent proof-plan R001
revagent proof-obligation R001 --add "Verify the theorem dependencies."
revagent proof-approve R001 --note "Author verified the proof change."
revagent experiment-plan R002
revagent experiment-contract R002
revagent experiment-run R002 --dry-run
revagent experiment-artifact R002 --path results/demo_metrics.csv --kind table --note "Observed seed-1 comparison."
revagent experiment-incorporate R002 --target tab:demo --field observed_result --text-file result_text.tex
revagent reason R001
revagent inspect R001
revagent edit-candidate C001 --text-file author_revision.tex
revagent approve C001
revagent apply --dry-run
revagent apply --approved
revagent restore --backup .revagent/backups/20260101T000000Z
revagent close-item R003
revagent provenance
revagent agent-status
revagent monitor
revagent agent-plan --goal rebuttal-draft
revagent agent-session
revagent agent-resume --watch --cycles 1
revagent agent-blockers
revagent agent-complete-check
revagent agent-decisions
revagent agent-eval --all
revagent agent-next
revagent agent-run --until-blocked
revagent agent-report
revagent validate
revagent export
```

The workspace is written to `.revagent/`. Per-item planning status follows
`triaged -> planned -> drafted -> evidence_ready -> approved -> incorporated -> closed`.
The safe-auto agent loop can advance reversible workspace artifacts, but it does
not approve proof workflows, approve candidate edits, apply manuscript edits, or
run experiments.

## Workspace Files

- `review_items.json`: structured reviewer/editor items.
- `latex_index.json`: reachable TeX files, includes, sections, custom theorem-like environments, theorem/proof/algorithm/figure/table blocks, labels, refs, citations, and unresolved refs.
- `item_plans.json`: structured per-review-item planner records.
- `item_plans.md`: reviewable rendering of reviewer intent, evidence, edit plan, dependencies, blockers, and completion criteria.
- `review_analyses.json`: structured reviewer intent, claim/evidence, risk, verification, response-strategy, and manuscript-action records.
- `review_analyses.md`: reviewable rendering of structured reviewer analyses.
- `proof_workflows.json`: structured proof workflow records with statement/proof snapshots, dependencies, obligations, and approval status.
- `proof_workflows.md`: reviewable proof workflow report.
- `experiment_manifests.json`: reproducibility contracts with command templates, seeds, artifact hashes, and backfill targets.
- `experiment_manifests.md`: reviewable experiment contract report.
- `experiment_run_attempts.jsonl`: append-only local experiment run attempts with exit codes, logs, and detected artifacts.
- `experiment_run_attempts.md`: reviewable rendering of experiment run attempts.
- `revision_plan.md`: item-level revision plan.
- `response_letter.md`: conservative point-by-point response draft.
- `proof_audit.md`: proof-lane assumptions, dependencies, unverified steps, and approval checklist.
- `experiment_plan.md`: experiment commands, seeds, expected artifacts, and result backfill fields.
- `manuscript.patch`: reviewable placeholder diff; it is not auto-applied.
- `candidate_edits.json`: proposed, edited, approved, rejected, blocked, and applied manuscript edits with safe patch operations.
- `decision_log.md`: append-only rationale log for proof audits, experiment plans, and reasoning.
- `experiment_runs.jsonl`: author-recorded experiment result provenance.
- `apply_log.jsonl`: append-only log for applied candidate edits.
- `agent_state.json`: deterministic safe-auto task queue and last run state.
- `agent_state.md`: reviewable rendering of pending, blocked, done, failed, and skipped agent tasks.
- `agent_runs.jsonl`: append-only safe task execution ledger.
- `agent_runs.md`: reviewable rendering of recent agent task runs.
- `agent_policy.json`: safe-auto, manual-required, and disallowed agent task policy.
- `agent_policy.md`: reviewable rendering of the agent safety policy.
- `agent_report.md`: latest scheduler report covering stale inputs, failed tasks, and manual gates.
- `agent_dashboard.md`: single-page monitor view with the current session, next action, lane progress, manual decisions, failed/stale tasks, and recent runs.
- `agent_sessions.jsonl`: goal-oriented agent session records with phases, status, blockers, and linked run ids.
- `agent_sessions.md`: reviewable rendering of goal-oriented agent sessions.
- `agent_decisions.json`: stable operator decision queue for manual gates and high-risk candidate decisions.
- `agent_decisions.md`: reviewable rendering of open, stale, resolved, and dismissed decisions.
- `agent_eval_report.json`: deterministic agent trajectory eval results for built-in fixtures.
- `agent_eval_report.md`: reviewable rendering of the latest agent eval report.
- `llm_drafts.json`: offline reviewer-intent, response, candidate-text drafts, author review status, and quality status marked as `llm_draft`.
- `llm_drafts.md`: reviewable rendering of LLM drafts, review notes, and quality issues; these are never auto-approved or auto-applied.
- `revision_provenance.json`: per-item provenance snapshot linking reviewer comments, LLM drafts, candidates, proof/experiment gates, and apply records.
- `revision_provenance.md`: reviewable provenance report.
- `revision_readiness.json`: per-item revision readiness status, blockers, and submit-pack gaps.
- `revision_readiness.md`: reviewable readiness report grouped by blockers and ready items.

## Commands

- `revagent init`: create `.revagent`.
- `revagent ingest-comments`: split and classify reviewer comments.
- `revagent plan`: index LaTeX and write revision/proof/experiment plans.
- `revagent analyze-review R001|--all [--force]`: create structured reviewer-intent, claim/evidence, risk, and response-strategy analysis.
- `revagent review-analysis [R001]`: show structured review analyses.
- `revagent plan-item R001|--all [--force]`: create deterministic per-item planning records.
- `revagent draft`: write response letter and patch notes.
- `revagent llm-draft R001|--all [--force] [--provider fake|openai-compatible]`: generate `llm_draft` reviewer intent, response, and candidate text without approving or applying edits.
- `revagent llm-review R001`: show an LLM draft for author review.
- `revagent llm-accept R001`: mark an LLM draft as accepted while leaving candidate approval separate.
- `revagent llm-reject R001 --note text`: reject an LLM draft with an author note.
- `revagent llm-edit R001 [--response-file path] [--candidate-file path]`: replace draft response and/or candidate text from author-edited files.
- `revagent llm-check R001|--all`: run deterministic quality checks for LLM draft safety boundaries.
- `revagent incorporate-drafts`: regenerate response letter and patch notes using only accepted/edited, quality-passed LLM drafts.
- `revagent schema`: print the workspace schema.
- `revagent migrate --dry-run|--apply`: inspect or apply safe workspace schema backfills.
- `revagent proof-audit [R001]`: show proof dependency and approval context.
- `revagent proof-plan R001`: create a proof workflow with snapshots, dependencies, and obligations.
- `revagent proof-obligation R001 --add text`: add a proof obligation to the workflow.
- `revagent proof-approve R001 --note text`: record author approval and close proof obligations.
- `revagent experiment-plan [R002]`: show experiment command/provenance plan.
- `revagent experiment-contract R002`: create a reproducibility contract for an experiment item.
- `revagent experiment-run R002 --dry-run|--record`: preview or explicitly execute the manifest command, capture logs, and record detected expected artifacts.
- `revagent experiment-artifact R002 --path path --kind table|figure|log|data --note text`: record an artifact and sha256 hash.
- `revagent experiment-incorporate R002 --target label --field name --text-file text.tex`: record how results are backfilled into the manuscript.
- `revagent record-result R002 --artifact path --note text`: record author-confirmed experiment result provenance.
- `revagent reason R001`: explain reviewer intent, context, risk, and blocked questions.
- `revagent propose [--force]`: generate candidate manuscript edits.
- `revagent inspect R001|C001`: inspect a review item or candidate edit.
- `revagent edit-candidate C001 --text-file text.tex`: replace candidate content with author-provided LaTeX text.
- `revagent approve C001 [--allow-high-risk]`: approve a candidate edit for application.
- `revagent reject C001`: reject a candidate edit.
- `revagent close-item R001`: close an incorporated or fully resolved review item.
- `revagent reopen-item R001`: reopen a closed item to `planned`.
- `revagent apply --dry-run`: print the approved candidate diff without writing files.
- `revagent apply --approved`: write approved candidate insertions after backing up touched files.
- `revagent restore --backup path`: restore TeX files from a RevAgent backup directory.
- `revagent provenance [R001]`: generate and show end-to-end revision provenance for all items or one item.
- `revagent readiness [R001]`: refresh and show revision readiness for all items or one item.
- `revagent submit-pack --dry-run`: summarize missing response-letter, TeX, validation, manual-gate, and blocker pieces before final submission.
- `revagent validate [--compile]`: validate schema, LaTeX references, and optionally run `latexmk`.
- `revagent status`: show item counts and workspace configuration.
- `revagent agent-status`: build and print the safe-auto agent task queue without executing tasks.
- `revagent monitor`: write and print the current agent dashboard for the revision workspace.
- `revagent agent-plan --goal rebuttal-draft|proof-response|experiment-response|full-revision-pass`: create a goal-oriented agent session.
- `revagent agent-session`: show recorded agent sessions.
- `revagent agent-resume [--limit N] [--retry-failed] [--watch --interval N --cycles N]`: resume the current session through safe-auto tasks until blocked or complete; watch mode repeats resume cycles until the session blocks, fails, completes, or reaches the cycle limit.
- `revagent agent-blockers`: show current manual gates and failed tasks with recovery commands.
- `revagent agent-complete-check`: refresh the current session status from the task graph.
- `revagent agent-decisions`: refresh and show the manual decision queue.
- `revagent agent-decision D001`: show one decision with context, risk, and required command.
- `revagent agent-decision-resolve D001 --note text`: mark a decision resolved after its underlying gate is complete.
- `revagent agent-decision-dismiss D001 --note text`: dismiss a decision with an author note.
- `revagent agent-eval [--fixture full-revision|stale-input|safety-gates|--all]`: run deterministic agent trajectory regression fixtures and write `agent_eval_report`.
- `revagent agent-next`: show the next safe task or blocking manual gate with the required command.
- `revagent agent-run [--limit N] [--until-blocked] [--retry-failed] [--max-failures N]`: execute safe tasks such as planning, proof/experiment contracts, draft/propose, LLM draft generation/checking, provenance refresh, and validation; every task run is logged with input dependency hashes.
- `revagent agent-report`: write and print the scheduler, stale-input, failure, and manual-gate report.
- `revagent doctor`: check Python, workspace, profiles, and optional `latexmk`.
- `revagent clean`: remove generated logs and exported artifacts.
- `revagent export`: copy deliverables into `.revagent/artifacts`.
- `revagent profiles`: list built-in and local journal profiles.

## LLM Providers

`revagent llm-draft` defaults to the deterministic offline `fake` provider. To use
an OpenAI-compatible chat-completions endpoint, set:

```powershell
$env:REVAGENT_LLM_BASE_URL="https://api.example.com/v1"
$env:REVAGENT_LLM_API_KEY="..."
$env:REVAGENT_LLM_MODEL="model-name"
revagent llm-draft R003 --provider openai-compatible
```

Provider outputs are still stored only as `llm_draft`; API keys are never written
to workspace artifacts, and drafts must pass author review and quality checks
before any separate candidate approval workflow.

## Journal Profiles

Built-in profiles: `siam`, `ams`, `springer`, and `elsevier`.

You can add or override profiles with `journal_profiles/<name>.yaml`:

```yaml
display_name: My Journal
response_heading: Response to the Associate Editor and Reviewers
tone: concise, formal, and mathematically precise
checks:
  - verify theorem numbering
  - confirm figure captions and table references
style_hints:
  - cite exact manuscript locations in every response
```

Then run:

```powershell
revagent init --journal myjournal --tex-root .
```

## Demo

See `examples/latex_revision_demo/` for a complete miniature LaTeX revision
project with theorem/proof content, a figure/table, experiment scaffolding, and
reviewer comments.

`revagent` indexes from the configured main TeX file when possible, following
basic `\input{}` and `\include{}` links. Candidate edits store scored location
evidence so `revagent inspect` can explain why a reviewer item was mapped to a
section, theorem/proof block, figure, table, label, or fallback line.

The package keeps `revagent.core` as a compatibility facade while exposing
subsystem modules for new integrations: `agent`, `workspace`, `latex`, `reviews`,
`planning`, `proofs`, `experiments`, `candidates`, `llm`, `review_analysis`,
`lanes`, `rendering`, and `validation`.
