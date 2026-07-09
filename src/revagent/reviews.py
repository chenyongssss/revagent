"""Reviewer comment parsing, classification, and item workflow public API."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ._utils import first_sentence, load_config, load_items, now_iso, read_json, read_text, write_items, write_json, write_text
from .profiles import load_profile

def split_comments(text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        is_heading = stripped.startswith("#")
        is_list_item = bool(re.match(r"^([-*]|\d+[.)])\s+", stripped))
        is_reviewer_marker = bool(re.match(r"^(reviewer|referee|editor)\b", stripped, re.I))
        if (is_heading or is_list_item or is_reviewer_marker) and current:
            chunks.append("\n".join(current).strip())
            current = []
        if stripped:
            current.append(stripped)
    if current:
        chunks.append("\n".join(current).strip())
    return [
        chunk
        for chunk in chunks
        if len(chunk) > 8 and not re.match(r"^#+\s*(reviewer|referee|editor)\b", chunk, re.I)
    ]

def classify_item(text: str) -> str:
    lowered = text.lower()
    proof_terms = [
        "proof",
        "prove",
        "theorem",
        "lemma",
        "proposition",
        "corollary",
        "assumption",
        "hypothesis",
        "convergence",
        "stability",
        "error estimate",
    ]
    experiment_terms = [
        "experiment",
        "numerical",
        "simulation",
        "benchmark",
        "table",
        "figure",
        "plot",
        "ablation",
        "parameter",
        "dataset",
        "runtime",
        "seed",
    ]
    if any(term in lowered for term in proof_terms):
        return "proof"
    if any(term in lowered for term in experiment_terms):
        return "experiment"
    return "manuscript"

def risk_for(kind: str, text: str) -> str:
    lowered = text.lower()
    if kind == "proof":
        return "high"
    if kind == "experiment":
        return "medium"
    if any(term in lowered for term in ["major", "incorrect", "invalid", "unclear contribution"]):
        return "high"
    return "medium"

def ingest_comments(base: Path, comments_path: str) -> int:
    config = load_config(base)
    raw = read_text((base / comments_path).resolve())
    chunks = split_comments(raw)
    items = []
    for index, chunk in enumerate(chunks, start=1):
        kind = classify_item(chunk)
        items.append(
            {
                "id": f"R{index:03d}",
                "kind": kind,
                "lane": kind,
                "severity": risk_for(kind, chunk),
                "requires_author_input": kind in {"proof", "experiment"},
                "evidence_required": kind in {"proof", "experiment"},
                "source": comments_path,
                "reviewer": infer_reviewer(chunk, index),
                "status": "triaged",
                "planning_status": "triaged",
                "risk": risk_for(kind, chunk),
                "comment": chunk,
                "tex_locations": [],
                "response_draft": "",
                "revision_plan": {},
                "completion_criteria": [],
                "blocking_questions": [],
                "required_evidence": [],
                "proof_lane": proof_lane_template(chunk) if kind == "proof" else None,
                "experiment_lane": experiment_lane_template(chunk) if kind == "experiment" else None,
                "author_confirmation_required": kind in {"proof", "experiment"},
                "created_at": now_iso(),
            }
        )
    write_json(config.workspace / "review_items.json", items)
    return len(items)

def infer_reviewer(chunk: str, index: int) -> str:
    match = re.search(r"\b(reviewer|referee|editor)\s*([0-9A-Za-z-]*)", chunk, re.I)
    if match:
        suffix = match.group(2).strip()
        return f"{match.group(1).title()} {suffix}".strip()
    return f"Reviewer {index}"

def proof_lane_template(comment: str) -> dict[str, object]:
    return {
        "affected_claim": "",
        "assumptions": [],
        "dependencies": [],
        "nearest_claim": None,
        "changed_labels": [],
        "changed_refs": [],
        "statement_snapshot": "",
        "proof_snapshot": "",
        "assumption_refs": [],
        "dependency_refs": [],
        "proof_obligations": [],
        "workflow_status": "not_planned",
        "proof_workflow_id": "",
        "proposed_proof_change": "Draft only after author confirms the nontrivial mathematical step.",
        "unverified_steps": [first_sentence(comment)],
        "author_approval": False,
        "approval_status": "required",
    }

def experiment_lane_template(comment: str) -> dict[str, object]:
    return {
        "command": "",
        "cwd": "",
        "parameters": {},
        "seed": "",
        "expected_artifacts": [],
        "artifact_hashes": {},
        "backfill_targets": [],
        "manifest_id": "",
        "command_template": "",
        "contract_status": "not_planned",
        "observed_artifacts": [],
        "recorded_results": [],
        "result_status": "not_recorded",
        "paper_locations": [],
        "result_backfill_fields": ["observed_result", "figure_or_table_update", "response_text"],
        "reviewer_request": first_sentence(comment),
    }

def bullet_lines(items: Iterable[dict]) -> str:
    lines = []
    for item in items:
        loc = item["tex_locations"][0] if item["tex_locations"] else None
        where = f"{loc['file']}:{loc['line']} score={loc.get('score', '?')}" if loc else "location not found"
        lines.append(f"- `{item['id']}` [{item['kind']}, {item['risk']} risk] {where}: {first_sentence(item['comment'])}")
    return "\n".join(lines) if lines else "- None.\n"

def render_plan(config: Config, items: list[dict], index: dict[str, object], base: Path) -> str:
    profile = load_profile(config.journal, base)
    return "\n".join(
        [
            "# Revision Plan",
            "",
            f"- Journal profile: {profile['display_name']}",
            f"- Main TeX file: `{config.main_tex}`",
            f"- Review items: {len(items)}",
            f"- Proof lane items: {sum(1 for item in items if item['kind'] == 'proof')}",
            f"- Experiment lane items: {sum(1 for item in items if item['kind'] == 'experiment')}",
            "",
            "## Items",
            "",
            bullet_lines(items),
            "",
            "## Publisher Checks",
            "",
            "\n".join(f"- {check}" for check in profile.get("checks", [])) or "- No publisher checks configured.",
            "",
            "## Manuscript Index",
            "",
            f"- Sections found: {len(index['sections'])}",
            f"- Labels found: {len(index['labels'])}",
            f"- References found: {len(index['refs'])}",
            f"- Unresolved references: {len(index['unresolved_refs'])}",
            f"- Reachable TeX files: {len(index.get('reachable_files', []))}",
            f"- Custom theorem-like environments found: {len(index.get('custom_environments', []))}",
            f"- Theorem/proof/algorithm/figure/table environments found: {len(index['environments'])}",
            "",
        ]
    )

def render_proof_audit(items: list[dict], index: dict[str, object]) -> str:
    proof_items = [item for item in items if item["kind"] == "proof"]
    lines = ["# Proof Audit", ""]
    if not proof_items:
        lines.append("No proof-related review items were detected.")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "This file is a proof-drafting and audit surface. It does not certify correctness.",
            "All proof text changes are high-risk and require author approval before manuscript edits.",
            "",
            "## Dependency Map",
            "",
        ]
    )
    deps = index.get("dependency_map", [])
    if deps:
        for dep in deps[:40]:
            labels = ", ".join(dep.get("labels", [])) or "no labels"
            refs = ", ".join(dep.get("refs", [])) or "no refs"
            lines.append(f"- `{dep['environment']}` at `{dep['file']}:{dep['line']}`; labels: {labels}; refs: {refs}")
    else:
        lines.append("- No theorem/proof environments found by the lightweight scanner.")
    lines.extend(["", "## Proof Items", ""])
    for item in proof_items:
        lane = item.get("proof_lane") or proof_lane_template(item["comment"])
        lines.extend(
            [
                f"### {item['id']}",
                "",
                f"Reviewer concern: {first_sentence(item['comment'])}",
                "",
                "Structured audit fields:",
                f"- Affected claim: {lane.get('affected_claim') or 'TBD'}",
                f"- Assumptions: {', '.join(lane.get('assumptions', [])) or 'TBD'}",
                f"- Dependencies: {', '.join(lane.get('dependencies', [])) or 'TBD'}",
                f"- Proposed proof change: {lane.get('proposed_proof_change')}",
                f"- Unverified steps: {', '.join(lane.get('unverified_steps', [])) or 'TBD'}",
                f"- Author approval: {lane.get('author_approval')}",
                "",
                "Audit checklist:",
                "- [ ] Dependencies and labels are correct.",
                "- [ ] No circular dependence is introduced.",
                "- [ ] Boundary cases and regularity assumptions are stated.",
                "- [ ] Author has verified the nontrivial mathematical step.",
                "",
            ]
        )
    return "\n".join(lines)

def render_open_issues(items: list[dict]) -> str:
    lines = ["# Open Issues", ""]
    high = [item for item in items if item["risk"] == "high" or item["author_confirmation_required"]]
    if not high:
        lines.append("No high-risk or author-confirmation items are currently open.")
        return "\n".join(lines) + "\n"
    for item in high:
        lines.append(f"- `{item['id']}` requires author confirmation: {first_sentence(item['comment'])}")
    return "\n".join(lines) + "\n"

def default_item_fields(item: dict, index: int, source: str = "") -> dict[str, object]:
    kind = item.get("kind") or classify_item(item.get("comment", ""))
    risk = item.get("risk") or risk_for(kind, item.get("comment", ""))
    return {
        "lane": kind,
        "severity": risk,
        "requires_author_input": kind in {"proof", "experiment"},
        "evidence_required": kind in {"proof", "experiment"},
        "source": source,
        "reviewer": item.get("reviewer") or f"Reviewer {index}",
        "planning_status": item.get("planning_status") or item.get("status") or "triaged",
        "revision_plan": item.get("revision_plan") or {},
        "completion_criteria": item.get("completion_criteria") or [],
        "blocking_questions": item.get("blocking_questions") or [],
        "required_evidence": item.get("required_evidence") or [],
    }

def create_plan(base: Path) -> None:
    from .experiments import render_experiment_plan
    from .latex import latex_index, update_locations

    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    update_locations(config, items)
    index = latex_index(config.tex_root, config.main_tex)
    write_json(config.workspace / "review_items.json", items)
    write_json(config.workspace / "latex_index.json", index)
    write_text(config.workspace / "revision_plan.md", render_plan(config, items, index, base))
    write_text(config.workspace / "proof_audit.md", render_proof_audit(items, index))
    write_text(config.workspace / "experiment_plan.md", render_experiment_plan(items, config.tex_root))
    write_text(config.workspace / "open_issues.md", render_open_issues(items))

__all__ = [
    "classify_item",
    "create_plan",
    "first_sentence",
    "ingest_comments",
    "risk_for",
    "split_comments",
]
