# Personal Revision History

History retrieval is local and author-controlled. Import stores a source hash,
purpose, and pending consent only; it does not retain the source path or text.

```powershell
revagent history import history.txt --purpose "style precedent"
revagent history redact H-001 --source-file history.txt --retention project_lifetime
revagent history approve H-001
revagent history rebuild
revagent history search "stability response"
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
