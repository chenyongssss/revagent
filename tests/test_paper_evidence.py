import hashlib
import json
from pathlib import Path

from revagent.cli import main
from revagent.paper_evidence import bind_experiment_evidence, review_claim_dependency
from revagent.paper_ingestion import build_paper_manifest
from revagent.workspace import init_workspace


def _workspace(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\newtheorem{assumption}{Assumption}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\n\\begin{assumption}Regularity.\\label{ass:reg}\\end{assumption}\n\\begin{theorem}Convergence under \\ref{ass:reg}.\\end{theorem}\n\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex"); build_paper_manifest(tmp_path)


def test_semantic_dependency_review_is_hash_bound(tmp_path: Path, monkeypatch) -> None:
    _workspace(tmp_path)
    review_claim_dependency(tmp_path, "CLM-002", "CLM-001", "expert-a", "supported", "The assumption is used in the estimate.")
    assert build_paper_manifest(tmp_path)["claims"][1]["semantic_dependency_reviews"][0]["decision"] == "supported"
    monkeypatch.chdir(tmp_path)
    assert main(["paper-dependency-review", "CLM-002", "CLM-001", "--reviewer", "expert-b", "--decision", "uncertain", "--note", "Proof details require review."]) == 0
    source = tmp_path / "paper.tex"; source.write_text(source.read_text(encoding="utf-8").replace("Regularity.", "Stronger regularity."), encoding="utf-8")
    assert build_paper_manifest(tmp_path)["semantic_dependency_reviews"] == []


def test_experiment_artifact_binding_requires_current_hash(tmp_path: Path, monkeypatch) -> None:
    _workspace(tmp_path); artifact = tmp_path / "results.csv"; artifact.write_text("error\n0.01\n", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest(); registry = tmp_path / ".revagent" / "experiment_manifests.json"
    registry.write_text(json.dumps({"R001": {"artifacts": [{"path": "results.csv", "sha256": digest}]}}), encoding="utf-8")
    assert bind_experiment_evidence(tmp_path, "CLM-002", "R001", "results.csv", "Observed result used by this claim.")["status"] == "recorded_evidence_not_validity_confirmation"
    assert build_paper_manifest(tmp_path)["claims"][1]["experiment_evidence"][0]["artifact_sha256"] == digest
    monkeypatch.chdir(tmp_path)
    assert main(["paper-experiment-bind", "CLM-002", "R001", "--artifact", "results.csv", "--note", "Current result artifact."]) == 0
    artifact.write_text("error\n0.02\n", encoding="utf-8")
    assert build_paper_manifest(tmp_path)["experiment_evidence_bindings"] == []
