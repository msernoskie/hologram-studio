#!/usr/bin/env python3
# ============================================================================
# OpenGhost — register a model's expression files.
#
#   scan_expressions.py [model_name]     (default: the active model)
#
# VTube-Studio models usually ship .exp3.json expression files WITHOUT
# registering them in the .model3.json — so they exist on disk but the
# runtime (and the emote selector) can't see them. jane_doe and fern both
# arrived like this. This scans the model's folder, registers any missing
# expressions in FileReferences.Expressions, and adds an empty `neutral`
# expression (all params reset) if the model doesn't have one.
#
# Prints a JSON summary. Reload the kiosk (or switch_model.sh) to apply.
# ============================================================================
import json
import os
import sys

HOME = os.path.expanduser("~")
OLV = os.path.join(HOME, "Open-LLM-VTuber")

NEUTRAL = {"Type": "Live2D Expression", "Parameters": []}


def conf_model():
    with open(os.path.join(OLV, "conf.yaml"), encoding="utf-8") as fh:
        for line in fh:
            if "live2d_model_name:" in line and "'" in line:
                return line.split("'")[1]
    return None


def scan(model_name):
    md = json.load(open(os.path.join(OLV, "model_dict.json"), encoding="utf-8"))
    entry = next((m for m in md if m["name"] == model_name), None)
    if not entry:
        return {"error": f"model {model_name!r} not in model_dict.json"}
    m3_path = os.path.join(OLV, entry["url"].lstrip("/"))
    if not os.path.exists(m3_path):
        return {"error": f"missing {m3_path}"}
    root = os.path.dirname(m3_path)

    m3 = json.load(open(m3_path, encoding="utf-8"))
    fr = m3.setdefault("FileReferences", {})
    existing = fr.get("Expressions") or []
    known_files = {os.path.normpath(e.get("File", "")) for e in existing}
    known_names = {e.get("Name") for e in existing}

    added = []
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            if not f.endswith(".exp3.json"):
                continue
            rel = os.path.normpath(os.path.relpath(os.path.join(dirpath, f), root))
            if rel in known_files:
                continue
            name = f[:-len(".exp3.json")]
            # avoid name collisions from duplicate files in subfolders
            base, n = name, 2
            while name in known_names:
                name = f"{base}_{n}"
                n += 1
            existing.append({"Name": name, "File": rel.replace(os.sep, "/")})
            known_names.add(name)
            known_files.add(rel)
            added.append(name)

    # a resets-everything neutral, so emotes can always be cleared
    made_neutral = False
    if existing and "neutral" not in known_names:
        np = os.path.join(root, "neutral.exp3.json")
        if not os.path.exists(np):
            json.dump(NEUTRAL, open(np, "w"), indent=2)
        existing.append({"Name": "neutral", "File": "neutral.exp3.json"})
        added.append("neutral")
        made_neutral = True

    if added:
        fr["Expressions"] = existing
        tmp = m3_path + ".tmp"
        json.dump(m3, open(tmp, "w"), ensure_ascii=False, indent=2)
        os.replace(tmp, m3_path)

    return {"model": model_name, "added": added, "made_neutral": made_neutral,
            "total": len(existing),
            "note": "reload the model (switch/restart) to apply" if added else "up to date"}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else conf_model()
    print(json.dumps(scan(target), indent=2))
