#!/usr/bin/env python
"""Run RevAgent's local pre-submission review without changing a manuscript."""

from __future__ import annotations

import argparse
from pathlib import Path

from revagent.pre_submission_review import build_pre_submission_review, render_pre_submission_review


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local advisory pre-submission review.")
    parser.add_argument("--journal", help="Optional journal_profiles/<name>.yaml override.")
    args = parser.parse_args()
    try:
        report = build_pre_submission_review(Path.cwd(), args.journal)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    print(render_pre_submission_review(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
