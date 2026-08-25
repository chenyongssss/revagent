# RevAgent 完整使用指南

[English](user-guide.md) · [Dashboard 指南](dashboard.md) · [社区贡献](community-contributions.md)

## 1. RevAgent 的作用

RevAgent 是计算数学论文返修的本地、可审计工作区。它把每条编辑或审稿请求关联到稿件位置、返修计划、证据、回复草稿和明确的作者决定；它不会认证数学结论，也不会提交稿件。

稿件应使用完整的 LaTeX 源码树。审稿意见可为 `.tex`、`.md` 或 `.txt`；`.docx` 与文本型 `.pdf` 会先在本地标准化到 `.revagent/imports/`，再进行解析。

## 2. 创建并运行工作区

每轮返修使用一个独立文件夹，并从稿件副本开始：

```text
my-paper-review/
  manuscript/
    paper.tex
    sections/
  reviewer_comments.tex
```

进入 `my-paper-review/` 后执行：

```powershell
revagent init --journal siam --tex-root manuscript --main-tex paper.tex
revagent ingest-comments reviewer_comments.tex
revagent plan
revagent draft
revagent cockpit --lang zh
revagent validate
```

将 `reviewer_comments.tex` 替换为真实文件名。`init` 创建 `.revagent/`；`ingest-comments` 为每项请求建立追踪事项；`plan` 将事项关联到 LaTeX 树；`draft` 生成不会自动应用的候选工件；`validate` 检查已记录的状态。

## 3. 查看生成工件

| 工件 | 用途 |
| --- | --- |
| `.revagent/review_items.json` | 规范的编辑/审稿事项、风险和来源定位。 |
| `.revagent/comment_import.json` | 原始审稿意见哈希；DOCX/PDF 还包含本地标准化副本。 |
| `.revagent/revision_plan.md` | 工作区级的返修、证明、实验和开放问题计划。 |
| `.revagent/response_letter.md` | 回复结构草稿；仍必须由作者审阅。 |
| `.revagent/author_cockpit.zh.html` | 中文静态 dashboard；英文版为 `author_cockpit.html`。 |
| `.revagent/revision_readiness.md` | 缺失证据、过期工作、豁免和阻塞性人工操作。 |

## 4. 逐项处理

| 目标 | 命令 |
| --- | --- |
| 查看事项 | `revagent inspect R001` |
| 创建详细计划 | `revagent plan-item R001` |
| 查看审稿意图分析 | `revagent review-analysis R001` |
| 规划并审计证明请求 | `revagent proof-plan R001`，再执行 `revagent proof-audit R001` |
| 记录实验要求 | `revagent experiment-contract R002` |
| 追踪回复、稿件、证据和 PDF 状态 | `revagent response-trace R001` |
| 查看就绪状态 | `revagent readiness` |

候选修改和生成的回复文字都只是建议。请先审阅；需要作者文字时补充作者文字；只有完成相应人工审阅后才能使用批准命令。

## 5. 验证与交接

每次有意义的改动后运行 `revagent validate`。只有在本地具备 LaTeX 工具链且明确需要编译检查时才添加 `--compile`。最终交接前运行 `revagent submit-pack --dry-run`，并解决全部 blocker、过期工件、豁免和升级事项。

## 6. Dashboard 与可选自动化

使用 `revagent cockpit --lang en` 或 `revagent cockpit --lang zh` 生成静态本地 dashboard。本地浏览器服务及其端点见 [Dashboard 指南](dashboard.md)。常规工作流不需要 coding agent 环境；只有可选的外部 runner 和 Codex review worker 功能需要 Codex CLI。

## 7. 完整命令参考

`revagent --help` 列出全部已安装命令。使用高级、远程、worker、benchmark、runtime 或自动化命令前，请先运行 `revagent <command> --help`。这些接口有意不属于第一次返修的必经流程。

