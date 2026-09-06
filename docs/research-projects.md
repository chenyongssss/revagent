# General Research Projects

The Phase 8 research-project foundation is local, durable, and deliberately
human-gated. A project contains `sources/`, `references/`, `tasks/`, `memory/`,
`reports/`, `experiments/`, and `.revagent/`.

`tasks/frontier.json` is the resumable task frontier. Tasks remain blocked until
their dependencies complete. Recording a result stores the path and SHA-256 of
each evidence artifact, but does not verify the result. A named human reviewer
must explicitly approve verification while the hashes still match.

Evidence reports are immutable numbered snapshots in `reports/`. The `family`
workflow creates an explicitly approved related project. The `evolve` workflow
is stricter: it creates a generalization branch only from a human-verified task,
and records both its evidence hashes and the separate generalization approval.

These controls are provenance gates, not claims of mathematical correctness.
No agent action may supply or bypass the human approvals.
