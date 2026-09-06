"""Public-source, agent-adjudicated journal rulepack verification."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ._utils import now_iso, read_json, write_json
from .profiles import load_profile

STATUS = "public_source_agent_adjudicated_not_expert_calibrated"
_ACTOR = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _path(base: Path, journal: str) -> Path:
    return base / ".revagent" / "rulepack_verification" / f"{journal.lower()}.json"


def initialize_rulepack_source(base: Path, journal: str, source_url: str, content: str, retrieved_at: str) -> dict:
    """Freeze an operator-supplied official-source snapshot; this performs no network access."""
    profile = load_profile(journal, base)
    if not source_url.startswith("https://") or source_url != profile.get("source_url"):
        raise ValueError("source_url must be HTTPS and match profile.yaml")
    if not content.strip() or not retrieved_at.strip():
        raise ValueError("source content and retrieval time are required")
    payload = {
        "version": 1, "journal": journal.lower(), "verification_tier": "public_source_agent_adjudicated",
        "calibration": "not_expert_calibrated", "source": {"url": source_url, "retrieved_at": retrieved_at,
        "content": content, "content_sha256": hashlib.sha256(content.encode()).hexdigest()},
        "rulepack_sha256": _hash((profile.get("rulepack") or {}).get("components", {})), "annotations": [],
        "adjudication": None, "status": "awaiting_independent_annotations",
        "limitations": ["Public-source agent coding is not human or domain-expert confirmation.",
                        "This record does not establish compliance with current journal policy."],
    }
    write_json(_path(base, journal), payload)
    return payload


def annotate_rulepack_source(base: Path, journal: str, actor: str, model: str, run_id: str, findings: list[dict]) -> dict:
    path = _path(base, journal); payload = read_json(path, {})
    if not payload: raise ValueError("initialize the rulepack source first")
    if not _ACTOR.fullmatch(actor) or not model.strip() or not run_id.strip(): raise ValueError("actor, model, and run_id are required")
    if actor in {row.get("actor") for row in payload["annotations"]}: raise ValueError("actor already annotated this source")
    source = payload["source"]["content"]
    clean = []
    for row in findings:
        field, value, excerpt = str(row.get("field", "")).strip(), row.get("value"), str(row.get("evidence_excerpt", "")).strip()
        if not field or not excerpt or excerpt not in source: raise ValueError("each finding requires a field and verbatim source evidence")
        clean.append({"field": field, "value": value, "evidence_excerpt": excerpt})
    payload["annotations"].append({"actor": actor, "model": model, "run_id": run_id, "created_at": now_iso(), "findings": clean})
    payload["status"] = "awaiting_adjudication" if len(payload["annotations"]) >= 2 else "awaiting_independent_annotations"
    write_json(path, payload); return payload


def adjudicate_rulepack_source(base: Path, journal: str, actor: str, model: str, run_id: str, findings: list[dict]) -> dict:
    path = _path(base, journal); payload = read_json(path, {})
    annotators = {row.get("actor") for row in payload.get("annotations", [])}
    if len(annotators) < 2: raise ValueError("two independent annotations are required")
    if actor in annotators or not _ACTOR.fullmatch(actor): raise ValueError("adjudicator must be a distinct valid actor")
    source = payload["source"]["content"]; clean = []
    for row in findings:
        field, excerpt = str(row.get("field", "")).strip(), str(row.get("evidence_excerpt", "")).strip()
        if not field or not excerpt or excerpt not in source: raise ValueError("adjudicated findings require verbatim source evidence")
        clean.append({"field": field, "value": row.get("value"), "evidence_excerpt": excerpt,
                      "disposition": str(row.get("disposition", "resolved"))})
    profile = load_profile(journal, base)
    current_hash = _hash((profile.get("rulepack") or {}).get("components", {}))
    payload["adjudication"] = {"actor": actor, "model": model, "run_id": run_id, "created_at": now_iso(), "findings": clean}
    payload["status"] = STATUS if current_hash == payload["rulepack_sha256"] and clean else "stale_or_incomplete"
    write_json(path, payload); return payload


def verify_rulepack_silver(base: Path, journal: str) -> dict:
    payload = read_json(_path(base, journal), {})
    profile = load_profile(journal, base)
    current_hash = _hash((profile.get("rulepack") or {}).get("components", {}))
    issues = []
    if payload.get("status") != STATUS: issues.append("public-source adjudication is incomplete")
    if payload.get("rulepack_sha256") != current_hash: issues.append("rulepack changed after source verification")
    if len({row.get("actor") for row in payload.get("annotations", [])}) < 2: issues.append("two independent annotators are required")
    return {"version": 1, "journal": journal.lower(), "ok": not issues, "status": STATUS if not issues else "incomplete",
            "verification_tier": "public_source_agent_adjudicated", "calibration": "not_expert_calibrated",
            "human_confirmed": profile.get("human_confirmed") is True, "issues": issues,
            "note": "Silver verification never grants or substitutes for human confirmation."}
