# Hologram Studio

A Raspberry Pi 5 Pepper's Ghost hologram running a live AI character: a Live2D
avatar under a beam-splitter cube that watches you (face tracking), responds to
hand gestures, plays labeled emote sequences, and talks through a local LLM —
all managed from a web UI (models, framing, gestures, sequences, AI backend,
character cards).

Built on top of two excellent open-source projects:

- **[OpenGhost](https://github.com/xanderchinxyz/OpenGhost)** by Alexander Chin —
  the Pepper's Ghost hardware design (Pi 5 + HyperPixel square display + beam
  splitter cube), py5 sketches, and STL files. This repo began as a clone of it
  and keeps its full commit history and MIT license.
- **[Open-LLM-VTuber](https://github.com/t41372/Open-LLM-VTuber)** by Yi-Ting
  Chiu (MIT) — the Live2D avatar runtime (rendering, LLM/STT/TTS pipeline,
  expression system) that the hologram displays. Not vendored here: it runs as
  a separate install at `~/Open-LLM-VTuber` that this project's scripts drive
  over CDP/HTTP and configure. Live2D itself is subject to the
  [Live2D license](https://www.live2d.com/en/terms/live2d-open-software-license-agreement/).

**No Live2D models are distributed in this repo.** Models live in the local
Open-LLM-VTuber install (`live2d-models/`) and each carries its own license —
use the sample models Open-LLM-VTuber ships with, or install your own via the
web UI's *Add model*. Third-party models must not be committed here.

## What's here

- `scripts/live2d_ghost.sh` — kiosk launcher (mirrored display, ghost look, autostart)
- `scripts/gesture_ctl.py` — camera sidecar: face tracking + remappable finger-count gestures
- `webui/` — Hologram Studio web UI on `:8800` (see `README-Gestures.md`)
- `scripts/add_model.py`, `scan_expressions.py` — model install + expression registration
- `README-Live2D.md`, `README-Gestures.md` — full documentation

The original OpenGhost documentation follows.

---

# OpenGhost

This is the repository for OpenGhost, an open-source Pepper's Ghost display that uses a Raspberry Pi 5 with a camera, square screen, and a beam splitter cube as the transparent reflector, which sits on top of the screen. Additional peripherals, such as microphones, speakers, etc., can be added for some more interactivity via the USB ports.

OpenGhost intends to be a futuristic and aesthetic display medium that can run all sorts of visual and interactive programs, so feel free to get creative by adding your own scripts or modifying the hardware/designs!

| ![Lorenz Attractor on 50 mm](assets/open_ghost_50_mm.jpg) | ![Lorenz Attractor on 70 mm](assets/open_ghost_70_mm.jpg) |
| --- | --- |
| 50 mm beam splitter cube | 70 mm beam splitter cube |

## Setup And Installation

### Hardware
- Raspberry Pi 5 (other versions should work, but the software installation may differ) + SD card
- [HyperPixel 4.0 Square - Hi-Res Display for Raspberry Pi (touchscreen version)](https://shop.pimoroni.com/products/hyperpixel-4-square?variant=30138251444307). Any 4-inch square screen that can attach to the Raspberry Pi 5 pins should work as well
- [70 mm beam splitter cube](https://www.aliexpress.com/item/1005005127247262.html?spm=a2g0o.order_list.order_list_main.17.2d60180247Uidc) or [50 mm beam splitter cube](https://www.aliexpress.com/item/1005006772844723.html?spm=a2g0o.order_list.order_list_main.5.2d60180247Uidc) (I got them off Aliexpress)
- 5V 5A USB-C power supply (5V 3A is suitable as well, but the former is recommended)
- 4x M2.5x14 mm screws
- 3D printed STL files in `/stl_files`
- Camera (optional). The one shown is the [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/)

### Software

I'm using the Python library [py5](https://py5coding.org/index.html) to display graphics. If you are planning to do the same, follow these instructions:

- Install Raspberry Pi OS Bookworm (uses Python 3.11)
- Enable the square display on the Pi by following [these instructions](https://shop.pimoroni.com/products/hyperpixel-4-square?variant=30138251444307). If you used a different display, follow the manufacturer's instructions to enable it
- Install a virtual environment with system site packages `python -m venv .venv --system-site-packages`
- Install Java headless using `sudo apt update && sudo apt install default-jdk`
- Install py5 using `pip install py5` (requires Java)
- Clone this repo

#### If The Camera Is Being Used
- Downgrade numpy to `numpy==1.26.4` (any numpy version less than 2.0)
- Install dependency `sudo apt install libcap-dev`
- Install picamera2 using `pip install picamera2`
- Install libcamera `sudo apt install libcamera-apps python3-libcamera python3-picamera2`


## How To Run Programs
- Open a terminal and activate the virtual environment
- Run `export DISPLAY=:0.0` if the terminal session is new
- Run the desired Python file

## Video Demos
https://github.com/user-attachments/assets/3b03c9a8-5584-4b67-a87c-34f891654d6c

https://github.com/user-attachments/assets/0c3369e9-3200-40ce-94e5-a6c8e77574fc
