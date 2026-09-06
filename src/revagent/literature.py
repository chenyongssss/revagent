"""Consent-gated literature metadata retrieval and reproducible local caching."""
from __future__ import annotations
import hashlib, json, re
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from ._utils import load_config, now_iso, read_json, write_json

PROVIDERS = ("openalex", "crossref", "arxiv", "semantic-scholar", "doi-metadata")
FETCH_PROVIDERS = ("openalex", "crossref", "arxiv", "semantic-scholar", "doi-metadata")
PROVIDER_CONTRACTS = {
    "openalex": "https://api.openalex.org/works",
    "crossref": "https://api.crossref.org/works",
    "arxiv": "https://export.arxiv.org/api/query",
    "semantic-scholar": "https://api.semanticscholar.org/graph/v1/paper/search",
    "doi-metadata": "https://doi.org/",
}

def _json_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()

def _authorized(base, provider: str) -> bool:
    ws = load_config(base).workspace
    data = read_json(ws / "literature_consent.json", {"authorizations": []})
    return any(x.get("provider") == provider for x in data.get("authorizations", []))

def authorize_literature_provider(base, provider: str, purpose: str) -> dict:
    if provider not in PROVIDERS:
        raise ValueError("unknown literature provider")
    ws = load_config(base).workspace
    data = read_json(ws / "literature_consent.json", {"version": 1, "authorizations": []})
    record = {"provider": provider, "purpose": purpose, "authorized_at": now_iso(), "network_enabled": False,
              "note": "Provider consent is local; each network query also requires one-use authorization."}
    data["authorizations"].append(record)
    write_json(ws / "literature_consent.json", data)
    return record

def _first(value: object) -> str:
    return str(value[0] if isinstance(value, list) and value else value or "").strip()

def _date(value: object) -> str:
    if isinstance(value, str): return value
    parts = value.get("date-parts", [[]]) if isinstance(value, dict) else [[]]
    return "-".join(str(v).zfill(2) if i else str(v) for i, v in enumerate(parts[0])) if parts and parts[0] else ""

def _authors(items: object) -> list[str]:
    result = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str): name = item
        elif isinstance(item, dict): name = " ".join(filter(None, (str(item.get("given", "")).strip(), str(item.get("family", "")).strip()))) or str(item.get("display_name", item.get("name", "")))
        else: name = ""
        if name.strip(): result.append(name.strip())
    return result

def _crossref_relations(item: dict) -> list[dict]:
    relations = []
    for kind, values in item.get("relation", {}).items() if isinstance(item.get("relation"), dict) else []:
        for value in values if isinstance(values, list) else []:
            if isinstance(value, dict) and value.get("id"):
                relations.append({"type": kind, "target": str(value["id"]), "target_type": value.get("id-type", "")})
    for update in item.get("update-to", []) if isinstance(item.get("update-to"), list) else []:
        if isinstance(update, dict) and update.get("DOI"):
            relations.append({"type": str(update.get("type", "update")), "target": str(update["DOI"]), "target_type": "doi"})
    return relations

