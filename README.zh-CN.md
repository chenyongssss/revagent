# RevAgent

[English](README.md)

RevAgent 将 LaTeX 稿件和审稿意见整理为可审计的本地工件：审稿事项、源码定位、返修计划、回复草稿、证据记录和作者决策。它帮助作者检查返修过程，而不是取代作者或子领域专家。

## 安装

```powershell
python -m pip install -e .[dev]
```

需要 Python 3.10 或更高版本。

## 从这里开始

在 LaTeX 项目副本中运行：

```powershell
revagent init --journal siam --tex-root . --main-tex paper.tex
revagent ingest-comments reviewer_comments.md
revagent plan
revagent draft
revagent cockpit
revagent cockpit --lang zh
revagent validate
```

所有生成记录都保存在 `.revagent/`。在修改稿件前，请先审阅回复草稿和候选修改。

## 日常工作流

| 目标 | 命令 |
| --- | --- |
| 查看一条审稿事项 | `revagent inspect R001` |
| 创建或查看单项计划 | `revagent plan-item R001` / `revagent review-analysis R001` |
| 审计证明类请求 | `revagent proof-plan R001`，再运行 `revagent proof-audit R001` |
| 记录实验复现约束 | `revagent experiment-contract R002` |
| 查看追踪关系和阻塞项 | `revagent response-trace` / `revagent readiness` |
| 打开本地总览 | `revagent cockpit --lang en` / `revagent cockpit --lang zh` |
| 检查最终交接包 | `revagent submit-pack --dry-run` |

使用 `revagent --help` 查看完整命令，使用 `revagent <command> --help` 查看具体参数。CLI 仍保留运行时、worker、基准和自动化等高级接口，供受控集成或脚本调用；首次返修并不需要使用它们。

如需本地浏览器界面，运行 `revagent serve`，然后打开 `http://127.0.0.1:8765/cockpit?lang=en` 或 `http://127.0.0.1:8765/cockpit?lang=zh`。

## 安全边界

- 证明、稳定性、收敛性、实验、回复事实和最终 PDF 必须由作者或子领域专家显式签核。
- 候选修改必须先供人工审阅，绝不会被静默应用。
- 实验必须显式授权；其输出是待确认的证据，而不是自动成立的科学结论。
- 远程 provider 默认关闭。启用后也需要针对任务、用途和材料类别的一次性限时授权。
- 本地 cockpit、验证、溯源和 readiness 报告会显式显示缺失、过期、豁免与升级事项。

完整的隐私与执行边界见 [SECURITY.md](SECURITY.md)。

## 社区校准

仓库只包含合成 fixtures。若你希望准备一个自愿贡献的案例，先生成数据卡模板，再导出一个**仅本地的元数据候选包**：

```powershell
revagent contribution-template --case-id community-001
revagent contribution-export --case-dir C:\path\to\deidentified_case --case-id community-001 --data-card C:\path\to\data_card.json --confirm
```

该导出包只包含数据卡、安全扫描和文件指纹；绝不复制论文原文、审稿意见、代码或数据。RevAgent 不验证脱敏或发表权利，任何分享仍需人工治理审核。

## 开发与发布状态

```powershell
python -m pytest
```

CI 覆盖 Windows、Linux 和 macOS。发布资产附带校验和、SPDX SBOM 和 GitHub 构建证明。v0.1.0 的限制与验证方法见 [RELEASE_NOTES.md](RELEASE_NOTES.md)。

更多内容：[演示项目](examples/latex_revision_demo/)、[贡献指南](CONTRIBUTING.md)、[安全政策](SECURITY.md) 和 [变更日志](CHANGELOG.md)。
