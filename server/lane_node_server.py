#!/usr/bin/env python3
"""WSL-SRV-side WebSocket server + tiny HTTP display.

NOW USING THE REAL wsl_scoring_engine.LaneScoring — same code path that
runs on WSL-SRV in production, just driven by Pi GPIO events instead of
the BPP_LANE poller.
"""

import asyncio
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# Add project root so we can import wsl_scoring_engine
sys.path.insert(0, '/home/pi/wsl-lane-nodes')
from wsl_scoring_engine import LaneScoring

from websockets.asyncio.server import serve

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('server')

# ============================================================
# SCORING STATE — one LaneScoring per lane, accessed under lock
# ============================================================
state_lock = threading.Lock()
lane_scoring = {}  # lane_id (int) → LaneScoring

def get_or_create_lane(lane_id):
    """Returns the LaneScoring for this lane, creating a default one if needed."""
    if lane_id not in lane_scoring:
        ls = LaneScoring(lane_id)
        ls.add_bowler('TEST', number=1, hdcp=0)
        ls.is_active = True
        lane_scoring[lane_id] = ls
        log.info(f"Lane {lane_id}: created scoring state with default bowler 'TEST'")
    return lane_scoring[lane_id]

# Cycle through pin_masks to make the demo interesting
PIN_MASK_CYCLE = [
    0b0000011111,  # 5 pins still standing (5 down)
    0,             # all down (spare on second ball, strike on first)
    0,             # all down again
    0b0001111111,  # 7 standing (3 down)
    0b0000001111,  # 4 standing (3 more down)
    0,             # all down (spare)
]

# ============================================================
# PROTOCOL
# ============================================================
class Msg:
    HELLO = "hello"
    BALL_EVENT = "ball_event"
    HEARTBEAT = "heartbeat"
    CYCLE = "cycle"

def encode(msg_type, **fields):
    return json.dumps({"type": msg_type, "ts": time.time(), **fields})

def decode(raw):
    return json.loads(raw)

# ============================================================
# WEBSOCKET HANDLER
# ============================================================
clients = {}
ball_counters = {}  # lane_id → int, used to index PIN_MASK_CYCLE

async def handle_node(websocket):
    addr = websocket.remote_address
    log.info(f"New connection from {addr}")
    node_id = None
    try:
        async for raw in websocket:
            msg = decode(raw)
            msg_type = msg.get("type")

            if msg_type == Msg.HELLO:
                node_id = msg.get("node", "<unknown>")
                clients[node_id] = websocket
                log.info(f"Node {node_id!r} registered")

            elif msg_type == Msg.BALL_EVENT:
                lane = msg.get("lane")
                with state_lock:
                    ls = get_or_create_lane(lane)
                    n = ball_counters.get(lane, 0)
                    pin_mask = PIN_MASK_CYCLE[n % len(PIN_MASK_CYCLE)]
                    ball_counters[lane] = n + 1
                    bowl = ls.record_ball(pin_mask)

                if bowl:
                    pins_down = 10 - bin(pin_mask).count("1")
                    log.info(f"Lane {lane}: {ls.current_bowler.name if ls.current_bowler else '?'} "
                             f"→ {bowl.display} ({pins_down} pins down)")
                else:
                    log.info(f"Lane {lane}: ball not recorded (game over?)")

                await websocket.send(encode(Msg.CYCLE, lane=lane))

            elif msg_type == Msg.HEARTBEAT:
                pass

    except Exception as e:
        log.warning(f"Handler error: {e}")
    finally:
        if node_id and clients.get(node_id) is websocket:
            del clients[node_id]
            log.info(f"Node {node_id!r} disconnected")

