"""Machine-diagnostics domain tests: server/machine_store.py + the
:8766 HTTP surface in server/lane_node_server.py.

Covers the Phase 8 diagnostics scope (docs/phase8_diagnostics_scope_
2026-07-19.md §2/§3) storage + API contract:
  - schema: severity is the ONLY enum CHECK; event_type/cycle_type are
    writer-validated (extensible sets, no table rebuild ever needed);
    the two specced indexes exist
  - POST /api/machine/events (batch) + POST /api/machine/cycles,
    including validation rejects (400 with the offending index)
  - ack idempotency (first ack wins; repeat is a no-op) + resolve
  - GET /api/lane/<N>/diagnostics (open faults, last-N events, latest
    cycle, baseline summary excluding aborted/shadow cycles)
  - GET /api/machine/health per-lane rollup + /api/health "machine"
    counts-only enrichment
  - business_date computed at write (local day, 04:00 cutoff, DST-safe)
  - retention prune (WSL_MACHINE_EVENT_RETENTION_DAYS, default 90)
  - WSL_MACHINE_DIAG kill-switch (ingest 503s; ack/reads keep working)
  - POSTs behind the existing X-Lane-Token gate; GETs stay open

All hardware-free: talks to the real HTTP handler over loopback with
throwaway temp DBs (STATE_DB_PATH + MACHINE_DB_PATH isolated before
import, so live state is never touched).

Run with:
    py -3 tests/test_machine_diagnostics.py
(also collectable by pytest).
"""

import json
import logging
import os
import sqlite3
import sys
import tempfile
import threading
import types
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

# The production server pins websockets, but this suite exercises only
# the HTTP surface — stub the import when the package is absent (same
# pattern as test_lane_fx_gateway.py).
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

# lane_node_server loads persisted scoring state at import time; point
# both stores at throwaway paths BEFORE importing.
_TMP = tempfile.TemporaryDirectory()
os.environ["STATE_DB_PATH"] = str(Path(_TMP.name) / "lane_state.db")
os.environ["MACHINE_DB_PATH"] = str(Path(_TMP.name) / "machine_diag.db")
os.environ.pop("LANE_FX_ENABLED", None)
os.environ.pop("WSL_MACHINE_DIAG", None)
os.environ.pop("WSL_MACHINE_EVENT_RETENTION_DAYS", None)

import machine_store  # noqa: E402
import lane_node_server as server  # noqa: E402

logging.getLogger('machine_store').setLevel(logging.CRITICAL)
logging.getLogger('server').setLevel(logging.CRITICAL)

# One real HTTP server on an ephemeral loopback port for the whole
# suite (the handler is stateless; per-test isolation comes from
# swapping machine_store.DB_PATH).
_httpd = HTTPServer(('127.0.0.1', 0), server.HttpHandler)
PORT = _httpd.server_address[1]
threading.Thread(target=_httpd.serve_forever, daemon=True).start()


def assert_eq(actual, expected, msg):
    if actual != expected:
        raise AssertionError(f"FAIL [{msg}]: expected {expected!r}, got {actual!r}")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL [{msg}]")


def http(method, path, body=None, headers=None):
    """Loopback request → (status, parsed-json-or-text)."""
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8')
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8')
        status = e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


