"""Focused regressions for durable, off-loop server diagnostics delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import sys
import time
import types
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


@pytest.fixture(autouse=True)
def isolated_diagnostic_stores(tmp_path, monkeypatch):
    server._stop_diagnostic_delivery_worker_for_tests()
    monkeypatch.setattr(
        state_store, "DB_PATH", tmp_path / "lane-state.sqlite3")
    monkeypatch.setattr(
        machine_store, "DB_PATH", tmp_path / "machine.sqlite3")
    state_store.clear_state()
    machine_store.clear_state()
    server._command_ack_waiters.clear()
    server._background_command_tasks.clear()
    try:
        yield
    finally:
        server._stop_diagnostic_delivery_worker_for_tests()
        server._command_ack_waiters.clear()
        server._background_command_tasks.clear()


def _wait_until(predicate, timeout_s=3.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition did not become true before deadline")


def _outbox_rows():
    with sqlite3.connect(state_store.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row) for row in conn.execute(
                "SELECT * FROM diagnostic_incident_outbox "
                "ORDER BY outbox_id").fetchall()
        ]


def _machine_events(code):
    with sqlite3.connect(machine_store.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row) for row in conn.execute(
                "SELECT * FROM machine_events WHERE code=? ORDER BY id",
                (code,)).fetchall()
        ]


def _begin_delivery(
        command_id, event_id, *, owner_boot_id=None, deadline=None):
    return state_store.begin_background_command_delivery({
        "command_id": command_id,
        "event_id": event_id,
        "lane_id": 21,
        "command_type": server.Msg.CYCLE,
        "owner_boot_id": owner_boot_id or server.SERVER_BOOT_ID,
        "issued_at": time.time(),
        "deadline_monotonic": (
            time.monotonic() + 30.0 if deadline is None else deadline),
    }, timeout_s=server.DIAGNOSTIC_DB_TIMEOUT_S)


async def _wait_for_background_finalizers():
    deadline = asyncio.get_running_loop().time() + 2.0
    while server._background_command_tasks:
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("background command finalizer did not finish")
        await asyncio.sleep(0.01)


def _scoring_metadata():
    return {
        "scoring_boot_id": "diag-loop-boot",
        "scoring_session_id": "diag-loop-session",
        "heartbeat_seq": 1,
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
            "scoring_clock_high_water_epoch": 100.0,
            "scoring_clock_observed_epoch": 100.0,
            "scoring_event_durable": True,
            "scoring_event_error": False,
            "scoring_event_overdue": False,
            "scoring_event_drops": 0,
            "scoring_event_expired": 0,
            "scoring_event_max_age_s": 30.0,
        },
        "node_ball_lockout_s": 8.0,
    }


def test_incident_outbox_normalizes_on_delivery_and_dedupes():
    detail = {
        "event_id": "diagnostic-loop-event",
        "requires_manual_reconciliation": True,
    }
    first = server._enqueue_diagnostic_incident_sync(
        21, "fault", "scoring_event_transport",
        "diagnostic_loop_isolation", detail)
    replay = server._enqueue_diagnostic_incident_sync(
        21, "fault", "scoring_event_transport",
        "diagnostic_loop_isolation", detail)

    assert replay["outbox_id"] == first["outbox_id"]
    rows = _outbox_rows()
    assert len(rows) == 1
    raw = json.loads(rows[0]["payload_json"])
    assert raw["detail"] == detail
    assert "business_date" not in raw
    assert "detail_json" not in raw
    machine_store.validate_event(raw)

    server._start_diagnostic_delivery_worker()
    _wait_until(lambda: bool(
        _outbox_rows() and _outbox_rows()[0]["delivered_at"] is not None))
    assert len(_machine_events("diagnostic_loop_isolation")) == 1

    tombstone = server._enqueue_diagnostic_incident_sync(
        21, "fault", "scoring_event_transport",
        "diagnostic_loop_isolation", detail)
    assert tombstone["outbox_id"] == first["outbox_id"]
    time.sleep(0.1)
    assert len(_machine_events("diagnostic_loop_isolation")) == 1


def test_bounded_machine_store_stall_keeps_loop_live_and_health_red(
        monkeypatch):
    ticks = 0
    stop = asyncio.Event()
    acquired = machine_store._db_lock.acquire(timeout=1.0)
    assert acquired

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    async def scenario():
        ticker_task = asyncio.create_task(ticker())
        started = time.monotonic()
        try:
            with pytest.raises((machine_store.StoreBusy, TimeoutError)):
                await server._run_control_db(
                    machine_store.touch_scoring_lanes,
                    [21], _scoring_metadata(),
                    timeout_s=server.DIAGNOSTIC_DB_TIMEOUT_S)
        finally:
            elapsed = time.monotonic() - started
            stop.set()
            await ticker_task
        return elapsed

    try:
        elapsed = asyncio.run(scenario())
        server._enqueue_diagnostic_incident_sync(
            21, "fault", "command_transport",
            "diagnostic_locked_db_health", {
                "command_id": "locked-db-health",
                "requires_manual_reconciliation": True,
            })
        monkeypatch.setattr(
            server, "_diagnostic_delivery_enforced", True)
        server._start_diagnostic_delivery_worker()
        _wait_until(
            lambda: server._diagnostic_delivery_health()[
                "consecutive_failures"] > 0)
        assert server._diagnostic_delivery_health()["ok"] is False
    finally:
        machine_store._db_lock.release()

    assert ticks >= 10
    assert elapsed <= server.DIAGNOSTIC_ASYNC_DEADLINE_S + 0.5
    _wait_until(
        lambda: len(_machine_events("diagnostic_locked_db_health")) == 1)
    _wait_until(lambda: server._diagnostic_delivery_health()["ok"] is True)
    with sqlite3.connect(machine_store.DB_PATH) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM machine_leases "
            "WHERE scoring_seen_at IS NOT NULL").fetchone()[0] == 0


def test_ball_cycle_ledger_is_durable_before_socket_send(monkeypatch):
    event_id = "ledger-before-cycle-send"
    expected_command_id = (
        "ball-cycle:"
        + hashlib.sha256(event_id.encode("utf-8")).hexdigest())
    observed = []

    class InspectingWebSocket:
        async def send(self, raw):
            frame = json.loads(raw)
            row = state_store.background_command_delivery(
                frame["command_id"],
                timeout_s=server.DIAGNOSTIC_DB_TIMEOUT_S)
            observed.append((frame, row))

        async def close(self, code=None, reason=None):
            raise AssertionError(f"unexpected close: {code} {reason}")

    async def fake_send_and_wait(ws, raw, sent_future=None):
        await ws.send(raw)
        if sent_future is not None and not sent_future.done():
            sent_future.set_result(True)
        return {"status": "completed", "original_status": None}

    monkeypatch.setattr(server, "_send_command_and_wait", fake_send_and_wait)

    async def scenario():
        await server._send_ball_cycle_before_receipt(
            InspectingWebSocket(), 21, event_id, time.time())
        await _wait_for_background_finalizers()

    asyncio.run(scenario())

    assert len(observed) == 1
    frame, ledger = observed[0]
    assert frame["command_id"] == expected_command_id
    assert ledger["event_id"] == event_id
    assert ledger["state"] == "pending"
    assert state_store.background_command_delivery(
        expected_command_id,
        timeout_s=server.DIAGNOSTIC_DB_TIMEOUT_S)["state"] == "completed"


def test_refused_background_cycle_enqueues_one_event_bound_incident():
    command_id = "ball-cycle:refused-diagnostic-loop"
    event_id = "refused-diagnostic-loop-event"
    _begin_delivery(command_id, event_id)

    async def scenario():
        task = asyncio.create_task(asyncio.sleep(
            0, result={"status": "refused"}))
        await task
        server._consume_ball_cycle_task(
            task, 21, event_id, command_id)
        server._consume_ball_cycle_task(
            task, 21, event_id, command_id)
        await _wait_for_background_finalizers()

    asyncio.run(scenario())

    delivery = state_store.background_command_delivery(
        command_id, timeout_s=server.DIAGNOSTIC_DB_TIMEOUT_S)
    assert delivery["state"] == "indeterminate"
    assert delivery["ack_status"] == "refused"
    assert delivery["reason"] == "command_refused"
    rows = _outbox_rows()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["code"] == "cycle_delivery_indeterminate"
    assert payload["detail"]["event_id"] == event_id
    assert payload["detail"]["command_id"] == command_id


def test_prior_boot_pending_command_dead_man_is_idempotent():
    command_id = "ball-cycle:prior-boot-diagnostic-loop"
    event_id = "prior-boot-diagnostic-loop-event"
    pending = _begin_delivery(
        command_id, event_id, owner_boot_id="previous-server-boot",
        deadline=time.monotonic() + 3600.0)

    stale = state_store.stale_background_command_deliveries(
        server.SERVER_BOOT_ID, time.monotonic(),
        timeout_s=server.DIAGNOSTIC_DB_TIMEOUT_S)
    assert [row["command_id"] for row in stale] == [command_id]

    first = server._finalize_dead_background_command(pending)
    replay = server._finalize_dead_background_command(pending)
    assert first["changed"] is True
    assert replay["changed"] is False
    assert len(_outbox_rows()) == 1

    server._start_diagnostic_delivery_worker()
    _wait_until(lambda: bool(
        _outbox_rows() and _outbox_rows()[0]["delivered_at"] is not None))
    server._stop_diagnostic_delivery_worker_for_tests()
    server._start_diagnostic_delivery_worker()
    time.sleep(0.1)

    delivery = state_store.background_command_delivery(
        command_id, timeout_s=server.DIAGNOSTIC_DB_TIMEOUT_S)
    assert delivery["state"] == "indeterminate"
    assert delivery["reason"] == "server_restarted_before_command_receipt"
    events = _machine_events("cycle_delivery_indeterminate")
    assert len(events) == 1
    detail = json.loads(events[0]["detail_json"])
    assert detail["event_id"] == event_id
    assert detail["command_id"] == command_id
