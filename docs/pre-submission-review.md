# Pre-submission Review MVP

The local pre-submission review is an advisory, deterministic check over the
reachable LaTeX source tree. It never sends paper material to a provider,
modifies a manuscript, asserts mathematical correctness, or recommends
acceptance.

After creating a normal RevAgent workspace, run:

```powershell
revagent review-paper --journal sisc
revagent review-status
```

The command writes `.revagent/pre_submission_review.json` and Markdown. Its
first checks cover unresolved references, missing captions, theorem/proof
structure, bibliography declarations, and profile-required structural signals.
High-risk findings require author or domain-expert review.

## Phase 2: freshness and rulepack provenance

Each generated report records an input fingerprint covering the reachable LaTeX
tree and the effective local journal rulepack. `revagent review-status` returns
nonzero and `revagent validate` emits a warning if either input changes; rerun
`revagent review-paper` to refresh the advisory report. Cockpit and dashboard
surface the same `stale` status. This tracks report provenance only and does
not certify manuscript correctness or submission readiness.

## Paper manifest and rendered observations

`revagent paper-ingest` creates a versioned source/PDF manifest. For each
theorem-like environment it records the source span, structurally adjacent
proof environment, referenced claims or assumptions, and an optional PDF page
reported by local SyncTeX data. When `pdfinfo` and `pdftotext` are available,
it also records page counts and per-page extractable-text counts. A text-empty
page may contain graphics or inaccessible text and is only a prompt for manual
inspection. Neither structural proof binding nor a source-to-page mapping
establishes semantic correctness.

## Reviewer-pack evaluation

`revagent benchmark-review-suite --suite PATH` measures deterministic reviewer
roles against local adjudicated labels. Each case must record at least two
distinct pseudonymous annotators and an adjudicator; model self-scores are
rejected. Reports include exact paper/label hashes and compute defect recall,
high-risk recall, and false-pass rate globally, by role, and by reviewer pack.
The records do not prove annotator expertise or independence and are not a
release calibration without the documented human protocol.

## Local journal rulepacks

RevAgent prefers a project-local directory rulepack at
`journal_profiles/<name>/`, containing `profile.yaml`, `rubric.yaml`,
`submission.yaml`, `rebuttal.yaml`, and `sources.md`. Legacy
`journal_profiles/<name>.yaml` files remain readable for compatibility.
Use `revagent journal list`, `journal validate`, `journal init`, and
`journal diff` to inspect and manage local rulepacks. A newly initialized pack
is deliberately unconfirmed and cannot silently produce a journal-specific
report.

The legacy flat parser supports top-level scalar values and lists:

```yaml
display_name: My Numerical Analysis Journal
response_heading: Response to the Editor and Reviewers
tone: precise and collegial
version: 1
required_checks:
  - contribution_statement
  - reproducibility
  - bibliography
checks:
  - Confirm page limits from the official journal site.
  - Confirm data and code policy before submission.
```

Keep the official source URL, retrieval date, and a human approval note in an
adjacent `sources.md`. Rulepacks are local policy inputs, not an assertion that
the journal has endorsed RevAgent or that a submission satisfies all rules.

The legacy `scripts/review-paper.py` and `scripts/review-status.py` wrappers
remain available for direct use, but the stable interface is the `revagent` CLI.
