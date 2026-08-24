"""Persistent local runtime for advancing a manuscript review project safely."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from typing import Any

import psutil

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .latex import tex_files
from .planning import plan_item
from .review_analysis import analyze_review_item, load_review_analyses
from .revision_spec import validate_revision_spec
from .actor_bundle import validate_actor_bundle
from .reviewer_report import validate_reviewer_report

RUNTIME_TASKS = ("analyze_review", "plan_review_item", "collect_evidence")
TERMINAL_TASKS = {"done", "blocked", "canceled", "failed"}
CYCLE_STATUSES = {"draft", "planned", "acted", "returned", "blocked", "awaiting_author_gate", "author_approved"}
MAX_CYCLE_ARTIFACT_BYTES = 1024 * 1024


def runtime_path(base: Path) -> Path:
    return load_config(base).workspace / "runtime.sqlite3"


def _connect(base: Path) -> sqlite3.Connection:
    path = runtime_path(base)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
          task_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, kind TEXT NOT NULL,
          status TEXT NOT NULL, dependencies TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          worker TEXT NOT NULL DEFAULT '', lease_until TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
          recorded_at TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS remote_consents (
          consent_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, provider TEXT NOT NULL,
          model TEXT NOT NULL, purpose TEXT NOT NULL, artifact_classes TEXT NOT NULL,
          expires_at TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS author_gates (
          gate_id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, kind TEXT NOT NULL,
          status TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence (
          item_id TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
          locator TEXT NOT NULL, sha256 TEXT NOT NULL DEFAULT '', recorded_at TEXT NOT NULL,
          PRIMARY KEY (item_id, kind, source, locator)
        );
        CREATE TABLE IF NOT EXISTS revision_cycles (
          cycle_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, status TEXT NOT NULL,
          round INTEGER NOT NULL DEFAULT 1, source_fingerprint TEXT NOT NULL,
          planner_id TEXT NOT NULL, actor_id TEXT NOT NULL DEFAULT '', reviewer_id TEXT NOT NULL DEFAULT '',
          plan_sha256 TEXT NOT NULL DEFAULT '', actor_sha256 TEXT NOT NULL DEFAULT '',
          review_sha256 TEXT NOT NULL DEFAULT '', verdict TEXT NOT NULL DEFAULT '',
          invalidated_at TEXT NOT NULL DEFAULT '', invalidation_reason TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS revision_cycle_artifacts (
          artifact_id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id TEXT NOT NULL, role TEXT NOT NULL,
          revision INTEGER NOT NULL, actor_id TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
          path TEXT NOT NULL, sha256 TEXT NOT NULL, recorded_at TEXT NOT NULL,
          UNIQUE(cycle_id, role, revision)
        );
        CREATE TABLE IF NOT EXISTS revision_cycle_events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id TEXT NOT NULL,
          from_status TEXT NOT NULL, to_status TEXT NOT NULL, action TEXT NOT NULL,
          actor_id TEXT NOT NULL, detail TEXT NOT NULL, recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS revision_cycle_author_decisions (
          decision_id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id TEXT NOT NULL,
          action TEXT NOT NULL, author_id TEXT NOT NULL, selected_id TEXT NOT NULL DEFAULT '',
          note TEXT NOT NULL, review_sha256 TEXT NOT NULL, recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS revision_reviewer_sessions (
          session_id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, round INTEGER NOT NULL,
          reviewer_id TEXT NOT NULL, input_fingerprint TEXT NOT NULL, plan_sha256 TEXT NOT NULL,
          actor_sha256 TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(cycle_id, round, reviewer_id)
        );
        CREATE INDEX IF NOT EXISTS revision_cycles_item_status ON revision_cycles(item_id, status);
        CREATE INDEX IF NOT EXISTS revision_cycle_events_cycle ON revision_cycle_events(cycle_id, event_id);
        """
    )
    for statement in ("ALTER TABLE remote_consents ADD COLUMN used_at TEXT NOT NULL DEFAULT ''",):
        try:
            connection.execute(statement)
        except sqlite3.OperationalError:
            pass
    return connection


def _task_id(item_id: str, kind: str) -> str:
    return f"{item_id}:{kind}"


def _render_runtime(base: Path) -> None:
    status = project_status(base)
    config = load_config(base)
    lines = ["# Review Project Runtime", "", f"- Generated at: {now_iso()}", f"- Tasks: {status['counts']}", ""]
    for task in status["tasks"]:
        lines.append(f"- `{task['task_id']}` {task['status']} attempts={task['attempts']}")
    if status["cycles"]:
        lines.extend(["", "## Revision Cycles", ""])
        for cycle in status["cycles"]:
            lines.append(f"- `{cycle['cycle_id']}` item={cycle['item_id']} status={cycle['status']} round={cycle['round']}")
    write_text(config.workspace / "project_runtime.md", "\n".join(lines) + "\n")


def initialize_project_runtime(base: Path) -> dict[str, object]:
    """Import review items into durable task graphs without changing item lifecycle state."""
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    connection = _connect(base)
    created = 0
    now = now_iso()
    try:
        for item in items if isinstance(items, list) else []:
            item_id = str(item.get("id", ""))
            if not item_id:
                continue
            previous = ""
            for kind in RUNTIME_TASKS:
                task_id = _task_id(item_id, kind)
                dependencies = [previous] if previous else []
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO tasks(task_id,item_id,kind,status,dependencies,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (task_id, item_id, kind, "pending", json.dumps(dependencies), now, now),
                )
                created += cursor.rowcount
                previous = task_id
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return {"created": created, "status": project_status(base)}


def _rows(connection: sqlite3.Connection) -> list[dict[str, object]]:
    return [dict(row) | {"dependencies": json.loads(row["dependencies"])} for row in connection.execute("SELECT * FROM tasks ORDER BY task_id")]


