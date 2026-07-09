from __future__ import annotations

import argparse
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
    proof_plan_for_item,
    reasoning_for_item,
    record_experiment_result,
    render_experiment_run_preview,
    render_item_plan,
    reopen_item,
)
from .llm import draft_all_with_llm, draft_item_with_llm, llm_accept, llm_check, llm_check_all, llm_edit, llm_reject, llm_review, render_llm_drafts
from .provenance import provenance_for_item
from .readiness import build_submit_pack_dry_run, render_revision_readiness, render_submit_pack_dry_run, write_revision_readiness
from .review_analysis import analyze_all_review_items, analyze_review_item, render_review_analyses, review_analysis_for_item
from .rendering import create_draft, incorporate_drafts
from .reviews import create_plan, ingest_comments
from .validation import doctor, validate_workspace
from .workspace import (
    clean_workspace,
    export_artifacts,
    init_workspace,
    load_config,
    migrate_workspace,
    render_migration_report,
    schema_markdown,
    status,
)
from .profiles import available_profiles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="revagent", description="Local revision workspace CLI for computational mathematics papers.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a local revision workspace.")
    init.add_argument("--journal", required=True, help="Built-in profile or journal_profiles/<name>.yaml.")
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
    readiness = sub.add_parser("readiness", help="Generate and show revision readiness.")
    readiness.add_argument("item_id", nargs="?")
    submit_pack = sub.add_parser("submit-pack", help="Inspect final submission package readiness.")
    submit_pack.add_argument("--dry-run", action="store_true", help="Show missing submission package pieces without writing final artifacts.")
    sub.add_parser("status", help="Print workspace item counts and configuration.")
    sub.add_parser("agent-status", help="Build and print the safe-auto agent task queue.")
    sub.add_parser("monitor", help="Write and print the agent dashboard.")
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
    agent_run = sub.add_parser("agent-run", help="Execute safe-auto agent tasks.")
    agent_run.add_argument("--limit", type=int, default=None, help="Maximum number of safe pending tasks to execute.")
    agent_run.add_argument("--until-blocked", action="store_true", help="Run safe tasks until only blocked/manual work remains.")
    agent_run.add_argument("--retry-failed", action="store_true", help="Retry failed safe tasks with unchanged inputs.")
    agent_run.add_argument("--max-failures", type=int, default=None, help="Stop after this many failed safe tasks.")
    sub.add_parser("doctor", help="Check local environment and profile availability.")
    sub.add_parser("clean", help="Remove generated logs and exported artifacts, preserving source workspace files.")
    sub.add_parser("export", help="Copy final artifacts into .revagent/artifacts.")
    profiles = sub.add_parser("profiles", help="List built-in and local journal profiles.")
    profiles.add_argument("--base", default=".", help="Project directory to scan for journal_profiles/*.yaml.")
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
    if args.command == "agent-status":
        state = build_agent_state(base)
        config = load_config(base)
        write_agent_state(config, state)
        print(render_agent_state(state), end="")
        return 0
    if args.command == "monitor":
        dashboard = write_agent_dashboard(base)
        print(render_agent_dashboard(dashboard), end="")
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
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
