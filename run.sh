#!/bin/bash
# Usage: ./run.sh <sketch.py>   e.g.  ./run.sh lorenz_attractor.py
# Activates the venv, points py5 at the HyperPixel X display, and runs the sketch.
cd "$(dirname "$0")"
source .venv/bin/activate

# py5's Java/JOGL backend needs an X display. On Raspberry Pi OS (labwc/Wayland)
# Xwayland provides one on :0 — without this py5 errors out as "headless".
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

if [ -z "$1" ]; then
  echo "Usage: ./run.sh <sketch.py>"
  echo "Available sketches:"
  ls *.py
  exit 1
fi

exec python "$1"
