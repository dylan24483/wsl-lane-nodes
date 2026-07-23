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
raises ContractUnavailable and the caller decides. machine_store fails
CLOSED to a frozen last-known snapshot embedded here as
_FALLBACK_VOCAB only when explicitly asked (load_vocab(allow_fallback=True))
— the fallback is refreshed in lockstep with the JSON and the sha256 test
guards it, but a live server must never die because a deploy dropped the
file mid-copy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parent / "machine_contract.json"


class ContractUnavailable(RuntimeError):
    """Raised when the contract file cannot be read/parsed."""


# Frozen last-known-good snapshot (refreshed in lockstep with the JSON; the
# sha256 sidecar test + the vocab-coverage test guard against silent drift).
# Used ONLY when the JSON is missing at runtime AND the caller opts in — a
# live daemon must not die because a deploy dropped the file mid-copy.
_FALLBACK_VOCAB = {
    "severities": ("info", "warn", "fault"),
    "states": ("HEALTHY", "FAULT", "OFFLINE", "UNKNOWN", "MAINTENANCE"),
    "cycle_types": ("ball", "reset", "power_on", "manual", "test"),
    "final_states": ("READY", "FAULT", "MANUAL_INTERVENTION"),
    "record_kinds": ("event", "cycle"),
    "interval_columns": ("ss_to_guard_ms", "guard_to_table_ms",
                         "table_to_ta2_ms", "ta2_to_sa_ms",
                         "sa_to_ta1zero_ms", "bs_to_ta1zero_ms"),
}


def load_contract(path=None):
    """Parse and return the whole contract dict. Raises ContractUnavailable."""
    p = Path(path) if path else CONTRACT_PATH
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001 — any read/parse failure is the same
        raise ContractUnavailable(f"cannot load {p}: {e}") from e


def load_vocab(path=None, *, allow_fallback=False):
    """Return the vocab sub-dict with tuple/frozenset-friendly values.

    Keys: severities, event_types, cycle_types, final_states, states
    (== MACHINE_STATES), record_kinds, interval_columns. event_types is
    returned as a set (writer validation membership); the ordered lists stay
    tuples so lockstep-order assertions keep working.
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
            "interval_columns": tuple(v["interval_columns"]),
        }
    except (ContractUnavailable, KeyError, TypeError):
        if allow_fallback:
            fb = dict(_FALLBACK_VOCAB)
            # event_types has no frozen fallback on purpose — a validator that
            # silently narrows the type set would re-open the poison-pill bug.
            # Fallback ingest accepts any string event_type (fail-open on the
            # taxonomy, never on delivery); the coverage test still gates dev.
            fb["event_types"] = None
            return fb
        raise
