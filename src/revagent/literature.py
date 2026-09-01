"""Consent-gated local literature query records; no network adapter is enabled here."""
from __future__ import annotations
import hashlib
import json
from urllib.parse import quote
from urllib.request import urlopen
from ._utils import load_config, now_iso, read_json, write_json

PROVIDERS = ("openalex", "crossref", "arxiv", "semantic-scholar", "doi-metadata")

def authorize_literature_provider(base, provider: str, purpose: str) -> dict:
    if provider not in PROVIDERS:
        raise ValueError("unknown literature provider")
    config = load_config(base)
    ledger = read_json(config.workspace / "literature_consent.json", {"version": 1, "authorizations": []})
    record = {"provider": provider, "purpose": purpose, "authorized_at": now_iso(), "network_enabled": False, "note": "Authorization is recorded locally; no request was sent."}
    ledger["authorizations"].append(record)
    write_json(config.workspace / "literature_consent.json", ledger)
    return record

def cache_literature_query(base, provider: str, query: str, response: object) -> dict:
    config = load_config(base)
    ledger = read_json(config.workspace / "literature_consent.json", {"authorizations": []})
    if not any(record.get("provider") == provider for record in ledger.get("authorizations", [])):
        raise ValueError(f"provider {provider} has no local authorization; run revagent literature authorize {provider} --purpose ...")
    digest = hashlib.sha256((provider + "\0" + query).encode()).hexdigest()
    record = {"provider": provider, "query": query, "queried_at": now_iso(), "response_sha256": hashlib.sha256(repr(response).encode()).hexdigest(), "response": response}
    write_json(config.workspace / "literature_cache" / f"{digest}.json", record)
    return record

def literature_provenance_report(base) -> dict:
    config = load_config(base)
    records = []
    for path in sorted((config.workspace / "literature_cache").glob("*.json")):
        records.append(read_json(path, {}))
    report = {"version": 1, "generated_at": now_iso(), "manuscript_evidence": "not included; this report contains retrieved metadata only", "retrieved_metadata": records, "availability": "available" if records else "no cached provider responses", "limitations": ["Cached metadata does not establish novelty, priority, correctness, or journal suitability."]}
    write_json(config.workspace / "literature_report.json", report)
    return report

def literature_status(base) -> dict:
    config = load_config(base)
    ledger = read_json(config.workspace / "literature_consent.json", {"authorizations": []})
    return {"providers": PROVIDERS, "authorizations": ledger.get("authorizations", []), "network_enabled": False}

def authorize_literature_query(base, provider: str, query: str, purpose: str, final_report_permission: bool) -> dict:
    config = load_config(base)
    ledger = read_json(config.workspace / "literature_query_authorizations.json", {"version": 1, "authorizations": []})
    record = {"authorization_id": f"LQ-{len(ledger['authorizations']) + 1:03d}", "provider": provider, "query_sha256": hashlib.sha256(query.encode()).hexdigest(), "purpose": purpose, "final_report_permission": final_report_permission, "authorized_at": now_iso(), "used": False}
    ledger["authorizations"].append(record)
    write_json(config.workspace / "literature_query_authorizations.json", ledger)
    return record

def fetch_openalex(base, query: str, authorization_id: str, offline: bool = False) -> dict:
    config = load_config(base)
    ledger = read_json(config.workspace / "literature_query_authorizations.json", {"authorizations": []})
    record = next((item for item in ledger["authorizations"] if item.get("authorization_id") == authorization_id), None)
    if not record or record.get("used") or record.get("provider") != "openalex" or record.get("query_sha256") != hashlib.sha256(query.encode()).hexdigest():
        raise ValueError("a matching unused OpenAlex per-query authorization is required")
    if offline:
        response = {"results": [], "offline": True}
    else:
        from .privacy import privacy_scan
        if not privacy_scan(base).get("remote_safe"):
            raise ValueError("privacy scan does not permit remote retrieval")
        url = "https://api.openalex.org/works?search=" + quote(query) + "&per-page=10"
        with urlopen(url, timeout=20) as handle:
            response = json.loads(handle.read().decode("utf-8"))
    record["used"] = True
    record["used_at"] = now_iso()
    write_json(config.workspace / "literature_query_authorizations.json", ledger)
    return cache_literature_query(base, "openalex", query, response)
