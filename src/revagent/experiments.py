"""Experiment manifest, artifact hash, and incorporation-state public API."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from pathlib import Path

from ._models import Config
from ._utils import append_decision_log, find_item, first_sentence, load_config, load_items, now_iso, read_json, read_text, write_items, write_json, write_text
from .reviews import experiment_lane_template

def detect_experiment_assets(tex_root: Path) -> list[dict[str, str]]:
    roots = [tex_root / name for name in ("scripts", "experiments", "notebooks", "results")]
    assets = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                assets.append({"kind": root.name, "path": str(path.relative_to(tex_root))})
                if len(assets) >= 40:
                    return assets
    return assets

def render_experiment_plan(items: list[dict], tex_root: Path) -> str:
    experiment_items = [item for item in items if item["kind"] == "experiment"]
    assets = detect_experiment_assets(tex_root)
    lines = ["# Experiment Plan", ""]
    lines.extend(["## Detected Assets", ""])
    if assets:
        lines.extend(f"- `{asset['path']}` ({asset['kind']})" for asset in assets)
    else:
        lines.append("- No scripts, experiments, notebooks, or results directories detected.")
    lines.append("")
    if not experiment_items:
        lines.append("No experiment-related review items were detected.")
        return "\n".join(lines) + "\n"
    for item in experiment_items:
        lane = item.get("experiment_lane") or experiment_lane_template(item["comment"])
        lines.extend(
            [
                f"## {item['id']}",
                "",
                f"Reviewer concern: {first_sentence(item['comment'])}",
                "",
                "Executable plan fields:",
                f"- Command: {lane.get('command') or 'TBD'}",
                f"- Parameters: {json.dumps(lane.get('parameters', {}), ensure_ascii=False)}",
                f"- Seed: {lane.get('seed') or 'TBD'}",
                f"- Expected artifacts: {', '.join(lane.get('expected_artifacts', [])) or 'TBD'}",
                f"- Paper figure/table locations: {', '.join(lane.get('paper_locations', [])) or 'TBD'}",
                "- Result backfill fields: observed_result, figure_or_table_update, response_text",
                "",
                "Execution boundary:",
                "- Do not run experiments from this plan until the author approves the command and environment.",
                "- Fill conclusions only from observed results, never from reviewer expectations.",
                "",
            ]
        )
    return "\n".join(lines)

def experiment_plan_for_item(base: Path, item_id: str | None = None) -> str:
    config = load_config(base)
    items = load_items(config)
    experiment_items = [item for item in items if item.get("kind") == "experiment"]
    if item_id:
        experiment_items = [item for item in experiment_items if item.get("id") == item_id]
        if not experiment_items:
            raise ValueError(f"unknown experiment item {item_id}")
    assets = detect_experiment_assets(config.tex_root)
    lines = ["# Experiment Command Plan", "", "## Detected Assets", ""]
    lines.extend(f"- `{asset['path']}` ({asset['kind']})" for asset in assets) if assets else lines.append("- None detected.")
    for item in experiment_items:
        lane = item.get("experiment_lane") or experiment_lane_template(item["comment"])
        lines.extend(
            [
                "",
                f"## {item['id']}",
                "",
                f"- Reviewer concern: {first_sentence(item['comment'])}",
                f"- Command: {lane.get('command') or 'TBD'}",
                f"- CWD: {lane.get('cwd') or str(config.tex_root)}",
                f"- Parameters: {json.dumps(lane.get('parameters', {}), ensure_ascii=False)}",
                f"- Seed: {lane.get('seed') or 'TBD'}",
                f"- Expected artifacts: {', '.join(lane.get('expected_artifacts', [])) or 'TBD'}",
                f"- Observed artifacts: {', '.join(lane.get('observed_artifacts', [])) or 'none recorded'}",
                f"- Result status: {lane.get('result_status', 'not_recorded')}",
                "",
                "Execution boundary: this command plan is not executed by RevAgent.",
            ]
        )
    append_decision_log(config, "Experiment plan generated", [f"- Items: {', '.join(item['id'] for item in experiment_items) or 'none'}"])
    return "\n".join(lines) + "\n"

def load_experiment_manifests(config: Config) -> dict[str, dict]:
    return read_json(config.workspace / "experiment_manifests.json", {})

def write_experiment_manifests(config: Config, manifests: dict[str, dict]) -> None:
    write_json(config.workspace / "experiment_manifests.json", manifests)
    write_text(config.workspace / "experiment_manifests.md", render_experiment_manifests(manifests))

def experiment_run_attempts_path(config: Config) -> Path:
    return config.workspace / "experiment_run_attempts.jsonl"

def load_experiment_run_attempts(config: Config) -> list[dict[str, object]]:
    path = experiment_run_attempts_path(config)
    if not path.exists():
        return []
    attempts = []
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            attempts.append(json.loads(line))
        except json.JSONDecodeError:
            attempts.append({"status": "invalid", "raw": line})
    return attempts

def render_experiment_run_attempts(attempts: list[dict[str, object]]) -> str:
    lines = ["# Experiment Run Attempts", ""]
    if not attempts:
        lines.append("No experiment run attempts recorded yet.")
        return "\n".join(lines) + "\n"
    for attempt in attempts[-80:]:
        lines.append(
            f"- `{attempt.get('attempt_id', '')}` {attempt.get('status', '')} "
            f"item={attempt.get('item_id', '')} exit={attempt.get('exit_code', '')} "
            f"command=`{attempt.get('command', '')}`"
        )
        if attempt.get("stdout_log"):
            lines.append(f"  stdout: `{attempt['stdout_log']}`")
        if attempt.get("stderr_log"):
            lines.append(f"  stderr: `{attempt['stderr_log']}`")
        detected = attempt.get("detected_artifacts", [])
        if detected:
            lines.append("  artifacts: " + ", ".join(f"{item.get('path')}:{str(item.get('sha256', ''))[:12]}" for item in detected))
        if attempt.get("error"):
            lines.append(f"  error: {attempt['error']}")
    return "\n".join(lines) + "\n"

def append_experiment_run_attempt(config: Config, attempt: dict[str, object]) -> None:
    path = experiment_run_attempts_path(config)
    existing = read_text(path) if path.exists() else ""
    write_text(path, existing + json.dumps(attempt, ensure_ascii=False, sort_keys=True) + "\n")
    write_text(config.workspace / "experiment_run_attempts.md", render_experiment_run_attempts(load_experiment_run_attempts(config)))

def next_attempt_id(attempts: list[dict[str, object]]) -> str:
    numbers = []
    for attempt in attempts:
        attempt_id = str(attempt.get("attempt_id", ""))
        if attempt_id.startswith("X") and attempt_id[1:].isdigit():
            numbers.append(int(attempt_id[1:]))
    return f"X{(max(numbers) if numbers else 0) + 1:03d}"

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def experiment_protocol_issues(manifest: dict[str, object]) -> list[str]:
    """Check auditability of an experiment protocol, never its scientific outcome."""
    issues: list[str] = []
    if not isinstance(manifest.get("comparators"), list) or not manifest["comparators"]:
        issues.append("comparators are not declared")
    if not isinstance(manifest.get("fairness_rules"), list) or not manifest["fairness_rules"]:
        issues.append("baseline fairness rules are not declared")
    discretization = manifest.get("discretization")
    required = ("grid", "time_step", "error_metric", "stopping_criterion")
    if not isinstance(discretization, dict) or any(not str(discretization.get(key, "")).strip() for key in required):
        issues.append("grid, time step, error metric, and stopping criterion are required")
    try:
        repetitions = int(manifest.get("repetitions", 0))
    except (TypeError, ValueError):
        repetitions = 0
    if repetitions < 2:
        issues.append("at least two repeated trials are required")
    if not str(manifest.get("uncertainty_method", "")).strip():
        issues.append("uncertainty method is not declared")
    if not str(manifest.get("hardware", "")).strip():
        issues.append("hardware description is not declared")
    return issues

def build_experiment_manifest(config: Config, item: dict) -> dict[str, object]:
    lane = item.get("experiment_lane") or experiment_lane_template(item.get("comment", ""))
    manifest_id = lane.get("manifest_id") or item["id"]
    artifacts = []
    artifact_hashes = dict(lane.get("artifact_hashes", {}))
    for record in lane.get("recorded_results", []):
        artifact = str(record.get("artifact", ""))
        artifact_path = (config.tex_root / artifact).resolve()
        artifact_hash = file_sha256(artifact_path) if artifact and artifact_path.exists() else artifact_hashes.get(artifact, "")
        if artifact:
            artifact_hashes[artifact] = artifact_hash
            artifacts.append(
                {
                    "path": artifact,
                    "kind": record.get("kind", "data"),
                    "note": record.get("note", ""),
                    "sha256": artifact_hash,
                    "recorded_at": record.get("recorded_at", ""),
                }
            )
    status = lane.get("contract_status") or "not_planned"
    if lane.get("backfill_targets"):
        status = "incorporated"
    elif artifacts or lane.get("result_status") == "recorded":
        status = "artifact_recorded"
    elif status == "not_planned":
        status = "planned"
    return {
        "id": manifest_id,
        "item_id": item["id"],
        "status": status,
        "command_template": lane.get("command_template") or lane.get("command", ""),
        "cwd": lane.get("cwd") or str(config.tex_root),
        "parameters": lane.get("parameters", {}),
        "seed": lane.get("seed", ""),
        "expected_artifacts": lane.get("expected_artifacts", []),
        "artifacts": artifacts,
        "artifact_hashes": artifact_hashes,
        "backfill_targets": lane.get("backfill_targets", []),
        "reviewer_request": lane.get("reviewer_request") or first_sentence(item.get("comment", "")),
        "comparators": lane.get("comparators", []),
        "fairness_rules": lane.get("fairness_rules", []),
        "discretization": lane.get("discretization", {}),
        "repetitions": lane.get("repetitions", 0),
        "uncertainty_method": lane.get("uncertainty_method", ""),
        "hardware": lane.get("hardware", ""),
        "protocol_status": "incomplete",
        "updated_at": now_iso(),
    }

def sync_experiment_lane_from_manifest(item: dict, manifest: dict[str, object]) -> None:
    lane = item.get("experiment_lane") or experiment_lane_template(item.get("comment", ""))
    lane["manifest_id"] = manifest["id"]
    lane["command_template"] = manifest.get("command_template", "")
    lane["command"] = lane.get("command") or manifest.get("command_template", "")
    lane["cwd"] = manifest.get("cwd", lane.get("cwd", ""))
    lane["parameters"] = manifest.get("parameters", {})
    lane["seed"] = manifest.get("seed", "")
    lane["expected_artifacts"] = manifest.get("expected_artifacts", [])
    lane["artifact_hashes"] = manifest.get("artifact_hashes", {})
    lane["backfill_targets"] = manifest.get("backfill_targets", [])
    for key in ("comparators", "fairness_rules", "discretization", "repetitions", "uncertainty_method", "hardware", "protocol_status"):
        lane[key] = manifest.get(key, lane.get(key))
    lane["contract_status"] = manifest.get("status", "planned")
    if manifest.get("artifacts"):
        lane["result_status"] = "recorded"
        lane["observed_artifacts"] = [artifact["path"] for artifact in manifest.get("artifacts", [])]
        lane["recorded_results"] = [
            {
                "item_id": item["id"],
                "artifact": artifact["path"],
                "kind": artifact.get("kind", "data"),
                "note": artifact.get("note", ""),
                "status": "recorded",
                "recorded_at": artifact.get("recorded_at", ""),
            }
            for artifact in manifest.get("artifacts", [])
        ]
    item["experiment_lane"] = lane

def render_experiment_manifest(manifest: dict[str, object]) -> str:
    lines = [
        f"# Experiment Manifest {manifest['item_id']}",
        "",
        f"- Status: {manifest.get('status')}",
        f"- Command: {manifest.get('command_template') or 'TBD'}",
        f"- CWD: {manifest.get('cwd') or 'TBD'}",
        f"- Seed: {manifest.get('seed') or 'TBD'}",
        f"- Parameters: {json.dumps(manifest.get('parameters', {}), ensure_ascii=False)}",
        f"- Expected artifacts: {', '.join(manifest.get('expected_artifacts', [])) or 'TBD'}",
        f"- Comparators: {', '.join(manifest.get('comparators', [])) or 'TBD'}",
        f"- Fairness rules: {', '.join(manifest.get('fairness_rules', [])) or 'TBD'}",
        f"- Repetitions: {manifest.get('repetitions', 0) or 'TBD'}; uncertainty: {manifest.get('uncertainty_method') or 'TBD'}",
        f"- Protocol status: {manifest.get('protocol_status', 'incomplete')}",
        "",
        "## Artifacts",
        "",
    ]
    artifacts = manifest.get("artifacts", [])
    lines.extend(f"- `{artifact['path']}` ({artifact.get('kind', 'data')}) sha256={artifact.get('sha256') or 'missing'}" for artifact in artifacts) if artifacts else lines.append("- None.")
    lines.extend(["", "## Backfill Targets", ""])
    backfills = manifest.get("backfill_targets", [])
    lines.extend(f"- `{target['target']}` {target['field']}: {target['text']}" for target in backfills) if backfills else lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"

def render_experiment_manifests(manifests: dict[str, dict]) -> str:
    if not manifests:
        return "# Experiment Manifests\n\nNo experiment manifests generated yet.\n"
    return "# Experiment Manifests\n\n" + "\n".join(render_experiment_manifest(manifests[key]).strip() for key in sorted(manifests)) + "\n"

def experiment_contract(base: Path, item_id: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    manifest = build_experiment_manifest(config, item)
    manifest["protocol_status"] = "complete" if not experiment_protocol_issues(manifest) else "incomplete"
    sync_experiment_lane_from_manifest(item, manifest)
    write_items(config, items)
    manifests = load_experiment_manifests(config)
    manifests[item_id] = manifest
    write_experiment_manifests(config, manifests)
    append_decision_log(config, f"Experiment contract planned for {item_id}", [f"- Status: {manifest['status']}"])
    return manifest

def experiment_artifact(base: Path, item_id: str, artifact_path: str, kind: str, note: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    path = (config.tex_root / artifact_path).resolve()
    if config.tex_root.resolve() not in path.parents or not path.is_file():
        raise ValueError(f"experiment artifact must be an existing file inside the project: {artifact_path}")
    manifests = load_experiment_manifests(config)
    manifest = manifests.get(item_id) or build_experiment_manifest(config, item)
    artifact_hash = file_sha256(path)
    artifact = {
        "path": artifact_path,
        "kind": kind,
        "note": note,
        "sha256": artifact_hash,
        "recorded_at": now_iso(),
    }
    manifest.setdefault("artifacts", [])
    manifest["artifacts"] = [entry for entry in manifest["artifacts"] if entry.get("path") != artifact_path] + [artifact]
    manifest.setdefault("artifact_hashes", {})[artifact_path] = artifact_hash
    manifest["status"] = "artifact_recorded"
    manifest["updated_at"] = now_iso()
    manifests[item_id] = manifest
    sync_experiment_lane_from_manifest(item, manifest)
    if item.get("planning_status") not in {"incorporated", "closed"}:
        item["planning_status"] = "evidence_ready"
    write_items(config, items)
    write_experiment_manifests(config, manifests)
    log_path = config.workspace / "experiment_runs.jsonl"
    record = {"item_id": item_id, "artifact": artifact_path, "kind": kind, "note": note, "sha256": artifact_hash, "status": "recorded", "recorded_at": artifact["recorded_at"]}
    write_text(log_path, (read_text(log_path) if log_path.exists() else "") + json.dumps(record, ensure_ascii=False) + "\n")
    append_decision_log(config, f"Experiment artifact recorded for {item_id}", [f"- Artifact: {artifact_path}", f"- SHA256: {artifact_hash}"])
    return artifact

def experiment_incorporate(base: Path, item_id: str, target: str, field: str, text_file: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    manifests = load_experiment_manifests(config)
    manifest = manifests.get(item_id) or build_experiment_manifest(config, item)
    text = read_text((base / text_file).resolve()).rstrip()
    backfill = {"target": target, "field": field, "text": text, "recorded_at": now_iso()}
    manifest.setdefault("backfill_targets", []).append(backfill)
    manifest["status"] = "incorporated"
    manifest["updated_at"] = now_iso()
    manifests[item_id] = manifest
    sync_experiment_lane_from_manifest(item, manifest)
    item["planning_status"] = "incorporated"
    write_items(config, items)
    write_experiment_manifests(config, manifests)
    append_decision_log(config, f"Experiment backfill incorporated for {item_id}", [f"- Target: {target}", f"- Field: {field}"])
    return backfill

def require_experiment_manifest(base: Path, item_id: str) -> tuple[Config, list[dict], dict, dict]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    manifests = load_experiment_manifests(config)
    manifest = manifests.get(item_id) or build_experiment_manifest(config, item)
    return config, items, item, manifest

def manifest_cwd(config: Config, manifest: dict[str, object]) -> Path:
    raw = str(manifest.get("cwd") or config.tex_root)
    path = Path(raw)
    if not path.is_absolute():
        path = config.tex_root / path
    return path.resolve()

def expected_artifact_status(config: Config, manifest: dict[str, object]) -> list[dict[str, object]]:
    artifacts = []
    for rel in manifest.get("expected_artifacts", []):
        rel_text = str(rel)
        path = (config.tex_root / rel_text).resolve()
        exists = config.tex_root.resolve() in path.parents and path.exists()
        artifacts.append(
            {
                "path": rel_text,
                "exists": exists,
                "sha256": file_sha256(path) if exists and path.is_file() else "",
            }
        )
    return artifacts

def experiment_run_preview(base: Path, item_id: str) -> dict[str, object]:
    config, _, _, manifest = require_experiment_manifest(base, item_id)
    command = str(manifest.get("command_template", "")).strip()
    cwd = manifest_cwd(config, manifest)
    return {
        "item_id": item_id,
        "mode": "dry_run",
        "ready": bool(command) and cwd.exists(),
        "command": command,
        "cwd": str(cwd),
        "expected_artifacts": expected_artifact_status(config, manifest),
        "stdout_log": str(config.workspace / "logs" / "experiments" / f"{item_id}-ATTEMPT.stdout.log"),
        "stderr_log": str(config.workspace / "logs" / "experiments" / f"{item_id}-ATTEMPT.stderr.log"),
        "issues": ([] if command else ["experiment manifest has no command_template"]) + ([] if cwd.exists() else [f"experiment cwd does not exist: {cwd}"]),
    }

def render_experiment_run_preview(preview: dict[str, object]) -> str:
    lines = [
        "# Experiment Run Preview",
        "",
        f"- Item: {preview.get('item_id', '')}",
        f"- Ready: {str(preview.get('ready', False)).lower()}",
        f"- Command: `{preview.get('command', '') or 'TBD'}`",
        f"- CWD: `{preview.get('cwd', '')}`",
        f"- Stdout log: `{preview.get('stdout_log', '')}`",
        f"- Stderr log: `{preview.get('stderr_log', '')}`",
        "",
        "## Expected Artifacts",
        "",
    ]
    artifacts = preview.get("expected_artifacts", [])
    if artifacts:
        for artifact in artifacts:
            state = "present" if artifact.get("exists") else "missing"
            lines.append(f"- `{artifact.get('path', '')}` {state} sha256={artifact.get('sha256') or '-'}")
    else:
        lines.append("- None configured.")
    if preview.get("issues"):
        lines.extend(["", "## Issues", ""])
        lines.extend(f"- {issue}" for issue in preview.get("issues", []))
    return "\n".join(lines).rstrip() + "\n"

def experiment_run_record(base: Path, item_id: str) -> dict[str, object]:
    config, items, item, manifest = require_experiment_manifest(base, item_id)
    preview = experiment_run_preview(base, item_id)
    if not preview["ready"]:
        raise ValueError("; ".join(preview["issues"]))
    attempts = load_experiment_run_attempts(config)
    attempt_id = next_attempt_id(attempts)
    log_dir = config.workspace / "logs" / "experiments"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_rel = str(Path("logs") / "experiments" / f"{item_id}-{attempt_id}.stdout.log")
    stderr_rel = str(Path("logs") / "experiments" / f"{item_id}-{attempt_id}.stderr.log")
    stdout_path = config.workspace / stdout_rel
    stderr_path = config.workspace / stderr_rel
    command = str(manifest.get("command_template", "")).strip()
    cwd = Path(str(preview["cwd"]))
    started_at = now_iso()
    error = ""
    try:
        result = subprocess.run(
            shlex.split(command),
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        exit_code = result.returncode
        write_text(stdout_path, result.stdout)
        write_text(stderr_path, result.stderr)
    except Exception as exc:
        exit_code = -1
        error = str(exc)
        write_text(stdout_path, "")
        write_text(stderr_path, error)
    finished_at = now_iso()
    detected = expected_artifact_status(config, manifest)
    attempt = {
        "attempt_id": attempt_id,
        "item_id": item_id,
        "status": "succeeded" if exit_code == 0 else "failed",
        "command": command,
        "cwd": str(cwd),
        "exit_code": exit_code,
        "stdout_log": stdout_rel,
        "stderr_log": stderr_rel,
        "started_at": started_at,
        "finished_at": finished_at,
        "detected_artifacts": detected,
        "error": error,
    }
    append_experiment_run_attempt(config, attempt)
    if exit_code == 0:
        # An exit code and generated file are execution evidence only.  They
        # are not an interpreted result and cannot satisfy a result gate.
        manifest["last_attempt_id"] = attempt_id
        manifest["last_attempt_status"] = "executed_not_interpreted"
        manifest["updated_at"] = now_iso()
        manifests = load_experiment_manifests(config)
        manifests[item_id] = manifest
        write_experiment_manifests(config, manifests)
    append_decision_log(config, f"Experiment run recorded for {item_id}", [f"- Attempt: {attempt_id}", f"- Exit code: {exit_code}"])
    return attempt

def record_experiment_result(base: Path, item_id: str, artifact: str, note: str) -> dict[str, object]:
    config = load_config(base)
    items = load_items(config)
    item = find_item(items, item_id)
    if item is None or item.get("kind") != "experiment":
        raise ValueError(f"unknown experiment item {item_id}")
    lane = item.get("experiment_lane") or experiment_lane_template(item["comment"])
    record = {
        "item_id": item_id,
        "artifact": artifact,
        "note": note,
        "status": "recorded",
        "recorded_at": now_iso(),
    }
    lane.setdefault("recorded_results", []).append(record)
    lane.setdefault("observed_artifacts", []).append(artifact)
    lane["result_status"] = "recorded"
    item["experiment_lane"] = lane
    if item.get("planning_status") not in {"incorporated", "closed"}:
        item["planning_status"] = "evidence_ready"
    manifest = build_experiment_manifest(config, item)
    manifests = load_experiment_manifests(config)
    manifests[item_id] = manifest
    sync_experiment_lane_from_manifest(item, manifest)
    write_items(config, items)
    write_experiment_manifests(config, manifests)
    log_path = config.workspace / "experiment_runs.jsonl"
    write_text(log_path, (read_text(log_path) if log_path.exists() else "") + json.dumps(record, ensure_ascii=False) + "\n")
    append_decision_log(config, f"Experiment result recorded for {item_id}", [f"- Artifact: {artifact}", f"- Note: {note}"])
    return record

__all__ = [
    "build_experiment_manifest",
    "experiment_artifact",
    "experiment_contract",
    "experiment_protocol_issues",
    "experiment_incorporate",
    "experiment_plan_for_item",
    "experiment_run_preview",
    "experiment_run_record",
    "file_sha256",
    "load_experiment_manifests",
    "load_experiment_run_attempts",
    "record_experiment_result",
    "render_experiment_manifests",
    "render_experiment_plan",
    "render_experiment_run_attempts",
    "render_experiment_run_preview",
    "write_experiment_manifests",
]
