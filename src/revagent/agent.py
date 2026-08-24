"""Deterministic safe-auto agent loop and task state."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

from ._models import Config
from ._utils import load_config, load_items, now_iso, read_json, write_json, write_text
from .candidates import llm_candidate_gate_reason, load_candidates, propose_candidates
from .experiments import experiment_contract, experiment_run_preview, load_experiment_manifests, load_experiment_run_attempts
from .llm import draft_all_with_llm, ensure_llm_review_fields, llm_check_all, load_llm_drafts
from .planning import load_item_plans, plan_item
from .provenance import provenance_missing_or_stale, source_fingerprint, write_revision_provenance
from .proofs import load_proof_workflows, proof_plan_for_item
from .readiness import build_revision_readiness, readiness_missing_or_stale, write_revision_readiness
from .rendering import create_draft
from .review_analysis import analyze_all_review_items, load_review_analyses
from .reviews import create_plan
from .validation import validate_workspace
from .workspace import migrate_workspace

TASK_STATUSES = {"pending", "running", "done", "blocked", "failed", "skipped", "stale", "manual_required"}
SAFE_TASK_KINDS = {
    "migrate",
    "plan_workspace",
    "plan_item",
    "proof_plan",
    "experiment_contract",
    "experiment_run_preview",
    "draft",
    "llm_draft",
    "llm_check",
    "propose",
    "provenance",
    "readiness",
    "review_analysis",
    "validate",
}
BLOCKED_TASK_KINDS = {
    "proof_approval_required",
    "experiment_result_required",
    "candidate_author_text_required",
    "llm_candidate_approval_required",
    "llm_review_required",
    "llm_quality_required",
}
POLICY_SAFE = "safe_auto"
POLICY_MANUAL = "manual_required"
POLICY_DISALLOWED = "disallowed"
SESSION_STATUSES = {"planned", "running", "blocked", "failed", "complete"}
DECISION_STATUSES = {"open", "resolved", "stale", "dismissed"}
DECISION_TASK_KINDS = BLOCKED_TASK_KINDS | {"candidate_approval_required", "candidate_apply_required"}
SESSION_GOALS = {
    "rebuttal-draft": [
        {"phase": "workspace_planning", "task_kinds": ["migrate", "plan_workspace", "review_analysis", "plan_item"]},
        {"phase": "evidence_contracts", "task_kinds": ["proof_plan", "experiment_contract", "experiment_run_preview"]},
        {"phase": "drafting", "task_kinds": ["draft", "propose", "llm_draft", "llm_check"]},
        {"phase": "provenance_validation", "task_kinds": ["provenance", "readiness", "validate"]},
    ],
    "proof-response": [
        {"phase": "proof_planning", "task_kinds": ["plan_workspace", "review_analysis", "plan_item", "proof_plan"]},
        {"phase": "author_proof_gate", "task_kinds": ["proof_approval_required"]},
        {"phase": "drafting", "task_kinds": ["draft", "propose", "llm_draft", "llm_check"]},
        {"phase": "provenance_validation", "task_kinds": ["provenance", "readiness", "validate"]},
    ],
    "experiment-response": [
        {"phase": "experiment_contracts", "task_kinds": ["plan_workspace", "review_analysis", "plan_item", "experiment_contract", "experiment_run_preview"]},
        {"phase": "author_experiment_gate", "task_kinds": ["experiment_result_required"]},
        {"phase": "drafting", "task_kinds": ["draft", "propose", "llm_draft", "llm_check"]},
        {"phase": "provenance_validation", "task_kinds": ["provenance", "readiness", "validate"]},
    ],
    "full-revision-pass": [
        {"phase": "workspace_planning", "task_kinds": ["migrate", "plan_workspace", "review_analysis", "plan_item"]},
        {"phase": "evidence_contracts", "task_kinds": ["proof_plan", "experiment_contract", "experiment_run_preview"]},
        {"phase": "drafting", "task_kinds": ["draft", "propose", "llm_draft", "llm_check"]},
        {"phase": "manual_gates", "task_kinds": sorted(BLOCKED_TASK_KINDS)},
        {"phase": "provenance_validation", "task_kinds": ["provenance", "readiness", "validate"]},
    ],
}
AGENT_EVAL_FIXTURES = {"full-revision", "stale-input", "safety-gates"}


def default_agent_policy() -> dict[str, object]:
    return {
        "version": 1,
        "safe_auto": sorted(SAFE_TASK_KINDS),
        "manual_required": sorted(BLOCKED_TASK_KINDS | {"approve", "apply", "proof_approve", "experiment_artifact", "experiment_incorporate", "experiment_run_record"}),
        "disallowed": ["run_experiment", "auto_approve_candidate", "auto_apply_candidate", "auto_approve_llm_draft"],
        "notes": [
            "Safe-auto tasks may refresh deterministic workspace artifacts.",
            "Manual-required tasks must be completed with explicit author commands.",
            "RevAgent never auto-approves LLM drafts, proof workflows, experiment results, or candidate edits.",
        ],
    }


def render_agent_policy(policy: dict[str, object]) -> str:
    lines = ["# Agent Policy", ""]
    for key in ("safe_auto", "manual_required", "disallowed"):
        lines.extend([f"## {key}", ""])
        values = policy.get(key, [])
        lines.extend(f"- `{value}`" for value in values)
        if not values:
            lines.append("- None.")
        lines.append("")
    lines.extend(["## Notes", ""])
    lines.extend(f"- {note}" for note in policy.get("notes", []))
    return "\n".join(lines).rstrip() + "\n"


def default_agent_state() -> dict[str, object]:
    return {
        "version": 1,
        "generated_at": now_iso(),
        "last_run_at": "",
        "tasks": [],
        "summary": {
            "pending": 0,
            "running": 0,
            "done": 0,
            "blocked": 0,
            "failed": 0,
            "skipped": 0,
            "stale": 0,
            "manual_required": 0,
        },
    }


def load_agent_state(config: Config) -> dict[str, object]:
    return read_json(config.workspace / "agent_state.json", default_agent_state())


def write_agent_state(config: Config, state: dict[str, object]) -> None:
    write_json(config.workspace / "agent_state.json", state)
    write_text(config.workspace / "agent_state.md", render_agent_state(state))


def load_agent_policy(config: Config) -> dict[str, object]:
    return read_json(config.workspace / "agent_policy.json", default_agent_policy())


def write_agent_policy(config: Config, policy: dict[str, object] | None = None) -> None:
    policy = policy or default_agent_policy()
    write_json(config.workspace / "agent_policy.json", policy)
    write_text(config.workspace / "agent_policy.md", render_agent_policy(policy))


def agent_runs_path(config: Config) -> Path:
    return config.workspace / "agent_runs.jsonl"


def load_agent_runs(config: Config) -> list[dict[str, object]]:
    path = agent_runs_path(config)
    if not path.exists():
        return []
    runs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            runs.append({"status": "invalid", "raw": line})
    return runs


def render_agent_runs(runs: list[dict[str, object]]) -> str:
    lines = ["# Agent Runs", ""]
    if not runs:
        lines.append("No agent runs recorded yet.")
        return "\n".join(lines) + "\n"
    for entry in runs[-80:]:
        lines.append(
            f"- `{entry.get('run_id', '')}` {entry.get('status', '')} "
            f"{entry.get('kind', '')} item={entry.get('item_id', '') or '-'} "
            f"fingerprint={str(entry.get('fingerprint', ''))[:12]}"
        )
        if entry.get("failure_class"):
            lines.append(f"  failure: {entry['failure_class']}")
        if entry.get("stale_reason"):
            lines.append(f"  stale: {entry['stale_reason']}")
        if entry.get("result"):
            lines.append(f"  result: {entry['result']}")
        if entry.get("error"):
            lines.append(f"  error: {entry['error']}")
    return "\n".join(lines) + "\n"


def write_agent_runs_markdown(config: Config) -> None:
    write_text(config.workspace / "agent_runs.md", render_agent_runs(load_agent_runs(config)))


def append_agent_run(config: Config, record: dict[str, object]) -> None:
    path = agent_runs_path(config)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    write_text(path, existing + json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    write_agent_runs_markdown(config)


def agent_sessions_path(config: Config) -> Path:
    return config.workspace / "agent_sessions.jsonl"


def load_agent_sessions(config: Config) -> list[dict[str, object]]:
    path = agent_sessions_path(config)
    if not path.exists():
        return []
    sessions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            sessions.append(json.loads(line))
        except json.JSONDecodeError:
            sessions.append({"status": "invalid", "raw": line})
    return sessions


def write_agent_sessions(config: Config, sessions: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(session, ensure_ascii=False, sort_keys=True) + "\n" for session in sessions)
    write_text(agent_sessions_path(config), text)
    write_text(config.workspace / "agent_sessions.md", render_agent_sessions(sessions))


def load_agent_decisions(config: Config) -> list[dict[str, object]]:
    return read_json(config.workspace / "agent_decisions.json", [])


def write_agent_decisions(config: Config, decisions: list[dict[str, object]]) -> None:
    write_json(config.workspace / "agent_decisions.json", decisions)
    write_text(config.workspace / "agent_decisions.md", render_agent_decisions(decisions))


def next_decision_id(decisions: list[dict[str, object]]) -> str:
    numbers = []
    for decision in decisions:
        decision_id = str(decision.get("decision_id", ""))
        if decision_id.startswith("D") and decision_id[1:].isdigit():
            numbers.append(int(decision_id[1:]))
    return f"D{(max(numbers) if numbers else 0) + 1:03d}"


def decision_fingerprint(entry: dict[str, object]) -> str:
    return stable_hash(
        {
            "kind": entry.get("kind", ""),
            "subject_id": entry.get("subject_id", ""),
            "task_fingerprint": entry.get("task_fingerprint", ""),
            "source_fingerprint": entry.get("source_fingerprint", ""),
        }
    )


def decision_subject_id(task_entry: dict[str, object]) -> str:
    kind = str(task_entry.get("kind", ""))
    if kind == "candidate_author_text_required":
        title = str(task_entry.get("title", ""))
        parts = title.split()
        return parts[-1] if parts else str(task_entry.get("item_id", ""))
    if kind == "llm_candidate_approval_required":
        title = str(task_entry.get("title", ""))
        parts = title.split()
        return parts[-1] if parts else str(task_entry.get("item_id", ""))
    return str(task_entry.get("item_id", "") or task_entry.get("id", ""))


def decision_risk(kind: str) -> str:
    if kind in {"proof_approval_required", "experiment_result_required", "candidate_approval_required", "candidate_apply_required"}:
        return "high"
    if kind in {"llm_candidate_approval_required", "llm_quality_required", "candidate_author_text_required"}:
        return "medium"
    return "low"


def decision_context(task_entry: dict[str, object]) -> str:
    bits = [str(task_entry.get("title", ""))]
    if task_entry.get("reason"):
        bits.append(str(task_entry["reason"]))
    if task_entry.get("stale_reason"):
        bits.append(str(task_entry["stale_reason"]))
    if task_entry.get("recovery_hint"):
        bits.append(str(task_entry["recovery_hint"]))
    return " ".join(bit for bit in bits if bit).strip()


def decision_from_task(task_entry: dict[str, object], linked_session_id: str = "") -> dict[str, object]:
    kind = str(task_entry.get("kind", ""))
    subject_id = decision_subject_id(task_entry)
    source = str(task_entry.get("fingerprint", "") or task_entry.get("dependency_fingerprint", ""))
    record = {
        "version": 1,
        "decision_id": "",
        "kind": kind,
        "subject_id": subject_id,
        "item_id": str(task_entry.get("item_id", "")),
        "status": "open",
        "risk": decision_risk(kind),
        "required_command": str(task_entry.get("manual_command", "")),
        "context_summary": decision_context(task_entry),
        "source_fingerprint": source,
        "task_fingerprint": str(task_entry.get("fingerprint", "")),
        "linked_session_id": linked_session_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "resolved_at": "",
        "dismissed_at": "",
        "note": "",
    }
    record["fingerprint"] = decision_fingerprint(record)
    return record


def candidate_decision_tasks(config: Config) -> list[dict[str, object]]:
    tasks = []
    for candidate in load_candidates(config):
        candidate_id = str(candidate.get("id", ""))
        item_id = str(candidate.get("item_id", ""))
        if candidate.get("status") in {"proposed", "edited"}:
            tasks.append(
                task(
                    f"D-{candidate_id}",
                    "candidate_approval_required",
                    f"Candidate approval required for {candidate_id}",
                    item_id=item_id,
                    status="blocked",
                    reason="candidate edit requires explicit author approval before it can be applied",
                    command=f"revagent approve {candidate_id}",
                )
            )
            tasks[-1]["fingerprint"] = stable_hash({"candidate": candidate, "kind": "candidate_approval_required"})
        if candidate.get("status") == "approved":
            tasks.append(
                task(
                    f"D-{candidate_id}",
                    "candidate_apply_required",
                    f"Candidate apply decision required for {candidate_id}",
                    item_id=item_id,
                    status="blocked",
                    reason="approved candidate requires explicit apply or rejection",
                    command="revagent apply --dry-run",
                )
            )
            tasks[-1]["fingerprint"] = stable_hash({"candidate": candidate, "kind": "candidate_apply_required"})
    return tasks


def decision_still_blocked(decision: dict[str, object], tasks: list[dict[str, object]]) -> bool:
    for task_entry in tasks:
        if task_entry.get("kind") != decision.get("kind"):
            continue
        if decision_subject_id(task_entry) == decision.get("subject_id"):
            return True
    return False


def refresh_agent_decisions(base: Path, linked_session_id: str = "") -> list[dict[str, object]]:
    config = load_config(base)
    existing = load_agent_decisions(config)
    state = build_agent_state(base)
    tasks = manual_gate_tasks(state) + [task for task in state.get("tasks", []) if task.get("status") == "failed"] + candidate_decision_tasks(config)
    active = [decision_from_task(task, linked_session_id=linked_session_id) for task in tasks]
    by_fingerprint = {str(decision.get("fingerprint", "")): decision for decision in existing}
    by_id = {str(decision.get("decision_id", "")): decision for decision in existing}
    merged: list[dict[str, object]] = []
    used_ids: set[str] = set()

    for active_decision in active:
        previous = by_fingerprint.get(str(active_decision.get("fingerprint", "")))
        if previous and previous.get("status") in DECISION_STATUSES:
            decision = dict(previous)
            status = str(previous.get("status", "open"))
            decision.update(
                {
                    "status": "open" if status in {"open", "stale"} else status,
                    "risk": active_decision["risk"],
                    "required_command": active_decision["required_command"],
                    "context_summary": active_decision["context_summary"],
                    "source_fingerprint": active_decision["source_fingerprint"],
                    "task_fingerprint": active_decision["task_fingerprint"],
                    "linked_session_id": linked_session_id or previous.get("linked_session_id", ""),
                    "updated_at": now_iso(),
                }
            )
        else:
            decision = dict(active_decision)
            decision["decision_id"] = next_decision_id(list(by_id.values()) + merged)
        used_ids.add(str(decision["decision_id"]))
        merged.append(decision)

    for decision in existing:
        decision_id = str(decision.get("decision_id", ""))
        if decision_id in used_ids:
            continue
        item = dict(decision)
        if item.get("status") == "open":
            item["status"] = "stale"
            item["updated_at"] = now_iso()
        merged.append(item)

    write_agent_decisions(config, merged)
    return merged


def get_agent_decision(base: Path, decision_id: str) -> dict[str, object]:
    config = load_config(base)
    refresh_agent_decisions(base)
    for decision in load_agent_decisions(config):
        if decision.get("decision_id") == decision_id:
            return decision
    raise ValueError(f"unknown decision {decision_id}")


def resolve_agent_decision(base: Path, decision_id: str, note: str) -> dict[str, object]:
    config = load_config(base)
    decisions = refresh_agent_decisions(base)
    state = build_agent_state(base)
    tasks = manual_gate_tasks(state) + [task for task in state.get("tasks", []) if task.get("status") == "failed"] + candidate_decision_tasks(config)
    for decision in decisions:
        if decision.get("decision_id") != decision_id:
            continue
        if decision.get("status") == "open" and decision_still_blocked(decision, tasks):
            raise ValueError(f"decision {decision_id} is still blocked; complete {decision.get('required_command') or 'the required command'} first")
        decision["status"] = "resolved"
        decision["resolved_at"] = now_iso()
        decision["updated_at"] = now_iso()
        decision["note"] = note
        write_agent_decisions(config, decisions)
        return decision
    raise ValueError(f"unknown decision {decision_id}")


def dismiss_agent_decision(base: Path, decision_id: str, note: str) -> dict[str, object]:
    config = load_config(base)
    decisions = refresh_agent_decisions(base)
    for decision in decisions:
        if decision.get("decision_id") == decision_id:
            decision["status"] = "dismissed"
            decision["dismissed_at"] = now_iso()
            decision["updated_at"] = now_iso()
            decision["note"] = note
            write_agent_decisions(config, decisions)
            return decision
    raise ValueError(f"unknown decision {decision_id}")


def next_session_id(sessions: list[dict[str, object]]) -> str:
    numbers = []
    for session in sessions:
        session_id = str(session.get("session_id", ""))
        if session_id.startswith("S") and session_id[1:].isdigit():
            numbers.append(int(session_id[1:]))
    return f"S{(max(numbers) if numbers else 0) + 1:03d}"


def current_agent_session(config: Config) -> dict[str, object] | None:
    for session in reversed(load_agent_sessions(config)):
        if session.get("status") not in {"complete", "failed", "invalid"}:
            return session
    return None


def manual_gate_tasks(state: dict[str, object]) -> list[dict[str, object]]:
    return [
        task
        for task in state.get("tasks", [])
        if task.get("status") in {"blocked", "manual_required"} or task.get("kind") in BLOCKED_TASK_KINDS
    ]


def step_status(state: dict[str, object], runs: list[dict[str, object]], task_kinds: list[str]) -> str:
    matching_tasks = [task for task in state.get("tasks", []) if task.get("kind") in task_kinds]
    if any(task.get("status") == "failed" for task in matching_tasks):
        return "failed"
    if any(task.get("status") in {"blocked", "manual_required"} for task in matching_tasks):
        return "blocked"
    if any(task.get("status") in {"pending", "stale", "running"} for task in matching_tasks):
        return "ready"
    if any(run.get("kind") in task_kinds and run.get("status") in {"done", "skipped"} for run in runs):
        return "done"
    return "waiting"


def build_session_steps(goal: str, state: dict[str, object], runs: list[dict[str, object]]) -> list[dict[str, object]]:
    steps = []
    for index, spec in enumerate(SESSION_GOALS[goal], start=1):
        task_kinds = list(spec["task_kinds"])
        steps.append(
            {
                "id": f"P{index:02d}",
                "phase": spec["phase"],
                "task_kinds": task_kinds,
                "status": step_status(state, runs, task_kinds),
            }
        )
    return steps


def session_status_from_state(state: dict[str, object]) -> tuple[str, str, str]:
    tasks = list(state.get("tasks", []))
    failed = [task for task in tasks if task.get("status") == "failed"]
    if failed:
        task = failed[0]
        return "failed", str(task.get("kind", "")), str(task.get("recovery_hint") or task.get("error") or "inspect the failed task")
    manual = manual_gate_tasks(state)
    if manual:
        task = manual[0]
        return "blocked", str(task.get("kind", "")), str(task.get("manual_command") or task.get("reason") or "complete the manual gate")
    runnable = [task for task in tasks if task.get("status") in {"pending", "stale", "running"} and task.get("kind") in SAFE_TASK_KINDS]
    if runnable:
        task = runnable[0]
        return "running", str(task.get("kind", "")), str(task.get("manual_command") or "run revagent agent-resume")
    return "complete", "complete", "no pending safe tasks or manual gates"


def refresh_agent_session(base: Path, session: dict[str, object]) -> dict[str, object]:
    config = load_config(base)
    state = build_agent_state(base)
    runs = load_agent_runs(config)
    goal = str(session.get("goal", "rebuttal-draft"))
    status, current_phase, hint = session_status_from_state(state)
    refreshed = dict(session)
    refreshed["status"] = status
    refreshed["current_phase"] = current_phase
    refreshed["blocked_reason"] = hint if status in {"blocked", "failed"} else ""
    refreshed["resume_hint"] = hint
    refreshed["updated_at"] = now_iso()
    refreshed["steps"] = build_session_steps(goal, state, runs)
    refreshed["manual_gates"] = manual_gate_tasks(state)
    decisions = refresh_agent_decisions(base, linked_session_id=str(session.get("session_id", "")))
    refreshed["open_decision_ids"] = [decision["decision_id"] for decision in decisions if decision.get("status") in {"open", "stale"}]
    return refreshed


def plan_agent_session(base: Path, goal: str) -> dict[str, object]:
    if goal not in SESSION_GOALS:
        raise ValueError(f"unknown agent goal {goal}; choose one of {', '.join(sorted(SESSION_GOALS))}")
    config = load_config(base)
    sessions = load_agent_sessions(config)
    state = build_agent_state(base)
    runs = load_agent_runs(config)
    status, current_phase, hint = session_status_from_state(state)
    session = {
        "version": 1,
        "session_id": next_session_id(sessions),
        "goal": goal,
        "status": "planned" if status == "running" else status,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "current_phase": current_phase,
        "blocked_reason": hint if status in {"blocked", "failed"} else "",
        "resume_hint": "run revagent agent-resume",
        "linked_run_ids": [],
        "steps": build_session_steps(goal, state, runs),
        "manual_gates": manual_gate_tasks(state),
        "open_decision_ids": [],
    }
    decisions = refresh_agent_decisions(base, linked_session_id=str(session["session_id"]))
    session["open_decision_ids"] = [decision["decision_id"] for decision in decisions if decision.get("status") in {"open", "stale"}]
    sessions.append(session)
    write_agent_sessions(config, sessions)
    return session


def update_current_session(base: Path, updated: dict[str, object]) -> dict[str, object]:
    config = load_config(base)
    sessions = load_agent_sessions(config)
    for index in range(len(sessions) - 1, -1, -1):
        if sessions[index].get("session_id") == updated.get("session_id"):
            sessions[index] = updated
            write_agent_sessions(config, sessions)
            return updated
    sessions.append(updated)
    write_agent_sessions(config, sessions)
    return updated


def resume_agent_session(base: Path, limit: int | None = None, retry_failed: bool = False) -> dict[str, object]:
    config = load_config(base)
    session = current_agent_session(config)
    if not session:
        raise ValueError("no active agent session; run revagent agent-plan --goal rebuttal-draft")
    before = load_agent_runs(config)
    running = dict(session)
    running["status"] = "running"
    running["updated_at"] = now_iso()
    update_current_session(base, running)
    state = run_agent_once(base, limit=limit, until_blocked=True, retry_failed=retry_failed)
    after = load_agent_runs(config)
    new_run_ids = [str(run.get("run_id", "")) for run in after[len(before) :] if run.get("run_id")]
    refreshed = refresh_agent_session(base, running)
    linked = list(dict.fromkeys(list(refreshed.get("linked_run_ids", [])) + new_run_ids))
    refreshed["linked_run_ids"] = linked
    refreshed["last_state_summary"] = state.get("summary", {})
    return update_current_session(base, refreshed)


def resume_agent_session_watch(base: Path, interval: float = 5.0, cycles: int | None = None, limit: int | None = None, retry_failed: bool = False) -> dict[str, object]:
    if cycles is not None and cycles <= 0:
        return complete_check_agent_session(base)
    completed = 0
    last_session: dict[str, object] | None = None
    while cycles is None or completed < cycles:
        last_session = resume_agent_session(base, limit=limit, retry_failed=retry_failed)
        completed += 1
        if last_session.get("status") in {"blocked", "failed", "complete"}:
            return last_session
        if interval > 0:
            time.sleep(interval)
    if last_session is None:
        raise ValueError("no active agent session; run revagent agent-plan --goal rebuttal-draft")
    return last_session


def agent_blockers(base: Path) -> list[dict[str, object]]:
    return [decision for decision in refresh_agent_decisions(base) if decision.get("status") in {"open", "stale"}]


def complete_check_agent_session(base: Path) -> dict[str, object]:
    config = load_config(base)
    session = current_agent_session(config)
    if not session:
        raise ValueError("no active agent session")
    refreshed = refresh_agent_session(base, session)
    return update_current_session(base, refreshed)


def render_agent_sessions(sessions: list[dict[str, object]]) -> str:
    lines = ["# Agent Sessions", ""]
    if not sessions:
        lines.append("No agent sessions recorded yet.")
        return "\n".join(lines) + "\n"
    for session in sessions:
        lines.append(f"## {session.get('session_id', '')} {session.get('goal', '')}")
        lines.append("")
        lines.append(f"- Status: {session.get('status', '')}")
        lines.append(f"- Current phase: {session.get('current_phase', '')}")
        lines.append(f"- Resume hint: {session.get('resume_hint', '')}")
        if session.get("blocked_reason"):
            lines.append(f"- Blocked reason: {session['blocked_reason']}")
        linked = session.get("linked_run_ids", [])
        if linked:
            lines.append(f"- Linked runs: {', '.join(linked)}")
        open_decisions = session.get("open_decision_ids", [])
        if open_decisions:
            lines.append(f"- Open decisions: {', '.join(open_decisions)}")
        lines.extend(["", "### Steps", ""])
        for step in session.get("steps", []):
            lines.append(f"- `{step.get('id', '')}` [{step.get('status', '')}] {step.get('phase', '')}: {', '.join(step.get('task_kinds', []))}")
        gates = session.get("manual_gates", [])
        if gates:
            lines.extend(["", "### Manual Gates", ""])
            for gate in gates:
                lines.append(f"- `{gate.get('id', '')}` {gate.get('kind', '')} item={gate.get('item_id', '') or '-'}")
                if gate.get("manual_command"):
                    lines.append(f"  command: `{gate['manual_command']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_agent_decisions(decisions: list[dict[str, object]]) -> str:
    lines = ["# Agent Decisions", ""]
    if not decisions:
        lines.append("No agent decisions recorded yet.")
        return "\n".join(lines) + "\n"
    for decision in decisions:
        lines.append(f"## {decision.get('decision_id', '')} {decision.get('kind', '')}")
        lines.append("")
        lines.append(f"- Status: {decision.get('status', '')}")
        lines.append(f"- Subject: {decision.get('subject_id', '')}")
        lines.append(f"- Item: {decision.get('item_id', '') or '-'}")
        lines.append(f"- Risk: {decision.get('risk', '')}")
        if decision.get("linked_session_id"):
            lines.append(f"- Session: {decision['linked_session_id']}")
        if decision.get("required_command"):
            lines.append(f"- Required command: `{decision['required_command']}`")
        if decision.get("context_summary"):
            lines.append(f"- Context: {decision['context_summary']}")
        if decision.get("note"):
            lines.append(f"- Note: {decision['note']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_agent_blockers(blockers: list[dict[str, object]]) -> str:
    lines = ["# Agent Blockers", ""]
    if not blockers:
        lines.append("- None.")
        return "\n".join(lines) + "\n"
    for entry in blockers:
        lines.append(f"- `{entry.get('decision_id', entry.get('id', ''))}` [{entry.get('status', '')}] {entry.get('kind', '')} item={entry.get('item_id', '') or '-'}")
        if entry.get("context_summary"):
            lines.append(f"  context: {entry['context_summary']}")
        if entry.get("reason"):
            lines.append(f"  reason: {entry['reason']}")
        if entry.get("recovery_hint"):
            lines.append(f"  recovery: {entry['recovery_hint']}")
        command = entry.get("required_command") or entry.get("manual_command")
        if command:
            lines.append(f"  command: `{command}`")
    return "\n".join(lines) + "\n"


def stable_hash(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    if not path.exists():
        return "<missing>"
    if not path.is_file():
        return "<not-file>"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latex_source_hash(config: Config) -> str:
    digest = hashlib.sha256()
    for path in sorted(config.tex_root.rglob("*.tex")):
        if config.workspace in path.parents:
            continue
        digest.update(str(path.relative_to(config.tex_root)).encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def item_snapshot(config: Config, item_id: str) -> object:
    if not item_id:
        return None
    for item in load_items(config):
        if item.get("id") == item_id:
            return item
    return {"missing_item": item_id}


def task_identity(entry: dict[str, object]) -> str:
    payload = {
        "kind": entry.get("kind", ""),
        "item_id": entry.get("item_id", ""),
        "title": entry.get("title", ""),
        "manual_command": entry.get("manual_command", ""),
    }
    return stable_hash(payload)


def dependency_entry(label: str, value: object) -> dict[str, str]:
    return {"label": label, "hash": stable_hash(value)}


def task_dependencies(config: Config, entry: dict[str, object]) -> list[dict[str, str]]:
    kind = str(entry.get("kind", ""))
    item_id = str(entry.get("item_id", ""))
    deps: list[dict[str, str]] = []

    def add_file(name: str) -> None:
        deps.append({"label": name, "hash": file_hash(config.workspace / name)})

    if item_id:
        deps.append(dependency_entry(f"review_item:{item_id}", item_snapshot(config, item_id)))
    if kind in {"migrate", "validate"}:
        add_file("revision.yaml")
    if kind in {"plan_workspace", "review_analysis", "plan_item", "proof_plan", "experiment_contract", "experiment_run_preview", "draft", "llm_draft", "propose", "readiness", "validate"}:
        add_file("review_items.json")
        deps.append({"label": "latex_sources", "hash": latex_source_hash(config)})
    if kind in {"review_analysis", "plan_item", "draft", "llm_draft", "propose", "readiness", "validate"}:
        add_file("latex_index.json")
        add_file("journal_profile.json")
    if kind in {"proof_plan", "draft", "propose", "readiness", "validate"}:
        add_file("proof_workflows.json")
    if kind in {"experiment_contract", "experiment_run_preview", "draft", "propose", "readiness", "validate"}:
        add_file("experiment_manifests.json")
    if kind in {"experiment_run_preview", "readiness", "validate"}:
        add_file("experiment_run_attempts.jsonl")
    if kind in {"plan_item", "draft", "llm_draft", "propose", "readiness", "validate"}:
        add_file("review_analyses.json")
    if kind in {"draft", "propose", "readiness", "validate"}:
        add_file("item_plans.json")
        add_file("candidate_edits.json")
    if kind in {"llm_draft", "llm_check", "propose", "provenance", "validate"}:
        add_file("llm_drafts.json")
    if kind == "provenance":
        deps.append({"label": "provenance_sources", "hash": source_fingerprint(config)})
    if kind == "readiness":
        for name in ("response_letter.md", "manuscript.patch", "revision_provenance.json", "experiment_runs.jsonl", "apply_log.jsonl"):
            add_file(name)
    if kind == "validate":
        for name in ("candidate_edits.json", "proof_workflows.json", "experiment_manifests.json", "revision_provenance.json", "agent_runs.jsonl"):
            add_file(name)
    if not deps:
        deps.append(dependency_entry("task", {"kind": kind, "item_id": item_id, "reason": entry.get("reason", "")}))
    return deps


def dependency_fingerprint(dependencies: list[dict[str, str]]) -> str:
    return stable_hash(dependencies)


def task_fingerprint(entry: dict[str, object], config: Config | None = None) -> str:
    dependency_hash = str(entry.get("dependency_fingerprint", ""))
    if config is not None and not dependency_hash:
        dependency_hash = dependency_fingerprint(task_dependencies(config, entry))
    payload = {"identity": task_identity(entry), "dependency_fingerprint": dependency_hash}
    return stable_hash(payload)


def latest_runs_by_fingerprint(runs: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    latest = {}
    for entry in runs:
        fingerprint = entry.get("fingerprint")
        if fingerprint:
            latest[str(fingerprint)] = entry
    return latest


def latest_runs_by_identity(runs: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    latest = {}
    for entry in runs:
        identity = entry.get("task_identity")
        if identity:
            latest[str(identity)] = entry
    return latest


def annotate_tasks_with_runs(config: Config, tasks: list[dict[str, object]], runs: list[dict[str, object]]) -> list[dict[str, object]]:
    latest = latest_runs_by_fingerprint(runs)
    latest_identity = latest_runs_by_identity(runs)
    annotated = []
    for entry in tasks:
        item = dict(entry)
        identity = task_identity(item)
        dependencies = task_dependencies(config, item)
        dependency_hash = dependency_fingerprint(dependencies)
        item["task_identity"] = identity
        item["dependency_fingerprint"] = dependency_hash
        item["dependencies"] = dependencies
        item["policy"] = POLICY_SAFE if item.get("kind") in SAFE_TASK_KINDS else POLICY_MANUAL
        fingerprint = task_fingerprint({**item, "dependency_fingerprint": dependency_hash})
        item["fingerprint"] = fingerprint
        last = latest.get(fingerprint, {})
        if last:
            item["last_run_status"] = last.get("status", "")
            item["last_run_result"] = last.get("result", "")
            item["last_run_error"] = last.get("error", "")
            item["last_run_at"] = last.get("finished_at", "")
            if item.get("status") == "pending" and last.get("status") == "failed":
                item["status"] = "failed"
                item["failure_class"] = last.get("failure_class", "unknown_failure")
                item["recovery_hint"] = last.get("recovery_hint", "fix the failure or rerun with --retry-failed")
        else:
            previous = latest_identity.get(identity, {})
            if previous:
                item["last_run_status"] = previous.get("status", "")
                item["last_run_result"] = previous.get("result", "")
                item["last_run_error"] = previous.get("error", "")
                item["last_run_at"] = previous.get("finished_at", "")
                item["stale_reason"] = "input dependencies changed since the last recorded run"
                if item.get("status") == "pending":
                    item["status"] = "stale"
        annotated.append(item)
    return annotated


def task(task_id: str, kind: str, title: str, *, item_id: str = "", status: str = "pending", reason: str = "", command: str = "") -> dict[str, object]:
    return {
        "id": task_id,
        "kind": kind,
        "title": title,
        "item_id": item_id,
        "status": status,
        "reason": reason,
        "manual_command": command,
        "created_at": now_iso(),
        "started_at": "",
        "finished_at": "",
        "result": "",
        "error": "",
    }


def summarize_tasks(tasks: list[dict[str, object]]) -> dict[str, int]:
    return {status: sum(1 for item in tasks if item.get("status") == status) for status in sorted(TASK_STATUSES)}


def candidate_needs_author_text(candidate: dict) -> bool:
    return bool(candidate.get("requires_author_text")) and candidate.get("status") in {"proposed", "blocked"}


def build_agent_tasks(base: Path) -> list[dict[str, object]]:
    config = load_config(base)
    tasks: list[dict[str, object]] = []

    migration = migrate_workspace(base, dry_run=True)
    if migration.get("actions"):
        tasks.append(task("T001", "migrate", "Apply safe workspace migration", reason=f"{len(migration['actions'])} migration actions available", command="revagent migrate --apply"))

    items = load_items(config)
    item_plans = load_item_plans(config)
    candidates = load_candidates(config)
    proof_workflows = load_proof_workflows(config)
    experiment_manifests = load_experiment_manifests(config)
    experiment_attempts = load_experiment_run_attempts(config)
    llm_drafts = load_llm_drafts(config)
    review_analyses = load_review_analyses(config)

    if items and any(not item.get("tex_locations") for item in items):
        tasks.append(task(f"T{len(tasks) + 1:03d}", "plan_workspace", "Refresh workspace plan and LaTeX locations", command="revagent plan"))

    if items and any(item["id"] not in review_analyses for item in items):
        tasks.append(task(f"T{len(tasks) + 1:03d}", "review_analysis", "Analyze reviewer intent and evidence needs", command="revagent analyze-review --all"))

    for item in items:
        item_id = item["id"]
        if item.get("planning_status", "triaged") == "triaged" or item_id not in item_plans:
            tasks.append(task(f"T{len(tasks) + 1:03d}", "plan_item", f"Plan review item {item_id}", item_id=item_id, command=f"revagent plan-item {item_id}"))
        if item.get("kind") == "proof":
            if item_id not in proof_workflows:
                tasks.append(task(f"T{len(tasks) + 1:03d}", "proof_plan", f"Create proof workflow for {item_id}", item_id=item_id, command=f"revagent proof-plan {item_id}"))
            lane = item.get("proof_lane") or {}
            if item_id in proof_workflows and lane.get("approval_status", "required") != "approved":
                tasks.append(
                    task(
                        f"T{len(tasks) + 1:03d}",
                        "proof_approval_required",
                        f"Author approval required for proof item {item_id}",
                        item_id=item_id,
                        status="blocked",
                        reason="proof workflow approval is required before proof edits can be approved",
                        command=f"revagent proof-approve {item_id} --note \"AUTHOR NOTE\"",
                    )
                )
        if item.get("kind") == "experiment":
            if item_id not in experiment_manifests:
                tasks.append(task(f"T{len(tasks) + 1:03d}", "experiment_contract", f"Create experiment contract for {item_id}", item_id=item_id, command=f"revagent experiment-contract {item_id}"))
            lane = item.get("experiment_lane") or {}
            manifest = experiment_manifests.get(item_id, {})
            has_attempt = any(attempt.get("item_id") == item_id and attempt.get("status") != "invalid" for attempt in experiment_attempts)
            if manifest.get("command_template") and not has_attempt:
                tasks.append(task(f"T{len(tasks) + 1:03d}", "experiment_run_preview", f"Preview experiment run for {item_id}", item_id=item_id, command=f"revagent experiment-run {item_id} --dry-run"))
            if item_id in experiment_manifests and lane.get("result_status") != "recorded":
                tasks.append(
                    task(
                        f"T{len(tasks) + 1:03d}",
                        "experiment_result_required",
                        f"Experiment result provenance required for {item_id}",
                        item_id=item_id,
                        status="blocked",
                        reason="RevAgent does not run experiments in the safe-auto loop",
                        command=f"revagent experiment-artifact {item_id} --path PATH --kind table --note \"NOTE\"",
                    )
                )

    if items and not candidates:
        tasks.append(task(f"T{len(tasks) + 1:03d}", "draft", "Draft response and candidate edits", command="revagent draft"))
    elif items:
        item_ids_with_candidates = {candidate.get("item_id") for candidate in candidates}
        if any(item["id"] not in item_ids_with_candidates for item in items):
            tasks.append(task(f"T{len(tasks) + 1:03d}", "propose", "Generate missing candidate edits", command="revagent propose"))

    if items and candidates and any(item["id"] not in llm_drafts for item in items):
        tasks.append(task(f"T{len(tasks) + 1:03d}", "llm_draft", "Generate offline LLM reviewer-intent drafts", command="revagent llm-draft --all"))

    for item in items:
        draft = llm_drafts.get(item["id"])
        if not draft:
            continue
        draft = ensure_llm_review_fields(draft)
        if draft.get("review_status") == "drafted":
            tasks.append(
                task(
                    f"T{len(tasks) + 1:03d}",
                    "llm_review_required",
                    f"Author review required for LLM draft {item['id']}",
                    item_id=item["id"],
                    status="blocked",
                    reason="LLM drafts must be accepted, rejected, or edited by the author",
                    command=f"revagent llm-review {item['id']}",
                )
            )
        elif draft.get("review_status") in {"accepted", "edited"} and draft.get("quality_status") == "unchecked":
            tasks.append(task(f"T{len(tasks) + 1:03d}", "llm_check", "Run LLM draft quality checks", command="revagent llm-check --all"))
        elif draft.get("quality_status") == "failed":
            tasks.append(
                task(
                    f"T{len(tasks) + 1:03d}",
                    "llm_quality_required",
                    f"Author revision required for LLM draft {item['id']}",
                    item_id=item["id"],
                    status="blocked",
                    reason="LLM draft quality check failed; edit or reject the draft",
                    command=f"revagent llm-review {item['id']}",
                )
            )

    for candidate in candidates:
        if candidate_needs_author_text(candidate):
            tasks.append(
                task(
                    f"T{len(tasks) + 1:03d}",
                    "candidate_author_text_required",
                    f"Author text required for candidate {candidate['id']}",
                    item_id=str(candidate.get("item_id", "")),
                    status="blocked",
                    reason="candidate requires author-provided final wording",
                    command=f"revagent edit-candidate {candidate['id']} --text-file PATH",
                )
            )
        elif candidate.get("status") == "proposed":
            reason = llm_candidate_gate_reason(config, candidate)
            if reason:
                tasks.append(
                    task(
                        f"T{len(tasks) + 1:03d}",
                        "llm_candidate_approval_required",
                        f"LLM candidate gate blocks {candidate['id']}",
                        item_id=str(candidate.get("item_id", "")),
                        status="blocked",
                        reason=reason,
                        command=f"revagent llm-review {candidate.get('llm_draft_id') or candidate.get('item_id')}",
                    )
                )

    if items and provenance_missing_or_stale(config):
        tasks.append(task(f"T{len(tasks) + 1:03d}", "provenance", "Generate revision provenance report", command="revagent provenance"))

    if items and readiness_missing_or_stale(config):
        tasks.append(task(f"T{len(tasks) + 1:03d}", "readiness", "Generate revision readiness report", command="revagent readiness"))

    tasks.append(task(f"T{len(tasks) + 1:03d}", "validate", "Validate workspace", command="revagent validate"))
    return annotate_tasks_with_runs(config, tasks, load_agent_runs(config))


def renumber_tasks(tasks: list[dict[str, object]]) -> list[dict[str, object]]:
    for index, entry in enumerate(tasks, start=1):
        entry["id"] = f"T{index:03d}"
    return tasks


def build_agent_state(base: Path) -> dict[str, object]:
    tasks = build_agent_tasks(base)
    return {
        "version": 1,
        "generated_at": now_iso(),
        "last_run_at": "",
        "tasks": tasks,
        "summary": summarize_tasks(tasks),
    }


def render_agent_state(state: dict[str, object]) -> str:
    lines = ["# Agent State", "", f"- Generated at: {state.get('generated_at', '')}", f"- Last run at: {state.get('last_run_at', '') or 'never'}", ""]
    summary = state.get("summary", {})
    lines.extend(["## Summary", ""])
    for status in ("pending", "blocked", "done", "failed", "skipped", "running"):
        lines.append(f"- {status}: {summary.get(status, 0)}")
    lines.extend(["", "## Tasks", ""])
    tasks = state.get("tasks", [])
    if not tasks:
        lines.append("- None.")
    for entry in tasks:
        item = f" item={entry.get('item_id')}" if entry.get("item_id") else ""
        lines.append(f"- `{entry['id']}` [{entry.get('status')}] {entry.get('kind')}{item}: {entry.get('title')}")
        if entry.get("fingerprint"):
            lines.append(f"  fingerprint: `{str(entry['fingerprint'])[:16]}`")
        if entry.get("dependency_fingerprint"):
            lines.append(f"  deps: `{str(entry['dependency_fingerprint'])[:16]}`")
        if entry.get("stale_reason"):
            lines.append(f"  stale: {entry['stale_reason']}")
        if entry.get("failure_class"):
            lines.append(f"  failure: {entry['failure_class']}")
        if entry.get("recovery_hint"):
            lines.append(f"  recovery: {entry['recovery_hint']}")
        if entry.get("last_run_status"):
            lines.append(f"  last run: {entry.get('last_run_status')} {entry.get('last_run_result') or entry.get('last_run_error') or ''}".rstrip())
        if entry.get("reason"):
            lines.append(f"  reason: {entry['reason']}")
        if entry.get("manual_command"):
            lines.append(f"  command: `{entry['manual_command']}`")
        if entry.get("result"):
            lines.append(f"  result: {entry['result']}")
        if entry.get("error"):
            lines.append(f"  error: {entry['error']}")
    return "\n".join(lines) + "\n"


def next_agent_task(state: dict[str, object]) -> dict[str, object] | None:
    tasks = list(state.get("tasks", []))
    for status in ("pending", "stale"):
        for entry in tasks:
            if entry.get("status") == status and entry.get("kind") in SAFE_TASK_KINDS:
                return entry
    for status in ("blocked", "manual_required", "failed"):
        for entry in tasks:
            if entry.get("status") == status:
                return entry
    return None


def render_agent_next(state: dict[str, object]) -> str:
    entry = next_agent_task(state)
    if not entry:
        return "No agent tasks are currently pending or blocked.\n"
    lines = [f"Next: `{entry.get('id', '')}` [{entry.get('status')}] {entry.get('kind')} {entry.get('title')}"]
    if entry.get("item_id"):
        lines.append(f"Item: {entry['item_id']}")
    if entry.get("stale_reason"):
        lines.append(f"Stale: {entry['stale_reason']}")
    if entry.get("reason"):
        lines.append(f"Reason: {entry['reason']}")
    if entry.get("failure_class"):
        lines.append(f"Failure: {entry['failure_class']}")
    if entry.get("recovery_hint"):
        lines.append(f"Recovery: {entry['recovery_hint']}")
    if entry.get("manual_command"):
        lines.append(f"Command: {entry['manual_command']}")
    return "\n".join(lines) + "\n"


def build_agent_report(base: Path) -> dict[str, object]:
    config = load_config(base)
    state = build_agent_state(base)
    runs = load_agent_runs(config)
    stale = [task for task in state["tasks"] if task.get("stale_reason")]
    failures = [task for task in state["tasks"] if task.get("status") == "failed"]
    manual = [task for task in state["tasks"] if task.get("status") in {"blocked", "manual_required"}]
    return {
        "version": 1,
        "generated_at": now_iso(),
        "summary": state["summary"],
        "next": next_agent_task(state) or {},
        "stale_count": len(stale),
        "failure_count": len(failures),
        "manual_count": len(manual),
        "run_count": len(runs),
        "recent_runs": runs[-10:],
        "stale_tasks": stale,
        "failed_tasks": failures,
        "manual_tasks": manual,
    }


def render_agent_report(report: dict[str, object]) -> str:
    lines = ["# Agent Report", "", f"- Generated at: {report.get('generated_at', '')}", f"- Runs recorded: {report.get('run_count', 0)}"]
    summary = report.get("summary", {})
    lines.extend(["", "## Summary", ""])
    for status in ("pending", "stale", "blocked", "failed", "done", "skipped", "running"):
        lines.append(f"- {status}: {summary.get(status, 0)}")
    lines.extend(["", "## Next", ""])
    next_task = report.get("next") or {}
    if next_task:
        lines.append(f"- `{next_task.get('id', '')}` [{next_task.get('status')}] {next_task.get('kind')}: {next_task.get('title')}")
        if next_task.get("manual_command"):
            lines.append(f"  command: `{next_task['manual_command']}`")
    else:
        lines.append("- None.")
    for heading, key in (("Stale Tasks", "stale_tasks"), ("Failed Tasks", "failed_tasks"), ("Manual Gates", "manual_tasks")):
        lines.extend(["", f"## {heading}", ""])
        entries = report.get(key, [])
        if not entries:
            lines.append("- None.")
            continue
        for entry in entries:
            lines.append(f"- `{entry.get('id', '')}` {entry.get('kind')} item={entry.get('item_id', '') or '-'}")
            if entry.get("stale_reason"):
                lines.append(f"  stale: {entry['stale_reason']}")
            if entry.get("failure_class"):
                lines.append(f"  failure: {entry['failure_class']}")
            if entry.get("manual_command"):
                lines.append(f"  command: `{entry['manual_command']}`")
    return "\n".join(lines) + "\n"


def write_agent_report(base: Path) -> dict[str, object]:
    config = load_config(base)
    report = build_agent_report(base)
    write_text(config.workspace / "agent_report.md", render_agent_report(report))
    return report


def count_by(values: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in values:
        value = str(item.get(key, "") or "missing")
        counts[value] = counts.get(value, 0) + 1
    return counts


def lane_summary(items: list[dict[str, object]], proof_workflows: dict[str, dict], experiment_manifests: dict[str, dict]) -> dict[str, dict[str, int]]:
    proofs = [item for item in items if item.get("kind") == "proof"]
    experiments = [item for item in items if item.get("kind") == "experiment"]
    manuscripts = [item for item in items if item.get("kind") == "manuscript"]
    return {
        "proof": {
            "total": len(proofs),
            "workflows": sum(1 for item in proofs if item.get("id") in proof_workflows),
            "approved": sum(1 for item in proofs if (item.get("proof_lane") or {}).get("approval_status") == "approved"),
            "blocked": sum(1 for item in proofs if (item.get("proof_lane") or {}).get("approval_status", "required") != "approved"),
        },
        "experiment": {
            "total": len(experiments),
            "contracts": sum(1 for item in experiments if item.get("id") in experiment_manifests),
            "recorded": sum(1 for item in experiments if (item.get("experiment_lane") or {}).get("result_status") == "recorded"),
            "blocked": sum(1 for item in experiments if (item.get("experiment_lane") or {}).get("result_status") != "recorded"),
        },
        "manuscript": {
            "total": len(manuscripts),
            "planned": sum(1 for item in manuscripts if item.get("planning_status") in {"planned", "drafted", "evidence_ready", "approved", "incorporated", "closed"}),
            "closed": sum(1 for item in manuscripts if item.get("planning_status") == "closed"),
            "blocked": sum(1 for item in manuscripts if item.get("blocking_questions")),
        },
    }


def active_session_for_dashboard(base: Path, config: Config) -> dict[str, object]:
    session = current_agent_session(config)
    if not session:
        return {}
    return update_current_session(base, refresh_agent_session(base, session))


def build_agent_dashboard(base: Path) -> dict[str, object]:
    config = load_config(base)
    session = active_session_for_dashboard(base, config)
    state = build_agent_state(base)
    write_agent_state(config, state)
    report = build_agent_report(base)
    decisions = refresh_agent_decisions(base, linked_session_id=str(session.get("session_id", "")) if session else "")
    items = load_items(config)
    candidates = load_candidates(config)
    proof_workflows = load_proof_workflows(config)
    experiment_manifests = load_experiment_manifests(config)
    experiment_attempts = load_experiment_run_attempts(config)
    review_analyses = load_review_analyses(config)
    readiness = build_revision_readiness(base)
    from .project_runtime import author_decision_console

    revision_cycles = author_decision_console(base)
    runs = load_agent_runs(config)
    open_decisions = [decision for decision in decisions if decision.get("status") in {"open", "stale"}]
    return {
        "version": 1,
        "generated_at": now_iso(),
        "workspace": str(config.workspace),
        "journal": config.journal,
        "main_tex": config.main_tex,
        "session": session,
        "summary": state.get("summary", {}),
        "next": next_agent_task(state) or {},
        "review_items": {
            "total": len(items),
            "by_kind": count_by(items, "kind"),
            "by_planning_status": count_by(items, "planning_status"),
            "high_risk": sum(1 for item in items if item.get("risk") == "high"),
            "analysis_ready": sum(1 for item in items if item.get("id") in review_analyses),
        },
        "lanes": lane_summary(items, proof_workflows, experiment_manifests),
        "experiment_runs": {
            "attempts": len([attempt for attempt in experiment_attempts if attempt.get("status") != "invalid"]),
            "succeeded": sum(1 for attempt in experiment_attempts if attempt.get("status") == "succeeded"),
            "failed": sum(1 for attempt in experiment_attempts if attempt.get("status") == "failed"),
            "ready_manifests": sum(1 for manifest in experiment_manifests.values() if manifest.get("command_template")),
        },
        "candidates": {
            "total": len(candidates),
            "by_status": count_by(candidates, "status"),
        },
        "readiness": {
            "overall_status": readiness.get("overall_status", ""),
            "summary_counts": readiness.get("summary_counts", {}),
            "score": int(
                100
                * (readiness.get("summary_counts", {}).get("ready", 0) if readiness.get("items") else 0)
                / max(1, len(readiness.get("items", [])))
            ),
            "top_blockers": readiness.get("blockers", [])[:5],
            "submit_pack_missing": readiness.get("submit_pack_missing", []),
        },
        "revision_cycles": revision_cycles,
        "manual_decisions": open_decisions,
        "failed_tasks": report.get("failed_tasks", []),
        "stale_tasks": report.get("stale_tasks", []),
        "recent_runs": runs[-8:],
    }


def render_count_map(values: dict[str, int]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


def render_agent_dashboard(dashboard: dict[str, object]) -> str:
    lines = [
        "# Agent Dashboard",
        "",
        f"- Generated at: {dashboard.get('generated_at', '')}",
        f"- Workspace: `{dashboard.get('workspace', '')}`",
        f"- Journal: {dashboard.get('journal', '')}",
        f"- Main TeX: `{dashboard.get('main_tex', '')}`",
        "",
        "## Current Session",
        "",
    ]
    session = dashboard.get("session") or {}
    if session:
        lines.append(f"- Session: `{session.get('session_id', '')}` goal={session.get('goal', '')}")
        lines.append(f"- Status: {session.get('status', '')}")
        lines.append(f"- Current phase: {session.get('current_phase', '')}")
        lines.append(f"- Resume hint: {session.get('resume_hint', '')}")
        if session.get("blocked_reason"):
            lines.append(f"- Blocked reason: {session['blocked_reason']}")
    else:
        lines.append("- No active session. Run `revagent agent-plan --goal rebuttal-draft`.")

    summary = dashboard.get("summary", {})
    lines.extend(["", "## Task Summary", ""])
    for status in ("pending", "stale", "blocked", "failed", "done", "skipped", "running"):
        lines.append(f"- {status}: {summary.get(status, 0)}")

    next_task = dashboard.get("next") or {}
    lines.extend(["", "## Next Action", ""])
    if next_task:
        lines.append(f"- `{next_task.get('id', '')}` [{next_task.get('status', '')}] {next_task.get('kind', '')}: {next_task.get('title', '')}")
        if next_task.get("item_id"):
            lines.append(f"- Item: {next_task['item_id']}")
        if next_task.get("reason"):
            lines.append(f"- Reason: {next_task['reason']}")
        if next_task.get("recovery_hint"):
            lines.append(f"- Recovery: {next_task['recovery_hint']}")
        if next_task.get("manual_command"):
            lines.append(f"- Command: `{next_task['manual_command']}`")
    else:
        lines.append("- No pending, stale, blocked, or failed agent tasks.")

    review = dashboard.get("review_items", {})
    lines.extend(["", "## Review Progress", ""])
    lines.append(f"- Items: {review.get('total', 0)} high_risk={review.get('high_risk', 0)}")
    lines.append(f"- Review analysis: {review.get('analysis_ready', 0)}/{review.get('total', 0)} ready")
    lines.append(f"- By kind: {render_count_map(review.get('by_kind', {}))}")
    lines.append(f"- By planning status: {render_count_map(review.get('by_planning_status', {}))}")

    lines.extend(["", "## Lanes", ""])
    lanes = dashboard.get("lanes", {})
    for lane_name in ("proof", "experiment", "manuscript"):
        lines.append(f"- {lane_name}: {render_count_map(lanes.get(lane_name, {}))}")
    experiment_runs = dashboard.get("experiment_runs", {})
    lines.append(f"- experiment runs: {render_count_map(experiment_runs)}")

    candidates = dashboard.get("candidates", {})
    lines.extend(["", "## Candidates", ""])
    lines.append(f"- Total: {candidates.get('total', 0)}")
    lines.append(f"- By status: {render_count_map(candidates.get('by_status', {}))}")

    readiness = dashboard.get("readiness", {})
    lines.extend(["", "## Readiness", ""])
    lines.append(f"- Overall: {readiness.get('overall_status', '')}")
    lines.append(f"- Score: {readiness.get('score', 0)}%")
    lines.append(f"- Counts: {render_count_map(readiness.get('summary_counts', {}))}")
    blockers = readiness.get("top_blockers", [])
    if blockers:
        lines.append("- Top blockers:")
        for blocker in blockers:
            lines.append(f"  - `{blocker.get('item_id', '')}` {blocker.get('readiness_status', '')}: {', '.join(blocker.get('missing_inputs', []) or blocker.get('manual_actions', [])) or 'blocked'}")
    else:
        lines.append("- Top blockers: none")
    missing = readiness.get("submit_pack_missing", [])
    lines.append(f"- Submit-pack dry-run: `revagent submit-pack --dry-run` ({len(missing)} missing)")

    cycles = dashboard.get("revision_cycles", {})
    lines.extend(["", "## Revision Cycles", ""])
    if cycles.get("pending"):
        lines.append("- NOT SUBMISSION READY: pending cycle decisions or evidence work remain.")
        for cycle in cycles["pending"]:
            lines.append(f"- `{cycle.get('cycle_id', '')}` item={cycle.get('item_id', '')} status={cycle.get('status', '')} verdict={cycle.get('verdict', '')}")
            lines.append(f"  - Next: `{cycle.get('next_command', '')}`")
            if cycle.get("invalidation_reason"):
                lines.append(f"  - Stale: {cycle['invalidation_reason']}")
    elif cycles.get("cycles"):
        lines.append("- All recorded revision cycles have completed their author decision; existing readiness gates still apply.")
    else:
        lines.append(f"- No revision cycles. {cycles.get('reason', '')}")

    decisions = dashboard.get("manual_decisions", [])
    lines.extend(["", "## Manual Decisions", ""])
    if decisions:
        for decision in decisions[:12]:
            lines.append(f"- `{decision.get('decision_id', '')}` [{decision.get('risk', '')}] {decision.get('kind', '')} subject={decision.get('subject_id', '')}")
            if decision.get("required_command"):
                lines.append(f"  command: `{decision['required_command']}`")
    else:
        lines.append("- None.")

    for title, key in (("Failed Tasks", "failed_tasks"), ("Stale Tasks", "stale_tasks")):
        lines.extend(["", f"## {title}", ""])
        entries = dashboard.get(key, [])
        if not entries:
            lines.append("- None.")
            continue
        for entry in entries[:12]:
            lines.append(f"- `{entry.get('id', '')}` {entry.get('kind', '')} item={entry.get('item_id', '') or '-'}")
            if entry.get("stale_reason"):
                lines.append(f"  stale: {entry['stale_reason']}")
            if entry.get("recovery_hint"):
                lines.append(f"  recovery: {entry['recovery_hint']}")

    runs = dashboard.get("recent_runs", [])
    lines.extend(["", "## Recent Runs", ""])
    if runs:
        for run in runs:
            lines.append(f"- `{run.get('run_id', '')}` {run.get('status', '')} {run.get('kind', '')} item={run.get('item_id', '') or '-'}")
    else:
        lines.append("- None.")
    return "\n".join(lines).rstrip() + "\n"


def write_agent_dashboard(base: Path) -> dict[str, object]:
    config = load_config(base)
    dashboard = build_agent_dashboard(base)
    write_text(config.workspace / "agent_dashboard.md", render_agent_dashboard(dashboard))
    return dashboard


def execute_task(base: Path, entry: dict[str, object]) -> str:
    kind = entry["kind"]
    item_id = str(entry.get("item_id", ""))
    if kind == "migrate":
        result = migrate_workspace(base, dry_run=False)
        return f"changed={result['changed']} actions={len(result['actions'])}"
    if kind == "plan_workspace":
        create_plan(base)
        return "workspace plan refreshed"
    if kind == "review_analysis":
        analyses = analyze_all_review_items(base)
        return f"review analyses count={len(analyses)}"
    if kind == "plan_item":
        plan_item(base, item_id)
        return f"planned {item_id}"
    if kind == "proof_plan":
        proof_plan_for_item(base, item_id)
        return f"proof workflow planned for {item_id}"
    if kind == "experiment_contract":
        experiment_contract(base, item_id)
        return f"experiment contract planned for {item_id}"
    if kind == "experiment_run_preview":
        preview = experiment_run_preview(base, item_id)
        return f"ready={preview['ready']} command={preview.get('command', '') or 'TBD'}"
    if kind == "draft":
        create_draft(base)
        return "draft and candidates generated"
    if kind == "propose":
        candidates = propose_candidates(base)
        return f"candidate edits count={len(candidates)}"
    if kind == "llm_draft":
        drafts = draft_all_with_llm(base)
        return f"llm drafts count={len(drafts)}"
    if kind == "llm_check":
        drafts = llm_check_all(base)
        failed = sum(1 for draft in drafts.values() if ensure_llm_review_fields(draft).get("quality_status") == "failed")
        return f"llm quality checked={len(drafts)} failed={failed}"
    if kind == "provenance":
        provenance = write_revision_provenance(base)
        return f"provenance items={len(provenance.get('items', []))}"
    if kind == "readiness":
        readiness = write_revision_readiness(base)
        return f"overall={readiness.get('overall_status')} blockers={len(readiness.get('blockers', []))}"
    if kind == "validate":
        result = validate_workspace(base)
        return f"ok={result['ok']} warnings={len(result['warnings'])} issues={len(result['issues'])}"
    raise ValueError(f"unsupported agent task kind {kind}")


def next_safe_task(tasks: list[dict[str, object]], attempted: set[str] | None = None, retry_failed: bool = False) -> dict[str, object] | None:
    attempted = attempted or set()
    runnable_statuses = {"pending", "stale"}
    if retry_failed:
        runnable_statuses.add("failed")
    pending = [
        entry
        for entry in tasks
        if entry.get("status") in runnable_statuses and entry.get("kind") in SAFE_TASK_KINDS and entry.get("fingerprint") not in attempted
    ]
    non_validate = [entry for entry in pending if entry.get("kind") != "validate"]
    if non_validate:
        return non_validate[0]
    return pending[0] if pending else None


def run_record(run_id: str, entry: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": run_id,
        "task_id": entry.get("id", ""),
        "task_identity": entry.get("task_identity") or task_identity(entry),
        "kind": entry.get("kind", ""),
        "item_id": entry.get("item_id", ""),
        "fingerprint": entry.get("fingerprint") or task_fingerprint(entry),
        "dependency_fingerprint": entry.get("dependency_fingerprint", ""),
        "dependencies": entry.get("dependencies", []),
        "stale_reason": entry.get("stale_reason", ""),
        "failure_class": entry.get("failure_class", ""),
        "recovery_hint": entry.get("recovery_hint", ""),
        "status": entry.get("status", ""),
        "started_at": entry.get("started_at", ""),
        "finished_at": entry.get("finished_at", ""),
        "result": entry.get("result", ""),
        "error": entry.get("error", ""),
    }


def unchanged_success(entry: dict[str, object]) -> bool:
    return entry.get("kind") != "validate" and entry.get("last_run_status") == "done"


def classify_failure(exc: Exception) -> tuple[str, str]:
    message = str(exc).lower()
    if "not found" in message or "missing" in message:
        return "input_missing", "create or restore the missing input, then rerun the agent"
    if "provider" in message or "environment" in message or "url" in message:
        return "provider_failed", "fix provider configuration or use the fake provider"
    if "validation" in message or "invalid" in message:
        return "validation_failed", "inspect revagent validate output, then rerun with --retry-failed"
    return "unknown_failure", "inspect the error, fix the input, or rerun with --retry-failed"


def run_agent_once(base: Path, limit: int | None = None, until_blocked: bool = False, retry_failed: bool = False, max_failures: int | None = None) -> dict[str, object]:
    config = load_config(base)
    executed = 0
    failures = 0
    history: list[dict[str, object]] = []
    final_tasks: list[dict[str, object]] = []
    attempted: set[str] = set()
    run_id = now_iso()
    while True:
        current_tasks = build_agent_tasks(base)
        entry = next_safe_task(current_tasks, attempted, retry_failed=retry_failed)
        if entry is None:
            final_tasks = history + [task for task in current_tasks if task.get("fingerprint") not in attempted]
            break
        if limit is not None and executed >= limit:
            final_tasks = history + current_tasks
            break
        if not until_blocked and limit is None and executed > 0:
            final_tasks = history + current_tasks
            break
        if entry.get("kind") == "validate" and any(task.get("kind") == "validate" and task.get("status") == "done" for task in history):
            final_tasks = history + [task for task in current_tasks if task.get("kind") != "validate"]
            break
        entry = dict(entry)
        fingerprint = str(entry.get("fingerprint") or task_fingerprint(entry))
        attempted.add(fingerprint)
        if unchanged_success(entry):
            entry["status"] = "skipped"
            entry["started_at"] = now_iso()
            entry["finished_at"] = now_iso()
            entry["result"] = "previous successful run unchanged"
            append_agent_run(config, run_record(run_id, entry))
            executed += 1
            history.append(entry)
            continue
        entry["status"] = "running"
        entry["started_at"] = now_iso()
        try:
            entry["result"] = execute_task(base, entry)
            entry["status"] = "done"
            executed += 1
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            entry["failure_class"], entry["recovery_hint"] = classify_failure(exc)
            entry["finished_at"] = now_iso()
            append_agent_run(config, run_record(run_id, entry))
            failures += 1
            final_tasks = history + [entry]
            state = {
                "version": 1,
                "generated_at": now_iso(),
                "last_run_at": now_iso(),
                "tasks": renumber_tasks(final_tasks),
                "summary": summarize_tasks(final_tasks),
            }
            write_agent_state(config, state)
            return state
        entry["finished_at"] = now_iso()
        append_agent_run(config, run_record(run_id, entry))
        history.append(entry)
        if max_failures is not None and failures >= max_failures:
            final_tasks = history + current_tasks
            break
        if entry.get("kind") == "validate":
            final_tasks = history + [task for task in build_agent_tasks(base) if task.get("kind") != "validate"]
            break
    final_tasks = renumber_tasks(final_tasks)
    state = {
        "version": 1,
        "generated_at": now_iso(),
        "last_run_at": now_iso(),
        "tasks": final_tasks,
        "summary": summarize_tasks(final_tasks),
    }
    write_agent_state(config, state)
    return state


def write_eval_demo_project(base: Path, comments: str | None = None) -> None:
    (base / "scripts").mkdir(parents=True, exist_ok=True)
    (base / "results").mkdir(parents=True, exist_ok=True)
    write_text(base / "scripts" / "run_demo.py", "print('demo')\n")
    write_text(
        base / "paper.tex",
        "\\documentclass{article}\n"
        "\\newtheorem{theorem}{Theorem}\n"
        "\\begin{document}\n"
        "\\section{Convergence}\n"
        "\\begin{theorem}\\label{thm:conv} The scheme converges by Lemma~\\ref{lem:stable}.\\end{theorem}\n"
        "\\begin{proof} The proof follows from stability.\\end{proof}\n"
        "\\section{Numerical Experiments}\n"
        "We report a benchmark in Figure~\\ref{fig:demo} and Table~\\ref{tab:demo}.\n"
        "\\begin{figure}\\caption{Demo figure.}\\label{fig:demo}\\end{figure}\n"
        "\\begin{table}\\caption{Demo table.}\\label{tab:demo}\\end{table}\n"
        "\\bibliography{refs}\n"
        "\\end{document}\n",
    )
    write_text(
        base / "comments.md",
        comments
        or "# Reviewer 1\n"
        "- Please clarify the proof of the convergence theorem and its assumptions.\n"
        "- Add a numerical experiment comparing the benchmark parameter choices with a fixed seed.\n"
        "- Please clarify the contribution in the introduction.\n",
    )


def eval_pass(name: str, detail: str, data: dict[str, object] | None = None) -> dict[str, object]:
    return {"name": name, "ok": True, "detail": detail, "data": data or {}}


def eval_fail(name: str, detail: str, data: dict[str, object] | None = None) -> dict[str, object]:
    return {"name": name, "ok": False, "detail": detail, "data": data or {}}


def run_full_revision_eval(base: Path) -> list[dict[str, object]]:
    from .workspace import init_workspace
    from .reviews import ingest_comments

    write_eval_demo_project(base)
    init_workspace(base, "siam", ".", "paper.tex")
    ingest_comments(base, "comments.md")
    session = plan_agent_session(base, "rebuttal-draft")
    session = resume_agent_session(base)
    config = load_config(base)
    decisions = refresh_agent_decisions(base)
    candidates = load_candidates(config)
    checks = [
        eval_pass("session_created", "agent session created", {"session_id": session["session_id"]})
        if session.get("session_id")
        else eval_fail("session_created", "missing session id"),
        eval_pass("session_blocked", "session blocks on manual gates")
        if session.get("status") == "blocked"
        else eval_fail("session_blocked", f"expected blocked, got {session.get('status')}"),
        eval_pass("manual_decisions", "manual decisions generated")
        if any(decision.get("status") == "open" for decision in decisions)
        else eval_fail("manual_decisions", "no open manual decisions generated"),
        eval_pass("proof_decision", "proof approval decision generated")
        if any(decision.get("kind") == "proof_approval_required" for decision in decisions)
        else eval_fail("proof_decision", "missing proof approval decision"),
        eval_pass("experiment_decision", "experiment result decision generated")
        if any(decision.get("kind") == "experiment_result_required" for decision in decisions)
        else eval_fail("experiment_decision", "missing experiment result decision"),
        eval_pass("no_auto_candidate_approval", "no candidates were auto-approved or auto-applied")
        if not any(candidate.get("status") in {"approved", "applied"} for candidate in candidates)
        else eval_fail("no_auto_candidate_approval", "candidate was approved/applied by safe loop"),
    ]
    return checks


def run_stale_input_eval(base: Path) -> list[dict[str, object]]:
    from .workspace import init_workspace

    write_eval_demo_project(base, comments="# Reviewer 1\n- Please clarify the contribution.\n")
    init_workspace(base, "siam", ".", "paper.tex")
    first = run_agent_once(base, limit=1)
    paper = base / "paper.tex"
    write_text(paper, paper.read_text(encoding="utf-8").replace("Demo table.", "Demo table with revised caption."))
    state = build_agent_state(base)
    validate_task = next((task for task in state.get("tasks", []) if task.get("kind") == "validate"), {})
    return [
        eval_pass("initial_validate_done", "initial validate task completed")
        if first.get("tasks", [{}])[0].get("status") == "done"
        else eval_fail("initial_validate_done", "initial validate did not complete"),
        eval_pass("stale_detected", "input change marked validate stale")
        if validate_task.get("status") == "stale"
        else eval_fail("stale_detected", f"expected stale validate, got {validate_task.get('status')}"),
    ]


def run_safety_gates_eval(base: Path) -> list[dict[str, object]]:
    checks = run_full_revision_eval(base)
    config = load_config(base)
    drafts = load_llm_drafts(config)
    decisions = load_agent_decisions(config)
    checks.extend(
        [
            eval_pass("llm_drafts_unreviewed", "LLM drafts remain drafted until author review")
            if drafts and all(draft.get("review_status") == "drafted" for draft in drafts.values())
            else eval_fail("llm_drafts_unreviewed", "LLM draft review status was advanced automatically"),
            eval_pass("decision_queue_blocks", "decision queue contains open manual gates")
            if any(decision.get("status") == "open" for decision in decisions)
            else eval_fail("decision_queue_blocks", "no open decisions remain"),
        ]
    )
    return checks


def run_eval_fixture(name: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=f"revagent-eval-{name}-") as tmp:
        base = Path(tmp)
        if name == "full-revision":
            checks = run_full_revision_eval(base)
        elif name == "stale-input":
            checks = run_stale_input_eval(base)
        elif name == "safety-gates":
            checks = run_safety_gates_eval(base)
        else:
            raise ValueError(f"unknown eval fixture {name}; choose one of {', '.join(sorted(AGENT_EVAL_FIXTURES))}")
    return {
        "fixture": name,
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
    }


def render_agent_eval_report(report: dict[str, object]) -> str:
    lines = ["# Agent Eval Report", "", f"- Generated at: {report.get('generated_at', '')}", f"- Overall: {'pass' if report.get('ok') else 'fail'}", ""]
    for fixture in report.get("fixtures", []):
        lines.append(f"## {fixture.get('fixture', '')}")
        lines.append("")
        lines.append(f"- Status: {'pass' if fixture.get('ok') else 'fail'}")
        for check in fixture.get("checks", []):
            marker = "pass" if check.get("ok") else "fail"
            lines.append(f"- {marker}: {check.get('name', '')} - {check.get('detail', '')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_agent_eval_report(base: Path, report: dict[str, object]) -> None:
    config = load_config(base)
    write_json(config.workspace / "agent_eval_report.json", report)
    write_text(config.workspace / "agent_eval_report.md", render_agent_eval_report(report))


def run_agent_eval(base: Path, fixture: str | None = None) -> dict[str, object]:
    names = sorted(AGENT_EVAL_FIXTURES) if fixture in {None, "all"} else [fixture]
    fixtures = [run_eval_fixture(str(name)) for name in names]
    report = {
        "version": 1,
        "generated_at": now_iso(),
        "ok": all(item["ok"] for item in fixtures),
        "fixtures": fixtures,
    }
    write_agent_eval_report(base, report)
    return report


__all__ = [
    "agent_blockers",
    "build_agent_report",
    "build_agent_state",
    "build_agent_dashboard",
    "complete_check_agent_session",
    "default_agent_policy",
    "dismiss_agent_decision",
    "get_agent_decision",
    "load_agent_decisions",
    "load_agent_sessions",
    "load_agent_state",
    "load_agent_runs",
    "load_agent_policy",
    "next_agent_task",
    "plan_agent_session",
    "refresh_agent_decisions",
    "render_agent_state",
    "render_agent_blockers",
    "render_agent_dashboard",
    "render_agent_decisions",
    "render_agent_runs",
    "render_agent_next",
    "render_agent_policy",
    "render_agent_report",
    "render_agent_sessions",
    "resume_agent_session",
    "resume_agent_session_watch",
    "resolve_agent_decision",
    "render_agent_eval_report",
    "run_agent_eval",
    "run_agent_once",
    "task_fingerprint",
    "write_agent_policy",
    "write_agent_decisions",
    "write_agent_report",
    "write_agent_sessions",
    "write_agent_state",
    "write_agent_dashboard",
]
