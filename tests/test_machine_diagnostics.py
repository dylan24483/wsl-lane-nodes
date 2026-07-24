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
os.environ.setdefault("WSL_MACHINE_LANES", "21,22")
os.environ.setdefault(
    "WSL_SCORING_NODE_TOPOLOGY", "test-pair-21-22=21,22")
os.environ.setdefault("WSL_ALLOW_UNAUTHENTICATED_BENCH", "1")
os.environ.setdefault("WSL_CONTROLLER_EXPECTED_MODE", "live")
os.environ.setdefault(
    "WSL_RP2040_QUALIFIED_RELEASES",
    "revD|deadbeef|aa4ff333,revD|test-release|test-config")
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


def scoring_meta(seq=1, session='test-scoring-session', **overrides):
    payload = {
        'scoring_boot_id': 'test-scoring-boot',
        'scoring_session_id': session,
        'heartbeat_seq': seq,
        'scoring_mode': 'camera',
        'camera_calibrated': True,
        'camera_ok': True,
        'camera_code': 'healthy',
        'outbox': {
            'cursor_ok': True,
            'error': False,
            'oldest_unsent_age_s': None,
            'backlog': 0,
            'backlog_bytes': 0,
            'pending_writes': 0,
            'dropped': 0,
            'quarantined': 0,
            'cycles_quarantined': 0,
            'post_errors': 0,
            'write_errors': 0,
            'sink_errors': 0,
            'scoring_event_queue_depth': 0,
            'scoring_event_queue_capacity': 128,
            'scoring_event_oldest_age_s': None,
            'scoring_capture_jobs': 0,
            'scoring_capture_oldest_age_s': None,
            'scoring_clock_observed': True,
            'scoring_clock_anomaly_latched': False,
            'scoring_clock_high_water_epoch': 1.0,
            'scoring_clock_observed_epoch': 1.0,
            'scoring_event_durable': True,
            'scoring_event_error': False,
            'scoring_event_overdue': False,
            'scoring_event_drops': 0,
            'scoring_event_expired': 0,
            'scoring_event_max_age_s': 30.0,
        },
        'node_ball_lockout_s': 8.0,
    }
    payload.update(overrides)
    return payload


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
            ([make_event(ts_mono=True)], 'ts_mono boolean'),
            ([make_event(ts_mono=-1)], 'ts_mono negative'),
            ([make_event(code=123)], 'code non-string'),
            (['not-an-object'], 'event non-dict'),
        ]
        # R3-1b (2026-07-23): ingest is PER-RECORD now — a bad record no
        # longer 400s the whole batch (that was the poison-pill stall). A
        # well-formed array with a single bad element returns 2xx with the
        # element in 'rejected', so the client's cursor still advances.
        for payload, label in cases:
            status, body = http('POST', '/api/machine/events', payload)
            assert_eq(status, 200, f"per-record 2xx: {label}")
            assert_eq(len(body['rejected']), 1, f"one rejected: {label}")
            assert_eq(body['rejected'][0]['index'], 0,
                      f"offending index: {label}")
            assert_eq(body['inserted'], 0, f"bad-only batch inserts 0: {label}")
        # Mixed batch: valid element inserts, bad element (index 1) rejected —
        # NOT all-or-nothing (the R3-1 fix: one poison record can't block the
        # rest and can't stall the cursor).
        status, body = http('POST', '/api/machine/events',
                            [make_event(), make_event(severity='nope')])
        assert_eq(status, 200, "mixed batch is 2xx (cursor-ack)")
        assert_eq(body['inserted'], 1, "valid element inserted")
        assert_eq(len(body['rejected']), 1, "one element rejected")
        assert_eq(body['rejected'][0]['index'], 1, "index points at the bad one")
        assert_eq(machine_store.health_counts()['events_total'], 1,
                  "per-record: the valid one survived")
        # Non-array / empty bodies are still a hard 400 (malformed request).
        for payload in ({}, {'events': []}, {'events': 'x'}):
            status, _ = http('POST', '/api/machine/events', payload)
            assert_eq(status, 400, f"reject non-array body {payload!r}")
        # Oversized batch is still a 400 (a bug, not a backlog).
        status, body = http('POST', '/api/machine/events',
                            [make_event()
                             for _ in range(machine_store.MAX_EVENT_BATCH + 1)])
        assert_eq(status, 400, "oversized batch rejected")


def test_all_invalid_event_batch_has_request_local_complete_ack():
    """A poison-only batch must not inherit another request's duplicates."""
    with fresh_db():
        replay = make_event(
            severity='info', event_type='recovered',
            source_id='disposition-test', boot_id='boot-a', seq=1)
        status, _ = http('POST', '/api/machine/events', [replay])
        assert_eq(status, 200, "seed delivery accepted")
        status, duplicate = http('POST', '/api/machine/events', [replay])
        assert_eq(status, 200, "seed replay acknowledged")
        assert_eq(duplicate['duplicates'], 1, "seed established duplicate")

        invalid = [
            {"lane_id": 22, "severity": "info",
             "event_type": "definitely_not_in_contract"},
            "not-an-event-object",
        ]
        status, body = http('POST', '/api/machine/events', invalid)
        assert_eq(status, 200, "poison-only batch is a cursor ack")
        assert_eq(body['accepted'], 0, "no invalid row accepted")
        assert_eq(body['duplicates'], 0,
                  "no stale duplicate disposition inherited")
        assert_eq(len(body['rejected']), 2, "each poison row rejected")
        assert_eq(
            body['accepted'] + body['duplicates'] + len(body['rejected']),
            len(invalid), "strict disposition equation covers every row")


