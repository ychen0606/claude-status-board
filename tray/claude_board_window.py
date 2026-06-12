#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Status Board — floating desktop window.

A small frameless, always-on-top window showing the aggregated state of every
Claude Code session:
  red (blinking) waiting on you / green working / grey idle / dark grey offline
A large colored dot on the left, three lines of text on the right (summary,
most urgent project, 5h/weekly usage quota). Drag to move, double-click to open
the web board, right-click to quit. Read-only on /status; server untouched.

Standard library only (tkinter) — no extra dependencies.
"""
import os
import json
import time
import threading
import webbrowser
import urllib.request
import tkinter as tk

HOST = os.environ.get("CLAUDE_BOARD_HOST", "192.168.1.50")
PORT = int(os.environ.get("CLAUDE_BOARD_PORT", "8088"))
POLL_SEC = float(os.environ.get("CLAUDE_BOARD_POLL", "1.0"))
STALE_SEC = 1800
TIMEOUT = 4.0
FAIL_GRACE = 4

STATUS_URL = "http://%s:%d/status" % (HOST, PORT)
BOARD_URL = "http://%s:%d/" % (HOST, PORT)

PRIORITY = {"attention": 3, "working": 2, "idle": 1}
COLORS = {"attention": "#e63c3c", "working": "#36be60", "idle": "#828282", "offline": "#505050"}
DIM_ATTN = "#5a2424"
STATE_LABEL = {"attention": "waiting on you", "working": "working",
               "idle": "idle", "offline": "offline"}

BG = "#1c1c1e"
FG = "#f0f0f0"
SUB = "#a8a8b0"
FONT = "Segoe UI"

SHARED = {"state": "offline", "head": "connecting…", "sub": "", "quota": ""}
LOCK = threading.Lock()


def aggregate(data):
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

    n = len(active)
    if n == 0:
        head = "idle · no sessions"
    else:
        parts = []
        if counts["attention"]:
            parts.append("%d waiting" % counts["attention"])
        if counts["working"]:
            parts.append("%d working" % counts["working"])
        if counts["idle"]:
            parts.append("%d idle" % counts["idle"])
        head = "%s · %d session(s)" % (", ".join(parts), n)

    focus = sorted(
        active,
        key=lambda s: (PRIORITY.get(s.get("state", "idle"), 0), int(s.get("ts", 0))),
        reverse=True,
    )[0] if active else None

    sub = ""
    if focus:
        proj = focus.get("project") or focus.get("cwd", "?")
        msg = (focus.get("msg") or "").replace("\n", " ").strip()
        if len(msg) > 40:
            msg = msg[:39] + "…"
        sub = "%s · %s" % (proj, STATE_LABEL.get(focus.get("state"), ""))
        if msg:
            sub += " · " + msg

    fh, sd = usage.get("five_hour"), usage.get("seven_day")
    q = []
    if fh is not None:
        q.append("5h %d%%" % fh)
    if sd is not None:
        q.append("7d %d%%" % sd)
    return best, head, sub, " · ".join(q)


def poll_loop():
    fails = 0
    while True:
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            fails = 0
            state, head, sub, quota = aggregate(data)
        except Exception:
            fails += 1
            if fails < FAIL_GRACE:        # network blip: keep the last frame
                time.sleep(POLL_SEC)
                continue
            state, head, sub, quota = "offline", "board offline", "can't reach %s" % HOST, ""
        with LOCK:
            SHARED.update(state=state, head=head, sub=sub, quota=quota)
        time.sleep(POLL_SEC)


def main():
    root = tk.Tk()
    root.title("Claude Status Board")
    root.overrideredirect(True)              # frameless
    root.attributes("-topmost", True)        # always on top
    try:
        root.attributes("-alpha", 0.94)
    except Exception:
        pass

    W, H = 300, 92
    sw = root.winfo_screenwidth()
    root.geometry("%dx%d+%d+%d" % (W, H, max(0, sw - W - 24), 48))

    outer = tk.Frame(root, bg=BG, highlightthickness=2, highlightbackground=BG)
    outer.pack(fill="both", expand=True)

    cv = tk.Canvas(outer, width=66, height=H, bg=BG, highlightthickness=0)
    cv.place(x=8, y=0)
    dot = cv.create_oval(8, H // 2 - 27, 62, H // 2 + 27, fill=COLORS["idle"], outline="")

    lab_head = tk.Label(outer, text="connecting…", bg=BG, fg=FG,
                        font=(FONT, 13, "bold"), anchor="w")
    lab_head.place(x=80, y=12)
    lab_sub = tk.Label(outer, text="", bg=BG, fg=SUB, font=(FONT, 9), anchor="w")
    lab_sub.place(x=80, y=40)
    lab_quota = tk.Label(outer, text="", bg=BG, fg=SUB, font=(FONT, 9), anchor="w")
    lab_quota.place(x=80, y=63)

    widgets = (outer, cv, lab_head, lab_sub, lab_quota)

    def start_move(e):
        root._dx, root._dy = e.x, e.y

    def do_move(e):
        root.geometry("+%d+%d" % (root.winfo_x() + e.x - root._dx,
                                  root.winfo_y() + e.y - root._dy))

    def open_board(_=None):
        webbrowser.open(BOARD_URL)

    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Open web board", command=open_board)
    menu.add_separator()
    menu.add_command(label="Quit", command=root.destroy)

    def popup(e):
        menu.tk_popup(e.x_root, e.y_root)

    for w in widgets:
        w.bind("<Button-1>", start_move)
        w.bind("<B1-Motion>", do_move)
        w.bind("<Double-Button-1>", open_board)
        w.bind("<Button-3>", popup)

    blink = {"on": True}

    def tick():
        with LOCK:
            st, h, s, q = SHARED["state"], SHARED["head"], SHARED["sub"], SHARED["quota"]
        lab_head.config(text=h)
        lab_sub.config(text=s)
        lab_quota.config(text=q)
        if st == "attention":
            blink["on"] = not blink["on"]
            cv.itemconfig(dot, fill=COLORS["attention"] if blink["on"] else DIM_ATTN)
            outer.config(highlightbackground=COLORS["attention"] if blink["on"] else BG)
            root.after(450, tick)
        else:
            cv.itemconfig(dot, fill=COLORS.get(st, COLORS["idle"]))
            outer.config(highlightbackground=BG)
            root.after(300, tick)

    threading.Thread(target=poll_loop, daemon=True).start()
    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
