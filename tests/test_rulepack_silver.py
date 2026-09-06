from pathlib import Path
import pytest

from revagent.rulepack_silver import annotate_rulepack_source, adjudicate_rulepack_source, initialize_rulepack_source, verify_rulepack_silver


def _pack(base: Path) -> None:
    directory = base / "journal_profiles" / "sample"; directory.mkdir(parents=True)
    (directory / "profile.yaml").write_text("display_name: Sample\nversion: 1\nsource_url: https://journal.test/rules\nsource_checked_at: 2026-09-01\nexpires_at: 2027-09-01\nhuman_confirmed: false\n", encoding="utf-8")
    for name in ("rubric.yaml", "submission.yaml", "rebuttal.yaml"):
        (directory / name).write_text("version: 1\n", encoding="utf-8")
    (directory / "sources.md").write_text("# Sources\n", encoding="utf-8")


def test_three_distinct_agents_produce_nonexpert_silver_verification(tmp_path: Path) -> None:
    _pack(tmp_path); source = "Authors must provide a data availability statement."
    initialize_rulepack_source(tmp_path, "sample", "https://journal.test/rules", source, "2026-09-04T00:00:00Z")
    finding = [{"field": "data_statement", "value": True, "evidence_excerpt": source}]
    annotate_rulepack_source(tmp_path, "sample", "agent-a", "model", "run-a", finding)
    annotate_rulepack_source(tmp_path, "sample", "agent-b", "model", "run-b", finding)
    result = adjudicate_rulepack_source(tmp_path, "sample", "agent-c", "model", "run-c", finding)
    assert result["status"].endswith("not_expert_calibrated")
    verification = verify_rulepack_silver(tmp_path, "sample")
    assert verification["ok"] is True
    assert verification["human_confirmed"] is False


def test_silver_verification_rejects_unbound_evidence_and_detects_rulepack_change(tmp_path: Path) -> None:
    _pack(tmp_path); source = "The limit is twelve pages."
    initialize_rulepack_source(tmp_path, "sample", "https://journal.test/rules", source, "2026-09-04")
    with pytest.raises(ValueError, match="verbatim"):
        annotate_rulepack_source(tmp_path, "sample", "agent-a", "model", "run-a", [{"field": "page_limit", "value": 12, "evidence_excerpt": "not present"}])
    finding = [{"field": "page_limit", "value": 12, "evidence_excerpt": source}]
    annotate_rulepack_source(tmp_path, "sample", "agent-a", "model", "run-a", finding)
    annotate_rulepack_source(tmp_path, "sample", "agent-b", "model", "run-b", finding)
    adjudicate_rulepack_source(tmp_path, "sample", "agent-c", "model", "run-c", finding)
    (tmp_path / "journal_profiles" / "sample" / "submission.yaml").write_text("version: 2\n", encoding="utf-8")
    assert verify_rulepack_silver(tmp_path, "sample")["ok"] is False
