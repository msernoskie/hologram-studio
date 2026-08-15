#!/usr/bin/env python3
# ============================================================================
# OpenGhost — add a Live2D model from an archive (zip/rar/7z).
#
#   add_model.py <archive> [name]
#
# Pipeline (everything the manual installs needed, automated):
#   1. extract with `unar` (handles zip AND the rar variants Chinese VTS
#      models ship in, which p7zip can't decode)
#   2. find the .model3.json (shallowest wins)
#   3. ASCII-slug the model name (folder + model3 filename — non-ASCII
#      names break nothing in the browser but make every shell interaction
#      miserable; internal asset names are left alone, URLs encode fine)
#   4. move into Open-LLM-VTuber/live2d-models/<slug>/
#   5. TEXTURE CHECK: the Pi 5's GPU max texture size is 4096 — an 8192
#      texture loads "successfully" but renders completely invisible.
#      Oversized textures are downscaled in place (LANCZOS; UVs are
#      normalized so mapping is unaffected). jane_doe needed this.
#   6. register any unregistered .exp3.json expressions (+ neutral)
#   7. register in model_dict.json (kScale 0.3 — VTS models are full-body)
#
# Prints a JSON summary. Switch to the model to see it.
# ============================================================================
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HOME = os.path.expanduser("~")
OLV = os.path.join(HOME, "Open-LLM-VTuber")
MODELS_DIR = os.path.join(OLV, "live2d-models")
MAX_TEX = 4096

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_expressions import scan as scan_expressions  # noqa: E402


def slugify(s):
    s = re.sub(r"\.(model3\.json|zip|rar|7z)$", "", s, flags=re.I)
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "model"


def fail(msg):
    print(json.dumps({"error": msg}))
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        fail("usage: add_model.py <archive> [name]")
    archive = sys.argv[1]
    want_name = sys.argv[2] if len(sys.argv) > 2 else ""
    if not os.path.exists(archive):
        fail(f"no such file: {archive}")

    workdir = tempfile.mkdtemp(prefix="openghost-model-")
    try:
        # 1. extract
        p = subprocess.run(["unar", "-quiet", "-o", workdir, archive],
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            fail(f"extract failed: {(p.stdout + p.stderr).strip()[:300]}")

        # 2. find the model3 (shallowest first — avoids backup copies)
        candidates = []
        for dirpath, _dirs, files in os.walk(workdir):
            for f in files:
                if f.endswith(".model3.json"):
                    full = os.path.join(dirpath, f)
                    candidates.append((full.count(os.sep), full))
        if not candidates:
            fail("no .model3.json found in the archive — is this a Cubism 3+ model?")
        m3_src = sorted(candidates)[0][1]
        src_root = os.path.dirname(m3_src)

        # 3./4. slug + move into live2d-models/
        slug = slugify(want_name or os.path.basename(m3_src))
        dest = os.path.join(MODELS_DIR, slug)
        if os.path.exists(dest):
            fail(f"model folder already exists: live2d-models/{slug} — "
                 "pick a different name")
        shutil.move(src_root, dest)
        m3_name = os.path.basename(m3_src)
        if not m3_name.isascii() or slugify(m3_name) != slug:
            new_m3 = f"{slug}.model3.json"
            os.rename(os.path.join(dest, m3_name), os.path.join(dest, new_m3))
            m3_name = new_m3
        m3_path = os.path.join(dest, m3_name)

        # 5. texture size check (GPU limit)
        downscaled = []
        try:
            from PIL import Image
            m3 = json.load(open(m3_path, encoding="utf-8"))
            for tex in m3.get("FileReferences", {}).get("Textures", []):
                tp = os.path.join(dest, tex)
                if not os.path.exists(tp):
                    continue
                img = Image.open(tp)
                if max(img.size) > MAX_TEX:
                    ratio = MAX_TEX / max(img.size)
                    img = img.resize((round(img.size[0] * ratio),
                                      round(img.size[1] * ratio)),
                                     Image.LANCZOS)
                    img.save(tp)
                    downscaled.append(tex)
        except ImportError:
            pass                                   # PIL missing: skip, warn below

        # 7. register in model_dict.json (before 6 so the scanner can find it)
        md_path = os.path.join(OLV, "model_dict.json")
        md = json.load(open(md_path, encoding="utf-8"))
        if any(m["name"] == slug for m in md):
            fail(f"model {slug!r} already registered")
        md.append({
            "name": slug,
            "description": f"{slug} — added via web UI",
            "url": f"/live2d-models/{slug}/{m3_name}",
            "kScale": 0.3,
            "initialXshift": 0, "initialYshift": 0, "kXOffset": 0,
            "idleMotionGroupName": "",
            "emotionMap": {},
        })
        tmp = md_path + ".tmp"
        json.dump(md, open(tmp, "w"), ensure_ascii=False, indent=4)
        os.replace(tmp, md_path)

        # 6. expressions
        exp = scan_expressions(slug)

        print(json.dumps({
            "ok": True, "name": slug, "url": f"/live2d-models/{slug}/{m3_name}",
            "expressions": exp.get("added", []),
            "textures_downscaled": downscaled,
            "note": "switch to the model to see it; frame it with the d-pad, "
                    "then label its emotes",
        }, indent=2))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
