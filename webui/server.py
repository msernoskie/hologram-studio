#!/usr/bin/env python3
# ============================================================================
# OpenGhost — hologram studio web UI (stdlib only, no pip deps).
#
#   http://<pi>:8800  —  swap models, fire emotes, build labeled emote
#   sequences, and export/apply the labels so an AI knows what to use.
#
# Storage: library.json (next to this file), committed to git:
#   { "<model>": { "emote_labels": {"<emote>": ["joy", ...]},
#                  "sequences": [ {"name","labels":[...],"steps":
#                        [{"emotes":["a","b"],"hold_ms":800}, ...]} ] } }
#
# AI integration:
#   GET  /api/export           machine-readable labels + sequences (all models)
#   POST /api/sequence/play    {"name": ...} — anything (incl. an LLM tool)
#                              can trigger a labeled sequence over HTTP
#   POST /api/apply-emotionmap writes single-emote labels into model_dict.json
#                              emotionMap — Open-LLM-VTuber's native mechanism
#                              (its live2d_expression_prompt injects the label
#                              list into the LLM system prompt; backend restart
#                              needed to pick it up: switch_model.sh <model>)
# ============================================================================
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
OLV = os.path.join(HOME, "Open-LLM-VTuber")
SCRIPTS = os.path.join(HOME, "OpenGhost", "scripts")
LIBRARY = os.path.join(HERE, "library.json")
PORT = 8800

_lock = threading.Lock()          # library file writes
_player = {"thread": None, "stop": False, "now": None}   # sequence playback


# ---- model / emote discovery (all file-based; no kiosk needed) --------------
def conf_model():
    with open(os.path.join(OLV, "conf.yaml"), encoding="utf-8") as fh:
        for line in fh:
            if "live2d_model_name:" in line and "'" in line:
                return line.split("'")[1]
    return None


def model_dict():
    with open(os.path.join(OLV, "model_dict.json"), encoding="utf-8") as fh:
        return json.load(fh)


def model_emotes(entry):
    """Expression names registered in this model's .model3.json."""
    path = os.path.join(OLV, entry["url"].lstrip("/"))
    try:
        with open(path, encoding="utf-8") as fh:
            m3 = json.load(fh)
        return [e["Name"] for e in m3.get("FileReferences", {}).get("Expressions", [])]
    except Exception:
        return []


