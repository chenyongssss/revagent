"""Deterministic benchmark runner for review-project agent regression metrics."""

from __future__ import annotations

import json
import hashlib
import difflib
import re
import shutil
import tempfile
import itertools
import sqlite3
from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .project_runtime import evaluate_review_item, initialize_project_runtime, project_status, run_project_cycle
from .pre_submission_engine import REVIEW_REPORT_VERSION, ROLES, run_role_review
from .reviews import ingest_comments
from .reviewer_packs import available_reviewer_packs
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
REVIEW_BENCHMARK_VERSION = 1
ALIGNMENT_BENCHMARK_VERSION = 1
HISTORY_BENCHMARK_VERSION = 1

def _validated_history_labels(case_dir: Path) -> dict[str, object]:
    labels = read_json(case_dir / "labels.json", {})
    required = {"version", "fixture_id", "query", "corpus", "relevant_history_ids", "label_provenance"}
    if not isinstance(labels, dict) or set(labels) != required or labels.get("version") != HISTORY_BENCHMARK_VERSION:
        raise ValueError(f"{case_dir.name}: labels.json must contain exactly the history retrieval benchmark v1 fields")
    if not isinstance(labels["fixture_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", labels["fixture_id"]):
        raise ValueError(f"{case_dir.name}: fixture_id must be a lowercase stable identifier")
    if not isinstance(labels["query"], str) or not labels["query"].strip():
        raise ValueError(f"{case_dir.name}: query is required")
    corpus = labels["corpus"]
    if not isinstance(corpus, list) or not corpus or any(not isinstance(item, dict) or set(item) != {"history_id", "purpose", "content"} or not all(isinstance(item[key], str) and item[key].strip() for key in item) for item in corpus):
        raise ValueError(f"{case_dir.name}: corpus requires non-empty history_id, purpose, and content")
    ids = [item["history_id"] for item in corpus]
    if len(set(ids)) != len(ids): raise ValueError(f"{case_dir.name}: corpus history_ids must be unique")
    relevant = labels["relevant_history_ids"]
    if not isinstance(relevant, list) or not relevant or not all(isinstance(value, str) and value for value in relevant) or not set(relevant) <= set(ids):
        raise ValueError(f"{case_dir.name}: relevant_history_ids must be a non-empty subset of corpus")
    provenance = labels["label_provenance"]
    annotators = provenance.get("annotators", []) if isinstance(provenance, dict) else []
    if not isinstance(provenance, dict) or provenance.get("status") != "adjudicated" or provenance.get("source") != "independent_human_review":
        raise ValueError(f"{case_dir.name}: labels require adjudicated independent human review")
    if not isinstance(annotators, list) or not all(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) for value in annotators) or len(set(annotators)) < 2:
        raise ValueError(f"{case_dir.name}: labels require at least two distinct pseudonymous annotators")
    if provenance.get("adjudicated_by") not in annotators or not provenance.get("labelled_at"):
        raise ValueError(f"{case_dir.name}: labels require a recorded adjudicator and date")
    return labels

def _rank_history_fixture(query: str, corpus: list[dict[str, str]], limit: int = 5) -> list[str]:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE history_fts USING fts5(history_id UNINDEXED, purpose, content)")
        con.executemany("INSERT INTO history_fts VALUES (?, ?, ?)", [(item["history_id"], item["purpose"], item["content"]) for item in corpus])
        return [row[0] for row in con.execute("SELECT history_id FROM history_fts WHERE history_fts MATCH ? ORDER BY bm25(history_fts),history_id LIMIT ?", (query, limit))]
    except sqlite3.OperationalError as exc:
        raise ValueError(f"invalid history benchmark query: {exc}") from exc
    finally: con.close()

