#!/usr/bin/env python3
# ============================================================================
# OpenGhost — gesture control sidecar.
#
#   Camera Module 3 --(rpicam-vid)--> MediaPipe Gesture Recognizer --(CDP)-->
#   the live hologram: nudge it, zoom it, make it look at you, fire emotes.
#
# Everything is a DISCRETE STEP that repeats while you hold the gesture — the
# same size step as the up.sh/zoom_in.sh scripts. Nothing tracks your hand
# continuously, so nothing can run away off-screen.
#
# Gestures are just HOW MANY fingers you hold up (thumb never counts).
# What each count DOES is REMAPPABLE in scripts/gesture_map.json (edited from
# the web UI's "Hand gestures" panel; hot-reloaded, no restart). Defaults:
#   0 (fist)           zoom OUT      3 fingers   next emote
#   1 finger           nudge         4 (palm)    zoom IN
#   2 fingers          gaze at hand  hold fist 3s = restore "home" framing
# Actions: none | zoom_in | zoom_out | nudge | gaze | emote_next | emote_off
#          | home | sequence:<web-UI sequence name>
#
# Home framing is snapshotted on first run and re-settable with
# `gesture_ctl.sh sethome` — it is NOT the model_dict default, which for a
# full-body model is a small centred figure nothing like a working crop.
#
# Run:  ~/OpenGhost/scripts/gesture_ctl.sh start   (or ... debug)
#
# NOTE: this owns the camera exclusively — nothing else can capture while it
# runs. It does NOT use picamera2 (system picamera2 is built against numpy 1.x
# and mediapipe needs numpy 2.x); frames come from rpicam-vid over a pipe.
# ============================================================================
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

os.environ.setdefault("GLOG_minloglevel", "2")        # must precede the mediapipe
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")    # import — it logs on load

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision
from websocket import create_connection

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
OLV = os.path.join(HOME, "Open-LLM-VTuber")
TASK_MODEL = os.path.join(HOME, "OpenGhost", "models", "gesture_recognizer.task")
FACE_MODEL = os.path.join(HOME, "OpenGhost", "models", "blaze_face_short_range.tflite")
FRAMING = os.path.join(HERE, "framing.json")
HOME_FILE = os.path.join(HERE, "gesture_home.json")
EMOTE_SH = os.path.join(HERE, "emote.sh")
HANDS_OFF_FLAG = os.path.join(HERE, ".hands_off")   # exists = hand gestures disabled
                                                    # (toggled by gesture_ctl.sh hands on|off;
                                                    # face tracking is unaffected)
PROACTIVE_FILE = os.path.join(HERE, "proactive.json")
DBG = "http://localhost:9222"

# ---- tuning knobs -----------------------------------------------------------
CAM_W, CAM_H, CAM_FPS = 640, 480, 15
FINGER_EXTENDED = 1.10  # reach ratio above which a finger counts as extended.
                        # Measured on this rig: extended 1.30-1.66, folded
                        # 0.71-0.95 — this sits in the gap. See finger_reach().
MIN_HAND_SPAN = 0.22    # a hand must fill this fraction of the frame to count.
                        # Geometry alone would read hands resting on the desk as
                        # a palm or fist and zoom forever; a deliberate raised
                        # gesture is much closer to the camera than idle hands.
MOVE_STEP = 0.06        # position nudge per step (up.sh uses 0.05)
ZOOM_STEP = 0.05        # scale nudge per step (zoom_in.sh uses 0.05)
STEP_INTERVAL = 0.25    # seconds between repeats while a gesture is held
STEP_WARMUP = 4         # frames a gesture must be stable before the first step,
                        # so mid-transition misreads (fist->palm) can't fire
SCALE_MIN, SCALE_MAX = 0.15, 4.0
POS_LIMIT = 1.2         # hard stop on offset, scaled by zoom (see pos_limit)
GAZE_GAIN = 1.7         # hand/face offset from centre -> look-target (clamped to +-1)
FACE_EVERY = 3          # run face detection every Nth frame — ~5Hz is plenty, the
                        # rig's own _dragManager easing smooths it out
FACE_MIN_SCORE = 0.5    # face detector confidence floor
FACE_TTL = 1.0          # seconds a cached face box stays valid between detections
FACE_OVERLAP_VETO = 0.6 # a "hand" this much inside the face box is the face
HAND_MIN_SCORE = 0.7    # raised from MediaPipe's 0.5 default: at 0.5 the palm
                        # detector fires on faces, and a face filling the frame
                        # reads as an open palm (= zoom in forever)
