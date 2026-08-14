#!/usr/bin/env python3
"""Dump what MediaPipe actually reports for a hand, so the thresholds in
gesture_ctl.py can be set from measurements instead of guesses.

    gesture_diag.py [seconds]

Stop the gesture sidecar first — it holds the camera exclusively:
    ~/OpenGhost/scripts/gesture_ctl.sh stop

Columns:
  classifier   MediaPipe's own canned gesture + confidence (unreliable here)
  idx/mid/ring/pinky   per-finger reach = dist(tip,wrist)/dist(middle joint,wrist)
                       measured: extended 1.30-1.66, folded 0.71-0.98
  span         hand bounding box as a fraction of the frame (MIN_HAND_SPAN gate)
  th-gap       thumb tip to middle-finger knuckle, over palm size
  th-rch       thumb reach, same form as the finger reaches
  th-dy        thumb tip height above the wrist (+ = above, i.e. thumbs-up-ish)
"""
import os
import subprocess
import sys
import time

os.environ.setdefault("GLOG_minloglevel", "2")
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision

W, H, FPS = 640, 480, 15
SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 45
MODEL = os.path.expanduser("~/OpenGhost/models/gesture_recognizer.task")

rec = vision.GestureRecognizer.create_from_options(
    vision.GestureRecognizerOptions(
        base_options=mpp.BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.VIDEO, num_hands=2))

p = subprocess.Popen(
    ["rpicam-vid", "-t", "0", "--codec", "yuv420", "--width", str(W), "--height", str(H),
     "--framerate", str(FPS), "--nopreview", "--flush", "-o", "-"],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
n = W * H * 3 // 2


def d(a, b):
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


t0 = time.time()
print("t     classifier(score)   idx   mid   ring  pinky span  th-gap th-rch th-dy")
print("-" * 80)
while time.time() - t0 < SECS:
    buf = p.stdout.read(n)
    if len(buf) < n:
        break
    yuv = np.frombuffer(buf, np.uint8).reshape(H * 3 // 2, W)
    rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)
    res = rec.recognize_for_video(
        mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)),
        int((time.time() - t0) * 1000))
    for i, lms in enumerate(res.hand_landmarks or []):
        w = lms[0]
        r = lambda tip, pip: d(lms[tip], w) / max(d(lms[pip], w), 1e-6)
        palm = max(d(lms[0], lms[9]), 1e-6)
        cat = res.gestures[i][0] if i < len(res.gestures) else None
        name = f"{cat.category_name}({cat.score:.2f})" if cat else "-"
        xs = [q.x for q in lms]
        ys = [q.y for q in lms]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        print(f"{time.time()-t0:5.1f} {name:<18} {r(8,6):.2f}  {r(12,10):.2f}  "
              f"{r(16,14):.2f}  {r(20,18):.2f}  {span:.2f}  "
              f"{d(lms[4], lms[9])/palm:.2f}   {r(4,2):.2f}   {w.y-lms[4].y:+.3f}")
        sys.stdout.flush()
p.terminate()
os._exit(0)
