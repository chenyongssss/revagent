#!/usr/bin/env python
"""Show the latest local pre-submission review without running it again."""

from __future__ import annotations

from pathlib import Path

from revagent.pre_submission_review import load_pre_submission_review, render_pre_submission_review


def main() -> int:
    report = load_pre_submission_review(Path.cwd())
    if not report or report.get("status") == "not_run":
        print("No pre-submission review run yet. Run: python scripts/review-paper.py")
        return 1
    print(render_pre_submission_review(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
