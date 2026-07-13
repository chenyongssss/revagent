"""Detached external-worker wrapper that records an atomic completion manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from ._utils import now_iso


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--stdout", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("--completion", required=True)
    args = parser.parse_args(argv)
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    stdout_path = Path(args.stdout)
    stderr_path = Path(args.stderr)
    completion = Path(args.completion)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    completion.parent.mkdir(parents=True, exist_ok=True)
    started_at = now_iso()
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            result = subprocess.run([args.command], input=prompt, text=True, stdout=stdout, stderr=stderr, check=False)
        exit_code = result.returncode
        error = "" if exit_code == 0 else f"external worker exited with code {exit_code}"
    except Exception as exc:  # Wrapper failures must be persisted for a later refresh.
        exit_code = -1
        error = str(exc)
    record = {"version": 1, "started_at": started_at, "finished_at": now_iso(), "exit_code": exit_code, "error": error}
    temp = completion.with_suffix(completion.suffix + ".tmp")
    temp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(completion)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
