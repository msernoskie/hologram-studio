#!/bin/bash
# Show the current model's saved framing and its live on-screen transform.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OLV="$HOME/Open-LLM-VTuber"
PY="$OLV/.venv/bin/python"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

model=$(grep -E 'live2d_model_name:' "$OLV/conf.yaml" | grep -oE "'[^']*'" | head -1 | tr -d "'")
echo "Active model: $model"
"$PY" -c "import json;d=json.load(open('$HERE/framing.json'));print('  saved framing:',d.get('$model','(none — using registered default)'))" 2>/dev/null || echo "  saved framing: (no framing.json)"
live="$("$PY" "$HERE/cdp_eval.py" '(()=>{try{const m=getLive2DManager()._models.at(0)._modelMatrix._tr;return JSON.stringify({scale:+m[0].toFixed(3),x:+m[12].toFixed(3),y:+m[13].toFixed(3)});}catch(e){return "offline";}})()' 2>/dev/null | tr -d '\\"' || true)"
echo "  live on-screen: ${live:-kiosk not running}"
