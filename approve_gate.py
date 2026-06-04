#!/usr/bin/env python3
# PreToolUse 网关（按会话分槽版）：受控工具亮红灯，等平板「批准/拒绝」，显示要批的内容。
# 安全：默认不放行；超时回退键盘 TUI（输出 ask）；任何异常都不自动 allow。
# 启用：存在 gate_enabled 文件 或 环境变量 GATE_FORCE 时才拦截。
import sys, json, os, time, re

DIR = os.path.dirname(os.path.abspath(__file__))
SLOTS = os.path.join(DIR, "slots")
DECISIONS = os.path.join(DIR, "decisions")
SETTINGS_LOCAL = os.path.expanduser("~/.claude/settings.local.json")
ENABLED_FLAG = os.path.join(DIR, "gate_enabled")
HOME = os.path.expanduser("~")
GATED_TOOLS = {"Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "Task"}
TIMEOUT = 90.0
POLL = 0.3

def is_gated(tool):
    # 5 类写/执行工具 + WebFetch + 子代理(Task) + 所有 MCP 工具(mcp__server__tool)
    return tool in GATED_TOOLS or tool.startswith("mcp__")

def project_name(cwd):
    if not cwd:
        return "?"
    cwd = cwd.rstrip("/")
    if cwd in (HOME, ""):
        return "~"
    return os.path.basename(cwd) or cwd

def safe_id(sid):
    return re.sub(r"[^A-Za-z0-9_-]", "", sid)[:64] or "nosid"

def write_slot(sid, cwd, state, msg="", req="", label=""):
    now = int(time.time())
    path = os.path.join(SLOTS, sid + ".json")
    # 待授权被钉住时, 并发 agent 的"运行中"不许覆盖(只刷新 ts)
    if state == "working":
        try:
            with open(path) as f:
                old = json.load(f)
        except Exception:
            old = {}
        if old.get("state") == "attention" and int(old.get("pin_until", 0) or 0) > now:
            try:
                old["ts"] = now
                tmp = path + ".tmp.%d" % os.getpid()
                with open(tmp, "w") as ff:
                    json.dump(old, ff, ensure_ascii=False)
                os.replace(tmp, path)
            except Exception:
                pass
            return
    obj = {"sid": sid, "project": project_name(cwd), "cwd": cwd,
           "state": state, "ts": now, "msg": msg, "req": req, "label": label,
           "pin_until": (now + 95) if state == "attention" else 0}
    try:
        os.makedirs(SLOTS, exist_ok=True)
        tmp = path + ".tmp.%d" % os.getpid()
        with open(tmp, "w") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass

def read_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}

def bash_allowlisted(cmd):
    try:
        d = json.load(open(SETTINGS_LOCAL))
        allow = d.get("permissions", {}).get("allow", [])
    except Exception:
        return False
    c = cmd.strip()
    for r in allow:
        if r == "Bash":
            return True
        if not (r.startswith("Bash(") and r.endswith(")")):
            continue
        inner = r[5:-1].strip()
        if inner.endswith(":*"):
            pre = inner[:-2]
            if pre and (c == pre or c.startswith(pre)):
                return True
        else:
            if c == inner or c.startswith(inner + " "):
                return True
    return False

def clip(s, maxlines, maxchars):
    s = (s or "").replace("\r", "")
    lines = s.split("\n")
    if len(lines) > maxlines:
        lines = lines[:maxlines] + ["… (还有 %d 行)" % (len(lines) - maxlines)]
    out = "\n".join(lines)
    if len(out) > maxchars:
        out = out[:maxchars] + "…"
    return out

