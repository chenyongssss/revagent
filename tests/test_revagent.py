import hashlib
import json
import sys
from pathlib import Path

import pytest

from revagent.cli import main
from revagent.core import (
    SCHEMA_FILES,
    analyze_all_review_items,
    analyze_review_item,
    apply_approved_candidates,
    approve_candidate,
    build_llm_context,
    build_agent_state,
    load_external_agent_runs,
    clean_workspace,
    close_item,
    create_draft,
    create_plan,
    edit_candidate,
    experiment_artifact,
    experiment_contract,
    experiment_incorporate,
    experiment_plan_for_item,
    experiment_run_preview,
    experiment_run_record,
    export_artifacts,
    incorporate_drafts,
    ingest_comments,
    init_workspace,
    inspect_record,
    latex_index,
    load_config,
    draft_all_with_llm,
    draft_item_with_llm,
    llm_accept,
    llm_check,
    llm_check_all,
    llm_edit,
    llm_reject,
    llm_review,
    load_agent_runs,
    load_candidates,
    load_experiment_run_attempts,
    load_llm_drafts,
    build_revision_memory,
    plan_all_items,
    plan_item,
    propose_candidates,
    proof_audit_for_item,
    proof_approve,
    proof_obligation,
    proof_plan_for_item,
    provenance_missing_or_stale,
    reasoning_for_item,
    record_experiment_result,
    reject_candidate,
    reopen_item,
    render_apply_diff,
    render_revision_readiness,
    render_submit_pack_dry_run,
    render_revision_provenance,
    render_revision_memory,
    run_external_agent,
    run_agent_once,
    write_dashboard_html,
    write_revision_memory,
    write_revision_readiness,
    build_submit_pack_dry_run,
    load_agent_decisions,
    load_agent_sessions,
    load_review_analyses,
    render_review_analyses,
    restore_backup,
    schema_markdown,
    status,
    validate_workspace,
    write_revision_provenance,
)
from revagent.profiles import load_profile
from revagent.workspace import CURRENT_SCHEMA_VERSION, migrate_workspace, render_migration_report
from revagent.latex import discover_tex_graph


def write_demo_project(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "scripts" / "run_demo.py").write_text("print('demo')\n", encoding="utf-8")
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n"
        "\\newtheorem{theorem}{Theorem}\n"
        "\\begin{document}\n"
        "\\section{Convergence}\n"
        "\\begin{theorem}\\label{thm:conv} The scheme converges by Lemma~\\ref{lem:stable}.\\end{theorem}\n"
        "\\begin{proof} The proof follows from stability.\\end{proof}\n"
        "\\section{Numerical Experiments}\n"
        "We report a benchmark in Figure~\\ref{fig:demo} and Table~\\ref{tab:demo}.\n"
        "\\begin{figure}\\caption{Demo figure.}\\label{fig:demo}\\end{figure}\n"
        "\\begin{table}\\caption{Demo table.}\\label{tab:demo}\\end{table}\n"
        "\\bibliography{refs}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "comments.md").write_text(
        "# Reviewer 1\n"
        "- Please clarify the proof of the convergence theorem and its assumptions.\n"
        "- Add a numerical experiment comparing the benchmark parameter choices with a fixed seed.\n"
        "- Please clarify the contribution in the introduction.\n",
        encoding="utf-8",
    )


def write_multifile_project(tmp_path: Path) -> None:
    (tmp_path / "sections").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\newtheorem{assumption}{Assumption}\n"
        "\\newtheorem{theorem}{Theorem}\n"
        "\\begin{document}\n"
        "\\input{sections/theory}\n"
        "\\include{sections/experiments}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "sections" / "theory.tex").write_text(
        "\\section{Stability Theory}\n"
        "\\begin{assumption}\\label{ass:regularity} The coefficient is smooth.\\end{assumption}\n"
        "\\begin{theorem}\\label{thm:stable} The PINN residual is stable under Assumption~\\ref{ass:regularity}.\\end{theorem}\n"
        "\\begin{proof} Use the coercivity estimate and the regularity assumption.\\end{proof}\n",
        encoding="utf-8",
    )
    (tmp_path / "sections" / "experiments.tex").write_text(
        "\\section{Ablation Experiments}\n"
        "\\begin{table}\\caption{PINN baseline comparison.}\\label{tab:baseline}\\end{table}\n",
        encoding="utf-8",
    )
    (tmp_path / "drafts" / "unused.tex").write_text("\\section{Unused Draft}\n", encoding="utf-8")
    (tmp_path / "comments.md").write_text(
        "# Reviewer 2\n"
        "- Please clarify the proof of Theorem 1 and the regularity assumption.\n"
        "- Table 1 should include the Oracle-filter FT baseline.\n"
        "- Please clarify the introduction and contribution.\n",
        encoding="utf-8",
    )


def test_revision_workspace_generates_core_artifacts(tmp_path: Path) -> None:
    write_demo_project(tmp_path)

    ws = init_workspace(tmp_path, "siam", ".", "paper.tex")
    assert (ws / "revision.yaml").exists()

    assert ingest_comments(tmp_path, "comments.md") == 3
    create_plan(tmp_path)
    create_draft(tmp_path)
    artifact_dir = export_artifacts(tmp_path)

    for name in SCHEMA_FILES:
        assert (ws / name).exists()

    items = (ws / "review_items.json").read_text(encoding="utf-8")
    assert '"kind": "proof"' in items
    assert '"kind": "experiment"' in items
    assert '"risk": "high"' in items
    assert "Dependency Map" in (ws / "proof_audit.md").read_text(encoding="utf-8")
    assert "Detected Assets" in (ws / "experiment_plan.md").read_text(encoding="utf-8")
    assert "REVAGENT clarification TODO" in (ws / "manuscript.patch").read_text(encoding="utf-8")
    assert (ws / "review_analyses.json").exists()
    assert (artifact_dir / "review_analyses.md").exists()
    assert (ws / "candidate_edits.json").exists()
    assert (ws / "decision_log.md").exists()
    assert (artifact_dir / "MANIFEST.md").exists()


