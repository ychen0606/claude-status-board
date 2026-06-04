#!/usr/bin/env python3
# Claude 多项目状态看板 + 平板远程审批（按会话分槽）—— 深色精致版 UI
# GET /        -> 多行看板网页（纯 ES5，兼容 Android 6.0 老 WebView）
# GET /status  -> {"slots":[...], "now":ts}  聚合 slots/*.json，过滤过期
# GET /decide?req=<id>&d=approve|deny -> 写 decisions/<req>，由 approve_gate.py 读取
import http.server, socketserver, os, time, json, re, io, hashlib, subprocess, threading
from urllib.parse import urlparse, parse_qs
try:
    import board_render            # 服务端渲染板子 UI(PIL)
except Exception as _e:
    board_render = None
    print("board_render unavailable:", _e, flush=True)

DIR = os.path.dirname(os.path.abspath(__file__))
SLOTS = os.path.join(DIR, "slots")
DECISIONS = os.path.join(DIR, "decisions")
PORT = int(os.environ.get("CLAUDE_BOARD_PORT", "8088"))
STALE = 1800
USAGE = os.path.join(DIR, "usage.json")  # claude-hud 写的 5h/周 配额快照

HTML = r"""<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Claude 看板</title>
<style>
  *{box-sizing:border-box;-webkit-tap-highlight-color:rgba(0,0,0,0);}
  html,body{margin:0;min-height:100%;width:100%;background:#0b0c0f;
    color:#e7e9ee;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif;}
  body{background:radial-gradient(120vmax 80vmax at 50% -20%,#15171d 0%,#0b0c0f 60%);}
  /* 顶栏 */
  #bar{position:fixed;top:0;left:0;right:0;height:10vmin;display:flex;align-items:center;
    justify-content:space-between;padding:0 4.5vmin;background:rgba(11,12,15,.86);
    border-bottom:1px solid #1d2027;z-index:10;}
  #brand{display:flex;align-items:center;font-weight:800;font-size:4.4vmin;letter-spacing:.3px;}
  #spark{width:2.6vmin;height:2.6vmin;border-radius:50%;background:#46d369;margin-right:2.4vmin;
    box-shadow:0 0 2.6vmin .4vmin rgba(70,211,105,.6);animation:breathe 2.6s ease-in-out infinite;}
  #brand small{color:#8b93a1;font-weight:600;font-size:3vmin;margin-left:2.4vmin;letter-spacing:0;}
  #clk{color:#737b89;font-size:3.4vmin;font-variant-numeric:tabular-nums;font-weight:600;}
  @keyframes breathe{50%{opacity:.45;}}
  /* 列表 */
  #list{padding:13vmin 3.2vmin 8vmin;}
  .card{position:relative;background:#15171d;border:1px solid #21252e;border-radius:3.4vmin;
    margin:2.6vmin 0;padding:3.6vmin 4vmin 3.6vmin 5.4vmin;overflow:hidden;
    transition:background .35s,border-color .35s,box-shadow .35s;}
  .card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:1.5vmin;background:#5c636e;}
  .card.working:before{background:#2ea043;}
  .card.idle:before{background:#3a4150;}
  .card.attention{background:#1f1418;border-color:#5a2630;animation:glow 2.2s ease-in-out infinite;}
  .card.attention:before{background:#ff4d57;}
  @keyframes glow{50%{box-shadow:0 0 7vmin 0 rgba(255,77,87,.22);}}
  .head{display:flex;align-items:center;justify-content:space-between;}
  .proj{display:flex;align-items:center;font-size:4.7vmin;font-weight:800;word-break:break-all;}
  .pill{display:flex;align-items:center;white-space:nowrap;margin-left:3vmin;
    font-size:3.1vmin;font-weight:700;padding:1vmin 2.8vmin;border-radius:6vmin;}
  .pill .d{width:2.1vmin;height:2.1vmin;border-radius:50%;margin-right:1.8vmin;}
  .working .pill{color:#7ee2a0;background:rgba(46,160,67,.14);} .working .pill .d{background:#46d369;}
  .idle .pill{color:#9aa3b2;background:rgba(120,130,150,.12);} .idle .pill .d{background:#5c636e;}
  .attention .pill{color:#ff9aa2;background:rgba(255,77,87,.16);} .attention .pill .d{background:#ff4d57;}
  .msg{font-size:3.4vmin;color:#9aa1ae;margin-top:1.6vmin;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  /* 审批详情：仿代码/diff */
  .detail{display:none;margin-top:2.6vmin;background:#0a0b0e;border:1px solid #20242d;border-radius:2.4vmin;
    padding:2.6vmin 2.8vmin;max-height:42vh;overflow:auto;-webkit-overflow-scrolling:touch;
    font-family:"SF Mono","JetBrains Mono",Menlo,Consolas,"Roboto Mono",monospace;
    font-size:2.95vmin;line-height:1.55;}
  .detail .ln{white-space:pre-wrap;word-break:break-all;padding:0 1.4vmin;border-radius:1vmin;}
  .detail .cmd{color:#cfe3ff;font-weight:700;}
  .detail .cmt{color:#6f7787;}
  .detail .del{color:#ff9aa2;background:rgba(255,77,87,.10);}
  .detail .add{color:#9ae6a0;background:rgba(46,160,67,.12);}
  .detail .txt{color:#c4cad6;}
  .detail .sep{color:#737b89;font-size:2.5vmin;font-weight:700;letter-spacing:.18em;
    text-transform:uppercase;margin:1.6vmin 0 .8vmin;padding:0 1.4vmin;}
  .detail .sep:first-child{margin-top:0;}
  /* 按钮 */
  .btns{display:none;margin-top:3vmin;}
  .b{font-size:4.3vmin;font-weight:800;color:#fff;border:none;border-radius:2.6vmin;
    padding:2.7vmin 0;width:48%;-webkit-appearance:none;transition:transform .08s,filter .15s;}
  .b:active{transform:scale(.96);filter:brightness(1.12);}
  .ok{background:#23a049;margin-right:4%;} .no{background:#d23b45;}
  /* 空态 */
  #empty{position:fixed;top:0;left:0;right:0;bottom:0;display:flex;flex-direction:column;
    align-items:center;justify-content:center;color:#566071;}
  #empty .e1{font-size:14vmin;opacity:.5;}
  #empty .e2{font-size:4vmin;margin-top:2vmin;font-weight:600;}
</style></head>
<body>
<div id="bar">
  <div id="brand"><span id="spark"></span>Claude<small id="cnt"></small></div>
  <div id="clk"></div>
</div>
<div id="list"></div>
<div id="empty"><div class="e1">◍</div><div class="e2">暂无活动项目</div></div>
<script>
var list=document.getElementById('list'), empty=document.getElementById('empty'),
    spark=document.getElementById('spark'), clk=document.getElementById('clk'), cnt=document.getElementById('cnt');
var cards={};
function makeCard(sid){
  var el=document.createElement('div'); el.className='card';
  var head=document.createElement('div'); head.className='head';
  var proj=document.createElement('div'); proj.className='proj';
  var nm=document.createElement('span');
  proj.appendChild(nm);
  var pill=document.createElement('div'); pill.className='pill';
  var pd=document.createElement('span'); pd.className='d'; var pt=document.createElement('span');
  pill.appendChild(pd); pill.appendChild(pt);
  head.appendChild(proj); head.appendChild(pill);
  var msg=document.createElement('div'); msg.className='msg';
  var detail=document.createElement('div'); detail.className='detail';
  var btns=document.createElement('div'); btns.className='btns';
  var ok=document.createElement('button'); ok.className='b ok'; ok.innerHTML='&#10003; 批准';
  var no=document.createElement('button'); no.className='b no'; no.innerHTML='&#10007; 拒绝';
  btns.appendChild(ok); btns.appendChild(no);
  el.appendChild(head); el.appendChild(msg); el.appendChild(detail); el.appendChild(btns);
  var c={el:el,nm:nm,pill:pill,pd:pd,pt:pt,msg:msg,detail:detail,btns:btns,ok:ok,no:no,
         curReq:'',shownReq:'',sentReq:''};
  ok.onclick=function(){decide(c,'approve');};
  no.onclick=function(){decide(c,'deny');};
  cards[sid]=c; list.appendChild(el);
  return c;
}
function decide(c,d){
  if(!c.curReq) return;
  c.sentReq=c.curReq;
  var x=new XMLHttpRequest();
  x.open('GET','/decide?d='+d+'&req='+encodeURIComponent(c.curReq)+'&t='+(+new Date()),true); x.send();
  c.btns.style.display='none'; c.detail.style.display='none';
  c.msg.style.display='block'; c.msg.textContent=(d==='approve'?'✓ 已批准':'✕ 已拒绝')+' · 处理中…';
  c.curReq='';
}
function renderDiff(box,text){
  while(box.firstChild) box.removeChild(box.firstChild);
  var lines=(text||'').split('\n'), mode='';
  for(var i=0;i<lines.length;i++){
    var ln=lines[i], cls='txt', el=document.createElement('div');
    if(ln.indexOf('────')>=0){
      cls='sep';
      if(ln.indexOf('删除')>=0) mode='del';
      else if(ln.indexOf('新增')>=0) mode='add';
      else if(ln.indexOf('内容预览')>=0) mode='code';
      else mode='';
      ln=ln.replace(/[─\s]/g,'')||'·';
    } else if(ln.charAt(0)==='$'){ cls='cmd'; }
      else if(ln.charAt(0)==='#'){ cls='cmt'; }
      else if(mode==='del'){ cls='del'; }
      else if(mode==='add'){ cls='add'; }
    el.className='ln '+cls; el.textContent=ln; box.appendChild(el);
  }
}
function update(c,s){
  var appr=(s.state==='attention' && s.req);
  c.el.className='card '+s.state;
  c.nm.textContent=s.project||'?';
  if(appr){ c.pt.textContent=s.label||'需要批准'; }
  else { c.pt.textContent=(s.state==='attention'?'需要你':(s.state==='working'?'工作中':'空闲')); }
  if(appr && c.sentReq===s.req){
    c.msg.style.display='block'; c.msg.textContent='已发送 · 处理中…';
    c.detail.style.display='none'; c.btns.style.display='none';
  } else if(appr){
    c.msg.style.display='none';
    c.detail.style.display='block';
    if(c.shownReq!==s.req){ renderDiff(c.detail,s.msg); c.detail.scrollTop=0; c.shownReq=s.req; }
    c.btns.style.display='block'; c.curReq=s.req;
  } else {
    c.msg.style.display='block'; c.msg.textContent=s.msg||'';
    c.detail.style.display='none'; c.btns.style.display='none';
    c.curReq=''; c.shownReq=''; c.sentReq='';
  }
}
function rank(s){ if(s.state==='attention'&&s.req)return 0; if(s.state==='attention')return 1;
                 if(s.state==='working')return 2; return 3; }
function render(d){
  var slots=d.slots||[];
  empty.style.display=slots.length?'none':'flex';
  cnt.textContent=slots.length?('· '+slots.length+' 个项目'):'';
  slots.sort(function(a,b){ var r=rank(a)-rank(b); return r!==0?r:(b.ts||0)-(a.ts||0); });
  var seen={};
  for(var i=0;i<slots.length;i++){
    var s=slots[i], sid=s.sid||('x'+i); seen[sid]=1;
    var c=cards[sid]||makeCard(sid); update(c,s); list.appendChild(c.el);
  }
  for(var k in cards){ if(!seen[k]){ list.removeChild(cards[k].el); delete cards[k]; } }
}
function poll(){
  var x=new XMLHttpRequest();
  x.open('GET','/status?t='+(+new Date()),true); x.timeout=4000;
  x.onreadystatechange=function(){ if(x.readyState===4){
    if(x.status===200){try{render(JSON.parse(x.responseText));spark.style.background='#46d369';}catch(e){spark.style.background='#ff9800';}}
    else{spark.style.background='#ff9800';} } };
  x.onerror=function(){spark.style.background='#ff9800';};
  x.ontimeout=function(){spark.style.background='#ff9800';};
  x.send();
}
function tick(){var t=new Date();function p(n){return(n<10?'0':'')+n;}
  clk.textContent=p(t.getHours())+':'+p(t.getMinutes())+':'+p(t.getSeconds());}
poll();setInterval(poll,1000);tick();setInterval(tick,1000);
</script>
</body></html>"""

