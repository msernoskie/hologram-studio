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
IDLE_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "idle.json")


def idle_cfg_js():
    """JS that pushes scripts/idle.json into the page (IDLE_JS reads it live).
    Missing/bad file -> empty object, and IDLE_JS's defaults take over."""
    try:
        with open(IDLE_CFG, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        cfg = {}
    return "window.__ghostIdleCfg=%s;'ok'" % json.dumps(cfg)


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
# Plus a PART-MOTION engine: a list of idle motions (torso bounce, head nod,
# breath pulse, ...) that each fire in bursts of N quick |sin| pulses — N picked
# at random per burst from the motion's list — at a random interval, whenever
# she isn't talking (including while gaze-following a face). Position never
# moves: each motion drives Live2D PARAMETERS, injected immediately before the
# core commit (this._model.update() at the end of LAppModel.update() — any
# later and they never render; learned the hard way). Params are addressed by
# NAME and resolved to indices per model, so parts a model lacks are silent
# no-ops and the same config works on every model.
#
# Configured by window.__ghostIdleCfg (from scripts/idle.json, pushed at launch
# below and live-edited by the web UI's "Idle motions" tab):
#   idle:false  = no figure-8 sway and no part motions (gaze unaffected)
#   motions: [{on, part, amp 0..1, len s/pulse, bursts [ints], min_gap, max_gap}]
IDLE_JS = """(()=>{
  if(typeof getLive2DManager!=="function") return "no-manager";
  if(window.__ghostIdleRAF) cancelAnimationFrame(window.__ghostIdleRAF);
  const mgr=getLive2DManager();
  const t0=performance.now();
  // Part presets: [param name, signed fraction of that param's range at amp=1].
  // Values scale to each param's own min/max, so one amp slider behaves the
  // same across angle params (±30) and 0..1 params like ParamBreath. Names a
  // model doesn't have simply resolve to no index and are skipped.
  const PARTS={
    torso:[["ParamBodyAngleY0",-0.5],["ParamBodyAngleY",-0.5],
           ["ParamChestAngleY",-0.35],["ParamShoulderAngleY",-0.3]],
    head:[["ParamAngleY",0.4]],
    chest:[["ParamChestAngleY",-0.5],["ParamBreath",0.35]],
    shoulders:[["ParamShoulderAngleY",-0.55]],
    breath:[["ParamBreath",0.9]],
    sway:[["ParamBodyAngleZ0",0.4],["ParamBodyAngleZ",0.4],["ParamAngleZ",0.15]],
    hips:[["ParamHipAngleZ0",0.5]]
  };
  function tick(now){
    let md=null; try{md=mgr._models.at(0);}catch(e){}
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
      }
      const IC=window.__ghostIdleCfg||{};
      const idleOn=IC.idle!==false;
      const talking=(md._lastLipSyncValue||0)>0.03;     // conversation in progress
      if(md._dragManager){
        const gz=window.__ghostGaze;                    // fresh = a hand is on screen
        if(gz&&now-gz.t<600){
          md._dragManager.set(gz.x,gz.y);               // look at it, beats idle
        } else if(!talking&&idleOn){
          const t=(now-t0)/1000;
          const x=0.38*Math.sin(t*0.9)+0.10*Math.sin(t*0.33); // slow horizontal sway
          const y=0.16*Math.sin(t*1.7)+0.06*Math.sin(t*0.5);  // subtler vertical bob
          md._dragManager.set(x,y);
        } else if(!talking){
          md._dragManager.set(0,0);              // idle animation off: rest centred
        }
      }
      // Part-motion engine. The rAF runs each motion's burst state machine and
      // publishes this frame's parameter adds; the pre-commit wrapper below
      // applies them. One state per motion index, re-armed a moment after any
      // interruption (talking / toggled off mid-burst).
      if(!window.__ghostMotion) window.__ghostMotion={st:{},adds:[]};
      const M=window.__ghostMotion;
      M.adds=[];
      const motions=(idleOn&&!talking)?(IC.motions||[]):[];
      motions.forEach((mo,i)=>{
        if(mo.on===false||!PARTS[mo.part]) return;
        let s=M.st[i]; if(!s) s=M.st[i]={next:now+1500+Math.random()*2500,n:0,start:0};
        const len=Math.max(0.15,mo.len||0.35);       // seconds per pulse
        if(s.n===0&&now>=s.next){
          const bs=(Array.isArray(mo.bursts)&&mo.bursts.length)?mo.bursts:[1,3];
          s.n=bs[Math.floor(Math.random()*bs.length)];
          s.start=now;
        }
        if(s.n>0){
          const el=(now-s.start)/1000;
          if(el>=s.n*len){
            s.n=0;
            const g0=mo.min_gap??4, g1=mo.max_gap??9;
            s.next=now+(g0+Math.random()*Math.max(0,g1-g0))*1000;
          } else {
            const env=Math.abs(Math.sin(el/len*Math.PI))*(mo.amp??0.5);
            PARTS[mo.part].forEach(pe=>M.adds.push([pe[0],env*pe[1]]));
          }
        }
      });
      // Pre-commit wrapper: parameter adds must land immediately BEFORE the
      // core commit (this._model.update(), the last call in LAppModel.update)
      // — any later and the next loadParameters() wipes them unrendered.
      // Params resolved name->index per model instance (cached, with each
      // param's range so add fractions scale correctly); unknown names skip.
      const cm=md._model;
      if(cm&&cm.update&&!cm.__ghostMotionWrap){
        cm.__ghostMotionWrap=true;
        const orig=cm.update.bind(cm);
        const cache={};
        cm.update=function(){
          const M=window.__ghostMotion;
          if(M&&M.adds.length){
            for(const a of M.adds){try{
              let e=cache[a[0]];
              if(e===undefined){
                e=null;
                const n=cm.getParameterCount();
                for(let j=0;j<n;j++){
                  const s=cm.getParameterId(j).getString();
                  if(String(s.s!==undefined?s.s:s)===a[0]){
                    e={ix:j,mx:Math.max(Math.abs(cm.getParameterMaximumValue(j)),
                                        Math.abs(cm.getParameterMinimumValue(j)))||1};
                    break;
                  }
                }
                cache[a[0]]=e;
              }
              if(e) cm.addParameterValueByIndex(e.ix,a[1]*e.mx);
            }catch(err){}}
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
                evaluate(ws, idle_cfg_js())
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
