#!/bin/bash
# ============================================================================
# OpenGhost — cycle / set the active model's expression(s) ("emotes").
#   emote.sh                     step to the NEXT emote (cycles through all)
#   emote.sh list                list the model's emotes + which is current
#   emote.sh <name>              apply one emote (e.g. emote.sh star_eyes)
#   emote.sh <name> <name> ...   apply SEVERAL at once (e.g. emote.sh angry hand_left)
#   emote.sh off                 clear back to neutral
# Applies live over CDP. Multiple emotes are merged into one expression.
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OLV="$HOME/Open-LLM-VTuber"
PY="$OLV/.venv/bin/python"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

model=$(grep -E 'live2d_model_name:' "$OLV/conf.yaml" | grep -oE "'[^']*'" | head -1 | tr -d "'")

read -r -d '' NAMES_JS <<'JS' || true
const md=getLive2DManager()._models.at(0);
let names=[];try{const e=md._expressions;if(e&&e._keyValues)names=e._keyValues.map(k=>k.first).filter(n=>n!=="__combo");}catch(e){}
JS

case "${1:-__next__}" in
  list)
    js="(()=>{${NAMES_JS} return {names, current:(window.__emoteIdx==null?null:names[window.__emoteIdx])};})()"
    out="$("$PY" "$HERE/cdp_eval.py" "$js" 2>/dev/null || true)" ;;
  off|neutral|reset)
    js="(()=>{${NAMES_JS} md.setExpression('neutral'); window.__emoteIdx=names.indexOf('neutral'); return {applied:'neutral'};})()"
    out="$("$PY" "$HERE/cdp_eval.py" "$js" 2>/dev/null || true)" ;;
  __next__)
    js="(()=>{${NAMES_JS} if(!names.length)return {error:'this model has no emotes'};
        let i=(window.__emoteIdx==null?-1:window.__emoteIdx)+1; if(i>=names.length)i=0;
        window.__emoteIdx=i; md.setExpression(names[i]);
        return {applied:names[i], idx:i+1, count:names.length};})()"
    out="$("$PY" "$HERE/cdp_eval.py" "$js" 2>/dev/null || true)" ;;
  *)  # one or more named emotes -> merged expression
    js="$("$PY" "$HERE/_emote_combine.py" "$model" "$@")"
    if [ "${js:0:4}" = "ERR:" ]; then echo "${js#ERR: }"; exit 1; fi
    out="$("$PY" "$HERE/cdp_eval.py" "$js" 2>/dev/null || true)" ;;
esac

printf '%s' "$out" | "$PY" "$HERE/_emote_fmt.py"
