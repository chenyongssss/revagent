"""Plan evolution and conservative supervisor loop helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ._models import Config
from ._utils import load_config, now_iso, read_json, read_text, write_json, write_text
from .agent import build_agent_state, run_agent_once, write_agent_state
from .external_agent import (
    build_monitor_report,
    build_external_agent_prompt,
    load_external_agent_runs,
    render_external_agent_supervision,
    run_external_agent,
    write_external_agent_prompt,
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


def supervisor_feedback_path(config: Config) -> Path:
    return config.workspace / "supervisor_feedback.json"


def supervisor_workers_path(config: Config) -> Path:
    return config.workspace / "supervisor_workers.json"


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


def phase_9_plan_block() -> str:
    return """## Phase 9 Scope

- Add supervisor evaluation and strategy feedback:
  - `revagent supervisor-feedback`
- Generate a read-only strategy report from supervisor runs, agent eval results, validation output, manual gates, and `plan.md`.
- Feed concise strategy feedback into `supervisor-plan` so the next loop can prioritize safe actions and surface blocked work clearly.
- Keep feedback advisory only; do not auto-approve manual gates, mutate strategy policy, launch external agents, or run tests automatically.

## Phase 9 Test Plan

- Verify `supervisor-feedback` writes JSON/Markdown from eval, validation, and supervisor run history.
- Verify failed eval checks and failed supervisor tasks become strategy recommendations.
- Verify `supervisor-plan` includes the latest feedback summary.
"""


def phase_10_plan_block() -> str:
    return """## Phase 10 Scope

- Add conservative multi-worker orchestration:
  - `revagent supervisor-workers [--workers N] [--queue]`
- Split safe supervisor tasks into isolated external-worker prompts.
- Default mode writes prompts and a worker plan only; it does not launch workers.
- `--queue` may create queued external run launch scripts, but must not start background processes or weaken manual gates.
- Workers must inherit the same forbidden actions as `revagent run`.

## Phase 10 Test Plan

