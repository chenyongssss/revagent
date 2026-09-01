"""Versioned local paper manifests for advisory pre-submission review."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ._utils import file_sha256, load_config, now_iso, read_json, write_json, write_text
from .latex import latex_index


PAPER_MANIFEST_VERSION = 1


def _bibliography_entries(config, index: dict[str, object]) -> dict[str, dict[str, object]]:
    entries: dict[str, dict[str, object]] = {}
    for declaration in index["bibliography"]:
        for target in str(declaration["target"]).split(","):
            path = config.tex_root / (target.strip() if target.strip().endswith(".bib") else f"{target.strip()}.bib")
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n@|\Z)", text, re.S):
                doi = re.search(r"\bdoi\s*=\s*[\{\"]?([^\}\",\s]+)", match.group(2), re.I)
                entries[match.group(1)] = {"path": str(path.relative_to(config.tex_root)), "doi": doi.group(1) if doi else ""}
    return entries


def _pdf_observations(pdf_path: Path) -> dict[str, object]:
    if not pdf_path.exists():
        return {"page_count": 0, "fonts": [], "blank_page_detection": "unavailable: no bound PDF"}
    data = pdf_path.read_bytes()
    fonts = sorted({item.decode("latin-1", errors="replace") for item in re.findall(rb"/BaseFont\s*/([^\s/]+)", data)})
    return {
        "page_count": len(re.findall(rb"/Type\s*/Page\b", data)),
        "fonts": fonts,
        "blank_page_detection": "not assessed: binary PDF heuristics cannot establish rendered blank pages",
    }


def paper_structural_checks(config, index: dict[str, object], pdf: dict[str, object], bibliography: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    cited = {key for citation in index["citations"] for key in citation["keys"]}
    missing_keys = sorted(cited - set(bibliography))
    if missing_keys:
        checks.append({"category": "bibliography_keys", "severity": "high", "message": f"{len(missing_keys)} cited bibliography key(s) have no local .bib entry: {', '.join(missing_keys)}.", "locations": []})
    unused = sorted(set(bibliography) - cited)
    if unused:
        checks.append({"category": "bibliography_unused", "severity": "low", "message": f"{len(unused)} local .bib entry/entries are not cited.", "locations": []})
    doi_to_keys: dict[str, list[str]] = {}
    for key, entry in bibliography.items():
        if entry["doi"]:
            doi_to_keys.setdefault(str(entry["doi"]).lower(), []).append(key)
    duplicate_dois = [keys for keys in doi_to_keys.values() if len(keys) > 1]
    if duplicate_dois:
        checks.append({"category": "doi_metadata", "severity": "medium", "message": f"{len(duplicate_dois)} DOI value(s) occur in multiple bibliography entries; verify metadata identity.", "locations": []})
    potential_symbols = index.get("potential_undefined_symbols", [])
    if potential_symbols:
        checks.append({"category": "undefined_symbol", "severity": "medium", "message": f"{len(potential_symbols)} uppercase control sequence(s) lack a local definition; verify package-provided or undefined symbols.", "locations": [entry["source_span"] for entry in potential_symbols]})
    environments = index["environments"]
    references = {ref["ref"] for ref in index["refs"]}
    for kind in ("figure", "table"):
        unused_envs = [env for env in environments if env["environment"] == kind and env["labels"] and not any(label in references for label in env["labels"])]
        if unused_envs:
            checks.append({"category": "figure_table_reference", "severity": "low", "message": f"{len(unused_envs)} {kind}(s) have labels but no indexed reference.", "locations": unused_envs})
    theorem_envs = [env for env in environments if env["theorem_kind"]]
    proofs = [env for env in environments if env["environment"] == "proof"]
    if theorem_envs and not proofs:
        checks.append({"category": "claim_evidence", "severity": "high", "message": "Indexed theorem-like claims have no indexed proof environment; author/domain-expert verification is required.", "locations": theorem_envs})
    if not pdf["exists"]:
        checks.append({"category": "pdf_binding", "severity": "medium", "message": "No same-stem compiled PDF is bound to this source snapshot.", "locations": []})
    return checks


def paper_input_fingerprint(base: Path) -> str:
    config = load_config(base)
    index = latex_index(config.tex_root, config.main_tex)
    digest = hashlib.sha256(json.dumps(index, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for relative in sorted(index["reachable_files"]):
        path = config.tex_root / str(relative)
        digest.update(str(relative).encode("utf-8"))
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
    pdf_path = (config.tex_root / config.main_tex).with_suffix(".pdf")
    digest.update(pdf_path.read_bytes() if pdf_path.exists() else b"<no-pdf>")
    return digest.hexdigest()


def build_paper_manifest(base: Path) -> dict[str, object]:
    """Index local source and PDF bindings without making semantic conclusions."""
    config = load_config(base)
    index = latex_index(config.tex_root, config.main_tex)
    source_files = []
    for relative in sorted(index["reachable_files"]):
        path = config.tex_root / str(relative)
        source_files.append({"path": str(relative), "sha256": file_sha256(path) if path.exists() else "", "exists": path.exists()})
    pdf_path = (config.tex_root / config.main_tex).with_suffix(".pdf")
    pdf = {
        "path": str(pdf_path),
        "exists": pdf_path.exists(),
        "sha256": file_sha256(pdf_path) if pdf_path.exists() else "",
        "observation": "A PDF binding is a rendered-file observation, not evidence of mathematical correctness or numerical validity.",
        **_pdf_observations(pdf_path),
    }
    bibliography = _bibliography_entries(config, index)
    manifest = {
        "version": PAPER_MANIFEST_VERSION,
        "generated_at": now_iso(),
        "status": "indexed",
        "input_fingerprint": paper_input_fingerprint(base),
        "source": {"tex_root": str(config.tex_root), "main_tex": config.main_tex, "root_file": index["root_file"], "files": source_files},
        "compiled_pdf": pdf,
        "index": {key: index[key] for key in ("sections", "environments", "citations", "bibliography", "dependency_map", "unresolved_refs", "potential_undefined_symbols", "warnings")},
        "claims": [{"claim_id": f"CLM-{number:03d}", "kind": env["theorem_kind"], "source_span": env["source_span"], "evidence_state": "proof_environment_indexed" if any(item["environment"] == "proof" for item in index["environments"]) else "no_indexed_proof"} for number, env in enumerate((env for env in index["environments"] if env["theorem_kind"]), 1)],
        "bibliography_entries": bibliography,
        "checks": paper_structural_checks(config, index, pdf, bibliography),
        "limitations": ["This manifest records local source and rendered-file observations only.", "It does not establish theorem correctness, experiment validity, or submission readiness."],
    }
    write_json(config.workspace / "paper_manifest.json", manifest)
    write_text(config.workspace / "paper_manifest.md", render_paper_manifest(manifest))
    return manifest


def load_paper_manifest(base: Path) -> dict:
    return read_json(load_config(base).workspace / "paper_manifest.json", {})


def paper_manifest_is_stale(base: Path, manifest: dict | None = None) -> bool:
    manifest = manifest if manifest is not None else load_paper_manifest(base)
    return not isinstance(manifest, dict) or manifest.get("status") == "not_ingested" or manifest.get("input_fingerprint") != paper_input_fingerprint(base)


def render_paper_manifest(manifest: dict) -> str:
    source = manifest.get("source", {})
    pdf = manifest.get("compiled_pdf", {})
    lines = ["# Paper Manifest", "", f"- Status: `{manifest.get('status', 'invalid')}`", f"- Main TeX: `{source.get('main_tex', '')}`", f"- Reachable source files: {len(source.get('files', []))}", f"- Compiled PDF bound: `{str(pdf.get('exists', False)).lower()}`", f"- PDF page observations: {pdf.get('page_count', 0)}", "", "## Structural Checks", ""]
    lines.extend(f"- [{row['severity']}] {row['message']}" for row in manifest.get("checks", []))
    if not manifest.get("checks"):
        lines.append("- No additional deterministic structural checks were triggered.")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in manifest.get("limitations", []))
    return "\n".join(lines) + "\n"
