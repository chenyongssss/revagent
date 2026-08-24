"""Static, local-only author cockpit in English or Simplified Chinese."""

from __future__ import annotations

import html

from ._utils import load_config, write_text
from .project_runtime import author_decision_console
from .readiness import build_revision_readiness
from .response_trace import build_response_trace


_TEXT = {
    "en": {
        "title": "RevAgent Author Cockpit",
        "summary": "Local evidence overview. It does not certify proofs, experiments, or submission readiness.",
        "items": "Revision items",
        "actions": "Author actions",
        "none": "None.",
        "headers": ("ID", "Lane", "Risk", "Readiness", "Response", "Evidence", "PDF", "Blockers / manual actions"),
    },
    "zh": {
        "title": "RevAgent 作者工作台",
        "summary": "本地证据总览；系统不判定证明、实验或投稿就绪性。",
        "items": "返修事项",
        "actions": "作者待办",
        "none": "无。",
        "headers": ("编号", "类别", "风险", "就绪状态", "回复", "证据", "PDF", "阻塞项 / 人工操作"),
    },
}


def _language(language: str) -> str:
    if language not in _TEXT:
        raise ValueError("language must be en or zh")
    return language


def render_author_cockpit(base, language: str = "en") -> str:
    language = _language(language)
    text = _TEXT[language]
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
        blockers = "; ".join(item.get("missing_inputs", []) + item.get("manual_actions", [])) or text["none"]
        values = (item.get("item_id", ""), item.get("kind", ""), item.get("risk", ""), item.get("readiness_status", ""), response, evidence, pdf, blockers)
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in values) + "</tr>")
    pending = "<br>".join(html.escape(f"{entry['cycle_id']}: {entry['next_command']}") for entry in cycles.get("pending", [])) or text["none"]
    headers = "".join(f"<th>{html.escape(value)}</th>" for value in text["headers"])
    toggle = "<a href=\"?lang=en\">English</a> | <a href=\"?lang=zh\">中文</a>"
    return """<!doctype html><html><head><meta charset=\"utf-8\"><title>""" + html.escape(text["title"]) + """</title><style>body{font-family:system-ui,sans-serif;margin:2rem;color:#18212b}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd4dc;padding:.5rem;text-align:left}th{background:#eef3f7}.warn{color:#8a3600}.language{float:right}</style></head><body>""" + f"<nav class=\"language\">{toggle}</nav><h1>{html.escape(text['title'])}</h1><p>{html.escape(text['summary'])}</p><h2>{html.escape(text['items'])}</h2><table><tr>{headers}</tr>{''.join(rows)}</table><h2>{html.escape(text['actions'])}</h2><p class=\"warn\">{pending}</p></body></html>"


def write_author_cockpit(base, language: str = "en"):
    language = _language(language)
    config = load_config(base)
    path = config.workspace / ("author_cockpit.html" if language == "en" else "author_cockpit.zh.html")
    write_text(path, render_author_cockpit(base, language))
    return path


__all__ = ["render_author_cockpit", "write_author_cockpit"]
