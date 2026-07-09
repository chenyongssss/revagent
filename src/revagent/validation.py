"""Workspace validation and local-environment doctor checks."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from ._models import CURRENT_SCHEMA_VERSION, EXPERIMENT_CONTRACT_STATUSES, PLANNING_STATUSES, SCHEMA_FILES
from ._utils import find_item, load_config, load_items, parse_simple_yaml, read_json, read_text, workspace_path, write_text
from .candidates import load_candidates, llm_candidate_gate_reason, verify_candidate_anchor, verify_candidate_operation
from .experiments import file_sha256, load_experiment_manifests, load_experiment_run_attempts
from .latex import latex_index
from .profiles import available_profiles
from .provenance import build_revision_provenance, provenance_missing_or_stale
from .proofs import load_proof_workflows
from .review_analysis import load_review_analyses
from .workspace import migrate_workspace

def read_jsonl_like(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records = []
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def validate_workspace(base: Path, compile_check: bool = False) -> dict[str, object]:
    config = load_config(base)
    issues: list[str] = []
    warnings: list[str] = []
    for name in SCHEMA_FILES:
        if not (config.workspace / name).exists():
            issues.append(f"missing workspace file: {name}")
    for name in ("review_items.json", "latex_index.json", "journal_profile.json", "candidate_edits.json", "proof_workflows.json", "experiment_manifests.json", "agent_state.json", "agent_policy.json", "agent_decisions.json", "agent_eval_report.json", "llm_drafts.json", "review_analyses.json", "revision_provenance.json", "revision_memory.json", "revision_readiness.json"):
        try:
            read_json(config.workspace / name, {})
        except json.JSONDecodeError as exc:
            issues.append(f"invalid JSON in {name}: {exc}")
    agent_runs = config.workspace / "agent_runs.jsonl"
    if agent_runs.exists():
        for index, line in enumerate(read_text(agent_runs).splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                warnings.append(f"invalid JSONL in agent_runs.jsonl line {index}: {exc}")
                continue
            if record.get("status") in {"done", "failed", "skipped"} and not record.get("fingerprint"):
                warnings.append(f"agent_runs.jsonl line {index} has no task fingerprint")
            if record.get("status") in {"done", "failed", "skipped"} and not record.get("task_identity"):
                warnings.append(f"agent_runs.jsonl line {index} has no task identity")
            if record.get("status") in {"done", "failed", "skipped"} and "dependencies" not in record:
                warnings.append(f"agent_runs.jsonl line {index} has no dependency metadata")
    external_runs = config.workspace / "external_agent_runs.jsonl"
    if external_runs.exists():
        valid_external_statuses = {"dry_run", "queued", "running", "done", "failed", "canceled", "invalid"}
        for index, line in enumerate(read_text(external_runs).splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                warnings.append(f"invalid JSONL in external_agent_runs.jsonl line {index}: {exc}")
                continue
            if not record.get("backend"):
                warnings.append(f"external_agent_runs.jsonl line {index} has no backend")
            if not record.get("prompt_path"):
                warnings.append(f"external_agent_runs.jsonl line {index} has no prompt_path")
            elif not Path(str(record.get("prompt_path"))).exists():
                warnings.append(f"external_agent_runs.jsonl line {index} prompt_path is missing")
            if record.get("status") not in valid_external_statuses:
                warnings.append(f"external_agent_runs.jsonl line {index} has invalid status {record.get('status')}")
            if record.get("status") == "queued":
                launch = str(record.get("launch_script", ""))
                if not launch:
                    warnings.append(f"external_agent_runs.jsonl line {index} queued run has no launch_script")
                elif not Path(launch).exists():
                    warnings.append(f"external_agent_runs.jsonl line {index} launch_script is missing")
            if record.get("status") == "done":
                for key in ("stdout_path", "stderr_path"):
                    value = str(record.get(key, ""))
                    if value and not Path(value).exists():
                        warnings.append(f"external_agent_runs.jsonl line {index} {key} is missing")
            if record.get("operator_note") and not record.get("marked_at"):
                warnings.append(f"external_agent_runs.jsonl line {index} has operator_note without marked_at")
    experiment_attempts_path = config.workspace / "experiment_run_attempts.jsonl"
    if experiment_attempts_path.exists():
        for index, line in enumerate(read_text(experiment_attempts_path).splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                warnings.append(f"invalid JSONL in experiment_run_attempts.jsonl line {index}: {exc}")
                continue
            try:
                exit_code = int(record.get("exit_code", 0) or 0)
            except (TypeError, ValueError):
                exit_code = -1
            if record.get("status") == "failed" or exit_code != 0:
                warnings.append(f"experiment_run_attempts.jsonl line {index} failed with exit_code {record.get('exit_code')}")
    agent_sessions = config.workspace / "agent_sessions.jsonl"
    if agent_sessions.exists():
        valid_session_statuses = {"planned", "running", "blocked", "failed", "complete"}
        run_ids = {str(record.get("run_id", "")) for record in read_jsonl_like(agent_runs)}
        for index, line in enumerate(read_text(agent_sessions).splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                warnings.append(f"invalid JSONL in agent_sessions.jsonl line {index}: {exc}")
                continue
            if record.get("status") not in valid_session_statuses:
                warnings.append(f"agent_sessions.jsonl line {index} has invalid status {record.get('status')}")
            for run_id in record.get("linked_run_ids", []):
                if str(run_id) not in run_ids:
                    warnings.append(f"agent_sessions.jsonl line {index} links unknown run_id {run_id}")
    decisions_path = config.workspace / "agent_decisions.json"
    if decisions_path.exists():
        valid_decision_statuses = {"open", "resolved", "stale", "dismissed"}
        decisions = read_json(decisions_path, [])
        if isinstance(decisions, list):
            seen_decisions = set()
            for decision in decisions:
                decision_id = str(decision.get("decision_id", ""))
                if not decision_id:
                    warnings.append("agent_decisions.json contains a decision without decision_id")
                elif decision_id in seen_decisions:
                    warnings.append(f"agent_decisions.json contains duplicate decision_id {decision_id}")
                seen_decisions.add(decision_id)
                if decision.get("status") not in valid_decision_statuses:
                    warnings.append(f"agent_decisions.json decision {decision_id or 'unknown'} has invalid status {decision.get('status')}")
                if decision.get("status") == "resolved" and not decision.get("resolved_at"):
                    warnings.append(f"agent_decisions.json decision {decision_id} is resolved without resolved_at")
        else:
            issues.append("agent_decisions.json must be a list")
    eval_report_path = config.workspace / "agent_eval_report.json"
    if eval_report_path.exists():
        report = read_json(eval_report_path, {})
        if not isinstance(report, dict):
            issues.append("agent_eval_report.json must be an object")
        else:
            if "fixtures" not in report:
                warnings.append("agent_eval_report.json has no fixtures field")
            elif not isinstance(report.get("fixtures"), list):
                warnings.append("agent_eval_report.json fixtures field must be a list")
    if (config.workspace / "revision_provenance.json").exists() and (config.workspace / "revision_provenance.md").exists() and provenance_missing_or_stale(config):
        warnings.append("revision provenance is stale; run revagent provenance")
    from .memory import memory_missing_or_stale

    if memory_missing_or_stale(config):
        warnings.append("revision memory is missing or stale; run revagent memory")
    from .readiness import readiness_missing_or_stale

    if readiness_missing_or_stale(config):
        warnings.append("revision readiness report is missing or stale; run revagent readiness")
    if not (config.tex_root / config.main_tex).exists():
        issues.append(f"main TeX file not found: {config.tex_root / config.main_tex}")
    index = latex_index(config.tex_root, config.main_tex)
    for warning in index.get("warnings", []):
        warnings.append(str(warning))
    missing_includes = [entry for entry in index.get("includes", []) if entry.get("missing")]
    if missing_includes:
        warnings.append(f"{len(missing_includes)} included TeX files were not found")
    if index["unresolved_refs"]:
        warnings.append(f"{len(index['unresolved_refs'])} unresolved LaTeX references detected")
    raw_config = parse_simple_yaml(read_text(config.workspace / "revision.yaml"))
    if raw_config.get("schema_version") != CURRENT_SCHEMA_VERSION:
        warnings.append(f"workspace schema_version is missing or not {CURRENT_SCHEMA_VERSION}")
    migration = migrate_workspace(base, dry_run=True)
    for action in migration.get("actions", []):
        warnings.append(f"workspace migration available: {action}")
    items = load_items(config)
    item_ids = {str(item.get("id", "")) for item in items}
    try:
        review_analyses = load_review_analyses(config)
    except json.JSONDecodeError:
        review_analyses = {}
    if not isinstance(review_analyses, dict):
        issues.append("review_analyses.json must be an object")
        review_analyses = {}
    for analysis_id, analysis in review_analyses.items():
        if str(analysis_id) not in item_ids:
            warnings.append(f"review_analyses.json contains unknown item id {analysis_id}")
        if isinstance(analysis, dict) and analysis.get("item_id") and str(analysis.get("item_id")) != str(analysis_id):
            warnings.append(f"review_analyses.json key {analysis_id} has mismatched item_id {analysis.get('item_id')}")
        if not isinstance(analysis, dict):
            warnings.append(f"review_analyses.json analysis {analysis_id} must be an object")
    for item_id in sorted(item_ids):
        if item_id and item_id not in review_analyses:
            warnings.append(f"{item_id} has no review analysis; run analyze-review {item_id}")
    candidates = load_candidates(config)
    proof_workflows = load_proof_workflows(config)
    experiment_manifests = load_experiment_manifests(config)
    experiment_attempts = load_experiment_run_attempts(config)
    provenance = build_revision_provenance(base)
    provenance_by_item = {record.get("item_id"): record for record in provenance.get("items", [])}
    required_item_fields = {
        "id",
        "kind",
        "lane",
        "severity",
        "risk",
        "status",
        "planning_status",
        "comment",
        "source",
        "reviewer",
        "revision_plan",
        "required_evidence",
        "blocking_questions",
        "completion_criteria",
    }
    for item in items:
        missing = sorted(required_item_fields - set(item))
        if missing:
            warnings.append(f"{item.get('id', 'unknown item')} missing fields: {', '.join(missing)}")
        planning_status = item.get("planning_status", "triaged")
        if planning_status not in PLANNING_STATUSES:
            issues.append(f"{item.get('id', 'unknown item')} has invalid planning_status {planning_status}")
        if planning_status in {"planned", "drafted", "evidence_ready", "approved"} and not item.get("revision_plan"):
            warnings.append(f"{item.get('id', 'unknown item')} has no revision_plan; run plan-item")
        if item.get("kind") == "proof":
            lane = item.get("proof_lane") or {}
            if lane.get("approval_status", "required") != "approved":
                warnings.append(f"{item['id']} proof lane requires author approval")
            if planning_status in {"planned", "drafted"} and lane.get("approval_status", "required") != "approved":
                warnings.append(f"{item['id']} planned proof item still has unresolved author verification")
            workflow = proof_workflows.get(item["id"])
            if not workflow:
                warnings.append(f"{item['id']} has no proof workflow; run proof-plan")
            else:
                if not workflow.get("statement_snapshot"):
                    warnings.append(f"{item['id']} proof workflow has no statement snapshot")
                if not workflow.get("proof_snapshot"):
                    warnings.append(f"{item['id']} proof workflow has no proof snapshot")
                open_obligations = [ob for ob in workflow.get("proof_obligations", []) if ob.get("status") != "closed"]
                if open_obligations:
                    warnings.append(f"{item['id']} proof workflow has {len(open_obligations)} open proof obligations")
        if item.get("kind") == "experiment":
            lane = item.get("experiment_lane") or {}
            if lane.get("result_status") != "recorded":
                warnings.append(f"{item['id']} experiment result provenance is not recorded")
            if planning_status in {"planned", "drafted"} and lane.get("result_status") != "recorded":
                warnings.append(f"{item['id']} planned experiment item lacks recorded result evidence")
            manifest = experiment_manifests.get(item["id"])
            if not manifest:
                warnings.append(f"{item['id']} has no experiment manifest; run experiment-contract")
            else:
                if manifest.get("status") not in EXPERIMENT_CONTRACT_STATUSES:
                    issues.append(f"{item['id']} has invalid experiment contract status {manifest.get('status')}")
                if not manifest.get("command_template"):
                    warnings.append(f"{item['id']} experiment manifest has no command template")
                if not manifest.get("seed"):
                    warnings.append(f"{item['id']} experiment manifest has no seed")
                if not manifest.get("expected_artifacts"):
                    warnings.append(f"{item['id']} experiment manifest has no expected artifacts")
                if manifest.get("command_template") and not any(attempt.get("item_id") == item["id"] and attempt.get("status") != "invalid" for attempt in experiment_attempts):
                    warnings.append(f"{item['id']} experiment manifest has no run attempt; run experiment-run {item['id']} --dry-run")
                for artifact in manifest.get("artifacts", []):
                    artifact_path = config.tex_root / artifact.get("path", "")
                    if not artifact_path.exists():
                        warnings.append(f"{item['id']} experiment artifact is missing: {artifact.get('path')}")
                        continue
                    current_hash = file_sha256(artifact_path)
                    if artifact.get("sha256") and current_hash != artifact.get("sha256"):
                        warnings.append(f"{item['id']} experiment artifact hash changed: {artifact.get('path')}")
        if planning_status == "incorporated":
            approved_for_item = [candidate for candidate in candidates if candidate.get("item_id") == item.get("id") and candidate.get("status") == "approved"]
            if approved_for_item:
                warnings.append(f"{item['id']} is incorporated but still has unapplied approved candidates")
            if item.get("kind") == "proof":
                lane = item.get("proof_lane") or {}
                if lane.get("approval_status") != "approved":
                    issues.append(f"{item['id']} is incorporated without proof workflow approval provenance")
            if item.get("kind") == "experiment":
                manifest = experiment_manifests.get(item.get("id", ""))
                if not manifest or not manifest.get("artifacts") or not manifest.get("backfill_targets"):
                    warnings.append(f"{item['id']} is incorporated without complete experiment artifact/backfill provenance")
        if planning_status == "closed" and item.get("blocking_questions"):
            warnings.append(f"{item['id']} is closed with unresolved blocking questions")
    allowed_candidate_status = {"proposed", "edited", "approved", "applied", "rejected", "blocked"}
    allowed_candidate_operations = {"insert_after_line", "replace_block", "insert_before_environment", "insert_after_environment", "update_caption"}
    for candidate in candidates:
        item = find_item(items, candidate.get("item_id", ""))
        if candidate.get("status") == "applied" and item is None:
            issues.append(f"{candidate.get('id')} is applied without a traceable review item")
        if candidate.get("status") not in allowed_candidate_status:
            issues.append(f"{candidate.get('id', 'unknown candidate')} has invalid status {candidate.get('status')}")
        if candidate.get("operation", "insert_after_line") not in allowed_candidate_operations:
            issues.append(f"{candidate.get('id', 'unknown candidate')} has invalid operation {candidate.get('operation')}")
        if candidate.get("operation") != "insert_after_line" and not candidate.get("original_content_hash"):
            warnings.append(f"{candidate.get('id', 'unknown candidate')} has no original_content_hash for {candidate.get('operation')}")
        if candidate.get("kind") == "proof" and candidate.get("status") == "approved":
            item = find_item(items, candidate.get("item_id", ""))
            lane = (item or {}).get("proof_lane") or {}
            if lane.get("approval_status") != "approved":
                issues.append(f"{candidate.get('id')} is an approved proof candidate without proof workflow approval")
        if candidate.get("kind") == "experiment" and candidate.get("status") in {"proposed", "approved", "applied"}:
            manifest = experiment_manifests.get(candidate.get("item_id", ""))
            if manifest and manifest.get("artifacts") and not manifest.get("backfill_targets"):
                warnings.append(f"{candidate.get('id')} uses experiment results without a backfill target mapping")
        if candidate.get("status") in {"approved", "applied"}:
            reason = llm_candidate_gate_reason(config, candidate)
            if reason:
                issues.append(reason)
        if candidate.get("status") == "applied" and item is not None:
            record = provenance_by_item.get(candidate.get("item_id", ""))
            if not record or not any(entry.get("id") == candidate.get("id") for entry in record.get("candidates", [])):
                issues.append(f"{candidate.get('id')} is applied without revision provenance")
        if candidate.get("status") == "approved":
            warnings.append(f"{candidate.get('id')} is approved but not applied")
            reason = verify_candidate_anchor(config, candidate) or verify_candidate_operation(config, candidate)
            if reason:
                warnings.append(f"{candidate.get('id')} would be blocked on apply: {reason}")
    if compile_check:
        exe = config.compile_command.split()[0]
        if shutil.which(exe) is None:
            warnings.append(f"compile check skipped because {exe!r} is not on PATH")
        else:
            result = subprocess.run(
                config.compile_command.split() + [config.main_tex],
                cwd=config.tex_root,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            write_text(config.workspace / "logs" / "latexmk.stdout.log", result.stdout)
            write_text(config.workspace / "logs" / "latexmk.stderr.log", result.stderr)
            if result.returncode != 0:
                issues.append(f"compile command failed with exit code {result.returncode}")
    return {"ok": not issues, "issues": issues, "warnings": warnings, "index": index}

def doctor(base: Path) -> dict[str, object]:
    checks = []
    checks.append({"name": "python", "ok": sys.version_info >= (3, 10), "detail": sys.version.split()[0]})
    checks.append({"name": "workspace", "ok": workspace_path(base).exists(), "detail": str(workspace_path(base))})
    checks.append({"name": "latexmk", "ok": shutil.which("latexmk") is not None, "detail": shutil.which("latexmk") or "not found"})
    checks.append({"name": "profiles", "ok": True, "detail": ", ".join(available_profiles(base))})
    if workspace_path(base).exists():
        config = load_config(base)
        checks.append({"name": "main_tex", "ok": (config.tex_root / config.main_tex).exists(), "detail": str(config.tex_root / config.main_tex)})
    return {"ok": all(check["ok"] for check in checks if check["name"] != "latexmk"), "checks": checks}

__all__ = ["doctor", "validate_workspace"]
