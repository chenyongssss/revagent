"""Candidate edit state machine and safe-apply public API."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ._models import Config
from ._utils import append_decision_log, find_candidate, find_item, first_sentence, load_config, load_items, now_iso, read_json, read_text, write_items, write_json, write_text
from .latex import context_hash_for_lines, latex_index, update_locations

def candidate_path(config: Config) -> Path:
    return config.workspace / "candidate_edits.json"

def load_candidates(config: Config) -> list[dict]:
    return read_json(candidate_path(config), [])

def write_candidates(config: Config, candidates: list[dict]) -> None:
    write_json(candidate_path(config), candidates)

def load_candidate_llm_draft(config: Config, candidate: dict) -> dict | None:
    draft_id = str(candidate.get("llm_draft_id") or candidate.get("item_id") or "")
    if not draft_id:
        return None
    return read_json(config.workspace / "llm_drafts.json", {}).get(draft_id)

def llm_candidate_gate_reason(config: Config, candidate: dict) -> str:
    if candidate.get("draft_source") != "llm_draft" or candidate.get("author_edited"):
        return ""
    draft_id = str(candidate.get("llm_draft_id") or candidate.get("item_id") or "")
    draft = load_candidate_llm_draft(config, candidate)
    if not draft:
        return f"candidate {candidate.get('id')} is linked to missing LLM draft {draft_id}"
    review_status = draft.get("review_status", "drafted")
    if review_status not in {"accepted", "edited"}:
        return f"candidate {candidate.get('id')} requires accepted or edited LLM draft before approval"
    quality_status = draft.get("quality_status", "unchecked")
    if quality_status != "passed":
        return f"candidate {candidate.get('id')} requires passed LLM quality check before approval"
    if str(candidate.get("content", "")).strip() != str(draft.get("candidate_text", "")).strip():
        return f"candidate {candidate.get('id')} content differs from its reviewed LLM draft; rerun incorporate-drafts or edit-candidate"
    return ""

def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]

def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

def span_hash(lines: list[str], start_line: int, end_line: int) -> str:
    start = max(1, start_line)
    end = min(len(lines), end_line)
    if start > end:
        return ""
    return text_hash("\n".join(lines[start - 1 : end]))

def default_anchor(config: Config) -> tuple[str, int, bool]:
    main = config.tex_root / config.main_tex
    if not main.exists():
        return config.main_tex, 1, True
    lines = read_text(main).splitlines()
    for index, line in enumerate(lines, start=1):
        if "\\begin{document}" in line:
            return config.main_tex, index, True
    return config.main_tex, max(1, len(lines)), True

def target_for_item(config: Config, item: dict) -> tuple[str, int, bool, dict[str, object]]:
    locations = item.get("tex_locations") or []
    if locations:
        loc = locations[0]
        low_confidence = int(loc.get("score", 0)) < 20
        return str(loc["file"]), int(loc["line"]), low_confidence, loc
    target_file, anchor_line, low_confidence = default_anchor(config)
    return target_file, anchor_line, low_confidence, {}

def anchor_hash_for(config: Config, target_file: str, anchor_line: int) -> str:
    target = config.tex_root / target_file
    if not target.exists():
        return ""
    lines = read_text(target).splitlines()
    if anchor_line < 1 or anchor_line > len(lines):
        return ""
    return line_hash(lines[anchor_line - 1])

def anchor_context_hash_for(config: Config, target_file: str, anchor_line: int) -> str:
    target = config.tex_root / target_file
    if not target.exists():
        return ""
    return context_hash_for_lines(read_text(target).splitlines(), anchor_line)

def environment_for_target(config: Config, target_file: str, anchor_line: int, context_type: str = "") -> dict[str, object] | None:
    index = latex_index(config.tex_root, config.main_tex)
    envs = [env for env in index.get("environments", []) if env.get("file") == target_file]
    containing = [env for env in envs if int(env.get("line", 0)) <= anchor_line <= int(env.get("end_line", 0))]
    if context_type:
        typed = [env for env in containing if env.get("environment") == context_type]
        if typed:
            return typed[0]
    if containing:
        return containing[0]
    if context_type:
        typed = [env for env in envs if env.get("environment") == context_type]
        if typed:
            return min(typed, key=lambda env: abs(int(env.get("line", 0)) - anchor_line))
    return min(envs, key=lambda env: abs(int(env.get("line", 0)) - anchor_line)) if envs else None

def candidate_patch_metadata(config: Config, item: dict, target_file: str, anchor_line: int, loc: dict[str, object]) -> dict[str, object]:
    context_type = str(loc.get("context_type", ""))
    target = config.tex_root / target_file
    lines = read_text(target).splitlines() if target.exists() else []
    operation = "insert_after_line"
    target_span = {"start_line": anchor_line, "end_line": anchor_line}
    environment_id = ""
    if item["kind"] == "proof" and context_type in {"proof", "theorem", "lemma", "proposition", "corollary", "assumption"}:
        env = environment_for_target(config, target_file, anchor_line, context_type)
        if env:
            operation = "insert_after_environment"
            target_span = {"start_line": int(env["line"]), "end_line": int(env["end_line"])}
            environment_id = f"{env.get('environment')}@{target_file}:{env.get('line')}"
    elif item["kind"] == "experiment" and context_type in {"figure", "table"}:
        env = environment_for_target(config, target_file, anchor_line, context_type)
        if env:
            operation = "update_caption"
            target_span = {"start_line": int(env["line"]), "end_line": int(env["end_line"])}
            environment_id = f"{env.get('environment')}@{target_file}:{env.get('line')}"
    original = span_hash(lines, int(target_span["start_line"]), int(target_span["end_line"]))
    return {
        "operation": operation,
        "target_span": target_span,
        "environment_id": environment_id,
        "original_content_hash": original,
    }

def template_candidate_content(item: dict) -> tuple[str, bool, str]:
    if item["kind"] == "proof":
        return (
            "% REVAGENT proof TODO: author must provide verified proof text before applying this item.",
            True,
            "blocked",
        )
    if item["kind"] == "experiment":
        lane = item.get("experiment_lane") or {}
        records = lane.get("recorded_results", [])
        if records:
            latest = records[-1]
            caption = "result backfill pending final author wording"
            if item.get("tex_locations") and item["tex_locations"][0].get("context_type") in {"figure", "table"}:
                caption = "Updated result backfill summary from author-recorded artifact " + str(latest.get("artifact", ""))
            return (
                caption,
                False,
                "proposed",
            )
        return (
            "% REVAGENT experiment TODO: author must provide observed results, seed, and artifact provenance before applying this item.",
            True,
            "blocked",
        )
    return (
        "% REVAGENT clarification TODO: replace this note with concise manuscript text addressing "
        + first_sentence(item["comment"]),
        False,
        "proposed",
    )

def next_candidate_id(existing: list[dict], index: int) -> str:
    used = {candidate.get("id") for candidate in existing}
    candidate_id = f"C{index:03d}"
    while candidate_id in used:
        index += 1
        candidate_id = f"C{index:03d}"
    return candidate_id

def make_candidate(config: Config, item: dict, candidate_id: str) -> dict:
    target_file, anchor_line, low_confidence, loc = target_for_item(config, item)
    content, requires_author_text, status_value = template_candidate_content(item)
    patch = candidate_patch_metadata(config, item, target_file, anchor_line, loc)
    return {
        "id": candidate_id,
        "item_id": item["id"],
        "kind": item["kind"],
        "risk": item["risk"],
        "status": status_value,
        "target_file": target_file,
        "anchor_line": anchor_line,
        "anchor_hash": anchor_hash_for(config, target_file, anchor_line),
        "anchor_context_hash": anchor_context_hash_for(config, target_file, anchor_line),
        "low_confidence_location": low_confidence,
        "location_score": loc.get("score", 0),
        "location_reason": loc.get("reason", "fallback insertion point"),
        "target_context": {
            "type": loc.get("context_type", "document"),
            "title": loc.get("context_title", ""),
        },
        "proof_workflow_id": item["id"] if item["kind"] == "proof" else "",
        "proof_gate_status": (item.get("proof_lane") or {}).get("approval_status", "required") if item["kind"] == "proof" else "",
        "operation": patch["operation"],
        "target_span": patch["target_span"],
        "environment_id": patch["environment_id"],
        "original_content_hash": patch["original_content_hash"],
        "conflict_reason": "",
        "backup_dir": "",
        "content": content,
        "requires_author_text": requires_author_text,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "approved_at": "",
        "applied_at": "",
        "blocked_reason": "author text required before proposal can be approved" if status_value == "blocked" else "",
    }

def propose_candidates(base: Path, force: bool = False) -> list[dict]:
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    if any(not item.get("tex_locations") for item in items):
        update_locations(config, items)
        write_json(config.workspace / "review_items.json", items)
    existing = load_candidates(config)
    preserved_statuses = {"edited", "approved", "applied"}
    if force:
        candidates = [candidate for candidate in existing if candidate.get("status") in preserved_statuses]
    else:
        candidates = list(existing)
    existing_item_ids = {candidate.get("item_id") for candidate in candidates}
    for item in items:
        if item["id"] in existing_item_ids:
            continue
        candidates.append(make_candidate(config, item, next_candidate_id(candidates, len(candidates) + 1)))
    candidate_item_ids = {candidate.get("item_id") for candidate in candidates}
    for item in items:
        if item["id"] in candidate_item_ids and item.get("planning_status") in {"triaged", "planned"}:
            item["planning_status"] = "drafted"
    write_items(config, items)
    write_candidates(config, candidates)
    return candidates

def inspect_record(base: Path, record_id: str) -> dict[str, object]:
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    candidates = load_candidates(config)
    if record_id.startswith("R"):
        item = find_item(items, record_id)
        if item is None:
            raise ValueError(f"unknown review item {record_id}")
        linked = [candidate for candidate in candidates if candidate.get("item_id") == record_id]
        return {"type": "review_item", "item": item, "candidates": linked}
    candidate = find_candidate(candidates, record_id)
    if candidate is None:
        raise ValueError(f"unknown candidate edit {record_id}")
    candidate = dict(candidate)
    if candidate.get("draft_source") == "llm_draft":
        draft = load_candidate_llm_draft(config, candidate)
        candidate["llm_review_status"] = draft.get("review_status", "missing") if draft else "missing"
        candidate["llm_quality_status"] = draft.get("quality_status", "missing") if draft else "missing"
    item = find_item(items, candidate["item_id"])
    return {"type": "candidate", "candidate": candidate, "item": item}

def candidate_summary(record: dict[str, object]) -> str:
    lines = []
    if record["type"] == "review_item":
        item = record["item"]
        lines.extend(
            [
                f"{item['id']} [{item['kind']}, {item['risk']} risk]",
                f"status: {item['status']}",
                f"comment: {first_sentence(item['comment'])}",
            ]
        )
        locations = item.get("tex_locations") or []
        if locations:
            lines.append("locations:")
            for loc in locations:
                lines.append(
                    f"- {loc['file']}:{loc['line']} score={loc.get('score', 0)} "
                    f"{loc.get('context_type', '')} {loc.get('context_title', '')} "
                    f"reason={loc.get('reason', '')}"
                )
        else:
            lines.append("locations: none")
        candidates = record["candidates"]
        if candidates:
            lines.append("candidates:")
            for candidate in candidates:
                lines.append(f"- {candidate['id']} {candidate['status']} {candidate['target_file']}:{candidate['anchor_line']}")
        else:
            lines.append("candidates: none")
        return "\n".join(lines)
    candidate = record["candidate"]
    item = record.get("item")
    lines.extend(
        [
            f"{candidate['id']} for {candidate['item_id']} [{candidate['kind']}, {candidate['risk']} risk]",
            f"status: {candidate['status']}",
            f"target: {candidate['target_file']}:{candidate['anchor_line']}",
            f"operation: {candidate['operation']}",
            f"target span: {candidate.get('target_span', {})}",
            f"environment: {candidate.get('environment_id', '')}",
            f"low confidence location: {str(candidate.get('low_confidence_location', False)).lower()}",
            f"location score: {candidate.get('location_score', 0)}",
            f"location reason: {candidate.get('location_reason', '')}",
            f"target context: {candidate.get('target_context', {}).get('type', '')} {candidate.get('target_context', {}).get('title', '')}",
            f"requires author text: {str(candidate.get('requires_author_text', False)).lower()}",
        ]
    )
    if candidate.get("draft_source"):
        lines.append(f"draft source: {candidate.get('draft_source', '')}")
    if candidate.get("llm_draft_id"):
        lines.append(f"llm draft id: {candidate.get('llm_draft_id', '')}")
    if candidate.get("llm_review_status") or candidate.get("llm_quality_status"):
        lines.append(f"llm draft status: review={candidate.get('llm_review_status', '')} quality={candidate.get('llm_quality_status', '')}")
    if candidate.get("blocked_reason"):
        lines.append(f"blocked reason: {candidate['blocked_reason']}")
    if candidate.get("conflict_reason"):
        lines.append(f"conflict reason: {candidate['conflict_reason']}")
    if candidate.get("backup_dir"):
        lines.append(f"backup dir: {candidate['backup_dir']}")
    if item:
        lines.append(f"comment: {first_sentence(item['comment'])}")
    lines.extend(["content:", candidate.get("content", "")])
    return "\n".join(lines)

def edit_candidate(base: Path, candidate_id: str, text_file: str) -> dict:
    config = load_config(base)
    candidates = load_candidates(config)
    candidate = find_candidate(candidates, candidate_id)
    if candidate is None:
        raise ValueError(f"unknown candidate edit {candidate_id}")
    candidate["content"] = read_text((base / text_file).resolve()).rstrip()
    candidate["status"] = "edited"
    candidate["requires_author_text"] = False
    candidate["author_edited"] = True
    candidate["blocked_reason"] = ""
    candidate["updated_at"] = now_iso()
    write_candidates(config, candidates)
    return candidate

def approve_candidate(base: Path, candidate_id: str, allow_high_risk: bool = False) -> dict:
    config = load_config(base)
    candidates = load_candidates(config)
    candidate = find_candidate(candidates, candidate_id)
    if candidate is None:
        raise ValueError(f"unknown candidate edit {candidate_id}")
    if candidate.get("status") not in {"proposed", "edited"}:
        raise ValueError(f"candidate {candidate_id} cannot be approved from status {candidate.get('status')}")
    if candidate.get("requires_author_text"):
        raise ValueError(f"candidate {candidate_id} requires author text before approval")
    llm_gate_reason = llm_candidate_gate_reason(config, candidate)
    if llm_gate_reason and candidate.get("status") != "edited":
        raise ValueError(llm_gate_reason)
    items = load_items(config)
    item = find_item(items, candidate["item_id"])
    if candidate.get("kind") == "proof":
        lane = (item or {}).get("proof_lane") or {}
        if lane.get("approval_status") != "approved":
            raise ValueError(f"candidate {candidate_id} is blocked by proof workflow approval gate")
        candidate["proof_gate_status"] = "approved"
    if candidate.get("risk") == "high" and not allow_high_risk:
        raise ValueError(f"candidate {candidate_id} is high risk; pass --allow-high-risk after author verification")
    candidate["status"] = "approved"
    candidate["approved_at"] = now_iso()
    candidate["updated_at"] = now_iso()
    write_candidates(config, candidates)
    if item is not None and not item.get("blocking_questions") and item.get("planning_status") not in {"incorporated", "closed"}:
        item["planning_status"] = "approved"
        write_items(config, items)
    return candidate

def reject_candidate(base: Path, candidate_id: str) -> dict:
    config = load_config(base)
    candidates = load_candidates(config)
    candidate = find_candidate(candidates, candidate_id)
    if candidate is None:
        raise ValueError(f"unknown candidate edit {candidate_id}")
    candidate["status"] = "rejected"
    candidate["updated_at"] = now_iso()
    write_candidates(config, candidates)
    return candidate

def candidate_insert_lines(candidate: dict) -> list[str]:
    content = candidate.get("content", "").rstrip("\n")
    return [""] + content.splitlines() + [""]

def apply_candidate_to_lines(lines: list[str], candidate: dict) -> list[str]:
    operation = candidate.get("operation", "insert_after_line")
    span = candidate.get("target_span") or {}
    start_line = int(span.get("start_line", candidate.get("anchor_line", 1)))
    end_line = int(span.get("end_line", candidate.get("anchor_line", 1)))
    anchor_line = int(candidate["anchor_line"])
    if operation == "insert_after_line":
        if anchor_line < 0 or anchor_line > len(lines):
            raise ValueError(f"anchor line {anchor_line} is outside target file")
        revised = list(lines)
        revised[anchor_line:anchor_line] = candidate_insert_lines(candidate)
        return revised
    if start_line < 1 or end_line > len(lines) or start_line > end_line:
        raise ValueError(f"target span {start_line}-{end_line} is outside target file")
    revised = list(lines)
    if operation == "insert_before_environment":
        revised[start_line - 1 : start_line - 1] = candidate_insert_lines(candidate)
        return revised
    if operation == "insert_after_environment":
        revised[end_line:end_line] = candidate_insert_lines(candidate)
        return revised
    if operation == "replace_block":
        revised[start_line - 1 : end_line] = candidate.get("content", "").rstrip("\n").splitlines()
        return revised
    if operation == "update_caption":
        block = "\n".join(revised[start_line - 1 : end_line])
        replacement = "\\caption{" + candidate.get("content", "").strip() + "}"
        updated, count = re.subn(r"\\caption(?:\[[^\]]*\])?\{[^{}]*\}", lambda _: replacement, block, count=1, flags=re.S)
        if count == 0:
            raise ValueError("target environment has no simple caption to update")
        revised[start_line - 1 : end_line] = updated.splitlines()
        return revised
    raise ValueError(f"unsupported candidate operation {operation}")

def verify_candidate_span(config: Config, candidate: dict) -> str:
    span = candidate.get("target_span") or {}
    expected = candidate.get("original_content_hash", "")
    if not expected or candidate.get("operation") == "insert_after_line":
        return ""
    target = config.tex_root / candidate["target_file"]
    if not target.exists():
        return f"target file not found: {candidate['target_file']}"
    lines = read_text(target).splitlines()
    current = span_hash(lines, int(span.get("start_line", 1)), int(span.get("end_line", 1)))
    if current != expected:
        return f"target span hash mismatch for {candidate['target_file']}:{span.get('start_line')}-{span.get('end_line')}"
    return ""

def verify_candidate_operation(config: Config, candidate: dict) -> str:
    operation = candidate.get("operation", "insert_after_line")
    allowed = {"insert_after_line", "replace_block", "insert_before_environment", "insert_after_environment", "update_caption"}
    if operation not in allowed:
        return f"unsupported candidate operation {operation}"
    span_reason = verify_candidate_span(config, candidate)
    if span_reason:
        return span_reason
    if operation == "update_caption":
        target = config.tex_root / candidate["target_file"]
        lines = read_text(target).splitlines() if target.exists() else []
        span = candidate.get("target_span") or {}
        start_line = int(span.get("start_line", 1))
        end_line = int(span.get("end_line", 1))
        block = "\n".join(lines[start_line - 1 : end_line])
        if not re.search(r"\\caption(?:\[[^\]]*\])?\{[^{}]*\}", block, re.S):
            return "target environment has no simple caption to update"
    return ""

def apply_candidate_to_target(config: Config, candidate: dict) -> list[str]:
    target = config.tex_root / candidate["target_file"]
    original = read_text(target).splitlines() if target.exists() else []
    return apply_candidate_to_lines(original, candidate)

def candidate_apply_order(candidate: dict) -> int:
    span = candidate.get("target_span") or {}
    return int(span.get("end_line", candidate.get("anchor_line", 1)))

def candidate_diff(config: Config, candidate: dict) -> list[str]:
    target = config.tex_root / candidate["target_file"]
    original = read_text(target).splitlines() if target.exists() else []
    revised = apply_candidate_to_lines(original, candidate)
    return list(
        difflib.unified_diff(
            original,
            revised,
            fromfile=f"a/{candidate['target_file']}",
            tofile=f"b/{candidate['target_file']}",
            lineterm="",
        )
    )

def verify_candidate_anchor(config: Config, candidate: dict) -> str:
    current = anchor_hash_for(config, candidate["target_file"], int(candidate["anchor_line"]))
    expected = candidate.get("anchor_hash", "")
    if expected and current != expected:
        return f"anchor hash mismatch for {candidate['target_file']}:{candidate['anchor_line']}"
    current_context = anchor_context_hash_for(config, candidate["target_file"], int(candidate["anchor_line"]))
    expected_context = candidate.get("anchor_context_hash", "")
    if expected_context and current_context != expected_context:
        return f"anchor context hash mismatch for {candidate['target_file']}:{candidate['anchor_line']}"
    return ""

def approved_candidates(config: Config) -> list[dict]:
    return [candidate for candidate in load_candidates(config) if candidate.get("status") == "approved"]

def render_apply_diff(base: Path, approved_only: bool = True) -> str:
    config = load_config(base)
    candidates = approved_candidates(config) if approved_only else load_candidates(config)
    outputs = []
    for candidate in candidates:
        outputs.append(
            f"# {candidate['id']} for {candidate['item_id']} "
            f"[{candidate['risk']} risk] {candidate['target_file']}:{candidate['anchor_line']} "
            f"operation={candidate.get('operation', 'insert_after_line')} "
            f"score={candidate.get('location_score', 0)} reason={candidate.get('location_reason', '')}"
        )
        try:
            outputs.extend(candidate_diff(config, candidate))
        except ValueError as exc:
            outputs.append(f"# blocked: {exc}")
    if not outputs:
        return "# No candidate edits selected for apply.\n"
    return "\n".join(outputs) + "\n"

def backup_targets(config: Config, candidates: list[dict]) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = config.workspace / "backups" / timestamp
    for target_name in sorted({candidate["target_file"] for candidate in candidates}):
        source = config.tex_root / target_name
        if source.exists():
            backup = backup_dir / target_name
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(source.read_bytes())
    return backup_dir

def apply_approved_candidates(base: Path) -> dict[str, object]:
    config = load_config(base)
    candidates = load_candidates(config)
    selected = [candidate for candidate in candidates if candidate.get("status") == "approved"]
    blocked = []
    for candidate in selected:
        reason = verify_candidate_anchor(config, candidate) or verify_candidate_operation(config, candidate)
        if reason:
            candidate["status"] = "blocked"
            candidate["blocked_reason"] = reason
            candidate["conflict_reason"] = reason
            candidate["updated_at"] = now_iso()
            blocked.append(candidate["id"])
    selected = [candidate for candidate in selected if candidate.get("status") == "approved"]
    if blocked:
        write_candidates(config, candidates)
        return {"applied": [], "blocked": blocked, "backup_dir": ""}
    if not selected:
        return {"applied": [], "blocked": [], "backup_dir": ""}
    backup_dir = backup_targets(config, selected)
    by_target: dict[str, list[dict]] = {}
    for candidate in selected:
        by_target.setdefault(candidate["target_file"], []).append(candidate)
    applied = []
    for target_name, target_candidates in by_target.items():
        target = config.tex_root / target_name
        lines = read_text(target).splitlines()
        for candidate in sorted(target_candidates, key=candidate_apply_order, reverse=True):
            lines = apply_candidate_to_lines(lines, candidate)
            candidate["status"] = "applied"
            candidate["applied_at"] = now_iso()
            candidate["updated_at"] = now_iso()
            candidate["backup_dir"] = str(backup_dir)
            candidate["conflict_reason"] = ""
            applied.append(candidate["id"])
        write_text(target, "\n".join(lines) + "\n")
    log_path = config.workspace / "apply_log.jsonl"
    for candidate_id in applied:
        entry = {"candidate_id": candidate_id, "applied_at": now_iso(), "backup_dir": str(backup_dir)}
        write_text(log_path, (read_text(log_path) if log_path.exists() else "") + json.dumps(entry, ensure_ascii=False) + "\n")
    write_candidates(config, candidates)
    items = load_items(config)
    applied_item_ids = {candidate["item_id"] for candidate in candidates if candidate.get("id") in applied}
    for item in items:
        if item.get("id") in applied_item_ids:
            item["planning_status"] = "incorporated"
    write_items(config, items)
    return {"applied": applied, "blocked": blocked, "backup_dir": str(backup_dir)}

def restore_backup(base: Path, backup_dir: str) -> list[str]:
    config = load_config(base)
    backup = Path(backup_dir)
    if not backup.is_absolute():
        backup = (base / backup).resolve()
    backups_root = (config.workspace / "backups").resolve()
    resolved = backup.resolve()
    if backups_root not in resolved.parents and resolved != backups_root:
        raise ValueError(f"backup is outside RevAgent backups: {backup_dir}")
    if not resolved.exists():
        raise ValueError(f"backup not found: {backup_dir}")
    restored = []
    for source in sorted(path for path in resolved.rglob("*") if path.is_file()):
        rel = source.relative_to(resolved)
        target = config.tex_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        restored.append(str(rel))
    append_decision_log(config, "Backup restored", [f"- Backup: {resolved}", f"- Files: {', '.join(restored) or 'none'}"])
    return restored

__all__ = [
    "apply_approved_candidates",
    "approve_candidate",
    "candidate_summary",
    "edit_candidate",
    "inspect_record",
    "load_candidates",
    "propose_candidates",
    "reject_candidate",
    "render_apply_diff",
    "restore_backup",
    "verify_candidate_anchor",
    "write_candidates",
]
