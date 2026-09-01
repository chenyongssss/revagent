from pathlib import Path

from revagent.cli import main
from revagent.pre_submission_review import build_pre_submission_review, pre_submission_review_summary
from revagent.validation import validate_workspace
from revagent.workspace import init_workspace


def test_pre_submission_review_is_local_advisory_and_traces_findings(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n"
        "\\newtheorem{theorem}{Theorem}\n"
        "\\begin{document}\n"
        "\\begin{theorem}Claim.\\end{theorem}\n"
        "See Figure~\\ref{fig:missing}.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    report = build_pre_submission_review(tmp_path)
    assert report["summary"]["status"] == "needs_author_review"
    assert any(row["category"] == "cross_reference" for row in report["findings"])
    assert any(row["category"] == "theory" for row in report["findings"])
    assert "No manuscript content was sent" in report["limitations"][1]
    assert (tmp_path / ".revagent" / "pre_submission_review.json").exists()
    assert report["source"]["paper_input_fingerprint"]
    assert len(report["source"]["paper_manifest_sha256"]) == 64
    assert (tmp_path / ".revagent" / "paper_manifest.json").exists()


def test_artifact_registry_records_core_json_yaml_artifacts_and_validation_flags_unknown(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}Text.\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    registry = (tmp_path / ".revagent" / "artifact_registry.json").read_text(encoding="utf-8")
    assert "revision.yaml" in registry
    assert "pre_submission_review.json" in registry

    (tmp_path / ".revagent" / "unregistered.json").write_text("{}\n", encoding="utf-8")
    assert any("unknown persisted artifact: unregistered.json" in warning for warning in validate_workspace(tmp_path)["warnings"])


def test_artifact_registry_detects_drift_and_cli_refreshes_it(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}Text.\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    (tmp_path / ".revagent" / "review_items.json").write_text("[{}]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(["artifact-registry", "--check"]) == 1
    assert main(["artifact-registry"]) == 0
    assert main(["artifact-registry", "--check"]) == 0


def test_pre_submission_review_cli_status_schema_and_dashboards(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nText.\\end{document}\n",
        encoding="utf-8",
    )
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    monkeypatch.chdir(tmp_path)

    assert main(["review-status"]) == 1
    assert main(["review-paper"]) == 0
    assert main(["review-status"]) == 0
    assert main(["schema"]) == 0
    assert main(["validate"]) == 0
    assert main(["cockpit"]) == 0
    assert main(["dashboard"]) == 0

    cockpit = (tmp_path / ".revagent" / "author_cockpit.html").read_text(encoding="utf-8")
    dashboard = (tmp_path / ".revagent" / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "Pre-submission review" in cockpit
    assert "Pre-submission Review" in dashboard


def test_pre_submission_review_becomes_stale_when_source_or_rulepack_changes(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nText.\\end{document}\n",
        encoding="utf-8",
    )
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    build_pre_submission_review(tmp_path)
    assert pre_submission_review_summary(tmp_path)["status"] != "stale"

    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nUpdated text.\\end{document}\n",
        encoding="utf-8",
    )
    assert pre_submission_review_summary(tmp_path)["status"] == "stale"
    assert any("pre-submission review is stale" in warning for warning in validate_workspace(tmp_path)["warnings"])

    monkeypatch.chdir(tmp_path)
    assert main(["review-status"]) == 1