def load_library():
    try:
        with open(LIBRARY, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_library(lib):
    with _lock:
        tmp = LIBRARY + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(lib, fh, indent=2)
        os.replace(tmp, LIBRARY)


def run_script(*argv, timeout=120):
    """Run a scripts/ helper; returns (ok, output)."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except Exception as e:
        return False, str(e)


def fire_emote(names):
    """names = list of emote names, or ['off'] to clear."""
    return run_script(os.path.join(SCRIPTS, "emote.sh"), *names, timeout=20)


# ---- sequence playback ------------------------------------------------------
def play_sequence(model, seq):
    """Run steps in a background thread; only one sequence plays at a time."""
    stop_player()
    _player["stop"] = False
    _player["now"] = seq["name"]

    def run():
        for step in seq.get("steps", []):
            if _player["stop"]:
                break
            emotes = step.get("emotes") or ["neutral"]
            fire_emote(emotes)
            time.sleep(max(0.1, step.get("hold_ms", 800) / 1000.0))
        if not _player["stop"]:
            fire_emote(["neutral"])           # always land somewhere sane
        _player["now"] = None

    t = threading.Thread(target=run, daemon=True)
    _player["thread"] = t
    t.start()


def stop_player():
    if _player["thread"] and _player["thread"].is_alive():
        _player["stop"] = True
        _player["thread"].join(timeout=5)
    _player["now"] = None


# ---- HTTP -------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):          # quiet access log
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    # ---- GET ----
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/state":
            md = model_dict()
            active = conf_model()
            lib = load_library().get(active, {})
            entry = next((m for m in md if m["name"] == active), None)
            self._json({
                "models": [{"name": m["name"], "description": m.get("description", "")}
                           for m in md],
                "active": active,
                "emotes": model_emotes(entry) if entry else [],
                "emote_labels": lib.get("emote_labels", {}),
                "sequences": lib.get("sequences", []),
                "emotion_map": (entry or {}).get("emotionMap", {}),
                "playing": _player["now"],
            })
            return

        if path == "/api/export":
            # Everything an AI needs: per model, the labeled emotes it can set
            # (single expressions) and the labeled sequences it can trigger by
            # POSTing {"name": ...} to /api/sequence/play on this server.
            md = model_dict()
            lib = load_library()
            out = {"active_model": conf_model(),
                   "play_endpoint": "POST /api/sequence/play {\"name\": ...}",
                   "emote_endpoint": "POST /api/emote {\"names\": [...]}",
                   "models": {}}
            for m in md:
                L = lib.get(m["name"], {})
                out["models"][m["name"]] = {
                    "emotes": model_emotes(m),
                    "emote_labels": L.get("emote_labels", {}),
                    "sequences": [{"name": s["name"], "labels": s.get("labels", []),
                                   "steps": s["steps"]}
                                  for s in L.get("sequences", [])],
                    "emotion_map": m.get("emotionMap", {}),
                }
            self._json(out)
            return

        self._json({"error": "not found"}, 404)

    # ---- POST ----
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
        except Exception:
            self._json({"error": "bad json"}, 400)
            return

        if path == "/api/switch":
            name = body.get("model", "")
            ok, out = run_script(os.path.join(SCRIPTS, "switch_model.sh"), name,
                                 timeout=180)
            self._json({"ok": ok, "output": out[-800:]})
            return

        if path == "/api/emote":
            names = body.get("names") or ["off"]
            ok, out = fire_emote(names)
            self._json({"ok": ok, "output": out[-400:]})
            return

        if path == "/api/labels":
            model = conf_model()
            lib = load_library()
            lib.setdefault(model, {})["emote_labels"] = body.get("emote_labels", {})
            save_library(lib)
            self._json({"ok": True})
            return

        if path == "/api/sequence/save":
            seq = body.get("sequence", {})
            if not seq.get("name") or not seq.get("steps"):
                self._json({"error": "sequence needs a name and steps"}, 400)
                return
            model = conf_model()
            lib = load_library()
            seqs = lib.setdefault(model, {}).setdefault("sequences", [])
            seqs[:] = [s for s in seqs if s["name"] != seq["name"]] + [seq]
            save_library(lib)
            self._json({"ok": True})
            return

        if path == "/api/sequence/delete":
            model = conf_model()
            lib = load_library()
            seqs = lib.setdefault(model, {}).setdefault("sequences", [])
            seqs[:] = [s for s in seqs if s["name"] != body.get("name")]
            save_library(lib)
            self._json({"ok": True})
            return

        if path == "/api/sequence/play":
            model = conf_model()
            seqs = load_library().get(model, {}).get("sequences", [])
            seq = next((s for s in seqs if s["name"] == body.get("name")), None)
            if not seq:
                self._json({"error": f"no sequence named {body.get('name')!r} "
                                     f"for model {model}"}, 404)
                return
            play_sequence(model, seq)
            self._json({"ok": True, "playing": seq["name"]})
            return

        if path == "/api/sequence/stop":
            stop_player()
            fire_emote(["off"])
            self._json({"ok": True})
            return

        if path == "/api/apply-emotionmap":
            # Push the SINGLE-emote labels into model_dict.json emotionMap —
            # the mechanism Open-LLM-VTuber's LLM pipeline natively consumes.
            model = conf_model()
            labels = load_library().get(model, {}).get("emote_labels", {})
            emap = {}
            for emote, labs in labels.items():
                for lab in labs:
                    emap[lab.strip().lower()] = emote
            emap.setdefault("neutral", "neutral")
            md = model_dict()
            for m in md:
                if m["name"] == model:
                    m["emotionMap"] = emap
            tmp = os.path.join(OLV, "model_dict.json.tmp")
            with open(tmp, "w") as fh:
                json.dump(md, fh, indent=4, ensure_ascii=False)
            os.replace(tmp, os.path.join(OLV, "model_dict.json"))
            self._json({"ok": True, "emotionMap": emap,
                        "note": "restart the backend to pick this up: "
                                f"scripts/switch_model.sh {model}"})
            return

        self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[webui] hologram studio on http://0.0.0.0:{PORT}")
    srv.serve_forever()
