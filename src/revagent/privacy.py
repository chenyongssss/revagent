"""Local-first privacy inventory and remote-consent guardrails."""

from __future__ import annotations

import re
from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json, write_text


DEFAULT_PRIVACY_POLICY = {
    "version": 1,
    "local_first": True,
    "allowed_remote_providers": ["fake", "openai-compatible"],
    "allowed_artifact_classes": ["review_comment", "response_draft", "project_snapshot"],
    "require_one_time_consent": True,
}
_SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    "api_key": re.compile(r"\b(?:sk|api)[_-][A-Za-z0-9_-]{16,}\b", re.I),
    "credential_assignment": re.compile(r"\b(?:password|secret|token)\s*[=:]\s*[^\s]{8,}", re.I),
}


def privacy_policy(config) -> dict[str, object]:
    path = config.workspace / "privacy_policy.json"
    policy = read_json(path, DEFAULT_PRIVACY_POLICY)
    if not isinstance(policy, dict):
        return dict(DEFAULT_PRIVACY_POLICY)
    return {**DEFAULT_PRIVACY_POLICY, **policy}


def classify_path(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".env", ".pem", ".key", ".p12", ".pfx"} or path.name.casefold() in {"id_rsa", "credentials"}:
        return "secret_candidate"
    if suffix in {".tex", ".bib", ".docx", ".pdf", ".md", ".txt"}:
        return "manuscript_or_review"
    if suffix in {".csv", ".json", ".h5", ".hdf5", ".npy", ".npz"}:
        return "data_or_metadata"
    if suffix in {".py", ".m", ".jl", ".r", ".ipynb"}:
        return "source_code"
    return "other"


def privacy_scan(base: Path) -> dict[str, object]:
    """Scan local text files for credentials without emitting secret values."""
    config = load_config(base)
    report = scan_directory(config.tex_root, excluded_directory=config.workspace)
    report.update({"version": 1, "scanned_at": now_iso(), "policy": privacy_policy(config), "remote_safe": not report["findings"]})
    write_json(config.workspace / "privacy_scan.json", report)
    lines = ["# Privacy Scan", "", f"- Remote-safe: {str(not report['findings']).lower()}", "", "## Findings", ""]
    lines.extend(f"- `{entry['path']}:{entry['line']}` {entry['kind']}" for entry in report["findings"]) if report["findings"] else lines.append("- None.")
    write_text(config.workspace / "privacy_scan.md", "\n".join(lines) + "\n")
    return report


def scan_directory(root: Path, *, excluded_directory: Path | None = None) -> dict[str, object]:
    """Inventory one local directory without exposing matched secret values."""
    findings: list[dict[str, object]] = []
    inventory: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or (excluded_directory and (path == excluded_directory or excluded_directory in path.parents)) or path.stat().st_size > 2 * 1024 * 1024:
            continue
        category = classify_path(path)
        rel = str(path.relative_to(root))
        inventory.append({"path": rel, "classification": category})
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for kind, pattern in _SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append({"path": rel, "line": text.count("\n", 0, match.start()) + 1, "kind": kind})
    return {"inventory": inventory, "findings": findings}


def remote_authorization_issues(base: Path, provider: str, artifact_classes: list[str]) -> list[str]:
    config = load_config(base)
    policy = privacy_policy(config)
    issues = []
    if provider not in policy["allowed_remote_providers"]:
        issues.append("provider is not on the local privacy allow-list")
    disallowed = sorted(set(artifact_classes) - set(policy["allowed_artifact_classes"]))
    if disallowed:
        issues.append(f"artifact classes are not on the allow-list: {', '.join(disallowed)}")
    report = privacy_scan(base)
    if report["findings"]:
        issues.append("sensitive credential candidates were found; resolve them before remote authorization")
    return issues


__all__ = ["DEFAULT_PRIVACY_POLICY", "classify_path", "privacy_policy", "privacy_scan", "remote_authorization_issues", "scan_directory"]
