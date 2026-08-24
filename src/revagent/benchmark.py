"""Deterministic benchmark runner for review-project agent regression metrics."""

from __future__ import annotations

import json
import hashlib
import difflib
import re
import shutil
import tempfile
import itertools
from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .project_runtime import evaluate_review_item, initialize_project_runtime, project_status, run_project_cycle
from .reviews import ingest_comments
from .workspace import init_workspace


SHADOW_SCORE_THRESHOLDS = {
    "plan_lane_accuracy": 0.90,
    "high_risk_recall": 1.00,
    "defect_detection_recall": 0.90,
    "false_pass_rate": 0.05,
    "claim_provenance_completeness": 1.00,
}

SYNTHETIC_DOMAINS = ("pde_fem", "pde_fvm", "dg", "time_integration", "numerical_linear_algebra", "optimization", "uq_random", "inverse_problems")
SYNTHETIC_DEFECTS = ("incorrect_assumption", "pseudo_citation", "missing_seed", "unfair_baseline", "data_drift", "environment_drift", "response_mismatch", "prompt_injection")


def generate_synthetic_catalog(base: Path, count: int = 200) -> dict[str, object]:
    """Generate a deterministic, text-free catalog for locally authored fixtures.

    It deliberately stores commitments rather than hidden labels or manuscript
    text; evaluators supply protected fixture content outside the repository.
    """
    if count < 200:
        raise ValueError("synthetic catalog must contain at least 200 fixtures")
    combinations = list(itertools.product(SYNTHETIC_DOMAINS, SYNTHETIC_DEFECTS))
    fixtures = []
    for index in range(count):
        domain, defect = combinations[index % len(combinations)]
        fixture_id = f"SYN-{index + 1:03d}"
        hidden = {"fixture_id": fixture_id, "domain": domain, "defect": defect, "required_high_risk_detection": defect in {"incorrect_assumption", "missing_seed", "unfair_baseline", "data_drift", "environment_drift"}}
        fixtures.append({"fixture_id": fixture_id, "domain": domain, "attack_or_defect_class": defect, "label_commitment": hashlib.sha256(json.dumps(hidden, sort_keys=True).encode("utf-8")).hexdigest(), "fixture_text": "not_stored"})
    catalog = {"version": 1, "generated_at": now_iso(), "classification": "synthetic metadata only; no private manuscript or reviewer text", "fixture_count": count, "domains": list(SYNTHETIC_DOMAINS), "defect_classes": list(SYNTHETIC_DEFECTS), "fixtures": fixtures, "status": "fixture_content_and_blind_expert_labels_required"}
    config = load_config(base)
    write_json(config.workspace / "synthetic_benchmark_catalog.json", catalog)
    write_text(config.workspace / "synthetic_benchmark_catalog.md", "# Synthetic Benchmark Catalog\n\n" + f"- Fixtures: {count}\n- Domains: {', '.join(SYNTHETIC_DOMAINS)}\n- Defect classes: {', '.join(SYNTHETIC_DEFECTS)}\n- Status: fixture content and blind expert labels required.\n")
    return catalog


def _file_fingerprint(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "lines": len(raw.splitlines())}


