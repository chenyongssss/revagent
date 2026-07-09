"""Plan evolution and conservative supervisor loop helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ._models import Config
from ._utils import load_config, now_iso, read_text, write_json, write_text
from .agent import build_agent_state, run_agent_once, write_agent_state
from .external_agent import (
    build_monitor_report,
    load_external_agent_runs,
    render_external_agent_supervision,
    write_dashboard_html,
    write_monitor_report,
)
from .memory import write_revision_memory
from .readiness import write_revision_readiness
from .validation import validate_workspace

PHASE_RE = re.compile(r"^## Phase (\d+) Scope", re.MULTILINE)


def supervisor_plan_path(config: Config) -> Path:
    return config.workspace / "supervisor_plan.json"


def supervisor_runs_path(config: Config) -> Path:
    return config.workspace / "supervisor_runs.jsonl"


def repo_plan_path(base: Path) -> Path:
    local = base / "plan.md"
    if local.exists():
        return local
    return Path(__file__).resolve().parents[2] / "plan.md"


def completed_phase_count(plan_text: str) -> int:
    phases = [int(match.group(1)) for match in PHASE_RE.finditer(plan_text)]
    return max(phases) if phases else 0


def phase_present(plan_text: str, phase: int) -> bool:
    return f"## Phase {phase} Scope" in plan_text


def phase_8_plan_block() -> str:
    return """## Phase 8 Scope

- Add automatic plan evolution and a conservative supervisor loop:
  - `revagent supervisor-plan [--update-plan]`
  - `revagent supervisor-loop [--cycles N] [--dry-run]`
- Generate the next safe supervisor plan from `plan.md`, agent state, monitor/dashboard state, external-run ledger, validation output, and test expectations.
- Execute only safe internal RevAgent commands: refresh monitor/dashboard/memory/readiness, run safe-auto tasks until blocked, and summarize external-run supervision.
- Never approve proof workflows, approve/apply candidate edits, accept LLM drafts, record experiment results, launch external agents, or run tests automatically.

## Phase 8 Test Plan