def run_history_benchmark_suite(base: Path, suite: Path) -> dict[str, object]:
    """Measure the production FTS retrieval strategy against adjudicated labels."""
    if not suite.is_dir(): raise ValueError("history retrieval benchmark suite must be a directory")
    case_dirs = sorted(path for path in suite.iterdir() if path.is_dir() and (path / "labels.json").is_file())
    if not case_dirs: raise ValueError("history retrieval benchmark suite contains no labelled cases")
    cases, fixture_ids = [], set()
    for case_dir in case_dirs:
        labels = _validated_history_labels(case_dir); fixture_id = labels["fixture_id"]
        if fixture_id in fixture_ids: raise ValueError(f"duplicate history retrieval benchmark fixture_id {fixture_id}")
        fixture_ids.add(fixture_id); retrieved = _rank_history_fixture(labels["query"], labels["corpus"])
        relevant = set(labels["relevant_history_ids"]); hits = [value for value in retrieved if value in relevant]
        first_rank = next((index for index, value in enumerate(retrieved, 1) if value in relevant), 0)
        cases.append({"fixture_id": fixture_id, "retrieved_history_ids": retrieved, "relevant_history_ids": sorted(relevant),
                      "recall_at_5": len(hits) / len(relevant), "precision_at_5": len(hits) / 5,
                      "reciprocal_rank": 1 / first_rank if first_rank else 0.0, "label_provenance": labels["label_provenance"],
                      "labels_sha256": _file_fingerprint(case_dir / "labels.json")["sha256"]})
    count = len(cases); metrics = {"case_count": count, "recall_at_5": sum(x["recall_at_5"] for x in cases) / count,
        "precision_at_5": sum(x["precision_at_5"] for x in cases) / count, "mean_reciprocal_rank": sum(x["reciprocal_rank"] for x in cases) / count,
        "zero_hit_rate": sum(x["reciprocal_rank"] == 0 for x in cases) / count}
    report = {"version": 1, "generated_at": now_iso(), "suite": str(suite), "engine": {"kind": "sqlite-fts5-bm25", "model": "none"},
              "metrics": metrics, "cases": cases, "status": "adjudicated_labels_measured_not_release_calibrated",
              "limitations": ["Fixture text must already be deidentified and authorized for evaluation.", "Pseudonymous records do not prove annotator expertise or independence.", "Retrieval metrics do not establish semantic equivalence."]}
    ws = load_config(base).workspace; write_json(ws / "history_benchmark_report.json", report)
    write_text(ws / "history_benchmark_report.md", "\n".join(["# History Retrieval Benchmark", "", f"- Cases: {count}", f"- Recall@5: {metrics['recall_at_5']:.3f}", f"- Precision@5: {metrics['precision_at_5']:.3f}", f"- MRR: {metrics['mean_reciprocal_rank']:.3f}", f"- Zero-hit rate: {metrics['zero_hit_rate']:.3f}", f"- Status: `{report['status']}`", "", "Results require human interpretation and are not release calibration.", ""]))
    return report

def _validated_alignment_labels(case_dir: Path) -> dict[str, object]:
    labels = read_json(case_dir / "labels.json", {})
    required = {"version", "fixture_id", "claim_excerpt", "candidates", "relevant_work_ids", "label_provenance"}
    if not isinstance(labels, dict) or set(labels) != required or labels.get("version") != ALIGNMENT_BENCHMARK_VERSION:
        raise ValueError(f"{case_dir.name}: labels.json must contain exactly the alignment benchmark v1 fields")
    if not isinstance(labels["fixture_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", labels["fixture_id"]):
        raise ValueError(f"{case_dir.name}: fixture_id must be a lowercase stable identifier")
    if not isinstance(labels["claim_excerpt"], str) or not labels["claim_excerpt"].strip():
        raise ValueError(f"{case_dir.name}: claim_excerpt is required")
    candidates = labels["candidates"]
    if not isinstance(candidates, list) or not candidates or any(not isinstance(item, dict) or set(item) != {"work_id", "title"} or not isinstance(item["work_id"], str) or not isinstance(item["title"], str) or not item["work_id"].strip() or not item["title"].strip() for item in candidates):
        raise ValueError(f"{case_dir.name}: candidates require non-empty work_id and title")
    if len({item["work_id"] for item in candidates}) != len(candidates):
        raise ValueError(f"{case_dir.name}: candidate work_ids must be unique")
    relevant = labels["relevant_work_ids"]
    if not isinstance(relevant, list) or not relevant or not all(isinstance(value, str) and value for value in relevant) or not set(relevant) <= {item["work_id"] for item in candidates}:
        raise ValueError(f"{case_dir.name}: relevant_work_ids must be a non-empty subset of candidates")
    provenance = labels["label_provenance"]
    annotators = provenance.get("annotators", []) if isinstance(provenance, dict) else []
    if not isinstance(provenance, dict) or provenance.get("status") != "adjudicated" or provenance.get("source") != "independent_human_review":
        raise ValueError(f"{case_dir.name}: labels require adjudicated independent human review")
    if not isinstance(annotators, list) or not all(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) for value in annotators) or len(set(annotators)) < 2:
        raise ValueError(f"{case_dir.name}: labels require at least two distinct pseudonymous annotators")
    if provenance.get("adjudicated_by") not in annotators or not provenance.get("labelled_at"):
        raise ValueError(f"{case_dir.name}: labels require a recorded adjudicator and date")
    return labels

