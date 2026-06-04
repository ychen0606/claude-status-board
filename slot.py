#!/usr/bin/env python3
# 按会话分槽的状态写入器（被 UserPromptSubmit/PostToolUse/Notification/Stop/SessionEnd 调用）
# 用法: slot.py <state> [msg]      state ∈ working|attention|idle|end
# 从 hook 的 stdin JSON 读取 session_id + cwd，写 slots/<sid>.json；end=删除该会话的槽。
import sys, json, os, time, re

DIR = os.path.dirname(os.path.abspath(__file__))
SLOTS = os.path.join(DIR, "slots")
HOME = os.path.expanduser("~")

def project_name(cwd):
    if not cwd:
        return "?"
    cwd = cwd.rstrip("/")
    if cwd in (HOME, ""):
        return "~"
    return os.path.basename(cwd) or cwd

def safe_id(sid):
    return re.sub(r"[^A-Za-z0-9_-]", "", sid)[:64] or "nosid"

def tool_summary(data):
    """从 hook stdin 的 tool_name/tool_input 概括正在跑的命令。"""
    tn = str(data.get("tool_name") or "")
    ti = data.get("tool_input") or {}
    if not tn:
        return ""
    try:
        if tn == "Bash":
            c = str(ti.get("command", "")).strip().replace("\n", " ")
            return ("Bash: " + c) if c else "Bash"
        if tn in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            return tn + ": " + os.path.basename(str(ti.get("file_path", "")))
        if tn == "Read":
            return "Read: " + os.path.basename(str(ti.get("file_path", "")))
        if tn in ("Grep", "Glob"):
            return tn + ": " + str(ti.get("pattern", ""))
        if tn == "Task":
            return "Agent: " + str(ti.get("description", ""))
        if tn == "WebFetch":
            return "WebFetch: " + str(ti.get("url", ""))
        return tn
    except Exception:
        return tn

def extract_model(data):
    m = data.get("model")
    if isinstance(m, dict):
        return str(m.get("display_name") or m.get("id") or "")
    if isinstance(m, str):
        return m
    return ""

def main():
    state = sys.argv[1] if len(sys.argv) > 1 else "idle"
    msg = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    sid = safe_id(str(data.get("session_id") or "nosid"))
    cwd = str(data.get("cwd") or "")
    event = str(data.get("hook_event_name", ""))   # PostToolUse/UserPromptSubmit/Notification/Stop
    # working 状态优先用真实工具命令(PostToolUse 才有 tool_name)
    if state == "working":
        ts_sum = tool_summary(data)
        if ts_sum:
            msg = ts_sum

    # Notification 事件：区分「真要权限」和「只是闲置等你输入」
    if state == "notify":
        m = str(data.get("message", "")).lower()
        if ("permission" in m) or ("approve" in m) or ("授权" in m) or ("confirm" in m):
            state, msg = "attention", "需要授权 — 去键盘确认"
        else:
            state, msg = "idle", "等你输入…"

    path = os.path.join(SLOTS, sid + ".json")

    if state == "end":
        try:
            os.remove(path)
        except Exception:
            pass
        return

    now = int(time.time())
    # 保留会话起始时间(算运行时长) + 模型(一次抓到后持续保留)
    old = {}
    try:
        with open(path) as f:
            old = json.load(f)
    except Exception:
        old = {}
    # 关键: 待授权(attention)被钉住, 不许并发 agent 的"运行中"覆盖, 只刷新 ts 防过期。
    # 否则多 agent 时一个弹权限、另一个在干活, 板子还没轮询到 attention 就被冲成 working → 不提醒。
    PIN_S = 60
    pinned = old.get("state") == "attention" and int(old.get("pin_until", 0) or 0) > now
    if state == "working" and pinned and event != "UserPromptSubmit":
        try:
            old["ts"] = now
            tmp = path + ".tmp.%d" % os.getpid()
            with open(tmp, "w") as ff:
                json.dump(old, ff, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass
        return

    start_ts = old.get("start_ts") or now
    model = extract_model(data) or old.get("model") or ""
    # 工作→空闲 = 刚完成一个任务(会话完成提醒用); 重新工作时清掉
    done_ts = old.get("done_ts", 0)
    if state == "idle" and old.get("state") == "working":
        done_ts = now
    elif state == "working":
        done_ts = 0
    # 钉住/解钉: attention 钉 60s; 用户回应(UserPromptSubmit)/结束(Stop)/空闲 解钉
    pin_until = int(old.get("pin_until", 0) or 0)
    if state == "attention":
        pin_until = now + PIN_S
    elif state == "idle" or event in ("UserPromptSubmit", "Stop"):
        pin_until = 0

    obj = {"sid": sid, "project": project_name(cwd), "cwd": cwd,
           "state": state, "ts": now, "start_ts": start_ts, "model": model,
           "done_ts": done_ts, "pin_until": pin_until, "msg": msg, "req": "", "label": ""}
    try:
        os.makedirs(SLOTS, exist_ok=True)
        tmp = path + ".tmp.%d" % os.getpid()
        with open(tmp, "w") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass

if __name__ == "__main__":
    main()