def test_insert_event_dispositions_are_returned_per_call():
    """Concurrent store callers receive their own transaction disposition."""
    with fresh_db():
        seed = machine_store.validate_event(make_event(
            severity='info', event_type='recovered',
            source_id='concurrent', boot_id='boot-a', seq=1))
        machine_store.insert_events_with_disposition([seed])
        new = machine_store.validate_event(make_event(
            severity='info', event_type='recovered',
            source_id='concurrent', boot_id='boot-a', seq=2))
        barrier = threading.Barrier(3)
        results = {}

        def run(name, row):
            barrier.wait()
            results[name] = machine_store.insert_events_with_disposition([row])

        threads = [
            threading.Thread(target=run, args=('duplicate', seed)),
            threading.Thread(target=run, args=('new', new)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
            assert_true(not thread.is_alive(), "concurrent insert completed")
        assert_eq(results['duplicate'][1], 1,
                  "duplicate call owns duplicate disposition")
        assert_eq(results['duplicate'][0], [],
                  "duplicate call inserts no row")
        assert_eq(results['new'][1], 0,
                  "new call owns inserted disposition")
        assert_eq(len(results['new'][0]), 1, "new call returns its id")


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
            status, body = http('POST', '/api/machine/cycles', payload)
            assert_eq(status, 200, f"cycle disposition: {label}")
            assert_eq(body['accepted'], 0, f"cycle not accepted: {label}")
            assert_eq(body['duplicates'], 0, f"cycle not duplicate: {label}")
            assert_eq(len(body['rejected']), 1, f"cycle rejected: {label}")


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

        _, recovery_body = http('POST', '/api/machine/events', [{
            'lane_id': 22, 'severity': 'info', 'event_type': 'recovered',
            'detail': {'recovery_of_event_id': eid},
        }])
        recovery_id = recovery_body['ids'][0]
        status, body = http(
            'POST', f'/api/machine/events/{eid}/resolve',
            {'resolved_by': 7, 'recovery_event_id': recovery_id})
        assert_eq(status, 200, "resolve ok")
        assert_true(body['event']['resolved_at'], "resolved_at set")
        assert_eq(body['resolution']['mode'], 'verified_recovery',
                  "response identifies evidence-backed resolution")
        assert_eq(body['resolution']['recovery_event_id'], recovery_id,
                  "response binds the recovery evidence")
        assert_eq(body['resolution']['override_pending'], False,
                  "verified recovery is not an override")
        resolved_at = body['event']['resolved_at']
        status, body = http(
            'POST', f'/api/machine/events/{eid}/resolve',
            {'resolved_by': 9, 'recovery_event_id': recovery_id})
        assert_eq(body['event']['resolved_at'], resolved_at,
                  "repeat resolve idempotent")
        assert_eq(body['event']['resolved_by'], 7,
                  "repeat resolve does not steal actor identity")
        assert_eq(body['event']['already_resolved'], True,
                  "repeat flagged as already resolved")

        _, alternate = http('POST', '/api/machine/events', [{
            'lane_id': 22, 'severity': 'info', 'event_type': 'recovered',
            'detail': {'recovery_of_event_id': eid},
        }])
        status, conflict = http(
            'POST', f'/api/machine/events/{eid}/resolve',
            {'resolved_by': 9,
             'recovery_event_id': alternate['ids'][0]})
        assert_eq(status, 400,
                  "resolved replay cannot substitute different evidence")
        assert_true('conflicts' in conflict['error'],
                    "evidence conflict is explicit")

        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(len(diag['open_faults']), 0, "resolved fault leaves the queue")

        # Bad requests.
        status, _ = http('POST', '/api/machine/events/99999/ack', {'by': 7})
        assert status == 404
        status, _ = http('POST', f'/api/machine/events/{eid}/ack', {})
        assert status == 400
        status, _ = http('POST', f'/api/machine/events/{eid}/ack',
                         {'by': 'seven'})
        assert status == 400
        status, _ = http('POST', f'/api/machine/events/{eid}/ack',
                         {'acknowledged_by': 'seven'})
        assert status == 400
        status, _ = http('POST', '/api/machine/events/abc/ack', {'by': 7})
        assert status == 400


def test_resolution_override_is_audited_but_cannot_false_green():
    with fresh_db():
        _, body = http('POST', '/api/machine/events', [
            make_event(lane=22, severity='fault', code='link:lost')])
        event_id = body['ids'][0]

        status, body = http(
            'POST', f'/api/machine/events/{event_id}/resolve',
            {'resolved_by': 7, 'override': {
                'actor_id': 7,
                'reason': 'Manager accepts temporary operation pending repair',
            }})
        assert_eq(status, 200, "privileged override recorded")
        assert_eq(body['event']['override_pending'], True,
                  "override is visibly pending")
        assert_eq(body['resolution']['mode'], 'override_pending',
                  "response identifies privileged override")
        assert_eq(body['resolution']['actor_id'], 7,
                  "override response binds the actor")
        assert_eq(body['event']['resolved_at'], None,
                  "override does not resolve the live fault")
        _, health = http('GET', '/api/machine/health')
        assert_eq(health['lanes']['22']['fault'], True,
                  "override cannot make health green")
        _, diag = http('GET', '/api/lane/22/diagnostics')
        assert_eq(diag['open_incidents'][0]['state'], 'override_pending',
                  "incident lifecycle exposes pending override")
        assert_eq(diag['resolution_audit'][0]['action'],
                  'override_requested', "override has durable audit row")

        _, recovery = http('POST', '/api/machine/events', [
            make_event(lane=22, severity='info',
                       event_type='recovered', code='link:lost')])
        status, body = http(
            'POST', f'/api/machine/events/{event_id}/resolve',
            {'resolved_by': 7,
             'recovery_event_id': recovery['ids'][0]})
        assert_eq(status, 200, "later recovery closes override-pending fault")
        assert_true(body['event']['resolved_at'],
                    "recovery evidence sets resolved_at")
        _, health = http('GET', '/api/machine/health')
        assert_eq(health['lanes']['22']['fault'], False,
                  "verified recovery may clear fault")
        eid = event_id
        status, _ = http(
            'POST', '/api/machine/events/99999/ack', {'by': 7})
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
    """The wsl_api proxy sends {'acknowledged_by': <positive staff id>} (pinned
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

        status, _ = http('POST', f'/api/machine/events/{eid2}/ack',
                         {'acknowledged_by': None})
        assert_eq(status, 400, "null actor cannot create an unaudited ack")


# ---------------------------------------------------------------
# Health rollups
# ---------------------------------------------------------------
def test_machine_health_per_lane_rollup():
    with fresh_db():
        _, body = http('POST', '/api/machine/events', [
            make_event(lane=21, severity='fault', code='motion_timeout:T'),
            make_event(lane=21, severity='fault', code='motion_timeout:S'),
            make_event(lane=21, severity='fault', code='old_resolved'),
            make_event(lane=21, severity='info', event_type='recovered',
                       code='old_resolved'),
            make_event(lane=21, severity='warn', event_type='drift_alarm',
                       code='ta2_to_sa:4sigma'),
            make_event(lane=22, severity='info', event_type='recovered'),
        ])
        resolved_id = body['ids'][2]
        recovery_id = body['ids'][3]
        newest_open_fault_id = body['ids'][1]
        http('POST', f'/api/machine/events/{resolved_id}/resolve',
             {'resolved_by': 7, 'recovery_event_id': recovery_id})
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
        _, recovery_body = http('POST', '/api/machine/events', [
            make_event(lane=21, severity='info', event_type='recovered',
                       code='motion_timeout:T'),
            make_event(lane=21, severity='info', event_type='recovered',
                       code='motion_timeout:S'),
        ])
        for eid, recovery_id in zip(
                body['ids'][:2], recovery_body['ids']):
            http('POST', f'/api/machine/events/{eid}/resolve',
                 {'resolved_by': 7,
                  'recovery_event_id': recovery_id})
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
        assert_eq(health['site_id'], server.SITE_ID or None,
                  "/api/health exposes process-observed site identity")
        assert_eq(health['site_identity_ok'],
                  server._valid_production_node_id(server.SITE_ID),
                  "/api/health reports site-identity syntax")
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
        # garbage ts_utc is NOT silently receive-time-stamped: it is a
        # per-record reject (R3-1b — a 2xx cursor-ack with the record in
        # 'rejected', never a whole-batch 400 that could stall the outbox).
        status, body = http('POST', '/api/machine/events', [{
            'lane_id': 22, 'severity': 'info', 'event_type': 'recovered',
            'ts_utc': 'yesterday-ish'}])
        assert_eq(status, 200, "garbage ts_utc: 2xx cursor-ack")
        assert_eq(len(body['rejected']), 1, "garbage ts_utc rejected per-record")
        assert_eq(body['inserted'], 0, "garbage ts_utc not stored")


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
                    make_event(severity='info', event_type='recovered',
                               created_at=iso_days_ago(days), code=code))
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
            make_event(severity='info', event_type='recovered',
                       created_at=iso_days_ago(365), code='undead'))
        machine_store.insert_events([old])
        with env_override(WSL_MACHINE_DIAG='0'):
            assert_eq(machine_store.prune_events(), 0,
                      "disabled store never prunes")


def test_retention_preserves_unresolved_fault_until_resolution():
    with fresh_db():
        old_fault = machine_store.validate_event(make_event(
            created_at=iso_days_ago(365), code='still_active'))
        ids, duplicates = machine_store.insert_events_with_disposition(
            [old_fault])
        assert_eq(duplicates, 0, "old active fault inserted")
        assert_eq(machine_store.prune_events(), 0,
                  "unresolved fault survives retention")
        health = machine_store.machine_health()
        assert_eq(health['lanes']['22']['fault'], True,
                  "expired unresolved fault remains operationally visible")
        assert_eq(health['lanes']['22']['open_faults'], 1,
                  "expired unresolved fault remains counted")
        assert_eq(health['lanes']['22']['state'], 'UNKNOWN',
                  "absent controller lease still has strict precedence")
        diag = machine_store.lane_diagnostics(22)
        assert_eq([row['id'] for row in diag['open_faults']], ids,
                  "expired unresolved row remains in open faults")

        recovery_id = machine_store.insert_events([
            machine_store.validate_event(make_event(
                severity='info', event_type='recovered',
                code='still_active'))])[0]
        machine_store.resolve_event(
            ids[0], 7, recovery_event_id=recovery_id)
        assert_eq(machine_store.prune_events(), 0,
                  "resolution evidence remains with its durable audit")
        assert_eq(machine_store.health_counts()['events_total'], 2,
                  "fault and recovery evidence remain auditable")


def test_retention_thread_prunes_at_startup_and_is_idempotent():
    with fresh_db():
        machine_store.insert_events([machine_store.validate_event(
            make_event(severity='info', event_type='recovered',
                       created_at=iso_days_ago(400), code='doomed'))])
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
            status, _ = http(
                'POST', '/api/machine/heartbeat', _heartbeat_body())
            assert_eq(status, 503, "controller lease refused when disabled")
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
# ---------------------------------------------------------------
# H4 (Codex audit 2026-07-21): cross-repo contract, SERVER side
# server/machine_contract.json is the single source of truth. The client
# suite (test_diag_events.py) pins HttpSink to the same file. The wrapped
# {"cycle": {...}} POST below is the exact shape the Pi has always sent —
# before the H4 fix the server validated the WRAPPER as the row and 400'd
# every real cycle POST while both sides' fakes stayed green.
# ---------------------------------------------------------------
CONTRACT_PATH = REPO_ROOT / "server" / "machine_contract.json"


def _contract():
    with open(CONTRACT_PATH, encoding='utf-8') as f:
        return json.load(f)


def _heartbeat_body(lane=22, seq=1, loop_seq=1, **overrides):
    heartbeat = {
        "lane_id": lane,
        "controller_boot_id": "machine-diagnostics-test",
        "heartbeat_seq": seq,
        "control_loop_seq": loop_seq,
        "controller_mode": "live",
        "live_outputs_acknowledged": True,
        "arm_state": True,
        "fsm_state": "ready",
        "manual_rearm_required": False,
        "legacy_identity_mode": False,
        "identity_assurance": "verified",
        "arm_prerequisite_reason": None,
        "safety_taps": {
            "ne555": True,
            "wdog_kick": True,
            "arm_permit": True,
            "rp2040_ok": True,
        },
        "board_rev": "revD",
        "contract_sha256": server._contract_sha256(),
        "contract_loaded": True,
        "identity_ok": True,
        "ro_fs": False,
        "observed_pcb": "revD",
        "observed_rid": "1",
        "observed_uid": "machine-diagnostics-test-uid",
        "fw_build": "test-release",
        "fw_cfg": "test-config",
        "fw_version": "test-version",
        "outbox": {
            "oldest_unsent_age_s": None,
            "backlog": 0,
            "backlog_bytes": 0,
            "cursor_ok": True,
            "error": False,
            "pending_writes": 0,
            "quarantined": 0,
            "cycles_quarantined": 0,
            "write_errors": 0,
            "sink_errors": 0,
            "dropped": 0,
        },
        "platform": {
            "ok": True,
            "reasons": [],
            "pi_probes_required": True,
        },
    }
    heartbeat.update(overrides)
    return {"heartbeat": heartbeat}


def test_revd_approved_heartbeat_requires_complete_identity_evidence():
    with fresh_db():
        body = _heartbeat_body()["heartbeat"]
        body.pop("observed_uid")
        status, response = http(
            'POST', '/api/machine/heartbeat', {"heartbeat": body})
        assert_eq(status, 400, "incomplete approved revD identity rejected")
        assert_true(
            "missing evidence" in response.get("error", ""),
            "identity rejection explains missing evidence")


def test_controller_heartbeat_requires_complete_runtime_safety_envelope():
    required = (
        "controller_mode", "live_outputs_acknowledged", "arm_state",
        "fsm_state", "manual_rearm_required", "legacy_identity_mode",
        "identity_assurance", "arm_prerequisite_reason", "safety_taps",
    )
    for field in required:
        body = _heartbeat_body()["heartbeat"]
        body.pop(field)
        try:
            machine_store.validate_heartbeat(body)
            raise AssertionError(f"heartbeat missing {field} was accepted")
        except ValueError as exc:
            assert_true(field in str(exc), f"missing {field} is explicit")

    body = _heartbeat_body()["heartbeat"]
    body["safety_taps"]["ne555"] = None
    try:
        machine_store.validate_heartbeat(body)
        raise AssertionError("verified revD nullable safety tap was accepted")
    except ValueError as exc:
        assert_true(
            "four booleans" in str(exc),
            "verified revD requires all four sampled taps")


def test_controller_posture_is_persisted_forwarded_and_fail_closed():
    old_mode = os.environ.get("WSL_CONTROLLER_EXPECTED_MODE")
    old_qualified = os.environ.get("WSL_RP2040_QUALIFIED_RELEASES")
    os.environ["WSL_CONTROLLER_EXPECTED_MODE"] = "live"
    os.environ["WSL_RP2040_QUALIFIED_RELEASES"] = (
        "revD|test-release|test-config")
    try:
        with fresh_db():
            status, _ = http(
                "POST", "/api/machine/heartbeat", _heartbeat_body())
            assert_eq(status, 200, "complete controller posture accepted")
            entry = machine_store.machine_health()["lanes"]["22"]
            assert_eq(entry["state"], "HEALTHY", "safe posture is healthy")
            assert_eq(entry["controller_mode"], "live", "mode forwarded")
            assert_eq(entry["arm_state"], True, "ARM state forwarded")
            assert_eq(entry["fsm_state"], "ready", "FSM state forwarded")
            assert_eq(
                entry["identity_assurance"], "verified",
                "identity assurance forwarded")
            assert_eq(
                entry["safety_taps"]["arm_permit"], True,
                "safety taps persisted and forwarded")

            status, _ = http(
                "POST", "/api/machine/heartbeat",
                _heartbeat_body(
                    seq=2, loop_seq=2,
                    controller_mode="shadow",
                    live_outputs_acknowledged=False,
                    arm_state=True,
                    fsm_state="fault",
                    manual_rearm_required=True,
                    identity_assurance="legacy_unverified",
                    legacy_identity_mode=True,
                    safety_taps={
                        "ne555": False,
                        "wdog_kick": False,
                        "arm_permit": False,
                        "rp2040_ok": False,
                    }))
            assert_eq(status, 200, "unsafe bounded facts remain observable")
            entry = machine_store.machine_health()["lanes"]["22"]
            assert_eq(entry["state"], "DEGRADED", "unsafe posture degrades")
            reasons = set(entry["degraded_reasons"])
            for reason in (
                    "controller_mode_mismatch",
                    "live_outputs_not_acknowledged",
                    "manual_rearm_required",
                    "identity_assurance_legacy_unverified",
                    "arm_fsm_inconsistent",
                    "arm_without_ne555",
                    "arm_without_rp2040_ok"):
                assert_true(reason in reasons, f"{reason} is explicit")
    finally:
        if old_mode is None:
            os.environ.pop("WSL_CONTROLLER_EXPECTED_MODE", None)
        else:
            os.environ["WSL_CONTROLLER_EXPECTED_MODE"] = old_mode
        if old_qualified is None:
            os.environ.pop("WSL_RP2040_QUALIFIED_RELEASES", None)
        else:
            os.environ["WSL_RP2040_QUALIFIED_RELEASES"] = old_qualified


def test_missing_or_malformed_controller_policy_is_visible_and_degraded():
    old_mode = os.environ.get("WSL_CONTROLLER_EXPECTED_MODE")
    old_qualified = os.environ.get("WSL_RP2040_QUALIFIED_RELEASES")
    try:
        os.environ["WSL_CONTROLLER_EXPECTED_MODE"] = "live"
        os.environ["WSL_RP2040_QUALIFIED_RELEASES"] = (
            "revD|test-release|test-config")
        with fresh_db():
            status, _ = http(
                "POST", "/api/machine/heartbeat", _heartbeat_body())
            assert_eq(status, 200, "safe heartbeat accepted")

            os.environ.pop("WSL_CONTROLLER_EXPECTED_MODE", None)
            entry = machine_store.machine_health()["lanes"]["22"]
            assert_eq(
                entry["state"], "DEGRADED",
                "missing production mode policy is fail-closed")
            assert_true(
                "controller_mode_policy_missing"
                in entry["degraded_reasons"],
                "missing mode policy is surfaced")

            os.environ["WSL_CONTROLLER_EXPECTED_MODE"] = "LIVE"
            entry = machine_store.machine_health()["lanes"]["22"]
            assert_true(
                "controller_mode_policy_invalid"
                in entry["degraded_reasons"],
                "malformed mode policy is surfaced")

            os.environ["WSL_CONTROLLER_EXPECTED_MODE"] = " live "
            entry = machine_store.machine_health()["lanes"]["22"]
            assert_true(
                "controller_mode_policy_invalid"
                in entry["degraded_reasons"],
                "whitespace-padded mode policy is rejected exactly")

            os.environ["WSL_CONTROLLER_EXPECTED_MODE"] = "live"
            os.environ.pop("WSL_RP2040_QUALIFIED_RELEASES", None)
            entry = machine_store.machine_health()["lanes"]["22"]
            assert_true(
                "qualified_release_policy_missing"
                in entry["degraded_reasons"],
                "missing qualified-release policy is surfaced")

            os.environ["WSL_RP2040_QUALIFIED_RELEASES"] = (
                "revD |test-release|test-config")
            entry = machine_store.machine_health()["lanes"]["22"]
            assert_true(
                "qualified_release_policy_invalid"
                in entry["degraded_reasons"],
                "malformed qualified-release policy is surfaced")
    finally:
        if old_mode is None:
            os.environ.pop("WSL_CONTROLLER_EXPECTED_MODE", None)
        else:
            os.environ["WSL_CONTROLLER_EXPECTED_MODE"] = old_mode
        if old_qualified is None:
            os.environ.pop("WSL_RP2040_QUALIFIED_RELEASES", None)
        else:
            os.environ["WSL_RP2040_QUALIFIED_RELEASES"] = old_qualified


def test_cycle_post_accepts_canonical_wrapped_shape():
    with fresh_db():
        # canonical wrapper (the H4 repro — this 400'd pre-fix)
        status, body = http('POST', '/api/machine/cycles', {
            'cycle': {'lane_id': 22, 'final_state': 'READY',
                      'cycle_type': 'ball', 'ball': 1}})
        assert_eq(status, 200, "canonical {'cycle': row} accepted")
        assert_true(isinstance(body['id'], int), "cycle id returned")
        # the contract fixture body VERBATIM — the same object the client
        # suite proves HttpSink.post_cycle emits byte-for-byte
        status, body = http('POST', '/api/machine/cycles',
                            _contract()['examples']['cycle_post_body'])
        assert_eq(status, 200, "contract fixture cycle body accepted")
        # events fixture verbatim too
        status, body = http('POST', '/api/machine/events',
                            _contract()['examples']['events_post_body'])
        assert_eq(status, 200, "contract fixture events body accepted")
        assert_eq(body['inserted'], 1, "fixture batch inserted")
        # a wrapped non-object is a permanent per-record rejection, not a
        # poison-head retry.
        status, body = http('POST', '/api/machine/cycles', {'cycle': 5})
        assert_eq(status, 200, "wrapped non-object disposition returned")
        assert_eq(len(body['rejected']), 1, "wrapped non-object rejected")


def test_contract_file_pins_server_vocab_and_shapes():
    c = _contract()
    ep = c['endpoints']
    assert_eq(ep['cycles_post']['path'], '/api/machine/cycles', "cycles path")
    assert_eq(ep['events_post']['path'], '/api/machine/events', "events path")
    assert_eq(ep['cycles_post']['request_wrapper_key'], 'cycle', "cycle wrapper")
    assert_eq(ep['events_post']['request_wrapper_key'], 'events', "events wrapper")
    assert_eq(ep['events_post']['max_batch'], machine_store.MAX_EVENT_BATCH,
              "max batch")
    v = c['vocab']
    assert_eq(sorted(machine_store.EVENT_TYPES), sorted(v['event_types']),
              "event_types vocab in lockstep")
    assert_eq(list(machine_store.SEVERITIES), v['severities'], "severities")
    assert_eq(sorted(machine_store.CYCLE_TYPES), v['cycle_types'], "cycle_types")
    assert_eq(sorted(machine_store.FINAL_STATES), v['final_states'],
              "final_states")
    assert_eq(list(machine_store.INTERVAL_COLUMNS), v['interval_columns'],
              "interval columns")
    # the recorded hash (the WSL Systems contract test asserts the same value)
    import hashlib
    sidecar_path = REPO_ROOT / "server" / "machine_contract.sha256"
    recorded = sidecar_path.read_text(encoding='utf-8').split()[0].strip()
    actual = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    assert_eq(recorded, actual,
              "machine_contract.sha256 must match machine_contract.json "
              "(update BOTH + every consumer when the contract changes)")
    # R3-8: the server's REPORTED build.contract_sha256 must be the hash of the
    # JSON it SERVES, not the sidecar text. deploy.ps1 compares the WSL pin
    # against this reported value, so a sidecar-trusting digest would let a
    # served-JSON/sidecar divergence pass green. Prove it hashes live AND
    # ignores a deliberately-wrong sidecar.
    assert_eq(server._contract_sha256(), actual,
              "server reports the LIVE machine_contract.json hash")
    _orig = sidecar_path.read_text(encoding='utf-8')
    try:
        sidecar_path.write_text("0" * 64 + "\n", encoding='utf-8')
        assert_eq(server._contract_sha256(), actual,
                  "reported digest stays the live JSON hash despite a WRONG "
                  "sidecar (R3-8: no sidecar-trusting blind spot)")
    finally:
        sidecar_path.write_text(_orig, encoding='utf-8')


def test_machine_health_carries_bridge_contract_keys():
    c = _contract()
    keys = c['endpoints']['machine_health_get']['lane_entry_bridge_keys']
    with fresh_db():
        http('POST', '/api/machine/events', [{
            'lane_id': 21, 'severity': 'fault', 'event_type': 'fsm_fault',
            'code': 'motion_timeout:S'}])
        status, body = http('GET', '/api/machine/health')
        assert_eq(status, 200, "machine health ok")
        entry = body['lanes']['21']
        for k in keys:
            assert_true(k in entry, f"bridge key {k!r} present in rollup entry")
        assert_eq(entry['fault'], True, "fault latched")
        # the contract's machine_health_response example (the WSL Systems
        # bridge-contract test loads it in place of its inline fake) must
        # carry EXACTLY the key set the real rollup produces for a faulted
        # lane — a drifted example would re-open the fake-vs-fake gap.
        example = c['examples']['machine_health_response']
        assert_eq(sorted(example['lanes']['21'].keys()), sorted(entry.keys()),
                  "machine_health_response example keys == real rollup keys")
        assert_eq(sorted(example.keys()),
                  sorted(c['endpoints']['machine_health_get']
                         ['response_top_fields']),
                  "example top-level keys match declared response fields")


# ---------------------------------------------------------------
# R2-10 (Codex round-2, 2026-07-21): board lease / explicit state
# ---------------------------------------------------------------
def test_machine_health_lease_states_and_maintenance():
    with fresh_db():
        # Never heard from -> configured lanes (default 21,22) appear as
        # UNKNOWN — never omitted (omission is how a dead board looks OK).
        health = machine_store.machine_health()
        for lane in ('21', '22'):
            entry = health['lanes'][lane]
            assert_eq(entry['state'], 'UNKNOWN', f"lane {lane} starts UNKNOWN")
            assert_eq(entry['last_seen'], None, f"lane {lane} no lease yet")
            assert_eq(entry['age_s'], None, f"lane {lane} no age yet")

        # Replay/ingest records activity but cannot prove the controller loop.
        http('POST', '/api/machine/cycles',
             {'cycle': {'lane_id': 22, 'final_state': 'READY'}})
        health = machine_store.machine_health()
        e22 = health['lanes']['22']
        assert_eq(e22['state'], 'UNKNOWN',
                  "ingest cannot renew controller lease")
        assert_true(e22['activity_seen_at'], "activity timestamp recorded")
        assert_eq(e22['last_seen'], None, "controller still unseen")
        http('POST', '/api/machine/heartbeat', _heartbeat_body())
        health = machine_store.machine_health()
        e22 = health['lanes']['22']
        assert_eq(e22['state'], 'HEALTHY',
                  "strict controller heartbeat + no fault = HEALTHY")
        assert_true(e22['last_seen'], "controller lease recorded")
        assert_true(e22['age_s'] is not None and e22['age_s'] < 30,
                    "age_s is fresh")
        assert_eq(health['lanes']['21']['state'], 'UNKNOWN',
                  "other lane unaffected")

        # Fresh lease + open fault = FAULT.
        http('POST', '/api/machine/events', [make_event(lane=22)])
        health = machine_store.machine_health()
        assert_eq(health['lanes']['22']['state'], 'FAULT',
                  "open fault on a fresh lease = FAULT")

        # Synthetic deploy markers (deploy.ps1 R2-8 smoke) must NOT fake
        # liveness for a board nobody has heard from.
        http('POST', '/api/machine/events', [
            make_event(lane=21, severity='info', event_type='service_restart',
                       code='deploy_marker:abc1234')])
        health = machine_store.machine_health()
        assert_eq(health['lanes']['21']['state'], 'UNKNOWN',
                  "deploy marker does not touch the lease")

        # Expired lease -> OFFLINE (backdate the lease row directly).
        old = (datetime.now(timezone.utc)
               - timedelta(seconds=machine_store.lease_window_s() + 60))
        conn = sqlite3.connect(machine_store.DB_PATH)
        conn.execute(
            "UPDATE machine_leases SET controller_seen_at = ? "
            "WHERE lane_id = 22",
            (machine_store._normalize_utc_iso(old),))
        conn.commit(); conn.close()
        health = machine_store.machine_health()
        e22 = health['lanes']['22']
        assert_eq(e22['state'], 'OFFLINE', "expired lease = OFFLINE (not FAULT)")
        assert_true(e22['age_s'] > machine_store.lease_window_s(),
                    "age_s reports the staleness")
        assert_eq(e22['fault'], True,
                  "fault fields stay visible alongside OFFLINE")

        # MAINTENANCE wins over everything; off restores derivation.
        status, body = http('POST', '/api/machine/lane/22/maintenance',
                            {'on': True, 'note': 'greasing the table',
                             'changed_by': 7})
        assert_eq(status, 200, "maintenance on accepted")
        assert_eq(body['maintenance'], True, "maintenance echoed")
        health = machine_store.machine_health()
        assert_eq(health['lanes']['22']['state'], 'MAINTENANCE',
                  "maintenance overrides OFFLINE/FAULT")
        http('POST', '/api/machine/lane/22/maintenance',
             {'on': False, 'changed_by': 7})
        health = machine_store.machine_health()
        assert_eq(health['lanes']['22']['state'], 'OFFLINE',
                  "maintenance off restores derived state")

        # Validation: non-bool 'on' and bad lane are 400s.
        status, _ = http('POST', '/api/machine/lane/22/maintenance',
                         {'on': 'yes', 'changed_by': 7})
        assert_eq(status, 400, "non-bool maintenance body rejected")
        status, _ = http('POST', '/api/machine/lane/99/maintenance',
                         {'on': True, 'changed_by': 7})
        assert_eq(status, 400, "out-of-range lane rejected")


def test_scoring_lease_is_visible_but_cannot_bless_controller():
    with fresh_db():
        machine_store.touch_scoring_lanes(
            [21, 22], scoring_meta())
        health = machine_store.machine_health()
        for lane in ('21', '22'):
            entry = health['lanes'][lane]
            assert_eq(entry['scoring_state'], 'HEALTHY',
                      f"Track-A scoring lease fresh on lane {lane}")
            assert_true(entry['scoring_seen_at'],
                        f"Track-A scoring timestamp present on lane {lane}")
            assert_true(entry['scoring_age_s'] is not None,
                        f"Track-A scoring age present on lane {lane}")
            assert_eq(entry['state'], 'UNKNOWN',
                      f"Track-A cannot bless Track-B lane {lane}")
            assert_eq(entry['last_seen'], None,
                      f"controller lease still absent on lane {lane}")

        stale = (datetime.now(timezone.utc)
                 - timedelta(seconds=machine_store.lease_window_s() + 5))
        machine_store.touch_scoring_lanes(
            [21], scoring_meta(session='stale-session'), when=stale)
        # The upsert is monotonic; directly backdate to exercise expiry.
        with sqlite3.connect(machine_store.DB_PATH) as conn:
            conn.execute(
                "UPDATE machine_leases SET scoring_seen_at = ? "
                "WHERE lane_id = 21",
                (stale.isoformat(),))
            conn.commit()
        entry = machine_store.machine_health()['lanes']['21']
        assert_eq(entry['scoring_state'], 'OFFLINE',
                  "expired scoring lease is explicit")
        assert_eq(entry['state'], 'UNKNOWN',
                  "expired scoring lease still cannot alter controller state")

        # Contract lockstep: states vocabulary + bridge keys carry the
        # lease fields.
        c = _contract()
        assert_eq(list(machine_store.MACHINE_STATES), c['vocab']['states'],
                  "states vocab in lockstep")
        for k in ('state', 'last_seen', 'age_s'):
            assert_true(
                k in c['endpoints']['machine_health_get']['lane_entry_bridge_keys'],
                f"contract bridge keys include {k!r}")


def test_future_lease_timestamps_fail_closed_after_clock_rollback():
    with fresh_db():
        machine_store.touch_scoring_lanes([21], scoring_meta())
        future = (
            datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(machine_store.DB_PATH) as conn:
            conn.execute(
                "UPDATE machine_leases SET scoring_seen_at = ?, "
                "controller_seen_at = ?, control_loop_progress_at = ? "
                "WHERE lane_id = 21",
                (future, future, future))
            conn.commit()
        entry = machine_store.machine_health()['lanes']['21']
        assert_eq(entry['scoring_state'], 'UNKNOWN',
                  "future scoring lease cannot look fresh")
        assert_eq(entry['scoring_seen_at'], None,
                  "future scoring timestamp is rejected")
        assert_eq(entry['scoring_reason'], 'scoring_timestamp_future',
                  "scoring rollback reason is explicit")
        assert_eq(entry['state'], 'UNKNOWN',
                  "future controller lease cannot look healthy")
        assert_eq(entry['last_seen'], None,
                  "future controller timestamp is rejected")
        assert_true(
            'controller_timestamp_future' in entry['degraded_reasons'],
            "controller rollback reason is explicit")

        with sqlite3.connect(machine_store.DB_PATH) as conn:
            conn.execute(
                "UPDATE machine_leases SET controller_seen_at = ?, "
                "control_loop_progress_at = ? WHERE lane_id = 21",
                (now, future))
            conn.commit()
        entry = machine_store.machine_health()['lanes']['21']
        assert_eq(entry['state'], 'DEGRADED',
                  "future progress timestamp cannot prove loop movement")
        assert_eq(entry['control_loop_progress_at'], None,
                  "future progress timestamp is rejected")
        assert_true(
            'control_loop_timestamp_future' in entry['degraded_reasons'],
            "progress rollback reason is explicit")


def test_scoring_capability_and_outbox_drive_degraded_state():
    with fresh_db():
        machine_store.touch_scoring_lanes(
            [21], scoring_meta(seq=1))
        entry = machine_store.machine_health()['lanes']['21']
        assert_eq(entry['scoring_state'], 'HEALTHY',
                  "healthy camera plus outbox makes scoring healthy")
        try:
            machine_store.touch_scoring_lanes(
                [21], scoring_meta(seq=1))
            raise AssertionError("replayed scoring sequence was accepted")
        except ValueError:
            pass

        machine_store.touch_scoring_lanes(
            [21], scoring_meta(
                seq=2, camera_ok=False, camera_code='capture_stalled',
                outbox={
                    'cursor_ok': False,
                    'error': True,
                    'oldest_unsent_age_s': 999.0,
                    'backlog': 1,
                    'backlog_bytes': 100,
                    'pending_writes': 1,
                    'dropped': 0,
                    'quarantined': 0,
                    'cycles_quarantined': 0,
                    'post_errors': 1,
                    'write_errors': 0,
                    'sink_errors': 0,
                    'scoring_event_queue_depth': 0,
                    'scoring_event_queue_capacity': 128,
                    'scoring_event_oldest_age_s': None,
                    'scoring_capture_jobs': 0,
                    'scoring_capture_oldest_age_s': None,
                    'scoring_clock_observed': True,
                    'scoring_clock_anomaly_latched': False,
                    'scoring_clock_high_water_epoch': 1.0,
                    'scoring_clock_observed_epoch': 1.0,
                    'scoring_event_durable': False,
                    'scoring_event_error': True,
                    'scoring_event_overdue': False,
                    'scoring_event_drops': 0,
                    'scoring_event_expired': 0,
                    'scoring_event_max_age_s': 30.0,
                }))
        entry = machine_store.machine_health()['lanes']['21']
        assert_eq(entry['scoring_state'], 'DEGRADED',
                  "camera/outbox failure degrades fresh scoring lease")
        assert_true('capture_stalled' in entry['scoring_reasons'],
                    "camera failure reason is visible")
        assert_true('outbox_cursor' in entry['scoring_reasons'],
                    "Track-A outbox failure reason is visible")
        assert_eq(entry['scoring_heartbeat_seq'], 2,
                  "committed scoring sequence is exposed")


def test_scoring_outbox_requires_backlog_byte_age_invariants():
    with fresh_db():
        base = scoring_meta()['outbox']
        invalid = [
            ({key: value for key, value in base.items()
              if key != 'backlog'}, "missing backlog"),
            ({**base, 'backlog': True}, "boolean backlog"),
            ({**base, 'backlog': 1.0}, "non-integer backlog"),
            ({**base, 'backlog_bytes': -1}, "negative backlog bytes"),
            ({**base, 'backlog_bytes': 1,
              'oldest_unsent_age_s': None}, "bytes without age"),
            ({**base, 'backlog_bytes': 0,
              'oldest_unsent_age_s': 0.0}, "age without bytes"),
            ({**base, 'scoring_capture_jobs': 1,
              'scoring_capture_oldest_age_s': None},
             "capture job without age"),
            ({**base, 'scoring_event_queue_depth': 0,
              'scoring_capture_jobs': 1,
              'scoring_capture_oldest_age_s': 1.0},
             "capture jobs exceed depth"),
            ({**base, 'scoring_clock_observed': False},
             "unobserved clock with epochs"),
            ({**base, 'scoring_clock_anomaly_latched': True,
              'scoring_event_error': False},
             "clock anomaly without transport error"),
        ]
        for outbox, label in invalid:
            try:
                machine_store.touch_scoring_lanes(
                    [21], scoring_meta(outbox=outbox))
                raise AssertionError(f"{label} was accepted")
            except ValueError:
                pass

        committed = machine_store.touch_scoring_lanes(
            [21], scoring_meta(outbox={
                **base,
                'backlog': 1,
                'backlog_bytes': 100,
                'oldest_unsent_age_s': 0.0,
            }))
        assert_eq(committed['heartbeat_seq'], 1,
                  "valid nonempty backlog commits")


def test_capture_and_clock_authority_have_distinct_health_reasons():
    with fresh_db():
        base = scoring_meta()['outbox']
        machine_store.touch_scoring_lanes(
            [21], scoring_meta(outbox={
                **base,
                'scoring_event_queue_depth': 1,
                'scoring_event_oldest_age_s': 5.0,
                'scoring_capture_jobs': 1,
                'scoring_capture_oldest_age_s': 5.0,
            }))
        entry = machine_store.machine_health()['lanes']['21']
        assert_true(
            'scoring_capture_pending' in entry['scoring_reasons'],
            "raw camera edge blocking FIFO is distinguished")

    with fresh_db():
        base = scoring_meta()['outbox']
        machine_store.touch_scoring_lanes(
            [21], scoring_meta(outbox={
                **base,
                'error': True,
                'scoring_event_error': True,
                'scoring_clock_anomaly_latched': True,
                'scoring_clock_high_water_epoch': 100.0,
                'scoring_clock_observed_epoch': 90.0,
            }))
        entry = machine_store.machine_health()['lanes']['21']
        assert_true(
            'scoring_clock_anomaly_latched' in entry['scoring_reasons'],
            "Pi command-clock latch is immediately visible")


def test_scoring_boot_retirement_is_durable_across_sessions():
    with fresh_db() as db_path:
        node_id = 'retirement-test-node'
        first = machine_store.accept_scoring_boot(
            node_id, 'boot-a', 'session-a1')
        assert_eq(first['scoring_boot_id'], 'boot-a',
                  "first boot accepted")
        same_boot = machine_store.accept_scoring_boot(
            node_id, 'boot-a', 'session-a2')
        assert_eq(same_boot['scoring_session_id'], 'session-a2',
                  "same boot may reconnect with a fresh session")
        advanced = machine_store.accept_scoring_boot(
            node_id, 'boot-b', 'session-b1')
        assert_eq(advanced['scoring_boot_id'], 'boot-b',
                  "new boot advances the durable owner")
        try:
            machine_store.accept_scoring_boot(
                node_id, 'boot-a', 'session-a3')
            raise AssertionError(
                "retired boot A regained ownership after A -> B")
        except ValueError as exc:
            assert_true('retired' in str(exc),
                        "retired-boot rejection is explicit")

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT scoring_boot_id, last_session_id, retired "
                "FROM scoring_node_boots WHERE node_id = ? "
                "ORDER BY scoring_boot_id",
                (node_id,)).fetchall()
        assert_eq(rows, [
            ('boot-a', 'session-a2', 1),
            ('boot-b', 'session-b1', 0),
        ], "A remains retired and B remains the sole current boot")


def test_api_health_carries_build_identity():
    # R2-8: /api/health must expose the deployed git hash so deploy.ps1
    # can record + compare it (None only when git AND VERSION both fail —
    # this checkout has git, so expect the exact full release commit).
    _, body = http('GET', '/api/health')
    assert_true('git_hash' in body, "git_hash key present in /api/health")
    assert_true(
        isinstance(body['git_hash'], str)
        and len(body['git_hash']) == 40
        and all(c in "0123456789abcdef" for c in body['git_hash']),
        "git identity is an exact lowercase 40-character commit")


TESTS = [
    test_schema_check_on_severity_only_plus_indexes,
    test_post_events_batch_and_diagnostics_readback,
    test_post_events_validation_rejects,
    test_all_invalid_event_batch_has_request_local_complete_ack,
    test_insert_event_dispositions_are_returned_per_call,
    test_post_cycle_and_validation,
    test_ack_is_idempotent_and_resolve_closes_fault,
    test_ack_accepts_bridge_contract_body,
    test_machine_health_per_lane_rollup,
    test_api_health_gains_counts_only_machine_section,
    test_business_date_rollover,
    test_event_ts_utc_is_honored_as_created_at,
    test_baseline_excludes_aborted_and_shadow_cycles,
    test_retention_prunes_only_expired_events,
    test_retention_preserves_unresolved_fault_until_resolution,
    test_retention_thread_prunes_at_startup_and_is_idempotent,
    test_kill_switch_blocks_ingest_not_ack_or_reads,
    test_machine_posts_share_the_lane_token_gate,
    test_revd_approved_heartbeat_requires_complete_identity_evidence,
    test_controller_heartbeat_requires_complete_runtime_safety_envelope,
    test_controller_posture_is_persisted_forwarded_and_fail_closed,
    test_cycle_post_accepts_canonical_wrapped_shape,
    test_contract_file_pins_server_vocab_and_shapes,
    test_machine_health_carries_bridge_contract_keys,
    test_machine_health_lease_states_and_maintenance,
    test_scoring_lease_is_visible_but_cannot_bless_controller,
    test_scoring_capability_and_outbox_drive_degraded_state,
    test_scoring_outbox_requires_backlog_byte_age_invariants,
    test_scoring_boot_retirement_is_durable_across_sessions,
    test_api_health_carries_build_identity,
]


def main():
    # This suite is the H4 contract gate, so a red run must be DIAGNOSABLE,
    # not just countable: a one-shot flake was observed once on a fresh
    # clean clone (17/18, unreproduced in 16+ follow-up runs, 2026-07-21
    # post-remediation review) and the failing check's identity was lost
    # because only the exception MESSAGE was printed. Print the full
    # traceback so any future transient failure pins the exact check and
    # line. Deliberately NO auto-retry: a gate that re-runs itself until
    # green is worse than a flake.
    import traceback as _tb
    print(f"  (loopback HTTP server on 127.0.0.1:{PORT})")
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
            _tb.print_exc(file=sys.stdout)
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            _tb.print_exc(file=sys.stdout)
            failed += 1

    print()
    print(f"  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