EMOTE_COOLDOWN = 1.5    # seconds between gesture-triggered emotes
ONESHOT_COOLDOWN = 4.0  # seconds between one-shot actions (home / sequences)
                        # mapped directly to a count. The HOLD action's timing
                        # lives in gesture_map.json instead.
LOST_GRACE = 0.25       # seconds a gesture may drop out before it counts as released


# ---- CDP --------------------------------------------------------------------
class CDP:
    """Persistent DevTools connection to the kiosk page (reconnects on drop)."""

    def __init__(self):
        self.ws = None
        self._id = 0

    def _page_ws(self):
        for t in json.load(urllib.request.urlopen(DBG + "/json", timeout=3)):
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
        return None

    def connect(self):
        url = self._page_ws()
        if not url:
            return False
        self.ws = create_connection(url, max_size=None, timeout=5)
        return True

    def eval(self, js):
        """Evaluate JS, return its value. None on any transport failure."""
        if self.ws is None and not self.connect():
            return None
        self._id += 1
        mid = self._id
        try:
            self.ws.send(json.dumps({
                "id": mid, "method": "Runtime.evaluate",
                "params": {"expression": js, "returnByValue": True},
            }))
            while True:                       # drain until our reply lands
                msg = json.loads(self.ws.recv())
                if msg.get("id") == mid:
                    return msg.get("result", {}).get("result", {}).get("value")
        except Exception:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
            return None

    def frame(self):
        """Current window.__ghostFrame as a dict, or None."""
        raw = self.eval("JSON.stringify(window.__ghostFrame||null)")
        try:
            return json.loads(raw) if raw else None
        except Exception:
            return None


# ---- helpers ----------------------------------------------------------------
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def pos_limit(scale):
    """How far the model may sit off-centre, in model-matrix units.

    Scales with zoom: a tightly zoomed model legitimately needs a big offset to
    frame a head or upper body (the working jane_doe framing is y=-1.1 at 2.15x).
    Capping the offset at the scale keeps part of the model on screen, since the
    model's on-screen half-extent grows with scale too."""
    return max(POS_LIMIT, scale)


def active_model():
    """Model name from conf.yaml — the key framing.json is stored under."""
    try:
        with open(os.path.join(OLV, "conf.yaml"), encoding="utf-8") as fh:
            for line in fh:
                if "live2d_model_name:" in line and "'" in line:
                    return line.split("'")[1]
    except Exception:
        pass
    return None


def _read_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def persist(frame, path=FRAMING):
    """Write framing for the active model (same format as _frame.sh)."""
    model = active_model()
    if not model or not frame:
        return None
    data = _read_json(path)
    # backstop: never write an off-screen position to disk — that would survive
    # a reboot into an apparently-blank display
    sc = clamp(float(frame["scale"]), SCALE_MIN, SCALE_MAX)
    lim = pos_limit(sc)
    data[model] = {"scale": round(sc, 3),
                   "x": round(clamp(float(frame["x"]), -lim, lim), 3),
                   "y": round(clamp(float(frame["y"]), -lim, lim), 3)}
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
    return data[model]


def get_home():
    return _read_json(HOME_FILE).get(active_model())