def normalize_provider_response(provider: str, response: object) -> list[dict]:
    if provider == "arxiv":
        xml = response.get("atom_xml", "") if isinstance(response, dict) else str(response)
        root = ET.fromstring(xml) if xml else ET.Element("feed")
        ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
        return [{
            "provider": provider, "provider_id": _first(e.findtext("a:id", "", ns)).rsplit("/", 1)[-1],
            "title": " ".join(_first(e.findtext("a:title", "", ns)).split()),
            "authors": [_first(a.findtext("a:name", "", ns)) for a in e.findall("a:author", ns)],
            "doi": _first(e.findtext("x:doi", "", ns)), "url": _first(e.findtext("a:id", "", ns)),
            "published": _first(e.findtext("a:published", "", ns)), "updated": _first(e.findtext("a:updated", "", ns)), "type": "preprint",
        } for e in root.findall("a:entry", ns)]
    if not isinstance(response, dict): return []
    if provider == "openalex": items = response.get("results", [])
    elif provider == "semantic-scholar": items = response.get("data", [])
    elif provider == "crossref": items = response.get("message", {}).get("items", [])
    elif provider == "doi-metadata": items = [] if response.get("offline") else [response]
    else: return []
    records = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict): continue
        if provider == "openalex":
            authors = [x.get("author", {}).get("display_name", "") for x in item.get("authorships", []) if isinstance(x, dict)]
            pid, doi = _first(item.get("id")), _first(item.get("doi")).removeprefix("https://doi.org/")
            published, url = _first(item.get("publication_date")), _first(item.get("doi") or item.get("id"))
            references = [_first(value) for value in item.get("referenced_works", [])]
            relations = []
        elif provider == "semantic-scholar":
            authors = _authors(item.get("authors", []))
            external = item.get("externalIds", {}) if isinstance(item.get("externalIds"), dict) else {}
            doi = _first(external.get("DOI"))
            pid = _first(item.get("paperId"))
            published = _first(item.get("publicationDate") or item.get("year"))
            url = _first(item.get("url")) or (f"https://doi.org/{doi}" if doi else "")
            references = [_first(value.get("paperId")) for value in item.get("references", []) if isinstance(value, dict)]
            relations = []
        else:
            authors, doi = _authors(item.get("author", [])), _first(item.get("DOI"))
            pid, published = _first(item.get("DOI") or item.get("URL")), _date(item.get("published") or item.get("issued"))
            url = _first(item.get("URL")) or (f"https://doi.org/{doi}" if doi else "")
            references = [_first(ref.get("DOI")) for ref in item.get("reference", []) if isinstance(ref, dict) and ref.get("DOI")]
            relations = _crossref_relations(item) if provider in {"crossref", "doi-metadata"} else []
        records.append({"provider": provider, "provider_id": pid, "title": _first(item.get("title") or item.get("display_name")),
                        "authors": [x for x in authors if x], "doi": doi, "url": url, "published": published,
                        "updated": _first(item.get("updated_date")), "type": _first(item.get("type")),
                        "reference_ids": [value for value in references if value], "relations": relations,
                        "open_access_url": _first((item.get("openAccessPdf") or {}).get("url")) if isinstance(item.get("openAccessPdf"), dict) else "",
                        "citation_count": item.get("citationCount") if isinstance(item.get("citationCount"), int) else None})
    return records

def cache_literature_query(base, provider: str, query: str, response: object, *, authorization: dict | None = None,
                           endpoint: str = "", content_type: str = "application/json", normalized: list[dict] | None = None) -> dict:
    if provider not in PROVIDERS: raise ValueError("unknown literature provider")
    if not _authorized(base, provider):
        raise ValueError(f"provider {provider} has no local authorization; run revagent literature authorize {provider} --purpose ...")
    ws = load_config(base).workspace
    digest = hashlib.sha256((provider + "\0" + query).encode()).hexdigest()
    record = {"version": 2, "provider": provider, "query": query, "queried_at": now_iso(), "endpoint": endpoint,
              "content_type": content_type, "response_sha256": _json_hash(response),
              "normalized_records": normalized if normalized is not None else normalize_provider_response(provider, response),
              "response": response, "authorization_id": authorization.get("authorization_id", "") if authorization else "",
              "purpose": authorization.get("purpose", "local metadata import") if authorization else "local metadata import",
              "final_report_permission": bool(authorization and authorization.get("final_report_permission")),
              "provenance_note": "Retrieved metadata is not manuscript evidence and does not establish novelty or correctness."}
    write_json(ws / "literature_cache" / f"{digest}.json", record)
    return record

def literature_provenance_report(base) -> dict:
    ws = load_config(base).workspace
    included, excluded = [], 0
    for path in sorted((ws / "literature_cache").glob("*.json")):
        record = read_json(path, {})
        if record.get("final_report_permission") is True: included.append(record)
        else: excluded += 1
    report = {"version": 2, "generated_at": now_iso(), "manuscript_evidence": "not included; this report contains retrieved metadata only",
              "retrieved_metadata": included, "excluded_local_only_records": excluded,
              "availability": "available" if included else "no permitted cached provider responses",
              "limitations": ["Metadata does not establish novelty, priority, correctness, or journal suitability."]}
    write_json(ws / "literature_report.json", report)
    return report

