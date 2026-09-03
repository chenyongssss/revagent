import json
from pathlib import Path

import pytest

from revagent.benchmark import run_history_benchmark_suite
from revagent.cli import main
from revagent.workspace import init_workspace


def _case(suite: Path, name: str = "case-a") -> Path:
    case = suite / name; case.mkdir(parents=True)
    labels = {"version": 1, "fixture_id": name, "query": "stability estimate",
              "corpus": [{"history_id": "H-001", "purpose": "precedent", "content": "We answered with a stability estimate."},
                         {"history_id": "H-002", "purpose": "style", "content": "We clarified the mesh notation."}],
              "relevant_history_ids": ["H-001"],
              "label_provenance": {"status": "adjudicated", "source": "independent_human_review", "annotators": ["expert_a", "expert_b"], "adjudicated_by": "expert_b", "labelled_at": "2026-09-03"}}
    (case / "labels.json").write_text(json.dumps(labels), encoding="utf-8"); return case


def _workspace(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")


def test_history_benchmark_measures_adjudicated_retrieval(tmp_path: Path, monkeypatch) -> None:
    _workspace(tmp_path); suite = tmp_path / "suite"; _case(suite)
    report = run_history_benchmark_suite(tmp_path, suite)
    assert report["metrics"] == {"case_count": 1, "recall_at_5": 1.0, "precision_at_5": 0.2, "mean_reciprocal_rank": 1.0, "zero_hit_rate": 0.0}
    assert report["engine"]["kind"] == "sqlite-fts5-bm25"
    assert (tmp_path / ".revagent" / "history_benchmark_report.json").exists()
    monkeypatch.chdir(tmp_path); assert main(["benchmark-history-suite", "--suite", str(suite)]) == 0


@pytest.mark.parametrize("mutator,message", [
    (lambda value: value["label_provenance"].update(source="model_self_score"), "independent human review"),
    (lambda value: value["label_provenance"].update(annotators=["expert_a"]), "two distinct"),
    (lambda value: value.update(relevant_history_ids=["H-999"]), "subset"),
])
def test_history_benchmark_rejects_unqualified_labels(tmp_path: Path, mutator, message: str) -> None:
    _workspace(tmp_path); case = _case(tmp_path / "suite"); path = case / "labels.json"
    labels = json.loads(path.read_text(encoding="utf-8")); mutator(labels); path.write_text(json.dumps(labels), encoding="utf-8")
    with pytest.raises(ValueError, match=message): run_history_benchmark_suite(tmp_path, tmp_path / "suite")


def test_history_benchmark_rejects_duplicate_fixture_ids(tmp_path: Path) -> None:
    _workspace(tmp_path); suite = tmp_path / "suite"; _case(suite, "case-a"); second = _case(suite, "case-b")
    path = second / "labels.json"; labels = json.loads(path.read_text(encoding="utf-8")); labels["fixture_id"] = "case-a"; path.write_text(json.dumps(labels), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"): run_history_benchmark_suite(tmp_path, suite)
