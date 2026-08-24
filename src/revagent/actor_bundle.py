"""Validation for traceable, non-conclusive actor evidence bundles."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .artifact_safety import reject_conclusions, require_closed_object


EVIDENCE_KINDS = {"source_snapshot", "derivation_candidate", "code_inspection", "experiment_manifest", "experiment_attempt", "result_artifact", "reproduction_log", "citation", "llm_draft"}
CLAIM_STATUSES = {"observed", "candidate", "unverified"}


def validate_actor_bundle(bundle: dict[str, Any], plan: dict[str, Any], base: Path) -> None:
    """Validate provenance and plan binding; this does not validate mathematical truth."""
    require_closed_object(bundle, {"version", "cycle_id", "item_id", "role", "actor_id", "input_fingerprint", "created_at", "plan_sha256", "collected_at", "evidence", "claims", "unresolved", "execution", "limitations", "prohibited_conclusions"}, "actor bundle")
    reject_conclusions(bundle, "actor bundle")
    if bundle.get("version") != 2:
        raise ValueError("actor bundle must use version 2")
    required = ("plan_sha256", "collected_at", "evidence", "claims", "unresolved", "execution", "limitations", "prohibited_conclusions")
    if not all(key in bundle for key in required) or not all(isinstance(bundle[key], list) for key in ("evidence", "claims", "unresolved", "execution", "limitations", "prohibited_conclusions")):
        raise ValueError("actor bundle lacks required evidence, claim, and limitation fields")
    evidence_requirements = {str(item.get("evidence_id")) for item in plan.get("evidence_requirements", []) if isinstance(item, dict)}
    plan_claims = {str(item.get("claim_id")) for item in plan.get("claim_inventory", []) if isinstance(item, dict)}
    evidence_ids: set[str] = set()
    for entry in bundle["evidence"]:
        require_closed_object(entry, {"evidence_id", "kind", "path", "sha256", "status", "non_evidentiary"}, "actor evidence")
        if not isinstance(entry, dict) or entry.get("evidence_id") not in evidence_requirements or entry.get("kind") not in EVIDENCE_KINDS:
            raise ValueError("actor evidence must reference a declared plan evidence_id and known kind")
        evidence_id = str(entry["evidence_id"])
        if evidence_id in evidence_ids:
            raise ValueError("actor evidence ids must be unique")
        evidence_ids.add(evidence_id)
        path = base / str(entry.get("path", ""))
        if not path.is_file() or base.resolve() not in path.resolve().parents:
            raise ValueError("actor evidence path must be an existing workspace file")
        if entry.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("actor evidence hash does not match the recorded artifact")
        if entry.get("kind") == "llm_draft" and entry.get("non_evidentiary") is not True:
            raise ValueError("LLM material must be explicitly non-evidentiary")
        if entry.get("kind") == "experiment_attempt" and entry.get("status") != "executed_not_interpreted":
            raise ValueError("experiment attempts may only be recorded as executed_not_interpreted")
    claim_ids: set[str] = set()
    for claim in bundle["claims"]:
        require_closed_object(claim, {"claim_id", "status", "evidence_ids"}, "actor claim")
        if not isinstance(claim, dict) or claim.get("claim_id") not in plan_claims or claim.get("status") not in CLAIM_STATUSES:
            raise ValueError("actor claims must reference a planned claim and remain non-conclusive")
        claim_id = str(claim["claim_id"])
        if claim_id in claim_ids or not isinstance(claim.get("evidence_ids"), list) or not set(claim["evidence_ids"]) <= evidence_ids:
            raise ValueError("actor claims require unique ids and recorded evidence references")
        claim_ids.add(claim_id)
