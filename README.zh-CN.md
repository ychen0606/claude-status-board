# Claude Status Board

[English](README.md) | 简体中文

给 Claude Code 用的一个状态看板。找台旧平板放桌上或挂墙上,隔着房间就能看到 Claude 在干嘛 —— 在跑、空闲、还是卡在等你。要跑命令或改文件的时候,直接在平板上点批准或拒绝,不用切回终端。

主机这边跑一个小的 Python 服务,只用标准库。平板那边就开一个网页。中间靠 Claude Code 的 hooks 连起来。页面是老式 ES5 写的,安卓 6.0 的旧浏览器也能开。

![截图](docs/screenshot.png)

## 几种状态

同时开几个会话时,每个占一行,按 session 区分,标题用它的工作目录名:

- 绿色 —— 在跑
- 灰色 —— 空闲,或者在等你下一条消息
- 红色 —— 在等你(权限确认或输入)
- 红色带按钮 —— 有个操作被拦下了等你批,旁边显示具体命令或 diff

谁需要你,谁排前面。

## 原理

```
Claude Code 会话                                平板 / 任意浏览器
  hooks ── slot.py ─────────▶  slots/<sid>.json
           approve_gate.py ──▶  (写入红灯 + req)        ┌────────────────────┐
                                                        │  GET /  (看板页面)  │
  server.py  :8088  ── 聚合 slots/ ───── /status ──────▶│  每秒轮询           │
                     ◀── decisions/<req> ◀──── /decide ─│  [批准] [拒绝]      │
           approve_gate.py 读裁决 → allow / deny         └────────────────────┘
```

`server.py` 起一个 HTTP 服务,出页面、把各会话的状态文件聚合起来。`slot.py` 是个 hook,每次事件把当前会话的状态写到 `slots/<session_id>.json`。`approve_gate.py` 挂在 `PreToolUse` 上,受控的操作会卡住等你点,点了或超时再放行。

## 安装

主机上要有 Python 3(标准库就够),再找台有浏览器的设备当显示屏。显示端不在同一台机器的话,把两边放进同一个内网,用 Tailscale 比较省事。

```
git clone https://github.com/ychen0606/claude-status-board.git
cd claude-status-board
./start.sh      # 在 :8088 起服务
./install.sh    # 打印带绝对路径的 hooks 配置
```

把 `install.sh` 打印的 `"hooks"` 块塞进 `~/.claude/settings.json`,新开的会话就生效了。然后浏览器打开 `http://主机:8088/`。想开机自启,crontab 里加一行 `@reboot /绝对路径/start.sh`。

### 平板当常显屏

平板装 Tailscale 进同一个网,再装 Fully Kiosk Browser,把网址设成 Start URL,打开常亮、开机自启、全屏。系统开发者选项里把"保持唤醒状态"打开,这样充电时不会息屏。插着电就一直亮着了。

## 远程审批

默认不开。

```
touch gate_enabled   # 开
rm gate_enabled      # 关
```

开了之后,`approve_gate.py` 会拦 `Bash`、`Write`、`Edit`、`MultiEdit`、`NotebookEdit` 这几类(改 `GATED_TOOLS` 可调)。已经在你 Claude Code 白名单里的 Bash 命令照跑不拦 —— 它会读 `~/.claude/settings.local.json`,只在你没批准过的新操作上停。

平板上把命令、文件预览或者 diff 显示出来,点批准或拒绝。`TIMEOUT`(90 秒)内没人点,就退回键盘那边正常确认 —— 不会自己放行,也不会卡死。嫌改文件也要批太烦,把 `Write`/`Edit` 从 `GATED_TOOLS` 里删掉就只拦 Bash。

## 配置

| 项目 | 在哪改 |
|------|--------|
| 端口 | 环境变量 `CLAUDE_BOARD_PORT`(默认 `8088`) |
| 过期行清理 | `server.py` 里的 `STALE`(默认 1800 秒) |
| 受控工具 / 审批超时 | `approve_gate.py` 里的 `GATED_TOOLS`、`TIMEOUT` |
| 界面文案 / 配色 | `server.py` 里的 `HTML` 块 |

## 安全

服务绑在 `0.0.0.0` 上,没有鉴权,所以只在可信的内网里跑 —— Tailscale、防火墙后面的局域网这种。别把 8088 开到公网:网关开着的时候,谁能访问 `/decide` 谁就能批。屏幕上会显示 Claude 要执行的命令和文件内容,当成你的终端看就行。

## 许可证

MIT,见 [LICENSE](LICENSE)。
