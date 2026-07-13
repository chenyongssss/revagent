"""Persistent local runtime for advancing a manuscript review project safely."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import psutil

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .planning import plan_item
from .review_analysis import analyze_review_item, load_review_analyses

RUNTIME_TASKS = ("analyze_review", "plan_review_item", "collect_evidence")
TERMINAL_TASKS = {"done", "blocked", "canceled", "failed"}


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
        return {"tasks": tasks, "counts": counts, "gates": gates, "paused": _is_paused(connection)}
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


class _StatusHandler(BaseHTTPRequestHandler):
    base: Path

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            body = b'{"ok":true}'
        elif self.path == "/status":
            body = json.dumps(project_status(self.base), ensure_ascii=False).encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
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


__all__ = ["authorize_remote", "evaluate_review_item", "initialize_project_runtime", "project_status", "recover_project_runtime", "refresh_review_evidence", "run_project_cycle", "service_health", "serve_project", "set_project_paused", "stop_project_service"]
