from pathlib import Path

from revagent.cli import main
from revagent.pre_submission_engine import authorize_followup, merge_role_reports, run_review_round, run_role_review
from revagent.workspace import init_workspace


def test_role_reports_are_isolated_and_merge_only_when_all_are_current(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\\begin{theorem}Claim.\\end{theorem}\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    theory = run_role_review(tmp_path, "theory-reviewer", "stability-convergence")
    assert theory["role"] == "theory-reviewer"
    assert theory["reviewer_pack"]["key"] == "stability-convergence"
    assert all("independent expert conclusion" in value for value in theory["limitations"][:1])
    assert merge_role_reports(tmp_path)["status"] == "incomplete"

    monkeypatch.chdir(tmp_path)
    assert main(["review-role", "text-reviewer"]) == 0
    assert main(["review-role", "experiment-reviewer"]) == 0
    assert main(["review-merge"]) == 0


def test_review_round_is_bounded_and_followups_require_author_authorization(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\\begin{theorem}Claim.\\end{theorem}\\end{document}\n", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    result = run_review_round(tmp_path, "nightmare")
    assert result["round"]["author_pause_required"] is True
    assert result["outputs"]["editor_summary"]["advisory"] is True
    task = result["followups"][0]
    assert task["status"] == "authorization_required"
    assert authorize_followup(tmp_path, task["task_id"])["status"] == "authorized"
    run_review_round(tmp_path)
    try:
        run_review_round(tmp_path)
        assert False, "third round must be blocked"
    except ValueError as exc:
        assert "maximum review rounds" in str(exc)
