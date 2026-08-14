#!/bin/bash
# Reset the current model's framing to its registered default (model_dict kScale,
# centered). Applies live if the kiosk is running, and clears the saved override.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OLV="$HOME/Open-LLM-VTuber"
PY="$OLV/.venv/bin/python"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

model=$(grep -E 'live2d_model_name:' "$OLV/conf.yaml" | grep -oE "'[^']*'" | head -1 | tr -d "'")
scale=$("$PY" -c "import json;d=json.load(open('$OLV/model_dict.json'));print(next((m.get('kScale',0.6) for m in d if m['name']=='$model'),0.6))")

js="(()=>{try{const m=getLive2DManager()._models.at(0)._modelMatrix._tr;const f={scale:$scale,x:0,y:0};window.__ghostFrame=f;m[0]=f.scale;m[5]=f.scale;m[12]=0;m[13]=0;return f;}catch(e){return{error:String(e)};}})()"
"$PY" "$HERE/cdp_eval.py" "$js" >/dev/null 2>&1 || true

"$PY" - "$HERE/framing.json" "$model" "$scale" <<'PY'
import json, os, sys
fp, model, scale = sys.argv[1], sys.argv[2], float(sys.argv[3])
data = {}
if os.path.exists(fp):
    try: data = json.load(open(fp, encoding="utf-8"))
    except Exception: data = {}
data[model] = {"scale": round(scale, 3), "x": 0.0, "y": 0.0}
json.dump(data, open(fp, "w"), indent=2)
print(f"{model}: reset to scale={round(scale,3)}  x=0  y=0")
PY
