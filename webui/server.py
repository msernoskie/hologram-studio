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
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
OLV = os.path.join(HOME, "Open-LLM-VTuber")
SCRIPTS = os.path.join(HOME, "OpenGhost", "scripts")
LIBRARY = os.path.join(HERE, "library.json")
GESTURE_MAP = os.path.join(SCRIPTS, "gesture_map.json")
HANDS_OFF_FLAG = os.path.join(SCRIPTS, ".hands_off")
IDLE_JSON = os.path.join(SCRIPTS, "idle.json")
# Idle part-motions — parts must match the PARTS map in IDLE_JS
# (openghost_kiosk_inject.py). idle = master toggle (figure-8 sway + motions).
MOTION_PARTS = ["torso", "head", "chest", "shoulders", "breath", "sway", "hips"]
DEFAULT_MOTIONS = [
    {"on": True, "part": "torso", "amp": 0.5, "len": 0.35, "bursts": [1, 3],
     "min_gap": 4.0, "max_gap": 9.0},
    {"on": False, "part": "head", "amp": 0.5, "len": 0.35, "bursts": [1, 3],
     "min_gap": 5.0, "max_gap": 11.0},
]


def clean_motion(m):
    """Validate/clamp one motion dict; raises on junk that isn't coercible."""
    part = str(m.get("part", ""))
    if part not in MOTION_PARTS:
        raise ValueError(f"unknown part {part!r}")
    bursts = m.get("bursts") or [1, 3]
    bursts = sorted({min(5, max(1, int(b))) for b in bursts[:4]})
    lo = min(60.0, max(1.0, float(m.get("min_gap", 4))))
    hi = min(60.0, max(1.0, float(m.get("max_gap", 9))))
    return {"on": bool(m.get("on", True)), "part": part,
            "amp": min(1.0, max(0.05, float(m.get("amp", 0.5)))),
            "len": min(1.5, max(0.15, float(m.get("len", 0.35)))),
            "bursts": bursts,
            "min_gap": min(lo, hi), "max_gap": max(lo, hi)}


def idle_state():
    conf = {"idle": True, "subtitles": True, "motions": DEFAULT_MOTIONS}
    try:
        with open(IDLE_JSON, encoding="utf-8") as fh:
            saved = json.load(fh)
        conf["idle"] = bool(saved.get("idle", True))
        conf["subtitles"] = bool(saved.get("subtitles", True))
        if isinstance(saved.get("motions"), list):
            conf["motions"] = [clean_motion(m) for m in saved["motions"][:8]]
    except Exception:
        pass
    return conf


# ---- chat (through the kiosk's own session) ---------------------------------
PROACTIVE_JSON = os.path.join(SCRIPTS, "proactive.json")
PROACTIVE_DEFAULTS = {
    "on": True, "away_secs": 300.0,
    "prompt": "(The user just walked back up to you after being away. Greet "
              "them warmly, in character, in one or two short sentences.)",
}


def conf_uid():
    """conf_uid from conf.yaml — the chat_history subdir the backend writes."""
    with open(os.path.join(OLV, "conf.yaml"), encoding="utf-8") as fh:
        for line in fh:
            if "conf_uid:" in line and "'" in line:
                return line.split("'")[1]
    return None


def history_dir():
    uid = conf_uid()
    return os.path.join(OLV, "chat_history", uid) if uid else None


def read_history(path):
    """[{role, content, timestamp}] from one backend history file."""
    try:
        with open(path, encoding="utf-8") as fh:
            entries = json.load(fh)
    except Exception:
        return []
    return [{"role": e.get("role"), "content": e.get("content", ""),
             "timestamp": e.get("timestamp", "")}
            for e in entries if e.get("role") in ("human", "ai")]


def history_files():
    """History file paths for the active character, newest first."""
    d = history_dir()
    if not d or not os.path.isdir(d):
        return []
    return sorted((os.path.join(d, f) for f in os.listdir(d)
                   if f.endswith(".json")), reverse=True)


def proactive_state():
    conf = dict(PROACTIVE_DEFAULTS)
    try:
        with open(PROACTIVE_JSON, encoding="utf-8") as fh:
            saved = json.load(fh)
        conf.update({k: saved[k] for k in PROACTIVE_DEFAULTS if k in saved})
    except Exception:
        pass
    return conf
GESTURE_ACTIONS = ["none", "zoom_in", "zoom_out", "nudge", "gaze",
                   "emote_next", "emote_off", "home"]
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


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


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


