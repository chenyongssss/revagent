"""Validation for conservative computational-mathematics revision specifications."""

from __future__ import annotations

from typing import Any

from .artifact_safety import reject_conclusions, require_closed_object


LANES = {"proof", "stability", "convergence", "discretization", "solver", "experiment", "rebuttal", "text", "mixed"}
RISKS = {"low", "medium", "high", "critical"}
POSTURES = {"accept", "clarify", "partially_accept", "respectfully_disagree", "defer"}
CLAIM_STATUSES = {"existing", "proposed", "unverified"}


def _items(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"revision specification {name} must be a list of objects")
    return value


def _closed_rows(rows: list[dict[str, Any]], allowed: set[str], label: str) -> None:
    for index, row in enumerate(rows):
        require_closed_object(row, allowed, f"{label}[{index}]")


def _ids(items: list[dict[str, Any]], key: str, name: str) -> set[str]:
    values = [str(item.get(key, "")).strip() for item in items]
    if not all(values) or len(values) != len(set(values)):
        raise ValueError(f"revision specification {name} requires unique non-empty {key} values")
    return set(values)


def _has_blocking_gate(gates: list[dict[str, Any]], gate: str) -> bool:
    return any(entry.get("gate") == gate and entry.get("blocking") is True for entry in gates)


def _required_object(spec: dict[str, Any], name: str, keys: set[str]) -> dict[str, Any]:
    value = spec.get(name)
    if not isinstance(value, dict) or not all(str(value.get(key, "")).strip() for key in keys):
        raise ValueError(f"revision specification {name} lacks required fields: {', '.join(sorted(keys))}")
    return value


