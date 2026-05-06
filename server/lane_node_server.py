#!/usr/bin/env python3
"""WSL-SRV-side WebSocket + HTTP. Now with desk-app-simulator endpoints."""

import asyncio
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, '/home/pi/wsl-lane-nodes')
from wsl_scoring_engine import LaneScoring

from websockets.asyncio.server import serve

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('server')

state_lock = threading.Lock()
lane_scoring = {}
ball_counters = {}
clients = {}
main_loop = None

def get_or_create_lane(lane_id, bowlers=None):
    if lane_id not in lane_scoring:
        ls = LaneScoring(lane_id)
        for i, name in enumerate(bowlers or ['TEST']):
            ls.add_bowler(name, number=i+1, hdcp=0)
        ls.is_active = True
        lane_scoring[lane_id] = ls
        log.info(f"Lane {lane_id}: created with bowlers {[b.name for b in ls.bowlers]}")
    return lane_scoring[lane_id]

PIN_MASK_CYCLE = [0b0000011111, 0, 0, 0b0001111111, 0b0000001111, 0]

# Bump this whenever a message type's shape changes incompatibly.
# Compared against the node's PROTOCOL_VERSION on HELLO; mismatch logs
# a warning but does NOT reject the connection (we'd rather degrade
# than refuse, since the alternative is a silently-broken pinsetter).
# v1 = single-lane (HELLO carries `lane`); v2 = multi-lane (HELLO carries `lanes`).
PROTOCOL_VERSION = 2

class Msg:
    HELLO = "hello"
    BALL_EVENT = "ball_event"
    HEARTBEAT = "heartbeat"
    CYCLE = "cycle"
    OPEN_LANE = "open_lane"
    CLOSE_LANE = "close_lane"
    RESET = "reset"
    POWER_ON = "power_on"
    POWER_OFF = "power_off"

def encode(t, **f): return json.dumps({"type": t, "ts": time.time(), **f})
def decode(r): return json.loads(r)

async def handle_node(websocket):
    addr = websocket.remote_address
    log.info(f"New connection from {addr}")
    node_id = None
    try:
        async for raw in websocket:
            msg = decode(raw)
            mt = msg.get("type")

            if mt == Msg.HELLO:
                node_id = msg.get("node", "<unknown>")
                clients[node_id] = websocket
                node_version = msg.get("protocol_version")
                node_lanes = msg.get("lanes") or (
                    [msg["lane"]] if "lane" in msg else []
                )
                if node_version != PROTOCOL_VERSION:
                    log.warning(
                        f"Node {node_id!r} protocol version mismatch: "
                        f"node={node_version}, server={PROTOCOL_VERSION}. "
                        f"Continuing — message handling may degrade."
                    )
                log.info(f"Node {node_id!r} registered "
                         f"(lanes={node_lanes}, protocol_version={node_version})")

            elif mt == Msg.BALL_EVENT:
                lane = msg.get("lane")
                with state_lock:
                    ls = get_or_create_lane(lane)
                    n = ball_counters.get(lane, 0)
                    pin_mask = PIN_MASK_CYCLE[n % len(PIN_MASK_CYCLE)]
                    ball_counters[lane] = n + 1
                    bowl = ls.record_ball(pin_mask)
                if bowl:
                    pd = 10 - bin(pin_mask).count("1")
                    log.info(f"Lane {lane}: {ls.current_bowler.name if ls.current_bowler else '?'}"
                             f" → {bowl.display} ({pd} pins)")
                await websocket.send(encode(Msg.CYCLE, lane=lane))

            elif mt == Msg.HEARTBEAT:
                pass
    except Exception as e:
        log.warning(f"Handler error: {e}")
    finally:
        if node_id and clients.get(node_id) is websocket:
            del clients[node_id]
            log.info(f"Node {node_id!r} disconnected")

def send_to_all_nodes(msg_str):
    """Schedule a send on the asyncio loop from the HTTP handler thread."""
    sent = 0
    for node_id, ws in list(clients.items()):
        try:
            fut = asyncio.run_coroutine_threadsafe(ws.send(msg_str), main_loop)
            fut.result(timeout=2)
            sent += 1
        except Exception as e:
            log.warning(f"send_to {node_id} failed: {e}")
    return sent

