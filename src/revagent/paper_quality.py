"""Deterministic Phase-2 DOI and high-risk claim provenance reports."""
from __future__ import annotations

from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json
from .paper_ingestion import load_paper_manifest, paper_manifest_is_stale

STATUS = "public_source_metadata_and_structural_checks_not_expert_calibrated"


def _doi(value: object) -> str:
    return str(value or "").strip().lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def build_doi_verification_report(base: Path) -> dict:
    """Match local bibliography DOI values to consent-gated cached provider metadata."""
    config = load_config(base); manifest = load_paper_manifest(base)
    if paper_manifest_is_stale(base, manifest): raise ValueError("paper manifest is missing or stale; run paper-ingest")
    cached: dict[str, list[dict]] = {}
    for path in sorted((config.workspace / "literature_cache").glob("*.json")):
        record = read_json(path, {})
        for item in record.get("normalized_records", []):
            doi = _doi(item.get("doi"))
            if doi:
                cached.setdefault(doi, []).append({"provider": record.get("provider", ""), "endpoint": record.get("endpoint", ""),
                    "response_sha256": record.get("response_sha256", ""), "authorization_id": record.get("authorization_id", ""),
                    "title": item.get("title", "")})
    rows = []
    for key, entry in sorted(manifest.get("bibliography_entries", {}).items()):
        doi = _doi(entry.get("doi")); matches = cached.get(doi, []) if doi else []
        rows.append({"citation_key": key, "doi": doi, "status": "metadata_observed" if matches else ("missing_doi" if not doi else "not_in_cache"),
                     "provider_observations": matches})
    report = {"version": 1, "generated_at": now_iso(), "status": STATUS,
              "paper_input_fingerprint": manifest.get("input_fingerprint", ""), "entries": rows,
              "summary": {"total": len(rows), "metadata_observed": sum(row["status"] == "metadata_observed" for row in rows),
                          "missing_doi": sum(row["status"] == "missing_doi" for row in rows), "not_in_cache": sum(row["status"] == "not_in_cache" for row in rows)},
              "limitations": ["Provider metadata is external bibliographic observation, not manuscript evidence.",
                              "A cache miss does not establish that a DOI is invalid."]}
    write_json(config.workspace / "doi_verification_report.json", report); return report


def build_high_risk_traceability_report(base: Path) -> dict:
    """Fail closed when theorem-like claims lack any required provenance dimension."""
    config = load_config(base); manifest = load_paper_manifest(base)
    if paper_manifest_is_stale(base, manifest): raise ValueError("paper manifest is missing or stale; run paper-ingest")
    rows = []
    for claim in manifest.get("claims", []):
        requirements = {
            "source_span": bool(claim.get("source_span") and claim.get("content_sha256")),
            "pdf_page": claim.get("pdf_location", {}).get("status") == "observed" and bool(claim.get("pdf_location", {}).get("page")),
            "evidence": claim.get("evidence_state") in {"proof_environment_bound", "assumption_declaration"} or bool(claim.get("experiment_evidence")),
            "dependencies": not claim.get("claim_dependencies") or all(
                any(review.get("dependency_id") == dependency for review in claim.get("semantic_dependency_reviews", []))
                for dependency in claim.get("claim_dependencies", [])),
            "input_snapshot": bool(manifest.get("input_fingerprint")),
        }
        missing = [name for name, present in requirements.items() if not present]
        rows.append({"claim_id": claim.get("claim_id", ""), "kind": claim.get("kind", ""), "risk": "high",
                     "claim_sha256": claim.get("content_sha256", ""), "requirements": requirements,
                     "status": "traceable" if not missing else "blocked", "missing": missing})
    report = {"version": 1, "generated_at": now_iso(), "status": STATUS,
              "paper_input_fingerprint": manifest.get("input_fingerprint", ""), "claims": rows,
              "summary": {"total_high_risk": len(rows), "traceable": sum(row["status"] == "traceable" for row in rows),
                          "blocked": sum(row["status"] == "blocked" for row in rows)},
              "ok": all(row["status"] == "traceable" for row in rows),
              "limitations": ["Completeness is structural and does not establish mathematical correctness or experimental validity."]}
    write_json(config.workspace / "high_risk_traceability_report.json", report); return report
