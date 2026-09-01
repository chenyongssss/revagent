import json
from pathlib import Path

import pytest

from revagent.benchmark import run_review_benchmark_suite
from revagent.cli import main
from revagent.workspace import init_workspace


def _case(suite: Path, name: str, tex: str, findings: list[dict], must_not_pass: bool = True) -> Path:
    case = suite / name
    case.mkdir(parents=True)
    (case / "paper.tex").write_text(tex, encoding="utf-8")
    labels = {
        "version": 1,
        "fixture_id": name,
        "pack": "numerical-pde",
        "expected_findings": findings,
        "must_not_pass": must_not_pass,
        "label_provenance": {
            "status": "adjudicated",
            "source": "independent_human_review",
            "annotators": ["expert-a", "expert-b"],
            "adjudicated_by": "expert-a",
            "labelled_at": "2026-09-01",
        },
    }
    (case / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    return case


def test_review_benchmark_measures_pack_role_recall_and_false_pass(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    init_workspace(project, "siam", ".", "paper.tex")
    suite = tmp_path / "suite"
    theorem = "\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\\begin{theorem}Claim.\\end{theorem}\\end{document}\n"
    proved = "\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\\begin{theorem}Claim.\\end{theorem}\\begin{proof}Proof.\\end{proof}\\end{document}\n"
    _case(suite, "missing-proof", theorem, [{"role": "theory-reviewer", "category": "claim_evidence", "high_risk": True}])
    _case(suite, "proved", proved, [], must_not_pass=False)

    report = run_review_benchmark_suite(project, suite)

    assert report["metrics"]["defect_detection_recall"] == 1.0
    assert report["metrics"]["high_risk_recall"] == 1.0
    assert report["metrics"]["false_pass_rate"] == 0.0
    assert report["per_pack"]["numerical-pde"]["case_count"] == 2
    assert report["per_role"]["theory-reviewer"]["high_risk_recall"] == 1.0
    assert report["per_role"]["text-reviewer"]["false_pass_rate"] == 0.0
    assert report["status"] == "adjudicated_labels_measured_not_release_calibrated"
    assert (project / ".revagent" / "review_benchmark_report.json").exists()

    monkeypatch.chdir(project)
    assert main(["benchmark-review-suite", "--suite", str(suite)]) == 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "draft", "adjudicated human review"),
        ("annotators", ["expert-a"], "at least two distinct"),
        ("source", "model_self_score", "model self-scores"),
    ],
)
def test_review_benchmark_rejects_unqualified_labels(tmp_path: Path, field: str, value: object, message: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    init_workspace(project, "siam", ".", "paper.tex")
    suite = tmp_path / "suite"
    case = _case(suite, "case", "\\documentclass{article}\n", [])
    labels = json.loads((case / "labels.json").read_text(encoding="utf-8"))
    labels["label_provenance"][field] = value
    (case / "labels.json").write_text(json.dumps(labels), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        run_review_benchmark_suite(project, suite)


def test_review_benchmark_rejects_duplicate_fixture_ids(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "paper.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    init_workspace(project, "siam", ".", "paper.tex")
    suite = tmp_path / "suite"
    first = _case(suite, "first", "\\documentclass{article}\n", [])
    second = _case(suite, "second", "\\documentclass{article}\n", [])
    labels = json.loads((second / "labels.json").read_text(encoding="utf-8"))
    labels["fixture_id"] = json.loads((first / "labels.json").read_text(encoding="utf-8"))["fixture_id"]
    (second / "labels.json").write_text(json.dumps(labels), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        run_review_benchmark_suite(project, suite)
