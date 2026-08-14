#!/bin/bash
# ============================================================================
# OpenGhost — Live2D talking avatar launcher
# ----------------------------------------------------------------------------
# Renders an Open-LLM-VTuber (Live2D + STT + LLM + TTS) session to the
# HyperPixel 4.0 Square (720x720) under the Pepper's Ghost beam splitter.
#
#   Mic --> sherpa-onnx STT --> oobabooga LLM (192.168.2.8) --> edge-tts
#        --> Live2D mouth, all rendered by Chromium in kiosk mode.
#
# This is independent of the py5 sketches — it's a separate display mode.
# Run it from the Pi's desktop (labwc/Wayland) session.
#
# Usage:
#   ./live2d_ghost.sh          # start backend (if needed) + kiosk
#   ./live2d_ghost.sh stop     # stop kiosk + backend, restore display
#   MIRROR=0 ./live2d_ghost.sh # start without the beam-splitter mirror flip
# ============================================================================
set -euo pipefail

# --- Config -----------------------------------------------------------------
OLV_DIR="$HOME/Open-LLM-VTuber"       # Open-LLM-VTuber checkout
OUTPUT="DPI-1"                         # HyperPixel output name (from wlr-randr)
URL="http://localhost:12393"
PORT=12393
MIRROR="${MIRROR:-1}"                 # 1 = flip display horizontally for the reflection
KIOSK_PROFILE="$HOME/.config/openghost-kiosk"   # persists frontend settings (black bg, model scale)

# --- Wayland environment (needed when launched from a non-desktop shell) ----
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export PATH="$HOME/.local/bin:$PATH"   # for uv

log() { echo "[openghost-live2d] $*"; }

stop() {
  log "Stopping kiosk + backend..."
  pkill -f "chromium.*openghost-kiosk" 2>/dev/null || true
  pkill -f "run_server.py" 2>/dev/null || true
  if [ "$MIRROR" = "1" ]; then
    wlr-randr --output "$OUTPUT" --transform normal 2>/dev/null || true
  fi
  log "Stopped."
}

if [ "${1:-}" = "stop" ]; then stop; exit 0; fi

# --- 1. Beam-splitter mirror ------------------------------------------------
# A single 45-degree beam splitter reflects the screen, so the image reads
# mirrored. Flip the whole output at the compositor level (cleanest — no app
# hacks). If your optical path doesn't need it, run with MIRROR=0.
if [ "$MIRROR" = "1" ]; then
  log "Mirroring $OUTPUT for the beam splitter (transform flipped)"
  wlr-randr --output "$OUTPUT" --transform flipped
fi

# --- 2. Backend (Open-LLM-VTuber) ------------------------------------------
if curl -s -m2 "http://localhost:$PORT/" >/dev/null 2>&1; then
  log "Backend already running on :$PORT"
else
  log "Starting Open-LLM-VTuber backend..."
  ( cd "$OLV_DIR" && nohup uv run run_server.py > /tmp/olv_server.log 2>&1 & )
  log "Waiting for backend to come up..."
  for i in $(seq 1 120); do
    curl -s -m2 "http://localhost:$PORT/" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -s -m2 "http://localhost:$PORT/" >/dev/null 2>&1 \
    && log "Backend is up." \
    || { log "ERROR: backend did not start — see /tmp/olv_server.log"; exit 1; }
fi

# --- 3. Chromium kiosk on the HyperPixel -----------------------------------
# --use-fake-ui-for-media-stream auto-grants the mic (no prompt in kiosk).
# --autoplay-policy lets the avatar's TTS audio play without a user gesture.
# --remote-debugging-port + --remote-allow-origins let the injector (step 4)
#   apply the Pepper's Ghost look and enable hands-free mic over DevTools.
# Fixed --user-data-dir persists the mic-autostart flag across reboots.
log "Launching Chromium kiosk at $URL"
chromium-browser \
  --ozone-platform=wayland \
  --kiosk "$URL" \
  --user-data-dir="$KIOSK_PROFILE" \
  --password-store=basic \
  --remote-debugging-port=9222 \
  --remote-allow-origins=* \
  --window-size=720,720 \
  --window-position=0,0 \
  --start-fullscreen \
  --use-fake-ui-for-media-stream \
  --autoplay-policy=no-user-gesture-required \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000 \
  --overscroll-history-navigation=0 &
CHROME_PID=$!

# --- 4. Apply Pepper's Ghost look + hands-free mic (via DevTools) -----------
# Background is already black (backgrounds/ceiling-window-room-night.jpeg was
# replaced with black). This hides the UI/cursor and arms the mic.
log "Applying ghost look + hands-free mic..."
"$OLV_DIR/.venv/bin/python" "$(dirname "$0")/openghost_kiosk_inject.py" || \
  log "WARN: injector failed; model is up but UI may be visible"

wait "$CHROME_PID"
