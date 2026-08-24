# RevAgent

[简体中文](README.zh-CN.md)

RevAgent turns a LaTeX manuscript and reviewer comments into auditable local artifacts: review items, source locations, revision plans, response drafts, evidence records, and author decisions. It is designed to make a revision easier to inspect—not to replace an author or domain expert.

![RevAgent workflow: reviewer feedback flows through an auditable revision graph, evidence checks, local protection, and human approval.](docs/assets/revagent-workflow.png)

## 1. Install in Codex or a terminal

Use a terminal in the Codex workspace, or any local terminal with Python 3.10+:

```powershell
git clone https://github.com/chenyongssss/revagent.git
cd revagent
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
python -m pytest
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`.

If you use Codex, open the cloned `revagent` folder first and run the commands above in its terminal. Afterwards, open your separate review workspace in Codex when you want assistance inspecting local artifacts or running RevAgent commands.

## 2. Prepare a review workspace

Work from a **copy** of the manuscript, not your only original. Create one folder per revision:

```text
my-paper-review/
  manuscript/
    paper.tex
    sections/
    bibliography.bib
  reviewer_comments.md
```

Put the complete LaTeX source tree in `manuscript/`, including files referenced by `\\input` or `\\include`. Put editor/reviewer comments in `reviewer_comments.md`; local Markdown, text, DOCX, and PDF imports are supported.

## 3. Run the first review pass

From `my-paper-review/`:

```powershell
revagent init --journal siam --tex-root manuscript --main-tex paper.tex
revagent ingest-comments reviewer_comments.md
revagent plan
revagent draft
revagent cockpit --lang en
revagent validate
```

What each command does:

- `init` creates the local `.revagent/` record and identifies the manuscript entry point.
- `ingest-comments` imports and numbers editor/reviewer requests as individual review items.
- `plan` maps those items to the LaTeX source and prepares revision or evidence obligations; it does not alter the manuscript.
- `draft` prepares reviewable response and candidate-edit artifacts; it does not apply edits.
- `cockpit --lang en` creates the local English overview. Use `--lang zh` for Chinese.
- `validate` checks the workspace, state, and traceability before hand-off; add `--compile` only when you explicitly want a LaTeX compilation check.

All generated records remain in `.revagent/`. Review the response draft and candidate edits before making any manuscript change.

## 4. Review and hand off

| Goal | Command |
| --- | --- |
| Inspect a reviewer item | `revagent inspect R001` |
| Build or view a per-item plan | `revagent plan-item R001` / `revagent review-analysis R001` |
| Audit a proof request | `revagent proof-plan R001` then `revagent proof-audit R001` |
| Record an experiment contract | `revagent experiment-contract R002` |
| See traceability and blockers | `revagent response-trace` / `revagent readiness` |
| Open the local overview | `revagent cockpit --lang en` / `revagent cockpit --lang zh` |
| Check a final hand-off package | `revagent submit-pack --dry-run` |

Use `revagent --help` to list commands, and `revagent <command> --help` for options. The CLI also exposes advanced runtime, worker, benchmark, and automation interfaces for controlled integrations; they are intentionally not needed for a first revision.

For a local browser interface, run `revagent serve` and open `http://127.0.0.1:8765/cockpit?lang=en` or `http://127.0.0.1:8765/cockpit?lang=zh`.

## Safety boundaries

- Proof, stability, convergence, experiment, response-fact, and final-PDF decisions always require explicit author or domain-expert approval.
- Candidate edits are reviewable first. They are never silently applied.
- Experiments are opt-in and recorded as evidence, not as automatically confirmed scientific conclusions.
- Remote providers are off by default. A task-specific, time-limited authorization is required before an enabled remote action can receive selected material.
- The local cockpit, validation, provenance, and readiness reports show missing, stale, waived, and escalated work rather than hiding it.

See [SECURITY.md](SECURITY.md) for the complete privacy and execution boundary.

## Community calibration

The repository contains synthetic fixtures only. To prepare a voluntary case for possible future governance review, first create a data-card template and then export a **local metadata-only** candidate package:

```powershell
revagent contribution-template --case-id community-001
revagent contribution-export --case-dir C:\path\to\deidentified_case --case-id community-001 --data-card C:\path\to\data_card.json --confirm
```

The export contains a data card, safety scan, and file fingerprints—never manuscript text, reviewer comments, source code, or data. RevAgent does not verify deidentification or publication rights; sharing still needs human governance approval.

## Development and release status

```powershell
python -m pytest
```

CI tests Windows, Linux, and macOS. Release assets include checksums, an SPDX SBOM, and GitHub build attestations. See [RELEASE_NOTES.md](RELEASE_NOTES.md) for v0.1.0 limitations and verification instructions.

Useful links: [contributing](CONTRIBUTING.md), [security policy](SECURITY.md), and [changelog](CHANGELOG.md).
