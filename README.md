# RevAgent

[简体中文](README.zh-CN.md)

RevAgent is a local-first, auditable revision assistant for computational-mathematics manuscripts. It turns editor and reviewer feedback into tracked review items, source locations, revision plans, evidence records, response drafts, and explicit author decisions.

Built for revision workflows common in journals such as *SIAM Journal on Scientific Computing (SISC)*, *SIAM Journal on Numerical Analysis (SINUM)*, *Mathematics of Computation*, *IMA Journal of Numerical Analysis*, *Journal of Computational Physics*, and *Numerische Mathematik*. These are representative use cases, not endorsements or submission guarantees.

![RevAgent workflow: reviewer feedback flows through an auditable revision graph, evidence checks, local protection, and human approval.](docs/assets/revagent-workflow.png)

## What it supports

| Material | Support |
| --- | --- |
| Manuscript | A complete LaTeX source tree. RevAgent can index labels, theorem-like environments, references, and source locations; candidate edits and compilation checks are LaTeX-only in v0.1. |
| Reviewer comments | **Preferred:** `.tex` or `.md`, parsed directly. `.txt` is also parsed directly. `.docx` and text-based `.pdf` are converted locally to an auditable Markdown copy before parsing. |

All material stays local. A converted comment copy, its source hash, and its conversion record are written under `.revagent/`; the original file is never changed or uploaded.

## 1. Install

Use a terminal in the Codex workspace, or any local terminal with Python 3.10+:

```powershell
git clone https://github.com/chenyongssss/revagent.git
cd revagent
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

On macOS or Linux, activate with `source .venv/bin/activate`.

## 2. Prepare one revision workspace

Work from a copy of the manuscript:

```text
my-paper-review/
  manuscript/
    paper.tex
    sections/
    bibliography.bib
  reviewer_comments.tex   # or .md, .txt, .docx, .pdf
```

Keep the full LaTeX source tree in `manuscript/`, including files referenced by `\input` or `\include`. TeX and Markdown reviewer files are recommended because their item boundaries and line locations are preserved directly.

## 3. Run the first pass

From `my-paper-review/`:

```powershell
revagent init --journal siam --tex-root manuscript --main-tex paper.tex
revagent ingest-comments reviewer_comments.tex
revagent plan
revagent draft
revagent cockpit --lang en
revagent validate
```

- `init` creates `.revagent/` and identifies the manuscript entry point.
- `ingest-comments` imports individual editor/reviewer requests; DOCX and PDF imports also create a local normalized Markdown record.
- `plan` connects requests to LaTeX locations and records revision or evidence obligations without changing the manuscript.
- `draft` prepares reviewable response and candidate-edit artifacts without applying them.
- `cockpit --lang en` creates a local overview; use `--lang zh` for Chinese.
- `validate` checks workspace state, provenance, and traceability. Add `--compile` only for an explicit LaTeX compilation check.

## Safety boundary

RevAgent never certifies proofs, stability, convergence, experiments, response facts, or a final PDF. Those decisions require author or domain-expert approval. Candidate edits are reviewable first and are never silently applied.

## More

See [advanced usage](docs/advanced-usage.md) for per-item commands, local browser access, community calibration, development, and release verification. See [security](SECURITY.md), [contributing](CONTRIBUTING.md), and [release notes](RELEASE_NOTES.md) for policy and project details.
