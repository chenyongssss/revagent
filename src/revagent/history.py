"""Local consent-gated revision-history lifecycle and FTS index."""
from __future__ import annotations
import re, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from ._utils import file_sha256, load_config, now_iso, read_json, write_json

RETENTION_RULES = {"30_days", "project_lifetime", "until_deleted"}
PATTERNS = (("email", r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), ("orcid", r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b"),
            ("credential", r"\b(api[_ -]?key|token|password|secret)\s*[:=]\s*\S+"), ("submission_id", r"\b(manuscript|submission)\s*(id|number|no\.?|#)\s*[:=]?\s*[A-Z0-9._/-]+"))

def _registry(base):
    path = load_config(base).workspace / "history_registry.json"
    return path, read_json(path, {"version": 2, "records": []})

def _find(data, history_id):
    record = next((x for x in data.get("records", []) if x.get("history_id") == history_id), None)
    if not record: raise ValueError("unknown history record")
    return record

def import_history(base, path: Path, purpose: str) -> dict:
    enforce_history_retention(base)
    if not path.is_file(): raise ValueError("history source must be a file")
    if not purpose.strip(): raise ValueError("history purpose is required")
    target, data = _registry(base)
    record = {"history_id": f"H-{len(data['records']) + 1:03d}", "source_sha256": file_sha256(path), "imported_at": now_iso(), "purpose": purpose.strip(),
              "consent": "pending", "deidentification_status": "not_started", "retention_rule": "", "indexed": False,
              "raw_content_stored": False, "deletion_status": "active"}
    data["version"] = 2; data["records"].append(record); write_json(target, data); return record

def redact_history(base, history_id: str, source_path: Path, retention_rule: str) -> dict:
    enforce_history_retention(base)
    if retention_rule not in RETENTION_RULES: raise ValueError("invalid retention rule")
    target, data = _registry(base); record = _find(data, history_id)
    if not source_path.is_file() or file_sha256(source_path) != record.get("source_sha256"): raise ValueError("history source hash does not match imported record")
    text, counts = source_path.read_text(encoding="utf-8", errors="replace"), {}
    for label, expression in PATTERNS:
        text, count = re.subn(expression, f"[REDACTED_{label.upper()}]", text, flags=re.I)
        if count: counts[label] = count
    ws = load_config(base).workspace; preview = ws / "history_previews" / f"{history_id}.txt"
    preview.parent.mkdir(parents=True, exist_ok=True); preview.write_text(text, encoding="utf-8")
    deidentification = "approved" if record.get("consent") == "approved" else "preview_ready"
    record.update({"deidentification_status": deidentification, "redacted_at": now_iso(), "redaction_counts": counts, "retention_rule": retention_rule,
                   "preview_path": str(preview.relative_to(ws)), "preview_sha256": file_sha256(preview), "indexed": False})
    write_json(target, data); return record

def approve_history(base, history_id: str) -> dict:
    enforce_history_retention(base)
    target, data = _registry(base); record = _find(data, history_id)
    if record.get("consent") != "pending": raise ValueError("history record is not awaiting consent")
    if record.get("deidentification_status") != "preview_ready": raise ValueError("history record requires a redaction preview before approval")
    record.update({"consent": "approved", "deidentification_status": "approved", "approved_at": now_iso()}); write_json(target, data); return record

def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None

def _expire_history_records(base, current_time: datetime | None = None) -> list[str]:
    ws = load_config(base).workspace; target, data = _registry(base)
    current = current_time or datetime.now(timezone.utc)
    if current.tzinfo is None: current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc); expired = []
    for record in data.get("records", []):
        anchor = _parse_time(record.get("approved_at")) or _parse_time(record.get("redacted_at"))
        if record.get("deletion_status", "active") != "active" or record.get("retention_rule") != "30_days" or not anchor or current < anchor + timedelta(days=30):
            continue
        preview = ws / str(record.get("preview_path", ""))
        if preview.is_file(): preview.unlink()
        record.update({"deletion_status": "expired", "deletion_reason": "retention_expired", "expired_at": current.isoformat(),
                       "indexed": False, "preview_path": "", "preview_sha256": ""})
        expired.append(record["history_id"])
    if expired: write_json(target, data)
    return expired