def _permitted_cache_records(base) -> list[dict]:
    ws = load_config(base).workspace
    return [record for path in sorted((ws / "literature_cache").glob("*.json"))
            if (record := read_json(path, {})).get("final_report_permission") is True]

def build_citation_graph(base) -> dict:
    ws = load_config(base).workspace
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges = set()
    for cache in _permitted_cache_records(base):
        provenance = {"provider": cache.get("provider", ""), "authorization_id": cache.get("authorization_id", ""),
                      "response_sha256": cache.get("response_sha256", ""), "query_sha256": hashlib.sha256(str(cache.get("query", "")).encode()).hexdigest()}
        for record in cache.get("normalized_records", []):
            source = _first(record.get("doi") or record.get("provider_id"))
            if not source: continue
            nodes.setdefault(source, {"id": source, "title": record.get("title", ""), "doi": record.get("doi", ""), "providers": []})
            if provenance["provider"] not in nodes[source]["providers"]: nodes[source]["providers"].append(provenance["provider"])
            targets = [(target, "cites") for target in record.get("reference_ids", [])]
            targets.extend((rel.get("target", ""), rel.get("type", "related")) for rel in record.get("relations", []) if isinstance(rel, dict))
            for target, relation in targets:
                target = _first(target)
                key = (source, target, relation, provenance["response_sha256"])
                if not target or key in seen_edges: continue
                seen_edges.add(key); nodes.setdefault(target, {"id": target, "title": "", "doi": target if target.lower().startswith("10.") else "", "providers": []})
                edges.append({"source": source, "target": target, "relation": relation, "provenance": provenance})
    graph = {"version": 1, "generated_at": now_iso(), "nodes": sorted(nodes.values(), key=lambda x: x["id"]),
             "edges": sorted(edges, key=lambda x: (x["source"], x["target"], x["relation"])),
             "limitations": ["Edges reflect deposited provider metadata only; absence of an edge is not evidence that no citation or relationship exists."]}
    write_json(ws / "literature_citation_graph.json", graph)
    return graph

def build_retraction_report(base) -> dict:
    ws = load_config(base).workspace
    assertions: list[dict] = []
    checked: set[str] = set()
    for cache in _permitted_cache_records(base):
        provenance = {"provider": cache.get("provider", ""), "authorization_id": cache.get("authorization_id", ""), "response_sha256": cache.get("response_sha256", "")}
        for record in cache.get("normalized_records", []):
            doi = _first(record.get("doi"))
            if doi: checked.add(doi)
            title_and_type = f"{record.get('title', '')} {record.get('type', '')}".lower()
            if doi and re.search(r"\b(retracted article|withdrawn article)\b", title_and_type):
                assertions.append({"doi": doi, "status": "potential_retraction_notice", "relation": "title_or_type_signal", "notice_doi": doi, "provenance": provenance})
            if doi and re.search(r"\bexpression of concern\b", title_and_type):
                assertions.append({"doi": doi, "status": "expression_of_concern", "relation": "title_or_type_signal", "notice_doi": doi, "provenance": provenance})
            for relation in record.get("relations", []):
                if not isinstance(relation, dict): continue
                kind, target = str(relation.get("type", "")).lower(), _first(relation.get("target"))
                if target: checked.add(target)
                if kind in {"retraction", "is-retracted-by", "retracts", "retracted-by"} and target:
                    retracted = doi if kind == "is-retracted-by" and doi else target
                    assertions.append({"doi": retracted, "status": "retracted", "relation": kind, "notice_doi": doi, "provenance": provenance})
    assertions.sort(key=lambda item: (item["status"] != "retracted", item["doi"], item["relation"]))
    retracted = {item["doi"] for item in assertions if item["status"] == "retracted"}
    warnings = {item["doi"]: item["status"] for item in assertions if item["status"] != "retracted"}
    report = {"version": 1, "generated_at": now_iso(), "assertions": assertions,
              "records": [{"doi": doi, "status": "retracted" if doi in retracted else warnings.get(doi, "no_retraction_metadata_observed")} for doi in sorted(checked | retracted)],
              "limitations": ["No retraction metadata observed is not confirmation that a work is unretracted; provider coverage and deposits may be incomplete."]}
    write_json(ws / "literature_retractions.json", report)
    return report

