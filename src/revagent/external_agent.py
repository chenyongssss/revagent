"""External agent runner, monitor recovery, and static dashboard helpers."""

from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
from pathlib import Path

from ._models import Config
from ._utils import load_config, now_iso, read_text, write_text
from .agent import (
    build_agent_dashboard,
    build_agent_report,
    build_agent_state,
    next_agent_task,
    refresh_agent_decisions,
    render_agent_dashboard,
    render_agent_next,
    write_agent_dashboard,
    write_agent_report,
    write_agent_state,
)
from .memory import build_revision_memory, render_revision_memory, write_revision_memory
from .readiness import write_revision_readiness

EXTERNAL_BACKENDS = {"codex"}
EXTERNAL_RUN_MARK_STATUSES = {"done", "failed", "canceled"}


def external_agent_runs_path(config: Config) -> Path:
    return config.workspace / "external_agent_runs.jsonl"


def load_external_agent_runs(config: Config) -> list[dict[str, object]]:
    path = external_agent_runs_path(config)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"status": "invalid", "raw": line})
    return records


def render_external_agent_runs(runs: list[dict[str, object]]) -> str:
    lines = ["# External Agent Runs", ""]
    if not runs:
        lines.append("No external agent runs recorded yet.")
        return "\n".join(lines) + "\n"
    for run in runs[-80:]:
        lines.append(
            f"- `{run.get('run_id', '')}` {run.get('status', '')} "
            f"backend={run.get('backend', '')} exit={run.get('exit_code', '')}"
        )
        if run.get("goal"):
            lines.append(f"  goal: {run['goal']}")
        if run.get("prompt_path"):
            lines.append(f"  prompt: `{run['prompt_path']}`")
        if run.get("stdout_path"):
            lines.append(f"  stdout: `{run['stdout_path']}`")
        if run.get("stderr_path"):
            lines.append(f"  stderr: `{run['stderr_path']}`")
        if run.get("error"):
            lines.append(f"  error: {run['error']}")
    return "\n".join(lines) + "\n"


def write_external_agent_runs(config: Config, runs: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(run, ensure_ascii=False, sort_keys=True) + "\n" for run in runs)
    write_text(external_agent_runs_path(config), text)
    write_text(config.workspace / "external_agent_runs.md", render_external_agent_runs(runs))


def append_external_agent_run(config: Config, record: dict[str, object]) -> None:
    runs = load_external_agent_runs(config)
    runs.append(record)
    write_external_agent_runs(config, runs)


def get_external_agent_run(config: Config, run_id: str | None = None) -> dict[str, object]:
    runs = load_external_agent_runs(config)
    if not runs:
        raise ValueError("no external agent runs recorded")
    if not run_id:
        return runs[-1]
    for run in runs:
        if str(run.get("run_id", "")) == run_id:
            return run
    raise ValueError(f"unknown external agent run {run_id}")


def mark_external_agent_run(base: Path, run_id: str, status: str, note: str = "") -> dict[str, object]:
    if status not in EXTERNAL_RUN_MARK_STATUSES:
        raise ValueError(f"invalid external run status {status}; choose one of {', '.join(sorted(EXTERNAL_RUN_MARK_STATUSES))}")
    config = load_config(base)
    runs = load_external_agent_runs(config)
    if not runs:
        raise ValueError("no external agent runs recorded")
    updated: dict[str, object] | None = None
    for run in runs:
        if str(run.get("run_id", "")) == run_id:
            run["status"] = status
            run["marked_at"] = now_iso()
            run["operator_note"] = note
            if status == "failed" and note and not run.get("error"):
                run["error"] = note
            if status in {"done", "failed", "canceled"} and not run.get("finished_at"):
                run["finished_at"] = now_iso()
            updated = run
            break
    if updated is None:
        raise ValueError(f"unknown external agent run {run_id}")
    write_external_agent_runs(config, runs)
    return updated


