from pathlib import Path
import subprocess

from revagent.cli import main
from revagent import paper_ingestion
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


def test_claim_evidence_is_bound_per_claim_and_records_assumption_edges(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n\\newtheorem{assumption}{Assumption}\n\\newtheorem{theorem}{Theorem}\n"
        "\\begin{document}\n"
        "\\begin{assumption}Regularity.\\label{ass:reg}\\end{assumption}\n"
        "\\begin{theorem}First claim under \\ref{ass:reg}.\\label{thm:first}\\end{theorem}\n"
        "\\begin{proof}Argument.\\end{proof}\n"
        "\\begin{theorem}Second unsupported claim.\\label{thm:second}\\end{theorem}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    manifest = build_paper_manifest(tmp_path)
    claims = {claim["claim_id"]: claim for claim in manifest["claims"]}

    assert claims["CLM-002"]["evidence_state"] == "proof_environment_bound"
    assert claims["CLM-003"]["evidence_state"] == "no_bound_proof"
    assert claims["CLM-002"]["assumption_dependencies"] == ["CLM-001"]
    assert any(edge["from"] == "CLM-002" and edge["to"] == "CLM-001" and edge["type"] == "assumption" for edge in manifest["claim_evidence_graph"])
    claim_check = next(check for check in manifest["checks"] if check["category"] == "claim_evidence")
    assert "1 theorem-like claim" in claim_check["message"]


def test_proof_before_any_claim_is_not_bound_or_crashing(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\n"
        "\\begin{proof}Preliminary argument.\\end{proof}\n"
        "\\begin{theorem}Later claim.\\end{theorem}\n\\end{document}\n",
        encoding="utf-8",
    )
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    manifest = build_paper_manifest(tmp_path)

    assert manifest["claims"][0]["evidence_state"] == "no_bound_proof"
    assert manifest["claims"][0]["proof_source_spans"] == []


def test_rendered_pdf_and_synctex_observations_are_explicitly_advisory(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n"
        "\\begin{document}\\begin{theorem}Claim.\\end{theorem}\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-local-observation")
    init_workspace(tmp_path, "siam", ".", "paper.tex")

    monkeypatch.setattr(paper_ingestion.shutil, "which", lambda name: name)

    def fake_tool(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "pdfinfo":
            return subprocess.CompletedProcess(command, 0, "Pages: 2\n", "")
        if command[0] == "synctex":
            return subprocess.CompletedProcess(command, 0, "Page:1\n", "")
        page = command[command.index("-f") + 1]
        return subprocess.CompletedProcess(command, 0, "Rendered theorem" if page == "1" else " \n", "")

    monkeypatch.setattr(paper_ingestion, "_run_local_tool", fake_tool)
    manifest = build_paper_manifest(tmp_path)

    rendered = manifest["compiled_pdf"]["rendered_inspection"]
    assert rendered["status"] == "observed"
    assert rendered["text_empty_pages"] == [2]
    assert manifest["claims"][0]["pdf_location"]["page"] == 1
    assert any(check["category"] == "pdf_text_empty_page" for check in manifest["checks"])
    assert any("not semantic proof verification" in limitation for limitation in manifest["limitations"])
