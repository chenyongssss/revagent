"""Local-only candidate contribution packages for community calibration."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .privacy import classify_path, scan_directory


_CASE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_DATA_CARD_FIELDS = {
    "version",
    "case_id",
    "permission_status",
    "deidentification_status",
    "intended_visibility",
    "retention_rule",
    "allowed_purposes",
    "subfield",
}
_VISIBILITIES = {"private_review", "public_benchmark"}


def contribution_data_card_template(case_id: str) -> dict[str, object]:
    """Return the closed data-card template; users must complete it locally."""
    return {
        "version": 1,
        "case_id": case_id,
        "permission_status": "not_confirmed",
        "deidentification_status": "not_confirmed",
        "intended_visibility": "private_review",
        "retention_rule": "",
        "allowed_purposes": [],
        "subfield": "",
    }


def _validate_data_card(data_card: object, case_id: str) -> dict[str, object]:
    if not isinstance(data_card, dict) or set(data_card) != _DATA_CARD_FIELDS:
        raise ValueError("data card must contain exactly the documented contribution fields")
    if data_card.get("version") != 1 or data_card.get("case_id") != case_id:
        raise ValueError("data card version or case_id is invalid")
    if data_card.get("permission_status") != "written":
        raise ValueError("data card requires written permission")
    if data_card.get("deidentification_status") != "completed":
        raise ValueError("data card requires completed deidentification")
    if data_card.get("intended_visibility") not in _VISIBILITIES:
        raise ValueError("data card intended_visibility is invalid")
    if not isinstance(data_card.get("allowed_purposes"), list) or not data_card["allowed_purposes"] or not all(isinstance(item, str) and item.strip() for item in data_card["allowed_purposes"]):
        raise ValueError("data card requires one or more allowed_purposes")
    if not all(isinstance(data_card.get(key), str) and data_card[key].strip() for key in ("retention_rule", "subfield")):
        raise ValueError("data card requires retention_rule and subfield")
    return {key: data_card[key] for key in sorted(_DATA_CARD_FIELDS)}


def _file_fingerprints(case_dir: Path) -> list[dict[str, object]]:
    fingerprints = []
    for path in sorted(case_dir.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            fingerprints.append({
                "path": str(path.relative_to(case_dir)),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "classification": classify_path(path),
            })
    return fingerprints


def create_contribution_package(base: Path, case_dir: Path, case_id: str, data_card_path: Path, *, confirmed: bool = False) -> Path:
    """Create a local metadata-only package after explicit contributor confirmation.

    This intentionally never copies source case files and never performs network I/O.
    The package is a reviewable manifest, not evidence that deidentification is correct.
    """
    if not _CASE_ID.fullmatch(case_id):
        raise ValueError("case_id must contain only lowercase letters, numbers, _ or -")
    case_dir = case_dir.resolve()
    if not case_dir.is_dir() or not any(path.is_file() for path in case_dir.rglob("*")):
        raise ValueError("case_dir must be a non-empty directory")
    if not confirmed:
        raise ValueError("explicit contributor confirmation is required; rerun with --confirm")
    data_card = _validate_data_card(read_json(data_card_path, {}), case_id)
    scan = scan_directory(case_dir)
    if scan["findings"]:
        raise ValueError("credential candidates found; resolve them before creating a contribution package")

    config = load_config(base)
    package = config.workspace / "contribution_candidates" / case_id
    if package.exists():
        raise ValueError("contribution package already exists; choose a new case_id")
    manifest = {
        "version": 1,
        "case_id": case_id,
        "created_at": now_iso(),
        "mode": "local_metadata_only",
        "network_activity": "none",
        "source_case_content_included": False,
        "human_review_required": True,
        "deidentification_assessment": "not assessed by RevAgent",
        "data_card": data_card,
        "scan": scan,
        "source_file_fingerprints": _file_fingerprints(case_dir),
    }
    write_json(package / "data_card.json", data_card)
    write_json(package / "manifest.json", manifest)
    write_text(package / "README.md", "# Local Contribution Candidate\n\nThis package contains metadata, safety-scan findings, and file fingerprints only. It contains no manuscript, reviewer text, source code, or data. RevAgent has not verified deidentification or publication rights. Do not upload this package or any source material until a human governance review approves the stated visibility and purposes.\n")
    return package


__all__ = ["contribution_data_card_template", "create_contribution_package"]
