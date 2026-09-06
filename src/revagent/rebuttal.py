"""Local, author-gated rebuttal thread and draft scaffolding."""
from __future__ import annotations
import re

from ._utils import file_sha256, load_config, now_iso, read_json, write_json, write_text
from .profiles import load_profile, validate_rulepack


PLACEHOLDER_MARKERS = ("AUTHOR MUST PROVIDE", "[TODO", "[INSERT", "TBD")
FUTURE_COMMITMENT = re.compile(r"\b(?:we|the authors?)\s+(?:will|plan to|intend to|shall)\b|\bwill\s+(?:add|revise|perform|include|provide|correct)\b", re.I)
DISCOURTEOUS = re.compile(r"\b(?:the reviewer is wrong|obviously the reviewer|the reviewer clearly misunderstood|nonsense|ridiculous)\b", re.I)
LIST_PREFIX = re.compile(r"^\s*(?:\(?[a-zA-Z0-9]+[.)]|[-*])\s+")
REQUEST_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=(?:Please|Could|Would|Clarify|Explain|Provide|Add|Report|Address|Why|How)\b)", re.I)


def _atomize(comment: str) -> list[str]:
    parts = []
    for line in comment.splitlines() or [comment]:
        cleaned = LIST_PREFIX.sub("", line).strip()
        parts.extend(part.strip() for part in REQUEST_BOUNDARY.split(cleaned) if part.strip())
    return parts or [comment]


def _words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text, re.UNICODE))