def enforce_history_retention(base, current_time: datetime | None = None) -> dict:
    expired = _expire_history_records(base, current_time)
    if expired: rebuild_history_index(base, enforce_retention=False)
    return {"version": 1, "enforced_at": (current_time or datetime.now(timezone.utc)).isoformat(), "expired_history_ids": expired}

def rebuild_history_index(base, enforce_retention: bool = True) -> dict:
    if enforce_retention: _expire_history_records(base)
    ws = load_config(base).workspace; target, data = _registry(base); db = ws / "history_index.sqlite3"; con = sqlite3.connect(db); indexed = []
    try:
        con.execute("DROP TABLE IF EXISTS history_fts"); con.execute("CREATE VIRTUAL TABLE history_fts USING fts5(history_id UNINDEXED, purpose, content)")
        for record in data.get("records", []):
            record["indexed"] = False; preview = ws / str(record.get("preview_path", ""))
            if record.get("consent") == "approved" and record.get("deidentification_status") == "approved" and record.get("deletion_status", "active") == "active" and preview.is_file() and file_sha256(preview) == record.get("preview_sha256"):
                con.execute("INSERT INTO history_fts VALUES (?, ?, ?)", (record["history_id"], record["purpose"], preview.read_text(encoding="utf-8"))); record["indexed"] = True; indexed.append(record["history_id"])
        con.commit()
    finally: con.close()
    data["last_rebuilt_at"] = now_iso(); write_json(target, data); return {"version": 1, "rebuilt_at": data["last_rebuilt_at"], "indexed_history_ids": indexed, "index_path": str(db)}

def search_history(base, query: str, limit: int = 10) -> list[dict]:
    if not query.strip() or not 1 <= limit <= 100: raise ValueError("search requires a query and limit between 1 and 100")
    enforce_history_retention(base)
    db = load_config(base).workspace / "history_index.sqlite3"
    if not db.exists(): raise ValueError("history index is missing; run revagent history rebuild")
    con = sqlite3.connect(db)
    try: rows = con.execute("SELECT history_id,purpose,snippet(history_fts,2,'[',']',' ... ',12),bm25(history_fts) FROM history_fts WHERE history_fts MATCH ? ORDER BY bm25(history_fts),history_id LIMIT ?", (query, limit)).fetchall()
    except sqlite3.OperationalError as exc: raise ValueError(f"invalid history search query: {exc}") from exc
    finally: con.close()
    return [{"history_id": x[0], "purpose": x[1], "snippet": x[2], "rank": x[3], "use": "style_or_precedent_suggestion_only"} for x in rows]

def delete_history(base, history_id: str, confirmed=False) -> dict:
    if not confirmed: raise ValueError("history deletion requires explicit --confirm")
    ws = load_config(base).workspace; target, data = _registry(base); record = _find(data, history_id); preview = ws / str(record.get("preview_path", ""))
    if preview.is_file(): preview.unlink()
    record.update({"deletion_status": "deleted", "deleted_at": now_iso(), "indexed": False, "preview_path": "", "preview_sha256": ""}); write_json(target, data); rebuild_history_index(base); return record

def export_history(base, output: Path) -> Path:
    enforce_history_retention(base)
    ws = load_config(base).workspace; _, data = _registry(base)
    if output.exists(): raise ValueError("history export target already exists")
    output.mkdir(parents=True); records = []
    for record in data.get("records", []):
        preview = ws / str(record.get("preview_path", ""))
        if record.get("consent") == "approved" and record.get("deidentification_status") == "approved" and record.get("deletion_status", "active") == "active" and preview.is_file() and file_sha256(preview) == record.get("preview_sha256"):
            copy = output / f"{record['history_id']}.txt"; copy.write_text(preview.read_text(encoding="utf-8"), encoding="utf-8"); records.append({"history_id": record["history_id"], "purpose": record["purpose"], "retention_rule": record["retention_rule"], "sha256": file_sha256(copy)})
    write_json(output / "manifest.json", {"version": 1, "exported_at": now_iso(), "raw_content_included": False, "records": records}); return output
