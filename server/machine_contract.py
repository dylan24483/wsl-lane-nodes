#!/usr/bin/env python3
"""machine_contract.py — the ONE loader for server/machine_contract.json.

R3-1a (Codex round-3, 2026-07-23) — the never-again gate for the
three-round cross-contract vocabulary-drift failure class. The
machine-diagnostics HTTP vocabulary (event types, cycle types, severities,
board/final states, interval columns, outbox record kinds) now has ONE
definition: server/machine_contract.json. Every consumer LOADS it here
instead of re-declaring its own copy:

  * server side  — server/machine_store.py imports load_vocab() to populate
    EVENT_TYPES / CYCLE_TYPES / FINAL_STATES / SEVERITIES / MACHINE_STATES /
    INTERVAL_COLUMNS. There is no second hand-maintained list to drift.
  * client side  — lane_node/diag_events.py imports the SAME file (via its
    own tiny loader that reaches this path) for SEVERITIES and the
    client-side event-type allow-set.
  * tests        — tests/test_event_type_vocab_coverage.py statically walks
    every emit site across lane_node/*.py and fails if any emitted
    event_type is absent here (the enumeration gate); tests/
    test_machine_diagnostics.py pins the sha256 sidecar.

The root failure this closes (R3-1 poison pill): the daemon emitted
'fw_identity' but machine_store's hand-kept EVENT_TYPES set omitted it, so
the server 400'd the WHOLE batch and the outbox cursor never advanced. With
the vocabulary loaded from one file, a type a consumer emits can no longer
be silently missing from the validator — and if a NEW type is ever added at
an emit site without updating the contract, the enumeration test fails
before it ships.

Fail posture: if the JSON is unreadable (a partial deploy), load_vocab()
raises ContractUnavailable and the caller decides. machine_store can import
with the frozen reviewed snapshot embedded here, but live ingest remains
unavailable until the on-disk contract is readable and matches what was loaded.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parent / "machine_contract.json"
FALLBACK_PROTOCOL_VERSION = 3


class ContractUnavailable(RuntimeError):
    """Raised when the contract file cannot be read/parsed."""


# Frozen last-known-good snapshot (refreshed in lockstep with the JSON; the
# sha256 sidecar test + the vocab-coverage test guard against silent drift).
# Used only when the JSON is missing at import time and the caller opts in.
# It keeps status reachable; diagnostics ingest still fails closed.
_FALLBACK_VOCAB = {
    "severities": ("info", "warn", "fault"),
    "states": ("HEALTHY", "DEGRADED", "FAULT", "OFFLINE", "UNKNOWN",
               "MAINTENANCE"),
    "cycle_types": ("ball", "reset", "power_on", "manual", "test"),
    "final_states": ("READY", "FAULT", "MANUAL_INTERVENTION"),
    "record_kinds": ("event", "cycle"),
    "controller_modes": ("live", "shadow"),
    "identity_assurances": ("verified", "legacy_unverified", "invalid"),
    "controller_fsm_states": (
        "power_off", "manual_intervention", "ready", "sweep_to_guard",
        "guard_delay", "table_detect", "runthrough", "spotting",
        "table_finish", "fault",
    ),
    "safety_tap_fields": (
        "ne555", "wdog_kick", "arm_permit", "rp2040_ok",
    ),
    "scoring_event_types": ("ball_event", "foul_event"),
    "scoring_event_dispositions": (
        "accepted", "duplicate", "ignored_lane_closed", "awaiting_manual",
        "stale_quarantined", "overdue_quarantined",
        "clock_anomaly_quarantined",
        "duplicate_window_suppressed",
    ),
    "command_types": (
        "cycle", "open_lane", "close_lane", "reset", "power_on",
        "power_off", "scoring_epoch_sync",
    ),
    "actuating_command_types": (
        "cycle", "open_lane", "close_lane", "reset", "power_on",
        "power_off",
    ),
    "command_ack_statuses": (
        "completed", "duplicate", "refused", "ambiguous", "failed",
    ),
    "manual_reconciliation_conditions": (
        "stale_scoring_epoch", "overdue_scoring_event",
        "scoring_event_lost", "command_indeterminate",
        "command_ambiguous", "command_collision", "command_refused",
        "command_failed", "operation_receipts_incomplete",
        "privileged_resolution_override", "cycle_delivery_indeterminate",
    ),
    "interval_columns": ("ss_to_guard_ms", "guard_to_table_ms",
                         "table_to_ta2_ms", "ta2_to_sa_ms",
                         "sa_to_ta1zero_ms", "bs_to_ta1zero_ms"),
    # Frozen reviewed allow-set. Missing live JSON must never become
    # accept-any taxonomy validation during a partial deployment.
    "event_types": {
        "ball_return_missing", "bank_unavailable", "be_no_current",
        "be_stuck_running", "beam_blocked", "camera_health",
        "camera_ref_drift", "chatter", "command_transport",
        "configured_role_missing",
        "control_loop_stalled", "contract_unavailable",
        "diag_corrupt_row", "diag_drops", "diag_storage_error",
        "diag_storage_pruned", "dist_index_stall", "drift_alarm",
        "field_wet_lost", "field_wet_restored", "fsm_fault",
        "fw_config_mismatch", "fw_fault", "fw_identity",
        "fw_identity_missing", "fw_reboot", "gripper_disagree",
        "gs_camera_disagree", "health_drop_stale",
        "health_drop_unhealthy", "heartbeat_rejected",
        "http_sink_drops", "link_lost", "maintenance_overdue",
        "manual_override", "outbox_quarantine", "pi_clock_drift",
        "pi_disk_low", "pi_fs_readonly", "pi_thermal",
        "pi_undervoltage", "rail_drop", "recovered",
        "rp2040_serial_corrupt", "rp2040_wdt_reset", "run_mismatch",
        "sensor_supply_lost", "sensor_supply_restored",
        "scoring_server_ack_stalled", "scoring_event_transport",
        "service_restart",
        "service_restart_loop", "short_rack",
        "stale_channel", "stuck_input", "tap_warn", "tapdump",
        "uart_drops", "unexpected_edge", "v5_out_of_range",
    },
}


def load_contract(path=None):
    """Parse and return the whole contract dict. Raises ContractUnavailable."""
    p = Path(path) if path else CONTRACT_PATH
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001 — any read/parse failure is the same
        raise ContractUnavailable(f"cannot load {p}: {e}") from e


def contract_sha256(path=None):
    """Return the digest of a readable, parseable live contract.

    A sidecar is intentionally never consulted. Deployment identity is the
    JSON content this process can parse, not an adjacent assertion about it.
    """
    p = Path(path) if path else CONTRACT_PATH
    try:
        raw = p.read_bytes()
        json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - all unavailable forms are equal
        raise ContractUnavailable(f"cannot hash live contract {p}: {e}") from e
    return hashlib.sha256(raw).hexdigest()


def load_vocab(path=None, *, allow_fallback=False):
    """Return the vocab sub-dict with tuple/frozenset-friendly values.

    Keys include the diagnostic, scoring-event, and command vocabularies plus
    cycle/final/machine states, record kinds, and interval columns.
    event_types is returned as a set (writer validation membership); ordered
    lists stay tuples so lockstep-order assertions keep working.
    """
    try:
        c = load_contract(path)
        v = c["vocab"]
        return {
            "severities": tuple(v["severities"]),
            "event_types": set(v["event_types"]),
            "cycle_types": tuple(v["cycle_types"]),
            "final_states": tuple(v["final_states"]),
            "states": tuple(v["states"]),
            "record_kinds": tuple(v.get("record_kinds", ("event", "cycle"))),
            "controller_modes": tuple(v["controller_modes"]),
            "identity_assurances": tuple(v["identity_assurances"]),
            "controller_fsm_states": tuple(v["controller_fsm_states"]),
            "safety_tap_fields": tuple(v["safety_tap_fields"]),
            "scoring_event_types": tuple(v["scoring_event_types"]),
            "scoring_event_dispositions": tuple(
                v["scoring_event_dispositions"]),
            "command_types": tuple(v["command_types"]),
            "actuating_command_types": tuple(v["actuating_command_types"]),
            "command_ack_statuses": tuple(v["command_ack_statuses"]),
            "manual_reconciliation_conditions": tuple(
                v["manual_reconciliation_conditions"]),
            "interval_columns": tuple(v["interval_columns"]),
        }
    except (ContractUnavailable, KeyError, TypeError):
        if allow_fallback:
            fb = dict(_FALLBACK_VOCAB)
            # Return a copy so callers cannot mutate the frozen reviewed
            # allow-set. This fallback never authorizes live ingest by itself;
            # diagnostics_contract_ready() still requires the live JSON.
            fb["event_types"] = set(_FALLBACK_VOCAB["event_types"])
            return fb
        raise
