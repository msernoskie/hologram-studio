#!/bin/bash
# ============================================================================
# stage3d — fetch the JS libraries (not committed, like scripts/get_models.sh).
#   get_vendor.sh            three.js + GLTFLoader + three-vrm
#   get_vendor.sh --sample   also drop pixiv's MIT sample avatar in models/
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
THREE=0.170.0
CDN="https://cdn.jsdelivr.net/npm"

mkdir -p "$HERE/vendor/addons/loaders" "$HERE/vendor/addons/utils" "$HERE/models"

get() { echo "  $2"; curl -fsSL -o "$HERE/vendor/$2" "$1"; }
echo "fetching vendor libs (three $THREE, three-vrm 3)…"
get "$CDN/three@$THREE/build/three.module.js"                       three.module.js
get "$CDN/three@$THREE/examples/jsm/loaders/GLTFLoader.js"          addons/loaders/GLTFLoader.js
get "$CDN/three@$THREE/examples/jsm/utils/BufferGeometryUtils.js"   addons/utils/BufferGeometryUtils.js
get "$CDN/@pixiv/three-vrm@3/lib/three-vrm.module.min.js"           three-vrm.module.min.js

if [ "${1:-}" = "--sample" ]; then
  echo "fetching sample VRM avatar (pixiv/three-vrm, MIT)…"
  curl -fsSL -o "$HERE/models/sample.vrm" \
    "https://raw.githubusercontent.com/pixiv/three-vrm/dev/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm"
fi
echo "done."
