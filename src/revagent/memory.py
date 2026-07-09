"""Generated revision memory facts for external agent grounding."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ._models import Config
from ._utils import first_sentence, load_config, load_items, now_iso, read_json, write_json, write_text
from .candidates import load_candidates
from .llm import ensure_llm_review_fields, load_llm_drafts
from .planning import load_item_plans
from .provenance import build_revision_provenance
from .readiness import build_revision_readiness
from .review_analysis import load_review_analyses

MEMORY_SOURCE_FILES = [
    "review_items.json",
    "review_analyses.json",
    "item_plans.json",
    "candidate_edits.json",
    "llm_drafts.json",
    "proof_workflows.json",
    "experiment_manifests.json",
    "experiment_run_attempts.jsonl",
    "experiment_runs.jsonl",
    "revision_provenance.json",
    "revision_readiness.json",
]


def memory_source_fingerprint(config: Config) -> str:
    digest = hashlib.sha256()
    for name in MEMORY_SOURCE_FILES:
        path = config.workspace / name
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def memory_path(config: Config) -> Path:
    return config.workspace / "revision_memory.json"


def memory_missing_or_stale(config: Config) -> bool:
    path = memory_path(config)
    if not path.exists() or not (config.workspace / "revision_memory.md").exists():
        return True
    try:
        memory = read_json(path, {})
    except Exception:
        return True
    return memory.get("source_fingerprint") != memory_source_fingerprint(config)


def candidates_by_item(candidates: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for candidate in candidates:
        grouped.setdefault(str(candidate.get("item_id", "")), []).append(candidate)
    return grouped


def status_command(fact: dict[str, object]) -> str:
    manual = list(fact.get("manual_actions", []))
    missing = list(fact.get("missing_inputs", []))
    item_id = str(fact.get("item_id", ""))
    if "author proof approval" in manual:
        return f"revagent proof-approve {item_id} --note \"AUTHOR NOTE\""
    if any("experiment" in entry for entry in manual + missing):
        return f"revagent experiment-plan {item_id}"
    if "review analysis" in missing:
        return f"revagent analyze-review {item_id}"
    if "item plan" in missing:
        return f"revagent plan-item {item_id}"
    if "candidate edit" in missing or fact.get("candidate_status") in {"missing", "needs_review"}:
        return "revagent propose"
    if fact.get("candidate_status") == "approved_unapplied":
        return "revagent apply --dry-run"
    if "response update" in missing:
        return "revagent draft"
    return "revagent agent-next"


def build_item_memory_fact(
    item: dict,
    *,
    analysis: dict,
    plan: dict,
    readiness: dict,
    provenance: dict,
    item_candidates: list[dict],
    draft: dict | None,
) -> dict[str, object]:
    draft = ensure_llm_review_fields(dict(draft or {})) if draft else {}
    fact = {
        "item_id": item.get("id", ""),
        "kind": item.get("kind", ""),
        "risk": item.get("risk", ""),
        "reviewer": item.get("reviewer", ""),
        "request": first_sentence(str(item.get("comment", ""))),
        "intent": analysis.get("intent_summary", ""),
        "claim_targets": analysis.get("claim_targets", []),
        "evidence_needs": analysis.get("evidence_needs", []),
        "planning_status": item.get("planning_status", ""),
        "readiness_status": readiness.get("readiness_status", ""),
        "missing_inputs": readiness.get("missing_inputs", []),
        "manual_actions": readiness.get("manual_actions", []),
        "candidate_status": readiness.get("candidate_status", ""),
        "proof_status": readiness.get("proof_status", ""),
        "experiment_status": readiness.get("experiment_status", ""),
        "response_status": readiness.get("response_status", ""),
        "validation_status": readiness.get("validation_status", ""),
        "provenance_status": provenance.get("provenance_status", ""),
        "candidate_ids": [candidate.get("id", "") for candidate in item_candidates],
        "candidate_statuses": {candidate.get("id", ""): candidate.get("status", "") for candidate in item_candidates},
        "llm_review_status": draft.get("review_status", "missing") if draft else "missing",
        "llm_quality_status": draft.get("quality_status", "missing") if draft else "missing",
        "completion_criteria": plan.get("completion_criteria", item.get("completion_criteria", [])),
        "blocked": bool(readiness.get("manual_actions") or readiness.get("missing_inputs")),
    }
    fact["next_command"] = status_command(fact)
    return fact


def build_revision_memory(base: Path) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    analyses = load_review_analyses(config)
    plans = load_item_plans(config)
    candidates = load_candidates(config)
    drafts = load_llm_drafts(config)
    readiness = build_revision_readiness(base)
    provenance = build_revision_provenance(base)
    readiness_by_item = {item.get("item_id"): item for item in readiness.get("items", [])}
    provenance_by_item = {item.get("item_id"): item for item in provenance.get("items", [])}
    grouped_candidates = candidates_by_item(candidates)
    facts = [
        build_item_memory_fact(
            item,
            analysis=analyses.get(str(item.get("id", "")), {}),
            plan=plans.get(str(item.get("id", "")), {}),
            readiness=readiness_by_item.get(str(item.get("id", "")), {}),
            provenance=provenance_by_item.get(str(item.get("id", "")), {}),
            item_candidates=grouped_candidates.get(str(item.get("id", "")), []),
            draft=drafts.get(str(item.get("id", ""))),
        )
        for item in items
    ]
    counts: dict[str, int] = {}
    for fact in facts:
        status = str(fact.get("readiness_status", "") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "version": 1,
        "generated_at": now_iso(),
        "source_fingerprint": memory_source_fingerprint(config),
        "workspace": str(config.workspace),
        "summary_counts": counts,
        "facts": facts,
    }


def render_revision_memory(memory: dict[str, object], item_id: str | None = None) -> str:
    facts = list(memory.get("facts", []))
    if item_id:
        facts = [fact for fact in facts if fact.get("item_id") == item_id]
        if not facts:
            raise ValueError(f"unknown memory item {item_id}")
    lines = [
        "# Revision Memory",
        "",
        f"- Generated at: {memory.get('generated_at', '')}",
        f"- Counts: {', '.join(f'{key}={value}' for key, value in sorted((memory.get('summary_counts') or {}).items())) or 'none'}",
        "",
    ]
    if not facts:
        lines.append("No review memory facts recorded.")
        return "\n".join(lines) + "\n"
    for fact in facts:
        lines.extend(
            [
                f"## {fact.get('item_id', '')} [{fact.get('kind', '')}, {fact.get('risk', '')} risk]",
                "",
                f"- Request: {fact.get('request', '')}",
                f"- Intent: {fact.get('intent', '') or 'unknown'}",
                f"- Readiness: {fact.get('readiness_status', '')}",
                f"- Provenance: {fact.get('provenance_status', '')}",
                f"- Missing: {', '.join(fact.get('missing_inputs', [])) or 'none'}",
                f"- Manual: {', '.join(fact.get('manual_actions', [])) or 'none'}",
                f"- Candidates: {', '.join(fact.get('candidate_ids', [])) or 'none'}",
                f"- LLM: review={fact.get('llm_review_status', '')} quality={fact.get('llm_quality_status', '')}",
                f"- Next command: `{fact.get('next_command', '')}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_revision_memory(base: Path) -> dict[str, object]:
    config = load_config(base)
    memory = build_revision_memory(base)
    write_json(config.workspace / "revision_memory.json", memory)
    write_text(config.workspace / "revision_memory.md", render_revision_memory(memory))
    return memory


def memory_for_item(base: Path, item_id: str | None = None) -> str:
    memory = write_revision_memory(base)
    return render_revision_memory(memory, item_id=item_id)


__all__ = [
    "build_revision_memory",
    "memory_for_item",
    "memory_missing_or_stale",
    "render_revision_memory",
    "write_revision_memory",
]
