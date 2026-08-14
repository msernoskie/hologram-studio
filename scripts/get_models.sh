#!/bin/bash
# Fetch the MediaPipe models gesture_ctl.py needs into ~/OpenGhost/models/
# (they are deliberately not committed — 8MB of third-party binaries).
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
mkdir -p "$DIR"
BASE="https://storage.googleapis.com/mediapipe-models"
curl -sSL -o "$DIR/gesture_recognizer.task" \
  "$BASE/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"
curl -sSL -o "$DIR/blaze_face_short_range.tflite" \
  "$BASE/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
ls -lh "$DIR"
