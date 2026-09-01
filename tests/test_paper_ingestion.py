from pathlib import Path

from revagent.cli import main
from revagent.paper_ingestion import build_paper_manifest, paper_manifest_is_stale
from revagent.validation import validate_workspace
from revagent.workspace import init_workspace


def test_paper_ingestion_binds_reachable_source_and_optional_pdf(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "chapter.tex").write_text("\\section{Method}\n", encoding="utf-8")
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\begin{document}\n\\input{chapter}\n\\end{document}\n", encoding="utf-8")
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-local-observation")
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    manifest = build_paper_manifest(tmp_path)

    assert manifest["compiled_pdf"]["exists"] is True
    assert [entry["path"] for entry in manifest["source"]["files"]] == ["chapter.tex", "paper.tex"]
    assert paper_manifest_is_stale(tmp_path) is False
    (tmp_path / "chapter.tex").write_text("\\section{Updated Method}\n", encoding="utf-8")
    assert paper_manifest_is_stale(tmp_path) is True
    assert any("paper manifest is stale" in warning for warning in validate_workspace(tmp_path)["warnings"])

    monkeypatch.chdir(tmp_path)
    assert main(["paper-ingest"]) == 0


def test_paper_ingestion_reports_bibliography_and_claim_evidence_gaps(tmp_path: Path) -> None:
    (tmp_path / "refs.bib").write_text("@article{unused, doi={10.1/unused}}\n", encoding="utf-8")
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\\begin{theorem}Claim.\\end{theorem}\\cite{missing}\\bibliography{refs}\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    manifest = build_paper_manifest(tmp_path)

    assert {check["category"] for check in manifest["checks"]} >= {"bibliography_keys", "bibliography_unused", "claim_evidence", "pdf_binding"}


def test_paper_ingestion_flags_potential_undefined_symbols_and_duplicate_dois(tmp_path: Path) -> None:
    (tmp_path / "refs.bib").write_text("@article{one, doi={10.1/same}}\n@article{two, doi={10.1/same}}\n", encoding="utf-8")
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\begin{document}\\UndefinedMacro\\cite{one,two}\\bibliography{refs}\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    manifest = build_paper_manifest(tmp_path)

    assert {check["category"] for check in manifest["checks"]} >= {"undefined_symbol", "doi_metadata"}