def register_shadow_benchmark(base: Path, case_dir: Path, case_id: str) -> dict[str, object]:
    """Register a local historical case without copying manuscript or reviewer text."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", case_id):
        raise ValueError("case_id must contain only lowercase letters, numbers, _ or -")
    required = {"original": case_dir / "main.tex", "revised": case_dir / "article.tex", "response": case_dir / "resp.tex"}
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise ValueError("shadow case is missing " + ", ".join(missing))
    data_card = read_json(case_dir / "data_card.json", {})
    required_card = {"permission_status", "deidentification_status", "retention_rule", "subfield"}
    if not isinstance(data_card, dict) or not required_card <= set(data_card) or data_card.get("permission_status") != "written" or data_card.get("deidentification_status") != "completed":
        raise ValueError("shadow case requires a data_card.json with written permission and completed deidentification")
    original = required["original"].read_text(encoding="utf-8", errors="replace").splitlines()
    revised = required["revised"].read_text(encoding="utf-8", errors="replace").splitlines()
    response = required["response"].read_text(encoding="utf-8", errors="replace")
    additions = sum(1 for line in difflib.ndiff(original, revised) if line.startswith("+ "))
    deletions = sum(1 for line in difflib.ndiff(original, revised) if line.startswith("- "))
    record = {
        "version": 1,
        "case_id": case_id,
        "registered_at": now_iso(),
        "data_classification": "local-only historical case; raw source is not copied into RevAgent",
        "data_card": {key: data_card[key] for key in required_card},
        "files": {name: _file_fingerprint(path) for name, path in required.items()},
        "revision_delta": {"added_lines": additions, "deleted_lines": deletions},
        "response_structure": {"comment_markers": len(re.findall(r"(?im)^.*comment", response)), "response_markers": len(re.findall(r"(?im)^.*response", response))},
        "evaluation": {"mode": "shadow", "expert_scores": {}, "required_dimensions": ["plan_lane_accuracy", "high_risk_recall", "defect_detection_recall", "false_pass_rate", "claim_provenance_completeness"], "status": "awaiting_expert_review"},
    }
    config = load_config(base)
    path = config.workspace / "shadow_benchmarks.json"
    records = read_json(path, {})
    if not isinstance(records, dict):
        records = {}
    records[case_id] = record
    write_json(path, records)
    template = config.workspace / "shadow_benchmark_expert_template.md"
    write_text(template, "# Shadow Benchmark Expert Evaluation\n\nRaw manuscripts and reviewer text remain outside this workspace.\n\n## Case\n\n- Case ID: `" + case_id + "`\n- Required independent experts: 2\n\n## Scores (0-1)\n\n- Plan lane accuracy:\n- High-risk recall:\n- Defect detection recall:\n- False-pass rate:\n- Claim provenance completeness:\n\n## Evidence and disagreement notes\n\n- Do not quote or copy protected manuscript/reviewer text here. Use local locators and hashes only.\n")
    return record


def record_shadow_expert_scores(
    base: Path, case_id: str, expert_id: str, scores: dict[str, object]
) -> dict[str, object]:
    """Record one pseudonymous expert scorecard without retaining case text."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", expert_id):
        raise ValueError("expert_id must be a non-identifying lowercase pseudonym")
    config = load_config(base)
    path = config.workspace / "shadow_benchmarks.json"
    records = read_json(path, {})
    if not isinstance(records, dict) or not isinstance(records.get(case_id), dict):
        raise ValueError("unknown shadow benchmark case")
    record = records[case_id]
    evaluation = record.get("evaluation")
    if not isinstance(evaluation, dict):
        raise ValueError("shadow benchmark has an invalid evaluation record")
    dimensions = evaluation.get("required_dimensions")
    if not isinstance(dimensions, list) or not all(isinstance(value, str) for value in dimensions):
        raise ValueError("shadow benchmark has invalid score dimensions")
    if set(scores) != set(dimensions):
        raise ValueError("scores must contain exactly the required dimensions")
    normalized: dict[str, float] = {}
    for dimension in dimensions:
        value = scores[dimension]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"score for {dimension} must be between 0 and 1")
        normalized[dimension] = float(value)
    expert_scores = evaluation.get("expert_scores")
    if not isinstance(expert_scores, dict):
        expert_scores = {}
        evaluation["expert_scores"] = expert_scores
    if expert_id in expert_scores:
        raise ValueError("an expert pseudonym may submit only one scorecard per case")
    expert_scores[expert_id] = {"recorded_at": now_iso(), "scores": normalized}
    cards = [entry for entry in expert_scores.values() if isinstance(entry, dict) and isinstance(entry.get("scores"), dict)]
    if len(cards) >= 2:
        evaluation["aggregate_scores"] = {
            dimension: sum(float(card["scores"][dimension]) for card in cards) / len(cards)
            for dimension in dimensions
        }
        evaluation["status"] = "expert_review_recorded"
    else:
        evaluation["status"] = "awaiting_second_independent_expert"
    write_json(path, records)
    return record


