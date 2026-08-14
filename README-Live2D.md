# OpenGhost — Live2D Talking Avatar

A voice-interactive Live2D avatar for the OpenGhost Pepper's Ghost display
(Raspberry Pi 5 + HyperPixel 4.0 Square 720×720 under a beam splitter).

This runs **alongside** the py5 sketches — it's a separate display mode, not a
replacement. py5 can't render Live2D Cubism models, so this uses a browser.

---

## How it works

```
 Mic ─▶ STT (sherpa-onnx, local) ─▶ LLM (oobabooga VM) ─▶ TTS (Piper, local) ─▶ Live2D mouth
                                          │
                        Open-LLM-VTuber backend  (Python, http://localhost:12393)
                                          │
              Chromium --kiosk ──────────▶ 720×720 HyperPixel (DPI-1)
              black background · UI hidden · mirrored for the beam splitter
```

- **Renderer:** Chromium in kiosk mode showing the [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)
  web frontend (WebGL / pixi-live2d). Lives in `~/Open-LLM-VTuber`.
- **STT (speech-to-text):** sherpa-onnx SenseVoice — local, offline, on the Pi.
- **TTS (text-to-speech):** sherpa-onnx + Piper `en_US-amy-medium` voice — local, offline.
- **LLM (the "brain"):** oobabooga text-generation-webui on the Proxmox VM at
  `http://192.168.2.8:5000/v1` (model `Cydonia.gguf`). Fallback: local Ollama
  `qwen2.5:3b` (installed on the Pi).
- **VAD:** Silero — hands-free speech detection + interruption.
- **Model:** `jane_doe` by default (VTS import). Others registered: `goth_mofu`,
  `shizuku`, `fern`, `elaine`, `mao_pro`. Swap with `scripts/switch_model.sh`.
