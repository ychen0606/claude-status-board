#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Status Board — Windows system-tray indicator.

Polls the board server's /status endpoint and collapses every Claude Code
session into a single colored dot in the Windows notification area (the same
state the desk traffic-light shows, just in your taskbar):

  red (blinking) = a session is waiting on you (permission / input)
  green          = a session is working
  grey           = all idle / no sessions
  dark grey      = cannot reach the board server (offline)

Hover for a tooltip (which project is doing what + 5h/weekly usage quota).
Right-click to open the web board or quit. Read-only on /status; the server
is untouched.

Dependencies: pystray, Pillow.
"""

import os
import json
import time
import webbrowser
import urllib.request

from PIL import Image, ImageDraw
import pystray

# ---- Config (override via environment variables) ---------------------------
# IP/host of the machine running server.py. Override with CLAUDE_BOARD_HOST,
# e.g. a LAN IP, a Tailscale IP, or a public address (open the firewall first).
HOST = os.environ.get("CLAUDE_BOARD_HOST", "192.168.1.50")
PORT = int(os.environ.get("CLAUDE_BOARD_PORT", "8088"))
POLL_SEC = float(os.environ.get("CLAUDE_BOARD_POLL", "1.0"))
STALE_SEC = 1800          # treat a slot older than this as expired (server also filters)
TIMEOUT = 4.0             # /status request timeout
FAIL_GRACE = 4            # show offline only after this many consecutive failures

STATUS_URL = "http://%s:%d/status" % (HOST, PORT)
BOARD_URL = "http://%s:%d/" % (HOST, PORT)

PRIORITY = {"attention": 3, "working": 2, "idle": 1}
COLORS = {
    "attention": (230, 60, 60),    # red
    "working":   (54, 190, 96),    # green
    "idle":      (130, 130, 130),  # grey
    "offline":   (80, 80, 80),     # dark grey
}
STATE_LABEL = {"attention": "waiting on you", "working": "working",
               "idle": "idle", "offline": "offline"}


def make_icon(state, dim=False):
    """Draw a filled circle as the tray icon."""
    rgb = COLORS.get(state, COLORS["idle"])
    if dim:
        rgb = tuple(int(c * 0.32) for c in rgb)
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 6, size - 6, size - 6], fill=rgb + (255,),
              outline=(0, 0, 0, 70), width=2)
    return img


class Board:
    """Polls /status and keeps the aggregated state + tooltip text."""

    def __init__(self):
        self.state = "offline"
        self.tooltip = u"Claude Status Board · connecting…"
        self._fails = 0

    def poll(self):
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            self._fails = 0
        except Exception:
            self._fails += 1
            if self._fails >= FAIL_GRACE:
                self.state = "offline"
                self.tooltip = u"Claude Status Board · offline (can't reach %s)" % HOST
            return self.state

        now = data.get("now", int(time.time()))
        slots = data.get("slots", []) or []
        usage = data.get("usage", {}) or {}

        active, counts = [], {"attention": 0, "working": 0, "idle": 0}
        best = "idle"
        for s in slots:
            if now - int(s.get("ts", 0)) > STALE_SEC:
                continue
            st = s.get("state", "idle")
            if st not in counts:
                st = "idle"
            active.append(s)
            counts[st] += 1
            if PRIORITY.get(st, 0) > PRIORITY.get(best, 0):
                best = st
        if not active:
            best = "idle"

        self.state = best
        self.tooltip = self._make_tip(best, active, counts, usage)
        return best

    def _make_tip(self, best, active, counts, usage):
        n = len(active)
        if n == 0:
            head = u"Claude Status Board · idle (no sessions)"
        else:
            parts = []
            if counts["attention"]:
                parts.append(u"%d waiting" % counts["attention"])
            if counts["working"]:
                parts.append(u"%d working" % counts["working"])
            if counts["idle"]:
                parts.append(u"%d idle" % counts["idle"])
            head = u"Claude Status Board · %d session(s): %s" % (n, ", ".join(parts))

        # most urgent session: highest state, then most recent
        focus = sorted(
            active,
            key=lambda s: (PRIORITY.get(s.get("state", "idle"), 0), int(s.get("ts", 0))),
            reverse=True,
        )[0] if active else None

        lines = [head]
        if focus:
            proj = focus.get("project") or focus.get("cwd", "?")
            msg = (focus.get("msg") or "").replace("\n", " ").strip()
            if len(msg) > 46:
                msg = msg[:45] + u"…"
            lines.append(u"%s · %s%s" % (proj, STATE_LABEL.get(focus.get("state"), ""),
                                         (u" · " + msg) if msg else ""))

        fh, sd = usage.get("five_hour"), usage.get("seven_day")
        if fh is not None or sd is not None:
            q = []
            if fh is not None:
                q.append(u"5h %d%%" % fh)
            if sd is not None:
                q.append(u"7d %d%%" % sd)
            lines.append(u" · ".join(q))

        tip = u"\n".join(lines)
        # Windows tray tooltip caps around 127 chars
        return tip[:127]


board = Board()


def _updater(icon):
    """Background thread: poll + refresh icon/tooltip; blink when attention."""
    icon.visible = True
    last_poll = 0.0
    blink = True
    while True:
        nowm = time.monotonic()
        if nowm - last_poll >= POLL_SEC:
            board.poll()
            last_poll = nowm
        if board.state == "attention":
            blink = not blink
            icon.icon = make_icon("attention", dim=not blink)
            nap = 0.6
        else:
            icon.icon = make_icon(board.state)
            nap = POLL_SEC
        icon.title = board.tooltip
        time.sleep(nap)


def _on_open(icon, item):
    webbrowser.open(BOARD_URL)


def _on_quit(icon, item):
    icon.visible = False
    icon.stop()


def main():
    menu = pystray.Menu(
        pystray.MenuItem("Open web board", _on_open, default=True),
        pystray.MenuItem("Quit", _on_quit),
    )
    icon = pystray.Icon("claude_board", make_icon("idle"), "Claude Status Board", menu)
    icon.run(setup=_updater)


if __name__ == "__main__":
    main()