def _positive_limit(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _render_stress_test(report: dict) -> str:
    lines = ["# Rebuttal Stress Test", "", f"- Status: `{'ready' if report['ok'] else 'author_review_required'}`", f"- Journal: `{report['journal']}`", f"- Total response words: {report['length']['total_words']}", "", "## Blocking Findings", ""]
    categories = (
        ("Open atoms", report["open_atoms"]), ("Traceability gaps", report["traceability_gaps"]),
        ("Missing responses", report["response_gaps"]), ("Placeholders", report["placeholder_gaps"]),
        ("Unresolved commitments", report["unresolved_commitments"]), ("Tone findings", report["tone_findings"]),
    )
    for label, values in categories:
        lines.append(f"- {label}: {', '.join(values) if values else 'none'}")
    for finding in report["length"]["findings"]:
        lines.append(f"- Length `{finding['scope']}`: {finding['observed']} words exceeds {finding['limit']}")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def parse_rebuttal(base) -> dict:
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    threads = {}
    for item in items:
        comment = str(item.get("comment", "")).strip()
        parts = _atomize(comment)
        atoms = [{"atom_id": f"RB-{item['id']}-{number}", "request": part, "source_item_id": str(item["id"]),
                  "source_comment": comment, "status": "unplanned", "manuscript_evidence": [], "author_approval": "required"}
                 for number, part in enumerate(parts, 1)]
        threads[str(item["id"])] = {"thread_id": f"RB-{item['id']}", "reviewer": item.get("reviewer", "reviewer"), "request": comment, "atoms": atoms}
    result = {"version": 2, "generated_at": now_iso(), "threads": threads}
    write_json(config.workspace / "rebuttal_threads.json", result)
    write_text(config.workspace / "rebuttal_threads.md", "# Rebuttal Threads\n\n" + "\n".join(f"- `{thread['thread_id']}`: {thread['request']}" for thread in threads.values()) + "\n")
    return result


def rebuttal_plan(base) -> dict:
    config = load_config(base)
    result = read_json(config.workspace / "rebuttal_threads.json", {})
    for thread in result.get("threads", {}).values():
        for atom in thread["atoms"]:
            atom["status"] = "planned"
            atom["plan"] = "Author identifies supporting manuscript/evidence locations before drafting."
    write_json(config.workspace / "rebuttal_threads.json", result)
    return result


def _render_rebuttal_draft(result: dict) -> str:
    lines = ["# PASTE_READY - Author Review Required", ""]
    for thread in result.get("threads", {}).values():
        for atom in thread["atoms"]:
            response = str(atom.get("response_text", "")).strip()
            rendered_response = response or "[AUTHOR MUST PROVIDE VERIFIED RESPONSE AND MANUSCRIPT LOCATION]"
            lines.extend([f"## {atom['atom_id']}", "", f"Reviewer request: {atom['request']}", "", f"Author response: {rendered_response}", ""])
            if atom.get("status") != "approved":
                atom["status"] = "drafted_unapproved"
    return "\n".join(lines)


def rebuttal_draft(base) -> str:
    config = load_config(base)
    result = read_json(config.workspace / "rebuttal_threads.json", {})
    draft = _render_rebuttal_draft(result)
    write_json(config.workspace / "rebuttal_threads.json", result)
    write_text(config.workspace / "rebuttal_draft.md", draft)
    structured = {"version": 1, "generated_at": now_iso(), "status": "author_review_required",
                  "atoms": [{key: atom.get(key, "") for key in ("atom_id", "source_item_id", "request", "response_text", "manuscript_locator", "evidence", "status", "author_approval")}
                            for thread in result.get("threads", {}).values() for atom in thread.get("atoms", [])],
                  "limitations": ["Responses remain author-gated and are not fact-verified by this export."]}
    write_json(config.workspace / "rebuttal_draft.json", structured)
    paste_ready = "\n\n".join(str(atom.get("response_text", "")).strip() or "[AUTHOR MUST PROVIDE VERIFIED RESPONSE]"
                               for thread in result.get("threads", {}).values() for atom in thread.get("atoms", [])) + "\n"
    write_text(config.workspace / "rebuttal_paste_ready.txt", paste_ready)
    return draft


def rebuttal_stress_test(base) -> dict:
    config = load_config(base)
    result = read_json(config.workspace / "rebuttal_threads.json", {})
    open_atoms = [atom["atom_id"] for thread in result.get("threads", {}).values() for atom in thread["atoms"] if atom.get("status") != "approved"]
    atoms = [atom for thread in result.get("threads", {}).values() for atom in thread["atoms"]]
    trace_gaps = [atom["atom_id"] for atom in atoms if atom.get("status") == "approved" and (not atom.get("manuscript_locator") or not atom.get("evidence"))]
    response_gaps = [atom["atom_id"] for atom in atoms if not str(atom.get("response_text", atom.get("approval_note", ""))).strip()]
    placeholder_gaps = [atom["atom_id"] for atom in atoms if any(marker.lower() in str(atom.get("response_text", atom.get("approval_note", ""))).lower() for marker in PLACEHOLDER_MARKERS)]
    unresolved_commitments = [atom["atom_id"] for atom in atoms if FUTURE_COMMITMENT.search(str(atom.get("response_text", atom.get("approval_note", ""))))]
    tone_findings = [atom["atom_id"] for atom in atoms if DISCOURTEOUS.search(str(atom.get("response_text", atom.get("approval_note", ""))))]
    profile = load_profile(config.journal, base)
    rebuttal_rules = profile.get("rebuttal", {}) if isinstance(profile.get("rebuttal"), dict) else {}
    max_words = _positive_limit(rebuttal_rules.get("max_words", 0))
    max_words_per_response = _positive_limit(rebuttal_rules.get("max_words_per_response", 0))
    atom_word_counts = {atom["atom_id"]: _words(str(atom.get("response_text", atom.get("approval_note", "")))) for atom in atoms}
    total_words = sum(atom_word_counts.values())
    length_findings = []
    if max_words and total_words > max_words:
        length_findings.append({"scope": "total", "observed": total_words, "limit": max_words})
    if max_words_per_response:
        length_findings.extend({"scope": atom_id, "observed": count, "limit": max_words_per_response} for atom_id, count in atom_word_counts.items() if count > max_words_per_response)
    blocking = bool(open_atoms or trace_gaps or response_gaps or placeholder_gaps or unresolved_commitments or tone_findings or length_findings)
    report = {
        "version": 2, "generated_at": now_iso(), "ok": not blocking, "open_atoms": open_atoms,
        "traceability_gaps": trace_gaps, "response_gaps": response_gaps, "placeholder_gaps": placeholder_gaps,
        "unresolved_commitments": unresolved_commitments, "tone_findings": tone_findings,
        "length": {"total_words": total_words, "atom_word_counts": atom_word_counts, "max_words": max_words, "max_words_per_response": max_words_per_response, "findings": length_findings},
        "journal": config.journal,
        "warnings": ["Commitment and tone matches are deterministic lint findings requiring author interpretation.", "Evidence references are traceability records; this tool does not verify that response facts or results are true."],
    }
    write_json(config.workspace / "rebuttal_stress_test.json", report)
    write_text(config.workspace / "rebuttal_stress_test.md", _render_stress_test(report))
    return report


def finalize_rebuttal(base, approved: bool) -> dict:
    if not approved:
        raise ValueError("finalization requires explicit --approved author confirmation")
    config = load_config(base)
    stress = rebuttal_stress_test(base)
    if not stress["ok"]:
        raise ValueError("all rebuttal atoms require explicit author approval before finalization")
    result = {"version": 2, "finalized_at": now_iso(), "author_approved": True, "stress_test_sha256": file_sha256(config.workspace / "rebuttal_stress_test.json"), "limitations": ["Finalization records author approval and lint completion; it does not verify response facts, experiments, or mathematical claims."]}
    write_json(config.workspace / "rebuttal_final.json", result)
    return result


def approve_rebuttal_atom(base, atom_id: str, note: str, manuscript_locator: str, evidence: str, response_text: str = "") -> dict:
    if not manuscript_locator or not evidence:
        raise ValueError("approval requires manuscript locator and evidence reference")
    config = load_config(base)
    payload = read_json(config.workspace / "rebuttal_threads.json", {})
    for thread in payload.get("threads", {}).values():
        for atom in thread.get("atoms", []):
            if atom.get("atom_id") == atom_id:
                response = response_text.strip() or note.strip()
                if not response:
                    raise ValueError("approval requires response text or a substantive approval note")
                atom.update({"status": "approved", "author_approval": "approved", "approval_note": note, "response_text": response, "manuscript_locator": manuscript_locator, "evidence": evidence, "approved_at": now_iso()})
                write_json(config.workspace / "rebuttal_threads.json", payload)
                rebuttal_draft(base)
                write_json(config.workspace / "rebuttal_final.json", {"version": 2, "status": "invalidated_by_atom_update", "invalidated_at": now_iso()})
                return atom
    raise ValueError(f"unknown rebuttal atom {atom_id}")


def resubmit_rebuttal(base, source_journal: str, target_journal: str) -> dict:
    config = load_config(base)
    if source_journal == target_journal:
        raise ValueError("source and target journals must differ")
    path = config.workspace / "resubmissions" / f"{target_journal}.json"
    if path.exists():
        raise ValueError(f"resubmission record already exists for {target_journal}")
    source_profile = load_profile(source_journal, base)
    target_profile = load_profile(target_journal, base)
    target_validation = validate_rulepack(target_journal, base)
    if target_profile.get("rulepack", {}).get("format") == "directory-v1" and not target_validation["ok"]:
        raise ValueError("target journal rulepack is blocked; run revagent journal validate and obtain human confirmation")
    result = {"version": 1, "created_at": now_iso(), "from_journal": source_journal, "to_journal": target_journal, "status": "isolated", "source_profile": source_profile, "target_profile": target_profile, "target_validation": target_validation, "note": "Target rules and submission versions must remain separate from the source journal."}
    write_json(path, result)
    return result
