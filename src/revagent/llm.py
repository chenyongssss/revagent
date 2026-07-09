"""Offline LLM-draft layer for reviewer intent and response text."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib import request

from ._models import Config
from ._utils import append_decision_log, find_item, first_sentence, load_config, load_items, now_iso, read_json, read_text, write_items, write_json, write_text
from .candidates import load_candidates, propose_candidates, write_candidates
from .experiments import load_experiment_manifests
from .latex import update_locations
from .planning import load_item_plans
from .profiles import load_profile
from .proofs import load_proof_workflows
from .rendering import response_for
from .review_analysis import load_review_analyses


def llm_drafts_path(config: Config) -> Path:
    return config.workspace / "llm_drafts.json"


def load_llm_drafts(config: Config) -> dict[str, dict]:
    return read_json(llm_drafts_path(config), {})


def write_llm_drafts(config: Config, drafts: dict[str, dict]) -> None:
    write_json(llm_drafts_path(config), drafts)
    write_text(config.workspace / "llm_drafts.md", render_llm_drafts(drafts))


def ensure_llm_review_fields(draft: dict) -> dict:
    draft.setdefault("review_status", "drafted")
    draft.setdefault("review_note", "")
    draft.setdefault("reviewed_at", "")
    draft.setdefault("edited_at", "")
    draft.setdefault("quality_status", "unchecked")
    draft.setdefault("quality_issues", [])
    draft.setdefault("quality_checked_at", "")
    return draft


def nearby_excerpt(config: Config, location: dict | None, radius: int = 3) -> dict[str, object]:
    if not location:
        return {"file": "", "line": 0, "start_line": 0, "end_line": 0, "text": ""}
    target = config.tex_root / str(location.get("file", ""))
    line = int(location.get("line", 0) or 0)
    if not target.exists() or line <= 0:
        return {"file": str(location.get("file", "")), "line": line, "start_line": 0, "end_line": 0, "text": ""}
    lines = read_text(target).splitlines()
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    numbered = [f"{number}: {lines[number - 1]}" for number in range(start, end + 1)]
    return {"file": str(location.get("file", "")), "line": line, "start_line": start, "end_line": end, "text": "\n".join(numbered)}


def item_lane(item: dict) -> dict:
    if item.get("kind") == "proof":
        return item.get("proof_lane") or {}
    if item.get("kind") == "experiment":
        return item.get("experiment_lane") or {}
    return {}


def build_llm_context(base: Path, item_id: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    if not item.get("tex_locations"):
        update_locations(config, items)
        write_items(config, items)
        item = find_item(items, item_id) or item
    location = (item.get("tex_locations") or [None])[0]
    candidates = load_candidates(config)
    return {
        "item": item,
        "journal_profile": load_profile(config.journal, base),
        "location": location or {},
        "nearby_context": nearby_excerpt(config, location),
        "lane": item_lane(item),
        "item_plan": load_item_plans(config).get(item_id, {}),
        "review_analysis": load_review_analyses(config).get(item_id, {}),
        "proof_workflow": load_proof_workflows(config).get(item_id, {}),
        "experiment_manifest": load_experiment_manifests(config).get(item_id, {}),
        "candidate": next((candidate for candidate in candidates if candidate.get("item_id") == item_id), {}),
    }


class FakeLLMProvider:
    """Deterministic local provider used for tests and offline operation."""

    name = "fake"

    def draft(self, context: dict[str, object]) -> dict[str, object]:
        item = context["item"]
        profile = context["journal_profile"]
        location = context["location"]
        lane = context["lane"]
        analysis = context.get("review_analysis", {}) if isinstance(context.get("review_analysis", {}), dict) else {}
        summary = first_sentence(str(item.get("comment", "")))
        loc_text = f"{location.get('file')}:{location.get('line')}" if location else "unresolved location"
        kind = str(item.get("kind", "manuscript"))
        requested_change = {
            "proof": "verify the mathematical step and add author-approved proof text",
            "experiment": "record reproducible evidence before claiming the numerical result",
            "manuscript": "clarify the manuscript wording at the located passage",
        }.get(kind, "clarify the manuscript wording")
        requested_change = str(analysis.get("requested_change") or requested_change)
        response = response_for(item)
        response += f" This LLM draft interprets the reviewer request as: {requested_change}."
        if kind == "proof":
            candidate_text = "% REVAGENT LLM DRAFT: author must verify proof text before use.\n% Suggested focus: " + summary
            risk_notes = list(analysis.get("risk_notes", [])) or ["proof lane requires author verification before any approval"]
        elif kind == "experiment" and lane.get("result_status") != "recorded":
            candidate_text = "% REVAGENT LLM DRAFT: fill observed result only after provenance is recorded.\n% Suggested focus: " + summary
            risk_notes = list(analysis.get("risk_notes", [])) or ["experiment lane lacks recorded result provenance"]
        elif kind == "experiment":
            candidate_text = "Updated result summary based on the author-recorded experiment artifact."
            risk_notes = list(analysis.get("risk_notes", [])) or ["confirm backfill mapping before approving the candidate"]
        else:
            candidate_text = "We clarify this point in the revised manuscript by making the contribution and scope explicit."
            risk_notes = list(analysis.get("risk_notes", [])) or ["author should review final wording before approval"]
        return {
            "reviewer_intent": {
                "summary": str(analysis.get("intent_summary") or summary),
                "requested_change": requested_change,
                "lane": kind,
                "risk": item.get("risk", ""),
            },
            "response_draft": response,
            "candidate_text": candidate_text,
            "risk_notes": risk_notes,
            "context_summary": f"{profile.get('display_name', profile.get('key', 'journal'))}; location={loc_text}; source=offline fake provider",
        }


REQUIRED_PROVIDER_FIELDS = {"reviewer_intent", "response_draft", "candidate_text", "risk_notes", "context_summary"}


def validate_provider_output(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("LLM provider response must be a JSON object")
    missing = sorted(REQUIRED_PROVIDER_FIELDS - set(data))
    if missing:
        raise ValueError(f"LLM provider response missing fields: {', '.join(missing)}")
    if not isinstance(data["reviewer_intent"], dict):
        raise ValueError("LLM provider reviewer_intent must be an object")
    if not isinstance(data["risk_notes"], list):
        raise ValueError("LLM provider risk_notes must be a list")
    return data


def provider_prompt(context: dict[str, object]) -> list[dict[str, str]]:
    system = (
        "You draft peer-review response artifacts for a LaTeX revision assistant. "
        "Return only JSON with reviewer_intent, response_draft, candidate_text, risk_notes, and context_summary. "
        "All text is llm_draft only; do not approve, apply, invent proof verification, or invent experiment results."
    )
    user = json.dumps(context, indent=2, ensure_ascii=False, default=str)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class OpenAICompatibleProvider:
    """OpenAI-compatible chat completions provider using only stdlib HTTP."""

    name = "openai-compatible"

    def __init__(self) -> None:
        self.base_url = os.environ.get("REVAGENT_LLM_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("REVAGENT_LLM_API_KEY", "")
        self.model = os.environ.get("REVAGENT_LLM_MODEL", "")
        missing = [
            name
            for name, value in (
                ("REVAGENT_LLM_BASE_URL", self.base_url),
                ("REVAGENT_LLM_API_KEY", self.api_key),
                ("REVAGENT_LLM_MODEL", self.model),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"missing OpenAI-compatible provider environment variables: {', '.join(missing)}")

    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    def draft(self, context: dict[str, object]) -> dict[str, object]:
        payload = {
            "model": self.model,
            "messages": provider_prompt(context),
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        req = request.Request(
            self.endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("OpenAI-compatible response missing choices[0].message.content") from exc
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"OpenAI-compatible message content is not valid JSON: {exc}") from exc
        return validate_provider_output(parsed)


def provider_for(name: str) -> FakeLLMProvider | OpenAICompatibleProvider:
    if name == "fake":
        return FakeLLMProvider()
    if name == "openai-compatible":
        return OpenAICompatibleProvider()
    raise ValueError("unknown LLM provider; choose fake or openai-compatible")


def draft_item_with_llm(base: Path, item_id: str, provider: str = "fake", force: bool = False) -> dict:
    config = load_config(base)
    drafts = load_llm_drafts(config)
    if item_id in drafts and not force:
        return drafts[item_id]
    context = build_llm_context(base, item_id)
    provider_impl = provider_for(provider)
    generated = validate_provider_output(provider_impl.draft(context))
    propose_candidates(base)
    draft = {
        "item_id": item_id,
        "provider": provider_impl.name,
        "draft_source": "llm_draft",
        "review_status": "drafted",
        "review_note": "",
        "reviewed_at": "",
        "edited_at": "",
        "quality_status": "unchecked",
        "quality_issues": [],
        "quality_checked_at": "",
        "reviewer_intent": generated["reviewer_intent"],
        "response_draft": generated["response_draft"],
        "candidate_text": generated["candidate_text"],
        "risk_notes": generated["risk_notes"],
        "context_summary": generated["context_summary"],
        "created_at": now_iso(),
    }
    drafts[item_id] = draft

    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    item["response_draft"] = draft["response_draft"]
    item["draft_source"] = "llm_draft"
    item["llm_draft_id"] = item_id
    write_items(config, items)

    candidates = load_candidates(config)
    for candidate in candidates:
        if candidate.get("item_id") != item_id:
            continue
        candidate["draft_source"] = "llm_draft"
        candidate["llm_draft_id"] = item_id
        if candidate.get("status") in {"proposed", "blocked"}:
            candidate["content"] = draft["candidate_text"]
            candidate["updated_at"] = now_iso()
            if candidate.get("kind") == "proof":
                candidate["status"] = "blocked"
                candidate["requires_author_text"] = True
                candidate["blocked_reason"] = "llm draft requires author-verified proof text before approval"
            elif candidate.get("kind") == "experiment" and item_lane(item).get("result_status") != "recorded":
                candidate["status"] = "blocked"
                candidate["requires_author_text"] = True
                candidate["blocked_reason"] = "llm draft requires recorded experiment provenance before approval"
        break
    write_candidates(config, candidates)
    write_llm_drafts(config, drafts)
    return draft


def require_llm_draft(base: Path, item_id: str) -> tuple[Config, dict[str, dict], dict]:
    config = load_config(base)
    drafts = load_llm_drafts(config)
    draft = drafts.get(item_id)
    if draft is None:
        raise ValueError(f"unknown LLM draft {item_id}; run llm-draft {item_id} first")
    return config, drafts, ensure_llm_review_fields(draft)


def sync_reviewed_draft_to_workspace(config: Config, draft: dict) -> None:
    item_id = str(draft["item_id"])
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    item["response_draft"] = draft["response_draft"]
    item["draft_source"] = "llm_draft"
    item["llm_draft_id"] = item_id
    write_items(config, items)

    candidates = load_candidates(config)
    for candidate in candidates:
        if candidate.get("item_id") != item_id:
            continue
        candidate["draft_source"] = "llm_draft"
        candidate["llm_draft_id"] = item_id
        if candidate.get("status") in {"proposed", "blocked"}:
            candidate["content"] = draft["candidate_text"]
            candidate["updated_at"] = now_iso()
        break
    write_candidates(config, candidates)


def llm_review(base: Path, item_id: str) -> str:
    _, _, draft = require_llm_draft(base, item_id)
    return render_llm_drafts({item_id: draft})


def llm_accept(base: Path, item_id: str) -> dict:
    config, drafts, draft = require_llm_draft(base, item_id)
    draft["review_status"] = "accepted"
    draft["reviewed_at"] = now_iso()
    draft["quality_status"] = "unchecked"
    draft["quality_issues"] = []
    draft["quality_checked_at"] = ""
    drafts[item_id] = draft
    sync_reviewed_draft_to_workspace(config, draft)
    write_llm_drafts(config, drafts)
    append_decision_log(config, f"LLM draft accepted for {item_id}", ["- Status: accepted"])
    return draft


def llm_reject(base: Path, item_id: str, note: str) -> dict:
    config, drafts, draft = require_llm_draft(base, item_id)
    draft["review_status"] = "rejected"
    draft["review_note"] = note
    draft["reviewed_at"] = now_iso()
    drafts[item_id] = draft
    write_llm_drafts(config, drafts)
    append_decision_log(config, f"LLM draft rejected for {item_id}", [f"- Note: {note}"])
    return draft


def llm_edit(base: Path, item_id: str, response_file: str | None = None, candidate_file: str | None = None) -> dict:
    if not response_file and not candidate_file:
        raise ValueError("provide --response-file, --candidate-file, or both")
    config, drafts, draft = require_llm_draft(base, item_id)
    if response_file:
        draft["response_draft"] = read_text((config.workspace.parent / response_file).resolve() if not Path(response_file).is_absolute() else Path(response_file))
    if candidate_file:
        draft["candidate_text"] = read_text((config.workspace.parent / candidate_file).resolve() if not Path(candidate_file).is_absolute() else Path(candidate_file))
    draft["review_status"] = "edited"
    draft["edited_at"] = now_iso()
    draft["reviewed_at"] = draft["edited_at"]
    draft["quality_status"] = "unchecked"
    draft["quality_issues"] = []
    draft["quality_checked_at"] = ""
    drafts[item_id] = draft
    sync_reviewed_draft_to_workspace(config, draft)
    write_llm_drafts(config, drafts)
    append_decision_log(config, f"LLM draft edited for {item_id}", [f"- Response file: {response_file or 'unchanged'}", f"- Candidate file: {candidate_file or 'unchanged'}"])
    return draft


def risky_claim_present(text: str, needles: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(needle in lower for needle in needles)


def quality_issues_for(config: Config, draft: dict) -> list[str]:
    item_id = str(draft["item_id"])
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        return [f"unknown review item {item_id}"]
    text = f"{draft.get('response_draft', '')}\n{draft.get('candidate_text', '')}"
    issues: list[str] = []
    if draft.get("draft_source") != "llm_draft":
        issues.append("draft_source must remain llm_draft")
    if item.get("kind") == "proof":
        lane = item.get("proof_lane") or {}
        if lane.get("approval_status", "required") != "approved":
            issues.append("proof workflow approval is required before an LLM proof draft can pass quality checks")
        if lane.get("approval_status", "required") != "approved" and risky_claim_present(text, ("we prove", "we have proved", "proof is complete", "establishes the theorem", "is proven")):
            issues.append("proof draft appears to claim a completed proof before proof workflow approval")
    if item.get("kind") == "experiment":
        lane = item.get("experiment_lane") or {}
        if lane.get("result_status") != "recorded":
            issues.append("recorded experiment provenance is required before an LLM experiment draft can pass quality checks")
        if lane.get("result_status") != "recorded" and risky_claim_present(text, ("observed", "improves", "outperforms", "reduced error", "accuracy", "%", "result shows")):
            issues.append("experiment draft appears to claim results before recorded provenance")
    candidates = load_candidates(config)
    for candidate in candidates:
        if candidate.get("item_id") != item_id:
            continue
        if candidate.get("status") in {"approved", "applied"} and candidate.get("llm_draft_id") == item_id:
            issues.append("LLM draft must not directly approve or apply a candidate")
        if candidate.get("draft_source") and candidate.get("draft_source") != "llm_draft":
            issues.append("candidate draft_source must remain llm_draft")
        break
    return issues


def llm_check(base: Path, item_id: str) -> dict:
    config, drafts, draft = require_llm_draft(base, item_id)
    issues = quality_issues_for(config, draft)
    draft["quality_issues"] = issues
    draft["quality_status"] = "failed" if issues else "passed"
    draft["quality_checked_at"] = now_iso()
    drafts[item_id] = draft
    write_llm_drafts(config, drafts)
    append_decision_log(config, f"LLM draft quality checked for {item_id}", [f"- Status: {draft['quality_status']}", f"- Issues: {len(issues)}"])
    return draft


def llm_check_all(base: Path) -> dict[str, dict]:
    config = load_config(base)
    for item_id in sorted(load_llm_drafts(config)):
        llm_check(base, item_id)
    return load_llm_drafts(config)


def draft_all_with_llm(base: Path, provider: str = "fake", force: bool = False) -> dict[str, dict]:
    config = load_config(base)
    result = load_llm_drafts(config)
    for item in load_items(config):
        result[item["id"]] = draft_item_with_llm(base, item["id"], provider=provider, force=force)
    return load_llm_drafts(config)


def render_llm_drafts(drafts: dict[str, dict]) -> str:
    lines = ["# LLM Drafts", ""]
    if not drafts:
        lines.append("No LLM drafts generated yet.")
    for item_id in sorted(drafts):
        draft = ensure_llm_review_fields(drafts[item_id])
        intent = draft.get("reviewer_intent", {})
        lines.extend(
            [
                f"## {item_id}",
                "",
                f"- Provider: {draft.get('provider', '')}",
                f"- Source: {draft.get('draft_source', '')}",
                f"- Review status: {draft.get('review_status', '')}",
                f"- Quality status: {draft.get('quality_status', '')}",
                f"- Intent: {intent.get('summary', '')}",
                f"- Requested change: {intent.get('requested_change', '')}",
                f"- Context: {draft.get('context_summary', '')}",
                "",
                "### Response Draft",
                "",
                str(draft.get("response_draft", "")),
                "",
                "### Candidate Manuscript Text",
                "",
                str(draft.get("candidate_text", "")),
                "",
            ]
        )
        if draft.get("review_note"):
            lines.extend(["### Review Note", "", str(draft.get("review_note", "")), ""])
        if draft.get("quality_issues"):
            lines.extend(["### Quality Issues", ""])
            lines.extend(f"- {issue}" for issue in draft.get("quality_issues", []))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "FakeLLMProvider",
    "build_llm_context",
    "draft_all_with_llm",
    "draft_item_with_llm",
    "ensure_llm_review_fields",
    "llm_accept",
    "llm_check",
    "llm_check_all",
    "llm_edit",
    "llm_reject",
    "llm_review",
    "load_llm_drafts",
    "render_llm_drafts",
    "write_llm_drafts",
]
