# Windows tray indicator

Prefer the taskbar over a tablet or a desk light? This variant shows the same
aggregated state as a single colored dot in the Windows notification area. It
polls the board server's `/status` endpoint and never touches the server.

- red (blinking) — a session is waiting on you (permission / input)
- green — a session is working
- grey — all idle / no sessions
- dark grey — can't reach the board server

Hover for a tooltip (most urgent project + 5h/weekly usage quota). Right-click
to open the web board or quit.

## Install

Install Python 3.9+ on Windows, then:

```
pip install -r requirements.txt
```

## Run

```
set CLAUDE_BOARD_HOST=192.168.1.50   & rem the host running server.py
python claude_board_tray.py
```

A dot appears in the tray. To run in the background with no console window,
double-click `run_tray_hidden.vbs` (launches via `pythonw`).

## Autostart at login

1. `Win+R`, type `shell:startup`, Enter — this opens the Startup folder.
2. Right-click `run_tray_hidden.vbs` → Create shortcut → move the shortcut into
   the Startup folder.

## Configuration

All via environment variables, no code edits:

- `CLAUDE_BOARD_HOST` — host running `server.py` (default `192.168.1.50`)
- `CLAUDE_BOARD_PORT` — default `8088`
- `CLAUDE_BOARD_POLL` — poll interval in seconds (default `1.0`)

Verify the machine can reach the server first:

```
curl http://192.168.1.50:8088/status
```

A JSON blob means you're good. If the server is on another network, reach it
over a VPN/Tailscale or a LAN route, then point `CLAUDE_BOARD_HOST` at it.

## Optional: package as a single .exe (no Python needed)

```
pip install pyinstaller
pyinstaller --noconsole --onefile --name claude-board claude_board_tray.py
```

The result is `dist\claude-board.exe`. Configure it through the same
environment variables, or edit the defaults at the top of the script and
rebuild.

## Floating window variant

The tray slot is a fixed size set by the OS, so the dot can only get so big.
If you want something more visible, `claude_board_window.py` is a small
frameless, always-on-top rounded card instead: a smooth glowing status dot plus
three lines of text — the most urgent project and session count, the state word
(in the state color) and current action, and the 5h/weekly quota. Drag to move,
mouse-wheel or right-click → Window size to resize (remembered across restarts),
double-click to open the web board, right-click to quit.

```
pip install pillow
set CLAUDE_BOARD_HOST=192.168.1.50
python claude_board_window.py
```

The card is rendered with PIL and composited with a Windows layered window
(per-pixel alpha), so the rounded corners stay smooth and crisp; it falls back
to a solid rectangle elsewhere. Needs Pillow (already in `requirements.txt`).
Same `CLAUDE_BOARD_HOST` / `CLAUDE_BOARD_PORT` / `CLAUDE_BOARD_POLL` environment
variables. Run it instead of, or alongside, the tray icon.

