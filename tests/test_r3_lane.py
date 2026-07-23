"""test_r3_lane.py — Codex round-3 lane-side ADVERSARIAL regressions.

Closure bar for the campaign is surviving Codex's adversarial reproduction,
not a happy-path unit test. This file replays the three reproductions Codex
ran and one supporting durability check:

  1. R3-1 poison-pill replay: a record the server used to whole-batch-400
     (fw_identity, or any unknown type) no longer stalls the outbox cursor.
     The valid record inserts, the cursor advances, and a genuinely-bad
     record is quarantined instead of retried forever.
  2. R3-3 two-file stranding: a missing/invalid cursor recovers from the
     OLDEST file with unsent records, not the newest — the older file's rows
     are shipped, never stranded.
  3. R3-5 stale firmware identity: a reboot from a v1.2.2 image into a v0.1
     image (no id line) must NOT leave the old identity readable.
  4. R3-3 durable cycles: a machine_cycles row written to the outbox is
     replayed to /api/machine/cycles after an outage.

Bootstrap mirrors test_r2_server.py (websockets stubbed, throwaway DBs, one
loopback HTTP server). Run under pytest or standalone.
"""
import json
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
LANE_DIR = REPO_ROOT / "lane_node"
for path in (str(REPO_ROOT), str(SERVER_DIR), str(LANE_DIR)):
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
os.environ.setdefault("MACHINE_DB_PATH", str(Path(_TMP.name) / "machine.db"))
os.environ.pop("WSL_MACHINE_DIAG", None)

import machine_store  # noqa: E402
import lane_node_server as server  # noqa: E402
import diag_events as de  # noqa: E402
from rp2040_link import RP2040Link  # noqa: E402

_httpd = HTTPServer(('127.0.0.1', 0), server.HttpHandler)
PORT = _httpd.server_address[1]
BASE = f"http://127.0.0.1:{PORT}"
threading.Thread(target=_httpd.serve_forever, daemon=True).start()


def _http(method, path, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode('utf-8'))


def _fresh_db(name):
    machine_store.DB_PATH = Path(_TMP.name) / name
    machine_store.clear_state()


def _write_outbox(d, rows, name="diag-20260723.jsonl"):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _ev(seq, event_type="recovered", **kw):
    r = {"lane_id": 21, "severity": "info", "event_type": event_type,
         "source_id": "r3-src", "boot_id": "boot-r3", "seq": seq}
    r.update(kw)
    return r


# ── 1. R3-1 poison-pill replay ─────────────────────────────────────────────

def test_fw_identity_no_longer_poisons_the_batch():
    """Codex's exact repro: an outbox holding [fw_identity, valid event]. Pre
    fix the server 400'd the WHOLE batch (fw_identity absent from the vocab),
    acked=0, cursor stuck. Now fw_identity is a first-class contract type: both
    records insert and the cursor advances."""
    _fresh_db("r3_poison1.db")
    d = tempfile.mkdtemp(prefix="r3_poison1_")
    _write_outbox(d, [_ev(1, "fw_identity", code="pcb_rev_mismatch",
                          detail_json='{"pcb":"revD"}'),
                      _ev(2, "recovered", code="after")])
    rep = de.OutboxReplayer(d, BASE)
    acked = rep.replay_once()
    assert acked == 2, f"both records shipped (got {acked})"
    _, diag = _http('GET', '/api/lane/21/diagnostics')
    types_seen = {e['event_type'] for e in diag['events']}
    assert "fw_identity" in types_seen, "fw_identity inserted, not rejected"
    assert "recovered" in types_seen, "the following valid event inserted too"
    cur = json.load(open(rep.cursor_path, encoding="utf-8"))
    assert cur["pos"] > 0, "cursor advanced past the whole file"


