"""Workspace schema, config, IO, and migration public API."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from ._models import CURRENT_SCHEMA_VERSION, PLANNING_STATUSES, SCHEMA_FILES, WORKSPACE, Config
from ._utils import (
    find_candidate,
    find_item,
    find_main_tex,
    load_config,
    load_items,
    now_iso,
    parse_simple_yaml,
    read_json,
    read_text,
    simple_yaml,
    workspace_path,
    write_items,
    write_json,
    write_text,
)
from .latex import latex_index
from .profiles import load_profile
from .reviews import classify_item, default_item_fields, experiment_lane_template, proof_lane_template, risk_for
from .candidates import (
    anchor_context_hash_for,
    candidate_patch_metadata,
    load_candidates,
    write_candidates,
)
from .experiments import (
    build_experiment_manifest,
    load_experiment_manifests,
    sync_experiment_lane_from_manifest,
    write_experiment_manifests,
)
from .llm import ensure_llm_review_fields, render_llm_drafts
from .review_analysis import render_review_analyses
from .readiness import READINESS_SCHEMA_VERSION, render_revision_readiness


ARTIFACT_REGISTRY_VERSION = 1


def artifact_registry_document(workspace: Path) -> dict[str, object]:
    """Describe persisted JSON/YAML artifacts without treating them as conclusions."""
    artifacts: list[dict[str, object]] = []
    for name in sorted(path for path in SCHEMA_FILES if path.endswith((".json", ".yaml")) and path != "artifact_registry.json"):
        path = workspace / name
        if not path.exists():
            continue
        schema_version: object = "legacy-unversioned"
        if name.endswith(".json"):
            try:
                payload = read_json(path, None)
            except (OSError, ValueError):
                payload = None
            if isinstance(payload, dict):
                schema_version = payload.get("schema_version", payload.get("version", schema_version))
        elif name == "revision.yaml":
            schema_version = parse_simple_yaml(read_text(path)).get("schema_version", schema_version)
        artifacts.append(
            {
                "path": name,
                "format": "json" if name.endswith(".json") else "yaml",
                "schema_version": str(schema_version),
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "owner": "workspace",
                "migration": "revagent migrate --apply",
                "compatibility": "Additive fields are supported; use migration before relying on an incompatible schema.",
            }
        )
    return {
        "version": ARTIFACT_REGISTRY_VERSION,
        "generated_at": now_iso(),
        "policy": "The registry records local artifact provenance. Hashes identify the observed snapshot and do not establish mathematical or numerical correctness.",
        "artifacts": artifacts,
    }


def write_artifact_registry(base: Path) -> dict[str, object]:
    workspace = load_config(base).workspace
    registry = artifact_registry_document(workspace)
    write_json(workspace / "artifact_registry.json", registry)
    return registry


def artifact_registry_is_stale(base: Path) -> bool:
    """Whether the registry no longer describes the current artifact snapshot."""
    workspace = load_config(base).workspace
    try:
        registry = read_json(workspace / "artifact_registry.json", {})
    except (OSError, ValueError):
        return True
    registered = registry.get("artifacts") if isinstance(registry, dict) else None
    if not isinstance(registered, list):
        return True
    recorded_hashes = {
        str(entry.get("path", "")): str(entry.get("content_sha256", ""))
        for entry in registered
        if isinstance(entry, dict)
    }
    current_hashes = {
        str(entry["path"]): str(entry["content_sha256"])
        for entry in artifact_registry_document(workspace)["artifacts"]
    }
    return recorded_hashes != current_hashes

def default_agent_policy_document() -> dict[str, object]:
    safe = [
        "draft",
        "experiment_contract",
        "experiment_run_preview",
        "llm_check",
        "llm_draft",
        "migrate",
        "plan_item",
        "plan_workspace",
        "proof_plan",
        "propose",
        "provenance",
        "readiness",
        "review_analysis",
        "validate",
    ]
    manual = [
        "approve",
        "apply",
        "candidate_author_text_required",
        "experiment_artifact",
        "experiment_incorporate",
        "experiment_run_record",
        "experiment_result_required",
        "llm_candidate_approval_required",
        "llm_quality_required",
        "llm_review_required",
        "proof_approval_required",
        "proof_approve",
    ]
    return {
        "version": 1,
        "safe_auto": safe,
        "manual_required": manual,
        "disallowed": ["run_experiment", "auto_approve_candidate", "auto_apply_candidate", "auto_approve_llm_draft"],
        "notes": [
            "Safe-auto tasks may refresh deterministic workspace artifacts.",
            "Manual-required tasks must be completed with explicit author commands.",
            "RevAgent never auto-approves LLM drafts, proof workflows, experiment results, or candidate edits.",
        ],
    }


def render_agent_policy_document(policy: dict[str, object]) -> str:
    lines = ["# Agent Policy", ""]
    for key in ("safe_auto", "manual_required", "disallowed"):
        lines.extend([f"## {key}", ""])
        values = policy.get(key, [])
        lines.extend(f"- `{value}`" for value in values)
        if not values:
            lines.append("- None.")
        lines.append("")
    lines.extend(["## Notes", ""])
    lines.extend(f"- {note}" for note in policy.get("notes", []))
    return "\n".join(lines).rstrip() + "\n"

def init_workspace(base: Path, journal: str, tex_root_arg: str, main_tex: str | None) -> Path:
    profile = load_profile(journal, base)
    tex_root = (base / tex_root_arg).resolve()
    main = main_tex or find_main_tex(tex_root)
    ws = workspace_path(base)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "artifacts").mkdir(exist_ok=True)
    (ws / "logs").mkdir(exist_ok=True)
    write_text(
        ws / "revision.yaml",
        simple_yaml(
            {
                "journal": profile["key"],
                "tex_root": str(tex_root),
                "main_tex": main,
                "workspace": WORKSPACE,
                "compile_command": "latexmk -pdf",
                "schema_version": CURRENT_SCHEMA_VERSION,
                "created_at": now_iso(),
            }
        ),
    )
    write_json(ws / "journal_profile.json", profile)
    write_json(ws / "review_items.json", [])
    write_json(ws / "comment_import.json", {"version": 1, "status": "not_imported"})
    write_json(ws / "latex_index.json", latex_index(tex_root, main))
    write_json(ws / "item_plans.json", {})
    write_text(ws / "item_plans.md", "# Item Plans\n\n")
    write_json(ws / "review_analyses.json", {})
    write_text(ws / "review_analyses.md", render_review_analyses({}))
    write_json(ws / "proof_workflows.json", {})
    write_text(ws / "proof_workflows.md", "# Proof Workflows\n\n")
    write_json(ws / "experiment_manifests.json", {})
    write_text(ws / "experiment_manifests.md", "# Experiment Manifests\n\n")
    write_text(ws / "experiment_run_attempts.jsonl", "")
    write_text(ws / "experiment_run_attempts.md", "# Experiment Run Attempts\n\nNo experiment run attempts recorded yet.\n")
    write_json(ws / "agent_state.json", {"version": 1, "generated_at": now_iso(), "last_run_at": "", "tasks": [], "summary": {}})
    write_text(ws / "agent_state.md", "# Agent State\n\nNo agent tasks generated yet.\n")
    write_text(ws / "agent_runs.jsonl", "")
    write_text(ws / "agent_runs.md", "# Agent Runs\n\nNo agent runs recorded yet.\n")
    policy = default_agent_policy_document()
    write_json(ws / "agent_policy.json", policy)
    write_text(ws / "agent_policy.md", render_agent_policy_document(policy))
    from .privacy import DEFAULT_PRIVACY_POLICY
    write_json(ws / "privacy_policy.json", DEFAULT_PRIVACY_POLICY)
    write_json(ws / "privacy_scan.json", {"version": 1, "scanned_at": "", "inventory": [], "findings": [], "remote_safe": False})
    write_text(ws / "privacy_scan.md", "# Privacy Scan\n\nNo scan run yet.\n")
    write_text(ws / "agent_report.md", "# Agent Report\n\nNo agent report generated yet.\n")
    write_text(ws / "agent_dashboard.md", "# Agent Dashboard\n\nNo agent dashboard generated yet.\n")
    write_text(ws / "agent_sessions.jsonl", "")
    write_text(ws / "agent_sessions.md", "# Agent Sessions\n\nNo agent sessions recorded yet.\n")
    write_json(ws / "agent_decisions.json", [])
    write_text(ws / "agent_decisions.md", "# Agent Decisions\n\nNo agent decisions recorded yet.\n")
    write_json(ws / "agent_eval_report.json", {"version": 1, "generated_at": "", "ok": False, "fixtures": []})
    write_text(ws / "agent_eval_report.md", "# Agent Eval Report\n\nNo agent eval report generated yet.\n")
    write_text(ws / "external_agent_runs.jsonl", "")
    write_text(ws / "external_agent_runs.md", "# External Agent Runs\n\nNo external agent runs recorded yet.\n")
    write_text(ws / "monitor.md", "# RevAgent Monitor\n\nNo monitor report generated yet.\n")
    write_json(ws / "supervisor_plan.json", {"version": 1, "generated_at": "", "tasks": []})
    write_text(ws / "supervisor_plan.md", "# Supervisor Plan\n\nNo supervisor plan generated yet.\n")
    write_text(ws / "supervisor_runs.jsonl", "")
    write_text(ws / "supervisor_runs.md", "# Supervisor Runs\n\nNo supervisor runs recorded yet.\n")
    write_json(ws / "supervisor_feedback.json", {"version": 1, "generated_at": "", "recommendations": []})
    write_text(ws / "supervisor_feedback.md", "# Supervisor Feedback\n\nNo supervisor feedback generated yet.\n")
    write_json(ws / "supervisor_workers.json", {"version": 1, "generated_at": "", "assignments": []})
    write_text(ws / "supervisor_workers.md", "# Supervisor Workers\n\nNo supervisor workers generated yet.\n")
    write_text(ws / "supervisor_observations.jsonl", "")
    write_text(ws / "supervisor_observations.md", "# Supervisor Observations\n\nNo queued worker observations recorded yet.\n")
    write_text(ws / "worker_runtime_events.jsonl", "")
    write_text(ws / "worker_runtime_events.md", "# Worker Runtime Events\n\nNo worker runtime events recorded yet.\n")
    write_json(ws / "worker_snapshots.json", {})
    write_text(ws / "worker_snapshots.md", "# Worker Snapshots\n\nNo worker snapshots recorded yet.\n")
    write_text(ws / "worker_evaluations.jsonl", "")
    write_text(ws / "worker_evaluations.md", "# Worker Evaluations\n\nNo worker evaluations recorded yet.\n")
    write_json(ws / "evolution_proposals.json", [])
    write_text(ws / "evolution_proposals.md", "# Evolution Proposals\n\nNo evolution proposals recorded yet.\n")
    import sqlite3
    sqlite3.connect(ws / "runtime.sqlite3").close()
    write_json(ws / "review_evidence.json", {})
    write_text(ws / "review_evidence.md", "# Review Evidence\n\nNo review evidence recorded yet.\n")
    write_json(ws / "review_evaluations.json", {})
    write_text(ws / "review_evaluations.md", "# Review Evaluations\n\nNo review evaluations recorded yet.\n")
    write_json(ws / "review_workers.json", {})
    write_text(ws / "review_workers.md", "# Review Workers\n\nNo review workers recorded yet.\n")
    write_json(ws / "review_conflicts.json", {})
    write_text(ws / "review_conflicts.md", "# Review Conflicts\n\nNo review conflicts recorded yet.\n")
    write_json(ws / "experiment_authorizations.json", {})
    write_text(ws / "experiment_authorizations.md", "# Experiment Authorizations\n\nNo experiment authorizations recorded yet.\n")
    write_json(ws / "service.json", {})
    write_json(ws / "llm_drafts.json", {})
    write_text(ws / "llm_drafts.md", "# LLM Drafts\n\nNo LLM drafts generated yet.\n")
    write_text(ws / "response_letter.md", f"# {profile['response_heading']}\n\n")
    write_text(ws / "revision_plan.md", "# Revision Plan\n\nNo reviewer comments ingested yet.\n")
    write_text(ws / "proof_audit.md", "# Proof Audit\n\nNo proof-related review items ingested yet.\n")
    write_text(ws / "experiment_plan.md", "# Experiment Plan\n\nNo experiment-related review items ingested yet.\n")
    write_text(ws / "manuscript.patch", "# No manuscript patch notes drafted yet.\n")
    write_json(ws / "candidate_edits.json", [])
    write_text(ws / "decision_log.md", "# Decision Log\n\n")
    write_text(ws / "open_issues.md", "# Open Issues\n\nNo open issues recorded yet.\n")
    from .provenance import write_revision_provenance

    write_revision_provenance(base)
    from .memory import write_revision_memory

    write_revision_memory(base)
    readiness_default = {
        "generated_at": "",
        "schema_version": READINESS_SCHEMA_VERSION,
        "source_fingerprint": "",
        "overall_status": "empty",
        "summary_counts": {},
        "items": [],
        "blockers": [],
        "submit_pack_missing": [],
    }
    write_json(ws / "revision_readiness.json", readiness_default)
    write_text(ws / "revision_readiness.md", render_revision_readiness(readiness_default))
    write_json(ws / "pre_submission_review.json", {"version": 1, "status": "not_run"})
    write_text(ws / "pre_submission_review.md", "# Pre-submission Review\n\nNo pre-submission review run yet. Run `revagent review-paper`.\n")
    write_json(ws / "paper_manifest.json", {"version": 1, "status": "not_ingested"})
    write_text(ws / "paper_manifest.md", "# Paper Manifest\n\nNo paper ingestion run yet. Run `revagent paper-ingest`.\n")
    write_json(ws / "review_reports.json", {"version": 1, "reports": {}})
    write_text(ws / "review_reports.md", "# Role-scoped Pre-submission Reports\n\nNo role reports run yet.\n")
    write_json(ws / "review_meta_report.json", {"version": 1, "status": "not_merged"})
    write_text(ws / "review_meta_report.md", "# Merged Pre-submission Review\n\nNo role reports merged yet.\n")
    write_json(ws / "review_engine.json", {"version": 1, "max_rounds": 2, "rounds": []})
    write_json(ws / "review_followups.json", {"version": 1, "tasks": []})
    write_text(ws / "review_followups.md", "# Verification Follow-ups\n\nNo follow-ups created.\n")
    write_json(ws / "review_outputs.json", {"version": 1, "status": "not_generated"})
    write_text(ws / "review_outputs.md", "# Advisory Pre-submission Outputs\n\nNo review round completed.\n")
    write_json(ws / "rebuttal_threads.json", {"version": 1, "threads": {}})
    write_text(ws / "rebuttal_threads.md", "# Rebuttal Threads\n\nNo rebuttal threads parsed yet.\n")
    write_text(ws / "rebuttal_draft.md", "# PASTE_READY — Author Review Required\n\nNo rebuttal draft generated yet.\n")
    write_json(ws / "rebuttal_stress_test.json", {"version": 2, "ok": False, "open_atoms": []})
    write_text(ws / "rebuttal_stress_test.md", "# Rebuttal Stress Test\n\nNo rebuttal stress test run yet.\n")
    write_json(ws / "rebuttal_final.json", {"version": 2, "status": "not_finalized"})
    write_json(ws / "literature_consent.json", {"version": 1, "authorizations": []})
    write_json(ws / "literature_report.json", {"version": 2, "availability": "not_generated", "retrieved_metadata": [], "excluded_local_only_records": 0})
    write_json(ws / "literature_query_authorizations.json", {"version": 1, "authorizations": []})
    write_json(ws / "literature_citation_graph.json", {"version": 1, "nodes": [], "edges": []})
    write_json(ws / "literature_retractions.json", {"version": 1, "records": [], "assertions": []})
    write_json(ws / "literature_alignments.json", {"version": 1, "candidates": []})
    write_json(ws / "history_registry.json", {"version": 2, "records": []})
    write_json(ws / "review_benchmark_report.json", {"version": 1, "status": "not_run"})
    write_text(ws / "review_benchmark_report.md", "# Reviewer Pack Benchmark\n\nNo adjudicated review benchmark run yet.\n")
    write_json(ws / "alignment_benchmark_report.json", {"version": 1, "status": "not_run"})
    write_text(ws / "alignment_benchmark_report.md", "# Claim Alignment Benchmark\n\nNo adjudicated alignment benchmark run yet.\n")
    write_json(ws / "alignment_case_registry.json", {"version": 1, "cases": {}})
    write_json(ws / "artifact_registry.json", artifact_registry_document(ws))
    return ws

def schema_markdown() -> str:
    return "\n".join(
        [
            "# RevAgent Workspace Schema",
            "",
            f"Schema version: {CURRENT_SCHEMA_VERSION}",
            "",
            "## Core Files",
            "",
            "- `revision.yaml`: journal, TeX root, main TeX file, compile command, schema version.",
            "- `review_items.json`: reviewer items with lane, risk, severity, source, reviewer, locations, and lane payloads.",
            "- `comment_import.json`: source and normalized-comment hashes, local conversion metadata, and import timestamp.",
            "- `latex_index.json`: reachable files, includes, sections, labels, refs, environments, and dependency map.",
            "- `item_plans.json`: structured per-item planning records keyed by review item id.",
            "- `item_plans.md`: reviewable markdown rendering of per-item plans.",
            "- `review_analyses.json`: structured reviewer-intent, claim/evidence, risk, and response-strategy records keyed by review item id.",
            "- `review_analyses.md`: reviewable rendering of reviewer intent, claim targets, evidence needs, author verification, and risk notes.",
            "- `proof_workflows.json`: structured proof workflow records keyed by proof review item id.",
            "- `proof_workflows.md`: reviewable proof workflow status, snapshots, obligations, and approval gates.",
            "- `experiment_manifests.json`: experiment reproducibility contracts keyed by experiment review item id.",
            "- `experiment_manifests.md`: reviewable experiment command, artifact, hash, and backfill contract report.",
            "- `experiment_run_attempts.jsonl`: append-only local experiment command attempts with exit codes, logs, and detected artifact hashes.",
            "- `experiment_run_attempts.md`: reviewable rendering of experiment run attempts.",
            "- `agent_state.json`: deterministic safe-auto task queue and last run state.",
            "- `agent_state.md`: reviewable rendering of pending, blocked, done, failed, and skipped agent tasks.",
            "- `agent_runs.jsonl`: append-only safe task execution ledger.",
            "- `agent_runs.md`: reviewable rendering of recent agent task runs.",
            "- `agent_policy.json`: safe-auto/manual/disallowed agent task policy.",
            "- `agent_policy.md`: reviewable rendering of the agent safety policy.",
            "- `agent_report.md`: latest agent scheduler, stale input, failure, and manual-gate report.",
            "- `agent_dashboard.md`: single-page monitor view for the current session, next action, lanes, decisions, failures, stale tasks, and recent runs.",
            "- `agent_sessions.jsonl`: append-only goal-oriented agent session records.",
            "- `agent_sessions.md`: reviewable rendering of agent goals, phases, blockers, and linked runs.",
            "- `agent_decisions.json`: stable manual decision queue for operator review.",
            "- `agent_decisions.md`: reviewable rendering of open, stale, resolved, and dismissed decisions.",
            "- `agent_eval_report.json`: deterministic agent trajectory eval results.",
            "- `agent_eval_report.md`: reviewable rendering of the latest agent eval report.",
            "- `external_agent_runs.jsonl`: append-only external Codex/agent run ledger.",
            "- `external_agent_runs.md`: reviewable rendering of external agent runs.",
            "- `monitor.md`: latest interactive recovery monitor output.",
            "- `supervisor_plan.json`: generated plan-evolution and safe-loop task plan.",
            "- `supervisor_plan.md`: reviewable rendering of the current supervisor plan.",
            "- `supervisor_runs.jsonl`: append-only conservative supervisor loop ledger.",
            "- `supervisor_runs.md`: reviewable rendering of supervisor loop runs.",
            "- `supervisor_feedback.json`: generated read-only supervisor strategy feedback.",
            "- `supervisor_feedback.md`: reviewable rendering of supervisor strategy feedback.",
            "- `supervisor_workers.json`: generated conservative external worker assignment plan.",
            "- `supervisor_workers.md`: reviewable rendering of supervisor worker assignments.",
            "- `supervisor_observations.jsonl`: append-only, read-only artifact observations for queued external workers.",
            "- `supervisor_observations.md`: reviewable rendering of queued worker observations.",
            "- `worker_runtime_events.jsonl`: append-only explicit worker lifecycle events with PID/create-time identity.",
            "- `worker_snapshots.json`: isolated RevAgent source snapshot manifests for controlled workers.",
            "- `worker_evaluations.jsonl`: append-only snapshot patch and test-gate evaluations.",
            "- `evolution_proposals.json`: manually approved RevAgent source evolution proposals.",
            "- `llm_drafts.json`: offline LLM reviewer-intent, response, candidate-text drafts, author review status, and quality status keyed by review item id.",
            "- `llm_drafts.md`: reviewable rendering of LLM drafts, author review notes, and quality issues. Entries are never auto-approved or auto-applied.",
            "- `revision_provenance.json`: generated per-item provenance snapshot linking reviewer comments, LLM drafts, candidates, proof/experiment gates, and apply records.",
            "- `revision_provenance.md`: reviewable rendering of the revision provenance snapshot.",
            "- `revision_memory.json`: generated durable facts for agent grounding.",
            "- `revision_memory.md`: reviewable rendering of revision memory facts.",
            "- `revision_readiness.json`: generated per-item readiness snapshot for submission gating.",
            "- `revision_readiness.md`: reviewable rendering of blockers, ready items, and submit-pack gaps.",
            "- `pre_submission_review.json`: latest local-only, deterministic, advisory pre-submission structural review; `status: not_run` until generated.",
            "- `pre_submission_review.md`: reviewable rendering of the advisory pre-submission report.",
            "- `paper_manifest.json`: versioned local source/PDF binding and LaTeX-index observations; it does not certify correctness.",
            "- `paper_manifest.md`: reviewable rendering of the local paper manifest.",
            "- `review_reports.json` / `review_reports.md`: role-scoped advisory structural reports with separate inputs and findings.",
            "- `review_meta_report.json` / `review_meta_report.md`: advisory merge of current role reports; never an editorial decision.",
            "- `review_engine.json`: bounded review-round policy and author-pause history.",
            "- `review_followups.json` / `review_followups.md`: bounded high-risk verification tasks, author-gated and never auto-executed.",
            "- `review_outputs.json` / `review_outputs.md`: advisory editor summary, reviewer report, and author action list.",
            "- `rebuttal_stress_test.json` / `rebuttal_stress_test.md`: deterministic coverage, provenance, placeholder, commitment, tone-pattern, and configured-length lint; never factual verification.",
            "- `review_benchmark_report.json` / `review_benchmark_report.md`: deterministic role/pack metrics against locally adjudicated labels; never model self-scores or release calibration by themselves.",
            "- `artifact_registry.json`: generated registry of persisted JSON/YAML artifact formats, versions, hashes, ownership, migration path, and compatibility policy.",
            "- `candidate_edits.json`: proposed/edited/approved/rejected/blocked/applied manuscript edits with safe patch operations.",
            "- `decision_log.md`: append-only rationale log for item reasoning and author decisions.",
            "- `experiment_runs.jsonl`: append-only experiment result provenance records.",
            "",
            "## Review Item Fields",
            "",
            "`id`, `kind`, `lane`, `severity`, `risk`, `status`, `planning_status`, `comment`, `source`, `reviewer`, `requires_author_input`, `evidence_required`, `required_evidence`, `blocking_questions`, `completion_criteria`, `revision_plan`, `tex_locations`, `proof_lane`, `experiment_lane`, `response_draft`.",
            "",
            "## Planning Status",
            "",
            "`triaged -> planned -> drafted -> evidence_ready -> approved -> incorporated -> closed`, with `reopen-item` returning closed items to `planned`.",
            "",
            "## Candidate Status",
            "",
            "`proposed -> edited -> approved -> applied`, with `rejected` and `blocked` terminal or recovery states. Supported operations: `insert_after_line`, `replace_block`, `insert_before_environment`, `insert_after_environment`, `update_caption`.",
            "",
        ]
    )

def migrate_workspace(base: Path, dry_run: bool = True) -> dict[str, object]:
    config = load_config(base)
    actions: list[str] = []
    changed = False

    revision_path = config.workspace / "revision.yaml"
    raw_config = parse_simple_yaml(read_text(revision_path))
    provenance_missing = not (config.workspace / "revision_provenance.json").exists() or not (config.workspace / "revision_provenance.md").exists()
    if raw_config.get("schema_version") != CURRENT_SCHEMA_VERSION:
        actions.append(f"set revision.yaml schema_version to {CURRENT_SCHEMA_VERSION}")
        if not dry_run:
            raw_config["schema_version"] = CURRENT_SCHEMA_VERSION
            write_text(revision_path, simple_yaml(raw_config))
            changed = True

    default_files = {
        "comment_import.json": {"version": 1, "status": "not_imported"},
        "candidate_edits.json": [],
        "item_plans.json": {},
        "item_plans.md": "# Item Plans\n\n",
        "review_analyses.json": {},
        "review_analyses.md": render_review_analyses({}),
        "proof_workflows.json": {},
        "proof_workflows.md": "# Proof Workflows\n\n",
        "experiment_manifests.json": {},
        "experiment_manifests.md": "# Experiment Manifests\n\n",
        "experiment_run_attempts.jsonl": "",
        "experiment_run_attempts.md": "# Experiment Run Attempts\n\nNo experiment run attempts recorded yet.\n",
        "agent_state.json": {"version": 1, "generated_at": now_iso(), "last_run_at": "", "tasks": [], "summary": {}},
        "agent_state.md": "# Agent State\n\nNo agent tasks generated yet.\n",
        "agent_runs.jsonl": "",
        "agent_runs.md": "# Agent Runs\n\nNo agent runs recorded yet.\n",
        "agent_policy.json": default_agent_policy_document(),
        "agent_policy.md": render_agent_policy_document(default_agent_policy_document()),
        "agent_report.md": "# Agent Report\n\nNo agent report generated yet.\n",
        "agent_dashboard.md": "# Agent Dashboard\n\nNo agent dashboard generated yet.\n",
        "agent_sessions.jsonl": "",
        "agent_sessions.md": "# Agent Sessions\n\nNo agent sessions recorded yet.\n",
        "agent_decisions.json": [],
        "agent_decisions.md": "# Agent Decisions\n\nNo agent decisions recorded yet.\n",
        "agent_eval_report.json": {"version": 1, "generated_at": "", "ok": False, "fixtures": []},
        "agent_eval_report.md": "# Agent Eval Report\n\nNo agent eval report generated yet.\n",
        "external_agent_runs.jsonl": "",
        "external_agent_runs.md": "# External Agent Runs\n\nNo external agent runs recorded yet.\n",
        "monitor.md": "# RevAgent Monitor\n\nNo monitor report generated yet.\n",
        "supervisor_plan.json": {"version": 1, "generated_at": "", "tasks": []},
        "supervisor_plan.md": "# Supervisor Plan\n\nNo supervisor plan generated yet.\n",
        "supervisor_runs.jsonl": "",
        "supervisor_runs.md": "# Supervisor Runs\n\nNo supervisor runs recorded yet.\n",
        "supervisor_feedback.json": {"version": 1, "generated_at": "", "recommendations": []},
        "supervisor_feedback.md": "# Supervisor Feedback\n\nNo supervisor feedback generated yet.\n",
        "supervisor_workers.json": {"version": 1, "generated_at": "", "assignments": []},
        "supervisor_workers.md": "# Supervisor Workers\n\nNo supervisor workers generated yet.\n",
        "supervisor_observations.jsonl": "",
        "supervisor_observations.md": "# Supervisor Observations\n\nNo queued worker observations recorded yet.\n",
        "worker_runtime_events.jsonl": "",
        "worker_runtime_events.md": "# Worker Runtime Events\n\nNo worker runtime events recorded yet.\n",
        "worker_snapshots.json": {},
        "worker_snapshots.md": "# Worker Snapshots\n\nNo worker snapshots recorded yet.\n",
        "worker_evaluations.jsonl": "",
        "worker_evaluations.md": "# Worker Evaluations\n\nNo worker evaluations recorded yet.\n",
        "evolution_proposals.json": [],
        "evolution_proposals.md": "# Evolution Proposals\n\nNo evolution proposals recorded yet.\n",
        "review_evidence.json": {},
        "review_evidence.md": "# Review Evidence\n\nNo review evidence recorded yet.\n",
        "review_evaluations.json": {},
        "review_evaluations.md": "# Review Evaluations\n\nNo review evaluations recorded yet.\n",
        "review_workers.json": {},
        "review_workers.md": "# Review Workers\n\nNo review workers recorded yet.\n",
        "review_conflicts.json": {},
        "review_conflicts.md": "# Review Conflicts\n\nNo review conflicts recorded yet.\n",
        "experiment_authorizations.json": {},
        "experiment_authorizations.md": "# Experiment Authorizations\n\nNo experiment authorizations recorded yet.\n",
        "service.json": {},
        "llm_drafts.json": {},
        "llm_drafts.md": "# LLM Drafts\n\nNo LLM drafts generated yet.\n",
        "revision_provenance.json": {"version": 1, "generated_at": "", "source_fingerprint": "", "items": []},
        "revision_provenance.md": "# Revision Provenance\n\nNo review items recorded.\n",
        "revision_memory.json": {"version": 1, "generated_at": "", "source_fingerprint": "", "facts": []},
        "revision_memory.md": "# Revision Memory\n\nNo review memory facts recorded.\n",
        "revision_readiness.json": {
            "generated_at": "",
            "schema_version": READINESS_SCHEMA_VERSION,
            "source_fingerprint": "",
            "overall_status": "empty",
            "summary_counts": {},
            "items": [],
            "blockers": [],
            "submit_pack_missing": [],
        },
        "revision_readiness.md": render_revision_readiness(
            {
                "generated_at": "",
                "schema_version": READINESS_SCHEMA_VERSION,
                "source_fingerprint": "",
                "overall_status": "empty",
                "summary_counts": {},
                "items": [],
                "blockers": [],
                "submit_pack_missing": [],
            }
        ),
        "pre_submission_review.json": {"version": 1, "status": "not_run"},
        "pre_submission_review.md": "# Pre-submission Review\n\nNo pre-submission review run yet. Run `revagent review-paper`.\n",
        "paper_manifest.json": {"version": 1, "status": "not_ingested"},
        "paper_manifest.md": "# Paper Manifest\n\nNo paper ingestion run yet. Run `revagent paper-ingest`.\n",
        "review_reports.json": {"version": 1, "reports": {}},
        "review_reports.md": "# Role-scoped Pre-submission Reports\n\nNo role reports run yet.\n",
        "review_meta_report.json": {"version": 1, "status": "not_merged"},
        "review_meta_report.md": "# Merged Pre-submission Review\n\nNo role reports merged yet.\n",
        "review_engine.json": {"version": 1, "max_rounds": 2, "rounds": []},
        "review_followups.json": {"version": 1, "tasks": []},
        "review_followups.md": "# Verification Follow-ups\n\nNo follow-ups created.\n",
        "review_outputs.json": {"version": 1, "status": "not_generated"},
        "review_outputs.md": "# Advisory Pre-submission Outputs\n\nNo review round completed.\n",
        "rebuttal_threads.json": {"version": 1, "threads": {}},
        "rebuttal_threads.md": "# Rebuttal Threads\n\nNo rebuttal threads parsed yet.\n",
        "rebuttal_draft.md": "# PASTE_READY — Author Review Required\n\nNo rebuttal draft generated yet.\n",
        "rebuttal_stress_test.json": {"version": 2, "ok": False, "open_atoms": []},
        "rebuttal_stress_test.md": "# Rebuttal Stress Test\n\nNo rebuttal stress test run yet.\n",
        "rebuttal_final.json": {"version": 2, "status": "not_finalized"},
        "literature_consent.json": {"version": 1, "authorizations": []},
        "literature_report.json": {"version": 2, "availability": "not_generated", "retrieved_metadata": [], "excluded_local_only_records": 0},
        "literature_query_authorizations.json": {"version": 1, "authorizations": []},
        "literature_citation_graph.json": {"version": 1, "nodes": [], "edges": []},
        "literature_retractions.json": {"version": 1, "records": [], "assertions": []},
        "literature_alignments.json": {"version": 1, "candidates": []},
        "history_registry.json": {"version": 2, "records": []},
        "review_benchmark_report.json": {"version": 1, "status": "not_run"},
        "review_benchmark_report.md": "# Reviewer Pack Benchmark\n\nNo adjudicated review benchmark run yet.\n",
        "alignment_benchmark_report.json": {"version": 1, "status": "not_run"},
        "alignment_benchmark_report.md": "# Claim Alignment Benchmark\n\nNo adjudicated alignment benchmark run yet.\n",
        "alignment_case_registry.json": {"version": 1, "cases": {}},
        "decision_log.md": "# Decision Log\n\n",
        "latex_index.json": latex_index(config.tex_root, config.main_tex),
        "proof_audit.md": "# Proof Audit\n\n",
        "experiment_plan.md": "# Experiment Plan\n\n",
        "manuscript.patch": "# No manuscript patch notes drafted yet.\n",
    }
    runtime_db = config.workspace / "runtime.sqlite3"
    if not runtime_db.exists():
        actions.append("create runtime.sqlite3")
        if not dry_run:
            import sqlite3
            sqlite3.connect(runtime_db).close()
            changed = True
    for name, default_value in default_files.items():
        target = config.workspace / name
        if not target.exists():
            actions.append(f"create missing {name}")
            if not dry_run:
                if name.endswith(".json"):
                    write_json(target, default_value)
                else:
                    write_text(target, str(default_value))
                changed = True

    literature_report_path = config.workspace / "literature_report.json"
    literature_report = read_json(literature_report_path, {})
    if literature_report.get("version") != 2:
        actions.append("upgrade literature_report.json to version 2")
        if not dry_run:
            literature_report["version"] = 2
            literature_report.setdefault("retrieved_metadata", [])
            literature_report.setdefault("excluded_local_only_records", 0)
            write_json(literature_report_path, literature_report)
            changed = True

    history_registry_path = config.workspace / "history_registry.json"
    history_registry = read_json(history_registry_path, {})
    if history_registry.get("version") != 2:
        actions.append("upgrade history_registry.json to version 2")
        if not dry_run:
            history_registry["version"] = 2
            for record in history_registry.get("records", []):
                record.setdefault("deidentification_status", "not_started")
                record.setdefault("retention_rule", "")
                record.setdefault("deletion_status", "active")
                record.setdefault("raw_content_stored", False)
                record["indexed"] = False
            write_json(history_registry_path, history_registry)
            changed = True

    llm_drafts_path = config.workspace / "llm_drafts.json"
    llm_drafts = read_json(llm_drafts_path, {})
    llm_changed = False
    for item_id, draft in llm_drafts.items():
        before = dict(draft)
        ensure_llm_review_fields(draft)
        if draft != before:
            actions.append(f"add LLM draft review fields {item_id}")
            llm_changed = True
    if llm_changed and not dry_run:
        write_json(llm_drafts_path, llm_drafts)
        write_text(config.workspace / "llm_drafts.md", render_llm_drafts(llm_drafts))
        changed = True

    items = load_items(config)
    item_changed = False
    for index, item in enumerate(items, start=1):
        defaults = default_item_fields(item, index, source=raw_config.get("comments_path", ""))
        for key, value in defaults.items():
            if key not in item:
                actions.append(f"add review item field {item.get('id', index)}.{key}")
                if not dry_run:
                    item[key] = value
                    item_changed = True
        if item.get("kind") == "proof":
            lane = item.get("proof_lane") or proof_lane_template(item.get("comment", ""))
            for key, value in proof_lane_template(item.get("comment", "")).items():
                if key not in lane:
                    actions.append(f"add proof lane field {item.get('id', index)}.{key}")
                    if not dry_run:
                        lane[key] = value
                        item_changed = True
            if not dry_run:
                item["proof_lane"] = lane
        if item.get("kind") == "experiment":
            lane = item.get("experiment_lane") or experiment_lane_template(item.get("comment", ""))
            for key, value in experiment_lane_template(item.get("comment", "")).items():
                if key not in lane:
                    actions.append(f"add experiment lane field {item.get('id', index)}.{key}")
                    if not dry_run:
                        lane[key] = value
                        item_changed = True
            if not dry_run:
                item["experiment_lane"] = lane
    if item_changed:
        write_items(config, items)
        changed = True

    manifests = load_experiment_manifests(config)
    manifest_changed = False
    for item in items:
        if item.get("kind") != "experiment":
            continue
        lane = item.get("experiment_lane") or {}
        if lane.get("recorded_results") and item.get("id") not in manifests:
            actions.append(f"migrate experiment manifest for {item.get('id')}")
            if not dry_run:
                manifest = build_experiment_manifest(config, item)
                manifests[item["id"]] = manifest
                sync_experiment_lane_from_manifest(item, manifest)
                manifest_changed = True
                item_changed = True
    if manifest_changed:
        write_items(config, items)
        write_experiment_manifests(config, manifests)
        changed = True

    candidates = load_candidates(config)
    candidate_changed = False
    for candidate in candidates:
        target_file = candidate.get("target_file", config.main_tex)
        anchor_line = int(candidate.get("anchor_line", 1))
        item = find_item(items, candidate.get("item_id", ""))
        loc = ((item or {}).get("tex_locations") or [{}])[0]
        patch = candidate_patch_metadata(config, item or {"kind": candidate.get("kind", "manuscript")}, target_file, anchor_line, loc)
        defaults = {
            "operation": "insert_after_line",
            "anchor_context_hash": anchor_context_hash_for(config, candidate.get("target_file", config.main_tex), int(candidate.get("anchor_line", 1))),
            "location_score": candidate.get("location_score", 0),
            "location_reason": candidate.get("location_reason", "migrated candidate"),
            "target_context": candidate.get("target_context", {"type": "unknown", "title": ""}),
            "proof_workflow_id": candidate.get("item_id", "") if candidate.get("kind") == "proof" else "",
            "proof_gate_status": "required" if candidate.get("kind") == "proof" else "",
            "target_span": patch["target_span"],
            "environment_id": patch["environment_id"],
            "original_content_hash": patch["original_content_hash"],
            "conflict_reason": "",
            "backup_dir": "",
        }
        for key, value in defaults.items():
            if key not in candidate:
                actions.append(f"add candidate field {candidate.get('id', 'unknown')}.{key}")
                if not dry_run:
                    candidate[key] = value
                    candidate_changed = True
    if candidate_changed:
        write_candidates(config, candidates)
        changed = True

    from .provenance import write_revision_provenance

    if provenance_missing:
        actions.append("refresh revision provenance snapshot")
        if not dry_run:
            write_revision_provenance(base)
            changed = True
    memory_missing = not (config.workspace / "revision_memory.json").exists() or not (config.workspace / "revision_memory.md").exists()
    if memory_missing:
        actions.append("refresh revision memory facts")
        if not dry_run:
            from .memory import write_revision_memory

            write_revision_memory(base)
            changed = True

    registry_path = config.workspace / "artifact_registry.json"
    if not registry_path.exists():
        actions.append("create missing artifact_registry.json")
        if not dry_run:
            write_artifact_registry(base)
            changed = True

    return {"dry_run": dry_run, "actions": actions, "changed": changed}

def render_migration_report(result: dict[str, object]) -> str:
    lines = ["# Migration Report", "", f"Dry run: {str(result['dry_run']).lower()}", ""]
    actions = result.get("actions", [])
    if actions:
        lines.append("Actions:")
        lines.extend(f"- {action}" for action in actions)
    else:
        lines.append("No migration actions required.")
    return "\n".join(lines) + "\n"

def status(base: Path) -> dict[str, object]:
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    candidates = load_candidates(config)
    counts = {
        "total": len(items),
        "proof": sum(1 for item in items if item.get("kind") == "proof"),
        "experiment": sum(1 for item in items if item.get("kind") == "experiment"),
        "manuscript": sum(1 for item in items if item.get("kind") == "manuscript"),
        "high_risk": sum(1 for item in items if item.get("risk") == "high"),
        "candidates": len(candidates),
        "approved_candidates": sum(1 for candidate in candidates if candidate.get("status") == "approved"),
        "applied_candidates": sum(1 for candidate in candidates if candidate.get("status") == "applied"),
    }
    for planning_status in sorted(PLANNING_STATUSES):
        counts[f"planning_{planning_status}"] = sum(1 for item in items if item.get("planning_status", "triaged") == planning_status)
    return {
        "workspace": str(config.workspace),
        "journal": config.journal,
        "tex_root": str(config.tex_root),
        "main_tex": config.main_tex,
        "counts": counts,
    }

def clean_workspace(base: Path) -> list[str]:
    config = load_config(base)
    removed = []
    for dirname in ("artifacts", "logs", "worker_snapshots", "worker_runtime", "evolution_patches"):
        target = config.workspace / dirname
        if target.exists():
            shutil.rmtree(target)
            removed.append(str(target))
        target.mkdir(exist_ok=True)
    return removed

def export_artifacts(base: Path) -> Path:
    config = load_config(base)
    from .provenance import write_revision_provenance

    write_revision_provenance(base)
    from .memory import write_revision_memory

    write_revision_memory(base)
    artifact_dir = config.workspace / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    exports = [
        "revision.yaml",
        "journal_profile.json",
        "review_items.json",
        "latex_index.json",
        "item_plans.json",
        "item_plans.md",
        "review_analyses.json",
        "review_analyses.md",
        "proof_workflows.json",
        "proof_workflows.md",
        "experiment_manifests.json",
        "experiment_manifests.md",
        "experiment_run_attempts.jsonl",
        "experiment_run_attempts.md",
        "agent_state.json",
        "agent_state.md",
        "agent_runs.jsonl",
        "agent_runs.md",
        "agent_policy.json",
        "agent_policy.md",
        "agent_report.md",
        "agent_dashboard.md",
        "agent_sessions.jsonl",
        "agent_sessions.md",
        "agent_decisions.json",
        "agent_decisions.md",
        "agent_eval_report.json",
        "agent_eval_report.md",
        "external_agent_runs.jsonl",
        "external_agent_runs.md",
        "monitor.md",
        "supervisor_plan.json",
        "supervisor_plan.md",
        "supervisor_runs.jsonl",
        "supervisor_runs.md",
        "supervisor_feedback.json",
        "supervisor_feedback.md",
        "supervisor_workers.json",
        "supervisor_workers.md",
        "supervisor_observations.jsonl",
        "supervisor_observations.md",
        "worker_runtime_events.jsonl",
        "worker_runtime_events.md",
        "worker_snapshots.json",
        "worker_snapshots.md",
        "worker_evaluations.jsonl",
        "worker_evaluations.md",
        "evolution_proposals.json",
        "evolution_proposals.md",
        "runtime.sqlite3",
        "review_evidence.json",
        "review_evidence.md",
        "review_evaluations.json",
        "review_evaluations.md",
        "review_workers.json",
        "review_workers.md",
        "review_conflicts.json",
        "review_conflicts.md",
        "experiment_authorizations.json",
        "experiment_authorizations.md",
        "service.json",
        "llm_drafts.json",
        "llm_drafts.md",
        "revision_provenance.json",
        "revision_provenance.md",
        "revision_memory.json",
        "revision_memory.md",
        "revision_readiness.json",
        "revision_readiness.md",
        "pre_submission_review.json",
        "pre_submission_review.md",
        "paper_manifest.json",
        "paper_manifest.md",
        "review_reports.json",
        "review_reports.md",
        "review_meta_report.json",
        "review_meta_report.md",
        "review_engine.json",
        "review_followups.json",
        "review_followups.md",
        "review_outputs.json",
        "review_outputs.md",
        "review_benchmark_report.json",
        "review_benchmark_report.md",
        "rebuttal_threads.json",
        "rebuttal_threads.md",
        "rebuttal_draft.md",
        "rebuttal_stress_test.json",
        "rebuttal_stress_test.md",
        "rebuttal_final.json",
        "artifact_registry.json",
        "revision_plan.md",
        "response_letter.md",
        "manuscript.patch",
        "candidate_edits.json",
        "apply_log.jsonl",
        "decision_log.md",
        "experiment_runs.jsonl",
        "proof_audit.md",
        "experiment_plan.md",
        "open_issues.md",
    ]
    lines = ["# Revision Export", ""]
    for name in exports:
        source = config.workspace / name
        if source.exists():
            target = artifact_dir / name
            target.write_bytes(source.read_bytes())
            lines.append(f"- `{name}`")
    write_text(artifact_dir / "MANIFEST.md", "\n".join(lines) + "\n")
    return artifact_dir

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ARTIFACT_REGISTRY_VERSION",
    "SCHEMA_FILES",
    "WORKSPACE",
    "Config",
    "clean_workspace",
    "artifact_registry_document",
    "artifact_registry_is_stale",
    "export_artifacts",
    "init_workspace",
    "load_config",
    "migrate_workspace",
    "read_json",
    "read_text",
    "render_migration_report",
    "schema_markdown",
    "status",
    "write_artifact_registry",
    "validate_workspace",
    "workspace_path",
    "write_json",
    "write_text",
]

def validate_workspace(base: Path, compile_check: bool = False) -> dict[str, object]:
    from .validation import validate_workspace as _validate_workspace

    return _validate_workspace(base, compile_check=compile_check)
