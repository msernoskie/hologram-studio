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

# When the systemd user service is installed (openghost-webui.service — always
# on, restarts on crash), it is the one canonical way to run the server; this
# script just drives it. The nohup path below is the fallback for setups
# without the service.
svc() { systemctl --user "$1" openghost-webui 2>/dev/null; }
have_svc() { systemctl --user cat openghost-webui >/dev/null 2>&1; }

case "${1:-start}" in
  start)
    if have_svc; then
      svc start
      sleep 1
      ip=$(hostname -I | awk '{print $1}')
      svc is-active >/dev/null && echo "web UI running (systemd): http://${ip}:8800" \
        || { echo "service failed:"; journalctl --user -u openghost-webui -n 5 --no-pager; exit 1; }
      exit 0
    fi
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
    have_svc && svc stop
    exec "$PY" -u "$SRV" ;;
  stop)
    if have_svc; then svc stop; echo "web UI stopped (systemd — restarts on next boot)"; exit 0; fi
    if running; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; fi
    rm -f "$PIDFILE"; echo "web UI stopped" ;;
  status)
    if have_svc; then
      svc is-active >/dev/null && echo "running (systemd service)" || echo "not running (systemd service installed)"
      journalctl --user -u openghost-webui -n 2 --no-pager 2>/dev/null || true
      exit 0
    fi
    if running; then echo "running (pid $(cat "$PIDFILE"))"; tail -2 "$LOG";
    else echo "not running"; fi ;;
  *) echo "usage: webui.sh {start|stop|status|debug}"; exit 1 ;;
esac