def fire(script, *args):
    """Run a helper script without blocking the capture loop."""
    try:
        subprocess.Popen([script, *args],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---- hand geometry ----------------------------------------------------------
def _dist(a, b):
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def finger_reach(lms):
    """Per-finger extension: distance(tip, wrist) / distance(middle joint, wrist).

    Measured on this camera: an extended finger lands around 1.3-1.66, a folded
    one around 0.71-0.95. FINGER_EXTENDED sits in the gap. This is far more
    reliable here than MediaPipe's canned gesture classifier, which returns
    "None" with 0.85+ confidence for plain palms and fists at this angle."""
    wrist = lms[0]

    def reach(tip, pip):
        return _dist(lms[tip], wrist) / max(_dist(lms[pip], wrist), 1e-6)

    return (reach(8, 6), reach(12, 10), reach(16, 14), reach(20, 18))


FINGER_TIPS = (8, 12, 16, 20)   # index, middle, ring, pinky tip landmarks
FINGER_MCPS = (5, 9, 13, 17)    # ...and their knuckles


def point_direction(lms, finger, invert_x, invert_y):
    """Which way an extended finger aims: up/down/left/right, or None.

    None only for a true 45 degree diagonal — without a margin the axis
    flip-flops frame to frame, which stalls the hold-to-repeat timer."""
    tip, mcp = FINGER_TIPS[finger], FINGER_MCPS[finger]
    dx = lms[tip].x - lms[mcp].x                            # knuckle -> fingertip
    dy = lms[tip].y - lms[mcp].y
    sx = -dx if invert_x else dx                            # into screen sense
    sy = dy if invert_y else -dy                            # image y points down
    if abs(sx) > abs(sy) * 1.15:
        return "right" if sx > 0 else "left"
    if abs(sy) > abs(sx) * 1.15:
        return "up" if sy > 0 else "down"
    return None


def hand_count(lms):
    """(finger_count, extended_flags, span) for this hand, or None if too far.

    Which fingers doesn't matter — only the count. The thumb is never counted:
    measured on this rig, a thumb reads the same folded or out (thumb-to-knuckle
    0.49 thumbs-up vs 0.55 fist — no separation), so it can't be trusted.
    What each count DOES comes from gesture_map.json (editable in the web UI)."""
    xs = [p.x for p in lms]
    ys = [p.y for p in lms]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span < MIN_HAND_SPAN:
        return None                                         # too far away to mean it
    out = [r >= FINGER_EXTENDED for r in finger_reach(lms)]
    return sum(out), out, span


# ---- remappable gesture map -------------------------------------------------
GESTURE_MAP_FILE = os.path.join(HERE, "gesture_map.json")
DEFAULT_GESTURE_MAP = {
    "counts": {"0": "zoom_out", "1": "nudge", "2": "gaze",
               "3": "emote_next", "4": "zoom_in"},
    "hold": {"count": 0, "seconds": 3.0, "action": "home"},
}
_gmap = {"mtime": None, "map": DEFAULT_GESTURE_MAP}


def gesture_map():
    """Current finger-count → action map; hot-reloads when the file changes
    (the web UI writes it), so remaps apply live without a restart."""
    try:
        mt = os.path.getmtime(GESTURE_MAP_FILE)
    except OSError:
        return _gmap["map"]
    if mt != _gmap["mtime"]:
        _gmap["mtime"] = mt
        try:
            with open(GESTURE_MAP_FILE, encoding="utf-8") as fh:
                m = json.load(fh)
            _gmap["map"] = {
                "counts": {**DEFAULT_GESTURE_MAP["counts"],
                           **{str(k): str(v) for k, v in (m.get("counts") or {}).items()}},
                "hold": {**DEFAULT_GESTURE_MAP["hold"], **(m.get("hold") or {})},
            }
            print(f"[gesture] map loaded: {_gmap['map']['counts']} "
                  f"hold={_gmap['map']['hold']}")
        except Exception as e:
            print(f"[gesture] bad gesture_map.json ({e}) — keeping previous map")
    return _gmap["map"]


# ---- proactive greeting -----------------------------------------------------
# When your face reappears after a long absence, she greets you unprompted.
# The greeting goes through the FULL conversation pipeline (window.__ghostSay
# types into the frontend's chat box), so she answers in character, fires her
# emotion expressions, and it lands in chat history like any exchange.
DEFAULT_PROACTIVE = {
    "on": True,
    "away_secs": 300.0,   # how long you must be gone for a return to count
    "prompt": "(The user just walked back up to you after being away. Greet "
              "them warmly, in character, in one or two short sentences.)",
}
GREET_SETTLE = 2.0        # face must be back this long before greeting (a
                          # walk-past shouldn't trigger it)
_proactive = {"mtime": None, "conf": DEFAULT_PROACTIVE}


def proactive_conf():
    """Current proactive-greeting config; hot-reloads when the web UI saves."""
    try:
        mt = os.path.getmtime(PROACTIVE_FILE)
    except OSError:
        return _proactive["conf"]
    if mt != _proactive["mtime"]:
        _proactive["mtime"] = mt
        try:
            with open(PROACTIVE_FILE, encoding="utf-8") as fh:
                c = json.load(fh)
            _proactive["conf"] = {**DEFAULT_PROACTIVE,
                                  **{k: c[k] for k in DEFAULT_PROACTIVE if k in c}}
            print(f"[gesture] proactive greeting: "
                  f"{'on' if _proactive['conf']['on'] else 'off'}, "
                  f"away >= {_proactive['conf']['away_secs']:.0f}s")
        except Exception as e:
            print(f"[gesture] bad proactive.json ({e}) — keeping previous config")
    return _proactive["conf"]


def play_webui_sequence(name):
    """Trigger a web-UI emote sequence over HTTP (server plays it in its own
    thread, so this returns immediately). Harmless no-op if the UI is down."""
    try:
        req = urllib.request.Request(
            "http://localhost:8800/api/sequence/play",
            data=json.dumps({"name": name}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception as e:
        print(f"[gesture] sequence {name!r} failed (web UI running?): {e}")
        return False


# ---- camera -----------------------------------------------------------------
class Camera:
    """Raw YUV420 frames straight out of rpicam-vid, converted to RGB."""

    def __init__(self, rotate=0):
        self.rotate = rotate
        self.proc = None
        self.nbytes = CAM_W * CAM_H * 3 // 2

    def start(self):
        cmd = ["rpicam-vid", "-t", "0", "--codec", "yuv420",
               "--width", str(CAM_W), "--height", str(CAM_H),
               "--framerate", str(CAM_FPS), "--nopreview", "--flush", "-o", "-"]
        if self.rotate:
            cmd += ["--rotation", str(self.rotate)]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)

    def read(self):
        buf = self.proc.stdout.read(self.nbytes)
        if not buf or len(buf) < self.nbytes:
            return None
        yuv = np.frombuffer(buf, np.uint8).reshape(CAM_H * 3 // 2, CAM_W)
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except Exception:
                self.proc.kill()
            self.proc = None


# ---- the one JS that moves the model ---------------------------------------
STEP_JS = """(()=>{const f=window.__ghostFrame; if(!f) return null;
  f.scale=Math.min(%(smax)f,Math.max(%(smin)f,f.scale+(%(ds)f)));
  const lim=Math.max(%(plim)f,f.scale);
  f.x=Math.min(lim,Math.max(-lim,f.x+(%(dx)f)));
  f.y=Math.min(lim,Math.max(-lim,f.y+(%(dy)f)));
  window.__ghostFrameTarget=null;          // steps are absolute, skip the easing
  return JSON.stringify(f);})()"""


def look(cdp, nx, ny):
    """Point the model's gaze at a normalised (0..1) spot in the camera's view."""
    gx = clamp((nx - 0.5) * 2 * GAZE_GAIN, -1.0, 1.0)
    gy = clamp((ny - 0.5) * 2 * GAZE_GAIN, -1.0, 1.0)
    cdp.eval("window.__ghostGaze={x:%f,y:%f,t:performance.now()}" % (gx, gy))


def nearest_face(detector, rgb, ts_ms):
    """Box of the LARGEST face in view as raw normalised (x0, y0, x1, y1), or None.

    Largest == closest, which at a desk is reliably you. Picking a specific
    person by identity would need a face-embedding model and an enrollment
    step; box area is the cheap approximation that works for one user.

    Raw (un-mirrored) coordinates, because this box is also used to veto hand
    detections that land on the face — that comparison has to happen in image
    space, before any display-mirroring is applied."""
    try:
        det = detector.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)),
            ts_ms)
    except Exception:
        return None
    biggest, area = None, 0.0
    for d in det.detections or []:
        b = d.bounding_box
        a = b.width * b.height
        if a > area:
            biggest, area = b, a
    if biggest is None:
        return None
    return (biggest.origin_x / CAM_W, biggest.origin_y / CAM_H,
            (biggest.origin_x + biggest.width) / CAM_W,
            (biggest.origin_y + biggest.height) / CAM_H)


