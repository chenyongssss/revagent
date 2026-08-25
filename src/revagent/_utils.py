from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from ._models import Config, WORKSPACE

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def write_json(path: Path, data: object) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(read_text(path))

def simple_yaml(data: dict[str, object]) -> str:
    lines = []
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"

def parse_simple_yaml(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or raw.startswith(" "):
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        result[key.strip()] = value.strip()
    return result

def find_main_tex(tex_root: Path) -> str:
    candidates = sorted(tex_root.glob("*.tex"))
    for path in candidates:
        text = read_text(path)
        if "\\documentclass" in text:
            return path.name
    if candidates:
        return candidates[0].name
    return "main.tex"

def workspace_path(base: Path) -> Path:
    return base / WORKSPACE

def load_config(base: Path) -> Config:
    ws = workspace_path(base)
    raw = parse_simple_yaml(read_text(ws / "revision.yaml"))
    tex_root = Path(raw.get("tex_root", "."))
    if not tex_root.is_absolute():
        tex_root = (base / tex_root).resolve()
    return Config(
        journal=raw["journal"],
        tex_root=tex_root,
        main_tex=raw.get("main_tex", "main.tex"),
        workspace=ws,
        compile_command=raw.get("compile_command", "latexmk -pdf"),
    )

def first_sentence(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 180:
        return compact
    return compact[:177].rstrip() + "..."

def append_decision_log(config: Config, title: str, lines: list[str]) -> None:
    path = config.workspace / "decision_log.md"
    existing = read_text(path) if path.exists() else "# Decision Log\n\n"
    entry = [f"## {title}", "", f"- Timestamp: {now_iso()}"] + lines + [""]
    write_text(path, existing.rstrip() + "\n\n" + "\n".join(entry))

def load_items(config: Config) -> list[dict]:
    return read_json(config.workspace / "review_items.json", [])

def write_items(config: Config, items: list[dict]) -> None:
    write_json(config.workspace / "review_items.json", items)

def find_item(items: list[dict], item_id: str) -> dict | None:
    return next((item for item in items if item.get("id") == item_id), None)

def find_candidate(candidates: list[dict], candidate_id: str) -> dict | None:
    return next((candidate for candidate in candidates if candidate.get("id") == candidate_id), None)