def test_unknown_type_is_quarantined_and_cursor_still_advances():
    """A genuinely-unknown type (a future poison) is per-record rejected: the
    batch is still a 2xx cursor-ack, the VALID record inserts, the bad record
    is quarantined (file + counter), and the cursor advances past it — it is
    never retried into a stall."""
    _fresh_db("r3_poison2.db")
    d = tempfile.mkdtemp(prefix="r3_poison2_")
    notified = []
    _write_outbox(d, [_ev(1, "totally_bogus_type_xyz", code="poison"),
                      _ev(2, "recovered", code="good")])
    rep = de.OutboxReplayer(
        d, BASE, on_quarantine=lambda n, lane, errs: notified.append((n, lane)))
    acked = rep.replay_once()
    # both lines are consumed (the run advances); one inserted, one quarantined
    assert acked == 2, "cursor-ack covers the whole segment"
    _, diag = _http('GET', '/api/lane/21/diagnostics')
    types_seen = {e['event_type'] for e in diag['events']}
    assert "recovered" in types_seen, "valid record inserted"
    assert "totally_bogus_type_xyz" not in types_seen, "poison NOT stored"
    assert rep.quarantined == 1, "poison record counted as quarantined"
    assert os.path.exists(rep.quarantine_path), "quarantine file written"
    q = [json.loads(ln) for ln in
         open(rep.quarantine_path, encoding="utf-8").read().splitlines() if ln]
    assert q and q[0]["row"]["event_type"] == "totally_bogus_type_xyz"
    assert notified and notified[0][0] == 1, "quarantine callback fired"
    cur = json.load(open(rep.cursor_path, encoding="utf-8"))
    assert cur["pos"] > 0, "cursor advanced past the poison record"
    # a second pass ships nothing new — the cursor did not stall
    assert rep.replay_once() == 0


# ── 2. R3-3 two-file stranding ─────────────────────────────────────────────

def test_missing_cursor_recovers_from_oldest_file_not_newest():
    """Codex's 2-file repro: two daily files, no cursor. The old code started
    at the NEWEST file and stranded the older file's unsent rows forever. Now
    recovery scans from the OLDEST file — both files ship."""
    _fresh_db("r3_strand.db")
    d = tempfile.mkdtemp(prefix="r3_strand_")
    _write_outbox(d, [_ev(1, code="older")], name="diag-20260722.jsonl")
    _write_outbox(d, [_ev(2, code="newer")], name="diag-20260723.jsonl")
    # no cursor file exists -> the recovery path chooses the start file
    rep = de.OutboxReplayer(d, BASE)
    total = 0
    for _ in range(4):
        total += rep.replay_once()
    _, diag = _http('GET', '/api/lane/21/diagnostics')
    codes = {e['code'] for e in diag['events']}
    assert "older" in codes, "the OLDER file was NOT stranded (R3-3)"
    assert "newer" in codes, "the newer file shipped too"
    assert total == 2, f"both records shipped exactly once (got {total})"


# ── 3. R3-5 stale firmware identity ────────────────────────────────────────

def test_reboot_invalidates_stale_firmware_identity():
    """Codex's v1.2.2 -> v0.1-boot repro. A board announces a full v1.2.2
    identity; then it reboots into a v0.1 image that sends NO id line. The old
    identity must NOT survive the reboot."""
    clock = {"t": 1000.0}
    link = RP2040Link(now=lambda: clock["t"])
    # v1.2.2 identity announced
    link.feed_line(json.dumps({
        "ev": "id", "fw": "1.2.2", "pcb": "revD", "rid": 1,
        "uid": "abc123", "build": "deadbeef", "cfg": "aa4ff333", "fi1": 0}))
    ident = link.fw_identity()
    assert ident is not None and ident["fw"] == "1.2.2", "identity captured"
    assert link.identity_ok() is True
    # establish a heartbeat so the next boot is a real REBOOT (rebooted=True)
    link.feed_line(json.dumps({"ev": "hb", "ok": 1, "flt": "", "up": 5000}))
    # reboot into a v0.1 image — a boot event with NO id follow-up
    clock["t"] = 1001.0
    link.feed_line(json.dumps({"ev": "boot", "fw": "0.1.0", "rp_ok": 0}))
    assert link.fw_identity() is None, \
        "STALE v1.2.2 identity must NOT survive the reboot (R3-5)"
    assert link.identity_ok() is False, "identity is not ok after the reboot"
    # v0.1 firmware never answers ID — poll_identity exhausts its budget and
    # reports missing exactly once.
    results = []
    for i in range(1, 30):
        clock["t"] = 1001.0 + i * 2.0     # advance past IDENTITY_RETRY_S each
        results.append(link.poll_identity())
    assert results.count("missing") == 1, \
        "identity reported MISSING exactly once after the retry budget"
    assert link.identity_missing() is True


