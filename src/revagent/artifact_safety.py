"""Fail-closed helpers shared by revision-cycle artifact validators."""

from __future__ import annotations

import re
from typing import Any


_CONCLUSION = re.compile(r"\b(?:proved|correct|validated|reproducible|approved)\b|\bresult\s+value\b", re.IGNORECASE)


def require_closed_object(value: object, allowed: set[str], label: str) -> dict[str, Any]:
    """Return an object only when it has no undeclared fields."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {', '.join(unknown)}")
    return value


def reject_conclusions(value: object, label: str = "artifact") -> None:
    """Reject conclusion language at every nesting depth, including unknown payloads."""
    if isinstance(value, dict):
        for key, child in value.items():
            if _CONCLUSION.search(str(key)):
                raise ValueError(f"{label} contains a prohibited conclusion field")
            reject_conclusions(child, label)
    elif isinstance(value, list):
        for child in value:
            reject_conclusions(child, label)
    elif isinstance(value, str) and _CONCLUSION.search(value):
        raise ValueError(f"{label} may not assert mathematical or experimental conclusions")
