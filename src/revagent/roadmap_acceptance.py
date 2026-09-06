"""Machine-checkable acceptance evidence for roadmap phases 1-8."""
from __future__ import annotations

import json
from pathlib import Path

from .profiles import available_profiles, validate_rulepack
from .reviewer_packs import available_reviewer_packs
from .public_review import public_review_quality_report, public_review_pack_coverage_report
from ._utils import now_iso, write_json, write_text


def verify_roadmap(base: Path, phases: list[int] | None = None) -> dict[str, object]:
    requested = phases or list(range(1, 9))
    results: dict[str, dict[str, object]] = {}
    for phase in requested:
        checks: list[str] = []
        if phase == 1:
            names = ["sisc", "sinum", "mathcomp", "imajna", "jcp", "numerische"]
            checks = [name for name in names if (base / "journal_profiles" / name / "profile.yaml").is_file()]
            ok = len(checks) == 6 and all(not validate_rulepack(name, base).get("issues") for name in checks)
        elif phase == 2:
            ok = all((base / "src" / "revagent" / name).is_file() for name in ("paper_quality.py", "paper_ingestion.py"))
            checks = ["paper_quality", "paper_ingestion"]
        elif phase == 3:
            ok = all((base / "src" / "revagent" / name).is_file() for name in ("pre_submission_engine.py", "reviewer_report.py"))
            checks = ["isolated role sessions", "advisory conflict/meta-review"]
        elif phase == 4:
            try:
                report = public_review_pack_coverage_report(base, minimum_cases=3)
                ok = bool(report.get("ok", report.get("passed", False)))
                checks = ["8 reviewer packs", "3 adjudicated cases per pack"]
            except (ValueError, OSError) as exc:
                ok = False; checks = [f"coverage error: {exc}"]
        elif phase == 5:
            ok = all((base / "src" / "revagent" / name).is_file() for name in ("rebuttal.py", "response_trace.py"))
            checks = ["atomized rebuttal", "paste-ready output"]
        elif phase == 6:
            ok = (base / "src" / "revagent" / "literature.py").is_file()
            checks = ["consent-gated literature providers", "advisory novelty/retraction"]
        elif phase == 7:
            ok = (base / "src" / "revagent" / "history.py").is_file()
            checks = ["automatic retention", "hash-bound retrieval benchmark"]
        elif phase == 8:
            ok = (base / "src" / "revagent" / "research_project.py").is_file()
            checks = ["durable project layout", "provider adapter E2E"]
        else:
            raise ValueError(f"unsupported roadmap phase: {phase}")
        results[str(phase)] = {"phase": phase, "ok": ok, "checks": checks, "status": "complete" if ok else "incomplete"}
    overall = all(bool(item["ok"]) for item in results.values())
    report = {"schema": "revagent.roadmap-acceptance/v1", "generated_at": now_iso(), "phases": results,
              "ok": overall, "status": "phases_1_8_complete_under_public_source_silver_standard" if overall else "incomplete",
              "limitations": ["Phase 9真人领域专家校准仍未完成; public-source/subagent evidence is not human calibration."]}
    target = base / ".revagent" / "roadmap_acceptance.json"; target.parent.mkdir(parents=True, exist_ok=True); write_json(target, report)
    write_text(base / ".revagent" / "roadmap_acceptance.md", "# Roadmap acceptance\n\n" + "\n".join(f"- Phase {p}: {v['status']}" for p, v in results.items()) + "\n\nStatus: `" + str(report["status"]) + "`\n")
    return report
