#!/usr/bin/env python3
"""Build the CDP JS that applies one OR MORE emotes at once on the active model.

Emotes are Live2D expressions (additive param toggles). This build shows only one
expression at a time, so to combine several we merge their Parameters into a single
runtime expression via CubismExpressionMotion.create() and apply that.

Usage: _emote_combine.py <model_name> <emote> [<emote> ...]
Prints a JS expression for cdp_eval.py, or a line starting with "ERR: ".
"""
import json, os, sys

OLV = os.path.expanduser("~/Open-LLM-VTuber")


def die(msg):
    print("ERR: " + msg)
    sys.exit(0)


model = sys.argv[1] if len(sys.argv) > 1 else ""
names = sys.argv[2:]
if not names:
    die("no emotes given")

try:
    mdict = json.load(open(os.path.join(OLV, "model_dict.json"), encoding="utf-8"))
except Exception as e:
    die("cannot read model_dict.json: %s" % e)

entry = next((m for m in mdict if m["name"] == model), None)
if not entry:
    die("model not found: " + model)

m3_path = os.path.join(OLV, entry["url"].lstrip("/"))
model_dir = os.path.dirname(m3_path)
try:
    m3 = json.load(open(m3_path, encoding="utf-8"))
except Exception as e:
    die("cannot read %s: %s" % (m3_path, e))

exprs = m3.get("FileReferences", {}).get("Expressions", [])
name2file = {e["Name"]: e["File"] for e in exprs}
if not name2file:
    die("model '%s' has no registered emotes" % model)

unknown = [n for n in names if n not in name2file]
if unknown:
    die("unknown emote(s): %s | available: %s"
        % (", ".join(unknown), ", ".join(name2file)))

merged = []  # last write wins per param Id
for n in names:
    f = os.path.join(model_dir, name2file[n])
    try:
        params = json.load(open(f, encoding="utf-8")).get("Parameters", [])
    except Exception as e:
        die("cannot read expression file for '%s': %s" % (n, e))
    for p in params:
        pid = p.get("Id")
        merged = [x for x in merged if x.get("Id") != pid]
        merged.append(p)

js = (
    '(()=>{const md=getLive2DManager()._models.at(0);'
    'const Ur=md._expressions._keyValues[0].second.constructor;'
    'const merged={Type:"Live2D Expression",Parameters:%s};'
    'const buf=new TextEncoder().encode(JSON.stringify(merged)).buffer;'
    'let e;try{e=Ur.create(buf,buf.byteLength);}catch(err){return {error:String(err)};}'
    'if(!e)return {error:"create returned null"};'
    'md._expressions.setValue("__combo",e);md.setExpression("__combo");window.__emoteIdx=null;'
    'return {applied:%s};})()'
) % (json.dumps(merged), json.dumps(names))
print(js)
