import json
from pathlib import Path

import pytest

from revagent.public_review import adjudicate_public_review_case, annotate_public_review_case, fetch_openreview_batch, initialize_public_review_case, public_review_pack_coverage_report, public_review_quality_report
from revagent.reviewer_packs import available_reviewer_packs
from revagent.workspace import init_workspace


def _setup(tmp_path: Path) -> Path:
    (tmp_path / "paper.tex").write_text("x", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    record = {"version": 1, "case_id": "public-001", "provider": "openreview", "venue": "Test", "record_id": "R1",
              "record_url": "https://openreview.net/forum?id=R1", "license": "CC-BY-4.0", "license_url": "https://openreview.net/legal/terms",
              "retrieved_at": "2026-09-04", "paper": {"title": "Method", "text": "A numerical method.", "license": "CC-BY-4.0"},
              "reviews": [{"review_id": "r1", "url": "https://openreview.net/r1", "attribution": "anonymous reviewer", "text": "The convergence evidence is missing.", "license": "CC-BY-4.0"},
                          {"review_id": "r2", "url": "https://openreview.net/r2", "attribution": "anonymous reviewer", "text": "Please add a stability experiment.", "license": "CC-BY-4.0"}]}
    path = tmp_path / "record.json"; path.write_text(json.dumps(record), encoding="utf-8"); return path


def _annotation(tmp_path: Path, name: str, excerpt: str = "The convergence evidence is missing.") -> Path:
    payload = {"method_note": "Independent coding from the frozen record.", "findings": [{"finding_id": "F1", "role": "theory-reviewer", "category": "claim_evidence", "high_risk": True, "review_id": "r1", "evidence_excerpt": excerpt}]}
    path = tmp_path / name; path.write_text(json.dumps(payload), encoding="utf-8"); return path


def test_public_review_agent_pipeline_is_explicitly_not_expert_calibrated(tmp_path: Path) -> None:
    record = _setup(tmp_path)
    initialize_public_review_case(tmp_path, "public-001", record, True)
    for actor in ("agent-a", "agent-b"):
        annotate_public_review_case(tmp_path, "public-001", actor, "codex", actor + "-run", _annotation(tmp_path, actor + ".json"))
    adjudicate_public_review_case(tmp_path, "public-001", "agent-c", "codex", "agent-c-run", _annotation(tmp_path, "c.json"))
    report = public_review_quality_report(tmp_path)
    assert report["expert_calibrated"] is False
    assert report["status"] == "public_review_agent_coded_proxy_metrics_not_expert_calibrated"
    assert report["metrics"]["mean_agent_agreement_jaccard"] == 1.0
    assert report["metrics"]["provenance_completeness"] == 1.0
    assert report["metrics"]["by_role"]["theory-reviewer"] == {"finding_count": 1, "high_risk_count": 1}
    assert "not expert calibration" in (tmp_path / ".revagent" / "public_review_quality_report.md").read_text(encoding="utf-8")


def test_public_review_rejects_unlicensed_text_and_unbound_evidence(tmp_path: Path) -> None:
    record = _setup(tmp_path); data = json.loads(record.read_text(encoding="utf-8")); data["paper"]["license"] = "unknown"; record.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="redistributed"): initialize_public_review_case(tmp_path, "public-001", record, True)
    record = _setup(tmp_path); initialize_public_review_case(tmp_path, "public-001", record, True)
    with pytest.raises(ValueError, match="verbatim"): annotate_public_review_case(tmp_path, "public-001", "agent-a", "codex", "run", _annotation(tmp_path, "bad.json", "invented evidence"))