def build_literature_advisory_report(base) -> dict:
    """Build provenance-bound novelty/reproducibility hints without semantic claims."""
    ws = load_config(base).workspace
    rows = []
    for cache in _permitted_cache_records(base):
        provenance = {"provider": cache.get("provider", ""), "authorization_id": cache.get("authorization_id", ""),
                      "response_sha256": cache.get("response_sha256", ""),
                      "query_sha256": hashlib.sha256(str(cache.get("query", "")).encode()).hexdigest()}
        for record in cache.get("normalized_records", []):
            work_id = _first(record.get("doi") or record.get("provider_id"))
            if not work_id:
                continue
            rows.append({
                "work_id": work_id, "title": record.get("title", ""), "published": record.get("published", ""),
                "novelty_advisory": "candidate_for_author_comparison",
                "reproducibility_advisory": "open_access_copy_observed" if record.get("open_access_url") else "no_open_access_copy_observed",
                "reference_count_observed": len(record.get("reference_ids", [])),
                "provenance": provenance,
            })
    report = {
        "version": 1, "generated_at": now_iso(), "records": rows,
        "status": "metadata_advisory_only_not_expert_calibrated",
        "limitations": [
            "Candidate records do not establish novelty, priority, or scientific correctness.",
            "Open-access and reference metadata do not establish computational reproducibility; code, data, environment, and reruns require separate verification.",
        ],
    }
    write_json(ws / "literature_advisory.json", report)
    return report

_ALIGNMENT_STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "of", "on", "or", "that", "the", "this", "to", "we", "with"}

def _alignment_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2 and token not in _ALIGNMENT_STOPWORDS}

def rank_literature_alignment_records(claim_excerpt: str, records: list[dict], limit: int = 5) -> list[dict]:
    claim_tokens = _alignment_tokens(claim_excerpt)
    best_by_work: dict[str, dict] = {}
    for record_index, record in enumerate(records):
        title_tokens = _alignment_tokens(str(record.get("title", "")))
        shared = sorted(claim_tokens & title_tokens)
        work_id = _first(record.get("doi") or record.get("provider_id") or record.get("work_id"))
        if shared and work_id:
            candidate = {"work_id": work_id, "title": record.get("title", ""), "record_index": record_index,
                         "lexical_score": round(len(shared) / len(claim_tokens | title_tokens), 6), "shared_terms": shared}
            current = best_by_work.get(work_id)
            if current is None or candidate["lexical_score"] > current["lexical_score"]:
                best_by_work[work_id] = candidate
    return sorted(best_by_work.values(), key=lambda item: (-item["lexical_score"], item["work_id"]))[:limit]

