"""Audit local revision histories without copying confidential manuscript text."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ._utils import now_iso, read_json, write_json, write_text

_CASE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_SOURCE_SUFFIXES = {".tex", ".docx"}
_RESPONSE_HINTS = ("resp", "response", "rebuttal", "reply")
_OLD_HINTS = ("old", "original", "initial", "submission")
_REVISED_HINTS = ("revision", "revised", "new", "final")
_PUBLIC_HOSTS = {
    "peerj": {"peerj.com", "api.crossref.org"},
    "f1000research": {"f1000research.com", "www.ebi.ac.uk", "europepmc.org"},
    "elife": {"elifesciences.org"},
    "openreview": {"openreview.net", "api2.openreview.net"},
}
_MAX_PUBLIC_ARTIFACT_BYTES = 50 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path, *, responses: bool) -> list[Path]:
    result = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix().lower()
        if "cover letter" in relative or "cover_letter" in relative:
            continue
        is_response = any(hint in relative for hint in _RESPONSE_HINTS)
        if is_response == responses:
            result.append(path)
    return sorted(result, key=lambda item: item.as_posix().lower())


def _snapshot(folder: Path, case_root: Path, snapshot_id: str, extra_files: list[Path] | None = None) -> dict:
    files = [] if extra_files is not None and folder == case_root else _files(folder, responses=False)
    if extra_files:
        files.extend(path for path in extra_files if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES)
        files = sorted(set(files), key=lambda item: item.as_posix().lower())
    return {
        "snapshot_id": snapshot_id,
        "path": folder.relative_to(case_root).as_posix(),
        "file_count": len(files),
        "files": [
            {
                "path": path.relative_to(case_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }


def audit_local_revision_case(case_dir: Path, case_id: str, expected_rounds: int,
                              outcome: str = "accepted_user_asserted") -> dict:
    """Return a metadata-only completeness assessment for one local case."""
    case_dir = case_dir.resolve()
    if not case_dir.is_dir():
        raise ValueError("case directory does not exist")
    if not _CASE_ID.fullmatch(case_id):
        raise ValueError("case_id must be a lowercase stable identifier")
    if not isinstance(expected_rounds, int) or expected_rounds < 1:
        raise ValueError("expected_rounds must be a positive integer")
    if outcome not in {"accepted_user_asserted", "accepted_documented", "rejected", "withdrawn", "unknown"}:
        raise ValueError("unsupported outcome")

    children = [path for path in case_dir.iterdir() if path.is_dir()]
    originals = [path for path in children if any(hint in path.name.lower() for hint in _OLD_HINTS)]
    revised = [path for path in children if any(hint in path.name.lower() for hint in _REVISED_HINTS)]
    if len(originals) != 1 or len(revised) != 1 or originals[0] == revised[0]:
        raise ValueError("case must contain exactly one original and one revised/final folder")

    response_files = _files(revised[0], responses=True)
    intermediate = sorted(
        (path for path in case_dir.iterdir() if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
         and any(hint in path.name.lower() for hint in ("article", "manuscript", "revision", "revised"))),
        key=lambda item: item.name.lower(),
    )
    snapshots = [_snapshot(originals[0], case_dir, "submitted-v1")]
    if expected_rounds > 1 and intermediate:
        snapshots.append(_snapshot(case_dir, case_dir, "revision-1", intermediate))
    snapshots.append(_snapshot(revised[0], case_dir, "final-revision"))
    available_transitions = max(0, len(snapshots) - 1)
    complete = (
        available_transitions >= expected_rounds
        and len(response_files) >= expected_rounds
        and all(item["file_count"] > 0 for item in snapshots)
    )
    gaps = []
    if available_transitions < expected_rounds:
        gaps.append(f"missing_{expected_rounds - available_transitions}_intermediate_manuscript_snapshot(s)")
    if len(response_files) < expected_rounds:
        gaps.append(f"missing_{expected_rounds - len(response_files)}_round_response_file(s)")
    if any(item["file_count"] == 0 for item in snapshots):
        gaps.append("empty_manuscript_snapshot")

    return {
        "version": 1,
        "case_id": case_id,
        "evidence_tier": "private_accepted_gold_candidate",
        "expert_calibrated": False,
        "content_copied": False,
        "case_path": str(case_dir),
        "outcome": outcome,
        "outcome_evidence_path": None,
        "expected_rounds": expected_rounds,
        "available_manuscript_transitions": available_transitions,
        "response_file_count": len(response_files),
        "response_files": [
            {"path": path.relative_to(case_dir).as_posix(), "size": path.stat().st_size, "sha256": _sha256(path)}
            for path in response_files
        ],
        "snapshots": snapshots,
        "final_state_verifiable": bool(response_files) and all(item["file_count"] > 0 for item in snapshots),
        "round_chain_complete": complete,
        "gaps": gaps,
        "audited_at": now_iso(),
    }


def audit_local_revision_corpus(base: Path, cases_dir: Path, rounds: dict[str, int]) -> dict:
    """Audit a bounded set of local cases and persist metadata under .revagent."""
    cases_dir = cases_dir.resolve()
    rows = []
    for folder_name, expected_rounds in rounds.items():
        folder = cases_dir / folder_name
        case_id = re.sub(r"[^a-z0-9]+", "-", folder_name.lower()).strip("-")
        rows.append(audit_local_revision_case(folder, case_id, expected_rounds))
    report = {
        "version": 1,
        "generated_at": now_iso(),
        "evidence_tier": "private_accepted_gold_candidate",
        "expert_calibrated": False,
        "case_count": len(rows),
        "round_chain_complete_count": sum(row["round_chain_complete"] for row in rows),
        "final_state_verifiable_count": sum(row["final_state_verifiable"] for row in rows),
        "cases": rows,
        "limitations": [
            "Acceptance is an outcome signal, not an expert item-level annotation.",
            "No manuscript or review text is copied into the report.",
            "Every review round requires its own before/after manuscript snapshots for round-level verification.",
        ],
    }
    output = base.resolve() / ".revagent"
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "local_revision_corpus.json", report)
    lines = [
        "# Local Revision Corpus Audit", "",
        f"- Cases: {report['case_count']}",
        f"- Complete round chains: {report['round_chain_complete_count']}",
        f"- Final states verifiable: {report['final_state_verifiable_count']}",
        "- Expert calibrated: `false`", "", "## Cases", "",
    ]
    lines.extend(
        f"- `{row['case_id']}`: rounds={row['expected_rounds']}; transitions={row['available_manuscript_transitions']}; "
        f"responses={row['response_file_count']}; complete={str(row['round_chain_complete']).lower()}; gaps={', '.join(row['gaps']) or 'none'}"
        for row in rows
    )
    write_text(output / "local_revision_corpus.md", "\n".join(lines) + "\n")
    return report


def audit_public_revision_catalog(base: Path, catalog_path: Path, cache_dir: Path) -> dict:
    """Verify cached public artifacts declared by a provenance catalog."""
    catalog = read_json(catalog_path, {})
    if not isinstance(catalog, dict) or catalog.get("version") != 1 or not isinstance(catalog.get("cases"), list):
        raise ValueError("public revision catalog must contain version 1 and a cases list")
    rows = []
    for case in catalog["cases"]:
        required = {"case_id", "provider", "domain", "record_url", "license", "license_url", "expected_rounds", "artifacts"}
        if not isinstance(case, dict) or set(case) != required:
            raise ValueError("public catalog case fields are invalid")
        artifacts = []
        missing = []
        for artifact in case["artifacts"]:
            if not isinstance(artifact, dict) or set(artifact) != {"kind", "version", "url", "cache_file"}:
                raise ValueError("public artifact fields are invalid")
            path = cache_dir / artifact["cache_file"]
            if path.is_file() and path.stat().st_size:
                artifacts.append({**artifact, "size": path.stat().st_size, "sha256": _sha256(path)})
            else:
                missing.append(artifact["cache_file"])
        versions = {item["version"] for item in artifacts if item["kind"] == "manuscript"}
        has_review = any(item["kind"] == "review_response" for item in artifacts)
        expected_versions = case["expected_rounds"] + 1
        complete = len(versions) >= expected_versions and has_review and not missing
        rows.append({
            "case_id": case["case_id"], "provider": case["provider"], "domain": case["domain"],
            "record_url": case["record_url"], "license": case["license"], "license_url": case["license_url"],
            "expected_rounds": case["expected_rounds"], "verified_artifacts": artifacts,
            "missing_cache_files": missing, "complete_revision_chain": complete,
            "status": "verified_complete" if complete else "candidate_pending_fetch",
        })
    report = {
        "version": 1, "generated_at": now_iso(), "evidence_tier": "public_revision_silver",
        "expert_calibrated": False, "candidate_count": len(rows),
        "verified_complete_count": sum(row["complete_revision_chain"] for row in rows),
        "pending_count": sum(not row["complete_revision_chain"] for row in rows), "cases": rows,
    }
    output = base.resolve() / ".revagent"
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "public_revision_corpus.json", report)
    return report


def fetch_public_revision_catalog(base: Path, catalog_path: Path, cache_dir: Path,
                                  confirmed: bool = False, overwrite: bool = False,
                                  case_ids: set[str] | None = None) -> dict:
    """Fetch catalog artifacts from provider-owned HTTPS endpoints into a local cache."""
    if not confirmed:
        raise ValueError("explicit confirmation of public access and licensing is required")
    catalog = read_json(catalog_path, {})
    if not isinstance(catalog, dict) or catalog.get("version") != 1 or not isinstance(catalog.get("cases"), list):
        raise ValueError("public revision catalog must contain version 1 and a cases list")
    cache_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for case in catalog["cases"]:
        if case_ids and case.get("case_id") not in case_ids:
            continue
        provider = case.get("provider") if isinstance(case, dict) else None
        if provider not in _PUBLIC_HOSTS or not isinstance(case.get("artifacts"), list):
            raise ValueError("unsupported public provider or artifacts")
        for artifact in case["artifacts"]:
            url = artifact.get("url", "")
            cache_file = artifact.get("cache_file", "")
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in _PUBLIC_HOSTS[provider]:
                raise ValueError("artifact URL must use an approved provider HTTPS host")
            if not isinstance(cache_file, str) or not cache_file or Path(cache_file).name != cache_file:
                raise ValueError("cache_file must be a plain filename")
            destination = cache_dir / cache_file
            if destination.is_file() and destination.stat().st_size and not overwrite:
                results.append({"case_id": case["case_id"], "cache_file": cache_file, "status": "cached",
                                "size": destination.stat().st_size, "sha256": _sha256(destination)})
                continue
            temporary = cache_dir / f".{cache_file}.part"
            try:
                request = Request(url, headers={"User-Agent": "revagent-public-review/0.1 (revision corpus validation)"})
                with urlopen(request, timeout=45) as response:  # nosec: host allowlist enforced above
                    length = response.headers.get("Content-Length")
                    if length and int(length) > _MAX_PUBLIC_ARTIFACT_BYTES:
                        raise ValueError("public artifact exceeds 50 MiB limit")
                    payload = response.read(_MAX_PUBLIC_ARTIFACT_BYTES + 1)
                if len(payload) > _MAX_PUBLIC_ARTIFACT_BYTES:
                    raise ValueError("public artifact exceeds 50 MiB limit")
                temporary.write_bytes(payload)
                temporary.replace(destination)
                results.append({"case_id": case["case_id"], "cache_file": cache_file, "status": "downloaded",
                                "size": len(payload), "sha256": _sha256(destination)})
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                temporary.unlink(missing_ok=True)
                results.append({"case_id": case.get("case_id", "unknown"), "cache_file": cache_file,
                                "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    report = {"version": 1, "generated_at": now_iso(), "selected_case_ids": sorted(case_ids or []), "results": results,
              "downloaded": sum(row["status"] == "downloaded" for row in results),
              "cached": sum(row["status"] == "cached" for row in results),
              "failed": sum(row["status"] == "failed" for row in results)}
    output = base.resolve() / ".revagent"
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "public_revision_fetch.json", report)
    return report
