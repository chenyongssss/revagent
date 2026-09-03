from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import (
    agent_blockers,
    build_agent_state,
    complete_check_agent_session,
    dismiss_agent_decision,
    get_agent_decision,
    load_agent_sessions,
    plan_agent_session,
    refresh_agent_decisions,
    render_agent_blockers,
    render_agent_dashboard,
    render_agent_decisions,
    render_agent_eval_report,
    render_agent_next,
    render_agent_report,
    render_agent_sessions,
    render_agent_state,
    resolve_agent_decision,
    run_agent_eval,
    resume_agent_session,
    resume_agent_session_watch,
    run_agent_once,
    write_agent_dashboard,
    write_agent_report,
    write_agent_state,
)
from .candidates import (
    apply_approved_candidates,
    approve_candidate,
    candidate_summary,
    edit_candidate,
    inspect_record,
    propose_candidates,
    reject_candidate,
    render_apply_diff,
    restore_backup,
)
from .lanes import (
    close_item,
    experiment_artifact,
    experiment_contract,
    experiment_incorporate,
    experiment_plan_for_item,
    experiment_run_preview,
    experiment_run_record,
    plan_all_items,
    plan_item,
    proof_audit_for_item,
    proof_approve,
    proof_obligation,
    proof_record_revision_diff,
    proof_plan_for_item,
    reasoning_for_item,
    record_experiment_result,
    render_experiment_run_preview,
    render_item_plan,
    reopen_item,
)
from .llm import draft_all_with_llm, draft_item_with_llm, llm_accept, llm_check, llm_check_all, llm_edit, llm_reject, llm_review, render_llm_drafts
from .memory import memory_for_item
from .provenance import provenance_for_item
from .readiness import build_submit_pack_dry_run, render_revision_readiness, render_submit_pack_dry_run, write_revision_readiness
from .review_analysis import analyze_all_review_items, analyze_review_item, render_review_analyses, review_analysis_for_item
from .rendering import create_draft, incorporate_drafts
from .response_trace import render_response_trace, write_response_trace
from .reviews import create_plan, ingest_comments
from .privacy import privacy_scan
from .contributions import contribution_data_card_template, create_contribution_package
from .alignment_intake import adjudicate_alignment_case, annotate_alignment_case, export_alignment_fixture, initialize_alignment_case
from .cockpit import write_author_cockpit
from .pre_submission_review import build_pre_submission_review, load_pre_submission_review, pre_submission_review_is_stale, render_pre_submission_review
from .paper_ingestion import build_paper_manifest, render_paper_manifest
from .paper_evidence import bind_experiment_evidence, review_claim_dependency
from .pre_submission_engine import ROLES, authorize_followup, merge_role_reports, run_review_round, run_role_review
from .reviewer_packs import available_reviewer_packs
from .rebuttal import approve_rebuttal_atom, finalize_rebuttal, parse_rebuttal, rebuttal_draft, rebuttal_plan, rebuttal_stress_test, resubmit_rebuttal
from .literature import FETCH_PROVIDERS, PROVIDERS, authorize_literature_provider, authorize_literature_query, build_citation_graph, build_claim_literature_alignments, build_retraction_report, cache_literature_query, fetch_literature_provider, fetch_openalex, literature_provenance_report, literature_status, review_claim_literature_alignment
from .history import approve_history, delete_history, enforce_history_retention, export_history, import_history, rebuild_history_index, redact_history, search_history
from .history_intake import adjudicate_history_case, annotate_history_case, export_history_fixture, initialize_history_case, publish_history_quality
from .validation import doctor, validate_workspace
from .external_agent import (
    external_agent_run_artifact,
    get_external_agent_run,
    load_external_agent_runs,
    mark_external_agent_run,
    recover_external_agent_run,
    render_external_agent_run_detail,
    render_external_agent_runs,
    render_external_agent_supervision,
    render_monitor_report,
    run_external_agent,
    supervisor_observations_snapshot,
    write_dashboard_html,
    write_monitor_report,
)
from .evolution import (
    apply_evolution,
    approve_evolution,
    cancel_worker,
    create_worker_snapshot,
    evaluate_worker,
    get_proposal,
    latest_runtime_events,
    plan_evolution,
    refresh_worker,
    reject_evolution,
    render_evaluations,
    render_proposals,
    render_runtime_events,
    start_worker,
)
from .project_runtime import attach_cycle_actor_bundle, attach_cycle_plan, attach_cycle_review, author_decision_console, authorize_remote, create_cycle_reviewer_session, evaluate_review_item, initialize_project_runtime, open_revision_cycle, project_status, record_cycle_author_escalation, record_cycle_author_gate, record_cycle_author_waiver, recover_project_runtime, reopen_revision_cycle, revision_cycle_status, run_project_cycle, service_health, serve_project, set_project_paused, stop_project_service
from .review_workers import authorize_experiment, collect_review_worker, create_review_snapshot, plan_review_workers, run_authorized_experiment, start_review_worker
from .review_rubric import run_review_rubric
from .benchmark import assess_shadow_scores, generate_synthetic_catalog, record_shadow_expert_scores, register_shadow_benchmark, run_alignment_benchmark_suite, run_benchmark, run_history_benchmark_suite, run_review_benchmark_suite
from .supervisor import build_supervisor_feedback, build_supervisor_plan, build_supervisor_workers, get_supervisor_observations, observe_supervisor_workers, render_supervisor_feedback, render_supervisor_observations, render_supervisor_plan, render_supervisor_runs, render_supervisor_workers, run_supervisor_loop
from .workspace import (
    clean_workspace,
    export_artifacts,
    init_workspace,
    load_config,
    migrate_workspace,
    render_migration_report,
    schema_markdown,
    status,
    artifact_registry_is_stale,
    write_artifact_registry,
)
from .profiles import available_profiles, diff_rulepacks, initialize_rulepack, render_rulepack_diff, render_rulepack_validation, validate_rulepack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="revagent", description="Local revision workspace CLI for computational mathematics papers.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a local revision workspace.")
    init.add_argument("--journal", required=True, help="Built-in profile, journal_profiles/<name>/profile.yaml, or legacy journal_profiles/<name>.yaml.")
    init.add_argument("--tex-root", default=".")
    init.add_argument("--main-tex", default=None)

    ingest = sub.add_parser("ingest-comments", help="Parse reviewer/editor comments into tracked review items.")
    ingest.add_argument("comments_path")

    sub.add_parser("plan", help="Create revision, proof, experiment, and open-issue plans.")
    plan_item_parser = sub.add_parser("plan-item", help="Create a structured planner record for one item or all items.")
    plan_item_parser.add_argument("item_id", nargs="?")
    plan_item_parser.add_argument("--all", action="store_true", help="Plan every review item.")
    plan_item_parser.add_argument("--force", action="store_true", help="Regenerate plans for incorporated or closed items.")
    analyze = sub.add_parser("analyze-review", help="Create structured reviewer-intent analysis for one item or all items.")
    analyze.add_argument("item_id", nargs="?")
    analyze.add_argument("--all", action="store_true", help="Analyze every review item.")
    analyze.add_argument("--force", action="store_true", help="Regenerate existing review analyses.")
    review_analysis = sub.add_parser("review-analysis", help="Show structured reviewer-intent analysis.")
    review_analysis.add_argument("item_id", nargs="?")
    sub.add_parser("draft", help="Draft response letter and reviewable manuscript patch notes.")
    sub.add_parser("privacy-scan", help="Classify local project files and scan for credential candidates before any remote authorization.")
    contribution_template = sub.add_parser("contribution-template", help="Print a local-only case contribution data-card template.")
    contribution_template.add_argument("--case-id", required=True)
    contribution_export = sub.add_parser("contribution-export", help="Create a local metadata-only, human-review-required contribution candidate; never uploads source material.")
    contribution_export.add_argument("--case-dir", required=True)
    contribution_export.add_argument("--case-id", required=True)
    contribution_export.add_argument("--data-card", required=True)
    contribution_export.add_argument("--confirm", action="store_true", help="Confirm that you reviewed the data card and intend to create a local candidate package.")
    alignment_case = sub.add_parser("alignment-case", help="Manage local human-gated claim-alignment evaluation cases.")
    alignment_case_sub = alignment_case.add_subparsers(dest="alignment_case_command", required=True)
    alignment_init = alignment_case_sub.add_parser("init")
    alignment_init.add_argument("case_id")
    alignment_claim = alignment_init.add_mutually_exclusive_group(required=True)
    alignment_claim.add_argument("--claim"); alignment_claim.add_argument("--claim-file")
    alignment_init.add_argument("--candidates", required=True); alignment_init.add_argument("--data-card", required=True); alignment_init.add_argument("--confirm", action="store_true")
    alignment_annotate = alignment_case_sub.add_parser("annotate")
    alignment_annotate.add_argument("case_id"); alignment_annotate.add_argument("--annotator", required=True); alignment_annotate.add_argument("--relevant-work-id", action="append", required=True); alignment_annotate.add_argument("--note", required=True)
    alignment_adjudicate = alignment_case_sub.add_parser("adjudicate")
    alignment_adjudicate.add_argument("case_id"); alignment_adjudicate.add_argument("--adjudicator", required=True); alignment_adjudicate.add_argument("--relevant-work-id", action="append", required=True); alignment_adjudicate.add_argument("--note", required=True)
    alignment_export = alignment_case_sub.add_parser("export-fixture")
    alignment_export.add_argument("case_id"); alignment_export.add_argument("--suite", required=True)
    history_case = sub.add_parser("history-case", help="Manage authorized, deidentified real history evaluation cases.")
    history_case_sub = history_case.add_subparsers(dest="history_case_command", required=True)
    history_init = history_case_sub.add_parser("init"); history_init.add_argument("case_id"); history_init.add_argument("--query", required=True); history_init.add_argument("--corpus", required=True); history_init.add_argument("--data-card", required=True); history_init.add_argument("--confirm", action="store_true")
    history_annotate = history_case_sub.add_parser("annotate"); history_annotate.add_argument("case_id"); history_annotate.add_argument("--annotator", required=True); history_annotate.add_argument("--relevant-history-id", action="append", required=True); history_annotate.add_argument("--note", required=True)
    history_adjudicate = history_case_sub.add_parser("adjudicate"); history_adjudicate.add_argument("case_id"); history_adjudicate.add_argument("--adjudicator", required=True); history_adjudicate.add_argument("--relevant-history-id", action="append", required=True); history_adjudicate.add_argument("--note", required=True)
    history_fixture = history_case_sub.add_parser("export-fixture"); history_fixture.add_argument("case_id"); history_fixture.add_argument("--suite", required=True)
    cockpit = sub.add_parser("cockpit", help="Write the local bilingual author cockpit HTML evidence overview.")
    cockpit.add_argument("--lang", choices=["en", "zh"], default="en")
    review_paper = sub.add_parser("review-paper", help="Run a local deterministic advisory pre-submission review.")
    review_paper.add_argument("--journal", help="Optional directory rulepack or legacy flat journal profile override.")
    dependency_review = sub.add_parser("paper-dependency-review", help="Record a human semantic assessment of a structural claim dependency.")
    dependency_review.add_argument("claim_id"); dependency_review.add_argument("dependency_id"); dependency_review.add_argument("--reviewer", required=True); dependency_review.add_argument("--decision", choices=("supported", "unsupported", "uncertain"), required=True); dependency_review.add_argument("--note", required=True)
    evidence_bind = sub.add_parser("paper-experiment-bind", help="Hash-bind a recorded experiment artifact to a current paper claim.")
    evidence_bind.add_argument("claim_id"); evidence_bind.add_argument("item_id"); evidence_bind.add_argument("--artifact", required=True); evidence_bind.add_argument("--note", required=True)
    sub.add_parser("review-status", help="Show the latest local advisory pre-submission review.")
    sub.add_parser("paper-ingest", help="Create a versioned local source/PDF paper manifest.")
    review_role = sub.add_parser("review-role", help="Generate one role-scoped local advisory structural report.")
    review_role.add_argument("role", choices=ROLES)
    review_role.add_argument("--pack", choices=available_reviewer_packs(), default="numerical-pde")
    sub.add_parser("review-merge", help="Merge current role-scoped reports into an advisory risk matrix.")
    review_round = sub.add_parser("review-round", help="Run one bounded local advisory review round with an author pause.")
    review_round.add_argument("--mode", choices=["standard", "hard", "nightmare"], default="standard")
    review_round.add_argument("--pack", choices=available_reviewer_packs(), default="numerical-pde")
    sub.add_parser("reviewer-packs", help="List bundled computational-mathematics reviewer packs.")
    rebuttal = sub.add_parser("rebuttal", help="Create local, author-gated rebuttal thread artifacts.")
    rebuttal_sub = rebuttal.add_subparsers(dest="rebuttal_command", required=True)
    for name in ("parse", "plan", "draft", "stress-test"):
        rebuttal_sub.add_parser(name)
    rebuttal_finalize = rebuttal_sub.add_parser("finalize")
    rebuttal_finalize.add_argument("--approved", action="store_true")
    rebuttal_approve = rebuttal_sub.add_parser("approve")
    rebuttal_approve.add_argument("atom_id")
    rebuttal_approve.add_argument("--note", required=True)
    rebuttal_approve.add_argument("--manuscript-locator", required=True)
    rebuttal_approve.add_argument("--evidence", required=True)
    rebuttal_approve.add_argument("--response-file", help="Author-written response text for deterministic linting; defaults to --note.")
    rebuttal_resubmit = rebuttal_sub.add_parser("resubmit")
    rebuttal_resubmit.add_argument("--from", dest="source_journal", required=True)
    rebuttal_resubmit.add_argument("--to", dest="target_journal", required=True)
    literature = sub.add_parser("literature", help="Manage local-only literature provider consent.")
    literature_sub = literature.add_subparsers(dest="literature_command", required=True)
    literature_authorize = literature_sub.add_parser("authorize")
    literature_authorize.add_argument("provider", choices=PROVIDERS)
    literature_authorize.add_argument("--purpose", required=True)
    literature_cache = literature_sub.add_parser("cache")
    literature_cache.add_argument("provider", choices=PROVIDERS)
    literature_cache.add_argument("--query", required=True)
    literature_cache.add_argument("--response-file", required=True, help="Local JSON response saved from an approved provider interaction.")
    literature_sub.add_parser("report")
    literature_sub.add_parser("status")
    literature_sub.add_parser("graph", help="Build a provenance-preserving graph from permitted cached metadata.")
    literature_sub.add_parser("retractions", help="Build a conservative retraction-status report from permitted cached metadata.")
    literature_sub.add_parser("align", help="Generate local claim-to-literature candidates for author review.")
    literature_align_review = literature_sub.add_parser("align-review", help="Record an explicit author decision on one alignment candidate.")
    literature_align_review.add_argument("candidate_id")
    literature_align_review.add_argument("--decision", choices=("approve", "reject"), required=True)
    literature_align_review.add_argument("--relationship", choices=("supports", "contrasts", "background", "method", "unrelated"), default="unrelated")
    literature_align_review.add_argument("--note", required=True)
    literature_query = literature_sub.add_parser("authorize-query")
    literature_query.add_argument("provider", choices=PROVIDERS)
    literature_query.add_argument("--query", required=True)
    literature_query.add_argument("--purpose", required=True)
    literature_query.add_argument("--final-report-permission", action="store_true")
    literature_fetch = literature_sub.add_parser("fetch-openalex")
    literature_fetch.add_argument("--query", required=True)
    literature_fetch.add_argument("--authorization-id", required=True)
    literature_fetch.add_argument("--offline", action="store_true")
    literature_fetch_any = literature_sub.add_parser("fetch", help="Fetch metadata using a consent-gated provider connector.")
    literature_fetch_any.add_argument("provider", choices=FETCH_PROVIDERS)
    literature_fetch_any.add_argument("--query", required=True)
    literature_fetch_any.add_argument("--authorization-id", required=True)
    literature_fetch_any.add_argument("--offline", action="store_true")
    history = sub.add_parser("history", help="Manage local, consent-gated revision-history metadata.")
    history_sub = history.add_subparsers(dest="history_command", required=True)
    history_import = history_sub.add_parser("import")
    history_import.add_argument("path")
    history_import.add_argument("--purpose", required=True)
    history_approve = history_sub.add_parser("approve")
    history_approve.add_argument("history_id")
    history_redact = history_sub.add_parser("redact"); history_redact.add_argument("history_id"); history_redact.add_argument("--source-file", required=True); history_redact.add_argument("--retention", choices=("30_days", "project_lifetime", "until_deleted"), required=True)
    history_sub.add_parser("rebuild")
    history_sub.add_parser("enforce-retention")
    history_search = history_sub.add_parser("search"); history_search.add_argument("query"); history_search.add_argument("--limit", type=int, default=10)
    history_delete = history_sub.add_parser("delete"); history_delete.add_argument("history_id"); history_delete.add_argument("--confirm", action="store_true")
    history_export = history_sub.add_parser("export"); history_export.add_argument("target")
    review_authorize = sub.add_parser("review-followup-authorize", help="Authorize one bounded verification follow-up; this does not execute it.")
    review_authorize.add_argument("task_id")
    response_trace = sub.add_parser("response-trace", help="Build a local request-response-manuscript-evidence traceability report.")
    response_trace.add_argument("item_id", nargs="?")
    llm_draft = sub.add_parser("llm-draft", help="Generate offline LLM reviewer-intent and response drafts.")
    llm_draft.add_argument("item_id", nargs="?")
    llm_draft.add_argument("--all", action="store_true", help="Draft every review item.")
    llm_draft.add_argument("--force", action="store_true", help="Regenerate existing LLM drafts.")
    llm_draft.add_argument("--provider", default="fake", choices=["fake", "openai-compatible"], help="LLM provider to use.")
    llm_review_parser = sub.add_parser("llm-review", help="Show one LLM draft for author review.")
    llm_review_parser.add_argument("item_id")
    llm_accept_parser = sub.add_parser("llm-accept", help="Mark an LLM draft as author accepted.")
    llm_accept_parser.add_argument("item_id")
    llm_reject_parser = sub.add_parser("llm-reject", help="Reject an LLM draft with an author note.")
    llm_reject_parser.add_argument("item_id")
    llm_reject_parser.add_argument("--note", required=True)
    llm_edit_parser = sub.add_parser("llm-edit", help="Replace LLM draft response and/or candidate text from files.")
    llm_edit_parser.add_argument("item_id")
    llm_edit_parser.add_argument("--response-file")
    llm_edit_parser.add_argument("--candidate-file")
    llm_check_parser = sub.add_parser("llm-check", help="Run deterministic quality checks for LLM drafts.")
    llm_check_parser.add_argument("item_id", nargs="?")
    llm_check_parser.add_argument("--all", action="store_true", help="Check every LLM draft.")
    sub.add_parser("incorporate-drafts", help="Regenerate artifacts using accepted and quality-passed LLM drafts.")
    sub.add_parser("schema", help="Print workspace schema documentation.")
    artifact_registry = sub.add_parser("artifact-registry", help="Refresh or check the JSON/YAML artifact registry snapshot.")
    artifact_registry.add_argument("--check", action="store_true", help="Check registry freshness without writing it.")
    migrate = sub.add_parser("migrate", help="Inspect or apply non-destructive workspace schema migrations.")
    migrate_mode = migrate.add_mutually_exclusive_group()
    migrate_mode.add_argument("--dry-run", action="store_true", help="Show migration actions without changing files.")
    migrate_mode.add_argument("--apply", action="store_true", help="Apply safe field/file backfills.")
    proof_audit = sub.add_parser("proof-audit", help="Show proof dependency and approval context.")
    proof_audit.add_argument("item_id", nargs="?")
    proof_plan = sub.add_parser("proof-plan", help="Create a structured proof workflow for a proof item.")
    proof_plan.add_argument("item_id")
    proof_ob = sub.add_parser("proof-obligation", help="Add a proof obligation to a proof workflow.")
    proof_ob.add_argument("item_id")
    proof_ob.add_argument("--add", required=True, help="Proof obligation text to add.")
    proof_diff = sub.add_parser("proof-diff", help="Record an author-supplied post-revision proof snapshot for audit.")
    proof_diff.add_argument("item_id")
    proof_diff.add_argument("--after-file", required=True)
    proof_approval = sub.add_parser("proof-approve", help="Record author approval for a proof workflow.")
    proof_approval.add_argument("item_id")
    proof_approval.add_argument("--note", required=True)
    experiment_plan = sub.add_parser("experiment-plan", help="Show experiment command/provenance plan.")
    experiment_plan.add_argument("item_id", nargs="?")
    experiment_contract_parser = sub.add_parser("experiment-contract", help="Create a reproducibility contract for an experiment item.")
    experiment_contract_parser.add_argument("item_id")
    experiment_artifact_parser = sub.add_parser("experiment-artifact", help="Record an experiment artifact and sha256 hash.")
    experiment_artifact_parser.add_argument("item_id")
    experiment_artifact_parser.add_argument("--path", required=True)
    experiment_artifact_parser.add_argument("--kind", required=True, choices=["table", "figure", "log", "data"])
    experiment_artifact_parser.add_argument("--note", required=True)
    experiment_incorporate_parser = sub.add_parser("experiment-incorporate", help="Record how an experiment result is incorporated into the paper.")
    experiment_incorporate_parser.add_argument("item_id")
    experiment_incorporate_parser.add_argument("--target", required=True)
    experiment_incorporate_parser.add_argument("--field", required=True)
    experiment_incorporate_parser.add_argument("--text-file", required=True)
    experiment_run_parser = sub.add_parser("experiment-run", help="Preview or record a local experiment command from the manifest.")
    experiment_run_parser.add_argument("item_id")
    experiment_run_mode = experiment_run_parser.add_mutually_exclusive_group(required=True)
    experiment_run_mode.add_argument("--dry-run", action="store_true", help="Show command, cwd, logs, and expected artifact status without executing.")
    experiment_run_mode.add_argument("--record", action="store_true", help="Execute the manifest command and record logs and detected artifact hashes.")
    record = sub.add_parser("record-result", help="Record author-confirmed experiment result provenance.")
    record.add_argument("item_id")
    record.add_argument("--artifact", required=True)
    record.add_argument("--note", required=True)
    reason = sub.add_parser("reason", help="Explain revision rationale for a review item.")
    reason.add_argument("item_id")
    propose = sub.add_parser("propose", help="Generate candidate manuscript edits.")
    propose.add_argument("--force", action="store_true", help="Regenerate non-edited candidate edits.")
    inspect = sub.add_parser("inspect", help="Inspect a review item or candidate edit.")
    inspect.add_argument("record_id")
    edit = sub.add_parser("edit-candidate", help="Replace candidate content with author-provided TeX text.")
    edit.add_argument("candidate_id")
    edit.add_argument("--text-file", required=True)
    approve = sub.add_parser("approve", help="Approve a candidate edit for application.")
    approve.add_argument("candidate_id")
    approve.add_argument("--allow-high-risk", action="store_true")
    reject = sub.add_parser("reject", help="Reject a candidate edit.")
    reject.add_argument("candidate_id")
    close = sub.add_parser("close-item", help="Close an incorporated or fully resolved review item.")
    close.add_argument("item_id")
    reopen = sub.add_parser("reopen-item", help="Reopen a closed review item for planning.")
    reopen.add_argument("item_id")
    apply = sub.add_parser("apply", help="Dry-run or apply approved candidate edits.")
    apply.add_argument("--dry-run", action="store_true", help="Print the approved candidate diff without writing files.")
    apply.add_argument("--approved", action="store_true", help="Apply approved candidate edits to manuscript files.")
    restore = sub.add_parser("restore", help="Restore TeX files from a RevAgent backup directory.")
    restore.add_argument("--backup", required=True)
    validate = sub.add_parser("validate", help="Validate workspace schema and LaTeX references.")
    validate.add_argument("--compile", action="store_true", help="Run the configured LaTeX compile command if available.")
    provenance = sub.add_parser("provenance", help="Generate and show revision provenance.")
    provenance.add_argument("item_id", nargs="?")
    memory = sub.add_parser("memory", help="Generate and show durable revision memory facts.")
    memory.add_argument("item_id", nargs="?")
    readiness = sub.add_parser("readiness", help="Generate and show revision readiness.")
    readiness.add_argument("item_id", nargs="?")
    submit_pack = sub.add_parser("submit-pack", help="Inspect final submission package readiness.")
    submit_pack.add_argument("--dry-run", action="store_true", help="Show missing submission package pieces without writing final artifacts.")
    sub.add_parser("status", help="Print workspace item counts and configuration.")
    project_init = sub.add_parser("project-init", help="Import review items into the persistent project runtime.")
    project_status_parser = sub.add_parser("project-status", help="Show durable review-project task state.")
    sub.add_parser("project-pause", help="Pause local project scheduling without changing review item gates.")
    sub.add_parser("project-resume", help="Resume local project scheduling.")
    sub.add_parser("project-stop", help="Request that a running local project service stop after its current request.")
    sub.add_parser("project-recover", help="Reconcile expired project task leases after service interruption.")
    sub.add_parser("service-health", help="Check persistent runtime and discovered local service health.")
    project_cycle = sub.add_parser("project-cycle", help="Run one bounded local reversible project scheduling cycle.")
    project_cycle.add_argument("--workers", type=int, default=2)
    cycle_open = sub.add_parser("cycle-open", help="Open an auditable planner/actor/reviewer revision cycle.")
    cycle_open.add_argument("item_id")
    cycle_open.add_argument("--planner-id", required=True)
    cycle_plan = sub.add_parser("cycle-plan", help="Freeze a planner specification in an open revision cycle.")
    cycle_plan.add_argument("cycle_id")
    cycle_plan.add_argument("--plan-file", required=True)
    cycle_act = sub.add_parser("cycle-act", help="Attach actor evidence only; this never edits the manuscript.")
    cycle_act.add_argument("cycle_id")
    cycle_act.add_argument("--actor-id", required=True)
    cycle_act.add_argument("--bundle-file", required=True)
    cycle_review = sub.add_parser("cycle-review", help="Attach an independent reviewer verdict to actor evidence.")
    cycle_review.add_argument("cycle_id")
    cycle_review.add_argument("--reviewer-id", required=True)
    cycle_review.add_argument("--review-file", required=True)
    cycle_session = sub.add_parser("cycle-review-session", help="Freeze planner and actor inputs for one independent reviewer.")
    cycle_session.add_argument("cycle_id")
    cycle_session.add_argument("--reviewer-id", required=True)
    cycle_gate = sub.add_parser("cycle-author-gate", help="Record the explicit author decision after independent review.")
    cycle_gate.add_argument("cycle_id")
    cycle_gate.add_argument("--author-id", required=True)
    cycle_gate.add_argument("--decision", required=True, choices=["approve", "reject"])
    cycle_gate.add_argument("--note", required=True)
    cycle_waive = sub.add_parser("cycle-author-waive", help="Record a non-blocking low-risk finding waiver without resolving the cycle.")
    cycle_waive.add_argument("cycle_id")
    cycle_waive.add_argument("--author-id", required=True)
    cycle_waive.add_argument("--finding-id", required=True)
    cycle_waive.add_argument("--note", required=True)
    cycle_escalate = sub.add_parser("cycle-author-escalate", help="Record an author/expert escalation and block the cycle.")
    cycle_escalate.add_argument("cycle_id")
    cycle_escalate.add_argument("--author-id", required=True)
    cycle_escalate.add_argument("--note", required=True)
    cycle_reopen = sub.add_parser("cycle-reopen", help="Open a new recorded round after a returned review cycle.")
    cycle_reopen.add_argument("cycle_id")
    cycle_reopen.add_argument("--note", required=True)
    cycle_status = sub.add_parser("cycle-status", help="Show revision-cycle artifacts and append-only events.")
    cycle_status.add_argument("cycle_id", nargs="?")
    sub.add_parser("author-console", help="Show pending cycle author decisions and their bound evidence hashes.")
    serve = sub.add_parser("serve", help="Run the loopback-only local review project service.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--workers", type=int, default=2)
    serve.add_argument("--once", action="store_true", help="Initialize and run one cycle without starting the HTTP server.")
    authorize = sub.add_parser("authorize-remote", help="Record one task-scoped remote model or retrieval authorization.")
    authorize.add_argument("task_id")
    authorize.add_argument("--provider", required=True)
    authorize.add_argument("--model", required=True)
    authorize.add_argument("--purpose", required=True)
    authorize.add_argument("--artifact-class", action="append", required=True)
    authorize.add_argument("--ttl-minutes", type=int, default=30)
    review_evaluate = sub.add_parser("review-evaluate", help="Evaluate deterministic evidence readiness for one review item.")
    review_evaluate.add_argument("item_id")
    rubric = sub.add_parser("review-rubric", help="Run one consent-gated semantic review rubric.")
    rubric.add_argument("item_id")
    rubric.add_argument("--authorization", type=int, required=True)
    worker_plan = sub.add_parser("worker-plan", help="Create role-specific isolated review workers for one item.")
    worker_plan.add_argument("item_id")
    worker_plan.add_argument("--backend", default="codex", choices=["codex", "openai-compatible"])
    worker_snapshot = sub.add_parser("review-sandbox-create", help="Create a complete isolated project snapshot for a review worker.")
    worker_snapshot.add_argument("worker_id")
    worker_start = sub.add_parser("review-worker-start", help="Start one prepared Codex review worker in its snapshot.")
    worker_start.add_argument("worker_id")
    worker_collect = sub.add_parser("review-worker-collect", help="Collect an exited review worker result bundle and conflicts.")
    worker_collect.add_argument("worker_id")
    experiment_authorize = sub.add_parser("experiment-authorize-worker", help="Authorize one sandboxed experiment worker command and resource budget.")
    experiment_authorize.add_argument("worker_id")
    experiment_authorize.add_argument("--command", dest="experiment_command", required=True)
    experiment_authorize.add_argument("--cwd", default=".")
    experiment_authorize.add_argument("--timeout-seconds", type=int, required=True)
    experiment_authorize.add_argument("--cpu", type=int, required=True)
    experiment_authorize.add_argument("--memory-mb", type=int, required=True)
    experiment_authorize.add_argument("--artifact", action="append", default=[])
    experiment_start = sub.add_parser("experiment-start-worker", help="Run one explicitly authorized sandboxed experiment.")
    experiment_start.add_argument("authorization_id")
    benchmark_run = sub.add_parser("benchmark-run", help="Run a deterministic synthetic or licensed benchmark fixture.")
    benchmark_run.add_argument("--fixture", required=True)
    benchmark_review = sub.add_parser("benchmark-review-suite", help="Measure reviewer roles and packs against adjudicated local labels.")
    benchmark_review.add_argument("--suite", required=True)
    benchmark_alignment = sub.add_parser("benchmark-alignment-suite", help="Measure claim-title retrieval against adjudicated local labels.")
    benchmark_alignment.add_argument("--suite", required=True)
    benchmark_history = sub.add_parser("benchmark-history-suite", help="Measure local history retrieval against adjudicated labels.")
    benchmark_history.add_argument("--suite", required=True)
    history_publish = sub.add_parser("history-quality-publish", help="Publish measured quality only for authorized real history cases.")
    history_publish.add_argument("--suite", required=True)
    benchmark_catalog = sub.add_parser("benchmark-synthetic-catalog", help="Generate a text-free local catalog of at least 200 synthetic evaluation fixtures.")
    benchmark_catalog.add_argument("--count", type=int, default=200)
    benchmark_shadow = sub.add_parser("benchmark-shadow", help="Register a local-only historical shadow benchmark without copying source text.")
    benchmark_shadow.add_argument("--case-dir", required=True)
    benchmark_shadow.add_argument("--case-id", required=True)
    benchmark_score = sub.add_parser("benchmark-shadow-score", help="Record one pseudonymous expert scorecard for a shadow benchmark.")
    benchmark_score.add_argument("--case-id", required=True)
    benchmark_score.add_argument("--expert-id", required=True)
    benchmark_score.add_argument("--scores-json", required=True)
    benchmark_assess = sub.add_parser("benchmark-shadow-assess", help="Fail closed against Phase 39 aggregate score thresholds.")
    benchmark_assess.add_argument("--scorecards-json", required=True)
    sub.add_parser("agent-status", help="Build and print the safe-auto agent task queue.")
    sub.add_parser("monitor", help="Refresh state and print the recovery monitor.")
    sub.add_parser("dashboard", help="Write the static HTML agent dashboard.")
    external_run = sub.add_parser("run", help="Launch an external agent runner.")
    external_run.add_argument("--goal", default="", help="Goal prompt for the external agent.")
    external_run.add_argument("--backend", default="codex", choices=["codex"], help="External agent backend.")
    external_run.add_argument("--dry-run", action="store_true", help="Write and print the prompt without launching the backend.")
    external_run.add_argument("--detach", action="store_true", help="Queue a launch script instead of running the backend immediately.")
    external_run.add_argument("--limit", type=int, default=None, help="Task limit hint included in the generated prompt.")
    external_run.add_argument("--dangerous-autonomy", action="store_true", help="Allow prompt instructions for broader autonomy; still records the run.")
    run_status = sub.add_parser("run-status", help="Show external agent run history or one run.")
    run_status.add_argument("run_id", nargs="?")
    run_recover = sub.add_parser("run-recover", help="Recover a failed or interrupted external agent run.")
    run_recover.add_argument("run_id", nargs="?")
    run_recover.add_argument("--dry-run", action="store_true", help="Regenerate the recovery prompt without launching the backend.")
    run_mark = sub.add_parser("run-mark", help="Manually mark an external agent run done, failed, or canceled.")
    run_mark.add_argument("run_id")
    run_mark.add_argument("--status", required=True, choices=["done", "failed", "canceled"])
    run_mark.add_argument("--note", default="")
    run_log = sub.add_parser("run-log", help="Print an external agent run artifact.")
    run_log.add_argument("run_id")
    run_log.add_argument("--artifact", default="stdout", choices=["prompt", "stdout", "stderr", "launch"])
    run_supervise = sub.add_parser("run-supervise", help="Summarize external-run health with persisted worker observations.")
    run_supervise.add_argument("run_id", nargs="?")
    run_start = sub.add_parser("run-start", help="Explicitly start a queued, snapshot-isolated external worker.")
    run_start.add_argument("run_id")
    run_refresh = sub.add_parser("run-refresh", help="Refresh explicit worker runtime state from its completion manifest.")
    run_refresh.add_argument("run_id")
    run_cancel = sub.add_parser("run-cancel", help="Terminate an explicitly started worker and record cancellation.")
    run_cancel.add_argument("run_id")
    run_cancel.add_argument("--note", required=True)
    worker_snapshot = sub.add_parser("worker-snapshot", help="Create an isolated source snapshot for a queued worker.")
    worker_snapshot.add_argument("run_id")
    worker_evaluate = sub.add_parser("worker-evaluate", help="Evaluate a completed isolated worker explicitly.")
    worker_evaluate.add_argument("run_id")
    sub.add_parser("evolution-plan", help="Create manual-gated source evolution proposals from passed worker evaluations.")
    evolution_review = sub.add_parser("evolution-review", help="Inspect one source evolution proposal.")
    evolution_review.add_argument("proposal_id")
    evolution_approve = sub.add_parser("evolution-approve", help="Approve a passed source evolution proposal without applying it.")
    evolution_approve.add_argument("proposal_id")
    evolution_approve.add_argument("--note", required=True)
    evolution_reject = sub.add_parser("evolution-reject", help="Reject a source evolution proposal.")
    evolution_reject.add_argument("proposal_id")
    evolution_reject.add_argument("--note", required=True)
    evolution_apply = sub.add_parser("evolution-apply", help="Apply an approved, current source evolution proposal.")
    evolution_apply.add_argument("proposal_id")
    evolution_apply.add_argument("--approved", action="store_true")
    agent_plan = sub.add_parser("agent-plan", help="Create a goal-oriented agent session plan.")
    agent_plan.add_argument("--goal", required=True, choices=["rebuttal-draft", "proof-response", "experiment-response", "full-revision-pass"])
    sub.add_parser("agent-session", help="Show recorded goal-oriented agent sessions.")
    agent_resume = sub.add_parser("agent-resume", help="Resume the current goal-oriented agent session.")
    agent_resume.add_argument("--limit", type=int, default=None)
    agent_resume.add_argument("--retry-failed", action="store_true")
    agent_resume.add_argument("--watch", action="store_true", help="Keep resuming until the session blocks, fails, completes, or --cycles is reached.")
    agent_resume.add_argument("--interval", type=float, default=5.0, help="Seconds between watch cycles.")
    agent_resume.add_argument("--cycles", type=int, default=None, help="Maximum watch cycles.")
    sub.add_parser("agent-blockers", help="Show current manual gates and failed tasks.")
    sub.add_parser("agent-complete-check", help="Refresh the current session completion status.")
    sub.add_parser("agent-decisions", help="Refresh and show the manual decision queue.")
    agent_decision = sub.add_parser("agent-decision", help="Show one manual decision.")
    agent_decision.add_argument("decision_id")
    agent_resolve = sub.add_parser("agent-decision-resolve", help="Mark a decision resolved after its underlying gate is complete.")
    agent_resolve.add_argument("decision_id")
    agent_resolve.add_argument("--note", required=True)
    agent_dismiss = sub.add_parser("agent-decision-dismiss", help="Dismiss a decision with an author note.")
    agent_dismiss.add_argument("decision_id")
    agent_dismiss.add_argument("--note", required=True)
    agent_eval = sub.add_parser("agent-eval", help="Run deterministic agent trajectory eval fixtures.")
    eval_mode = agent_eval.add_mutually_exclusive_group()
    eval_mode.add_argument("--fixture", choices=["full-revision", "stale-input", "safety-gates"])
    eval_mode.add_argument("--all", action="store_true", help="Run every built-in eval fixture.")
    sub.add_parser("agent-next", help="Show the next safe task or blocking manual gate.")
    sub.add_parser("agent-report", help="Write and print the agent scheduler, stale-input, and manual-gate report.")
    supervisor_plan = sub.add_parser("supervisor-plan", help="Generate the next conservative supervisor plan.")
    supervisor_plan.add_argument("--update-plan", action="store_true", help="Append the Phase 8 roadmap section to plan.md if missing.")
    supervisor_loop = sub.add_parser("supervisor-loop", help="Run the conservative supervisor loop over safe internal tasks.")
    supervisor_loop.add_argument("--cycles", type=int, default=1)
    supervisor_loop.add_argument("--dry-run", action="store_true")
    supervisor_loop.add_argument("--update-plan", action="store_true", help="Append the Phase 8 roadmap section to plan.md if missing.")
    supervisor_feedback = sub.add_parser("supervisor-feedback", help="Generate read-only supervisor strategy feedback.")
    supervisor_feedback.add_argument("--update-plan", action="store_true", help="Append the Phase 9 roadmap section to plan.md if missing.")
    supervisor_workers = sub.add_parser("supervisor-workers", help="Create conservative external worker prompt assignments.")
    supervisor_workers.add_argument("--workers", type=int, default=2)
    supervisor_workers.add_argument("--queue", action="store_true", help="Queue external worker launch scripts without starting them.")
    supervisor_workers.add_argument("--update-plan", action="store_true", help="Append the Phase 10 roadmap section to plan.md if missing.")
    supervisor_observe = sub.add_parser("supervisor-observe", help="Record read-only observations for queued external workers.")
    supervisor_observe.add_argument("run_id", nargs="?")
    supervisor_observe.add_argument("--update-plan", action="store_true", help="Append the Phase 11 roadmap section to plan.md if missing.")
    supervisor_observation = sub.add_parser("supervisor-observation", help="Show recorded read-only worker observations.")
    supervisor_observation.add_argument("run_id", nargs="?")
    supervisor_observation.add_argument("--update-plan", action="store_true", help="Append the Phase 12 roadmap section to plan.md if missing.")
    agent_run = sub.add_parser("agent-run", help="Execute safe-auto agent tasks.")
    agent_run.add_argument("--limit", type=int, default=None, help="Maximum number of safe pending tasks to execute.")
    agent_run.add_argument("--until-blocked", action="store_true", help="Run safe tasks until only blocked/manual work remains.")
    agent_run.add_argument("--retry-failed", action="store_true", help="Retry failed safe tasks with unchanged inputs.")
    agent_run.add_argument("--max-failures", type=int, default=None, help="Stop after this many failed safe tasks.")
    sub.add_parser("doctor", help="Check local environment and profile availability.")
    sub.add_parser("clean", help="Remove generated logs and exported artifacts, preserving source workspace files.")
    sub.add_parser("export", help="Copy final artifacts into .revagent/artifacts.")
    profiles = sub.add_parser("profiles", help="List built-in and local journal profiles.")
    profiles.add_argument("--base", default=".", help="Project directory to scan for journal_profiles directory rulepacks and legacy *.yaml files.")
    journal = sub.add_parser("journal", help="Inspect local journal rulepacks without contacting external services.")
    journal_sub = journal.add_subparsers(dest="journal_command", required=True)
    journal_list = journal_sub.add_parser("list", help="List built-in, directory, and legacy local journal profiles.")
    journal_list.add_argument("--base", default=".")
    journal_validate = journal_sub.add_parser("validate", help="Validate one journal rulepack's local provenance metadata.")
    journal_validate.add_argument("name")
    journal_validate.add_argument("--base", default=".")
    journal_init = journal_sub.add_parser("init", help="Create an unconfirmed directory-v1 rulepack template.")
    journal_init.add_argument("name")
    journal_init.add_argument("--base", default=".")
    journal_diff = journal_sub.add_parser("diff", help="Compare two local journal rulepacks without fetching sources.")
    journal_diff.add_argument("left")
    journal_diff.add_argument("right")
    journal_diff.add_argument("--base", default=".")
    return parser


