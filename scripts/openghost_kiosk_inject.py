#!/usr/bin/env python3
"""Post-launch tuning for the OpenGhost Live2D kiosk, applied over the Chrome
DevTools Protocol (the kiosk runs with --remote-debugging-port=9222).

It waits for the Live2D canvas to exist, then:
  1. Enables hands-free mic auto-start (persists in the kiosk profile's localStorage).
  2. Injects CSS that blacks out the page and hides all UI except the model,
     and hides the mouse cursor — i.e. the Pepper's Ghost look.

Re-run safe (idempotent). CSS injection must run every launch (not persisted);
the localStorage flags persist across reboots but are set here anyway.
"""
import json, os, re, time, urllib.request
from websocket import create_connection

DBG = "http://localhost:9222"
CONF = os.path.expanduser("~/Open-LLM-VTuber/conf.yaml")
FRAMING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "framing.json")


def current_model():
    """Active live2d_model_name from conf.yaml."""
    try:
        m = re.search(r"live2d_model_name:\s*'([^']*)'", open(CONF, encoding="utf-8").read())
        return m.group(1) if m else None
    except Exception:
        return None


def saved_frame():
    """Persisted {scale,x,y} framing for the active model, or None."""
    try:
        data = json.load(open(FRAMING, encoding="utf-8"))
        return data.get(current_model())
    except Exception:
        return None

GHOST_CSS = (
    "html,body,#root{background:#000!important}"
    "#root>*:not(:has(#canvas)){display:none!important}"  # hide UI overlay, keep model stage
    "*{cursor:none!important}"                              # hide mouse cursor
)

SETUP_JS = """(()=>{
  // Hands-free: auto-start mic on load and re-arm after each reply.
  localStorage.setItem("autoStartMicOn","true");
  localStorage.setItem("autoStartMicOnConvEnd","true");
  let s=document.getElementById("openghost-style");
  if(!s){s=document.createElement("style");s.id="openghost-style";document.head.appendChild(s);}
  s.textContent=%s;
  return !!document.querySelector("#canvas");
})()""" % json.dumps(GHOST_CSS)

# Cute idle: when NOT talking, gently drive the model's look-point in a slow
# figure-8. The Cubism rig turns head/body/eyes toward it (with physics, so hair
# and accessories follow) -> a soft alive bob. Works for models with no baked
# motions (e.g. goth_mofu). Pauses while _lastLipSyncValue shows she's speaking,
# so it never fights lip-sync during a conversation. Idempotent (cancels prior loop).
#
# Also hosts the head-coupled parallax ("portalgraph") consumer: gesture_ctl.py
# publishes window.__ghostView = {x,y,z,cfg,t} (viewer degrees off the camera
# axis + tuning) at ~14Hz; this loop eases it at 60fps and applies
#   - translation/dolly to the model MATRIX only (never __ghostFrame, which is
#     the persisted framing truth — so parallax can't leak into framing.json)
#   - counter-rotation via post-update parameter adds (a wrapper on md.update),
#     cancelling the dragManager's head/body drive and replacing it with the
#     opposite-of-viewer angle, while the EYES keep following you (eye contact)
# A blend factor b eases the whole effect in/out on data freshness, so no-face,
# peace-sign gaze, and parallax-off all melt back to stock behavior.
IDLE_JS = """(()=>{
  if(typeof getLive2DManager!=="function") return "no-manager";
  if(window.__ghostIdleRAF) cancelAnimationFrame(window.__ghostIdleRAF);
  const mgr=getLive2DManager();
  const t0=performance.now();
  function tick(now){
    let md=null; try{md=mgr._models.at(0);}catch(e){}
    // Eased parallax state (shared with the update-wrapper below).
    if(!window.__ghostPar) window.__ghostPar={x:0,y:0,z:0,b:0,cfg:null};
    const P=window.__ghostPar, gv=window.__ghostView;
    const pfresh=!!(gv&&now-gv.t<600);
    if(pfresh) P.cfg=gv.cfg;
    const pk=(P.cfg&&P.cfg.k)||0.25;
    P.b+=((pfresh?1:0)-P.b)*pk;
    P.x+=((pfresh?gv.x:0)-P.x)*pk;
    P.y+=((pfresh?gv.y:0)-P.y)*pk;
    P.z+=((pfresh?gv.z:0)-P.z)*pk;
    if(md){
      // Persisted framing (scale/pos): enforced every frame so it survives the
      // frontend's own layout and never drifts. window.__ghostFrame is the source
      // of truth, set by the inject script + live-edited by the frame nudge scripts.
      if(md._modelMatrix){
        const m=md._modelMatrix._tr;
        if(!window.__ghostFrame) window.__ghostFrame={scale:m[0],x:m[12],y:m[13]};
        // Gesture drag/zoom: ease __ghostFrame toward a FRESH target published by
        // gesture_ctl.py. Easing here (60fps) instead of at the sender's ~15fps is
        // what makes a hand-drag look smooth. Targets older than 500ms are ignored,
        // so the frame nudge scripts (which set __ghostFrame directly) still win.
        const gt=window.__ghostFrameTarget;
        if(gt&&now-gt.t<500){
          const fr=window.__ghostFrame, k=0.3;
          fr.scale+=(gt.scale-fr.scale)*k; fr.x+=(gt.x-fr.x)*k; fr.y+=(gt.y-fr.y)*k;
        }
        const f=window.__ghostFrame;
        m[0]=f.scale; m[5]=f.scale; m[12]=f.x; m[13]=f.y;
        // Parallax translation/dolly ride on the matrix ONLY — f is untouched,
        // so persist()/steps/home-restore never absorb a viewer offset.
        // (m[1]/m[4] shear slots are free if a keystone term is ever wanted.)
        const pc=P.cfg;
        if(pc&&P.b>0.01){
          m[12]=f.x-P.x*pc.tg*P.b;
          m[13]=f.y-P.y*pc.tg*pc.ty*P.b;
          if(pc.dolly){const s=f.scale*(1+P.z*pc.dolly*P.b); m[0]=s; m[5]=s;}
        }
      }
      if(md._dragManager){
        const talking=(md._lastLipSyncValue||0)>0.03;   // conversation in progress
        const gz=window.__ghostGaze;                    // fresh = a hand is on screen
        if(gz&&now-gz.t<600){
          md._dragManager.set(gz.x,gz.y);               // look at the hand, beats idle
        } else if(!talking){
          const t=(now-t0)/1000;
          const x=0.38*Math.sin(t*0.9)+0.10*Math.sin(t*0.33); // slow horizontal sway
          const y=0.16*Math.sin(t*1.7)+0.06*Math.sin(t*0.5);  // subtler vertical bob
          md._dragManager.set(x,y);
        }
      }
      // Parallax rotation: wrap the CORE model's update() — the single call
      // that commits the parameter buffer to the renderer at the END of
      // LAppModel.update(). Adds must land immediately BEFORE that commit:
      // any later and they render never (next frame's loadParameters() wipes
      // them first — learned the hard way). Per-frame check (not a global
      // flag) so a model switch re-wraps the new instance automatically.
      // Cancels the dragManager's head/body drive (dx*30 etc. — the stock
      // multipliers) and substitutes the counter-rotation.
      const cm0=md._model;
      if(cm0&&cm0.update&&!cm0.__ghostParWrap){
        cm0.__ghostParWrap=true;
        const orig=cm0.update.bind(cm0);
        cm0.update=function(){
          const P=window.__ghostPar;
          if(P&&P.cfg&&P.b>=0.01){
            const c=P.cfg, dm=md._dragManager;
            const dx=dm?dm.getX():0, dy=dm?dm.getY():0;
            const lim=c.maxd||25;
            const yaw=Math.max(-lim,Math.min(lim,-P.x*c.rot));
            const pit=Math.max(-lim,Math.min(lim,-P.y*c.rot*c.ry));
            const add=(id,v)=>{try{cm0.addParameterValueById(id,v*P.b);}catch(e){}};
            add(md._idParamAngleX, yaw-dx*30);
            add(md._idParamAngleY, pit-dy*30);
            add(md._idParamAngleZ, yaw*pit*-0.033-dx*dy*-30);
            add(md._idParamBodyAngleX, yaw*c.body-dx*10);
            if(c.eyes){
              // Eye contact must survive the counter-rotation: the head just
              // turned yaw/pit degrees AWAY from the viewer, so the eyeballs
              // deflect the opposite way by the same angle (param 1 ~ 30 deg,
              // Cubism clamps to the model's range) — gaze stays ON the face.
              add(md._idParamEyeBallX, -yaw/30);
              add(md._idParamEyeBallY, -pit/30);
            }else{add(md._idParamEyeBallX,-dx);add(md._idParamEyeBallY,-dy);}
          }
          orig();
        };
      }
    }
    window.__ghostIdleRAF=requestAnimationFrame(tick);
  }
  window.__ghostIdleRAF=requestAnimationFrame(tick);
  return "idle-started";
})()"""


