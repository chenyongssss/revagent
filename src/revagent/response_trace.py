"""Local, non-conclusive response-to-evidence traceability snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ._utils import load_config, load_items, now_iso, read_json, read_text, write_json, write_text
from .candidates import load_candidates
from .experiments import load_experiment_manifests
from .proofs import load_proof_workflows


TRACE_FILES = ("review_items.json", "candidate_edits.json", "proof_workflows.json", "experiment_manifests.json", "response_letter.md", "apply_log.jsonl")


def response_trace_fingerprint(base: Path) -> str:
    config = load_config(base)
    digest = hashlib.sha256()
    for name in TRACE_FILES:
        path = config.workspace / name
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def response_trace_path(base: Path) -> Path:
    return load_config(base).workspace / "response_trace.json"


def response_trace_missing_or_stale(base: Path) -> bool:
    path = response_trace_path(base)
    if not path.exists() or not path.with_suffix(".md").exists():
        return True
    return read_json(path, {}).get("source_fingerprint") != response_trace_fingerprint(base)


def _response_locator(letter: str, item_id: str) -> dict[str, object]:
    lines = letter.splitlines()
    heading = f"## {item_id}"
    start = next((index + 1 for index, line in enumerate(lines) if line.strip() == heading), 0)
    if not start:
        return {"status": "missing", "line": 0}
    end = next((index + 1 for index, line in enumerate(lines[start:], start=start) if line.startswith("## ")), len(lines))
    return {"status": "present", "line": start, "end_line": end, "sha256": hashlib.sha256("\n".join(lines[start - 1:end]).encode("utf-8")).hexdigest()}


def _final_pdf(config) -> dict[str, object]:
    path = config.tex_root / Path(config.main_tex).with_suffix(".pdf")
    if not path.is_file():
        return {"status": "not_assessed", "path": str(path.relative_to(config.tex_root)), "sha256": ""}
    return {"status": "present", "path": str(path.relative_to(config.tex_root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build_response_trace(base: Path) -> dict[str, object]:
    """Build a four-way trace; statuses represent provenance completeness only."""
    config = load_config(base)
    items = load_items(config)
    candidates = load_candidates(config)
    workflows = load_proof_workflows(config)
    manifests = load_experiment_manifests(config)
    letter_path = config.workspace / "response_letter.md"
    letter = read_text(letter_path) if letter_path.exists() else ""
    by_item: dict[str, list[dict]] = {}
    for candidate in candidates:
        by_item.setdefault(str(candidate.get("item_id", "")), []).append(candidate)
    records = []
    for item in items:
        item_id = str(item.get("id", ""))
        proof = workflows.get(item_id, {}) if item.get("kind") == "proof" else {}
        experiment = manifests.get(item_id, {}) if item.get("kind") == "experiment" else {}
        evidence = {"status": "not_assessed", "kind": "none"}
        if proof:
            evidence = {"status": "recorded" if proof.get("revision_diff", {}).get("status") == "recorded" else "not_assessed", "kind": "proof", "workflow_id": proof.get("id", ""), "approval_status": proof.get("approval_status", "required"), "revision_diff": proof.get("revision_diff", {})}
        elif experiment:
            evidence = {"status": "recorded" if experiment.get("artifacts") else "not_assessed", "kind": "experiment", "manifest_id": experiment.get("id", ""), "artifacts": experiment.get("artifacts", []), "backfill_targets": experiment.get("backfill_targets", [])}
        linked_candidates = [{"id": candidate.get("id", ""), "status": candidate.get("status", ""), "target_file": candidate.get("target_file", ""), "applied_at": candidate.get("applied_at", "")} for candidate in by_item.get(item_id, [])]
        records.append({
            "item_id": item_id,
            "review_request": {"reviewer": item.get("reviewer", ""), "source_locator": item.get("source_locator", item.get("source", "")), "comment_sha256": hashlib.sha256(str(item.get("comment", "")).encode("utf-8")).hexdigest()},
            "response_assertion": _response_locator(letter, item_id),
            "manuscript_diff": {"status": "applied" if any(candidate["status"] == "applied" for candidate in linked_candidates) else "not_assessed", "candidates": linked_candidates},
            "evidence": evidence,
            "final_pdf": _final_pdf(config),
        })
    return {"version": 1, "generated_at": now_iso(), "source_fingerprint": response_trace_fingerprint(base), "records": records}


def render_response_trace(trace: dict[str, object], item_id: str | None = None) -> str:
    records = [record for record in trace.get("records", []) if not item_id or record.get("item_id") == item_id]
    if item_id and not records:
        raise ValueError(f"unknown review item {item_id}")
    lines = ["# Response Trace", "", "This is a provenance completeness report; it does not verify mathematical or scientific claims.", ""]
    for record in records:
        response, diff, evidence, pdf = record["response_assertion"], record["manuscript_diff"], record["evidence"], record["final_pdf"]
        lines.extend([f"## {record['item_id']}", "", f"- Request: {record['review_request'].get('source_locator') or 'missing'}", f"- Response assertion: {response.get('status')} line={response.get('line', 0)}", f"- Manuscript diff: {diff.get('status')}", f"- Evidence: {evidence.get('kind')} / {evidence.get('status')}", f"- Final PDF: {pdf.get('status')} {pdf.get('path', '')}", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_response_trace(base: Path) -> dict[str, object]:
    config = load_config(base)
    trace = build_response_trace(base)
    write_json(config.workspace / "response_trace.json", trace)
    write_text(config.workspace / "response_trace.md", render_response_trace(trace))
    return trace


__all__ = ["build_response_trace", "render_response_trace", "response_trace_missing_or_stale", "write_response_trace"]
