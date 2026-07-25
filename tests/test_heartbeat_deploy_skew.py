"""Heartbeat contract must survive the split-deploy boundary (round-5 audit).

The heartbeat producer is `controller_daemon` on the Pi; the validator is
`machine_store` behind `lane_node_server` on WSL-SRV. Same repo, DIFFERENT
machines, updated independently -- deploy.ps1 states outright that it "never
git-updates the lane repo".

Round 5 added 9 REQUIRED fields while also rejecting unknown fields. That made
BOTH deploy orders fail:

  * old Pi -> new server  ->  "heartbeat missing required fields: [...]"
  * new Pi -> old server  ->  "heartbeat has unknown fields: [...]"

and because `_maybe_heartbeat` swallowed the exception with no log line, the
deadlock was SILENT: `controller_seen_at` never renewed, both lanes fell to
OFFLINE, and `wsl_machine_alerts` raised `machine_offline` ~300 s later with
no hint that the cause was a schema mismatch.

These tests pin the two properties that make the schema deployable again:
additive fields are tolerated, and every rejection names its likely cause.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))

import machine_store  # noqa: E402


def _valid_body():
    """A minimal heartbeat that satisfies the current contract."""
    return {
        "lane_id": 21,
        "controller_boot_id": "boot-abc",
        "heartbeat_seq": 1,
        "control_loop_seq": 1,
        "controller_mode": "shadow",
        "live_outputs_acknowledged": False,
        "arm_state": False,
        "fsm_state": "idle",
        "manual_rearm_required": False,
        "legacy_identity_mode": False,
        "identity_assurance": "verified",
        "arm_prerequisite_reason": None,
        "safety_taps": {
            "ne555": True, "wdog_kick": True,
            "arm_permit": False, "rp2040_ok": True,
        },
        "board_rev": "revD",
        "contract_sha256": "0" * 64,
        "contract_loaded": True,
        "identity_ok": True,
        "ro_fs": False,
        "outbox": {
            "cursor_ok": True, "write_errors": 0, "sink_errors": 0,
            "dropped": 0, "health_unavailable": False,
        },
        "platform": {"ok": True, "reasons": []},
        # A verified rev-D board must carry complete identity evidence.
        "observed_pcb": "revD",
        "observed_rid": "rid-21",
        "observed_uid": "uid-21",
        "fw_build": "rel-0c746b5747143b8011b01d43",
        "fw_cfg": "05d808411db4bb0d",
        "fw_version": "phase8b-rp2040 v1.2.3",
    }


def _validate(body):
    """Validate, tolerating shape errors unrelated to the field-set contract.

    These tests are about WHICH KEYS are accepted, not about the value schema
    of safety_taps/outbox/platform, which other suites cover.
    """
    try:
        return machine_store.validate_heartbeat(body), None
    except ValueError as exc:
        return None, str(exc)


def _field_set_error(message):
    """True if the failure is about the accepted key set."""
    return message is not None and (
        "missing required fields" in message or "unknown fields" in message)


# --- forward compatibility: a NEWER producer must not be dropped -----------

def test_unknown_additive_fields_are_tolerated_not_rejected():
    """The regression that made the schema un-deployable.

    A newer lane node sending a field this build has never heard of must not
    lose its lease over it. A server cannot act on a field it does not
    understand either way, so dropping the WHOLE heartbeat buys nothing and
    costs the lane's liveness. This matches the rule the RP2040 link protocol
    already follows for additive fields.
    """
    body = _valid_body()
    body["some_future_field_v6"] = {"nested": True}
    body["another_new_flag"] = False
    _, error = _validate(body)
    assert not _field_set_error(error), (
        f"additive fields must not be rejected, got: {error}")


def test_ignored_unknown_fields_are_reported_not_hidden():
    """Tolerance must be observable, or it masks real producer drift."""
    body = _valid_body()
    body["some_future_field_v6"] = 1
    row, error = _validate(body)
    assert error is None, f"fixture must be a valid heartbeat: {error}"
    assert row["_unknown_fields"] == ["some_future_field_v6"]


def test_unknown_fields_do_not_leak_into_the_persisted_row():
    body = _valid_body()
    body["some_future_field_v6"] = 1
    row, error = _validate(body)
    assert error is None, f"fixture must be a valid heartbeat: {error}"
    assert "some_future_field_v6" not in row


# --- backward direction: still fail closed, but say WHY -------------------

@pytest.mark.parametrize("field", [
    "controller_mode", "live_outputs_acknowledged", "arm_state", "fsm_state",
    "manual_rearm_required", "legacy_identity_mode", "identity_assurance",
    "arm_prerequisite_reason", "safety_taps",
])
def test_missing_runtime_safety_field_is_still_rejected(field):
    """Do NOT weaken this: the server must not infer a safety posture."""
    body = _valid_body()
    body.pop(field)
    _, error = _validate(body)
    assert error is not None and "missing required fields" in error
    assert field in error


def test_missing_field_error_names_the_deploy_skew_cause():
    """An operator seeing only 'lane OFFLINE' must be able to find this."""
    body = _valid_body()
    body.pop("arm_state")
    _, error = _validate(body)
    assert error is not None
    assert "OLDER build" in error
    assert "phase8_pi_provisioning" in error


def test_a_complete_current_heartbeat_is_accepted():
    row, error = _validate(_valid_body())
    assert error is None, f"fixture must be a valid heartbeat: {error}"
    assert row["lane_id"] == 21
    assert row["_unknown_fields"] == []
