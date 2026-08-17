# OpenGhost — Gesture Control

Control the hologram with your hands, and have her watch you while you work.
Camera Module 3 → MediaPipe → the live Live2D model.

---

## Quick start

```bash
~/OpenGhost/scripts/gesture_ctl.sh start     # background, log: ~/openghost-gesture.log
~/OpenGhost/scripts/gesture_ctl.sh debug     # foreground, prints what it sees   ← use to test
~/OpenGhost/scripts/gesture_ctl.sh stop      # stop + release the camera
~/OpenGhost/scripts/gesture_ctl.sh status    # running? + hands on/off + last log lines
~/OpenGhost/scripts/gesture_ctl.sh sethome   # save the CURRENT framing as the panic-button target
~/OpenGhost/scripts/gesture_ctl.sh hands on  # enable hand gestures
~/OpenGhost/scripts/gesture_ctl.sh hands off # face-tracking only — no pose can move/zoom her
```

The hologram must already be running (`~/OpenGhost/scripts/live2d_ghost.sh`).

**`hands on|off` applies instantly** — no restart. The setting is a flag file
(`scripts/.hands_off`), so it also survives restarts and reboots. With hands off she still watches
you (face tracking is separate), the hand model isn't even run, and nothing you do with your hands
can move, zoom or emote her. **Current default: off** — turn them on when you want to adjust her.

In `debug` you get a line a second like `[13.8fps] action=zoom_in  hand=(0.62,0.44)` —
frame rate, the single action that won this frame, and where your hand is.

---

## Face tracking (always on, no gesture needed)