def inside_face(lms, face):
    """True if this 'hand' is really the face being misdetected as a palm.

    MediaPipe's palm detector fires on faces surprisingly often — a face filling
    the frame reads as an open palm, which would zoom forever. Any hand whose box
    sits mostly inside the face box is discarded."""
    if not face:
        return False
    fx0, fy0, fx1, fy1 = face
    xs = [p.x for p in lms]
    ys = [p.y for p in lms]
    hx0, hy0, hx1, hy1 = min(xs), min(ys), max(xs), max(ys)
    ow = max(0.0, min(hx1, fx1) - max(hx0, fx0))
    oh = max(0.0, min(hy1, fy1) - max(hy0, fy0))
    hand_area = max((hx1 - hx0) * (hy1 - hy0), 1e-6)
    return (ow * oh) / hand_area > FACE_OVERLAP_VETO


def step(cdp, ds=0.0, dx=0.0, dy=0.0):
    """Apply one clamped nudge, atomically, inside the page."""
    raw = cdp.eval(STEP_JS % {"ds": ds, "dx": dx, "dy": dy,
                              "smin": SCALE_MIN, "smax": SCALE_MAX,
                              "plim": POS_LIMIT})
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None


# ---- main loop --------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Gesture control for the OpenGhost hologram")
    ap.add_argument("--debug", action="store_true", help="print detected gestures + actions")
    ap.add_argument("--set-home", action="store_true",
                    help="save the CURRENT framing as home (what 🤟 restores) and exit")
    ap.add_argument("--no-invert-x", dest="invert_x", action="store_false",
                    help="flip horizontal sense (the display is mirrored for the "
                         "beam splitter, so the default may feel backwards to you)")
    ap.add_argument("--invert-y", action="store_true", help="flip vertical sense")
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 180],
                    help="camera rotation if the module is mounted upside down")
    ap.set_defaults(invert_x=True)
    args = ap.parse_args()

    if not os.path.exists(TASK_MODEL):
        sys.exit(f"missing gesture model: {TASK_MODEL}")

    cdp = CDP()
    if not cdp.connect():
        sys.exit("kiosk not reachable on :9222 — start the hologram first "
                 "(~/OpenGhost/scripts/live2d_ghost.sh)")

    if args.set_home:
        saved = persist(cdp.frame(), HOME_FILE)
        if not saved:
            sys.exit("could not read the live framing — is the hologram running?")
        print(f"home set to {saved}")
        return

    # Re-inject the idle loop so the gaze/frame hooks this script drives are
    # definitely live (idempotent — it cancels and replaces its own rAF).
    sys.path.insert(0, HERE)
    from openghost_kiosk_inject import IDLE_JS, idle_cfg_js  # noqa: E402
    cdp.eval(IDLE_JS)
    cdp.eval(idle_cfg_js())

    # First run for this model: whatever is on screen now is a framing the user
    # can actually see, so it makes a sane home. Never overwritten automatically.
    if not get_home():
        saved = persist(cdp.frame(), HOME_FILE)
        if saved:
            print(f"[gesture] home framing snapshotted: {saved}")

    # num_hands=2: with 1 the tracker latches onto whichever hand it found first
    # and simply ignores the other one, so only one hand ever works.
    recognizer = vision.GestureRecognizer.create_from_options(
        vision.GestureRecognizerOptions(
            base_options=mpp.BaseOptions(model_asset_path=TASK_MODEL),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=HAND_MIN_SCORE,
            min_hand_presence_confidence=HAND_MIN_SCORE))

    face_det = None
    if os.path.exists(FACE_MODEL):
        face_det = vision.FaceDetector.create_from_options(
            vision.FaceDetectorOptions(
                base_options=mpp.BaseOptions(model_asset_path=FACE_MODEL),
                running_mode=vision.RunningMode.VIDEO,
                min_detection_confidence=FACE_MIN_SCORE))
    else:
        print(f"[gesture] no face model at {FACE_MODEL} — face tracking disabled")

    cam = Camera(rotate=args.rotate)
    cam.start()

    running = {"go": True}
    signal.signal(signal.SIGINT, lambda *a: running.update(go=False))
    signal.signal(signal.SIGTERM, lambda *a: running.update(go=False))

    held = None          # what action is currently being held ("zoom_in", "up", ...)
    held_frames = 0      # frames it has been stable for
    last_step = 0.0
    dirty = False        # framing changed since the last save
    hold_since = None
    hold_fired = False
    last_oneshot = 0.0
    last_emote = 0.0
    last_seen = 0.0
    active = None
    face = None          # cached face box (raw normalised x0,y0,x1,y1)
    face_at = 0.0
    face_prev = False    # was a face present last frame (greeting transitions)
    absent_since = None  # when the face left; None = present or never seen
    greet_at = None      # face returned after a long absence at this time
    hands_on = not os.path.exists(HANDS_OFF_FLAG)
    t_start = time.monotonic()
    frames = 0
    print("[gesture] running — fingers up: 0=zoom out  1=nudge  2=gaze  "
          "3=emote  4=zoom in  (fist held 3s = home)")
    if not hands_on:
        print("[gesture] hand gestures DISABLED (face tracking only) — "
              "enable with: gesture_ctl.sh hands on")

    try:
        while running["go"]:
            rgb = cam.read()
            if rgb is None:                      # camera died — restart it
                cam.stop()
                time.sleep(1)
                cam.start()
                continue
            frames += 1
            now = time.monotonic()

            # Face FIRST: its box is needed to veto hands that are really the
            # face. Detection runs every FACE_EVERY frames; the box is cached in
            # between, and expires so a stale one can't veto a real hand.
            if face_det and frames % FACE_EVERY == 0:
                box = nearest_face(face_det, rgb, int((now - t_start) * 1000))
                if box:
                    face, face_at = box, now
            if face and now - face_at > FACE_TTL:
                face = None

            # ---- proactive greeting ----
            # Fire once when the face returns after a long absence and stays
            # for GREET_SETTLE (a walk-past shouldn't count). A sidecar restart
            # never greets: absent_since only arms on a present->absent
            # transition observed by THIS run.
            pgc = proactive_conf()
            if face:
                if absent_since is not None:
                    if pgc["on"] and now - absent_since >= float(pgc["away_secs"]):
                        greet_at = now
                    absent_since = None
                if greet_at is not None and now - greet_at >= GREET_SETTLE:
                    greet_at = None
                    ok = cdp.eval("window.__ghostSay(%s)" % json.dumps(pgc["prompt"]))
                    print("[gesture] proactive greeting fired"
                          + ("" if ok else " (chat box not ready — skipped)"))
            else:
                if face_prev:
                    absent_since = now
                greet_at = None
            face_prev = face is not None

            # Hand-gesture mode is toggled LIVE by `gesture_ctl.sh hands on|off`
            # (a flag file, checked every frame — a stat costs nothing at 14fps).
            # With hands off the hand model isn't even run: face tracking gets
            # the whole frame budget, and no pose can move or zoom her.
            hands_now = not os.path.exists(HANDS_OFF_FLAG)
            if hands_now != hands_on:
                hands_on = hands_now
                print(f"[gesture] hand gestures {'ENABLED' if hands_on else 'DISABLED'}"
                      f"{'' if hands_on else ' — face tracking stays on'}")

            hand_list = []
            if hands_on:
                res = recognizer.recognize_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)),
                    int((now - t_start) * 1000))
                hand_list = res.hand_landmarks or []

            # ---- decide ONE action for this frame ----
            # Every hand is considered (so left and right both work), but only a
            # single hand can win — the biggest one (closest = most deliberate).
            # The finger COUNT is fixed detection; what a count DOES comes from
            # gesture_map.json, hot-reloaded so web-UI remaps apply live.
            gmap = gesture_map()
            action, raw_count, hx, hy = None, None, 0.0, 0.0
            best = None
            for lms in hand_list:
                if inside_face(lms, face):       # your face is not an open palm
                    continue
                hc = hand_count(lms)
                if hc and (best is None or hc[2] > best[0]):
                    best = (hc[2], hc[0], hc[1], lms)
            if best:
                _, raw_count, out, lms = best
                w = lms[0]
                hx = (1.0 - w.x) if args.invert_x else w.x   # wrist: stable
                hy = w.y if args.invert_y else (1.0 - w.y)   # whatever fingers do
                last_seen = now
                mapped = gmap["counts"].get(str(raw_count), "none")
                if mapped == "nudge":
                    # direction comes from a finger — use the first extended one
                    # (a count with none extended can't aim, so it does nothing)
                    if any(out):
                        action = point_direction(lms, out.index(True),
                                                 args.invert_x, args.invert_y)
                elif mapped != "none":
                    action = mapped

            # A gesture that blinks out mid-hold is not a release — hand tracking
            # drops constantly. Grace only DELAYS the release; it never invents an
            # action, or steps keep firing after your hand has left the frame.
            releasing = action is None and (now - last_seen) >= LOST_GRACE

            # ---- repeating steps: zoom and nudge ----
            delta = {"zoom_in": (ZOOM_STEP, 0, 0), "zoom_out": (-ZOOM_STEP, 0, 0),
                     "up": (0, 0, MOVE_STEP), "down": (0, 0, -MOVE_STEP),
                     "right": (0, MOVE_STEP, 0), "left": (0, -MOVE_STEP, 0)}.get(action)
            if action != held and (action is not None or releasing):
                if dirty:                        # changed action — save and re-arm
                    persist(cdp.frame())
                    dirty = False
                held, held_frames, last_step = action, 0, 0.0
            # once the hold action has fired, the still-held hand must NOT keep
            # stepping — it would walk her off the framing it just restored
            if delta and action == held and not hold_fired:
                held_frames += 1
                # STEP_WARMUP kills the misreads that happen mid-transition, e.g.
                # the frame or two of "fist" as you flick your hand open
                if held_frames >= STEP_WARMUP and now - last_step >= STEP_INTERVAL:
                    last_step = now
                    f = step(cdp, *delta)
                    dirty = True
                    if args.debug:
                        print(f"[step] {action} -> {f}")

            # ---- GAZE ----
            # A peace sign takes priority (you're deliberately leading her eyes);
            # otherwise she watches the face found above, and only falls back to
            # the idle sway when the room is empty.
            if action == "gaze":
                look(cdp, hx, hy)
            elif face:
                cx, cy = (face[0] + face[2]) / 2, (face[1] + face[3]) / 2
                fx = (1.0 - cx) if args.invert_x else cx
                fy = cy if args.invert_y else (1.0 - cy)
                look(cdp, fx, fy)
                if args.debug and frames % 30 == 0:
                    print(f"[face] ({fx:.2f},{fy:.2f})")

            # ---- ONE-SHOT actions (cooldown-gated so a held hand fires once) ----
            def restore_home():
                h = get_home()
                if h:
                    cdp.eval("window.__ghostFrame=%s;window.__ghostFrameTarget=null;'ok'"
                             % json.dumps(h))
                    persist(h)
                    print(f"[gesture] restored home framing {h}")
                else:
                    print("[gesture] no home framing saved — run: gesture_ctl.sh sethome")

            if action in ("emote_next", "emote_off") and now - last_emote > EMOTE_COOLDOWN:
                last_emote = now
                fire(EMOTE_SH) if action == "emote_next" else fire(EMOTE_SH, "off")
                if args.debug:
                    print(f"[emote] {action}")
            elif action == "home" and now - last_oneshot > ONESHOT_COOLDOWN:
                last_oneshot = now
                restore_home()
                dirty = False
            elif action and action.startswith("sequence:") \
                    and now - last_oneshot > ONESHOT_COOLDOWN:
                last_oneshot = now
                play_webui_sequence(action.split(":", 1)[1])
                if args.debug:
                    print(f"[sequence] {action}")

            # ---- HOLD action: holding the configured count for N seconds ----
            # (default: fist 3s = restore home — the blind panic button). Any
            # steps fired during the hold are overwritten when it lands, and
            # hold_fired suppresses further stepping until release.
            hold = gmap["hold"]
            if raw_count is not None and raw_count == int(hold.get("count", 0)):
                if hold_since is None:
                    hold_since, hold_fired = now, False
                elif not hold_fired and now - hold_since >= float(hold.get("seconds", 3.0)):
                    hold_fired = True
                    ha = str(hold.get("action", "home"))
                    if ha == "home":
                        restore_home()
                        dirty = False
                    elif ha.startswith("sequence:"):
                        play_webui_sequence(ha.split(":", 1)[1])
                    elif ha in ("emote_next", "emote_off"):
                        fire(EMOTE_SH) if ha == "emote_next" else fire(EMOTE_SH, "off")
                    print(f"[gesture] hold fired: {ha}")
            else:
                hold_since, hold_fired = None, False

            if args.debug and frames % 15 == 0:
                fps = frames / (now - t_start)
                print(f"[{fps:4.1f}fps] action={action or '-':<11} hand=({hx:.2f},{hy:.2f})")
    finally:
        if dirty:
            persist(cdp.frame())
        cam.stop()
        try:
            recognizer.close()
        except Exception:
            pass
        print("\n[gesture] stopped")
        os._exit(0)     # mediapipe's teardown throws on interpreter shutdown


if __name__ == "__main__":
    main()
