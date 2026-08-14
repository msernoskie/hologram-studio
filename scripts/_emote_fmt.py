#!/usr/bin/env python3
"""Format emote.sh's CDP result into a friendly line. Reads JSON on stdin."""
import json, sys

raw = sys.stdin.read().strip()
if not raw or raw == "null":
    print("kiosk not running (start it with live2d_ghost.sh)")
    sys.exit(1)
try:
    d = json.loads(raw)
except Exception:
    print(raw)
    sys.exit(0)
if not isinstance(d, dict):
    print(d)
    sys.exit(0)

if d.get("error") == "unknown emote":
    print("unknown emote: " + str(d.get("want")))
    print("available: " + ", ".join(d.get("names", [])))
    sys.exit(1)
if d.get("error"):
    print(d["error"])
    sys.exit(1)
if "names" in d:
    cur = d.get("current")
    print("available emotes:")
    for n in d["names"]:
        print(("  * " if n == cur else "    ") + n)
else:
    applied = d.get("applied")
    if isinstance(applied, list):
        applied = " + ".join(applied)
    tag = "  (%s/%s)" % (d["idx"], d["count"]) if "idx" in d else ""
    print("emote -> %s%s" % (applied, tag))
