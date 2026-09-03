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

`paper-dependency-review` records a pseudonymous human assessment of a
structurally detected claim dependency. `paper-experiment-bind` binds a current,
previously recorded experiment artifact hash to a current claim hash. Changed
claim or artifact content invalidates the binding. Neither command confirms
proof correctness or experimental validity. When installed, `pdffonts`,
`pdfimages`, and `pdftotext -bbox-layout` add advisory observations for font
embedding, image-bearing pages, and text boxes outside PDF page boundaries.

## Reviewer-pack evaluation

`revagent benchmark-review-suite --suite PATH` measures deterministic reviewer
roles against local adjudicated labels. Each case must record at least two
distinct pseudonymous annotators and an adjudicator; model self-scores are
rejected. Reports include exact paper/label hashes and compute defect recall,
high-risk recall, and false-pass rate globally, by role, and by reviewer pack.
The records do not prove annotator expertise or independence and are not a
release calibration without the documented human protocol.

## Rebuttal linting

Use `rebuttal approve ... --response-file PATH` to bind author-written response
text to an atom. `rebuttal stress-test` then checks atom coverage, manuscript
and evidence locators, unresolved placeholders, future-tense commitments,
several clearly discourteous phrases, and configured length limits. Directory
rulepacks may define positive integer `max_words` and
`max_words_per_response` values in `rebuttal.yaml`; absent or zero values mean
that no verified limit is applied. These deterministic matches require author
interpretation and never verify facts, experiments, or mathematical claims.

## Consent-gated literature metadata

OpenAlex, Crossref, arXiv, and DOI content-negotiation connectors retrieve
metadata only. Each request requires both provider consent and a matching,
unused per-query authorization; remote requests also require a passing privacy
scan. For example:

```powershell
revagent literature authorize crossref --purpose "related-work metadata"
revagent literature authorize-query crossref --query "finite element estimator" --purpose "related-work metadata" --final-report-permission
revagent literature fetch crossref --query "finite element estimator" --authorization-id LQ-001
revagent literature report
revagent literature graph
revagent literature retractions
revagent literature align
revagent literature align-review ALN-ID --decision approve --relationship background --note "Author-verified context"
```

Cache records retain the endpoint, content type, canonical response hash, raw
provider response, normalized metadata, and authorization link. Records without
`--final-report-permission` remain local and are excluded from the provenance
report. Retrieved metadata is not evidence of novelty, priority, correctness,
or journal suitability.

The graph records each citation or provider-declared relationship together with
the provider, query authorization, and cached response hash. Retraction status
is derived conservatively from Crossref `update-to` and relationship metadata.
`no_retraction_metadata_observed` means only that the permitted cached metadata
contained no matching assertion; it never means that a work is confirmed not
to be retracted.

Claim alignment is local and deterministic: it compares indexed claim excerpts
with permitted metadata titles and emits at most five lexical-overlap candidates
per claim. Candidates remain `pending_author_review` until explicitly approved
or rejected. Approval records a relationship (`supports`, `contrasts`,
`background`, or `method`) and an author note; the score itself is never a
semantic judgment or novelty assessment.

`revagent benchmark-alignment-suite --suite PATH` evaluates the deterministic
ranker against local adjudicated fixtures. Labels require at least two distinct
pseudonymous annotators, an adjudicator, and independent-human-review
provenance. Reports bind label hashes and measure recall@5, precision@5, mean
reciprocal rank, and zero-hit rate. These measurements are not release or
novelty calibration.

Real-case intake remains local and human-gated:

```powershell
revagent alignment-case init case-001 --claim-file deidentified_claim.txt --candidates candidates.json --data-card data_card.json --confirm
revagent alignment-case annotate case-001 --annotator expert-a --relevant-work-id 10.x/a --note "Independent assessment"
revagent alignment-case annotate case-001 --annotator expert-b --relevant-work-id 10.x/a --note "Independent assessment"
revagent alignment-case adjudicate case-001 --adjudicator expert-a --relevant-work-id 10.x/a --note "Resolved disagreement"
revagent alignment-case export-fixture case-001 --suite benchmarks/alignment
```

The data card must record written permission, completed deidentification,
retention/access rules, and the `claim_alignment_benchmark` purpose. RevAgent
does not verify expert identity, independence, permission, or deidentification,
and performs no upload.

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
