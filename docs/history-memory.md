# Personal Revision History

History retrieval is local and author-controlled. Import stores a source hash,
purpose, and pending consent only; it does not retain the source path or text.

```powershell
revagent history import history.txt --purpose "style precedent"
revagent history redact H-001 --source-file history.txt --retention project_lifetime
revagent history approve H-001
revagent history rebuild
revagent history enforce-retention
revagent history search "stability response"
revagent benchmark-history-suite --suite adjudicated-history-suite
revagent history export private-history-export
revagent history delete H-001 --confirm
```

Review `.revagent/history_previews/H-001.txt` before approval. The deterministic
redactor covers common emails, ORCID-like identifiers, credential assignments,
and submission identifiers; it cannot guarantee complete deidentification.
Only approved, untampered, non-deleted previews enter SQLite FTS. Deletion
removes the preview and index entry while retaining an audit tombstone. Exports
contain approved redacted previews and a hash manifest, never the imported raw
source. Retrieval is for style or precedent suggestions only.

The `30_days` rule is enforced automatically before rebuild, search, and export,
using approval time (or redaction time for migrated records). Expiration removes
the preview and index entry and retains an `expired` audit tombstone.
`project_lifetime` and `until_deleted` require explicit project or user action.

History benchmark cases use the same SQLite FTS5/BM25 ranking strategy. Each
`labels.json` contains exactly `version`, `fixture_id`, `query`, `corpus`,
`relevant_history_ids`, and `label_provenance`. Provenance must record
`independent_human_review`, two distinct pseudonymous annotators, an adjudicator,
and a date. Fixture text must already be deidentified and authorized. Reports
measure Recall@5, Precision@5, MRR, and zero-hit rate; they are not release or
semantic-quality calibration.

Real-case intake and publication are separate, fail-closed steps:

```powershell
revagent history-case init case-001 --query "stability estimate" --corpus corpus.json --data-card data-card.json --confirm
revagent history-case annotate case-001 --annotator expert-a --relevant-history-id H-001 --note "Independent assessment"
revagent history-case annotate case-001 --annotator expert-b --relevant-history-id H-001 --note "Independent assessment"
revagent history-case adjudicate case-001 --adjudicator expert-a --relevant-history-id H-001 --note "Resolved after independent review"
revagent history-case export-fixture case-001 --suite adjudicated-history-suite
revagent history-quality-publish --suite adjudicated-history-suite
```

Publication additionally requires each exported fixture to carry its data card
with written permission, completed deidentification, the
`history_retrieval_benchmark` purpose, and `public_benchmark` visibility. With no
such real cases, `.revagent/history_quality_report.json` remains explicitly
`not_published`; RevAgent does not substitute synthetic cases for real evidence.
