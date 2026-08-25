#!/usr/bin/env python3
"""stage3d — tiny server for the head-coupled 3D spinoff (port 8801).

Serves the Three.js page from this directory, plus:
  GET  /api/face    latest tracked face from the gesture sidecar
                    (published to tmpfs at /dev/shm/openghost_face.json)
  GET  /api/models  files dropped into stage3d/models/ (*.vrm *.glb *.gltf)
  GET  /api/calib   calibration knobs (calib.json, defaults merged)
  POST /api/calib   save calibration knobs (atomic write)
"""
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8801
FACE_BRIDGE = "/dev/shm/openghost_face.json"
CALIB = os.path.join(HERE, "calib.json")
MODELS = os.path.join(HERE, "models")
_lock = threading.Lock()

CALIB_DEFAULTS = {
    "screen_mm": 72.0,        # HyperPixel 4.0 Square active area (~72mm)
    "cam_hfov_deg": 66.0,     # Camera Module 3 field of view
    "cam_vfov_deg": 41.0,
    "cam_offset_mm": {"x": 0, "y": 40},   # camera position relative to screen centre
    "ref_face_w": 0.18,       # normalised face width at the nominal standing spot
    "ref_dist_mm": 500,       # actual distance at that spot (mm)
    "invert_x": False,        # flip the parallax sense (mirrored display makes
    "invert_y": False,        #   first-principles signs a coin flip — calibrate)
    "ease": 0.12,             # per-frame easing toward the tracked eye
    "depth_mm": 40,           # how far behind the screen plane the model stands
    "model_fit": 0.85,        # model height as a fraction of the screen height
}


def read_calib():
    conf = dict(CALIB_DEFAULTS)
    try:
        with open(CALIB) as f:
            saved = json.load(f)
        conf.update({k: saved[k] for k in CALIB_DEFAULTS if k in saved})
    except Exception:
        pass
    return conf


def clean_calib(body):
    """Whitelist + clamp — same defensive shape as webui/server.py."""
    out = read_calib()
    num = {"screen_mm": (20, 500), "cam_hfov_deg": (20, 160),
           "cam_vfov_deg": (20, 160), "ref_face_w": (0.02, 0.9),
           "ref_dist_mm": (100, 3000), "ease": (0.02, 1.0),
           "depth_mm": (-100, 300), "model_fit": (0.1, 2.0)}
    for k, (lo, hi) in num.items():
        if k in body:
            out[k] = max(lo, min(hi, float(body[k])))
    for k in ("invert_x", "invert_y"):
        if k in body:
            out[k] = bool(body[k])
    if isinstance(body.get("cam_offset_mm"), dict):
        off = body["cam_offset_mm"]
        out["cam_offset_mm"] = {
            "x": max(-300, min(300, float(off.get("x", 0)))),
            "y": max(-300, min(300, float(off.get("y", 0))))}
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/face"):
            try:
                with open(FACE_BRIDGE) as f:
                    self._json(json.load(f))
            except Exception:
                self._json({"present": False, "t": 0})
        elif self.path.startswith("/api/models"):
            try:
                names = sorted(n for n in os.listdir(MODELS)
                               if n.lower().endswith((".vrm", ".glb", ".gltf")))
            except FileNotFoundError:
                names = []
            self._json(names)
        elif self.path.startswith("/api/calib"):
            self._json(read_calib())
        else:
            super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/calib"):
            self._json({"error": "unknown endpoint"}, 404)
            return
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0))))
            conf = clean_calib(body)
        except Exception as e:
            self._json({"error": str(e)}, 400)
            return
        with _lock:
            tmp = CALIB + ".tmp"
            with open(tmp, "w") as f:
                json.dump(conf, f, indent=2)
            os.replace(tmp, CALIB)
        self._json(conf)


if __name__ == "__main__":
    os.makedirs(MODELS, exist_ok=True)
    print(f"[stage3d] serving {HERE} on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
