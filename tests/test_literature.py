import json
from pathlib import Path

import pytest

from revagent.cli import main
from revagent.literature import authorize_literature_provider, authorize_literature_query, build_citation_graph, build_retraction_report, cache_literature_query, fetch_literature_provider, normalize_provider_response
from revagent.workspace import init_workspace, migrate_workspace


def test_literature_authorization_is_local_only(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "response.json").write_text('{"works": []}', encoding="utf-8")
    assert main(["literature", "cache", "openalex", "--query", "numerical PDE", "--response-file", "response.json"]) == 1
    assert main(["literature", "authorize", "openalex", "--purpose", "related-work metadata"]) == 0
    consent = (tmp_path / ".revagent" / "literature_consent.json").read_text(encoding="utf-8")
    assert '"network_enabled": false' in consent
    assert main(["literature", "cache", "openalex", "--query", "numerical PDE", "--response-file", "response.json"]) == 0
    assert list((tmp_path / ".revagent" / "literature_cache").glob("*.json"))
    assert main(["literature", "report"]) == 0
    assert main(["literature", "status"]) == 0
    assert "retrieved metadata only" in (tmp_path / ".revagent" / "literature_report.json").read_text(encoding="utf-8")


def _workspace(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")


def test_provider_response_normalization() -> None:
    crossref = {"message": {"items": [{"DOI": "10.1/test", "title": ["A result"], "author": [{"given": "Ada", "family": "Lovelace"}], "issued": {"date-parts": [[2024, 3, 2]]}, "type": "journal-article"}]}}
    assert normalize_provider_response("crossref", crossref)[0]["authors"] == ["Ada Lovelace"]
    assert normalize_provider_response("crossref", crossref)[0]["published"] == "2024-03-02"
    atom = """<feed xmlns='http://www.w3.org/2005/Atom'><entry><id>http://arxiv.org/abs/2401.00001v1</id><updated>2024-01-02T00:00:00Z</updated><published>2024-01-01T00:00:00Z</published><title> A paper </title><author><name>Ada Lovelace</name></author></entry></feed>"""
    assert normalize_provider_response("arxiv", {"atom_xml": atom})[0]["provider_id"] == "2401.00001v1"
    doi = {"DOI": "10.1234/example", "title": "CSL title", "author": [{"given": "A", "family": "B"}], "issued": {"date-parts": [[2023]]}}
    assert normalize_provider_response("doi-metadata", doi)[0]["title"] == "CSL title"


@pytest.mark.parametrize("provider,query", [("openalex", "PDE"), ("crossref", "PDE"), ("arxiv", "PDE"), ("doi-metadata", "10.1234/example")])
def test_offline_connectors_use_one_time_authorization(tmp_path: Path, provider: str, query: str) -> None:
    _workspace(tmp_path)
    authorize_literature_provider(tmp_path, provider, "metadata")
    auth = authorize_literature_query(tmp_path, provider, query, "metadata", True)
    cached = fetch_literature_provider(tmp_path, provider, query, auth["authorization_id"], offline=True)
    assert cached["version"] == 2
    assert cached["endpoint"].startswith("https://")
    assert cached["authorization_id"] == auth["authorization_id"]
    with pytest.raises(ValueError, match="unused"):
        fetch_literature_provider(tmp_path, provider, query, auth["authorization_id"], offline=True)


def test_fetch_requires_provider_consent_before_query_use(tmp_path: Path) -> None:
    _workspace(tmp_path)
    auth = authorize_literature_query(tmp_path, "crossref", "PDE", "metadata", False)
    with pytest.raises(ValueError, match="no local authorization"):
        fetch_literature_provider(tmp_path, "crossref", "PDE", auth["authorization_id"], offline=True)
    ledger = json.loads((tmp_path / ".revagent" / "literature_query_authorizations.json").read_text(encoding="utf-8"))
    assert ledger["authorizations"][0]["used"] is False


def test_report_excludes_records_without_final_report_permission(tmp_path: Path, monkeypatch) -> None:
    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["literature", "authorize", "crossref", "--purpose", "metadata"]) == 0
    hidden = authorize_literature_query(tmp_path, "crossref", "hidden", "metadata", False)
    visible = authorize_literature_query(tmp_path, "crossref", "visible", "metadata", True)
    fetch_literature_provider(tmp_path, "crossref", "hidden", hidden["authorization_id"], offline=True)
    fetch_literature_provider(tmp_path, "crossref", "visible", visible["authorization_id"], offline=True)
    assert main(["literature", "report"]) == 0
    report = json.loads((tmp_path / ".revagent" / "literature_report.json").read_text(encoding="utf-8"))
    assert report["excluded_local_only_records"] == 1
    assert [item["query"] for item in report["retrieved_metadata"]] == ["visible"]


