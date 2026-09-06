from pathlib import Path

from revagent.candidates import approve_candidate, edit_candidate
from revagent.revision_workflow import apply_revision_candidates, run_revision_workflow, revision_consistency_report
from revagent.workspace import init_workspace


def test_comment_to_rebuttal_workflow_is_traceable_and_gated(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", encoding="utf-8")
    (tmp_path / "comments.md").write_text("Reviewer 1:\n- Clarify the method.\n- Provide a convergence experiment.", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    result = run_revision_workflow(tmp_path, "comments.md")
    assert len(result["atoms"]["atoms"]) == 2
    assert result["tasks"]["tasks"][0]["status"] == "ready"
    assert result["tasks"]["tasks"][1]["status"] == "awaiting_author"
    assert result["consistency"]["ok"] is False
    assert revision_consistency_report(tmp_path)["status"] == "author_review_required"


def test_approved_low_risk_candidate_applies_with_backup_and_revalidation(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\begin{document}\nMethod text.\n\\end{document}\n", encoding="utf-8")
    (tmp_path / "comments.md").write_text("Reviewer 1:\n- Clarify the method description.", encoding="utf-8")
    init_workspace(tmp_path, "siam", ".", "paper.tex")
    result = run_revision_workflow(tmp_path, "comments.md")
    candidate = result["candidates"]["candidates"][0]
    response = tmp_path / "candidate.txt"
    response.write_text("We clarify the method assumptions in this paragraph.", encoding="utf-8")
    edit_candidate(tmp_path, candidate["id"], "candidate.txt")
    approve_candidate(tmp_path, candidate["id"])
    applied = apply_revision_candidates(tmp_path)
    assert applied["apply"]["applied"] == [candidate["id"]]
    assert Path(applied["apply"]["backup_dir"]).is_dir()
    assert applied["package"]["status"] == "author_review_required"
    assert applied["manifest"]["input_fingerprint"]