def run_alignment_benchmark_suite(base: Path, suite: Path) -> dict[str, object]:
    """Measure deterministic claim-title retrieval against adjudicated labels."""
    from .literature import rank_literature_alignment_records
    if not suite.is_dir(): raise ValueError("alignment benchmark suite must be a directory")
    case_dirs = sorted(path for path in suite.iterdir() if path.is_dir() and (path / "labels.json").is_file())
    if not case_dirs: raise ValueError("alignment benchmark suite contains no labelled cases")
    cases, fixture_ids = [], set()
    for case_dir in case_dirs:
        labels = _validated_alignment_labels(case_dir)
        fixture_id = labels["fixture_id"]
        if fixture_id in fixture_ids: raise ValueError(f"duplicate alignment benchmark fixture_id {fixture_id}")
        fixture_ids.add(fixture_id)
        ranked = rank_literature_alignment_records(labels["claim_excerpt"], labels["candidates"], 5)
        retrieved = [item["work_id"] for item in ranked]
        relevant = set(labels["relevant_work_ids"])
        hits = [work_id for work_id in retrieved if work_id in relevant]
        first_rank = next((index for index, work_id in enumerate(retrieved, 1) if work_id in relevant), 0)
        cases.append({"fixture_id": fixture_id, "retrieved_work_ids": retrieved, "relevant_work_ids": sorted(relevant),
                      "recall_at_5": len(hits) / len(relevant), "precision_at_5": len(hits) / 5,
                      "reciprocal_rank": 1 / first_rank if first_rank else 0.0, "label_provenance": labels["label_provenance"],
                      "labels_sha256": _file_fingerprint(case_dir / "labels.json")["sha256"]})
    count = len(cases)
    metrics = {"case_count": count, "recall_at_5": sum(item["recall_at_5"] for item in cases) / count,
               "precision_at_5": sum(item["precision_at_5"] for item in cases) / count,
               "mean_reciprocal_rank": sum(item["reciprocal_rank"] for item in cases) / count,
               "zero_hit_rate": sum(item["reciprocal_rank"] == 0 for item in cases) / count}
    report = {"version": 1, "generated_at": now_iso(), "suite": str(suite), "engine": {"kind": "deterministic-lexical-title-overlap", "model": "none"},
              "metrics": metrics, "cases": cases, "status": "adjudicated_labels_measured_not_release_calibrated",
              "limitations": ["Pseudonymous records do not prove annotator expertise or independence.", "Retrieval metrics do not establish semantic alignment or novelty."]}
    ws = load_config(base).workspace
    write_json(ws / "alignment_benchmark_report.json", report)
    write_text(ws / "alignment_benchmark_report.md", "\n".join(["# Claim Alignment Benchmark", "", f"- Cases: {count}",
               f"- Recall@5: {metrics['recall_at_5']:.3f}", f"- Precision@5: {metrics['precision_at_5']:.3f}",
               f"- MRR: {metrics['mean_reciprocal_rank']:.3f}", f"- Zero-hit rate: {metrics['zero_hit_rate']:.3f}",
               f"- Status: `{report['status']}`", "", "Results require human interpretation and are not novelty calibration.", ""]))
    return report


