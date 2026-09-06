import json
from pathlib import Path

from revagent.literature import authorize_literature_provider, cache_literature_query
from revagent.paper_evidence import review_claim_dependency
from revagent.paper_ingestion import build_paper_manifest
from revagent.paper_quality import build_doi_verification_report, build_high_risk_traceability_report
from revagent.workspace import init_workspace


def test_doi_report_uses_hash_bound_consent_gated_cache(tmp_path: Path) -> None:
    (tmp_path / "refs.bib").write_text("@article{work, doi={10.1234/example}}\n", encoding="utf-8")
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}\\cite{work}\\bibliography{refs}\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex"); build_paper_manifest(tmp_path)
    authorize_literature_provider(tmp_path, "doi-metadata", "verify bibliography")
    cache_literature_query(tmp_path, "doi-metadata", "10.1234/example", {"DOI": "10.1234/example", "title": "Example"},
                           endpoint="https://doi.org/10.1234/example")
    report = build_doi_verification_report(tmp_path)
    assert report["summary"] == {"total": 1, "metadata_observed": 1, "missing_doi": 0, "not_in_cache": 0}
    assert report["entries"][0]["provider_observations"][0]["response_sha256"]


def test_high_risk_traceability_fails_closed_then_accepts_reviewed_dependency(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\newtheorem{assumption}{Assumption}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\n\\begin{assumption}Regularity.\\label{a}\\end{assumption}\n\\begin{theorem}Result under \\ref{a}.\\end{theorem}\n\\begin{proof}Proof.\\end{proof}\n\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    monkeypatch.setattr("revagent.paper_ingestion._synctex_page", lambda *args: {"status": "observed", "page": 1, "reason": "test"})
    (tmp_path / "paper.pdf").write_bytes(b"%PDF /Type /Page")
    build_paper_manifest(tmp_path)
    first = build_high_risk_traceability_report(tmp_path)
    assert first["ok"] is False
    assert first["claims"][1]["missing"] == ["dependencies"]
    review_claim_dependency(tmp_path, "CLM-002", "CLM-001", "expert-a", "supported", "Dependency checked.")
    build_paper_manifest(tmp_path)
    second = build_high_risk_traceability_report(tmp_path)
    assert second["ok"] is True
    assert second["status"].endswith("not_expert_calibrated")
