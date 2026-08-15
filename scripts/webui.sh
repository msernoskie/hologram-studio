#!/bin/bash
# ============================================================================
# OpenGhost — start/stop the hologram studio web UI (port 8800).
#   webui.sh start | stop | status | debug
# UI: http://<pi-ip>:8800  — swap models, fire emotes, build labeled
# emote sequences, export labels for AI use.
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="python3"
SRV="$HERE/../webui/server.py"
LOG="$HOME/openghost-webui.log"
PIDFILE="/tmp/openghost-webui.pid"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-start}" in
  start)
    if running; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    nohup "$PY" -u "$SRV" >"$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 1
    if running; then
      ip=$(hostname -I | awk '{print $1}')
      echo "web UI running: http://${ip}:8800  (log: $LOG)"
    else
      echo "failed to start:"; tail -5 "$LOG"; exit 1
    fi ;;
  debug)
    exec "$PY" -u "$SRV" ;;
  stop)
    if running; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; fi
    rm -f "$PIDFILE"; echo "web UI stopped" ;;
  status)
    if running; then echo "running (pid $(cat "$PIDFILE"))"; tail -2 "$LOG";
    else echo "not running"; fi ;;
  *) echo "usage: webui.sh {start|stop|status|debug}"; exit 1 ;;
esac