class fresh_db:
    """Point machine_store at a throwaway temp DB for one test."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = machine_store.DB_PATH
        machine_store.DB_PATH = Path(self._tmp.name) / 'machine_diag_test.db'
        return machine_store.DB_PATH

    def __exit__(self, *exc):
        machine_store.DB_PATH = self._old
        try:
            self._tmp.cleanup()
        except OSError:
            pass  # Windows may hold -wal/-shm briefly; temp dir reaps it
        return False


class env_override:
    """Set/unset env vars for one test, restoring on exit."""

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.old = {}
        for k, v in self.kw.items():
            self.old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, prev in self.old.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
        return False


def iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def make_event(lane=22, severity='fault', event_type='fsm_fault',
               **extra):
    ev = {'lane_id': lane, 'severity': severity, 'event_type': event_type}
    ev.update(extra)
    return ev


# ---------------------------------------------------------------
# Schema
# ---------------------------------------------------------------
def test_schema_check_on_severity_only_plus_indexes():
    with fresh_db() as db_path:
        # Any store call creates the schema.
        machine_store.health_counts()
        with sqlite3.connect(db_path) as conn:
            rows = dict(conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'"))
            events_sql = rows['machine_events']
            cycles_sql = rows['machine_cycles']
            index_names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")]
        # severity is the ONLY enum CHECK (lane_id range CHECK is
        # structural, not a vocabulary).
        assert_true("CHECK(severity IN ('info','warn','fault'))"
                    in events_sql.replace('\n', ' '),
                    "severity enum CHECK present")
        assert_eq(events_sql.count('CHECK'), 2,
                  "machine_events has exactly lane_id + severity CHECKs")
        assert_eq(cycles_sql.count('CHECK'), 1,
                  "machine_cycles has only the lane_id CHECK")
        assert_true('event_type    TEXT NOT NULL,' in events_sql,
                    "event_type is un-CHECKed (writer-validated)")
        assert_true('cycle_type    TEXT,' in cycles_sql,
                    "cycle_type is un-CHECKed (writer-validated)")
        assert_true('idx_mc_lane_date' in index_names, "cycles index exists")
        assert_true('idx_me_open' in index_names, "events open-index exists")
        # 2026-07-19 review: lane-leading indexes so lane_diagnostics + the
        # machine_health rollup never full-scan under _db_lock.
        assert_true('idx_me_lane_created' in index_names,
                    "events lane/created index exists")
        assert_true('idx_me_open_fault' in index_names,
                    "partial open-fault index exists")
        assert_true('idx_mc_lane_started' in index_names,
                    "cycles lane/started index exists")


# ---------------------------------------------------------------
# POST /api/machine/events + /api/machine/cycles
# ---------------------------------------------------------------
def test_post_events_batch_and_diagnostics_readback():
    with fresh_db():
        status, body = http('POST', '/api/machine/events', [
            make_event(lane=22, severity='fault', event_type='fsm_fault',
                       code='motion_timeout:S',
                       detail={'state': 'SWEEP_TO_GUARD', 'elapsed_s': 8.02},
                       blackbox_file='blackbox_lane22_0001.json'),
            make_event(lane=22, severity='info', event_type='recovered',
                       code='pbz_two_press'),
        ])
        assert_eq(status, 200, "batch insert accepted")
        assert_eq(body['inserted'], 2, "two events inserted")
        assert_eq(len(body['ids']), 2, "two ids returned")

        # Wrapped form {"events": [...]} also accepted.
        status, body = http('POST', '/api/machine/events',
                            {'events': [make_event(lane=21, severity='warn',
                                                   event_type='drift_alarm')]})
        assert_eq(status, 200, "wrapped events form accepted")

        status, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(status, 200, "diagnostics readable")
        assert_eq(diag['lane'], 22, "lane echoed")
        assert_eq(len(diag['events']), 2, "lane 22 sees only its 2 events")
        assert_eq(len(diag['open_faults']), 1, "one unresolved fault")
        fault = diag['open_faults'][0]
        assert_eq(fault['code'], 'motion_timeout:S', "fault code stored")
        assert_eq(json.loads(fault['detail_json'])['state'], 'SWEEP_TO_GUARD',
                  "detail dict serialized to detail_json")
        assert_true(fault['created_at'].endswith('+00:00'),
                    "created_at stored normalized UTC")
        assert_true(fault['business_date'], "business_date stamped at write")
        assert_eq(fault['acknowledged_at'], None, "not yet acked")

        # ?events=1 caps the event list, not the faults.
        status, diag = http('GET', '/api/lane/22/diagnostics?events=1')
        assert_eq(len(diag['events']), 1, "events limit honored")


def test_post_events_validation_rejects():
    with fresh_db():
        cases = [
            ([make_event(severity='critical')], 'severity'),
            ([make_event(event_type='made_up_type')], 'event_type'),
            ([make_event(lane=0)], 'lane_id low'),
            ([make_event(lane=33)], 'lane_id high'),
            ([make_event(lane='22')], 'lane_id string'),
            ([make_event(created_at='not-a-date')], 'created_at garbage'),
            ([make_event(code=123)], 'code non-string'),
            (['not-an-object'], 'event non-dict'),
        ]
        for payload, label in cases:
            status, body = http('POST', '/api/machine/events', payload)
            assert_eq(status, 400, f"reject: {label}")
            assert_eq(body.get('index'), 0, f"offending index: {label}")
        # Second element bad → index 1, nothing inserted (all-or-nothing).
        status, body = http('POST', '/api/machine/events',
                            [make_event(), make_event(severity='nope')])
        assert_eq(status, 400, "batch with one bad event rejected")
        assert_eq(body['index'], 1, "index points at the bad element")
        assert_eq(machine_store.health_counts()['events_total'], 0,
                  "all-or-nothing: nothing inserted")
        # Non-array bodies.
        for payload in ({}, {'events': []}, {'events': 'x'}):
            status, _ = http('POST', '/api/machine/events', payload)
            assert_eq(status, 400, f"reject non-array body {payload!r}")
        # Oversized batch.
        status, body = http('POST', '/api/machine/events',
                            [make_event()
                             for _ in range(machine_store.MAX_EVENT_BATCH + 1)])
        assert_eq(status, 400, "oversized batch rejected")


def test_post_cycle_and_validation():
    with fresh_db():
        status, body = http('POST', '/api/machine/cycles', {
            'lane_id': 22, 'cycle_type': 'ball', 'ball': 1,
            'final_state': 'READY',
            'started_at': '2026-07-19T05:00:00Z',
            'ended_at': '2026-07-19T05:00:09Z',
            'ss_to_guard_ms': 750.4,  # numeric → integer ms
            'guard_to_table_ms': 1200,
            'gs_mask': 0x3FF, 'cam_mask': 0x3FF,
            'fw_version': 'v1.1.1', 'shadow': True,
        })
        assert_eq(status, 200, "cycle insert accepted")
        assert_true(isinstance(body['id'], int), "cycle id returned")

        status, diag = http('GET', '/api/lane/22/diagnostics')
        cyc = diag['latest_cycle']
        assert_eq(cyc['ss_to_guard_ms'], 750, "float duration stored as int ms")
        assert_eq(cyc['final_state'], 'READY', "final_state stored")
        assert_eq(cyc['shadow'], 1, "shadow flag stored")
        assert_true(cyc['started_at'].endswith('+00:00'),
                    "started_at normalized UTC")

        bad_cycles = [
            ({'lane_id': 22, 'final_state': 'EXPLODED'}, 'final_state'),
            ({'lane_id': 22, 'final_state': 'READY',
              'cycle_type': 'nope'}, 'cycle_type'),
            ({'lane_id': 22, 'final_state': 'READY',
              'ss_to_guard_ms': -5}, 'negative duration'),
            ({'lane_id': 22, 'final_state': 'READY',
              'ss_to_guard_ms': 'fast'}, 'non-numeric duration'),
            ({'lane_id': 22, 'final_state': 'READY',
              'gs_mask': 2048}, 'gs_mask out of range'),
            ({'final_state': 'READY'}, 'missing lane_id'),
            ({'lane_id': 22}, 'missing final_state'),
        ]
        for payload, label in bad_cycles:
            status, _ = http('POST', '/api/machine/cycles', payload)
            assert_eq(status, 400, f"cycle reject: {label}")


# ---------------------------------------------------------------
# Ack / resolve
# ---------------------------------------------------------------
def test_ack_is_idempotent_and_resolve_closes_fault():
    with fresh_db():
        _, body = http('POST', '/api/machine/events', [make_event()])
        eid = body['ids'][0]

        status, body = http('POST', f'/api/machine/events/{eid}/ack',
                            {'by': 7})
        assert_eq(status, 200, "first ack ok")
        assert_eq(body['event']['acknowledged_by'], 7, "acked by staff 7")
        assert_eq(body['event']['already_acknowledged'], False,
                  "first ack is fresh")
        first_at = body['event']['acknowledged_at']
        assert_true(first_at, "acknowledged_at set")

        # Second ack by someone else: idempotent — first ack wins.
        status, body = http('POST', f'/api/machine/events/{eid}/ack',
                            {'by': 9})
        assert_eq(status, 200, "repeat ack still ok")
        assert_eq(body['event']['acknowledged_by'], 7,
                  "repeat ack does NOT steal ownership")
        assert_eq(body['event']['acknowledged_at'], first_at,
                  "repeat ack does not move the timestamp")
        assert_eq(body['event']['already_acknowledged'], True,
                  "repeat flagged as already acknowledged")

        # Fault stays in open_faults until RESOLVED (ack != resolve).
        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(len(diag['open_faults']), 1, "acked fault still open")

        status, body = http('POST', f'/api/machine/events/{eid}/resolve')
        assert_eq(status, 200, "resolve ok")
        assert_true(body['event']['resolved_at'], "resolved_at set")
        resolved_at = body['event']['resolved_at']
        status, body = http('POST', f'/api/machine/events/{eid}/resolve')
        assert_eq(body['event']['resolved_at'], resolved_at,
                  "repeat resolve idempotent")
        assert_eq(body['event']['already_resolved'], True,
                  "repeat flagged as already resolved")

        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(len(diag['open_faults']), 0, "resolved fault leaves the queue")

        # Bad requests.
        status, _ = http('POST', '/api/machine/events/99999/ack', {'by': 7})
        assert_eq(status, 404, "ack of unknown id → 404")
        status, _ = http('POST', f'/api/machine/events/{eid}/ack', {})
        assert_eq(status, 400, "ack without by → 400")
        status, _ = http('POST', f'/api/machine/events/{eid}/ack',
                         {'by': 'seven'})
        assert_eq(status, 400, "ack with non-int by → 400")
        status, _ = http('POST', f'/api/machine/events/{eid}/ack',
                         {'acknowledged_by': 'seven'})
        assert_eq(status, 400, "ack with non-int acknowledged_by → 400")
        status, _ = http('POST', '/api/machine/events/abc/ack', {'by': 7})
        assert_eq(status, 400, "non-numeric event id → 400")


def test_ack_accepts_bridge_contract_body():
    """The wsl_api proxy sends {'acknowledged_by': <staff id|null>} (pinned
    by WSL Systems tests/test_phase8_bridge_contract.py). 2026-07-19 review:
    only {'by': int} was accepted, so every desk ack 400'd."""
    with fresh_db():
        _, body = http('POST', '/api/machine/events',
                       [make_event(), make_event()])
        eid1, eid2 = body['ids']

        status, body = http('POST', f'/api/machine/events/{eid1}/ack',
                            {'acknowledged_by': 7})
        assert_eq(status, 200, "acknowledged_by spelling accepted")
        assert_eq(body['event']['acknowledged_by'], 7,
                  "staff id stored from acknowledged_by")

        # null staff id (actor without a staff_id) acks with NULL — the id is
        # an opaque wsl.db reference; a missing one must not block the ack.
        status, body = http('POST', f'/api/machine/events/{eid2}/ack',
                            {'acknowledged_by': None})
        assert_eq(status, 200, "null acknowledged_by accepted")
        assert_eq(body['event']['acknowledged_by'], None,
                  "NULL stored for a null staff id")
        assert_true(body['event']['acknowledged_at'],
                    "acknowledged_at still stamped")


