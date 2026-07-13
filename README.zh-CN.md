# RevAgent

[English](README.md)

RevAgent 是面向计算数学论文修订的本地优先 review-agent 工具。它把 LaTeX 稿件、审稿意见、证明检查、代码与实验约束组织为可审查的工作区工件，帮助作者团队推进返修与回复信。

## 状态与边界

当前版本为 alpha。RevAgent 不验证数学正确性，不自动批准证明、实验结果或稿件修改，不自动关闭审稿项，也不会提交论文。

默认所有工作在本地完成。启用外部 Codex 或 OpenAI-compatible provider 前，作者必须确认数据政策。语义 rubric 评审可能发送完整项目快照，但只会在任务级、一次性、限时授权后执行。

## 安装

```powershell
python -m pip install -e .[dev]
```

## 基本流程

```powershell
cd path\to\latex-paper
revagent init --journal siam --tex-root . --main-tex paper.tex
revagent ingest-comments reviewer_comments.md
revagent project-init
revagent project-cycle --workers 2
revagent project-status
revagent review-evaluate R001
```

常规返修流程也可使用 `plan`、`analyze-review`、`plan-item`、`draft`、`proof-plan`、`experiment-contract`、`provenance` 和 `readiness`。所有结果均写入 `.revagent/`，以 JSON/Markdown 工件保留审计线索。

## 项目运行时

`revagent serve` 启动仅绑定本机回环地址的项目运行时；它只推进可逆的分析、规划与证据收集任务。可用命令包括：

```powershell
revagent project-pause
revagent project-resume
revagent project-recover
revagent service-health
revagent project-stop
```

运行时使用 SQLite 保存任务图、lease、事件、证据、作者门禁和远程授权。证明批准、实验结果确认、候选修改应用、审稿项关闭始终需要作者显式操作。

## 专业 Review Worker

RevAgent 可为审稿项创建文本、证明、代码与实验 worker。worker 在完整项目快照中运行，不直接修改父项目；结果通过 bundle 汇聚，并对相同变更路径生成冲突记录。

```powershell
revagent worker-plan R001 --backend codex
revagent review-sandbox-create W-R001-proof
revagent review-worker-start W-R001-proof
revagent review-worker-collect W-R001-proof
```

实验 worker 必须先获授权，授权记录绑定命令、快照、工作目录、超时、CPU、内存和预期工件：

```powershell
revagent experiment-authorize-worker W-R002-experiment `
  --command "python scripts/run_demo.py" --timeout-seconds 600 `
  --cpu 1 --memory-mb 1024 --artifact results/demo.csv
revagent experiment-start-worker EXP-001
```

实验执行结果仅是待作者确认的证据，不会自动写入论文或形成科学结论。

## 语义评审与远程授权

先运行确定性证据检查，再对同一任务创建一次性授权并运行 rubric：

```powershell
revagent authorize-remote R001:collect_evidence `
  --provider openai-compatible --model model-name --purpose rubric `
  --artifact-class project_snapshot --ttl-minutes 30
revagent review-rubric R001 --authorization 1
```

rubric 输出覆盖度、回复准确性、稿件定位、证据支持、矛盾和不确定性分数。它只能将项目标记为“可供作者关闭”，不会自动关闭审稿项。

## 基准与验证

仓库仅包含合成 benchmark。真实案例必须在获得许可、完成脱敏审查、附带数据卡与预期标签后单独发布。

```powershell
revagent benchmark-run --fixture benchmarks/synthetic/basic
python -m pytest
```

CI 覆盖 Windows、Linux 和 macOS。受保护的周度 provider E2E 只使用合成项目，不上传原始 prompts、模型响应或私有稿件。

## 安全与贡献

请阅读 [SECURITY.md](SECURITY.md) 了解本地文件、外部 provider 和完整快照传输的边界；贡献规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。