def collect_slots():
    out = []
    now = int(time.time())
    try:
        for fn in os.listdir(SLOTS):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(SLOTS, fn)) as f:
                    s = json.load(f)
            except Exception:
                continue
            if now - int(s.get("ts", 0)) <= STALE:
                out.append(s)
    except Exception:
        pass
    return out

def read_usage():
    """读 claude-hud 写的 5h/周 配额快照(usage.json)。返回 used_percentage 和距重置分钟数。"""
    out = {"five_hour": None, "seven_day": None, "fh_reset_min": None, "sd_reset_min": None, "age": None}
    try:
        with open(USAGE) as f:
            u = json.load(f)
    except Exception:
        return out
    import datetime
    now = time.time()
    for key, mk in (("five_hour", "fh_reset_min"), ("seven_day", "sd_reset_min")):
        w = u.get(key) or {}
        try:
            out[key] = int(w.get("used_percentage"))
        except Exception:
            pass
        r = w.get("resets_at")
        if r:
            try:
                dt = datetime.datetime.fromisoformat(str(r).replace("Z", "+00:00"))
                out[mk] = max(0, int((dt.timestamp() - now) / 60))
            except Exception:
                pass
    ua = u.get("updated_at")
    if ua:
        try:
            dt = datetime.datetime.fromisoformat(str(ua).replace("Z", "+00:00"))
            out["age"] = max(0, int(now - dt.timestamp()))
        except Exception:
            pass
    return out

