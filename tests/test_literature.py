from pathlib import Path

from revagent.cli import main
from revagent.workspace import init_workspace


def test_literature_authorization_is_local_only(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "response.json").write_text('{"works": []}', encoding="utf-8")
    assert main(["literature", "cache", "openalex", "--query", "numerical PDE", "--response-file", "response.json"]) == 1
    assert main(["literature", "authorize", "openalex", "--purpose", "related-work metadata"]) == 0
    consent = (tmp_path / ".revagent" / "literature_consent.json").read_text(encoding="utf-8")
    assert '"network_enabled": false' in consent
    assert main(["literature", "cache", "openalex", "--query", "numerical PDE", "--response-file", "response.json"]) == 0
    assert list((tmp_path / ".revagent" / "literature_cache").glob("*.json"))
    assert main(["literature", "report"]) == 0
    assert main(["literature", "status"]) == 0
    assert "retrieved metadata only" in (tmp_path / ".revagent" / "literature_report.json").read_text(encoding="utf-8")
