import json
from pathlib import Path

import pytest

from revagent.alignment_intake import adjudicate_alignment_case, annotate_alignment_case, export_alignment_fixture, initialize_alignment_case
from revagent.benchmark import run_alignment_benchmark_suite
from revagent.cli import main
from revagent.contributions import contribution_data_card_template
from revagent.workspace import init_workspace


def _inputs(tmp_path: Path, case_id: str = "real-case-001") -> tuple[Path, Path]:
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps([
        {"work_id": "10.1000/relevant", "title": "Adaptive finite element convergence"},
        {"work_id": "10.1000/control", "title": "Stochastic sampling control"},
    ]), encoding="utf-8")
    card = contribution_data_card_template(case_id)
    card.update({"permission_status": "written", "deidentification_status": "completed", "retention_rule": "delete after evaluation",
                 "allowed_purposes": ["claim_alignment_benchmark"], "subfield": "numerical PDE"})
    card_path = tmp_path / "data_card.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    return candidates, card_path


def _workspace(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")


def test_alignment_case_requires_confirmation_and_allowed_purpose(tmp_path: Path) -> None:
    _workspace(tmp_path)
    candidates, card = _inputs(tmp_path)
    with pytest.raises(ValueError, match="confirmation"):
        initialize_alignment_case(tmp_path, "real-case-001", "Adaptive finite element convergence", candidates, card)
    data = json.loads(card.read_text(encoding="utf-8")); data["allowed_purposes"] = ["other"]
    card.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="claim_alignment_benchmark"):
        initialize_alignment_case(tmp_path, "real-case-001", "Adaptive finite element convergence", candidates, card, True)


def test_alignment_case_two_annotator_adjudication_and_export(tmp_path: Path) -> None:
    _workspace(tmp_path)
    candidates, card = _inputs(tmp_path)
    case = initialize_alignment_case(tmp_path, "real-case-001", "Adaptive finite element convergence", candidates, card, True)
    assert case["status"] == "awaiting_annotations"
    annotate_alignment_case(tmp_path, case["case_id"], "expert-a", ["10.1000/relevant"], "Relevant method and result.")
    with pytest.raises(ValueError, match="only once"):
        annotate_alignment_case(tmp_path, case["case_id"], "expert-a", ["10.1000/relevant"], "Duplicate.")
    with pytest.raises(ValueError, match="two distinct"):
        adjudicate_alignment_case(tmp_path, case["case_id"], "expert-a", ["10.1000/relevant"], "Too early.")
    with pytest.raises(ValueError, match="only adjudicated"):
        export_alignment_fixture(tmp_path, case["case_id"], tmp_path / "suite")
    annotate_alignment_case(tmp_path, case["case_id"], "expert-b", ["10.1000/relevant"], "Independently relevant.")
    adjudicated = adjudicate_alignment_case(tmp_path, case["case_id"], "expert-a", ["10.1000/relevant"], "Both annotations agree after review.")
    assert adjudicated["status"] == "adjudicated"
    with pytest.raises(ValueError, match="already adjudicated"):
        adjudicate_alignment_case(tmp_path, case["case_id"], "expert-a", ["10.1000/control"], "Attempted rewrite.")
    fixture = export_alignment_fixture(tmp_path, case["case_id"], tmp_path / "suite")
    labels = json.loads((fixture / "labels.json").read_text(encoding="utf-8"))
    assert labels["label_provenance"]["annotators"] == ["expert-a", "expert-b"]
    assert run_alignment_benchmark_suite(tmp_path, tmp_path / "suite")["metrics"]["recall_at_5"] == 1.0


def test_alignment_case_cli_lifecycle(tmp_path: Path, monkeypatch) -> None:
    _workspace(tmp_path)
    candidates, card = _inputs(tmp_path, "cli-case")
    monkeypatch.chdir(tmp_path)
    assert main(["alignment-case", "init", "cli-case", "--claim", "Adaptive finite element convergence", "--candidates", str(candidates), "--data-card", str(card), "--confirm"]) == 0
    assert main(["alignment-case", "annotate", "cli-case", "--annotator", "expert-a", "--relevant-work-id", "10.1000/relevant", "--note", "Independent assessment."]) == 0
    assert main(["alignment-case", "annotate", "cli-case", "--annotator", "expert-b", "--relevant-work-id", "10.1000/relevant", "--note", "Independent assessment."]) == 0
    assert main(["alignment-case", "adjudicate", "cli-case", "--adjudicator", "expert-a", "--relevant-work-id", "10.1000/relevant", "--note", "Resolved by agreement."]) == 0
    assert main(["alignment-case", "export-fixture", "cli-case", "--suite", str(tmp_path / "suite")]) == 0