# ---- framing / placement ----------------------------------------------------
def cdp_js(js):
    """Evaluate JS in the kiosk via cdp_eval.py (OLV venv has websocket-client)."""
    ok, out = run_script(os.path.join(OLV, ".venv", "bin", "python"),
                         os.path.join(SCRIPTS, "cdp_eval.py"), js, timeout=10)
    return out if ok else None


def live_frame():
    raw = cdp_js("JSON.stringify(window.__ghostFrame||null)")
    try:
        return json.loads(json.loads(raw))    # cdp prints the JSON of a string
    except Exception:
        return None


def frame_state():
    model = conf_model()
    saved = _read_json(os.path.join(SCRIPTS, "framing.json")).get(model)
    home = _read_json(os.path.join(SCRIPTS, "gesture_home.json")).get(model)
    return {"model": model, "saved": saved, "home": home, "live": live_frame()}


def apply_frame(frame):
    """Set the live frame outright + persist to framing.json (clamped)."""
    sc = max(0.15, min(4.0, float(frame["scale"])))
    lim = max(1.2, sc)
    f = {"scale": round(sc, 3),
         "x": round(max(-lim, min(lim, float(frame["x"]))), 3),
         "y": round(max(-lim, min(lim, float(frame["y"]))), 3)}
    cdp_js("window.__ghostFrame=%s;window.__ghostFrameTarget=null;'ok'" % json.dumps(f))
    model = conf_model()
    path = os.path.join(SCRIPTS, "framing.json")
    data = _read_json(path)
    data[model] = f
    with _lock:
        with open(path + ".tmp", "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(path + ".tmp", path)
    return f


# ---- conf.yaml surgery ------------------------------------------------------
# Targeted line edits (same approach as switch_model.sh) — a YAML library
# round-trip would destroy the file's extensive comments.
CONF = os.path.join(OLV, "conf.yaml")


def read_conf():
    with open(CONF, encoding="utf-8") as fh:
        return fh.read()


def write_conf(text):
    with _lock:
        tmp = CONF + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, CONF)


def _q(v):
    """Sanitise a value for a single-quoted YAML scalar."""
    return str(v).replace("\n", " ").replace("'", "''")


def _set_quoted(text, pattern, value):
    """Replace the quoted value on the first line matching pattern.
    pattern must have groups (prefix)(old)(suffix-quote); comments survive."""
    import re
    return re.sub(pattern, lambda m: m.group(1) + _q(value) + m.group(3),
                  text, count=1, flags=re.M)


