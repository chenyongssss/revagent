"""Built-in and local publisher-level journal profiles."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

PROFILES = {
    "siam": {
        "display_name": "SIAM",
        "response_heading": "Response to the Editor and Reviewers",
        "tone": "precise, collegial, and concise",
        "style_hints": [
            "Track every reviewer request explicitly.",
            "Prefer precise mathematical wording over broad claims.",
            "Flag theorem, proof, algorithm, and numerical experiment changes for author review.",
        ],
        "checks": [
            "SIAM LaTeX class or compatible formatting",
            "consistent theorem/lemma numbering",
            "clear numerical reproducibility notes",
        ],
    },
    "ams": {
        "display_name": "AMS",
        "response_heading": "Response to the Referee Reports",
        "tone": "formal, mathematically focused, and restrained",
        "style_hints": [
            "Emphasize theorem hypotheses and proof dependencies.",
            "Avoid overstating computational evidence as proof.",
            "Keep responses compact while citing exact manuscript locations.",
        ],
        "checks": [
            "AMS-compatible theorem environments",
            "bibliography and citation consistency",
            "notation introduced before use",
        ],
    },
    "springer": {
        "display_name": "Springer",
        "response_heading": "Author Response to Reviewers",
        "tone": "structured, courteous, and explicit",
        "style_hints": [
            "Use point-by-point responses with manuscript locations.",
            "Separate implemented revisions from planned or declined changes.",
            "Flag supplementary material and appendix changes clearly.",
        ],
        "checks": [
            "Springer-compatible article structure",
            "figure/table caption completeness",
            "declarations or supplementary material notes when applicable",
        ],
    },
    "elsevier": {
        "display_name": "Elsevier",
        "response_heading": "Detailed Response to the Reviewers",
        "tone": "direct, polite, and implementation-oriented",
        "style_hints": [
            "Make each response self-contained.",
            "State exactly what changed and where.",
            "Keep experimental additions tied to reviewer concerns.",
        ],
        "checks": [
            "Elsevier-compatible front matter and highlights if required",
            "graphical/table references remain consistent",
            "cover letter and response files are separable",
        ],
    },
}


def _parse_scalar(value: str) -> str | bool:
    value = value.strip().strip("'\"")
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def parse_profile_yaml(text: str) -> dict[str, object]:
    """Parse the small YAML subset used by journal_profiles/*.yaml."""

    result: dict[str, object] = {}
    current_list: str | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("  - ") and current_list:
            result.setdefault(current_list, [])
            assert isinstance(result[current_list], list)
            result[current_list].append(_parse_scalar(raw[4:]))
            continue
        current_list = None
        if ":" not in raw or raw.startswith(" "):
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            result[key] = _parse_scalar(value)
        else:
            result[key] = []
            current_list = key
    return result


def built_in_profile(name: str) -> dict[str, object]:
    key = name.lower()
    if key not in PROFILES:
        allowed = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown journal profile {name!r}; choose one of: {allowed}, or add journal_profiles/{key}.yaml")
    return {"key": key, **PROFILES[key]}


def load_profile(name: str, base: Path | None = None) -> dict[str, object]:
    """Load a built-in profile, then a directory rulepack or legacy flat override."""

    key = name.lower()
    if key in PROFILES:
        profile = built_in_profile(key)
    else:
        profile = {
            "key": key,
            "display_name": name,
            "response_heading": "Response to the Editor and Reviewers",
            "tone": "precise, collegial, and conservative",
            "style_hints": [],
            "checks": [],
        }
    if base is None:
        return profile

    rulepack_dir = base / "journal_profiles" / key
    rulepack_profile = rulepack_dir / "profile.yaml"
    if rulepack_profile.exists():
        local = parse_profile_yaml(rulepack_profile.read_text(encoding="utf-8", errors="replace"))
        profile.update(local)
        profile["key"] = key
        components: dict[str, dict[str, str]] = {}
        for component in ("profile.yaml", "rubric.yaml", "submission.yaml", "rebuttal.yaml", "sources.md"):
            path = rulepack_dir / component
            if path.exists():
                components[component] = {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                if component.endswith(".yaml") and component != "profile.yaml":
                    profile[component.removesuffix(".yaml")] = parse_profile_yaml(path.read_text(encoding="utf-8", errors="replace"))
        profile["source"] = str(rulepack_profile)
        profile["rulepack"] = {
            "format": "directory-v1",
            "directory": str(rulepack_dir),
            "components": components,
            "missing_components": [name for name in ("rubric.yaml", "submission.yaml", "rebuttal.yaml", "sources.md") if name not in components],
        }
        return profile

    override = base / "journal_profiles" / f"{key}.yaml"
    if override.exists():
        local = parse_profile_yaml(override.read_text(encoding="utf-8", errors="replace"))
        profile.update(local)
        profile["key"] = key
        profile["source"] = str(override)
        profile["rulepack"] = {"format": "legacy-flat-v1", "path": str(override)}
    return profile


def get_profile(name: str) -> dict[str, object]:
    return built_in_profile(name)


def available_profiles(base: Path | None = None) -> list[str]:
    names = set(PROFILES)
    if base is not None:
        profile_dir = base / "journal_profiles"
        if profile_dir.exists():
            names.update(path.stem.lower() for path in profile_dir.glob("*.yaml"))
            names.update(path.name.lower() for path in profile_dir.iterdir() if path.is_dir() and (path / "profile.yaml").exists())
    return sorted(names)


def validate_rulepack(name: str, base: Path) -> dict[str, object]:
    """Validate directory rulepack provenance without claiming journal compliance."""
    profile = load_profile(name, base)
    rulepack = profile.get("rulepack", {})
    result: dict[str, object] = {
        "journal": profile["key"],
        "display_name": profile["display_name"],
        "format": rulepack.get("format", "built-in") if isinstance(rulepack, dict) else "invalid",
        "issues": [],
        "warnings": [],
        "blocking": [],
    }
    issues = result["issues"]
    warnings = result["warnings"]
    blocking = result["blocking"]
    assert isinstance(issues, list) and isinstance(warnings, list) and isinstance(blocking, list)
    if not isinstance(rulepack, dict) or rulepack.get("format") != "directory-v1":
        warnings.append("A directory-v1 rulepack is not available; legacy or built-in profile checks remain advisory only.")
    else:
        for component in rulepack.get("missing_components", []):
            issues.append(f"missing required rulepack component: {component}")
        for field in ("version", "source_url", "source_checked_at", "expires_at"):
            if not profile.get(field):
                issues.append(f"profile.yaml is missing {field}")
        checked_at = str(profile.get("source_checked_at", ""))
        expires_at = str(profile.get("expires_at", ""))
        for field, value in (("source_checked_at", checked_at), ("expires_at", expires_at)):
            if value:
                try:
                    parsed = date.fromisoformat(value)
                except ValueError:
                    issues.append(f"profile.yaml {field} must use YYYY-MM-DD")
                else:
                    if field == "expires_at" and parsed < date.today():
                        blocking.append("rulepack has expired; refresh official rules and obtain human confirmation")
        if profile.get("human_confirmed") is not True:
            blocking.append("rulepack is not human-confirmed")
    result["ok"] = not issues and not blocking
    return result


def render_rulepack_validation(result: dict[str, object]) -> str:
    lines = [f"Journal: {result['display_name']} ({result['journal']})", f"Rulepack format: {result['format']}"]
    for label in ("issues", "warnings", "blocking"):
        values = result.get(label, [])
        if isinstance(values, list):
            lines.extend(f"{label[:-1]}: {value}" for value in values)
    lines.append("status: valid" if result.get("ok") else "status: not ready for journal-specific reporting")
    return "\n".join(lines) + "\n"


def initialize_rulepack(name: str, base: Path) -> Path:
    """Create an unconfirmed local rulepack template without sourcing journal policy."""
    key = name.strip().lower()
    if not key or any(character in key for character in "\\/:"):
        raise ValueError("journal name must be a simple local rulepack key")
    directory = base / "journal_profiles" / key
    if directory.exists():
        raise ValueError(f"rulepack already exists: {directory}")
    directory.mkdir(parents=True)
    files = {
        "profile.yaml": (
            f"display_name: {name}\nversion: 1\nsource_url: \nsource_checked_at: \nexpires_at: \nhuman_confirmed: false\n"
            "response_heading: Response to the Editor and Reviewers\ntone: precise, collegial, and conservative\nrequired_checks:\n  - contribution_statement\n  - reproducibility\n"
        ),
        "rubric.yaml": "version: 1\nchecks:\n  - Replace with reviewed journal-specific evaluation criteria.\n",
        "submission.yaml": "version: 1\nchecks:\n  - Replace with reviewed submission requirements.\n",
        "rebuttal.yaml": "version: 1\nchecks:\n  - Replace with reviewed rebuttal requirements.\n",
        "sources.md": "# Official sources\n\nRecord the official URL, retrieval date, exact policy scope, and human reviewer before confirming this rulepack.\n",
    }
    for filename, content in files.items():
        (directory / filename).write_text(content, encoding="utf-8")
    return directory


def diff_rulepacks(left: str, right: str, base: Path) -> dict[str, object]:
    """Compare local profile metadata and component hashes; never fetches sources."""
    left_profile = load_profile(left, base)
    right_profile = load_profile(right, base)
    ignored = {"source", "rulepack"}
    left_metadata = {key: value for key, value in left_profile.items() if key not in ignored}
    right_metadata = {key: value for key, value in right_profile.items() if key not in ignored}
    left_components = ((left_profile.get("rulepack") or {}).get("components") or {}) if isinstance(left_profile.get("rulepack"), dict) else {}
    right_components = ((right_profile.get("rulepack") or {}).get("components") or {}) if isinstance(right_profile.get("rulepack"), dict) else {}
    differences: list[str] = []
    if left_metadata != right_metadata:
        differences.append("profile metadata differs")
    for component in sorted(set(left_components) | set(right_components)):
        left_hash = (left_components.get(component) or {}).get("sha256")
        right_hash = (right_components.get(component) or {}).get("sha256")
        if left_hash != right_hash:
            differences.append(f"{component} differs")
    return {"left": left_profile["key"], "right": right_profile["key"], "differences": differences, "identical": not differences}


def render_rulepack_diff(result: dict[str, object]) -> str:
    lines = [f"Rulepack diff: {result['left']} -> {result['right']}"]
    differences = result.get("differences", [])
    lines.extend(f"- {difference}" for difference in differences)
    if not differences:
        lines.append("- No local metadata or component-hash differences.")
    return "\n".join(lines) + "\n"
