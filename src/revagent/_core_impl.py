from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .profiles import available_profiles, load_profile

WORKSPACE = ".revagent"
CURRENT_SCHEMA_VERSION = "1"
PLANNING_STATUSES = {"triaged", "planned", "drafted", "evidence_ready", "approved", "incorporated", "closed"}
EXPERIMENT_CONTRACT_STATUSES = {"not_planned", "planned", "artifact_recorded", "incorporated"}
SCHEMA_FILES = [
    "revision.yaml",
    "journal_profile.json",
    "review_items.json",
    "latex_index.json",
    "item_plans.json",
    "item_plans.md",
    "proof_workflows.json",
    "proof_workflows.md",
    "experiment_manifests.json",
    "experiment_manifests.md",
    "revision_plan.md",
    "response_letter.md",
    "proof_audit.md",
    "experiment_plan.md",
    "manuscript.patch",
    "candidate_edits.json",
    "decision_log.md",
]


@dataclass
class Config:
    journal: str
    tex_root: Path
    main_tex: str
    workspace: Path
    compile_command: str = "latexmk -pdf"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: object) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(read_text(path))


def simple_yaml(data: dict[str, object]) -> str:
    lines = []
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def parse_simple_yaml(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw.startswith(" "):
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def find_main_tex(tex_root: Path) -> str:
    candidates = sorted(tex_root.glob("*.tex"))
    for path in candidates:
        text = read_text(path)
        if "\\documentclass" in text:
            return path.name
    if candidates:
        return candidates[0].name
    return "main.tex"


def workspace_path(base: Path) -> Path:
    return base / WORKSPACE


def load_config(base: Path) -> Config:
    ws = workspace_path(base)
    raw = parse_simple_yaml(read_text(ws / "revision.yaml"))
    tex_root = Path(raw.get("tex_root", "."))
    if not tex_root.is_absolute():
        tex_root = (base / tex_root).resolve()
    return Config(
        journal=raw["journal"],
        tex_root=tex_root,
        main_tex=raw.get("main_tex", "main.tex"),
        workspace=ws,
        compile_command=raw.get("compile_command", "latexmk -pdf"),
    )


def init_workspace(base: Path, journal: str, tex_root_arg: str, main_tex: str | None) -> Path:
    profile = load_profile(journal, base)
    tex_root = (base / tex_root_arg).resolve()
    main = main_tex or find_main_tex(tex_root)
    ws = workspace_path(base)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "artifacts").mkdir(exist_ok=True)
    (ws / "logs").mkdir(exist_ok=True)
    write_text(
        ws / "revision.yaml",
        simple_yaml(
            {
                "journal": profile["key"],
                "tex_root": str(tex_root),
                "main_tex": main,
                "workspace": WORKSPACE,
                "compile_command": "latexmk -pdf",
                "schema_version": CURRENT_SCHEMA_VERSION,
                "created_at": now_iso(),
            }
        ),
    )
    write_json(ws / "journal_profile.json", profile)
    write_json(ws / "review_items.json", [])
    write_json(ws / "latex_index.json", latex_index(tex_root, main))
    write_json(ws / "item_plans.json", {})
    write_text(ws / "item_plans.md", "# Item Plans\n\n")
    write_json(ws / "proof_workflows.json", {})
    write_text(ws / "proof_workflows.md", "# Proof Workflows\n\n")
    write_json(ws / "experiment_manifests.json", {})
    write_text(ws / "experiment_manifests.md", "# Experiment Manifests\n\n")
    write_text(ws / "response_letter.md", f"# {profile['response_heading']}\n\n")
    write_text(ws / "revision_plan.md", "# Revision Plan\n\nNo reviewer comments ingested yet.\n")
    write_text(ws / "proof_audit.md", "# Proof Audit\n\nNo proof-related review items ingested yet.\n")
    write_text(ws / "experiment_plan.md", "# Experiment Plan\n\nNo experiment-related review items ingested yet.\n")
    write_text(ws / "manuscript.patch", "# No manuscript patch notes drafted yet.\n")
    write_json(ws / "candidate_edits.json", [])
    write_text(ws / "decision_log.md", "# Decision Log\n\n")
    write_text(ws / "open_issues.md", "# Open Issues\n\nNo open issues recorded yet.\n")
    return ws


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


def normalize_tex_child(name: str) -> str:
    child = name.strip().strip("{}").strip()
    if not child.endswith(".tex"):
        child += ".tex"
    return child.replace("/", "\\")


def discover_tex_graph(tex_root: Path, main_tex: str | None = None) -> dict[str, object]:
    all_files = sorted(path for path in tex_root.rglob("*.tex") if WORKSPACE not in path.parts)
    root = tex_root / main_tex if main_tex else None
    if root is None or not root.exists():
        return {
            "root_file": main_tex or "",
            "files": [str(path.relative_to(tex_root)) for path in all_files],
            "includes": [],
            "reachable_files": [str(path.relative_to(tex_root)) for path in all_files],
            "warnings": ["main tex not found; fell back to scanning all .tex files"] if main_tex else [],
        }

    reachable: list[Path] = []
    includes: list[dict[str, str]] = []
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.exists():
            return
        seen.add(resolved)
        reachable.append(path)
        rel_from = str(path.relative_to(tex_root))
        text = cleaned_latex(read_text(path))
        for match in re.finditer(r"\\(input|include)\{([^}]+)\}", text):
            child_name = normalize_tex_child(match.group(2))
            child = (path.parent / child_name).resolve()
            if not child.exists():
                child = (tex_root / child_name).resolve()
            if child.exists() and tex_root.resolve() in child.parents:
                rel_to = str(child.relative_to(tex_root))
                includes.append({"from": rel_from, "to": rel_to, "command": match.group(1)})
                visit(child)
            else:
                includes.append({"from": rel_from, "to": child_name, "command": match.group(1), "missing": "true"})

    visit(root)
    return {
        "root_file": str(root.relative_to(tex_root)),
        "files": [str(path.relative_to(tex_root)) for path in all_files],
        "includes": includes,
        "reachable_files": [str(path.relative_to(tex_root)) for path in reachable],
        "warnings": [],
    }


def tex_files(tex_root: Path, main_tex: str | None = None) -> list[Path]:
    if main_tex:
        graph = discover_tex_graph(tex_root, main_tex)
        return [tex_root / rel for rel in graph["reachable_files"]]
    return sorted(path for path in tex_root.rglob("*.tex") if WORKSPACE not in path.parts)


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def strip_latex_comments(line: str) -> str:
    escaped = False
    chars = []
    for char in line:
        if char == "%" and not escaped:
            break
        chars.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    return "".join(chars)


def cleaned_latex(text: str) -> str:
    return "\n".join(strip_latex_comments(line) for line in text.splitlines())


def nearest_section(sections: list[dict[str, object]], rel: str, line: int) -> dict[str, object] | None:
    candidates = [section for section in sections if section["file"] == rel and int(section["line"]) <= line]
    if not candidates:
        return None
    return max(candidates, key=lambda section: int(section["line"]))


def context_hash_for_lines(lines: list[str], anchor_line: int, radius: int = 2) -> str:
    start = max(0, anchor_line - 1 - radius)
    end = min(len(lines), anchor_line + radius)
    return hashlib.sha256("\n".join(lines[start:end]).encode("utf-8")).hexdigest()[:16]


