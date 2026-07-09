"""Response-letter and manuscript-patch rendering public API."""

from __future__ import annotations

import difflib
from pathlib import Path

from ._utils import append_decision_log, find_item, first_sentence, load_config, read_json, read_text, write_json, write_text
from .candidates import load_candidates, propose_candidates, render_apply_diff, write_candidates
from .latex import update_locations
from .profiles import load_profile

def response_for(item: dict) -> str:
    if item["kind"] == "proof":
        action = "We will revise the relevant theoretical discussion and proof after author verification of the nontrivial mathematical step."
    elif item["kind"] == "experiment":
        action = "We will add or revise the numerical evidence after running the proposed experiment and confirming the observed result."
    else:
        action = "We will revise the manuscript text to address this point and cite the updated location in the final response."
    loc = item["tex_locations"][0] if item["tex_locations"] else None
    where = f" The current candidate location is `{loc['file']}:{loc['line']}`." if loc else " The exact manuscript location still needs author confirmation."
    return f"**Response.** Thank you for this comment. {action}{where}"

def load_eligible_llm_drafts(config: Config) -> dict[str, dict]:
    drafts = read_json(config.workspace / "llm_drafts.json", {})
    return {
        item_id: draft
        for item_id, draft in drafts.items()
        if draft.get("review_status") in {"accepted", "edited"} and draft.get("quality_status") == "passed"
    }

def draft_response_for(item: dict, eligible_drafts: dict[str, dict]) -> str:
    draft = eligible_drafts.get(item.get("id", ""))
    if draft:
        return str(draft.get("response_draft", ""))
    return response_for(item)

def render_response_letter(config: Config, items: list[dict], base: Path) -> str:
    profile = load_profile(config.journal, base)
    eligible_drafts = load_eligible_llm_drafts(config)
    lines = [
        f"# {profile['response_heading']}",
        "",
        f"Journal profile: {profile['display_name']}",
        f"Response tone target: {profile['tone']}",
        "",
        "We thank the editor and reviewers for their careful reading and constructive comments. Below we respond point by point.",
        "",
    ]
    for item in items:
        lines.extend(
            [
                f"## {item['id']}",
                "",
                f"**Reviewer comment.** {item['comment']}",
                "",
                draft_response_for(item, eligible_drafts),
                "",
            ]
        )
    return "\n".join(lines)

def insertion_block(items: list[dict]) -> list[str]:
    lines = ["", "% REVAGENT REVISION NOTES BEGIN"]
    for item in items:
        lines.append(f"% {item['id']} response note ({item['kind']}, {item['risk']} risk): {first_sentence(item['comment'])}")
        if item["kind"] == "proof":
            lines.extend(
                [
                    "% Proof TODO: identify affected theorem/lemma and add verified proof text only after author approval.",
                    "% Proof TODO: record changed assumptions and dependency labels in proof_audit.md.",
                ]
            )
        elif item["kind"] == "experiment":
            lines.extend(
                [
                    "% Experiment placeholder: insert observed result, command, seed, and figure/table update after execution.",
                    "% Experiment placeholder: do not claim improvement until result files are confirmed.",
                ]
            )
        else:
            lines.append("% Clarification placeholder: insert concise manuscript wording and exact response-letter location.")
    lines.append("% REVAGENT REVISION NOTES END")
    return lines

def render_patch_notes(config: Config, items: list[dict]) -> str:
    header = [
        "# This is a reviewable patch-note diff, not an auto-applied manuscript edit.",
        "# It inserts conservative notes/placeholders only; proof and experiment claims require author confirmation.",
    ]
    diff = render_apply_diff(config.workspace.parent, approved_only=False)
    if diff.startswith("# No candidate"):
        main = config.tex_root / config.main_tex
        original = read_text(main).splitlines() if main.exists() else [f"% Missing main TeX file: {config.main_tex}"]
        revised = list(original)
        insert_at = next((i + 1 for i, line in enumerate(revised) if "\\begin{document}" in line), len(revised))
        revised[insert_at:insert_at] = insertion_block(items)
        diff_lines = difflib.unified_diff(original, revised, fromfile=f"a/{config.main_tex}", tofile=f"b/{config.main_tex}", lineterm="")
        diff = "\n".join(diff_lines) + "\n"
    return "\n".join(header) + "\n" + diff

def create_draft(base: Path) -> None:
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    if any(not item.get("tex_locations") for item in items):
        update_locations(config, items)
    for item in items:
        item["response_draft"] = response_for(item)
    write_json(config.workspace / "review_items.json", items)
    propose_candidates(base)
    write_text(config.workspace / "response_letter.md", render_response_letter(config, items, base))
    write_text(config.workspace / "manuscript.patch", render_patch_notes(config, items))

def incorporate_drafts(base: Path) -> dict[str, object]:
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    if any(not item.get("tex_locations") for item in items):
        update_locations(config, items)
    propose_candidates(base)
    eligible_drafts = load_eligible_llm_drafts(config)
    all_drafts = read_json(config.workspace / "llm_drafts.json", {})
    warnings = []
    for item_id, draft in all_drafts.items():
        if draft.get("review_status") in {"accepted", "edited"} and draft.get("quality_status") != "passed":
            warnings.append(f"{item_id} has review_status={draft.get('review_status')} but quality_status={draft.get('quality_status', 'unchecked')}")

    for item in items:
        draft = eligible_drafts.get(item["id"])
        item["response_draft"] = str(draft.get("response_draft", "")) if draft else response_for(item)
    write_json(config.workspace / "review_items.json", items)

    candidates = load_candidates(config)
    for candidate in candidates:
        draft = eligible_drafts.get(candidate.get("item_id", ""))
        if not draft or candidate.get("status") not in {"proposed", "blocked"}:
            continue
        item = find_item(items, candidate.get("item_id", ""))
        candidate["content"] = str(draft.get("candidate_text", ""))
        if item and item.get("kind") == "proof":
            candidate["status"] = "blocked"
            candidate["requires_author_text"] = True
            candidate["blocked_reason"] = "author-verified proof text required before approval"
        elif item and item.get("kind") == "experiment" and (item.get("experiment_lane") or {}).get("result_status") != "recorded":
            candidate["status"] = "blocked"
            candidate["requires_author_text"] = True
            candidate["blocked_reason"] = "recorded experiment provenance required before approval"
    write_candidates(config, candidates)

    write_text(config.workspace / "response_letter.md", render_response_letter(config, items, base))
    write_text(config.workspace / "manuscript.patch", render_patch_notes(config, items))
    append_decision_log(config, "LLM drafts incorporated into generated artifacts", [f"- Eligible drafts: {len(eligible_drafts)}", f"- Warnings: {len(warnings)}"])
    return {"eligible": sorted(eligible_drafts), "warnings": warnings}

__all__ = ["create_draft", "incorporate_drafts", "render_response_letter"]
