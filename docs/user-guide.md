# RevAgent user guide

[中文](user-guide.zh-CN.md) · [Dashboard guide](dashboard.md) · [Community contributions](community-contributions.md)

## 1. What RevAgent does

RevAgent is a local, auditable workspace for computational-mathematics revision. It links each editor or reviewer request to manuscript locations, revision plans, evidence, response drafts, and explicit author decisions. It does not certify mathematical claims or submit a manuscript.

Use a complete LaTeX source tree for the manuscript. Reviewer comments may be `.tex`, `.md`, or `.txt`; `.docx` and text-based `.pdf` are normalized locally into `.revagent/imports/` before parsing.

## 2. Create and run a workspace

Create one folder per revision, starting from a copy of the manuscript:

```text
my-paper-review/
  manuscript/
    paper.tex
    sections/
  reviewer_comments.tex
```

From `my-paper-review/`, run:

```powershell
revagent init --journal siam --tex-root manuscript --main-tex paper.tex
revagent ingest-comments reviewer_comments.tex
revagent plan
revagent draft
revagent cockpit --lang en
revagent validate
```

Replace `reviewer_comments.tex` with the actual comment filename. `init` creates `.revagent/`; `ingest-comments` makes one tracked item per request; `plan` maps items to the LaTeX tree; `draft` prepares reviewable artifacts without applying edits; and `validate` checks the recorded state.

## 3. Read the generated artifacts

| Artifact | Purpose |
| --- | --- |
| `.revagent/review_items.json` | Canonical reviewer/editor items, risk and source locations. |
| `.revagent/comment_import.json` | Original-comment hash and, for DOCX/PDF, the normalized local copy. |
| `.revagent/revision_plan.md` | Workspace-level revision, proof, experiment, and open-issue plan. |
| `.revagent/response_letter.md` | Draft response structure; author review is still required. |
| `.revagent/author_cockpit.html` | English static dashboard; use `.zh.html` for Chinese. |
| `.revagent/revision_readiness.md` | Missing evidence, stale work, waivers, and blocking manual actions. |

## 4. Work one item at a time

| Goal | Command |
| --- | --- |
| Inspect an item | `revagent inspect R001` |
| Create a detailed plan | `revagent plan-item R001` |
| View reviewer-intent analysis | `revagent review-analysis R001` |
| Plan and audit a proof request | `revagent proof-plan R001`, then `revagent proof-audit R001` |
| Record experiment requirements | `revagent experiment-contract R002` |
| Trace response, manuscript, evidence, and PDF state | `revagent response-trace R001` |
| Review readiness | `revagent readiness` |

Candidate edits and generated response text are proposals. Review them, supply author text where required, and use the approval commands only after the relevant human review.

## 5. Validate and hand off

Run `revagent validate` after each meaningful change. Add `--compile` only when a local LaTeX toolchain is available and you intend to perform a compilation check. Before a final hand-off, run `revagent submit-pack --dry-run` and resolve every reported blocker, stale artifact, waiver, or escalation.

## 6. Dashboard and optional automation

Use `revagent cockpit --lang en` or `revagent cockpit --lang zh` for a static local dashboard. For the local browser service and its endpoints, see the [dashboard guide](dashboard.md). The normal workflow requires no coding-agent environment; only the optional external runner and Codex review-worker features require the Codex CLI.

## 7. Complete command reference

`revagent --help` lists every installed command. Use `revagent <command> --help` before advanced, remote, worker, benchmark, runtime, or automation commands. Those interfaces are intentionally not part of the first-pass workflow.

