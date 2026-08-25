# Advanced usage

## Per-item review and hand-off

| Goal | Command |
| --- | --- |
| Inspect a reviewer item | `revagent inspect R001` |
| Create or view an item plan | `revagent plan-item R001` / `revagent review-analysis R001` |
| Audit a proof request | `revagent proof-plan R001` then `revagent proof-audit R001` |
| Record an experiment contract | `revagent experiment-contract R002` |
| See traceability and blockers | `revagent response-trace` / `revagent readiness` |
| Check a final hand-off package | `revagent submit-pack --dry-run` |

Run `revagent --help` for all commands and `revagent <command> --help` for options.

## Local browser overview

Run `revagent serve`, then open `http://127.0.0.1:8765/cockpit?lang=en` or `http://127.0.0.1:8765/cockpit?lang=zh`.

## Community calibration

The repository contains synthetic fixtures only. To create a voluntary, local metadata-only candidate package:

```powershell
revagent contribution-template --case-id community-001
revagent contribution-export --case-dir C:\path\to\deidentified_case --case-id community-001 --data-card C:\path\to\data_card.json --confirm
```

The package contains a data card, safety scan, and file fingerprints; it never copies manuscript text, reviewer comments, source code, or data. Human governance approval remains required before sharing.

## Development and release

```powershell
python -m pytest
```

CI covers Windows, Linux, and macOS. Release verification and limitations are documented in [RELEASE_NOTES.md](../RELEASE_NOTES.md).
