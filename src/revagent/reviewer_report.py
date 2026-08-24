"""Independent, non-conclusive review of frozen planner and actor artifacts."""

from __future__ import annotations

from typing import Any

from .artifact_safety import reject_conclusions, require_closed_object


VERDICTS = {"pass", "return", "blocked", "escalate"}


def _assessment_ids(rows: object, key: str, label: str) -> set[str]:
    if not isinstance(rows, list) or not all(isinstance(row, dict) and str(row.get(key, "")).strip() for row in rows):
        raise ValueError(f"reviewer report {label} must contain identified assessments")
    values = [str(row[key]) for row in rows]
    if len(values) != len(set(values)):
        raise ValueError(f"reviewer report {label} contains duplicate assessments")
    return set(values)


def validate_reviewer_report(report: dict[str, Any], plan: dict[str, Any], actor: dict[str, Any]) -> None:
    """Validate coverage and separation of review, not correctness of scientific claims."""
    require_closed_object(report, {"version", "cycle_id", "item_id", "role", "actor_id", "input_fingerprint", "created_at", "plan_sha256", "actor_sha256", "review_session_id", "review_session_sha256", "verdict", "claim_assessments", "evidence_assessments", "criterion_assessments", "findings", "required_corrections", "uncertainty"}, "reviewer report")
    reject_conclusions(report, "reviewer report")
    if report.get("version") != 2 or report.get("verdict") not in VERDICTS:
        raise ValueError("reviewer report must use version 2 with a known verdict")
    required = ("claim_assessments", "evidence_assessments", "criterion_assessments", "findings", "required_corrections", "uncertainty")
    if not str(report.get("review_session_id", "")).strip() or not str(report.get("review_session_sha256", "")).strip() or not all(isinstance(report.get(key), list) for key in required):
        raise ValueError("reviewer report lacks required assessment lists")
    plan_claims = {str(row.get("claim_id")) for row in plan.get("claim_inventory", []) if isinstance(row, dict)}
    plan_criteria = {str(row.get("criterion_id")) for row in plan.get("acceptance_criteria", []) if isinstance(row, dict)}
    actor_evidence = {str(row.get("evidence_id")) for row in actor.get("evidence", []) if isinstance(row, dict)}
    if _assessment_ids(report["claim_assessments"], "claim_id", "claim") != plan_claims:
        raise ValueError("reviewer must assess every planned claim exactly once")
    if _assessment_ids(report["evidence_assessments"], "evidence_id", "evidence") != actor_evidence:
        raise ValueError("reviewer must assess every actor evidence record exactly once")
    if _assessment_ids(report["criterion_assessments"], "criterion_id", "criterion") != plan_criteria:
        raise ValueError("reviewer must assess every acceptance criterion exactly once")
    if not all(row.get("status") in {"evidence_assessed", "insufficient", "not_assessed"} for row in report["claim_assessments"]):
        raise ValueError("claim assessments must remain evidence-focused and non-conclusive")
    if not all(row.get("status") in {"verified_reference", "insufficient", "not_assessed"} for row in report["evidence_assessments"]):
        raise ValueError("evidence assessments have an invalid status")
    if not all(row.get("status") in {"satisfied", "unsatisfied", "not_assessed"} for row in report["criterion_assessments"]):
        raise ValueError("criterion assessments have an invalid status")
    high_risk = plan.get("lane") in {"proof", "stability", "convergence", "experiment"}
    if report["verdict"] == "pass":
        if high_risk or report["required_corrections"] or report["uncertainty"]:
            raise ValueError("high-risk plans or unresolved review findings cannot receive pass")
        if any(row["status"] != "satisfied" for row in report["criterion_assessments"]):
            raise ValueError("pass requires every acceptance criterion to be satisfied")
