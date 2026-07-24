"""HTTP regressions for scoring generations, replay, transfer, and manual work."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import sys
import threading
import time
import types
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
for entry in (str(REPO_ROOT), str(SERVER_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

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

import lane_node_server as server  # noqa: E402
import machine_store  # noqa: E402
import state_store  # noqa: E402


@pytest.fixture(scope="module")
def http_origin():
    httpd = server.BoundedThreadingHTTPServer(
        ("127.0.0.1", 0), server.HttpHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


@pytest.fixture(autouse=True)
def isolated_server_state(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY", "test-pair-21-22=21,22")
    monkeypatch.setattr(
        state_store, "DB_PATH", tmp_path / "lane-state.sqlite3")
    monkeypatch.setattr(
        machine_store, "DB_PATH", tmp_path / "machine.sqlite3")
    monkeypatch.setattr(server, "AUTH_TOKEN", "")
    sent = []

    def deliver(lane, raw):
        sent.append((lane, json.loads(raw)))
        return 1

    monkeypatch.setattr(server, "send_to_lane", deliver)
    monkeypatch.setattr(server, "_emit_fx_event", lambda _payload: True)
    monkeypatch.setattr(
        server, "_record_manual_score_state",
        lambda *_args, **_kwargs: None)
    state_store.clear_state()
    machine_store.clear_state()
    with server.state_lock:
        server.lane_scoring.clear()
        server.ball_counters.clear()
        server.pending_foul.clear()
        server._last_ball_at.clear()
    try:
        yield sent
    finally:
        with server._BACKUP_FENCE_GUARD:
            if server._BACKUP_FENCE is not None:
                server._release_backup_fence_locked("test_cleanup")


def _request(origin, method, path, body=None, token=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{origin}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("X-Lane-Token", token)
    for key, value in (headers or {}).items():
        request.add_header(key, str(value))
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    with response:
        return response.status, json.loads(
            response.read().decode("utf-8"))


def _raw_request(origin, method, path, raw):
    request = urllib.request.Request(
        f"{origin}{path}", data=raw.encode("utf-8"), method=method)
    request.add_header("Content-Type", "application/json")
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    with response:
        return response.status, json.loads(
            response.read().decode("utf-8"))


def _open(origin, lane, generation, bowlers, send=True):
    return _request(origin, "POST", f"/api/lane/{lane}/open", {
        "bowlers": bowlers,
        "send_open_command": send,
        "session_generation": generation,
    })


def _league_body(left=21, right=22, generations=None, send=True):
    return {
        "team1_bowlers": ["ALICE"],
        "team2_bowlers": ["BOB"],
        "team1_name": "LEFT",
        "team2_name": "RIGHT",
        "send_open_command": send,
        "session_generations": generations or {
            str(left): 1, str(right): 1},
    }


def _age_generation_rows(lanes, age_s=3600):
    updated_at = time.time() - age_s
    with sqlite3.connect(state_store.DB_PATH) as conn:
        conn.executemany(
            "UPDATE lane_session_generations SET updated_at=? "
            "WHERE lane_id=?",
            [(updated_at, lane) for lane in lanes])
        conn.commit()
    return updated_at


def _record_pending_manual(lane, scoring_epoch, event_id):
    now = time.time()
    frame = {
        "type": server.Msg.BALL_EVENT,
        "ts": now,
        "lane": lane,
        "pin_mask": None,
        "awaiting_manual": True,
        "event_id": event_id,
        "event_created_at": now,
        "scoring_epoch": scoring_epoch,
    }
    state_store.record_scoring_event_receipt({
        "event_id": event_id,
        "node_id": f"node-{lane}",
        "lane_id": lane,
        "event_type": server.Msg.BALL_EVENT,
        "event_created_at": now,
        "payload": frame,
        "disposition": "awaiting_manual",
    })


class _FiniteWebSocket:
    def __init__(self, messages):
        self.remote_address = ("finite-test-node", 1234)
        self._messages = iter(messages)
        self.sent = []
        self.closed = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def close(self, code=None, reason=None):
        self.closed.append((code, reason))


def _node_hello(node, lanes):
    os.environ["WSL_SCORING_NODE_TOPOLOGY"] = f"{node}=21,22"
    return {
        "type": server.Msg.HELLO,
        "ts": time.time(),
        "node": node,
        "lanes": [21, 22] if lanes == [21] else lanes,
        "protocol_version": server.PROTOCOL_VERSION,
        "scoring_boot_id": f"{node}-boot",
        "scoring_session_id": f"{node}-session",
        "heartbeat_seq": 0,
        "scoring_mode": "manual",
        "camera_calibrated": False,
        "camera_ok": False,
        "camera_code": "manual",
        "outbox": {
            "cursor_ok": True,
            "error": False,
            "oldest_unsent_age_s": None,
            "backlog": 0,
            "backlog_bytes": 0,
            "pending_writes": 0,
            "dropped": 0,
            "quarantined": 0,
            "cycles_quarantined": 0,
            "post_errors": 0,
            "write_errors": 0,
            "sink_errors": 0,
            "scoring_event_queue_depth": 0,
            "scoring_event_queue_capacity": 128,
            "scoring_event_oldest_age_s": None,
            "scoring_capture_jobs": 0,
            "scoring_capture_oldest_age_s": None,
            "scoring_clock_observed": True,
            "scoring_clock_anomaly_latched": False,
            "scoring_clock_high_water_epoch": 1.0,
            "scoring_clock_observed_epoch": 1.0,
            "scoring_event_durable": True,
            "scoring_event_error": False,
            "scoring_event_overdue": False,
            "scoring_event_drops": 0,
            "scoring_event_expired": 0,
            "scoring_event_max_age_s": 30.0,
        },
        "node_ball_lockout_s": 8.0,
    }


def test_single_open_replay_conflict_close_and_empty_roster(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, opened = _open(http_origin, 21, 1, [])
    assert status == 200 and opened["ok"] is True
    epoch = opened["scoring_epoch"]
    scorer = server.lane_scoring[21]
    assert scorer.is_active is True
    assert scorer.bowlers == []  # explicit empty roster is not rewritten TEST
    assert state_store.lane_session_generation(21)["generation"] == 1
    assert sent[-1][1]["command_id"] == "open:21:1"
    assert sent[-1][1]["scoring_epoch"] == epoch
    assert opened["bowlers"] == []
    assert len(opened["request_fingerprint"]) == 64

    # Same generation and same desired state is a retry, not a reset.
    status, replay = _open(http_origin, 21, 1, [])
    assert status == 200 and replay["replayed"] is True
    assert replay["scoring_epoch"] == epoch
    assert replay["request_fingerprint"] == opened["request_fingerprint"]
    assert replay["bowlers"] == []
    assert server.lane_scoring[21] is scorer
    assert sent[-1][1]["command_id"] == "open:21:1"

    status, conflict = _open(http_origin, 21, 1, ["DIFFERENT"])
    assert status == 409
    assert conflict["error"] == "session_generation_payload_conflict"
    assert server.lane_scoring[21] is scorer

    status, closed = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})
    assert status == 200 and closed["ok"] is True
    assert 21 not in server.lane_scoring
    generation = state_store.lane_session_generation(21)
    assert bool(generation["active"]) is False
    assert sent[-1][1]["command_id"] == "close:21:1"

    status, replay_close = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})
    assert status == 200 and replay_close["replayed"] is True
    assert sent[-1][1]["command_id"] == "close:21:1"

    # A newer CLOSE is an ordering tombstone.  It is safe even when its OPEN
    # has not reached this server yet, and it makes that late OPEN stale.
    status, advanced_close = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 2})
    assert status == 200 and advanced_close["replayed"] is False
    assert sent[-1][1]["command_id"] == "close:21:2"
    generation = state_store.lane_session_generation(21)
    assert generation["generation"] == 2
    assert bool(generation["active"]) is False

    status, stale_open = _open(http_origin, 21, 2, ["LATE"])
    assert status == 409
    assert stale_open["error"] == "stale_or_retired_session_generation"
    assert 21 not in server.lane_scoring

    status, stale_close = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})
    assert status == 409
    assert stale_close["error"] == "stale_session_generation"


def test_close_before_first_open_persists_monotonic_tombstone(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, closed = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 7})
    assert status == 200
    assert closed["ok"] is True
    assert closed["replayed"] is False
    assert closed["closed_lanes"] == [21]
    assert closed["session_generations"] == {"21": 7}
    assert len(closed["request_fingerprint"]) == 64
    assert closed["expected_commands"] == 1
    assert closed["sent_close_commands"] == 1
    assert sent[-1][1]["command_id"] == "close:21:7"

    row = state_store.lane_session_generation(21)
    assert row["generation"] == 7
    assert bool(row["active"]) is False
    assert bool(row["open_actuation_authorized"]) is False

    status, late = _open(http_origin, 21, 7, ["TOO LATE"])
    assert status == 409
    assert late["error"] == "stale_or_retired_session_generation"

    status, replay = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 7})
    assert status == 200
    assert replay["replayed"] is True
    assert replay["session_generations"] == {"21": 7}
    assert replay["request_fingerprint"] == closed["request_fingerprint"]
    assert sent[-1][1]["command_id"] == "close:21:7"


def test_newer_close_dominates_an_older_active_generation(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, opened = _open(http_origin, 21, 3, ["ACTIVE"])
    assert status == 200
    original = server.lane_scoring[21]
    original.record_ball(0)
    sent.clear()

    status, closed = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 4})
    assert status == 200
    assert closed["ok"] is True
    assert closed["replayed"] is False
    assert closed["session_generation"] == 4
    assert sent[-1][1]["command_id"] == "close:21:4"
    assert 21 not in server.lane_scoring

    row = state_store.lane_session_generation(21)
    assert row["generation"] == 4
    assert bool(row["active"]) is False
    assert bool(row["open_actuation_authorized"]) is False

    status, delayed = _open(http_origin, 21, 3, ["ACTIVE"])
    assert status == 409
    assert delayed["error"] == "stale_or_retired_session_generation"


def test_missing_server_auth_refuses_all_mutation_even_on_bench_routes(
        http_origin, isolated_server_state, monkeypatch):
    monkeypatch.setattr(server, "AUTH_TOKEN", "")
    monkeypatch.setattr(server, "ALLOW_UNAUTHENTICATED_BENCH", False)
    status, body = _open(
        http_origin, 21, 1, ["A"], send=False)
    assert status == 503
    assert body["error"] == "LANE_NODE_TOKEN is not configured"
    assert server.lane_scoring == {}
    assert state_store.lane_session_generation(21) is None


def test_backup_fence_is_authenticated_quiescent_and_cross_store(
        http_origin, isolated_server_state, monkeypatch):
    token = "backup-fence-test-token"
    monkeypatch.setattr(server, "AUTH_TOKEN", token)
    monkeypatch.setattr(
        machine_store, "configured_lanes", lambda: [21, 22])
    # This HTTP-only fixture has no production WS event loop.  The dedicated
    # gate test below exercises the real cross-thread asyncio acquisition.
    monkeypatch.setattr(
        server, "_acquire_ws_mutation_gate", lambda _timeout: "test-owner")
    monkeypatch.setattr(
        server, "_release_ws_mutation_gate",
        lambda _owner, timeout_s=server.BACKUP_FENCE_LOCK_TIMEOUT_S: True)

    fence_id = str(uuid.uuid4())
    acquire_body = {
        "fence_id": fence_id,
        "lease_seconds": 30,
        "expected_lanes": [21, 22],
    }
    status, unauthenticated = _request(
        http_origin, "POST", "/api/system/backup-fence/acquire",
        acquire_body)
    assert status == 401
    assert "unauthorized" in unauthenticated["error"]

    # An active session is a hard quiescence failure and must not leave locks.
    status, _ = _request(
        http_origin, "POST", "/api/lane/21/open", {
            "bowlers": ["ACTIVE"],
            "send_open_command": True,
            "session_generation": 1,
        }, token=token)
    assert status == 200
    status, busy = _request(
        http_origin, "POST", "/api/system/backup-fence/acquire",
        acquire_body, token=token)
    assert status == 409
    assert busy["error"] == "backup_fence_not_quiescent"
    assert any("lane 21 is open" in item for item in busy["errors"])
    assert server._BACKUP_FENCE is None

    status, _ = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1}, token=token)
    assert status == 200

    status, acquired = _request(
        http_origin, "POST", "/api/system/backup-fence/acquire",
        acquire_body, token=token)
    assert status == 200
    assert acquired["ok"] is True
    assert acquired["phase"] == "active"
    assert acquired["pending_mutations"] == 0
    assert acquired["lanes"]["21"]["generation_state"] == "retired"
    assert acquired["lanes"]["22"]["generation_state"] == "never_opened"
    assert (
        acquired["stores"]["lane_state"]["canonical_path"]
        == str(state_store.DB_PATH.resolve()))
    assert (
        acquired["stores"]["machine_diag"]["canonical_path"]
        == str(machine_store.DB_PATH.resolve()))
    for identity in acquired["stores"].values():
        assert len(identity["schema_sha256"]) == 64
        assert identity["schema_version"] > 0

    status, fenced = _request(
        http_origin, "GET", "/api/health")
    assert status == 503
    assert fenced["error"] == "backup_fence_active"

    started = threading.Event()
    lane_done = threading.Event()
    machine_done = threading.Event()

    def lane_writer():
        started.set()
        state_store.record_scoring_event_receipt({
            "event_id": "post-fence-lane-write",
            "node_id": "node-21",
            "lane_id": 21,
            "event_type": "foul_event",
            "event_created_at": time.time(),
            "payload": {"type": "foul_event"},
            "disposition": "accepted",
        })
        lane_done.set()

    def machine_writer():
        machine_store.insert_events([machine_store.validate_event({
            "lane_id": 21,
            "severity": "info",
            "event_type": "service_restart",
            "code": "post_fence_machine_write",
        })])
        machine_done.set()

    lane_thread = threading.Thread(target=lane_writer)
    machine_thread = threading.Thread(target=machine_writer)
    lane_thread.start()
    machine_thread.start()
    assert started.wait(timeout=1)
    time.sleep(0.05)
    assert lane_done.is_set() is False
    assert machine_done.is_set() is False

    status, verified = _request(
        http_origin, "POST", "/api/system/backup-fence/verify", {
            "fence_id": fence_id,
            "expected_lanes": [21, 22],
        }, token=token)
    assert status == 200
    assert verified["phase"] == "active"
    assert verified["stores"] == acquired["stores"]

    status, released = _request(
        http_origin, "POST", "/api/system/backup-fence/release", {
            "fence_id": fence_id,
        }, token=token)
    assert status == 200
    assert released == {
        "ok": True, "fence_id": fence_id, "released": True}
    lane_thread.join(timeout=2)
    machine_thread.join(timeout=2)
    assert lane_done.is_set() is True
    assert machine_done.is_set() is True


def test_backup_fence_rejects_state_outside_configured_topology(
        http_origin, isolated_server_state, monkeypatch):
    token = "backup-fence-test-token"
    monkeypatch.setattr(server, "AUTH_TOKEN", token)
    monkeypatch.setattr(
        machine_store, "configured_lanes", lambda: [21, 22])
    monkeypatch.setattr(
        server, "_acquire_ws_mutation_gate", lambda _timeout: "test-owner")
    monkeypatch.setattr(
        server, "_release_ws_mutation_gate",
        lambda _owner, timeout_s=server.BACKUP_FENCE_LOCK_TIMEOUT_S: True)

    status, opened = _request(
        http_origin, "POST", "/api/lane/23/open", {
            "bowlers": ["UNCONFIGURED"],
            "send_open_command": False,
            "session_generation": 1,
        }, token=token)
    assert status == 200
    _record_pending_manual(24, "orphan-epoch", "orphan-manual")
    state_store.record_scoring_event_receipt({
        "event_id": "orphan-foul",
        "node_id": "node-25",
        "lane_id": 25,
        "event_type": "foul_event",
        "event_created_at": time.time(),
        "payload": {"type": "foul_event"},
        "disposition": "accepted",
    })
    server.pending_foul[26] = True

    status, rejected = _request(
        http_origin, "POST", "/api/system/backup-fence/acquire", {
            "fence_id": str(uuid.uuid4()),
            "lease_seconds": 30,
            "expected_lanes": [21, 22],
        }, token=token)
    assert status == 409
    assert rejected["error"] == "backup_fence_not_quiescent"
    joined = " | ".join(rejected["errors"])
    assert "scoring state exists outside configured lanes" in joined
    assert "active durable generation outside configured lanes: 23" in joined
    assert "pending manual scores outside configured lanes: 24" in joined
    assert "pending foul state outside configured lanes: 25" in joined
    assert "process-local foul state is present" in joined
    assert server._BACKUP_FENCE is None


def test_backup_fence_verify_detects_out_of_band_database_mutation(
        http_origin, isolated_server_state, monkeypatch):
    token = "backup-fence-test-token"
    monkeypatch.setattr(server, "AUTH_TOKEN", token)
    monkeypatch.setattr(
        machine_store, "configured_lanes", lambda: [21, 22])
    monkeypatch.setattr(
        server, "_acquire_ws_mutation_gate", lambda _timeout: "test-owner")
    monkeypatch.setattr(
        server, "_release_ws_mutation_gate",
        lambda _owner, timeout_s=server.BACKUP_FENCE_LOCK_TIMEOUT_S: True)
    assert state_store.save_lanes({}, {}) is True

    fence_id = str(uuid.uuid4())
    status, acquired = _request(
        http_origin, "POST", "/api/system/backup-fence/acquire", {
            "fence_id": fence_id,
            "lease_seconds": 30,
            "expected_lanes": [21, 22],
        }, token=token)
    assert status == 200
    acquired_hash = acquired["stores"]["lane_state"]["content_sha256"]

    # Model a second process that bypasses this process's Python lock.
    with sqlite3.connect(state_store.DB_PATH) as conn:
        conn.execute(
            "UPDATE lane_state SET updated_at=updated_at+1 WHERE lane_id=0")
        conn.commit()

    status, rejected = _request(
        http_origin, "POST", "/api/system/backup-fence/verify", {
            "fence_id": fence_id,
            "expected_lanes": [21, 22],
        }, token=token)
    assert status == 409
    assert rejected["error"] == "backup_fence_store_identity_changed"
    assert (
        rejected["acquired_stores"]["lane_state"]["content_sha256"]
        == acquired_hash)
    assert (
        rejected["current_stores"]["lane_state"]["content_sha256"]
        != acquired_hash)
    assert server._BACKUP_FENCE is None


def test_backup_fence_blocks_pending_command_and_attests_incident_backlog(
        http_origin, isolated_server_state, monkeypatch):
    token = "backup-fence-safety-ledger-token"
    monkeypatch.setattr(server, "AUTH_TOKEN", token)
    monkeypatch.setattr(
        machine_store, "configured_lanes", lambda: [21, 22])
    monkeypatch.setattr(
        server, "_acquire_ws_mutation_gate", lambda _timeout: "test-owner")
    monkeypatch.setattr(
        server, "_release_ws_mutation_gate",
        lambda _owner, timeout_s=server.BACKUP_FENCE_LOCK_TIMEOUT_S: True)
    assert state_store.save_lanes({}, {}) is True

    state_store.enqueue_diagnostic_incident(
        "backup-evidence-incident", {
            "lane_id": 21,
            "severity": "warn",
            "event_type": "command_transport",
            "code": "backup_evidence_test",
            "detail": {"test": True},
        })
    state_store.begin_background_command_delivery({
        "command_id": "backup-pending-command",
        "event_id": "backup-pending-event",
        "lane_id": 21,
        "command_type": server.Msg.CYCLE,
        "owner_boot_id": server.SERVER_BOOT_ID,
        "issued_at": time.time(),
        "deadline_monotonic": time.monotonic() + 30.0,
    })

    fence_id = str(uuid.uuid4())
    body = {
        "fence_id": fence_id,
        "lease_seconds": 30,
        "expected_lanes": [21, 22],
    }
    status, rejected = _request(
        http_origin, "POST", "/api/system/backup-fence/acquire",
        body, token=token)
    assert status == 409
    assert rejected["pending_mutations"] == 1
    assert rejected["safety_ledgers"] == {
        "diagnostic_incident_outbox_pending_count": 1,
        "background_command_deliveries_pending_count": 1,
    }
    assert any(
        "background command deliveries pending" in error
        for error in rejected["errors"])
    assert server._BACKUP_FENCE is None

    state_store.finalize_background_command_delivery(
        "backup-pending-command", "completed",
        ack_status="completed")
    status, acquired = _request(
        http_origin, "POST", "/api/system/backup-fence/acquire",
        body, token=token)
    assert status == 200
    assert acquired["pending_mutations"] == 0
    assert acquired["safety_ledgers"] == {
        "diagnostic_incident_outbox_pending_count": 1,
        "background_command_deliveries_pending_count": 0,
    }

    status, released = _request(
        http_origin, "POST", "/api/system/backup-fence/release", {
            "fence_id": fence_id,
        }, token=token)
    assert status == 200
    assert released["released"] is True


def test_trigger_ball_validates_body_before_scoring(
        http_origin, isolated_server_state, monkeypatch):
    monkeypatch.setenv("WSL_ENABLE_TRIGGER_BALL", "1")
    status, _opened = _open(http_origin, 21, 1, ["BENCH"])
    assert status == 200
    scorer = server.lane_scoring[21]

    def bowl_count():
        return sum(
            len(frame.bowls)
            for bowler in scorer.bowlers for frame in bowler.frames)

    status, no_body = _request(
        http_origin, "POST", "/api/lane/21/trigger-ball",
        headers={
            "X-Operation-Key": "bench-no-body",
            "X-Operation-Issued-At": time.time(),
        })
    assert status == 200
    assert no_body["replayed"] is False
    assert no_body["pin_mask_source"] == "cycle"
    assert bowl_count() == 1

    status, empty_body = _request(
        http_origin, "POST", "/api/lane/21/trigger-ball", {},
        headers={
            "X-Operation-Key": "bench-empty-body",
            "X-Operation-Issued-At": time.time(),
        })
    assert status == 200
    assert empty_body["replayed"] is False
    assert bowl_count() == 2

    before = bowl_count()
    status, invalid = _request(
        http_origin, "POST", "/api/lane/21/trigger-ball",
        {"pin_mask": True},
        headers={
            "X-Operation-Key": "bench-bool-mask",
            "X-Operation-Issued-At": time.time(),
        })
    assert status == 400
    assert invalid["error"] == "pin_mask must be int 0-1023 or null"
    assert bowl_count() == before
    assert (
        state_store.bench_ball_operation_receipt("bench-bool-mask")
        is None)


def test_trigger_ball_lost_response_retry_is_exactly_once_and_bound(
        http_origin, isolated_server_state, monkeypatch):
    monkeypatch.setenv("WSL_ENABLE_TRIGGER_BALL", "1")
    status, opened = _open(http_origin, 21, 1, ["BENCH"])
    assert status == 200
    scorer = server.lane_scoring[21]
    sent = []
    delivery_results = iter([0, 1])

    def deliver(lane, raw):
        sent.append((lane, json.loads(raw)))
        return next(delivery_results)

    monkeypatch.setattr(server, "send_to_lane", deliver)
    issued_at = f"{time.time():.6f}"
    headers = {
        "X-Operation-Key": "bench-lost-response",
        "X-Operation-Issued-At": issued_at,
    }
    body = {"pin_mask": 0, "foul": False}
    status, first = _request(
        http_origin, "POST", "/api/lane/21/trigger-ball",
        body, headers=headers)
    assert status == 503
    assert first["reconciliation_required"] is True
    assert first["replayed"] is False
    bowls_after_first = sum(
        len(frame.bowls)
        for bowler in scorer.bowlers for frame in bowler.frames)
    assert bowls_after_first == 1

    status, replay = _request(
        http_origin, "POST", "/api/lane/21/trigger-ball",
        body, headers=headers)
    assert status == 200
    assert replay["replayed"] is True
    assert replay["reconciliation_required"] is False
    assert replay["request_fingerprint"] == first["request_fingerprint"]
    assert replay["scoring_epoch"] == opened["scoring_epoch"]
    assert sum(
        len(frame.bowls)
        for bowler in scorer.bowlers for frame in bowler.frames
    ) == bowls_after_first
    assert [frame["command_id"] for _, frame in sent] == [
        "trigger-ball:21:bench-lost-response",
        "trigger-ball:21:bench-lost-response",
    ]

    receipt = state_store.bench_ball_operation_receipt(
        "bench-lost-response")
    assert receipt["request_fingerprint"] == first["request_fingerprint"]
    assert receipt["session_generation"] == 1
    assert receipt["scoring_epoch"] == opened["scoring_epoch"]
    assert receipt["result"]["pin_mask"] == 0

    status, conflict = _request(
        http_origin, "POST", "/api/lane/21/trigger-ball",
        {"pin_mask": 1, "foul": False}, headers=headers)
    assert status == 409
    assert conflict["error"] == "trigger_ball_idempotency_conflict"
    assert sum(
        len(frame.bowls)
        for bowler in scorer.bowlers for frame in bowler.frames
    ) == bowls_after_first


def test_ws_backup_gate_timeout_boundary_releases_owned_lock(monkeypatch):
    """A caller-side timeout after acquisition must not wedge WS traffic."""
    loop = asyncio.new_event_loop()
    loop_started = threading.Event()

    def run_loop():
        asyncio.set_event_loop(loop)
        loop_started.set()
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    assert loop_started.wait(timeout=1)

    monkeypatch.setattr(server, "main_loop", loop)
    monkeypatch.setattr(server, "_ws_mutation_gate", None)
    monkeypatch.setattr(server, "_ws_mutation_gate_owner", None)
    real_submit = asyncio.run_coroutine_threadsafe
    submissions = 0

    class BoundaryTimeout:
        def __init__(self, inner):
            self.inner = inner

        def result(self, timeout=None):
            # The event-loop task has acquired the gate, but emulate the
            # concurrent Future deadline winning immediately afterward.
            self.inner.result(timeout=timeout)
            raise TimeoutError("simulated timeout at ownership handoff")

        def cancel(self):
            return self.inner.cancel()

    def submit(coro, target_loop):
        nonlocal submissions
        submissions += 1
        inner = real_submit(coro, target_loop)
        if submissions == 1:
            return BoundaryTimeout(inner)
        return inner

    monkeypatch.setattr(server.asyncio, "run_coroutine_threadsafe", submit)
    try:
        with pytest.raises(
                TimeoutError, match="simulated timeout at ownership handoff"):
            server._acquire_ws_mutation_gate(1)
        assert server._ws_mutation_gate_owner is None

        owner = server._acquire_ws_mutation_gate(1)
        assert isinstance(owner, str) and owner
        assert server._ws_mutation_gate_owner == owner
        assert server._release_ws_mutation_gate(owner, timeout_s=1) is True
        assert server._ws_mutation_gate_owner is None
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


def test_backup_fence_expiry_is_monotonic_across_wall_clock_rollback(
        monkeypatch):
    fence_id = str(uuid.uuid4())
    fence = {
        "fence_id": fence_id,
        "phase": "active",
        "acquired_at_epoch": 5000.0,
        # The advertised wall deadline now appears far in the future after a
        # clock rollback, while the process-local monotonic lease has elapsed.
        "expires_at_epoch": 5030.0,
        "expires_at_monotonic": 99.0,
        "expected_lanes": [],
        "lanes": {},
        "pending_mutations": 0,
        "ws_gate": False,
        "ws_gate_token": None,
        "state_lock": False,
        "state_db_lock": False,
        "machine_lock": False,
        "timer": None,
    }
    monkeypatch.setattr(
        server, "time",
        types.SimpleNamespace(time=lambda: 1000.0, monotonic=lambda: 100.0))
    with server._BACKUP_FENCE_GUARD:
        server._BACKUP_FENCE = fence

    server._expire_backup_fence(fence_id)

    assert server._BACKUP_FENCE is None
    assert fence["released_reason"] == "lease_expired"


@pytest.mark.parametrize("missing", [
    "bowlers", "send_open_command", "session_generation"])
def test_single_open_requires_exact_generation_control_shape(
        http_origin, missing):
    body = {
        "bowlers": ["A"],
        "send_open_command": True,
        "session_generation": 1,
    }
    body.pop(missing)
    status, response = _request(
        http_origin, "POST", "/api/lane/21/open", body)
    assert status == 400
    assert response["error"] == "invalid open body fields"
    assert 21 not in server.lane_scoring
    assert state_store.lane_session_generation(21) is None


def test_open_commits_then_same_generation_reconciles_after_no_owner(
        http_origin, monkeypatch):
    monkeypatch.setattr(server, "send_to_lane", lambda _lane, _raw: 0)
    status, pending = _open(http_origin, 21, 1, ["A"])
    assert status == 503
    assert pending["ok"] is False
    assert pending["reconciliation_required"] is True
    scorer = server.lane_scoring[21]
    epoch = scorer.scoring_epoch
    generation = state_store.lane_session_generation(21)
    assert bool(generation["active"]) is True

    delivered = []

    def deliver(lane, raw):
        delivered.append((lane, json.loads(raw)))
        return 1

    monkeypatch.setattr(server, "send_to_lane", deliver)
    status, replay = _open(http_origin, 21, 1, ["A"])
    assert status == 200
    assert replay["replayed"] is True
    assert replay["reconciliation_required"] is False
    assert server.lane_scoring[21] is scorer
    assert replay["scoring_epoch"] == epoch
    assert delivered[0][1]["command_id"] == "open:21:1"


def test_state_only_open_requires_epoch_sync_not_physical_open(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, body = _open(
        http_origin, 21, 1, ["A"], send=False)
    assert status == 200 and body["ok"] is True
    assert body["hardware_command_sent"] is False
    assert body["msg"]["type"] == server.Msg.SCORING_EPOCH_SYNC
    assert sent == [(21, body["msg"])]
    assert sent[0][1]["command_id"] == "sync:21:1"
    assert sent[0][1]["scoring_epoch"] == body["scoring_epoch"]
    assert sent[0][1]["session_generation"] == 1


def test_state_only_open_repair_renews_only_sync_authorization(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, opened = _open(
        http_origin, 21, 1, ["A"], send=False)
    assert status == 200
    first = sent[-1][1]
    old_updated_at = _age_generation_rows([21])
    sent.clear()

    status, replay = _open(
        http_origin, 21, 1, ["A"], send=False)
    assert status == 200 and replay["replayed"] is True
    renewed = sent[-1][1]
    assert renewed["command_id"] == first["command_id"] == "sync:21:1"
    assert renewed["session_generation"] == 1
    assert renewed["scoring_epoch"] == first["scoring_epoch"]
    assert renewed["issued_at"] > old_updated_at + 600

    # The same durable generation never receives renewed physical authority.
    status, escalation = _open(
        http_origin, 21, 1, ["A"], send=True)
    assert status == 409
    assert escalation["error"] == "open_actuation_intent_escalation"
    assert len(sent) == 1


def test_state_only_new_generation_may_supersede_stale_active_state(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, first = _open(http_origin, 21, 1, ["OLD"], send=True)
    assert status == 200
    first_scorer = server.lane_scoring[21]

    status, conflict = _open(
        http_origin, 21, 2, ["NEW"], send=True)
    assert status == 409
    assert conflict["error"] == "active_session_generation_conflict"
    assert server.lane_scoring[21] is first_scorer

    sent.clear()
    status, repaired = _open(
        http_origin, 21, 2, ["NEW"], send=False)
    assert status == 200 and repaired["replayed"] is False
    assert repaired["hardware_command_sent"] is False
    assert repaired["scoring_epoch"] != first["scoring_epoch"]
    assert [b.name for b in server.lane_scoring[21].bowlers] == ["NEW"]
    assert sent[0][1]["type"] == server.Msg.SCORING_EPOCH_SYNC
    assert sent[0][1]["command_id"] == "sync:21:2"


@pytest.mark.parametrize("missing", [
    "team1_bowlers", "team2_bowlers", "team1_name", "team2_name",
    "send_open_command", "session_generations"])
def test_league_open_requires_exact_desired_state_shape(
        http_origin, missing):
    body = _league_body()
    body.pop(missing)
    status, response = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", body)
    assert status == 400
    assert response["error"] == "invalid open-league body fields"
    assert server.lane_scoring == {}


def test_league_roster_metadata_is_bounded_and_finite(http_origin):
    body = _league_body()
    body["team1_bowlers"] = [{
        "name": "ALICE",
        "current_avg": float("nan"),
    }]
    status, response = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", body)
    assert status == 400
    assert response["error"] == "invalid JSON body"

    body = _league_body()
    body["team1_bowlers"] = [{
        "name": "ALICE",
        "current_avg": 180,
        "unexpected": "field",
    }]
    status, response = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", body)
    assert status == 400
    assert response["error"] == "invalid bowler fields"


def test_league_state_only_new_generations_supersede_stale_pair(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, first = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        _league_body())
    assert status == 200
    first_scorer = server.lane_scoring[21]
    next_generations = {"21": 2, "22": 2}

    status, conflict = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        _league_body(generations=next_generations, send=True))
    assert status == 409
    assert conflict["error"] == "active_session_generation_conflict"
    assert server.lane_scoring[21] is first_scorer

    sent.clear()
    status, repaired = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        _league_body(generations=next_generations, send=False))
    assert status == 200 and repaired["replayed"] is False
    assert repaired["hardware_command_sent"] is False
    assert repaired["scoring_epoch"] != first["scoring_epoch"]
    assert repaired["sent_epoch_sync_commands"] == 2
    assert {frame["command_id"] for _, frame in sent} == {
        "sync:21:2", "sync:22:2"}


def test_league_state_only_repair_renews_syncs_without_actuation_escalation(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    request = _league_body(send=False)
    status, opened = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", request)
    assert status == 200
    first = {lane: frame for lane, frame in sent}
    old_updated_at = _age_generation_rows([21, 22])
    sent.clear()

    status, replay = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", request)
    assert status == 200 and replay["replayed"] is True
    assert replay["sent_epoch_sync_commands"] == 2
    for lane, frame in sent:
        assert frame["command_id"] == f"sync:{lane}:1"
        assert frame["session_generation"] == 1
        assert frame["scoring_epoch"] == first[lane]["scoring_epoch"]
        assert frame["issued_at"] > old_updated_at + 600

    escalated = dict(request, send_open_command=True)
    status, response = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", escalated)
    assert status == 409
    assert response["error"] == "open_actuation_intent_escalation"
    assert len(sent) == 2


def test_league_replay_preserves_shared_scorer_and_pair_close_acks_both(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    request = _league_body()
    status, opened = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", request)
    assert status == 200 and opened["sent_open_commands"] == 2
    assert len(opened["request_fingerprint"]) == 64
    assert opened["team1_bowlers"] == ["ALICE"]
    assert opened["team2_bowlers"] == ["BOB"]
    scorer = server.lane_scoring[21]
    assert server.lane_scoring[22] is scorer
    epoch = scorer.scoring_epoch
    scorer.record_ball_for_lane(21, 0)
    bowls_before = len(scorer.bowlers[0].frames[0].bowls)

    status, replay = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", request)
    assert status == 200 and replay["replayed"] is True
    assert replay["request_fingerprint"] == opened["request_fingerprint"]
    assert replay["team1_name"] == "LEFT"
    assert replay["team2_name"] == "RIGHT"
    assert replay["team1_bowlers"] == ["ALICE"]
    assert replay["team2_bowlers"] == ["BOB"]
    assert server.lane_scoring[21] is scorer
    assert server.lane_scoring[22] is scorer
    assert scorer.scoring_epoch == epoch
    assert len(scorer.bowlers[0].frames[0].bowls) == bowls_before

    conflict_request = dict(request)
    conflict_request["team1_bowlers"] = ["NOT-ALICE"]
    status, conflict = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        conflict_request)
    assert status == 409
    assert conflict["error"] == "session_generation_payload_conflict"

    sent.clear()
    status, closed = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})
    assert status == 200 and closed["ok"] is True
    assert closed["expected_commands"] == 2
    assert closed["sent_close_commands"] == 2
    assert closed["closed_lanes"] == [21, 22]
    assert closed["session_generations"] == {"21": 1, "22": 1}
    assert len(closed["request_fingerprint"]) == 64
    assert {lane for lane, _ in sent} == {21, 22}
    assert {frame["command_id"] for _, frame in sent} == {
        "close:21:1", "close:22:1"}
    assert 21 not in server.lane_scoring
    assert 22 not in server.lane_scoring
    assert not bool(state_store.lane_session_generation(21)["active"])
    assert not bool(state_store.lane_session_generation(22)["active"])

    # Once the shared scorer is removed, a retry must still reconstruct and
    # verify both stable CLOSE commands from durable generation metadata.
    sent.clear()
    status, replay_close = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})
    assert status == 200 and replay_close["replayed"] is True
    assert replay_close["expected_commands"] == 2
    assert replay_close["closed_lanes"] == [21, 22]
    assert replay_close["session_generations"] == {"21": 1, "22": 1}
    assert (
        replay_close["request_fingerprint"]
        == closed["request_fingerprint"])
    assert {frame["command_id"] for _, frame in sent} == {
        "close:21:1", "close:22:1"}


def test_pair_close_commit_failure_restores_volatile_ordering_state(
        http_origin, isolated_server_state, monkeypatch):
    sent = isolated_server_state
    status, _opened = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        _league_body())
    assert status == 200
    sent.clear()

    server.pending_foul.update({21: True, 22: True})
    server._last_ball_at.update({21: 101.25, 22: 202.5})

    def fail_after_concurrent_ball(*_args, **_kwargs):
        # Model a newer WebSocket observation arriving while the transactional
        # pending-manual guard rejects CLOSE. Rollback must not overwrite it
        # with the older pre-close dedup timestamp.
        server._last_ball_at[21] = 303.75
        return False

    monkeypatch.setattr(server, "save_lanes", fail_after_concurrent_ball)

    status, failed = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})

    assert status == 503
    assert failed["error"] == "close_state_commit_failed"
    assert sent == []
    assert server.lane_scoring[21] is server.lane_scoring[22]
    assert server.lane_scoring[21].is_active is True
    assert server.pending_foul == {21: True, 22: True}
    assert server._last_ball_at == {21: 303.75, 22: 202.5}
    assert bool(state_store.lane_session_generation(21)["active"]) is True
    assert bool(state_store.lane_session_generation(22)["active"]) is True


def test_newer_pair_close_replays_same_mixed_generation_command_identities(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, _opened = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        _league_body())
    assert status == 200
    sent.clear()

    status, closed = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 3})
    assert status == 200
    assert closed["closed_lanes"] == [21, 22]
    assert closed["session_generations"] == {"21": 3, "22": 1}
    assert len(closed["request_fingerprint"]) == 64
    first = {lane: frame for lane, frame in sent}
    assert first[21]["command_id"] == "close:21:3"
    assert first[22]["command_id"] == "close:22:1"
    row_21 = state_store.lane_session_generation(21)
    row_22 = state_store.lane_session_generation(22)
    assert row_21["generation"] == 3 and not bool(row_21["active"])
    assert row_22["generation"] == 1 and not bool(row_22["active"])
    assert row_21["session_group_id"] == row_22["session_group_id"]

    # A retry through either member of the retired group reconstructs each
    # lane's own immutable command identity and authorization timestamp.
    sent.clear()
    status, replay = _request(
        http_origin, "POST", "/api/lane/22/close",
        {"session_generation": 1})
    assert status == 200 and replay["replayed"] is True
    assert replay["closed_lanes"] == [21, 22]
    repeated = {lane: frame for lane, frame in sent}
    for lane in (21, 22):
        assert repeated[lane]["command_id"] == first[lane]["command_id"]
        assert repeated[lane]["issued_at"] == first[lane]["issued_at"]
        assert repeated[lane]["scoring_epoch"] is None

    status, stale_open = _open(http_origin, 21, 3, ["LATE"])
    assert status == 409
    assert stale_open["error"] == "stale_or_retired_session_generation"


def test_pair_close_is_blocked_by_pending_manual_work_on_partner(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, opened = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        _league_body())
    assert status == 200
    scorer = server.lane_scoring[21]
    _record_pending_manual(
        22, opened["scoring_epoch"], "partner-close-pending")
    sent.clear()

    status, blocked = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})

    assert status == 409
    assert blocked["error"] == "pending_manual_scoring_reconciliation"
    assert blocked["pending_manual_scores"][0]["lane"] == 22
    assert server.lane_scoring[21] is scorer
    assert server.lane_scoring[22] is scorer
    assert bool(state_store.lane_session_generation(21)["active"]) is True
    assert bool(state_store.lane_session_generation(22)["active"]) is True
    assert sent == []


def test_pair_transfer_rekeys_same_object_and_is_idempotent(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, _ = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        _league_body())
    assert status == 200
    scorer = server.lane_scoring[21]
    epoch = scorer.scoring_epoch
    bowl = scorer.record_ball_for_lane(21, 0x001)
    assert bowl is not None
    preserved_display = bowl.display
    sent.clear()

    transfer = {
        "from_lane": 21,
        "to_lane": 23,
        "paired_from": 22,
        "paired_to": 24,
        "session_generations": {
            "21": 1, "22": 1, "23": 1, "24": 1},
        "send_hardware_commands": True,
    }
    status, moved = _request(
        http_origin, "POST", "/api/lane/transfer", transfer)
    assert status == 200 and moved["ok"] is True
    assert moved["sent_close_commands"] == 2
    assert moved["sent_open_commands"] == 2
    assert moved["scoring_epoch"] == epoch
    assert len(moved["request_fingerprint"]) == 64
    assert 21 not in server.lane_scoring
    assert 22 not in server.lane_scoring
    assert server.lane_scoring[23] is scorer
    assert server.lane_scoring[24] is scorer
    assert scorer.lane_ids == [23, 24]
    assert scorer.bowlers[0].frames[0].bowls[0].display == preserved_display
    assert set(scorer._lane_queues) == {23, 24}
    assert {lane for lane, _ in sent} == {21, 22, 23, 24}
    first_command_ids = {frame["command_id"] for _, frame in sent}

    scorer_id = id(scorer)
    sent.clear()
    status, replay = _request(
        http_origin, "POST", "/api/lane/transfer", transfer)
    assert status == 200 and replay["replayed"] is True
    assert replay["request_fingerprint"] == moved["request_fingerprint"]
    assert id(server.lane_scoring[23]) == scorer_id
    assert server.lane_scoring[24] is server.lane_scoring[23]
    assert len(server.lane_scoring[23].bowlers[0].frames[0].bowls) == 1
    assert {frame["command_id"] for _, frame in sent} == first_command_ids

    # Transfer targets retain explicit topology separate from the operation
    # fingerprint, so a later paired CLOSE remains replayable after the scorer
    # object has been removed.
    sent.clear()
    status, closed = _request(
        http_origin, "POST", "/api/lane/23/close",
        {"session_generation": 1})
    assert status == 200 and closed["closed_lanes"] == [23, 24]
    sent.clear()
    status, replay_closed = _request(
        http_origin, "POST", "/api/lane/23/close",
        {"session_generation": 1})
    assert status == 200 and replay_closed["replayed"] is True
    assert replay_closed["closed_lanes"] == [23, 24]
    assert {frame["command_id"] for _, frame in sent} == {
        "close:23:1", "close:24:1"}


def test_transfer_commits_once_then_reconciles_missing_command_acks(
        http_origin, monkeypatch):
    status, _ = _open(http_origin, 21, 1, ["A"])
    assert status == 200
    scorer = server.lane_scoring[21]
    epoch = scorer.scoring_epoch
    transfer = {
        "from_lane": 21,
        "to_lane": 23,
        "paired_from": None,
        "paired_to": None,
        "session_generations": {"21": 1, "23": 1},
        "send_hardware_commands": True,
    }
    attempts = []

    def lose_target_ack(lane, raw):
        attempts.append((lane, json.loads(raw)))
        return 0 if lane == 23 else 1

    monkeypatch.setattr(server, "send_to_lane", lose_target_ack)
    status, pending = _request(
        http_origin, "POST", "/api/lane/transfer", transfer)
    assert status == 503
    assert pending["ok"] is False
    assert pending["reconciliation_required"] is True
    assert pending["sent_close_commands"] == 1
    assert pending["sent_open_commands"] == 0
    assert 21 not in server.lane_scoring
    assert server.lane_scoring[23] is scorer
    assert scorer.scoring_epoch == epoch
    first_ids = {frame["command_id"] for _, frame in attempts}

    attempts.clear()
    monkeypatch.setattr(
        server, "send_to_lane",
        lambda lane, raw: attempts.append(
            (lane, json.loads(raw))) or 1)
    status, replay = _request(
        http_origin, "POST", "/api/lane/transfer", transfer)
    assert status == 200
    assert replay["replayed"] is True
    assert replay["reconciliation_required"] is False
    assert server.lane_scoring[23] is scorer
    assert {frame["command_id"] for _, frame in attempts} == first_ids

    attempts.clear()
    changed_intent = dict(transfer, send_hardware_commands=False)
    status, conflict = _request(
        http_origin, "POST", "/api/lane/transfer", changed_intent)
    assert status == 409
    assert conflict["error"] == "transfer_source_generation_mismatch"
    assert attempts == []


def test_state_only_transfer_replay_renews_epoch_sync_authorization(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, opened = _open(http_origin, 21, 1, ["A"])
    assert status == 200
    epoch = opened["scoring_epoch"]
    sent.clear()
    transfer = {
        "from_lane": 21,
        "to_lane": 23,
        "paired_from": None,
        "paired_to": None,
        "session_generations": {"21": 1, "23": 1},
        "send_hardware_commands": False,
    }
    status, moved = _request(
        http_origin, "POST", "/api/lane/transfer", transfer)
    assert status == 200 and moved["sent_epoch_sync_commands"] == 2
    first = {lane: frame for lane, frame in sent}
    old_updated_at = _age_generation_rows([21, 23])
    sent.clear()

    status, replay = _request(
        http_origin, "POST", "/api/lane/transfer", transfer)
    assert status == 200 and replay["replayed"] is True
    assert replay["sent_epoch_sync_commands"] == 2
    for lane, frame in sent:
        assert frame["command_id"] == first[lane]["command_id"]
        assert frame["session_generation"] == 1
        assert frame["scoring_epoch"] == (
            None if lane == 21 else epoch)
        assert frame["issued_at"] > old_updated_at + 600


def test_pending_manual_work_blocks_topology_until_scored(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    status, opened = _open(http_origin, 21, 1, ["A"])
    assert status == 200
    original = server.lane_scoring[21]
    original_epoch = opened["scoring_epoch"]
    _record_pending_manual(21, original_epoch, "manual-before-transition")
    sent.clear()

    status, blocked_open = _open(
        http_origin, 21, 2, ["B"], send=False)
    assert status == 409
    assert blocked_open["error"] == (
        "pending_manual_scoring_reconciliation")
    assert blocked_open["pending_manual_scores"] == [{
        "lane": 21,
        "event_id": "manual-before-transition",
        "event_created_at":
            blocked_open["pending_manual_scores"][0]["event_created_at"],
        "scoring_epoch": original_epoch,
    }]
    assert server.lane_scoring[21] is original
    assert state_store.lane_session_generation(21)["generation"] == 1
    assert sent == []

    status, blocked_close = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})
    assert status == 409
    assert blocked_close["error"] == (
        "pending_manual_scoring_reconciliation")
    assert server.lane_scoring[21] is original

    status, scored = _request(
        http_origin, "POST", "/api/lane/21/score",
        {"event_id": "manual-before-transition", "pin_mask": 0})
    assert status == 200 and scored["ok"] is True
    assert state_store.pending_manual_events(21) == []

    status, repaired = _open(
        http_origin, 21, 2, ["B"], send=False)
    assert status == 200 and repaired["session_generation"] == 2


def test_pending_manual_work_can_be_audited_without_inventing_score(
        http_origin, isolated_server_state):
    status, opened = _open(http_origin, 21, 1, ["A"])
    assert status == 200
    original_epoch = opened["scoring_epoch"]
    _record_pending_manual(
        21, original_epoch, "manual-false-trigger")

    resolution_body = {
        "event_id": "manual-false-trigger",
        "actor_id": 17,
        "disposition": "false_trigger_discarded",
        "note": "Mechanic beam test; no ball was delivered.",
    }
    status, resolved = _request(
        http_origin, "POST", "/api/lane/21/score/resolve",
        resolution_body)
    assert status == 200
    assert resolved["ok"] is True
    assert resolved["replayed"] is False
    assert resolved["resolution"]["actor_id"] == 17
    assert resolved["resolution"]["disposition"] == (
        "false_trigger_discarded")
    assert state_store.pending_manual_events(21) == []

    status, replay = _request(
        http_origin, "POST", "/api/lane/21/score/resolve",
        resolution_body)
    assert status == 200
    assert replay["replayed"] is True
    assert replay["resolution"]["created_at"] == (
        resolved["resolution"]["created_at"])

    status, conflict = _request(
        http_origin, "POST", "/api/lane/21/score/resolve", {
            **resolution_body,
            "disposition": "session_abandoned",
            "note": "Different disposition.",
        })
    assert status == 409
    assert conflict["error"] == (
        "manual_score_resolution_idempotency_conflict")

    status, score_after_resolution = _request(
        http_origin, "POST", "/api/lane/21/score", {
            "event_id": "manual-false-trigger",
            "pin_mask": 0,
        })
    assert status == 409
    assert score_after_resolution["error"] == (
        "manual_scoring_event_resolved_without_score")

    status, closed = _request(
        http_origin, "POST", "/api/lane/21/close",
        {"session_generation": 1})
    assert status == 200
    assert closed["ok"] is True


def test_pending_manual_on_partner_blocks_league_replacement_but_is_scoreable(
        http_origin, isolated_server_state):
    sent = isolated_server_state
    request = _league_body()
    status, opened = _request(
        http_origin, "POST", "/api/pair/21-22/open-league", request)
    assert status == 200
    scorer = server.lane_scoring[21]
    epoch = opened["scoring_epoch"]
    _record_pending_manual(22, epoch, "league-manual-pending")
    sent.clear()

    replacement = _league_body(
        generations={"21": 2, "22": 2}, send=False)
    status, blocked = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        replacement)
    assert status == 409
    assert blocked["error"] == "pending_manual_scoring_reconciliation"
    assert blocked["pending_manual_scores"][0]["lane"] == 22
    assert blocked["pending_manual_scores"][0]["event_id"] == (
        "league-manual-pending")
    assert server.lane_scoring[21] is scorer
    assert server.lane_scoring[22] is scorer
    assert state_store.lane_session_generation(21)["generation"] == 1
    assert sent == []

    status, scored = _request(
        http_origin, "POST", "/api/lane/22/score",
        {"event_id": "league-manual-pending", "pin_mask": 0})
    assert status == 200 and scored["ok"] is True
    status, replaced = _request(
        http_origin, "POST", "/api/pair/21-22/open-league",
        replacement)
    assert status == 200
    assert replaced["session_generations"] == {"21": 2, "22": 2}


def test_topology_mutations_clear_ball_dedup_only_on_new_transition(
        http_origin, isolated_server_state):
    server._last_ball_at[21] = 1.0
    status, _ = _open(http_origin, 21, 1, ["A"])
    assert status == 200
    assert 21 not in server._last_ball_at

    server._last_ball_at[21] = 2.0
    status, replay = _open(http_origin, 21, 1, ["A"])
    assert status == 200 and replay["replayed"] is True
    assert server._last_ball_at[21] == 2.0

    transfer = {
        "from_lane": 21,
        "to_lane": 23,
        "paired_from": None,
        "paired_to": None,
        "session_generations": {"21": 1, "23": 1},
        "send_hardware_commands": False,
    }
    server._last_ball_at[23] = 3.0
    status, _ = _request(
        http_origin, "POST", "/api/lane/transfer", transfer)
    assert status == 200
    assert 21 not in server._last_ball_at
    assert 23 not in server._last_ball_at

    server._last_ball_at[23] = 4.0
    status, replay = _request(
        http_origin, "POST", "/api/lane/transfer", transfer)
    assert status == 200 and replay["replayed"] is True
    assert server._last_ball_at[23] == 4.0

    status, _ = _request(
        http_origin, "POST", "/api/lane/23/close",
        {"session_generation": 1})
    assert status == 200
    assert 23 not in server._last_ball_at

    server._last_ball_at[25] = 5.0
    server._last_ball_at[26] = 6.0
    league = _league_body(left=25, right=26)
    status, _ = _request(
        http_origin, "POST", "/api/pair/25-26/open-league",
        league)
    assert status == 200
    assert 25 not in server._last_ball_at
    assert 26 not in server._last_ball_at

    server._last_ball_at[25] = 7.0
    server._last_ball_at[26] = 8.0
    status, replay = _request(
        http_origin, "POST", "/api/pair/25-26/open-league",
        league)
    assert status == 200 and replay["replayed"] is True
    assert server._last_ball_at[25] == 7.0
    assert server._last_ball_at[26] == 8.0


def test_manual_score_requires_pending_event_and_replays_exactly_once(
        http_origin, isolated_server_state):
    status, opened = _open(http_origin, 21, 1, ["A"])
    assert status == 200
    epoch = opened["scoring_epoch"]
    pending = {
        "event_id": "manual-event-1",
        "node_id": "pair-21-22",
        "lane_id": 21,
        "event_type": "ball_event",
        "event_created_at": time.time(),
        "payload": {
            "lane": 21,
            "pin_mask": None,
            "awaiting_manual": True,
            "scoring_epoch": epoch,
        },
        "disposition": "awaiting_manual",
    }
    state_store.record_scoring_event_receipt(pending)
    scorer = server.lane_scoring[21]

    status, scored = _request(
        http_origin, "POST", "/api/lane/21/score", {
            "event_id": "manual-event-1",
            "pin_mask": 0,
            "foul": False,
        })
    assert status == 200 and scored["ok"] is True
    assert scored["display"] == "X"
    assert len(scorer.bowlers[0].frames[0].bowls) == 1
    assert state_store.pending_manual_events(21) == []

    status, replay = _request(
        http_origin, "POST", "/api/lane/21/score", {
            "event_id": "manual-event-1",
            "pin_mask": 0,
            "foul": False,
        })
    assert status == 200 and replay["replayed"] is True
    assert len(scorer.bowlers[0].frames[0].bowls) == 1

    status, conflict = _request(
        http_origin, "POST", "/api/lane/21/score", {
            "event_id": "manual-event-1",
            "pin_mask": 0x3FF,
            "foul": False,
        })
    assert status == 409
    assert conflict["error"] == "manual_score_idempotency_conflict"
    assert len(scorer.bowlers[0].frames[0].bowls) == 1

    status, absent = _request(
        http_origin, "POST", "/api/lane/21/score", {
            "event_id": "never-seen",
            "pin_mask": 0,
        })
    assert status == 409
    assert absent["error"] == "manual_scoring_event_not_pending"
    assert len(scorer.bowlers[0].frames[0].bowls) == 1


def test_mutation_json_rejects_duplicate_keys_and_nonfinite_before_state(
        http_origin, isolated_server_state):
    status, _ = _raw_request(
        http_origin, "POST", "/api/lane/21/open",
        '{"bowlers":["A"],"send_open_command":false,'
        '"session_generation":1,"session_generation":2}')
    assert status == 400
    assert 21 not in server.lane_scoring
    assert state_store.lane_session_generation(21) is None

    status, _ = _raw_request(
        http_origin, "POST", "/api/lane/21/open",
        '{"bowlers":["A"],"send_open_command":false,'
        '"session_generation":NaN}')
    assert status == 400
    assert 21 not in server.lane_scoring
    assert state_store.lane_session_generation(21) is None


def test_partial_http_body_has_hard_deadline_and_does_not_block_health(
        http_origin, monkeypatch):
    monkeypatch.setattr(server, "HTTP_BODY_DEADLINE_S", 0.25)
    monkeypatch.setattr(server, "HTTP_IO_TIMEOUT_S", 0.25)
    port = int(http_origin.rsplit(":", 1)[1])
    stalled = socket.create_connection(("127.0.0.1", port), timeout=2)
    stalled.settimeout(2)
    try:
        stalled.sendall(
            b"POST /api/lane/21/score HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 100\r\n"
            b"Connection: close\r\n\r\n{")
        started = time.monotonic()
        status, payload = _request(http_origin, "GET", "/api/health")
        assert status == 200
        assert isinstance(payload, dict)
        assert time.monotonic() - started < 1.0
        response = b""
        while True:
            chunk = stalled.recv(4096)
            if not chunk:
                break
            response += chunk
        assert b"400" in response
        assert b"incomplete JSON body" in response
        assert time.monotonic() - started < 1.5
    finally:
        stalled.close()


def test_aged_crash_recovered_camera_edge_stays_manual_and_retry_safe(
        http_origin, isolated_server_state, monkeypatch):
    status, opened = _open(
        http_origin, 21, 1, ["A"], send=False)
    assert status == 200
    now = time.time()
    event = {
        "type": server.Msg.BALL_EVENT,
        "ts": now,
        "lane": 21,
        "pin_mask": None,
        "awaiting_manual": True,
        "capture_interrupted": True,
        "event_id": "crash-recovered-camera-edge",
        "event_created_at": (
            now - server.SCORING_EVENT_AUTO_APPLY_MAX_AGE_S - 5),
        "scoring_epoch": opened["scoring_epoch"],
    }
    diagnostics = []
    monkeypatch.setattr(
        server, "_record_manual_score_state",
        lambda *args, **kwargs: diagnostics.append((args, kwargs)))
    monkeypatch.setattr(server, "_routing_lock", None)
    monkeypatch.setattr(server, "_ws_mutation_gate", None)
    with server.clients_lock:
        server.clients.clear()
        server.client_metadata.clear()

    websocket = _FiniteWebSocket([
        json.dumps(_node_hello("camera-node", [21])),
        json.dumps(event),
        # Lost event ACK: the exact durable event is resent after reconnect.
        json.dumps(event),
    ])
    asyncio.run(server.handle_node(websocket))

    frame_types = [frame["type"] for frame in websocket.sent]
    assert server.Msg.CYCLE not in frame_types
    assert [
        frame["disposition"] for frame in websocket.sent
        if frame["type"] == server.Msg.SCORING_EVENT_ACK
    ] == ["awaiting_manual", "duplicate"]
    receipt = state_store.scoring_event_receipt(event["event_id"])
    assert receipt["disposition"] == "capture_interrupted_manual_only"
    assert [item["event_id"] for item in
            state_store.pending_manual_events(21)] == [event["event_id"]]
    assert [entry[0][3] for entry in diagnostics] == [
        "camera_capture_interrupted_manual_score_pending"]
    assert not any(
        entry[0][3] == "cycle_delivery_indeterminate"
        for entry in diagnostics)


def test_server_clock_rollback_quarantines_queued_ball_without_cycle(
        http_origin, isolated_server_state, monkeypatch):
    status, opened = _open(
        http_origin, 21, 1, ["A"], send=False)
    assert status == 200
    now = time.time()
    state_store.observe_control_wall_clock(now=now + 120)
    event = {
        "type": server.Msg.BALL_EVENT,
        "ts": now,
        "lane": 21,
        "pin_mask": 0,
        "event_id": "rollback-queued-ball",
        "event_created_at": now,
        "scoring_epoch": opened["scoring_epoch"],
    }
    diagnostics = []
    monkeypatch.setattr(
        server, "_record_manual_score_state",
        lambda *args, **kwargs: diagnostics.append((args, kwargs)))
    monkeypatch.setattr(server, "_routing_lock", None)
    monkeypatch.setattr(server, "_ws_mutation_gate", None)
    with server.clients_lock:
        server.clients.clear()
        server.client_metadata.clear()
    websocket = _FiniteWebSocket([
        json.dumps(_node_hello("rollback-node", [21])),
        json.dumps(event),
    ])

    asyncio.run(server.handle_node(websocket))

    assert server.Msg.CYCLE not in [
        frame["type"] for frame in websocket.sent]
    assert [
        frame["disposition"] for frame in websocket.sent
        if frame["type"] == server.Msg.SCORING_EVENT_ACK
    ] == ["clock_anomaly_quarantined"]
    assert len(server.lane_scoring[21].bowlers[0].frames[0].bowls) == 0
    receipt = state_store.scoring_event_receipt(event["event_id"])
    assert receipt["disposition"] == "clock_anomaly_manual_only"
    assert [item["event_id"] for item in
            state_store.pending_manual_events(21)] == [event["event_id"]]
    assert diagnostics[0][0][3] == (
        "wall_clock_anomaly_scoring_event_quarantined")


def test_manual_score_rejects_retired_epoch_without_mutation(
        http_origin, isolated_server_state):
    status, _ = _open(http_origin, 21, 1, ["A"])
    assert status == 200
    stale = {
        "event_id": "manual-stale",
        "node_id": "pair-21-22",
        "lane_id": 21,
        "event_type": "ball_event",
        "event_created_at": time.time(),
        "payload": {
            "lane": 21,
            "pin_mask": None,
            "awaiting_manual": True,
            "scoring_epoch": "retired-epoch",
        },
        "disposition": "awaiting_manual",
    }
    state_store.record_scoring_event_receipt(stale)
    scorer = server.lane_scoring[21]

    status, body = _request(
        http_origin, "POST", "/api/lane/21/score", {
            "event_id": "manual-stale",
            "pin_mask": 0,
        })
    assert status == 409
    assert body["error"] == "manual_score_epoch_mismatch"
    assert len(scorer.bowlers[0].frames[0].bowls) == 0
    assert [item["event_id"] for item in
            state_store.pending_manual_events(21)] == ["manual-stale"]