# ---------------------------------------------------------------
# Health rollups
# ---------------------------------------------------------------
def test_machine_health_per_lane_rollup():
    with fresh_db():
        _, body = http('POST', '/api/machine/events', [
            make_event(lane=21, severity='fault', code='motion_timeout:T'),
            make_event(lane=21, severity='fault', code='motion_timeout:S'),
            make_event(lane=21, severity='fault', code='old_resolved'),
            make_event(lane=21, severity='warn', event_type='drift_alarm',
                       code='ta2_to_sa:4sigma'),
            make_event(lane=22, severity='info', event_type='recovered'),
        ])
        resolved_id = body['ids'][2]
        newest_open_fault_id = body['ids'][1]
        http('POST', f'/api/machine/events/{resolved_id}/resolve')
        http('POST', '/api/machine/cycles',
             {'lane_id': 22, 'final_state': 'READY'})

        status, health = http('GET', '/api/machine/health')
        assert_eq(status, 200, "machine health readable")
        lanes = health['lanes']
        assert_eq(lanes['21']['open_faults'], 2,
                  "lane 21 open faults exclude the resolved one")
        assert_eq(lanes['21']['last_event_code'], 'ta2_to_sa:4sigma',
                  "lane 21 last event is the newest insert")
        assert_eq(lanes['21']['last_event_type'], 'drift_alarm',
                  "lane 21 last event type")
        assert_eq(lanes['21']['last_cycle_final_state'], None,
                  "lane 21 has no cycles yet")
        assert_eq(lanes['22']['open_faults'], 0, "lane 22 has no open faults")
        assert_eq(lanes['22']['last_cycle_final_state'], 'READY',
                  "lane 22 last cycle final_state")
        assert_true(lanes['22']['last_event_at'], "lane 22 last event ts set")

        # ---- bridge-contract keys (2026-07-19 review) ----
        # wsl_phase8_bridge._parse_machine_health whitelists
        # {fault, code, since, acked, event_id, severity}; without them every
        # lane coerced to fault=False and the desk badge + mechanic SMS were
        # a silent no-op end-to-end. Change ONLY in lockstep with
        # WSL Systems tests/test_phase8_bridge_contract.py.
        assert_eq(lanes['21']['fault'], True, "lane 21 fault flag set")
        assert_eq(lanes['21']['code'], 'motion_timeout:S',
                  "code = newest OPEN fault's code")
        assert_eq(lanes['21']['event_id'], newest_open_fault_id,
                  "event_id points at the open fault row")
        assert_eq(lanes['21']['severity'], 'fault', "severity surfaced")
        assert_eq(lanes['21']['acked'], False, "unacked fault -> acked False")
        assert_true(lanes['21']['since'], "since = fault created_at")
        assert_eq(lanes['22']['fault'], False, "healthy lane fault False")
        assert_eq(lanes['22']['code'], None, "healthy lane has no code")
        assert_eq(lanes['22']['acked'], False, "healthy lane acked False")

        # The fault 'code' is STABLE while the fault stays open: routine info
        # events roll last_event_code forward but must NOT change 'code' —
        # wsl_machine_alerts treats a code change as a NEW latch, so a rolling
        # code would send one SMS per info event, bypassing the throttle.
        http('POST', '/api/machine/events', [
            make_event(lane=21, severity='info', event_type='manual_override',
                       code='manual:MAN_T')])
        _, health = http('GET', '/api/machine/health')
        assert_eq(health['lanes']['21']['last_event_code'], 'manual:MAN_T',
                  "last_event_code rolls with info events")
        assert_eq(health['lanes']['21']['code'], 'motion_timeout:S',
                  "open-fault code is stable across info events")

        # acked flips once the open fault is acknowledged...
        http('POST',
             f"/api/machine/events/{newest_open_fault_id}/ack", {'by': 7})
        _, health = http('GET', '/api/machine/health')
        assert_eq(health['lanes']['21']['acked'], True,
                  "acked reflects the open fault's acknowledged_at")
        # ...and resolving every open fault clears the flag entirely.
        for eid in body['ids'][:2]:
            http('POST', f'/api/machine/events/{eid}/resolve')
        _, health = http('GET', '/api/machine/health')
        assert_eq(health['lanes']['21']['fault'], False,
                  "all faults resolved -> fault False")
        assert_eq(health['lanes']['21']['code'], None,
                  "no open fault -> code None")


