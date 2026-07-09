"""End-to-end revision provenance snapshots."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from ._models import Config
from ._utils import find_item, first_sentence, load_config, load_items, now_iso, read_json, read_text, write_json, write_text
from .candidates import load_candidates
from .experiments import load_experiment_manifests
from .llm import ensure_llm_review_fields, load_llm_drafts
from .proofs import load_proof_workflows

PROVENANCE_SOURCE_FILES = [
    "review_items.json",
    "candidate_edits.json",
    "llm_drafts.json",
    "proof_workflows.json",
    "experiment_manifests.json",
    "apply_log.jsonl",
    "experiment_runs.jsonl",
]


def source_fingerprint(config: Config) -> str:
    digest = hashlib.sha256()
    for name in PROVENANCE_SOURCE_FILES:
        path = config.workspace / name
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def provenance_path(config: Config) -> Path:
    return config.workspace / "revision_provenance.json"


def provenance_missing_or_stale(config: Config) -> bool:
    path = provenance_path(config)
    if not path.exists() or not (config.workspace / "revision_provenance.md").exists():
        return True
    provenance = read_json(path, {})
    return provenance.get("source_fingerprint") != source_fingerprint(config)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"invalid": line})
    return records


def apply_records_by_candidate(config: Config) -> dict[str, list[dict]]:
    records: dict[str, list[dict]] = {}
    for entry in read_jsonl(config.workspace / "apply_log.jsonl"):
        candidate_id = str(entry.get("candidate_id", ""))
        if candidate_id:
            records.setdefault(candidate_id, []).append(entry)
    return records


def location_summary(item: dict) -> dict[str, object]:
    loc = (item.get("tex_locations") or [{}])[0]
    return {
        "file": loc.get("file", ""),
        "line": loc.get("line", 0),
        "score": loc.get("score", 0),
        "context_type": loc.get("context_type", ""),
        "context_title": loc.get("context_title", ""),
    }


def draft_summary(drafts: dict[str, dict], item_id: str) -> dict[str, object]:
    draft = drafts.get(item_id)
    if not draft:
        return {"present": False}
    draft = ensure_llm_review_fields(dict(draft))
    return {
        "present": True,
        "draft_source": draft.get("draft_source", ""),
        "provider": draft.get("provider", ""),
        "review_status": draft.get("review_status", ""),
        "quality_status": draft.get("quality_status", ""),
        "quality_issues": draft.get("quality_issues", []),
        "reviewed_at": draft.get("reviewed_at", ""),
        "edited_at": draft.get("edited_at", ""),
        "quality_checked_at": draft.get("quality_checked_at", ""),
    }


def candidate_summary(candidate: dict, apply_records: dict[str, list[dict]]) -> dict[str, object]:
    return {
        "id": candidate.get("id", ""),
        "kind": candidate.get("kind", ""),
        "status": candidate.get("status", ""),
        "draft_source": candidate.get("draft_source", ""),
        "llm_draft_id": candidate.get("llm_draft_id", ""),
        "author_edited": bool(candidate.get("author_edited")),
        "target_file": candidate.get("target_file", ""),
        "anchor_line": candidate.get("anchor_line", 0),
        "operation": candidate.get("operation", "insert_after_line"),
        "approved_at": candidate.get("approved_at", ""),
        "applied_at": candidate.get("applied_at", ""),
        "backup_dir": candidate.get("backup_dir", ""),
        "apply_log": apply_records.get(str(candidate.get("id", "")), []),
    }


def proof_summary(workflows: dict[str, dict], item: dict) -> dict[str, object]:
    workflow = workflows.get(item.get("id", ""))
    lane = item.get("proof_lane") or {}
    if not workflow and not lane:
        return {}
    return {
        "workflow_present": bool(workflow),
        "workflow_status": (workflow or {}).get("status", lane.get("workflow_status", "")),
        "approval_status": (workflow or {}).get("approval_status", lane.get("approval_status", "required")),
        "approval_note": (workflow or {}).get("approval_note", ""),
        "open_obligations": [
            obligation
            for obligation in (workflow or {}).get("proof_obligations", lane.get("proof_obligations", []))
            if obligation.get("status") != "closed"
        ],
        "dependency_refs": (workflow or {}).get("dependency_refs", lane.get("dependency_refs", [])),
    }


def experiment_summary(manifests: dict[str, dict], item: dict) -> dict[str, object]:
    manifest = manifests.get(item.get("id", ""))
    lane = item.get("experiment_lane") or {}
    if not manifest and not lane:
        return {}
    return {
        "manifest_present": bool(manifest),
        "status": (manifest or {}).get("status", lane.get("contract_status", "")),
        "result_status": lane.get("result_status", "not_recorded"),
        "artifacts": (manifest or {}).get("artifacts", []),
        "backfill_targets": (manifest or {}).get("backfill_targets", lane.get("backfill_targets", [])),
        "recorded_results": lane.get("recorded_results", []),
    }


def provenance_status(record: dict) -> str:
    candidates = record.get("candidates", [])
    if any(candidate.get("status") == "applied" for candidate in candidates):
        return "applied"
    if any(candidate.get("status") == "approved" for candidate in candidates):
        return "approved"
    if any(candidate.get("status") in {"proposed", "edited", "blocked"} for candidate in candidates):
        return "candidate_pending"
    if record.get("llm_draft", {}).get("present"):
        return "drafted"
    return "planned"


def build_revision_provenance(base: Path) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    candidates = load_candidates(config)
    drafts = load_llm_drafts(config)
    workflows = load_proof_workflows(config)
    manifests = load_experiment_manifests(config)
    apply_records = apply_records_by_candidate(config)
    by_item: dict[str, list[dict]] = {}
    for candidate in candidates:
        by_item.setdefault(str(candidate.get("item_id", "")), []).append(candidate)
    records = []
    for item in items:
        item_id = str(item.get("id", ""))
        record = {
            "item_id": item_id,
            "kind": item.get("kind", ""),
            "risk": item.get("risk", ""),
            "planning_status": item.get("planning_status", ""),
            "reviewer": item.get("reviewer", ""),
            "comment": item.get("comment", ""),
            "comment_summary": first_sentence(item.get("comment", "")),
            "location": location_summary(item),
            "llm_draft": draft_summary(drafts, item_id),
            "candidates": [candidate_summary(candidate, apply_records) for candidate in by_item.get(item_id, [])],
            "proof": proof_summary(workflows, item) if item.get("kind") == "proof" else {},
            "experiment": experiment_summary(manifests, item) if item.get("kind") == "experiment" else {},
        }
        record["provenance_status"] = provenance_status(record)
        records.append(record)
    return {
        "version": 1,
        "generated_at": now_iso(),
        "source_fingerprint": source_fingerprint(config),
        "workspace": str(config.workspace),
        "items": records,
    }


def render_revision_provenance(provenance: dict[str, object], item_id: str | None = None) -> str:
    records = list(provenance.get("items", []))
    if item_id:
        records = [record for record in records if record.get("item_id") == item_id]
        if not records:
            raise ValueError(f"unknown provenance item {item_id}")
    lines = ["# Revision Provenance", "", f"- Generated at: {provenance.get('generated_at', '')}", ""]
    if not records:
        lines.append("No review items recorded.")
        return "\n".join(lines) + "\n"
    for record in records:
        loc = record.get("location", {})
        draft = record.get("llm_draft", {})
        lines.extend(
            [
                f"## {record.get('item_id')} [{record.get('kind')}, {record.get('risk')} risk]",
                "",
                f"- Status: {record.get('provenance_status')} / planning={record.get('planning_status')}",
                f"- Reviewer: {record.get('reviewer') or 'unknown'}",
                f"- Comment: {record.get('comment_summary')}",
                f"- Location: {loc.get('file') or 'unknown'}:{loc.get('line') or 'unknown'} score={loc.get('score', 0)}",
                f"- LLM draft: review={draft.get('review_status', 'missing')} quality={draft.get('quality_status', 'missing')} provider={draft.get('provider', 'missing')}",
                "",
                "### Candidates",
                "",
            ]
        )
        candidates = record.get("candidates", [])
        if candidates:
            for candidate in candidates:
                lines.append(
                    f"- `{candidate.get('id')}` {candidate.get('status')} "
                    f"{candidate.get('operation')} {candidate.get('target_file')}:{candidate.get('anchor_line')} "
                    f"approved={candidate.get('approved_at') or 'no'} applied={candidate.get('applied_at') or 'no'}"
                )
        else:
            lines.append("- None.")
        proof = record.get("proof", {})
        if proof:
            lines.extend(["", "### Proof Gate", ""])
            lines.append(f"- Workflow: {proof.get('workflow_status', 'missing')} approval={proof.get('approval_status', 'required')}")
            lines.append(f"- Open obligations: {len(proof.get('open_obligations', []))}")
        experiment = record.get("experiment", {})
        if experiment:
            lines.extend(["", "### Experiment Provenance", ""])
            lines.append(f"- Manifest: {experiment.get('status', 'missing')} result={experiment.get('result_status', 'not_recorded')}")
            lines.append(f"- Artifacts: {len(experiment.get('artifacts', []))}")
            lines.append(f"- Backfill targets: {len(experiment.get('backfill_targets', []))}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_revision_provenance(base: Path) -> dict[str, object]:
    config = load_config(base)
    provenance = build_revision_provenance(base)
    write_json(config.workspace / "revision_provenance.json", provenance)
    write_text(config.workspace / "revision_provenance.md", render_revision_provenance(provenance))
    return provenance


def provenance_for_item(base: Path, item_id: str | None = None) -> str:
    provenance = write_revision_provenance(base)
    return render_revision_provenance(provenance, item_id=item_id)


__all__ = [
    "build_revision_provenance",
    "provenance_for_item",
    "provenance_missing_or_stale",
    "render_revision_provenance",
    "source_fingerprint",
    "write_revision_provenance",
]
