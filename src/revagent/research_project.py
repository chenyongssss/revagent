"""Durable, human-gated workflows for general research projects."""

from __future__ import annotations

import hashlib
import json
import re
import html
from pathlib import Path
from typing import Callable, Protocol

from ._utils import now_iso, read_json, write_json, write_text


PROJECT_DIRS = ("sources", "references", "tasks", "memory", "reports", "experiments", ".revagent")
TASK_STATES = {"ready", "blocked", "in_progress", "completed", "canceled"}
RESEARCH_PROVIDERS = {"ollama", "vllm", "openai-compatible", "codex", "claude"}


class ResearchProviderAdapter(Protocol):
    """Minimal provider contract; adapters return data and never approve a gate."""

    name: str

    def invoke(self, *, model: str, endpoint: str, task: str, payload: dict[str, object]) -> dict[str, object]: ...


class MockResearchProvider:
    name = "mock"

    def invoke(self, *, model: str, endpoint: str, task: str, payload: dict[str, object]) -> dict[str, object]:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {
            "provider": self.name,
            "model": model,
            "task": task,
            "output": f"mock:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
            "usage": {"cost": 0.0},
        }


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not result:
        raise ValueError("name must contain at least one letter or digit")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _project_path(base: Path) -> Path:
    return base / ".revagent" / "research_project.json"


def _frontier_path(base: Path) -> Path:
    return base / "tasks" / "frontier.json"


def _load_project(base: Path) -> dict[str, object]:
    data = read_json(_project_path(base), {})
    if not isinstance(data, dict) or data.get("schema") != "revagent.research-project/v1":
        raise ValueError(f"not a RevAgent research project: {base}")
    return data


def _load_frontier(base: Path) -> dict[str, object]:
    data = read_json(_frontier_path(base), {})
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError("task frontier is missing or invalid")
    return data


def initialize_research_project(base: Path, title: str, research_question: str) -> dict[str, object]:
    """Create the prescribed project layout without overwriting an existing project."""
    if _project_path(base).exists():
        raise ValueError("research project is already initialized")
    if not title.strip() or not research_question.strip():
        raise ValueError("title and research question are required")
    for name in PROJECT_DIRS:
        (base / name).mkdir(parents=True, exist_ok=True)
    created = now_iso()
    project: dict[str, object] = {
        "schema": "revagent.research-project/v1",
        "project_id": _slug(title),
        "title": title.strip(),
        "research_question": research_question.strip(),
        "created_at": created,
        "parent": None,
        "status": "active",
        "human_gates": ["evidence_verification", "generalization_approval", "family_creation"],
    }
    frontier = {"schema": "revagent.task-frontier/v1", "revision": 0, "updated_at": created, "tasks": []}
    write_json(_project_path(base), project)
    write_json(_frontier_path(base), frontier)
    write_text(base / "memory" / "README.md", "# Project Memory\n\nOnly reviewed summaries belong here; source artifacts remain in `sources/`.\n")
    return project


