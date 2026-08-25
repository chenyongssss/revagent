# RevAgent

<p align="center"><strong>Local-first · Auditable · Human-gated</strong></p>

<p align="center"><a href="README.zh-CN.md">简体中文</a> · <a href="#quick-start">Quick start</a> · <a href="docs/advanced-usage.md">Advanced usage</a> · <a href="SECURITY.md">Security</a></p>

RevAgent is a local-first, auditable revision assistant for computational-mathematics manuscripts. It turns editor and reviewer feedback into tracked review items, source locations, revision plans, evidence records, response drafts, and explicit author decisions.

> [!NOTE]
> Designed for revision workflows common in *SISC*, *SINUM*, *Mathematics of Computation*, *IMA Journal of Numerical Analysis*, *Journal of Computational Physics*, and *Numerische Mathematik*. These are representative use cases, not endorsements or submission guarantees.

<p align="center"><img src="docs/assets/revagent-workflow.png" alt="RevAgent workflow: reviewer feedback flows through an auditable revision graph, evidence checks, local protection, and human approval." width="1200"></p>

<p align="center"><em>Feedback → revision map → evidence → human review → response package</em></p>

## At a glance

| Material | Support |
| --- | --- |
| Manuscript | A complete LaTeX source tree. RevAgent can index labels, theorem-like environments, references, and source locations; candidate edits and compilation checks are LaTeX-only in v0.1. |
| Reviewer comments | **Preferred:** `.tex` or `.md`, parsed directly. `.txt` is also parsed directly. `.docx` and text-based `.pdf` are converted locally to an auditable Markdown copy before parsing. |
| Coding agents | Any coding agent can help deploy RevAgent and run its local workflow. The optional external automation commands (`revagent run` and Codex review workers) currently require the Codex CLI. |

All material stays local. A converted comment copy, its source hash, and its conversion record are written under `.revagent/`; the original file is never changed or uploaded.

> [!TIP]
> For the clearest item boundaries and source locations, use TeX or Markdown for reviewer comments.

## Quick start

### 1. Install

Use any local terminal with Python 3.10+, including the terminal provided by Codex, Claude Code, or another coding agent:

```powershell
git clone https://github.com/chenyongssss/revagent.git
cd revagent
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

On macOS or Linux, activate with `source .venv/bin/activate`.

**Using a coding agent:** Codex, Claude Code, or another local coding agent can open the cloned `revagent` folder and perform this installation for you. Afterward, the standard local workflow does not require an agent environment. The optional `revagent run` and Codex review-worker automation features are the current exception: they require the Codex CLI.

### 2. Prepare one revision workspace

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

### 3. Run the first pass

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

**Result:** inspect the generated local records in `.revagent/`, then use the cockpit or the advanced commands when you are ready to review individual items.

## Safety boundary

> [!IMPORTANT]
> RevAgent never certifies proofs, stability, convergence, experiments, response facts, or a final PDF. Those decisions require author or domain-expert approval. Candidate edits are reviewable first and are never silently applied.

## More

- [User guide](docs/user-guide.md): the complete practical workflow, artifacts, per-item review, validation, and hand-off.
- [Dashboard guide](docs/dashboard.md): static cockpit files, local browser service, endpoints, and lifecycle.
- [Community contributions](docs/community-contributions.md): how to prepare an openly shareable case without exposing material accidentally.
- [Advanced usage](docs/advanced-usage.md): compact command reference, development, and release verification.
- [Security](SECURITY.md): privacy and execution boundaries.
- [Contributing](CONTRIBUTING.md) and [release notes](RELEASE_NOTES.md): project collaboration and version limitations.