def test_api_health_gains_counts_only_machine_section():
    with fresh_db():
        http('POST', '/api/machine/events',
             [make_event(), make_event(severity='info',
                                       event_type='recovered')])
        http('POST', '/api/machine/cycles',
             {'lane_id': 22, 'final_state': 'FAULT'})
        status, health = http('GET', '/api/health')
        assert_eq(status, 200, "/api/health ok")
        m = health['machine']
        assert_eq(m['ok'], True, "machine section healthy")
        assert_eq(m['events_total'], 2, "events counted")
        assert_eq(m['open_faults'], 1, "open faults counted")
        assert_eq(m['cycles_total'], 1, "cycles counted")
        assert_eq(m['enabled'], True, "kill-switch state surfaced")
        assert_eq(m['retention_days'], machine_store.DEFAULT_RETENTION_DAYS,
                  "retention config surfaced")
        # Counts only — no row payloads ride /api/health.
        for heavy in ('events', 'open_fault_rows', 'lanes'):
            assert_true(heavy not in m, f"no bulk '{heavy}' key in /api/health")


# ---------------------------------------------------------------
# business_date at write
# ---------------------------------------------------------------
def test_business_date_rollover():
    with env_override(WSL_BUSINESS_DAY_TIMEZONE='America/Los_Angeles',
                      WSL_BUSINESS_DAY_CUTOFF='04:00'):
        # 10:30Z on Jul 19 = 03:30 PDT — before cutoff → previous day.
        assert_eq(machine_store.business_date_for('2026-07-19T10:30:00Z'),
                  '2026-07-18', "pre-cutoff local time rolls back a day")
        # 11:30Z = 04:30 PDT — after cutoff → same local day.
        assert_eq(machine_store.business_date_for('2026-07-19T11:30:00Z'),
                  '2026-07-19', "post-cutoff local time keeps the day")
        # Winter (PST, UTC-8): 11:30Z = 03:30 PST — still pre-cutoff.
        assert_eq(machine_store.business_date_for('2026-01-15T11:30:00Z'),
                  '2026-01-14', "DST-off rollover correct")
    with env_override(WSL_BUSINESS_DAY_TIMEZONE='America/Los_Angeles',
                      WSL_BUSINESS_DAY_CUTOFF='06:00'):
        assert_eq(machine_store.business_date_for('2026-07-19T12:30:00Z'),
                  '2026-07-18', "configurable cutoff hour honored")
    with env_override(WSL_BUSINESS_DAY_TIMEZONE='Not/AZone',
                      WSL_BUSINESS_DAY_CUTOFF='25:99'):
        # Bad config must never raise on the write path — falls back.
        assert_eq(machine_store.business_date_for('2026-07-19T11:30:00Z'),
                  '2026-07-19', "bad tz/cutoff config falls back to defaults")

    # Stamped at write from the row's own timestamp (late-shipped
    # batches land on the right business day).
    with fresh_db(), env_override(
            WSL_BUSINESS_DAY_TIMEZONE='America/Los_Angeles',
            WSL_BUSINESS_DAY_CUTOFF='04:00'):
        _, body = http('POST', '/api/machine/events',
                       [make_event(created_at='2026-07-19T10:30:00Z')])
        assert_eq(body['inserted'], 1, "backdated event accepted")
        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(diag['events'][0]['business_date'], '2026-07-18',
                  "stored business_date rolls back before the cutoff")
        http('POST', '/api/machine/cycles',
             {'lane_id': 22, 'final_state': 'READY',
              'started_at': '2026-07-19T11:30:00Z'})
        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(diag['latest_cycle']['business_date'], '2026-07-19',
                  "cycle business_date from started_at")


