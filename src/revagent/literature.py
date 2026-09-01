"""Consent-gated literature metadata retrieval and reproducible local caching."""
from __future__ import annotations
import hashlib, json, re
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from ._utils import load_config, now_iso, read_json, write_json

PROVIDERS = ("openalex", "crossref", "arxiv", "semantic-scholar", "doi-metadata")
FETCH_PROVIDERS = ("openalex", "crossref", "arxiv", "doi-metadata")
PROVIDER_CONTRACTS = {
    "openalex": "https://api.openalex.org/works",
    "crossref": "https://api.crossref.org/works",
    "arxiv": "https://export.arxiv.org/api/query",
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
        else:
            authors, doi = _authors(item.get("author", [])), _first(item.get("DOI"))
            pid, published = _first(item.get("DOI") or item.get("URL")), _date(item.get("published") or item.get("issued"))
            url = _first(item.get("URL")) or (f"https://doi.org/{doi}" if doi else "")
        records.append({"provider": provider, "provider_id": pid, "title": _first(item.get("title") or item.get("display_name")),
                        "authors": [x for x in authors if x], "doi": doi, "url": url, "published": published,
                        "updated": _first(item.get("updated_date")), "type": _first(item.get("type"))})
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