def page_ws():
    for t in json.load(urllib.request.urlopen(DBG + "/json")):
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    return None


def evaluate(ws, js):
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": js, "returnByValue": True, "awaitPromise": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 1:
            return m.get("result", {}).get("result", {}).get("value")


def nudge_pointer(ws):
    """Dispatch one real pointer move so Chromium applies `cursor:none`.

    On a mouse-less appliance the pointer never moves, so the browser's
    cursor:none never fires and the startup arrow lingers. A synthetic CDP
    move triggers it once; nothing brings the cursor back. (The transparent
    XCURSOR theme in ~/.config/labwc/environment is the compositor-level
    backstop; this handles the browser layer.)"""
    for i, (x, y) in enumerate(((360, 360), (5, 5)), start=100):
        ws.send(json.dumps({"id": i, "method": "Input.dispatchMouseEvent",
                            "params": {"type": "mouseMoved", "x": x, "y": y}}))
        while True:
            if json.loads(ws.recv()).get("id") == i:
                break


def main():
    # Wait for the debug endpoint + a page target (Chromium may still be starting).
    ws_url = None
    for _ in range(60):
        try:
            ws_url = page_ws()
            if ws_url:
                break
        except Exception:
            pass
        time.sleep(1)
    if not ws_url:
        print("[inject] no page target; is the kiosk running with --remote-debugging-port?")
        return

    ws = create_connection(ws_url, max_size=None)
    # Wait until the Live2D canvas has rendered, then apply setup.
    for _ in range(60):
        try:
            if evaluate(ws, SETUP_JS):
                nudge_pointer(ws)
                idle = evaluate(ws, IDLE_JS)
                frame = saved_frame()
                if frame:
                    evaluate(ws, "window.__ghostFrame=%s;'ok'" % json.dumps(frame))
                print(f"[inject] ghost look + mic + cursor-hide + idle:{idle}; framing:{frame or 'default'}")
                ws.close()
                return
        except Exception as e:
            print("[inject] retrying:", e)
        time.sleep(1)
    print("[inject] canvas never appeared; applied CSS anyway")
    ws.close()


if __name__ == "__main__":
    main()