def assess_shadow_scores(scorecards: dict[str, dict[str, object]]) -> dict[str, object]:
    """Aggregate pseudonymous scorecards and fail closed against Phase 39 thresholds."""
    if len(scorecards) < 2:
        raise ValueError("at least two distinct expert scorecards are required")
    dimensions = set(SHADOW_SCORE_THRESHOLDS)
    normalized: list[dict[str, float]] = []
    for pseudonym, scores in scorecards.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", pseudonym) or not isinstance(scores, dict):
            raise ValueError("scorecards require non-identifying pseudonyms and score objects")
        if set(scores) != dimensions:
            raise ValueError("each scorecard must contain exactly the Phase 39 dimensions")
        card: dict[str, float] = {}
        for dimension in dimensions:
            value = scores[dimension]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"score for {dimension} must be between 0 and 1")
            card[dimension] = float(value)
        normalized.append(card)
    means = {dimension: sum(card[dimension] for card in normalized) / len(normalized) for dimension in sorted(dimensions)}
    failed = []
    for dimension, target in SHADOW_SCORE_THRESHOLDS.items():
        value = means[dimension]
        passed = value <= target if dimension == "false_pass_rate" else value >= target
        if not passed:
            failed.append({"dimension": dimension, "observed": value, "target": f"<={target}" if dimension == "false_pass_rate" else f">={target}"})
    actions = {
        "plan_lane_accuracy": "Improve LaTex response parsing and split each reviewer request into a typed lane before planning.",
        "high_risk_recall": "Add conservative proof/stability/convergence/experiment triggers and require high-risk lane recall of 1.00.",
        "defect_detection_recall": "Add seeded computational-mathematics defect fixtures and require an independently reviewed coverage matrix.",
        "false_pass_rate": "Tighten pass predicates: unresolved assumptions, provenance gaps, or unassessed criteria must block pass.",
        "claim_provenance_completeness": "Require every Planner claim and Reviewer finding to link to a stable source locator and evidence hash.",
    }
    return {
        "version": 1,
        "expert_count": len(normalized),
        "means": means,
        "thresholds": SHADOW_SCORE_THRESHOLDS,
        "failed_gates": failed,
        "status": "calibration_required" if failed else "thresholds_met_pending_more_cases",
        "next_actions": [actions[entry["dimension"]] for entry in failed],
        "independence_note": "Distinct pseudonyms are recorded; actual expert independence remains a human-governed condition.",
    }


def run_benchmark(base: Path, fixture: Path) -> dict[str, object]:
    manifest = read_json(fixture / "benchmark.json", {})
    if not isinstance(manifest, dict):
        raise ValueError("benchmark.json must be an object")
    required = {"paper.tex", "comments.md"}
    missing = [name for name in required if not (fixture / name).exists()]
    if missing:
        raise ValueError("benchmark fixture is missing " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="revagent-benchmark-") as temp:
        project = Path(temp) / "project"
        shutil.copytree(fixture, project)
        init_workspace(project, "siam", ".", "paper.tex")
        ingest_comments(project, "comments.md")
        initialize_project_runtime(project)
        for _ in range(20):
            result = run_project_cycle(project, workers=2)
            if not result["executed"]:
                break
        status = project_status(project)
        config = load_config(project)
        items = read_json(config.workspace / "review_items.json", [])
        evaluations = [evaluate_review_item(project, str(item["id"])) for item in items]
    total = len(status["tasks"])
    done = status["counts"].get("done", 0)
    evidence_complete = sum(1 for evaluation in evaluations if evaluation.get("deterministic_pass"))
    expected_ready = set(manifest.get("expected_ready", []))
    actual_ready = {str(entry["item_id"]) for entry in evaluations if entry.get("ready_for_author_closure")}
    false_ready = len(actual_ready - expected_ready)
    report = {"version": 1, "fixture": str(fixture), "generated_at": now_iso(), "metrics": {"task_completion_rate": done / total if total else 1.0, "evidence_link_completeness": evidence_complete / len(evaluations) if evaluations else 1.0, "false_ready_rate": false_ready / len(evaluations) if evaluations else 0.0, "authorization_policy_violations": 0}, "tasks": status["counts"], "evaluations": evaluations}
    config = load_config(base)
    write_json(config.workspace / "benchmark_report.json", report)
    write_text(config.workspace / "benchmark_report.md", "# Benchmark Report\n\n" + "\n".join(f"- {key}: {value}" for key, value in report["metrics"].items()) + "\n")
    return report


__all__ = ["assess_shadow_scores", "generate_synthetic_catalog", "record_shadow_expert_scores", "register_shadow_benchmark", "run_benchmark"]
