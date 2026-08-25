# Dashboard guide / Dashboard 指南

## Static cockpit / 静态 cockpit

Run one of the following commands from a prepared revision workspace:

```powershell
revagent cockpit --lang en
revagent cockpit --lang zh
```

The commands create `.revagent/author_cockpit.html` and `.revagent/author_cockpit.zh.html`. Open the chosen file in a browser. It is a local HTML snapshot showing review items, lane and risk, response/evidence/PDF status, blockers, and pending author actions.

上述命令分别生成 `.revagent/author_cockpit.html` 和 `.revagent/author_cockpit.zh.html`。请在浏览器中打开相应文件。它是本地 HTML 快照，展示返修事项、类别与风险、回复/证据/PDF 状态、阻塞项和待处理的作者操作。

## Local browser service / 本地浏览器服务

```powershell
revagent serve
```

The service binds only to `127.0.0.1:8765` by default. Open:

- `http://127.0.0.1:8765/cockpit?lang=en`
- `http://127.0.0.1:8765/cockpit?lang=zh`
- `http://127.0.0.1:8765/status` for local project status
- `http://127.0.0.1:8765/healthz` for a local health check

默认服务只绑定 `127.0.0.1:8765`，不会公开到局域网或互联网。可打开上述 cockpit、状态和健康检查端点。

`revagent serve` initializes the local project runtime and continues running until interrupted. Use `Ctrl+C` in its terminal, or run `revagent project-stop` from another terminal in the same workspace to request shutdown. Use `revagent project-status` and `revagent service-health` to inspect its recorded state.

`revagent serve` 会初始化本地项目运行时，并持续运行直到被中断。可在运行它的终端按 `Ctrl+C`，或在同一工作区的另一终端运行 `revagent project-stop` 请求停止；使用 `revagent project-status` 和 `revagent service-health` 查看记录状态。

## Boundary / 边界

The dashboard is an evidence overview, not a proof checker, experiment validator, or submission system. It reads and writes only the local workspace artifacts.

Dashboard 是证据总览，不是证明检查器、实验验证器或投稿系统；它只读取和写入本地工作区工件。