def test_fresh_id_after_reboot_clears_missing():
    """The symmetric good path: a v1.2.2 board that reboots and re-announces
    its id clears the missing/stale state (identity is current again)."""
    clock = {"t": 0.0}
    link = RP2040Link(now=lambda: clock["t"])
    link.feed_line(json.dumps({"ev": "hb", "ok": 1, "flt": "", "up": 5000}))
    clock["t"] = 1.0
    link.feed_line(json.dumps({"ev": "boot", "fw": "1.2.2", "rp_ok": 0}))
    assert link.fw_identity() is None, "cleared on reboot"
    # the firmware re-announces after boot
    link.feed_line(json.dumps({
        "ev": "id", "fw": "1.2.2", "pcb": "revD", "rid": 1,
        "build": "cafef00d", "cfg": "aa4ff333", "fi1": 0}))
    assert link.identity_ok() is True, "identity current again"
    assert link.identity_missing() is False
    assert link.poll_identity() is None, "no missing report once id is heard"


# ── 4. R3-3 durable cycles ─────────────────────────────────────────────────

def test_cycle_row_rides_the_durable_outbox():
    """A machine_cycles row written to the outbox (tagged '_kind: cycle') is
    replayed to /api/machine/cycles after an outage — the lossy in-memory-only
    CycleShipper path had no replay."""
    _fresh_db("r3_cycle.db")
    d = tempfile.mkdtemp(prefix="r3_cycle_")
    cycle = {"lane_id": 22, "final_state": "READY", "cycle_type": "ball",
             "ball": 1, "_kind": "cycle",
             "source_id": "r3-src", "boot_id": "boot-r3", "seq": 5}
    ev = _ev(6, "recovered", code="mixed")
    ev["lane_id"] = 22
    _write_outbox(d, [cycle, ev])
    rep = de.OutboxReplayer(d, BASE)
    total = 0
    for _ in range(4):
        total += rep.replay_once()
    assert total == 2, f"cycle + event both shipped (got {total})"
    _, diag = _http('GET', '/api/lane/22/diagnostics')
    assert diag['latest_cycle'] is not None, "durable cycle reached the store"
    assert diag['latest_cycle']['final_state'] == 'READY'
    assert rep.cycles_shipped == 1, "cycle counted on the durable path"


# ── heartbeat endpoint (R3-2, server side) ─────────────────────────────────

def test_heartbeat_touches_lease_and_records_identity():
    _fresh_db("r3_hb.db")
    status, body = _http('POST', '/api/machine/heartbeat', {"heartbeat": {
        "lane_id": 21, "board_rev": "revD", "fw_build": "deadbeef",
        "fw_cfg": "aa4ff333", "contract_sha256": "x" * 64,
        "identity_ok": True, "ro_fs": False,
        "outbox": {"backlog_bytes": 0, "cursor_ok": True}}})
    assert status == 200 and body["ok"] is True
    assert body["last_seen"], "heartbeat stamped the lease"
    # the lane now has a fresh lease -> HEALTHY (not UNKNOWN/OFFLINE)
    _, health = _http('GET', '/api/machine/health')
    assert health['lanes']['21']['state'] == 'HEALTHY', \
        "a quiet controller's heartbeat keeps the lane HEALTHY (R3-2)"
    # a bare object (no wrapper) is tolerated
    status, _ = _http('POST', '/api/machine/heartbeat', {"lane_id": 22})
    assert status == 200


