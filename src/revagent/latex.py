"""LaTeX graph, indexing, and reviewer-location public API."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ._models import Config, WORKSPACE
from ._utils import first_sentence, read_text
from .reviews import classify_item

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

__all__ = [
    "cleaned_latex",
    "context_hash_for_lines",
    "discover_tex_graph",
    "latex_index",
    "locate_item",
    "normalize_tex_child",
    "tex_files",
    "update_locations",
]
