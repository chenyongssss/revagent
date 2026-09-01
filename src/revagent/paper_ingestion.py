"""Versioned local paper manifests for advisory pre-submission review."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
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


def _run_local_tool(command: list[str]) -> subprocess.CompletedProcess[str] | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        return subprocess.run(command, text=True, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _pdf_observations(pdf_path: Path) -> dict[str, object]:
    if not pdf_path.exists():
        return {"page_count": 0, "fonts": [], "rendered_inspection": {"status": "unavailable", "reason": "no bound PDF", "text_pages": [], "text_empty_pages": []}}
    data = pdf_path.read_bytes()
    fonts = sorted({item.decode("latin-1", errors="replace") for item in re.findall(rb"/BaseFont\s*/([^\s/]+)", data)})
    page_count = len(re.findall(rb"/Type\s*/Page\b", data))
    info = _run_local_tool(["pdfinfo", str(pdf_path)])
    if info is not None and info.returncode == 0:
        match = re.search(r"^Pages:\s*(\d+)\s*$", info.stdout, re.MULTILINE | re.IGNORECASE)
        if match:
            page_count = int(match.group(1))
    text_pages: list[dict[str, object]] = []
    text_empty_pages: list[int] = []
    extractor_available = shutil.which("pdftotext") is not None
    if extractor_available and page_count:
        for page in range(1, page_count + 1):
            result = _run_local_tool(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf_path), "-"])
            if result is None or result.returncode != 0:
                continue
            character_count = len(re.sub(r"\s+", "", result.stdout))
            text_pages.append({"page": page, "text_character_count": character_count})
            if character_count == 0:
                text_empty_pages.append(page)
    return {
        "page_count": page_count,
        "fonts": fonts,
        "rendered_inspection": {
            "status": "observed" if text_pages else "unavailable",
            "reason": "" if text_pages else "pdftotext unavailable or extraction failed",
            "text_pages": text_pages,
            "text_empty_pages": text_empty_pages,
            "limitation": "A text-empty page may contain graphics or inaccessible text and is not conclusively blank.",
        },
    }


def _synctex_page(pdf_path: Path, tex_path: Path, line: int) -> dict[str, object]:
    result = _run_local_tool(["synctex", "view", "-i", f"{line}:0:{tex_path}", "-o", str(pdf_path)])
    if result is None:
        return {"status": "unavailable", "page": 0, "reason": "synctex unavailable"}
    if result.returncode != 0:
        return {"status": "unavailable", "page": 0, "reason": "SyncTeX data unavailable or query failed"}
    match = re.search(r"^Page:(\d+)\s*$", result.stdout, re.MULTILINE)
    if not match:
        return {"status": "unavailable", "page": 0, "reason": "SyncTeX returned no page"}
    return {"status": "observed", "page": int(match.group(1)), "reason": "source line mapped through local SyncTeX data"}


def _claim_evidence_graph(config, index: dict[str, object], pdf_path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    claims = [env for env in index["environments"] if env["theorem_kind"]]
    proofs = [entry for entry in index["dependency_map"] if entry["environment"] == "proof"]
    label_to_claim = {label: number for number, claim in enumerate(claims, 1) for label in claim["labels"]}
    assumption_ids = {
        number for number, claim in enumerate(claims, 1) if claim["theorem_kind"] == "assumption"
    }
    graph: list[dict[str, object]] = []
    manifest_claims: list[dict[str, object]] = []
    for number, claim in enumerate(claims, 1):
        claim_id = f"CLM-{number:03d}"
        bound_proofs = [
            proof for proof in proofs
            if (proof.get("nearest_claim") or {}).get("line") == claim["line"]
            and (proof.get("nearest_claim") or {}).get("environment") == claim["environment"]
            and proof["file"] == claim["file"]
        ]
        referenced_claim_ids = sorted({
            f"CLM-{label_to_claim[ref]:03d}"
            for group in claim["refs"] for ref in group.split(",")
            if ref in label_to_claim and label_to_claim[ref] != number
        })
        assumption_dependencies = [item for item in referenced_claim_ids if int(item.split("-")[1]) in assumption_ids]
        page = _synctex_page(pdf_path, config.tex_root / claim["file"], int(claim["line"])) if pdf_path.exists() else {"status": "unavailable", "page": 0, "reason": "no bound PDF"}
        evidence_state = "proof_environment_bound" if bound_proofs else ("assumption_declaration" if claim["theorem_kind"] == "assumption" else "no_bound_proof")
        manifest_claims.append({
            "claim_id": claim_id, "kind": claim["theorem_kind"], "source_span": claim["source_span"],
            "pdf_location": page, "evidence_state": evidence_state,
            "proof_source_spans": [proof["source_span"] for proof in bound_proofs],
            "claim_dependencies": referenced_claim_ids, "assumption_dependencies": assumption_dependencies,
        })
        for dependency in referenced_claim_ids:
            graph.append({"from": claim_id, "to": dependency, "type": "assumption" if dependency in assumption_dependencies else "claim_reference", "observation": "LaTeX reference in claim environment"})
        for proof in bound_proofs:
            graph.append({"from": claim_id, "to": f"{proof['file']}:{proof['line']}", "type": "proof_environment", "observation": "nearest following proof environment in the same source file"})
    return manifest_claims, graph


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
    claims, claim_evidence_graph = _claim_evidence_graph(config, index, pdf_path)
    unsupported_claims = [claim for claim in claims if claim["evidence_state"] == "no_bound_proof"]
    checks = paper_structural_checks(config, index, pdf, bibliography)
    if unsupported_claims:
        checks.append({"category": "claim_evidence", "severity": "high", "message": f"{len(unsupported_claims)} theorem-like claim(s) have no structurally bound proof environment; author/domain-expert verification is required.", "locations": [claim["source_span"] for claim in unsupported_claims]})
    empty_pages = pdf.get("rendered_inspection", {}).get("text_empty_pages", [])
    if empty_pages:
        checks.append({"category": "pdf_text_empty_page", "severity": "medium", "message": f"PDF page(s) {', '.join(map(str, empty_pages))} yielded no extractable text; inspect rendering manually.", "locations": [{"page": page} for page in empty_pages]})
    manifest = {
        "version": PAPER_MANIFEST_VERSION,
        "generated_at": now_iso(),
        "status": "indexed",
        "input_fingerprint": paper_input_fingerprint(base),
        "source": {"tex_root": str(config.tex_root), "main_tex": config.main_tex, "root_file": index["root_file"], "files": source_files},
        "compiled_pdf": pdf,
        "index": {key: index[key] for key in ("sections", "environments", "citations", "bibliography", "dependency_map", "unresolved_refs", "potential_undefined_symbols", "warnings")},
        "claims": claims,
        "claim_evidence_graph": claim_evidence_graph,
        "bibliography_entries": bibliography,
        "checks": checks,
        "limitations": ["This manifest records local source and rendered-file observations only.", "Proof binding is structural proximity and LaTeX-reference analysis, not semantic proof verification.", "SyncTeX page mappings and extracted PDF text are tool observations and may be unavailable or incomplete.", "It does not establish theorem correctness, experiment validity, or submission readiness."],
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
    rendered = pdf.get("rendered_inspection", {})
    claims = manifest.get("claims", [])
    mapped_claims = sum(1 for claim in claims if claim.get("pdf_location", {}).get("status") == "observed")
    lines = ["# Paper Manifest", "", f"- Status: `{manifest.get('status', 'invalid')}`", f"- Main TeX: `{source.get('main_tex', '')}`", f"- Reachable source files: {len(source.get('files', []))}", f"- Compiled PDF bound: `{str(pdf.get('exists', False)).lower()}`", f"- PDF page observations: {pdf.get('page_count', 0)}", f"- Rendered text inspection: `{rendered.get('status', 'unavailable')}`", f"- Claims mapped to PDF pages: {mapped_claims}/{len(claims)}", "", "## Claims and Evidence", ""]
    for claim in claims:
        page = claim.get("pdf_location", {}).get("page", 0)
        lines.append(f"- `{claim['claim_id']}` {claim['kind']}: evidence=`{claim['evidence_state']}`, PDF page={page or 'unavailable'}")
    if not claims:
        lines.append("- No theorem-like claims indexed.")
    lines.extend(["", "## Structural Checks", ""])
    lines.extend(f"- [{row['severity']}] {row['message']}" for row in manifest.get("checks", []))
    if not manifest.get("checks"):
        lines.append("- No additional deterministic structural checks were triggered.")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in manifest.get("limitations", []))
    return "\n".join(lines) + "\n"
