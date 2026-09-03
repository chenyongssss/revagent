"""Local, human-gated intake for real claim-alignment benchmark cases."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ._utils import load_config, now_iso, read_json, write_json
from .contributions import _validate_data_card

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def _registry(base) -> tuple[Path, dict]:
    path = load_config(base).workspace / "alignment_case_registry.json"
    return path, read_json(path, {"version": 1, "cases": {}})


def initialize_alignment_case(base, case_id: str, claim_excerpt: str, candidates_path: Path, data_card_path: Path, confirmed: bool = False) -> dict:
    if not _ID.fullmatch(case_id):
        raise ValueError("case_id must be a lowercase stable identifier")
    if not confirmed:
        raise ValueError("explicit contributor confirmation is required")
    if not claim_excerpt.strip():
        raise ValueError("a deidentified claim excerpt is required")
    card = _validate_data_card(read_json(data_card_path, {}), case_id)
    if "claim_alignment_benchmark" not in card["allowed_purposes"]:
        raise ValueError("data card must allow claim_alignment_benchmark")
    candidates = read_json(candidates_path, [])
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("candidates file must contain at least two works")
    if any(not isinstance(item, dict) or set(item) != {"work_id", "title"} or not all(isinstance(item.get(key), str) and item[key].strip() for key in ("work_id", "title")) for item in candidates):
        raise ValueError("each candidate requires exactly work_id and title")
    if len({item["work_id"] for item in candidates}) != len(candidates):
        raise ValueError("candidate work_ids must be unique")
    path, registry = _registry(base)
    if case_id in registry.get("cases", {}):
        raise ValueError("alignment case already exists")
    content_hash = hashlib.sha256(json.dumps({"claim_excerpt": claim_excerpt.strip(), "candidates": candidates}, sort_keys=True).encode()).hexdigest()
    record = {"version": 1, "case_id": case_id, "created_at": now_iso(), "status": "awaiting_annotations",
              "claim_excerpt": claim_excerpt.strip(), "candidates": candidates, "content_sha256": content_hash,
              "data_card": card, "annotations": {}, "adjudication": {}, "network_activity": "none",
              "limitations": ["RevAgent records contributor assertions but does not verify permission, deidentification, expertise, or independence."]}
    registry.setdefault("cases", {})[case_id] = record
    write_json(path, registry)
    return record


def annotate_alignment_case(base, case_id: str, annotator_id: str, relevant_work_ids: list[str], note: str) -> dict:
    if not _ID.fullmatch(annotator_id):
        raise ValueError("annotator_id must be a non-identifying lowercase pseudonym")
    if not note.strip():
        raise ValueError("annotation requires a substantive note")
    path, registry = _registry(base)
    case = registry.get("cases", {}).get(case_id)
    if not isinstance(case, dict): raise ValueError("unknown alignment case")
    if case.get("status") == "adjudicated": raise ValueError("adjudicated case cannot accept new annotations")
    if annotator_id in case.get("annotations", {}): raise ValueError("annotator pseudonym may submit only once")
    candidate_ids = {item["work_id"] for item in case.get("candidates", [])}
    relevant = sorted(set(relevant_work_ids))
    if not relevant or not set(relevant) <= candidate_ids:
        raise ValueError("relevant work ids must be a non-empty subset of candidates")
    annotation = {"annotator_id": annotator_id, "relevant_work_ids": relevant, "note": note.strip(), "annotated_at": now_iso()}
    case.setdefault("annotations", {})[annotator_id] = annotation
    case["status"] = "awaiting_adjudication" if len(case["annotations"]) >= 2 else "awaiting_second_annotation"
    write_json(path, registry)
    return annotation


def adjudicate_alignment_case(base, case_id: str, adjudicator_id: str, relevant_work_ids: list[str], note: str) -> dict:
    if not note.strip(): raise ValueError("adjudication requires a substantive disagreement-resolution note")
    path, registry = _registry(base)
    case = registry.get("cases", {}).get(case_id)
    if not isinstance(case, dict): raise ValueError("unknown alignment case")
    if case.get("status") == "adjudicated": raise ValueError("alignment case is already adjudicated")
    annotations = case.get("annotations", {})
    if not isinstance(annotations, dict) or len(annotations) < 2:
        raise ValueError("adjudication requires two distinct annotations")
    if adjudicator_id not in annotations:
        raise ValueError("adjudicator must be one of the recorded annotators")
    candidate_ids = {item["work_id"] for item in case.get("candidates", [])}
    relevant = sorted(set(relevant_work_ids))
    if not relevant or not set(relevant) <= candidate_ids:
        raise ValueError("adjudicated work ids must be a non-empty subset of candidates")
    case["adjudication"] = {"adjudicated_by": adjudicator_id, "relevant_work_ids": relevant, "note": note.strip(), "adjudicated_at": now_iso()}
    case["status"] = "adjudicated"
    write_json(path, registry)
    return case


def export_alignment_fixture(base, case_id: str, suite: Path) -> Path:
    _, registry = _registry(base)
    case = registry.get("cases", {}).get(case_id)
    if not isinstance(case, dict) or case.get("status") != "adjudicated":
        raise ValueError("only adjudicated alignment cases can be exported")
    target = suite / case_id
    if target.exists(): raise ValueError("alignment fixture already exists")
    annotators = sorted(case["annotations"])
    labels = {"version": 1, "fixture_id": case_id, "claim_excerpt": case["claim_excerpt"], "candidates": case["candidates"],
              "relevant_work_ids": case["adjudication"]["relevant_work_ids"],
              "label_provenance": {"status": "adjudicated", "source": "independent_human_review", "annotators": annotators,
                                   "adjudicated_by": case["adjudication"]["adjudicated_by"], "labelled_at": case["adjudication"]["adjudicated_at"]}}
    write_json(target / "labels.json", labels)
    return target