def test_event_ts_utc_is_honored_as_created_at():
    """DiagEvent.to_dict ships the event's wall-clock time as 'ts_utc'.
    2026-07-19 review: ingest read only 'created_at' and silently stamped
    server RECEIVE time, so late-shipped batches landed on the wrong
    business day and chronology reflected shipping latency."""
    with fresh_db(), env_override(
            WSL_BUSINESS_DAY_TIMEZONE='America/Los_Angeles',
            WSL_BUSINESS_DAY_CUTOFF='04:00'):
        # The exact shape the Pi's DiagWriter/HttpSink POSTs.
        status, _ = http('POST', '/api/machine/events', {'events': [{
            'lane_id': 22, 'severity': 'fault', 'event_type': 'fsm_fault',
            'code': 'motion_timeout:S', 'ts_utc': '2026-07-19T10:59:58+00:00',
            'ts_mono': 12345.6, 'detail': {'state': 'SWEEP_TO_GUARD'},
        }]})
        assert_eq(status, 200, "Pi-shaped event accepted")
        _, diag = http('GET', '/api/lane/22/diagnostics')
        ev = diag['events'][0]
        assert_eq(ev['created_at'], '2026-07-19T10:59:58.000+00:00',
                  "ts_utc becomes created_at (event time, not receive time)")
        assert_eq(ev['business_date'], '2026-07-18',
                  "business_date computed from the event's own time "
                  "(03:59:58 PDT is pre-cutoff)")
        # explicit created_at still wins over ts_utc when both are present
        http('POST', '/api/machine/events', [{
            'lane_id': 22, 'severity': 'info', 'event_type': 'recovered',
            'created_at': '2026-07-19T20:00:00Z',
            'ts_utc': '2026-07-19T10:00:00Z'}])
        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(diag['events'][0]['created_at'],
                  '2026-07-19T20:00:00.000+00:00', "created_at beats ts_utc")
        # garbage ts_utc is a 400, not a silent receive-time stamp
        status, _ = http('POST', '/api/machine/events', [{
            'lane_id': 22, 'severity': 'info', 'event_type': 'recovered',
            'ts_utc': 'yesterday-ish'}])
        assert_eq(status, 400, "garbage ts_utc rejected")


