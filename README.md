# RevAgent

[简体中文](README.zh-CN.md)

> **v0.1.0 alpha — shadow-only and calibration-required.** RevAgent is a local-first workspace for organizing computational-mathematics revisions. It does not certify proofs or numerical conclusions, submit manuscripts, upload project material, or publish user data.

RevAgent turns a LaTeX manuscript and reviewer comments into auditable local artifacts: review items, source locations, revision plans, response drafts, evidence records, and author decisions. It is designed to make a revision easier to inspect—not to replace an author or domain expert.

## Install

```powershell
python -m pip install -e .[dev]
```

Python 3.10 or newer is required.

## Start here

From a copy of your LaTeX project:

```powershell
revagent init --journal siam --tex-root . --main-tex paper.tex
revagent ingest-comments reviewer_comments.md
revagent plan
revagent draft
revagent cockpit
revagent validate
```

All generated records remain in `.revagent/`. Review the response draft and candidate edits before making any manuscript change.

## The everyday workflow

| Goal | Command |
| --- | --- |
| Inspect a reviewer item | `revagent inspect R001` |
| Build or view a per-item plan | `revagent plan-item R001` / `revagent review-analysis R001` |
| Audit a proof request | `revagent proof-plan R001` then `revagent proof-audit R001` |
| Record an experiment contract | `revagent experiment-contract R002` |
| See traceability and blockers | `revagent response-trace` / `revagent readiness` |
| Open the local overview | `revagent cockpit` |
| Check a final hand-off package | `revagent submit-pack --dry-run` |

Use `revagent --help` to list commands, and `revagent <command> --help` for options. The CLI also exposes advanced runtime, worker, benchmark, and automation interfaces for controlled integrations; they are intentionally not needed for a first revision.

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

Useful links: [demo project](examples/latex_revision_demo/), [contributing](CONTRIBUTING.md), [security policy](SECURITY.md), and [changelog](CHANGELOG.md).
