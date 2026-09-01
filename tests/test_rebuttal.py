from pathlib import Path

from revagent.cli import main
from revagent.workspace import init_workspace


def test_rebuttal_threads_and_drafts_are_author_gated(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    (tmp_path / ".revagent" / "review_items.json").write_text('[{"id":"R001","reviewer":"Reviewer 1","comment":"Clarify convergence."}]', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["rebuttal", "parse"]) == 0
    assert main(["rebuttal", "plan"]) == 0
    assert main(["rebuttal", "draft"]) == 0
    assert main(["rebuttal", "stress-test"]) == 0
    assert main(["rebuttal", "approve", "RB-R001-1", "--note", "Verified response and location.", "--manuscript-locator", "paper.tex:1", "--evidence", "results/table-1"]) == 0
    assert main(["rebuttal", "finalize", "--approved"]) == 0
    assert "AUTHOR MUST PROVIDE" in (tmp_path / ".revagent" / "rebuttal_draft.md").read_text(encoding="utf-8")
