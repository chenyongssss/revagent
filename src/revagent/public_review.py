"""Governed silver benchmarks built from licensed public peer-review records."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from ._utils import load_config, now_iso, read_json, write_json, write_text
from .reviewer_packs import available_reviewer_packs

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_PROVIDERS = {"openreview", "f1000research", "elife", "peerj"}
_LICENSES = {"CC-BY-4.0", "CC-BY-3.0", "CC0-1.0"}
_ROLES = {"text-reviewer", "theory-reviewer", "experiment-reviewer"}
_DOMAIN_TERMS = {
    "computational-math": ("numerical", "optimization", "finite element", "differential equation", "scientific computing", "inverse problem", "solver", "simulation"),
    "numerical-pde": ("pde", "partial differential", "finite element", "finite volume", "spectral method", "discretization"),
    "optimization": ("optimization", "optimisation", "convex", "gradient", "proximal", "variational"),
    "scientific-ml": ("scientific machine learning", "physics-informed", "neural operator", "operator learning", "surrogate model"),
}
_LICENSE_ALIASES = {"CC BY 4.0": "CC-BY-4.0", "CC BY 3.0": "CC-BY-3.0", "CC0 1.0": "CC0-1.0"}


def _workspace(base: Path) -> Path:
    """Allow corpus collection at a repository root as well as in a manuscript workspace."""
    revision = base / ".revagent" / "revision.yaml"
    workspace = load_config(base).workspace if revision.is_file() else base / ".revagent"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _value(value: object) -> object:
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def _license(value: object) -> str:
    raw = str(_value(value)).strip()
    return _LICENSE_ALIASES.get(raw, raw)


def _public(note: dict) -> bool:
    readers = note.get("readers", [])
    return isinstance(readers, list) and "everyone" in {str(item).lower() for item in readers}


def _api_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "revagent-public-review/0.1"})
    with urlopen(request, timeout=30) as response:  # nosec: URL is restricted by the caller
        return json.loads(response.read().decode("utf-8"))


def _notes(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("notes"), list):
        raise ValueError("OpenReview response must contain a notes list")
    return [item for item in payload["notes"] if isinstance(item, dict)]


def fetch_openreview_batch(base: Path, venue_id: str, domain: str = "computational-math", limit: int = 10,
                           confirmed: bool = False, fixture_path: Path | None = None,
                           api_base: str = "https://api2.openreview.net") -> dict:
    """Fetch, filter, normalize, and register a bounded batch of public OpenReview records."""
    if not confirmed:
        raise ValueError("explicit confirmation of public access and licensing is required")
    if domain not in _DOMAIN_TERMS:
        raise ValueError(f"domain must be one of: {', '.join(sorted(_DOMAIN_TERMS))}")
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if not venue_id.strip():
        raise ValueError("venue_id is required")
    if fixture_path:
        frozen = read_json(fixture_path, {})
        submissions = _notes(frozen.get("submissions")) if isinstance(frozen, dict) else []
        replies_by_forum = frozen.get("replies_by_forum", {}) if isinstance(frozen, dict) else {}
        if not isinstance(replies_by_forum, dict):
            raise ValueError("fixture replies_by_forum must be an object")
        source = str(fixture_path.resolve())
    else:
        parsed = urlparse(api_base)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("OpenReview API base must be HTTPS")
        query = urlencode({"content.venueid": venue_id, "limit": limit})
        submissions = _notes(_api_json(f"{api_base.rstrip('/')}/notes?{query}"))
        replies_by_forum = {}
        source = f"{api_base.rstrip('/')}/notes?{query}"
    terms = _DOMAIN_TERMS[domain]
    output_dir = _workspace(base) / "public_review_records"
    output_dir.mkdir(parents=True, exist_ok=True)
    imported, excluded = [], []
    for note in submissions[:limit]:
        record_id = str(note.get("id", "")).strip()
        content = note.get("content", {})
        title = str(_value(content.get("title", ""))).strip() if isinstance(content, dict) else ""
        abstract = str(_value(content.get("abstract", ""))).strip() if isinstance(content, dict) else ""
        paper_license = _license(content.get("license", "")) if isinstance(content, dict) else ""
        haystack = f"{title} {abstract}".lower()
        if not record_id or not _public(note):
            excluded.append({"record_id": record_id or "unknown", "reason": "submission_not_public"}); continue
        if paper_license not in _LICENSES:
            excluded.append({"record_id": record_id, "reason": "paper_license_not_accepted"}); continue
        if not any(term in haystack for term in terms):
            excluded.append({"record_id": record_id, "reason": "domain_filter"}); continue
        if fixture_path:
            replies = _notes(replies_by_forum.get(record_id, {"notes": []}))
        else:
            replies = _notes(_api_json(f"{api_base.rstrip('/')}/notes?{urlencode({'forum': record_id, 'limit': 100})}"))
        reviews = []
        for reply in replies:
            invitation = str(reply.get("invitation", "")).lower()
            reply_content = reply.get("content", {})
            review_text = _value(reply_content.get("review", "")) if isinstance(reply_content, dict) else ""
            if "review" not in invitation or not _public(reply) or not isinstance(review_text, str) or not review_text.strip():
                continue
            review_id = str(reply.get("id", "")).strip()
            if not review_id:
                continue
            signatures = reply.get("signatures", [])
            attribution = ", ".join(map(str, signatures)) if isinstance(signatures, list) and signatures else "anonymous reviewer"
            reviews.append({"review_id": review_id, "url": f"https://openreview.net/forum?id={record_id}&noteId={review_id}",
                            "attribution": attribution, "text": review_text.strip(), "license": "CC-BY-4.0"})
        if len(reviews) < 2:
            excluded.append({"record_id": record_id, "reason": "fewer_than_two_public_reviews"}); continue
        case_stub = re.sub(r"[^a-z0-9]+", "-", record_id.lower()).strip("-")[:44]
        case_id = f"or-{case_stub}-{hashlib.sha256(record_id.encode('utf-8')).hexdigest()[:8]}"
        record = {"version": 1, "case_id": case_id, "provider": "openreview", "venue": venue_id,
                  "record_id": record_id, "record_url": f"https://openreview.net/forum?id={record_id}",
                  "license": "CC-BY-4.0", "license_url": "https://openreview.net/legal/terms",
                  "retrieved_at": now_iso(), "paper": {"title": title, "text": abstract, "license": paper_license}, "reviews": reviews}
        record_path = output_dir / f"{case_id}.json"
        write_json(record_path, record)
        try:
            initialize_public_review_case(base, case_id, record_path, True)
        except ValueError as exc:
            if "already exists" not in str(exc):
                raise
            excluded.append({"record_id": record_id, "reason": "already_imported"}); continue
        imported.append({"case_id": case_id, "record_id": record_id, "record_path": str(record_path), "review_count": len(reviews)})
    manifest = {"version": 1, "provider": "openreview", "venue_id": venue_id, "domain": domain, "limit": limit,
                "source": source, "retrieved_at": now_iso(), "license_assumption": "public OpenReview reviews are CC-BY-4.0 under OpenReview terms",
                "imported": imported, "excluded": excluded}
    write_json(output_dir / "last_fetch_manifest.json", manifest)
    return manifest


def _registry(base: Path) -> tuple[Path, dict]:
    path = _workspace(base) / "public_review_registry.json"
    return path, read_json(path, {"version": 1, "cases": {}})


def _https(value: object) -> bool:
    return isinstance(value, str) and urlparse(value).scheme == "https" and bool(urlparse(value).netloc)


def _validate_record(record: object, case_id: str) -> dict:
    required = {"version", "case_id", "provider", "venue", "record_id", "record_url", "license", "license_url", "retrieved_at", "paper", "reviews"}
    if not isinstance(record, dict) or set(record) != required:
        raise ValueError("public record must contain exactly the documented fields")
    if record["version"] != 1 or record["case_id"] != case_id or record["provider"] not in _PROVIDERS:
        raise ValueError("public record version, case_id, or provider is invalid")
    if record["license"] not in _LICENSES or not _https(record["license_url"]) or not _https(record["record_url"]):
        raise ValueError("public record requires an accepted license and HTTPS provenance URLs")
    if not all(isinstance(record.get(key), str) and record[key].strip() for key in ("venue", "record_id", "retrieved_at")):
        raise ValueError("public record requires venue, record_id, and retrieved_at")
    paper = record["paper"]
    if not isinstance(paper, dict) or set(paper) != {"title", "text", "license"} or not paper["title"].strip() or not paper["text"].strip():
        raise ValueError("paper requires title, text, and license")
    if paper["license"] not in _LICENSES:
        raise ValueError("paper text cannot be redistributed without an accepted license")
    reviews = record["reviews"]
    if not isinstance(reviews, list) or len(reviews) < 2:
        raise ValueError("at least two public review records are required")
    for review in reviews:
        if not isinstance(review, dict) or set(review) != {"review_id", "url", "attribution", "text", "license"}:
            raise ValueError("each review requires review_id, url, attribution, text, and license")
        if not _https(review["url"]) or review["license"] not in _LICENSES or not all(isinstance(review[key], str) and review[key].strip() for key in ("review_id", "attribution", "text")):
            raise ValueError("review provenance or license is invalid")
    if len({item["review_id"] for item in reviews}) != len(reviews):
        raise ValueError("review_ids must be unique")
    return record


def initialize_public_review_case(base: Path, case_id: str, record_path: Path, confirmed: bool = False) -> dict:
    if not _ID.fullmatch(case_id):
        raise ValueError("case_id must be a lowercase stable identifier")
    if not confirmed:
        raise ValueError("explicit confirmation of public access and licensing is required")
    record = _validate_record(read_json(record_path, {}), case_id)
    path, registry = _registry(base)
    if case_id in registry["cases"]:
        raise ValueError("public review case already exists")
    digest = hashlib.sha256(record_path.read_bytes()).hexdigest()
    case = {"version": 1, "case_id": case_id, "created_at": now_iso(), "status": "awaiting_agent_annotations",
            "record": record, "record_sha256": digest, "annotations": {}, "adjudication": {},
            "evidence_tier": "public_review_silver", "expert_calibrated": False}
    registry["cases"][case_id] = case
    write_json(path, registry)
    return case


def _validate_findings(case: dict, payload: object) -> list[dict]:
    if not isinstance(payload, dict) or set(payload) != {"findings", "method_note"} or not isinstance(payload["method_note"], str) or not payload["method_note"].strip():
        raise ValueError("annotation requires findings and a substantive method_note")
    review_text = {item["review_id"]: item["text"] for item in case["record"]["reviews"]}
    findings = payload["findings"]
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    for item in findings:
        if not isinstance(item, dict) or set(item) != {"finding_id", "role", "category", "high_risk", "review_id", "evidence_excerpt"}:
            raise ValueError("each finding must contain the documented fields")
        if item["role"] not in _ROLES or not isinstance(item["high_risk"], bool) or item["review_id"] not in review_text:
            raise ValueError("finding role, risk, or review_id is invalid")
        if not all(isinstance(item[key], str) and item[key].strip() for key in ("finding_id", "category", "evidence_excerpt")):
            raise ValueError("finding identifiers and evidence must be non-empty")
        if item["evidence_excerpt"] not in review_text[item["review_id"]]:
            raise ValueError("evidence_excerpt must occur verbatim in the cited public review")
    return findings


def annotate_public_review_case(base: Path, case_id: str, actor_id: str, model: str, run_id: str, annotation_path: Path) -> dict:
    if not _ID.fullmatch(actor_id) or not actor_id.startswith("agent-"):
        raise ValueError("actor_id must be a non-human agent-* identifier")
    path, registry = _registry(base); case = registry["cases"].get(case_id)
    if not isinstance(case, dict): raise ValueError("unknown public review case")
    if case["status"] == "agent_adjudicated": raise ValueError("adjudicated case is immutable")
    if actor_id in case["annotations"]: raise ValueError("agent may annotate only once")
    if not model.strip() or not run_id.strip(): raise ValueError("model and run_id are required")
    findings = _validate_findings(case, read_json(annotation_path, {}))
    annotation = {"actor_id": actor_id, "actor_kind": "subagent", "model": model, "run_id": run_id,
                  "input_sha256": case["record_sha256"], "findings": findings, "annotated_at": now_iso()}
    case["annotations"][actor_id] = annotation
    case["status"] = "awaiting_agent_adjudication" if len(case["annotations"]) >= 2 else "awaiting_second_agent_annotation"
    write_json(path, registry); return annotation


def adjudicate_public_review_case(base: Path, case_id: str, actor_id: str, model: str, run_id: str, annotation_path: Path) -> dict:
    path, registry = _registry(base); case = registry["cases"].get(case_id)
    if not isinstance(case, dict): raise ValueError("unknown public review case")
    if len(case["annotations"]) < 2: raise ValueError("two independent agent annotations are required")
    if actor_id in case["annotations"]: raise ValueError("adjudicator must be distinct from annotators")
    findings = _validate_findings(case, read_json(annotation_path, {}))
    case["adjudication"] = {"actor_id": actor_id, "actor_kind": "subagent", "model": model, "run_id": run_id,
                            "findings": findings, "adjudicated_at": now_iso()}
    case["status"] = "agent_adjudicated"; write_json(path, registry); return case


def public_review_quality_report(base: Path) -> dict:
    _, registry = _registry(base)
    cases = [case for case in registry["cases"].values() if case.get("status") == "agent_adjudicated"]
    if not cases: raise ValueError("no agent-adjudicated public review cases are available")
    rows = []
    for case in cases:
        sets = [{(f["role"], f["category"], f["review_id"]) for f in ann["findings"]} for ann in case["annotations"].values()]
        intersection, union = set.intersection(*sets), set.union(*sets)
        final = case["adjudication"]["findings"]
        rows.append({"case_id": case["case_id"], "record_sha256": case["record_sha256"],
                     "agent_agreement_jaccard": len(intersection) / len(union) if union else 1.0,
                     "adjudicated_findings": len(final), "evidence_coverage": sum(bool(f["evidence_excerpt"]) for f in final) / len(final) if final else 1.0})
    adjudicated = [finding for case in cases for finding in case["adjudication"]["findings"]]
    def breakdown(key: str) -> dict:
        values = sorted({str(finding[key]) for finding in adjudicated})
        return {value: {"finding_count": sum(str(finding[key]) == value for finding in adjudicated),
                        "high_risk_count": sum(str(finding[key]) == value and finding["high_risk"] for finding in adjudicated)} for value in values}
    metrics = {"case_count": len(rows), "adjudicated_finding_count": len(adjudicated),
               "mean_agent_agreement_jaccard": sum(r["agent_agreement_jaccard"] for r in rows) / len(rows),
               "mean_evidence_coverage": sum(r["evidence_coverage"] for r in rows) / len(rows),
               "by_role": breakdown("role"), "by_category": breakdown("category"),
               "provenance_completeness": sum(bool(case.get("record_sha256")) for case in cases) / len(cases)}
    report = {"version": 1, "generated_at": now_iso(), "status": "public_review_agent_coded_proxy_metrics_not_expert_calibrated",
              "evidence_tier": "public_review_silver", "expert_calibrated": False, "metrics": metrics, "cases": rows,
              "limitations": ["Subagents are not domain experts.", "Public reviews were not written against the RevAgent taxonomy.", "Agreement is not correctness or release calibration."]}
    ws = _workspace(base); write_json(ws / "public_review_quality_report.json", report)
    role_lines = "\n".join(f"- `{role}`: {values['finding_count']} findings ({values['high_risk_count']} high risk)" for role, values in metrics["by_role"].items()) or "- none"
    write_text(ws / "public_review_quality_report.md", f"# Public Review Silver Benchmark\n\n- Cases: {len(rows)}\n- Adjudicated findings: {len(adjudicated)}\n- Mean agent agreement (Jaccard): {metrics['mean_agent_agreement_jaccard']:.3f}\n- Evidence coverage: {metrics['mean_evidence_coverage']:.3f}\n- Provenance completeness: {metrics['provenance_completeness']:.3f}\n- Status: `{report['status']}`\n\n## By Role\n\n{role_lines}\n\nThis is a public-record proxy benchmark, not expert calibration.\n")
    return report


def public_review_pack_coverage_report(base: Path, assignments: dict[str, list[str]] | None = None,
                                       minimum_cases: int = 3) -> dict:
    """Verify pack coverage using adjudicated licensed public cases, never expert labels.

    When assignments is omitted, every adjudicated case is deliberately reused for every
    pack. Callers may instead provide an explicit pack-to-case-id mapping.
    """
    if not isinstance(minimum_cases, int) or minimum_cases < 1:
        raise ValueError("minimum_cases must be a positive integer")
    _, registry = _registry(base)
    cases = registry.get("cases", {})
    if not isinstance(cases, dict):
        raise ValueError("public review registry cases must be an object")
    adjudicated = {case_id: case for case_id, case in cases.items() if isinstance(case, dict) and case.get("status") == "agent_adjudicated"}
    packs = available_reviewer_packs()
    if assignments is None:
        assignments = {pack: sorted(adjudicated) for pack in packs}
        assignment_policy = "reuse_all_adjudicated_public_cases_across_packs"
    else:
        if set(assignments) != set(packs) or not all(isinstance(value, list) for value in assignments.values()):
            raise ValueError("assignments must map every available reviewer pack to a case-id list")
        assignment_policy = "explicit_pack_case_assignments"

    matrix = {}
    for pack in packs:
        case_ids = list(dict.fromkeys(str(value) for value in assignments[pack]))
        rows = []
        for case_id in case_ids:
            case = adjudicated.get(case_id)
            if not case:
                rows.append({"case_id": case_id, "eligible": False, "reason": "not_adjudicated_or_unknown"})
                continue
            record = case.get("record", {})
            annotations = case.get("annotations", {})
            findings = case.get("adjudication", {}).get("findings", [])
            provenance = bool(case.get("record_sha256")) and _https(record.get("record_url")) and _https(record.get("license_url"))
            provenance = provenance and len(annotations) >= 2 and all(annotation.get("input_sha256") == case.get("record_sha256") for annotation in annotations.values())
            review_text = {review.get("review_id"): review.get("text", "") for review in record.get("reviews", []) if isinstance(review, dict)}
            evidence = isinstance(findings, list) and all(finding.get("evidence_excerpt", "") in review_text.get(finding.get("review_id"), "") for finding in findings)
            rows.append({"case_id": case_id, "eligible": provenance and evidence, "provenance_complete": provenance,
                         "evidence_complete": evidence, "record_sha256": case.get("record_sha256", "")})
        eligible = [row for row in rows if row["eligible"]]
        matrix[pack] = {"assigned_case_count": len(case_ids), "eligible_case_count": len(eligible), "minimum_cases": minimum_cases,
                        "provenance_completeness": sum(row.get("provenance_complete", False) for row in rows) / len(rows) if rows else 0.0,
                        "evidence_completeness": sum(row.get("evidence_complete", False) for row in rows) / len(rows) if rows else 0.0,
                        "passed": len(eligible) >= minimum_cases and len(eligible) == len(rows), "cases": rows}
    passed = all(row["passed"] and row["provenance_completeness"] == 1.0 and row["evidence_completeness"] == 1.0 for row in matrix.values())
    report = {"version": 1, "generated_at": now_iso(), "status": "not_expert_calibrated", "expert_calibrated": False,
              "verification_tier": "public_source_agent_adjudicated", "assignment_policy": assignment_policy,
              "minimum_cases_per_pack": minimum_cases, "passed": passed, "packs": matrix,
              "limitations": ["Cases may be reused across reviewer packs and do not provide independent pack-specific expert labels.",
                              "Passing establishes silver-standard coverage and provenance only, not reviewer accuracy or expert calibration."]}
    ws = _workspace(base)
    write_json(ws / "public_review_pack_coverage.json", report)
    lines = ["# Public Review Pack Coverage", "", f"- Passed: `{str(passed).lower()}`", "- Status: `not_expert_calibrated`",
             f"- Minimum cases per pack: {minimum_cases}", f"- Assignment policy: `{assignment_policy}`", "", "## Matrix", ""]
    lines.extend(f"- `{pack}`: {row['eligible_case_count']}/{minimum_cases} eligible; provenance={row['provenance_completeness']:.3f}; evidence={row['evidence_completeness']:.3f}; passed={str(row['passed']).lower()}" for pack, row in matrix.items())
    lines.extend(["", "This verifies public-source silver coverage only; it is not expert calibration.", ""])
    write_text(ws / "public_review_pack_coverage.md", "\n".join(lines))
    return report
