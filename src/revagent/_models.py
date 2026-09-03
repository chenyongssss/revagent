from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

WORKSPACE = ".revagent"
CURRENT_SCHEMA_VERSION = "43"
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
    "rebuttal_threads.json",
    "rebuttal_threads.md",
    "rebuttal_draft.md",
    "rebuttal_stress_test.json",
    "rebuttal_stress_test.md",
    "rebuttal_final.json",
    "literature_consent.json",
    "literature_report.json",
    "literature_query_authorizations.json",
    "literature_citation_graph.json",
    "literature_retractions.json",
    "literature_alignments.json",
    "history_registry.json",
    "review_benchmark_report.json",
    "review_benchmark_report.md",
    "alignment_benchmark_report.json",
    "alignment_benchmark_report.md",
    "alignment_case_registry.json",
    "artifact_registry.json",
    "revision_plan.md",
    "response_letter.md",
    "proof_audit.md",
    "experiment_plan.md",
    "manuscript.patch",
    "candidate_edits.json",
    "decision_log.md",
]

# Registry schema versions are deliberately kept separate from the payloads:
# older append-only and list-shaped artifacts cannot safely gain a top-level
# version field without changing their on-disk contract. The registry is the
# compatibility authority for those legacy shapes.
ARTIFACT_SCHEMA_VERSIONS = {
    name: "1" for name in SCHEMA_FILES if name.endswith((".json", ".yaml"))
}
ARTIFACT_SCHEMA_VERSIONS.update({
    "revision.yaml": CURRENT_SCHEMA_VERSION,
    "review_items.json": "2",
    "latex_index.json": "2",
    "pre_submission_review.json": "2",
    "paper_manifest.json": "2",
    "artifact_registry.json": "2",
    "rebuttal_stress_test.json": "2",
    "rebuttal_final.json": "2",
    "literature_report.json": "2",
})


@dataclass
class Config:
    journal: str
    tex_root: Path
    main_tex: str
    workspace: Path
    compile_command: str = "latexmk -pdf"
