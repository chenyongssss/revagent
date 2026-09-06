"""Build the checked-in, text-limited public evaluation release."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "release-v0.1"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest_values(values: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()


def main() -> None:
    registry = load(ROOT / ".revagent" / "public_review_registry.json")["cases"]
    quality = load(ROOT / ".revagent" / "public_review_quality_report.json")
    revision = load(ROOT / ".revagent" / "public_revision_corpus.json")
    local = load(ROOT / ".revagent" / "local_revision_corpus.json")
    selected = sorted(case_id for case_id, case in registry.items() if case.get("status") == "agent_adjudicated")
    public_cases = []
    revision_ids = {row["case_id"] for row in revision["cases"] if row["complete_revision_chain"]}
    for case_id in selected:
        case = registry[case_id]
        record = case["record"]
        public_cases.append({
            "case_id": case_id,
            "provider": record["provider"],
            "venue": record["venue"],
            "record_id": record["record_id"],
            "record_url": record["record_url"],
            "license": record["license"],
            "license_url": record["license_url"],
            "record_sha256": case["record_sha256"],
            "evaluation_tier": "complete_revision_chain" if case_id in revision_ids else "review_only_legacy",
            "expert_calibrated": False,
            "annotation_runs": [
                {"actor_id": value["actor_id"], "actor_kind": value["actor_kind"], "model": value["model"],
                 "run_id": value["run_id"], "input_sha256": value["input_sha256"], "findings": value["findings"]}
                for value in case["annotations"].values()
            ],
            "adjudication": {
                "actor_id": case["adjudication"]["actor_id"], "actor_kind": case["adjudication"]["actor_kind"],
                "model": case["adjudication"]["model"], "run_id": case["adjudication"]["run_id"],
                "findings": case["adjudication"]["findings"],
            },
        })
    dump(OUT / "public_cases.json", {"schema": "revagent.public-case-release/v1", "case_count": len(public_cases),
                                     "complete_revision_chain_count": sum(row["evaluation_tier"] == "complete_revision_chain" for row in public_cases),
                                     "review_only_legacy_count": sum(row["evaluation_tier"] == "review_only_legacy" for row in public_cases),
                                     "expert_calibrated": False, "cases": public_cases})
    safe_metrics = {key: quality["metrics"][key] for key in ("case_count", "adjudicated_finding_count", "mean_agent_agreement_jaccard", "mean_evidence_coverage", "by_role", "by_category", "provenance_completeness")}
    dump(OUT / "public_quality_report.json", {"schema": "revagent.public-quality-release/v1", "status": quality["status"],
                                               "evidence_tier": quality["evidence_tier"], "expert_calibrated": False,
                                               "metrics": safe_metrics, "limitations": quality["limitations"]})
    private_cases = []
    for index, row in enumerate(local["cases"], 1):
        hashes = [item["sha256"] for snapshot in row["snapshots"] for item in snapshot["files"]]
        hashes.extend(item["sha256"] for item in row["response_files"])
        private_cases.append({"case_id": f"case-{index}", "domain": "computational_mathematics",
                              "visibility": "private_metadata_only", "expected_rounds": row["expected_rounds"],
                              "available_manuscript_transitions": row["available_manuscript_transitions"],
                              "round_chain_complete": row["round_chain_complete"], "final_state_verifiable": row["final_state_verifiable"],
                              "outcome": row["outcome"], "aggregate_sha256": digest_values(hashes),
                              "raw_content_in_release": False, "expert_calibrated": False})
    dump(OUT / "private_case_metadata.json", {"schema": "revagent.private-case-metadata/v1", "case_count": len(private_cases),
                                               "privacy_note": "No manuscript, review, response, title, author, journal identifier, or local path is included.",
                                               "cases": private_cases})
    (OUT / "README.md").write_text(
        "# RevAgent evaluation release v0.1\n\n"
        "This directory contains eight licensed public-record proxy cases: five complete eLife revision chains and three legacy F1000 review-only cases. "
        "It also contains metadata-only fingerprints for three private computational-mathematics revision histories.\n\n"
        "The annotations were produced and adjudicated by agents. They are silver proxy labels, not human-expert calibration. "
        "Source URLs, licenses, attribution fields, immutable input hashes, annotation run IDs, and limitations are retained in the JSON files.\n\n"
        "No private manuscript or review text is included.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
