"""Focused durability tests for the Track-A scoring/command transport."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

from lane_node.reliable_transport import DurableTransport, TransportError


def _event(event_id: str, created_at: float | None = None, **extra) -> str:
    return json.dumps({
        "type": "ball_event",
        "event_id": event_id,
        "event_created_at": (
            time.time() if created_at is None else created_at),
        "lane": 21,
        "pin_mask": 0x3FF,
        "awaiting_manual": False,
        "scoring_epoch": "epoch-1",
        **extra,
    }, sort_keys=True)


def _capture_edge(
        event_id: str, created_at: float | None = None,
        lane: int = 21) -> str:
    return json.dumps({
        "type": "ball_event",
        "event_id": event_id,
        "event_created_at": (
            time.time() if created_at is None else created_at),
        "lane": lane,
        "pin_mask": None,
        "awaiting_manual": True,
        "scoring_epoch": "epoch-1",
    }, sort_keys=True)


def _command(command_id: str = "cmd-1", **extra) -> dict:
    return {
        "type": "open_lane",
        "ts": time.time(),
        "lane": 21,
        "command_id": command_id,
        "issued_at": time.time(),
        "bowlers": ["A"],
        "scoring_epoch": "epoch-1",
        **extra,
    }


def test_scoring_outbox_is_fifo_restart_safe_and_head_acked(tmp_path):
    db = tmp_path / "transport.sqlite3"
    first = _event("event-1", time.time() - 2)
    second = _event("event-2", time.time() - 1)
    third = _event("event-3")

    transport = DurableTransport(db, event_capacity=2)
    assert transport.put_event(first) == "admitted"
    assert transport.put_event(second) == "admitted"
    assert transport.put_event(first) == "duplicate"
    assert transport.put_event(third) == "full"
    assert transport.peek_event()["event_id"] == "event-1"

    # A new process instance sees the same ordered head.
    restarted = DurableTransport(db, event_capacity=2)
    assert restarted.peek_event()["frame_json"] == first
    health = restarted.event_health()
    assert health["ok"] is True
    assert health["depth"] == 2
    assert health["capacity"] == 2
    assert health["oldest_age_s"] is not None
    assert health["oldest_age_s"] >= 1.5

    # A receipt for a later event cannot punch a hole in FIFO delivery.
    with pytest.raises(
            TransportError, match="does not match durable outbox head"):
        restarted.ack_event("event-2")
    assert restarted.peek_event()["event_id"] == "event-1"

    assert restarted.ack_event("event-1") is True
    assert restarted.put_event(third) == "admitted"
    assert restarted.peek_event()["event_id"] == "event-2"
    # A reconnect can replay the receipt after the executor completed the
    # previous DELETE but before the cancelled sender cleared its in-memory
    # pending pointer.  That retry is idempotent and must not wedge behind the
    # next FIFO head.
    assert restarted.ack_event("event-1") is False
    assert restarted.peek_event()["event_id"] == "event-2"
    assert restarted.ack_event("event-2") is True
    assert restarted.peek_event()["event_id"] == "event-3"
    assert restarted.ack_event("event-3") is True
    assert restarted.ack_event("event-3") is False
    assert restarted.event_health()["depth"] == 0


def test_camera_edge_is_reserved_before_capture_and_restart_recovers_manual(
        tmp_path):
    db = tmp_path / "capture-restart.sqlite3"
    edge = _capture_edge("camera-edge-1")
    transport = DurableTransport(db, event_capacity=1)

    assert transport.begin_capture_job(edge) == "admitted"
    assert transport.peek_event() is None
    assert [row["event_id"] for row in transport.capture_jobs()] == [
        "camera-edge-1"]
    health = transport.event_health()
    assert health["depth"] == 1
    assert health["capture_jobs"] == 1
    assert health["capture_oldest_age_s"] is not None
    assert transport.put_event(_event("other")) == "full"

    restarted = DurableTransport(db, event_capacity=1)
    assert restarted.recover_capture_jobs() == 1
    assert restarted.capture_jobs() == []
    recovered = restarted.peek_event()
    assert recovered["event_id"] == "camera-edge-1"
    recovered_frame = json.loads(recovered["frame_json"])
    assert recovered_frame["awaiting_manual"] is True
    assert recovered_frame["capture_interrupted"] is True
    assert restarted.recover_capture_jobs() == 0


def test_camera_edge_reserves_fifo_position_ahead_of_later_foul(tmp_path):
    transport = DurableTransport(tmp_path / "capture-foul-order.sqlite3")
    edge = _capture_edge("ball-edge")
    foul = json.dumps({
        "type": "foul_event",
        "event_id": "later-foul",
        "event_created_at": time.time() + 0.001,
        "lane": 21,
        "foul": True,
        "scoring_epoch": "epoch-1",
    }, sort_keys=True)

    assert transport.begin_capture_job(edge) == "admitted"
    assert transport.put_event(foul) == "admitted"
    # The unsettled ball is the durable head and blocks later delivery.
    assert transport.peek_event() is None

    final = dict(json.loads(edge), pin_mask=0x3FF)
    final.pop("awaiting_manual")
    assert transport.complete_capture_job(
        "ball-edge", json.dumps(final, sort_keys=True)) == "admitted"
    assert transport.peek_event()["event_id"] == "ball-edge"
    assert transport.ack_event("ball-edge") is True
    assert transport.peek_event()["event_id"] == "later-foul"


def test_cross_lane_capture_completion_cannot_invert_edge_order(tmp_path):
    transport = DurableTransport(tmp_path / "capture-lane-order.sqlite3")
    first = _capture_edge("lane-21-edge", lane=21)
    second = _capture_edge("lane-22-edge", lane=22)
    assert transport.begin_capture_job(first) == "admitted"
    assert transport.begin_capture_job(second) == "admitted"

    second_final = dict(json.loads(second), pin_mask=0)
    second_final.pop("awaiting_manual")
    assert transport.complete_capture_job(
        "lane-22-edge", json.dumps(second_final, sort_keys=True)
    ) == "admitted"
    assert transport.peek_event() is None

    first_final = dict(json.loads(first), pin_mask=0)
    first_final.pop("awaiting_manual")
    assert transport.complete_capture_job(
        "lane-21-edge", json.dumps(first_final, sort_keys=True)
    ) == "admitted"
    assert transport.peek_event()["event_id"] == "lane-21-edge"
    assert transport.ack_event("lane-21-edge") is True
    assert transport.peek_event()["event_id"] == "lane-22-edge"


def test_camera_capture_completion_is_atomic_and_payload_bound(tmp_path):
    transport = DurableTransport(tmp_path / "capture-complete.sqlite3")
    edge = _capture_edge("camera-edge-2")
    assert transport.begin_capture_job(edge) == "admitted"
    final = json.loads(edge)
    final["pin_mask"] = 0
    final.pop("awaiting_manual")
    final_json = json.dumps(final, sort_keys=True)

    assert transport.complete_capture_job(
        "camera-edge-2", final_json) == "admitted"
    assert transport.capture_jobs() == []
    assert transport.peek_event()["frame_json"] == final_json
    assert transport.complete_capture_job(
        "camera-edge-2", final_json) == "duplicate"

    collision = dict(final, pin_mask=1)
    assert transport.complete_capture_job(
        "camera-edge-2", json.dumps(collision, sort_keys=True)
    ) == "collision"


def test_command_ledger_binds_id_to_immutable_payload_and_result(tmp_path):
    db = tmp_path / "transport.sqlite3"
    transport = DurableTransport(db)
    command = _command()

    assert transport.begin_command(
        "cmd-1", "open_lane", 21, command) == ("new", None)
    assert transport.begin_command(
        "cmd-1", "open_lane", 21, command) == ("ambiguous", None)
    transport.complete_command("cmd-1", {"status": "completed"})

    # Envelope ts and the shared token may change on a reconnect; neither is
    # part of the physical operation identity.
    replay = dict(command, ts=time.time() + 1, token="rotated-envelope")
    claim, result = DurableTransport(db).begin_command(
        "cmd-1", "open_lane", 21, replay)
    assert claim == "completed"
    assert result == {"status": "completed"}

    # Every field that changes the authorized action remains bound.
    collision = dict(replay, bowlers=["DIFFERENT"])
    assert transport.begin_command(
        "cmd-1", "open_lane", 21, collision) == ("collision", None)
    assert transport.begin_command(
        "cmd-1", "close_lane", 21, replay) == ("collision", None)
    assert transport.begin_command(
        "cmd-1", "open_lane", 22, replay) == ("collision", None)

    with pytest.raises(
            TransportError,
            match="does not match a started receipt"):
        transport.complete_command("cmd-1", {"status": "completed"})


def test_completed_command_tombstone_survives_apparent_wall_clock_age(
        tmp_path):
    db = tmp_path / "retained-receipt.sqlite3"
    command = _command(command_id="permanent-safety-tombstone")
    transport = DurableTransport(db)
    assert transport.begin_command(
        command["command_id"], command["type"], 21, command
    ) == ("new", None)
    transport.complete_command(
        command["command_id"], {"status": "completed"})

    # Simulate both a very old receipt and a future wall-clock jump.  Opening
    # the ledger must never prune the only proof that actuation completed.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE command_receipts SET completed_at=? WHERE command_id=?",
            (1.0, command["command_id"]))
        conn.commit()

    restarted = DurableTransport(db)
    claim, result = restarted.begin_command(
        command["command_id"], command["type"], 21,
        dict(command, ts=time.time() + 100 * 365 * 86400))
    assert claim == "completed"
    assert result == {"status": "completed"}


def test_command_clock_rollback_latches_across_restart_and_audits_reset(
        tmp_path):
    db = tmp_path / "clock-guard.sqlite3"
    transport = DurableTransport(db)
    first = transport.observe_wall_clock(
        now=10_000.0, rollback_tolerance_s=5.0)
    assert first["observed"] is True
    assert first["anomaly_latched"] is False

    restarted = DurableTransport(db)
    rolled_back = restarted.observe_wall_clock(
        now=9_900.0, rollback_tolerance_s=5.0)
    assert rolled_back["anomaly_latched"] is True
    assert rolled_back["high_water_epoch"] == 10_000.0
    assert DurableTransport(db).wall_clock_status() == rolled_back

    audit = restarted.reset_wall_clock(
        10_100.0, 7, "NTP synchronized; operator verified UTC")
    assert audit["prior_high_water"] == 10_000.0
    assert audit["new_epoch"] == 10_100.0
    assert restarted.wall_clock_status()["anomaly_latched"] is False
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT actor_id,note,new_epoch "
            "FROM transport_clock_reset_audit").fetchone()
    assert row == (
        7, "NTP synchronized; operator verified UTC", 10_100.0)


def test_epoch_sync_renews_age_but_binds_generation_and_recovers_started(
        tmp_path):
    transport = DurableTransport(tmp_path / "sync.sqlite3")
    sync = {
        "type": "scoring_epoch_sync",
        "ts": time.time(),
        "lane": 21,
        "command_id": "sync:21:4",
        "issued_at": time.time(),
        "session_generation": 4,
        "scoring_epoch": "epoch-4",
    }
    assert transport.begin_command(
        sync["command_id"], sync["type"], 21, sync) == ("new", None)

    # A crash leaves the row started. This exact non-actuating assignment is
    # safely reclaimable with fresh transport authorization.
    renewed = dict(sync, ts=time.time() + 1, issued_at=time.time() + 1)
    assert transport.begin_command(
        sync["command_id"], sync["type"], 21, renewed) == ("new", None)
    transport.complete_command(
        sync["command_id"], {"status": "completed"})
    assert transport.begin_command(
        sync["command_id"], sync["type"], 21,
        dict(renewed, issued_at=time.time() + 2)
    ) == ("completed", {"status": "completed"})

    assert transport.begin_command(
        sync["command_id"], sync["type"], 21,
        dict(renewed, session_generation=5)
    ) == ("collision", None)
    assert transport.begin_command(
        sync["command_id"], sync["type"], 21,
        dict(renewed, scoring_epoch="different")
    ) == ("collision", None)


@pytest.mark.parametrize("terminal_status", ["refused", "failed"])
def test_terminal_non_success_is_replayed_without_reactuation(
        tmp_path, terminal_status):
    transport = DurableTransport(
        tmp_path / f"{terminal_status}.sqlite3")
    command = _command(command_id=f"cmd-{terminal_status}")
    assert transport.begin_command(
        command["command_id"], command["type"], 21, command
    ) == ("new", None)
    transport.complete_command(
        command["command_id"], {"status": terminal_status})

    claim, result = transport.begin_command(
        command["command_id"], command["type"], 21,
        dict(command, ts=time.time()))
    assert claim == "completed"
    assert result == {"status": terminal_status}


def test_legacy_command_schema_migrates_fail_safe(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE command_receipts (
              command_id TEXT PRIMARY KEY,
              command_type TEXT NOT NULL,
              lane_id INTEGER NOT NULL,
              received_at REAL NOT NULL,
              state TEXT NOT NULL,
              completed_at REAL,
              result_json TEXT
            );
        """)
        conn.execute(
            "INSERT INTO command_receipts VALUES (?,?,?,?,?,?,?)",
            ("legacy-command", "open_lane", 21, time.time(),
             "completed", time.time(), '{"status":"completed"}'))
        conn.commit()

    transport = DurableTransport(db)
    with sqlite3.connect(db) as conn:
        columns = {
            row[1] for row in
            conn.execute("PRAGMA table_info(command_receipts)")}
    assert "payload_sha256" in columns

    # The old row cannot prove its immutable payload. Treating it as a
    # collision is the safe direction: never blindly re-actuate it.
    assert transport.begin_command(
        "legacy-command", "open_lane", 21, _command(
            command_id="legacy-command")) == ("collision", None)
    assert transport.begin_command(
        "new-command", "open_lane", 21, _command(
            command_id="new-command")) == ("new", None)
