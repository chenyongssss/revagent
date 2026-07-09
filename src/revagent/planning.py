"""Per-review-item planning and status workflow public API."""

from __future__ import annotations

import json
from pathlib import Path

from ._utils import append_decision_log, find_item, first_sentence, load_config, load_items, now_iso, read_json, write_items, write_json, write_text
from .candidates import load_candidates
from .review_analysis import analyze_review_item, load_review_analyses
from .reviews import experiment_lane_template, proof_lane_template

def reasoning_for_item(base: Path, item_id: str) -> str:
    config = load_config(base)
    items = load_items(config)
    candidates = load_candidates(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    analysis = analyze_review_item(base, item_id)
    loc = (item.get("tex_locations") or [{}])[0]
    linked = [candidate for candidate in candidates if candidate.get("item_id") == item_id]
    plan = item.get("revision_plan") or {}
    blocked = []
    if item.get("kind") == "proof":
        blocked.append("author must verify nontrivial mathematical steps")
    if item.get("kind") == "experiment" and (item.get("experiment_lane") or {}).get("result_status") != "recorded":
        blocked.append("experiment result provenance is not recorded")
    lines = [
        f"# Revision Reasoning for {item_id}",
        "",
        f"- Reviewer intent: {first_sentence(item['comment'])}",
        f"- Analysis intent: {analysis.get('intent_summary', '')}",
        f"- Requested change: {analysis.get('requested_change', '')}",
        f"- Lane: {item.get('lane', item.get('kind'))}",
        f"- Severity: {item.get('severity', item.get('risk'))}",
        f"- Manuscript context: {loc.get('context_type', 'unknown')} {loc.get('context_title', '')} at {loc.get('file', 'unknown')}:{loc.get('line', 'unknown')}",
        f"- Location rationale: {loc.get('reason', 'not located')} score={loc.get('score', 0)}",
        f"- Proposed action: {'review candidate edits and author confirmations' if linked else 'generate candidate edit'}",
        f"- Risk: {item.get('risk')}",
        f"- Planning status: {item.get('planning_status', item.get('status', 'triaged'))}",
        f"- Blocked questions: {', '.join(blocked) if blocked else 'none'}",
        "",
        "## Claim Targets",
        "",
        *[f"- {target}" for target in analysis.get("claim_targets", [])],
        "",
        "## Evidence Needs",
        "",
        *[f"- {need}" for need in analysis.get("evidence_needs", [])],
        "",
        "## Author Verification",
        "",
        *[f"- {need}" for need in analysis.get("author_verification", [])],
        "",
    ]
    if plan:
        lines.extend(
            [
                "## Planned Criteria",
                "",
                *[f"- {criterion}" for criterion in plan.get("completion_criteria", [])],
                "",
            ]
        )
    append_decision_log(config, f"Reasoning generated for {item_id}", [f"- Risk: {item.get('risk')}", f"- Blocked: {', '.join(blocked) if blocked else 'none'}"])
    return "\n".join(lines)

def load_item_plans(config: Config) -> dict[str, dict]:
    return read_json(config.workspace / "item_plans.json", {})

def write_item_plans(config: Config, plans: dict[str, dict]) -> None:
    write_json(config.workspace / "item_plans.json", plans)
    write_text(config.workspace / "item_plans.md", render_item_plans(plans))

def reviewer_intent_decomposition(item: dict, analysis: dict | None = None) -> list[str]:
    if analysis:
        return [
            f"Intent: {analysis.get('intent_summary', '')}",
            f"Requested change: {analysis.get('requested_change', '')}",
            "Claim targets: " + "; ".join(analysis.get("claim_targets", [])),
        ]
    comment = first_sentence(item.get("comment", ""))
    if item.get("kind") == "proof":
        return [
            f"Identify the mathematical claim behind: {comment}",
            "Check whether the theorem/lemma statement, assumptions, and proof steps align.",
            "Separate author-verified mathematics from RevAgent-generated placeholder text.",
        ]
    if item.get("kind") == "experiment":
        return [
            f"Identify the empirical evidence requested by: {comment}",
            "Specify reproducible command, parameters, seed, expected artifacts, and paper backfill target.",
            "Do not incorporate numerical conclusions until result provenance is recorded.",
        ]
    return [
        f"Clarify the manuscript concern behind: {comment}",
        "Locate the paragraph or section most likely to address the reviewer intent.",
        "Prepare a conservative manuscript edit and matching response-letter reference.",
    ]

def required_evidence_for_item(item: dict, analysis: dict | None = None) -> list[str]:
    if analysis and analysis.get("evidence_needs"):
        return list(analysis["evidence_needs"])
    loc = (item.get("tex_locations") or [{}])[0]
    if item.get("kind") == "proof":
        lane = item.get("proof_lane") or {}
        return [
            f"affected claim: {lane.get('nearest_claim') or lane.get('affected_claim') or 'author must identify'}",
            f"assumptions/dependencies: {', '.join(lane.get('dependencies', [])) or 'author must verify'}",
            "author-verified proof obligation closure before approval",
        ]
    if item.get("kind") == "experiment":
        lane = item.get("experiment_lane") or {}
        return [
            f"command template: {lane.get('command') or 'TBD'}",
            f"seed/parameters: {lane.get('seed') or 'TBD'} / {json.dumps(lane.get('parameters', {}), ensure_ascii=False)}",
            f"recorded result artifact: {', '.join(lane.get('observed_artifacts', [])) or 'not recorded'}",
            f"paper backfill target: {', '.join(lane.get('paper_locations', [])) or loc.get('context_title') or 'TBD'}",
        ]
    return [
        f"manuscript target: {loc.get('file', 'unknown')}:{loc.get('line', 'unknown')}",
        "author-approved replacement or insertion text",
        "response-letter pointer to revised location",
    ]

def manuscript_edit_plan_for_item(item: dict, candidates: list[dict], analysis: dict | None = None) -> list[str]:
    linked = [candidate for candidate in candidates if candidate.get("item_id") == item.get("id")]
    loc = (item.get("tex_locations") or [{}])[0]
    if linked:
        planned = [
            f"review candidate {candidate['id']} ({candidate.get('operation', 'insert_after_line')}) at {candidate.get('target_file')}:{candidate.get('anchor_line')}"
            for candidate in linked
        ]
        if analysis and analysis.get("manuscript_action"):
            planned.insert(0, str(analysis["manuscript_action"]))
        return planned
    if analysis and analysis.get("manuscript_action"):
        return [str(analysis["manuscript_action"])]
    return [
        f"generate candidate insertion near {loc.get('file', 'unknown')}:{loc.get('line', 'unknown')}",
        "keep generated text as a TODO/placeholder unless the author supplies final wording",
    ]

def dependency_plan_for_item(item: dict) -> list[str]:
    if item.get("kind") == "proof":
        lane = item.get("proof_lane") or {}
        deps = lane.get("dependencies", [])
        return [
            f"nearest claim: {lane.get('nearest_claim') or 'TBD'}",
            f"tracked labels/refs: {', '.join(deps) if deps else 'none yet'}",
            "verify no theorem statement or assumption change is incorporated without author approval",
        ]
    if item.get("kind") == "experiment":
        lane = item.get("experiment_lane") or {}
        return [
            f"expected artifacts: {', '.join(lane.get('expected_artifacts', [])) or 'TBD'}",
            f"result status: {lane.get('result_status', 'not_recorded')}",
            "map recorded artifacts back to response letter and figure/table placeholders",
        ]
    return ["no proof or experiment dependency lane required"]

def blocking_questions_for_item(item: dict, analysis: dict | None = None) -> list[str]:
    if analysis and item.get("kind") in {"proof", "experiment"}:
        return list(analysis.get("author_verification", []))
    if item.get("kind") == "proof":
        return [
            "Which exact theorem/lemma/proof obligation should change?",
            "Has the author verified every new nontrivial proof step?",
        ]
    if item.get("kind") == "experiment":
        lane = item.get("experiment_lane") or {}
        if lane.get("result_status") == "recorded":
            return []
        return [
            "Which command, seed, and parameter set should be treated as authoritative?",
            "Where is the recorded result artifact that supports the manuscript change?",
        ]
    return []

def completion_criteria_for_item(item: dict, analysis: dict | None = None) -> list[str]:
    if item.get("kind") == "proof":
        criteria = [
            "author approval recorded for proof lane",
            "candidate text contains no unverified mathematical claim",
            "response letter cites the revised proof location",
        ]
        if analysis and analysis.get("response_strategy"):
            criteria.append(f"response follows strategy: {analysis['response_strategy']}")
        return criteria
    if item.get("kind") == "experiment":
        criteria = [
            "experiment result provenance recorded",
            "figure/table or text backfill is linked to the recorded artifact",
            "response letter states only observed results",
        ]
        if analysis and analysis.get("response_strategy"):
            criteria.append(f"response follows strategy: {analysis['response_strategy']}")
        return criteria
    return [
        "candidate edit reviewed and approved",
        "approved edit incorporated or explicitly rejected",
        "response letter points to the revised manuscript location",
    ]

def build_revision_plan(item: dict, candidates: list[dict], analysis: dict | None = None) -> dict[str, object]:
    plan = {
        "item_id": item["id"],
        "kind": item.get("kind"),
        "planning_status": "planned",
        "review_analysis_id": analysis.get("item_id", "") if analysis else "",
        "reviewer_intent_decomposition": reviewer_intent_decomposition(item, analysis),
        "required_evidence": required_evidence_for_item(item, analysis),
        "manuscript_edit_plan": manuscript_edit_plan_for_item(item, candidates, analysis),
        "dependency_plan": dependency_plan_for_item(item),
        "blocking_questions": blocking_questions_for_item(item, analysis),
        "completion_criteria": completion_criteria_for_item(item, analysis),
        "updated_at": now_iso(),
    }
    return plan

def render_item_plan(plan: dict[str, object]) -> str:
    lines = [f"# Item Plan {plan['item_id']}", "", f"- Kind: {plan.get('kind')}", f"- Status: {plan.get('planning_status')}", ""]
    sections = [
        ("Reviewer Intent Decomposition", "reviewer_intent_decomposition"),
        ("Required Evidence", "required_evidence"),
        ("Manuscript Edit Plan", "manuscript_edit_plan"),
        ("Proof/Experiment Dependency Plan", "dependency_plan"),
        ("Blocking Questions", "blocking_questions"),
        ("Completion Criteria", "completion_criteria"),
    ]
    for title, key in sections:
        values = plan.get(key) or []
        lines.extend([f"## {title}", ""])
        lines.extend(f"- {value}" for value in values) if values else lines.append("- None.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

def render_item_plans(plans: dict[str, dict]) -> str:
    if not plans:
        return "# Item Plans\n\nNo item plans generated yet.\n"
    return "# Item Plans\n\n" + "\n".join(render_item_plan(plans[key]).strip() for key in sorted(plans)) + "\n"

def plan_item(base: Path, item_id: str, force: bool = False) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    if item.get("planning_status") in {"closed", "incorporated"} and item.get("revision_plan") and not force:
        return item["revision_plan"]
    candidates = load_candidates(config)
    analysis = load_review_analyses(config).get(item_id) or analyze_review_item(base, item_id)
    plan = build_revision_plan(item, candidates, analysis)
    item["planning_status"] = "planned"
    item["revision_plan"] = plan
    item["required_evidence"] = plan["required_evidence"]
    item["blocking_questions"] = plan["blocking_questions"]
    item["completion_criteria"] = plan["completion_criteria"]
    write_items(config, items)
    plans = load_item_plans(config)
    plans[item_id] = plan
    write_item_plans(config, plans)
    append_decision_log(config, f"Item plan generated for {item_id}", [f"- Kind: {item.get('kind')}", f"- Blocking questions: {len(plan['blocking_questions'])}"])
    return plan

def plan_all_items(base: Path, force: bool = False) -> list[dict[str, object]]:
    config = load_config(base)
    items = load_items(config)
    return [plan_item(base, item["id"], force=force) for item in items]

def close_item(base: Path, item_id: str) -> dict:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    candidates = [candidate for candidate in load_candidates(config) if candidate.get("item_id") == item_id]
    has_unapplied_candidate = any(candidate.get("status") in {"proposed", "edited", "approved", "blocked"} for candidate in candidates)
    if item.get("planning_status") != "incorporated" and (item.get("blocking_questions") or has_unapplied_candidate):
        raise ValueError(f"item {item_id} is not ready to close")
    item["planning_status"] = "closed"
    write_items(config, items)
    append_decision_log(config, f"Item closed {item_id}", [f"- Previous status: {item.get('status', 'unknown')}"])
    return item

def reopen_item(base: Path, item_id: str) -> dict:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    item["planning_status"] = "planned"
    write_items(config, items)
    append_decision_log(config, f"Item reopened {item_id}", ["- New planning status: planned"])
    return item

__all__ = [
    "close_item",
    "plan_all_items",
    "plan_item",
    "reasoning_for_item",
    "render_item_plan",
    "reopen_item",
]
