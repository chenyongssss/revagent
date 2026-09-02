import json
from pathlib import Path

import pytest

from revagent.benchmark import run_alignment_benchmark_suite
from revagent.cli import main
from revagent.workspace import init_workspace


def _case(suite: Path, name: str, fixture_id: str = "case-one") -> Path:
    case = suite / name
    case.mkdir(parents=True)
    labels = {
        "version": 1,
        "fixture_id": fixture_id,
        "claim_excerpt": "adaptive finite element convergence",
        "candidates": [
            {"work_id": "10.1000/relevant", "title": "Adaptive finite element convergence analysis"},
            {"work_id": "10.1000/other", "title": "Unrelated stochastic sampling"},
        ],
        "relevant_work_ids": ["10.1000/relevant"],
        "label_provenance": {
            "status": "adjudicated", "source": "independent_human_review",
            "annotators": ["expert-a", "expert-b"], "adjudicated_by": "expert-a", "labelled_at": "2026-09-01",
        },
    }
    (case / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    return case


def test_alignment_benchmark_measures_retrieval(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    suite = tmp_path / "suite"
    _case(suite, "case")
    report = run_alignment_benchmark_suite(tmp_path, suite)
    assert report["metrics"]["recall_at_5"] == 1.0
    assert report["metrics"]["precision_at_5"] == 0.2
    assert report["metrics"]["mean_reciprocal_rank"] == 1.0
    assert report["status"] == "adjudicated_labels_measured_not_release_calibrated"
    assert (tmp_path / ".revagent" / "alignment_benchmark_report.json").exists()
    monkeypatch.chdir(tmp_path)
    assert main(["benchmark-alignment-suite", "--suite", str(suite)]) == 0


@pytest.mark.parametrize("mutator,message", [
    (lambda labels: labels.update({"label_provenance": {"status": "adjudicated", "source": "model_self_score", "annotators": ["a", "b"], "adjudicated_by": "a", "labelled_at": "2026-09-01"}}), "independent human"),
    (lambda labels: labels.update({"label_provenance": {"status": "adjudicated", "source": "independent_human_review", "annotators": ["expert-a"], "adjudicated_by": "expert-a", "labelled_at": "2026-09-01"}}), "two distinct"),
])
def test_alignment_benchmark_rejects_unqualified_labels(tmp_path: Path, mutator, message: str) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    suite = tmp_path / "suite"
    case = _case(suite, "case")
    labels = json.loads((case / "labels.json").read_text(encoding="utf-8"))
    mutator(labels)
    (case / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        run_alignment_benchmark_suite(tmp_path, suite)


def test_alignment_benchmark_rejects_duplicate_fixture_ids(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    suite = tmp_path / "suite"
    _case(suite, "first", "duplicate")
    _case(suite, "second", "duplicate")
    with pytest.raises(ValueError, match="duplicate"):
        run_alignment_benchmark_suite(tmp_path, suite)


def test_alignment_benchmark_rejects_malformed_identifier_types(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    suite = tmp_path / "suite"
    case = _case(suite, "case")
    labels = json.loads((case / "labels.json").read_text(encoding="utf-8"))
    labels["candidates"][0]["work_id"] = {"invalid": True}
    (case / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    with pytest.raises(ValueError, match="work_id"):
        run_alignment_benchmark_suite(tmp_path, suite)
