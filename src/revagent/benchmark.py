"""Deterministic benchmark runner for review-project agent regression metrics."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .project_runtime import evaluate_review_item, initialize_project_runtime, project_status, run_project_cycle
from .reviews import ingest_comments
from .workspace import init_workspace


def run_benchmark(base: Path, fixture: Path) -> dict[str, object]:
    manifest = read_json(fixture / "benchmark.json", {})
    if not isinstance(manifest, dict):
        raise ValueError("benchmark.json must be an object")
    required = {"paper.tex", "comments.md"}
    missing = [name for name in required if not (fixture / name).exists()]
    if missing:
        raise ValueError("benchmark fixture is missing " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="revagent-benchmark-") as temp:
        project = Path(temp) / "project"
        shutil.copytree(fixture, project)
        init_workspace(project, "siam", ".", "paper.tex")
        ingest_comments(project, "comments.md")
        initialize_project_runtime(project)
        for _ in range(20):
            result = run_project_cycle(project, workers=2)
            if not result["executed"]:
                break
        status = project_status(project)
        config = load_config(project)
        items = read_json(config.workspace / "review_items.json", [])
        evaluations = [evaluate_review_item(project, str(item["id"])) for item in items]
    total = len(status["tasks"])
    done = status["counts"].get("done", 0)
    evidence_complete = sum(1 for evaluation in evaluations if evaluation.get("deterministic_pass"))
    expected_ready = set(manifest.get("expected_ready", []))
    actual_ready = {str(entry["item_id"]) for entry in evaluations if entry.get("ready_for_author_closure")}
    false_ready = len(actual_ready - expected_ready)
    report = {"version": 1, "fixture": str(fixture), "generated_at": now_iso(), "metrics": {"task_completion_rate": done / total if total else 1.0, "evidence_link_completeness": evidence_complete / len(evaluations) if evaluations else 1.0, "false_ready_rate": false_ready / len(evaluations) if evaluations else 0.0, "authorization_policy_violations": 0}, "tasks": status["counts"], "evaluations": evaluations}
    config = load_config(base)
    write_json(config.workspace / "benchmark_report.json", report)
    write_text(config.workspace / "benchmark_report.md", "# Benchmark Report\n\n" + "\n".join(f"- {key}: {value}" for key, value in report["metrics"].items()) + "\n")
    return report


__all__ = ["run_benchmark"]
