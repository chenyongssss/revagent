import hashlib
import json
from pathlib import Path

from revagent.cli import main
from revagent.core import (
    SCHEMA_FILES,
    apply_approved_candidates,
    approve_candidate,
    clean_workspace,
    close_item,
    create_draft,
    create_plan,
    edit_candidate,
    experiment_artifact,
    experiment_contract,
    experiment_incorporate,
    experiment_plan_for_item,
    export_artifacts,
    ingest_comments,
    init_workspace,
    inspect_record,
    latex_index,
    load_config,
    load_candidates,
    plan_all_items,
    plan_item,
    propose_candidates,
    proof_audit_for_item,
    proof_approve,
    proof_obligation,
    proof_plan_for_item,
    reasoning_for_item,
    record_experiment_result,
    reject_candidate,
    reopen_item,
    render_apply_diff,
    restore_backup,
    schema_markdown,
    status,
    validate_workspace,
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
    assert (tmp_path / ".revagent" / "proof_workflows.json").exists()
    assert (tmp_path / ".revagent" / "proof_workflows.md").exists()
    assert (tmp_path / ".revagent" / "experiment_manifests.json").exists()
    assert (tmp_path / ".revagent" / "experiment_manifests.md").exists()
    post = validate_workspace(tmp_path)
    assert post["ok"]

    monkeypatch.chdir(tmp_path)
    assert main(["migrate", "--dry-run"]) == 0


def test_public_subsystem_modules_expose_stable_boundaries(tmp_path: Path) -> None:
    write_demo_project(tmp_path)
    graph = discover_tex_graph(tmp_path, "paper.tex")
    assert graph["root_file"] == "paper.tex"
