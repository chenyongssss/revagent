"""Local, author-gated rebuttal thread and draft scaffolding."""
from __future__ import annotations

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .profiles import load_profile, validate_rulepack


def parse_rebuttal(base) -> dict:
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    threads = {str(item["id"]): {"thread_id": f"RB-{item['id']}", "reviewer": item.get("reviewer", "reviewer"), "request": item.get("comment", ""), "atoms": [{"atom_id": f"RB-{item['id']}-1", "request": item.get("comment", ""), "status": "unplanned", "manuscript_evidence": [], "author_approval": "required"}]} for item in items}
    result = {"version": 1, "generated_at": now_iso(), "threads": threads}
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


def rebuttal_draft(base) -> str:
    config = load_config(base)
    result = read_json(config.workspace / "rebuttal_threads.json", {})
    lines = ["# PASTE_READY — Author Review Required", ""]
    for thread in result.get("threads", {}).values():
        for atom in thread["atoms"]:
            lines.extend([f"## {atom['atom_id']}", "", f"Reviewer request: {atom['request']}", "", "Author response: [AUTHOR MUST PROVIDE VERIFIED RESPONSE AND MANUSCRIPT LOCATION]", ""])
            atom["status"] = "drafted_unapproved"
    write_json(config.workspace / "rebuttal_threads.json", result)
    draft = "\n".join(lines)
    write_text(config.workspace / "rebuttal_draft.md", draft)
    return draft


def rebuttal_stress_test(base) -> dict:
    config = load_config(base)
    result = read_json(config.workspace / "rebuttal_threads.json", {})
    open_atoms = [atom["atom_id"] for thread in result.get("threads", {}).values() for atom in thread["atoms"] if atom.get("status") != "approved"]
    atoms = [atom for thread in result.get("threads", {}).values() for atom in thread["atoms"]]
    trace_gaps = [atom["atom_id"] for atom in atoms if atom.get("status") == "approved" and (not atom.get("manuscript_locator") or not atom.get("evidence"))]
    report = {"version": 1, "generated_at": now_iso(), "ok": not open_atoms and not trace_gaps, "open_atoms": open_atoms, "traceability_gaps": trace_gaps, "warnings": ["No fabricated results, facts, or commitments may be inserted by this tool.", "Tone, length, and commitment review remain author responsibilities; placeholders are deliberately preserved."]}
    write_json(config.workspace / "rebuttal_stress_test.json", report)
    return report


def finalize_rebuttal(base, approved: bool) -> dict:
    if not approved:
        raise ValueError("finalization requires explicit --approved author confirmation")
    config = load_config(base)
    stress = rebuttal_stress_test(base)
    if not stress["ok"]:
        raise ValueError("all rebuttal atoms require explicit author approval before finalization")
    result = {"version": 1, "finalized_at": now_iso(), "author_approved": True}
    write_json(config.workspace / "rebuttal_final.json", result)
    return result


def approve_rebuttal_atom(base, atom_id: str, note: str, manuscript_locator: str, evidence: str) -> dict:
    if not manuscript_locator or not evidence:
        raise ValueError("approval requires manuscript locator and evidence reference")
    config = load_config(base)
    payload = read_json(config.workspace / "rebuttal_threads.json", {})
    for thread in payload.get("threads", {}).values():
        for atom in thread.get("atoms", []):
            if atom.get("atom_id") == atom_id:
                atom.update({"status": "approved", "author_approval": "approved", "approval_note": note, "manuscript_locator": manuscript_locator, "evidence": evidence, "approved_at": now_iso()})
                write_json(config.workspace / "rebuttal_threads.json", payload)
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
