# RevAgent

[English](README.md)

RevAgent 是一个面向计算数学论文返修的本地优先、可审计助手。它把编辑和审稿意见转化为可追踪的审稿事项、源码位置、返修计划、证据记录、回复草稿和明确的作者决策。

适用于 *SIAM Journal on Scientific Computing (SISC)*、*SIAM Journal on Numerical Analysis (SINUM)*、*Mathematics of Computation*、*IMA Journal of Numerical Analysis*、*Journal of Computational Physics* 和 *Numerische Mathematik* 等期刊中常见的返修工作流。这些仅是代表性使用场景，不代表期刊认可或投稿保证。

![RevAgent 工作流：审稿意见经过可审计的返修图谱、证据检查、本地保护与人工签核。](docs/assets/revagent-workflow.png)

## 支持范围

| 材料 | 支持方式 |
| --- | --- |
| 稿件 | 完整 LaTeX 源码树。RevAgent 可索引标签、定理类环境、引用和源码位置；v0.1 的候选修改与编译检查仅支持 LaTeX。 |
| 审稿意见 | **优先：** `.tex` 或 `.md`，直接解析；`.txt` 也可直接解析；`.docx` 和文本型 `.pdf` 会先在本地转换为可审计的 Markdown 副本，再进行解析。 |

所有材料均保留在本地。转换后的审稿意见副本、原文件哈希和转换记录均写入 `.revagent/`；原文件不会被修改或上传。

## 1. 安装

在 Codex 工作区终端或任意具备 Python 3.10+ 的本地终端中运行：

```powershell
git clone https://github.com/chenyongssss/revagent.git
cd revagent
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

macOS 或 Linux 请使用 `source .venv/bin/activate` 激活环境。

## 2. 准备一个返修工作区

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

## 3. 第一次运行

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

## 安全边界

RevAgent 不会认证证明、稳定性、收敛性、实验、回复事实或最终 PDF；这些决定必须由作者或子领域专家签核。候选修改必须先供人工审阅，绝不会被静默应用。

## 更多内容

单项审阅命令、本地浏览器界面、社区校准、开发和发布验证见[高级用法](docs/advanced-usage.md)。隐私与执行边界见[安全政策](SECURITY.md)，项目协作见[贡献指南](CONTRIBUTING.md)，版本限制见[发布说明](RELEASE_NOTES.md)。