def _validated_review_labels(case_dir: Path) -> dict[str, object]:
    labels = read_json(case_dir / "labels.json", {})
    if not isinstance(labels, dict) or labels.get("version") != REVIEW_BENCHMARK_VERSION:
        raise ValueError(f"{case_dir.name}: labels.json must use review benchmark version {REVIEW_BENCHMARK_VERSION}")
    required = {"fixture_id", "pack", "expected_findings", "must_not_pass", "label_provenance"}
    if not required <= set(labels):
        raise ValueError(f"{case_dir.name}: labels.json is missing required review benchmark fields")
    if not isinstance(labels["fixture_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", labels["fixture_id"]):
        raise ValueError(f"{case_dir.name}: fixture_id must be a lowercase stable identifier")
    if labels["pack"] not in available_reviewer_packs():
        raise ValueError(f"{case_dir.name}: unknown reviewer pack")
    provenance = labels["label_provenance"]
    if not isinstance(provenance, dict) or provenance.get("status") != "adjudicated":
        raise ValueError(f"{case_dir.name}: labels require adjudicated human review")
    annotators = provenance.get("annotators")
    if not isinstance(annotators, list) or not all(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) for value in annotators) or len(set(annotators)) < 2:
        raise ValueError(f"{case_dir.name}: labels require at least two distinct pseudonymous annotators")
    if provenance.get("source") == "model_self_score":
        raise ValueError(f"{case_dir.name}: model self-scores cannot be benchmark labels")
    if provenance.get("source") != "independent_human_review":
        raise ValueError(f"{case_dir.name}: labels must declare independent_human_review provenance")
    if provenance.get("adjudicated_by") not in annotators or not provenance.get("labelled_at"):
        raise ValueError(f"{case_dir.name}: labels require a recorded adjudicator and date")
    findings = labels["expected_findings"]
    if not isinstance(findings, list):
        raise ValueError(f"{case_dir.name}: expected_findings must be a list")
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {"role", "category", "high_risk"} or finding.get("role") not in ROLES or not isinstance(finding.get("category"), str) or not isinstance(finding.get("high_risk"), bool):
            raise ValueError(f"{case_dir.name}: each expected finding requires role, category, and high_risk")
    if not isinstance(labels["must_not_pass"], bool):
        raise ValueError(f"{case_dir.name}: must_not_pass must be boolean")
    return labels


def _review_metrics(cases: list[dict[str, object]]) -> dict[str, object]:
    expected = [finding for case in cases for finding in case["expected_findings"]]
    detected = [finding for case in cases for finding in case["detected_findings"]]
    expected_keys = {(item["fixture_id"], item["role"], item["category"]) for item in expected}
    detected_keys = {(item["fixture_id"], item["role"], item["category"]) for item in detected}
    high_risk_keys = {(item["fixture_id"], item["role"], item["category"]) for item in expected if item["high_risk"]}
    detected_high_risk_keys = {(item["fixture_id"], item["role"], item["category"]) for item in detected if item.get("severity") in {"high", "critical"}}
    blocked_cases = [case for case in cases if case["must_not_pass"]]
    false_passes = [case for case in blocked_cases if not case["predicted_blocking"]]
    return {
        "case_count": len(cases),
        "expected_defects": len(expected_keys),
        "detected_defects": len(expected_keys & detected_keys),
        "defect_detection_recall": len(expected_keys & detected_keys) / len(expected_keys) if expected_keys else 1.0,
        "high_risk_recall": len(high_risk_keys & detected_high_risk_keys) / len(high_risk_keys) if high_risk_keys else 1.0,
        "false_pass_rate": len(false_passes) / len(blocked_cases) if blocked_cases else 0.0,
    }


