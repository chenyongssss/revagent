"""Explicit, snapshot-isolated runtime and manual-gated RevAgent evolution."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import psutil

from ._utils import load_config, now_iso, read_json, read_text, write_json, write_text
from .external_agent import get_external_agent_run, load_external_agent_runs


ALLOWED_MUTABLE_PATHS = ("src/", "tests/", "README.md", "plan.md", "pyproject.toml")
IGNORED_SNAPSHOT_NAMES = {".git", ".revagent", ".pytest_cache", "__pycache__", "build", "dist", ".tmp", ".venv", "venv"}
TERMINAL_RUNTIME_STATES = {"completed", "failed", "canceled", "lost"}


def _safe_id(value: object) -> str:
    return "".join(char if char.isalnum() else "-" for char in str(value)).strip("-") or "worker"


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and not any(part in IGNORED_SNAPSHOT_NAMES for part in path.relative_to(root).parts))


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(_hash_file(path).encode("ascii"))
    return digest.hexdigest()


def ensure_source_checkout(base: Path) -> None:
    missing = [name for name in ("pyproject.toml", "plan.md", "src/revagent", "tests") if not (base / name).exists()]
    if missing:
        raise ValueError("worker evolution requires a RevAgent source checkout; missing " + ", ".join(missing))


def _runtime_path(config) -> Path:
    return config.workspace / "worker_runtime_events.jsonl"


def _snapshots_path(config) -> Path:
    return config.workspace / "worker_snapshots.json"


def _evaluations_path(config) -> Path:
    return config.workspace / "worker_evaluations.jsonl"


def _proposals_path(config) -> Path:
    return config.workspace / "evolution_proposals.json"


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in read_text(path).splitlines():
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path.name} contains a non-object record")
            records.append(record)
    return records


def _append_jsonl(path: Path, record: dict[str, object]) -> None:
    existing = read_text(path) if path.exists() else ""
    write_text(path, existing + json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def render_runtime_events(records: list[dict[str, object]]) -> str:
    lines = ["# Worker Runtime Events", ""]
    if not records:
        return "\n".join(lines + ["No worker runtime events recorded yet.", ""])
    for record in records[-80:]:
        lines.append(f"- `{record.get('run_id', '')}` state={record.get('state', '')} pid={record.get('pid', '')} exit={record.get('exit_code', '')}")
    return "\n".join(lines) + "\n"


def append_runtime_event(config, record: dict[str, object]) -> None:
    _append_jsonl(_runtime_path(config), record)
    write_text(config.workspace / "worker_runtime_events.md", render_runtime_events(_load_jsonl(_runtime_path(config))))


def latest_runtime_events(config) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for record in _load_jsonl(_runtime_path(config)):
        run_id = str(record.get("run_id", ""))
        if run_id:
            latest[run_id] = record
    return latest


def runtime_event_for_run(config, run_id: str) -> dict[str, object] | None:
    return latest_runtime_events(config).get(run_id)


def _snapshot_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED_SNAPSHOT_NAMES}


def render_snapshots(snapshots: dict[str, object]) -> str:
    lines = ["# Worker Snapshots", ""]
    if not snapshots:
        return "\n".join(lines + ["No worker snapshots recorded yet.", ""])
    for run_id, snapshot in sorted(snapshots.items()):
        if isinstance(snapshot, dict):
            lines.append(f"- `{run_id}` `{snapshot.get('path', '')}` fingerprint={snapshot.get('source_fingerprint', '')}")
    return "\n".join(lines) + "\n"


def create_worker_snapshot(base: Path, run_id: str) -> dict[str, object]:
    ensure_source_checkout(base)
    config = load_config(base)
    get_external_agent_run(config, run_id)
    root = config.workspace / "worker_snapshots" / _safe_id(run_id)
    if root.exists():
        raise ValueError(f"worker snapshot already exists for {run_id}")
    shutil.copytree(base, root, ignore=_snapshot_ignore)
    files = {path.relative_to(root).as_posix(): _hash_file(path) for path in _files(root)}
    manifest = {
        "version": 1,
        "run_id": run_id,
        "created_at": now_iso(),
        "path": str(root),
        "source_fingerprint": source_fingerprint(base),
        "files": files,
        "allowed_mutable_paths": list(ALLOWED_MUTABLE_PATHS),
    }
    write_json(root / "snapshot_manifest.json", manifest)
    snapshots = read_json(_snapshots_path(config), {})
    if not isinstance(snapshots, dict):
        raise ValueError("worker_snapshots.json must be an object")
    snapshots[run_id] = manifest
    write_json(_snapshots_path(config), snapshots)
    write_text(config.workspace / "worker_snapshots.md", render_snapshots(snapshots))
    return manifest


def get_worker_snapshot(config, run_id: str) -> dict[str, object]:
    snapshots = read_json(_snapshots_path(config), {})
    if not isinstance(snapshots, dict) or not isinstance(snapshots.get(run_id), dict):
        raise ValueError(f"no worker snapshot recorded for {run_id}")
    snapshot = snapshots[run_id]
    path = Path(str(snapshot.get("path", "")))
    manifest_path = path / "snapshot_manifest.json"
    if not path.exists() or not manifest_path.exists():
        raise ValueError(f"worker snapshot is missing for {run_id}")
    manifest = read_json(manifest_path, {})
    if not isinstance(manifest, dict) or manifest.get("run_id") != run_id:
        raise ValueError(f"worker snapshot manifest is invalid for {run_id}")
    return manifest


def _completion_path(config, run_id: str) -> Path:
    return config.workspace / "worker_runtime" / f"{_safe_id(run_id)}.completion.json"


def start_worker(base: Path, run_id: str) -> dict[str, object]:
    ensure_source_checkout(base)
    config = load_config(base)
    run = get_external_agent_run(config, run_id)
    if run.get("status") != "queued":
        raise ValueError(f"external run {run_id} is not queued")
    if runtime_event_for_run(config, run_id) is not None:
        raise ValueError(f"external run {run_id} already has runtime history")
    snapshot = get_worker_snapshot(config, run_id)
    if str(snapshot.get("source_fingerprint", "")) != source_fingerprint(base):
        raise ValueError(f"worker snapshot is stale for {run_id}; create a new queued worker")
    command = str(run.get("command", ""))
    if not command or not Path(command).exists():
        raise ValueError(f"external worker backend is unavailable for {run_id}")
    prompt_path = Path(str(run.get("prompt_path", "")))
    if not prompt_path.exists():
        raise ValueError(f"external worker prompt is missing for {run_id}")
    logs = config.workspace / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    safe_id = _safe_id(run_id)
    stdout_path = logs / f"worker-{safe_id}.stdout.log"
    stderr_path = logs / f"worker-{safe_id}.stderr.log"
    completion = _completion_path(config, run_id)
    args = [sys.executable, "-m", "revagent.worker_wrapper", "--command", command, "--prompt", str(prompt_path), "--stdout", str(stdout_path), "--stderr", str(stderr_path), "--completion", str(completion)]
    kwargs: dict[str, object] = {"cwd": str(snapshot["path"]), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(args, **kwargs)  # Explicit user-triggered detached process.
    proc = psutil.Process(process.pid)
    record = {
        "version": 1,
        "recorded_at": now_iso(),
        "run_id": run_id,
        "state": "running",
        "pid": process.pid,
        "process_created_at": proc.create_time(),
        "completion_path": str(completion),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "exit_code": None,
    }
    append_runtime_event(config, record)
    return record


def refresh_worker(base: Path, run_id: str) -> dict[str, object]:
    config = load_config(base)
    get_external_agent_run(config, run_id)
    latest = runtime_event_for_run(config, run_id)
    if latest is None:
        raise ValueError(f"external run {run_id} has not been started")
    if str(latest.get("state")) in TERMINAL_RUNTIME_STATES:
        return latest
    completion = Path(str(latest.get("completion_path", "")))
    if completion.exists():
        data = read_json(completion, {})
        if not isinstance(data, dict) or not isinstance(data.get("exit_code"), int):
            raise ValueError(f"worker completion manifest is invalid for {run_id}")
        exit_code = int(data["exit_code"])
        record = {**latest, "recorded_at": now_iso(), "state": "completed" if exit_code == 0 else "failed", "exit_code": exit_code, "finished_at": data.get("finished_at", now_iso()), "error": data.get("error", "")}
        append_runtime_event(config, record)
        return record
    try:
        process = psutil.Process(int(latest["pid"]))
        is_same_process = abs(process.create_time() - float(latest["process_created_at"])) < 0.01
        if process.is_running() and is_same_process:
            return latest
    except (psutil.Error, KeyError, TypeError, ValueError):
        pass
    record = {**latest, "recorded_at": now_iso(), "state": "lost", "exit_code": None, "error": "worker process ended without a completion manifest"}
    append_runtime_event(config, record)
    return record


def cancel_worker(base: Path, run_id: str, note: str) -> dict[str, object]:
    config = load_config(base)
    latest = refresh_worker(base, run_id)
    if str(latest.get("state")) in TERMINAL_RUNTIME_STATES:
        raise ValueError(f"external run {run_id} is already {latest.get('state')}")
    try:
        process = psutil.Process(int(latest["pid"]))
        if abs(process.create_time() - float(latest["process_created_at"])) >= 0.01:
            raise ValueError(f"worker process identity no longer matches for {run_id}")
        children = process.children(recursive=True)
        for child in children:
            child.terminate()
        process.terminate()
        _, alive = psutil.wait_procs(children + [process], timeout=5)
        for child in alive:
            child.kill()
    except psutil.NoSuchProcess:
        pass
    record = {**latest, "recorded_at": now_iso(), "state": "canceled", "finished_at": now_iso(), "operator_note": note, "exit_code": None}
    append_runtime_event(config, record)
    return record


def _is_allowed(path: str) -> bool:
    return path in ALLOWED_MUTABLE_PATHS or path.startswith("src/") or path.startswith("tests/")


def _snapshot_changes(base: Path, snapshot: dict[str, object]) -> tuple[list[dict[str, str]], str]:
    root = Path(str(snapshot["path"]))
    before = snapshot.get("files", {})
    if not isinstance(before, dict):
        raise ValueError("worker snapshot manifest has invalid file hashes")
    after = {path.relative_to(root).as_posix(): _hash_file(path) for path in _files(root) if path.name != "snapshot_manifest.json"}
    paths = sorted(set(before) | set(after))
    changes: list[dict[str, str]] = []
    chunks: list[str] = []
    for relative in paths:
        old = before.get(relative)
        new = after.get(relative)
        if old == new:
            continue
        if old is None:
            kind = "added"
        elif new is None:
            kind = "deleted"
        else:
            kind = "modified"
        changes.append({"path": relative, "kind": kind})
        old_text = (base / relative).read_text(encoding="utf-8", errors="replace") if old is not None else ""
        new_text = (root / relative).read_text(encoding="utf-8", errors="replace") if new is not None else ""
        chunks.extend(difflib.unified_diff(old_text.splitlines(keepends=True), new_text.splitlines(keepends=True), fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    return changes, "".join(chunks)


def render_evaluations(records: list[dict[str, object]]) -> str:
    lines = ["# Worker Evaluations", ""]
    if not records:
        return "\n".join(lines + ["No worker evaluations recorded yet.", ""])
    for record in records[-80:]:
        lines.append(f"- `{record.get('evaluation_id', '')}` run=`{record.get('run_id', '')}` status={record.get('status', '')}")
    return "\n".join(lines) + "\n"


def evaluate_worker(base: Path, run_id: str) -> dict[str, object]:
    ensure_source_checkout(base)
    config = load_config(base)
    runtime = refresh_worker(base, run_id)
    snapshot = get_worker_snapshot(config, run_id)
    evaluations = _load_jsonl(_evaluations_path(config))
    evaluation_id = f"E{len(evaluations) + 1:03d}"
    status = "ineligible"
    reason = "worker did not complete successfully"
    changes: list[dict[str, str]] = []
    patch_path = ""
    test_exit_code: int | None = None
    test_log = config.workspace / "logs" / f"worker-{_safe_id(run_id)}.tests.log"
    if runtime.get("state") == "completed" and runtime.get("exit_code") == 0:
        if str(snapshot.get("source_fingerprint", "")) != source_fingerprint(base):
            reason = "parent source changed after snapshot creation"
        else:
            changes, patch = _snapshot_changes(base, snapshot)
        forbidden = [change["path"] for change in changes if not _is_allowed(change["path"])]
        deleted = [change["path"] for change in changes if change["kind"] == "deleted"]
        if reason != "parent source changed after snapshot creation" and not changes:
            reason = "worker produced no source changes"
        elif reason != "parent source changed after snapshot creation" and (forbidden or deleted):
            reason = "worker changed forbidden paths: " + ", ".join(forbidden + deleted)
        elif reason != "parent source changed after snapshot creation":
            result = subprocess.run([sys.executable, "-m", "pytest"], cwd=str(snapshot["path"]), text=True, capture_output=True, check=False)
            test_log.parent.mkdir(parents=True, exist_ok=True)
            write_text(test_log, result.stdout + result.stderr)
            test_exit_code = result.returncode
            if result.returncode == 0:
                patch_target = config.workspace / "evolution_patches" / f"{evaluation_id}.patch"
                write_text(patch_target, patch)
                patch_path = str(patch_target)
                status, reason = "passed", "snapshot changes and tests passed"
            else:
                status, reason = "failed", "snapshot test suite failed"
    record: dict[str, object] = {"version": 1, "evaluation_id": evaluation_id, "evaluated_at": now_iso(), "run_id": run_id, "runtime_state": runtime.get("state"), "status": status, "reason": reason, "snapshot_path": snapshot.get("path"), "source_fingerprint": snapshot.get("source_fingerprint"), "changes": changes, "patch_path": patch_path, "patch_sha256": _hash_file(Path(patch_path)) if patch_path else "", "test_command": f"{sys.executable} -m pytest", "test_exit_code": test_exit_code, "test_log": str(test_log) if test_exit_code is not None else ""}
    _append_jsonl(_evaluations_path(config), record)
    write_text(config.workspace / "worker_evaluations.md", render_evaluations(_load_jsonl(_evaluations_path(config))))
    return record


def _load_proposals(config) -> list[dict[str, object]]:
    proposals = read_json(_proposals_path(config), [])
    if not isinstance(proposals, list):
        raise ValueError("evolution_proposals.json must be a list")
    return [proposal for proposal in proposals if isinstance(proposal, dict)]


def render_proposals(proposals: list[dict[str, object]]) -> str:
    lines = ["# Evolution Proposals", ""]
    if not proposals:
        return "\n".join(lines + ["No evolution proposals recorded yet.", ""])
    for proposal in proposals:
        lines.append(f"- `{proposal.get('proposal_id', '')}` status={proposal.get('status', '')} evaluation=`{proposal.get('evaluation_id', '')}`")
    return "\n".join(lines) + "\n"


def plan_evolution(base: Path) -> list[dict[str, object]]:
    ensure_source_checkout(base)
    config = load_config(base)
    proposals = _load_proposals(config)
    existing = {str(proposal.get("evaluation_id", "")) for proposal in proposals}
    feedback = read_json(config.workspace / "supervisor_feedback.json", {})
    recommendations = feedback.get("recommendations", []) if isinstance(feedback, dict) else []
    rationale = str(recommendations[0].get("reason", "passed isolated worker evaluation")) if recommendations and isinstance(recommendations[0], dict) else "passed isolated worker evaluation"
    for evaluation in _load_jsonl(_evaluations_path(config)):
        if evaluation.get("status") != "passed" or str(evaluation.get("evaluation_id", "")) in existing:
            continue
        proposal_id = f"P{len(proposals) + 1:03d}"
        proposals.append({"version": 1, "proposal_id": proposal_id, "created_at": now_iso(), "status": "proposed", "evaluation_id": evaluation.get("evaluation_id"), "run_id": evaluation.get("run_id"), "source_fingerprint": evaluation.get("source_fingerprint"), "patch_path": evaluation.get("patch_path"), "patch_sha256": evaluation.get("patch_sha256"), "changes": evaluation.get("changes", []), "test_command": evaluation.get("test_command"), "test_exit_code": evaluation.get("test_exit_code"), "rationale": rationale, "note": ""})
    write_json(_proposals_path(config), proposals)
    write_text(config.workspace / "evolution_proposals.md", render_proposals(proposals))
    return proposals


def get_proposal(config, proposal_id: str) -> dict[str, object]:
    for proposal in _load_proposals(config):
        if proposal.get("proposal_id") == proposal_id:
            return proposal
    raise ValueError(f"unknown evolution proposal {proposal_id}")


def _update_proposal(config, proposal_id: str, status: str, note: str) -> dict[str, object]:
    proposals = _load_proposals(config)
    for proposal in proposals:
        if proposal.get("proposal_id") == proposal_id:
            if proposal.get("status") != "proposed":
                raise ValueError(f"evolution proposal {proposal_id} is already {proposal.get('status')}")
            proposal["status"] = status
            proposal["note"] = note
            proposal[f"{status}_at"] = now_iso()
            write_json(_proposals_path(config), proposals)
            write_text(config.workspace / "evolution_proposals.md", render_proposals(proposals))
            return proposal
    raise ValueError(f"unknown evolution proposal {proposal_id}")


def approve_evolution(base: Path, proposal_id: str, note: str) -> dict[str, object]:
    if not note.strip():
        raise ValueError("evolution approval requires a note")
    config = load_config(base)
    proposal = get_proposal(config, proposal_id)
    if proposal.get("test_exit_code") != 0:
        raise ValueError(f"evolution proposal {proposal_id} has not passed evaluation")
    return _update_proposal(config, proposal_id, "approved", note)


def reject_evolution(base: Path, proposal_id: str, note: str) -> dict[str, object]:
    if not note.strip():
        raise ValueError("evolution rejection requires a note")
    return _update_proposal(load_config(base), proposal_id, "rejected", note)


def apply_evolution(base: Path, proposal_id: str) -> dict[str, object]:
    ensure_source_checkout(base)
    config = load_config(base)
    proposal = get_proposal(config, proposal_id)
    if proposal.get("status") != "approved":
        raise ValueError(f"evolution proposal {proposal_id} is not approved")
    if str(proposal.get("source_fingerprint", "")) != source_fingerprint(base):
        raise ValueError(f"evolution proposal {proposal_id} is stale against the current source tree")
    patch = Path(str(proposal.get("patch_path", "")))
    if not patch.exists() or _hash_file(patch) != proposal.get("patch_sha256"):
        raise ValueError(f"evolution proposal {proposal_id} has an invalid patch artifact")
    snapshot = get_worker_snapshot(config, str(proposal.get("run_id", "")))
    root = Path(str(snapshot["path"]))
    changes = proposal.get("changes", [])
    if not isinstance(changes, list) or not changes:
        raise ValueError(f"evolution proposal {proposal_id} has no applicable changes")
    backup = config.workspace / "backups" / "evolution" / f"{_safe_id(proposal_id)}-{now_iso().replace(':', '')}"
    backup.mkdir(parents=True, exist_ok=True)
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError(f"evolution proposal {proposal_id} has an invalid change")
        relative = str(change.get("path", ""))
        if not _is_allowed(relative) or change.get("kind") == "deleted":
            raise ValueError(f"evolution proposal {proposal_id} contains a forbidden change: {relative}")
        source = root / relative
        target = base / relative
        if not source.exists():
            raise ValueError(f"evolution proposal {proposal_id} snapshot file is missing: {relative}")
        if target.exists():
            backup_target = backup / relative
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    proposals = _load_proposals(config)
    for item in proposals:
        if item.get("proposal_id") == proposal_id:
            item["status"] = "applied"
            item["applied_at"] = now_iso()
            item["backup_path"] = str(backup)
    write_json(_proposals_path(config), proposals)
    write_text(config.workspace / "evolution_proposals.md", render_proposals(proposals))
    return get_proposal(config, proposal_id)


__all__ = [
    "append_runtime_event", "apply_evolution", "approve_evolution", "cancel_worker", "create_worker_snapshot",
    "ensure_source_checkout", "evaluate_worker", "get_proposal", "get_worker_snapshot", "latest_runtime_events",
    "plan_evolution", "refresh_worker", "reject_evolution", "render_evaluations", "render_proposals",
    "render_runtime_events", "render_snapshots", "runtime_event_for_run", "source_fingerprint", "start_worker",
]
