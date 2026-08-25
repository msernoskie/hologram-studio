#!/bin/bash
# ============================================================================
# stage3d — run the head-coupled 3D spinoff and put it on the cube.
#   stage.sh start|stop|status   the little server on :8801
#   stage.sh show                open/activate the 3D stage tab on the kiosk
#   stage.sh hide                back to the Live2D avatar (closes the tab)
# The kiosk keeps running either way — this only switches which tab is
# visible, so `hide` restores the avatar exactly as it was.
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PIDFILE=/tmp/stage3d.pid
LOG="$HOME/stage3d.log"
URL="http://localhost:8801/"
DBG="http://localhost:9222"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

tab_id() {  # id of the first kiosk page whose URL contains $1
  curl -s -m3 "$DBG/json" | python3 -c '
import json, sys
for t in json.load(sys.stdin):
    if t.get("type") == "page" and sys.argv[1] in t.get("url", ""):
        print(t["id"]); break' "$1"
}

case "${1:-status}" in
  start)
    [ -d "$HERE/vendor" ] || { echo "no vendor libs — run: $HERE/get_vendor.sh"; exit 1; }
    if running; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    nohup python3 -u "$HERE/server.py" >"$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 1
    running && echo "stage3d server on :8801 — log: $LOG" \
            || { echo "failed to start:"; tail -5 "$LOG"; exit 1; } ;;
  stop)
    if running; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; fi
    rm -f "$PIDFILE"
    echo "stage3d server stopped" ;;
  show)
    running || "$0" start
    id="$(tab_id 8801)"
    if [ -z "$id" ]; then
      # newer Chromium wants PUT for /json/new — and this build ignores the
      # ?url= parameter entirely (tab opens as about:blank), so create the tab
      # and then navigate it over the DevTools websocket
      curl -s -m3 -X PUT "$DBG/json/new" >/dev/null || curl -s -m3 "$DBG/json/new" >/dev/null
      sleep 1
      PYV="$HOME/Open-LLM-VTuber/.venv/bin/python"   # has websocket-client
      [ -x "$PYV" ] || PYV=python3
      "$PYV" - "$URL" <<'EOF'
import json, sys, urllib.request
from websocket import create_connection
url = sys.argv[1]
for t in json.load(urllib.request.urlopen("http://localhost:9222/json")):
    if t.get("type") == "page" and t.get("url") == "about:blank":
        ws = create_connection(t["webSocketDebuggerUrl"])
        ws.send(json.dumps({"id": 1, "method": "Page.navigate",
                            "params": {"url": url}}))
        ws.recv()
        ws.close()
        break
EOF
      sleep 2
      id="$(tab_id 8801)"
    fi
    [ -n "$id" ] || { echo "could not open the stage tab — kiosk running on :9222?"; exit 1; }
    curl -s -m3 "$DBG/json/activate/$id" >/dev/null
    echo "3D stage is on the glass — 'stage.sh hide' brings the avatar back" ;;
  hide)
    olv="$(tab_id 12393)"
    [ -n "$olv" ] && curl -s -m3 "$DBG/json/activate/$olv" >/dev/null
    sid="$(tab_id 8801)"
    [ -n "$sid" ] && curl -s -m3 "$DBG/json/close/$sid" >/dev/null
    echo "back to the Live2D avatar" ;;
  status)
    if running; then echo "server: running (pid $(cat "$PIDFILE"))"; else echo "server: not running"; fi
    [ -n "$(tab_id 8801 2>/dev/null)" ] && echo "kiosk: 3D stage tab is open" || echo "kiosk: avatar only" ;;
  *)
    echo "usage: stage.sh {start|stop|show|hide|status}"; exit 1 ;;
esac
