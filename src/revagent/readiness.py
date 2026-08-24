"""Revision readiness and submit-pack dry-run reports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ._models import Config
from ._utils import first_sentence, load_config, load_items, now_iso, read_json, read_text, write_json, write_text
from .candidates import load_candidates
from .experiments import load_experiment_manifests, load_experiment_run_attempts
from .planning import load_item_plans
from .proofs import load_proof_workflows
from .provenance import provenance_missing_or_stale
from .review_analysis import load_review_analyses

READINESS_SCHEMA_VERSION = 2
READINESS_STATUSES = {
    "ready",
    "blocked_manual",
    "needs_evidence",
    "needs_candidate_review",
    "needs_apply",
    "needs_response_update",
    "needs_validation",
}
READINESS_SOURCE_FILES = [
    "review_items.json",
    "item_plans.json",
    "review_analyses.json",
    "candidate_edits.json",
    "proof_workflows.json",
    "experiment_manifests.json",
    "experiment_run_attempts.jsonl",
    "experiment_runs.jsonl",
    "apply_log.jsonl",
    "response_letter.md",
    "manuscript.patch",
    "revision_provenance.json",
]


def readiness_source_fingerprint(config: Config) -> str:
    digest = hashlib.sha256()
    for name in READINESS_SOURCE_FILES:
        path = config.workspace / name
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
        digest.update(b"\0")
    from .project_runtime import author_decision_console

    cycles = author_decision_console(config.workspace.parent)
    digest.update(json.dumps(cycles.get("cycles", []), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    digest.update(json.dumps(cycles.get("integrity_issues", []), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def readiness_path(config: Config) -> Path:
    return config.workspace / "revision_readiness.json"


def readiness_missing_or_stale(config: Config) -> bool:
    json_path = readiness_path(config)
    md_path = config.workspace / "revision_readiness.md"
    if not json_path.exists() or not md_path.exists():
        return True
    try:
        readiness = read_json(json_path, {})
    except Exception:
        return True
    return readiness.get("source_fingerprint") != readiness_source_fingerprint(config)


def response_present(config: Config, item: dict) -> bool:
    if str(item.get("response_draft", "")).strip():
        return True
    path = config.workspace / "response_letter.md"
    if not path.exists():
        return False
    text = read_text(path)
    return f"## {item.get('id', '')}" in text


def candidate_status_for(item_candidates: list[dict]) -> tuple[str, list[str], list[str]]:
    if not item_candidates:
        return "missing", ["candidate edit"], []
    statuses = {str(candidate.get("status", "")) for candidate in item_candidates}
    manual = []
    missing = []
    if any(candidate.get("requires_author_text") and candidate.get("status") in {"proposed", "blocked"} for candidate in item_candidates):
        missing.append("author text for candidate edit")
    if "approved" in statuses:
        return "approved_unapplied", missing, manual
    if "applied" in statuses:
        return "applied", missing, manual
    if statuses & {"proposed", "edited", "blocked"}:
        return "needs_review", missing, manual
    if statuses == {"rejected"}:
        return "rejected", missing + ["replacement candidate edit"], manual
    return ",".join(sorted(statuses)) or "unknown", [], manual


def proof_status_for(item: dict, workflow: dict | None) -> tuple[str, list[str], list[str]]:
    if item.get("kind") != "proof":
        return "not_applicable", [], []
    if not workflow:
        return "missing_workflow", ["proof workflow"], []
    missing = []
    if not workflow.get("statement_snapshot"):
        missing.append("proof statement snapshot")
    if not workflow.get("proof_snapshot"):
        missing.append("proof snapshot")
    open_obligations = [ob for ob in workflow.get("proof_obligations", []) if ob.get("status") != "closed"]
    manual = []
    if workflow.get("approval_status", "required") != "approved" or open_obligations:
        manual.append("author proof approval")
    status = "approved" if not manual and not missing else "blocked"
    return status, missing, manual


def experiment_status_for(item: dict, manifest: dict | None, attempts: list[dict]) -> tuple[str, list[str], list[str]]:
    if item.get("kind") != "experiment":
        return "not_applicable", [], []
    lane = item.get("experiment_lane") or {}
    if not manifest:
        return "missing_manifest", ["experiment manifest"], []
    missing = []
    if not manifest.get("command_template"):
        missing.append("experiment command")
    if not manifest.get("expected_artifacts"):
        missing.append("expected artifacts")
    has_attempt = any(attempt.get("item_id") == item.get("id") and attempt.get("status") != "invalid" for attempt in attempts)
    if manifest.get("command_template") and not has_attempt:
        missing.append("experiment run attempt")
    if lane.get("result_status") != "recorded" and not manifest.get("artifacts"):
        missing.append("recorded experiment result")
    if manifest.get("artifacts") and not manifest.get("backfill_targets"):
        missing.append("experiment result backfill")
    status = "recorded" if not missing else "incomplete"
    return status, missing, []


def classify_readiness(
    *,
    missing_inputs: list[str],
    manual_actions: list[str],
    candidate_status: str,
    response_status: str,
    validation_status: str,
) -> str:
    if manual_actions:
        return "blocked_manual"
    evidence_missing = [
        entry
        for entry in missing_inputs
        if entry not in {"candidate edit", "replacement candidate edit", "author text for candidate edit", "response update", "validation refresh"}
    ]
    if evidence_missing:
        return "needs_evidence"
    if candidate_status == "approved_unapplied":
        return "needs_apply"
    if candidate_status in {"missing", "needs_review", "rejected"}:
        return "needs_candidate_review"
    if response_status != "present":
        return "needs_response_update"
    if validation_status != "current":
        return "needs_validation"
    return "ready"


def build_item_readiness(
    config: Config,
    item: dict,
    *,
    item_plans: dict,
    review_analyses: dict,
    candidates_by_item: dict[str, list[dict]],
    proof_workflows: dict[str, dict],
    experiment_manifests: dict[str, dict],
    experiment_attempts: list[dict],
    revision_cycles: list[dict] | None = None,
) -> dict[str, object]:
    item_id = str(item.get("id", ""))
    missing_inputs: list[str] = []
    manual_actions: list[str] = []
    if item_id not in review_analyses:
        missing_inputs.append("review analysis")
    if item_id not in item_plans and item.get("planning_status", "triaged") == "triaged":
        missing_inputs.append("item plan")

    candidate_status, candidate_missing, candidate_manual = candidate_status_for(candidates_by_item.get(item_id, []))
    missing_inputs.extend(candidate_missing)
    manual_actions.extend(candidate_manual)

    proof_status, proof_missing, proof_manual = proof_status_for(item, proof_workflows.get(item_id))
    missing_inputs.extend(proof_missing)
    manual_actions.extend(proof_manual)

    experiment_status, experiment_missing, experiment_manual = experiment_status_for(
        item,
        experiment_manifests.get(item_id),
        experiment_attempts,
    )
    missing_inputs.extend(experiment_missing)
    manual_actions.extend(experiment_manual)

    response_status = "present" if response_present(config, item) else "missing"
    if response_status != "present":
        missing_inputs.append("response update")

    validation_status = "stale" if provenance_missing_or_stale(config) and candidate_status == "applied" else "current"
    if validation_status != "current":
        missing_inputs.append("validation refresh")

    cycle_records = revision_cycles or []
    for cycle in cycle_records:
        state = str(cycle.get("status", ""))
        cycle_id = str(cycle.get("cycle_id", ""))
        if state == "awaiting_author_gate":
            manual_actions.append(f"revision cycle {cycle_id} author decision")
        elif state in {"draft", "planned", "acted", "returned"}:
            missing_inputs.append(f"revision cycle {cycle_id} {state}")
        elif state == "blocked":
            reason = str(cycle.get("invalidation_reason", "")).strip()
            missing_inputs.append(f"revision cycle {cycle_id} blocked{': ' + reason if reason else ''}")
        if any(isinstance(decision, dict) and decision.get("action") == "waive" for decision in cycle.get("author_decisions", [])):
            missing_inputs.append(f"revision cycle {cycle_id} waiver disclosure")

    readiness_status = classify_readiness(
        missing_inputs=missing_inputs,
        manual_actions=manual_actions,
        candidate_status=candidate_status,
        response_status=response_status,
        validation_status=validation_status,
    )
    return {
        "item_id": item_id,
        "kind": item.get("kind", ""),
        "risk": item.get("risk", ""),
        "comment_summary": first_sentence(str(item.get("comment", ""))),
        "readiness_status": readiness_status,
        "missing_inputs": sorted(set(missing_inputs)),
        "manual_actions": sorted(set(manual_actions)),
        "evidence_status": "complete" if not [m for m in missing_inputs if m not in {"candidate edit", "replacement candidate edit", "response update", "validation refresh"}] else "incomplete",
        "candidate_status": candidate_status,
        "proof_status": proof_status,
        "experiment_status": experiment_status,
        "response_status": response_status,
        "validation_status": validation_status,
        "revision_cycles": cycle_records,
    }


def build_revision_readiness(base: Path) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item_plans = load_item_plans(config)
    review_analyses = load_review_analyses(config)
    candidates = load_candidates(config)
    proof_workflows = load_proof_workflows(config)
    experiment_manifests = load_experiment_manifests(config)
    experiment_attempts = load_experiment_run_attempts(config)
    from .project_runtime import author_decision_console

    cycle_console = author_decision_console(base)
    cycles_by_item: dict[str, list[dict]] = {}
    for cycle in cycle_console.get("cycles", []):
        if isinstance(cycle, dict):
            cycles_by_item.setdefault(str(cycle.get("item_id", "")), []).append(cycle)
    candidates_by_item: dict[str, list[dict]] = {}
    for candidate in candidates:
        candidates_by_item.setdefault(str(candidate.get("item_id", "")), []).append(candidate)
    item_records = [
        build_item_readiness(
            config,
            item,
            item_plans=item_plans,
            review_analyses=review_analyses,
            candidates_by_item=candidates_by_item,
            proof_workflows=proof_workflows,
            experiment_manifests=experiment_manifests,
            experiment_attempts=experiment_attempts,
            revision_cycles=cycles_by_item.get(str(item.get("id", "")), []),
        )
        for item in items
    ]
    cycle_item_ids = {str(cycle.get("cycle_id", "")): str(cycle.get("item_id", "")) for cycle in cycle_console.get("cycles", []) if isinstance(cycle, dict)}
    for issue in cycle_console.get("integrity_issues", []):
        if isinstance(issue, str):
            for record in item_records:
                cycle_id = next((identifier for identifier in cycle_item_ids if f"revision cycle {identifier} " in issue), "")
                if cycle_id and cycle_item_ids[cycle_id] != record["item_id"]:
                    continue
                record["missing_inputs"].append(f"cycle integrity: {issue}")
                record["readiness_status"] = classify_readiness(record["missing_inputs"], record["manual_actions"], record["stale_inputs"])
    summary_counts = {status: sum(1 for item in item_records if item.get("readiness_status") == status) for status in sorted(READINESS_STATUSES)}
    blockers = [
        {
            "item_id": item["item_id"],
            "readiness_status": item["readiness_status"],
            "missing_inputs": item["missing_inputs"],
            "manual_actions": item["manual_actions"],
        }
        for item in item_records
        if item.get("readiness_status") != "ready"
    ]
    submit_pack_missing = submit_pack_missing_from_readiness(config, item_records)
    overall_status = "ready" if item_records and not blockers and not submit_pack_missing else "not_ready"
    if not item_records:
        overall_status = "empty"
    return {
        "generated_at": now_iso(),
        "schema_version": READINESS_SCHEMA_VERSION,
        "source_fingerprint": readiness_source_fingerprint(config),
        "overall_status": overall_status,
        "summary_counts": summary_counts,
        "items": item_records,
        "blockers": blockers,
        "submit_pack_missing": submit_pack_missing,
    }


def submit_pack_missing_from_readiness(config: Config, items: list[dict[str, object]]) -> list[str]:
    missing = []
    if not (config.workspace / "response_letter.md").exists():
        missing.append("response_letter.md")
    if not (config.tex_root / config.main_tex).exists():
        missing.append(f"patched TeX source {config.main_tex}")
    if any(item.get("response_status") != "present" for item in items):
        missing.append("response updates for all review items")
    if any(item.get("candidate_status") == "approved_unapplied" for item in items):
        missing.append("approved candidates applied to TeX")
    if any(item.get("manual_actions") for item in items):
        missing.append("manual gates resolved")
    if any(item.get("readiness_status") != "ready" for item in items):
        missing.append("remaining readiness blockers resolved")
    if any(any(cycle.get("status") != "author_approved" for cycle in item.get("revision_cycles", [])) for item in items):
        missing.append("revision cycles resolved")
    from .project_runtime import cycle_integrity_issues
    if cycle_integrity_issues(config.workspace.parent):
        missing.append("revision cycle integrity restored")
    return sorted(set(missing))


def render_revision_readiness(readiness: dict[str, object], item_id: str | None = None) -> str:
    items = list(readiness.get("items", []))
    if item_id:
        items = [item for item in items if item.get("item_id") == item_id]
        if not items:
            raise ValueError(f"unknown readiness item {item_id}")
    blockers = [item for item in items if item.get("readiness_status") != "ready"]
    ready = [item for item in items if item.get("readiness_status") == "ready"]
    lines = [
        "# Revision Readiness",
        "",
        f"- Generated at: {readiness.get('generated_at', '')}",
        f"- Overall: {readiness.get('overall_status', '')}",
        f"- Counts: {', '.join(f'{key}={value}' for key, value in sorted((readiness.get('summary_counts') or {}).items())) or 'none'}",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        for item in blockers:
            lines.append(f"### {item.get('item_id', '')} - {item.get('readiness_status', '')}")
            lines.append("")
            lines.append(f"- Comment: {item.get('comment_summary', '')}")
            lines.append(f"- Missing inputs: {', '.join(item.get('missing_inputs', [])) or 'none'}")
            lines.append(f"- Manual actions: {', '.join(item.get('manual_actions', [])) or 'none'}")
            lines.append(f"- Evidence: {item.get('evidence_status', '')}")
            lines.append(f"- Candidate: {item.get('candidate_status', '')}")
            lines.append(f"- Proof: {item.get('proof_status', '')}")
            lines.append(f"- Experiment: {item.get('experiment_status', '')}")
            lines.append(f"- Response: {item.get('response_status', '')}")
            lines.append("")
    else:
        lines.append("- None.")
        lines.append("")
    lines.append("## Ready Items")
    lines.append("")
    if ready:
        for item in ready:
            lines.append(f"- `{item.get('item_id', '')}` {item.get('kind', '')}: {item.get('comment_summary', '')}")
    else:
        lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


def write_revision_readiness(base: Path) -> dict[str, object]:
    config = load_config(base)
    readiness = build_revision_readiness(base)
    write_json(config.workspace / "revision_readiness.json", readiness)
    write_text(config.workspace / "revision_readiness.md", render_revision_readiness(readiness))
    return readiness


def readiness_for_item(base: Path, item_id: str) -> dict[str, object]:
    readiness = write_revision_readiness(base)
    if not any(item.get("item_id") == item_id for item in readiness.get("items", [])):
        raise ValueError(f"unknown readiness item {item_id}")
    return readiness


def build_submit_pack_dry_run(base: Path) -> dict[str, object]:
    readiness = write_revision_readiness(base)
    from .validation import validate_workspace
    from .response_trace import write_response_trace

    validation = validate_workspace(base)
    response_trace = write_response_trace(base)
    missing = list(readiness.get("submit_pack_missing", []))
    trace_missing: list[str] = []
    for record in response_trace.get("records", []):
        item_id = str(record.get("item_id", "unknown"))
        for label, key in (("response assertion", "response_assertion"), ("manuscript diff", "manuscript_diff"), ("evidence", "evidence"), ("final PDF", "final_pdf")):
            state = (record.get(key) or {}).get("status")
            if state in {"missing", "not_assessed", ""}:
                trace_missing.append(f"{item_id} {label} trace")
    if trace_missing:
        missing.append("response trace completeness")
    if validation.get("warnings"):
        missing.append("validation warnings reviewed")
    if validation.get("issues"):
        missing.append("validation issues resolved")
    return {
        "generated_at": now_iso(),
        "ready": readiness.get("overall_status") == "ready" and not validation.get("issues") and not validation.get("warnings"),
        "readiness": readiness,
        "validation_warnings": validation.get("warnings", []),
        "validation_issues": validation.get("issues", []),
        "response_trace_missing": trace_missing,
        "missing": sorted(set(missing)),
    }


def render_submit_pack_dry_run(report: dict[str, object]) -> str:
    readiness = report.get("readiness", {})
    lines = [
        "# Submit Pack Dry Run",
        "",
        f"- Generated at: {report.get('generated_at', '')}",
        f"- Ready: {str(report.get('ready', False)).lower()}",
        f"- Readiness: {readiness.get('overall_status', '')}",
        "",
        "## Missing",
        "",
    ]
    missing = report.get("missing", [])
    lines.extend(f"- {entry}" for entry in missing) if missing else lines.append("- None.")
    lines.extend(["", "## Validation Warnings", ""])
    warnings = report.get("validation_warnings", [])
    lines.extend(f"- {warning}" for warning in warnings[:30]) if warnings else lines.append("- None.")
    lines.extend(["", "## Validation Issues", ""])
    issues = report.get("validation_issues", [])
    lines.extend(f"- {issue}" for issue in issues) if issues else lines.append("- None.")
    lines.extend(["", "## Response Trace Gaps", ""])
    trace_gaps = report.get("response_trace_missing", [])
    lines.extend(f"- {gap}" for gap in trace_gaps) if trace_gaps else lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "build_revision_readiness",
    "build_submit_pack_dry_run",
    "readiness_missing_or_stale",
    "render_revision_readiness",
    "render_submit_pack_dry_run",
    "write_revision_readiness",
]