def provider_blocks(text):
    """{provider: {field: value}} for each 6-space stanza with LLM fields."""
    import re
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^      (\w+):\s*(#.*)?$", line)
        if m:
            cur = m.group(1)
            continue
        if cur and re.match(r"^\S|^  \S|^    \S", line):   # dedent past 6 spaces
            cur = None
        f = re.match(r"^        (base_url|model|llm_api_key): '([^']*)'", line)
        if cur and f:
            out.setdefault(cur, {})[f.group(1)] = f.group(2)
    return {k: v for k, v in out.items() if "model" in v or "base_url" in v}


def set_provider_field(text, provider, field, value):
    """Set one 8-space field inside a specific provider stanza."""
    import re
    lines = text.splitlines(keepends=True)
    inside = False
    for i, line in enumerate(lines):
        if re.match(rf"^      {re.escape(provider)}:\s*(#.*)?$", line):
            inside = True
            continue
        if inside and re.match(r"^\S|^  \S|^    \S|^      \S", line):
            break                                           # left the stanza
        if inside:
            m = re.match(rf"^(        {field}: ')([^']*)(')", line)
            if m:
                lines[i] = m.group(1) + _q(value) + m.group(3) + line[m.end():]
                return "".join(lines)
    return None                                             # field not found


def get_persona(text):
    import re
    m = re.search(r"^  persona_prompt: \|\n((?:[ \t]*\n|    .*\n)*)", text, re.M)
    if not m:
        return ""
    return "\n".join(l[4:] if l.startswith("    ") else ""
                     for l in m.group(1).splitlines()).strip()


def set_persona(text, prompt):
    import re
    block = "".join("    " + l.rstrip() + "\n" if l.strip() else "\n"
                    for l in prompt.strip().splitlines()) or "    \n"
    return re.sub(r"^(  persona_prompt: \|\n)(?:[ \t]*\n|    .*\n)*",
                  lambda m: m.group(1) + block + "\n", text, count=1, flags=re.M)


def ai_state():
    text = read_conf()
    import re
    cur = re.search(r"^\s+llm_provider: '([^']*)'", text, re.M)
    cname = re.search(r"^  character_name: '([^']*)'", text, re.M)
    hname = re.search(r"^  human_name: '([^']*)'", text, re.M)
    return {
        "llm_provider": cur.group(1) if cur else None,
        "providers": provider_blocks(text),
        "character_name": cname.group(1) if cname else "",
        "human_name": hname.group(1) if hname else "",
        "persona_prompt": get_persona(text),
        "cards": load_library().get("_cards", []),
    }


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

        if path == "/api/ai":
            self._json(ai_state())
            return

        if path == "/api/frame":
            self._json(frame_state())
            return

        if path == "/api/gestures":
            gmap = {"counts": {"0": "zoom_out", "1": "nudge", "2": "gaze",
                               "3": "emote_next", "4": "zoom_in"},
                    "hold": {"count": 0, "seconds": 3.0, "action": "home"}}
            try:
                with open(GESTURE_MAP, encoding="utf-8") as fh:
                    saved = json.load(fh)
                gmap["counts"].update({str(k): str(v)
                                       for k, v in (saved.get("counts") or {}).items()})
                gmap["hold"].update(saved.get("hold") or {})
            except Exception:
                pass
            seqs = load_library().get(conf_model(), {}).get("sequences", [])
            self._json({
                "map": gmap,
                "hands_on": not os.path.exists(HANDS_OFF_FLAG),
                "actions": GESTURE_ACTIONS,
                "sequence_actions": [f"sequence:{s['name']}" for s in seqs],
            })
            return

        if path == "/api/idle":
            self._json({**idle_state(), "parts": MOTION_PARTS})
            return

        if path == "/api/chat/current":
            files = history_files()
            self._json({"model": conf_model(),
                        "id": os.path.basename(files[0]) if files else None,
                        "messages": read_history(files[0]) if files else []})
            return

        if path == "/api/chat/histories":
            out = []
            for p in history_files()[:30]:
                msgs = read_history(p)
                out.append({"id": os.path.basename(p),
                            "count": len(msgs),
                            "preview": (msgs[0]["content"][:80] if msgs else "(empty)")})
            self._json({"histories": out})
            return

        if path == "/api/chat/history":
            hid = os.path.basename(  # basename() forecloses path traversal
                (parse_qs(urlparse(self.path).query).get("id") or [""])[0])
            d = history_dir()
            p = os.path.join(d, hid) if d and hid.endswith(".json") else None
            if not p or not os.path.isfile(p):
                self._json({"error": "no such history"}, 404)
                return
            self._json({"id": hid, "messages": read_history(p)})
            return

        if path == "/api/proactive":
            self._json(proactive_state())
            return

        self._json({"error": "not found"}, 404)

    # ---- POST ----
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/models/upload":
            # raw archive bytes; filename + optional name come as query params
            # (our own page sends fetch(file) — no multipart parsing needed)
            from urllib.parse import parse_qs
            q = parse_qs(parsed.query)
            fname = os.path.basename(q.get("filename", ["model.zip"])[0])
            want = q.get("name", [""])[0]
            n = int(self.headers.get("Content-Length", 0))
            if not (0 < n <= 300 * 1024 * 1024):
                self._json({"error": "empty or oversized upload (300MB max)"}, 400)
                return
            updir = os.path.join(HERE, "uploads")
            os.makedirs(updir, exist_ok=True)
            dest = os.path.join(updir, fname)
            with open(dest, "wb") as fh:
                remaining = n
                while remaining:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)
            ok, out = run_script("python3", os.path.join(SCRIPTS, "add_model.py"),
                                 dest, want, timeout=600)
            try:
                os.remove(dest)
            except OSError:
                pass
            try:                       # add_model prints a JSON summary
                self._json(json.loads(out[out.index("{"):]))
            except Exception:
                self._json({"error": out[-400:] or "add_model failed"}, 500)
            return

        try:
            body = self._body()
        except Exception:
            self._json({"error": "bad json"}, 400)
            return

        if path == "/api/models/scan":
            # register any unregistered .exp3.json expressions for a model
            target = body.get("model") or conf_model()
            ok, out = run_script("python3",
                                 os.path.join(SCRIPTS, "scan_expressions.py"),
                                 target, timeout=60)
            try:
                self._json(json.loads(out[out.index("{"):]))
            except Exception:
                self._json({"error": out[-400:] or "scan failed"}, 500)
            return

        if path == "/api/switch":
            name = body.get("model", "")
            # register any unregistered expression files FIRST, so the kiosk
            # reload that switch_model.sh performs picks them up (VTS models
            # routinely ship .exp3.json files without registering them)
            scanned = []
            ok_s, out_s = run_script("python3",
                                     os.path.join(SCRIPTS, "scan_expressions.py"),
                                     name, timeout=60)
            try:
                scanned = json.loads(out_s[out_s.index("{"):]).get("added", [])
            except Exception:
                pass
            ok, out = run_script(os.path.join(SCRIPTS, "switch_model.sh"), name,
                                 timeout=180)
            self._json({"ok": ok, "output": out[-800:],
                        "expressions_registered": scanned})
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

        if path == "/api/frame":
            # {"ds":…, "dx":…, "dy":…} — one nudge via _frame.sh (live + persisted),
            # exactly what the up/down/left/right/zoom_in/zoom_out scripts do
            try:
                ds = max(-1.0, min(1.0, float(body.get("ds", 0))))
                dx = max(-1.0, min(1.0, float(body.get("dx", 0))))
                dy = max(-1.0, min(1.0, float(body.get("dy", 0))))
            except (TypeError, ValueError):
                self._json({"error": "ds/dx/dy must be numbers"}, 400)
                return
            ok, out = run_script(os.path.join(SCRIPTS, "_frame.sh"),
                                 str(ds), str(dx), str(dy), timeout=20)
            self._json({"ok": ok, "output": out[-200:], "state": frame_state()})
            return

        if path == "/api/frame/reset":
            ok, out = run_script(os.path.join(SCRIPTS, "reset.sh"), timeout=20)
            self._json({"ok": ok, "output": out[-200:], "state": frame_state()})
            return

        if path == "/api/frame/home":
            home = frame_state()["home"]
            if not home:
                self._json({"error": "no home framing saved for this model"}, 404)
                return
            f = apply_frame(home)
            self._json({"ok": True, "applied": f, "state": frame_state()})
            return

        if path == "/api/frame/sethome":
            f = live_frame()
            if not f:
                self._json({"error": "kiosk not reachable — is the hologram running?"},
                           502)
                return
            model = conf_model()
            path_h = os.path.join(SCRIPTS, "gesture_home.json")
            data = _read_json(path_h)
            data[model] = {"scale": round(float(f["scale"]), 3),
                           "x": round(float(f["x"]), 3),
                           "y": round(float(f["y"]), 3)}
            with _lock:
                with open(path_h + ".tmp", "w") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(path_h + ".tmp", path_h)
            self._json({"ok": True, "home": data[model], "state": frame_state()})
            return

        if path == "/api/gestures":
            # {"map": {"counts": {...}, "hold": {...}}} — validated, then written
            # to scripts/gesture_map.json; the sidecar hot-reloads it (no restart)
            m = body.get("map", {})
            counts = {str(k): str(v) for k, v in (m.get("counts") or {}).items()
                      if str(k) in "01234"}
            valid = set(GESTURE_ACTIONS)
            bad = [v for v in counts.values()
                   if v not in valid and not v.startswith("sequence:")]
            hold = m.get("hold") or {}
            ha = str(hold.get("action", "home"))
            if ha not in valid and not ha.startswith("sequence:"):
                bad.append(ha)
            if bad:
                self._json({"error": f"unknown action(s): {bad}"}, 400)
                return
            out = {"counts": counts,
                   "hold": {"count": int(hold.get("count", 0)),
                            "seconds": max(1.0, float(hold.get("seconds", 3.0))),
                            "action": ha}}
            with _lock:
                tmp = GESTURE_MAP + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(out, fh, indent=2)
                os.replace(tmp, GESTURE_MAP)
            self._json({"ok": True, "map": out,
                        "note": "applies live — the sidecar reloads on change"})
            return

        if path == "/api/hands":
            if body.get("on"):
                try:
                    os.remove(HANDS_OFF_FLAG)
                except OSError:
                    pass
            else:
                open(HANDS_OFF_FLAG, "w").close()
            self._json({"ok": True, "hands_on": not os.path.exists(HANDS_OFF_FLAG)})
            return

        if path == "/api/idle":
            # {"idle": bool} and/or {"motions": [...]} — validated, written to
            # scripts/idle.json, and pushed straight into the live page.
            conf = idle_state()
            try:
                if "idle" in body:
                    conf["idle"] = bool(body["idle"])
                if "subtitles" in body:
                    conf["subtitles"] = bool(body["subtitles"])
                if "motions" in body:
                    if not isinstance(body["motions"], list):
                        raise ValueError("motions must be a list")
                    conf["motions"] = [clean_motion(m) for m in body["motions"][:8]]
            except (TypeError, ValueError, KeyError) as e:
                self._json({"error": f"bad motion: {e}"}, 400)
                return
            with _lock:
                tmp = IDLE_JSON + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(conf, fh, indent=2)
                os.replace(tmp, IDLE_JSON)
            cdp_js("window.__ghostIdleCfg=%s;'ok'" % json.dumps(conf))
            self._json({"ok": True, **conf})
            return

        if path == "/api/chat/send":
            # Types into the kiosk's hidden chat box (window.__ghostSay), so
            # the message runs the full pipeline in the KIOSK's own session:
            # LLM -> expressions on the hologram -> subtitle -> history.
            text = str(body.get("text", "")).strip()
            if not text:
                self._json({"error": "empty message"}, 400)
                return
            raw = cdp_js("window.__ghostSay ? window.__ghostSay(%s) : 'no-hook'"
                         % json.dumps(text[:2000]))
            if raw is None or "no-hook" in str(raw):
                self._json({"error": "kiosk not reachable (is the hologram "
                                     "running with the idle loop injected?)"}, 502)
                return
            self._json({"ok": True})
            return

        if path == "/api/proactive":
            conf = proactive_state()
            try:
                if "on" in body:
                    conf["on"] = bool(body["on"])
                if "away_secs" in body:
                    conf["away_secs"] = min(86400.0, max(10.0, float(body["away_secs"])))
                if "prompt" in body and str(body["prompt"]).strip():
                    conf["prompt"] = str(body["prompt"]).strip()[:1000]
            except (TypeError, ValueError) as e:
                self._json({"error": f"bad value: {e}"}, 400)
                return
            with _lock:
                tmp = PROACTIVE_JSON + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(conf, fh, indent=2)
                os.replace(tmp, PROACTIVE_JSON)
            self._json({"ok": True, **conf,
                        "note": "applies live — the sidecar reloads on change"})
            return

        if path == "/api/ai/backend":
            # {"provider": ..., "base_url"?, "model"?, "llm_api_key"?}
            prov = body.get("provider", "")
            text = read_conf()
            if prov not in provider_blocks(text):
                self._json({"error": f"unknown provider {prov!r}"}, 400)
                return
            text = _set_quoted(text, r"^(\s+llm_provider: ')([^']*)(')", prov)
            skipped = []
            for field in ("base_url", "model", "llm_api_key"):
                if field in body and body[field] != "":
                    t2 = set_provider_field(text, prov, field, body[field])
                    if t2 is None:
                        skipped.append(field)   # stanza doesn't have this field
                    else:
                        text = t2
            write_conf(text)
            self._json({"ok": True, "skipped": skipped,
                        "note": "restart the backend to apply"})
            return

        if path == "/api/ai/character":
            # {"character_name"?, "human_name"?, "persona_prompt"?}
            text = read_conf()
            if body.get("character_name"):
                text = _set_quoted(text, r"^(  character_name: ')([^']*)(')",
                                   body["character_name"])
            if body.get("human_name"):
                text = _set_quoted(text, r"^(  human_name: ')([^']*)(')",
                                   body["human_name"])
            if "persona_prompt" in body and body["persona_prompt"].strip():
                text = set_persona(text, body["persona_prompt"])
            write_conf(text)
            self._json({"ok": True, "note": "restart the backend to apply"})
            return

        if path == "/api/ai/restart":
            # switch_model.sh to the CURRENT model = clean backend restart
            # + kiosk reload + ghost look re-applied
            ok, out = run_script(os.path.join(SCRIPTS, "switch_model.sh"),
                                 conf_model() or "", timeout=180)
            self._json({"ok": ok, "output": out[-800:]})
            return

        if path == "/api/cards/save":
            card = body.get("card", {})
            if not card.get("name"):
                self._json({"error": "card needs a name"}, 400)
                return
            lib = load_library()
            cards = lib.setdefault("_cards", [])
            cards[:] = [c for c in cards if c["name"] != card["name"]] + [card]
            save_library(lib)
            self._json({"ok": True})
            return

        if path == "/api/cards/delete":
            lib = load_library()
            cards = lib.setdefault("_cards", [])
            cards[:] = [c for c in cards if c["name"] != body.get("name")]
            save_library(lib)
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