# ---------------------------------------------------------------
# Baseline summary
# ---------------------------------------------------------------
def test_baseline_excludes_aborted_and_shadow_cycles():
    with fresh_db():
        for ms, extra in ((700, {}), (800, {}),
                          (9999, {'aborted': True}),
                          (5555, {'shadow': True})):
            payload = {'lane_id': 22, 'final_state': 'READY',
                       'ss_to_guard_ms': ms}
            payload.update(extra)
            status, _ = http('POST', '/api/machine/cycles', payload)
            assert_eq(status, 200, f"cycle {ms} accepted")
        _, diag = http('GET', '/api/lane/22/diagnostics')
        base = diag['baseline']
        assert_true(base is not None, "baseline present")
        assert_eq(base['sample_cycles'], 2, "aborted + shadow excluded")
        iv = base['intervals']['ss_to_guard_ms']
        assert_eq(iv['n'], 2, "two clean samples")
        assert_eq(iv['mean_ms'], 750.0, "mean over clean cycles only")
        assert_eq(iv['min_ms'], 700, "min")
        assert_eq(iv['max_ms'], 800, "max")
        # latest_cycle is still the newest row regardless of shadow flag.
        assert_eq(diag['latest_cycle']['shadow'], 1,
                  "latest cycle unfiltered")
        # A lane with no cycles has no baseline and no latest cycle.
        _, diag21 = http('GET', '/api/lane/21/diagnostics')
        assert_eq(diag21['baseline'], None, "no cycles → no baseline")
        assert_eq(diag21['latest_cycle'], None, "no cycles → no latest")


