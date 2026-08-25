#!/usr/bin/env python3
"""Tiny Chrome DevTools Protocol client: evaluate JS in the first page target.
Usage: python cdp_eval.py '<javascript expression>'
Reads JS from argv[1] or stdin. Prints the JSON result value."""
import sys, json, urllib.request
from websocket import create_connection  # websocket-client (already installed)

DBG = "http://localhost:9222"

def page_ws():
    pages = [t for t in json.load(urllib.request.urlopen(DBG + "/json"))
             if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    # Prefer the OLV kiosk page — the stage3d spinoff may own a second tab
    for t in pages:
        if "12393" in t.get("url", ""):
            return t["webSocketDebuggerUrl"]
    if pages:
        return pages[0]["webSocketDebuggerUrl"]
    raise SystemExit("no page target found")

def main():
    js = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    ws = create_connection(page_ws(), max_size=None)
    ws.send(json.dumps({
        "id": 1, "method": "Runtime.evaluate",
        "params": {"expression": js, "returnByValue": True, "awaitPromise": True},
    }))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == 1:
            r = msg.get("result", {})
            if "exceptionDetails" in r:
                print("JS EXCEPTION:", json.dumps(r["exceptionDetails"])[:500])
            else:
                print(json.dumps(r.get("result", {}).get("value"), indent=2, ensure_ascii=False))
            break
    ws.close()

if __name__ == "__main__":
    main()
