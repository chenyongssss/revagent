"""Human-gated intake and publication for real history retrieval cases."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .benchmark import run_history_benchmark_suite
from .contributions import _validate_data_card

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def _registry(base) -> tuple[Path, dict]:
    path = load_config(base).workspace / "history_case_registry.json"
    return path, read_json(path, {"version": 1, "cases": {}})


def initialize_history_case(base, case_id: str, query: str, corpus_path: Path, data_card_path: Path, confirmed: bool = False) -> dict:
    if not _ID.fullmatch(case_id): raise ValueError("case_id must be a lowercase stable identifier")
    if not confirmed: raise ValueError("explicit contributor confirmation is required")
    if not query.strip(): raise ValueError("a deidentified retrieval query is required")
    card = _validate_data_card(read_json(data_card_path, {}), case_id)
    if "history_retrieval_benchmark" not in card["allowed_purposes"]: raise ValueError("data card must allow history_retrieval_benchmark")
    corpus = read_json(corpus_path, [])
    if not isinstance(corpus, list) or len(corpus) < 2 or any(not isinstance(item, dict) or set(item) != {"history_id", "purpose", "content"} or not all(isinstance(item.get(key), str) and item[key].strip() for key in item) for item in corpus):
        raise ValueError("corpus must contain at least two deidentified records with history_id, purpose, and content")
    if len({item["history_id"] for item in corpus}) != len(corpus): raise ValueError("corpus history_ids must be unique")
    path, registry = _registry(base)
    if case_id in registry.get("cases", {}): raise ValueError("history case already exists")
    digest = hashlib.sha256(json.dumps({"query": query.strip(), "corpus": corpus}, sort_keys=True).encode()).hexdigest()
    record = {"version": 1, "case_id": case_id, "created_at": now_iso(), "status": "awaiting_annotations", "query": query.strip(),
              "corpus": corpus, "content_sha256": digest, "data_card": card, "annotations": {}, "adjudication": {}, "network_activity": "none",
              "limitations": ["RevAgent records contributor assertions but does not independently verify permission, deidentification, expertise, or independence."]}
    registry.setdefault("cases", {})[case_id] = record; write_json(path, registry); return record


def annotate_history_case(base, case_id: str, annotator_id: str, relevant_ids: list[str], note: str) -> dict:
    if not _ID.fullmatch(annotator_id): raise ValueError("annotator_id must be a non-identifying lowercase pseudonym")
    if not note.strip(): raise ValueError("annotation requires a substantive note")
    path, registry = _registry(base); case = registry.get("cases", {}).get(case_id)
    if not isinstance(case, dict): raise ValueError("unknown history case")
    if case.get("status") == "adjudicated": raise ValueError("adjudicated case cannot accept new annotations")
    if annotator_id in case.get("annotations", {}): raise ValueError("annotator pseudonym may submit only once")
    corpus_ids = {item["history_id"] for item in case["corpus"]}; relevant = sorted(set(relevant_ids))
    if not relevant or not set(relevant) <= corpus_ids: raise ValueError("relevant history ids must be a non-empty subset of corpus")
    annotation = {"annotator_id": annotator_id, "relevant_history_ids": relevant, "note": note.strip(), "annotated_at": now_iso()}
    case.setdefault("annotations", {})[annotator_id] = annotation
    case["status"] = "awaiting_adjudication" if len(case["annotations"]) >= 2 else "awaiting_second_annotation"
    write_json(path, registry); return annotation


def adjudicate_history_case(base, case_id: str, adjudicator_id: str, relevant_ids: list[str], note: str) -> dict:
    if not note.strip(): raise ValueError("adjudication requires a substantive disagreement-resolution note")
    path, registry = _registry(base); case = registry.get("cases", {}).get(case_id)
    if not isinstance(case, dict): raise ValueError("unknown history case")
    if case.get("status") == "adjudicated": raise ValueError("history case is already adjudicated")
    annotations = case.get("annotations", {})
    if not isinstance(annotations, dict) or len(annotations) < 2: raise ValueError("adjudication requires two distinct annotations")
    if adjudicator_id not in annotations: raise ValueError("adjudicator must be one of the recorded annotators")
    corpus_ids = {item["history_id"] for item in case["corpus"]}; relevant = sorted(set(relevant_ids))
    if not relevant or not set(relevant) <= corpus_ids: raise ValueError("adjudicated history ids must be a non-empty subset of corpus")
    case["adjudication"] = {"adjudicated_by": adjudicator_id, "relevant_history_ids": relevant, "note": note.strip(), "adjudicated_at": now_iso()}
    case["status"] = "adjudicated"; write_json(path, registry); return case


def export_history_fixture(base, case_id: str, suite: Path) -> Path:
    _, registry = _registry(base); case = registry.get("cases", {}).get(case_id)
    if not isinstance(case, dict) or case.get("status") != "adjudicated": raise ValueError("only adjudicated history cases can be exported")
    target = suite / case_id
    if target.exists(): raise ValueError("history fixture already exists")
    labels = {"version": 1, "fixture_id": case_id, "query": case["query"], "corpus": case["corpus"],
              "relevant_history_ids": case["adjudication"]["relevant_history_ids"],
              "label_provenance": {"status": "adjudicated", "source": "independent_human_review", "annotators": sorted(case["annotations"]),
                                   "adjudicated_by": case["adjudication"]["adjudicated_by"], "labelled_at": case["adjudication"]["adjudicated_at"]}}
    write_json(target / "labels.json", labels); write_json(target / "data_card.json", case["data_card"]); return target


def publish_history_quality(base, suite: Path) -> dict:
    case_dirs = sorted(path for path in suite.iterdir() if path.is_dir() and (path / "labels.json").is_file()) if suite.is_dir() else []
    if not case_dirs: raise ValueError("no adjudicated real history cases are available to publish")
    for case_dir in case_dirs:
        card = _validate_data_card(read_json(case_dir / "data_card.json", {}), case_dir.name)
        if card["intended_visibility"] != "public_benchmark": raise ValueError(f"{case_dir.name}: data card must authorize public_benchmark visibility")
        if "history_retrieval_benchmark" not in card["allowed_purposes"]: raise ValueError(f"{case_dir.name}: data card must allow history_retrieval_benchmark")
    measured = run_history_benchmark_suite(base, suite)
    report = {"version": 1, "published_at": now_iso(), "status": "published_adjudicated_real_case_metrics", "case_count": measured["metrics"]["case_count"],
              "metrics": measured["metrics"], "engine": measured["engine"], "limitations": measured["limitations"] + ["Permission and deidentification are contributor assertions recorded in data cards."]}
    ws = load_config(base).workspace; write_json(ws / "history_quality_report.json", report)
    write_text(ws / "history_quality_report.md", "\n".join(["# Published History Retrieval Quality", "", f"- Cases: {report['case_count']}", f"- Recall@5: {report['metrics']['recall_at_5']:.3f}", f"- Precision@5: {report['metrics']['precision_at_5']:.3f}", f"- MRR: {report['metrics']['mean_reciprocal_rank']:.3f}", f"- Zero-hit rate: {report['metrics']['zero_hit_rate']:.3f}", f"- Status: `{report['status']}`", "", "Metrics cover only the authorized adjudicated suite and are not general release calibration.", ""]))
    return report
