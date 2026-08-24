"""Proof workflow, obligation, and approval-gate public API."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Iterable

from ._models import Config
from ._utils import append_decision_log, find_item, first_sentence, load_config, load_items, now_iso, read_json, write_items, write_json, write_text
from .latex import latex_index, update_locations
from .reviews import proof_lane_template

def proof_audit_for_item(base: Path, item_id: str | None = None) -> str:
    config = load_config(base)
    items = load_items(config)
    index = latex_index(config.tex_root, config.main_tex)
    proof_items = [item for item in items if item.get("kind") == "proof"]
    if item_id:
        proof_items = [item for item in proof_items if item.get("id") == item_id]
        if not proof_items:
            raise ValueError(f"unknown proof item {item_id}")
    lines = ["# Proof Audit Detail", ""]
    for item in proof_items:
        loc = (item.get("tex_locations") or [{}])[0]
        deps = [
            dep
            for dep in index.get("dependency_map", [])
            if dep.get("file") == loc.get("file") and abs(int(dep.get("line", 0)) - int(loc.get("line", 0) or 0)) <= 20
        ]
        lane = item.get("proof_lane") or proof_lane_template(item["comment"])
        if deps and not lane.get("nearest_claim"):
            lane["nearest_claim"] = deps[0].get("nearest_claim")
            lane["dependencies"] = deps[0].get("refs", [])
        lines.extend(
            [
                f"## {item['id']}",
                "",
                f"- Reviewer concern: {first_sentence(item['comment'])}",
                f"- Location: {loc.get('file', 'unknown')}:{loc.get('line', 'unknown')} score={loc.get('score', 0)}",
                f"- Affected claim: {lane.get('affected_claim') or 'TBD'}",
                f"- Assumptions: {', '.join(lane.get('assumptions', [])) or 'TBD'}",
                f"- Dependencies: {', '.join(lane.get('dependencies', [])) or 'TBD'}",
                f"- Nearest claim: {lane.get('nearest_claim') or 'TBD'}",
                f"- Unverified steps: {', '.join(lane.get('unverified_steps', [])) or 'TBD'}",
                f"- Author approval: {lane.get('approval_status', 'required')}",
                "",
            ]
        )
    append_decision_log(config, "Proof audit generated", [f"- Items: {', '.join(item['id'] for item in proof_items) or 'none'}"])
    return "\n".join(lines)

def load_proof_workflows(config: Config) -> dict[str, dict]:
    return read_json(config.workspace / "proof_workflows.json", {})

def write_proof_workflows(config: Config, workflows: dict[str, dict]) -> None:
    write_json(config.workspace / "proof_workflows.json", workflows)
    write_text(config.workspace / "proof_workflows.md", render_proof_workflows(workflows))

def flat_refs(ref_groups: Iterable[object]) -> list[str]:
    refs: list[str] = []
    for group in ref_groups:
        if isinstance(group, str):
            refs.extend(part.strip() for part in group.split(",") if part.strip())
        elif isinstance(group, list):
            refs.extend(str(part).strip() for part in group if str(part).strip())
    return refs

def proof_context_for_item(item: dict, index: dict[str, object]) -> dict[str, object]:
    loc = (item.get("tex_locations") or [{}])[0]
    loc_file = loc.get("file")
    loc_line = int(loc.get("line", 0) or 0)
    envs = [env for env in index.get("environments", []) if env.get("file") == loc_file]
    proof_envs = [env for env in envs if env.get("environment") == "proof"]
    claim_envs = [env for env in envs if env.get("environment") in {"theorem", "lemma", "proposition", "corollary", "assumption"}]
    proof_env = next(
        (
            env
            for env in proof_envs
            if int(env.get("line", 0)) <= loc_line <= int(env.get("end_line", 0))
        ),
        None,
    )
    if proof_env is None and proof_envs:
        proof_env = min(proof_envs, key=lambda env: abs(int(env.get("line", 0)) - loc_line))
    claim_env = None
    if proof_env:
        previous_claims = [env for env in claim_envs if int(env.get("line", 0)) <= int(proof_env.get("line", 0))]
        if previous_claims:
            claim_env = max(previous_claims, key=lambda env: int(env.get("line", 0)))
    if claim_env is None and claim_envs:
        claim_env = min(claim_envs, key=lambda env: abs(int(env.get("line", 0)) - loc_line))
    refs = flat_refs((proof_env or {}).get("refs", [])) + flat_refs((claim_env or {}).get("refs", []))
    supporting_envs = [env for env in envs if env.get("environment") in {"assumption", "definition"}]
    return {
        "claim": claim_env or {},
        "proof": proof_env or {},
        "dependency_refs": sorted(set(refs)),
        "assumption_refs": sorted(ref for ref in set(refs) if ref.startswith("ass:") or "assumption" in ref.lower()),
        "assumption_definitions": [
            {
                "kind": env.get("environment"),
                "labels": env.get("labels", []),
                "source_span": env.get("source_span", {}),
                "content_sha256": env.get("content_sha256", ""),
                "excerpt": env.get("excerpt", ""),
            }
            for env in supporting_envs
        ],
    }

def build_proof_workflow(item: dict, index: dict[str, object]) -> dict[str, object]:
    context = proof_context_for_item(item, index)
    claim = context["claim"]
    proof = context["proof"]
    lane = item.get("proof_lane") or proof_lane_template(item.get("comment", ""))
    obligations = lane.get("proof_obligations") or [
        {
            "id": "PO001",
            "description": "Author must verify the affected claim, assumptions, and every nontrivial proof step.",
            "status": "open",
            "created_at": now_iso(),
            "closed_at": "",
            "closure_note": "",
        }
    ]
    return {
        "id": item["id"],
        "item_id": item["id"],
        "status": "planned",
        "affected_claim": claim.get("labels", []) or lane.get("affected_claim") or [],
        "statement_snapshot": claim.get("excerpt", "") or lane.get("statement_snapshot", ""),
        "proof_snapshot": proof.get("excerpt", "") or lane.get("proof_snapshot", ""),
        "claim_location": {"file": claim.get("file", ""), "line": claim.get("line", 0), "environment": claim.get("environment", "")},
        "proof_location": {"file": proof.get("file", ""), "line": proof.get("line", 0), "environment": proof.get("environment", "")},
        "statement_source_span": claim.get("source_span", {}),
        "proof_source_span": proof.get("source_span", {}),
        "statement_content_sha256": claim.get("content_sha256", ""),
        "proof_content_sha256": proof.get("content_sha256", ""),
        "assumption_refs": context["assumption_refs"],
        "assumption_definition_inventory": context["assumption_definitions"],
        "dependency_refs": context["dependency_refs"],
        "dependency_graph": [
            {"from": claim.get("labels", []), "to": ref, "source": "claim_or_proof_reference"}
            for ref in context["dependency_refs"]
        ],
        "revision_diff": {"status": "not_recorded", "before_content_sha256": proof.get("content_sha256", ""), "after_content_sha256": "", "locator": ""},
        "proof_obligations": obligations,
        "unverified_steps": lane.get("unverified_steps", []),
        "approval_status": lane.get("approval_status", "required"),
        "approval_note": "",
        "updated_at": now_iso(),
    }

def sync_proof_lane_from_workflow(item: dict, workflow: dict[str, object]) -> None:
    lane = item.get("proof_lane") or proof_lane_template(item.get("comment", ""))
    lane["proof_workflow_id"] = workflow["id"]
    lane["workflow_status"] = workflow["status"]
    lane["statement_snapshot"] = workflow.get("statement_snapshot", "")
    lane["proof_snapshot"] = workflow.get("proof_snapshot", "")
    lane["assumption_refs"] = workflow.get("assumption_refs", [])
    lane["dependency_refs"] = workflow.get("dependency_refs", [])
    lane["assumption_definition_inventory"] = workflow.get("assumption_definition_inventory", [])
    lane["revision_diff"] = workflow.get("revision_diff", {})
    lane["dependencies"] = workflow.get("dependency_refs", [])
    lane["proof_obligations"] = workflow.get("proof_obligations", [])
    lane["approval_status"] = workflow.get("approval_status", "required")
    lane["author_approval"] = workflow.get("approval_status") == "approved"
    item["proof_lane"] = lane

def render_proof_workflow(workflow: dict[str, object]) -> str:
    lines = [
        f"# Proof Workflow {workflow['item_id']}",
        "",
        f"- Status: {workflow.get('status')}",
        f"- Approval: {workflow.get('approval_status')}",
        f"- Claim: {json.dumps(workflow.get('claim_location', {}), ensure_ascii=False)}",
        f"- Proof: {json.dumps(workflow.get('proof_location', {}), ensure_ascii=False)}",
        f"- Dependency refs: {', '.join(workflow.get('dependency_refs', [])) or 'none'}",
        f"- Assumption refs: {', '.join(workflow.get('assumption_refs', [])) or 'none'}",
        f"- Statement source: {json.dumps(workflow.get('statement_source_span', {}), ensure_ascii=False)}",
        f"- Proof source: {json.dumps(workflow.get('proof_source_span', {}), ensure_ascii=False)}",
        f"- Revision diff: {json.dumps(workflow.get('revision_diff', {}), ensure_ascii=False)}",
        "",
        "## Statement Snapshot",
        "",
        workflow.get("statement_snapshot") or "TBD",
        "",
        "## Proof Snapshot",
        "",
        workflow.get("proof_snapshot") or "TBD",
        "",
        "## Proof Obligations",
        "",
    ]
    obligations = workflow.get("proof_obligations", [])
    lines.extend(f"- {ob['id']} [{ob['status']}] {ob['description']}" for ob in obligations) if obligations else lines.append("- None.")
    lines.extend(["", "## Assumptions and Definitions", ""])
    inventory = workflow.get("assumption_definition_inventory", [])
    lines.extend(f"- {entry.get('kind')} labels={', '.join(entry.get('labels', [])) or 'none'} span={json.dumps(entry.get('source_span', {}), ensure_ascii=False)}" for entry in inventory) if inventory else lines.append("- None located; expert must record any applicable assumptions or definitions.")
    if workflow.get("approval_note"):
        lines.extend(["", "## Approval Note", "", str(workflow["approval_note"])])
    return "\n".join(lines).rstrip() + "\n"

def render_proof_workflows(workflows: dict[str, dict]) -> str:
    if not workflows:
        return "# Proof Workflows\n\nNo proof workflows generated yet.\n"
    return "# Proof Workflows\n\n" + "\n".join(render_proof_workflow(workflows[key]).strip() for key in sorted(workflows)) + "\n"

def proof_plan_for_item(base: Path, item_id: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "proof":
        raise ValueError(f"unknown proof item {item_id}")
    if not item.get("tex_locations"):
        update_locations(config, items)
    index = latex_index(config.tex_root, config.main_tex)
    workflow = build_proof_workflow(item, index)
    sync_proof_lane_from_workflow(item, workflow)
    write_items(config, items)
    workflows = load_proof_workflows(config)
    workflows[item_id] = workflow
    write_proof_workflows(config, workflows)
    append_decision_log(config, f"Proof workflow planned for {item_id}", [f"- Obligations: {len(workflow['proof_obligations'])}"])
    return workflow

def proof_obligation(base: Path, item_id: str, description: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "proof":
        raise ValueError(f"unknown proof item {item_id}")
    workflows = load_proof_workflows(config)
    workflow = workflows.get(item_id) or proof_plan_for_item(base, item_id)
    obligations = workflow.setdefault("proof_obligations", [])
    obligation = {
        "id": f"PO{len(obligations) + 1:03d}",
        "description": description,
        "status": "open",
        "created_at": now_iso(),
        "closed_at": "",
        "closure_note": "",
    }
    obligations.append(obligation)
    workflow["status"] = "planned"
    workflow["updated_at"] = now_iso()
    workflows[item_id] = workflow
    sync_proof_lane_from_workflow(item, workflow)
    write_items(config, items)
    write_proof_workflows(config, workflows)
    append_decision_log(config, f"Proof obligation added for {item_id}", [f"- {obligation['id']}: {description}"])
    return obligation


def proof_record_revision_diff(base: Path, item_id: str, after_file: str) -> dict[str, object]:
    """Freeze an author-supplied post-revision snapshot; it is not a proof verdict."""
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "proof":
        raise ValueError(f"unknown proof item {item_id}")
    source = (base / after_file).resolve()
    if base.resolve() not in source.parents or not source.is_file():
        raise ValueError("proof revision snapshot must be an existing file inside the local project")
    raw = source.read_bytes()
    if not raw:
        raise ValueError("proof revision snapshot must not be empty")
    target_dir = config.workspace / "proof_diffs"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{item_id}-after.txt"
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    workflows = load_proof_workflows(config)
    workflow = workflows.get(item_id) or proof_plan_for_item(base, item_id)
    workflow["revision_diff"] = {
        "status": "recorded",
        "before_content_sha256": workflow.get("proof_content_sha256", ""),
        "after_content_sha256": digest,
        "locator": str(target.relative_to(config.workspace)),
        "recorded_at": now_iso(),
        "note": "Author/expert must assess the mathematical effect of this snapshot.",
    }
    workflow["updated_at"] = now_iso()
    workflows[item_id] = workflow
    sync_proof_lane_from_workflow(item, workflow)
    write_items(config, items)
    write_proof_workflows(config, workflows)
    append_decision_log(config, f"Proof revision snapshot recorded for {item_id}", [f"- SHA256: {digest}", "- No proof correctness conclusion was recorded."])
    return workflow["revision_diff"]

def proof_approve(base: Path, item_id: str, note: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "proof":
        raise ValueError(f"unknown proof item {item_id}")
    workflows = load_proof_workflows(config)
    workflow = workflows.get(item_id) or proof_plan_for_item(base, item_id)
    for obligation in workflow.get("proof_obligations", []):
        if obligation.get("status") == "open":
            obligation["status"] = "closed"
            obligation["closed_at"] = now_iso()
            obligation["closure_note"] = note
    workflow["status"] = "approved"
    workflow["approval_status"] = "approved"
    workflow["approval_note"] = note
    workflow["updated_at"] = now_iso()
    workflows[item_id] = workflow
    sync_proof_lane_from_workflow(item, workflow)
    if item.get("planning_status") not in {"incorporated", "closed"}:
        item["planning_status"] = "approved"
    write_items(config, items)
    write_proof_workflows(config, workflows)
    append_decision_log(config, f"Proof workflow approved for {item_id}", [f"- Note: {note}"])
    return workflow

__all__ = [
    "load_proof_workflows",
    "proof_audit_for_item",
    "proof_approve",
    "proof_obligation",
    "proof_record_revision_diff",
    "proof_plan_for_item",
    "render_proof_workflow",
    "render_proof_workflows",
    "write_proof_workflows",
]
