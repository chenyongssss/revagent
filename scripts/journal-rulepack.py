#!/usr/bin/env python
"""Install or inspect bundled journal rulepacks for a RevAgent project."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from revagent.profiles import parse_profile_yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
RULEPACKS = REPO_ROOT / "journal_profiles"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or inspect a local RevAgent journal rulepack.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    install = sub.add_parser("install")
    install.add_argument("journal")
    install.add_argument("--force", action="store_true")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("journal")
    args = parser.parse_args()
    available = {path.stem: path for path in RULEPACKS.glob("*.yaml")}
    if args.command == "list":
        print("\n".join(sorted(available)))
        return 0
    if args.journal not in available:
        print(f"error: unknown bundled rulepack {args.journal!r}; choose: {', '.join(sorted(available))}")
        return 1
    source = available[args.journal]
    if args.command == "inspect":
        data = parse_profile_yaml(source.read_text(encoding="utf-8"))
        print(f"journal: {data.get('display_name', args.journal)}")
        print(f"version: {data.get('version', 'missing')}")
        print(f"source: {data.get('source_url', 'manual confirmation required')}")
        print(f"human_confirmed: {data.get('human_confirmed', False)}")
        return 0
    destination = Path.cwd() / "journal_profiles" / source.name
    if destination.exists() and not args.force:
        print(f"error: {destination} already exists; use --force only after reviewing local changes")
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    print(f"Installed {args.journal} rulepack at {destination}")
    print("Review source_checked_at and set human_confirmed: true only after checking the official journal policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