def validate_revision_spec(spec: dict[str, Any]) -> None:
    """Validate a planning contract, never the truth of its mathematical content."""
    require_closed_object(spec, {"version", "cycle_id", "item_id", "role", "actor_id", "input_fingerprint", "created_at", "summary", "lane", "risk_level", "reviewer_request", "manuscript_scope", "taxonomy", "claim_inventory", "evidence_requirements", "acceptance_criteria", "dependencies", "blockers", "manual_gates", "uncertainties", "out_of_scope", "rebuttal_plan", "proof_spec", "stability_spec", "convergence_spec", "experiment_spec"}, "planner artifact")
    reject_conclusions(spec, "planner artifact")
    if spec.get("version") != 2:
        raise ValueError("planner artifact must use typed revision specification version 2")
    if spec.get("lane") not in LANES or spec.get("risk_level") not in RISKS:
        raise ValueError("revision specification has an invalid lane or risk_level")
    request = _required_object(spec, "reviewer_request", {"verbatim_locator", "quoted_request"})
    require_closed_object(request, {"verbatim_locator", "quoted_request", "normalized_requests"}, "reviewer_request")
    normalized = _items(request.get("normalized_requests"), "reviewer_request.normalized_requests")
    _closed_rows(normalized, {"request_id", "text"}, "normalized_requests")
    request_ids = _ids(normalized, "request_id", "normalized reviewer requests")
    scope = _items(spec.get("manuscript_scope"), "manuscript_scope")
    _closed_rows(scope, {"locator", "why"}, "manuscript_scope")
    if not scope or not all(str(item.get("locator", "")).strip() and str(item.get("why", "")).strip() for item in scope):
        raise ValueError("revision specification requires traceable manuscript_scope locators")
    taxonomy = _items(spec.get("taxonomy"), "taxonomy")
    _closed_rows(taxonomy, {"family", "topic"}, "taxonomy")
    if not taxonomy or not all(item.get("family") in LANES and str(item.get("topic", "")).strip() for item in taxonomy):
        raise ValueError("revision specification taxonomy requires known families and topics")
    claims = _items(spec.get("claim_inventory"), "claim_inventory")
    _closed_rows(claims, {"claim_id", "proposition", "status"}, "claim_inventory")
    claim_ids = _ids(claims, "claim_id", "claim inventory")
    if not all(item.get("status") in CLAIM_STATUSES and str(item.get("proposition", "")).strip() for item in claims):
        raise ValueError("claims must be propositions with an unverified, proposed, or existing status")
    evidence = _items(spec.get("evidence_requirements"), "evidence_requirements")
    _closed_rows(evidence, {"evidence_id"}, "evidence_requirements")
    evidence_ids = _ids(evidence, "evidence_id", "evidence requirements")
    criteria = _items(spec.get("acceptance_criteria"), "acceptance_criteria")
    _closed_rows(criteria, {"criterion_id", "observable", "required_evidence_ids"}, "acceptance_criteria")
    _ids(criteria, "criterion_id", "acceptance criteria")
    if not all(str(item.get("observable", "")).strip() and isinstance(item.get("required_evidence_ids"), list) and set(item["required_evidence_ids"]) <= evidence_ids for item in criteria):
        raise ValueError("acceptance criteria must be observable and reference declared evidence")
    gates = _items(spec.get("manual_gates"), "manual_gates")
    _closed_rows(gates, {"gate", "required_action", "blocking"}, "manual_gates")
    if not gates or not all(str(item.get("gate", "")).strip() and str(item.get("required_action", "")).strip() and isinstance(item.get("blocking"), bool) for item in gates):
        raise ValueError("manual_gates must state a gate, required action, and blocking flag")
    for name in ("blockers", "uncertainties", "out_of_scope", "dependencies"):
        rows = _items(spec.get(name), name)
        _closed_rows(rows, {"id", "detail"}, name)
    rebuttal = _required_object(spec, "rebuttal_plan", {"response_posture"})
    require_closed_object(rebuttal, {"response_posture", "response_commitments", "non_claims", "manuscript_response_consistency_checks"}, "rebuttal_plan")
    if rebuttal.get("response_posture") not in POSTURES or not all(isinstance(rebuttal.get(key), list) for key in ("response_commitments", "non_claims", "manuscript_response_consistency_checks")):
        raise ValueError("rebuttal_plan is incomplete")
    for commitment in rebuttal["response_commitments"]:
        require_closed_object(commitment, {"request_id", "manuscript_locator"}, "rebuttal commitment")
        if not isinstance(commitment, dict) or commitment.get("request_id") not in request_ids or not str(commitment.get("manuscript_locator", "")).strip():
            raise ValueError("each rebuttal commitment must map a known request to a manuscript locator")
    if rebuttal["response_posture"] == "respectfully_disagree" and not _has_blocking_gate(gates, "author_position_required"):
        raise ValueError("a respectful disagreement requires an author_position_required blocking gate")
    high_risk = spec["lane"] in {"proof", "stability", "convergence", "experiment"} or any(item.get("family") in {"proof", "stability", "convergence", "experiment"} for item in taxonomy)
    if high_risk and spec["risk_level"] not in {"high", "critical"}:
        raise ValueError("proof, stability, convergence, and experiment specifications are high risk")
    if high_risk and not any(item.get("blocking") is True for item in gates):
        raise ValueError("high-risk revision specifications require a blocking author gate")
    if spec["lane"] == "proof":
        _required_object(spec, "proof_spec", {"statement_locator", "target_conclusion"})
        if not _has_blocking_gate(gates, "author_proof_approval"):
            raise ValueError("proof specifications require author_proof_approval")
    if spec["lane"] == "stability":
        _required_object(spec, "stability_spec", {"norm_or_energy", "parameter_regime"})
        if not _has_blocking_gate(gates, "author_stability_check"):
            raise ValueError("stability specifications require author_stability_check")
    if spec["lane"] == "convergence":
        _required_object(spec, "convergence_spec", {"quantity_of_interest", "norm", "claimed_rate", "verification_route"})
        if not _has_blocking_gate(gates, "author_convergence_check"):
            raise ValueError("convergence specifications require author_convergence_check")
    if spec["lane"] == "experiment":
        experiment = _required_object(spec, "experiment_spec", {"research_question", "resource_class"})
        if not all(isinstance(experiment.get(key), list) and experiment[key] for key in ("comparators", "metrics", "expected_artifacts")):
            raise ValueError("experiment specifications require comparators, metrics, and expected artifacts")
        if not (_has_blocking_gate(gates, "experiment_authorization") and _has_blocking_gate(gates, "author_result_confirmation")):
            raise ValueError("experiment specifications require authorization and author result confirmation gates")
