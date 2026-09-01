"""Local, deterministic, advisory pre-submission review reports."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from ._utils import file_sha256, load_config, now_iso, read_json, write_json, write_text
from .latex import latex_index
from .paper_ingestion import build_paper_manifest
from .profiles import load_profile, validate_rulepack


def _finding(category: str, severity: str, message: str, locations: list[dict] | None = None) -> dict:
    return {
        "id": "", "category": category, "severity": severity, "message": message,
        "locations": locations or [], "status": "open", "advisory": True,
        "requires_author_review": severity in {"high", "critical"},
    }


def pre_submission_input_fingerprint(base: Path, journal: str | None = None) -> str:
    """Hash only the reachable manuscript source and effective local rulepack."""
    config = load_config(base)
    profile = load_profile(journal or config.journal, base)
    index = latex_index(config.tex_root, config.main_tex)
    digest = hashlib.sha256()
    digest.update(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    digest.update(b"\0")
    for relative_path in sorted(index["reachable_files"]):
        path = config.tex_root / str(relative_path)
        digest.update(str(relative_path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def pre_submission_review_is_stale(base: Path, report: dict | None = None) -> bool:
    report = report if report is not None else load_pre_submission_review(base)
    if not report or report.get("status") == "not_run":
        return False
    source = report.get("source", {})
    if not isinstance(source, dict):
        return True
    journal = str((report.get("journal") or {}).get("key", "")) or None
    return source.get("input_fingerprint") != pre_submission_input_fingerprint(base, journal)


def render_pre_submission_review(report: dict) -> str:
    journal = report["journal"]
    summary = report["summary"]
    source = report.get("source", {})
    lines = ["# Pre-submission Review", "", f"- Journal: {journal['display_name']} (rulepack v{journal.get('version', '1')})", f"- Status: `{summary['status']}`", f"- Journal-specific status: `{report.get('journal_specific_status', 'advisory')}`", f"- Paper snapshot: `{source.get('paper_input_fingerprint', '')}`", f"- Generated: {report['generated_at']}", "", "## Findings", ""]
    if not report["findings"]:
        lines.append("- No deterministic structural findings. Manual expert review is still required.")
    for row in report["findings"]:
        locations = ", ".join(f"{loc.get('file', '')}:{loc.get('line', '')}" for loc in row["locations"][:3])
        lines.append(f"- `{row['id']}` [{row['severity']}] {row['message']}{f' ({locations})' if locations else ''}")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {value}" for value in report["limitations"])
    for heading, key in (("Rubric Notes", "rubric_checks"), ("Submission Checklist", "submission_checks")):
        lines.extend(["", f"## {heading}", ""])
        values = report.get(key, [])
        lines.extend(f"- {value}" for value in values if isinstance(value, str))
        if not values:
            lines.append("- Not available: the selected rulepack is blocked or does not define these local advisory notes.")
    return "\n".join(lines) + "\n"


def build_pre_submission_review(base: Path, journal: str | None = None) -> dict:
    """Write a reproducible report; it never sends manuscript material remotely."""
    config = load_config(base)
    profile = load_profile(journal or config.journal, base)
    journal_validation = validate_rulepack(profile["key"], base)
    paper_manifest = build_paper_manifest(base)
    paper_manifest_path = config.workspace / "paper_manifest.json"
    index = latex_index(config.tex_root, config.main_tex)
    envs = index["environments"]
    findings: list[dict] = []
    directory_rulepack = (profile.get("rulepack") or {}).get("format") == "directory-v1" if isinstance(profile.get("rulepack"), dict) else False
    journal_specific_status = "ready" if journal_validation["ok"] else ("blocked" if directory_rulepack else "advisory")
    if journal_specific_status == "blocked":
        reasons = list(journal_validation["issues"]) + list(journal_validation["blocking"])
        findings.append(_finding("journal_rulepack", "critical", f"Journal-specific checks are blocked: {'; '.join(reasons)}"))
    for check in paper_manifest.get("checks", []):
        findings.append(_finding(str(check["category"]), str(check["severity"]), str(check["message"]), list(check.get("locations", []))))
    def component_checks(component: str) -> list[str]:
        value = profile.get(component, {})
        checks = value.get("checks", []) if isinstance(value, dict) else []
        return [str(check) for check in checks] if isinstance(checks, list) else []
    journal_rules_available = journal_specific_status != "blocked"
    rubric_checks = component_checks("rubric") if journal_rules_available else []
    submission_checks = component_checks("submission") if journal_rules_available else []
    if journal_rules_available:
        page_limit = str(profile.get("page_limit", ""))
        page_count = int(paper_manifest.get("compiled_pdf", {}).get("page_count", 0))
        if page_limit.isdigit() and page_count > int(page_limit):
            findings.append(_finding("page_limit", "high", f"Bound PDF has {page_count} observed page objects, exceeding profile page_limit {page_limit}."))
        required_attachments = profile.get("required_attachments", [])
        if isinstance(required_attachments, list):
            missing_attachments = [str(item) for item in required_attachments if not (config.tex_root / str(item)).is_file()]
            if missing_attachments:
                findings.append(_finding("attachments", "medium", f"Missing profile-declared attachment(s): {', '.join(missing_attachments)}."))
    if index["unresolved_refs"]:
        findings.append(_finding("cross_reference", "high", f"{len(index['unresolved_refs'])} unresolved cross-reference(s).", index["unresolved_refs"]))
    figures = [row for row in envs if row["environment"] == "figure"]
    tables = [row for row in envs if row["environment"] == "table"]
    missing_captions = [row for row in figures + tables if not row["caption"]]
    if missing_captions:
        findings.append(_finding("figure_table", "medium", f"{len(missing_captions)} figure/table environment(s) lack a caption.", missing_captions))
    theorem_envs = [row for row in envs if row["theorem_kind"]]
    proofs = [row for row in envs if row["environment"] == "proof"]
    if theorem_envs and not proofs:
        findings.append(_finding("theory", "high", "Theorem-like environments were found but no proof environment was indexed.", theorem_envs))
    if index["citations"] and not index["bibliography"]:
        findings.append(_finding("bibliography", "high", "Citation commands were found but no bibliography declaration was indexed."))
    if not index["citations"]:
        findings.append(_finding("bibliography", "medium", "No citation commands were indexed; confirm this is appropriate for the target venue."))
    titles = " ".join(str(row["title"]).lower() for row in index["sections"])
    for requirement in profile.get("required_checks", []) if journal_specific_status != "blocked" else []:
        if requirement == "contribution_statement" and not any(word in titles for word in ("introduction", "contribution", "novel")):
            findings.append(_finding("contribution", "medium", "No Introduction/Contribution section was detected; manually verify the decisive advance."))
        if requirement == "reproducibility" and not any(word in titles for word in ("experiment", "implementation", "reproduc", "numerical")):
            findings.append(_finding("reproducibility", "medium", "No experiment, implementation, or reproducibility section was detected."))
        if requirement == "figure_accessibility" and figures:
            findings.append(_finding("figure_accessibility", "low", "Target profile requires image accessibility review; this cannot be certified from LaTeX indexing."))
    for number, finding in enumerate(findings, 1):
        finding["id"] = f"PSR{number:03d}"
    status = "needs_author_review" if any(row["severity"] in {"high", "critical"} for row in findings) else "advisory_review_complete"
    report = {
        "version": 2, "generated_at": now_iso(), "journal": profile, "journal_validation": journal_validation, "journal_specific_status": journal_specific_status, "rubric_checks": rubric_checks, "submission_checks": submission_checks,
        "source": {"tex_root": str(config.tex_root), "main_tex": config.main_tex, "root_file": index["root_file"], "input_fingerprint": pre_submission_input_fingerprint(base, profile["key"]), "paper_input_fingerprint": paper_manifest["input_fingerprint"], "paper_manifest_sha256": file_sha256(paper_manifest_path)},
        "summary": {"status": status, "finding_counts": dict(sorted(Counter(row["severity"] for row in findings).items())), "sections": len(index["sections"]), "theorem_like_environments": len(theorem_envs), "proof_environments": len(proofs), "figures": len(figures), "tables": len(tables)},
        "findings": findings,
        "limitations": ["This is an advisory structural review, not a correctness proof, numerical validation, plagiarism determination, or editorial decision.", "No manuscript content was sent to a remote provider."],
    }
    write_json(config.workspace / "pre_submission_review.json", report)
    write_text(config.workspace / "pre_submission_review.md", render_pre_submission_review(report))
    return report


def load_pre_submission_review(base: Path) -> dict:
    return read_json(load_config(base).workspace / "pre_submission_review.json", {})


def pre_submission_review_summary(base: Path) -> dict:
    """Return a display-safe summary without treating the report as a submission decision."""
    try:
        report = load_pre_submission_review(base)
    except (OSError, json.JSONDecodeError):
        return {"status": "invalid", "generated_at": "", "finding_counts": {}}
    if not isinstance(report, dict) or report.get("status") == "not_run" or not report:
        return {"status": "not_run", "generated_at": "", "finding_counts": {}}
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        return {"status": "invalid", "generated_at": "", "finding_counts": {}}
    counts = summary.get("finding_counts", {})
    report_status = str(summary.get("status", "invalid"))
    return {
        "status": "stale" if pre_submission_review_is_stale(base, report) else report_status,
        "report_status": report_status,
        "generated_at": str(report.get("generated_at", "")),
        "finding_counts": counts if isinstance(counts, dict) else {},
    }