# ---------------------------------------------------------------
# Retention
# ---------------------------------------------------------------
def test_retention_prunes_only_expired_events():
    with fresh_db():
        rows = [machine_store.validate_event(
                    make_event(created_at=iso_days_ago(days), code=code))
                for days, code in ((100, 'ancient'), (40, 'middle'),
                                   (1, 'fresh'))]
        machine_store.insert_events(rows)

        # Default 90 days: only the 100-day-old event goes.
        with env_override(WSL_MACHINE_EVENT_RETENTION_DAYS=None):
            assert_eq(machine_store.prune_events(), 1,
                      "default prune deletes exactly the expired event")
        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(sorted(e['code'] for e in diag['events']),
                  ['fresh', 'middle'], "recent events survive")

        # Tighter env window prunes deeper.
        with env_override(WSL_MACHINE_EVENT_RETENTION_DAYS='30'):
            assert_eq(machine_store.retention_days(), 30, "env override read")
            assert_eq(machine_store.prune_events(), 1,
                      "30-day window deletes the 40-day event")
        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq([e['code'] for e in diag['events']], ['fresh'],
                  "only the fresh event remains")

        # Garbage env falls back to the default instead of raising.
        with env_override(WSL_MACHINE_EVENT_RETENTION_DAYS='soon'):
            assert_eq(machine_store.retention_days(),
                      machine_store.DEFAULT_RETENTION_DAYS,
                      "bad retention env falls back to default")
            assert_eq(machine_store.prune_events(), 0,
                      "fallback window deletes nothing fresh")

        # Kill-switch off → prune is a no-op.
        old = machine_store.validate_event(
            make_event(created_at=iso_days_ago(365), code='undead'))
        machine_store.insert_events([old])
        with env_override(WSL_MACHINE_DIAG='0'):
            assert_eq(machine_store.prune_events(), 0,
                      "disabled store never prunes")