def latex_index(tex_root: Path, main_tex: str | None = None) -> dict[str, object]:
    graph = discover_tex_graph(tex_root, main_tex)
    sections = []
    labels = []
    refs = []
    citations = []
    envs = []
    bibliography = []
    dependency_map = []
    custom_environments: list[dict[str, object]] = []
    texts: dict[str, str] = {}
    default_theorem_like = {"theorem", "lemma", "proposition", "corollary", "definition", "remark", "assumption"}

    for path in tex_files(tex_root, main_tex):
        rel = str(path.relative_to(tex_root))
        text = cleaned_latex(read_text(path))
        texts[rel] = text
        for match in re.finditer(r"\\newtheorem\{([^}]+)\}(?:\[[^]]+\])?\{([^}]+)\}", text):
            custom_environments.append(
                {
                    "file": rel,
                    "line": line_for_offset(text, match.start()),
                    "environment": match.group(1),
                    "display_name": match.group(2),
                }
            )
        for match in re.finditer(r"\\(section|subsection|subsubsection)\*?\{([^{}]+)\}", text):
            sections.append({"file": rel, "line": line_for_offset(text, match.start()), "level": match.group(1), "title": match.group(2).strip()})

    env_names = sorted(default_theorem_like | {entry["environment"] for entry in custom_environments} | {"proof", "algorithm", "figure", "table"})
    env_pattern = re.compile(
        rf"\\begin\{{({'|'.join(re.escape(name) for name in env_names)})\}}(\[[^\]]*\])?(.*?)\\end\{{\1\}}",
        re.S,
    )
    previous_claim: dict[str, dict[str, object]] = {}
    for path in tex_files(tex_root, main_tex):
        rel = str(path.relative_to(tex_root))
        text = texts.get(rel, cleaned_latex(read_text(path)))
        for match in re.finditer(r"\\label\{([^}]+)\}", text):
            labels.append({"file": rel, "line": line_for_offset(text, match.start()), "label": match.group(1)})
        for match in re.finditer(r"\\(?:eqref|ref|autoref|cref|Cref)\{([^}]+)\}", text):
            for ref in [part.strip() for part in match.group(1).split(",") if part.strip()]:
                refs.append({"file": rel, "line": line_for_offset(text, match.start()), "ref": ref})
        for match in re.finditer(r"\\(?:cite|citet|citep|citealp)\{([^}]+)\}", text):
            citations.append({"file": rel, "line": line_for_offset(text, match.start()), "keys": [part.strip() for part in match.group(1).split(",")]})
        for match in re.finditer(r"\\(?:bibliography|addbibresource)\{([^}]+)\}", text):
            bibliography.append({"file": rel, "line": line_for_offset(text, match.start()), "target": match.group(1)})
        for match in env_pattern.finditer(text):
            body = match.group(3)
            line = line_for_offset(text, match.start())
            section = nearest_section(sections, rel, line)
            env_type = match.group(1)
            env = {
                "file": rel,
                "line": line,
                "end_line": line_for_offset(text, match.end()),
                "environment": env_type,
                "labels": re.findall(r"\\label\{([^}]+)\}", body),
                "refs": re.findall(r"\\(?:eqref|ref|autoref|cref|Cref)\{([^}]+)\}", body),
                "caption": "",
                "section_title": section["title"] if section else "",
                "section_level": section["level"] if section else "",
                "section_line": section["line"] if section else 0,
                "excerpt": first_sentence(re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", body)),
            }
            caption = re.search(r"\\caption(?:\[[^\]]*\])?\{([^{}]+)\}", body, re.S)
            if caption:
                env["caption"] = " ".join(caption.group(1).split())
            envs.append(env)
            if env_type in default_theorem_like or env_type == "proof":
                nearest_claim = previous_claim.get(rel)
                dependency_map.append(
                    {
                        "file": rel,
                        "line": line,
                        "environment": env_type,
                        "labels": env["labels"],
                        "refs": [ref for group in env["refs"] for ref in group.split(",")],
                        "section_title": env["section_title"],
                        "nearest_claim": nearest_claim if env_type == "proof" else None,
                    }
                )
            if env_type in default_theorem_like:
                previous_claim[rel] = {"environment": env_type, "line": line, "labels": env["labels"], "excerpt": env["excerpt"]}
    label_names = {entry["label"] for entry in labels}
    unresolved_refs = [entry for entry in refs if entry["ref"] not in label_names]
    return {
        "root_file": graph["root_file"],
        "files": graph["files"],
        "includes": graph["includes"],
        "reachable_files": graph["reachable_files"],
        "warnings": graph["warnings"],
        "custom_environments": custom_environments,
        "sections": sections,
        "labels": labels,
        "refs": refs,
        "unresolved_refs": unresolved_refs,
        "citations": citations,
        "bibliography": bibliography,
        "environments": envs,
        "dependency_map": dependency_map,
    }


def keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", text.lower())
    stop = {
        "reviewer",
        "referee",
        "editor",
        "paper",
        "manuscript",
        "authors",
        "please",
        "would",
        "could",
        "should",
        "there",
        "their",
        "these",
        "those",
        "about",
        "comment",
    }
    seen = []
    for word in words:
        if word not in stop and word not in seen:
            seen.append(word)
    return seen[:8]


def locator_mentions(comment: str) -> dict[str, set[str]]:
    lowered = comment.lower()
    result = {"environment": set(), "figure": set(), "table": set(), "section": set()}
    for name in ("theorem", "lemma", "proposition", "corollary", "assumption", "definition", "remark", "proof"):
        if name in lowered:
            result["environment"].add(name)
    if "figure" in lowered or "fig." in lowered:
        result["figure"].add("figure")
    if "table" in lowered or "tab." in lowered:
        result["table"].add("table")
    if "section" in lowered or "introduction" in lowered:
        result["section"].add("section")
    return result


def score_text(keys: list[str], text: str) -> tuple[int, list[str]]:
    lowered = text.lower()
    matched = [key for key in keys if key in lowered]
    return len(matched) * 10, matched[:5]


def location_hit(file: str, line: int, score: int, reason: str, context_type: str, context_title: str, matched: list[str]) -> dict[str, object]:
    return {
        "file": file,
        "line": line,
        "score": score,
        "reason": reason,
        "context_type": context_type,
        "context_title": context_title,
        "matched": matched,
    }


def locate_item(tex_root: Path, comment: str, index: dict[str, object] | None = None, main_tex: str | None = None) -> list[dict[str, object]]:
    index = index or latex_index(tex_root, main_tex)
    keys = keywords(comment)
    mentions = locator_mentions(comment)
    hits = []

    for env in index.get("environments", []):
        env_name = str(env["environment"])
        haystack = " ".join(
            [
                env_name,
                str(env.get("section_title", "")),
                str(env.get("caption", "")),
                " ".join(env.get("labels", [])),
                " ".join(env.get("refs", [])),
                str(env.get("excerpt", "")),
            ]
        )
        score, matched = score_text(keys, haystack)
        reasons = []
        if env_name in mentions["environment"] or (env_name == "proof" and "proof" in comment.lower()):
            score += 40
            reasons.append(f"mentioned {env_name}")
        if env_name == "figure" and mentions["figure"]:
            score += 40
            reasons.append("mentioned figure")
        if env_name == "table" and mentions["table"]:
            score += 40
            reasons.append("mentioned table")
        if env_name == "proof" and classify_item(comment) == "proof":
            score += 20
            reasons.append("proof-lane item")
        if score > 0:
            title = str(env.get("caption") or env.get("section_title") or env_name)
            hits.append(location_hit(str(env["file"]), int(env["line"]), score, "; ".join(reasons) or "environment keyword match", env_name, title, matched))

    for section in index.get("sections", []):
        score, matched = score_text(keys, str(section.get("title", "")))
        if mentions["section"]:
            score += 10
        if score > 0:
            hits.append(location_hit(str(section["file"]), int(section["line"]), score, "section title match", "section", str(section["title"]), matched))

    for label in index.get("labels", []):
        score, matched = score_text(keys, str(label.get("label", "")))
        if score > 0:
            hits.append(location_hit(str(label["file"]), int(label["line"]), score + 10, "label match", "label", str(label["label"]), matched))

    for path in tex_files(tex_root, main_tex):
        rel = str(path.relative_to(tex_root))
        for number, line in enumerate(read_text(path).splitlines(), start=1):
            score, matched = score_text(keys, line)
            if matched:
                section = nearest_section(index.get("sections", []), rel, number)
                hits.append(
                    location_hit(
                        rel,
                        number,
                        score,
                        "line keyword match",
                        "line",
                        str(section["title"]) if section else "",
                        matched,
                    )
                )
    hits.sort(key=lambda hit: int(hit["score"]), reverse=True)
    unique = []
    seen: set[tuple[str, int, str]] = set()
    for hit in hits:
        key = (str(hit["file"]), int(hit["line"]), str(hit["context_type"]))
        if key not in seen:
            seen.add(key)
            unique.append(hit)
        if len(unique) >= 5:
            break
    return unique


def update_locations(config: Config, items: list[dict]) -> None:
    index = latex_index(config.tex_root, config.main_tex)
    for item in items:
        item["tex_locations"] = locate_item(config.tex_root, item["comment"], index=index, main_tex=config.main_tex)


def bullet_lines(items: Iterable[dict]) -> str:
    lines = []
    for item in items:
        loc = item["tex_locations"][0] if item["tex_locations"] else None
        where = f"{loc['file']}:{loc['line']} score={loc.get('score', '?')}" if loc else "location not found"
        lines.append(f"- `{item['id']}` [{item['kind']}, {item['risk']} risk] {where}: {first_sentence(item['comment'])}")
    return "\n".join(lines) if lines else "- None.\n"


def first_sentence(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 180:
        return compact
    return compact[:177].rstrip() + "..."


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


def detect_experiment_assets(tex_root: Path) -> list[dict[str, str]]:
    roots = [tex_root / name for name in ("scripts", "experiments", "notebooks", "results")]
    assets = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                assets.append({"kind": root.name, "path": str(path.relative_to(tex_root))})
                if len(assets) >= 40:
                    return assets
    return assets


def render_experiment_plan(items: list[dict], tex_root: Path) -> str:
    experiment_items = [item for item in items if item["kind"] == "experiment"]
    assets = detect_experiment_assets(tex_root)
    lines = ["# Experiment Plan", ""]
    lines.extend(["## Detected Assets", ""])
    if assets:
        lines.extend(f"- `{asset['path']}` ({asset['kind']})" for asset in assets)
    else:
        lines.append("- No scripts, experiments, notebooks, or results directories detected.")
    lines.append("")
    if not experiment_items:
        lines.append("No experiment-related review items were detected.")
        return "\n".join(lines) + "\n"
    for item in experiment_items:
        lane = item.get("experiment_lane") or experiment_lane_template(item["comment"])
        lines.extend(
            [
                f"## {item['id']}",
                "",
                f"Reviewer concern: {first_sentence(item['comment'])}",
                "",
                "Executable plan fields:",
                f"- Command: {lane.get('command') or 'TBD'}",
                f"- Parameters: {json.dumps(lane.get('parameters', {}), ensure_ascii=False)}",
                f"- Seed: {lane.get('seed') or 'TBD'}",
                f"- Expected artifacts: {', '.join(lane.get('expected_artifacts', [])) or 'TBD'}",
                f"- Paper figure/table locations: {', '.join(lane.get('paper_locations', [])) or 'TBD'}",
                "- Result backfill fields: observed_result, figure_or_table_update, response_text",
                "",
                "Execution boundary:",
                "- Do not run experiments from this plan until the author approves the command and environment.",
                "- Fill conclusions only from observed results, never from reviewer expectations.",
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


def schema_markdown() -> str:
    return "\n".join(
        [
            "# RevAgent Workspace Schema",
            "",
            "Schema version: 1",
            "",
            "## Core Files",
            "",
            "- `revision.yaml`: journal, TeX root, main TeX file, compile command, schema version.",
            "- `review_items.json`: reviewer items with lane, risk, severity, source, reviewer, locations, and lane payloads.",
            "- `latex_index.json`: reachable files, includes, sections, labels, refs, environments, and dependency map.",
            "- `item_plans.json`: structured per-item planning records keyed by review item id.",
            "- `item_plans.md`: reviewable markdown rendering of per-item plans.",
            "- `proof_workflows.json`: structured proof workflow records keyed by proof review item id.",
            "- `proof_workflows.md`: reviewable proof workflow status, snapshots, obligations, and approval gates.",
            "- `experiment_manifests.json`: experiment reproducibility contracts keyed by experiment review item id.",
            "- `experiment_manifests.md`: reviewable experiment command, artifact, hash, and backfill contract report.",
            "- `candidate_edits.json`: proposed/edited/approved/rejected/blocked/applied manuscript edits with safe patch operations.",
            "- `decision_log.md`: append-only rationale log for item reasoning and author decisions.",
            "- `experiment_runs.jsonl`: append-only experiment result provenance records.",
            "",
            "## Review Item Fields",
            "",
            "`id`, `kind`, `lane`, `severity`, `risk`, `status`, `planning_status`, `comment`, `source`, `reviewer`, `requires_author_input`, `evidence_required`, `required_evidence`, `blocking_questions`, `completion_criteria`, `revision_plan`, `tex_locations`, `proof_lane`, `experiment_lane`, `response_draft`.",
            "",
            "## Planning Status",
            "",
            "`triaged -> planned -> drafted -> evidence_ready -> approved -> incorporated -> closed`, with `reopen-item` returning closed items to `planned`.",
            "",
            "## Candidate Status",
            "",
            "`proposed -> edited -> approved -> applied`, with `rejected` and `blocked` terminal or recovery states. Supported operations: `insert_after_line`, `replace_block`, `insert_before_environment`, `insert_after_environment`, `update_caption`.",
            "",
        ]
    )


def append_decision_log(config: Config, title: str, lines: list[str]) -> None:
    path = config.workspace / "decision_log.md"
    existing = read_text(path) if path.exists() else "# Decision Log\n\n"
    entry = [f"## {title}", "", f"- Timestamp: {now_iso()}"] + lines + [""]
    write_text(path, existing.rstrip() + "\n\n" + "\n".join(entry))


def load_items(config: Config) -> list[dict]:
    return read_json(config.workspace / "review_items.json", [])


def write_items(config: Config, items: list[dict]) -> None:
    write_json(config.workspace / "review_items.json", items)


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


def migrate_workspace(base: Path, dry_run: bool = True) -> dict[str, object]:
    config = load_config(base)
    actions: list[str] = []
    changed = False

    revision_path = config.workspace / "revision.yaml"
    raw_config = parse_simple_yaml(read_text(revision_path))
    if raw_config.get("schema_version") != CURRENT_SCHEMA_VERSION:
        actions.append(f"set revision.yaml schema_version to {CURRENT_SCHEMA_VERSION}")
        if not dry_run:
            raw_config["schema_version"] = CURRENT_SCHEMA_VERSION
            write_text(revision_path, simple_yaml(raw_config))
            changed = True

    default_files = {
        "candidate_edits.json": [],
        "item_plans.json": {},
        "item_plans.md": "# Item Plans\n\n",
        "proof_workflows.json": {},
        "proof_workflows.md": "# Proof Workflows\n\n",
        "experiment_manifests.json": {},
        "experiment_manifests.md": "# Experiment Manifests\n\n",
        "decision_log.md": "# Decision Log\n\n",
        "latex_index.json": latex_index(config.tex_root, config.main_tex),
        "proof_audit.md": "# Proof Audit\n\n",
        "experiment_plan.md": "# Experiment Plan\n\n",
        "manuscript.patch": "# No manuscript patch notes drafted yet.\n",
    }
    for name, default_value in default_files.items():
        target = config.workspace / name
        if not target.exists():
            actions.append(f"create missing {name}")
            if not dry_run:
                if name.endswith(".json"):
                    write_json(target, default_value)
                else:
                    write_text(target, str(default_value))
                changed = True

    items = load_items(config)
    item_changed = False
    for index, item in enumerate(items, start=1):
        defaults = default_item_fields(item, index, source=raw_config.get("comments_path", ""))
        for key, value in defaults.items():
            if key not in item:
                actions.append(f"add review item field {item.get('id', index)}.{key}")
                if not dry_run:
                    item[key] = value
                    item_changed = True
        if item.get("kind") == "proof":
            lane = item.get("proof_lane") or proof_lane_template(item.get("comment", ""))
            for key, value in proof_lane_template(item.get("comment", "")).items():
                if key not in lane:
                    actions.append(f"add proof lane field {item.get('id', index)}.{key}")
                    if not dry_run:
                        lane[key] = value
                        item_changed = True
            if not dry_run:
                item["proof_lane"] = lane
        if item.get("kind") == "experiment":
            lane = item.get("experiment_lane") or experiment_lane_template(item.get("comment", ""))
            for key, value in experiment_lane_template(item.get("comment", "")).items():
                if key not in lane:
                    actions.append(f"add experiment lane field {item.get('id', index)}.{key}")
                    if not dry_run:
                        lane[key] = value
                        item_changed = True
            if not dry_run:
                item["experiment_lane"] = lane
    if item_changed:
        write_items(config, items)
        changed = True

    manifests = load_experiment_manifests(config)
    manifest_changed = False
    for item in items:
        if item.get("kind") != "experiment":
            continue
        lane = item.get("experiment_lane") or {}
        if lane.get("recorded_results") and item.get("id") not in manifests:
            actions.append(f"migrate experiment manifest for {item.get('id')}")
            if not dry_run:
                manifest = build_experiment_manifest(config, item)
                manifests[item["id"]] = manifest
                sync_experiment_lane_from_manifest(item, manifest)
                manifest_changed = True
                item_changed = True
    if manifest_changed:
        write_items(config, items)
        write_experiment_manifests(config, manifests)
        changed = True

    candidates = load_candidates(config)
    candidate_changed = False
    for candidate in candidates:
        target_file = candidate.get("target_file", config.main_tex)
        anchor_line = int(candidate.get("anchor_line", 1))
        item = find_item(items, candidate.get("item_id", ""))
        loc = ((item or {}).get("tex_locations") or [{}])[0]
        patch = candidate_patch_metadata(config, item or {"kind": candidate.get("kind", "manuscript")}, target_file, anchor_line, loc)
        defaults = {
            "operation": "insert_after_line",
            "anchor_context_hash": anchor_context_hash_for(config, candidate.get("target_file", config.main_tex), int(candidate.get("anchor_line", 1))),
            "location_score": candidate.get("location_score", 0),
            "location_reason": candidate.get("location_reason", "migrated candidate"),
            "target_context": candidate.get("target_context", {"type": "unknown", "title": ""}),
            "proof_workflow_id": candidate.get("item_id", "") if candidate.get("kind") == "proof" else "",
            "proof_gate_status": "required" if candidate.get("kind") == "proof" else "",
            "target_span": patch["target_span"],
            "environment_id": patch["environment_id"],
            "original_content_hash": patch["original_content_hash"],
            "conflict_reason": "",
            "backup_dir": "",
        }
        for key, value in defaults.items():
            if key not in candidate:
                actions.append(f"add candidate field {candidate.get('id', 'unknown')}.{key}")
                if not dry_run:
                    candidate[key] = value
                    candidate_changed = True
    if candidate_changed:
        write_candidates(config, candidates)
        changed = True

    return {"dry_run": dry_run, "actions": actions, "changed": changed}


def render_migration_report(result: dict[str, object]) -> str:
    lines = ["# Migration Report", "", f"Dry run: {str(result['dry_run']).lower()}", ""]
    actions = result.get("actions", [])
    if actions:
        lines.append("Actions:")
        lines.extend(f"- {action}" for action in actions)
    else:
        lines.append("No migration actions required.")
    return "\n".join(lines) + "\n"


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
    return {
        "claim": claim_env or {},
        "proof": proof_env or {},
        "dependency_refs": sorted(set(refs)),
        "assumption_refs": sorted(ref for ref in set(refs) if ref.startswith("ass:") or "assumption" in ref.lower()),
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
        "assumption_refs": context["assumption_refs"],
        "dependency_refs": context["dependency_refs"],
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


def experiment_plan_for_item(base: Path, item_id: str | None = None) -> str:
    config = load_config(base)
    items = load_items(config)
    experiment_items = [item for item in items if item.get("kind") == "experiment"]
    if item_id:
        experiment_items = [item for item in experiment_items if item.get("id") == item_id]
        if not experiment_items:
            raise ValueError(f"unknown experiment item {item_id}")
    assets = detect_experiment_assets(config.tex_root)
    lines = ["# Experiment Command Plan", "", "## Detected Assets", ""]
    lines.extend(f"- `{asset['path']}` ({asset['kind']})" for asset in assets) if assets else lines.append("- None detected.")
    for item in experiment_items:
        lane = item.get("experiment_lane") or experiment_lane_template(item["comment"])
        lines.extend(
            [
                "",
                f"## {item['id']}",
                "",
                f"- Reviewer concern: {first_sentence(item['comment'])}",
                f"- Command: {lane.get('command') or 'TBD'}",
                f"- CWD: {lane.get('cwd') or str(config.tex_root)}",
                f"- Parameters: {json.dumps(lane.get('parameters', {}), ensure_ascii=False)}",
                f"- Seed: {lane.get('seed') or 'TBD'}",
                f"- Expected artifacts: {', '.join(lane.get('expected_artifacts', [])) or 'TBD'}",
                f"- Observed artifacts: {', '.join(lane.get('observed_artifacts', [])) or 'none recorded'}",
                f"- Result status: {lane.get('result_status', 'not_recorded')}",
                "",
                "Execution boundary: this command plan is not executed by RevAgent.",
            ]
        )
    append_decision_log(config, "Experiment plan generated", [f"- Items: {', '.join(item['id'] for item in experiment_items) or 'none'}"])
    return "\n".join(lines) + "\n"


def load_experiment_manifests(config: Config) -> dict[str, dict]:
    return read_json(config.workspace / "experiment_manifests.json", {})


def write_experiment_manifests(config: Config, manifests: dict[str, dict]) -> None:
    write_json(config.workspace / "experiment_manifests.json", manifests)
    write_text(config.workspace / "experiment_manifests.md", render_experiment_manifests(manifests))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_experiment_manifest(config: Config, item: dict) -> dict[str, object]:
    lane = item.get("experiment_lane") or experiment_lane_template(item.get("comment", ""))
    manifest_id = lane.get("manifest_id") or item["id"]
    artifacts = []
    artifact_hashes = dict(lane.get("artifact_hashes", {}))
    for record in lane.get("recorded_results", []):
        artifact = str(record.get("artifact", ""))
        artifact_path = (config.tex_root / artifact).resolve()
        artifact_hash = file_sha256(artifact_path) if artifact and artifact_path.exists() else artifact_hashes.get(artifact, "")
        if artifact:
            artifact_hashes[artifact] = artifact_hash
            artifacts.append(
                {
                    "path": artifact,
                    "kind": record.get("kind", "data"),
                    "note": record.get("note", ""),
                    "sha256": artifact_hash,
                    "recorded_at": record.get("recorded_at", ""),
                }
            )
    status = lane.get("contract_status") or "not_planned"
    if lane.get("backfill_targets"):
        status = "incorporated"
    elif artifacts or lane.get("result_status") == "recorded":
        status = "artifact_recorded"
    elif status == "not_planned":
        status = "planned"
    return {
        "id": manifest_id,
        "item_id": item["id"],
        "status": status,
        "command_template": lane.get("command_template") or lane.get("command", ""),
        "cwd": lane.get("cwd") or str(config.tex_root),
        "parameters": lane.get("parameters", {}),
        "seed": lane.get("seed", ""),
        "expected_artifacts": lane.get("expected_artifacts", []),
        "artifacts": artifacts,
        "artifact_hashes": artifact_hashes,
        "backfill_targets": lane.get("backfill_targets", []),
        "reviewer_request": lane.get("reviewer_request") or first_sentence(item.get("comment", "")),
        "updated_at": now_iso(),
    }


def sync_experiment_lane_from_manifest(item: dict, manifest: dict[str, object]) -> None:
    lane = item.get("experiment_lane") or experiment_lane_template(item.get("comment", ""))
    lane["manifest_id"] = manifest["id"]
    lane["command_template"] = manifest.get("command_template", "")
    lane["command"] = lane.get("command") or manifest.get("command_template", "")
    lane["cwd"] = manifest.get("cwd", lane.get("cwd", ""))
    lane["parameters"] = manifest.get("parameters", {})
    lane["seed"] = manifest.get("seed", "")
    lane["expected_artifacts"] = manifest.get("expected_artifacts", [])
    lane["artifact_hashes"] = manifest.get("artifact_hashes", {})
    lane["backfill_targets"] = manifest.get("backfill_targets", [])
    lane["contract_status"] = manifest.get("status", "planned")
    if manifest.get("artifacts"):
        lane["result_status"] = "recorded"
        lane["observed_artifacts"] = [artifact["path"] for artifact in manifest.get("artifacts", [])]
        lane["recorded_results"] = [
            {
                "item_id": item["id"],
                "artifact": artifact["path"],
                "kind": artifact.get("kind", "data"),
                "note": artifact.get("note", ""),
                "status": "recorded",
                "recorded_at": artifact.get("recorded_at", ""),
            }
            for artifact in manifest.get("artifacts", [])
        ]
    item["experiment_lane"] = lane


def render_experiment_manifest(manifest: dict[str, object]) -> str:
    lines = [
        f"# Experiment Manifest {manifest['item_id']}",
        "",
        f"- Status: {manifest.get('status')}",
        f"- Command: {manifest.get('command_template') or 'TBD'}",
        f"- CWD: {manifest.get('cwd') or 'TBD'}",
        f"- Seed: {manifest.get('seed') or 'TBD'}",
        f"- Parameters: {json.dumps(manifest.get('parameters', {}), ensure_ascii=False)}",
        f"- Expected artifacts: {', '.join(manifest.get('expected_artifacts', [])) or 'TBD'}",
        "",
        "## Artifacts",
        "",
    ]
    artifacts = manifest.get("artifacts", [])
    lines.extend(f"- `{artifact['path']}` ({artifact.get('kind', 'data')}) sha256={artifact.get('sha256') or 'missing'}" for artifact in artifacts) if artifacts else lines.append("- None.")
    lines.extend(["", "## Backfill Targets", ""])
    backfills = manifest.get("backfill_targets", [])
    lines.extend(f"- `{target['target']}` {target['field']}: {target['text']}" for target in backfills) if backfills else lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


def render_experiment_manifests(manifests: dict[str, dict]) -> str:
    if not manifests:
        return "# Experiment Manifests\n\nNo experiment manifests generated yet.\n"
    return "# Experiment Manifests\n\n" + "\n".join(render_experiment_manifest(manifests[key]).strip() for key in sorted(manifests)) + "\n"


def experiment_contract(base: Path, item_id: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    manifest = build_experiment_manifest(config, item)
    sync_experiment_lane_from_manifest(item, manifest)
    write_items(config, items)
    manifests = load_experiment_manifests(config)
    manifests[item_id] = manifest
    write_experiment_manifests(config, manifests)
    append_decision_log(config, f"Experiment contract planned for {item_id}", [f"- Status: {manifest['status']}"])
    return manifest


def experiment_artifact(base: Path, item_id: str, artifact_path: str, kind: str, note: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    path = (config.tex_root / artifact_path).resolve()
    if not path.exists():
        raise ValueError(f"experiment artifact not found: {artifact_path}")
    manifests = load_experiment_manifests(config)
    manifest = manifests.get(item_id) or build_experiment_manifest(config, item)
    artifact_hash = file_sha256(path)
    artifact = {
        "path": artifact_path,
        "kind": kind,
        "note": note,
        "sha256": artifact_hash,
        "recorded_at": now_iso(),
    }
    manifest.setdefault("artifacts", [])
    manifest["artifacts"] = [entry for entry in manifest["artifacts"] if entry.get("path") != artifact_path] + [artifact]
    manifest.setdefault("artifact_hashes", {})[artifact_path] = artifact_hash
    manifest["status"] = "artifact_recorded"
    manifest["updated_at"] = now_iso()
    manifests[item_id] = manifest
    sync_experiment_lane_from_manifest(item, manifest)
    if item.get("planning_status") not in {"incorporated", "closed"}:
        item["planning_status"] = "evidence_ready"
    write_items(config, items)
    write_experiment_manifests(config, manifests)
    log_path = config.workspace / "experiment_runs.jsonl"
    record = {"item_id": item_id, "artifact": artifact_path, "kind": kind, "note": note, "sha256": artifact_hash, "status": "recorded", "recorded_at": artifact["recorded_at"]}
    write_text(log_path, (read_text(log_path) if log_path.exists() else "") + json.dumps(record, ensure_ascii=False) + "\n")
    append_decision_log(config, f"Experiment artifact recorded for {item_id}", [f"- Artifact: {artifact_path}", f"- SHA256: {artifact_hash}"])
    return artifact


def experiment_incorporate(base: Path, item_id: str, target: str, field: str, text_file: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    manifests = load_experiment_manifests(config)
    manifest = manifests.get(item_id) or build_experiment_manifest(config, item)
    text = read_text((base / text_file).resolve()).rstrip()
    backfill = {"target": target, "field": field, "text": text, "recorded_at": now_iso()}
    manifest.setdefault("backfill_targets", []).append(backfill)
    manifest["status"] = "incorporated"
    manifest["updated_at"] = now_iso()
    manifests[item_id] = manifest
    sync_experiment_lane_from_manifest(item, manifest)
    item["planning_status"] = "incorporated"
    write_items(config, items)
    write_experiment_manifests(config, manifests)
    append_decision_log(config, f"Experiment backfill incorporated for {item_id}", [f"- Target: {target}", f"- Field: {field}"])
    return backfill


def record_experiment_result(base: Path, item_id: str, artifact: str, note: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    lane = item.get("experiment_lane") or experiment_lane_template(item["comment"])
    record = {
        "item_id": item_id,
        "artifact": artifact,
        "note": note,
        "status": "recorded",
        "recorded_at": now_iso(),
    }
    lane.setdefault("recorded_results", []).append(record)
    lane.setdefault("observed_artifacts", []).append(artifact)
    lane["result_status"] = "recorded"
    item["experiment_lane"] = lane
    if item.get("planning_status") not in {"incorporated", "closed"}:
        item["planning_status"] = "evidence_ready"
    manifest = build_experiment_manifest(config, item)
    manifests = load_experiment_manifests(config)
    manifests[item_id] = manifest
    sync_experiment_lane_from_manifest(item, manifest)
    write_items(config, items)
    write_experiment_manifests(config, manifests)
    log_path = config.workspace / "experiment_runs.jsonl"
    write_text(log_path, (read_text(log_path) if log_path.exists() else "") + json.dumps(record, ensure_ascii=False) + "\n")
    append_decision_log(config, f"Experiment result recorded for {item_id}", [f"- Artifact: {artifact}", f"- Note: {note}"])
    return record


def reasoning_for_item(base: Path, item_id: str) -> str:
    config = load_config(base)
    items = load_items(config)
    candidates = load_candidates(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    loc = (item.get("tex_locations") or [{}])[0]
    linked = [candidate for candidate in candidates if candidate.get("item_id") == item_id]
    plan = item.get("revision_plan") or {}
    blocked = []
    if item.get("kind") == "proof":
        blocked.append("author must verify nontrivial mathematical steps")
    if item.get("kind") == "experiment" and (item.get("experiment_lane") or {}).get("result_status") != "recorded":
        blocked.append("experiment result provenance is not recorded")
    lines = [
        f"# Revision Reasoning for {item_id}",
        "",
        f"- Reviewer intent: {first_sentence(item['comment'])}",
        f"- Lane: {item.get('lane', item.get('kind'))}",
        f"- Severity: {item.get('severity', item.get('risk'))}",
        f"- Manuscript context: {loc.get('context_type', 'unknown')} {loc.get('context_title', '')} at {loc.get('file', 'unknown')}:{loc.get('line', 'unknown')}",
        f"- Location rationale: {loc.get('reason', 'not located')} score={loc.get('score', 0)}",
        f"- Proposed action: {'review candidate edits and author confirmations' if linked else 'generate candidate edit'}",
        f"- Risk: {item.get('risk')}",
        f"- Planning status: {item.get('planning_status', item.get('status', 'triaged'))}",
        f"- Blocked questions: {', '.join(blocked) if blocked else 'none'}",
        "",
    ]
    if plan:
        lines.extend(
            [
                "## Planned Criteria",
                "",
                *[f"- {criterion}" for criterion in plan.get("completion_criteria", [])],
                "",
            ]
        )
    append_decision_log(config, f"Reasoning generated for {item_id}", [f"- Risk: {item.get('risk')}", f"- Blocked: {', '.join(blocked) if blocked else 'none'}"])
    return "\n".join(lines)


def load_item_plans(config: Config) -> dict[str, dict]:
    return read_json(config.workspace / "item_plans.json", {})


def write_item_plans(config: Config, plans: dict[str, dict]) -> None:
    write_json(config.workspace / "item_plans.json", plans)
    write_text(config.workspace / "item_plans.md", render_item_plans(plans))


def reviewer_intent_decomposition(item: dict) -> list[str]:
    comment = first_sentence(item.get("comment", ""))
    if item.get("kind") == "proof":
        return [
            f"Identify the mathematical claim behind: {comment}",
            "Check whether the theorem/lemma statement, assumptions, and proof steps align.",
            "Separate author-verified mathematics from RevAgent-generated placeholder text.",
        ]
    if item.get("kind") == "experiment":
        return [
            f"Identify the empirical evidence requested by: {comment}",
            "Specify reproducible command, parameters, seed, expected artifacts, and paper backfill target.",
            "Do not incorporate numerical conclusions until result provenance is recorded.",
        ]
    return [
        f"Clarify the manuscript concern behind: {comment}",
        "Locate the paragraph or section most likely to address the reviewer intent.",
        "Prepare a conservative manuscript edit and matching response-letter reference.",
    ]


def required_evidence_for_item(item: dict) -> list[str]:
    loc = (item.get("tex_locations") or [{}])[0]
    if item.get("kind") == "proof":
        lane = item.get("proof_lane") or {}
        return [
            f"affected claim: {lane.get('nearest_claim') or lane.get('affected_claim') or 'author must identify'}",
            f"assumptions/dependencies: {', '.join(lane.get('dependencies', [])) or 'author must verify'}",
            "author-verified proof obligation closure before approval",
        ]
    if item.get("kind") == "experiment":
        lane = item.get("experiment_lane") or {}
        return [
            f"command template: {lane.get('command') or 'TBD'}",
            f"seed/parameters: {lane.get('seed') or 'TBD'} / {json.dumps(lane.get('parameters', {}), ensure_ascii=False)}",
            f"recorded result artifact: {', '.join(lane.get('observed_artifacts', [])) or 'not recorded'}",
            f"paper backfill target: {', '.join(lane.get('paper_locations', [])) or loc.get('context_title') or 'TBD'}",
        ]
    return [
        f"manuscript target: {loc.get('file', 'unknown')}:{loc.get('line', 'unknown')}",
        "author-approved replacement or insertion text",
        "response-letter pointer to revised location",
    ]


def manuscript_edit_plan_for_item(item: dict, candidates: list[dict]) -> list[str]:
    linked = [candidate for candidate in candidates if candidate.get("item_id") == item.get("id")]
    loc = (item.get("tex_locations") or [{}])[0]
    if linked:
        return [
            f"review candidate {candidate['id']} ({candidate.get('operation', 'insert_after_line')}) at {candidate.get('target_file')}:{candidate.get('anchor_line')}"
            for candidate in linked
        ]
    return [
        f"generate candidate insertion near {loc.get('file', 'unknown')}:{loc.get('line', 'unknown')}",
        "keep generated text as a TODO/placeholder unless the author supplies final wording",
    ]


def dependency_plan_for_item(item: dict) -> list[str]:
    if item.get("kind") == "proof":
        lane = item.get("proof_lane") or {}
        deps = lane.get("dependencies", [])
        return [
            f"nearest claim: {lane.get('nearest_claim') or 'TBD'}",
            f"tracked labels/refs: {', '.join(deps) if deps else 'none yet'}",
            "verify no theorem statement or assumption change is incorporated without author approval",
        ]
    if item.get("kind") == "experiment":
        lane = item.get("experiment_lane") or {}
        return [
            f"expected artifacts: {', '.join(lane.get('expected_artifacts', [])) or 'TBD'}",
            f"result status: {lane.get('result_status', 'not_recorded')}",
            "map recorded artifacts back to response letter and figure/table placeholders",
        ]
    return ["no proof or experiment dependency lane required"]


def blocking_questions_for_item(item: dict) -> list[str]:
    if item.get("kind") == "proof":
        return [
            "Which exact theorem/lemma/proof obligation should change?",
            "Has the author verified every new nontrivial proof step?",
        ]
    if item.get("kind") == "experiment":
        lane = item.get("experiment_lane") or {}
        if lane.get("result_status") == "recorded":
            return []
        return [
            "Which command, seed, and parameter set should be treated as authoritative?",
            "Where is the recorded result artifact that supports the manuscript change?",
        ]
    return []


def completion_criteria_for_item(item: dict) -> list[str]:
    if item.get("kind") == "proof":
        return [
            "author approval recorded for proof lane",
            "candidate text contains no unverified mathematical claim",
            "response letter cites the revised proof location",
        ]
    if item.get("kind") == "experiment":
        return [
            "experiment result provenance recorded",
            "figure/table or text backfill is linked to the recorded artifact",
            "response letter states only observed results",
        ]
    return [
        "candidate edit reviewed and approved",
        "approved edit incorporated or explicitly rejected",
        "response letter points to the revised manuscript location",
    ]


def build_revision_plan(item: dict, candidates: list[dict]) -> dict[str, object]:
    plan = {
        "item_id": item["id"],
        "kind": item.get("kind"),
        "planning_status": "planned",
        "reviewer_intent_decomposition": reviewer_intent_decomposition(item),
        "required_evidence": required_evidence_for_item(item),
        "manuscript_edit_plan": manuscript_edit_plan_for_item(item, candidates),
        "dependency_plan": dependency_plan_for_item(item),
        "blocking_questions": blocking_questions_for_item(item),
        "completion_criteria": completion_criteria_for_item(item),
        "updated_at": now_iso(),
    }
    return plan


def render_item_plan(plan: dict[str, object]) -> str:
    lines = [f"# Item Plan {plan['item_id']}", "", f"- Kind: {plan.get('kind')}", f"- Status: {plan.get('planning_status')}", ""]
    sections = [
        ("Reviewer Intent Decomposition", "reviewer_intent_decomposition"),
        ("Required Evidence", "required_evidence"),
        ("Manuscript Edit Plan", "manuscript_edit_plan"),
        ("Proof/Experiment Dependency Plan", "dependency_plan"),
        ("Blocking Questions", "blocking_questions"),
        ("Completion Criteria", "completion_criteria"),
    ]
    for title, key in sections:
        values = plan.get(key) or []
        lines.extend([f"## {title}", ""])
        lines.extend(f"- {value}" for value in values) if values else lines.append("- None.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_item_plans(plans: dict[str, dict]) -> str:
    if not plans:
        return "# Item Plans\n\nNo item plans generated yet.\n"
    return "# Item Plans\n\n" + "\n".join(render_item_plan(plans[key]).strip() for key in sorted(plans)) + "\n"


def plan_item(base: Path, item_id: str, force: bool = False) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    if item.get("planning_status") in {"closed", "incorporated"} and item.get("revision_plan") and not force:
        return item["revision_plan"]
    candidates = load_candidates(config)
    plan = build_revision_plan(item, candidates)
    item["planning_status"] = "planned"
    item["revision_plan"] = plan
    item["required_evidence"] = plan["required_evidence"]
    item["blocking_questions"] = plan["blocking_questions"]
    item["completion_criteria"] = plan["completion_criteria"]
    write_items(config, items)
    plans = load_item_plans(config)
    plans[item_id] = plan
    write_item_plans(config, plans)
    append_decision_log(config, f"Item plan generated for {item_id}", [f"- Kind: {item.get('kind')}", f"- Blocking questions: {len(plan['blocking_questions'])}"])
    return plan


def plan_all_items(base: Path, force: bool = False) -> list[dict[str, object]]:
    config = load_config(base)
    items = load_items(config)
    return [plan_item(base, item["id"], force=force) for item in items]


def close_item(base: Path, item_id: str) -> dict:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    candidates = [candidate for candidate in load_candidates(config) if candidate.get("item_id") == item_id]
    has_unapplied_candidate = any(candidate.get("status") in {"proposed", "edited", "approved", "blocked"} for candidate in candidates)
    if item.get("planning_status") != "incorporated" and (item.get("blocking_questions") or has_unapplied_candidate):
        raise ValueError(f"item {item_id} is not ready to close")
    item["planning_status"] = "closed"
    write_items(config, items)
    append_decision_log(config, f"Item closed {item_id}", [f"- Previous status: {item.get('status', 'unknown')}"])
    return item


def reopen_item(base: Path, item_id: str) -> dict:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None:
        raise ValueError(f"unknown review item {item_id}")
    item["planning_status"] = "planned"
    write_items(config, items)
    append_decision_log(config, f"Item reopened {item_id}", ["- New planning status: planned"])
    return item


def create_plan(base: Path) -> None:
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


def render_response_letter(config: Config, items: list[dict], base: Path) -> str:
    profile = load_profile(config.journal, base)
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
                response_for(item),
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


def candidate_path(config: Config) -> Path:
    return config.workspace / "candidate_edits.json"


def load_candidates(config: Config) -> list[dict]:
    return read_json(candidate_path(config), [])


def write_candidates(config: Config, candidates: list[dict]) -> None:
    write_json(candidate_path(config), candidates)


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


def find_item(items: list[dict], item_id: str) -> dict | None:
    return next((item for item in items if item.get("id") == item_id), None)


def find_candidate(candidates: list[dict], candidate_id: str) -> dict | None:
    return next((candidate for candidate in candidates if candidate.get("id") == candidate_id), None)


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


def validate_workspace(base: Path, compile_check: bool = False) -> dict[str, object]:
    config = load_config(base)
    issues: list[str] = []
    warnings: list[str] = []
    for name in SCHEMA_FILES:
        if not (config.workspace / name).exists():
            issues.append(f"missing workspace file: {name}")
    for name in ("review_items.json", "latex_index.json", "journal_profile.json", "candidate_edits.json", "proof_workflows.json", "experiment_manifests.json"):
        try:
            read_json(config.workspace / name, {})
        except json.JSONDecodeError as exc:
            issues.append(f"invalid JSON in {name}: {exc}")
    if not (config.tex_root / config.main_tex).exists():
        issues.append(f"main TeX file not found: {config.tex_root / config.main_tex}")
    index = latex_index(config.tex_root, config.main_tex)
    for warning in index.get("warnings", []):
        warnings.append(str(warning))
    missing_includes = [entry for entry in index.get("includes", []) if entry.get("missing")]
    if missing_includes:
        warnings.append(f"{len(missing_includes)} included TeX files were not found")
    if index["unresolved_refs"]:
        warnings.append(f"{len(index['unresolved_refs'])} unresolved LaTeX references detected")
    raw_config = parse_simple_yaml(read_text(config.workspace / "revision.yaml"))
    if raw_config.get("schema_version") != CURRENT_SCHEMA_VERSION:
        warnings.append(f"workspace schema_version is missing or not {CURRENT_SCHEMA_VERSION}")
    migration = migrate_workspace(base, dry_run=True)
    for action in migration.get("actions", []):
        warnings.append(f"workspace migration available: {action}")
    items = load_items(config)
    candidates = load_candidates(config)
    proof_workflows = load_proof_workflows(config)
    experiment_manifests = load_experiment_manifests(config)
    required_item_fields = {
        "id",
        "kind",
        "lane",
        "severity",
        "risk",
        "status",
        "planning_status",
        "comment",
        "source",
        "reviewer",
        "revision_plan",
        "required_evidence",
        "blocking_questions",
        "completion_criteria",
    }
    for item in items:
        missing = sorted(required_item_fields - set(item))
        if missing:
            warnings.append(f"{item.get('id', 'unknown item')} missing fields: {', '.join(missing)}")
        planning_status = item.get("planning_status", "triaged")
        if planning_status not in PLANNING_STATUSES:
            issues.append(f"{item.get('id', 'unknown item')} has invalid planning_status {planning_status}")
        if planning_status in {"planned", "drafted", "evidence_ready", "approved"} and not item.get("revision_plan"):
            warnings.append(f"{item.get('id', 'unknown item')} has no revision_plan; run plan-item")
        if item.get("kind") == "proof":
            lane = item.get("proof_lane") or {}
            if lane.get("approval_status", "required") != "approved":
                warnings.append(f"{item['id']} proof lane requires author approval")
            if planning_status in {"planned", "drafted"} and lane.get("approval_status", "required") != "approved":
                warnings.append(f"{item['id']} planned proof item still has unresolved author verification")
            workflow = proof_workflows.get(item["id"])
            if not workflow:
                warnings.append(f"{item['id']} has no proof workflow; run proof-plan")
            else:
                if not workflow.get("statement_snapshot"):
                    warnings.append(f"{item['id']} proof workflow has no statement snapshot")
                if not workflow.get("proof_snapshot"):
                    warnings.append(f"{item['id']} proof workflow has no proof snapshot")
                open_obligations = [ob for ob in workflow.get("proof_obligations", []) if ob.get("status") != "closed"]
                if open_obligations:
                    warnings.append(f"{item['id']} proof workflow has {len(open_obligations)} open proof obligations")
        if item.get("kind") == "experiment":
            lane = item.get("experiment_lane") or {}
            if lane.get("result_status") != "recorded":
                warnings.append(f"{item['id']} experiment result provenance is not recorded")
            if planning_status in {"planned", "drafted"} and lane.get("result_status") != "recorded":
                warnings.append(f"{item['id']} planned experiment item lacks recorded result evidence")
            manifest = experiment_manifests.get(item["id"])
            if not manifest:
                warnings.append(f"{item['id']} has no experiment manifest; run experiment-contract")
            else:
                if manifest.get("status") not in EXPERIMENT_CONTRACT_STATUSES:
                    issues.append(f"{item['id']} has invalid experiment contract status {manifest.get('status')}")
                if not manifest.get("command_template"):
                    warnings.append(f"{item['id']} experiment manifest has no command template")
                if not manifest.get("seed"):
                    warnings.append(f"{item['id']} experiment manifest has no seed")
                if not manifest.get("expected_artifacts"):
                    warnings.append(f"{item['id']} experiment manifest has no expected artifacts")
                for artifact in manifest.get("artifacts", []):
                    artifact_path = config.tex_root / artifact.get("path", "")
                    if not artifact_path.exists():
                        warnings.append(f"{item['id']} experiment artifact is missing: {artifact.get('path')}")
                        continue
                    current_hash = file_sha256(artifact_path)
                    if artifact.get("sha256") and current_hash != artifact.get("sha256"):
                        warnings.append(f"{item['id']} experiment artifact hash changed: {artifact.get('path')}")
        if planning_status == "incorporated":
            approved_for_item = [candidate for candidate in candidates if candidate.get("item_id") == item.get("id") and candidate.get("status") == "approved"]
            if approved_for_item:
                warnings.append(f"{item['id']} is incorporated but still has unapplied approved candidates")
        if planning_status == "closed" and item.get("blocking_questions"):
            warnings.append(f"{item['id']} is closed with unresolved blocking questions")
    allowed_candidate_status = {"proposed", "edited", "approved", "applied", "rejected", "blocked"}
    allowed_candidate_operations = {"insert_after_line", "replace_block", "insert_before_environment", "insert_after_environment", "update_caption"}
    for candidate in candidates:
        if candidate.get("status") not in allowed_candidate_status:
            issues.append(f"{candidate.get('id', 'unknown candidate')} has invalid status {candidate.get('status')}")
        if candidate.get("operation", "insert_after_line") not in allowed_candidate_operations:
            issues.append(f"{candidate.get('id', 'unknown candidate')} has invalid operation {candidate.get('operation')}")
        if candidate.get("operation") != "insert_after_line" and not candidate.get("original_content_hash"):
            warnings.append(f"{candidate.get('id', 'unknown candidate')} has no original_content_hash for {candidate.get('operation')}")
        if candidate.get("kind") == "proof" and candidate.get("status") == "approved":
            item = find_item(items, candidate.get("item_id", ""))
            lane = (item or {}).get("proof_lane") or {}
            if lane.get("approval_status") != "approved":
                issues.append(f"{candidate.get('id')} is an approved proof candidate without proof workflow approval")
        if candidate.get("kind") == "experiment" and candidate.get("status") in {"proposed", "approved", "applied"}:
            manifest = experiment_manifests.get(candidate.get("item_id", ""))
            if manifest and manifest.get("artifacts") and not manifest.get("backfill_targets"):
                warnings.append(f"{candidate.get('id')} uses experiment results without a backfill target mapping")
        if candidate.get("status") == "approved":
            reason = verify_candidate_anchor(config, candidate) or verify_candidate_operation(config, candidate)
            if reason:
                warnings.append(f"{candidate.get('id')} would be blocked on apply: {reason}")
    if compile_check:
        exe = config.compile_command.split()[0]
        if shutil.which(exe) is None:
            warnings.append(f"compile check skipped because {exe!r} is not on PATH")
        else:
            result = subprocess.run(
                config.compile_command.split() + [config.main_tex],
                cwd=config.tex_root,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            write_text(config.workspace / "logs" / "latexmk.stdout.log", result.stdout)
            write_text(config.workspace / "logs" / "latexmk.stderr.log", result.stderr)
            if result.returncode != 0:
                issues.append(f"compile command failed with exit code {result.returncode}")
    return {"ok": not issues, "issues": issues, "warnings": warnings, "index": index}


def doctor(base: Path) -> dict[str, object]:
    checks = []
    checks.append({"name": "python", "ok": sys.version_info >= (3, 10), "detail": sys.version.split()[0]})
    checks.append({"name": "workspace", "ok": workspace_path(base).exists(), "detail": str(workspace_path(base))})
    checks.append({"name": "latexmk", "ok": shutil.which("latexmk") is not None, "detail": shutil.which("latexmk") or "not found"})
    checks.append({"name": "profiles", "ok": True, "detail": ", ".join(available_profiles(base))})
    if workspace_path(base).exists():
        config = load_config(base)
        checks.append({"name": "main_tex", "ok": (config.tex_root / config.main_tex).exists(), "detail": str(config.tex_root / config.main_tex)})
    return {"ok": all(check["ok"] for check in checks if check["name"] != "latexmk"), "checks": checks}


def status(base: Path) -> dict[str, object]:
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    candidates = load_candidates(config)
    counts = {
        "total": len(items),
        "proof": sum(1 for item in items if item.get("kind") == "proof"),
        "experiment": sum(1 for item in items if item.get("kind") == "experiment"),
        "manuscript": sum(1 for item in items if item.get("kind") == "manuscript"),
        "high_risk": sum(1 for item in items if item.get("risk") == "high"),
        "candidates": len(candidates),
        "approved_candidates": sum(1 for candidate in candidates if candidate.get("status") == "approved"),
        "applied_candidates": sum(1 for candidate in candidates if candidate.get("status") == "applied"),
    }
    for planning_status in sorted(PLANNING_STATUSES):
        counts[f"planning_{planning_status}"] = sum(1 for item in items if item.get("planning_status", "triaged") == planning_status)
    return {
        "workspace": str(config.workspace),
        "journal": config.journal,
        "tex_root": str(config.tex_root),
        "main_tex": config.main_tex,
        "counts": counts,
    }


def clean_workspace(base: Path) -> list[str]:
    config = load_config(base)
    removed = []
    for dirname in ("artifacts", "logs"):
        target = config.workspace / dirname
        if target.exists():
            shutil.rmtree(target)
            removed.append(str(target))
        target.mkdir(exist_ok=True)
    return removed


def export_artifacts(base: Path) -> Path:
    config = load_config(base)
    artifact_dir = config.workspace / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    exports = [
        "revision.yaml",
        "journal_profile.json",
        "review_items.json",
        "latex_index.json",
        "item_plans.json",
        "item_plans.md",
        "proof_workflows.json",
        "proof_workflows.md",
        "experiment_manifests.json",
        "experiment_manifests.md",
        "revision_plan.md",
        "response_letter.md",
        "manuscript.patch",
        "candidate_edits.json",
        "apply_log.jsonl",
        "decision_log.md",
        "experiment_runs.jsonl",
        "proof_audit.md",
        "experiment_plan.md",
        "open_issues.md",
    ]
    lines = ["# Revision Export", ""]
    for name in exports:
        source = config.workspace / name
        if source.exists():
            target = artifact_dir / name
            target.write_bytes(source.read_bytes())
            lines.append(f"- `{name}`")
    write_text(artifact_dir / "MANIFEST.md", "\n".join(lines) + "\n")
    return artifact_dir
