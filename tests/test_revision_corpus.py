from pathlib import Path

import json

from revagent.revision_corpus import audit_local_revision_case, audit_local_revision_corpus, audit_public_revision_catalog, fetch_public_revision_catalog


def _case(root: Path, name: str, responses: int = 1) -> Path:
    case = root / name
    old = case / "paper_old"
    revised = case / "paper_revision" / "response"
    old.mkdir(parents=True)
    revised.mkdir(parents=True)
    (old / "main.tex").write_text("old", encoding="utf-8")
    (revised.parent / "main.tex").write_text("new", encoding="utf-8")
    for number in range(responses):
        (revised / f"resp{number + 1}.tex").write_text(f"round {number + 1}", encoding="utf-8")
    return case


def test_one_round_case_is_complete_and_metadata_only(tmp_path: Path) -> None:
    report = audit_local_revision_case(_case(tmp_path, "Case1"), "case1", 1)
    assert report["round_chain_complete"] is True
    assert report["final_state_verifiable"] is True
    assert report["content_copied"] is False
    assert report["expert_calibrated"] is False
    assert report["outcome"] == "accepted_user_asserted"
    assert report["outcome_evidence_path"] is None
    assert report["snapshots"][0]["files"][0]["sha256"]


def test_two_round_case_without_intermediate_snapshot_fails_closed(tmp_path: Path) -> None:
    report = audit_local_revision_case(_case(tmp_path, "Case2", responses=2), "case2", 2)
    assert report["final_state_verifiable"] is True
    assert report["round_chain_complete"] is False
    assert report["gaps"] == ["missing_1_intermediate_manuscript_snapshot(s)"]


def test_root_intermediate_manuscript_completes_two_round_chain(tmp_path: Path) -> None:
    case = _case(tmp_path, "Case2", responses=2)
    (case / "ex_article.tex").write_text("round one", encoding="utf-8")
    report = audit_local_revision_case(case, "case2", 2)
    assert report["round_chain_complete"] is True
    assert [item["snapshot_id"] for item in report["snapshots"]] == ["submitted-v1", "revision-1", "final-revision"]


def test_corpus_report_keeps_acceptance_separate_from_expert_calibration(tmp_path: Path) -> None:
    cases = tmp_path / "Cases"
    _case(cases, "Case1")
    _case(cases, "Case2", responses=2)
    report = audit_local_revision_corpus(tmp_path, cases, {"Case1": 1, "Case2": 2})
    assert report["case_count"] == 2
    assert report["round_chain_complete_count"] == 1
    assert report["final_state_verifiable_count"] == 2
    assert report["expert_calibrated"] is False
    assert (tmp_path / ".revagent" / "local_revision_corpus.json").is_file()


def test_public_catalog_counts_only_fully_cached_version_chains(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in ("v1.pdf", "v2.pdf", "reviews.html"):
        (cache / name).write_bytes(b"public artifact")
    cases = [{
        "case_id": "complete", "provider": "elife", "domain": "applied-mathematics",
        "record_url": "https://example.test/complete", "license": "CC-BY-4.0",
        "license_url": "https://example.test/license", "expected_rounds": 1,
        "artifacts": [
            {"kind": "manuscript", "version": "v1", "url": "https://example.test/v1", "cache_file": "v1.pdf"},
            {"kind": "manuscript", "version": "v2", "url": "https://example.test/v2", "cache_file": "v2.pdf"},
            {"kind": "review_response", "version": "r1", "url": "https://example.test/reviews", "cache_file": "reviews.html"},
        ],
    }, {
        "case_id": "pending", "provider": "peerj", "domain": "scientific-ml",
        "record_url": "https://example.test/pending", "license": "CC-BY-4.0",
        "license_url": "https://example.test/license", "expected_rounds": 1,
        "artifacts": [
            {"kind": "manuscript", "version": "v1", "url": "https://example.test/p1", "cache_file": "missing-v1.pdf"},
            {"kind": "manuscript", "version": "v2", "url": "https://example.test/p2", "cache_file": "missing-v2.pdf"},
            {"kind": "review_response", "version": "r1", "url": "https://example.test/pr", "cache_file": "missing.html"},
        ],
    }]
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"version": 1, "cases": cases}), encoding="utf-8")
    report = audit_public_revision_catalog(tmp_path, catalog, cache)
    assert report["verified_complete_count"] == 1
    assert report["pending_count"] == 1
    assert report["cases"][1]["status"] == "candidate_pending_fetch"


def test_public_fetch_requires_confirmation_and_rejects_unapproved_hosts(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    case = {
        "case_id": "bad", "provider": "elife", "domain": "math",
        "record_url": "https://example.test", "license": "CC-BY-4.0",
        "license_url": "https://example.test/license", "expected_rounds": 1,
        "artifacts": [{"kind": "manuscript", "version": "v1", "url": "https://example.test/file.pdf", "cache_file": "file.pdf"}],
    }
    catalog.write_text(json.dumps({"version": 1, "cases": [case]}), encoding="utf-8")
    try:
        fetch_public_revision_catalog(tmp_path, catalog, tmp_path / "cache")
        assert False, "confirmation must be required"
    except ValueError as exc:
        assert "confirmation" in str(exc)
    try:
        fetch_public_revision_catalog(tmp_path, catalog, tmp_path / "cache", confirmed=True)
        assert False, "host allowlist must be enforced"
    except ValueError as exc:
        assert "approved provider" in str(exc)