# ── R3-10 robustness: hardened serial parsing ──────────────────────────────

def test_nan_infinity_garbage_lines_never_poison_the_link():
    """R3-10: NaN/Infinity/garbage telemetry lines are counted + quarantined
    and dropped — they never raise and never reach the handlers (a float('nan')
    in FwClock / extrema math is poison)."""
    link = RP2040Link(now=lambda: 0.0)
    before = link.parse_errors
    # NaN / Infinity constants (json.loads accepts these by DEFAULT — the trap)
    link.feed_line('{"ev":"hb","ok":1,"up":NaN}')
    link.feed_line('{"ev":"hb","v5":Infinity}')
    link.feed_line('{"ev":"hb","v5":-Infinity}')
    link.feed_line('not json at all')
    link.feed_line('{"ev":"hb","up":1e999}')       # overflow -> inf
    assert link.parse_errors >= 4, "bad lines counted"
    assert len(link._quar_lines) >= 4, "bad lines quarantined (bounded ring)"
    # a clean line after the garbage still parses fine (reader not wedged)
    link.feed_line('{"ev":"hb","ok":1,"up":1000}')
    assert link._last_up == 1000, "reader kept running after the garbage"
    # _num rejects any non-finite that somehow slips through
    assert RP2040Link._num({"x": float("nan")}, "x") is None
    assert RP2040Link._num({"x": float("inf")}, "x") is None
    assert RP2040Link._num({"x": 5}, "x") == 5


# ── R3-10 maintenance expiration ───────────────────────────────────────────

def test_maintenance_overdue_emits_once_then_stays_maintenance():
    """R3-10: a lane left in MAINTENANCE past the max age emits ONE
    maintenance_overdue warn (state stays MAINTENANCE — only the mechanic
    clears it) and does not re-emit."""
    from datetime import datetime, timezone, timedelta
    _fresh_db("r3_maint.db")
    old = os.environ.get("WSL_MACHINE_MAINTENANCE_MAX_S")
    os.environ["WSL_MACHINE_MAINTENANCE_MAX_S"] = "10"
    try:
        machine_store.set_maintenance(21, True, note="mech on it")
        assert machine_store.sweep_maintenance_overdue() == 0, "fresh: not due"
        future = datetime.now(timezone.utc) + timedelta(seconds=20)
        assert machine_store.sweep_maintenance_overdue(now=future) == 1, \
            "past the max -> one overdue event"
        assert machine_store.sweep_maintenance_overdue(now=future) == 0, \
            "idempotent -> no re-emit"
        _, health = _http('GET', '/api/machine/health')
        assert health['lanes']['21']['state'] == 'MAINTENANCE', \
            "state stays MAINTENANCE (the mechanic must clear it)"
        _, diag = _http('GET', '/api/lane/21/diagnostics')
        assert any(e['event_type'] == 'maintenance_overdue'
                   for e in diag['events']), "the overdue event is on the lane"
        # clearing + re-arming maintenance resets the overdue latch
        machine_store.set_maintenance(21, False)
        machine_store.set_maintenance(21, True)
        assert machine_store.sweep_maintenance_overdue(now=future) == 1, \
            "a fresh maintenance window can alert again"
    finally:
        if old is None:
            os.environ.pop("WSL_MACHINE_MAINTENANCE_MAX_S", None)
        else:
            os.environ["WSL_MACHINE_MAINTENANCE_MAX_S"] = old


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
        except Exception as e:   # noqa: BLE001
            fails += 1
            print(f"ERR  {name}: {e!r}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
