"""Author-focused reviewer-comment to verified-rebuttal workflow."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .reviews import classify_item, risk_for, normalize_review_comments, parse_review_requests

HIGH_RISK = {"proof", "experiment", "statistics", "data", "clinical_or_ethics"}


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_comment_atoms(base: Path, comments_path: str) -> dict[str, object]:
    config = load_config(base)
    source = (base / comments_path).resolve()
    if not source.is_file() or base.resolve() not in source.parents:
        raise ValueError("reviewer comments must be an existing file inside the local project")
    raw, imported = normalize_review_comments(base, source, config.workspace)
    atoms = []
    for index, request in enumerate(parse_review_requests(raw), 1):
        text = request["comment"]
        kind = classify_item(text)
        atom_id = f"CA-{index:04d}"
        atoms.append({
            "atom_id": atom_id, "reviewer_id": request["reviewer"], "source_comment": text,
            "source_locator": f"{imported['normalized_path']}:{request['line_start']}-{request['line_end']}",
            "source_hash": imported["source_hash"], "request_type": kind,
            "lane": kind, "risk_level": risk_for(kind, text), "status": "triaged",
            "manuscript_scope": [], "claim_refs": [], "evidence_requirements": [],
            "author_decision": None, "revision_task_id": f"RT-{index:04d}",
            "candidate_ids": [], "verification_ids": [], "rebuttal_atom_id": f"RB-CA-{index:04d}",
            "uncertainty": "high" if kind in HIGH_RISK else "medium",
            "human_gate": kind in HIGH_RISK, "created_at": now_iso(),
        })
    result = {"version": 1, "generated_at": now_iso(), "input": imported, "atoms": atoms,
              "status": "awaiting_author_decisions"}
    write_json(config.workspace / "review_comment_atoms.json", result)
    return result


def plan_revision_tasks(base: Path) -> dict[str, object]:
    config = load_config(base)
    payload = read_json(config.workspace / "review_comment_atoms.json", {})
    atoms = payload.get("atoms", [])
    tasks = []
    for atom in atoms:
        task = {"version": 1, "task_id": atom["revision_task_id"], "atom_id": atom["atom_id"],
                "action_type": f"address_{atom['request_type']}", "required_inputs": [],
                "expected_artifacts": [], "affected_files": [], "verification_plan": ["recompile", "consistency"],
                "author_gate": bool(atom["human_gate"]), "dependencies": [],
                "status": "awaiting_author" if atom["human_gate"] else "ready"}
        tasks.append(task); atom["status"] = "planned"
    result = {"version": 1, "generated_at": now_iso(), "tasks": tasks}
    write_json(config.workspace / "revision_tasks.json", result)
    write_json(config.workspace / "review_comment_atoms.json", payload)
    return result


def revision_consistency_report(base: Path) -> dict[str, object]:
    config = load_config(base)
    atoms_payload = read_json(config.workspace / "review_comment_atoms.json", {})
    rebuttal = read_json(config.workspace / "rebuttal_threads.json", {})
    tasks = read_json(config.workspace / "revision_tasks.json", {}).get("tasks", [])
    candidates = read_json(config.workspace / "candidate_edits.json", [])
    candidate_ids = {str(c.get("id")) for c in candidates if isinstance(c, dict)}
    task_by_atom = {str(t.get("atom_id")): t for t in tasks if isinstance(t, dict)}
    rows, failures = [], []
    rebuttal_atoms = {str(a.get("source_item_id")): a for thread in rebuttal.get("threads", {}).values() for a in thread.get("atoms", [])}
    for atom in atoms_payload.get("atoms", []):
        aid = str(atom["atom_id"]); task = task_by_atom.get(aid, {}); response = rebuttal_atoms.get(f"R{int(aid.split('-')[-1]):03d}")
        checks = {"task_exists": bool(task), "candidate_linked": all(str(cid) in candidate_ids for cid in atom.get("candidate_ids", [])),
                  "response_exists": bool(response and str(response.get("response_text", "")).strip()),
                  "high_risk_gated": not atom["human_gate"] or task.get("status") in {"awaiting_author", "approved", "verified"}}
        if not all(checks.values()): failures.append({"atom_id": aid, "checks": checks})
        rows.append({"atom_id": aid, "task_id": atom["revision_task_id"], "checks": checks,
                     "status": "consistent" if all(checks.values()) else "blocked"})
    report = {"version": 1, "generated_at": now_iso(), "status": "ready" if not failures and rows else "author_review_required",
              "ok": not failures and bool(rows), "atoms": rows, "failures": failures,
              "limitations": ["Consistency and execution checks do not establish scientific correctness."]}
    write_json(config.workspace / "revision_consistency.json", report)
    write_text(config.workspace / "revision_consistency.md", "# Revision Consistency\n\n" + "\n".join(f"- `{r['atom_id']}`: {r['status']}" for r in rows) + "\n")
    return report


def generate_revision_candidates(base: Path) -> dict[str, object]:
    """Reuse the existing guarded candidate engine and bind candidates to atoms."""
    from .candidates import propose_candidates
    config = load_config(base)
    candidates = propose_candidates(base)
    atoms_payload = read_json(config.workspace / "review_comment_atoms.json", {})
    atoms = atoms_payload.get("atoms", [])
    items = read_json(config.workspace / "review_items.json", [])
    item_by_id = {str(item.get("id")): item for item in items if isinstance(item, dict)}
    for atom in atoms:
        item = item_by_id.get(f"R{int(atom['atom_id'].split('-')[-1]):03d}")
        linked = [candidate for candidate in candidates if item and candidate.get("item_id") == item.get("id")]
        atom["candidate_ids"] = [str(candidate.get("id")) for candidate in linked]
        atom["manuscript_scope"] = [{"file": c.get("target_file"), "line": c.get("anchor_line"), "hash": c.get("original_content_hash")} for c in linked]
        if linked and any(c.get("status") in {"proposed", "edited"} for c in linked):
            atom["status"] = "candidate_ready"
    write_json(config.workspace / "review_comment_atoms.json", atoms_payload)
    return {"candidates": candidates, "atoms": atoms}


def run_revision_workflow(base: Path, comments_path: str) -> dict[str, object]:
    from .reviews import ingest_comments
    ingest_comments(base, comments_path)
    atoms = build_comment_atoms(base, comments_path)
    tasks = plan_revision_tasks(base)
    candidates = generate_revision_candidates(base)
    from .rebuttal import parse_rebuttal, rebuttal_plan, rebuttal_draft
    parse_rebuttal(base); rebuttal_plan(base); rebuttal_draft(base)
    consistency = revision_consistency_report(base)
    return {"atoms": atoms, "tasks": tasks, "candidates": candidates, "consistency": consistency}


def apply_revision_candidates(base: Path) -> dict[str, object]:
    """Apply only candidates already approved through the existing author gate."""
    from .candidates import apply_approved_candidates
    from .validation import validate_workspace
    result = apply_approved_candidates(base)
    validation = validate_workspace(base, compile_check=False)
    from .paper_ingestion import build_paper_manifest
    manifest = build_paper_manifest(base)
    config = load_config(base)
    atoms_payload = read_json(config.workspace / "review_comment_atoms.json", {})
    applied = set(result.get("applied", []))
    for atom in atoms_payload.get("atoms", []):
        if applied.intersection(str(cid) for cid in atom.get("candidate_ids", [])):
            atom["status"] = "applied"
    write_json(config.workspace / "review_comment_atoms.json", atoms_payload)
    tasks = read_json(config.workspace / "revision_tasks.json", {})
    for task in tasks.get("tasks", []):
        atom = next((a for a in atoms_payload.get("atoms", []) if a.get("revision_task_id") == task.get("task_id")), None)
        if atom and atom.get("status") == "applied":
            task["status"] = "verification_required"
    write_json(config.workspace / "revision_tasks.json", tasks)
    from .rebuttal import rebuttal_draft
    rebuttal_draft(base)
    consistency = revision_consistency_report(base)
    package = {
        "version": 1, "generated_at": now_iso(),
        "status": "ready_for_author_submission" if consistency.get("ok") and not validation.get("issues") else "author_review_required",
        "consistency": consistency, "validation": validation,
        "manifest_fingerprint": manifest.get("input_fingerprint", ""),
        "limitations": ["Ready status means local traceability checks passed; it is not a scientific correctness or journal acceptance decision."],
    }
    write_json(config.workspace / "submission_package_status.json", package)
    return {"apply": result, "validation": validation, "manifest": manifest, "consistency": consistency, "package": package}
