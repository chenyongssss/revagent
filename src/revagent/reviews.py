"""Reviewer comment parsing, classification, and item workflow public API."""

from __future__ import annotations

import re
import subprocess
import zipfile
from xml.etree import ElementTree
from pathlib import Path
from typing import Iterable

from ._utils import file_sha256, first_sentence, load_config, load_items, now_iso, read_json, read_text, write_items, write_json, write_text
from .profiles import load_profile

_REVIEWER_MARKER = re.compile(r"^(?:#+\s*)?(reviewer|referee|editor)\s*([0-9A-Za-z-]*)\s*[:.]?\s*$", re.I)
_LIST_MARKER = re.compile(r"^(?:[-*]|\d+[.)]|\\item(?:\[[^]]+\])?)\s*(.*)$")
_DIRECT_COMMENT_SUFFIXES = {".tex", ".md", ".txt"}
_NORMALIZED_COMMENT_SUFFIXES = {".docx", ".pdf"}


def _docx_text(path: Path) -> str:
    """Extract paragraph text locally without loading macros or external resources."""
    try:
        with zipfile.ZipFile(path) as archive:
            document = archive.read("word/document.xml")
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"cannot read DOCX reviewer comments: {exc}") from exc
    root = ElementTree.fromstring(document)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n".join("".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip() for paragraph in root.iter(f"{namespace}p"))


def _pdf_text(path: Path) -> str:
    """Use the local Poppler extractor; PDF contents are never sent to a service."""
    try:
        result = subprocess.run(["pdftotext", "-layout", str(path), "-"], text=True, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot extract local PDF reviewer comments: {exc}") from exc
    if result.returncode != 0:
        raise ValueError(f"cannot extract local PDF reviewer comments: {result.stderr.strip() or 'pdftotext failed'}")
    if not result.stdout.strip():
        raise ValueError("cannot extract local PDF reviewer comments: no extractable text found")
    return result.stdout


def read_review_comments(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        return _docx_text(path)
    if suffix == ".pdf":
        return _pdf_text(path)
    return read_text(path)


def normalize_review_comments(base: Path, source_path: Path, workspace: Path) -> tuple[str, dict[str, object]]:
    """Return locally normalized comment text and record an auditable import."""
    suffix = source_path.suffix.casefold()
    if suffix not in _DIRECT_COMMENT_SUFFIXES | _NORMALIZED_COMMENT_SUFFIXES:
        raise ValueError("unsupported reviewer comment format; use .tex, .md, .txt, .docx, or a text-based .pdf")
    source_hash = file_sha256(source_path)
    source_relative = source_path.relative_to(base.resolve()).as_posix()
    if suffix in _DIRECT_COMMENT_SUFFIXES:
        normalized_relative = source_relative
        normalized_path = source_path
        conversion = "direct"
        text = read_text(source_path)
    else:
        text = read_review_comments(source_path)
        imports = workspace / "imports"
        imports.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_path.stem).strip("._") or "reviewer_comments"
        normalized_path = imports / f"{safe_stem}-{source_hash[:12]}.md"
        write_text(normalized_path, text)
        normalized_relative = normalized_path.relative_to(base.resolve()).as_posix()
        conversion = f"{suffix[1:]}_to_markdown"
    record = {
        "version": 1,
        "status": "imported",
        "source_path": source_relative,
        "source_hash": source_hash,
        "normalized_path": normalized_relative,
        "normalized_hash": file_sha256(normalized_path),
        "format": suffix[1:],
        "conversion": conversion,
        "imported_at": now_iso(),
    }
    write_json(workspace / "comment_import.json", record)
    return text, record


def parse_review_requests(text: str) -> list[dict[str, str]]:
    """Split each Markdown or LaTeX list request while retaining reviewer and line span."""
    requests: list[dict[str, str]] = []
    reviewer = "Unassigned reviewer"
    current: list[str] = []
    start_line = 0

    def flush(end_line: int) -> None:
        nonlocal current, start_line
        body = " ".join(part.strip() for part in current if part.strip()).strip()
        if len(body) > 8:
            requests.append({"comment": body, "reviewer": reviewer, "line_start": str(start_line), "line_end": str(end_line)})
        current, start_line = [], 0

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            flush(line_number - 1)
            continue
        if stripped in {r"\begin{description}", r"\end{description}", r"\begin{enumerate}", r"\end{enumerate}", r"\begin{itemize}", r"\end{itemize}"}:
            continue
        marker = _REVIEWER_MARKER.match(stripped)
        if marker:
            flush(line_number - 1)
            reviewer = f"{marker.group(1).title()} {marker.group(2)}".strip()
            continue
        item = _LIST_MARKER.match(stripped)
        if item:
            flush(line_number - 1)
            label = re.search(r"^\\item\[([^]]+)\]", stripped)
            if label and _REVIEWER_MARKER.match(label.group(1).strip()):
                reviewer = label.group(1).strip()
            current, start_line = [item.group(1).strip()], line_number
            continue
        if _REVIEWER_MARKER.match(stripped.rstrip(":")):
            flush(line_number - 1)
            marker = _REVIEWER_MARKER.match(stripped.rstrip(":"))
            assert marker is not None
            reviewer = f"{marker.group(1).title()} {marker.group(2)}".strip()
            continue
        if not current:
            current, start_line = [stripped.lstrip("#").strip()], line_number
        else:
            current.append(stripped)
    flush(len(text.splitlines()))
    return requests


def split_comments(text: str) -> list[str]:
    """Compatibility view of the typed request parser."""
    return [request["comment"] for request in parse_review_requests(text)]

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
    source_path = (base / comments_path).resolve()
    if base.resolve() not in source_path.parents or not source_path.is_file():
        raise ValueError("reviewer comments must be an existing file inside the local project")
    raw, comment_import = normalize_review_comments(base, source_path, config.workspace)
    chunks = parse_review_requests(raw)
    items = []
    for index, request in enumerate(chunks, start=1):
        chunk = request["comment"]
        kind = classify_item(chunk)
        items.append(
            {
                "id": f"R{index:03d}",
                "kind": kind,
                "lane": kind,
                "severity": risk_for(kind, chunk),
                "requires_author_input": kind in {"proof", "experiment"},
                "evidence_required": kind in {"proof", "experiment"},
                "source": str(comment_import["source_path"]),
                "source_locator": f"{comment_import['normalized_path']}:{request['line_start']}-{request['line_end']}",
                "normalized_source": str(comment_import["normalized_path"]),
                "source_hash": str(comment_import["source_hash"]),
                "normalized_hash": str(comment_import["normalized_hash"]),
                "reviewer": request["reviewer"] if request["reviewer"] != "Unassigned reviewer" else infer_reviewer(chunk, index),
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
        "comparators": [],
        "fairness_rules": [],
        "discretization": {"grid": "", "time_step": "", "error_metric": "", "stopping_criterion": ""},
        "repetitions": 0,
        "uncertainty_method": "",
        "hardware": "",
        "protocol_status": "incomplete",
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