def print_check_result(result: dict[str, object]) -> None:
    for check in result["checks"]:
        marker = "ok" if check["ok"] else "fail"
        print(f"{marker:4} {check['name']}: {check['detail']}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    base = Path.cwd()

    if args.command == "init":
        ws = init_workspace(base, args.journal, args.tex_root, args.main_tex)
        print(f"Initialized revision workspace at {ws}")
        return 0
    if args.command == "ingest-comments":
        count = ingest_comments(base, args.comments_path)
        print(f"Ingested {count} review items")
        return 0
    if args.command == "plan":
        create_plan(base)
        print("Wrote revision_plan.md, proof_audit.md, experiment_plan.md, latex_index.json, and open_issues.md")
        return 0
    if args.command == "plan-item":
        try:
            if args.all:
                plans = plan_all_items(base, force=args.force)
                print(f"Planned {len(plans)} items")
                return 0
            if not args.item_id:
                print("error: provide an item id or --all")
                return 1
            print(render_item_plan(plan_item(base, args.item_id, force=args.force)))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "analyze-review":
        try:
            if args.all:
                analyses = analyze_all_review_items(base, force=args.force)
                print(render_review_analyses(analyses), end="")
                return 0
            if not args.item_id:
                print("error: provide an item id or --all")
                return 1
            analysis = analyze_review_item(base, args.item_id, force=args.force)
            print(render_review_analyses({analysis["item_id"]: analysis}), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "review-analysis":
        try:
            print(review_analysis_for_item(base, args.item_id), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "draft":
        create_draft(base)
        print("Wrote response_letter.md, manuscript.patch, and candidate_edits.json")
        return 0
    if args.command == "llm-draft":
        try:
            if args.all:
                print(render_llm_drafts(draft_all_with_llm(base, provider=args.provider, force=args.force)), end="")
                return 0
            if not args.item_id:
                print("error: provide an item id or --all")
                return 1
            draft = draft_item_with_llm(base, args.item_id, provider=args.provider, force=args.force)
            print(render_llm_drafts({draft["item_id"]: draft}), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "llm-review":
        try:
            print(llm_review(base, args.item_id), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "llm-accept":
        try:
            draft = llm_accept(base, args.item_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Accepted LLM draft {draft['item_id']}")
        return 0
    if args.command == "llm-reject":
        try:
            draft = llm_reject(base, args.item_id, args.note)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Rejected LLM draft {draft['item_id']}")
        return 0
    if args.command == "llm-edit":
        try:
            draft = llm_edit(base, args.item_id, response_file=args.response_file, candidate_file=args.candidate_file)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Edited LLM draft {draft['item_id']}")
        return 0
    if args.command == "llm-check":
        try:
            if args.all:
                print(render_llm_drafts(llm_check_all(base)), end="")
                return 0
            if not args.item_id:
                print("error: provide an item id or --all")
                return 1
            draft = llm_check(base, args.item_id)
            print(render_llm_drafts({draft["item_id"]: draft}), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "incorporate-drafts":
        result = incorporate_drafts(base)
        print(f"Incorporated {len(result['eligible'])} eligible LLM drafts")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
        return 0
    if args.command == "schema":
        print(schema_markdown())
        return 0
    if args.command == "artifact-registry":
        if args.check:
            if artifact_registry_is_stale(base):
                print("Artifact registry is stale. Run: revagent artifact-registry")
                return 1
            print("Artifact registry is current.")
            return 0
        registry = write_artifact_registry(base)
        print(f"Recorded {len(registry['artifacts'])} JSON/YAML artifact(s) in .revagent/artifact_registry.json")
        return 0
    if args.command == "migrate":
        dry_run = not args.apply
        print(render_migration_report(migrate_workspace(base, dry_run=dry_run)))
        return 0
    if args.command == "proof-audit":
        try:
            print(proof_audit_for_item(base, args.item_id))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "response-trace":
        trace = write_response_trace(base)
        try:
            print(render_response_trace(trace, args.item_id), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "privacy-scan":
        print(json.dumps(privacy_scan(base), ensure_ascii=False, indent=2))
        return 0
    if args.command == "contribution-template":
        print(json.dumps(contribution_data_card_template(args.case_id), ensure_ascii=False, indent=2))
        return 0
    if args.command == "contribution-export":
        try:
            print(create_contribution_package(base, Path(args.case_dir), args.case_id, Path(args.data_card), confirmed=args.confirm))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "alignment-case":
        try:
            if args.alignment_case_command == "init":
                claim = Path(args.claim_file).read_text(encoding="utf-8") if args.claim_file else args.claim
                result = initialize_alignment_case(base, args.case_id, claim, Path(args.candidates), Path(args.data_card), args.confirm)
                print(f"Alignment case {result['case_id']}: {result['status']}")
            elif args.alignment_case_command == "annotate":
                result = annotate_alignment_case(base, args.case_id, args.annotator, args.relevant_work_id, args.note)
                print(f"Recorded annotation from {result['annotator_id']}")
            elif args.alignment_case_command == "adjudicate":
                result = adjudicate_alignment_case(base, args.case_id, args.adjudicator, args.relevant_work_id, args.note)
                print(f"Alignment case {result['case_id']}: adjudicated")
            else:
                print(export_alignment_fixture(base, args.case_id, Path(args.suite)))
        except (ValueError, OSError) as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "history-case":
        try:
            if args.history_case_command == "init": result = initialize_history_case(base, args.case_id, args.query, Path(args.corpus), Path(args.data_card), args.confirm); print(f"History case {result['case_id']}: {result['status']}")
            elif args.history_case_command == "annotate": result = annotate_history_case(base, args.case_id, args.annotator, args.relevant_history_id, args.note); print(f"Recorded annotation from {result['annotator_id']}")
            elif args.history_case_command == "adjudicate": result = adjudicate_history_case(base, args.case_id, args.adjudicator, args.relevant_history_id, args.note); print(f"History case {result['case_id']}: adjudicated")
            else: print(export_history_fixture(base, args.case_id, Path(args.suite)))
        except (ValueError, OSError) as exc:
            print(f"error: {exc}"); return 1
        return 0
    if args.command == "cockpit":
        print(write_author_cockpit(base, args.lang))
        return 0
    if args.command == "review-paper":
        try:
            print(render_pre_submission_review(build_pre_submission_review(base, args.journal)), end="")
        except (OSError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "review-status":
        try:
            report = load_pre_submission_review(base)
        except (OSError, json.JSONDecodeError):
            print("error: pre-submission review report is invalid; run: revagent review-paper")
            return 1
        if not report or report.get("status") == "not_run":
            print("No pre-submission review run yet. Run: revagent review-paper")
            return 1
        try:
            print(render_pre_submission_review(report), end="")
        except (KeyError, TypeError):
            print("error: pre-submission review report is invalid; run: revagent review-paper")
            return 1
        if pre_submission_review_is_stale(base, report):
            print("warning: pre-submission review is stale; run: revagent review-paper")
            return 1
        if report.get("journal_specific_status") == "blocked":
            print("warning: journal-specific reporting is blocked; run: revagent journal validate " + str((report.get("journal") or {}).get("key", "")))
            return 1
        return 0
    if args.command == "paper-ingest":
        try:
            print(render_paper_manifest(build_paper_manifest(base)), end="")
        except OSError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "paper-dependency-review":
        try: record = review_claim_dependency(base, args.claim_id, args.dependency_id, args.reviewer, args.decision, args.note)
        except ValueError as exc: print(f"error: {exc}"); return 1
        print(f"Reviewed {record['claim_id']} dependency on {record['dependency_id']}: {record['decision']}"); return 0
    if args.command == "paper-experiment-bind":
        try: record = bind_experiment_evidence(base, args.claim_id, args.item_id, args.artifact, args.note)
        except ValueError as exc: print(f"error: {exc}"); return 1
        print(f"Bound {record['artifact_path']} to {record['claim_id']}"); return 0
    if args.command == "review-role":
        report = run_role_review(base, args.role, args.pack)
        print(f"Generated {report['role']} report with {len(report['issues'])} advisory issue(s)")
        return 0
    if args.command == "review-merge":
        result = merge_role_reports(base)
        print(f"Merged role reports: {result['status']}")
        return 0 if result["status"] == "advisory_merged" else 1
    if args.command == "review-round":
        try:
            result = run_review_round(base, args.mode, args.pack)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Completed advisory review round {result['round']['round']}; author pause required")
        return 0
    if args.command == "reviewer-packs":
        print("\n".join(available_reviewer_packs()))
        return 0
    if args.command == "rebuttal":
        if args.rebuttal_command == "parse":
            result = parse_rebuttal(base)
            print(f"Parsed {len(result['threads'])} rebuttal thread(s)")
        elif args.rebuttal_command == "plan":
            rebuttal_plan(base)
            print("Planned rebuttal atoms")
        elif args.rebuttal_command == "draft":
            print(rebuttal_draft(base), end="")
        elif args.rebuttal_command == "stress-test":
            result = rebuttal_stress_test(base)
            print("Rebuttal stress test: " + ("ready" if result["ok"] else "author review required"))
        elif args.rebuttal_command == "approve":
            try:
                response_text = Path(args.response_file).read_text(encoding="utf-8") if args.response_file else ""
                approve_rebuttal_atom(base, args.atom_id, args.note, args.manuscript_locator, args.evidence, response_text)
            except (OSError, ValueError) as exc:
                print(f"error: {exc}")
                return 1
            print(f"Approved rebuttal atom {args.atom_id}")
        elif args.rebuttal_command == "finalize":
            try:
                finalize_rebuttal(base, args.approved)
            except ValueError as exc:
                print(f"error: {exc}")
                return 1
            print("Finalized author-approved rebuttal")
        else:
            try:
                result = resubmit_rebuttal(base, args.source_journal, args.target_journal)
            except ValueError as exc:
                print(f"error: {exc}")
                return 1
            print(f"Created isolated resubmission record for {result['to_journal']}")
        return 0
    if args.command == "literature":
        if args.literature_command == "authorize":
            record = authorize_literature_provider(base, args.provider, args.purpose)
            print(f"Recorded provider consent for {record['provider']}; no request was sent and each remote query still requires one-use authorization")
            return 0
        if args.literature_command == "report":
            report = literature_provenance_report(base)
            print(f"Literature provenance report: {report['availability']}")
            return 0
        if args.literature_command == "status":
            print(json.dumps(literature_status(base), ensure_ascii=False, indent=2))
            return 0
        if args.literature_command == "graph":
            graph = build_citation_graph(base)
            print(f"Literature graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
            return 0
        if args.literature_command == "retractions":
            report = build_retraction_report(base)
            print(f"Retraction metadata: {len(report['assertions'])} assertions across {len(report['records'])} works")
            return 0
        if args.literature_command == "align":
            try:
                payload = build_claim_literature_alignments(base)
            except ValueError as exc:
                print(f"error: {exc}")
                return 1
            pending = sum(item.get("status") == "pending_author_review" for item in payload["candidates"])
            print(f"Literature alignments: {len(payload['candidates'])} candidates, {pending} pending author review")
            return 0
        if args.literature_command == "align-review":
            try:
                candidate = review_claim_literature_alignment(base, args.candidate_id, args.decision, args.relationship, args.note)
            except ValueError as exc:
                print(f"error: {exc}")
                return 1
            print(f"Alignment {candidate['candidate_id']}: {candidate['status']}")
            return 0
        if args.literature_command == "authorize-query":
            record = authorize_literature_query(base, args.provider, args.query, args.purpose, args.final_report_permission)
            print(record["authorization_id"])
            return 0
        if args.literature_command == "fetch-openalex":
            try:
                fetch_openalex(base, args.query, args.authorization_id, args.offline)
            except ValueError as exc:
                print(f"error: {exc}")
                return 1
            print("Cached OpenAlex response")
            return 0
        if args.literature_command == "fetch":
            try:
                record = fetch_literature_provider(base, args.provider, args.query, args.authorization_id, args.offline)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                print(f"error: {exc}")
                return 1
            print(f"Cached {record['provider']} metadata with {len(record['normalized_records'])} normalized records")
            return 0
        try:
            response = json.loads(Path(args.response_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: invalid local provider response: {exc}")
            return 1
        try:
            record = cache_literature_query(base, args.provider, args.query, response)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Cached local {record['provider']} query response; no network request was sent")
        return 0
    if args.command == "history":
        try:
            if args.history_command == "import": record = import_history(base, Path(args.path), args.purpose); message = f"Registered history {record['history_id']}; raw content was not stored"
            elif args.history_command == "redact": record = redact_history(base, args.history_id, Path(args.source_file), args.retention); message = f"Created redaction preview for {record['history_id']}"
            elif args.history_command == "approve": record = approve_history(base, args.history_id); message = f"Approved redacted history {record['history_id']}"
            elif args.history_command == "rebuild": result = rebuild_history_index(base); message = f"Rebuilt history index with {len(result['indexed_history_ids'])} records"
            elif args.history_command == "enforce-retention": result = enforce_history_retention(base); message = f"Expired {len(result['expired_history_ids'])} history records"
            elif args.history_command == "search": print(json.dumps(search_history(base, args.query, args.limit), ensure_ascii=False, indent=2)); return 0
            elif args.history_command == "delete": record = delete_history(base, args.history_id, args.confirm); message = f"Deleted stored preview for {record['history_id']}"
            else: message = str(export_history(base, Path(args.target)))
        except (ValueError, OSError) as exc:
            print(f"error: {exc}")
            return 1
        print(message)
        return 0
    if args.command == "review-followup-authorize":
        try:
            task = authorize_followup(base, args.task_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Authorized follow-up {task['task_id']}; no follow-up work was executed")
        return 0
    if args.command == "proof-plan":
        try:
            workflow = proof_plan_for_item(base, args.item_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Planned proof workflow for {workflow['item_id']}")
        return 0
    if args.command == "proof-obligation":
        try:
            obligation = proof_obligation(base, args.item_id, args.add)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Added {obligation['id']} to {args.item_id}")
        return 0
    if args.command == "proof-diff":
        try:
            diff = proof_record_revision_diff(base, args.item_id, args.after_file)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Recorded proof revision snapshot for {args.item_id}: {diff['after_content_sha256']}")
        return 0
    if args.command == "proof-approve":
        try:
            workflow = proof_approve(base, args.item_id, args.note)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Approved proof workflow for {workflow['item_id']}")
        return 0
    if args.command == "experiment-plan":
        try:
            print(experiment_plan_for_item(base, args.item_id))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "experiment-contract":
        try:
            manifest = experiment_contract(base, args.item_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Planned experiment contract for {manifest['item_id']}")
        return 0
    if args.command == "experiment-artifact":
        try:
            artifact = experiment_artifact(base, args.item_id, args.path, args.kind, args.note)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Recorded experiment artifact {artifact['path']} sha256={artifact['sha256']}")
        return 0
    if args.command == "experiment-incorporate":
        try:
            backfill = experiment_incorporate(base, args.item_id, args.target, args.field, args.text_file)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Recorded experiment backfill {backfill['target']} {backfill['field']}")
        return 0
    if args.command == "experiment-run":
        try:
            if args.dry_run:
                print(render_experiment_run_preview(experiment_run_preview(base, args.item_id)), end="")
                return 0
            attempt = experiment_run_record(base, args.item_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Recorded experiment run {attempt['attempt_id']} exit={attempt['exit_code']}")
        return 0 if attempt.get("exit_code") == 0 else 1
    if args.command == "record-result":
        try:
            record = record_experiment_result(base, args.item_id, args.artifact, args.note)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Recorded result for {record['item_id']}: {record['artifact']}")
        return 0
    if args.command == "reason":
        try:
            print(reasoning_for_item(base, args.item_id))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "propose":
        candidates = propose_candidates(base, force=args.force)
        print(f"Wrote {len(candidates)} candidate edits")
        return 0
    if args.command == "inspect":
        try:
            print(candidate_summary(inspect_record(base, args.record_id)))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "edit-candidate":
        try:
            candidate = edit_candidate(base, args.candidate_id, args.text_file)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Edited {candidate['id']}")
        return 0
    if args.command == "approve":
        try:
            candidate = approve_candidate(base, args.candidate_id, allow_high_risk=args.allow_high_risk)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Approved {candidate['id']}")
        return 0
    if args.command == "reject":
        try:
            candidate = reject_candidate(base, args.candidate_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Rejected {candidate['id']}")
        return 0
    if args.command == "close-item":
        try:
            item = close_item(base, args.item_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Closed {item['id']}")
        return 0
    if args.command == "reopen-item":
        try:
            item = reopen_item(base, args.item_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Reopened {item['id']}")
        return 0
    if args.command == "apply":
        if args.dry_run == args.approved:
            print("error: choose exactly one of --dry-run or --approved")
            return 1
        if args.dry_run:
            print(render_apply_diff(base), end="")
            return 0
        result = apply_approved_candidates(base)
        for candidate_id in result["blocked"]:
            print(f"blocked: {candidate_id}")
        for candidate_id in result["applied"]:
            print(f"applied: {candidate_id}")
        if result["backup_dir"]:
            print(f"backup: {result['backup_dir']}")
        return 0
    if args.command == "restore":
        try:
            restored = restore_backup(base, args.backup)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        for path in restored:
            print(f"restored: {path}")
        return 0
    if args.command == "validate":
        result = validate_workspace(base, compile_check=args.compile)
        for warning in result["warnings"]:
            print(f"warning: {warning}")
        for issue in result["issues"]:
            print(f"error: {issue}")
        print("validation ok" if result["ok"] else "validation failed")
        return 0 if result["ok"] else 1
    if args.command == "provenance":
        try:
            print(provenance_for_item(base, args.item_id), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "memory":
        try:
            print(memory_for_item(base, args.item_id), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "readiness":
        try:
            readiness_report = write_revision_readiness(base)
            print(render_revision_readiness(readiness_report, args.item_id), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "submit-pack":
        if not args.dry_run:
            print("error: submit-pack currently supports --dry-run only")
            return 1
        print(render_submit_pack_dry_run(build_submit_pack_dry_run(base)), end="")
        return 0
    if args.command == "status":
        result = status(base)
        print(f"workspace: {result['workspace']}")
        print(f"journal: {result['journal']}")
        print(f"tex root: {result['tex_root']}")
        print(f"main tex: {result['main_tex']}")
        for key, value in result["counts"].items():
            print(f"{key}: {value}")
        return 0
    if args.command == "project-init":
        print(json.dumps(initialize_project_runtime(base), ensure_ascii=False, indent=2))
        return 0
    if args.command == "project-status":
        print(json.dumps(project_status(base), ensure_ascii=False, indent=2))
        return 0
    if args.command == "project-pause":
        set_project_paused(base, True)
        print("Project scheduling paused")
        return 0
    if args.command == "project-resume":
        set_project_paused(base, False)
        print("Project scheduling resumed")
        return 0
    if args.command == "project-stop":
        stop_project_service(base)
        print("Project service stop requested")
        return 0
    if args.command == "project-recover":
        print(json.dumps(recover_project_runtime(base), ensure_ascii=False, indent=2))
        return 0
    if args.command == "service-health":
        print(json.dumps(service_health(base), ensure_ascii=False, indent=2))
        return 0
    if args.command == "project-cycle":
        try:
            print(json.dumps(run_project_cycle(base, args.workers), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-open":
        try:
            print(json.dumps(open_revision_cycle(base, args.item_id, args.planner_id), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-plan":
        try:
            print(json.dumps(attach_cycle_plan(base, args.cycle_id, Path(args.plan_file)), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-act":
        try:
            print(json.dumps(attach_cycle_actor_bundle(base, args.cycle_id, args.actor_id, Path(args.bundle_file)), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-review":
        try:
            print(json.dumps(attach_cycle_review(base, args.cycle_id, args.reviewer_id, Path(args.review_file)), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-review-session":
        try:
            print(json.dumps(create_cycle_reviewer_session(base, args.cycle_id, args.reviewer_id), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-author-gate":
        try:
            print(json.dumps(record_cycle_author_gate(base, args.cycle_id, args.author_id, args.decision, args.note), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-author-waive":
        try:
            print(json.dumps(record_cycle_author_waiver(base, args.cycle_id, args.author_id, args.finding_id, args.note), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-author-escalate":
        try:
            print(json.dumps(record_cycle_author_escalation(base, args.cycle_id, args.author_id, args.note), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-reopen":
        try:
            print(json.dumps(reopen_revision_cycle(base, args.cycle_id, args.note), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "cycle-status":
        try:
            print(json.dumps(revision_cycle_status(base, args.cycle_id), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "author-console":
        print(json.dumps(author_decision_console(base), ensure_ascii=False, indent=2))
        return 0
    if args.command == "serve":
        try:
            serve_project(base, args.host, args.port, args.workers, args.once)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "authorize-remote":
        try:
            print(json.dumps(authorize_remote(base, args.task_id, args.provider, args.model, args.purpose, args.artifact_class, args.ttl_minutes), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "review-evaluate":
        print(json.dumps(evaluate_review_item(base, args.item_id), ensure_ascii=False, indent=2))
        return 0
    if args.command == "review-rubric":
        try:
            print(json.dumps(run_review_rubric(base, args.item_id, args.authorization), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "worker-plan":
        try:
            print(json.dumps(plan_review_workers(base, args.item_id, args.backend), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "review-sandbox-create":
        try:
            print(json.dumps(create_review_snapshot(base, args.worker_id), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "review-worker-start":
        try:
            print(json.dumps(start_review_worker(base, args.worker_id), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "review-worker-collect":
        try:
            print(json.dumps(collect_review_worker(base, args.worker_id), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "experiment-authorize-worker":
        try:
            print(json.dumps(authorize_experiment(base, args.worker_id, args.experiment_command, args.cwd, args.timeout_seconds, args.cpu, args.memory_mb, args.artifact), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "experiment-start-worker":
        try:
            print(json.dumps(run_authorized_experiment(base, args.authorization_id), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "benchmark-run":
        try:
            print(json.dumps(run_benchmark(base, Path(args.fixture)), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "benchmark-review-suite":
        try:
            print(json.dumps(run_review_benchmark_suite(base, Path(args.suite)), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "benchmark-alignment-suite":
        try:
            report = run_alignment_benchmark_suite(base, Path(args.suite))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Alignment benchmark: recall@5={report['metrics']['recall_at_5']:.3f}, MRR={report['metrics']['mean_reciprocal_rank']:.3f}")
        return 0
    if args.command == "benchmark-history-suite":
        try:
            report = run_history_benchmark_suite(base, Path(args.suite))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"History benchmark: recall@5={report['metrics']['recall_at_5']:.3f}, MRR={report['metrics']['mean_reciprocal_rank']:.3f}")
        return 0
    if args.command == "history-quality-publish":
        try: report = publish_history_quality(base, Path(args.suite))
        except ValueError as exc:
            print(f"error: {exc}"); return 1
        print(f"Published history quality from {report['case_count']} adjudicated real cases")
        return 0
    if args.command == "benchmark-shadow":
        try:
            print(json.dumps(register_shadow_benchmark(base, Path(args.case_dir), args.case_id), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "benchmark-synthetic-catalog":
        try:
            print(json.dumps(generate_synthetic_catalog(base, args.count), ensure_ascii=False, indent=2))
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "benchmark-shadow-score":
        try:
            scores = json.loads(args.scores_json)
            if not isinstance(scores, dict):
                raise ValueError("scores-json must be a JSON object")
            print(json.dumps(record_shadow_expert_scores(base, args.case_id, args.expert_id, scores), ensure_ascii=False, indent=2))
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "benchmark-shadow-assess":
        try:
            scorecards = json.loads(args.scorecards_json)
            if not isinstance(scorecards, dict):
                raise ValueError("scorecards-json must be a JSON object")
            print(json.dumps(assess_shadow_scores(scorecards), ensure_ascii=False, indent=2))
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "agent-status":
        state = build_agent_state(base)
        config = load_config(base)
        write_agent_state(config, state)
        print(render_agent_state(state), end="")
        return 0
    if args.command == "monitor":
        monitor = write_monitor_report(base)
        write_dashboard_html(base)
        print(render_monitor_report(monitor), end="")
        return 0
    if args.command == "dashboard":
        path = write_dashboard_html(base)
        print(f"Wrote dashboard to {path}")
        return 0
    if args.command == "run":
        try:
            result = run_external_agent(base, backend=args.backend, goal=args.goal, dry_run=args.dry_run, detach=args.detach, limit=args.limit, dangerous_autonomy=args.dangerous_autonomy)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        if args.dry_run:
            print(result.get("prompt", ""), end="")
            return 0
        print(f"external agent {result.get('status')} backend={result.get('backend')} prompt={result.get('prompt_path')}")
        if result.get("stdout_path"):
            print(f"stdout: {result['stdout_path']}")
        if result.get("stderr_path"):
            print(f"stderr: {result['stderr_path']}")
        if result.get("launch_script"):
            print(f"launch: {result['launch_script']}")
        if result.get("error"):
            print(f"error: {result['error']}")
        return 0 if result.get("status") in {"done", "queued"} else 1
    if args.command == "run-status":
        config = load_config(base)
        try:
            runtime = latest_runtime_events(config)
            if args.run_id:
                print(render_external_agent_run_detail(get_external_agent_run(config, args.run_id), supervisor_observations_snapshot(config)), end="")
                if args.run_id in runtime:
                    print(render_runtime_events([runtime[args.run_id]]), end="")
            else:
                print(render_external_agent_runs(load_external_agent_runs(config), supervisor_observations_snapshot(config)), end="")
                if runtime:
                    print(render_runtime_events(list(runtime.values())), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "run-recover":
        try:
            result = recover_external_agent_run(base, run_id=args.run_id, dry_run=args.dry_run)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        if args.dry_run:
            print(result.get("prompt", ""), end="")
            return 0
        print(f"external agent recovery {result.get('status')} backend={result.get('backend')} prompt={result.get('prompt_path')}")
        if result.get("launch_script"):
            print(f"launch: {result['launch_script']}")
        if result.get("error"):
            print(f"error: {result['error']}")
        return 0 if result.get("status") in {"done", "queued"} else 1
    if args.command == "run-mark":
        try:
            result = mark_external_agent_run(base, args.run_id, args.status, note=args.note)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_external_agent_run_detail(result), end="")
        return 0
    if args.command == "run-log":
        config = load_config(base)
        try:
            run = get_external_agent_run(config, args.run_id)
            print(external_agent_run_artifact(run, args.artifact), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "run-supervise":
        config = load_config(base)
        try:
            runs = [get_external_agent_run(config, args.run_id)] if args.run_id else load_external_agent_runs(config)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_external_agent_supervision(runs, supervisor_observations_snapshot(config)), end="")
        runtime = latest_runtime_events(config)
        selected_runtime = [runtime[str(run.get("run_id", ""))] for run in runs if str(run.get("run_id", "")) in runtime]
        if selected_runtime:
            print(render_runtime_events(selected_runtime), end="")
        return 0
    if args.command == "worker-snapshot":
        try:
            snapshot = create_worker_snapshot(base, args.run_id)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Created worker snapshot for {args.run_id}: {snapshot['path']}")
        return 0
    if args.command == "run-start":
        try:
            print(render_runtime_events([start_worker(base, args.run_id)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "run-refresh":
        try:
            print(render_runtime_events([refresh_worker(base, args.run_id)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "run-cancel":
        try:
            print(render_runtime_events([cancel_worker(base, args.run_id, args.note)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "worker-evaluate":
        try:
            print(render_evaluations([evaluate_worker(base, args.run_id)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "evolution-plan":
        try:
            print(render_proposals(plan_evolution(base)), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "evolution-review":
        try:
            print(render_proposals([get_proposal(load_config(base), args.proposal_id)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "evolution-approve":
        try:
            print(render_proposals([approve_evolution(base, args.proposal_id, args.note)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "evolution-reject":
        try:
            print(render_proposals([reject_evolution(base, args.proposal_id, args.note)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "evolution-apply":
        if not args.approved:
            print("error: evolution-apply requires --approved")
            return 1
        try:
            print(render_proposals([apply_evolution(base, args.proposal_id)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "agent-plan":
        try:
            session = plan_agent_session(base, args.goal)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_agent_sessions([session]), end="")
        return 0
    if args.command == "agent-session":
        config = load_config(base)
        print(render_agent_sessions(load_agent_sessions(config)), end="")
        return 0
    if args.command == "agent-resume":
        try:
            if args.watch:
                session = resume_agent_session_watch(base, interval=args.interval, cycles=args.cycles, limit=args.limit, retry_failed=args.retry_failed)
            else:
                session = resume_agent_session(base, limit=args.limit, retry_failed=args.retry_failed)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_agent_sessions([session]), end="")
        return 0 if session.get("status") != "failed" else 1
    if args.command == "agent-blockers":
        print(render_agent_blockers(agent_blockers(base)), end="")
        return 0
    if args.command == "agent-complete-check":
        try:
            session = complete_check_agent_session(base)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_agent_sessions([session]), end="")
        return 0 if session.get("status") != "failed" else 1
    if args.command == "agent-decisions":
        print(render_agent_decisions(refresh_agent_decisions(base)), end="")
        return 0
    if args.command == "agent-decision":
        try:
            print(render_agent_decisions([get_agent_decision(base, args.decision_id)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "agent-decision-resolve":
        try:
            print(render_agent_decisions([resolve_agent_decision(base, args.decision_id, args.note)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "agent-decision-dismiss":
        try:
            print(render_agent_decisions([dismiss_agent_decision(base, args.decision_id, args.note)]), end="")
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0
    if args.command == "agent-eval":
        try:
            report = run_agent_eval(base, fixture=None if args.all or not args.fixture else args.fixture)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_agent_eval_report(report), end="")
        return 0 if report.get("ok") else 1
    if args.command == "agent-next":
        state = build_agent_state(base)
        config = load_config(base)
        write_agent_state(config, state)
        print(render_agent_next(state), end="")
        return 0
    if args.command == "agent-report":
        report = write_agent_report(base)
        write_agent_dashboard(base)
        print(render_agent_report(report), end="")
        return 0
    if args.command == "supervisor-plan":
        print(render_supervisor_plan(build_supervisor_plan(base, update_plan=args.update_plan)), end="")
        return 0
    if args.command == "supervisor-loop":
        try:
            result = run_supervisor_loop(base, cycles=args.cycles, dry_run=args.dry_run, update_plan=args.update_plan)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_supervisor_runs([result]), end="")
        return 0 if result.get("status") != "failed" else 1
    if args.command == "supervisor-feedback":
        print(render_supervisor_feedback(build_supervisor_feedback(base, update_plan=args.update_plan)), end="")
        return 0
    if args.command == "supervisor-workers":
        try:
            worker_plan = build_supervisor_workers(base, workers=args.workers, queue=args.queue, update_plan=args.update_plan)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_supervisor_workers(worker_plan), end="")
        return 0
    if args.command == "supervisor-observe":
        try:
            observations = observe_supervisor_workers(base, args.run_id, update_plan=args.update_plan)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_supervisor_observations(observations), end="")
        return 0
    if args.command == "supervisor-observation":
        try:
            observations = get_supervisor_observations(base, args.run_id, update_plan=args.update_plan)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(render_supervisor_observations(observations), end="")
        return 0
    if args.command == "agent-run":
        state = run_agent_once(base, limit=args.limit, until_blocked=args.until_blocked, retry_failed=args.retry_failed, max_failures=args.max_failures)
        print(render_agent_state(state), end="")
        return 0 if state["summary"].get("failed", 0) == 0 else 1
    if args.command == "doctor":
        result = doctor(base)
        print_check_result(result)
        return 0 if result["ok"] else 1
    if args.command == "clean":
        removed = clean_workspace(base)
        if removed:
            print("Removed generated directories:")
            for path in removed:
                print(f"- {path}")
        else:
            print("No generated directories needed cleaning")
        return 0
    if args.command == "export":
        artifact_dir = export_artifacts(base)
        print(f"Exported artifacts to {artifact_dir}")
        return 0
    if args.command == "profiles":
        for name in available_profiles(Path(args.base).resolve()):
            print(name)
        return 0
    if args.command == "journal":
        journal_base = Path(args.base).resolve()
        if args.journal_command == "list":
            for name in available_profiles(journal_base):
                print(name)
            return 0
        if args.journal_command == "validate":
            result = validate_rulepack(args.name, journal_base)
            print(render_rulepack_validation(result), end="")
            return 0 if result["ok"] else 1
        if args.journal_command == "init":
            try:
                directory = initialize_rulepack(args.name, journal_base)
            except ValueError as exc:
                print(f"error: {exc}")
                return 1
            print(f"Created unconfirmed rulepack template: {directory}")
            return 0
        if args.journal_command == "diff":
            print(render_rulepack_diff(diff_rulepacks(args.left, args.right, journal_base)), end="")
            return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