def build_claim_literature_alignments(base) -> dict:
    ws = load_config(base).workspace
    manifest = read_json(ws / "paper_manifest.json", {})
    if manifest.get("status") != "indexed":
        raise ValueError("paper manifest is not indexed; run revagent paper-ingest")
    if any(not claim.get("content_sha256") for claim in manifest.get("claims", [])):
        raise ValueError("paper manifest lacks claim alignment fields; rerun revagent paper-ingest")
    from .paper_ingestion import paper_manifest_is_stale
    if paper_manifest_is_stale(base, manifest):
        raise ValueError("paper manifest is stale; rerun revagent paper-ingest")
    permitted = _permitted_cache_records(base)
    literature_input_sha256 = _json_hash([{"provider": item.get("provider", ""), "authorization_id": item.get("authorization_id", ""),
                                          "response_sha256": item.get("response_sha256", "")} for item in permitted])
    records = []
    for cache in permitted:
        for item in cache.get("normalized_records", []):
            if item.get("title"):
                records.append((item, cache))
    previous = read_json(ws / "literature_alignments.json", {"candidates": []})
    prior = {item.get("candidate_id"): item for item in previous.get("candidates", [])}
    candidates = []
    for claim in manifest.get("claims", []):
        claim_tokens = _alignment_tokens(str(claim.get("excerpt", "")))
        if not claim_tokens:
            continue
        for ranked in rank_literature_alignment_records(str(claim.get("excerpt", "")), [item[0] for item in records]):
            score, work_id, shared = ranked["lexical_score"], ranked["work_id"], ranked["shared_terms"]
            record, cache = records[ranked["record_index"]]
            fingerprint = _json_hash({"claim": claim.get("content_sha256", ""), "work": work_id, "response": cache.get("response_sha256", "")})
            candidate_id = "ALN-" + fingerprint[:10].upper()
            candidate = {"candidate_id": candidate_id, "claim_id": claim.get("claim_id", ""), "claim_excerpt": claim.get("excerpt", ""),
                         "claim_content_sha256": claim.get("content_sha256", ""), "work_id": work_id, "title": record.get("title", ""),
                         "doi": record.get("doi", ""), "lexical_score": score, "shared_terms": shared, "status": "pending_author_review",
                         "relationship": "unreviewed", "provenance": {"provider": cache.get("provider", ""), "authorization_id": cache.get("authorization_id", ""),
                         "response_sha256": cache.get("response_sha256", "")}, "candidate_fingerprint": fingerprint,
                         "limitation": "Lexical overlap is a discovery hint, not evidence that the work supports, contradicts, or establishes novelty for the claim."}
            old = prior.get(candidate_id, {})
            if old.get("candidate_fingerprint") == fingerprint and old.get("status") in {"approved", "rejected"}:
                candidate.update({key: old[key] for key in ("status", "relationship", "author_note", "reviewed_at") if key in old})
            candidates.append(candidate)
    payload = {"version": 1, "generated_at": now_iso(), "paper_input_fingerprint": manifest.get("input_fingerprint", ""),
               "literature_input_sha256": literature_input_sha256,
               "candidates": sorted(candidates, key=lambda x: (x["claim_id"], -x["lexical_score"], x["work_id"])),
               "limitations": ["Candidates use deterministic title/claim lexical overlap only.", "Every relationship requires author review; no novelty conclusion is generated."]}
    write_json(ws / "literature_alignments.json", payload)
    return payload

def claim_literature_alignments_are_stale(base, payload: dict | None = None) -> bool:
    ws = load_config(base).workspace
    payload = payload if payload is not None else read_json(ws / "literature_alignments.json", {})
    if not payload.get("generated_at"):
        return False
    manifest = read_json(ws / "paper_manifest.json", {})
    current_literature = _json_hash([{"provider": item.get("provider", ""), "authorization_id": item.get("authorization_id", ""),
                                     "response_sha256": item.get("response_sha256", "")} for item in _permitted_cache_records(base)])
    return payload.get("paper_input_fingerprint") != manifest.get("input_fingerprint") or payload.get("literature_input_sha256") != current_literature

def review_claim_literature_alignment(base, candidate_id: str, decision: str, relationship: str, note: str) -> dict:
    if decision not in {"approve", "reject"}: raise ValueError("decision must be approve or reject")
    if not note.strip(): raise ValueError("author review requires a substantive note")
    allowed = {"supports", "contrasts", "background", "method", "unrelated"}
    if decision == "approve" and relationship not in allowed - {"unrelated"}:
        raise ValueError("approved alignment requires supports, contrasts, background, or method relationship")
    ws = load_config(base).workspace
    payload = read_json(ws / "literature_alignments.json", {"candidates": []})
    if claim_literature_alignments_are_stale(base, payload):
        raise ValueError("literature alignments are stale; rerun revagent literature align")
    for candidate in payload.get("candidates", []):
        if candidate.get("candidate_id") == candidate_id:
            candidate.update({"status": "approved" if decision == "approve" else "rejected", "relationship": relationship if decision == "approve" else "unrelated",
                              "author_note": note.strip(), "reviewed_at": now_iso()})
            write_json(ws / "literature_alignments.json", payload)
            return candidate
    raise ValueError(f"unknown literature alignment candidate {candidate_id}")

def literature_status(base) -> dict:
    ws = load_config(base).workspace
    consent = read_json(ws / "literature_consent.json", {"authorizations": []})
    queries = read_json(ws / "literature_query_authorizations.json", {"authorizations": []})
    return {"providers": PROVIDERS, "fetch_providers": FETCH_PROVIDERS, "contracts": PROVIDER_CONTRACTS,
            "authorizations": consent.get("authorizations", []), "query_authorizations": queries.get("authorizations", []), "network_enabled": False}

