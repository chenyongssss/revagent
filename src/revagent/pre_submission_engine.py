"""Local role-scoped advisory reports for pre-submission review."""

from __future__ import annotations

from collections import Counter

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .paper_ingestion import build_paper_manifest, load_paper_manifest, paper_input_fingerprint
from .reviewer_packs import load_reviewer_pack


REVIEW_REPORT_VERSION = 1
ROLES = ("text-reviewer", "theory-reviewer", "experiment-reviewer")
ROLE_CATEGORIES = {
    "text-reviewer": {"bibliography_keys", "bibliography_unused", "figure_table_reference", "undefined_symbol"},
    "theory-reviewer": {"claim_evidence", "undefined_symbol"},
    "experiment-reviewer": {"pdf_binding", "attachments", "page_limit"},
}


def _issue(number: int, role: str, check: dict[str, object]) -> dict[str, object]:
    severity = str(check["severity"])
    return {
        "issue_id": f"{role.split('-')[0].upper()}-{number:03d}",
        "category": str(check["category"]),
        "severity": severity,
        "confidence": "deterministic-structural",
        "claim_evidence_references": list(check.get("locations", [])),
        "rationale": str(check["message"]),
        "requested_verification": "Author or domain expert verifies the relevant source/PDF observation.",
        "required_author_decision": severity in {"high", "critical"},
        "advisory": True,
    }


def _load_reports(base) -> dict:
    return read_json(load_config(base).workspace / "review_reports.json", {"version": REVIEW_REPORT_VERSION, "reports": {}})


def _render_reports(payload: dict) -> str:
    lines = ["# Role-scoped Pre-submission Reports", ""]
    reports = payload.get("reports", {})
    for role in ROLES:
        report = reports.get(role) if isinstance(reports, dict) else None
        lines.extend([f"## {role}", ""])
        if not isinstance(report, dict):
            lines.append("- Not run.")
        else:
            lines.extend(f"- `{item['issue_id']}` [{item['severity']}] {item['rationale']}" for item in report.get("issues", []))
            if not report.get("issues"):
                lines.append("- No role-scoped deterministic findings.")
        lines.append("")
    return "\n".join(lines)


def run_role_review(base, role: str, pack: str = "numerical-pde") -> dict:
    if role not in ROLES:
        raise ValueError(f"unknown review role {role!r}")
    manifest = build_paper_manifest(base)
    checks = [check for check in manifest.get("checks", []) if check.get("category") in ROLE_CATEGORIES[role]]
    report = {
        "version": REVIEW_REPORT_VERSION,
        "role": role,
        "generated_at": now_iso(),
        "paper_input_fingerprint": manifest["input_fingerprint"],
        "reviewer_pack": load_reviewer_pack(pack),
        "issues": [_issue(number, role, check) for number, check in enumerate(checks, 1)],
        "limitations": ["This is a role-scoped deterministic structural report, not an independent expert conclusion or editorial decision.", "No prior role conclusions were used to generate this report."],
    }
    payload = _load_reports(base)
    payload.setdefault("reports", {})[role] = report
    config = load_config(base)
    write_json(config.workspace / "review_reports.json", payload)
    write_text(config.workspace / "review_reports.md", _render_reports(payload))
    return report


def merge_role_reports(base) -> dict:
    payload = _load_reports(base)
    reports = payload.get("reports", {}) if isinstance(payload, dict) else {}
    current_fingerprint = paper_input_fingerprint(base)
    merged: dict[tuple[str, str], dict] = {}
    missing_roles = []
    stale_roles = []
    for role in ROLES:
        report = reports.get(role) if isinstance(reports, dict) else None
        if not isinstance(report, dict):
            missing_roles.append(role)
            continue
        if report.get("paper_input_fingerprint") != current_fingerprint:
            stale_roles.append(role)
        for issue in report.get("issues", []):
            key = (str(issue.get("severity")), str(issue.get("rationale")))
            merged.setdefault(key, {**issue, "roles": []})["roles"].append(role)
    result = {
        "version": REVIEW_REPORT_VERSION,
        "generated_at": now_iso(),
        "paper_input_fingerprint": current_fingerprint,
        "status": "incomplete" if missing_roles or stale_roles else "advisory_merged",
        "missing_roles": missing_roles,
        "stale_roles": stale_roles,
        "risk_matrix": dict(sorted(Counter(str(issue["severity"]) for issue in merged.values()).items())),
        "issues": list(merged.values()),
        "limitations": ["The merge deduplicates local deterministic observations; it is not a meta-review or journal decision."],
    }
    config = load_config(base)
    write_json(config.workspace / "review_meta_report.json", result)
    lines = ["# Merged Pre-submission Review", "", f"- Status: `{result['status']}`", f"- Missing roles: {', '.join(missing_roles) or 'none'}", f"- Stale roles: {', '.join(stale_roles) or 'none'}", "", "## Issues", ""]
    lines.extend(f"- [{item['severity']}] {item['rationale']} (roles: {', '.join(item['roles'])})" for item in result["issues"])
    write_text(config.workspace / "review_meta_report.md", "\n".join(lines) + "\n")
    return result


