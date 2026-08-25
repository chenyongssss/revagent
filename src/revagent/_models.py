from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

WORKSPACE = ".revagent"
CURRENT_SCHEMA_VERSION = "33"
PLANNING_STATUSES = {"triaged", "planned", "drafted", "evidence_ready", "approved", "incorporated", "closed"}
EXPERIMENT_CONTRACT_STATUSES = {"not_planned", "planned", "artifact_recorded", "incorporated"}
SCHEMA_FILES = [
    "revision.yaml",
    "journal_profile.json",
    "review_items.json",
    "comment_import.json",
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
    "revision_plan.md",
    "response_letter.md",
    "proof_audit.md",
    "experiment_plan.md",
    "manuscript.patch",
    "candidate_edits.json",
    "decision_log.md",
]


@dataclass
class Config:
    journal: str
    tex_root: Path
    main_tex: str
    workspace: Path
    compile_command: str = "latexmk -pdf"
