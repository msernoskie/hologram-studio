#!/bin/bash
# ============================================================================
# OpenGhost — switch the active Live2D model
#   ./switch_model.sh            list installed models + show the current one
#   ./switch_model.sh <name>     make <name> the active model (persists)
#
# Updates conf.yaml, restarts the Open-LLM-VTuber backend, and (if the kiosk
# is running) reloads the display and re-applies the Pepper's Ghost look.
# The choice is written to conf.yaml, so it survives reboots / autostart.
# ============================================================================
set -euo pipefail

OLV_DIR="$HOME/Open-LLM-VTuber"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$OLV_DIR/.venv/bin/python"
export PATH="$HOME/.local/bin:$PATH"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
cd "$OLV_DIR"

current=$(grep -E 'live2d_model_name:' conf.yaml | grep -oE "'[^']*'" | head -1 | tr -d "'")
models=$("$PY" -c "import json;print(' '.join(m['name'] for m in json.load(open('model_dict.json'))))")

# --- No argument: list ------------------------------------------------------
if [ $# -eq 0 ]; then
  echo "Current model: $current"
  echo "Installed models (from model_dict.json):"
  for m in $models; do
    [ "$m" = "$current" ] && echo "  * $m   (current)" || echo "    $m"
  done
  echo
  echo "Usage: $0 <model-name>"
  exit 0
fi

target="$1"
if ! echo "$models" | tr ' ' '\n' | grep -qx "$target"; then
  echo "Unknown model '$target'."
  echo "Available: $models"
  echo "(Add new ones to $OLV_DIR/model_dict.json + live2d-models/ — see README-Live2D.md)"
  exit 1
fi

if [ "$target" = "$current" ]; then
  echo "'$target' is already the active model."
fi

# --- Set conf.yaml (single-line, value-only replace) ------------------------
"$PY" - "$target" <<'PY'
import re, sys
t = sys.argv[1]
s = open("conf.yaml", encoding="utf-8").read()
s = re.sub(r"(\n\s*live2d_model_name:\s*)'[^']*'", r"\1'%s'" % t, s, count=1)
open("conf.yaml", "w", encoding="utf-8").write(s)
PY
echo "conf.yaml -> live2d_model_name: '$target'"

# --- Restart backend --------------------------------------------------------
# (bracket pattern targets the real python process, not this script's argv)
pkill -f "[r]un_server.py" 2>/dev/null || true
sleep 2
setsid bash -c "export PATH=\"\$HOME/.local/bin:\$PATH\" && cd '$OLV_DIR' && exec uv run run_server.py" \
  > /tmp/olv_server.log 2>&1 < /dev/null &
disown 2>/dev/null || true
printf "Restarting backend"
for i in $(seq 1 90); do
  curl -s -m2 -o /dev/null http://localhost:12393/ && break
  printf "."; sleep 1
done
echo " up."

# --- Reload the kiosk display (if running) ----------------------------------
if curl -s -m2 -o /dev/null http://localhost:9222/json 2>/dev/null; then
  "$PY" "$HERE/cdp_eval.py" 'location.reload(); "reload"' >/dev/null 2>&1 || true
  sleep 12
  "$PY" "$HERE/openghost_kiosk_inject.py" || true
  echo "Display now showing: $target"
else
  echo "Kiosk not running — start it with: $HERE/live2d_ghost.sh"
fi