def external_run_recovery_hint(run: dict[str, object]) -> str:
    status = str(run.get("status", ""))
    if status == "queued":
        return f"run launch script `{run.get('launch_script', '')}` or use `revagent run-recover`"
    if status == "failed":
        if "not found" in str(run.get("error", "")).lower():
            return "install or fix the backend command, then run `revagent run-recover`"
        return "inspect stdout/stderr logs, then run `revagent run-recover`"
    if status == "running":
        return "check whether the external process is still active; if not, run `revagent run-recover`"
    if status == "dry_run":
        return "review the prompt, then run `revagent run`"
    return "no recovery needed"


def render_external_agent_run_detail(run: dict[str, object]) -> str:
    lines = [
        "# External Agent Run",
        "",
        f"- Run: `{run.get('run_id', '')}`",
        f"- Status: {run.get('status', '')}",
        f"- Backend: {run.get('backend', '')}",
        f"- Goal: {run.get('goal', '') or 'none'}",
        f"- Dangerous autonomy: {str(run.get('dangerous_autonomy', False)).lower()}",
        f"- Prompt: `{run.get('prompt_path', '')}`",
        f"- Stdout: `{run.get('stdout_path', '')}`",
        f"- Stderr: `{run.get('stderr_path', '')}`",
        f"- Launch script: `{run.get('launch_script', '')}`",
        f"- Error: {run.get('error', '') or 'none'}",
        f"- Operator note: {run.get('operator_note', '') or 'none'}",
        f"- Recovery: {external_run_recovery_hint(run)}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def recover_external_agent_run(
    base: Path,
    *,
    run_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    config = load_config(base)
    previous = get_external_agent_run(config, run_id)
    return run_external_agent(
        base,
        backend=str(previous.get("backend", "codex") or "codex"),
        goal=str(previous.get("goal", "")),
        dry_run=dry_run,
        detach=bool(previous.get("status") == "queued") and not dry_run,
        dangerous_autonomy=bool(previous.get("dangerous_autonomy", False)),
    )


def codex_command() -> str | None:
    if os.name == "nt":
        cmd = shutil.which("codex.cmd")
        if cmd:
            return cmd
    return shutil.which("codex")


def backend_available(backend: str) -> bool:
    if backend == "codex":
        return codex_command() is not None
    return False


def safe_command_list() -> list[str]:
    return [
        "revagent monitor",
        "revagent agent-status",
        "revagent agent-next",
        "revagent agent-run --until-blocked",
        "revagent agent-report",
        "revagent dashboard",
        "revagent validate",
    ]


def forbidden_actions(dangerous_autonomy: bool) -> list[str]:
    if dangerous_autonomy:
        return [
            "Do not delete user work or rewrite history.",
            "Do not run destructive shell commands.",
            "Explain every manual gate before taking irreversible action.",
        ]
    return [
        "Do not approve proof workflows.",
        "Do not approve or apply candidate edits.",
        "Do not accept LLM drafts.",
        "Do not record experiment results.",
        "Do not run experiments with --record.",
        "Do not edit manuscript files directly.",
    ]


def build_external_agent_prompt(base: Path, *, goal: str = "", limit: int | None = None, dangerous_autonomy: bool = False) -> str:
    config = load_config(base)
    dashboard = build_agent_dashboard(base)
    memory = build_revision_memory(base)
    state = build_agent_state(base)
    next_text = render_agent_next(state).strip()
    repo_plan = Path(__file__).resolve().parents[2] / "plan.md"
    plan_path = base / "plan.md"
    if not plan_path.exists() and repo_plan.exists():
        plan_path = repo_plan
    plan_excerpt = read_text(plan_path)[:4000] if plan_path.exists() else "plan.md is missing; create it from the current Iteris-style roadmap before continuing."
    prompt = [
        "You are an external RevAgent implementation assistant running inside this repository.",
        "",
        "First, read `plan.md` and continue that roadmap. Keep changes scoped to the current phase.",
        "",
        f"Goal: {goal or 'continue the next RevAgent Iteris-style task'}",
        f"Workspace: {config.workspace}",
        f"Main TeX: {config.main_tex}",
        f"Task limit hint: {limit if limit is not None else 'none'}",
        f"Dangerous autonomy: {str(dangerous_autonomy).lower()}",
        "",
        "Allowed default commands:",
        *(f"- `{command}`" for command in safe_command_list()),
        "",
        "Forbidden by default:",
        *(f"- {action}" for action in forbidden_actions(dangerous_autonomy)),
        "",
        "Current next action:",
        next_text,
        "",
        "Current dashboard summary:",
        render_agent_dashboard(dashboard),
        "",
        "Current revision memory:",
        render_revision_memory(memory)[:5000],
        "",
        "Current plan.md excerpt:",
        plan_excerpt,
        "",
        "Before finishing, run relevant tests if you changed code and summarize exactly what changed.",
    ]
    return "\n".join(prompt).rstrip() + "\n"


def write_external_agent_prompt(base: Path, prompt: str) -> Path:
    config = load_config(base)
    prompts = config.workspace / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    path = prompts / f"external-agent-{now_iso().replace(':', '').replace('+', 'Z')}.md"
    write_text(path, prompt)
    return path


def shell_quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def write_external_launch_script(base: Path, record: dict[str, object], prompt_path: Path) -> Path:
    config = load_config(base)
    runners = config.workspace / "runners"
    runners.mkdir(parents=True, exist_ok=True)
    safe_run_id = str(record["run_id"]).replace(":", "").replace("+", "Z")
    backend = str(record.get("backend", "codex"))
    command = str(record.get("command") or backend)
    if os.name == "nt":
        script = runners / f"external-agent-{safe_run_id}.cmd"
        text = "\n".join(["@echo off", "setlocal", f"cd /d {shell_quote(str(base))}", f"{shell_quote(command)} < {shell_quote(str(prompt_path))}", ""])
    else:
        script = runners / f"external-agent-{safe_run_id}.sh"
        text = "\n".join(["#!/usr/bin/env sh", "set -eu", f"cd {shell_quote(str(base))}", f"{shell_quote(command)} < {shell_quote(str(prompt_path))}", ""])
    write_text(script, text)
    return script


def run_external_agent(
    base: Path,
    *,
    backend: str = "codex",
    goal: str = "",
    dry_run: bool = False,
    detach: bool = False,
    limit: int | None = None,
    dangerous_autonomy: bool = False,
) -> dict[str, object]:
    if backend not in EXTERNAL_BACKENDS:
        raise ValueError(f"unsupported external agent backend {backend}; choose one of {', '.join(sorted(EXTERNAL_BACKENDS))}")
    config = load_config(base)
    prompt = build_external_agent_prompt(base, goal=goal, limit=limit, dangerous_autonomy=dangerous_autonomy)
    prompt_path = write_external_agent_prompt(base, prompt)
    command_path = codex_command() if backend == "codex" else None
    record = {
        "run_id": now_iso(),
        "backend": backend,
        "goal": goal,
        "dry_run": dry_run,
        "dangerous_autonomy": dangerous_autonomy,
        "prompt_path": str(prompt_path),
        "command": command_path or backend,
        "started_at": now_iso(),
        "finished_at": "",
        "status": "dry_run" if dry_run else "running",
        "exit_code": None,
        "stdout_path": "",
        "stderr_path": "",
        "launch_script": "",
        "error": "",
    }
    if dry_run:
        record["finished_at"] = now_iso()
        return {**record, "prompt": prompt}
    if detach:
        script = write_external_launch_script(base, record, prompt_path)
        record["status"] = "queued"
        record["finished_at"] = now_iso()
        record["launch_script"] = str(script)
        append_external_agent_run(config, record)
        return record
    if not command_path:
        record["status"] = "failed"
        record["finished_at"] = now_iso()
        record["error"] = f"{backend} command not found on PATH"
        append_external_agent_run(config, record)
        return record
    logs = config.workspace / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    safe_run_id = str(record["run_id"]).replace(":", "").replace("+", "Z")
    stdout_path = logs / f"external-agent-{safe_run_id}.stdout.log"
    stderr_path = logs / f"external-agent-{safe_run_id}.stderr.log"
    try:
        result = subprocess.run(
            [command_path],
            input=prompt,
            text=True,
            capture_output=True,
            cwd=base,
            check=False,
        )
        write_text(stdout_path, result.stdout)
        write_text(stderr_path, result.stderr)
        record["stdout_path"] = str(stdout_path)
        record["stderr_path"] = str(stderr_path)
        record["exit_code"] = result.returncode
        record["status"] = "done" if result.returncode == 0 else "failed"
        if result.returncode != 0:
            record["error"] = f"external agent exited with code {result.returncode}"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    record["finished_at"] = now_iso()
    append_external_agent_run(config, record)
    return record


def recommended_monitor_command(report: dict[str, object], codex_ok: bool, has_session: bool) -> tuple[str, str]:
    manual = list(report.get("manual_tasks", []))
    failures = list(report.get("failed_tasks", []))
    stale = list(report.get("stale_tasks", []))
    next_task = report.get("next") or {}
    if manual:
        command = str(manual[0].get("manual_command", "") or "revagent agent-blockers")
        return command, f"manual gate: {manual[0].get('kind', '')}"
    if failures:
        return "revagent agent-run --retry-failed --limit 1", f"failed task: {failures[0].get('kind', '')}"
    if stale:
        return "revagent agent-run --retry-failed --limit 1", f"stale task: {stale[0].get('kind', '')}"
    if not has_session:
        return "revagent agent-plan --goal rebuttal-draft", "no active session"
    if codex_ok and next_task:
        return "revagent run", "external agent can continue safe work"
    if next_task:
        return str(next_task.get("manual_command") or "revagent agent-run --until-blocked"), "next safe task available"
    return "revagent dashboard", "workspace has no pending or blocked agent tasks"


def build_monitor_report(base: Path) -> dict[str, object]:
    config = load_config(base)
    write_revision_readiness(base)
    write_revision_memory(base)
    state = build_agent_state(base)
    write_agent_state(config, state)
    report = write_agent_report(base)
    dashboard = write_agent_dashboard(base)
    decisions = refresh_agent_decisions(base)
    codex_ok = backend_available("codex")
    session = dashboard.get("session") or {}
    command, reason = recommended_monitor_command(report, codex_ok, bool(session))
    external_runs = load_external_agent_runs(config)
    latest_external = external_runs[-1] if external_runs else {}
    return {
        "version": 1,
        "generated_at": now_iso(),
        "workspace": str(config.workspace),
        "codex_available": codex_ok,
        "active_session": session,
        "summary": state.get("summary", {}),
        "manual_decisions": [decision for decision in decisions if decision.get("status") in {"open", "stale"}],
        "failed_tasks": report.get("failed_tasks", []),
        "stale_tasks": report.get("stale_tasks", []),
        "next": report.get("next") or {},
        "recommended_command": command,
        "recommendation_reason": reason,
        "dashboard_path": str(config.workspace / "dashboard" / "index.html"),
        "latest_external_run": latest_external,
        "latest_external_recovery": external_run_recovery_hint(latest_external) if latest_external else "none",
    }


def render_monitor_report(monitor: dict[str, object]) -> str:
    lines = ["# RevAgent Monitor", "", f"- Generated at: {monitor.get('generated_at', '')}", f"- Workspace: `{monitor.get('workspace', '')}`"]
    lines.append(f"- Codex CLI: {'available' if monitor.get('codex_available') else 'missing'}")
    session = monitor.get("active_session") or {}
    if session:
        lines.append(f"- Active session: `{session.get('session_id', '')}` goal={session.get('goal', '')} status={session.get('status', '')}")
    else:
        lines.append("- Active session: none")
    summary = monitor.get("summary", {})
    lines.extend(["", "## State", ""])
    for key in ("pending", "stale", "blocked", "failed", "done", "skipped"):
        lines.append(f"- {key}: {summary.get(key, 0)}")
    lines.extend(["", "## Recommendation", ""])
    lines.append(f"- Reason: {monitor.get('recommendation_reason', '')}")
    lines.append(f"- Command: `{monitor.get('recommended_command', '')}`")
    lines.append(f"- Dashboard: `{monitor.get('dashboard_path', '')}`")
    latest_external = monitor.get("latest_external_run") or {}
    lines.extend(["", "## External Agent", ""])
    if latest_external:
        lines.append(f"- Latest: `{latest_external.get('run_id', '')}` {latest_external.get('status', '')}")
        lines.append(f"- Recovery: {monitor.get('latest_external_recovery', '')}")
    else:
        lines.append("- No external agent runs recorded.")
    decisions = monitor.get("manual_decisions", [])
    lines.extend(["", "## Manual Decisions", ""])
    if decisions:
        for decision in decisions[:8]:
            lines.append(f"- `{decision.get('decision_id', '')}` {decision.get('kind', '')} subject={decision.get('subject_id', '')}")
            if decision.get("required_command"):
                lines.append(f"  command: `{decision['required_command']}`")
    else:
        lines.append("- None.")
    for title, key in (("Failed Tasks", "failed_tasks"), ("Stale Tasks", "stale_tasks")):
        lines.extend(["", f"## {title}", ""])
        entries = monitor.get(key, [])
        if not entries:
            lines.append("- None.")
            continue
        for entry in entries[:8]:
            lines.append(f"- `{entry.get('id', '')}` {entry.get('kind', '')} item={entry.get('item_id', '') or '-'}")
    return "\n".join(lines).rstrip() + "\n"


def write_monitor_report(base: Path) -> dict[str, object]:
    config = load_config(base)
    monitor = build_monitor_report(base)
    write_text(config.workspace / "monitor.md", render_monitor_report(monitor))
    return monitor


def html_count_map(values: dict[str, int]) -> str:
    if not values:
        return "<span>none</span>"
    return "".join(f"<span>{html.escape(str(key))}: {value}</span>" for key, value in sorted(values.items()))


def render_dashboard_html(dashboard: dict[str, object], external_runs: list[dict[str, object]]) -> str:
    summary = dashboard.get("summary", {})
    next_task = dashboard.get("next") or {}
    readiness = dashboard.get("readiness", {})
    review = dashboard.get("review_items", {})
    lanes = dashboard.get("lanes", {})
    decisions = dashboard.get("manual_decisions", [])
    failed = dashboard.get("failed_tasks", [])
    stale = dashboard.get("stale_tasks", [])
    recent = dashboard.get("recent_runs", [])
    session = dashboard.get("session") or {}
    workspace = Path(str(dashboard.get("workspace", ""))) if dashboard.get("workspace") else None
    memory = build_revision_memory(workspace.parent) if workspace else {"facts": []}

    def task_list(entries: list[dict[str, object]], empty: str) -> str:
        if not entries:
            return f"<p>{html.escape(empty)}</p>"
        items = []
        for entry in entries[:12]:
            label = f"{entry.get('id', '')} {entry.get('kind', '')} {entry.get('item_id', '') or ''}".strip()
            detail = entry.get("reason") or entry.get("stale_reason") or entry.get("recovery_hint") or entry.get("manual_command") or ""
            items.append(f"<li><strong>{html.escape(label)}</strong><br><span>{html.escape(str(detail))}</span></li>")
        return "<ul>" + "".join(items) + "</ul>"

    external_items = "".join(
        f"<li><strong>{html.escape(str(run.get('run_id', '')))}</strong> {html.escape(str(run.get('status', '')))} "
        f"backend={html.escape(str(run.get('backend', '')))}</li>"
        for run in external_runs[-8:]
    ) or "<li>No external runs.</li>"
    internal_items = "".join(
        f"<li><strong>{html.escape(str(run.get('run_id', '')))}</strong> {html.escape(str(run.get('status', '')))} {html.escape(str(run.get('kind', '')))}</li>"
        for run in recent
    ) or "<li>No internal runs.</li>"
    blockers = readiness.get("top_blockers", [])
    blocker_items = "".join(
        f"<li><strong>{html.escape(str(blocker.get('item_id', '')))}</strong> {html.escape(str(blocker.get('readiness_status', '')))} "
        f"{html.escape(', '.join(blocker.get('missing_inputs', []) or blocker.get('manual_actions', [])))}</li>"
        for blocker in blockers
    ) or "<li>No readiness blockers.</li>"
    memory_items = "".join(
        f"<li><strong>{html.escape(str(fact.get('item_id', '')))}</strong> {html.escape(str(fact.get('readiness_status', '')))}<br>"
        f"<code>{html.escape(str(fact.get('next_command', '')))}</code></li>"
        for fact in list(memory.get("facts", []))[:8]
    ) or "<li>No memory facts.</li>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RevAgent Dashboard</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #f6f7f9; color: #1f2933; }}
    header {{ background: #12343b; color: white; padding: 24px 32px; }}
    main {{ padding: 24px 32px; display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
    section {{ background: white; border: 1px solid #d8dee4; border-radius: 8px; padding: 18px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    .metric {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .metric span {{ background: #eef2f6; border-radius: 6px; padding: 6px 8px; }}
    ul {{ padding-left: 20px; }}
    code {{ background: #eef2f6; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>RevAgent Dashboard</h1>
    <p>Generated at {html.escape(str(dashboard.get('generated_at', '')))} for <code>{html.escape(str(dashboard.get('workspace', '')))}</code></p>
  </header>
  <main>
    <section><h2>Session</h2><p>{html.escape(str(session.get('session_id', 'No active session')))} {html.escape(str(session.get('goal', '')))} {html.escape(str(session.get('status', '')))}</p></section>
    <section><h2>Task Summary</h2><div class="metric">{html_count_map(summary)}</div></section>
    <section><h2>Next Action</h2><p><strong>{html.escape(str(next_task.get('kind', 'none')))}</strong> {html.escape(str(next_task.get('title', '')))}</p><p><code>{html.escape(str(next_task.get('manual_command', '')))}</code></p></section>
    <section><h2>Review Progress</h2><p>Items: {review.get('total', 0)} high risk: {review.get('high_risk', 0)} analysis: {review.get('analysis_ready', 0)}/{review.get('total', 0)}</p><div class="metric">{html_count_map(review.get('by_kind', {}))}</div></section>
    <section><h2>Lanes</h2><p>Proof</p><div class="metric">{html_count_map(lanes.get('proof', {}))}</div><p>Experiment</p><div class="metric">{html_count_map(lanes.get('experiment', {}))}</div><p>Manuscript</p><div class="metric">{html_count_map(lanes.get('manuscript', {}))}</div></section>
    <section><h2>Readiness</h2><p>Overall: {html.escape(str(readiness.get('overall_status', '')))} score: {readiness.get('score', 0)}%</p><ul>{blocker_items}</ul></section>
    <section><h2>Revision Memory</h2><ul>{memory_items}</ul></section>
    <section><h2>Manual Decisions</h2>{task_list(decisions, 'No manual decisions.')}</section>
    <section><h2>Failed Tasks</h2>{task_list(failed, 'No failed tasks.')}</section>
    <section><h2>Stale Tasks</h2>{task_list(stale, 'No stale tasks.')}</section>
    <section><h2>Recent Internal Runs</h2><ul>{internal_items}</ul></section>
    <section><h2>Recent External Runs</h2><ul>{external_items}</ul></section>
  </main>
</body>
</html>
"""


def write_dashboard_html(base: Path) -> Path:
    config = load_config(base)
    dashboard = write_agent_dashboard(base)
    target = config.workspace / "dashboard" / "index.html"
    write_text(target, render_dashboard_html(dashboard, load_external_agent_runs(config)))
    return target


__all__ = [
    "build_external_agent_prompt",
    "build_monitor_report",
    "load_external_agent_runs",
    "get_external_agent_run",
    "mark_external_agent_run",
    "recover_external_agent_run",
    "render_dashboard_html",
    "render_external_agent_runs",
    "render_external_agent_run_detail",
    "render_monitor_report",
    "run_external_agent",
    "write_dashboard_html",
    "write_monitor_report",
]
