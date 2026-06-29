"""Built-in and local publisher-level journal profiles."""

from __future__ import annotations

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
    """Load a built-in profile, optionally overridden by journal_profiles/name.yaml."""

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

    override = base / "journal_profiles" / f"{key}.yaml"
    if override.exists():
        local = parse_profile_yaml(override.read_text(encoding="utf-8", errors="replace"))
        profile.update(local)
        profile["key"] = key
        profile["source"] = str(override)
    return profile


def get_profile(name: str) -> dict[str, object]:
    return built_in_profile(name)


def available_profiles(base: Path | None = None) -> list[str]:
    names = set(PROFILES)
    if base is not None:
        profile_dir = base / "journal_profiles"
        if profile_dir.exists():
            names.update(path.stem.lower() for path in profile_dir.glob("*.yaml"))
    return sorted(names)