def describe(tool, ti):
    if tool == "Bash":
        cmd = str(ti.get("command", ""))
        desc = str(ti.get("description", "") or "")
        return "Bash 命令", ("# " + desc + "\n\n" if desc else "") + "$ " + clip(cmd, 25, 700)
    if tool == "Write":
        fp = str(ti.get("file_path", ""))
        content = str(ti.get("content", ""))
        nb = len(content.encode("utf-8", "ignore"))
        nl = content.count("\n") + 1
        return "写入文件", "%s\n(%d 行 · %d 字节)\n──────── 内容预览 ────────\n%s" % (fp, nl, nb, clip(content, 16, 600))
    if tool == "Edit":
        fp = str(ti.get("file_path", ""))
        return "修改文件", "%s\n──────── 删除 ────────\n%s\n──────── 新增 ────────\n%s" % (
            fp, clip(str(ti.get("old_string", "")), 9, 350), clip(str(ti.get("new_string", "")), 9, 350))
    if tool == "MultiEdit":
        fp = str(ti.get("file_path", ""))
        edits = ti.get("edits", []) or []
        parts = ["%s  (%d 处编辑)" % (fp, len(edits))]
        for i, e in enumerate(edits[:3]):
            parts.append("【%d】删: %s\n    增: %s" % (i + 1,
                         clip(str(e.get("old_string", "")), 3, 140), clip(str(e.get("new_string", "")), 3, 140)))
        if len(edits) > 3:
            parts.append("… 还有 %d 处" % (len(edits) - 3))
        return "批量修改", "\n".join(parts)
    if tool == "NotebookEdit":
        fp = str(ti.get("notebook_path", ""))
        return "Notebook 编辑", "%s\n──────────\n%s" % (fp, clip(str(ti.get("new_source", "")), 14, 450))
    if tool == "WebFetch":
        return "联网抓取", "%s\n──────────\n%s" % (str(ti.get("url", "")), clip(str(ti.get("prompt", "")), 8, 320))
    if tool == "Task":
        return "派子代理", "%s  [%s]\n──────────\n%s" % (
            str(ti.get("description", "")), str(ti.get("subagent_type", "")),
            clip(str(ti.get("prompt", "")), 12, 450))
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        name = (parts[1] + " · " + parts[2]) if len(parts) >= 3 else tool
        try:
            preview = json.dumps(ti, ensure_ascii=False, indent=1)
        except Exception:
            preview = str(ti)
        return "MCP 调用", name + "\n──────────\n" + clip(preview, 15, 450)
    return tool, ""

def prune_decisions():
    try:
        now = time.time()
        for fn in os.listdir(DECISIONS):
            p = os.path.join(DECISIONS, fn)
            try:
                if now - os.path.getmtime(p) > 600:
                    os.remove(p)
            except Exception:
                pass
    except Exception:
        pass

def emit(decision, reason):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
           "permissionDecision": decision, "permissionDecisionReason": reason}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()

def main():
    data = read_stdin()
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    sid = safe_id(str(data.get("session_id") or "nosid"))
    cwd = str(data.get("cwd") or "")

    enabled = os.path.exists(ENABLED_FLAG) or bool(os.environ.get("GATE_FORCE"))
    if not enabled or not is_gated(tool):
        write_slot(sid, cwd, "working", "运行中…")
        return
    if tool == "Bash" and bash_allowlisted(str(ti.get("command", ""))):
        write_slot(sid, cwd, "working", "运行中…")
        return

    os.makedirs(DECISIONS, exist_ok=True)
    prune_decisions()
    badge, detail = describe(tool, ti)
    req = "%d-%d" % (os.getpid(), int(time.time() * 1000))
    decision_path = os.path.join(DECISIONS, re.sub(r"[^0-9-]", "", req))
    try:
        os.remove(decision_path)
    except Exception:
        pass
    write_slot(sid, cwd, "attention", detail, req, badge)

    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        dec = None
        try:
            with open(decision_path) as f:
                dec = json.load(f)
        except Exception:
            dec = None
        if dec:
            try:
                os.remove(decision_path)
            except Exception:
                pass
            if dec.get("decision") == "approve":
                write_slot(sid, cwd, "working", "已批准 · 运行中…")
                emit("allow", "平板批准")
                return
            write_slot(sid, cwd, "idle", "已拒绝 %s" % badge)
            emit("deny", "用户在平板上拒绝了这个%s" % badge)
            return
        time.sleep(POLL)

    write_slot(sid, cwd, "attention", "平板超时，请用键盘确认")
    emit("ask", "平板未响应，转键盘确认")

if __name__ == "__main__":
    main()