# ============================================================
# HTML DISPLAY + DESK SIMULATOR
# ============================================================
DISPLAY_HTML = """<!doctype html>
<html><head><title>Lane Display</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif;
         background: #0a0a0a; color: #f0f0f0; padding: 1.5em; margin: 0; }
  h1 { color: #888; font-weight: 300; font-size: 1.1em; margin: 0 0 1em 0; }
  .controls { background: #1a1a1a; border-radius: 12px; padding: 1em;
              margin-bottom: 1em; display: flex; gap: 0.6em; align-items: center; }
  .controls label { color: #888; font-size: 0.9em; }
  .controls button { background: #2a2a2a; color: #f0f0f0; border: 1px solid #444;
                     padding: 0.5em 1em; border-radius: 6px; cursor: pointer;
                     font-size: 0.9em; }
  .controls button:hover { background: #3a3a3a; }
  .controls button.open { border-color: #2d6a3e; color: #b8e8c5; }
  .controls button.close { border-color: #6a2d2d; color: #e8b8b8; }
  .controls button.reset { border-color: #6a5b2d; color: #e8d8b8; }
  .controls button.power-on { border-color: #2d5a6a; color: #b8d8e8; }
  .controls button.power-off { border-color: #4a4a4a; color: #aaa; }
  .lane { background: #1a1a1a; border-radius: 12px; padding: 1.2em; margin: 1em 0; }
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
  .frame .pts { color: #aaa; font-size: 0.85em; }
  .frame.strike { background: #2d6a3e; }
  .frame.spare  { background: #2d4a6a; }
  .stats { display: flex; gap: 1em; color: #888; font-size: 0.85em; margin-top: 0.6em; }
  .empty { color: #555; padding: 2em; text-align: center; }
  .toast { position: fixed; bottom: 1em; right: 1em; background: #2d6a3e;
           padding: 0.8em 1.2em; border-radius: 8px; color: #fff;
           opacity: 0; transition: opacity 0.2s; }
  .toast.show { opacity: 1; }
</style>
<script>
async function action(lane, op) {
  const r = await fetch(`/api/lane/${lane}/${op}`, { method: 'POST' });
  const data = await r.json();
  toast(`${op.toUpperCase()} sent to lane ${lane} (${data.sent_to} node${data.sent_to===1?'':'s'})`);
  refresh();
}
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1500);
}
async function refresh() {
  try {
    const r = await fetch('/api/state');
    const data = await r.json();
    const root = document.getElementById('lanes');
    if (Object.keys(data).length === 0) {
      root.innerHTML = '<div class="empty">No lane events yet — press the button on the Pi or click Open Lane</div>';
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
          return `<div class="frame ${cls}"><div class="num">${f.frame}</div>
                  <div class="bowls">${bowlsStr || '·'}</div>
                  <div class="pts">${f.points || 0}</div></div>`;
        }).join('');
        return `<div class="bowler"><div class="bowler-row">
                  <span class="bowler-name">${p.name}</span>
                  <span class="bowler-total">${p.current_total || 0}</span></div>
                <div class="frames">${framesHtml}</div></div>`;
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
        </div>`;
      root.appendChild(div);
    }
  } catch (e) { console.error(e); }
}
setInterval(refresh, 500);
window.addEventListener('load', refresh);
</script>
</head>
<body>
  <h1>WSL Lane Node Display — desk simulator + live scoring</h1>
  <div class="controls">
    <label>Lane 21:</label>
    <button class="open" onclick="action(21, 'open')">Open Lane</button>
    <button class="close" onclick="action(21, 'close')">Close Lane</button>
    <button class="reset" onclick="action(21, 'reset')">Reset Pins</button>
    <button class="power-on" onclick="action(21, 'power-on')">Power On</button>
    <button class="power-off" onclick="action(21, 'power-off')">Power Off</button>
  </div>
  <div class="controls">
    <label>Lane 22:</label>
    <button class="open" onclick="action(22, 'open')">Open Lane</button>
    <button class="close" onclick="action(22, 'close')">Close Lane</button>
    <button class="reset" onclick="action(22, 'reset')">Reset Pins</button>
    <button class="power-on" onclick="action(22, 'power-on')">Power On</button>
    <button class="power-off" onclick="action(22, 'power-off')">Power Off</button>
  </div>
  <div id="lanes" class="empty">Loading...</div>
  <div id="toast" class="toast"></div>
</body></html>
"""

class HttpHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self._send(200, 'text/html; charset=utf-8', DISPLAY_HTML.encode('utf-8'))
        elif self.path == '/api/state':
            with state_lock:
                snap = {str(l): ls.to_scoring_response() for l, ls in lane_scoring.items()}
            self._send(200, 'application/json', json.dumps(snap).encode('utf-8'))
        else:
            self._send(404, 'text/plain', b'Not found')

    def do_POST(self):
        # /api/lane/{N}/{open|close|reset}
        parts = self.path.strip('/').split('/')
        if len(parts) == 4 and parts[0] == 'api' and parts[1] == 'lane':
            try:
                lane = int(parts[2])
                action = parts[3]
            except ValueError:
                return self._send(400, 'application/json', b'{"error":"bad lane"}')

            type_map = {
                'open': Msg.OPEN_LANE,
                'close': Msg.CLOSE_LANE,
                'reset': Msg.RESET,
                'power-on': Msg.POWER_ON,
                'power-off': Msg.POWER_OFF,
            }
            msg_type = type_map.get(action)
            if not msg_type:
                return self._send(400, 'application/json', b'{"error":"bad action"}')

            # If opening, reset the scoring state
            if msg_type == Msg.OPEN_LANE:
                with state_lock:
                    lane_scoring.pop(lane, None)
                    ball_counters.pop(lane, None)
                    get_or_create_lane(lane, bowlers=['ALICE', 'BOB'])
                log.info(f"OPEN_LANE: reset scoring for lane {lane} with new bowlers")

            msg = encode(msg_type, lane=lane)
            sent = send_to_all_nodes(msg)
            log.info(f"→ {action.upper()} lane {lane} sent to {sent} node(s)")
            self._send(200, 'application/json',
                       json.dumps({"sent_to": sent, "msg": json.loads(msg)}).encode('utf-8'))
        else:
            self._send(404, 'application/json', b'{"error":"not found"}')

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass

def http_thread():
    HTTPServer(('0.0.0.0', 8766), HttpHandler).serve_forever()

async def main():
    global main_loop
    main_loop = asyncio.get_running_loop()
    threading.Thread(target=http_thread, daemon=True).start()
    log.info("HTTP display + desk simulator: http://0.0.0.0:8766")
    log.info("WebSocket: ws://0.0.0.0:8765")
    async with serve(handle_node, "0.0.0.0", 8765):
        await asyncio.Future()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
