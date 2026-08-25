# stage3d — head-coupled 3D spinoff

A self-contained experiment, separate from the Live2D avatar: a real 3D scene
(Three.js) rendered with **off-axis projection** driven by the Pi camera's face
tracking. The screen plane is the fixed "window"; the virtual camera sits
wherever your tracked face is, so objects inside the cube show true motion
parallax — the depth cue a flat Live2D model can't produce. Works for one
viewer at a time (the tracked face).

## Setup

```bash
stage3d/get_vendor.sh            # fetch three.js + three-vrm (not committed)
stage3d/get_vendor.sh --sample   # …plus pixiv's MIT sample VRM avatar
stage3d/stage.sh show            # put the 3D stage on the cube
stage3d/stage.sh hide            # back to the Live2D avatar
```

The gesture sidecar must be running (`scripts/gesture_ctl.sh start`) — it
publishes the tracked face to `/dev/shm/openghost_face.json` at ~5 Hz, which
this page polls. No second camera consumer, no CDP involved.

With no model dropped in you get a test scene (wireframe room + cubes at
staggered depths) — the best way to verify the parallax before any avatar.

## Models

Drop `.vrm` / `.glb` / `.gltf` files into `stage3d/models/` (gitignored, never
committed — same rule as the Live2D models). The first one auto-loads;
`?model=name` in the URL picks a specific one.

**VRM** is the format to want: VRoid Hub / Booth avatars load directly, the
eyes automatically follow your tracked face, spring bones (hair/skirt) react
to the idle sway, and auto-blink works. **VRChat avatars are Unity assets and
can't be loaded directly** (and ripping them violates VRChat's ToS) — but many
of the same avatars are distributed as VRM, and VRoid Studio exports VRM.

## Calibration (`calib.json`, applies live within ~2 s)

| knob | meaning |
|---|---|
| `screen_mm` | physical size of the square screen (HyperPixel 4 Sq ≈ 72) |
| `cam_hfov_deg`/`cam_vfov_deg` | camera field of view (Module 3: 66/41) |
| `cam_offset_mm` | camera position relative to the screen centre |
| `ref_face_w` | normalised face width at your normal standing spot (read it from `gesture_ctl.sh debug` or the `?debug=1` overlay) |
| `ref_dist_mm` | your actual distance at that spot |
| `invert_x`/`invert_y` | flip the parallax sense — the mirrored display makes signs a coin flip, so calibrate: step **right** → you should see more of the scene's **left wall**, like a real window. If it moves with you, flip. |
| `ease` | smoothing (lower = smoother/laggier) |
| `depth_mm` | how far behind the window plane the model stands |
| `model_fit` | model height as a fraction of the screen |

Edit via `curl -X POST localhost:8801/api/calib -d '{"invert_x": true}'` or the
file directly. Debug overlay: `http://<pi>:8801/?debug=1` (or press `d` on a
keyboard) shows fps, raw face data, and the eased eye position.
`window.__forceEye = {x:200,y:0,z:500}` in the console pins the viewpoint for
testing; `= null` releases it.