# ============================================================
# HTTP DISPLAY
# ============================================================
DISPLAY_HTML = """<!doctype html>
<html><head><title>Lane Score Display</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif;
         background: #0a0a0a; color: #f0f0f0; padding: 1.5em; margin: 0; }
  h1 { color: #888; font-weight: 300; font-size: 1.1em; margin: 0 0 1em 0; }
  .lane { background: #1a1a1a; border-radius: 12px; padding: 1.2em; margin: 1em 0;
          box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
  .lane-header { display: flex; justify-content: space-between; align-items: baseline;
                 margin-bottom: 0.8em; }
  .lane-num { color: #ffce42; font-size: 1.5em; font-weight: 700; }
  .lane-meta { color: #888; font-size: 0.85em; }
  .bowler { padding: 0.8em 0; border-top: 1px solid #2a2a2a; }
  .bowler-row { display: flex; justify-content: space-between; align-items: center;
                margin-bottom: 0.5em; }
  .bowler-name { font-size: 1.2em; font-weight: 600; }
  .bowler-total { font-size: 2.5em; font-weight: 800; color: #fff; line-height: 1; }
  .frames { display: flex; gap: 0.3em; flex-wrap: wrap; }
  .frame { background: #2a2a2a; border-radius: 6px; padding: 0.4em 0.6em;
           min-width: 3.2em; text-align: center; font-family: ui-monospace, Menlo, monospace; }
  .frame .num { color: #555; font-size: 0.7em; }
  .frame .bowls { font-size: 1.1em; font-weight: 600; }
  .frame .pts { color: #aaa; font-size: 0.85em; margin-top: 0.1em; }
  .frame.strike { background: #2d6a3e; }
  .frame.spare  { background: #2d4a6a; }
  .stats { display: flex; gap: 1em; color: #888; font-size: 0.85em; margin-top: 0.6em; }
  .empty { color: #555; padding: 2em; text-align: center; }
</style>
<script>
async function refresh() {
  try {
    const r = await fetch('/api/state');
    const data = await r.json();
    const root = document.getElementById('lanes');
    if (Object.keys(data).length === 0) {
      root.innerHTML = '<div class="empty">No lane events yet — press the button on the Pi</div>';
      return;
    }
    root.innerHTML = '';
    for (const [lane, scoring] of Object.entries(data)) {
      const div = document.createElement('div');
      div.className = 'lane';
      const players = scoring.players || [];
      const playersHtml = players.map(p => {
        const framesHtml = (p.frames || []).map(f => {
          const isStrike = (f.bowls || []).some(b => b.display === 'X');
          const isSpare = (f.bowls || []).some(b => b.display === '/');
          const cls = isStrike ? 'strike' : (isSpare ? 'spare' : '');
          const bowlsStr = (f.bowls || []).map(b => b.display).join(' ');
          return `<div class="frame ${cls}">
                    <div class="num">${f.frame}</div>
                    <div class="bowls">${bowlsStr || '·'}</div>
                    <div class="pts">${f.points || 0}</div>
                  </div>`;
        }).join('');
        return `<div class="bowler">
                  <div class="bowler-row">
                    <span class="bowler-name">${p.name}</span>
                    <span class="bowler-total">${p.current_total || 0}</span>
                  </div>
                  <div class="frames">${framesHtml}</div>
                </div>`;
      }).join('');
      const stats = scoring.stats || {};
      div.innerHTML = `
        <div class="lane-header">
          <span class="lane-num">Lane ${lane}</span>
          <span class="lane-meta">Game ${scoring.game || 1}</span>
        </div>
        ${playersHtml}
        <div class="stats">
          <span>Strikes: ${stats.strikes || 0}</span>
          <span>Spares: ${stats.spares || 0}</span>
          <span>Gutters: ${stats.gutters || 0}</span>
        </div>
      `;
      root.appendChild(div);
    }
  } catch (e) {
    console.error(e);
  }
}
setInterval(refresh, 500);
refresh();
</script>
</head>
<body>
  <h1>WSL Lane Node Display — driven by wsl_scoring_engine.LaneScoring</h1>
  <div id="lanes" class="empty">Loading...</div>
</body></html>
"""

class HttpHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(DISPLAY_HTML.encode('utf-8'))
        elif self.path == '/api/state':
            with state_lock:
                snapshot = {
                    str(lane): ls.to_scoring_response()
                    for lane, ls in lane_scoring.items()
                }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(snapshot).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass

def http_thread():
    HTTPServer(('0.0.0.0', 8766), HttpHandler).serve_forever()

# ============================================================
# MAIN
# ============================================================
async def main():
    threading.Thread(target=http_thread, daemon=True).start()
    log.info("HTTP display: http://0.0.0.0:8766")
    log.info("WebSocket:    ws://0.0.0.0:8765")
    async with serve(handle_node, "0.0.0.0", 8765):
        await asyncio.Future()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
