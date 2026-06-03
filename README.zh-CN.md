# Claude Status Board · Claude 状态看板

[English](README.md) | **简体中文**

把任何一台闲置平板（哪怕是远古的安卓 6.0）变成 [Claude Code](https://claude.com/claude-code) 的**实体状态红绿灯 + 远程审批面板**。

每个项目一行,隔着房间一眼就知道 Claude 在干嘛 —— 🟢 工作中、🌙 空闲、🔴 需要你。当 Claude 想跑命令或改文件时,看板会**变红并显示完整命令 / diff**,配上**批准 / 拒绝**两个大按钮。点一下就放行,不用伸手去够键盘。

不刷机、不装 App、不上云。主机端是**纯 Python 标准库**,平板端就一个 HTML 页面,靠 Claude Code 的 hooks 串起来。

![screenshot](docs/screenshot.png)

## 为什么做这个

你开了个耗时的 Claude Code 任务,然后扭头去忙别的。它跑完了吗?是不是卡在等你授权?同时开几个项目时更乱。这块牌子就是放你旁边的物理信号灯:

- **🟢 工作中** —— 某个会话正在跑工具
- **🔴 需要你** —— 在等权限确认或等你输入
- **🌙 空闲** —— 干完了 / 等你下一条消息
- **🔴 + 按钮** —— 一个受控操作被拦下等你批准(并显示命令 / diff)

每个 Claude Code 会话(按 `session_id` 区分、用工作目录名标注)各占一行,谁需要你就排到最上面。

## 工作原理

```
Claude Code 会话                                平板 / 任意浏览器
  hooks ── slot.py ─────────▶  slots/<sid>.json
           approve_gate.py ──▶  (写入红灯 + req)        ┌────────────────────┐
                                                        │  GET /  (看板页面)  │
  server.py  :8088  ── 聚合 slots/ ───── /status ──────▶│  每秒轮询           │
                     ◀── decisions/<req> ◀──── /decide ─│  [批准] [拒绝]      │
           approve_gate.py 读裁决 → allow / deny         └────────────────────┘
```

- **`server.py`** —— 零依赖 HTTP 服务。`/` 出看板页面,`/status` 聚合各会话状态文件,`/decide` 记录批准/拒绝。
- **`slot.py`** —— hook 辅助脚本。Claude Code 每触发一个事件,就把该会话状态写到 `slots/<session_id>.json`。
- **`approve_gate.py`** —— `PreToolUse` hook。受控工具会在看板上亮红并**阻塞等你点**(超时则安全回退到键盘确认)。
- 页面是纯 **ES5 + XHR**,所以连安卓 5/6 那种老 WebView 都能渲染。

## 安装

依赖:运行 Claude Code 的机器上有 **Python 3**(只用标准库)。一台平板/手机/旧笔记本当显示屏。如果显示屏在另一台设备上,用 [Tailscale](https://tailscale.com/)（或任意内网）打通。

```bash
git clone https://github.com/ychen0606/claude-status-board.git
cd claude-status-board
./start.sh            # 在 :8088 后台启动看板
./install.sh          # 打印填好绝对路径的 hooks 配置
```

1. **接上 hooks。** 运行 `./install.sh`,把打印出来的 `"hooks"` 块合并进 `~/.claude/settings.json`（参考 [`examples/hooks.json`](examples/hooks.json)）。新开的 Claude Code 会话会自动生效。
2. **打开看板** `http://<主机>:8088/`,用你想当显示屏的设备访问。页面每秒自刷。
3. **开机自启**（可选）:`crontab -e` → 加一行 `@reboot /claude-status-board的绝对路径/start.sh`。

### 用平板做常显屏

1. 让平板进同一个内网(比如装 **Tailscale** App、登同一个账号),这样它能访问主机 IP。
2. 装 **Fully Kiosk Browser**,Start URL 填 `http://<主机>:8088/`,打开 *Keep Screen On*、*Start on Boot*、全屏。
3. 平板上:开发者选项 → **保持唤醒状态**(充电时永不息屏),休眠时间调到最长,一直插着充电。

## 远程审批（网关）

默认关闭。用一个开关文件启用:

```bash
touch gate_enabled    # 开:受控工具会等你在看板上点
rm    gate_enabled    # 关:看板变成纯显示
```

开启后,`approve_gate.py` 会拦截这些工具的 `PreToolUse`（可在文件顶部的 `GATED_TOOLS` 配置）:

`Bash`、`Write`、`Edit`、`MultiEdit`、`NotebookEdit`

- **已在你 Claude Code 白名单里的 Bash 命令照样秒跑** —— 网关会读 `~/.claude/settings.local.json`,跳过你已经批准过的,只在真正新的操作上拦你。
- 看板会显示完整命令、文件内容预览、或红/绿 diff,配 **批准 / 拒绝**。
- **安全保证**:绝不自动放行。`TIMEOUT`(默认 90 秒)内没人点,就回退到正常的键盘权限确认。出任何错都回退,绝不放行。

在 `approve_gate.py` 顶部可调:`GATED_TOOLS`、`TIMEOUT`。不想拦文件改动,就从 `GATED_TOOLS` 删掉 `Write`/`Edit`。

## 配置

| 项目 | 在哪改 |
|------|--------|
| 端口 | 环境变量 `CLAUDE_BOARD_PORT`（默认 `8088`） |
| 过期行清理 | `server.py` 里的 `STALE`（默认 1800 秒） |
| 受控工具 / 审批超时 | `approve_gate.py` 里的 `GATED_TOOLS`、`TIMEOUT` |
| UI 文案 / 配色 | `server.py` 内联的 `HTML` 块 |

## 安全

- 服务绑定 `0.0.0.0` 且**无鉴权**。只在可信/内网里跑(Tailscale、防火墙后的局域网等)。**不要把 8088 端口暴露到公网** —— 网关开启时,任何能访问 `/decide` 的人都能批准操作。
- 看板会显示 Claude 即将做的事(命令、文件内容)。把这块屏当成你的终端来看待。

## 许可证

MIT —— 见 [LICENSE](LICENSE)。

---

*用 Claude Code 构建。*
