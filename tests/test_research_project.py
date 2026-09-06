from pathlib import Path

import pytest

from revagent.research_project import (
    PROJECT_DIRS,
    add_research_task,
    configure_research_provider,
    create_project_family,
    evolve_research_project,
    initialize_research_project,
    MockResearchProvider,
    record_task_result,
    research_frontier,
    run_research_provider,
    verify_task_result,
    write_evidence_report,
    write_research_dashboard,
)


def test_layout_and_resumable_dependency_frontier(tmp_path: Path) -> None:
    initialize_research_project(tmp_path, "Stable solvers", "When is the solver stable?")
    assert all((tmp_path / name).is_dir() for name in PROJECT_DIRS)
    first = add_research_task(tmp_path, "Run baseline")
    second = add_research_task(tmp_path, "Analyze bound", dependencies=[first["task_id"]])
    assert second["state"] == "blocked"
    artifact = tmp_path / "experiments" / "baseline.txt"
    artifact.write_text("residual=0.01\n", encoding="utf-8")
    record_task_result(tmp_path, first["task_id"], [artifact])
    frontier = research_frontier(tmp_path)
    assert next(task for task in frontier["tasks"] if task["task_id"] == second["task_id"])["state"] == "ready"


def test_verified_result_generalization_is_human_gated_and_hash_bound(tmp_path: Path) -> None:
    initialize_research_project(tmp_path, "Parent", "Question")
    task = add_research_task(tmp_path, "Establish result")
    artifact = tmp_path / "experiments" / "result.json"
    artifact.write_text('{"verified": true}\n', encoding="utf-8")
    record_task_result(tmp_path, task["task_id"], [artifact])
    with pytest.raises(ValueError, match="human-verified"):
        evolve_research_project(tmp_path, task["task_id"], tmp_path / "child", "General theorem", "author", "reviewed", approved=True)
    with pytest.raises(ValueError, match="explicit"):
        verify_task_result(tmp_path, task["task_id"], "author", "checked", approved=False)
    verify_task_result(tmp_path, task["task_id"], "author", "checked calculations", approved=True)
    child = evolve_research_project(tmp_path, task["task_id"], tmp_path / "child", "General theorem", "author", "approved scope", approved=True)
    assert child["branch_kind"] == "verified_result_generalization"
    assert child["parent"]["task_id"] == task["task_id"]


def test_changed_evidence_cannot_be_verified(tmp_path: Path) -> None:
    initialize_research_project(tmp_path, "Parent", "Question")
    task = add_research_task(tmp_path, "Establish result")
    artifact = tmp_path / "sources" / "proof.txt"
    artifact.write_text("first", encoding="utf-8")
    record_task_result(tmp_path, task["task_id"], [artifact])
    artifact.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        verify_task_result(tmp_path, task["task_id"], "reviewer", "checked", approved=True)


def test_reports_are_versioned_and_family_is_approved(tmp_path: Path) -> None:
    initialize_research_project(tmp_path, "Parent", "Question")
    task = add_research_task(tmp_path, "Survey")
    first = write_evidence_report(tmp_path, task["task_id"])
    second = write_evidence_report(tmp_path, task["task_id"])
    assert (first["version"], second["version"]) == (1, 2)
    assert first["report_sha256"] != ""
    with pytest.raises(ValueError, match="approval"):
        create_project_family(tmp_path, tmp_path / "family", "Related", "", "", approved=False)
    family = create_project_family(tmp_path, tmp_path / "family", "Related", "lead", "scope accepted", approved=True)
    assert family["branch_kind"] == "human_approved_family"


def test_providers_are_scoped_and_dashboard_is_local(tmp_path: Path) -> None:
    initialize_research_project(tmp_path, "Parent", "Question")
    with pytest.raises(ValueError, match="consent"):
        configure_research_provider(tmp_path, "ollama", "local", "http://127.0.0.1:11434", ["summarize"], 0, consent=False)
    with pytest.raises(ValueError, match="loopback"):
        configure_research_provider(tmp_path, "vllm", "local", "http://example.com", ["summarize"], 0, consent=True)
    provider = configure_research_provider(tmp_path, "claude", "model", "https://api.example.test", ["review"], 2.5, consent=True)
    assert provider["credentials_stored"] is False and provider["task_scopes"] == ["review"]
    dashboard = write_research_dashboard(tmp_path)
    assert "Agents cannot verify evidence" in dashboard.read_text(encoding="utf-8")


def test_provider_plugin_runs_end_to_end_without_crossing_verification_gate(tmp_path: Path) -> None:
    initialize_research_project(tmp_path, "Provider E2E", "Can an adapter produce traceable evidence?")
    task = add_research_task(tmp_path, "Summarize evidence")
    configure_research_provider(tmp_path, "claude", "test-model", "https://api.example.test", ["review"], 1.0, consent=True)
    run = run_research_provider(tmp_path, "claude", task["task_id"], "review", {"claim": "bounded"}, MockResearchProvider())
    assert run["status"] == "unverified_model_output"
    artifact = tmp_path / str(run["artifact"])
    assert artifact.is_file() and len(str(run["sha256"])) == 64
    assert research_frontier(tmp_path)["tasks"][0]["verification"] is None
    with pytest.raises(ValueError, match="scope"):
        run_research_provider(tmp_path, "claude", task["task_id"], "summarize", {}, MockResearchProvider())