- **Idle:** when no one is talking, the avatar gently sways (head/body/eyes via
  the rig's own physics) so she never looks frozen — set up in the inject script.

---

## Hardware you still need

The Pi itself has **no microphone and no speaker** (`arecord -l` shows no capture
devices; the Pi 5 also has **no 3.5 mm jack**, and the HyperPixel carries no audio).

- **Easiest:** one **USB headset** or **USB speakerphone puck** → gives mic + audio
  in a single device.
- Or any USB mic + any USB/USB-C speaker.

Once plugged in, **no config change is needed** — the mic auto-starts (see below).

---

## Running it

All command scripts live in **`~/OpenGhost/scripts/`**.

```bash
~/OpenGhost/scripts/live2d_ghost.sh          # start backend + kiosk + ghost look
~/OpenGhost/scripts/live2d_ghost.sh stop     # stop everything, un-mirror the display
MIRROR=0 ~/OpenGhost/scripts/live2d_ghost.sh # start without the beam-splitter flip
```

### Auto-start on boot
Configured in `~/.config/labwc/autostart` — the Pi autologins to the desktop and
launches the avatar automatically on power-on. Boot log: `~/openghost-boot.log`.
The fullscreen kiosk covers the desktop; if it exits, the normal desktop is still
there underneath.

---

## The Pepper's Ghost look (black + no UI)

The reflection only shows bright pixels, so the avatar must be a model floating on
pure black with no UI. This is achieved by:

1. **Black background** — the app draws its background as a pixi sprite *inside*
   the WebGL canvas (no CSS handle), so the default background file
   `~/Open-LLM-VTuber/backgrounds/ceiling-window-room-night.jpeg` was **replaced
   with a solid black image** (original saved as `…night.jpeg.orig`).
2. **Hidden UI + cursor** — `openghost_kiosk_inject.py` connects to Chromium's
   DevTools port (9222) after launch and injects CSS that hides everything except
   the model canvas and the mouse cursor.
3. **Hands-free mic** — the same injector sets `autoStartMicOn` in the kiosk's
   localStorage (persists across reboots), so the mic arms itself with no clicking.
4. **Mirroring** — `wlr-randr --output DPI-1 --transform flipped` flips the whole
   display for the single-reflection beam splitter. Toggle with `MIRROR=0`.

These are model-independent — they work for **any** model.

---

## Switching between installed models (one command)

Once models are registered (below), swap between them live — no reboot:

```bash
~/OpenGhost/scripts/switch_model.sh              # list installed models + which is current
~/OpenGhost/scripts/switch_model.sh goth_mofu    # switch to that model
~/OpenGhost/scripts/switch_model.sh jane_doe     # switch back
```
It updates `conf.yaml`, restarts the backend, and reloads the display with the
ghost look. The choice persists (it's written to `conf.yaml`), so it survives reboots.

## Framing the model (move / zoom) — one command each

New models often load full-body and tiny. These adjust the **currently active**
model live *and* remember it per-model (saved to `scripts/framing.json`, so the
framing comes back on reload and reboot):

```bash
~/OpenGhost/scripts/zoom_in.sh     # bigger        ~/OpenGhost/scripts/up.sh     # move up
~/OpenGhost/scripts/zoom_out.sh    # smaller       ~/OpenGhost/scripts/down.sh   # move down
~/OpenGhost/scripts/left.sh        # move left     ~/OpenGhost/scripts/right.sh  # move right
~/OpenGhost/scripts/reset.sh       # back to the model's registered default
~/OpenGhost/scripts/show.sh        # print saved + live framing for the active model
```

Each press nudges by a small step; run them a few times to dial it in while
watching the display. The values are stored per-model, so every character keeps
its own framing.

## Emotes / expressions (cycle or set)

```bash
~/OpenGhost/scripts/emote.sh                    # step to the NEXT emote (cycles all)
~/OpenGhost/scripts/emote.sh list               # list this model's emotes + current
~/OpenGhost/scripts/emote.sh star_eyes          # apply one emote
~/OpenGhost/scripts/emote.sh angry hand_left    # apply SEVERAL at once (merged)
~/OpenGhost/scripts/emote.sh off                # clear back to neutral
```

Passing multiple names layers them — they're merged into one expression at runtime
(`_emote_combine.py` → `CubismExpressionMotion.create`), since this build only shows
one expression at a time otherwise.

Emotes are the model's Live2D **expressions**. They must be registered in the
model's `.model3.json` under `FileReferences.Expressions` (`{"Name":"...","File":"...exp3.json"}`).
Jane Doe's VTube-Studio expression files were wired in this way — available:
`neutral, star_eyes, blush, hand_right, hand_left, tears, angry, blank_eyes, face_dark, blood`.
A model with no registered expressions will report *"this model has no emotes."*
(The idle sway runs regardless; emotes are a separate, manual overlay.)

### The LLM drives expressions automatically

The avatar changes its own face while talking. It works via `emotionMap` in
`model_dict.json` — a map of **emotion keyword → expression name**:

```jsonc
"emotionMap": { "joy": "star_eyes", "angry": "angry", "sad": "tears", ... }
```

How it flows (all built into Open-LLM-VTuber):
1. On startup the keyword list (`[joy], [angry], …`) is injected into the LLM's
   system prompt (`prompts/utils/live2d_expression_prompt.txt` +
   `tool_prompts.live2d_expression_prompt` in `conf.yaml`), telling it to sprinkle
   `[keyword]` tags into its replies.
2. The backend parses those tags, applies the mapped expression, and **strips the
   tag from the text** so the TTS voice never says the word.

The map value may be an expression **name** (string, recommended) or its **index**
(int) in the model3.json `Expressions` array. Jane Doe's map is already set
(`joy/excited→star_eyes`, `smug/shy/blush→blush`, `sad/crying→tears`, `angry`,
`surprised/shocked/fear→blank_eyes`, `disgust/menacing→face_dark`, `hurt→blood`).
**To enable it for a new model:** register its expressions (above), add an
`emotionMap`, then restart the backend (`switch_model.sh <name>`).

> Whether the face actually moves depends on the LLM following the prompt and
> emitting the tags. Instruct/RP models usually do; if yours doesn't, reinforce it
> in `conf.yaml` → `character_config.persona_prompt`.

## Adding / changing the Live2D model

**Difficulty: easy** if you have a pre-rigged Cubism 3/4 model. 3 steps
(after this, `switch_model.sh <name>` handles the swapping):

**1. Drop the model folder in:**
```
~/Open-LLM-VTuber/live2d-models/<yourmodel>/
```
It must contain a `.model3.json` (+ `.moc3`, textures, motions) — i.e. **Cubism
3/4** format. The old Cubism 2 `.model.json` format is not supported.

**2. Register it in `~/Open-LLM-VTuber/model_dict.json`** (copy the `mao_pro` block):
```jsonc
{
  "name": "yourmodel",
  "url": "/live2d-models/yourmodel/runtime/yourmodel.model3.json",
  "kScale": 0.5,          // ── size / framing knobs for the 720×720 ghost
  "initialXshift": 0,     //    (zoom to head+torso for a nicer reflection)
  "initialYshift": 0,
  "kXOffset": 1150,
  "idleMotionGroupName": "Idle",             // idle motion group in the model3.json
  "emotionMap": { "neutral": 0, "joy": 3 }   // optional: LLM-triggered expressions
}
```

**3. Point the config at it** — in `~/Open-LLM-VTuber/conf.yaml`:
```yaml
character_config:
  live2d_model_name: 'yourmodel'
```
Then `scripts/switch_model.sh yourmodel` (or re-run `scripts/live2d_ghost.sh`).

> **Pi GPU limit:** textures must be **≤ 4096×4096**. A model with an 8192 texture
> loads but renders **invisible**. Downscale the texture PNG to 4096 (UVs are
> normalized, so it's lossless to the mapping) and it'll show. `.rar` models from
> Chinese sources often need `unar` (installed) — `7z` fails with "Unsupported Method".

### Where to get models
- Live2D's official **sample models** are free.
- [ShiraLive2D](https://shiralive2d.com/live2d-sample-models/), booth.pm, VTuber
  shops — mind the license (many free ones are non-commercial).
- **Copyrighted VTuber characters** (e.g. Hololive members) are **not** legally
  downloadable as Live2D models — only unauthorized rips exist. Use a model you
  own/commissioned, or a properly-licensed one.
- Rigging your own from an illustration needs **Live2D Cubism Editor** and is a
  large manual effort — dropping in a pre-rigged model is the easy path above.

---

## Terminal chat (`~/start_chat`)

Talk to the LLM from a terminal and watch the hologram react — handy when there's
no mic/speaker. You type, the reply prints, and the avatar changes expression to
match (via the reply's `[emotion]` tags → emotionMap → `emote.sh`).

```bash
~/start_chat --no_mic --no_speaker   # text in / text out (right for a Pi with no audio)
~/start_chat                         # full mode (attempts voice; --no_* to disable each)
```
Flags: `--no_mic` (don't use speech-to-text — you type) · `--no_speaker` (no TTS, text
only). In-chat: `/neutral` reset face · `/reset` clear convo · `/help` · `/quit`.

It reads the LLM + persona straight from `conf.yaml`, so it's the same brain as the
hologram. It talks to the LLM directly (not through the backend), so there's no
lip-sync — the interaction you get today is expression changes. Full voice + lip-sync
is the kiosk's job once a mic/speaker is attached.

## Other tweaks

| Want to… | Where |
|---|---|
| Change the voice | `conf.yaml` → `tts_config.sherpa_onnx_tts.vits_model` (any [Piper voice](https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models)) |
| Change the persona | `conf.yaml` → `character_config.persona_prompt` |
| Switch LLM to local Ollama | `conf.yaml` → `agent_settings.basic_memory_agent.llm_provider: 'ollama_llm'` |
| Reframe the model | `scripts/up.sh` · `down.sh` · `zoom_in.sh` · `zoom_out.sh` · `reset.sh` |

---

## Files (in `~/OpenGhost/scripts/`)

| File | Purpose |
|---|---|
| `live2d_ghost.sh` | Launcher: mirror display, start backend, open kiosk, apply ghost look |
| `switch_model.sh` | List / swap the active Live2D model in one command |
| `up/down/left/right/zoom_in/zoom_out/reset/show.sh` | Frame the active model (live + saved) |
| `emote.sh` | Cycle / set the active model's expression (emote) |
| `_frame.sh` · `framing.json` | Framing core + per-model saved positions (used by the above) |
| `openghost_kiosk_inject.py` | Injects black/hide-UI CSS, hides cursor, arms mic, starts idle sway, applies saved framing |
| `cdp_eval.py` | Debug helper: evaluate JS in the kiosk page over DevTools |

`README-Live2D.md` stays in `~/OpenGhost/`. The py5 sketches (`boids.py`, etc.) also
stay in `~/OpenGhost/` — they're a separate display mode, not command scripts.

Config & app live in `~/Open-LLM-VTuber/` (`conf.yaml`, `model_dict.json`,
`live2d-models/`, `backgrounds/`, `models/tts/`).

---

## Troubleshooting

- **Avatar doesn't respond to voice** — check a mic exists: `arecord -l`. No
  capture device → plug in a USB mic/headset.
- **No sound** — check output: `wpctl status` (Sinks). Plug in a USB speaker/headset.
- **Blank/desktop instead of avatar** — check `~/openghost-boot.log` and
  `/tmp/olv_server.log`; re-run `~/OpenGhost/live2d_ghost.sh`.
- **LLM not replying** — the oobabooga VM (`192.168.2.8:5000`) must be on with a
  model loaded, or switch `llm_provider` to `ollama_llm` for fully-local operation.
- **Reflection reads backwards** — toggle the mirror with `MIRROR=0`.
