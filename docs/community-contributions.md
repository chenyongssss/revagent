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