HPC_FILE = os.path.join(DIR, "hpc.json")
# HPC sbatch 监控(可选): 设环境变量 CLAUDE_BOARD_HPC_HOST=<ssh主机别名> 开启。
# 用户默认取 CLAUDE_BOARD_HPC_USER 或 $USER。需本机能免密 ssh 到该主机。
HPC_HOST = os.environ.get("CLAUDE_BOARD_HPC_HOST", "")
HPC_USER = os.environ.get("CLAUDE_BOARD_HPC_USER", os.environ.get("USER", ""))

def hpc_poller():
    """后台每 60s 跑 ssh <host> squeue, 缓存到 hpc.json。HPC 不可达就保留旧值。"""
    if not HPC_HOST:
        return
    while True:
        try:
            r = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", HPC_HOST,
                 "squeue -u %s -h -o '%%i|%%j|%%T|%%M|%%D'" % HPC_USER],
                capture_output=True, text=True, timeout=25)
            jobs = []
            for line in (r.stdout or "").strip().splitlines():
                p = line.split("|")
                if len(p) >= 5:
                    jobs.append({"id": p[0], "name": p[1], "state": p[2], "time": p[3], "nodes": p[4]})
            tmp = HPC_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"jobs": jobs, "ts": int(time.time())}, f, ensure_ascii=False)
            os.replace(tmp, HPC_FILE)
        except Exception:
            pass
        time.sleep(60)

