# Reviewer Pack Evaluation Suites

Each case is a directory containing `paper.tex` and `labels.json`. Labels are
accepted only after adjudication by at least two distinct pseudonymous human
annotators. Model self-scores are rejected.

Required `labels.json` shape:

```json
{
  "version": 1,
  "fixture_id": "local-case-id",
  "pack": "numerical-pde",
  "expected_findings": [
    {"role": "theory-reviewer", "category": "claim_evidence", "high_risk": true}
  ],
  "must_not_pass": true,
  "label_provenance": {
    "status": "adjudicated",
    "source": "independent_human_review",
    "annotators": ["expert-a", "expert-b"],
    "adjudicated_by": "expert-a",
    "labelled_at": "YYYY-MM-DD"
  }
}
```

Run `revagent benchmark-review-suite --suite PATH`. The report measures defect
recall, high-risk recall, and false-pass rate globally, by reviewer role, and by
pack. Pseudonyms and schema checks cannot prove expertise or independence;
those remain human-governed release requirements.