def test_openreview_batch_fetch_filters_and_preserves_provenance(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("x", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    submission = {"id": "Math_1", "readers": ["everyone"], "content": {
        "title": {"value": "A finite element solver"}, "abstract": {"value": "Numerical PDE discretization."},
        "license": {"value": "CC BY 4.0"}}}
    off_topic = {"id": "Vision_1", "readers": ["everyone"], "content": {
        "title": {"value": "Image classification"}, "abstract": {"value": "Vision benchmark."},
        "license": {"value": "CC-BY-4.0"}}}
    replies = {"notes": [
        {"id": "rev1", "forum": "Math_1", "invitation": "Venue/-/Official_Review", "readers": ["everyone"],
         "signatures": ["Venue/AnonReviewer1"], "content": {"review": {"value": "The convergence proof needs detail."}}},
        {"id": "rev2", "forum": "Math_1", "invitation": "Venue/-/Official_Review", "readers": ["everyone"],
         "signatures": ["Venue/AnonReviewer2"], "content": {"review": {"value": "The stability experiment is incomplete."}}},
        {"id": "secret", "forum": "Math_1", "invitation": "Venue/-/Official_Review", "readers": ["Venue/PC"],
         "content": {"review": {"value": "Confidential text."}}},
    ]}
    fixture = tmp_path / "openreview.json"
    fixture.write_text(json.dumps({"submissions": {"notes": [submission, off_topic]}, "replies_by_forum": {"Math_1": replies}}), encoding="utf-8")
    manifest = fetch_openreview_batch(tmp_path, "Venue/2026/Conference", "numerical-pde", 5, True, fixture)
    assert len(manifest["imported"]) == 1
    assert manifest["imported"][0]["case_id"].startswith("or-math-1-")
    assert manifest["imported"][0]["review_count"] == 2
    assert manifest["excluded"] == [{"record_id": "Vision_1", "reason": "domain_filter"}]
    registry = json.loads((tmp_path / ".revagent" / "public_review_registry.json").read_text(encoding="utf-8"))
    record = registry["cases"][manifest["imported"][0]["case_id"]]["record"]
    assert record["record_url"] == "https://openreview.net/forum?id=Math_1"
    assert "Confidential text." not in json.dumps(record)
    assert Path(manifest["source"]) == fixture.resolve()


def test_openreview_batch_fetch_is_bounded_and_requires_confirmation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="confirmation"):
        fetch_openreview_batch(tmp_path, "venue", confirmed=False)
    with pytest.raises(ValueError, match="between 1 and 50"):
        fetch_openreview_batch(tmp_path, "venue", limit=51, confirmed=True)


def test_pack_coverage_requires_three_complete_adjudicated_public_cases(tmp_path: Path) -> None:
    for number in range(1, 4):
        record = _setup(tmp_path)
        case_id = f"public-00{number}"
        data = json.loads(record.read_text(encoding="utf-8")); data["case_id"] = case_id; data["record_id"] = f"R{number}"
        case_path = tmp_path / f"record-{number}.json"; case_path.write_text(json.dumps(data), encoding="utf-8")
        initialize_public_review_case(tmp_path, case_id, case_path, True)
        for actor in ("agent-a", "agent-b"):
            annotate_public_review_case(tmp_path, case_id, actor, "codex", f"{actor}-{number}", _annotation(tmp_path, f"{actor}-{number}.json"))
        adjudicate_public_review_case(tmp_path, case_id, "agent-c", "codex", f"agent-c-{number}", _annotation(tmp_path, f"c-{number}.json"))
    report = public_review_pack_coverage_report(tmp_path)
    assert report["passed"] is True
    assert report["status"] == "not_expert_calibrated"
    assert set(report["packs"]) == set(available_reviewer_packs())
    assert all(row["eligible_case_count"] == 3 and row["provenance_completeness"] == 1.0 and row["evidence_completeness"] == 1.0 for row in report["packs"].values())


def test_pack_coverage_fails_closed_for_short_or_incomplete_assignments(tmp_path: Path) -> None:
    record = _setup(tmp_path); initialize_public_review_case(tmp_path, "public-001", record, True)
    report = public_review_pack_coverage_report(tmp_path)
    assert report["passed"] is False
    assert all(row["eligible_case_count"] == 0 for row in report["packs"].values())
    with pytest.raises(ValueError, match="every available"):
        public_review_pack_coverage_report(tmp_path, {"numerical-pde": []})