def run_review_round(base, mode: str = "standard", pack: str = "numerical-pde") -> dict:
    """Run bounded local role reports; follow-up work always remains author-gated."""
    if mode not in {"standard", "hard", "nightmare"}:
        raise ValueError("mode must be standard, hard, or nightmare")
    config = load_config(base)
    state = read_json(config.workspace / "review_engine.json", {"version": 1, "max_rounds": 2, "rounds": []})
    rounds = state.setdefault("rounds", [])
    if len(rounds) >= int(state.get("max_rounds", 2)):
        raise ValueError("maximum review rounds reached; author must explicitly revise the local review-engine policy")
    reports = [run_role_review(base, role, pack) for role in ROLES]
    merged = merge_role_reports(base)
    followups = read_json(config.workspace / "review_followups.json", {"version": 1, "tasks": []})
    tasks = followups.setdefault("tasks", [])
    for issue in merged["issues"]:
        if issue["severity"] not in {"high", "critical"}:
            continue
        task_id = f"VF-{len(tasks) + 1:03d}"
        tasks.append({"task_id": task_id, "issue_id": issue["issue_id"], "category": issue.get("category", ""), "status": "authorization_required", "requested_verification": issue["requested_verification"], "author_gate": "Explicit author authorization required before any follow-up work.", "round": len(rounds) + 1})
    rounds.append({"round": len(rounds) + 1, "mode": mode, "pack": pack, "generated_at": now_iso(), "paper_input_fingerprint": merged["paper_input_fingerprint"], "author_pause_required": True})
    write_json(config.workspace / "review_engine.json", state)
    write_json(config.workspace / "review_followups.json", followups)
    write_text(config.workspace / "review_followups.md", "# Verification Follow-ups\n\n" + "\n".join(f"- `{task['task_id']}` [{task['status']}] {task['requested_verification']}" for task in tasks) + "\n")
    outputs = {"version": 1, "generated_at": now_iso(), "editor_summary": {"risk_matrix": merged["risk_matrix"], "advisory": True}, "reviewer_report": merged["issues"], "author_action_list": tasks, "limitations": ["Outputs are model assistance and local structural observations, not an accept/reject recommendation."]}
    write_json(config.workspace / "review_outputs.json", outputs)
    write_text(config.workspace / "review_outputs.md", "# Advisory Pre-submission Outputs\n\n## Editor Summary\n\n" + "\n".join(f"- {key}: {value}" for key, value in outputs["editor_summary"]["risk_matrix"].items()) + "\n\n## Author Action List\n\n" + "\n".join(f"- `{task['task_id']}` {task['status']}: {task['requested_verification']}" for task in tasks) + "\n")
    return {"round": rounds[-1], "reports": reports, "merged": merged, "followups": tasks, "outputs": outputs}


def authorize_followup(base, task_id: str) -> dict:
    config = load_config(base)
    payload = read_json(config.workspace / "review_followups.json", {"version": 1, "tasks": []})
    for task in payload.get("tasks", []):
        if task.get("task_id") == task_id:
            if task.get("status") != "authorization_required":
                raise ValueError(f"follow-up {task_id} is not awaiting authorization")
            task["status"] = "authorized"
            task["authorized_at"] = now_iso()
            write_json(config.workspace / "review_followups.json", payload)
            return task
    raise ValueError(f"unknown follow-up {task_id}")
