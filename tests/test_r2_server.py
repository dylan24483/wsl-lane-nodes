"""test_r2_server.py — Codex round-2 server-side items (2026-07-21):
  R2-8  /api/health build identity (git hash + contract sha)
  R2-12 ingest ack reports identity-deduped duplicates
  R2-14 GS-vs-camera disagreement counter at cycle ingest

Bootstrap mirrors test_machine_diagnostics.py (websockets stubbed, throwaway
DBs, one loopback HTTP server). Run under pytest or standalone.
"""
import json
import logging
import os
import sys
import tempfile
import threading
import types
import urllib.request
from http.server import HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from websockets.asyncio.server import serve as _real_serve  # noqa: F401
except ModuleNotFoundError:
    _ws_server = types.ModuleType("websockets.asyncio.server")
    _ws_server.serve = None
    _ws_asyncio = types.ModuleType("websockets.asyncio")
    _ws_asyncio.server = _ws_server
    _ws_root = types.ModuleType("websockets")
    _ws_root.asyncio = _ws_asyncio
    sys.modules["websockets"] = _ws_root
    sys.modules["websockets.asyncio"] = _ws_asyncio
    sys.modules["websockets.asyncio.server"] = _ws_server

_TMP = tempfile.TemporaryDirectory()
os.environ.setdefault("STATE_DB_PATH", str(Path(_TMP.name) / "lane_state.db"))
os.environ.setdefault("MACHINE_DB_PATH",
                      str(Path(_TMP.name) / "machine_diag.db"))
os.environ.setdefault("WSL_MACHINE_LANES", "21,22")
os.environ.setdefault(
    "WSL_SCORING_NODE_TOPOLOGY", "test-pair-21-22=21,22")
os.environ.setdefault("WSL_ALLOW_UNAUTHENTICATED_BENCH", "1")
os.environ.pop("WSL_MACHINE_DIAG", None)

import machine_store  # noqa: E402
import lane_node_server as server  # noqa: E402

logging.getLogger('machine_store').setLevel(logging.CRITICAL)

_httpd = HTTPServer(('127.0.0.1', 0), server.HttpHandler)
PORT = _httpd.server_address[1]
threading.Thread(target=_httpd.serve_forever, daemon=True).start()


def http(method, path, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode('utf-8'))


def _fresh_db(name):
    machine_store.DB_PATH = Path(_TMP.name) / name
    machine_store.clear_state()


def test_health_carries_build_identity():
    status, body = http('GET', '/api/health')
    assert status == 200
    assert 'git_hash' in body
    build = body.get('build')
    assert isinstance(build, dict)
    assert 'contract_sha256' in build and 'started_at' in build
    # the contract sha matches the sidecar on disk
    sidecar = (SERVER_DIR / 'machine_contract.sha256') \
        .read_text(encoding='utf-8').split()[0].strip()
    assert build['contract_sha256'] == sidecar


def test_events_ack_reports_duplicates():
    _fresh_db("r2_dup.db")
    ev = {'lane_id': 21, 'severity': 'info', 'event_type': 'recovered',
          'source_id': 's1', 'boot_id': 'b1', 'seq': 1}
    status, body = http('POST', '/api/machine/events', [ev])
    assert status == 200
    assert body['inserted'] == 1 and body['duplicates'] == 0
    status, body = http('POST', '/api/machine/events', [ev])   # replay
    assert status == 200, "replay must still 2xx (the cursor-ack)"
    assert body['inserted'] == 0 and body['duplicates'] == 1


def test_gs_camera_disagreement_counter():
    _fresh_db("r2_gscam.db")
    # camera saw pins 1+2 standing (mask 0b11); GS claims only pin 1
    server._note_camera_mask(21, 0b0000000011)
    status, body = http('POST', '/api/machine/cycles', {
        'cycle': {'lane_id': 21, 'final_state': 'READY',
                  'cycle_type': 'ball', 'gs_mask': 0b0000000001}})
    assert status == 200
    status, diag = http('GET', '/api/lane/21/diagnostics')
    assert status == 200
    evs = [e for e in diag['events']
           if e['event_type'] == 'gs_camera_disagree']
    assert len(evs) == 1
    detail = json.loads(evs[0]['detail_json'])
    assert detail['disagree_pins'] == [2]
    # agreement -> no event
    server._note_camera_mask(21, 0b0000000001)
    http('POST', '/api/machine/cycles', {
        'cycle': {'lane_id': 21, 'final_state': 'READY',
                  'gs_mask': 0b0000000001}})
    _, diag = http('GET', '/api/lane/21/diagnostics')
    evs = [e for e in diag['events']
           if e['event_type'] == 'gs_camera_disagree']
    assert len(evs) == 1
    # shadow rows never feed the counter
    server._note_camera_mask(21, 0b0000000111)
    http('POST', '/api/machine/cycles', {
        'cycle': {'lane_id': 21, 'final_state': 'READY',
                  'gs_mask': 0, 'shadow': True}})
    _, diag = http('GET', '/api/lane/21/diagnostics')
    evs = [e for e in diag['events']
           if e['event_type'] == 'gs_camera_disagree']
    assert len(evs) == 1


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    fails = 0
    for name, fn in fns:
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            fails += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
