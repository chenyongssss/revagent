from pathlib import Path

import pytest

from revagent.cli import main
from revagent.rebuttal import approve_rebuttal_atom, finalize_rebuttal, parse_rebuttal, rebuttal_draft, rebuttal_stress_test
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
    assert "Verified response and location." in (tmp_path / ".revagent" / "rebuttal_draft.md").read_text(encoding="utf-8")


def test_rebuttal_lint_blocks_commitment_tone_and_rulepack_length(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    rulepack = tmp_path / "journal_profiles" / "siam"
    rulepack.mkdir(parents=True)
    (rulepack / "profile.yaml").write_text("display_name: SIAM\nversion: 1\ntone: precise and collegial\n", encoding="utf-8")
    (rulepack / "rebuttal.yaml").write_text("version: 1\nmax_words: 8\nmax_words_per_response: 6\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    (tmp_path / ".revagent" / "review_items.json").write_text('[{"id":"R001","reviewer":"Reviewer 1","comment":"Clarify convergence."}]', encoding="utf-8")
    parse_rebuttal(tmp_path)
    rebuttal_draft(tmp_path)
    response = tmp_path / "response.txt"
    response.write_text("Obviously the reviewer misunderstood; we will add extensive new experiments.", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main(["rebuttal", "approve", "RB-R001-1", "--note", "Author supplied response.", "--manuscript-locator", "paper.tex:1", "--evidence", "results/table-1", "--response-file", str(response)]) == 0
    report = rebuttal_stress_test(tmp_path)

    assert report["ok"] is False
    assert report["unresolved_commitments"] == ["RB-R001-1"]
    assert report["tone_findings"] == ["RB-R001-1"]
    assert report["length"]["findings"]
    with pytest.raises(ValueError, match="explicit author approval"):
        finalize_rebuttal(tmp_path, True)

    clean = "We revised Section 2."
    approve_rebuttal_atom(tmp_path, "RB-R001-1", "Verified concise response.", "paper.tex:1", "results/table-1", clean)
    assert rebuttal_stress_test(tmp_path)["ok"] is True
    final = finalize_rebuttal(tmp_path, True)
    assert len(final["stress_test_sha256"]) == 64
    assert clean in (tmp_path / ".revagent" / "rebuttal_draft.md").read_text(encoding="utf-8")
    assert "AUTHOR MUST PROVIDE" not in rebuttal_draft(tmp_path)


def test_rebuttal_atomizes_compound_requests_and_exports_traceable_formats(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("x", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    items = '[{"id":"R009","reviewer":"Reviewer 2","comment":"1. Clarify convergence.\\n2. Provide the solver tolerance."}]'
    (tmp_path / ".revagent" / "review_items.json").write_text(items, encoding="utf-8")
    parsed = parse_rebuttal(tmp_path)
    atoms = parsed["threads"]["R009"]["atoms"]
    assert [atom["atom_id"] for atom in atoms] == ["RB-R009-1", "RB-R009-2"]
    assert all(atom["source_item_id"] == "R009" and atom["source_comment"] for atom in atoms)
    rebuttal_draft(tmp_path)
    payload = __import__("json").loads((tmp_path / ".revagent" / "rebuttal_draft.json").read_text(encoding="utf-8"))
    assert len(payload["atoms"]) == 2
    assert (tmp_path / ".revagent" / "rebuttal_paste_ready.txt").read_text(encoding="utf-8").count("AUTHOR MUST PROVIDE") == 2
