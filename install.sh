#!/usr/bin/env bash
# Prints the Claude Code hooks block with this repo's absolute path filled in,
# so you can paste it into ~/.claude/settings.json. Does NOT edit your settings
# automatically (to avoid clobbering an existing config).
DIR="$(cd "$(dirname "$0")" && pwd)"
cat <<EOF
Add (or merge) the following "hooks" block into ~/.claude/settings.json:

  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 $DIR/slot.py working" } ] }
    ],
    "PreToolUse": [
      { "matcher": "*", "hooks": [ { "type": "command", "command": "python3 $DIR/approve_gate.py", "timeout": 100 } ] }
    ],
    "PostToolUse": [
      { "matcher": "*", "hooks": [ { "type": "command", "command": "python3 $DIR/slot.py working" } ] }
    ],
    "Notification": [
      { "hooks": [ { "type": "command", "command": "python3 $DIR/slot.py notify" } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": "python3 $DIR/slot.py idle" } ] }
    ],
    "SessionEnd": [
      { "hooks": [ { "type": "command", "command": "python3 $DIR/slot.py end" } ] }
    ]
  }

Then start the board:   $DIR/start.sh
Open in a browser:      http://<host>:8088/
Enable remote approval: touch $DIR/gate_enabled   (disable: rm $DIR/gate_enabled)
EOF
