"""Local, consent-gated revision-history registry."""
from __future__ import annotations
from pathlib import Path
from ._utils import file_sha256, load_config, now_iso, read_json, write_json

def import_history(base, path: Path, purpose: str) -> dict:
    if not path.is_file():
        raise ValueError("history source must be a file")
    config = load_config(base)
    registry = read_json(config.workspace / "history_registry.json", {"version": 1, "records": []})
    record = {"history_id": f"H-{len(registry['records']) + 1:03d}", "source_sha256": file_sha256(path), "imported_at": now_iso(), "purpose": purpose, "consent": "pending", "indexed": False, "raw_content_stored": False}
    registry["records"].append(record)
    write_json(config.workspace / "history_registry.json", registry)
    return record

def approve_history(base, history_id: str) -> dict:
    config = load_config(base)
    registry = read_json(config.workspace / "history_registry.json", {"records": []})
    for record in registry.get("records", []):
        if record.get("history_id") == history_id:
            if record.get("consent") != "pending":
                raise ValueError("history record is not awaiting consent")
            record["consent"] = "approved"
            record["approved_at"] = now_iso()
            write_json(config.workspace / "history_registry.json", registry)
            return record
    raise ValueError("unknown history record")
