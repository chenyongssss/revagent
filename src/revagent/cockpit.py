"""Static local author cockpit; it contains no remote scripts or trackers."""

from __future__ import annotations

import html

from ._utils import load_config, write_text
from .project_runtime import author_decision_console
from .readiness import build_revision_readiness
from .response_trace import build_response_trace


def render_author_cockpit(base) -> str:
    readiness = build_revision_readiness(base)
    trace = build_response_trace(base)
    cycles = author_decision_console(base)
    trace_by_item = {str(record.get("item_id", "")): record for record in trace.get("records", [])}
    rows = []
    for item in readiness.get("items", []):
        record = trace_by_item.get(str(item.get("item_id", "")), {})
        response = (record.get("response_assertion") or {}).get("status", "not_assessed")
        evidence = (record.get("evidence") or {}).get("status", "not_assessed")
        pdf = (record.get("final_pdf") or {}).get("status", "not_assessed")
        blockers = "; ".join(item.get("missing_inputs", []) + item.get("manual_actions", [])) or "none"
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in (item.get("item_id", ""), item.get("kind", ""), item.get("risk", ""), item.get("readiness_status", ""), response, evidence, pdf, blockers)) + "</tr>")
    pending = "<br>".join(html.escape(f"{entry['cycle_id']}: {entry['next_command']}") for entry in cycles.get("pending", [])) or "None."
    return """<!doctype html><html><head><meta charset=\"utf-8\"><title>RevAgent Author Cockpit</title><style>body{font-family:system-ui,sans-serif;margin:2rem;color:#18212b}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd4dc;padding:.5rem;text-align:left}th{background:#eef3f7}.warn{color:#8a3600}</style></head><body>""" + f"<h1>RevAgent Author Cockpit</h1><p>Local evidence overview. It does not certify proofs, experiments, or submission readiness.</p><h2>Revision items</h2><table><tr><th>ID</th><th>Lane</th><th>Risk</th><th>Readiness</th><th>Response</th><th>Evidence</th><th>PDF</th><th>Blockers / manual actions</th></tr>{''.join(rows)}</table><h2>Author actions</h2><p class=\"warn\">{pending}</p></body></html>"


def write_author_cockpit(base):
    config = load_config(base)
    path = config.workspace / "author_cockpit.html"
    write_text(path, render_author_cockpit(base))
    return path


__all__ = ["render_author_cockpit", "write_author_cockpit"]
