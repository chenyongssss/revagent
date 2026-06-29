from __future__ import annotations

import argparse
from pathlib import Path

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
    plan_all_items,
    plan_item,
    proof_audit_for_item,
    proof_approve,
    proof_obligation,
    proof_plan_for_item,
    reasoning_for_item,
    record_experiment_result,
    render_item_plan,
    reopen_item,
)
from .rendering import create_draft
from .reviews import create_plan, ingest_comments
from .validation import doctor, validate_workspace
from .workspace import (
    clean_workspace,
    export_artifacts,
    init_workspace,
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
    sub.add_parser("draft", help="Draft response letter and reviewable manuscript patch notes.")
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
    sub.add_parser("status", help="Print workspace item counts and configuration.")
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
    if args.command == "draft":
        create_draft(base)
        print("Wrote response_letter.md, manuscript.patch, and candidate_edits.json")
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
    if args.command == "status":
        result = status(base)
        print(f"workspace: {result['workspace']}")
        print(f"journal: {result['journal']}")
        print(f"tex root: {result['tex_root']}")
        print(f"main tex: {result['main_tex']}")
        for key, value in result["counts"].items():
            print(f"{key}: {value}")
        return 0
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
