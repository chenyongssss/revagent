import shutil
from pathlib import Path

from revagent.cli import main
from revagent.pre_submission_review import build_pre_submission_review
from revagent.profiles import available_profiles, diff_rulepacks, load_profile, validate_rulepack
from revagent.workspace import init_workspace


def test_project_local_sisc_rulepack_drives_required_checks(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Method}\nText.\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "journal_profiles").mkdir()
    repo = Path(__file__).resolve().parents[1]
    shutil.copy2(repo / "journal_profiles" / "sisc.yaml", tmp_path / "journal_profiles" / "sisc.yaml")
    init_workspace(tmp_path, "sisc", ".", "paper.tex")
    report = build_pre_submission_review(tmp_path)
    assert report["journal"]["display_name"] == "SIAM Journal on Scientific Computing"
    assert {"contribution", "reproducibility"} <= {row["category"] for row in report["findings"]}


def test_directory_rulepack_is_preferred_and_records_component_hashes(tmp_path: Path, monkeypatch) -> None:
    rulepack = tmp_path / "journal_profiles" / "custom"
    rulepack.mkdir(parents=True)
    (rulepack / "profile.yaml").write_text("display_name: Custom Directory Journal\nversion: 1\nsource_url: https://example.test/rules\nsource_checked_at: 2026-08-30\nexpires_at: 2027-08-30\nhuman_confirmed: true\npage_limit: 0\nrequired_attachments:\n  - supplement.zip\nrequired_checks:\n  - reproducibility\n", encoding="utf-8")
    (rulepack / "rubric.yaml").write_text("version: 1\nchecks:\n  - Explain the numerical contribution.\n", encoding="utf-8")
    (rulepack / "submission.yaml").write_text("version: 1\nchecks:\n  - Attach the reproducibility archive.\n", encoding="utf-8")
    (rulepack / "rebuttal.yaml").write_text("version: 1\n", encoding="utf-8")
    (rulepack / "sources.md").write_text("# Sources\n", encoding="utf-8")
    (tmp_path / "journal_profiles" / "custom.yaml").write_text("display_name: Legacy Custom Journal\n", encoding="utf-8")

    profile = load_profile("custom", tmp_path)

    assert profile["display_name"] == "Custom Directory Journal"
    assert profile["rulepack"]["format"] == "directory-v1"
    assert set(profile["rulepack"]["components"]) == {"profile.yaml", "rubric.yaml", "submission.yaml", "rebuttal.yaml", "sources.md"}
    assert "custom" in available_profiles(tmp_path)
    assert validate_rulepack("custom", tmp_path)["ok"] is True
    monkeypatch.chdir(tmp_path)
    assert main(["journal", "list"]) == 0
    assert main(["journal", "validate", "custom"]) == 0
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}Text.\\end{document}\n", encoding="utf-8")
    (tmp_path / "paper.pdf").write_bytes(b"/Type /Page")
    init_workspace(tmp_path, "custom", ".", "paper.tex")
    report = build_pre_submission_review(tmp_path)
    assert report["rubric_checks"] == ["Explain the numerical contribution."]
    assert report["submission_checks"] == ["Attach the reproducibility archive."]
    assert {finding["category"] for finding in report["findings"]} >= {"attachments", "page_limit"}


def test_directory_rulepack_validation_blocks_unconfirmed_or_expired_profiles(tmp_path: Path) -> None:
    rulepack = tmp_path / "journal_profiles" / "expired"
    rulepack.mkdir(parents=True)
    (rulepack / "profile.yaml").write_text("display_name: Expired Journal\nversion: 1\nsource_url: https://example.test/rules\nsource_checked_at: 2026-01-01\nexpires_at: 2026-02-01\nhuman_confirmed: false\n", encoding="utf-8")
    for component in ("rubric.yaml", "submission.yaml", "rebuttal.yaml", "sources.md"):
        (rulepack / component).write_text("version: 1\n", encoding="utf-8")

    result = validate_rulepack("expired", tmp_path)

    assert result["ok"] is False
    assert any("expired" in message for message in result["blocking"])
    assert any("not human-confirmed" in message for message in result["blocking"])


def test_journal_init_and_diff_create_a_safe_unconfirmed_rulepack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["journal", "init", "newjournal"]) == 0
    rulepack = tmp_path / "journal_profiles" / "newjournal"
    assert {path.name for path in rulepack.iterdir()} == {"profile.yaml", "rubric.yaml", "submission.yaml", "rebuttal.yaml", "sources.md"}
    assert validate_rulepack("newjournal", tmp_path)["ok"] is False
    assert diff_rulepacks("newjournal", "newjournal", tmp_path)["identical"] is True
    assert main(["journal", "diff", "newjournal", "newjournal"]) == 0


def test_shipped_directory_starters_are_complete_but_unconfirmed() -> None:
    repo = Path(__file__).resolve().parents[1]
    for name in ("sisc", "sinum", "mathcomp", "imajna", "jcp", "numerische"):
        rulepack = repo / "journal_profiles" / name
        assert {path.name for path in rulepack.iterdir()} == {"profile.yaml", "rubric.yaml", "submission.yaml", "rebuttal.yaml", "sources.md"}
        assert validate_rulepack(name, repo)["ok"] is False


def test_unconfirmed_directory_rulepack_blocks_journal_specific_review(tmp_path: Path) -> None:
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\\begin{document}Text.\\end{document}\n", encoding="utf-8")
    rulepack = tmp_path / "journal_profiles" / "blocked"
    rulepack.mkdir(parents=True)
    (rulepack / "profile.yaml").write_text("display_name: Blocked Journal\nversion: 1\nsource_url: https://example.test/rules\nsource_checked_at: 2026-08-30\nexpires_at: 2027-08-30\nhuman_confirmed: false\nrequired_checks:\n  - reproducibility\n", encoding="utf-8")
    for component in ("rubric.yaml", "submission.yaml", "rebuttal.yaml", "sources.md"):
        (rulepack / component).write_text("version: 1\n", encoding="utf-8")
    init_workspace(tmp_path, "blocked", ".", "paper.tex")

    report = build_pre_submission_review(tmp_path)

    assert report["journal_specific_status"] == "blocked"
    assert report["findings"][0]["category"] == "journal_rulepack"
    assert not any(row["category"] == "reproducibility" for row in report["findings"])