def project_status(base: Path) -> dict[str, object]:
    connection = _connect(base)
    try:
        tasks = _rows(connection)
        counts: dict[str, int] = {}
        for task in tasks:
            counts[str(task["status"])] = counts.get(str(task["status"]), 0) + 1
        gates = [dict(row) for row in connection.execute("SELECT * FROM author_gates ORDER BY gate_id DESC")]
        cycles = [dict(row) for row in connection.execute("SELECT * FROM revision_cycles ORDER BY cycle_id")]
        cycle_counts: dict[str, int] = {}
        for cycle in cycles:
            cycle_counts[str(cycle["status"])] = cycle_counts.get(str(cycle["status"]), 0) + 1
        return {"tasks": tasks, "counts": counts, "gates": gates, "paused": _is_paused(connection), "cycles": cycles, "cycle_counts": cycle_counts}
    finally:
        connection.close()


def _is_paused(connection: sqlite3.Connection) -> bool:
    connection.execute("CREATE TABLE IF NOT EXISTS runtime_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = connection.execute("SELECT value FROM runtime_settings WHERE key='paused'").fetchone()
    return bool(row and row["value"] == "true")


def _is_stopped(connection: sqlite3.Connection) -> bool:
    connection.execute("CREATE TABLE IF NOT EXISTS runtime_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = connection.execute("SELECT value FROM runtime_settings WHERE key='stopped'").fetchone()
    return bool(row and row["value"] == "true")


def set_project_paused(base: Path, paused: bool) -> None:
    connection = _connect(base)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS runtime_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO runtime_settings(key,value) VALUES('paused',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("true" if paused else "false",))
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)


def stop_project_service(base: Path) -> None:
    connection = _connect(base)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS runtime_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO runtime_settings(key,value) VALUES('stopped','true') ON CONFLICT(key) DO UPDATE SET value='true'")
        connection.commit()
    finally:
        connection.close()


def recover_project_runtime(base: Path) -> dict[str, object]:
    """Reconcile expired leases after a service crash without bypassing manual gates."""
    connection = _connect(base)
    recovered = []
    now = datetime.now(timezone.utc)
    try:
        for row in connection.execute("SELECT task_id, attempts, lease_until FROM tasks WHERE status='running'"):
            lease = row["lease_until"]
            if not lease or datetime.fromisoformat(lease) > now:
                continue
            status = "pending" if int(row["attempts"]) < 3 else "failed"
            detail = "expired worker lease recovered" if status == "pending" else "expired worker lease exceeded retry budget"
            connection.execute("UPDATE tasks SET status=?, worker='', lease_until='', error=?, updated_at=? WHERE task_id=?", (status, detail, now_iso(), row["task_id"]))
            connection.execute("INSERT INTO task_events(task_id,recorded_at,state,detail) VALUES(?,?,?,?)", (row["task_id"], now_iso(), status, detail))
            recovered.append({"task_id": row["task_id"], "status": status})
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return {"recovered": recovered, "status": project_status(base)}


def service_health(base: Path) -> dict[str, object]:
    config = load_config(base)
    metadata = read_json(config.workspace / "service.json", {})
    pid = int(metadata.get("pid", 0) or 0) if isinstance(metadata, dict) else 0
    process_alive = False
    if pid:
        try:
            process_alive = psutil.Process(pid).is_running()
        except psutil.Error:
            pass
    runtime_ok = runtime_path(base).exists()
    return {"ok": runtime_ok and (not metadata or process_alive or metadata.get("health") == "stopped"), "runtime_db": runtime_ok, "service": metadata, "process_alive": process_alive}


def _claim_tasks(base: Path, capacity: int) -> list[dict[str, object]]:
    connection = _connect(base)
    now = datetime.now(timezone.utc)
    claimed: list[dict[str, object]] = []
    try:
        if _is_paused(connection):
            return []
        tasks = _rows(connection)
        by_id = {str(task["task_id"]): task for task in tasks}
        for task in tasks:
            if len(claimed) >= capacity or task["status"] != "pending":
                continue
            dependencies = task["dependencies"]
            if any(by_id.get(dependency, {}).get("status") != "done" for dependency in dependencies):
                continue
            lease_until = (now + timedelta(minutes=10)).isoformat()
            connection.execute("UPDATE tasks SET status='running', worker=?, lease_until=?, attempts=attempts+1, updated_at=? WHERE task_id=? AND status='pending'", ("local-runtime", lease_until, now_iso(), task["task_id"]))
            connection.execute("INSERT INTO task_events(task_id,recorded_at,state,detail) VALUES(?,?,?,?)", (task["task_id"], now_iso(), "running", "claimed by local runtime"))
            claimed.append(dict(task) | {"status": "running"})
        connection.commit()
    finally:
        connection.close()
    return claimed


def _complete_task(base: Path, task: dict[str, object], status: str, detail: str) -> None:
    connection = _connect(base)
    try:
        final_status = status
        if status == "failed":
            row = connection.execute("SELECT attempts FROM tasks WHERE task_id=?", (task["task_id"],)).fetchone()
            if row and int(row["attempts"]) < 3:
                final_status = "pending"
                detail = f"transient failure; retry {row['attempts']} of 2: {detail}"
        connection.execute("UPDATE tasks SET status=?, lease_until='', error=?, updated_at=? WHERE task_id=?", (final_status, "" if final_status == "done" else detail, now_iso(), task["task_id"]))
        connection.execute("INSERT INTO task_events(task_id,recorded_at,state,detail) VALUES(?,?,?,?)", (task["task_id"], now_iso(), final_status, detail))
        connection.commit()
    finally:
        connection.close()


def run_project_cycle(base: Path, workers: int = 2) -> dict[str, object]:
    if workers < 1 or workers > 2:
        raise ValueError("project runtime supports one or two local workers")
    claimed = _claim_tasks(base, workers)
    executed = []
    for task in claimed:
        try:
            if task["kind"] == "analyze_review":
                analyze_review_item(base, str(task["item_id"]))
            elif task["kind"] == "plan_review_item":
                plan_item(base, str(task["item_id"]))
            elif task["kind"] == "collect_evidence":
                refresh_review_evidence(base, str(task["item_id"]))
            _complete_task(base, task, "done", "completed by local reversible task")
            executed.append({"task_id": task["task_id"], "status": "done"})
        except Exception as exc:
            _complete_task(base, task, "failed", str(exc))
            executed.append({"task_id": task["task_id"], "status": "failed", "error": str(exc)})
    _render_runtime(base)
    return {"executed": executed, "status": project_status(base)}


def _evidence_entry(kind: str, source: str, locator: str, sha256: str = "") -> dict[str, str]:
    return {"kind": kind, "source": source, "locator": locator, "sha256": sha256}


def refresh_review_evidence(base: Path, item_id: str) -> dict[str, object]:
    config = load_config(base)
    analyses = load_review_analyses(config)
    evidence: list[dict[str, str]] = []
    analysis = analyses.get(item_id, {}) if isinstance(analyses, dict) else {}
    if analysis:
        evidence.append(_evidence_entry("review_analysis", "review_analyses.json", item_id))
    items = read_json(config.workspace / "review_items.json", [])
    item = next((row for row in items if row.get("id") == item_id), {}) if isinstance(items, list) else {}
    for location in item.get("tex_locations", []) if isinstance(item, dict) else []:
        evidence.append(_evidence_entry("manuscript_location", "latex_index.json", str(location)))
    for filename, kind in (("proof_workflows.json", "proof"), ("experiment_manifests.json", "experiment"), ("candidate_edits.json", "candidate")):
        data = read_json(config.workspace / filename, {} if filename != "candidate_edits.json" else [])
        text = json.dumps(data, ensure_ascii=False)
        if item_id in text:
            evidence.append(_evidence_entry(kind, filename, item_id))
    document = read_json(config.workspace / "review_evidence.json", {})
    if not isinstance(document, dict):
        document = {}
    document[item_id] = {"refreshed_at": now_iso(), "evidence": evidence}
    write_json(config.workspace / "review_evidence.json", document)
    lines = ["# Review Evidence", ""]
    for key, value in sorted(document.items()):
        lines.append(f"## {key}")
        for entry in value.get("evidence", []):
            lines.append(f"- {entry['kind']}: `{entry['source']}` {entry['locator']}")
        lines.append("")
    write_text(config.workspace / "review_evidence.md", "\n".join(lines))
    connection = _connect(base)
    try:
        connection.execute("DELETE FROM evidence WHERE item_id=?", (item_id,))
        for entry in evidence:
            connection.execute("INSERT INTO evidence(item_id,kind,source,locator,sha256,recorded_at) VALUES(?,?,?,?,?,?)", (item_id, entry["kind"], entry["source"], entry["locator"], entry["sha256"], now_iso()))
        connection.commit()
    finally:
        connection.close()
    return document[item_id]


def authorize_remote(base: Path, task_id: str, provider: str, model: str, purpose: str, artifact_classes: list[str], ttl_minutes: int = 30) -> dict[str, object]:
    if ttl_minutes < 1 or ttl_minutes > 1440:
        raise ValueError("remote authorization ttl must be between 1 and 1440 minutes")
    from .privacy import remote_authorization_issues
    issues = remote_authorization_issues(base, provider, artifact_classes)
    if issues:
        raise ValueError("; ".join(issues))
    connection = _connect(base)
    try:
        if not connection.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone():
            raise ValueError(f"unknown runtime task {task_id}")
        expires = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
        cursor = connection.execute("INSERT INTO remote_consents(task_id,provider,model,purpose,artifact_classes,expires_at,created_at) VALUES(?,?,?,?,?,?,?)", (task_id, provider, model, purpose, json.dumps(artifact_classes), expires, now_iso()))
        connection.commit()
        return {"authorization_id": cursor.lastrowid, "task_id": task_id, "provider": provider, "model": model, "purpose": purpose, "artifact_classes": artifact_classes, "expires_at": expires}
    finally:
        connection.close()


def evaluate_review_item(base: Path, item_id: str) -> dict[str, object]:
    """Deterministic evidence gate; remote semantic review remains consent-gated and advisory."""
    config = load_config(base)
    evidence_doc = read_json(config.workspace / "review_evidence.json", {})
    entries = evidence_doc.get(item_id, {}).get("evidence", []) if isinstance(evidence_doc, dict) else []
    kinds = {entry.get("kind") for entry in entries if isinstance(entry, dict)}
    required = {"review_analysis", "manuscript_location"}
    items = read_json(config.workspace / "review_items.json", [])
    item = next((row for row in items if row.get("id") == item_id), {}) if isinstance(items, list) else {}
    lane = str(item.get("lane", "")) if isinstance(item, dict) else ""
    if lane == "proof": required.add("proof")
    if lane == "experiment": required.add("experiment")
    missing = sorted(required - kinds)
    connection = _connect(base)
    try:
        task_id = _task_id(item_id, "collect_evidence")
        now = datetime.now(timezone.utc).isoformat()
        consent = connection.execute("SELECT provider, model FROM remote_consents WHERE task_id=? AND expires_at>? ORDER BY consent_id DESC LIMIT 1", (task_id, now)).fetchone()
    finally:
        connection.close()
    semantic_status = "authorized_remote_review_pending" if consent else "requires_author_or_authorized_remote_review"
    result = {"item_id": item_id, "evaluated_at": now_iso(), "deterministic_pass": not missing, "semantic_status": semantic_status, "missing_evidence": missing, "ready_for_author_closure": False}
    evaluations = read_json(config.workspace / "review_evaluations.json", {})
    if not isinstance(evaluations, dict):
        evaluations = {}
    evaluations[item_id] = result
    write_json(config.workspace / "review_evaluations.json", evaluations)
    write_text(config.workspace / "review_evaluations.md", "# Review Evaluations\n\n" + "\n".join(f"- `{key}` deterministic={value.get('deterministic_pass')} missing={', '.join(value.get('missing_evidence', [])) or 'none'}" for key, value in sorted(evaluations.items())) + "\n")
    return result


def _cycle_source_fingerprint(base: Path, item_id: str) -> str:
    """Hash only the review inputs that a three-role cycle is allowed to rely on."""
    config = load_config(base)
    payload: dict[str, object] = {"item_id": item_id}
    for filename, default in (("review_items.json", []), ("review_analyses.json", {}), ("latex_index.json", {})):
        value = read_json(config.workspace / filename, default)
        if filename == "review_items.json" and isinstance(value, list):
            value = next((row for row in value if isinstance(row, dict) and row.get("id") == item_id), {})
        elif isinstance(value, dict):
            value = value.get(item_id, value if filename == "latex_index.json" else {})
        payload[filename] = value
    payload["tex_files"] = {
        str(path.relative_to(config.tex_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tex_files(config.tex_root, config.main_tex)
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cycle_row(connection: sqlite3.Connection, cycle_id: str) -> dict[str, object]:
    row = connection.execute("SELECT * FROM revision_cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
    if not row:
        raise ValueError(f"unknown revision cycle {cycle_id}")
    return dict(row)


def _record_cycle_event(connection: sqlite3.Connection, cycle_id: str, before: str, after: str, action: str, actor_id: str, detail: str) -> None:
    connection.execute(
        "INSERT INTO revision_cycle_events(cycle_id,from_status,to_status,action,actor_id,detail,recorded_at) VALUES(?,?,?,?,?,?,?)",
        (cycle_id, before, after, action, actor_id, detail, now_iso()),
    )


def _require_current_cycle_inputs(base: Path, connection: sqlite3.Connection, cycle: dict[str, object]) -> None:
    if _cycle_source_fingerprint(base, str(cycle["item_id"])) == cycle["source_fingerprint"]:
        return
    before = str(cycle["status"])
    connection.execute(
        "UPDATE revision_cycles SET status='blocked', invalidated_at=?, invalidation_reason=?, updated_at=? WHERE cycle_id=?",
        (now_iso(), "review inputs changed", now_iso(), cycle["cycle_id"]),
    )
    _record_cycle_event(connection, str(cycle["cycle_id"]), before, "blocked", "cycle-invalidate", "runtime", "review inputs changed; cycle is stale")
    connection.commit()
    raise ValueError("review inputs changed; cycle was marked blocked and a new cycle may be opened")


def _identity(value: object) -> str:
    return str(value).strip().casefold()


def _transition_cycle(connection: sqlite3.Connection, cycle: dict[str, object], allowed: set[str], after: str, action: str, actor_id: str, detail: str) -> None:
    before = str(cycle["status"])
    if before not in allowed or after not in CYCLE_STATUSES:
        raise ValueError(f"cycle {cycle['cycle_id']} cannot {action} from {before}")
    connection.execute("UPDATE revision_cycles SET status=?, updated_at=? WHERE cycle_id=?", (after, now_iso(), cycle["cycle_id"]))
    _record_cycle_event(connection, str(cycle["cycle_id"]), before, after, action, actor_id, detail)


def _cycle_result(base: Path, cycle_id: str) -> dict[str, object]:
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        artifacts = [dict(row) for row in connection.execute("SELECT * FROM revision_cycle_artifacts WHERE cycle_id=? ORDER BY artifact_id", (cycle_id,))]
        events = [dict(row) for row in connection.execute("SELECT * FROM revision_cycle_events WHERE cycle_id=? ORDER BY event_id", (cycle_id,))]
        return {"cycle": cycle, "artifacts": artifacts, "events": events}
    finally:
        connection.close()


def open_revision_cycle(base: Path, item_id: str, planner_id: str) -> dict[str, object]:
    """Open an auditable planning cycle; it never changes a review item's lifecycle."""
    if not planner_id.strip():
        raise ValueError("planner_id is required")
    if not runtime_path(base).exists():
        raise ValueError("project runtime is not initialized; run revagent project-init first")
    config = load_config(base)
    items = read_json(config.workspace / "review_items.json", [])
    if not any(isinstance(item, dict) and item.get("id") == item_id for item in items if isinstance(items, list)):
        raise ValueError(f"unknown review item {item_id}")
    connection = _connect(base)
    try:
        active = connection.execute("SELECT cycle_id FROM revision_cycles WHERE item_id=? AND status NOT IN ('blocked','author_approved')", (item_id,)).fetchone()
        if active:
            raise ValueError(f"review item {item_id} already has active cycle {active['cycle_id']}")
        sequence = int(connection.execute("SELECT COUNT(*) FROM revision_cycles").fetchone()[0]) + 1
        cycle_id = f"CYC-{sequence:03d}"
        fingerprint = _cycle_source_fingerprint(base, item_id)
        now = now_iso()
        connection.execute(
            "INSERT INTO revision_cycles(cycle_id,item_id,status,source_fingerprint,planner_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (cycle_id, item_id, "draft", fingerprint, planner_id, now, now),
        )
        _record_cycle_event(connection, cycle_id, "", "draft", "cycle-open", planner_id, "planner opened a revision cycle")
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return _cycle_result(base, cycle_id)


def _load_cycle_artifact(path: Path, cycle: dict[str, object], role: str, actor_id: str) -> tuple[dict[str, object], bytes, str]:
    if not path.is_file():
        raise ValueError(f"artifact file does not exist: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_CYCLE_ARTIFACT_BYTES:
        raise ValueError("cycle artifact exceeds 1 MiB")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cycle artifact must be UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("cycle artifact must be a JSON object")
    required = {"version", "cycle_id", "item_id", "role", "actor_id", "input_fingerprint", "created_at"}
    expected_version = 2
    if not required.issubset(payload) or payload.get("version") != expected_version:
        raise ValueError("cycle artifact lacks the required versioned identity fields")
    expected = {"cycle_id": cycle["cycle_id"], "item_id": cycle["item_id"], "role": role, "actor_id": actor_id, "input_fingerprint": cycle["source_fingerprint"]}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("cycle artifact identity or frozen input fingerprint does not match")
    sha256 = hashlib.sha256(raw).hexdigest()
    return payload, raw, sha256


def _store_cycle_artifact(base: Path, connection: sqlite3.Connection, cycle: dict[str, object], role: str, actor_id: str, raw: bytes, sha256: str) -> None:
    revision = int(cycle["round"])
    target_dir = load_config(base).workspace / "revision_cycles" / str(cycle["cycle_id"])
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{revision:02d}-{role}.json"
    if target.exists():
        raise ValueError(f"{role} artifact already recorded for cycle round {revision}")
    target.write_bytes(raw)
    if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
        raise ValueError("stored cycle artifact hash verification failed")
    connection.execute(
        "INSERT INTO revision_cycle_artifacts(cycle_id,role,revision,actor_id,input_fingerprint,path,sha256,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
        (cycle["cycle_id"], role, revision, actor_id, cycle["source_fingerprint"], str(target.relative_to(load_config(base).workspace)), sha256, now_iso()),
    )


def attach_cycle_plan(base: Path, cycle_id: str, plan_file: Path) -> dict[str, object]:
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        _require_current_cycle_inputs(base, connection, cycle)
        payload, raw, sha256 = _load_cycle_artifact(plan_file, cycle, "planner", str(cycle["planner_id"]))
        if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
            raise ValueError("planner artifact lacks the required revision specification fields")
        try:
            validate_revision_spec(payload)
        except ValueError as exc:
            raise ValueError(f"planner artifact lacks a valid typed revision specification: {exc}") from exc
        _transition_cycle(connection, cycle, {"draft", "returned"}, "planned", "cycle-plan", str(cycle["planner_id"]), "frozen planner specification")
        _store_cycle_artifact(base, connection, cycle, "planner", str(cycle["planner_id"]), raw, sha256)
        connection.execute("UPDATE revision_cycles SET plan_sha256=? WHERE cycle_id=?", (sha256, cycle_id))
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return _cycle_result(base, cycle_id)


def attach_cycle_actor_bundle(base: Path, cycle_id: str, actor_id: str, bundle_file: Path) -> dict[str, object]:
    if not actor_id.strip():
        raise ValueError("actor_id is required")
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        if _identity(actor_id) == _identity(cycle["planner_id"]):
            raise ValueError("planner and actor identities must be distinct")
        _require_current_cycle_inputs(base, connection, cycle)
        payload, raw, sha256 = _load_cycle_artifact(bundle_file, cycle, "actor", actor_id)
        plan_path = load_config(base).workspace / "revision_cycles" / cycle_id / f"{int(cycle['round']):02d}-planner.json"
        plan = read_json(plan_path, {})
        if payload.get("plan_sha256") != cycle["plan_sha256"] or not isinstance(plan, dict):
            raise ValueError("actor artifact is not bound to the current planner specification")
        try:
            validate_actor_bundle(payload, plan, base)
        except ValueError as exc:
            raise ValueError(f"actor artifact lacks a valid traceable evidence bundle: {exc}") from exc
        _transition_cycle(connection, cycle, {"planned"}, "acted", "cycle-act", actor_id, "actor evidence bundle attached; no manuscript edit applied")
        _store_cycle_artifact(base, connection, cycle, "actor", actor_id, raw, sha256)
        connection.execute("UPDATE revision_cycles SET actor_id=?, actor_sha256=? WHERE cycle_id=?", (actor_id, sha256, cycle_id))
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return _cycle_result(base, cycle_id)


def create_cycle_reviewer_session(base: Path, cycle_id: str, reviewer_id: str) -> dict[str, object]:
    """Freeze the current planner/actor pair for one independent reviewer."""
    if not reviewer_id.strip():
        raise ValueError("reviewer_id is required")
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        if _identity(reviewer_id) in {_identity(cycle["planner_id"]), _identity(cycle["actor_id"])}:
            raise ValueError("reviewer identity must be independent from planner and actor")
        _require_current_cycle_inputs(base, connection, cycle)
        if cycle["status"] != "acted":
            raise ValueError("reviewer session is available only after actor evidence is frozen")
        existing = connection.execute("SELECT * FROM revision_reviewer_sessions WHERE cycle_id=? AND round=? AND reviewer_id=?", (cycle_id, cycle["round"], reviewer_id)).fetchone()
        if existing:
            return dict(existing)
        workspace = load_config(base).workspace
        round_number = int(cycle["round"])
        planner = workspace / "revision_cycles" / cycle_id / f"{round_number:02d}-planner.json"
        actor = workspace / "revision_cycles" / cycle_id / f"{round_number:02d}-actor.json"
        if not planner.is_file() or not actor.is_file():
            raise ValueError("current planner and actor artifacts are missing")
        reviewer_token = hashlib.sha256(reviewer_id.encode("utf-8")).hexdigest()[:10]
        session_id = f"RS-{cycle_id}-{round_number:02d}-{reviewer_token}"
        payload = {"version": 1, "session_id": session_id, "cycle_id": cycle_id, "round": round_number, "reviewer_id": reviewer_id, "input_fingerprint": cycle["source_fingerprint"], "plan_sha256": cycle["plan_sha256"], "actor_sha256": cycle["actor_sha256"], "planner_artifact": str(planner.relative_to(workspace)), "actor_artifact": str(actor.relative_to(workspace)), "created_at": now_iso(), "instruction": "Assess evidence completeness only; do not validate mathematical or experimental truth."}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        target_dir = workspace / "reviewer_sessions" / cycle_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{round_number:02d}-{reviewer_token}.json"
        target.write_bytes(raw)
        connection.execute("INSERT INTO revision_reviewer_sessions(session_id,cycle_id,round,reviewer_id,input_fingerprint,plan_sha256,actor_sha256,path,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (session_id, cycle_id, round_number, reviewer_id, cycle["source_fingerprint"], cycle["plan_sha256"], cycle["actor_sha256"], str(target.relative_to(workspace)), digest, now_iso()))
        _record_cycle_event(connection, cycle_id, "acted", "acted", "cycle-review-session", reviewer_id, f"frozen independent review session {session_id}")
        connection.commit()
        return {**payload, "path": str(target.relative_to(workspace)), "sha256": digest}
    finally:
        connection.close()


def attach_cycle_review(base: Path, cycle_id: str, reviewer_id: str, review_file: Path) -> dict[str, object]:
    if not reviewer_id.strip():
        raise ValueError("reviewer_id is required")
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        if _identity(reviewer_id) in {_identity(cycle["planner_id"]), _identity(cycle["actor_id"])}:
            raise ValueError("reviewer identity must be independent from planner and actor")
        _require_current_cycle_inputs(base, connection, cycle)
        payload, raw, sha256 = _load_cycle_artifact(review_file, cycle, "reviewer", reviewer_id)
        verdict = payload.get("verdict")
        plan_path = load_config(base).workspace / "revision_cycles" / cycle_id / f"{int(cycle['round']):02d}-planner.json"
        actor_path = load_config(base).workspace / "revision_cycles" / cycle_id / f"{int(cycle['round']):02d}-actor.json"
        plan, actor = read_json(plan_path, {}), read_json(actor_path, {})
        session = connection.execute("SELECT * FROM revision_reviewer_sessions WHERE session_id=?", (payload.get("review_session_id"),)).fetchone()
        if not session or session["cycle_id"] != cycle_id or session["round"] != cycle["round"] or session["reviewer_id"] != reviewer_id or session["sha256"] != payload.get("review_session_sha256") or session["input_fingerprint"] != cycle["source_fingerprint"] or session["plan_sha256"] != cycle["plan_sha256"] or session["actor_sha256"] != cycle["actor_sha256"]:
            raise ValueError("reviewer artifact must reference a current independent frozen review session")
        if verdict not in {"pass", "return", "blocked", "escalate"} or payload.get("plan_sha256") != cycle["plan_sha256"] or payload.get("actor_sha256") != cycle["actor_sha256"] or not isinstance(plan, dict) or not isinstance(actor, dict):
            raise ValueError("reviewer artifact is incomplete or not bound to the current evidence bundle")
        try:
            validate_reviewer_report(payload, plan, actor)
        except ValueError as exc:
            raise ValueError(f"reviewer artifact lacks a valid independent assessment: {exc}") from exc
        destination = {"pass": "awaiting_author_gate", "escalate": "awaiting_author_gate", "return": "returned", "blocked": "blocked"}[str(verdict)]
        _transition_cycle(connection, cycle, {"acted"}, destination, "cycle-review", reviewer_id, f"independent reviewer verdict: {verdict}; author closure remains manual")
        _store_cycle_artifact(base, connection, cycle, "reviewer", reviewer_id, raw, sha256)
        connection.execute("UPDATE revision_cycles SET reviewer_id=?, review_sha256=?, verdict=? WHERE cycle_id=?", (reviewer_id, sha256, verdict, cycle_id))
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return _cycle_result(base, cycle_id)


def record_cycle_author_gate(base: Path, cycle_id: str, author_id: str, decision: str, note: str) -> dict[str, object]:
    if not author_id.strip() or decision not in {"approve", "reject"} or not note.strip():
        raise ValueError("author_id and a non-empty approve or reject decision note are required")
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        if _identity(author_id) in {_identity(cycle["planner_id"]), _identity(cycle["actor_id"]), _identity(cycle["reviewer_id"])}:
            raise ValueError("author identity must be distinct from planner, actor, and reviewer")
        _require_current_cycle_inputs(base, connection, cycle)
        if cycle["status"] != "awaiting_author_gate":
            raise ValueError("author gate is available only after an independent reviewer verdict")
        if decision == "approve" and cycle["verdict"] != "pass":
            raise ValueError("only a pass verdict may enter author approval; escalation requires an author decision outside this cycle")
        after = "author_approved" if decision == "approve" else "returned"
        _transition_cycle(connection, cycle, {"awaiting_author_gate"}, after, "cycle-author-gate", author_id, f"{decision}: {note.strip()}")
        connection.execute("INSERT INTO revision_cycle_author_decisions(cycle_id,action,author_id,note,review_sha256,recorded_at) VALUES(?,?,?,?,?,?)", (cycle_id, decision, author_id, note.strip(), cycle["review_sha256"], now_iso()))
        connection.execute("INSERT INTO author_gates(item_id,kind,status,note,created_at) VALUES(?,?,?,?,?)", (cycle["item_id"], "revision_cycle", decision, f"{cycle_id} author={author_id} source={cycle['source_fingerprint']} review={cycle['review_sha256']}: {note.strip()}", now_iso()))
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return _cycle_result(base, cycle_id)


def _author_identity_allowed(cycle: dict[str, object], author_id: str) -> None:
    if not author_id.strip() or _identity(author_id) in {_identity(cycle["planner_id"]), _identity(cycle["actor_id"]), _identity(cycle["reviewer_id"])}:
        raise ValueError("author identity must be distinct from planner, actor, and reviewer")


def record_cycle_author_escalation(base: Path, cycle_id: str, author_id: str, note: str) -> dict[str, object]:
    """Record an author/expert escalation; it blocks the cycle and never starts work."""
    if not note.strip():
        raise ValueError("escalation note is required")
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        _author_identity_allowed(cycle, author_id)
        _require_current_cycle_inputs(base, connection, cycle)
        _transition_cycle(connection, cycle, {"awaiting_author_gate"}, "blocked", "cycle-author-escalate", author_id, note.strip())
        connection.execute("INSERT INTO revision_cycle_author_decisions(cycle_id,action,author_id,note,review_sha256,recorded_at) VALUES(?,?,?,?,?,?)", (cycle_id, "escalate", author_id, note.strip(), cycle["review_sha256"], now_iso()))
        connection.execute("INSERT INTO author_gates(item_id,kind,status,note,created_at) VALUES(?,?,?,?,?)", (cycle["item_id"], "revision_cycle_escalation", "escalated", f"{cycle_id} review={cycle['review_sha256']}: {note.strip()}", now_iso()))
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return _cycle_result(base, cycle_id)


def record_cycle_author_waiver(base: Path, cycle_id: str, author_id: str, finding_id: str, note: str) -> dict[str, object]:
    """Record, but never resolve, a low-risk non-blocking reviewer finding."""
    if not finding_id.strip() or not note.strip():
        raise ValueError("finding_id and waiver note are required")
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        _author_identity_allowed(cycle, author_id)
        _require_current_cycle_inputs(base, connection, cycle)
        if cycle["status"] != "awaiting_author_gate" or cycle["verdict"] != "pass":
            raise ValueError("waivers are limited to a current low-risk pass awaiting author review")
        plan_path = load_config(base).workspace / "revision_cycles" / cycle_id / f"{int(cycle['round']):02d}-planner.json"
        review_path = load_config(base).workspace / "revision_cycles" / cycle_id / f"{int(cycle['round']):02d}-reviewer.json"
        plan, report = read_json(plan_path, {}), read_json(review_path, {})
        finding = next((entry for entry in report.get("findings", []) if isinstance(entry, dict) and entry.get("finding_id") == finding_id), None) if isinstance(report, dict) else None
        if not isinstance(plan, dict) or plan.get("lane") not in {"text", "rebuttal"} or not isinstance(finding, dict) or finding.get("severity") not in {"info", "minor"} or finding.get("blocks_verdict") is True:
            raise ValueError("only non-blocking info/minor findings in text or rebuttal cycles may be waived")
        connection.execute("INSERT INTO revision_cycle_author_decisions(cycle_id,action,author_id,selected_id,note,review_sha256,recorded_at) VALUES(?,?,?,?,?,?,?)", (cycle_id, "waive", author_id, finding_id, note.strip(), cycle["review_sha256"], now_iso()))
        _record_cycle_event(connection, cycle_id, str(cycle["status"]), str(cycle["status"]), "cycle-author-waive", author_id, f"finding={finding_id}: {note.strip()}")
        connection.execute("INSERT INTO author_gates(item_id,kind,status,note,created_at) VALUES(?,?,?,?,?)", (cycle["item_id"], "revision_cycle_waiver", "waived", f"{cycle_id} finding={finding_id}: {note.strip()}", now_iso()))
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return _cycle_result(base, cycle_id)


def reopen_revision_cycle(base: Path, cycle_id: str, note: str) -> dict[str, object]:
    """Start a new, explicitly recorded actor/planner round after a return verdict."""
    if not note.strip():
        raise ValueError("reopen note is required")
    connection = _connect(base)
    try:
        cycle = _cycle_row(connection, cycle_id)
        _transition_cycle(connection, cycle, {"returned"}, "draft", "cycle-reopen", "author", note.strip())
        connection.execute(
            "UPDATE revision_cycles SET round=round+1, source_fingerprint=?, actor_id='', reviewer_id='', plan_sha256='', actor_sha256='', review_sha256='', verdict='' WHERE cycle_id=?",
            (_cycle_source_fingerprint(base, str(cycle["item_id"])), cycle_id),
        )
        connection.commit()
    finally:
        connection.close()
    _render_runtime(base)
    return _cycle_result(base, cycle_id)


def revision_cycle_status(base: Path, cycle_id: str | None = None) -> dict[str, object]:
    if cycle_id:
        return _cycle_result(base, cycle_id)
    connection = _connect(base)
    try:
        cycles = [dict(row) for row in connection.execute("SELECT * FROM revision_cycles ORDER BY cycle_id")]
        return {"cycles": cycles}
    finally:
        connection.close()


def cycle_integrity_issues(base: Path) -> list[str]:
    """Recompute immutable cycle bindings without changing runtime state."""
    if not runtime_path(base).exists():
        return []
    config = load_config(base)
    issues: list[str] = []
    connection = _connect(base)
    try:
        cycles = [dict(row) for row in connection.execute("SELECT * FROM revision_cycles ORDER BY cycle_id")]
        for cycle in cycles:
            cycle_id = str(cycle["cycle_id"])
            round_number = int(cycle["round"])
            artifacts = [dict(row) for row in connection.execute("SELECT * FROM revision_cycle_artifacts WHERE cycle_id=? ORDER BY artifact_id", (cycle_id,))]
            events = [dict(row) for row in connection.execute("SELECT * FROM revision_cycle_events WHERE cycle_id=? ORDER BY event_id", (cycle_id,))]
            previous = ""
            for event in events:
                if event["from_status"] != previous or event["to_status"] not in CYCLE_STATUSES:
                    issues.append(f"revision cycle {cycle_id} has a tampered or discontinuous event chain")
                    break
                previous = str(event["to_status"])
            if events and previous != cycle["status"]:
                issues.append(f"revision cycle {cycle_id} database status does not match its event chain")
            for artifact in artifacts:
                path = config.workspace / str(artifact["path"])
                try:
                    path.resolve().relative_to(config.workspace.resolve())
                except ValueError:
                    issues.append(f"revision cycle {cycle_id} artifact path escapes the workspace")
                    continue
                if not path.is_file():
                    issues.append(f"revision cycle {cycle_id} artifact is missing: {artifact['path']}")
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != artifact["sha256"]:
                    issues.append(f"revision cycle {cycle_id} artifact hash drift: {artifact['path']}")
                expected_path = f"revision_cycles/{cycle_id}/{int(artifact['revision']):02d}-{artifact['role']}.json"
                if str(artifact["path"]).replace("\\", "/") != expected_path:
                    issues.append(f"revision cycle {cycle_id} artifact path is not canonical")
            current = {row["role"]: row for row in artifacts if int(row["revision"]) == round_number}
            for role, column in (("planner", "plan_sha256"), ("actor", "actor_sha256"), ("reviewer", "review_sha256")):
                recorded = str(cycle[column])
                artifact = current.get(role)
                if bool(recorded) != bool(artifact) or artifact and recorded != artifact["sha256"]:
                    issues.append(f"revision cycle {cycle_id} {role} database hash binding is invalid")
            identities = [_identity(cycle["planner_id"]), _identity(cycle["actor_id"]), _identity(cycle["reviewer_id"])]
            populated = [identity for identity in identities if identity]
            if len(populated) != len(set(populated)):
                issues.append(f"revision cycle {cycle_id} reuses planner, actor, reviewer, or author identity")
            if str(cycle["status"]) != "blocked" and _cycle_source_fingerprint(base, str(cycle["item_id"])) != cycle["source_fingerprint"]:
                issues.append(f"revision cycle {cycle_id} source fingerprint drift")
            decisions = [dict(row) for row in connection.execute("SELECT * FROM revision_cycle_author_decisions WHERE cycle_id=?", (cycle_id,))]
            for decision in decisions:
                if decision["review_sha256"] != cycle["review_sha256"]:
                    issues.append(f"revision cycle {cycle_id} author decision is bound to a stale review hash")
            sessions = [dict(row) for row in connection.execute("SELECT * FROM revision_reviewer_sessions WHERE cycle_id=?", (cycle_id,))]
            for session in sessions:
                session_path = config.workspace / str(session["path"])
                try:
                    session_path.resolve().relative_to(config.workspace.resolve())
                except ValueError:
                    issues.append(f"revision cycle {cycle_id} reviewer session path escapes the workspace")
                    continue
                if not session_path.is_file() or hashlib.sha256(session_path.read_bytes()).hexdigest() != session["sha256"]:
                    issues.append(f"revision cycle {cycle_id} reviewer session hash drift")
                if _identity(session["reviewer_id"]) in {_identity(cycle["planner_id"]), _identity(cycle["actor_id"])}:
                    issues.append(f"revision cycle {cycle_id} reviewer session reuses a planner or actor identity")
    finally:
        connection.close()
    return sorted(set(issues))


def author_decision_console(base: Path) -> dict[str, object]:
    """Read-only author-facing handoff; it never resolves a gate or closes an item."""
    if not runtime_path(base).exists():
        return {"cycles": [], "pending": [], "submission_ready": False, "reason": "project runtime is not initialized"}
    status = project_status(base)
    connection = _connect(base)
    try:
        decisions = [dict(row) for row in connection.execute("SELECT * FROM revision_cycle_author_decisions ORDER BY decision_id")]
    finally:
        connection.close()
    decisions_by_cycle: dict[str, list[dict[str, object]]] = {}
    for decision in decisions:
        decisions_by_cycle.setdefault(str(decision["cycle_id"]), []).append(decision)
    for cycle in status["cycles"]:
        cycle["author_decisions"] = decisions_by_cycle.get(str(cycle["cycle_id"]), [])
    pending: list[dict[str, object]] = []
    for cycle in status["cycles"]:
        state = str(cycle["status"])
        if state not in {"awaiting_author_gate", "returned", "blocked"}:
            continue
        verdict = str(cycle.get("verdict", ""))
        if state == "awaiting_author_gate" and verdict == "pass":
            command = f"revagent cycle-author-gate {cycle['cycle_id']} --author-id AUTHOR_ID --decision approve --note \"...\""
        elif state == "returned":
            command = f"revagent cycle-reopen {cycle['cycle_id']} --note \"...\""
        else:
            command = "Author/expert review required; do not approve or close this item."
        pending.append({
            "cycle_id": cycle["cycle_id"], "item_id": cycle["item_id"], "round": cycle["round"], "status": state,
            "verdict": verdict, "planner_sha256": cycle["plan_sha256"], "actor_sha256": cycle["actor_sha256"],
            "review_sha256": cycle["review_sha256"], "source_fingerprint": cycle["source_fingerprint"],
            "invalidation_reason": cycle["invalidation_reason"], "author_decisions": cycle.get("author_decisions", []), "next_command": command,
        })
    has_waivers = any(decision["action"] == "waive" for decision in decisions)
    integrity_issues = cycle_integrity_issues(base)
    return {"cycles": status["cycles"], "pending": pending, "decisions": decisions, "has_waivers": has_waivers, "integrity_issues": integrity_issues, "submission_ready": not pending and not has_waivers and not integrity_issues and bool(status["cycles"]), "reason": "all cycles have completed author decisions" if not pending and not has_waivers and not integrity_issues else "author decisions, waivers, integrity failures, or evidence work remain"}


class _StatusHandler(BaseHTTPRequestHandler):
    base: Path

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            body = b'{"ok":true}'
        elif self.path == "/status":
            body = json.dumps(project_status(self.base), ensure_ascii=False).encode("utf-8")
        elif urlparse(self.path).path == "/cockpit":
            from .cockpit import write_author_cockpit
            language = parse_qs(urlparse(self.path).query).get("lang", ["en"])[0]
            try:
                body = write_author_cockpit(self.base, language).read_bytes()
            except ValueError:
                self.send_error(400, "lang must be en or zh")
                return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8" if urlparse(self.path).path == "/cockpit" else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def serve_project(base: Path, host: str = "127.0.0.1", port: int = 8765, workers: int = 2, once: bool = False) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("project service may bind only to a loopback host")
    initialize_project_runtime(base)
    if once:
        run_project_cycle(base, workers)
        return
    run_project_cycle(base, workers)
    connection = _connect(base)
    try:
        connection.execute("INSERT INTO runtime_settings(key,value) VALUES('stopped','false') ON CONFLICT(key) DO UPDATE SET value='false'")
        connection.commit()
    finally:
        connection.close()
    config = load_config(base)
    write_json(config.workspace / "service.json", {"pid": os.getpid(), "host": host, "port": port, "started_at": now_iso(), "schema_version": "32", "health": "starting"})
    stop_event = threading.Event()

    def scheduler() -> None:
        while not stop_event.wait(5):
            connection = _connect(base)
            try:
                stopped = _is_stopped(connection)
            finally:
                connection.close()
            if stopped:
                stop_event.set()
                return
            run_project_cycle(base, workers)

    thread = threading.Thread(target=scheduler, name="revagent-project-runtime", daemon=True)
    thread.start()
    handler = type("ProjectStatusHandler", (_StatusHandler,), {"base": base})
    server = ThreadingHTTPServer((host, port), handler)
    server.timeout = 1
    write_json(load_config(base).workspace / "service.json", {"pid": os.getpid(), "host": host, "port": port, "started_at": now_iso(), "schema_version": "32", "health": "ready"})
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        stop_event.set()
        write_json(load_config(base).workspace / "service.json", {"pid": os.getpid(), "host": host, "port": port, "stopped_at": now_iso(), "health": "stopped"})
        server.server_close()


__all__ = ["attach_cycle_actor_bundle", "attach_cycle_plan", "attach_cycle_review", "author_decision_console", "authorize_remote", "create_cycle_reviewer_session", "cycle_integrity_issues", "evaluate_review_item", "initialize_project_runtime", "open_revision_cycle", "project_status", "record_cycle_author_escalation", "record_cycle_author_gate", "record_cycle_author_waiver", "recover_project_runtime", "refresh_review_evidence", "reopen_revision_cycle", "revision_cycle_status", "run_project_cycle", "service_health", "serve_project", "set_project_paused", "stop_project_service"]
