#!/bin/bash
# ============================================================================
# OpenGhost — start/stop the gesture control sidecar.
#   gesture_ctl.sh start    run in the background (log: ~/openghost-gesture.log)
#   gesture_ctl.sh debug    run in the FOREGROUND with per-frame gesture output
#   gesture_ctl.sh stop     stop it (releases the camera)
#   gesture_ctl.sh status   is it running?
# Extra args are passed through, e.g.:  gesture_ctl.sh debug --no-invert-x
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HOME/OpenGhost/gesture-venv/bin/python"
LOG="$HOME/openghost-gesture.log"
PIDFILE="/tmp/openghost-gesture.pid"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

cmd="${1:-start}"; shift || true

case "$cmd" in
  start)
    if running; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
    # mediapipe's C++ layer chatters on stderr regardless of log-level env vars,
    # so it goes to its own file and $LOG stays readable
    nohup "$PY" -u "$HERE/gesture_ctl.py" "$@" >"$LOG" 2>"$LOG.stderr" &
    echo $! > "$PIDFILE"
    sleep 3
    if running; then
      echo "gesture control started (pid $(cat "$PIDFILE")) — log: $LOG"
      grep -E "^\[gesture\]|error|Error|Traceback" "$LOG" | head -3 || true
    else
      echo "failed to start — last lines of $LOG:"; tail -5 "$LOG"; exit 1
    fi ;;
  debug)
    exec "$PY" "$HERE/gesture_ctl.py" --debug "$@" ;;
  sethome)
    # snapshot the framing on screen right now as what the panic hold restores.
    # No camera needed, so it works fine while the sidecar is running.
    exec "$PY" "$HERE/gesture_ctl.py" --set-home ;;
  hands)
    # toggle hand-gesture mode LIVE (no restart) — the sidecar checks this flag
    # file every frame. Face tracking is unaffected either way.
    case "${1:-}" in
      on)  rm -f "$HERE/.hands_off"; echo "hand gestures ENABLED" ;;
      off) touch "$HERE/.hands_off"; echo "hand gestures DISABLED — face tracking stays on" ;;
      *)   if [ -f "$HERE/.hands_off" ]; then echo "hand gestures: off (face tracking only)";
           else echo "hand gestures: on"; fi ;;
    esac ;;
  stop)
    if running; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; fi
    rm -f "$PIDFILE"
    # the camera child can outlive the parent; the bracket keeps this pattern
    # from matching (and killing) the shell that is running it
    pkill -f "[r]picam-vid --codec yuv420" 2>/dev/null || true
    echo "gesture control stopped" ;;
  status)
    if running; then echo "running (pid $(cat "$PIDFILE"))"; else echo "not running"; fi
    if [ -f "$HERE/.hands_off" ]; then echo "hand gestures: off (face tracking only)";
    else echo "hand gestures: on"; fi
    if running; then tail -3 "$LOG"; fi ;;
  *)
    echo "usage: gesture_ctl.sh {start|debug|stop|status|sethome|hands on|off} [--no-invert-x] [--invert-y] [--rotate 180]"; exit 1 ;;
esac
