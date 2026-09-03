"""Human-reviewed semantic dependencies and hash-bound experiment evidence."""
from __future__ import annotations

import re

from ._utils import file_sha256, load_config, now_iso, read_json, write_json
from .paper_ingestion import load_paper_manifest, paper_manifest_is_stale

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def _registry(base):
    path = load_config(base).workspace / "paper_evidence_reviews.json"
    return path, read_json(path, {"version": 1, "dependency_reviews": [], "experiment_bindings": []})


def _current_claim(base, claim_id: str) -> tuple[dict, dict]:
    manifest = load_paper_manifest(base)
    if paper_manifest_is_stale(base, manifest): raise ValueError("paper manifest is missing or stale; run revagent paper-ingest")
    claim = next((item for item in manifest.get("claims", []) if item.get("claim_id") == claim_id), None)
    if not claim: raise ValueError("unknown claim_id")
    return manifest, claim


def review_claim_dependency(base, claim_id: str, dependency_id: str, reviewer_id: str, decision: str, note: str) -> dict:
    if not _ID.fullmatch(reviewer_id): raise ValueError("reviewer_id must be a non-identifying lowercase pseudonym")
    if decision not in {"supported", "unsupported", "uncertain"}: raise ValueError("invalid dependency review decision")
    if not note.strip(): raise ValueError("dependency review requires a substantive note")
    manifest, claim = _current_claim(base, claim_id)
    if dependency_id not in claim.get("claim_dependencies", []): raise ValueError("dependency_id is not a structural dependency of the claim")
    dependency = next(item for item in manifest["claims"] if item["claim_id"] == dependency_id)
    record = {"claim_id": claim_id, "claim_sha256": claim["content_sha256"], "dependency_id": dependency_id,
              "dependency_sha256": dependency["content_sha256"], "reviewer_id": reviewer_id, "decision": decision,
              "note": note.strip(), "reviewed_at": now_iso(), "scope": "human_semantic_dependency_assessment"}
    path, registry = _registry(base); registry["dependency_reviews"] = [item for item in registry["dependency_reviews"] if not (item.get("claim_id") == claim_id and item.get("dependency_id") == dependency_id)] + [record]
    write_json(path, registry); return record


def bind_experiment_evidence(base, claim_id: str, item_id: str, artifact_path: str, note: str) -> dict:
    if not note.strip(): raise ValueError("experiment binding requires a substantive note")
    _, claim = _current_claim(base, claim_id); config = load_config(base)
    manifests = read_json(config.workspace / "experiment_manifests.json", {})
    experiment = manifests.get(item_id) if isinstance(manifests, dict) else None
    if not isinstance(experiment, dict): raise ValueError("unknown experiment manifest item")
    artifact = next((item for item in experiment.get("artifacts", []) if item.get("path") == artifact_path), None)
    path = (config.tex_root / artifact_path).resolve()
    if not artifact or not path.is_file() or file_sha256(path) != artifact.get("sha256"): raise ValueError("experiment artifact is missing, unrecorded, or hash-mismatched")
    record = {"claim_id": claim_id, "claim_sha256": claim["content_sha256"], "item_id": item_id, "artifact_path": artifact_path,
              "artifact_sha256": artifact["sha256"], "note": note.strip(), "bound_at": now_iso(),
              "status": "recorded_evidence_not_validity_confirmation"}
    target, registry = _registry(base); registry["experiment_bindings"] = [item for item in registry["experiment_bindings"] if not (item.get("claim_id") == claim_id and item.get("item_id") == item_id and item.get("artifact_path") == artifact_path)] + [record]
    write_json(target, registry); return record


def current_paper_evidence(base, claims: list[dict]) -> tuple[list[dict], list[dict]]:
    config = load_config(base); _, registry = _registry(base); by_id = {item["claim_id"]: item for item in claims}
    reviews = [item for item in registry.get("dependency_reviews", []) if item.get("claim_id") in by_id and item.get("dependency_id") in by_id and item.get("claim_sha256") == by_id[item["claim_id"]].get("content_sha256") and item.get("dependency_sha256") == by_id[item["dependency_id"]].get("content_sha256")]
    bindings = []
    for item in registry.get("experiment_bindings", []):
        claim = by_id.get(item.get("claim_id")); artifact = (config.tex_root / str(item.get("artifact_path", ""))).resolve()
        if claim and item.get("claim_sha256") == claim.get("content_sha256") and artifact.is_file() and file_sha256(artifact) == item.get("artifact_sha256"): bindings.append(item)
    return reviews, bindings