- Verify `supervisor-plan` writes JSON/Markdown from plan, ledger, dashboard, and validation context.
- Verify `supervisor-plan --update-plan` appends Phase 8 once and is idempotent.
- Verify `supervisor-loop --dry-run` records intended safe actions without executing them.
- Verify `supervisor-loop` executes safe internal actions and stops at manual gates.
"""


def maybe_update_plan_md(base: Path, phase: int = 8) -> Path:
    path = repo_plan_path(base)
    text = read_text(path) if path.exists() else "# RevAgent Iteris-Style Roadmap\n\n"
    if phase == 8 and not phase_present(text, 8):
        write_text(path, text.rstrip() + "\n\n" + phase_8_plan_block())
    return path


def supervisor_tasks(base: Path, monitor: dict[str, object], validation: dict[str, object]) -> list[dict[str, object]]:
    config = load_config(base)
    state = build_agent_state(base)
    summary = state.get("summary", {})
    external_runs = load_external_agent_runs(config)
    tasks: list[dict[str, object]] = [
        {
            "id": "SUP001",
            "kind": "refresh_supervisor_context",
            "status": "pending",
            "safe_to_execute": True,
            "command": "revagent monitor",
            "reason": "refresh monitor, dashboard, readiness, memory, and decisions before selecting work",
        }
    ]
    if summary.get("pending", 0) or summary.get("stale", 0):
        tasks.append(
            {
                "id": "SUP002",
                "kind": "run_safe_internal_tasks",
                "status": "pending",
                "safe_to_execute": True,
                "command": "revagent agent-run --until-blocked",
                "reason": "safe-auto tasks are available and can run until blocked by manual gates",
            }
        )
    if external_runs:
        tasks.append(
            {
                "id": "SUP003",
                "kind": "summarize_external_runs",
                "status": "pending",
                "safe_to_execute": True,
                "command": "revagent run-supervise",
                "reason": "external-run ledger exists and should be summarized for recovery",
            }
        )
    if validation.get("warnings") or validation.get("issues"):
        tasks.append(
            {
                "id": "SUP004",
                "kind": "inspect_validation",
                "status": "manual_required",
                "safe_to_execute": False,
                "command": "revagent validate",
                "reason": "validation warnings or errors need operator review before broader automation",
            }
        )
    tasks.append(
        {
            "id": "SUP005",
            "kind": "run_tests",
            "status": "manual_required",
            "safe_to_execute": False,
            "command": "python -m pytest",
            "reason": "tests are required verification but supervisor-loop does not execute arbitrary shell commands",
        }
    )
    if monitor.get("manual_decisions"):
        tasks.append(
            {
                "id": "SUP006",
                "kind": "manual_gate_review",
                "status": "manual_required",
                "safe_to_execute": False,
                "command": "revagent agent-decisions",
                "reason": "manual gates remain open and must not be auto-approved",
            }
        )
    return tasks


def build_supervisor_plan(base: Path, *, update_plan: bool = False) -> dict[str, object]:
    config = load_config(base)
    if update_plan:
        maybe_update_plan_md(base, 8)
    plan_path = repo_plan_path(base)
    plan_text = read_text(plan_path) if plan_path.exists() else ""
    write_revision_readiness(base)
    write_revision_memory(base)
    monitor = build_monitor_report(base)
    dashboard_path = write_dashboard_html(base)
    validation = validate_workspace(base)
    external_runs = load_external_agent_runs(config)
    phase_count = completed_phase_count(plan_text)
    next_phase = phase_count + 1 if not phase_present(plan_text, 8) else 8
    plan = {
        "version": 1,
        "generated_at": now_iso(),
        "plan_path": str(plan_path),
        "completed_phase_count": phase_count,
        "next_phase": next_phase,
        "phase": "automatic plan evolution and supervisor loop",
        "dashboard_path": str(dashboard_path),
        "monitor_recommendation": monitor.get("recommended_command", ""),
        "monitor_reason": monitor.get("recommendation_reason", ""),
        "agent_summary": monitor.get("summary", {}),
        "external_run_count": len(external_runs),
        "validation_ok": validation.get("ok", False),
        "validation_warnings": validation.get("warnings", []),
        "validation_issues": validation.get("issues", []),
        "tasks": supervisor_tasks(base, monitor, validation),
        "safety": {
            "executes_shell": False,
            "launches_external_agents": False,
            "approves_manual_gates": False,
            "runs_tests_automatically": False,
        },
    }
    write_json(supervisor_plan_path(config), plan)
    write_text(config.workspace / "supervisor_plan.md", render_supervisor_plan(plan))
    return plan


def render_supervisor_plan(plan: dict[str, object]) -> str:
    lines = [
        "# Supervisor Plan",
        "",
        f"- Generated at: {plan.get('generated_at', '')}",
        f"- Plan path: `{plan.get('plan_path', '')}`",
        f"- Completed phases: {plan.get('completed_phase_count', 0)}",
        f"- Current phase: {plan.get('next_phase', '')} {plan.get('phase', '')}",
        f"- Dashboard: `{plan.get('dashboard_path', '')}`",
        f"- Monitor recommendation: `{plan.get('monitor_recommendation', '')}`",
        f"- Validation ok: {str(plan.get('validation_ok', False)).lower()}",
        "",
        "## Tasks",
        "",
    ]
    for task in plan.get("tasks", []):
        lines.append(f"- `{task.get('id', '')}` [{task.get('status', '')}] {task.get('kind', '')}")
        lines.append(f"  command: `{task.get('command', '')}`")
        lines.append(f"  safe: {str(task.get('safe_to_execute', False)).lower()}")
        lines.append(f"  reason: {task.get('reason', '')}")
    warnings = plan.get("validation_warnings", [])
    issues = plan.get("validation_issues", [])
    if warnings or issues:
        lines.extend(["", "## Validation", ""])
        for warning in warnings:
            lines.append(f"- warning: {warning}")
        for issue in issues:
            lines.append(f"- error: {issue}")
    return "\n".join(lines).rstrip() + "\n"


def load_supervisor_runs(config: Config) -> list[dict[str, object]]:
    path = supervisor_runs_path(config)
    if not path.exists():
        return []
    runs = []
    for line in read_text(path).splitlines():
        if line.strip():
            runs.append(json.loads(line))
    return runs


def write_supervisor_runs(config: Config, runs: list[dict[str, object]]) -> None:
    write_text(supervisor_runs_path(config), "".join(json.dumps(run, ensure_ascii=False, sort_keys=True) + "\n" for run in runs))
    write_text(config.workspace / "supervisor_runs.md", render_supervisor_runs(runs))


def append_supervisor_run(config: Config, record: dict[str, object]) -> None:
    runs = load_supervisor_runs(config)
    runs.append(record)
    write_supervisor_runs(config, runs)


def execute_supervisor_task(base: Path, task: dict[str, object], *, dry_run: bool) -> dict[str, object]:
    result = dict(task)
    result["started_at"] = now_iso()
    if dry_run:
        result["status"] = "planned"
        result["result"] = "dry-run only"
        result["finished_at"] = now_iso()
        return result
    kind = task.get("kind")
    if kind == "refresh_supervisor_context":
        monitor = write_monitor_report(base)
        write_dashboard_html(base)
        result["result"] = str(monitor.get("recommended_command", ""))
        result["status"] = "done"
    elif kind == "run_safe_internal_tasks":
        state = run_agent_once(base, until_blocked=True)
        result["result"] = state.get("summary", {})
        result["status"] = "done" if state.get("summary", {}).get("failed", 0) == 0 else "failed"
    elif kind == "summarize_external_runs":
        config = load_config(base)
        text = render_external_agent_supervision(load_external_agent_runs(config))
        write_text(config.workspace / "external_agent_supervision.md", text)
        result["result"] = str(config.workspace / "external_agent_supervision.md")
        result["status"] = "done"
    else:
        result["status"] = "skipped"
        result["result"] = "manual-only task"
    result["finished_at"] = now_iso()
    return result


def run_supervisor_loop(base: Path, *, cycles: int = 1, dry_run: bool = False, update_plan: bool = False) -> dict[str, object]:
    if cycles <= 0:
        raise ValueError("cycles must be positive")
    config = load_config(base)
    record: dict[str, object] = {
        "version": 1,
        "run_id": now_iso(),
        "started_at": now_iso(),
        "finished_at": "",
        "cycles": cycles,
        "dry_run": dry_run,
        "status": "running",
        "executed": [],
        "blocked": [],
    }
    for _ in range(cycles):
        plan = build_supervisor_plan(base, update_plan=update_plan)
        safe_tasks = [task for task in plan.get("tasks", []) if task.get("safe_to_execute") and task.get("status") == "pending"]
        manual_tasks = [task for task in plan.get("tasks", []) if not task.get("safe_to_execute")]
        record["blocked"] = manual_tasks
        if not safe_tasks:
            break
        for task in safe_tasks:
            result = execute_supervisor_task(base, task, dry_run=dry_run)
            record["executed"].append(result)
            if result.get("status") == "failed":
                record["status"] = "failed"
                record["finished_at"] = now_iso()
                append_supervisor_run(config, record)
                return record
        if dry_run:
            break
    record["status"] = "blocked" if record.get("blocked") else "complete"
    record["finished_at"] = now_iso()
    append_supervisor_run(config, record)
    return record


def render_supervisor_runs(runs: list[dict[str, object]]) -> str:
    lines = ["# Supervisor Runs", ""]
    if not runs:
        lines.append("No supervisor runs recorded yet.")
        return "\n".join(lines) + "\n"
    for run in runs[-80:]:
        lines.append(f"- `{run.get('run_id', '')}` {run.get('status', '')} dry_run={str(run.get('dry_run', False)).lower()} cycles={run.get('cycles', '')}")
        for task in run.get("executed", []):
            lines.append(f"  - {task.get('kind', '')}: {task.get('status', '')}")
        blocked = run.get("blocked", [])
        if blocked:
            lines.append(f"  blocked: {', '.join(str(task.get('kind', '')) for task in blocked)}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "build_supervisor_plan",
    "load_supervisor_runs",
    "maybe_update_plan_md",
    "render_supervisor_plan",
    "render_supervisor_runs",
    "run_supervisor_loop",
]
