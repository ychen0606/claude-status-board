#!/usr/bin/env bash
# Start (or restart) the status board server, fully detached from the terminal.
# Idempotent: frees the port first. Add to crontab as "@reboot /path/to/start.sh" for autostart.
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${CLAUDE_BOARD_PORT:-8088}"

# Kill whatever currently holds the port, plus any stale server.py
PID="$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)"
[ -n "$PID" ] && kill -9 "$PID" 2>/dev/null
pkill -9 -f "$DIR/server.py" 2>/dev/null
sleep 1

setsid nohup python3 "$DIR/server.py" > "$DIR/server.log" 2>&1 < /dev/null &
sleep 1

if pgrep -f "$DIR/server.py" >/dev/null; then
  echo "Claude status board running on port $PORT"
  IP="$(tailscale ip -4 2>/dev/null | head -1)"
  [ -n "$IP" ] && echo "  Tailscale : http://$IP:$PORT/"
  echo "  Local     : http://127.0.0.1:$PORT/"
else
  echo "Failed to start. See $DIR/server.log"
  cat "$DIR/server.log"
fi
