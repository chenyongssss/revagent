# RevAgent

<p align="center"><strong>本地优先 · 可审计 · 人工签核</strong></p>

<p align="center"><a href="README.md">English</a> · <a href="#快速开始">快速开始</a> · <a href="docs/advanced-usage.md">高级用法</a> · <a href="SECURITY.md">安全政策</a></p>

RevAgent 是一个面向计算数学论文返修的本地优先、可审计助手。它把编辑和审稿意见转化为可追踪的审稿事项、源码位置、返修计划、证据记录、回复草稿和明确的作者决策。

> [!NOTE]
> 适用于 *SISC*、*SINUM*、*Mathematics of Computation*、*IMA Journal of Numerical Analysis*、*Journal of Computational Physics* 和 *Numerische Mathematik* 等期刊中常见的返修工作流。这些仅是代表性使用场景，不代表期刊认可或投稿保证。

<p align="center"><img src="docs/assets/revagent-workflow.png" alt="RevAgent 工作流：审稿意见经过可审计的返修图谱、证据检查、本地保护与人工签核。" width="1200"></p>

<p align="center"><em>审稿意见 → 返修图谱 → 证据 → 人工审阅 → 回复包</em></p>

## 一览

| 材料 | 支持方式 |
| --- | --- |
| 稿件 | 完整 LaTeX 源码树。RevAgent 可索引标签、定理类环境、引用和源码位置；v0.1 的候选修改与编译检查仅支持 LaTeX。 |
| 审稿意见 | **优先：** `.tex` 或 `.md`，直接解析；`.txt` 也可直接解析；`.docx` 和文本型 `.pdf` 会先在本地转换为可审计的 Markdown 副本，再进行解析。 |
| 编码 Agent | 任意编码 Agent 都可协助部署 RevAgent 并执行本地工作流；可选的外部自动化命令（`revagent run` 与 Codex review worker）目前需要 Codex CLI。 |

所有材料均保留在本地。转换后的审稿意见副本、原文件哈希和转换记录均写入 `.revagent/`；原文件不会被修改或上传。

> [!TIP]
> 为获得最清晰的事项边界和源码定位，建议将审稿意见保存为 TeX 或 Markdown。

## 快速开始

### 1. 安装

在任意具备 Python 3.10+ 的本地终端中运行；也可以使用 Codex、Claude Code 或其他编码 Agent 提供的终端：

```powershell
git clone https://github.com/chenyongssss/revagent.git
cd revagent
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

macOS 或 Linux 请使用 `source .venv/bin/activate` 激活环境。

**使用编码 Agent：** Codex、Claude Code 或其他本地编码 Agent 都可以打开克隆后的 `revagent` 文件夹，并代你执行上述安装命令。完成后，标准本地工作流不需要 Agent 环境。例外是可选的 `revagent run` 和 Codex review-worker 自动化功能：它们目前需要安装 Codex CLI。

### 2. 准备一个返修工作区

请从稿件的副本开始：

```text
my-paper-review/
  manuscript/
    paper.tex
    sections/
    bibliography.bib
  reviewer_comments.tex   # 也可为 .md、.txt、.docx、.pdf
```

将完整 LaTeX 源码树放入 `manuscript/`，包括被 `\input` 或 `\include` 引用的文件。推荐使用 TeX 或 Markdown 审稿意见，因为系统可直接保留其事项边界和行号位置。

### 3. 第一次运行

进入 `my-paper-review/` 后执行：

```powershell
revagent init --journal siam --tex-root manuscript --main-tex paper.tex
revagent ingest-comments reviewer_comments.tex
revagent plan
revagent draft
revagent cockpit --lang zh
revagent validate
```

- `init`：创建 `.revagent/` 并指定主稿入口。
- `ingest-comments`：导入编辑和审稿请求；DOCX/PDF 导入还会生成本地标准化 Markdown 记录。
- `plan`：将请求关联到 LaTeX 位置，并记录返修或证据义务；不会修改稿件。
- `draft`：生成可审阅的回复和候选修改工件；不会应用修改。
- `cockpit --lang zh`：生成中文本地总览；使用 `--lang en` 可生成英文版。
- `validate`：检查工作区状态、溯源和追踪关系；只有在明确需要检查 LaTeX 编译时才添加 `--compile`。

**结果：** 在 `.revagent/` 查看生成的本地记录；准备逐项审阅时，可使用 cockpit 或高级命令。

## 安全边界

> [!IMPORTANT]
> RevAgent 不会认证证明、稳定性、收敛性、实验、回复事实或最终 PDF；这些决定必须由作者或子领域专家签核。候选修改必须先供人工审阅，绝不会被静默应用。

## 更多内容

- [完整使用指南](docs/user-guide.zh-CN.md)：完整工作流、生成工件、单项审阅、验证和交接。
- [Dashboard 指南](docs/dashboard.md)：静态 cockpit、本地浏览器服务、端点和生命周期。
- [社区贡献](docs/community-contributions.md)：如何在不意外暴露材料的前提下准备可公开分享的案例。
- [高级用法](docs/advanced-usage.md)：紧凑命令参考、开发和发布验证。
- [安全政策](SECURITY.md)：隐私与执行边界。
- [贡献指南](CONTRIBUTING.md) 和 [发布说明](RELEASE_NOTES.md)：项目协作与版本限制。
