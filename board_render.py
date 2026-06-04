#!/usr/bin/env python3
# Claude 看板 —— 服务端渲染 (240x320), 板子只负责拉 PNG 显示 + 触摸。
# render(state, view, req) -> (PIL.Image, buttons:list, led:str)
#   state = {"slots":[...], "usage":{...}, "now":ts}
#   view  = "list" | "approve";  req = 选中的待批请求(approve 视图用)
#   buttons = [{"x","y","w","h","act","req"}]  act: open|approve|deny|back
import time, math, os
from PIL import Image, ImageDraw, ImageFont

W, H = 240, 320
# 字体: 默认 Noto Sans CJK(Debian: fonts-noto-cjk), 可用环境变量覆盖。
REG = os.environ.get("CLAUDE_BOARD_FONT", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
BLD = os.environ.get("CLAUDE_BOARD_FONT_BOLD", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
_fc = {}
def f(sz, bold=False):
    k = (sz, bold)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(BLD if bold else REG, sz)
    return _fc[k]

BG   = (13, 15, 20)
CARD = (24, 28, 37)
TXT  = (234, 237, 243)
MUT  = (143, 152, 164)
GRN  = (64, 211, 110)
AMB  = (245, 184, 64)
RED  = (255, 86, 92)
DIV  = (33, 38, 48)

def lvl(p): return GRN if p < 50 else (AMB if p < 80 else RED)
def mix(c, bg, a):  # c over bg with alpha a
    return tuple(int(c[i]*a + bg[i]*(1-a)) for i in range(3))

def _tw(d, s, ft): return d.textlength(s, font=ft)
def rtext(d, xr, y, s, ft, fill): d.text((xr - _tw(d, s, ft), y), s, font=ft, fill=fill)
def rr(d, box, r, **kw): d.rounded_rectangle(box, radius=r, **kw)

def dot(d, cx, cy, r, col):           # 带柔光的状态点
    d.ellipse((cx-r-2, cy-r-2, cx+r+2, cy+r+2), fill=mix(col, BG, 0.28))
    d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=col)

def gear(d, cx, cy, r, col):          # 齿轮(设置)图标
    teeth = 8; pts = []
    for i in range(teeth * 2):
        a = math.pi * i / teeth
        rad = r if i % 2 == 0 else r * 0.66
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    d.polygon(pts, fill=col)
    d.ellipse((cx - r*0.36, cy - r*0.36, cx + r*0.36, cy + r*0.36), fill=BG)

def pill(d, xr, y, text, col, ft):    # 右对齐的状态胶囊
    tw = _tw(d, text, ft); padx = 9; h = 20
    x1 = xr; x0 = xr - (tw + padx*2)
    rr(d, (x0, y, x1, y+h), 9, fill=mix(col, BG, 0.20))
    d.text((x0+padx, y+2), text, font=ft, fill=col)
    return x0

def fmt_reset(m):
    if m is None or m < 0: return ""
    if m >= 1440:
        d_, h = m//1440, (m%1440)//60
        return f"{d_}天{h}时" if h else f"{d_}天"
    if m >= 60:
        h, mm = m//60, m%60
        return f"{h}时{mm}分" if mm else f"{h}时"
    return f"{m}分"

def fmt_ago(sec):
    if sec is None or sec < 0: return ""
    if sec < 60: return "刚刚"
    if sec < 3600: return f"{sec//60}分钟前"
    if sec < 86400: return f"{sec//3600}小时前"
    return f"{sec//86400}天前"

def fmt_dur(sec):
    if sec is None or sec < 60: return "刚开始"
    if sec < 3600: return f"{sec//60}分"
    h, m = sec//3600, (sec%3600)//60
    return f"{h}时{m}分" if m else f"{h}时"

def short_model(m):
    return m.split()[0] if m else ""    # "Opus 4.8 (1M context)" -> "Opus"

STWORD = {"working": ("工作中", GRN), "attention": ("需要你", AMB), "idle": ("空闲", MUT)}

def _wrap(d, text, ft, maxw):
    out = []
    for para in (text or "").split("\n"):
        line = ""
        for ch in para:
            if _tw(d, line + ch, ft) > maxw and line:
                out.append(line); line = ch
            else:
                line += ch
        out.append(line)
    return out

def _usage(d, y, lab, pct, rmin):
    d.text((12, y), lab, font=f(14), fill=MUT)
    bx, bw, by, bh = 44, 100, y+4, 8
    rr(d, (bx, by, bx+bw, by+bh), 4, fill=CARD)
    if pct is not None and pct >= 0:
        fw = max(4, int(bw*min(pct,100)/100))
        rr(d, (bx, by, bx+fw, by+bh), 4, fill=lvl(pct))
    pc = f"{pct}%" if (pct is not None and pct >= 0) else "—"
    d.text((bx+bw+9, y-1), pc, font=f(14, True), fill=TXT)
    r = fmt_reset(rmin)
    if r: rtext(d, 234, y, r, f(13), MUT)

def render(state, view="list", req=""):
    slots = state.get("slots", []) or []
    usage = state.get("usage", {}) or {}
    now = state.get("now", int(time.time()))
    rank = {"attention_req": 0, "attention": 1, "working": 2, "idle": 3}
    def rk(s):
        if s.get("state") == "attention" and s.get("req"): return 0
        if s.get("state") == "attention": return 1
        if s.get("state") == "working": return 2
        return 3
    slots = sorted(slots, key=rk)
    attn = [s for s in slots if s.get("state") == "attention"]   # 需要你处理(含终端审批, 无 req)
    pend = [s for s in attn if s.get("req")]                     # 可直接在板上批准的(有 req)
    done = [s for s in slots if 0 < (now - int(s.get("done_ts", 0) or 0)) < 12]  # 刚完成(12s 内)
    hpc = (state.get("hpc") or {}).get("jobs", [])

    # 背光亮度策略(板子据此调屏): 待处理=最亮, 工作=正常, 空闲=暗, 无会话/夜间=更暗
    hour = ((now + 8*3600) % 86400) // 3600
    if attn:                                              bright = 255
    elif any(s.get("state") == "working" for s in slots): bright = 170
    elif slots:                                           bright = 60
    else:                                                 bright = 28
    if hour >= 23 or hour < 7:                            bright = min(bright, 30)

    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    buttons = []
    led = "off"

    if view == "approve":
        s = next((x for x in slots if x.get("req") == req), None)
        if s is None:
            view = "list"           # 请求没了, 退回列表
        else:
            led = "alert"
            rr(d, (0, 0, W, 40), 0, fill=mix(RED, BG, 0.22))
            d.text((12, 9), "‹ 返回", font=f(16), fill=TXT)
            buttons.append({"x":0,"y":0,"w":90,"h":40,"act":"back","req":""})
            pj = s.get("project","?")
            rtext(d, 230, 9, pj[:14], f(16, True), TXT)
            d.text((14, 54), "⚠", font=f(20), fill=RED)
            d.text((40, 55), s.get("label") or "需要授权", font=f(18, True), fill=RED)
            rr(d, (10, 88, 230, 214), 10, fill=CARD)
            msg = (s.get("msg") or "").replace("\r"," ")
            ty = 98
            for line in msg.split("\n")[:6]:
                while line and _tw(d, line, f(13)) > 200:
                    line = line[:-1]
                d.text((20, ty), line, font=f(13), fill=(206,212,222)); ty += 19
            rr(d, (10, 232, 116, 304), 11, fill=(36, 158, 78))
            rr(d, (124, 232, 230, 304), 11, fill=(196, 58, 64))
            d.text((44, 256), "批准", font=f(22, True), fill=(255,255,255))
            d.text((154, 256), "拒绝", font=f(22, True), fill=(255,255,255))
            buttons.append({"x":10,"y":232,"w":106,"h":72,"act":"approve","req":req})
            buttons.append({"x":124,"y":232,"w":106,"h":72,"act":"deny","req":req})
            return im, buttons, led, bright

    if view == "detail":
        s = next((x for x in slots if x.get("sid") == req), None)
        if s is None:
            view = "list"
        else:
            st = s.get("state", "idle")
            d.text((12, 9), "‹ 返回", font=f(16), fill=TXT)
            buttons.append({"x": 0, "y": 0, "w": 90, "h": 40, "act": "back", "req": ""})
            rtext(d, 230, 9, s.get("project", "?")[:14], f(16, True), TXT)
            d.line((0, 40, W, 40), fill=DIV)
            word, wc = ((("需授权" if s.get("req") else "待确认"), RED) if st == "attention"
                        else STWORD.get(st, ("空闲", MUT)))
            dot(d, 20, 61, 6, wc)
            d.text((36, 52), word, font=f(18, True), fill=wc)
            mdl = short_model(s.get("model", ""))
            if mdl: rtext(d, 230, 55, mdl, f(14), MUT)
            rr(d, (10, 80, 230, 304), 10, fill=CARD)
            iy = [92]
            def kv(label, val):
                d.text((20, iy[0]), label, font=f(12), fill=MUT)
                d.text((68, iy[0]), val, font=f(13), fill=(210, 216, 226)); iy[0] += 23
            kv("时长", fmt_dur(now - int(s.get("start_ts", s.get("ts", now)))))
            kv("活跃", fmt_ago(now - int(s.get("ts", now))) or "刚刚")
            cwd = s.get("cwd", "")
            kv("目录", ("…" + cwd[-24:]) if len(cwd) > 25 else cwd)
            d.text((20, iy[0]), "命令 / 动作", font=f(12), fill=MUT); iy[0] += 21
            for line in _wrap(d, (s.get("msg") or "").replace("\r", " "), f(13), 198)[:7]:
                d.text((20, iy[0]), line, font=f(13), fill=(206, 212, 222)); iy[0] += 19
            return im, buttons, led, bright

    # ---- 列表视图 ----
    # 顶栏
    dot(d, 17, 15, 4, GRN if any(s.get("state")=="working" for s in slots) else MUT)
    d.text((28, 6), "Claude 看板", font=f(16, True), fill=TXT)
    gear(d, 223, 15, 9, MUT)                       # 右上设置(配网)按钮
    buttons.append({"x": 204, "y": 1, "w": 36, "h": 30, "act": "wifi", "req": ""})
    t = (now + 8*3600) % 86400
    rtext(d, 199, 8, "%02d:%02d" % (t//3600, (t%3600)//60), f(14), MUT)
    d.line((0, 31, W, 31), fill=DIV)

    y = 38
    # 授权/待处理 高亮横幅(任一 attention 即闪)
    if attn:
        rr(d, (8, y, W-8, y+30), 9, fill=RED)
        d.text((18, y+6), "⚠", font=f(17, True), fill=(255,255,255))
        d.text((40, y+6), f"{len(attn)} 个会话需要授权", font=f(15, True), fill=(255,255,255))
        led = "alert"
        y += 38

    # 配额
    _usage(d, y, "5h", usage.get("five_hour"), usage.get("fh_reset_min")); y += 23
    _usage(d, y, "周", usage.get("seven_day"), usage.get("sd_reset_min")); y += 26
    d.line((0, y, W, y), fill=DIV); y += 6

    if led == "off":
        if done:                                              led = "done"   # 刚完成 -> 绿色提醒
        elif any(s.get("state")=="working" for s in slots):   led = "work"
        elif slots:                                           led = "idle"
        else:                                                 led = "off"

    if not slots and not hpc:
        d.text((16, 150), "无活跃会话", font=f(16), fill=MUT)
        return im, buttons, led, bright

    rowh = 50
    for s in slots:
        if y + rowh > H: break
        appr = s.get("state") == "attention"
        isdone = (not appr) and 0 < (now - int(s.get("done_ts", 0) or 0)) < 12   # 刚完成
        st = s.get("state","idle")
        col = RED if appr else (GRN if (st=="working" or isdone) else (AMB if st=="attention" else MUT))
        cardbg = mix(RED, BG, 0.16) if appr else (mix(GRN, BG, 0.14) if isdone else CARD)
        rr(d, (8, y, W-8, y+rowh-4), 9, fill=cardbg)
        if appr:
            rr(d, (8, y, 13, y+rowh-4), 0, fill=RED)   # 左侧红条
        elif isdone:
            rr(d, (8, y, 13, y+rowh-4), 0, fill=GRN)   # 左侧绿条(刚完成)
        dot(d, 24, y+16, 5, col)
        d.text((38, y+7), s.get("project","?")[:20], font=f(16, True), fill=TXT)
        if appr:
            word, wc = (s.get("label") or ("需授权" if s.get("req") else "去终端确认")), RED
        elif isdone:
            word, wc = "✓ 完成", GRN
        else:
            word, wc = STWORD.get(st, ("空闲", MUT))
        px = pill(d, W-14, y+7, word, wc, f(13, True))
        # 第二行: 模型·命令 + 运行时长(working) 或 活跃时间
        model = short_model(s.get("model", ""))
        cmd = (s.get("msg") or "").replace("\n", " ").replace("\r", " ")
        det = (model + " · " + cmd) if (model and cmd) else (cmd or model)
        if st == "working":
            rt = fmt_dur(now - int(s.get("start_ts", s.get("ts", now))))
        else:
            rt = fmt_ago(now - int(s.get("ts", now)))
        rtw = _tw(d, rt, f(12)) if rt else 0
        detmax = (W - 14 - rtw - 10) - 38
        while det and _tw(d, det, f(12)) > detmax:
            det = det[:-1]
        d.text((38, y+29), det, font=f(12), fill=MUT)
        if rt: rtext(d, W-14, y+29, rt, f(12), MUT)
        if appr:                       # 审批卡: 有 req=板上批准(open); 无 req=仅提醒脉动(alert)
            buttons.append({"x":8,"y":y,"w":W-16,"h":rowh-4,
                            "act": "open" if s.get("req") else "alert", "req": s.get("req","")})
        else:                          # 其它卡: 点进详情
            buttons.append({"x":8,"y":y,"w":W-16,"h":rowh-4, "act": "detail", "req": s.get("sid","")})
        y += rowh

    # ---- HPC 任务区(squeue) ----
    if hpc and y + 26 <= H:
        d.line((10, y+2, W-10, y+2), fill=DIV)
        d.text((12, y+5), "HPC", font=f(12, True), fill=lvl(0))
        nrun = sum(1 for j in hpc if j.get("state","").upper().startswith("R"))
        rtext(d, 230, y+5, f"{len(hpc)}个 · {nrun}运行", f(12), MUT)
        y += 24
        for j in hpc:
            if y + 22 > H: break
            jst = j.get("state", "").upper()
            jc = GRN if jst.startswith("R") else (AMB if jst.startswith("PD") else MUT)
            dot(d, 18, y+8, 4, jc)
            nm = j.get("name", "")[:16]
            d.text((30, y), nm, font=f(13), fill=(210, 216, 226))
            rtext(d, 230, y, f"{jst[:2]} {j.get('time','')}", f(12), jc)
            y += 22
    return im, buttons, led, bright


if __name__ == "__main__":
    now = int(time.time())
    st = {"now": now, "usage": {"five_hour":15,"seven_day":20,"fh_reset_min":156,"sd_reset_min":5766},
          "slots": [
            {"project":"cm_prolif","state":"attention","req":"888888","label":"需要授权",
             "msg":"Bash: rm -rf build/ && cmake .. && make -j8","ts":now-3,"start_ts":now-200,"model":"Opus 4.8"},
            {"project":"shuaji","state":"working","req":"","msg":"Bash: make -j8 install","ts":now-12,"start_ts":now-451,"model":"Opus 4.8"},
            {"project":"gnf2133","state":"idle","req":"","msg":"完成 · DESeq2 跑完","ts":now-480,"start_ts":now-3600,"model":"Sonnet 4.6"},
            {"project":"yap_mef2a","state":"working","req":"","msg":"读取 features.tsv.gz","ts":now-65,"start_ts":now-95,"model":"Haiku 4.5"},
          ]}
    a, ba, la, bra = render(st, "list")
    b, bb, lb, brb = render(st, "approve", "888888")
    canvas = Image.new("RGB", (W*2+30, H+40), (40,40,40))
    canvas.paste(a, (10,30)); canvas.paste(b, (W+20,30))
    dd = ImageDraw.Draw(canvas)
    dd.text((10,8), "列表(授权高亮) led=%s"%la, font=f(13), fill=(255,255,255))
    dd.text((W+20,8), "批准视图 led=%s"%lb, font=f(13), fill=(255,255,255))
    canvas.save("/tmp/board_render.png")
    print("saved /tmp/board_render.png; list buttons:", ba)
