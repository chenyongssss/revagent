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
revagent plan-item --all
revagent draft
revagent migrate --dry-run
revagent proof-audit R001
revagent proof-plan R001
revagent proof-obligation R001 --add "Verify the theorem dependencies."
revagent proof-approve R001 --note "Author verified the proof change."
revagent experiment-plan R002
revagent experiment-contract R002
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
revagent validate
revagent export
```

The workspace is written to `.revagent/`. Per-item planning status follows
`triaged -> planned -> drafted -> evidence_ready -> approved -> incorporated -> closed`.

## Workspace Files

- `review_items.json`: structured reviewer/editor items.
- `latex_index.json`: reachable TeX files, includes, sections, custom theorem-like environments, theorem/proof/algorithm/figure/table blocks, labels, refs, citations, and unresolved refs.
- `item_plans.json`: structured per-review-item planner records.
- `item_plans.md`: reviewable rendering of reviewer intent, evidence, edit plan, dependencies, blockers, and completion criteria.
- `proof_workflows.json`: structured proof workflow records with statement/proof snapshots, dependencies, obligations, and approval status.
- `proof_workflows.md`: reviewable proof workflow report.
- `experiment_manifests.json`: reproducibility contracts with command templates, seeds, artifact hashes, and backfill targets.
- `experiment_manifests.md`: reviewable experiment contract report.
- `revision_plan.md`: item-level revision plan.
- `response_letter.md`: conservative point-by-point response draft.
- `proof_audit.md`: proof-lane assumptions, dependencies, unverified steps, and approval checklist.
- `experiment_plan.md`: experiment commands, seeds, expected artifacts, and result backfill fields.
- `manuscript.patch`: reviewable placeholder diff; it is not auto-applied.
- `candidate_edits.json`: proposed, edited, approved, rejected, blocked, and applied manuscript edits with safe patch operations.
- `decision_log.md`: append-only rationale log for proof audits, experiment plans, and reasoning.
- `experiment_runs.jsonl`: author-recorded experiment result provenance.
- `apply_log.jsonl`: append-only log for applied candidate edits.

## Commands

- `revagent init`: create `.revagent`.
- `revagent ingest-comments`: split and classify reviewer comments.
- `revagent plan`: index LaTeX and write revision/proof/experiment plans.
- `revagent plan-item R001|--all [--force]`: create deterministic per-item planning records.
- `revagent draft`: write response letter and patch notes.
- `revagent schema`: print the workspace schema.
- `revagent migrate --dry-run|--apply`: inspect or apply safe workspace schema backfills.
- `revagent proof-audit [R001]`: show proof dependency and approval context.
- `revagent proof-plan R001`: create a proof workflow with snapshots, dependencies, and obligations.
- `revagent proof-obligation R001 --add text`: add a proof obligation to the workflow.
- `revagent proof-approve R001 --note text`: record author approval and close proof obligations.
- `revagent experiment-plan [R002]`: show experiment command/provenance plan.
- `revagent experiment-contract R002`: create a reproducibility contract for an experiment item.
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
- `revagent validate [--compile]`: validate schema, LaTeX references, and optionally run `latexmk`.
- `revagent status`: show item counts and workspace configuration.
- `revagent doctor`: check Python, workspace, profiles, and optional `latexmk`.
- `revagent clean`: remove generated logs and exported artifacts.
- `revagent export`: copy deliverables into `.revagent/artifacts`.
- `revagent profiles`: list built-in and local journal profiles.

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
subsystem modules for new integrations: `workspace`, `latex`, `reviews`,
`candidates`, `lanes`, `rendering`, and `validation`.
