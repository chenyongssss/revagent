"""Protected CI smoke test for a real OpenAI-compatible rubric provider."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from revagent.project_runtime import authorize_remote, evaluate_review_item, initialize_project_runtime, run_project_cycle
from revagent.review_rubric import run_review_rubric
from revagent.reviews import ingest_comments
from revagent.workspace import init_workspace


def main() -> None:
    fixture = Path(__file__).resolve().parents[1] / "benchmarks" / "synthetic" / "basic"
    with tempfile.TemporaryDirectory(prefix="revagent-provider-e2e-") as temp:
        project = Path(temp) / "project"
        shutil.copytree(fixture, project)
        init_workspace(project, "siam", ".", "paper.tex")
        ingest_comments(project, "comments.md")
        initialize_project_runtime(project)
        for _ in range(4):
            run_project_cycle(project)
        evaluate_review_item(project, "R001")
        authorization = authorize_remote(project, "R001:collect_evidence", "openai-compatible", __import__("os").environ["REVAGENT_LLM_MODEL"], "rubric", ["project_snapshot"], ttl_minutes=10)
        run_review_rubric(project, "R001", int(authorization["authorization_id"]))


if __name__ == "__main__":
    main()
