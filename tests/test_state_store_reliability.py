"""Atomic scoring receipts, foul/manual work, and session generations."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

from server import state_store
from wsl_scoring_engine import CrossLaneScoring, LaneScoring


def _lane(epoch="epoch-1"):
    lane = LaneScoring(21)
    lane.start(["A"])
    lane.scoring_epoch = epoch
    return lane


def _receipt(
        event_id, event_type="ball_event", disposition="accepted",
        epoch="epoch-1", **payload):
    body = {
        "lane": 21,
        "scoring_epoch": epoch,
        **payload,
    }
    return {
        "event_id": event_id,
        "node_id": "pair-21-22",
        "lane_id": 21,
        "event_type": event_type,
        "event_created_at": time.time(),
        "payload": body,
        "disposition": disposition,
    }


@pytest.fixture(autouse=True)
def isolated_state_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        state_store, "DB_PATH", tmp_path / "lane-state.sqlite3")
    state_store.clear_state()


def test_receipt_collision_and_pending_foul_filtering():
    accepted = _receipt(
        "foul-accepted", event_type="foul_event",
        disposition="accepted")
    stale = _receipt(
        "foul-stale", event_type="foul_event",
        disposition="stale_quarantined", epoch="retired")

    assert state_store.record_scoring_event_receipt(
        accepted)[0] == "accepted"
    assert state_store.record_scoring_event_receipt(
        dict(accepted))[0] == "duplicate"
    assert state_store.record_scoring_event_receipt(stale)[0] == "accepted"
    assert state_store.pending_foul_event_ids(21) == ["foul-accepted"]

    collision = dict(accepted)
    collision["payload"] = {
        **accepted["payload"], "scoring_epoch": "different"}
    with pytest.raises(ValueError, match="payload collision"):
        state_store.record_scoring_event_receipt(collision)


def test_snapshot_receipt_foul_and_generation_commit_atomically():
    foul = _receipt(
        "foul-1", event_type="foul_event", disposition="accepted")
    state_store.record_scoring_event_receipt(foul)
    lane = _lane()
    ball = _receipt(
        "ball-1", event_type="ball_event", disposition="accepted",
        pin_mask=0)
    assert state_store.save_lanes(
        {21: lane}, {21: 1},
        scoring_receipt=ball,
        consume_foul_lane=21,
        session_updates={21: {
            "generation": 7,
            "active": True,
            "scoring_epoch": "epoch-1",
            "request_fingerprint": "a" * 64,
        }}) is True

    loaded, counters = state_store.load_lanes()
    assert set(loaded) == {21}
    assert loaded[21].scoring_epoch == "epoch-1"
    assert counters == {21: 1}
    assert state_store.scoring_event_receipt("ball-1")[
        "disposition"] == "accepted"
    assert state_store.scoring_event_receipt("foul-1")[
        "consumed_by"] == "ball-1"
    generation = state_store.lane_session_generation(21)
    assert generation["generation"] == 7
    assert bool(generation["active"]) is True
    assert generation["scoring_epoch"] == "epoch-1"


def test_failed_generation_validation_rolls_back_every_side_effect():
    foul = _receipt(
        "foul-pending", event_type="foul_event",
        disposition="accepted")
    state_store.record_scoring_event_receipt(foul)
    ball = _receipt(
        "ball-rollback", disposition="accepted", pin_mask=0)

    assert state_store.save_lanes(
        {21: _lane()}, {21: 1},
        scoring_receipt=ball,
        consume_foul_lane=21,
        session_updates={21: {
            "generation": 0,  # invalid, after snapshot/receipt SQL is staged
            "active": True,
            "scoring_epoch": "epoch-1",
            "request_fingerprint": "b" * 64,
        }}) is False

    assert state_store.scoring_event_receipt("ball-rollback") is None
    assert state_store.pending_foul_event_ids(21) == ["foul-pending"]
    assert state_store.lane_session_generation(21) is None
    with sqlite3.connect(state_store.DB_PATH) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM lane_state").fetchone()[0] == 0


def test_corrupt_snapshot_is_health_visible_until_explicit_recovery():
    assert state_store.save_lanes({21: _lane()}, {21: 1}) is True
    with sqlite3.connect(state_store.DB_PATH) as conn:
        conn.execute(
            "UPDATE lane_state SET state_pickle=? WHERE lane_id=0",
            (b"{not valid json",))
        conn.commit()

    loaded, counters = state_store.load_lanes()
    assert loaded == {}
    assert counters == {}
    status = state_store.get_save_status()
    assert status["ok"] is False
    assert status["save_ok"] is True
    assert status["load_ok"] is False
    assert status["last_load_state"] == "snapshot_decode_failed"
    assert status["state_discarded"] is True
    assert status["last_load_error"]

    # A deliberate clear is the operator-visible recovery boundary.
    state_store.clear_state()
    recovered = state_store.get_save_status()
    assert recovered["ok"] is True
    assert recovered["load_ok"] is True
    assert recovered["last_load_state"] == "explicitly_cleared"
    assert recovered["state_discarded"] is False


def _plant_snapshot(blob):
    state_store._ensure_schema()
    with sqlite3.connect(state_store.DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lane_state "
            "(lane_id,state_pickle,ball_counter,updated_at) "
            "VALUES (0,?,0,?)",
            (blob, time.time()))
        conn.commit()


@pytest.mark.parametrize("mutation", [
    "extra_top_level",
    "missing_object",
    "lane_object_mismatch",
    "orphan_counter",
    "invalid_cursor",
    "out_of_range_lane",
])
def test_semantically_corrupt_json_snapshot_fails_atomically(mutation):
    lane = _lane()
    data = json.loads(state_store._snapshot_to_json(
        {21: lane}, {21: 3}))
    if mutation == "extra_top_level":
        data["ignored"] = True
    elif mutation == "missing_object":
        data["objects"] = []
        data["lanes"]["21"] = 99
    elif mutation == "lane_object_mismatch":
        data["objects"][0]["lane_id"] = 22
    elif mutation == "orphan_counter":
        data["ball_counters"]["22"] = 1
    elif mutation == "invalid_cursor":
        data["objects"][0]["current_bowler_idx"] = 99
    elif mutation == "out_of_range_lane":
        data["lanes"]["33"] = data["lanes"].pop("21")
        data["objects"][0]["lane_id"] = 33
        data["ball_counters"]["33"] = data["ball_counters"].pop("21")
    _plant_snapshot(json.dumps(data).encode("utf-8"))

    loaded, counters = state_store.load_lanes()

    assert loaded == {}
    assert counters == {}
    status = state_store.get_save_status()
    assert status["load_ok"] is False
    assert status["state_discarded"] is True
    assert status["last_load_state"] == "snapshot_decode_failed"


def test_snapshot_rejects_duplicate_json_keys_and_broken_cross_lane_bijection():
    cross = CrossLaneScoring(21, 22)
    cross.add_bowler("A", starting_lane=21)
    cross.add_bowler("B", starting_lane=22)
    cross.start()
    cross.scoring_epoch = "cross-epoch"
    data = json.loads(state_store._snapshot_to_json(
        {21: cross, 22: cross}, {21: 0, 22: 0}))

    broken = json.loads(json.dumps(data))
    broken["lanes"].pop("22")
    _plant_snapshot(json.dumps(broken).encode("utf-8"))
    assert state_store.load_lanes() == ({}, {})
    assert state_store.get_save_status()["load_ok"] is False

    state_store.clear_state()
    raw = json.dumps(data)
    duplicate = raw.replace(
        f'"version": {state_store.STATE_FORMAT_VERSION}',
        f'"version": {state_store.STATE_FORMAT_VERSION}, '
        f'"version": {state_store.STATE_FORMAT_VERSION}',
        1)
    _plant_snapshot(duplicate.encode("utf-8"))
    assert state_store.load_lanes() == ({}, {})
    assert state_store.get_save_status()["load_ok"] is False


def test_manual_score_consumption_and_result_are_one_transaction():
    pending = _receipt(
        "manual-1", disposition="awaiting_manual",
        pin_mask=None, awaiting_manual=True)
    state_store.record_scoring_event_receipt(pending)
    lane = _lane()
    result = {
        "lane": 21,
        "event_id": "manual-1",
        "pin_mask": 0,
        "foul": False,
        "display": "X",
    }
    assert state_store.save_lanes(
        {21: lane}, {21: 1},
        manual_score={
            "event_id": "manual-1",
            "request_fingerprint": "c" * 64,
            "result": result,
        }) is True

    assert state_store.pending_manual_events(21) == []
    stored = state_store.manual_score_receipt("manual-1")
    assert stored["request_fingerprint"] == "c" * 64
    assert stored["result"] == result
    assert state_store.scoring_event_receipt("manual-1")[
        "consumed_by"] == "manual_score:manual-1"

    # A second consumer cannot record another score or replace the result.
    assert state_store.save_lanes(
        {21: lane}, {21: 2},
        manual_score={
            "event_id": "manual-1",
            "request_fingerprint": "d" * 64,
            "result": {**result, "pin_mask": 0x3FF},
        }) is False
    _, counters = state_store.load_lanes()
    assert counters == {21: 1}
    assert state_store.manual_score_receipt("manual-1")["result"] == result


def test_manual_score_no_score_resolution_is_atomic_audited_and_idempotent():
    pending = _receipt(
        "manual-discard", disposition="awaiting_manual",
        pin_mask=None, awaiting_manual=True)
    state_store.record_scoring_event_receipt(pending)

    status, resolution = state_store.resolve_manual_score_event(
        "manual-discard", 21, 17, "false_trigger_discarded",
        "Beam test fired without a delivered ball.", "d" * 64)
    assert status == "resolved"
    assert resolution["actor_id"] == 17
    assert resolution["disposition"] == "false_trigger_discarded"
    assert state_store.pending_manual_events(21) == []
    assert state_store.scoring_event_receipt("manual-discard")[
        "consumed_by"] == "manual_resolution:manual-discard"

    stored = state_store.manual_score_resolution("manual-discard")
    assert stored["request_fingerprint"] == "d" * 64
    assert stored["note"] == "Beam test fired without a delivered ball."

    status, replay = state_store.resolve_manual_score_event(
        "manual-discard", 21, 17, "false_trigger_discarded",
        "Beam test fired without a delivered ball.", "d" * 64)
    assert status == "replayed"
    assert replay["created_at"] == stored["created_at"]

    status, conflict = state_store.resolve_manual_score_event(
        "manual-discard", 21, 18, "session_abandoned",
        "Different disposition.", "e" * 64)
    assert status == "conflict"
    assert conflict["actor_id"] == 17

    # Once consumed by an audited no-score disposition, a score cannot race in.
    assert state_store.save_lanes(
        {21: _lane()}, {21: 1},
        manual_score={
            "event_id": "manual-discard",
            "request_fingerprint": "f" * 64,
            "result": {
                "lane": 21,
                "event_id": "manual-discard",
                "pin_mask": 0,
                "foul": False,
                "display": "X",
            },
        }) is False
    assert state_store.load_lanes() == ({}, {})


def test_clear_state_removes_all_reliability_ledgers():
    pending = _receipt(
        "manual-clear", disposition="awaiting_manual",
        pin_mask=None, awaiting_manual=True)
    state_store.record_scoring_event_receipt(pending)
    assert state_store.save_lanes(
        {21: _lane()}, {21: 0},
        session_updates={21: {
            "generation": 1,
            "active": True,
            "scoring_epoch": "epoch-1",
            "request_fingerprint": None,
        }}) is True

    state_store.clear_state()
    assert state_store.load_lanes() == ({}, {})
    assert state_store.scoring_event_receipt("manual-clear") is None
    assert state_store.lane_session_generation(21) is None
    assert state_store.pending_manual_events() == []


def test_server_clock_guard_latches_and_reset_is_closed_state_audited():
    baseline = time.time()
    high_water = baseline + 120
    state_store.observe_control_wall_clock(
        now=high_water, rollback_tolerance_s=5.0)
    latched = state_store.observe_control_wall_clock(
        now=baseline, rollback_tolerance_s=5.0)
    assert latched["anomaly_latched"] is True
    assert state_store.get_save_status()["ok"] is False

    audit = state_store.reset_control_wall_clock(
        high_water + 60, 42, "NTP synchronized and host UTC verified")
    assert audit["prior_high_water"] == high_water
    assert audit["new_epoch"] == high_water + 60
    assert state_store.control_wall_clock_status()[
        "anomaly_latched"] is False
    with sqlite3.connect(state_store.DB_PATH) as conn:
        row = conn.execute(
            "SELECT actor_id,note,new_epoch "
            "FROM control_clock_reset_audit").fetchone()
    assert row == (
        42, "NTP synchronized and host UTC verified", high_water + 60)