She watches the **nearest face** in the camera's view — head, eyes and body turn to follow, with
the hair physics trailing behind. When nobody is in frame she falls back to the idle figure-8 sway.
She also does idle **part-motion bursts** — by default a little torso bounce: 1 or 3 quick pulses,
picked at random, every few seconds (paused while she's talking) — a liveliness tic, not a reaction
to anything. The web UI's **Idle motions** tab configures all of it: a master toggle, plus one row
per motion — which part moves (torso bounce, head nod, chest, shoulders, breath, body sway, hip
sway), strength, pulse length, the possible burst sizes, and the random rest range between bursts.
Motions drive Live2D parameters directly, never her position/framing; parts a model doesn't have
are silently skipped. Settings live in `scripts/idle.json` and apply live on save.

Nearest = largest face in frame, which at a desk is reliably you. Picking *you specifically* out of
several people would need a face-embedding model plus an enrollment step — possible, but a
different piece of work; box size is the cheap approximation that works for one person at a desk.

Two fingers up overrides it: while you hold them, she watches your hand instead.

---

## The gestures

One rule: **count the fingers you hold up.** Which fingers doesn't matter. Every action is a
discrete step that repeats while you hold it — the same step size as the `up.sh` / `zoom_in.sh`
scripts. Nothing tracks your hand continuously, so nothing can run away.

| Fingers up | What it does |
|---|---|
| **0** (fist) | **Zoom out** — one step per 0.25s while held |
| **1** — aim it up, down, left or right | **Nudge** one step that way |
| **2** | She watches your **hand** instead of your face |
| **3** | **Next emote** (the cycle passes through neutral, so keep going to clear) |
| **4** (open palm) | **Zoom in** — one step per 0.25s while held |
| **Fist held 3 s** | **Panic button** — restore the saved home framing |

**The thumb is never counted.** Measured on this rig, a thumb reads the same folded or out
(thumb-to-knuckle 0.49 for thumbs-up vs 0.55 for a fist — no separation), so palm-with-tucked-thumb
and palm-with-thumb are both "4", and a thumbs-up is just a fist: it zooms out.

**The panic hold zooms out first** — the fist steps until the 3 s lands, then home overwrites those
steps, and the still-held fist stays quiet until you release it. If you *want* a long zoom-out,
release and re-fist before the 3 s is up.

---

## Moving her around

**By gesture:** hold up **one finger and aim it** — up, down, left or right. She takes one step
that way every 0.25s for as long as you hold it, so you can walk her across the screen. Down is
just pointing your finger at the floor.

Two things that stop a point from registering:
- **Distance.** Your hand must fill ~22% of the frame. Raise it toward the camera, don't point from
  your lap.
- **The other fingers.** Exactly one finger clearly out, the rest clearly curled. Two half-open
  fingers read as "2" and she'll watch your hand instead of moving.

**By terminal** — always works, no camera involved, and the fastest way to frame her precisely:

```bash
~/OpenGhost/scripts/down.sh        # one step down   (repeat as needed)
~/OpenGhost/scripts/up.sh          # one step up
~/OpenGhost/scripts/left.sh        # one step left
~/OpenGhost/scripts/right.sh       # one step right
~/OpenGhost/scripts/zoom_in.sh     # bigger
~/OpenGhost/scripts/zoom_out.sh    # smaller
~/OpenGhost/scripts/show.sh        # where is she now?
```

Same step size as the gestures, applied live and saved to `framing.json`. Once she's where you want
her, `gesture_ctl.sh sethome` makes that the panic-button target.

**Either hand works**, and both are watched at once — with two hands up, one is picked; keep the
other down for predictability.

**Only one action can fire per frame** — a finger count maps to exactly one action, so a single
pose can never register as two things and send her drifting.

Zoom and nudge **persist** to `scripts/framing.json` when you change or release the gesture, so they
survive reload and reboot — exactly like the `up.sh` / `zoom_in.sh` scripts.

---

## Help — she vanished

1. **Hold a fist for 3 seconds** — the panic button. Restores your saved home framing, works
   blind (she zooms out during the hold; home overwrites that when it lands).
2. **From a terminal:**
   ```bash
   ~/OpenGhost/scripts/show.sh    # where is she? saved + live position
   ```
3. **Back to a known-good framing** (jane_doe, upper body):
   ```bash
   ~/Open-LLM-VTuber/.venv/bin/python ~/OpenGhost/scripts/cdp_eval.py \
     'window.__ghostFrame={scale:2.15,x:0,y:-1.1};window.__ghostFrameTarget=null;"ok"'
   ```

**Do not use `reset.sh` as a panic button.** It resets to the *model_dict* default — `kScale: 0.62`
centred — which for a full-body model like jane_doe is a small figure in the middle of the screen,
nothing like a working crop, and it overwrites `framing.json` on the way. That is what made "reset
isn't working" look broken: it fired correctly and gave you the wrong framing.

Home is snapshotted on first run and never changed automatically. If it holds something bad, fix it
by framing her the way you want (gestures or `up.sh`/`zoom_in.sh`) and running:

```bash
~/OpenGhost/scripts/gesture_ctl.sh sethome
```

Offsets are also hard-clamped (`pos_limit()`, scaled by zoom level), so part of her always stays on
screen and an off-screen position can never be written to `framing.json`.

---

## If the directions feel backwards

Likely — the display is flipped horizontally for the beam splitter
(`wlr-randr --transform flipped`), so screen sense is a coin flip until you try it. This affects
nudge direction, gaze direction and face tracking together.

```bash
~/OpenGhost/scripts/gesture_ctl.sh stop
~/OpenGhost/scripts/gesture_ctl.sh debug --no-invert-x    # horizontal feels backwards
~/OpenGhost/scripts/gesture_ctl.sh debug --invert-y       # vertical feels backwards
~/OpenGhost/scripts/gesture_ctl.sh debug --rotate 180     # camera mounted upside down
```

Flags combine, and work with `start` too. To make it permanent, edit
`ap.set_defaults(invert_x=True)` near the bottom of `scripts/gesture_ctl.py`.

---

## Test checklist

1. **Face** — sit in front of the camera and move side to side.
   → She tracks your face. Leave the frame → idle sway resumes after ~0.6s.
2. **Zoom** — hold up an open palm. → She grows, one step per 0.25s. Fist → shrinks.
3. **Nudge** — point up, then left. → One step per 0.25s in that direction.
4. **Both hands** — repeat step 2 with your other hand. → Identical behaviour.
5. **Gaze** — hold two fingers up and move the hand. → She follows it rather than your face.
6. **Emotes** — three fingers up, a few times ~2s apart. → Face changes each time; the cycle
   passes through neutral.
   Check what's available first: `~/OpenGhost/scripts/emote.sh list`
7. **Persistence** — after zooming, `~/OpenGhost/scripts/show.sh` → saved matches live.
8. **Panic** — fist held 3s. → Snaps back to home framing.

---

## Troubleshooting

**Nothing detected (`action=-` always)**
- **Get your hand closer.** A hand must fill at least 22% of the frame (`MIN_HAND_SPAN`) to count,
  so that hands resting on the desk don't zoom her forever. Raise it toward the camera.
- Aim the camera at yourself — `rpicam-hello -t 5000` shows a preview (stop the sidecar first,
  it holds the camera exclusively).
- More light helps; a backlit hand tracks poorly.
- Hold the shape still for ~4 frames (`STEP_WARMUP`) before the first step fires.

**A gesture fires when I didn't mean it**
Raise `MIN_HAND_SPAN` (fewer stray hands qualify) or `STEP_WARMUP` (longer deliberate hold) in the
tuning block at the top of `gesture_ctl.py`.

**Leaning toward the camera used to zoom her in.** MediaPipe's palm detector fires on faces, so a
face filling the frame was read as an open palm. Two guards now: the hand-detection confidence
floor is raised to 0.7 (`HAND_MIN_SCORE`, up from MediaPipe's 0.5 default), and any "hand" whose
box sits more than 60% inside the detected face box is discarded (`FACE_OVERLAP_VETO`). Face
detection therefore runs *before* hand classification each frame, and its box is cached for up to
a second (`FACE_TTL`) so a stale box can't veto a real hand.

**Recognition is decided by finger geometry, not MediaPipe's gesture classifier.**
Measured on this rig, the canned classifier returns `None` with 0.85+ confidence for plain palms
and fists at normal desk distance — it is simply unreliable here. Instead each finger gets a
"reach" score, `distance(tip, wrist) / distance(middle joint, wrist)`: extended fingers measure
1.30–1.66, folded ones 0.71–0.98, and `FINGER_EXTENDED = 1.10` splits the gap. Counting extended
fingers gives every gesture directly, and the cases are mutually exclusive, so one hand can never
fire two actions. The classifier is no longer used at all.

To re-measure after moving the camera:
```bash
~/OpenGhost/scripts/gesture_ctl.sh stop
~/OpenGhost/gesture-venv/bin/python ~/OpenGhost/scripts/gesture_diag.py 45
```
It prints per-finger reach, hand span and thumb metrics for every frame. Those numbers are the only
thing the thresholds above are set from.

**`kiosk not reachable on :9222`** — start the hologram first.

**Camera busy / no frames**
```bash
pgrep -af "[r]picam-vid"
~/OpenGhost/scripts/gesture_ctl.sh stop     # kills the sidecar and its camera child
```

**Logs**
```
~/openghost-gesture.log          # gesture events
~/openghost-gesture.log.stderr   # MediaPipe's C++ chatter — noisy, ignorable
```

---

## How it works

```
rpicam-vid (raw YUV420)
   → MediaPipe Face Detector      (every 3rd frame; box cached 1s)
   → MediaPipe Hand Landmarker    (every frame, 2 hands, face-box vetoed)
   → finger-count classifier      (one action per frame)
   → CDP → kiosk page
```

Face detection runs **first** because its box is needed to reject hands that are really your face.

The sidecar never touches the model directly. It publishes two values onto the page:

- `window.__ghostFrameTarget = {scale, x, y, t}` — where the model should be
- `window.__ghostGaze = {x, y, t}` — where it should look

The idle loop in `scripts/openghost_kiosk_inject.py` reads them every frame. Both are **ignored
once stale** (>500ms framing, >600ms gaze), so the existing `up.sh` / `zoom_in.sh` / `emote.sh`
scripts keep working normally and the idle sway resumes the moment you leave.

Tuning knobs (step sizes, repeat rate, confidence floors, clamps) are in a labelled block near the
top of `scripts/gesture_ctl.py`.

**Dependencies** live in their own venv at `~/OpenGhost/gesture-venv` — deliberately *not* the
Open-LLM-VTuber venv. MediaPipe needs numpy 2.x, which breaks the system `picamera2` (built against
numpy 1.24); that's why frames come from `rpicam-vid` over a pipe rather than picamera2.

Models are in `~/OpenGhost/models/` (`gesture_recognizer.task`, `blaze_face_short_range.tflite`).

Not wired into autostart yet — start it by hand until the directions are dialled in.

---

## Web UI — Hologram Studio

`http://<pi-ip>:8800` (LAN only). Start/stop with:

```bash
~/OpenGhost/scripts/webui.sh start|stop|status|debug    # log: ~/openghost-webui.log
```

Three panels:

- **Models** — click to switch the active Live2D model (runs `switch_model.sh`:
  restarts the backend and reloads the hologram, ~15 s).
- **Emotes & AI labels** — every expression the active model registers. Click a name to
  preview it live; tick several and "Fire selected" to preview a merged combo. Each emote
  takes comma-separated emotion labels (e.g. `joy, excited`). **Apply labels → AI emotionMap**
  writes them into Open-LLM-VTuber's `model_dict.json` `emotionMap` — the mechanism its LLM
  pipeline natively uses to pick expressions from `[joy]`-style tags (restart the backend to
  pick it up: `scripts/switch_model.sh <model>`).
- **Sequences** — chain steps (each step = one or more emotes + a hold time) into named,
  labeled sequences ("greeting", "victory dance"). Play/edit/delete from the list; playback
  always lands back on neutral.

The header has tabs; besides the main **Studio** view and **Idle motions** (see above):

- **Chat tab** — talk to her from the browser. Messages are typed into the hologram's
  own (hidden) chat box, so they run Open-LLM-VTuber's full pipeline: her LLM + persona
  reply, emotion tags fire her expressions on the display, and everything lands in the
  same chat history voice would use. The tab shows the live conversation (polled), and
  the conversation dropdown browses past history files (stored by the backend under
  `Open-LLM-VTuber/chat_history/<conf_uid>/`).
- **Subtitles** — her replies are mirrored onto the hologram itself as a subtitle line
  at the bottom of the display (emotion tags stripped), fading out after she finishes.
  Until a speaker is attached this is how she "speaks". Toggle in the Chat tab
  (stored as `subtitles` in `scripts/idle.json`).
- **Proactive greeting** — when the camera sees your face again after you've been away
  (default 5 min) and you stay ~2 s, the gesture sidecar sends a hidden instruction
  through the chat pipeline and she greets you in character, unprompted. Configure
  on/off, the away threshold and the instruction in the Chat tab
  (`scripts/proactive.json`, hot-reloaded — a sidecar restart never greets by itself).

Chat endpoints: `POST /api/chat/send {"text": …}`, `GET /api/chat/current`,
`GET /api/chat/histories`, `GET /api/chat/history?id=…`, `GET/POST /api/proactive`.

**For AI integration**, the server is itself an API (all JSON):

```
GET  /api/export                     everything: models, emotes, labels, sequences
POST /api/emote            {"names": ["star_eyes"]}          set expression(s)
POST /api/sequence/play    {"name": "greeting"}              run a labeled sequence
POST /api/sequence/stop
POST /api/switch           {"model": "jane_doe"}
```

So an LLM with tool access can `GET /api/export` to learn what's available (the labels are
the semantic hints) and then fire emotes or sequences over HTTP. Sequence/label storage is
`webui/library.json`, per model, committed to git.

### AI backend & character (web UI)

Two more panels at the bottom of the studio:

- **AI backend** — pick the LLM provider (`openai_compatible_llm` = the oobabooga VM,
  `ollama_llm` = local Ollama, plus claude/openai/gemini/etc.), set its `base_url`, `model`
  and API key. Writes to `conf.yaml` surgically (comments survive). **Restart backend now**
  applies it (clean backend restart + hologram reload).
- **Character** — the character's name, what she calls you, and the persona/system prompt.
  **Character cards** are named presets stored in `webui/library.json`: fill the fields,
  "Save as card", then **apply** any card later to swap personalities in one click
  (+ backend restart to make it live). The emotion-tag instructions are injected by
  Open-LLM-VTuber automatically — personas don't need to mention them.

API: `GET /api/ai`, `POST /api/ai/backend`, `POST /api/ai/character`, `POST /api/ai/restart`,
`POST /api/cards/save|delete`.

### Remapping gestures (web UI)

The **Hand gestures** panel in the studio maps each finger count (0–4) to an action:
`none`, `zoom_in`, `zoom_out`, `nudge`, `gaze`, `emote_next`, `emote_off`, `home`, or
**any saved sequence** (`▶ name`) — so e.g. three fingers can play your "greeting" sequence.
The **hold** row is the long-press: which count, held how long, does what (default fist 3 s =
restore home). There's also a hands on/off toggle button, same switch as
`gesture_ctl.sh hands on|off`.

Mapping lives in `scripts/gesture_map.json`; the sidecar watches the file's mtime and reloads
on change, so saves from the UI apply **live** — no restart. `nudge` aims where the finger
points, so it only makes sense on count 1. Direct-mapped `home`/sequence actions have a 4 s
cooldown so a held hand fires once.

### Framing from the web UI

The Models panel now includes a **Framing** d-pad: arrows nudge her around, ＋/－ zoom, with a
step-size selector (fine/medium/big — one "fine" step = one `up.sh`). The readout shows live,
saved, and home framing side by side. Buttons: **Restore home**, **Set home = current**, and
**Reset to model default** (confirm-guarded — that's the small centred `kScale` framing, and it
does not touch home). Everything applies live and persists per model, exactly like the shell
scripts, which all still work.

API: `GET/POST /api/frame` (`{ds,dx,dy}`), `POST /api/frame/home|sethome|reset`.

### Adding models & expression scanning (web UI)

**Add model** (Models panel): upload a Cubism 3+ archive — zip, rar or 7z, VTube Studio
exports included. The pipeline (`scripts/add_model.py`) extracts it (`unar`, which handles
the rar variants p7zip can't), finds the `.model3.json`, ASCII-slugs the folder/entry name,
**downscales any texture over 4096 px** (the Pi 5 GPU's max — oversized textures load but
render invisible), registers all expression files, and adds it to `model_dict.json`.

**Expression scanning**: VTS models routinely ship `.exp3.json` expression files without
registering them in the `.model3.json` — they exist on disk but the emote selector can't see
them (fern arrived like this; jane_doe was fixed by hand before this existed). The scanner
(`scripts/scan_expressions.py [model]`) registers the missing ones and adds an empty
`neutral`. It runs automatically on **every model switch** and during **Add model**; the
"Scan for expressions" button in the emotes panel runs it on demand.
