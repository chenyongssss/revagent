import hashlib
import json
from pathlib import Path

import pytest

from revagent.benchmark import run_public_review_retrieval_suite
from revagent.history import import_history
from revagent.literature import (
    FETCH_PROVIDERS,
    _provider_request,
    authorize_literature_provider,
    authorize_literature_query,
    build_literature_advisory_report,
    build_retraction_report,
    cache_literature_query,
    fetch_literature_provider,
    normalize_provider_response,
)
from revagent.workspace import init_workspace


def _workspace(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")


def test_semantic_scholar_is_a_real_consent_gated_connector(tmp_path: Path) -> None:
    _workspace(tmp_path)
    assert "semantic-scholar" in FETCH_PROVIDERS
    request, accept = _provider_request("semantic-scholar", "finite elements")
    assert request.full_url.startswith("https://api.semanticscholar.org/graph/v1/paper/search?")
    assert "references.paperId" in request.full_url and accept == "application/json"
    normalized = normalize_provider_response("semantic-scholar", {"data": [{
        "paperId": "S2-1", "title": "Finite element method", "authors": [{"name": "Ada"}],
        "externalIds": {"DOI": "10.1/example"}, "references": [{"paperId": "S2-0"}],
        "openAccessPdf": {"url": "https://example.test/paper.pdf"}, "citationCount": 5,
    }]})
    assert normalized[0]["doi"] == "10.1/example"
    assert normalized[0]["reference_ids"] == ["S2-0"]
    authorize_literature_provider(tmp_path, "semantic-scholar", "metadata")
    auth = authorize_literature_query(tmp_path, "semantic-scholar", "finite elements", "metadata", True)
    cached = fetch_literature_provider(tmp_path, "semantic-scholar", "finite elements", auth["authorization_id"], offline=True)
    assert cached["endpoint"].startswith("https://api.semanticscholar.org/")


def test_advisory_and_broader_retraction_signals_keep_provenance(tmp_path: Path) -> None:
    _workspace(tmp_path)
    authorize_literature_provider(tmp_path, "crossref", "metadata")
    auth = authorize_literature_query(tmp_path, "crossref", "notice", "metadata", True)
    cache = cache_literature_query(tmp_path, "crossref", "notice", {"message": {"items": [{
        "DOI": "10.1/notice", "title": ["Expression of concern"],
        "relation": {"retracts": [{"id": "10.1/work", "id-type": "doi"}]},
        "reference": [{"DOI": "10.1/reference"}],
    }]}}, authorization=auth)
    retractions = build_retraction_report(tmp_path)
    statuses = {row["doi"]: row["status"] for row in retractions["records"]}
    assert statuses["10.1/work"] == "retracted"
    assert statuses["10.1/notice"] == "expression_of_concern"
    assert all(row["provenance"]["response_sha256"] == cache["response_sha256"] for row in retractions["assertions"])
    advisory = build_literature_advisory_report(tmp_path)
    assert advisory["status"] == "metadata_advisory_only_not_expert_calibrated"
    assert advisory["records"][0]["provenance"]["response_sha256"] == cache["response_sha256"]


def _public_case(suite: Path, tamper: bool = False) -> None:
    case = suite / "case-a"
    case.mkdir(parents=True)
    title, abstract = "Adaptive finite element convergence", "Stability estimator for elliptic problems"
    relevant = "The stability estimator and adaptive convergence argument need a missing assumption."
    other = "The manuscript formatting should use a different bibliography style."
    labels = {
        "version": 1, "fixture_id": "case-a",
        "paper": {"title": title, "abstract": abstract, "source_url": "https://example.test/paper", "sha256": hashlib.sha256((title + "\n" + abstract).encode()).hexdigest()},
        "reviews": [
            {"review_id": "R-1", "text": relevant, "source_url": "https://example.test/r1", "license": "CC-BY-4.0", "sha256": hashlib.sha256(relevant.encode()).hexdigest()},
            {"review_id": "R-2", "text": other, "source_url": "https://example.test/r2", "license": "CC-BY-4.0", "sha256": hashlib.sha256(other.encode()).hexdigest()},
        ],
        "relevant_review_ids": ["R-1"],
        "label_provenance": {"status": "adjudicated", "calibration": "not_expert_calibrated", "agents": ["agent-a", "agent-b", "agent-c"], "adjudicator": "agent-c"},
    }
    if tamper:
        labels["reviews"][0]["text"] += " changed"
    (case / "labels.json").write_text(json.dumps(labels), encoding="utf-8")


def test_public_paper_to_review_retrieval_benchmark_is_objective_and_hashed(tmp_path: Path) -> None:
    _workspace(tmp_path)
    suite = tmp_path / "suite"
    _public_case(suite)
    report = run_public_review_retrieval_suite(tmp_path, suite)
    assert report["metrics"]["recall_at_5"] == 1.0
    assert report["metrics"]["mean_reciprocal_rank"] == 1.0
    assert report["cases"][0]["review_sha256s"]["R-1"]
    assert report["status"].endswith("not_expert_calibrated")


def test_public_review_retrieval_fails_closed_on_tampering(tmp_path: Path) -> None:
    _workspace(tmp_path)
    suite = tmp_path / "suite"
    _public_case(suite, tamper=True)
    with pytest.raises(ValueError, match="review sha256"):
        run_public_review_retrieval_suite(tmp_path, suite)


def test_import_entrypoint_enforces_expired_records(tmp_path: Path) -> None:
    _workspace(tmp_path)
    registry = tmp_path / ".revagent" / "history_registry.json"
    preview = tmp_path / ".revagent" / "history_previews" / "H-001.txt"
    preview.parent.mkdir(parents=True)
    preview.write_text("old", encoding="utf-8")
    registry.write_text(json.dumps({"version": 2, "records": [{
        "history_id": "H-001", "retention_rule": "30_days", "approved_at": "2000-01-01T00:00:00+00:00",
        "deletion_status": "active", "preview_path": "history_previews/H-001.txt", "preview_sha256": hashlib.sha256(b"old").hexdigest(),
    }]}), encoding="utf-8")
    source = tmp_path / "new.txt"
    source.write_text("new", encoding="utf-8")
    import_history(tmp_path, source, "precedent")
    data = json.loads(registry.read_text(encoding="utf-8"))
    assert data["records"][0]["deletion_status"] == "expired"
    assert not preview.exists()
