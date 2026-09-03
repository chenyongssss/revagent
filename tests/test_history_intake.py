import json
from pathlib import Path

import pytest

from revagent.cli import main
from revagent.contributions import contribution_data_card_template
from revagent.history_intake import adjudicate_history_case, annotate_history_case, export_history_fixture, initialize_history_case, publish_history_quality
from revagent.workspace import init_workspace


def _workspace(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")


def _inputs(tmp_path: Path, case_id: str, visibility: str = "public_benchmark") -> tuple[Path, Path]:
    corpus = tmp_path / f"{case_id}-corpus.json"
    corpus.write_text(json.dumps([{"history_id": "H-001", "purpose": "precedent", "content": "We supplied a stability estimate."}, {"history_id": "H-002", "purpose": "style", "content": "We clarified notation."}]), encoding="utf-8")
    card = contribution_data_card_template(case_id); card.update({"permission_status": "written", "deidentification_status": "completed", "intended_visibility": visibility, "retention_rule": "delete after evaluation", "allowed_purposes": ["history_retrieval_benchmark"], "subfield": "numerical PDE"})
    card_path = tmp_path / f"{case_id}-card.json"; card_path.write_text(json.dumps(card), encoding="utf-8"); return corpus, card_path


def _adjudicated(tmp_path: Path, case_id: str = "real-history-001", visibility: str = "public_benchmark") -> Path:
    corpus, card = _inputs(tmp_path, case_id, visibility)
    initialize_history_case(tmp_path, case_id, "stability estimate", corpus, card, True)
    annotate_history_case(tmp_path, case_id, "expert-a", ["H-001"], "Relevant response precedent.")
    annotate_history_case(tmp_path, case_id, "expert-b", ["H-001"], "Independent relevance assessment.")
    adjudicate_history_case(tmp_path, case_id, "expert-a", ["H-001"], "Agreement after independent review.")
    return export_history_fixture(tmp_path, case_id, tmp_path / "suite")


def test_history_real_case_intake_and_quality_publication(tmp_path: Path, monkeypatch) -> None:
    _workspace(tmp_path); fixture = _adjudicated(tmp_path)
    assert (fixture / "data_card.json").exists()
    report = publish_history_quality(tmp_path, tmp_path / "suite")
    assert report["status"] == "published_adjudicated_real_case_metrics" and report["metrics"]["recall_at_5"] == 1.0
    monkeypatch.chdir(tmp_path); assert main(["history-quality-publish", "--suite", str(tmp_path / "suite")]) == 0


def test_history_intake_fails_closed_without_authorization_or_adjudication(tmp_path: Path) -> None:
    _workspace(tmp_path); corpus, card = _inputs(tmp_path, "case-a")
    with pytest.raises(ValueError, match="confirmation"): initialize_history_case(tmp_path, "case-a", "stability", corpus, card)
    initialize_history_case(tmp_path, "case-a", "stability", corpus, card, True)
    with pytest.raises(ValueError, match="only adjudicated"): export_history_fixture(tmp_path, "case-a", tmp_path / "suite")
    with pytest.raises(ValueError, match="no adjudicated real"): publish_history_quality(tmp_path, tmp_path / "empty")


def test_private_case_cannot_be_published(tmp_path: Path) -> None:
    _workspace(tmp_path); _adjudicated(tmp_path, visibility="private_review")
    with pytest.raises(ValueError, match="public_benchmark"): publish_history_quality(tmp_path, tmp_path / "suite")


def test_history_case_cli_lifecycle(tmp_path: Path, monkeypatch) -> None:
    _workspace(tmp_path); corpus, card = _inputs(tmp_path, "cli-history"); monkeypatch.chdir(tmp_path)
    assert main(["history-case", "init", "cli-history", "--query", "stability estimate", "--corpus", str(corpus), "--data-card", str(card), "--confirm"]) == 0
    for expert in ("expert-a", "expert-b"):
        assert main(["history-case", "annotate", "cli-history", "--annotator", expert, "--relevant-history-id", "H-001", "--note", "Independent assessment."]) == 0
    assert main(["history-case", "adjudicate", "cli-history", "--adjudicator", "expert-a", "--relevant-history-id", "H-001", "--note", "Resolved by agreement."]) == 0
    assert main(["history-case", "export-fixture", "cli-history", "--suite", str(tmp_path / "suite")]) == 0
