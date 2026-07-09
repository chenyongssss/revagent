"""Structured reviewer-intent analysis artifacts."""

from __future__ import annotations

from pathlib import Path

from ._models import Config
from ._utils import append_decision_log, find_item, first_sentence, load_config, load_items, now_iso, read_json, write_items, write_json, write_text
from .latex import update_locations


def review_analyses_path(config: Config) -> Path:
    return config.workspace / "review_analyses.json"


def load_review_analyses(config: Config) -> dict[str, dict]:
    return read_json(review_analyses_path(config), {})


def write_review_analyses(config: Config, analyses: dict[str, dict]) -> None:
    write_json(review_analyses_path(config), analyses)
    write_text(config.workspace / "review_analyses.md", render_review_analyses(analyses))


def location_text(item: dict) -> str:
    loc = (item.get("tex_locations") or [{}])[0]
    file = loc.get("file") or "unknown file"
    line = loc.get("line") or "unknown line"
    context = " ".join(str(part) for part in (loc.get("context_type", ""), loc.get("context_title", "")) if part).strip()
    return f"{file}:{line}" + (f" ({context})" if context else "")


def claim_targets_for(item: dict) -> list[str]:
    kind = item.get("kind", "manuscript")
    loc = (item.get("tex_locations") or [{}])[0]
    context = str(loc.get("context_title") or loc.get("context_type") or "").strip()
    lane = item.get("proof_lane") or item.get("experiment_lane") or {}
    targets = []
    if kind == "proof":
        targets.append(str(lane.get("nearest_claim") or lane.get("affected_claim") or context or "nearest theorem/proof block"))
        targets.append("assumptions, dependencies, and proof obligations linked to the reviewer concern")
    elif kind == "experiment":
        targets.append(str(context or "nearest figure/table/numerical experiment block"))
        targets.append("command, seed, artifacts, and manuscript backfill supporting the requested empirical claim")
    else:
        targets.append(str(context or "nearest manuscript passage"))
        targets.append("response-letter pointer and conservative wording change")
    return [target for target in targets if target]


def evidence_needs_for(item: dict) -> list[str]:
    kind = item.get("kind", "manuscript")
    lane = item.get("proof_lane") or item.get("experiment_lane") or {}
    if kind == "proof":
        return [
            "author-verified proof obligation closure before any proof candidate approval",
            "checked theorem/lemma assumptions and dependency labels",
            f"revised proof location: {location_text(item)}",
        ]
    if kind == "experiment":
        return [
            f"reproducible command template: {lane.get('command_template') or lane.get('command') or 'TBD'}",
            f"seed and parameters: {lane.get('seed') or 'TBD'}",
            "recorded artifact hash for the recorded result and explicit manuscript backfill target",
        ]
    return [
        f"manuscript location: {location_text(item)}",
        "author-reviewed wording that directly addresses the reviewer request",
        "response-letter citation to the revised passage",
    ]


def risk_notes_for(item: dict) -> list[str]:
    kind = item.get("kind", "manuscript")
    if kind == "proof":
        return ["high risk: proof text must not claim correctness before author verification"]
    if kind == "experiment":
        return ["medium risk: numerical conclusions must not be stated before result provenance is recorded"]
    return ["medium risk: wording should remain conservative and location-specific"]


def author_verification_for(item: dict) -> list[str]:
    kind = item.get("kind", "manuscript")
    if kind == "proof":
        return [
            "Author must confirm the exact theorem/lemma/proof block that changes.",
            "Author must verify every nontrivial mathematical step introduced by the revision.",
        ]
    if kind == "experiment":
        return [
            "Author must confirm the authoritative command, seed, and parameter set.",
            "Author must confirm the recorded artifact supports the response and manuscript text.",
        ]
    return ["Review final wording before approving any manuscript candidate."]


def response_strategy_for(item: dict) -> str:
    kind = item.get("kind", "manuscript")
    if kind == "proof":
        return "Acknowledge the concern, identify the affected claim, and state only author-verified proof changes."
    if kind == "experiment":
        return "Acknowledge the requested evidence, cite reproducible artifacts, and report only recorded results."
    return "Acknowledge the clarification request and point to the revised manuscript location."