def read_hpc():
    try:
        with open(HPC_FILE) as f:
            d = json.load(f)
        return {"jobs": d.get("jobs", []), "age": int(time.time()) - int(d.get("ts", 0))}
    except Exception:
        return {"jobs": [], "age": None}

def board_assets(view, req):
    """渲染板子 UI -> (png_bytes, hash, buttons, led)。hash=PNG字节md5(状态不变则稳定)。"""
    state = {"slots": collect_slots(), "usage": read_usage(), "hpc": read_hpc(), "now": int(time.time())}
    img, buttons, led, bright = board_render.render(state, view, req)
    buf = io.BytesIO(); img.save(buf, "PNG")
    png = buf.getvalue()
    h = hashlib.md5(png).hexdigest()[:12]
    return png, h, buttons, led, bright

class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        if self.path.startswith("/status"):
            body = json.dumps({"slots": collect_slots(), "usage": read_usage(), "now": int(time.time())},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        elif self.path.startswith("/decide"):
            q = parse_qs(urlparse(self.path).query)
            req = re.sub(r"[^0-9-]", "", (q.get("req", [""])[0]))[:40]
            d = "approve" if q.get("d", [""])[0] == "approve" else "deny"
            if req:
                try:
                    os.makedirs(DECISIONS, exist_ok=True)
                    p = os.path.join(DECISIONS, req)
                    tmp = p + ".tmp"
                    with open(tmp, "w") as f:
                        f.write('{"decision":"%s","ts":%d}' % (d, int(time.time())))
                    os.replace(tmp, p)
                except Exception:
                    pass
            self._send(200, "application/json; charset=utf-8", b'{"ok":true}')
        elif self.path.startswith("/board."):
            if board_render is None:
                self._send(500, "text/plain", b"board_render unavailable"); return
            q = parse_qs(urlparse(self.path).query)
            view = q.get("view", ["list"])[0]
            req = re.sub(r"[^A-Za-z0-9_-]", "", (q.get("req", [""])[0]))[:64]   # 允许 sid(详情视图)
            try:
                png, h, buttons, led, bright = board_assets(view, req)
            except Exception as e:
                self._send(500, "text/plain", str(e).encode("utf-8")); return
            if self.path.startswith("/board.png"):
                # Conditional request: the board sends If-None-Match=<last hash>; reply 304
                # (small) when unchanged, else the PNG. buttons/led/bright ride in headers so
                # the board gets everything in one round-trip (no separate /board.json poll).
                code = 304 if self.headers.get("If-None-Match", "") == h else 200
                self.send_response(code)
                self.send_header("ETag", h)
                self.send_header("X-Led", led)
                self.send_header("X-Bright", str(bright))
                self.send_header("X-Buttons", json.dumps(buttons, ensure_ascii=False))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                if code == 200:
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(png)))
                    self.end_headers()
                    try:
                        self.wfile.write(png)
                    except Exception:
                        pass
                else:
                    self.send_header("Content-Length", "0")
                    self.end_headers()
            else:  # /board.json (kept for compatibility)
                body = json.dumps({"hash": h, "led": led, "bright": bright, "view": view, "buttons": buttons},
                                  ensure_ascii=False).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body)
        elif self.path == "/" or self.path.startswith("/index"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"404")

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    # 多线程: 一个慢/挂死的客户端连接不再堵住整个服务(之前单线程 TCPServer
    # 被板子每秒轮询里偶发的慢连接堵死, 导致所有客户端间歇性连不上)。
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    H.timeout = 15  # 单连接闲置超时, 慢/半开连接最多占住一个线程 15s
    threading.Thread(target=hpc_poller, daemon=True).start()   # HPC sbatch 监控后台轮询
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), H) as httpd:
        print("Claude board (v2 UI, threaded) on :%d" % PORT, flush=True)
        httpd.serve_forever()
