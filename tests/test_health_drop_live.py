"""R4 shared health hand-off: live platform probe and fail-honest status."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path

LANE_DIR = Path(__file__).resolve().parents[1] / "lane_node"
if str(LANE_DIR) not in sys.path:
    sys.path.insert(0, str(LANE_DIR))

import health_drop  # noqa: E402


def _controller_board(**overrides):
    board = {
        "lane_id": 21,
        "controller_boot_id": "test-controller-boot",
        "control_loop_seq": 10,
        "board_rev": "revD",
        "fw_build": "test-build",
        "fw_cfg": "test-cfg",
        "identity_ok": True,
        "identity_reason": None,
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
    }
    board.update(overrides)
    return board


def _controller_payload(**overrides):
    payload = {
        "ok": True,
        "lanes": [21],
        "boards": [_controller_board()],
        "platform": {"ok": True, "reasons": []},
    }
    payload.update(overrides)
    return payload


def test_snapshot_id_is_stable_for_identical_payload(tmp_path):
    path = tmp_path / "health_drop.json"
    payload = _controller_payload()
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CONTROLLER, payload)
    first = json.loads(path.read_text(encoding="utf-8"))["controller"]
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CONTROLLER, payload)
    second = json.loads(path.read_text(encoding="utf-8"))["controller"]
    assert second["snapshot_id"] == first["snapshot_id"]
    changed = _controller_payload(
        ok=False, platform={"ok": False, "reasons": ["filesystem_readonly"]})
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CONTROLLER, changed)
    third = json.loads(path.read_text(encoding="utf-8"))["controller"]
    assert third["snapshot_id"] != first["snapshot_id"]


def test_stale_and_missing_foreign_drop_are_explicit(tmp_path):
    path = tmp_path / "health_drop.json"
    missing = health_drop.read_foreign_statuses(
        str(path), health_drop.SERVICE_CAMERA)
    assert missing[0]["status"] == "missing"
    path.write_text(json.dumps({
        "controller": {
            "written_at": 10.0,
            "snapshot_id": "stable-1",
            "payload": {"ok": True},
        }
    }), encoding="utf-8")
    stale = health_drop.read_foreign_statuses(
        str(path), health_drop.SERVICE_CAMERA, now=1000.0, max_age_s=5.0)
    assert stale[0]["status"] == "stale"
    assert stale[0]["snapshot_id"] == "stable-1"


def test_future_and_nonfinite_written_at_are_stale_not_false_fresh(tmp_path):
    path = tmp_path / "health_drop.json"
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CONTROLLER, _controller_payload())
    cases = [
        (1001.0, "future_written_at"),
        (float("nan"), "invalid_written_at"),
        (float("inf"), "invalid_written_at"),
        (True, "invalid_written_at"),
    ]
    for written_at, expected_error in cases:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["controller"]["written_at"] = written_at
        path.write_text(json.dumps(raw), encoding="utf-8")
        status = health_drop.read_foreign_statuses(
            str(path), health_drop.SERVICE_CAMERA,
            now=1000.0, max_age_s=30.0)[0]
        assert status["status"] == "stale"
        assert status["age_s"] is None
        assert status["timestamp_error"] == expected_error
        assert health_drop.read_foreign_drops(
            str(path), health_drop.SERVICE_CAMERA,
            now=1000.0, max_age_s=30.0) == []


def test_payload_and_snapshot_identity_tamper_are_rejected(tmp_path):
    path = tmp_path / "health_drop.json"
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CONTROLLER,
        _controller_payload())
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["controller"]["payload"]["ok"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    status = health_drop.read_foreign_statuses(
        str(path), health_drop.SERVICE_CAMERA)[0]
    assert status["status"] == "stale"
    assert status["integrity_error"] == "payload_sha256_mismatch"
    assert health_drop.read_foreign_drops(
        str(path), health_drop.SERVICE_CAMERA) == []

    # A normal writer pass repairs both integrity fields.  Mutating only the
    # stable id must then be detected independently of the payload digest.
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CONTROLLER,
        _controller_payload(ok=False))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["controller"]["snapshot_id"] = "controller-1-deadbeefdead"
    path.write_text(json.dumps(raw), encoding="utf-8")
    status = health_drop.read_foreign_statuses(
        str(path), health_drop.SERVICE_CAMERA)[0]
    assert status["status"] == "stale"
    assert status["integrity_error"] == "snapshot_id_mismatch"


def test_controller_drop_requires_complete_board_safety_schema(tmp_path):
    path = tmp_path / "health_drop.json"
    board = _controller_board()
    board.pop("controller_mode")
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CONTROLLER,
        _controller_payload(boards=[board])) is False
    assert not path.exists()

    board = _controller_board()
    board["safety_taps"]["ne555"] = None
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CONTROLLER,
        _controller_payload(boards=[board])) is False
    assert not path.exists()


def test_controller_drop_relays_mode_rearm_assurance_and_tap_faults(monkeypatch):
    monkeypatch.setenv("WSL_CONTROLLER_EXPECTED_MODE", "live")
    monkeypatch.setenv(
        "WSL_RP2040_QUALIFIED_RELEASES",
        "revD|test-build|test-cfg")
    healthy = health_drop.snapshot_fault_events(
        health_drop.SERVICE_CONTROLLER, _controller_payload())
    assert not [
        event for event in healthy
        if event["event_type"] == "health_drop_unhealthy"]

    board = _controller_board(
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
        })
    events = health_drop.snapshot_fault_events(
        health_drop.SERVICE_CONTROLLER,
        _controller_payload(ok=False, boards=[board]))
    codes = {event["code"] for event in events}
    assert "controller:21:controller_mode_mismatch" in codes
    assert "controller:21:live_outputs_not_acknowledged" in codes
    assert "controller:21:manual_rearm_required" in codes
    assert "controller:21:identity_assurance_legacy_unverified" in codes
    assert "controller:21:arm_fsm_inconsistent" in codes
    assert "controller:21:arm_without_ne555" in codes
    assert "controller:21:arm_without_rp2040_ok" in codes


def test_controller_drop_rejects_approximate_mode_policy(monkeypatch):
    monkeypatch.setenv("WSL_CONTROLLER_EXPECTED_MODE", " live ")
    monkeypatch.setenv(
        "WSL_RP2040_QUALIFIED_RELEASES",
        "revD|test-build|test-cfg")
    codes = {
        event["code"]
        for event in health_drop.snapshot_fault_events(
            health_drop.SERVICE_CONTROLLER, _controller_payload())
    }
    assert "controller:21:controller_mode_policy_invalid" in codes
    assert "controller:21:controller_mode_mismatch" not in codes


def test_write_drop_fsyncs_parent_directory(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        health_drop, "_fsync_parent_dir",
        lambda path: calls.append(path) or True)
    path = tmp_path / "health_drop.json"
    assert health_drop.write_drop(
        str(path), health_drop.SERVICE_CAMERA, {"ok": True})
    assert calls == [str(path)]


def test_common_platform_probe_proves_writable_directory(tmp_path):
    result = health_drop.collect_platform_health(str(tmp_path))
    assert result["filesystem_writable"] is True
    assert isinstance(result["disk_free_bytes"], int)
    assert "reasons" in result


def test_pi_probe_requirement_is_explicit_and_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        health_drop, "_probe_temperature_c",
        lambda: (None, "FileNotFoundError"))
    monkeypatch.setattr(
        health_drop, "_probe_throttled_mask",
        lambda: (None, "FileNotFoundError"))

    host = health_drop.collect_platform_health(
        str(tmp_path), disk_low_bytes=0)
    assert host["ok"] is True
    assert host["temperature_probe_ok"] is False
    assert host["throttled_probe_ok"] is False
    assert host["pi_probes_required"] is False
    assert "temperature_probe_failed" not in host["reasons"]
    assert "vcgencmd_probe_failed" not in host["reasons"]

    production = health_drop.collect_platform_health(
        str(tmp_path), disk_low_bytes=0, require_pi_probes=True)
    assert production["ok"] is False
    assert production["pi_probes_required"] is True
    assert set(production["reasons"]) == {
        "temperature_probe_failed", "vcgencmd_probe_failed"}
    assert health_drop.platform_fault_events(production) == [
        ("temperature_probe_failed", "warn", "pi_thermal",
         "soc_temp_unavailable"),
        ("vcgencmd_probe_failed", "warn", "pi_undervoltage",
         "get_throttled_unavailable"),
    ]


def test_historical_get_throttled_bits_are_visible_and_typed(
        tmp_path, monkeypatch):
    mask = (1 << 16) | (1 << 18)
    monkeypatch.setattr(
        health_drop, "_probe_temperature_c", lambda: (45.0, None))
    monkeypatch.setattr(
        health_drop, "_probe_throttled_mask", lambda: (mask, None))
    result = health_drop.collect_platform_health(
        str(tmp_path), disk_low_bytes=0, require_pi_probes=True)
    assert result["ok"] is False
    assert result["throttle_facts"] == {
        "current_mask": 0,
        "historical_mask": 5,
        "current": [],
        "historical": ["undervoltage", "throttled"],
        "unknown_mask": 0,
    }
    assert result["reasons"] == ["pi_power_or_throttle_history"]
    assert health_drop.platform_fault_events(result) == [
        ("pi_power_or_throttle_history", "warn", "pi_undervoltage",
         "get_throttled_history")]


def test_controller_legacy_snapshot_surfaces_historical_throttle_fact():
    events = health_drop.snapshot_fault_events(
        health_drop.SERVICE_CONTROLLER, {
            "ok": False,
            "lanes": [21, 22],
            "last_throttled": 1 << 16,
        })
    assert [(event["event_type"], event["code"]) for event in events] == [
        ("pi_undervoltage", "get_throttled_history")]
    assert events[0]["evidence"]["throttle_facts"]["historical"] == [
        "undervoltage"]


def test_write_failure_is_counted(tmp_path, monkeypatch):
    before = health_drop.stats()["write_errors"]

    def fail_replace(_src, _dst):
        raise OSError("forced")

    monkeypatch.setattr(health_drop.os, "replace", fail_replace)
    assert health_drop.write_drop(
        str(tmp_path / "drop.json"),
        health_drop.SERVICE_CAMERA,
        {"ok": True}) is False
    assert health_drop.stats()["write_errors"] == before + 1


def test_platform_probe_reasons_map_to_contract_event_types():
    events = health_drop.platform_fault_events({
        "reasons": [
            "thermal",
            "disk_low",
            "filesystem_readonly",
            "unknown_future_reason",
        ]
    })
    assert events == [
        ("disk_low", "warn", "pi_disk_low", "diag_volume"),
        ("filesystem_readonly", "fault", "pi_fs_readonly", "diag_volume"),
        ("thermal", "warn", "pi_thermal", "soc_temp"),
    ]


def test_fresh_unhealthy_camera_snapshot_is_typed_and_episode_deduped():
    state = {}
    unhealthy = {
        "service": health_drop.SERVICE_CAMERA,
        "status": "fresh",
        "snapshot_id": "camera-bad-1",
        "age_s": 1.0,
        "payload": {
            "ok": False,
            "camera": {
                "ok": False, "code": "frozen", "lanes": [21, 22]},
            "platform": {"ok": True, "reasons": []},
        },
    }
    first = health_drop.plan_foreign_relay(unhealthy, state)
    assert [(e["severity"], e["event_type"], e["code"]) for e in first] == [
        ("warn", "camera_health", "frozen")]
    assert first[0]["lanes"] == [21, 22]
    assert health_drop.plan_foreign_relay(unhealthy, state) == []

    healthy = {
        **unhealthy,
        "snapshot_id": "camera-good-2",
        "payload": {
            "ok": True,
            "camera": {"ok": True, "code": "healthy", "lanes": [21, 22]},
            "platform": {"ok": True, "reasons": []},
        },
    }
    recovered = health_drop.plan_foreign_relay(healthy, state)
    assert [(e["severity"], e["event_type"], e["code"])
            for e in recovered] == [("info", "recovered", "camera_health")]
    assert health_drop.plan_foreign_relay(healthy, state) == []


def test_snapshot_relay_preserves_specific_faults_and_lane_scope():
    events = health_drop.snapshot_fault_events(
        health_drop.SERVICE_CONTROLLER, {
            "ok": False,
            "lanes": [21, 22],
            "platform": {
                "ok": False,
                "reasons": ["filesystem_readonly", "thermal"],
            },
            "boards": [
                _controller_board(
                    lane_id=22, identity_ok=False,
                    identity_reason="uid_mismatch",
                    identity_assurance="invalid"),
            ],
        })
    by_type = {event["event_type"]: event for event in events}
    assert by_type["pi_fs_readonly"]["severity"] == "fault"
    assert by_type["pi_fs_readonly"]["lanes"] == [21, 22]
    assert by_type["pi_thermal"]["severity"] == "warn"
    assert by_type["fw_identity"]["severity"] == "fault"
    assert by_type["fw_identity"]["lanes"] == [22]


def test_unattributable_false_snapshot_uses_explicit_health_event():
    events = health_drop.snapshot_fault_events(
        health_drop.SERVICE_CONTROLLER,
        {"ok": False, "lanes": [21, 22]})
    assert [(e["severity"], e["event_type"], e["code"]) for e in events] == [
        ("warn", "health_drop_unhealthy", "controller:unattributed")]


def test_stale_episode_requires_fresh_snapshot_before_fault_recovery():
    state = {}
    bad = {
        "service": health_drop.SERVICE_CAMERA,
        "status": "fresh",
        "snapshot_id": "bad",
        "age_s": 1.0,
        "payload": {
            "ok": False,
            "camera": {"ok": False, "code": "dead", "lanes": [21, 22]},
        },
    }
    health_drop.plan_foreign_relay(bad, state)
    stale = {**bad, "status": "stale", "age_s": 999.0}
    plan = health_drop.plan_foreign_relay(stale, state)
    assert [(e["event_type"], e["code"]) for e in plan] == [
        ("health_drop_stale", "camera:stale")]
    # Staleness is not evidence that the camera recovered.
    assert not any(e["code"] == "camera_health" for e in plan)

    good = {
        **bad,
        "snapshot_id": "good",
        "payload": {
            "ok": True,
            "camera": {"ok": True, "code": "healthy", "lanes": [21, 22]},
        },
    }
    plan = health_drop.plan_foreign_relay(good, state)
    assert [(e["event_type"], e["code"]) for e in plan] == [
        ("recovered", "health_drop_stale"),
        ("recovered", "health_drop_stale"),
        ("recovered", "camera_health"),
    ]
    assert [
        event["detail"]["recovered_code"] for event in plan[:2]
    ] == ["camera:missing", "camera:stale"]


def test_wall_monotonic_drift_monitor_reports_once_then_rebaselines():
    clock = {"wall": 1000.0, "mono": 100.0}
    monitor = health_drop.WallMonotonicDriftMonitor(
        5.0,
        wall_clock=lambda: clock["wall"],
        monotonic_clock=lambda: clock["mono"])
    first = monitor.sample()
    assert first["baseline"] is True
    clock.update(wall=1004.0, mono=104.0)
    assert monitor.sample()["drifted"] is False
    clock.update(wall=1015.0, mono=105.0)
    drift = monitor.sample()
    assert drift["drifted"] is True
    assert drift["code"] == "wall_step"
    assert drift["step_s"] == 10.0
    # Same new offset is not a duplicate episode after re-baselining.
    clock.update(wall=1016.0, mono=106.0)
    assert monitor.sample()["drifted"] is False
    invalid = monitor.sample(wall=float("nan"), monotonic=107.0)
    assert invalid["ok"] is False
    assert invalid["code"] == "clock_probe_invalid"


def test_durable_service_start_window_rejects_bad_prior_timestamps(tmp_path):
    path = tmp_path / "service_starts.json"
    path.write_text(json.dumps({
        "count": 7,
        "recent": [995.0, float("nan"), float("inf"), 1100.0],
    }), encoding="utf-8")
    first = health_drop.record_service_start(
        str(path), now=1000.0, window_s=10.0, threshold=3)
    assert first["persisted"] is True
    assert first["count"] == 8
    assert first["starts_in_window"] == 2
    assert first["restart_loop"] is False
    assert first["discarded_timestamps"] == 3

    second = health_drop.record_service_start(
        str(path), now=1001.0, window_s=10.0, threshold=3)
    assert second["persisted"] is True
    assert second["count"] == 9
    assert second["starts_in_window"] == 3
    assert second["restart_loop"] is True
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["recent"] == [995.0, 1000.0, 1001.0]


def test_service_start_per_lane_wal_is_immutable_and_exactly_acked(tmp_path):
    path = tmp_path / "service_starts.json"
    facts = health_drop.record_service_start(
        str(path), now=1000.0, monotonic_now=50.0,
        track_delivery=True)
    assert facts["persisted"] is True
    item = facts["pending_events"][0]
    stamp = datetime.fromtimestamp(
        item["started_at_epoch"], timezone.utc).isoformat(
            timespec="milliseconds")
    detail = {
        "count": item["count"],
        "started_at_epoch": item["started_at_epoch"],
        "starts_in_window": item["starts_in_window"],
        "window_s": item["window_s"],
        "threshold": item["threshold"],
        "restart_loop": item["restart_loop"],
        "replayed_start_evidence": False,
    }
    rows = [
        {
            "ts_utc": stamp,
            "ts_mono": item["started_at_monotonic"],
            "lane_id": lane,
            "severity": "info",
            "event_type": "service_restart",
            "code": "lane_node_start",
            "detail": dict(detail),
            "source_id": "lane-node",
            "boot_id": "boot-a",
            "seq": seq,
        }
        for lane, seq in ((21, 101), (22, 102))
    ]
    prepared = health_drop.prepare_service_start_deliveries(
        str(path), item["count"], "service_restart", rows)
    assert prepared == rows

    replacement = [
        {**row, "boot_id": "must-not-replace"}
        for row in rows
    ]
    assert health_drop.prepare_service_start_deliveries(
        str(path), item["count"], "service_restart",
        replacement) == rows
    overflow = health_drop.record_service_start(
        str(path), now=1001.0, monotonic_now=51.0,
        track_delivery=True, max_pending=1)
    assert overflow["persisted"] is True
    assert overflow["pending_delivery_overflow"] == 1
    assert overflow["pending_events"][0][
        "service_restart_deliveries"] == rows
    assert health_drop.acknowledge_service_start_event(
        str(path), item["count"], "service_restart") is False

    first = rows[0]
    assert health_drop.acknowledge_service_start_lane(
        str(path), item["count"], "service_restart", first["lane_id"],
        first["source_id"], first["boot_id"], first["seq"]) is True
    state = json.loads(path.read_text(encoding="utf-8"))
    remaining = state["pending_events"][0][
        "service_restart_deliveries"]
    assert remaining == [rows[1]]
    assert health_drop.acknowledge_service_start_lane(
        str(path), item["count"], "service_restart", 22,
        rows[1]["source_id"], "wrong-boot", rows[1]["seq"]) is False

    second = rows[1]
    assert health_drop.acknowledge_service_start_lane(
        str(path), item["count"], "service_restart", second["lane_id"],
        second["source_id"], second["boot_id"], second["seq"]) is True
    state = json.loads(path.read_text(encoding="utf-8"))
    assert "pending_events" not in state


def test_service_start_corrupt_delivery_wal_is_not_repaired(tmp_path):
    path = tmp_path / "service_starts.json"
    facts = health_drop.record_service_start(
        str(path), now=1000.0, monotonic_now=50.0,
        track_delivery=True)
    assert facts["persisted"] is True
    state = json.loads(path.read_text(encoding="utf-8"))
    state["pending_events"][0]["service_restart_deliveries"] = [{
        "lane_id": 21,
        "unexpected": "ambiguous accepted identity",
    }]
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    before = path.read_bytes()

    retry = health_drop.record_service_start(
        str(path), now=1001.0, monotonic_now=51.0,
        track_delivery=True)
    assert retry["persisted"] is False
    assert retry["error"] == "previous_delivery_state_invalid"
    assert path.read_bytes() == before


def test_service_start_overflow_loss_latch_survives_ack_and_restart(tmp_path):
    path = tmp_path / "service_starts.json"
    first = health_drop.record_service_start(
        str(path), now=1000.0, monotonic_now=50.0,
        track_delivery=True, max_pending=1)
    second = health_drop.record_service_start(
        str(path), now=1001.0, monotonic_now=51.0,
        track_delivery=True, max_pending=1)
    assert first["pending_delivery_overflow"] == 0
    assert second["pending_delivery_overflow"] == 1
    assert second["pending_delivery_overflow_new"] == 1
    assert health_drop.acknowledge_service_start_event(
        str(path), first["count"], "service_restart") is True

    third = health_drop.record_service_start(
        str(path), now=1002.0, monotonic_now=52.0,
        track_delivery=True, max_pending=1)
    assert third["persisted"] is True
    assert third["pending_delivery_overflow"] == 1
    assert third["pending_delivery_overflow_new"] == 0
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["delivery_overflow_count"] == 1


def test_delivery_receipt_requires_complete_exact_row_and_is_bounded(
        tmp_path, monkeypatch):
    row = {
        "ts_utc": "2026-07-24T12:00:00+00:00",
        "ts_mono": 1.0,
        "lane_id": 21,
        "severity": "info",
        "event_type": "service_restart",
        "code": "daemon_start",
        "detail": {"count": 1},
        "source_id": "node-a",
        "boot_id": "boot-a",
        "seq": 1,
    }
    log = tmp_path / "diag-20260724.jsonl"
    log.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert health_drop.delivery_receipt_status(
        str(tmp_path), row) == health_drop.DELIVERY_RECEIPT_EXACT

    mismatched = dict(row)
    mismatched["code"] = "tampered"
    log.write_text(json.dumps(mismatched) + "\n", encoding="utf-8")
    assert health_drop.delivery_receipt_status(
        str(tmp_path), row) == health_drop.DELIVERY_RECEIPT_MISMATCH

    log.write_text("{not-json}\n", encoding="utf-8")
    assert health_drop.delivery_receipt_status(
        str(tmp_path), row) == health_drop.DELIVERY_RECEIPT_AMBIGUOUS

    log.write_text(json.dumps(row) + "\n", encoding="utf-8")
    (tmp_path / "diag-20260723.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(health_drop, "DELIVERY_RECEIPT_MAX_FILES", 1)
    assert health_drop.delivery_receipt_status(
        str(tmp_path), row) == health_drop.DELIVERY_RECEIPT_AMBIGUOUS