def manuscript_action_for(item: dict) -> str:
    kind = item.get("kind", "manuscript")
    if kind == "proof":
        return f"Prepare author-verified proof text near {location_text(item)} after proof obligations are closed."
    if kind == "experiment":
        return f"Backfill recorded numerical evidence near {location_text(item)} after artifact provenance is recorded."
    return f"Prepare conservative clarification text near {location_text(item)}."


def build_review_analysis(item: dict) -> dict[str, object]:
    loc = (item.get("tex_locations") or [{}])[0]
    confidence = "medium" if loc.get("file") and loc.get("line") else "low"
    requested_change = {
        "proof": "verify and clarify the mathematical claim or proof step",
        "experiment": "provide reproducible empirical evidence before stating the result",
        "manuscript": "clarify the manuscript wording and response-letter location",
    }.get(str(item.get("kind", "manuscript")), "clarify the revision response")
    return {
        "version": 1,
        "item_id": item["id"],
        "kind": item.get("kind", "manuscript"),
        "intent_summary": first_sentence(str(item.get("comment", ""))),
        "requested_change": requested_change,
        "claim_targets": claim_targets_for(item),
        "evidence_needs": evidence_needs_for(item),
        "risk_notes": risk_notes_for(item),
        "author_verification": author_verification_for(item),
        "response_strategy": response_strategy_for(item),
        "manuscript_action": manuscript_action_for(item),
        "confidence": confidence,
        "location": location_text(item),
        "updated_at": now_iso(),
    }


def analyze_review_item(base: Path, item_id: str, force: bool = False) -> dict[str, object]:
    config = load_config(base)
    analyses = load_review_analyses(config)
    if item_id in analyses and not force:
        return analyses[item_id]
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    if not item.get("tex_locations"):
        update_locations(config, items)
        write_items(config, items)
        item = find_item(items, item_id) or item
    analysis = build_review_analysis(item)
    analyses[item_id] = analysis
    write_review_analyses(config, analyses)
    append_decision_log(config, f"Review analysis generated for {item_id}", [f"- Kind: {analysis.get('kind')}", f"- Confidence: {analysis.get('confidence')}"])
    return analysis


def analyze_all_review_items(base: Path, force: bool = False) -> dict[str, dict]:
    config = load_config(base)
    for item in load_items(config):
        analyze_review_item(base, str(item["id"]), force=force)
    return load_review_analyses(config)


def render_review_analyses(analyses: dict[str, dict], item_id: str | None = None) -> str:
    keys = [item_id] if item_id else sorted(analyses)
    lines = ["# Review Analyses", ""]
    if not analyses:
        lines.append("No review analyses generated yet.")
        return "\n".join(lines) + "\n"
    for key in keys:
        if key not in analyses:
            raise ValueError(f"unknown review analysis {key}")
        analysis = analyses[key]
        lines.extend(
            [
                f"## {key}",
                "",
                f"- Kind: {analysis.get('kind', '')}",
                f"- Confidence: {analysis.get('confidence', '')}",
                f"- Intent: {analysis.get('intent_summary', '')}",
                f"- Requested change: {analysis.get('requested_change', '')}",
                f"- Location: {analysis.get('location', '')}",
                f"- Response strategy: {analysis.get('response_strategy', '')}",
                f"- Manuscript action: {analysis.get('manuscript_action', '')}",
                "",
                "### Claim Targets",
                "",
            ]
        )
        lines.extend(f"- {target}" for target in analysis.get("claim_targets", []) or ["None."])
        lines.extend(["", "### Evidence Needs", ""])
        lines.extend(f"- {need}" for need in analysis.get("evidence_needs", []) or ["None."])
        lines.extend(["", "### Author Verification", ""])
        lines.extend(f"- {need}" for need in analysis.get("author_verification", []) or ["None."])
        lines.extend(["", "### Risk Notes", ""])
        lines.extend(f"- {note}" for note in analysis.get("risk_notes", []) or ["None."])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def review_analysis_for_item(base: Path, item_id: str | None = None) -> str:
    config = load_config(base)
    return render_review_analyses(load_review_analyses(config), item_id=item_id)


__all__ = [
    "analyze_all_review_items",
    "analyze_review_item",
    "load_review_analyses",
    "render_review_analyses",
    "review_analysis_for_item",
    "write_review_analyses",
]