def test_latex_index_tracks_refs_environments_and_unresolved_refs(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    index = latex_index(tmp_path)

    assert len(index["sections"]) == 2
    assert any(env["environment"] == "theorem" for env in index["environments"])
    assert any(env["environment"] == "figure" and env["caption"] == "Demo figure." for env in index["environments"])
    assert any(ref["ref"] == "lem:stable" for ref in index["unresolved_refs"])
    assert index["bibliography"][0]["target"] == "refs"


def test_validate_status_clean_and_cli(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "ams", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)

    result = validate_workspace(tmp_path)
    assert result["ok"]
    assert result["warnings"]
    assert status(tmp_path)["counts"]["experiment"] == 1

    monkeypatch.chdir(tmp_path)
    assert main(["status"]) == 0
    assert main(["validate"]) == 0
    assert main(["profiles"]) == 0
    assert main(["inspect", "R001"]) == 0
    assert main(["schema"]) == 0
    assert main(["proof-audit", "R001"]) == 0
    assert main(["experiment-plan", "R002"]) == 0
    assert main(["reason", "R001"]) == 0

    export_artifacts(tmp_path)
    removed = clean_workspace(tmp_path)
    assert any(path.endswith("artifacts") for path in removed)
    assert (tmp_path / ".revagent" / "artifacts").exists()


def test_revision_readiness_reports_blockers_and_submit_pack(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    analyze_all_review_items(tmp_path)
    plan_all_items(tmp_path)
    proof_plan_for_item(tmp_path, "R001")
    experiment_contract(tmp_path, "R002")
    config = load_config(tmp_path)
    manifests = json.loads((config.workspace / "experiment_manifests.json").read_text(encoding="utf-8"))
    manifests["R002"]["command_template"] = f"{sys.executable} scripts/run_demo.py"
    manifests["R002"]["expected_artifacts"] = ["results/demo_metrics.csv"]
    (config.workspace / "experiment_manifests.json").write_text(json.dumps(manifests, indent=2) + "\n", encoding="utf-8")
    create_draft(tmp_path)

    readiness = write_revision_readiness(tmp_path)
    by_item = {item["item_id"]: item for item in readiness["items"]}
    assert by_item["R001"]["readiness_status"] == "blocked_manual"
    assert "author proof approval" in by_item["R001"]["manual_actions"]
    assert by_item["R002"]["readiness_status"] == "needs_evidence"
    assert "experiment run attempt" in by_item["R002"]["missing_inputs"]
    assert "recorded experiment result" in by_item["R002"]["missing_inputs"]
    assert (tmp_path / ".revagent" / "revision_readiness.json").exists()
    assert "## Blockers" in (tmp_path / ".revagent" / "revision_readiness.md").read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main(["readiness", "R001"]) == 0
    assert main(["submit-pack", "--dry-run"]) == 0
    submit_pack = build_submit_pack_dry_run(tmp_path)
    assert not submit_pack["ready"]
    assert "manual gates resolved" in submit_pack["missing"]
    assert "# Submit Pack Dry Run" in render_submit_pack_dry_run(submit_pack)


def test_revision_readiness_needs_apply_then_ready_after_apply(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    analyze_all_review_items(tmp_path)
    plan_all_items(tmp_path)
    create_draft(tmp_path)

    config = load_config(tmp_path)
    manuscript_candidate = next(candidate for candidate in load_candidates(config) if candidate["kind"] == "manuscript")
    (tmp_path / "author_text.tex").write_text("We added a concise clarification requested by the reviewer.", encoding="utf-8")
    edit_candidate(tmp_path, manuscript_candidate["id"], "author_text.tex")
    approve_candidate(tmp_path, manuscript_candidate["id"])

    readiness = write_revision_readiness(tmp_path)
    item = next(item for item in readiness["items"] if item["item_id"] == manuscript_candidate["item_id"])
    assert item["readiness_status"] == "needs_apply"
    validation = validate_workspace(tmp_path)
    assert any(f"{manuscript_candidate['id']} is approved but not applied" in warning for warning in validation["warnings"])

    apply_approved_candidates(tmp_path)
    write_revision_provenance(tmp_path)
    readiness = write_revision_readiness(tmp_path)
    item = next(item for item in readiness["items"] if item["item_id"] == manuscript_candidate["item_id"])
    assert item["readiness_status"] == "ready"
    assert "Ready Items" in render_revision_readiness(readiness)


def test_agent_safe_loop_refreshes_readiness(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    state = run_agent_once(tmp_path, until_blocked=True)

    assert (tmp_path / ".revagent" / "revision_readiness.json").exists()
    assert any(task.get("kind") == "readiness" and task.get("status") == "done" for task in state.get("tasks", []))
    candidates = load_candidates(load_config(tmp_path))
    assert not any(candidate.get("status") in {"approved", "applied"} for candidate in candidates)


def test_custom_journal_profile_override(tmp_path: Path) -> None:
    (tmp_path / "journal_profiles").mkdir()
    (tmp_path / "journal_profiles" / "custom.yaml").write_text(
        "display_name: Custom Journal\n"
        "response_heading: Custom Response\n"
        "tone: compact and formal\n"
        "checks:\n"
        "  - custom check\n",
        encoding="utf-8",
    )
    profile = load_profile("custom", tmp_path)

    assert profile["display_name"] == "Custom Journal"
    assert profile["response_heading"] == "Custom Response"
    assert profile["checks"] == ["custom check"]


def test_candidate_workflow_dry_run_approve_apply_and_reject(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)

    config = load_config(tmp_path)
    candidates = load_candidates(config)
    manuscript_candidate = next(candidate for candidate in candidates if candidate["kind"] == "manuscript")
    proof_candidate = next(candidate for candidate in candidates if candidate["kind"] == "proof")

    original = (tmp_path / "paper.tex").read_text(encoding="utf-8")
    diff = render_apply_diff(tmp_path, approved_only=False)
    assert "REVAGENT clarification TODO" in diff
    assert (tmp_path / "paper.tex").read_text(encoding="utf-8") == original

    (tmp_path / "author_text.tex").write_text("We added a concise clarification requested by the reviewer.", encoding="utf-8")
    edited = edit_candidate(tmp_path, manuscript_candidate["id"], "author_text.tex")
    assert edited["status"] == "edited"
    approved = approve_candidate(tmp_path, manuscript_candidate["id"])
    assert approved["status"] == "approved"

    rejected = reject_candidate(tmp_path, proof_candidate["id"])
    assert rejected["status"] == "rejected"

    result = apply_approved_candidates(tmp_path)
    assert result["applied"] == [manuscript_candidate["id"]]
    assert result["blocked"] == []
    revised = (tmp_path / "paper.tex").read_text(encoding="utf-8")
    assert "We added a concise clarification requested by the reviewer." in revised
    assert (tmp_path / ".revagent" / "apply_log.jsonl").exists()
    assert Path(result["backup_dir"]).exists()

    candidates = load_candidates(config)
    assert next(candidate for candidate in candidates if candidate["id"] == manuscript_candidate["id"])["status"] == "applied"

    monkeypatch.chdir(tmp_path)
    assert main(["inspect", manuscript_candidate["id"]]) == 0
    assert main(["apply", "--dry-run"]) == 0


def test_candidate_apply_blocks_when_anchor_changes(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    candidates = propose_candidates(tmp_path)
    manuscript_candidate = next(candidate for candidate in candidates if candidate["kind"] == "manuscript")

    (tmp_path / "author_text.tex").write_text("Clarification text.", encoding="utf-8")
    edit_candidate(tmp_path, manuscript_candidate["id"], "author_text.tex")
    approve_candidate(tmp_path, manuscript_candidate["id"])

    paper = tmp_path / manuscript_candidate["target_file"]
    lines = paper.read_text(encoding="utf-8").splitlines()
    anchor_index = int(manuscript_candidate["anchor_line"]) - 1
    lines[anchor_index] = lines[anchor_index] + " % changed after approval"
    paper.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = apply_approved_candidates(tmp_path)
    assert result["applied"] == []
    assert result["blocked"] == [manuscript_candidate["id"]]
    config = load_config(tmp_path)
    blocked = next(candidate for candidate in load_candidates(config) if candidate["id"] == manuscript_candidate["id"])
    assert blocked["status"] == "blocked"
    assert blocked["conflict_reason"]


def test_candidate_patch_operations_caption_replace_environment_and_restore(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    record_experiment_result(tmp_path, "R002", "results/demo_metrics.csv", "Observed seed-1 baseline comparison.")
    proof_plan_for_item(tmp_path, "R001")
    proof_approve(tmp_path, "R001", "Author verified proof insertion.")
    candidates = propose_candidates(tmp_path, force=True)
    config = load_config(tmp_path)

    proof_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R001")
    experiment_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R002")
    manuscript_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R003")
    assert proof_candidate["operation"] == "insert_after_environment"
    assert experiment_candidate["operation"] == "update_caption"

    (tmp_path / "proof_text.tex").write_text("Author-verified proof clarification.", encoding="utf-8")
    edit_candidate(tmp_path, proof_candidate["id"], "proof_text.tex")
    approve_candidate(tmp_path, proof_candidate["id"], allow_high_risk=True)
    approve_candidate(tmp_path, experiment_candidate["id"])

    paper = tmp_path / "paper.tex"
    original = paper.read_text(encoding="utf-8")
    lines = original.splitlines()
    contribution_line = next(index for index, line in enumerate(lines, start=1) if "We report a benchmark" in line)
    manuscript_candidate["operation"] = "replace_block"
    manuscript_candidate["target_span"] = {"start_line": contribution_line, "end_line": contribution_line}
    manuscript_candidate["original_content_hash"] = hashlib.sha256(lines[contribution_line - 1].encode("utf-8")).hexdigest()[:16]
    manuscript_candidate["content"] = "We report a benchmark and clarify the contribution in the numerical section."
    manuscript_candidate["requires_author_text"] = False
    manuscript_candidate["status"] = "approved"
    manuscript_candidate["approved_at"] = "manual-test"
    all_candidates = load_candidates(config)
    for index, candidate in enumerate(all_candidates):
        if candidate["id"] == manuscript_candidate["id"]:
            all_candidates[index] = manuscript_candidate
    (config.workspace / "candidate_edits.json").write_text(json.dumps(all_candidates, indent=2) + "\n", encoding="utf-8")

    diff = render_apply_diff(tmp_path)
    assert "operation=replace_block" in diff
    assert "operation=update_caption" in diff

    result = apply_approved_candidates(tmp_path)
    assert set(result["applied"]) == {proof_candidate["id"], experiment_candidate["id"], manuscript_candidate["id"]}
    revised = paper.read_text(encoding="utf-8")
    assert "Author-verified proof clarification." in revised
    assert "Updated result backfill summary from author-recorded artifact" in revised
    assert "clarify the contribution" in revised
    applied = load_candidates(config)
    assert all(next(candidate for candidate in applied if candidate["id"] == cid)["backup_dir"] for cid in result["applied"])

    restored = restore_backup(tmp_path, result["backup_dir"])
    assert "paper.tex" in restored
    assert paper.read_text(encoding="utf-8") == original

    monkeypatch.chdir(tmp_path)
    assert main(["restore", "--backup", result["backup_dir"]]) == 0


def test_candidate_update_caption_blocks_on_stale_span(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    record_experiment_result(tmp_path, "R002", "results/demo_metrics.csv", "Observed seed-1 baseline comparison.")
    candidates = propose_candidates(tmp_path, force=True)
    experiment_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R002")
    assert experiment_candidate["operation"] == "update_caption"
    approve_candidate(tmp_path, experiment_candidate["id"])

    paper = tmp_path / "paper.tex"
    paper.write_text(paper.read_text(encoding="utf-8").replace("Demo table.", "Changed table."), encoding="utf-8")

    result = apply_approved_candidates(tmp_path)
    assert result["applied"] == []
    assert result["blocked"] == [experiment_candidate["id"]]
    config = load_config(tmp_path)
    blocked = next(candidate for candidate in load_candidates(config) if candidate["id"] == experiment_candidate["id"])
    assert "hash mismatch" in blocked["conflict_reason"]


def test_multifile_custom_theorem_scored_locations_and_candidate_context(tmp_path: Path) -> None:
    write_multifile_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "main.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)

    index = latex_index(tmp_path, "main.tex")
    assert "sections\\theory.tex" in index["reachable_files"] or "sections/theory.tex" in index["reachable_files"]
    assert not any("unused.tex" in rel for rel in index["reachable_files"])
    assert any(env["environment"] == "assumption" for env in index["custom_environments"])
    assert any(env["environment"] == "assumption" for env in index["environments"])

    config = load_config(tmp_path)
    items = (tmp_path / ".revagent" / "review_items.json").read_text(encoding="utf-8")
    assert '"reason":' in items
    candidates = load_candidates(config)
    proof_candidate = next(candidate for candidate in candidates if candidate["kind"] == "proof")
    table_candidate = next(candidate for candidate in candidates if candidate["kind"] == "experiment")

    assert proof_candidate["target_file"].endswith("theory.tex")
    assert proof_candidate["location_score"] >= 20
    assert proof_candidate["target_context"]["type"] in {"proof", "theorem", "assumption"}
    assert table_candidate["target_context"]["type"] == "table"

    record = inspect_record(tmp_path, proof_candidate["item_id"])
    assert record["item"]["tex_locations"][0]["score"] >= 20
    diff = render_apply_diff(tmp_path, approved_only=False)
    assert f"# {proof_candidate['id']} for {proof_candidate['item_id']}" in diff
    assert "score=" in diff


def test_schema_proof_experiment_reason_and_result_provenance(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)

    assert "candidate_edits.json" in schema_markdown()
    assert "Proof Audit Detail" in proof_audit_for_item(tmp_path, "R001")
    assert "Experiment Command Plan" in experiment_plan_for_item(tmp_path, "R002")
    assert "Revision Reasoning for R001" in reasoning_for_item(tmp_path, "R001")

    record = record_experiment_result(tmp_path, "R002", "results/demo_metrics.csv", "Observed seed-1 baseline comparison.")
    assert record["status"] == "recorded"
    assert (tmp_path / ".revagent" / "experiment_runs.jsonl").exists()

    candidates = propose_candidates(tmp_path, force=True)
    experiment_candidate = next(candidate for candidate in candidates if candidate["kind"] == "experiment")
    assert experiment_candidate["status"] == "proposed"
    assert experiment_candidate["requires_author_text"] is False
    assert "result backfill" in experiment_candidate["content"]

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("proof lane requires author approval" in warning for warning in validation["warnings"])
    assert not any("R002 experiment result provenance is not recorded" in warning for warning in validation["warnings"])


def test_review_analysis_cli_planning_and_llm_context(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)

    proof = analyze_review_item(tmp_path, "R001")
    assert proof["kind"] == "proof"
    assert "author-verified proof obligation" in " ".join(proof["evidence_needs"])
    assert proof["author_verification"]

    analyses = analyze_all_review_items(tmp_path)
    assert set(analyses) == {"R001", "R002", "R003"}
    assert "Review Analyses" in render_review_analyses(analyses)
    assert "recorded artifact hash" in " ".join(analyses["R002"]["evidence_needs"])
    assert "conservative clarification" in analyses["R003"]["manuscript_action"].lower()

    plan = plan_item(tmp_path, "R001", force=True)
    assert plan["review_analysis_id"] == "R001"
    assert any("Requested change" in text or "Requested change:" in text for text in plan["reviewer_intent_decomposition"])

    context = build_llm_context(tmp_path, "R001")
    assert context["review_analysis"]["item_id"] == "R001"

    reasoning = reasoning_for_item(tmp_path, "R001")
    assert "Claim Targets" in reasoning
    assert "Evidence Needs" in reasoning

    monkeypatch.chdir(tmp_path)
    assert main(["review-analysis", "R001"]) == 0
    assert main(["analyze-review", "--all", "--force"]) == 0


def test_llm_draft_context_updates_review_item_and_candidate_without_approval(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)

    context = build_llm_context(tmp_path, "R003")
    assert "contribution" in context["item"]["comment"].lower()
    assert context["journal_profile"]["display_name"]
    assert context["location"]
    assert "paper.tex" in context["nearby_context"]["file"]

    manuscript_draft = draft_item_with_llm(tmp_path, "R003")
    assert manuscript_draft["draft_source"] == "llm_draft"
    assert manuscript_draft["review_status"] == "drafted"
    assert manuscript_draft["reviewer_intent"]["lane"] == "manuscript"
    assert (tmp_path / ".revagent" / "llm_drafts.json").exists()
    assert "LLM Drafts" in (tmp_path / ".revagent" / "llm_drafts.md").read_text(encoding="utf-8")

    config = load_config(tmp_path)
    items = json.loads((config.workspace / "review_items.json").read_text(encoding="utf-8"))
    assert next(item for item in items if item["id"] == "R003")["draft_source"] == "llm_draft"
    manuscript_candidate = next(candidate for candidate in load_candidates(config) if candidate["item_id"] == "R003")
    assert manuscript_candidate["draft_source"] == "llm_draft"
    assert manuscript_candidate["status"] == "proposed"
    assert manuscript_candidate["approved_at"] == ""
    assert manuscript_candidate["applied_at"] == ""

    proof_draft = draft_item_with_llm(tmp_path, "R001")
    assert proof_draft["reviewer_intent"]["lane"] == "proof"
    proof_candidate = next(candidate for candidate in load_candidates(config) if candidate["item_id"] == "R001")
    assert proof_candidate["status"] == "blocked"
    assert proof_candidate["requires_author_text"] is True

    monkeypatch.chdir(tmp_path)
    assert main(["llm-draft", "R003"]) == 0
    assert main(["llm-draft", "--all", "--force"]) == 0
    assert main(["llm-draft"]) == 1


def test_llm_review_gate_accept_reject_and_edit_without_candidate_approval(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    draft_all_with_llm(tmp_path)

    assert "Review status: drafted" in llm_review(tmp_path, "R003")
    accepted = llm_accept(tmp_path, "R003")
    assert accepted["review_status"] == "accepted"
    assert accepted["quality_status"] == "unchecked"

    config = load_config(tmp_path)
    manuscript_candidate = next(candidate for candidate in load_candidates(config) if candidate["item_id"] == "R003")
    assert manuscript_candidate["status"] == "proposed"
    assert manuscript_candidate["approved_at"] == ""
    assert manuscript_candidate["applied_at"] == ""

    rejected = llm_reject(tmp_path, "R002", "Needs experiment provenance wording.")
    assert rejected["review_status"] == "rejected"
    assert rejected["review_note"] == "Needs experiment provenance wording."

    (tmp_path / "response_edit.md").write_text("**Response.** We clarified the contribution after author review.", encoding="utf-8")
    (tmp_path / "candidate_edit.tex").write_text("We clarify the contribution and scope in the revised manuscript.", encoding="utf-8")
    edited = llm_edit(tmp_path, "R003", response_file="response_edit.md", candidate_file="candidate_edit.tex")
    assert edited["review_status"] == "edited"
    assert edited["quality_status"] == "unchecked"
    assert "author review" in edited["response_draft"]
    assert "contribution and scope" in edited["candidate_text"]

    manuscript_candidate = next(candidate for candidate in load_candidates(config) if candidate["item_id"] == "R003")
    assert manuscript_candidate["status"] == "proposed"
    assert "contribution and scope" in manuscript_candidate["content"]
    assert "LLM draft edited" in (config.workspace / "decision_log.md").read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main(["llm-review", "R003"]) == 0
    assert main(["llm-accept", "R003"]) == 0
    assert main(["llm-reject", "R002", "--note", "Still too speculative."]) == 0
    assert main(["llm-edit", "R003", "--response-file", "response_edit.md", "--candidate-file", "candidate_edit.tex"]) == 0
    assert main(["llm-edit", "R003"]) == 1


def test_llm_quality_gate_blocks_unverified_proof_and_experiment_claims(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    draft_all_with_llm(tmp_path)

    proof = llm_check(tmp_path, "R001")
    assert proof["quality_status"] == "failed"
    assert any("proof workflow approval" in issue for issue in proof["quality_issues"])

    experiment = llm_check(tmp_path, "R002")
    assert experiment["quality_status"] == "failed"
    assert any("experiment provenance" in issue or "recorded provenance" in issue for issue in experiment["quality_issues"])

    accepted = llm_accept(tmp_path, "R003")
    assert accepted["quality_status"] == "unchecked"
    manuscript = llm_check(tmp_path, "R003")
    assert manuscript["quality_status"] == "passed"
    assert manuscript["quality_issues"] == []

    config = load_config(tmp_path)
    assert not any(candidate["status"] in {"approved", "applied"} for candidate in load_candidates(config))
    assert "Quality Issues" in (config.workspace / "llm_drafts.md").read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main(["llm-check", "R003"]) == 0
    assert main(["llm-check", "--all"]) == 0
    assert main(["llm-check"]) == 1


def test_llm_candidate_approval_gate_requires_reviewed_quality_passed_draft(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    draft_all_with_llm(tmp_path)

    config = load_config(tmp_path)
    manuscript_candidate = next(candidate for candidate in load_candidates(config) if candidate["item_id"] == "R003")
    with pytest.raises(ValueError, match="accepted or edited LLM draft"):
        approve_candidate(tmp_path, manuscript_candidate["id"])

    llm_accept(tmp_path, "R003")
    with pytest.raises(ValueError, match="passed LLM quality check"):
        approve_candidate(tmp_path, manuscript_candidate["id"])

    llm_check(tmp_path, "R003")
    incorporate_drafts(tmp_path)
    approved = approve_candidate(tmp_path, manuscript_candidate["id"])
    assert approved["status"] == "approved"

    record = inspect_record(tmp_path, manuscript_candidate["id"])
    assert record["candidate"]["llm_review_status"] == "accepted"
    assert record["candidate"]["llm_quality_status"] == "passed"


def test_llm_candidate_gate_blocks_divergent_text_but_allows_author_edit(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    draft_all_with_llm(tmp_path)
    llm_accept(tmp_path, "R003")
    llm_check(tmp_path, "R003")
    incorporate_drafts(tmp_path)

    config = load_config(tmp_path)
    candidates = load_candidates(config)
    manuscript_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R003")
    manuscript_candidate["content"] = "Divergent unreviewed manuscript text."
    for index, candidate in enumerate(candidates):
        if candidate["id"] == manuscript_candidate["id"]:
            candidates[index] = manuscript_candidate
            break
    (config.workspace / "candidate_edits.json").write_text(json.dumps(candidates, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="content differs"):
        approve_candidate(tmp_path, manuscript_candidate["id"])

    (tmp_path / "author_text.tex").write_text("Author-approved manuscript text.", encoding="utf-8")
    edit_candidate(tmp_path, manuscript_candidate["id"], "author_text.tex")
    approved = approve_candidate(tmp_path, manuscript_candidate["id"])
    assert approved["status"] == "approved"
    assert approved["author_edited"] is True


def test_validate_flags_invalid_approved_llm_candidate(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    draft_all_with_llm(tmp_path)

    config = load_config(tmp_path)
    candidates = load_candidates(config)
    manuscript_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R003")
    manuscript_candidate["status"] = "approved"
    manuscript_candidate["approved_at"] = "manual-test"
    for index, candidate in enumerate(candidates):
        if candidate["id"] == manuscript_candidate["id"]:
            candidates[index] = manuscript_candidate
            break
    (config.workspace / "candidate_edits.json").write_text(json.dumps(candidates, indent=2) + "\n", encoding="utf-8")

    validation = validate_workspace(tmp_path)
    assert not validation["ok"]
    assert any("accepted or edited LLM draft" in issue for issue in validation["issues"])


def test_revision_provenance_tracks_llm_candidate_approval_and_apply(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    draft_all_with_llm(tmp_path)
    llm_accept(tmp_path, "R003")
    llm_check(tmp_path, "R003")
    incorporate_drafts(tmp_path)

    config = load_config(tmp_path)
    manuscript_candidate = next(candidate for candidate in load_candidates(config) if candidate["item_id"] == "R003")
    approve_candidate(tmp_path, manuscript_candidate["id"])
    apply_approved_candidates(tmp_path)

    provenance = write_revision_provenance(tmp_path)
    record = next(item for item in provenance["items"] if item["item_id"] == "R003")
    assert record["provenance_status"] == "applied"
    assert record["llm_draft"]["review_status"] == "accepted"
    assert record["llm_draft"]["quality_status"] == "passed"
    assert record["candidates"][0]["status"] == "applied"
    assert record["candidates"][0]["apply_log"]
    assert "R003" in render_revision_provenance(provenance, "R003")
    assert (config.workspace / "revision_provenance.json").exists()
    assert "Revision Provenance" in (config.workspace / "revision_provenance.md").read_text(encoding="utf-8")

    validation = validate_workspace(tmp_path)
    assert validation["ok"]

    monkeypatch.chdir(tmp_path)
    assert main(["provenance", "R003"]) == 0
    assert main(["provenance", "R999"]) == 1


def test_revision_provenance_covers_proof_and_experiment_gates_and_export(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    proof_plan_for_item(tmp_path, "R001")
    proof_approve(tmp_path, "R001", "Author verified proof workflow.")
    experiment_contract(tmp_path, "R002")
    (tmp_path / "results" / "demo_metrics.csv").write_text("method,error\nPINN,0.10\n", encoding="utf-8")
    experiment_artifact(tmp_path, "R002", "results/demo_metrics.csv", "table", "Observed seed-1 comparison.")
    (tmp_path / "backfill.tex").write_text("Observed seed-1 comparison.", encoding="utf-8")
    experiment_incorporate(tmp_path, "R002", "tab:demo", "observed_result", "backfill.tex")

    provenance = write_revision_provenance(tmp_path)
    proof_record = next(item for item in provenance["items"] if item["item_id"] == "R001")
    experiment_record = next(item for item in provenance["items"] if item["item_id"] == "R002")
    assert proof_record["proof"]["approval_status"] == "approved"
    assert not proof_record["proof"]["open_obligations"]
    assert experiment_record["experiment"]["artifacts"]
    assert experiment_record["experiment"]["backfill_targets"]

    artifact_dir = export_artifacts(tmp_path)
    assert (artifact_dir / "revision_provenance.json").exists()
    assert (artifact_dir / "revision_provenance.md").exists()
    assert "revision_provenance.md" in (artifact_dir / "MANIFEST.md").read_text(encoding="utf-8")


def test_revision_provenance_stale_detection_validate_and_agent(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    write_revision_provenance(tmp_path)

    config = load_config(tmp_path)
    assert not provenance_missing_or_stale(config)

    candidates = load_candidates(config)
    manuscript_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R003")
    manuscript_candidate["content"] = "Changed after provenance snapshot."
    (config.workspace / "candidate_edits.json").write_text(json.dumps(candidates, indent=2) + "\n", encoding="utf-8")

    assert provenance_missing_or_stale(config)
    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("revision provenance is stale" in warning for warning in validation["warnings"])

    state = build_agent_state(tmp_path)
    assert any(task["kind"] == "provenance" and task["status"] == "pending" for task in state["tasks"])

    write_revision_provenance(tmp_path)
    assert not provenance_missing_or_stale(config)
    refreshed = validate_workspace(tmp_path)
    assert not any("revision provenance is stale" in warning for warning in refreshed["warnings"])


def test_revision_memory_builds_facts_cli_and_export(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    analyze_all_review_items(tmp_path)
    plan_all_items(tmp_path)
    proof_plan_for_item(tmp_path, "R001")
    create_draft(tmp_path)

    memory = write_revision_memory(tmp_path)
    fact = next(item for item in memory["facts"] if item["item_id"] == "R001")
    assert fact["kind"] == "proof"
    assert fact["readiness_status"] == "blocked_manual"
    assert "author proof approval" in fact["manual_actions"]
    assert fact["next_command"].startswith("revagent proof-approve R001")
    assert "R001" in render_revision_memory(memory, "R001")
    assert build_revision_memory(tmp_path)["summary_counts"]

    monkeypatch.chdir(tmp_path)
    assert main(["memory"]) == 0
    assert main(["memory", "R001"]) == 0
    assert main(["memory", "R999"]) == 1
    assert "Revision Memory" in (tmp_path / ".revagent" / "revision_memory.md").read_text(encoding="utf-8")

    artifact_dir = export_artifacts(tmp_path)
    assert (artifact_dir / "revision_memory.json").exists()
    assert (artifact_dir / "revision_memory.md").exists()


def test_openai_compatible_provider_env_validation_and_mock_response(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)

    for name in ("REVAGENT_LLM_BASE_URL", "REVAGENT_LLM_API_KEY", "REVAGENT_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    try:
        draft_item_with_llm(tmp_path, "R003", provider="openai-compatible", force=True)
        assert False, "openai-compatible provider should require environment configuration"
    except ValueError as exc:
        assert "missing OpenAI-compatible provider environment variables" in str(exc)

    config = load_config(tmp_path)
    assert load_llm_drafts(config) == {}

    monkeypatch.setenv("REVAGENT_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("REVAGENT_LLM_API_KEY", "secret-test-key")
    monkeypatch.setenv("REVAGENT_LLM_MODEL", "test-model")

    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            content = {
                "reviewer_intent": {"summary": "clarify contribution", "requested_change": "clarify", "lane": "manuscript", "risk": "low"},
                "response_draft": "**Response.** We clarify the contribution.",
                "candidate_text": "We clarify the contribution in the revised manuscript.",
                "risk_notes": ["author should verify wording"],
                "context_summary": "mock provider response",
            }
            return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode("utf-8")

    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["authorization"] = req.headers["Authorization"]
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return MockResponse()

    monkeypatch.setattr("revagent.llm.request.urlopen", fake_urlopen)
    draft = draft_item_with_llm(tmp_path, "R003", provider="openai-compatible", force=True)
    assert draft["provider"] == "openai-compatible"
    assert draft["review_status"] == "drafted"
    assert draft["quality_status"] == "unchecked"
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret-test-key"
    assert captured["payload"]["model"] == "test-model"
    assert "secret-test-key" not in (config.workspace / "llm_drafts.json").read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main(["llm-draft", "R003", "--provider", "fake", "--force"]) == 0


def test_openai_compatible_provider_malformed_response_does_not_write_draft(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    monkeypatch.setenv("REVAGENT_LLM_BASE_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("REVAGENT_LLM_API_KEY", "secret-test-key")
    monkeypatch.setenv("REVAGENT_LLM_MODEL", "test-model")

    class BadResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps({"response_draft": "missing required fields"})}}]}).encode("utf-8")

    monkeypatch.setattr("revagent.llm.request.urlopen", lambda req, timeout: BadResponse())
    try:
        draft_item_with_llm(tmp_path, "R003", provider="openai-compatible", force=True)
        assert False, "malformed provider response should fail"
    except ValueError as exc:
        assert "missing fields" in str(exc)

    config = load_config(tmp_path)
    assert load_llm_drafts(config) == {}


def test_incorporate_drafts_uses_only_accepted_quality_passed_llm_drafts(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    draft_all_with_llm(tmp_path)

    (tmp_path / "response_edit.md").write_text("**Response.** Accepted quality-passed contribution response.", encoding="utf-8")
    (tmp_path / "candidate_edit.tex").write_text("We add the accepted quality-passed contribution clarification.", encoding="utf-8")
    llm_edit(tmp_path, "R003", response_file="response_edit.md", candidate_file="candidate_edit.tex")
    llm_check(tmp_path, "R003")
    llm_accept(tmp_path, "R002")

    result = incorporate_drafts(tmp_path)
    assert result["eligible"] == ["R003"]
    assert any("R002" in warning for warning in result["warnings"])

    config = load_config(tmp_path)
    response_letter = (config.workspace / "response_letter.md").read_text(encoding="utf-8")
    assert "Accepted quality-passed contribution response" in response_letter
    assert "numerical evidence" in response_letter

    manuscript_candidate = next(candidate for candidate in load_candidates(config) if candidate["item_id"] == "R003")
    assert manuscript_candidate["status"] == "proposed"
    assert manuscript_candidate["approved_at"] == ""
    assert manuscript_candidate["applied_at"] == ""
    assert "accepted quality-passed contribution" in manuscript_candidate["content"]
    assert "LLM drafts incorporated" in (config.workspace / "decision_log.md").read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main(["incorporate-drafts"]) == 0


def test_experiment_contract_artifact_hash_backfill_and_cli(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)

    manifest = experiment_contract(tmp_path, "R002")
    assert manifest["status"] == "planned"
    assert (tmp_path / ".revagent" / "experiment_manifests.json").exists()
    assert "Experiment Manifest R002" in (tmp_path / ".revagent" / "experiment_manifests.md").read_text(encoding="utf-8")

    (tmp_path / "results" / "demo_metrics.csv").write_text("method,error\nPINN,0.10\n", encoding="utf-8")
    artifact = experiment_artifact(tmp_path, "R002", "results/demo_metrics.csv", "table", "Observed seed-1 comparison.")
    assert len(artifact["sha256"]) == 64

    candidates = propose_candidates(tmp_path, force=True)
    experiment_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R002")
    assert experiment_candidate["status"] == "proposed"

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("without a backfill target mapping" in warning for warning in validation["warnings"])

    (tmp_path / "backfill.tex").write_text("The recorded table reports the observed seed-1 comparison.", encoding="utf-8")
    backfill = experiment_incorporate(tmp_path, "R002", "tab:demo", "observed_result", "backfill.tex")
    assert backfill["target"] == "tab:demo"

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert not any("without a backfill target mapping" in warning for warning in validation["warnings"])

    (tmp_path / "results" / "demo_metrics.csv").write_text("method,error\nPINN,0.20\n", encoding="utf-8")
    validation = validate_workspace(tmp_path)
    assert any("experiment artifact hash changed" in warning for warning in validation["warnings"])

    monkeypatch.chdir(tmp_path)
    assert main(["experiment-contract", "R002"]) == 0
    assert main(["experiment-artifact", "R002", "--path", "results/demo_metrics.csv", "--kind", "table", "--note", "Re-recorded artifact."]) == 0
    assert main(["experiment-incorporate", "R002", "--target", "tab:demo", "--field", "observed_result", "--text-file", "backfill.tex"]) == 0


def test_experiment_run_preview_record_and_failure_validation(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    experiment_contract(tmp_path, "R002")
    config = load_config(tmp_path)
    manifests = json.loads((config.workspace / "experiment_manifests.json").read_text(encoding="utf-8"))
    manifests["R002"]["command_template"] = f'"{sys.executable}" scripts/run_demo.py'
    manifests["R002"]["cwd"] = str(tmp_path)
    manifests["R002"]["expected_artifacts"] = ["results/runner_metrics.csv"]
    (config.workspace / "experiment_manifests.json").write_text(json.dumps(manifests, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "scripts" / "run_demo.py").write_text(
        "from pathlib import Path\n"
        "Path('results').mkdir(exist_ok=True)\n"
        "Path('results/runner_metrics.csv').write_text('method,error\\nPINN,0.10\\n', encoding='utf-8')\n"
        "print('runner ok')\n",
        encoding="utf-8",
    )

    preview = experiment_run_preview(tmp_path, "R002")
    assert preview["ready"] is True
    assert preview["expected_artifacts"][0]["exists"] is False
    assert load_experiment_run_attempts(config) == []

    monkeypatch.chdir(tmp_path)
    assert main(["experiment-run", "R002", "--dry-run"]) == 0
    assert load_experiment_run_attempts(config) == []

    attempt = experiment_run_record(tmp_path, "R002")
    assert attempt["status"] == "succeeded"
    assert attempt["exit_code"] == 0
    assert attempt["detected_artifacts"][0]["exists"] is True
    assert (config.workspace / attempt["stdout_log"]).exists()
    assert (config.workspace / attempt["stderr_log"]).exists()
    attempts = load_experiment_run_attempts(config)
    assert attempts[-1]["attempt_id"] == attempt["attempt_id"]
    updated = json.loads((config.workspace / "experiment_manifests.json").read_text(encoding="utf-8"))["R002"]
    assert updated["artifacts"][0]["path"] == "results/runner_metrics.csv"
    assert len(updated["artifacts"][0]["sha256"]) == 64
    assert main(["experiment-run", "R002", "--record"]) == 0

    manifests = json.loads((config.workspace / "experiment_manifests.json").read_text(encoding="utf-8"))
    manifests["R002"]["command_template"] = f'"{sys.executable}" scripts/missing_runner.py'
    manifests["R002"]["expected_artifacts"] = ["results/missing_runner.csv"]
    (config.workspace / "experiment_manifests.json").write_text(json.dumps(manifests, indent=2) + "\n", encoding="utf-8")
    failed = experiment_run_record(tmp_path, "R002")
    assert failed["status"] == "failed"
    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("experiment_run_attempts.jsonl" in warning and "failed" in warning for warning in validation["warnings"])


def test_proof_workflow_snapshots_obligations_approval_gate_and_cli(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)

    workflow = proof_plan_for_item(tmp_path, "R001")
    assert workflow["statement_snapshot"]
    assert workflow["proof_snapshot"]
    assert workflow["proof_obligations"][0]["status"] == "open"
    assert (tmp_path / ".revagent" / "proof_workflows.json").exists()
    assert "Proof Workflow R001" in (tmp_path / ".revagent" / "proof_workflows.md").read_text(encoding="utf-8")

    obligation = proof_obligation(tmp_path, "R001", "Verify the stability lemma dependency is sufficient.")
    assert obligation["id"] == "PO002"

    config = load_config(tmp_path)
    proof_candidate = next(candidate for candidate in load_candidates(config) if candidate["kind"] == "proof")
    (tmp_path / "proof_text.tex").write_text("Author-verified proof clarification.", encoding="utf-8")
    edit_candidate(tmp_path, proof_candidate["id"], "proof_text.tex")
    try:
        approve_candidate(tmp_path, proof_candidate["id"], allow_high_risk=True)
        assert False, "proof candidate approval should require proof workflow approval"
    except ValueError as exc:
        assert "proof workflow approval gate" in str(exc)

    approved_workflow = proof_approve(tmp_path, "R001", "Author verified the proof change and dependencies.")
    assert approved_workflow["approval_status"] == "approved"
    assert all(ob["status"] == "closed" for ob in approved_workflow["proof_obligations"])
    approved_candidate = approve_candidate(tmp_path, proof_candidate["id"], allow_high_risk=True)
    assert approved_candidate["status"] == "approved"
    assert approved_candidate["proof_gate_status"] == "approved"

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert not any("R001 proof workflow has" in warning for warning in validation["warnings"])

    monkeypatch.chdir(tmp_path)
    assert main(["proof-plan", "R001"]) == 0
    assert main(["proof-obligation", "R001", "--add", "Check theorem statement did not change."]) == 0
    assert main(["proof-approve", "R001", "--note", "Author re-confirmed proof workflow."]) == 0


def test_item_planner_generates_structured_plans_and_cli(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)

    proof_plan = plan_item(tmp_path, "R001")
    experiment_plan = plan_item(tmp_path, "R002")
    manuscript_plan = plan_item(tmp_path, "R003")

    assert proof_plan["planning_status"] == "planned"
    assert any("author" in question.lower() for question in proof_plan["blocking_questions"])
    assert any("recorded result" in evidence.lower() for evidence in experiment_plan["required_evidence"])
    assert manuscript_plan["manuscript_edit_plan"]
    assert (tmp_path / ".revagent" / "item_plans.json").exists()
    assert "Item Plan R001" in (tmp_path / ".revagent" / "item_plans.md").read_text(encoding="utf-8")

    items = {item["id"]: item for item in json.loads((tmp_path / ".revagent" / "review_items.json").read_text(encoding="utf-8"))}
    assert items["R001"]["planning_status"] == "planned"

    monkeypatch.chdir(tmp_path)
    assert main(["plan-item", "R001"]) == 0
    assert main(["plan-item", "--all"]) == 0
    assert main(["plan-item"]) == 1

    planned_items = load_config(tmp_path)
    assert planned_items.workspace.exists()


def test_planning_status_transitions_close_and_reopen(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    plan_all_items(tmp_path)
    create_draft(tmp_path)

    config = load_config(tmp_path)
    items = {item["id"]: item for item in json.loads((config.workspace / "review_items.json").read_text(encoding="utf-8"))}
    assert items["R003"]["planning_status"] == "drafted"

    record_experiment_result(tmp_path, "R002", "results/demo_metrics.csv", "Observed seed-1 baseline comparison.")
    items = {item["id"]: item for item in json.loads((config.workspace / "review_items.json").read_text(encoding="utf-8"))}
    assert items["R002"]["planning_status"] == "evidence_ready"

    candidates = load_candidates(config)
    manuscript_candidate = next(candidate for candidate in candidates if candidate["item_id"] == "R003")
    (tmp_path / "author_text.tex").write_text("We clarified the contribution.", encoding="utf-8")
    edit_candidate(tmp_path, manuscript_candidate["id"], "author_text.tex")
    approve_candidate(tmp_path, manuscript_candidate["id"])
    items = {item["id"]: item for item in json.loads((config.workspace / "review_items.json").read_text(encoding="utf-8"))}
    assert items["R003"]["planning_status"] == "approved"

    apply_approved_candidates(tmp_path)
    items = {item["id"]: item for item in json.loads((config.workspace / "review_items.json").read_text(encoding="utf-8"))}
    assert items["R003"]["planning_status"] == "incorporated"

    closed = close_item(tmp_path, "R003")
    assert closed["planning_status"] == "closed"
    reopened = reopen_item(tmp_path, "R003")
    assert reopened["planning_status"] == "planned"


def test_workspace_migration_dry_run_and_apply(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    revision = tmp_path / ".revagent" / "revision.yaml"
    revision.write_text(
        "\n".join(line for line in revision.read_text(encoding="utf-8").splitlines() if not line.startswith("schema_version:")) + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".revagent" / "decision_log.md").unlink()
    (tmp_path / ".revagent" / "candidate_edits.json").unlink()
    (tmp_path / ".revagent" / "item_plans.json").unlink()
    (tmp_path / ".revagent" / "item_plans.md").unlink()
    (tmp_path / ".revagent" / "proof_workflows.json").unlink()
    (tmp_path / ".revagent" / "proof_workflows.md").unlink()
    (tmp_path / ".revagent" / "experiment_manifests.json").unlink()
    (tmp_path / ".revagent" / "experiment_manifests.md").unlink()
    (tmp_path / ".revagent" / "agent_state.json").unlink()
    (tmp_path / ".revagent" / "agent_state.md").unlink()
    (tmp_path / ".revagent" / "agent_runs.jsonl").unlink()
    (tmp_path / ".revagent" / "agent_runs.md").unlink()
    (tmp_path / ".revagent" / "agent_policy.json").unlink()
    (tmp_path / ".revagent" / "agent_policy.md").unlink()
    (tmp_path / ".revagent" / "agent_report.md").unlink()
    (tmp_path / ".revagent" / "agent_sessions.jsonl").unlink()
    (tmp_path / ".revagent" / "agent_sessions.md").unlink()
    (tmp_path / ".revagent" / "agent_decisions.json").unlink()
    (tmp_path / ".revagent" / "agent_decisions.md").unlink()
    (tmp_path / ".revagent" / "agent_eval_report.json").unlink()
    (tmp_path / ".revagent" / "agent_eval_report.md").unlink()
    (tmp_path / ".revagent" / "llm_drafts.json").unlink()
    (tmp_path / ".revagent" / "llm_drafts.md").unlink()
    (tmp_path / ".revagent" / "experiment_run_attempts.jsonl").unlink()
    (tmp_path / ".revagent" / "experiment_run_attempts.md").unlink()
    (tmp_path / ".revagent" / "review_analyses.json").unlink()
    (tmp_path / ".revagent" / "review_analyses.md").unlink()
    (tmp_path / ".revagent" / "revision_provenance.json").unlink()
    (tmp_path / ".revagent" / "revision_provenance.md").unlink()

    items_path = tmp_path / ".revagent" / "review_items.json"
    import json

    items = json.loads(items_path.read_text(encoding="utf-8"))
    for item in items:
        for key in (
            "lane",
            "severity",
            "source",
            "reviewer",
            "requires_author_input",
            "evidence_required",
            "planning_status",
            "revision_plan",
            "completion_criteria",
            "blocking_questions",
            "required_evidence",
        ):
            item.pop(key, None)
        if item.get("proof_lane"):
            for key in ("statement_snapshot", "proof_snapshot", "proof_obligations", "workflow_status", "proof_workflow_id"):
                item["proof_lane"].pop(key, None)
    items_path.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    (tmp_path / ".revagent" / "llm_drafts.json").write_text(
        json.dumps({"R001": {"item_id": "R001", "provider": "fake", "draft_source": "llm_draft"}}, indent=2) + "\n",
        encoding="utf-8",
    )

    dry = migrate_workspace(tmp_path, dry_run=True)
    assert dry["actions"]
    assert "schema_version" in render_migration_report(dry)
    assert not (tmp_path / ".revagent" / "decision_log.md").exists()

    validation = validate_workspace(tmp_path)
    assert not validation["ok"]
    assert any("workspace migration available" in warning for warning in validation["warnings"])

    applied = migrate_workspace(tmp_path, dry_run=False)
    assert applied["changed"]
    assert (tmp_path / ".revagent" / "decision_log.md").exists()
    assert (tmp_path / ".revagent" / "candidate_edits.json").exists()
    assert f"schema_version: {CURRENT_SCHEMA_VERSION}" in revision.read_text(encoding="utf-8")
    migrated_items = json.loads(items_path.read_text(encoding="utf-8"))
    assert all("lane" in item and "reviewer" in item and "planning_status" in item for item in migrated_items)
    assert (tmp_path / ".revagent" / "item_plans.json").exists()
    assert (tmp_path / ".revagent" / "item_plans.md").exists()
    assert (tmp_path / ".revagent" / "review_analyses.json").exists()
    assert (tmp_path / ".revagent" / "review_analyses.md").exists()
    assert (tmp_path / ".revagent" / "proof_workflows.json").exists()
    assert (tmp_path / ".revagent" / "proof_workflows.md").exists()
    assert (tmp_path / ".revagent" / "experiment_manifests.json").exists()
    assert (tmp_path / ".revagent" / "experiment_manifests.md").exists()
    assert (tmp_path / ".revagent" / "experiment_run_attempts.jsonl").exists()
    assert (tmp_path / ".revagent" / "experiment_run_attempts.md").exists()
    assert (tmp_path / ".revagent" / "agent_state.json").exists()
    assert (tmp_path / ".revagent" / "agent_state.md").exists()
    assert (tmp_path / ".revagent" / "agent_runs.jsonl").exists()
    assert (tmp_path / ".revagent" / "agent_runs.md").exists()
    assert (tmp_path / ".revagent" / "agent_policy.json").exists()
    assert (tmp_path / ".revagent" / "agent_policy.md").exists()
    assert (tmp_path / ".revagent" / "experiment_run_attempts.jsonl").exists()
    assert (tmp_path / ".revagent" / "experiment_run_attempts.md").exists()
    assert (tmp_path / ".revagent" / "agent_report.md").exists()
    assert (tmp_path / ".revagent" / "agent_dashboard.md").exists()
    assert (tmp_path / ".revagent" / "agent_sessions.jsonl").exists()
    assert (tmp_path / ".revagent" / "agent_sessions.md").exists()
    assert (tmp_path / ".revagent" / "agent_decisions.json").exists()
    assert (tmp_path / ".revagent" / "agent_decisions.md").exists()
    assert (tmp_path / ".revagent" / "agent_eval_report.json").exists()
    assert (tmp_path / ".revagent" / "agent_eval_report.md").exists()
    assert (tmp_path / ".revagent" / "external_agent_runs.jsonl").exists()
    assert (tmp_path / ".revagent" / "external_agent_runs.md").exists()
    assert (tmp_path / ".revagent" / "monitor.md").exists()
    assert (tmp_path / ".revagent" / "llm_drafts.json").exists()
    assert (tmp_path / ".revagent" / "llm_drafts.md").exists()
    assert (tmp_path / ".revagent" / "review_analyses.json").exists()
    assert (tmp_path / ".revagent" / "review_analyses.md").exists()
    assert (tmp_path / ".revagent" / "revision_provenance.json").exists()
    assert (tmp_path / ".revagent" / "revision_provenance.md").exists()
    assert (tmp_path / ".revagent" / "revision_memory.json").exists()
    assert (tmp_path / ".revagent" / "revision_memory.md").exists()
    migrated_draft = json.loads((tmp_path / ".revagent" / "llm_drafts.json").read_text(encoding="utf-8"))["R001"]
    assert migrated_draft["review_status"] == "drafted"
    assert migrated_draft["quality_status"] == "unchecked"
    migrated_provenance = json.loads((tmp_path / ".revagent" / "revision_provenance.json").read_text(encoding="utf-8"))
    assert migrated_provenance["source_fingerprint"]
    post = validate_workspace(tmp_path)
    assert post["ok"]

    monkeypatch.chdir(tmp_path)
    assert main(["migrate", "--dry-run"]) == 0


def test_agent_state_files_created_on_init(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    assert (tmp_path / ".revagent" / "agent_state.json").exists()
    assert (tmp_path / ".revagent" / "agent_state.md").exists()
    assert (tmp_path / ".revagent" / "agent_runs.jsonl").exists()
    assert (tmp_path / ".revagent" / "agent_runs.md").exists()
    assert (tmp_path / ".revagent" / "agent_policy.json").exists()
    assert (tmp_path / ".revagent" / "agent_policy.md").exists()
    assert (tmp_path / ".revagent" / "agent_report.md").exists()
    assert (tmp_path / ".revagent" / "agent_sessions.jsonl").exists()
    assert (tmp_path / ".revagent" / "agent_sessions.md").exists()
    assert (tmp_path / ".revagent" / "agent_decisions.json").exists()
    assert (tmp_path / ".revagent" / "agent_decisions.md").exists()
    assert (tmp_path / ".revagent" / "agent_eval_report.json").exists()
    assert (tmp_path / ".revagent" / "agent_eval_report.md").exists()
    assert (tmp_path / ".revagent" / "external_agent_runs.jsonl").exists()
    assert (tmp_path / ".revagent" / "external_agent_runs.md").exists()
    assert (tmp_path / ".revagent" / "monitor.md").exists()
    assert (tmp_path / ".revagent" / "llm_drafts.json").exists()
    assert (tmp_path / ".revagent" / "llm_drafts.md").exists()
    assert (tmp_path / ".revagent" / "review_analyses.json").exists()
    assert (tmp_path / ".revagent" / "review_analyses.md").exists()
    assert (tmp_path / ".revagent" / "revision_provenance.json").exists()
    assert (tmp_path / ".revagent" / "revision_provenance.md").exists()
    assert (tmp_path / ".revagent" / "revision_memory.json").exists()
    assert (tmp_path / ".revagent" / "revision_memory.md").exists()
    assert not provenance_missing_or_stale(load_config(tmp_path))
    state = json.loads((tmp_path / ".revagent" / "agent_state.json").read_text(encoding="utf-8"))
    assert state["tasks"] == []


def test_agent_status_builds_queue_without_executing_safe_tasks(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    state = build_agent_state(tmp_path)
    kinds = [task["kind"] for task in state["tasks"]]
    assert "plan_workspace" in kinds
    assert "review_analysis" in kinds
    assert "plan_item" in kinds
    assert "proof_plan" in kinds
    assert "experiment_contract" in kinds
    assert "validate" in kinds
    assert not (tmp_path / ".revagent" / "proof_workflows.json").read_text(encoding="utf-8").strip("{}\n ")

    monkeypatch.chdir(tmp_path)
    assert main(["agent-status"]) == 0
    persisted = json.loads((tmp_path / ".revagent" / "agent_state.json").read_text(encoding="utf-8"))
    assert persisted["summary"]["pending"] >= 1


def test_agent_run_limit_executes_one_safe_task(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    monkeypatch.chdir(tmp_path)
    assert main(["agent-run", "--limit", "1"]) == 0
    state = json.loads((tmp_path / ".revagent" / "agent_state.json").read_text(encoding="utf-8"))
    assert state["summary"]["done"] == 1
    assert state["tasks"][0]["kind"] == "plan_workspace"
    assert state["tasks"][0]["status"] == "done"
    runs = load_agent_runs(load_config(tmp_path))
    assert len(runs) == 1
    assert runs[0]["kind"] == "plan_workspace"
    assert runs[0]["status"] == "done"
    assert runs[0]["fingerprint"]


def test_agent_run_ledger_skips_unchanged_successful_task(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    config = load_config(tmp_path)
    initial = build_agent_state(tmp_path)
    first_task = initial["tasks"][0]
    (config.workspace / "agent_runs.jsonl").write_text(
        json.dumps(
            {
                "run_id": "manual-test",
                "task_id": first_task["id"],
                "kind": first_task["kind"],
                "item_id": first_task.get("item_id", ""),
                "fingerprint": first_task["fingerprint"],
                "status": "done",
                "started_at": "manual-test",
                "finished_at": "manual-test",
                "result": "already done",
                "error": "",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    second = run_agent_once(tmp_path, limit=1)
    assert second["tasks"][0]["status"] == "skipped"

    runs = load_agent_runs(config)
    assert [entry["status"] for entry in runs[:2]] == ["done", "skipped"]
    assert runs[0]["fingerprint"] == runs[1]["fingerprint"]
    assert runs[1]["task_identity"]
    assert "dependencies" in runs[1]


def test_agent_marks_task_stale_when_input_dependencies_change(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    first = run_agent_once(tmp_path, limit=1)
    assert first["tasks"][0]["kind"] == "validate"
    assert first["tasks"][0]["status"] == "done"

    paper = tmp_path / "paper.tex"
    paper.write_text(paper.read_text(encoding="utf-8").replace("Demo table.", "Demo table with revised caption."), encoding="utf-8")

    state = build_agent_state(tmp_path)
    validate_task = next(task for task in state["tasks"] if task["kind"] == "validate")
    assert validate_task["status"] == "stale"
    assert validate_task["stale_reason"] == "input dependencies changed since the last recorded run"
    assert validate_task["last_run_status"] == "done"

    rerun = run_agent_once(tmp_path, limit=1)
    assert rerun["tasks"][0]["kind"] == "validate"
    assert rerun["tasks"][0]["status"] == "done"


def test_agent_next_and_report_show_manual_gates(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    state = run_agent_once(tmp_path, until_blocked=True)
    assert state["summary"]["blocked"] >= 1

    monkeypatch.chdir(tmp_path)
    assert main(["agent-next"]) == 0
    assert main(["agent-report"]) == 0
    assert main(["monitor"]) == 0
    report = (tmp_path / ".revagent" / "agent_report.md").read_text(encoding="utf-8")
    assert "Manual Gates" in report
    assert "proof_approval_required" in report or "llm_review_required" in report
    dashboard = (tmp_path / ".revagent" / "agent_dashboard.md").read_text(encoding="utf-8")
    assert "Agent Dashboard" in dashboard
    assert "Next Action" in dashboard
    assert "Manual Decisions" in dashboard
    assert "Review analysis:" in dashboard
    assert "proof_approval_required" in dashboard or "llm_review_required" in dashboard


def test_external_agent_dry_run_writes_prompt_and_static_dashboard(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    monkeypatch.chdir(tmp_path)
    assert main(["run", "--dry-run", "--goal", "continue phase one"]) == 0
    prompts = sorted((tmp_path / ".revagent" / "prompts").glob("external-agent-*.md"))
    assert prompts
    prompt = prompts[-1].read_text(encoding="utf-8")
    assert "First, read `plan.md`" in prompt
    assert "continue phase one" in prompt
    assert "Do not approve proof workflows." in prompt
    assert "RevAgent Iteris-Style Roadmap" in prompt
    assert "Current revision memory:" in prompt
    assert load_external_agent_runs(load_config(tmp_path)) == []

    assert main(["dashboard"]) == 0
    dashboard = tmp_path / ".revagent" / "dashboard" / "index.html"
    assert dashboard.exists()
    html = dashboard.read_text(encoding="utf-8")
    assert "RevAgent Dashboard" in html
    assert "Manual Decisions" in html
    assert "Revision Memory" in html
    assert "Recent External Runs" in html


def test_external_agent_run_records_ledger_and_logs(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    monkeypatch.chdir(tmp_path)

    class FakeCompleted:
        returncode = 0
        stdout = "agent stdout"
        stderr = "agent stderr"

    captured = {}

    def fake_run(command, input, text, capture_output, cwd, check):
        captured["command"] = command
        captured["input"] = input
        captured["cwd"] = cwd
        return FakeCompleted()

    monkeypatch.setattr("revagent.external_agent.codex_command", lambda: "codex")
    monkeypatch.setattr("revagent.external_agent.subprocess.run", fake_run)

    result = run_external_agent(tmp_path, goal="mock run")
    assert result["status"] == "done"
    assert captured["command"] == ["codex"]
    assert "mock run" in captured["input"]
    runs = load_external_agent_runs(load_config(tmp_path))
    assert len(runs) == 1
    assert runs[0]["backend"] == "codex"
    assert Path(runs[0]["stdout_path"]).read_text(encoding="utf-8") == "agent stdout"
    assert Path(runs[0]["stderr_path"]).read_text(encoding="utf-8") == "agent stderr"
    assert "External Agent Runs" in (tmp_path / ".revagent" / "external_agent_runs.md").read_text(encoding="utf-8")
    assert main(["run-status"]) == 0
    assert main(["run-status", runs[0]["run_id"]]) == 0


def test_external_agent_run_recover_dry_run_reuses_previous_request(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    monkeypatch.setattr("revagent.external_agent.codex_command", lambda: None)

    monkeypatch.chdir(tmp_path)
    assert main(["run", "--goal", "recover me"]) == 1
    runs = load_external_agent_runs(load_config(tmp_path))
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert "not found" in runs[0]["error"]

    assert main(["run-recover", "--dry-run"]) == 0
    after = load_external_agent_runs(load_config(tmp_path))
    assert after == runs
    prompts = sorted((tmp_path / ".revagent" / "prompts").glob("external-agent-*.md"))
    assert "recover me" in prompts[-1].read_text(encoding="utf-8")


def test_external_agent_run_detach_writes_launch_script_and_queued_record(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    monkeypatch.setattr("revagent.external_agent.codex_command", lambda: "codex")

    monkeypatch.chdir(tmp_path)
    assert main(["run", "--goal", "queued work", "--detach"]) == 0
    runs = load_external_agent_runs(load_config(tmp_path))
    assert len(runs) == 1
    assert runs[0]["status"] == "queued"
    assert runs[0]["goal"] == "queued work"
    launch = Path(runs[0]["launch_script"])
    assert launch.exists()
    assert "codex" in launch.read_text(encoding="utf-8")

    assert main(["run-status", runs[0]["run_id"]]) == 0
    assert main(["run-recover", runs[0]["run_id"], "--dry-run"]) == 0
    assert len(load_external_agent_runs(load_config(tmp_path))) == 1
    assert main(["run-mark", runs[0]["run_id"], "--status", "done", "--note", "Finished from launch script."]) == 0
    marked = load_external_agent_runs(load_config(tmp_path))[0]
    assert marked["status"] == "done"
    assert marked["operator_note"] == "Finished from launch script."
    assert main(["run-mark", "missing", "--status", "canceled"]) == 1


def test_codex_command_prefers_cmd_shim_on_windows(monkeypatch) -> None:
    import revagent.external_agent as external_agent

    calls = []

    def fake_which(name):
        calls.append(name)
        return f"C:/bin/{name}" if name == "codex.cmd" else f"C:/bin/{name}"

    monkeypatch.setattr(external_agent.os, "name", "nt")
    monkeypatch.setattr(external_agent.shutil, "which", fake_which)

    assert external_agent.codex_command() == "C:/bin/codex.cmd"
    assert calls == ["codex.cmd"]


def test_monitor_recommends_manual_recovery_and_writes_report(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    run_agent_once(tmp_path, until_blocked=True)

    monkeypatch.setattr("revagent.external_agent.codex_command", lambda: None)
    monkeypatch.chdir(tmp_path)
    assert main(["monitor"]) == 0
    monitor = (tmp_path / ".revagent" / "monitor.md").read_text(encoding="utf-8")
    assert "RevAgent Monitor" in monitor
    assert "Codex CLI: missing" in monitor
    assert "Recommendation" in monitor
    assert "External Agent" in monitor
    assert "revagent proof-approve" in monitor or "revagent experiment-artifact" in monitor or "revagent llm-review" in monitor
    assert (tmp_path / ".revagent" / "dashboard" / "index.html").exists()


def test_agent_session_plan_resume_blockers_and_complete_check(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    monkeypatch.chdir(tmp_path)
    assert main(["agent-plan", "--goal", "rebuttal-draft"]) == 0
    sessions = load_agent_sessions(load_config(tmp_path))
    assert len(sessions) == 1
    assert sessions[0]["goal"] == "rebuttal-draft"
    assert sessions[0]["status"] == "planned"
    assert any(step["phase"] == "drafting" for step in sessions[0]["steps"])

    assert main(["agent-resume"]) == 0
    resumed = load_agent_sessions(load_config(tmp_path))[-1]
    assert resumed["session_id"] == sessions[0]["session_id"]
    assert resumed["status"] == "blocked"
    assert resumed["linked_run_ids"]
    assert resumed["manual_gates"]
    assert any(gate["kind"] in {"proof_approval_required", "experiment_result_required", "llm_review_required"} for gate in resumed["manual_gates"])

    assert main(["agent-resume", "--watch", "--interval", "0", "--cycles", "1"]) == 0
    watched = load_agent_sessions(load_config(tmp_path))[-1]
    assert watched["status"] == "blocked"
    assert watched["manual_gates"]

    assert main(["agent-blockers"]) == 0
    assert main(["agent-complete-check"]) == 0
    checked = load_agent_sessions(load_config(tmp_path))[-1]
    assert checked["status"] == "blocked"
    assert "Agent Sessions" in (tmp_path / ".revagent" / "agent_sessions.md").read_text(encoding="utf-8")


def test_agent_decision_queue_tracks_resolve_and_dismiss(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    monkeypatch.chdir(tmp_path)
    assert main(["agent-plan", "--goal", "rebuttal-draft"]) == 0
    assert main(["agent-resume"]) == 0
    assert main(["agent-decisions"]) == 0

    config = load_config(tmp_path)
    decisions = load_agent_decisions(config)
    open_decisions = [decision for decision in decisions if decision["status"] == "open"]
    assert open_decisions
    assert any(decision["kind"] == "proof_approval_required" for decision in open_decisions)
    assert any(decision["risk"] == "high" for decision in open_decisions)
    assert "Agent Decisions" in (config.workspace / "agent_decisions.md").read_text(encoding="utf-8")

    proof_decision = next(decision for decision in open_decisions if decision["kind"] == "proof_approval_required")
    assert main(["agent-decision", proof_decision["decision_id"]]) == 0
    assert main(["agent-decision-resolve", proof_decision["decision_id"], "--note", "too early"]) == 1

    assert main(["proof-approve", proof_decision["subject_id"], "--note", "Author verified proof workflow."]) == 0
    assert main(["agent-decision-resolve", proof_decision["decision_id"], "--note", "Proof workflow approved."]) == 0
    resolved = next(decision for decision in load_agent_decisions(config) if decision["decision_id"] == proof_decision["decision_id"])
    assert resolved["status"] == "resolved"
    assert resolved["note"] == "Proof workflow approved."

    remaining_open = [decision for decision in load_agent_decisions(config) if decision["status"] == "open"]
    dismissable = next(decision for decision in remaining_open if decision["decision_id"] != proof_decision["decision_id"])
    assert main(["agent-decision-dismiss", dismissable["decision_id"], "--note", "Author will handle outside RevAgent."]) == 0
    dismissed = next(decision for decision in load_agent_decisions(config) if decision["decision_id"] == dismissable["decision_id"])
    assert dismissed["status"] == "dismissed"
    assert not any(candidate["status"] in {"approved", "applied"} for candidate in load_candidates(config))


def test_agent_eval_runs_builtin_fixtures_and_writes_report(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    monkeypatch.chdir(tmp_path)
    assert main(["agent-eval", "--all"]) == 0
    report = json.loads((tmp_path / ".revagent" / "agent_eval_report.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert {fixture["fixture"] for fixture in report["fixtures"]} == {"full-revision", "safety-gates", "stale-input"}
    assert all(fixture["ok"] for fixture in report["fixtures"])
    markdown = (tmp_path / ".revagent" / "agent_eval_report.md").read_text(encoding="utf-8")
    assert "Agent Eval Report" in markdown
    assert "stale_detected" in markdown

    assert main(["agent-eval", "--fixture", "safety-gates"]) == 0
    focused = json.loads((tmp_path / ".revagent" / "agent_eval_report.json").read_text(encoding="utf-8"))
    assert [fixture["fixture"] for fixture in focused["fixtures"]] == ["safety-gates"]


def test_agent_session_validation_warns_on_bad_jsonl(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    (tmp_path / ".revagent" / "agent_sessions.jsonl").write_text('{"status":"bogus","linked_run_ids":["missing-run"]}\n{bad\n', encoding="utf-8")

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("agent_sessions.jsonl" in warning for warning in validation["warnings"])
    assert any("invalid status" in warning for warning in validation["warnings"])
    assert any("unknown run_id" in warning for warning in validation["warnings"])


def test_validate_warns_on_invalid_agent_decisions(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    (tmp_path / ".revagent" / "agent_decisions.json").write_text(
        json.dumps(
            [
                {"decision_id": "D001", "status": "invalid"},
                {"decision_id": "D001", "status": "resolved"},
                {"status": "open"},
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("invalid status" in warning for warning in validation["warnings"])
    assert any("duplicate decision_id D001" in warning for warning in validation["warnings"])
    assert any("without decision_id" in warning for warning in validation["warnings"])
    assert any("resolved without resolved_at" in warning for warning in validation["warnings"])


def test_validate_warns_on_invalid_agent_eval_report(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    (tmp_path / ".revagent" / "agent_eval_report.json").write_text(json.dumps({"ok": True, "fixtures": "bad"}) + "\n", encoding="utf-8")

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("agent_eval_report.json fixtures field must be a list" in warning for warning in validation["warnings"])


def test_validate_warns_on_invalid_review_analyses(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    (tmp_path / ".revagent" / "review_analyses.json").write_text(
        json.dumps(
            {
                "R999": {"item_id": "R999", "intent_summary": "unknown"},
                "R001": {"item_id": "R002"},
                "R002": "bad",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("unknown item id R999" in warning for warning in validation["warnings"])
    assert any("mismatched item_id R002" in warning for warning in validation["warnings"])
    assert any("analysis R002 must be an object" in warning for warning in validation["warnings"])
    assert any("R003 has no review analysis" in warning for warning in validation["warnings"])


def test_validate_warns_on_malformed_agent_run_ledger(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    (tmp_path / ".revagent" / "agent_runs.jsonl").write_text("{bad json\n", encoding="utf-8")
    (tmp_path / ".revagent" / "experiment_run_attempts.jsonl").write_text("{bad json\n", encoding="utf-8")

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("agent_runs.jsonl" in warning for warning in validation["warnings"])
    assert any("experiment_run_attempts.jsonl" in warning for warning in validation["warnings"])


def test_validate_warns_on_invalid_external_agent_runs(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    (tmp_path / ".revagent" / "external_agent_runs.jsonl").write_text(
        json.dumps(
            {
                "run_id": "E001",
                "backend": "codex",
                "status": "queued",
                "prompt_path": str(tmp_path / ".revagent" / "missing-prompt.md"),
                "launch_script": str(tmp_path / ".revagent" / "missing.cmd"),
                "operator_note": "marked without timestamp",
            },
            sort_keys=True,
        )
        + "\n"
        + json.dumps({"run_id": "E002", "backend": "codex", "status": "bogus", "prompt_path": ""}, sort_keys=True)
        + "\n{bad\n",
        encoding="utf-8",
    )

    validation = validate_workspace(tmp_path)
    assert validation["ok"]
    assert any("prompt_path is missing" in warning for warning in validation["warnings"])
    assert any("launch_script is missing" in warning for warning in validation["warnings"])
    assert any("operator_note without marked_at" in warning for warning in validation["warnings"])
    assert any("invalid status bogus" in warning for warning in validation["warnings"])
    assert any("invalid JSONL in external_agent_runs.jsonl" in warning for warning in validation["warnings"])


def test_agent_run_until_blocked_converges_and_blocks_author_decisions(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")

    state = run_agent_once(tmp_path, until_blocked=True)
    kinds_by_status = {(task["kind"], task["status"]) for task in state["tasks"]}
    assert ("proof_approval_required", "blocked") in kinds_by_status
    assert ("experiment_result_required", "blocked") in kinds_by_status
    assert any(task["kind"] == "draft" and task["status"] == "done" for task in state["tasks"])
    assert any(task["kind"] == "llm_draft" and task["status"] == "done" for task in state["tasks"])
    assert ("llm_review_required", "blocked") in kinds_by_status
    assert any(task["kind"] == "validate" and task["status"] == "done" for task in state["tasks"])
    assert not any(task["kind"] in {"plan_workspace", "review_analysis", "plan_item", "proof_plan", "experiment_contract", "draft", "propose", "llm_draft"} and task["status"] == "pending" for task in state["tasks"])

    config = load_config(tmp_path)
    candidates = load_candidates(config)
    assert candidates
    assert set(load_review_analyses(config)) == {"R001", "R002", "R003"}
    assert load_llm_drafts(config)
    assert all(draft.get("review_status") == "drafted" for draft in load_llm_drafts(config).values())
    assert not any(candidate["status"] in {"approved", "applied"} for candidate in candidates)
    assert not (config.workspace / "apply_log.jsonl").exists()

    monkeypatch.chdir(tmp_path)
    assert main(["agent-run", "--until-blocked"]) == 0


def test_agent_checks_accepted_llm_drafts_and_blocks_failed_quality(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    ingest_comments(tmp_path, "comments.md")
    create_plan(tmp_path)
    create_draft(tmp_path)
    draft_all_with_llm(tmp_path)
    llm_accept(tmp_path, "R001")

    state = run_agent_once(tmp_path, until_blocked=True)
    assert any(task["kind"] == "llm_check" and task["status"] == "done" for task in state["tasks"])
    assert any(task["kind"] == "llm_quality_required" and task["status"] == "blocked" for task in state["tasks"])

    config = load_config(tmp_path)
    drafts = load_llm_drafts(config)
    assert drafts["R001"]["quality_status"] == "failed"
    assert not any(candidate["status"] in {"approved", "applied"} for candidate in load_candidates(config))


def test_public_subsystem_modules_expose_stable_boundaries(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    graph = discover_tex_graph(tmp_path, "paper.tex")
    assert graph["root_file"] == "paper.tex"
    from revagent import agent, candidates, core, experiments, external_agent, latex, llm, memory, planning, proofs, provenance, rendering, review_analysis, reviews, validation, workspace

    assert agent.build_agent_state is build_agent_state
    assert workspace.init_workspace is init_workspace
    assert latex.latex_index is latex_index
    assert reviews.ingest_comments is ingest_comments
    assert candidates.propose_candidates is propose_candidates
    assert llm.draft_item_with_llm is draft_item_with_llm
    assert llm.llm_check_all is llm_check_all
    assert planning.plan_item is plan_item
    assert proofs.proof_plan_for_item is proof_plan_for_item
    assert experiments.experiment_contract is experiment_contract
    assert experiments.experiment_run_preview is experiment_run_preview
    assert rendering.create_draft is create_draft
    assert rendering.incorporate_drafts is incorporate_drafts
    assert provenance.write_revision_provenance is write_revision_provenance
    assert memory.write_revision_memory is write_revision_memory
    assert review_analysis.analyze_review_item is analyze_review_item
    assert external_agent.run_external_agent is run_external_agent
    assert validation.validate_workspace is validate_workspace
    assert core.init_workspace is init_workspace
    assert core.draft_all_with_llm is draft_all_with_llm
    assert core.analyze_review_item is analyze_review_item
    assert core.write_revision_provenance is write_revision_provenance
    assert core.write_revision_memory is write_revision_memory
    assert core.proof_plan_for_item is proof_plan_for_item

    for module in (agent, candidates, experiments, external_agent, latex, llm, memory, planning, proofs, provenance, rendering, review_analysis, reviews, validation, workspace):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "._core_impl" not in source
    assert "._core_impl" not in Path(core.__file__).read_text(encoding="utf-8")


def test_cli_smoke_revision_subsystem_flow(tmp_path: Path, monkeypatch) -> None:
    write_demo_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["init", "--journal", "siam", "--tex-root", ".", "--main-tex", "paper.tex"]) == 0
    assert main(["ingest-comments", "comments.md"]) == 0
    assert main(["plan"]) == 0
    assert main(["analyze-review", "--all"]) == 0
    assert main(["review-analysis", "R001"]) == 0
    assert main(["plan-item", "R001"]) == 0
    assert main(["proof-plan", "R001"]) == 0
    assert main(["experiment-contract", "R002"]) == 0
    assert main(["propose"]) == 0
    assert main(["llm-draft", "--all"]) == 0
    assert main(["llm-review", "R003"]) == 0
    assert main(["llm-accept", "R003"]) == 0
    assert main(["llm-check", "R003"]) == 0
    assert main(["incorporate-drafts"]) == 0
    assert main(["provenance"]) == 0
    assert main(["validate"]) == 0