def test_migration_upgrades_literature_report_without_losing_records(tmp_path: Path) -> None:
    _workspace(tmp_path)
    path = tmp_path / ".revagent" / "literature_report.json"
    path.write_text(json.dumps({"version": 1, "availability": "available", "retrieved_metadata": [{"query": "kept"}]}), encoding="utf-8")
    dry = migrate_workspace(tmp_path, dry_run=True)
    assert "upgrade literature_report.json to version 2" in dry["actions"]
    migrate_workspace(tmp_path, dry_run=False)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["version"] == 2
    assert report["retrieved_metadata"] == [{"query": "kept"}]


def test_citation_graph_and_retraction_report_preserve_provenance(tmp_path: Path) -> None:
    _workspace(tmp_path)
    authorize_literature_provider(tmp_path, "crossref", "metadata")
    authorization = authorize_literature_query(tmp_path, "crossref", "notice", "metadata", True)
    response = {"message": {"items": [{
        "DOI": "10.1000/notice",
        "title": ["Retraction notice"],
        "reference": [{"DOI": "10.1000/cited"}],
        "update-to": [{"DOI": "10.1000/retracted", "type": "retraction", "source": "publisher"}],
    }]}}
    cached = cache_literature_query(tmp_path, "crossref", "notice", response, authorization=authorization)
    graph = build_citation_graph(tmp_path)
    assert {(edge["target"], edge["relation"]) for edge in graph["edges"]} == {
        ("10.1000/cited", "cites"),
        ("10.1000/retracted", "retraction"),
    }
    assert all(edge["provenance"]["response_sha256"] == cached["response_sha256"] for edge in graph["edges"])
    report = build_retraction_report(tmp_path)
    assert report["assertions"][0]["doi"] == "10.1000/retracted"
    assert {item["doi"]: item["status"] for item in report["records"]}["10.1000/notice"] == "no_retraction_metadata_observed"
    assert {item["doi"]: item["status"] for item in report["records"]}["10.1000/retracted"] == "retracted"


def test_derived_literature_artifacts_exclude_unpermitted_cache(tmp_path: Path, monkeypatch) -> None:
    _workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    authorize_literature_provider(tmp_path, "openalex", "metadata")
    hidden = authorize_literature_query(tmp_path, "openalex", "hidden", "metadata", False)
    response = {"results": [{"id": "https://openalex.org/W1", "display_name": "Hidden", "referenced_works": ["https://openalex.org/W2"]}]}
    cache_literature_query(tmp_path, "openalex", "hidden", response, authorization=hidden)
    assert main(["literature", "graph"]) == 0
    assert main(["literature", "retractions"]) == 0
    graph = json.loads((tmp_path / ".revagent" / "literature_citation_graph.json").read_text(encoding="utf-8"))
    retractions = json.loads((tmp_path / ".revagent" / "literature_retractions.json").read_text(encoding="utf-8"))
    assert graph["nodes"] == [] and graph["edges"] == []
    assert retractions["records"] == [] and retractions["assertions"] == []
