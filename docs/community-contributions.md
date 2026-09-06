# Community contributions / 社区贡献

## Purpose / 目的

RevAgent welcomes voluntary, openly shareable computational-mathematics revision cases for future community calibration. A case may include a manuscript and review history only when every relevant rightsholder has authorized that sharing and the material has been appropriately deidentified.

RevAgent 欢迎自愿、可公开分享的计算数学返修案例，用于未来的社区校准。只有在所有相关权利人均已授权分享、且材料已经适当脱敏时，案例才可以包含稿件和审稿历史。

## Local preparation / 本地准备

1. Obtain and retain written permission from authors and, where applicable, editors, reviewers, publishers, and any data/code owners.
2. Remove personal data, submission identifiers, confidential correspondence, credentials, and non-shareable data.
3. Generate and complete a data card locally:

```powershell
revagent contribution-template --case-id community-001
```

4. Create a local metadata-only candidate package:

```powershell
revagent contribution-export --case-dir C:\path\to\deidentified_case --case-id community-001 --data-card C:\path\to\data_card.json --confirm
```

The command records the data card, safety scan, and file fingerprints under `.revagent/contribution_candidates/`. It does **not** copy manuscript text, reviewer comments, source code, or data, and it performs no upload.

该命令会在 `.revagent/contribution_candidates/` 中记录数据卡、安全扫描和文件指纹；它**不会**复制论文原文、审稿意见、代码或数据，也不会上传任何材料。

## Publication boundary / 公开边界

A local candidate package is not an approved public dataset. RevAgent does not verify deidentification, permission, copyright, or publication rights, and this repository currently has no automatic upload path for raw cases. Do not put raw manuscripts or reviews in a public issue, pull request, or repository branch until a maintainer-approved governance process exists.

本地候选包并不是获批的公开数据集。RevAgent 不验证脱敏、授权、版权或公开权利；当前仓库也没有原始案例的自动上传通道。在维护者批准治理流程之前，不要将原始稿件或审稿意见放入公开 issue、PR 或仓库分支。

## What can be shared now / 当前可分享内容

Share only the metadata candidate package after you have completed its data card and safety review. If a future governance process accepts an openly licensed case, it should publish a data card, permission record, deidentification report, and retention/access rules alongside the case.

完成数据卡与安全审阅后，当前只能分享元数据候选包。若未来治理流程接受开放许可的案例，应同时发布数据卡、授权记录、脱敏报告以及保留/访问规则。

## Claim-alignment evaluation intake

Use the local `alignment-case` workflow documented in
`docs/pre-submission-review.md` for claim-alignment evaluation cases. It
requires a completed contribution data card, two distinct pseudonymous
annotations, and explicit adjudication before a benchmark fixture can be
exported. Prefer `--claim-file` so deidentified claim text does not appear in
shell history. Export is local only and is not publication approval; RevAgent
does not verify permission, deidentification, expertise, or independence.

## Public-review silver benchmarks

When new private cases or human annotators are unavailable, use licensed public
peer-review records through the separate `public-review` workflow. It accepts
OpenReview, F1000Research, eLife, and PeerJ records only after recording HTTPS
source URLs, accepted per-record licenses, attribution, retrieval date, and the
licensed paper and review text. PubPeer and records with unclear manuscript
rights are not accepted.

Two isolated subagents may code findings and a third distinct subagent may
adjudicate them. Annotation JSON must cite a review ID and include an exact
excerpt from that review.

```powershell
revagent public-review init public-001 --record record.json --confirm
revagent public-review annotate public-001 --actor agent-a --model MODEL --run-id RUN_A --annotation agent-a.json
revagent public-review annotate public-001 --actor agent-b --model MODEL --run-id RUN_B --annotation agent-b.json
revagent public-review adjudicate public-001 --actor agent-c --model MODEL --run-id RUN_C --annotation adjudicated.json
revagent public-review report
```

Licensed OpenReview records can also be collected in a bounded batch. The fetcher
requires public `readers`, an explicit accepted paper license, at least two public
official reviews, and a computational-mathematics domain match. It never imports
confidential replies. Every import and exclusion is recorded in
`.revagent/public_review_records/last_fetch_manifest.json`.

```powershell
revagent public-review fetch-openreview `
  --venue-id "VENUE_ID_FROM_OPENREVIEW" `
  --domain numerical-pde `
  --limit 10 `
  --confirm
```

Available profiles are `computational-math`, `numerical-pde`, `optimization`, and
`scientific-ml`. The hard maximum is 50 submissions per run. For reproducible,
offline evaluation, pass `--fixture openreview-api-snapshot.json`; the fixture must
contain `submissions: {notes: [...]}` and `replies_by_forum: {FORUM: {notes: [...]}}`.
`--confirm` means the operator has verified that the venue records are public and
that OpenReview's review license applies. Paper licenses are still checked per note.

The report is labelled
`public_review_agent_coded_proxy_metrics_not_expert_calibrated` and cannot enter
the human `history-quality-publish` path. This provides a reproducible
public-record silver benchmark; it does not substitute subagents for experts.

## Revision-chain corpus audit

Use the separate metadata-only audit before treating a local or public record as
an end-to-end revision case. Local manuscript and response text remains in place;
the generated report stores paths, sizes, and SHA-256 fingerprints only.

```powershell
revagent revision-corpus audit --cases-dir Cases `
  --case Case1=1 --case Case2=2 --case Case3=2
```

For licensed public records, declare every manuscript version and the associated
review/response artifact in a catalog, download them to a non-versioned cache,
then verify the cache. Fetching is restricted to provider-owned HTTPS hosts, is
bounded to 50 MiB per artifact, and requires explicit confirmation:

```powershell
revagent revision-corpus fetch-public `
  --catalog benchmarks/revision-corpus/public-candidates.json `
  --cache-dir .tmp --confirm

revagent revision-corpus audit-public `
  --catalog benchmarks/revision-corpus/public-candidates.json `
  --cache-dir .tmp
```

A case is counted as `verified_complete` only when the cache contains at least
one more distinct manuscript version than review rounds and a review/response
artifact. Discovery metadata alone is reported as `candidate_pending_fetch`.
Acceptance remains separate from item-level expert calibration.