- Verify `supervisor-workers` writes worker JSON/Markdown and prompt files without appending external runs.
- Verify `supervisor-workers --queue` records queued external runs without starting them.
- Verify worker prompts preserve manual safety gate restrictions.
"""


def maybe_update_plan_md(base: Path, phase: int = 8) -> Path:
    path = repo_plan_path(base)
    text = read_text(path) if path.exists() else "# RevAgent Iteris-Style Roadmap\n\n"
    if phase == 8 and not phase_present(text, 8):
        write_text(path, text.rstrip() + "\n\n" + phase_8_plan_block())
    if phase == 9 and not phase_present(text, 9):
        write_text(path, text.rstrip() + "\n\n" + phase_9_plan_block())
    if phase == 10 and not phase_present(text, 10):
        write_text(path, text.rstrip() + "\n\n" + phase_10_plan_block())
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


def failed_eval_checks(report: dict[str, object]) -> list[dict[str, object]]:
    failures = []
    fixtures = report.get("fixtures", [])
    if not isinstance(fixtures, list):
        return failures
    for fixture in fixtures:
        for check in fixture.get("checks", []):
            if not check.get("ok"):
                failures.append(
                    {
                        "fixture": fixture.get("fixture", ""),
                        "check": check.get("name", ""),
                        "detail": check.get("detail", ""),
                    }
                )
    return failures


def build_supervisor_feedback(base: Path, *, update_plan: bool = False) -> dict[str, object]:
    config = load_config(base)
    if update_plan:
        maybe_update_plan_md(base, 9)
    plan_path = repo_plan_path(base)
    plan_text = read_text(plan_path) if plan_path.exists() else ""
    validation = validate_workspace(base)
    eval_report = read_json(config.workspace / "agent_eval_report.json", {})
    if not isinstance(eval_report, dict):
        eval_report = {}
    runs = load_supervisor_runs(config)
    latest_run = runs[-1] if runs else {}
    failed_tasks = [
        {"kind": task.get("kind", ""), "status": task.get("status", ""), "result": task.get("result", "")}
        for run in runs[-10:]
        for task in run.get("executed", [])
        if task.get("status") == "failed"
    ]
    blocked_tasks = list(latest_run.get("blocked", [])) if latest_run else []
    eval_failures = failed_eval_checks(eval_report)
    recommendations = []
    if eval_failures:
        recommendations.append(
            {
                "kind": "fix_eval_regression",
                "priority": "high",
                "command": "revagent agent-eval --all",
                "reason": f"{len(eval_failures)} eval checks are failing",
            }
        )
    if failed_tasks:
        recommendations.append(
            {
                "kind": "recover_failed_supervisor_task",
                "priority": "high",
                "command": "revagent supervisor-loop --dry-run",
                "reason": f"{len(failed_tasks)} supervisor tasks failed in recent runs",
            }
        )
    if validation.get("issues"):
        recommendations.append(
            {
                "kind": "repair_validation_errors",
                "priority": "high",
                "command": "revagent validate",
                "reason": f"{len(validation.get('issues', []))} validation errors are present",
            }
        )
    elif validation.get("warnings"):
        recommendations.append(
            {
                "kind": "inspect_validation_warnings",
                "priority": "medium",
                "command": "revagent validate",
                "reason": f"{len(validation.get('warnings', []))} validation warnings are present",
            }
        )
    if blocked_tasks:
        recommendations.append(
            {
                "kind": "resolve_manual_gates",
                "priority": "medium",
                "command": "revagent agent-decisions",
                "reason": f"{len(blocked_tasks)} manual-only supervisor tasks are blocking autonomy",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "kind": "continue_safe_loop",
                "priority": "low",
                "command": "revagent supervisor-loop --cycles 1",
                "reason": "no eval, validation, or supervisor failures detected",
            }
        )
    feedback = {
        "version": 1,
        "generated_at": now_iso(),
        "plan_path": str(plan_path),
        "completed_phase_count": completed_phase_count(plan_text),
        "eval_ok": bool(eval_report.get("ok")) if eval_report else False,
        "eval_failures": eval_failures,
        "validation_ok": validation.get("ok", False),
        "validation_warnings": validation.get("warnings", []),
        "validation_issues": validation.get("issues", []),
        "supervisor_run_count": len(runs),
        "latest_supervisor_status": latest_run.get("status", "") if latest_run else "",
        "failed_supervisor_tasks": failed_tasks,
        "blocked_tasks": blocked_tasks,
        "recommendations": recommendations,
        "safety": {
            "advisory_only": True,
            "approves_manual_gates": False,
            "launches_external_agents": False,
            "runs_tests_automatically": False,
        },
    }
    write_json(supervisor_feedback_path(config), feedback)
    write_text(config.workspace / "supervisor_feedback.md", render_supervisor_feedback(feedback))
    return feedback


def feedback_summary(feedback: dict[str, object]) -> dict[str, object]:
    recommendations = list(feedback.get("recommendations", []))
    return {
        "eval_ok": feedback.get("eval_ok", False),
        "validation_ok": feedback.get("validation_ok", False),
        "latest_supervisor_status": feedback.get("latest_supervisor_status", ""),
        "top_recommendation": recommendations[0] if recommendations else {},
    }


def worker_goal_for_task(task: dict[str, object], index: int) -> str:
    return (
        f"Supervisor worker {index}: inspect and advance only safe RevAgent task `{task.get('kind', '')}`. "
        f"Suggested command: {task.get('command', '')}. "
        "Do not approve manual gates, apply manuscript edits, accept LLM drafts, record experiments, or launch nested agents."
    )


def build_supervisor_workers(
    base: Path,
    *,
    workers: int = 2,
    queue: bool = False,
    update_plan: bool = False,
) -> dict[str, object]:
    if workers <= 0:
        raise ValueError("workers must be positive")
    config = load_config(base)
    if update_plan:
        maybe_update_plan_md(base, 10)
    plan = build_supervisor_plan(base)
    safe_tasks = [task for task in plan.get("tasks", []) if task.get("safe_to_execute") and task.get("status") == "pending"]
    assignments = []
    for index, task in enumerate(safe_tasks[:workers], start=1):
        goal = worker_goal_for_task(task, index)
        if queue:
            run = run_external_agent(base, goal=goal, detach=True)
            prompt_path = str(run.get("prompt_path", ""))
            external_run_id = str(run.get("run_id", ""))
            launch_script = str(run.get("launch_script", ""))
            status = "queued"
        else:
            prompt = build_external_agent_prompt(base, goal=goal, limit=1)
            prompt_path = str(write_external_agent_prompt(base, prompt))
            external_run_id = ""
            launch_script = ""
            status = "planned"
        assignments.append(
            {
                "worker_id": f"W{index:03d}",
                "task_id": task.get("id", ""),
                "task_kind": task.get("kind", ""),
                "goal": goal,
                "status": status,
                "prompt_path": prompt_path,
                "external_run_id": external_run_id,
                "launch_script": launch_script,
                "safe_to_execute": True,
            }
        )
    worker_plan = {
        "version": 1,
        "generated_at": now_iso(),
        "queue": queue,
        "requested_workers": workers,
        "assigned_workers": len(assignments),
        "assignments": assignments,
        "blocked_tasks": [task for task in plan.get("tasks", []) if not task.get("safe_to_execute")],
        "safety": {
            "launches_processes": False,
            "queues_only": bool(queue),
            "approves_manual_gates": False,
            "applies_candidate_edits": False,
        },
    }
    write_json(supervisor_workers_path(config), worker_plan)
    write_text(config.workspace / "supervisor_workers.md", render_supervisor_workers(worker_plan))
    return worker_plan


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
    feedback = build_supervisor_feedback(base)
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
        "feedback": feedback_summary(feedback),
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
    feedback = plan.get("feedback") or {}
    top = feedback.get("top_recommendation", {}) if isinstance(feedback, dict) else {}
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
    ]
    if feedback:
        lines.append(f"- Feedback eval ok: {str(feedback.get('eval_ok', False)).lower()}")
        lines.append(f"- Feedback recommendation: `{top.get('command', '')}` {top.get('reason', '')}")
    lines.extend(["", "## Tasks", ""])
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


def render_supervisor_feedback(feedback: dict[str, object]) -> str:
    lines = [
        "# Supervisor Feedback",
        "",
        f"- Generated at: {feedback.get('generated_at', '')}",
        f"- Completed phases: {feedback.get('completed_phase_count', 0)}",
        f"- Eval ok: {str(feedback.get('eval_ok', False)).lower()}",
        f"- Validation ok: {str(feedback.get('validation_ok', False)).lower()}",
        f"- Supervisor runs: {feedback.get('supervisor_run_count', 0)}",
        f"- Latest supervisor status: {feedback.get('latest_supervisor_status', '') or 'none'}",
        "",
        "## Recommendations",
        "",
    ]
    for item in feedback.get("recommendations", []):
        lines.append(f"- `{item.get('priority', '')}` {item.get('kind', '')}")
        lines.append(f"  command: `{item.get('command', '')}`")
        lines.append(f"  reason: {item.get('reason', '')}")
    failures = feedback.get("eval_failures", [])
    if failures:
        lines.extend(["", "## Eval Failures", ""])
        for failure in failures:
            lines.append(f"- `{failure.get('fixture', '')}` {failure.get('check', '')}: {failure.get('detail', '')}")
    failed_tasks = feedback.get("failed_supervisor_tasks", [])
    if failed_tasks:
        lines.extend(["", "## Failed Supervisor Tasks", ""])
        for task in failed_tasks:
            lines.append(f"- `{task.get('kind', '')}` {task.get('status', '')}: {task.get('result', '')}")
    blocked = feedback.get("blocked_tasks", [])
    if blocked:
        lines.extend(["", "## Manual-Only Blockers", ""])
        for task in blocked:
            lines.append(f"- `{task.get('kind', '')}` command=`{task.get('command', '')}`")
    return "\n".join(lines).rstrip() + "\n"


def render_supervisor_workers(worker_plan: dict[str, object]) -> str:
    lines = [
        "# Supervisor Workers",
        "",
        f"- Generated at: {worker_plan.get('generated_at', '')}",
        f"- Queue mode: {str(worker_plan.get('queue', False)).lower()}",
        f"- Requested workers: {worker_plan.get('requested_workers', 0)}",
        f"- Assigned workers: {worker_plan.get('assigned_workers', 0)}",
        "",
        "## Assignments",
        "",
    ]
    assignments = worker_plan.get("assignments", [])
    if not assignments:
        lines.append("No safe worker assignments available.")
    for assignment in assignments:
        lines.append(f"- `{assignment.get('worker_id', '')}` {assignment.get('task_kind', '')} status={assignment.get('status', '')}")
        lines.append(f"  prompt: `{assignment.get('prompt_path', '')}`")
        if assignment.get("external_run_id"):
            lines.append(f"  external run: `{assignment.get('external_run_id', '')}`")
        if assignment.get("launch_script"):
            lines.append(f"  launch: `{assignment.get('launch_script', '')}`")
    blocked = worker_plan.get("blocked_tasks", [])
    if blocked:
        lines.extend(["", "## Manual-Only Tasks", ""])
        for task in blocked:
            lines.append(f"- `{task.get('id', '')}` {task.get('kind', '')} command=`{task.get('command', '')}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "build_supervisor_plan",
    "build_supervisor_feedback",
    "load_supervisor_runs",
    "maybe_update_plan_md",
    "render_supervisor_feedback",
    "render_supervisor_plan",
    "render_supervisor_runs",
    "build_supervisor_workers",
    "render_supervisor_workers",
    "run_supervisor_loop",
]