def test_retention_thread_prunes_at_startup_and_is_idempotent():
    with fresh_db():
        machine_store.insert_events([machine_store.validate_event(
            make_event(created_at=iso_days_ago(400), code='doomed'))])
        t = machine_store.start_retention_thread(interval_s=3600)
        assert_true(t is not None, "first start returns the thread")
        # The startup prune runs ON the background thread — poll briefly.
        import time as _time
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline:
            if machine_store.health_counts()['events_total'] == 0:
                break
            _time.sleep(0.05)
        assert_eq(machine_store.health_counts()['events_total'], 0,
                  "startup prune removed the expired event")
        assert_true(machine_store.start_retention_thread() is None,
                    "second start is a no-op (idempotent)")


# ---------------------------------------------------------------
# Kill-switch + auth posture
# ---------------------------------------------------------------
def test_kill_switch_blocks_ingest_not_ack_or_reads():
    with fresh_db():
        _, body = http('POST', '/api/machine/events', [make_event()])
        eid = body['ids'][0]
        with env_override(WSL_MACHINE_DIAG='0'):
            assert_eq(machine_store.enabled(), False, "switch reads off")
            status, _ = http('POST', '/api/machine/events', [make_event()])
            assert_eq(status, 503, "event ingest refused when disabled")
            status, _ = http('POST', '/api/machine/cycles',
                             {'lane_id': 22, 'final_state': 'READY'})
            assert_eq(status, 503, "cycle ingest refused when disabled")
            # Reads + desk ack on existing rows keep working.
            status, diag = http('GET', '/api/lane/22/diagnostics')
            assert_eq(status, 200, "diagnostics readable when disabled")
            assert_eq(len(diag['events']), 1, "existing data still visible")
            status, body = http('POST', f'/api/machine/events/{eid}/ack',
                                {'by': 7})
            assert_eq(status, 200, "ack still allowed when disabled")
            _, health = http('GET', '/api/health')
            assert_eq(health['machine']['enabled'], False,
                      "health surfaces the disabled state")
        assert_eq(machine_store.enabled(), True, "switch restores")


def test_machine_posts_share_the_lane_token_gate():
    with fresh_db():
        old_token = server.AUTH_TOKEN
        server.AUTH_TOKEN = 'sekret'
        try:
            status, _ = http('POST', '/api/machine/events', [make_event()])
            assert_eq(status, 401, "POST without token rejected")
            status, _ = http('POST', '/api/machine/events', [make_event()],
                             headers={'X-Lane-Token': 'sekret'})
            assert_eq(status, 200, "POST with token accepted")
            # GETs stay open (LAN posture, same as scoring/health GETs).
            status, _ = http('GET', '/api/lane/22/diagnostics')
            assert_eq(status, 200, "diagnostics GET needs no token")
            status, _ = http('GET', '/api/machine/health')
            assert_eq(status, 200, "machine health GET needs no token")
        finally:
            server.AUTH_TOKEN = old_token


# ---------------------------------------------------------------
# Runner
# ---------------------------------------------------------------
TESTS = [
    test_schema_check_on_severity_only_plus_indexes,
    test_post_events_batch_and_diagnostics_readback,
    test_post_events_validation_rejects,
    test_post_cycle_and_validation,
    test_ack_is_idempotent_and_resolve_closes_fault,
    test_ack_accepts_bridge_contract_body,
    test_machine_health_per_lane_rollup,
    test_api_health_gains_counts_only_machine_section,
    test_business_date_rollover,
    test_event_ts_utc_is_honored_as_created_at,
    test_baseline_excludes_aborted_and_shadow_cycles,
    test_retention_prunes_only_expired_events,
    test_retention_thread_prunes_at_startup_and_is_idempotent,
    test_kill_switch_blocks_ingest_not_ack_or_reads,
    test_machine_posts_share_the_lane_token_gate,
]


def main():
    passed = 0
    failed = 0
    for t in TESTS:
        name = t.__name__
        try:
            t()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed += 1

    print()
    print(f"  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