def add_research_task(base: Path, title: str, *, dependencies: list[str] | None = None) -> dict[str, object]:
    _load_project(base)
    frontier = _load_frontier(base)
    tasks = frontier["tasks"]
    assert isinstance(tasks, list)
    dependencies = list(dict.fromkeys(dependencies or []))
    known = {str(item.get("task_id")) for item in tasks if isinstance(item, dict)}
    missing = [item for item in dependencies if item not in known]
    if missing:
        raise ValueError("unknown task dependencies: " + ", ".join(missing))
    task_id = f"T{len(tasks) + 1:04d}"
    task = {
        "task_id": task_id,
        "title": title.strip(),
        "state": "blocked" if dependencies else "ready",
        "dependencies": dependencies,
        "attempts": 0,
        "evidence": [],
        "verification": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if not task["title"]:
        raise ValueError("task title is required")
    tasks.append(task)
    frontier["revision"] = int(frontier.get("revision", 0)) + 1
    frontier["updated_at"] = now_iso()
    write_json(_frontier_path(base), frontier)
    return task


def research_frontier(base: Path) -> dict[str, object]:
    """Reconcile dependency state and return the durable resumable frontier."""
    frontier = _load_frontier(base)
    tasks = frontier["tasks"]
    assert isinstance(tasks, list)
    completed = {str(item["task_id"]) for item in tasks if isinstance(item, dict) and item.get("state") == "completed"}
    changed = False
    for task in tasks:
        if isinstance(task, dict) and task.get("state") == "blocked" and set(task.get("dependencies", [])) <= completed:
            task["state"] = "ready"
            task["updated_at"] = now_iso()
            changed = True
    if changed:
        frontier["revision"] = int(frontier.get("revision", 0)) + 1
        frontier["updated_at"] = now_iso()
        write_json(_frontier_path(base), frontier)
    return frontier


def record_task_result(base: Path, task_id: str, evidence_paths: list[Path]) -> dict[str, object]:
    """Record a result as completed but unverified; this never satisfies the human gate."""
    frontier = research_frontier(base)
    tasks = frontier["tasks"]
    assert isinstance(tasks, list)
    task = next((item for item in tasks if isinstance(item, dict) and item.get("task_id") == task_id), None)
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    if task.get("state") not in {"ready", "in_progress"}:
        raise ValueError(f"task {task_id} is not executable")
    if not evidence_paths:
        raise ValueError("at least one evidence artifact is required")
    records = []
    for candidate in evidence_paths:
        path = candidate if candidate.is_absolute() else base / candidate
        path = path.resolve()
        try:
            relative = path.relative_to(base.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("evidence must be inside the project") from exc
        if not path.is_file():
            raise ValueError(f"evidence does not exist: {relative}")
        records.append({"path": relative, "sha256": _sha256(path)})
    task.update({"state": "completed", "evidence": records, "verification": None, "attempts": int(task.get("attempts", 0)) + 1, "updated_at": now_iso()})
    frontier["revision"] = int(frontier.get("revision", 0)) + 1
    frontier["updated_at"] = now_iso()
    write_json(_frontier_path(base), frontier)
    return task


def verify_task_result(base: Path, task_id: str, reviewer: str, note: str, *, approved: bool) -> dict[str, object]:
    if not approved:
        raise ValueError("verification requires explicit --approved confirmation")
    if not reviewer.strip() or not note.strip():
        raise ValueError("reviewer and verification note are required")
    frontier = _load_frontier(base)
    tasks = frontier["tasks"]
    assert isinstance(tasks, list)
    task = next((item for item in tasks if isinstance(item, dict) and item.get("task_id") == task_id), None)
    if task is None or task.get("state") != "completed" or not task.get("evidence"):
        raise ValueError("only a completed evidence-backed task can be verified")
    for evidence in task["evidence"]:
        path = base / str(evidence["path"])
        if not path.is_file() or _sha256(path) != evidence["sha256"]:
            raise ValueError("evidence changed after result recording")
    task["verification"] = {"status": "human_verified", "reviewer": reviewer.strip(), "note": note.strip(), "verified_at": now_iso()}
    frontier["revision"] = int(frontier.get("revision", 0)) + 1
    frontier["updated_at"] = now_iso()
    write_json(_frontier_path(base), frontier)
    return task


def write_evidence_report(base: Path, task_id: str) -> dict[str, object]:
    frontier = _load_frontier(base)
    task = next((item for item in frontier["tasks"] if isinstance(item, dict) and item.get("task_id") == task_id), None)
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    versions = sorted((base / "reports").glob(f"{task_id}.v*.json"))
    version = len(versions) + 1
    report = {
        "schema": "revagent.evidence-report/v1",
        "report_id": f"{task_id}.v{version}",
        "version": version,
        "created_at": now_iso(),
        "task": task,
        "frontier_revision": frontier.get("revision"),
    }
    target = base / "reports" / f"{task_id}.v{version}.json"
    write_json(target, report)
    report["report_sha256"] = _sha256(target)
    return report


def evolve_research_project(base: Path, task_id: str, destination: Path, generalization: str, approver: str, note: str, *, approved: bool) -> dict[str, object]:
    """Create a child generalization only from verified evidence and explicit approval."""
    if not approved:
        raise ValueError("generalization requires explicit --approved confirmation")
    frontier = _load_frontier(base)
    task = next((item for item in frontier["tasks"] if isinstance(item, dict) and item.get("task_id") == task_id), None)
    if task is None or not isinstance(task.get("verification"), dict) or task["verification"].get("status") != "human_verified":
        raise ValueError("generalization requires a human-verified result")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("generalization destination must be empty")
    child = initialize_research_project(destination, generalization, generalization)
    child["parent"] = {
        "project_id": _load_project(base)["project_id"],
        "task_id": task_id,
        "evidence": task["evidence"],
        "approval": {"approver": approver.strip(), "note": note.strip(), "approved_at": now_iso()},
    }
    child["branch_kind"] = "verified_result_generalization"
    write_json(_project_path(destination), child)
    return child


def create_project_family(base: Path, destination: Path, title: str, approver: str, note: str, *, approved: bool) -> dict[str, object]:
    """Create a manually approved sibling/child project without claiming verified generalization."""
    if not approved or not approver.strip() or not note.strip():
        raise ValueError("family creation requires explicit approval, approver, and note")
    parent = _load_project(base)
    child = initialize_research_project(destination, title, title)
    child["parent"] = {"project_id": parent["project_id"], "approval": {"approver": approver.strip(), "note": note.strip(), "approved_at": now_iso()}}
    child["branch_kind"] = "human_approved_family"
    write_json(_project_path(destination), child)
    return child


def configure_research_provider(base: Path, provider: str, model: str, endpoint: str, scopes: list[str], budget: float, *, consent: bool) -> dict[str, object]:
    _load_project(base)
    if provider not in RESEARCH_PROVIDERS: raise ValueError("unsupported research provider")
    if not consent: raise ValueError("provider configuration requires explicit consent")
    if not model.strip() or not scopes: raise ValueError("model and task scopes are required")
    if budget < 0: raise ValueError("budget must be non-negative")
    if provider in {"ollama", "vllm"} and not (endpoint.startswith("http://127.0.0.1") or endpoint.startswith("http://localhost")):
        raise ValueError("local providers require a loopback endpoint")
    if provider not in {"ollama", "vllm"} and endpoint and not endpoint.startswith("https://"):
        raise ValueError("remote provider endpoints must use HTTPS")
    path = base / ".revagent" / "research_providers.json"
    data = read_json(path, {"schema": "revagent.research-providers/v1", "providers": {}})
    record = {"provider": provider, "model": model.strip(), "endpoint": endpoint, "task_scopes": sorted(set(scopes)), "budget": budget,
              "consent": "explicit", "configured_at": now_iso(), "credentials_stored": False, "privacy_policy": "no upload outside authorized task scopes"}
    data.setdefault("providers", {})[provider] = record; write_json(path, data); return record


def run_research_provider(
    base: Path,
    provider: str,
    task_id: str,
    scope: str,
    payload: dict[str, object],
    adapter: ResearchProviderAdapter,
) -> dict[str, object]:
    """Run one configured adapter and persist an auditable, unverified result."""
    _load_project(base)
    providers = read_json(base / ".revagent" / "research_providers.json", {}).get("providers", {})
    config = providers.get(provider) if isinstance(providers, dict) else None
    if not isinstance(config, dict) or config.get("consent") != "explicit":
        raise ValueError("provider requires an explicit stored configuration")
    if scope not in config.get("task_scopes", []):
        raise ValueError("task scope is not authorized for this provider")
    if adapter.name not in {provider, "mock"}:
        raise ValueError("adapter identity does not match configured provider")
    frontier = research_frontier(base)
    task = next((row for row in frontier["tasks"] if row.get("task_id") == task_id), None)
    if task is None or task.get("state") not in {"ready", "in_progress"}:
        raise ValueError("provider task must exist and be executable")
    response = adapter.invoke(
        model=str(config["model"]), endpoint=str(config.get("endpoint", "")), task=scope, payload=payload
    )
    usage = response.get("usage", {})
    cost = float(usage.get("cost", 0.0)) if isinstance(usage, dict) else 0.0
    if cost < 0 or cost > float(config.get("budget", 0.0)):
        raise ValueError("provider response exceeds the configured budget")
    run_id = hashlib.sha256(
        json.dumps({"provider": provider, "task_id": task_id, "scope": scope, "payload": payload}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    artifact = base / "experiments" / f"{task_id}.provider-{run_id}.json"
    record = {
        "schema": "revagent.research-provider-run/v1",
        "run_id": run_id,
        "provider": provider,
        "adapter": adapter.name,
        "task_id": task_id,
        "scope": scope,
        "request": payload,
        "response": response,
        "status": "unverified_model_output",
        "created_at": now_iso(),
    }
    write_json(artifact, record)
    record["artifact"] = artifact.relative_to(base).as_posix()
    record["sha256"] = _sha256(artifact)
    return record


def write_research_dashboard(base: Path) -> Path:
    project = _load_project(base); frontier = research_frontier(base)
    rows = ["<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(html.escape(str(t["task_id"])), html.escape(str(t["title"])), html.escape(str(t["state"]))) for t in frontier["tasks"]]
    body = "<!doctype html><html><head><meta charset='utf-8'><title>Research Project</title></head><body>" + f"<h1>{html.escape(str(project['title']))}</h1><p>{html.escape(str(project['research_question']))}</p>" + "<table><tbody>" + "".join(rows) + "</tbody></table><p>Agents cannot verify evidence, approve generalization, or create families.</p></body></html>"
    target = base / "reports" / "index.html"; write_text(target, body); return target
