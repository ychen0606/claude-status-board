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

def main():
    state = sys.argv[1] if len(sys.argv) > 1 else "idle"
    msg = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    sid = safe_id(str(data.get("session_id") or "nosid"))
    cwd = str(data.get("cwd") or "")

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

    obj = {"sid": sid, "project": project_name(cwd), "cwd": cwd,
           "state": state, "ts": int(time.time()), "msg": msg, "req": "", "label": ""}
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
