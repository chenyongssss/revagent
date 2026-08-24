# RevAgent v0.1.0 — Alpha

RevAgent v0.1.0 is an alpha, local-first computational-mathematics revision workspace. It is released for shadow-mode evaluation, workflow feedback, and safely governed community calibration only.

## Safety and scope

- Status: `alpha`, `shadow-only`, `calibration_required`.
- RevAgent does not determine whether a proof, stability claim, convergence claim, or numerical conclusion is correct.
- It does not automatically submit manuscripts, upload project material, or make user material public.
- Proof, stability, convergence, experiment, response-fact, and final-PDF decisions remain subject to explicit author or domain-expert approval.
- Community contribution packages are local metadata-only packages. They include a data card, safety scan, and file fingerprints, but never copy case source material. A human governance review is required before any sharing decision.

## Included in this release

- Closed-schema Planner, Actor, and independent Reviewer evidence workflows with integrity validation.
- Local review-comment ingestion, LaTeX source locating, proof obligations, controlled experiment records, response traceability, and author cockpit.
- Synthetic benchmark catalog generation and local shadow-benchmark registration.
- Local contribution-package export with explicit confirmation, permission/deidentification declarations, and credential scanning.

## Verification

Release assets include SHA-256 checksums and an SPDX SBOM. GitHub Actions generates build and SBOM attestations; verify release assets with `gh attestation verify` before use.

## Known limitations

This release has not completed independent expert calibration or real-case benchmark gates. Do not use it as a mathematical correctness oracle or as an autonomous revision/submission system.
