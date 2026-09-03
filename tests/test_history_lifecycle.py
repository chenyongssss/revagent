import json
from pathlib import Path

import pytest

from revagent.cli import main
from revagent.history import approve_history, delete_history, enforce_history_retention, export_history, import_history, rebuild_history_index, redact_history, search_history
from revagent.workspace import init_workspace, migrate_workspace


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    source = tmp_path / "history.txt"
    source.write_text("Contact Ada@example.org. Manuscript ID ABC-123. We answered with a stability estimate.", encoding="utf-8")
    return source


def test_history_requires_redaction_before_approval_and_index(tmp_path: Path) -> None:
    source = _workspace(tmp_path)
    record = import_history(tmp_path, source, "style precedent")
    with pytest.raises(ValueError, match="redaction preview"):
        approve_history(tmp_path, record["history_id"])
    assert rebuild_history_index(tmp_path)["indexed_history_ids"] == []
    preview = redact_history(tmp_path, record["history_id"], source, "project_lifetime")
    text = (tmp_path / ".revagent" / preview["preview_path"]).read_text(encoding="utf-8")
    assert "Ada@example.org" not in text and "ABC-123" not in text
    approve_history(tmp_path, record["history_id"])
    assert rebuild_history_index(tmp_path)["indexed_history_ids"] == [record["history_id"]]
    result = search_history(tmp_path, "stability")
    assert result[0]["history_id"] == record["history_id"]
    assert result[0]["use"] == "style_or_precedent_suggestion_only"


def test_history_tamper_delete_and_export_boundaries(tmp_path: Path) -> None:
    source = _workspace(tmp_path); record = import_history(tmp_path, source, "precedent")
    redacted = redact_history(tmp_path, record["history_id"], source, "until_deleted"); approve_history(tmp_path, record["history_id"])
    preview = tmp_path / ".revagent" / redacted["preview_path"]
    preview.write_text("tampered stability", encoding="utf-8")
    assert rebuild_history_index(tmp_path)["indexed_history_ids"] == []
    redact_history(tmp_path, record["history_id"], source, "until_deleted"); approve = json.loads((tmp_path / ".revagent" / "history_registry.json").read_text(encoding="utf-8"))
    assert approve["records"][0]["raw_content_stored"] is False
    exported = export_history(tmp_path, tmp_path / "export")
    assert (exported / "H-001.txt").exists()
    with pytest.raises(ValueError, match="--confirm"):
        delete_history(tmp_path, record["history_id"])
    deleted = delete_history(tmp_path, record["history_id"], True)
    assert deleted["deletion_status"] == "deleted" and not preview.exists()
    assert search_history(tmp_path, "stability") == []


def test_history_cli_and_non_destructive_registry_migration(tmp_path: Path, monkeypatch) -> None:
    source = _workspace(tmp_path); monkeypatch.chdir(tmp_path)
    assert main(["history", "import", str(source), "--purpose", "precedent"]) == 0
    assert main(["history", "redact", "H-001", "--source-file", str(source), "--retention", "30_days"]) == 0
    assert main(["history", "approve", "H-001"]) == 0
    assert main(["history", "rebuild"]) == 0
    assert main(["history", "search", "stability"]) == 0
    registry = tmp_path / ".revagent" / "history_registry.json"
    data = json.loads(registry.read_text(encoding="utf-8")); data["version"] = 1; registry.write_text(json.dumps(data), encoding="utf-8")
    assert "upgrade history_registry.json to version 2" in migrate_workspace(tmp_path, True)["actions"]
    migrate_workspace(tmp_path, False)
    migrated = json.loads(registry.read_text(encoding="utf-8"))
    assert migrated["version"] == 2 and migrated["records"][0]["source_sha256"]


def test_history_30_day_retention_expires_preview_and_index(tmp_path: Path, monkeypatch) -> None:
    source = _workspace(tmp_path); record = import_history(tmp_path, source, "precedent")
    redacted = redact_history(tmp_path, record["history_id"], source, "30_days"); approve_history(tmp_path, record["history_id"])
    rebuild_history_index(tmp_path); registry = tmp_path / ".revagent" / "history_registry.json"
    data = json.loads(registry.read_text(encoding="utf-8")); data["records"][0]["approved_at"] = "2000-01-01T00:00:00+00:00"
    registry.write_text(json.dumps(data), encoding="utf-8")
    assert search_history(tmp_path, "stability") == []
    expired = json.loads(registry.read_text(encoding="utf-8"))["records"][0]
    assert expired["deletion_status"] == "expired" and expired["deletion_reason"] == "retention_expired"
    assert not (tmp_path / ".revagent" / redacted["preview_path"]).exists()
    monkeypatch.chdir(tmp_path)
    assert main(["history", "enforce-retention"]) == 0


def test_non_expiring_history_is_not_automatically_removed(tmp_path: Path) -> None:
    source = _workspace(tmp_path); record = import_history(tmp_path, source, "precedent")
    redacted = redact_history(tmp_path, record["history_id"], source, "until_deleted"); approve_history(tmp_path, record["history_id"])
    registry = tmp_path / ".revagent" / "history_registry.json"; data = json.loads(registry.read_text(encoding="utf-8"))
    data["records"][0]["approved_at"] = "2000-01-01T00:00:00+00:00"; registry.write_text(json.dumps(data), encoding="utf-8")
    assert enforce_history_retention(tmp_path)["expired_history_ids"] == []
    assert (tmp_path / ".revagent" / redacted["preview_path"]).exists()