def authorize_literature_query(base, provider: str, query: str, purpose: str, final_report_permission: bool) -> dict:
    if provider not in PROVIDERS: raise ValueError("unknown literature provider")
    ws = load_config(base).workspace
    data = read_json(ws / "literature_query_authorizations.json", {"version": 1, "authorizations": []})
    record = {"authorization_id": f"LQ-{len(data['authorizations']) + 1:03d}", "provider": provider,
              "query_sha256": hashlib.sha256(query.encode()).hexdigest(), "purpose": purpose,
              "final_report_permission": final_report_permission, "authorized_at": now_iso(), "used": False}
    data["authorizations"].append(record); write_json(ws / "literature_query_authorizations.json", data)
    return record

def _provider_request(provider: str, query: str) -> tuple[Request, str]:
    if provider == "openalex": url, accept = PROVIDER_CONTRACTS[provider] + "?" + urlencode({"search": query, "per-page": 10}), "application/json"
    elif provider == "crossref": url, accept = PROVIDER_CONTRACTS[provider] + "?" + urlencode({"query.bibliographic": query, "rows": 10}), "application/json"
    elif provider == "arxiv": url, accept = PROVIDER_CONTRACTS[provider] + "?" + urlencode({"search_query": f"all:{query}", "start": 0, "max_results": 10}), "application/atom+xml"
    elif provider == "semantic-scholar":
        fields = "paperId,title,authors,externalIds,url,year,publicationDate,references.paperId,openAccessPdf,citationCount"
        url, accept = PROVIDER_CONTRACTS[provider] + "?" + urlencode({"query": query, "limit": 10, "fields": fields}), "application/json"
    elif provider == "doi-metadata":
        doi = query.strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
        if not re.fullmatch(r"10\.\d{4,9}/\S+", doi, re.I): raise ValueError("DOI metadata queries require a valid DOI")
        url, accept = PROVIDER_CONTRACTS[provider] + quote(doi, safe="/"), "application/vnd.citationstyles.csl+json"
    else: raise ValueError(f"provider {provider} has no fetch connector")
    return Request(url, headers={"Accept": accept, "User-Agent": "RevAgent/metadata-only"}), accept

def fetch_literature_provider(base, provider: str, query: str, authorization_id: str, offline: bool = False) -> dict:
    if provider not in FETCH_PROVIDERS: raise ValueError(f"provider {provider} has no fetch connector")
    if not _authorized(base, provider): raise ValueError(f"provider {provider} has no local authorization")
    ws = load_config(base).workspace
    data = read_json(ws / "literature_query_authorizations.json", {"authorizations": []})
    qhash = hashlib.sha256(query.encode()).hexdigest()
    auth = next((x for x in data.get("authorizations", []) if x.get("authorization_id") == authorization_id), None)
    if not auth or auth.get("used") or auth.get("provider") != provider or auth.get("query_sha256") != qhash:
        raise ValueError(f"a matching unused {provider} per-query authorization is required")
    request, accept = _provider_request(provider, query)
    if offline:
        response = {"atom_xml": "<feed xmlns='http://www.w3.org/2005/Atom'/>", "offline": True} if provider == "arxiv" else {"results": [], "offline": True}
        content_type = accept
    else:
        from .privacy import privacy_scan
        if not privacy_scan(base).get("remote_safe"): raise ValueError("privacy scan does not permit remote retrieval")
        with urlopen(request, timeout=20) as handle:
            payload, content_type = handle.read().decode(), handle.headers.get_content_type()
        response = {"atom_xml": payload} if provider == "arxiv" else json.loads(payload)
    cached = cache_literature_query(base, provider, query, response, authorization=auth, endpoint=request.full_url,
                                    content_type=content_type, normalized=normalize_provider_response(provider, response))
    auth.update({"used": True, "used_at": now_iso(), "cache_response_sha256": cached["response_sha256"]})
    write_json(ws / "literature_query_authorizations.json", data)
    return cached

def fetch_openalex(base, query: str, authorization_id: str, offline: bool = False) -> dict:
    return fetch_literature_provider(base, "openalex", query, authorization_id, offline)
