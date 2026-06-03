# Claude Status Board

**English** | [简体中文](README.zh-CN.md)

Turn any spare tablet (even an ancient Android 6.0 one) into a desk/wall **status light + remote approval panel** for [Claude Code](https://claude.com/claude-code).

A row per project shows what Claude is doing — 🟢 working, 🌙 idle, 🔴 needs you — at a glance from across the room. When Claude wants to run a command or edit a file, the board turns **red and shows the exact command / diff** with **Approve / Reject** buttons. Tap to let it through; no need to reach for the keyboard.

No flashing, no app, no cloud. **Pure Python standard library** on the host, a single HTML page on the tablet, glued together by Claude Code hooks.

![screenshot](docs/screenshot.png)

## Why

You start a long Claude Code task and look away. Did it finish? Is it stuck waiting for permission? With several projects running in parallel it's worse. This puts a physical traffic light next to you:

- **🟢 working** — a session is actively running tools
- **🔴 needs you** — waiting on a permission prompt or your input
- **🌙 idle** — finished / waiting for your next message
- **🔴 + buttons** — a guarded action is paused for your approval (with the command/diff shown)

Each Claude Code session (keyed by `session_id`, labeled by its working directory) gets its own row, sorted so whatever needs you floats to the top.

## How it works

```
Claude Code session(s)                          Tablet / any browser
  hooks ── slot.py ─────────▶  slots/<sid>.json
           approve_gate.py ──▶  (writes red + req)        ┌────────────────────┐
                                                          │  GET /  (dashboard)│
  server.py  :8088  ── aggregates slots/ ───── /status ──▶│  polls every 1s    │
                     ◀── decisions/<req> ◀──── /decide ───│  [Approve][Reject] │
           approve_gate.py reads decision → allow / deny  └────────────────────┘
```

- **`server.py`** — zero-dependency HTTP server. Serves the dashboard at `/`, aggregates the per-session state files at `/status`, and records approve/reject taps at `/decide`.
- **`slot.py`** — a hook helper. On each Claude Code event it writes that session's state to `slots/<session_id>.json`.
- **`approve_gate.py`** — a `PreToolUse` hook. For guarded tools it shows the action on the board and **blocks until you tap** (or times out safely back to the keyboard).
- The web page is plain **ES5 + XHR**, so it renders on WebView as old as Android 5/6.

## Install

Requirements: **Python 3** (stdlib only) on the machine running Claude Code. A tablet/phone/old laptop with any browser for the display. [Tailscale](https://tailscale.com/) (or any private network) if the display is on a different device.

```bash
git clone https://github.com/ychen0606/claude-status-board.git
cd claude-status-board
./start.sh            # starts the board on :8088 (detached)
./install.sh          # prints the hooks block with the correct absolute path
```

1. **Wire the hooks.** Run `./install.sh` and merge the printed `"hooks"` block into `~/.claude/settings.json` (see [`examples/hooks.json`](examples/hooks.json)). New Claude Code sessions pick it up automatically.
2. **Open the board** at `http://<host>:8088/` from the device you want to use as the display. The page auto-refreshes every second.
3. **Autostart on boot** (optional): `crontab -e` → add `@reboot /absolute/path/to/claude-status-board/start.sh`.

### Use a tablet as an always-on display

1. Put the tablet on the same private network (e.g. install the **Tailscale** app, log in to the same account) so it can reach the host's IP.
2. Install **Fully Kiosk Browser**, set Start URL to `http://<host>:8088/`, and enable *Keep Screen On*, *Start on Boot*, and fullscreen.
3. On the tablet: Developer Options → **Stay awake** (screen never sleeps while charging), set display timeout to max, keep it plugged in.

## Remote approval (the gate)

Off by default. Enable it with a flag file:

```bash
touch gate_enabled    # arm: guarded tools wait for a tap on the board
rm    gate_enabled    # disarm: board becomes display-only
```

When armed, `approve_gate.py` intercepts `PreToolUse` for these tools (configurable via `GATED_TOOLS` at the top of the file):

`Bash`, `Write`, `Edit`, `MultiEdit`, `NotebookEdit`

- **Bash commands already on your Claude Code allow-list run instantly** — the gate reads `~/.claude/settings.local.json` and skips anything you've already approved, so it only stops on genuinely new actions.
- The board shows the full command, file content preview, or red/green diff, with **Approve / Reject**.
- **Safety:** it never auto-approves. If no one taps within `TIMEOUT` (default 90s) it falls back to the normal keyboard permission prompt. Any error → fall back, never allow.

Tune at the top of `approve_gate.py`: `GATED_TOOLS`, `TIMEOUT`. To stop gating file edits, remove `Write`/`Edit` from `GATED_TOOLS`.

## Configuration

| What | Where |
|------|-------|
| Port | `CLAUDE_BOARD_PORT` env var (default `8088`) |
| Stale row timeout | `STALE` in `server.py` (default 1800s) |
| Guarded tools / approval timeout | `GATED_TOOLS`, `TIMEOUT` in `approve_gate.py` |
| UI strings / colors | inline in `server.py` (the `HTML` block) |

## Security

- The server binds `0.0.0.0` and has **no authentication**. Run it on a trusted/private network only (Tailscale, LAN behind a firewall, etc.). **Do not expose port 8088 to the public internet** — anyone who can reach `/decide` can approve actions when the gate is armed.
- The board displays whatever Claude is about to do (commands, file contents). Treat the screen as you would your terminal.

## License

MIT — see [LICENSE](LICENSE).

---

*Built with Claude Code. UI strings are in Chinese; PRs to internationalize are welcome.*
