#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Status Board — floating desktop window.

A small frameless, always-on-top rounded card showing the aggregated state of
every Claude Code session:
  red (blinking) waiting on you / green working / grey idle / dark grey offline
A smooth glowing dot on the left, three lines on the right:
  line 1 = the most urgent project (bold) + session count
  line 2 = state word (in the state color) + current action (de-duplicated)
  line 3 = 5h/weekly usage quota
Drag to move; mouse-wheel or right-click menu to resize (remembered in a config
file); double-click to open the web board; right-click to quit.
Read-only on /status; server untouched.

The whole card is rendered with PIL (supersampled anti-aliased rounded corners,
gaussian glow, smooth text) and composited to the desktop with a Windows
layered window (UpdateLayeredWindow, per-pixel alpha), so the rounded corners
are both smooth and crisp — no region-clip jaggies, no semi-transparent fringe.
Falls back to a solid rectangle if the layered path is unavailable.
Requires Pillow (pip install pillow).
"""
import os
import sys
import json
import time
import threading
import webbrowser
import urllib.request
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops, ImageTk

HOST = os.environ.get("CLAUDE_BOARD_HOST", "192.168.1.50")
PORT = int(os.environ.get("CLAUDE_BOARD_PORT", "8088"))
POLL_SEC = float(os.environ.get("CLAUDE_BOARD_POLL", "1.0"))
STALE_SEC = 1800
TIMEOUT = 4.0
FAIL_GRACE = 4

STATUS_URL = "http://%s:%d/status" % (HOST, PORT)
BOARD_URL = "http://%s:%d/" % (HOST, PORT)
CONFIG = os.path.join(os.path.expanduser("~"), ".claude_board_window.json")

PRIORITY = {"attention": 3, "working": 2, "idle": 1}
COLORS = {"attention": (255, 90, 82), "working": (57, 211, 83),
          "idle": (138, 141, 150), "offline": (90, 93, 102), "connecting": (138, 141, 150)}
DIM_ATTN = (122, 43, 43)
STATE_WORD = {"attention": "waiting", "working": "working", "idle": "idle", "offline": "offline"}
WORDCOL = {"attention": (255, 90, 82), "working": (57, 211, 83),
           "idle": (154, 156, 165), "offline": (140, 142, 150)}

CARD = (35, 36, 43)
BORDER = (58, 60, 69)
HEAD = (242, 243, 245)
SUBC = (154, 156, 165)
QUOTAC = (127, 130, 140)

SCALE_MIN, SCALE_MAX = 0.6, 2.2

SHARED = {"state": "connecting", "project": "", "fstate": "idle", "msg": "", "n": 0, "quota": ""}
LOCK = threading.Lock()


def load_scale():
    try:
        with open(CONFIG) as f:
            return float(json.load(f).get("scale", 1.0))
    except Exception:
        return 1.0


def save_scale(v):
    try:
        with open(CONFIG, "w") as f:
            json.dump({"scale": v}, f)
    except Exception:
        pass


def set_dpi_aware():
    if not sys.platform.startswith("win"):
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def load_font(size, bold=False):
    cands = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/msyhbd.ttc",
             "segoeuib.ttf"] if bold else \
            ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/msyh.ttc", "segoeui.ttf"]
    for c in cands:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def fit(s, maxpx):
    w, out = 0, []
    for ch in s:
        cw = 14 if ord(ch) > 0x2E7F else 7
        if w + cw > maxpx:
            return "".join(out).rstrip(" ·—-") + "…"
        w += cw
        out.append(ch)
    return s


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

    focus = sorted(
        active,
        key=lambda s: (PRIORITY.get(s.get("state", "idle"), 0), int(s.get("ts", 0))),
        reverse=True,
    )[0] if active else None

    project, fstate, msg = "", "idle", ""
    if focus:
        project = focus.get("project") or focus.get("cwd", "?")
        fstate = focus.get("state", "idle")
        if fstate not in STATE_WORD:
            fstate = "idle"
        msg = (focus.get("msg") or "").replace("\n", " ").strip()

    fh, sd = usage.get("five_hour"), usage.get("seven_day")
    q = []
    if fh is not None:
        q.append("5h %d%%" % fh)
    if sd is not None:
        q.append("7d %d%%" % sd)

    return {"state": best, "project": project, "fstate": fstate, "msg": msg,
            "n": len(active), "quota": "    ".join(q)}


def poll_loop():
    fails = 0
    while True:
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
            fails = 0
            fields = aggregate(data)
        except Exception:
            fails += 1
            if fails < FAIL_GRACE:
                time.sleep(POLL_SEC)
                continue
            fields = {"state": "offline", "project": "", "fstate": "offline",
                      "msg": "", "n": 0, "quota": ""}
        with LOCK:
            SHARED.update(fields)
        time.sleep(POLL_SEC)


# ---- PIL rendering ---------------------------------------------------------
LOGICAL_W, LOGICAL_H = 360, 96
SS = 3

_base_cache = {}


def render_base(state, dim, S):
    key = (state, dim, round(S, 3))
    if key in _base_cache:
        return _base_cache[key]
    u = S * SS
    Wb, Hb = round(LOGICAL_W * u), round(LOGICAL_H * u)
    big = Image.new("RGBA", (Wb, Hb), (0, 0, 0, 0))      # transparent outside the rounded card
    d = ImageDraw.Draw(big)
    pad, rad = round(2 * u), round(22 * u)
    d.rounded_rectangle([pad, pad, Wb - pad, Hb - pad], radius=rad,
                        fill=CARD + (255,), outline=BORDER + (255,), width=max(1, round(u)))

    col = DIM_ATTN if (state == "attention" and dim) else COLORS.get(state, COLORS["idle"])
    cx, cy = round(48 * u), Hb // 2
    glow = Image.new("RGBA", (Wb, Hb), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gr = round(30 * u)
    gd.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=col + (165,))
    glow = glow.filter(ImageFilter.GaussianBlur(round(14 * u)))
    big.alpha_composite(glow)
    cr = round(17 * u)
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=col + (255,))

    base = big.resize((round(LOGICAL_W * S), round(LOGICAL_H * S)), Image.LANCZOS)
    if len(_base_cache) > 40:
        _base_cache.clear()
    _base_cache[key] = base
    return base


def render(f, dim, S, fonts):
    img = render_base(f["state"], dim, S).copy()
    d = ImageDraw.Draw(img)
    fhead, fsub, fcount = fonts
    x = round(86 * S)
    y1, y2, y3 = round(18 * S), round(45 * S), round(65 * S)
    st, n = f["state"], f["n"]

    if st == "connecting":
        d.text((x, y1), "connecting…", font=fhead, fill=HEAD + (255,))
    elif st == "offline":
        d.text((x, y1), "board offline", font=fhead, fill=HEAD + (255,))
        d.text((x, y2), "can't reach %s" % HOST, font=fsub, fill=SUBC + (255,))
    elif n == 0:
        d.text((x, y1), "idle · no sessions", font=fhead, fill=HEAD + (255,))
    else:
        proj = fit(f["project"], 244 if n <= 1 else 176)
        d.text((x, y1), proj, font=fhead, fill=HEAD + (255,))
        if n > 1:
            pw = d.textlength(proj, font=fhead)
            d.text((x + pw + round(10 * S), y1 + round(4 * S)),
                   "· %d sessions" % n, font=fcount, fill=QUOTAC + (255,))
        word = STATE_WORD.get(f["fstate"], "")
        d.text((x, y2), word, font=fsub, fill=WORDCOL.get(f["fstate"], SUBC) + (255,))
        msg = f["msg"]
        if msg.startswith(word):
            msg = msg[len(word):].lstrip(" —·-")
        msg = fit(msg, 196)
        if msg:
            ww = d.textlength(word, font=fsub)
            d.text((x + ww + round(10 * S), y2), msg, font=fsub, fill=SUBC + (255,))

    if f["quota"]:
        d.text((x, y3), f["quota"], font=fsub, fill=QUOTAC + (255,))
    return img


# ---- Windows layered window (per-pixel alpha) ------------------------------
def _bgra_premul(img):
    r, g, b, a = img.split()
    r = ImageChops.multiply(r, a)
    g = ImageChops.multiply(g, a)
    b = ImageChops.multiply(b, a)
    return Image.merge("RGBA", (r, g, b, a)).tobytes("raw", "BGRA")


class LayeredWindow:
    def __init__(self, hwnd):
        import ctypes
        from ctypes import wintypes
        self.c, self.wt = ctypes, wintypes
        self.u, self.g = ctypes.windll.user32, ctypes.windll.gdi32
        self.hwnd = ctypes.c_void_p(hwnd)
        cvp = ctypes.c_void_p

        class BLEND(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                        ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]

        class BMIH(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        self.BLEND, self.BMIH = BLEND, BMIH

        self.u.GetDC.restype = cvp; self.u.GetDC.argtypes = [cvp]
        self.u.ReleaseDC.argtypes = [cvp, cvp]
        self.g.CreateCompatibleDC.restype = cvp; self.g.CreateCompatibleDC.argtypes = [cvp]
        self.g.DeleteDC.argtypes = [cvp]
        self.g.CreateDIBSection.restype = cvp
        self.g.CreateDIBSection.argtypes = [cvp, cvp, wintypes.UINT, ctypes.POINTER(cvp), cvp, wintypes.DWORD]
        self.g.SelectObject.restype = cvp; self.g.SelectObject.argtypes = [cvp, cvp]
        self.g.DeleteObject.argtypes = [cvp]
        self.u.GetWindowLongW.restype = wintypes.LONG; self.u.GetWindowLongW.argtypes = [cvp, ctypes.c_int]
        self.u.SetWindowLongW.restype = wintypes.LONG
        self.u.SetWindowLongW.argtypes = [cvp, ctypes.c_int, wintypes.LONG]
        self.u.UpdateLayeredWindow.restype = wintypes.BOOL
        self.u.UpdateLayeredWindow.argtypes = [cvp, cvp, ctypes.POINTER(wintypes.POINT),
                                               ctypes.POINTER(wintypes.SIZE), cvp,
                                               ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
                                               ctypes.POINTER(BLEND), wintypes.DWORD]
        GWL_EXSTYLE, WS_EX_LAYERED = -20, 0x00080000
        ex = self.u.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        self.u.SetWindowLongW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)

    def paint(self, img, x, y):
        c, wt, u, g = self.c, self.wt, self.u, self.g
        W, H = img.size
        raw = _bgra_premul(img)
        hdc_screen = u.GetDC(None)
        hdc_mem = g.CreateCompatibleDC(hdc_screen)
        bmi = self.BMIH()
        bmi.biSize = c.sizeof(self.BMIH)
        bmi.biWidth, bmi.biHeight = W, -H
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
        ppv = c.c_void_p()
        hbmp = g.CreateDIBSection(hdc_mem, c.byref(bmi), 0, c.byref(ppv), None, 0)
        c.memmove(ppv, raw, len(raw))
        old = g.SelectObject(hdc_mem, hbmp)
        blend = self.BLEND(0, 0, 255, 1)            # AC_SRC_OVER, 255, AC_SRC_ALPHA
        size = wt.SIZE(W, H)
        psrc = wt.POINT(0, 0)
        pdst = wt.POINT(int(x), int(y))
        res = u.UpdateLayeredWindow(self.hwnd, hdc_screen, c.byref(pdst), c.byref(size),
                                    hdc_mem, c.byref(psrc), 0, c.byref(blend), 2)  # ULW_ALPHA
        g.SelectObject(hdc_mem, old)
        g.DeleteObject(hbmp)
        g.DeleteDC(hdc_mem)
        u.ReleaseDC(None, hdc_screen)
        return res


def main():
    set_dpi_aware()
    root = tk.Tk()
    root.title("Claude Status Board")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.config(bg="#%02x%02x%02x" % CARD)

    DPI = root.winfo_fpixels("1i") / 96.0
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    st = {"us": max(SCALE_MIN, min(SCALE_MAX, load_scale())), "img": None}
    ctx = {}

    lw = [None]
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.GetAncestor.restype = ctypes.c_void_p
            ctypes.windll.user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()
            lw[0] = LayeredWindow(hwnd)
        except Exception:
            lw[0] = None

    lbl = None
    if lw[0] is None:
        lbl = tk.Label(root, bd=0, highlightthickness=0, bg="#%02x%02x%02x" % CARD)
        lbl.pack(fill="both", expand=True)

    blink = {"on": True}

    def rebuild():
        ES = DPI * st["us"]
        W, H = round(LOGICAL_W * ES), round(LOGICAL_H * ES)
        ctx["ES"], ctx["W"], ctx["H"] = ES, W, H
        ctx["fonts"] = (load_font(round(17 * ES), bold=True),
                        load_font(round(13 * ES)), load_font(round(12 * ES)))
        if "x" not in st:
            st["x"] = max(0, sw - W - round(24 * DPI))
            st["y"] = round(56 * DPI)
        st["x"] = max(0, min(st["x"], sw - W))
        st["y"] = max(0, min(st["y"], sh - H))
        root.geometry("%dx%d+%d+%d" % (W, H, st["x"], st["y"]))
        root.update_idletasks()

    rebuild()

    def show(img):
        st["img"] = img
        if lw[0] is not None:
            lw[0].paint(img, st["x"], st["y"])
        else:
            photo = ImageTk.PhotoImage(img)
            lbl.config(image=photo)
            lbl.image = photo

    def compose():
        with LOCK:
            f = dict(SHARED)
        dim = (f["state"] == "attention" and not blink["on"])
        return render(f, dim, ctx["ES"], ctx["fonts"])

    def set_scale(v):
        st["us"] = max(SCALE_MIN, min(SCALE_MAX, round(v, 3)))
        save_scale(st["us"])
        rebuild()
        show(compose())

    def open_board(_=None):
        webbrowser.open(BOARD_URL)

    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Open web board", command=open_board)
    size_menu = tk.Menu(menu, tearoff=0)
    for name, val in (("Small", 0.8), ("Medium", 1.0), ("Large", 1.25), ("X-Large", 1.6)):
        size_menu.add_command(label=name, command=lambda v=val: set_scale(v))
    menu.add_cascade(label="Window size", menu=size_menu)
    menu.add_separator()
    menu.add_command(label="Quit", command=root.destroy)

    def b1(e):
        st["sx"], st["sy"], st["ox"], st["oy"] = e.x_root, e.y_root, st["x"], st["y"]

    def b1m(e):
        st["x"] = max(0, min(st["ox"] + (e.x_root - st["sx"]), sw - ctx["W"]))
        st["y"] = max(0, min(st["oy"] + (e.y_root - st["sy"]), sh - ctx["H"]))
        if lw[0] is not None and st["img"] is not None:
            lw[0].paint(st["img"], st["x"], st["y"])
        else:
            root.geometry("+%d+%d" % (st["x"], st["y"]))

    def on_wheel(e):
        set_scale(st["us"] + (0.1 if e.delta > 0 else -0.1))

    def popup(e):
        menu.tk_popup(e.x_root, e.y_root)

    for w in (root, lbl):
        if w is None:
            continue
        w.bind("<Button-1>", b1)
        w.bind("<B1-Motion>", b1m)
        w.bind("<Double-Button-1>", open_board)
        w.bind("<Button-3>", popup)
        w.bind("<MouseWheel>", on_wheel)

    def tick():
        if SHARED["state"] == "attention":
            blink["on"] = not blink["on"]
            nap = 450
        else:
            blink["on"] = True
            nap = 300
        show(compose())
        root.after(nap, tick)

    threading.Thread(target=poll_loop, daemon=True).start()
    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
