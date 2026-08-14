#!/bin/bash
# ============================================================================
# OpenGhost — framing core (internal; called by up/down/zoom/left/right/reset).
#   _frame.sh <dScale> <dX> <dY>
# Adjusts the CURRENTLY ACTIVE model's on-screen scale/position:
#   * live over CDP (instant, if the kiosk is running)
#   * persisted to framing.json per-model, so it survives reload + reboot
# Y is +up / -down, X is +right / -left, scale is bigger = zoomed in.
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OLV="$HOME/Open-LLM-VTuber"
PY="$OLV/.venv/bin/python"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

dS="${1:-0}"; dX="${2:-0}"; dY="${3:-0}"
model=$(grep -E 'live2d_model_name:' "$OLV/conf.yaml" | grep -oE "'[^']*'" | head -1 | tr -d "'")

# Live update: read current frame (window.__ghostFrame, else the live matrix),
# apply the delta, store it back on window.__ghostFrame, and push it to the
# matrix immediately. Returns the new frame object (or {error:...} on failure).
js="(()=>{try{
  const md=getLive2DManager()._models.at(0);
  const m=md._modelMatrix._tr;
  let f=window.__ghostFrame; if(!f){f={scale:m[0],x:m[12],y:m[13]};}
  f={scale:Math.max(0.1,f.scale+($dS)),x:f.x+($dX),y:f.y+($dY)};
  window.__ghostFrame=f;
  m[0]=f.scale; m[5]=f.scale; m[12]=f.x; m[13]=f.y;
  return f;
}catch(e){return {error:String(e)};}})()"
live="$("$PY" "$HERE/cdp_eval.py" "$js" 2>/dev/null || true)"

# Persist (python is authoritative for the file). Prefer the live result; if the
# kiosk was unreachable, nudge the stored value by the same delta so the file
# still advances and the change applies on next launch.
"$PY" - "$HERE/framing.json" "$model" "$live" "$dS" "$dX" "$dY" <<'PY'
import json, os, sys
fp, model, raw, dS, dX, dY = sys.argv[1:7]
data = {}
if os.path.exists(fp):
    try: data = json.load(open(fp, encoding="utf-8"))
    except Exception: data = {}
frame = None
try:
    j = json.loads(raw) if raw.strip() else None
    if isinstance(j, dict) and "scale" in j:
        frame = {"scale": float(j["scale"]), "x": float(j["x"]), "y": float(j["y"])}
except Exception:
    pass
live_ok = frame is not None
if frame is None:  # kiosk not reachable — nudge stored value (or a sane default)
    base = data.get(model, {"scale": 0.9, "x": 0.0, "y": 0.0})
    frame = {"scale": max(0.1, base["scale"] + float(dS)),
             "x": base["x"] + float(dX), "y": base["y"] + float(dY)}
data[model] = {"scale": round(frame["scale"], 3), "x": round(frame["x"], 3), "y": round(frame["y"], 3)}
json.dump(data, open(fp, "w"), indent=2)
f = data[model]
tag = "live" if live_ok else "saved (kiosk offline — applies next launch)"
print(f"{model}:  scale={f['scale']}  x={f['x']}  y={f['y']}   [{tag}]")
PY