def run_review_benchmark_suite(base: Path, suite: Path) -> dict[str, object]:
    """Evaluate deterministic reviewer roles against adjudicated local labels."""
    if not suite.is_dir():
        raise ValueError("review benchmark suite must be a directory")
    case_dirs = sorted(path for path in suite.iterdir() if path.is_dir() and (path / "labels.json").exists())
    if not case_dirs:
        raise ValueError("review benchmark suite contains no labelled cases")
    cases: list[dict[str, object]] = []
    fixture_ids: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="revagent-review-benchmark-") as temp:
        for number, case_dir in enumerate(case_dirs, 1):
            labels = _validated_review_labels(case_dir)
            fixture_id = str(labels["fixture_id"])
            if fixture_id in fixture_ids:
                raise ValueError(f"duplicate review benchmark fixture_id {fixture_id}")
            fixture_ids.add(fixture_id)
            if not (case_dir / "paper.tex").is_file():
                raise ValueError(f"{case_dir.name}: paper.tex is required")
            project = Path(temp) / f"case-{number:03d}"
            shutil.copytree(case_dir, project)
            init_workspace(project, "siam", ".", "paper.tex")
            reports = [run_role_review(project, role, str(labels["pack"])) for role in ROLES]
            detected = [
                {"fixture_id": labels["fixture_id"], "role": report["role"], "category": issue["category"], "severity": issue["severity"]}
                for report in reports for issue in report["issues"]
            ]
            expected = [{"fixture_id": labels["fixture_id"], **finding} for finding in labels["expected_findings"]]
            cases.append({
                "fixture_id": labels["fixture_id"], "pack": labels["pack"], "expected_findings": expected,
                "detected_findings": detected, "must_not_pass": labels["must_not_pass"],
                "predicted_blocking": any(item["severity"] in {"high", "critical"} for item in detected),
                "label_provenance": labels["label_provenance"],
                "input_hashes": {"paper": _file_fingerprint(case_dir / "paper.tex")["sha256"], "labels": _file_fingerprint(case_dir / "labels.json")["sha256"]},
                "pack_version": reports[0]["reviewer_pack"]["version"],
            })
    per_pack = {pack: _review_metrics([case for case in cases if case["pack"] == pack]) for pack in sorted({str(case["pack"]) for case in cases})}
    per_role = {}
    for role in ROLES:
        role_cases = []
        for case in cases:
            role_detected = [item for item in case["detected_findings"] if item["role"] == role]
            role_expected = [item for item in case["expected_findings"] if item["role"] == role]
            role_cases.append({
                **case,
                "expected_findings": role_expected,
                "detected_findings": role_detected,
                "must_not_pass": any(item["high_risk"] for item in role_expected),
                "predicted_blocking": any(item["severity"] in {"high", "critical"} for item in role_detected),
            })
        per_role[role] = _review_metrics(role_cases)
    report = {
        "version": REVIEW_BENCHMARK_VERSION, "generated_at": now_iso(), "suite": str(suite),
        "engine": {"kind": "deterministic-structural", "review_report_version": REVIEW_REPORT_VERSION, "model": "none"},
        "metrics": _review_metrics(cases), "per_pack": per_pack, "per_role": per_role, "cases": cases,
        "status": "adjudicated_labels_measured_not_release_calibrated",
        "limitations": ["Pseudonymous label records do not independently prove annotator expertise or independence.", "These deterministic metrics are not model self-scores and do not establish journal or expert performance."],
    }
    config = load_config(base)
    write_json(config.workspace / "review_benchmark_report.json", report)
    lines = ["# Reviewer Pack Benchmark", "", f"- Cases: {report['metrics']['case_count']}", f"- Defect detection recall: {report['metrics']['defect_detection_recall']:.3f}", f"- High-risk recall: {report['metrics']['high_risk_recall']:.3f}", f"- False-pass rate: {report['metrics']['false_pass_rate']:.3f}", f"- Status: `{report['status']}`", "", "Results require human interpretation and are not release calibration.\n"]
    write_text(config.workspace / "review_benchmark_report.md", "\n".join(lines))
    return report


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


__all__ = ["assess_shadow_scores", "generate_synthetic_catalog", "record_shadow_expert_scores", "register_shadow_benchmark", "run_benchmark", "run_review_benchmark_suite"]
