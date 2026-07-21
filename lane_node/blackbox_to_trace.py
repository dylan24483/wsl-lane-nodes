#!/usr/bin/env python3
"""
blackbox_to_trace.py — FlightRecorder blackbox dump -> trace_replay trace.

The named Layer-2 gap in docs/phase8_diagnostics_scope_2026-07-19.md §2:
FlightRecorder dumps a forensic timeline ({"lane", "reason", "events":
[{"t","kind","name","value"}, ...]} — see flight_recorder._write_dump), while
trace_replay consumes a DRIVING script ({"events": [{"t","kind":"input|call|
poll", ...}]}). The formats differ in kind: a dump records what the FSM DID
(outputs + observed state transitions); a trace records what was DONE TO the
FSM (cam calls, input levels, polls). This converter reconstructs the driving
events from the recorded effects so a real machine fault can be replayed
deterministically in CI:

    py -3 lane_node/blackbox_to_trace.py <blackbox.json> <out.trace>

HOW THE RECONSTRUCTION WORKS (follows code, not docs)
  Production dumps contain NO raw cam/ball records — the recorder taps are
  outputs (controller_io 'out'), 'arm', daemon 'state' transitions, telemetry
  rows and tick errors. So the converter is driven by the 'state' records
  (name=new, value=prev, recorded by controller_daemon._observe) mapped back
  to the FSM calls that cause each transition (mirroring rp2040_link.
  dispatch_cam: SA and TA1 are dual-trip cams and are emitted as their two
  explicit sub-calls, exactly like trace_replay's own builders). Poll-driven
  transitions (GUARD_DELAY exit, MAX_MOTION/GUARD_DELAY_MAX faults) become
  'poll' records; interlock-caused faults that can't be proven from timing are
  reproduced via a scripted interlock dip. Two SILENT edges (no state record)
  are synthesized from 'out' records: TA1-zero during RUNTHROUGH (table stops,
  T->off) and the fresh-rack TA1 park in TABLE_FINISH. The gripper mask is
  recovered from the 'out' pin_lamps record the TA2 latch writes (RecordingIO;
  MachineIO.set_pin_lamps has no recorder tap — then a fresh-rack/respot
  scan-ahead heuristic picks the mask). A dump that starts mid-cycle (ring
  eviction) gets a synthetic PREAMBLE walking a fresh FSM from POWER_OFF to
  the first record's prev-state.

HONEST LIMITS (reported, never silent)
  * Ball-parity drift: PBZ toggles in READY and on_foul reclassification leave
    no state record; the first in-window cycle's parity is corrected from a
    fresh-rack/mask scan-ahead, later invisible toggles can still skew Ball
    lamps (state sequence stays correct or verification fails loudly).
  * Bench-gated transitions (GUARD_DELAY->RUNTHROUGH skip-descent) are not
    reproducible under default module flags -> reported as a gap.
  * Multi-hop transitions inside one daemon tick (prev doesn't match the
    replay state) are reported as gaps, not guessed at.
  Every conversion is self-VERIFIED by replaying the produced trace through
  the live FSM (trace_replay.replay) and comparing the final state to the
  dump's last state record; the result lands in meta + the CLI exit code.

PURE SOFTWARE, READ-ONLY: imports the FSM + trace_replay, drives no hardware,
edits nothing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cycle_control_8270 import (State, MOTION_STATES, TIME_DELAY_S,  # noqa: E402
                                MAX_MOTION_S, GUARD_DELAY_MAX_S)

# state-value shorthands (the dump records State.value strings)
POWER_OFF_V = State.POWER_OFF.value
MI_V = State.MANUAL_INTERVENTION.value
READY_V = State.READY.value
SWEEP_TO_GUARD_V = State.SWEEP_TO_GUARD.value
GUARD_DELAY_V = State.GUARD_DELAY.value
TABLE_DETECT_V = State.TABLE_DETECT.value
RUNTHROUGH_V = State.RUNTHROUGH.value
SPOTTING_V = State.SPOTTING.value
TABLE_FINISH_V = State.TABLE_FINISH.value
FAULT_V = State.FAULT.value
STATE_VALUES = {s.value for s in State}
MOTION_VALUES = {s.value for s in MOTION_STATES}

# Preamble layout: the synthetic walk-up ends PRE_GAP seconds before the first
# dump record (> GUARD_DELAY_MAX_S so a first-record GUARD_DELAY fault can
# reproduce), with PRE_STEP between steps (> TIME_DELAY_S so the settle poll
# advances).
PRE_GAP = 40.0
PRE_STEP = 4.0
# Same-tick window: an 'out' record and the state record from the same FSM call
# land within this many seconds of each other (daemon tick is 20 ms).
EPS = 0.25
# Arbitrary-but-documented standing-pin mask used when a respot cycle's real
# latched mask never made it into the dump window (7 + 10 leave).
RESPOT_MASK = 0b0000000101


class ConvertError(Exception):
    """Unconvertible dump (bad shape / nothing to replay)."""


# ---- tiny trace-record builders -------------------------------------------------
def _call(t, name):
    return {"t": round(float(t), 6), "kind": "call", "name": name}


def _input(t, name, value):
    return {"t": round(float(t), 6), "kind": "input", "name": name, "value": value}


def _poll(t):
    return {"t": round(float(t), 6), "kind": "poll"}


def _sa_pair(t):
    """One physical SA edge = both angle sub-calls (rp2040_link.dispatch_cam)."""
    return [_call(t, "cam_SA_runthrough"), _call(t, "cam_SA_zero")]


def _ta1_pair(t):
    """One physical TA1 edge = both angle sub-calls (rp2040_link.dispatch_cam)."""
    return [_call(t, "cam_TA1_delayreset"), _call(t, "cam_TA1_zero")]


# ---- dump parsing ----------------------------------------------------------------
def _normalize_events(doc):
    evs = doc.get("events")
    if not isinstance(evs, list):
        raise ConvertError("dump has no 'events' list (not a FlightRecorder blackbox dump?)")
    out = []
    for i, e in enumerate(evs):
        if not isinstance(e, dict) or "kind" not in e:
            raise ConvertError(f"events[{i}] is not a {{t,kind,name,value}} record")
        try:
            t = float(e.get("t", 0.0))
        except Exception:
            t = 0.0
        out.append({"t": t, "kind": e.get("kind"), "name": e.get("name"),
                    "value": e.get("value")})
    return out


# ---- scan-ahead helpers ----------------------------------------------------------
def _fresh_rack_ahead(events, start_i):
    """From events[start_i+1:], does the cycle reach SPOTTING before READY?
    True = fresh-rack, False = respot, None = unknown (fault/window end first)."""
    for e in events[start_i + 1:]:
        if e["kind"] != "state":
            continue
        new = e["name"]
        if new == SPOTTING_V:
            return True
        if new == READY_V:
            return False
        if new in (FAULT_V, MI_V):
            return None
    return None


def _cycle_mask_ahead(events, start_i):
    """The pin_lamps mask the TA2 latch will record for the cycle starting at
    events[start_i], or None if it never lands in the window."""
    for e in events[start_i + 1:]:
        if e["kind"] == "out" and e["name"] == "pin_lamps":
            try:
                return int(e["value"])
            except Exception:
                return None
        if e["kind"] == "state" and e["name"] in (READY_V, FAULT_V, MI_V):
            break
    return None


def _next_state_rec(events, i):
    for e in events[i + 1:]:
        if e["kind"] == "state":
            return e
    return None


# ---- preamble: fresh FSM (POWER_OFF) -> the dump's starting state ----------------
def _build_preamble(target, t_first, mask):
    """Trace events walking a fresh CycleController to `target`, laid out so the
    last step lands PRE_GAP before t_first. Returns (events, notes)."""
    notes = []
    if target == POWER_OFF_V:
        return [], notes
    steps = [(0.0, lambda t: [_call(t, "power_restore")])]

    def _laid_out():
        total = sum(g for g, _ in steps)
        cursor = t_first - PRE_GAP - total
        evs = []
        for gap, maker in steps:
            cursor += gap
            evs.extend(maker(cursor))
        return evs

    if target == MI_V:
        return _laid_out(), notes
    steps.append((PRE_STEP, lambda t: [_call(t, "first_ball_zero")]))
    if target == READY_V:
        return _laid_out(), notes
    notes.append(f"dump starts mid-cycle ({target}); synthetic preamble with "
                 f"grippers mask {mask:#012b}")
    steps.append((PRE_STEP,
                  lambda t: [_input(t, "grippers", mask), _call(t, "on_ball")]))
    if target == SWEEP_TO_GUARD_V:
        return _laid_out(), notes
    if target == FAULT_V:
        # a motion left running past MAX_MOTION_S: one poll latches FAULT
        steps.append((MAX_MOTION_S + 1.0, lambda t: [_poll(t)]))
        return _laid_out(), notes
    steps.append((PRE_STEP, lambda t: [_call(t, "cam_SB_guard")]))
    if target == GUARD_DELAY_V:
        return _laid_out(), notes
    steps.append((PRE_STEP, lambda t: [_poll(t)]))     # PRE_STEP > TIME_DELAY_S
    if target == TABLE_DETECT_V:
        return _laid_out(), notes
    steps.append((PRE_STEP, lambda t: [_call(t, "cam_TA2_runthrough")]))
    if target == RUNTHROUGH_V:
        return _laid_out(), notes
    steps.append((PRE_STEP, lambda t: _sa_pair(t)))
    if target == TABLE_FINISH_V:
        return _laid_out(), notes
    # SPOTTING: fresh-rack only; mask was forced 0 by the caller
    steps.append((PRE_STEP,
                  lambda t: [_input(t, "bs", True), _call(t, "bin_full")]))
    return _laid_out(), notes


# ---- the converter ---------------------------------------------------------------
def convert(doc, source=None):
    """Convert one blackbox dump doc (parsed JSON dict) into a trace doc.
    Returns (trace_doc, report). Raises ConvertError only for an unusable dump
    (wrong shape / zero state records); mapping problems are reported, not
    raised."""
    events = _normalize_events(doc)
    state_is = [i for i, e in enumerate(events) if e["kind"] == "state"]
    if not state_is:
        raise ConvertError("dump contains no 'state' records — nothing to replay")
    for i in state_is:
        e = events[i]
        if e["name"] not in STATE_VALUES or e["value"] not in STATE_VALUES:
            raise ConvertError(f"events[{i}]: unrecognized state record "
                               f"{e['value']!r} -> {e['name']!r}")

    first_prev = events[state_is[0]]["value"]
    t_first = events[0]["t"]
    expected_final = events[state_is[-1]]["name"]

    # preamble cycle-class: fresh-rack needs mask 0, respot needs pins standing
    pre_fresh = _fresh_rack_ahead(events, -1)
    if first_prev == SPOTTING_V:
        pre_mask = 0
    else:
        pre_mask = 0 if pre_fresh in (True, None) else RESPOT_MASK
    out_events, notes = _build_preamble(first_prev, t_first, pre_mask)

    # replay-side tracking
    cur = first_prev
    entry_t = out_events[-1]["t"] if out_events else t_first - PRE_GAP
    table_done = first_prev in (TABLE_FINISH_V, SPOTTING_V) and pre_fresh is False
    ball_first = True                     # preamble PBZ arms 1st ball
    cycle_fresh = pre_mask == 0           # class of any preamble-started cycle
    last_pin_lamps = pre_mask if first_prev in (RUNTHROUGH_V, TABLE_FINISH_V,
                                                SPOTTING_V) else None
    gaps = []
    skipped = {}
    converted = 0

    def _trip_soon(nxt, t):
        return (nxt is not None and nxt["name"] in (FAULT_V, MI_V)
                and nxt["t"] - t < EPS)

    for i, rec in enumerate(events):
        kind, t = rec["kind"], rec["t"]

        if kind == "out":
            name, value = rec["name"], rec["value"]
            if name == "pin_lamps":
                try:
                    last_pin_lamps = int(value)
                except Exception:
                    pass
            off = value in (False, 0)
            nxt = _next_state_rec(events, i)
            # silent TA1 edge during RUNTHROUGH: table stops at zero, no state
            # record (cycle_control_8270.cam_TA1_zero RUNTHROUGH branch)
            if name == "T" and off and cur == RUNTHROUGH_V and not _trip_soon(nxt, t):
                out_events.extend(_ta1_pair(t))
                table_done = True
            # fresh-rack TA1 park in TABLE_FINISH ("awaiting BS"): T->off with no
            # state change. The respot-completion T->off is part of the same-tick
            # (table_finish -> ready) transition and is handled by its mapping.
            elif name == "T" and off and cur == TABLE_FINISH_V:
                same_tick_finish = (nxt is not None and nxt["name"] == READY_V
                                    and nxt["value"] == TABLE_FINISH_V
                                    and nxt["t"] - t < EPS)
                if not same_tick_finish and not _trip_soon(nxt, t):
                    out_events.extend(_ta1_pair(t))
                    table_done = True
            # sweep-zero SA edge after the run-through stop (S->off in
            # TABLE_FINISH/SPOTTING, no state change)
            elif (name == "S" and off and cur in (TABLE_FINISH_V, SPOTTING_V)
                    and not _trip_soon(nxt, t)):
                out_events.extend(_sa_pair(t))
            # keep every output as a descriptive record (replay ignores them)
            out_events.append({"t": round(t, 6), "kind": "output",
                               "name": str(name), "value": value})
            continue

        if kind != "state":
            skipped[str(kind)] = skipped.get(str(kind), 0) + 1
            continue

        new, prev = rec["name"], rec["value"]
        if prev != cur:
            gaps.append(f"events[{i}] t={t:.3f}: dump transition {prev} -> {new} "
                        f"but replay is at {cur} (multi-hop tick or ring gap)")
            continue

        seq = None
        if new == MI_V:
            seq = [_call(t, "first_ball_zero")] if prev == FAULT_V \
                else [_call(t, "power_restore")]
        elif new == FAULT_V:
            if prev == GUARD_DELAY_V:
                # only the GUARD_DELAY_MAX_S bound faults here; GP is held open
                # so the settle poll can't advance to TABLE_DETECT instead.
                tp = max(t, entry_t + GUARD_DELAY_MAX_S + 0.01)
                seq = [_input(t, "gp", False), _poll(tp), _input(tp, "gp", True)]
            elif prev in MOTION_VALUES:
                if (t - entry_t) > MAX_MOTION_S:
                    seq = [_poll(t)]      # MAX_MOTION_S backstop reproduces it
                else:
                    # timing can't prove a timeout — reproduce via a scripted
                    # interlock dip (mid-motion re-check faults identically)
                    seq = [_input(t, "interlock", False), _poll(t),
                           _input(t, "interlock", True)]
        elif prev == MI_V and new == READY_V:
            seq = [_call(t, "first_ball_zero")]
            ball_first = True
        elif prev == READY_V and new == SWEEP_TO_GUARD_V:
            seq = []
            fresh = _fresh_rack_ahead(events, i)
            mask = _cycle_mask_ahead(events, i)
            # parity fix: a fresh-rack cycle with pins standing is a SECOND
            # ball; a respot requires a FIRST ball. PBZ in READY toggles.
            if fresh is True and mask and ball_first:
                seq.append(_call(t, "first_ball_zero"))
                ball_first = False
            elif fresh is False and not ball_first:
                seq.append(_call(t, "first_ball_zero"))
                ball_first = True
            cycle_fresh = not ball_first  # SECOND_BALL is fresh; FIRST refined at TA2
            table_done = False
            seq.append(_call(t, "on_ball"))
        elif prev == SWEEP_TO_GUARD_V and new == GUARD_DELAY_V:
            seq = [_call(t, "cam_SB_guard")]
        elif prev == GUARD_DELAY_V and new == TABLE_DETECT_V:
            tp = max(t, entry_t + TIME_DELAY_S + 0.001)
            if tp > t + 0.01:
                notes.append(f"events[{i}]: settle poll nudged {tp - t:.3f}s "
                             f"forward to satisfy TIME_DELAY_S")
            seq = [_poll(tp)]
        elif prev == GUARD_DELAY_V and new == RUNTHROUGH_V:
            gaps.append(f"events[{i}] t={t:.3f}: bench-gated skip-descent "
                        f"transition (GUARD_DELAY -> RUNTHROUGH) is not "
                        f"reproducible under default flags")
            continue
        elif prev == TABLE_DETECT_V and new == RUNTHROUGH_V:
            if last_pin_lamps is not None:
                mask = last_pin_lamps
            else:
                fresh = _fresh_rack_ahead(events, i)
                mask = 0 if fresh in (True, None) else RESPOT_MASK
                notes.append(f"events[{i}]: no pin_lamps record — grippers mask "
                             f"assumed {mask:#012b} from cycle shape")
            if ball_first and mask == 0:
                cycle_fresh = True        # STRIKE reclassification at the latch
            seq = [_input(t, "grippers", int(mask)),
                   _call(t, "cam_TA2_runthrough")]
        elif prev == RUNTHROUGH_V and new == TABLE_FINISH_V:
            seq = _sa_pair(t)
        elif prev == RUNTHROUGH_V and new == READY_V:
            # respot completed inside the SA call (table already at zero)
            seq = ([] if table_done else _ta1_pair(t)) + _sa_pair(t)
            ball_first = cycle_fresh
        elif prev == TABLE_FINISH_V and new == SPOTTING_V:
            seq = [_input(t, "bs", True), _call(t, "bin_full")]
        elif prev == TABLE_FINISH_V and new == READY_V:
            seq = _ta1_pair(t)
            ball_first = cycle_fresh
        elif prev == SPOTTING_V and new == READY_V:
            seq = _ta1_pair(t)
            ball_first = cycle_fresh
        elif prev == POWER_OFF_V and new == MI_V:
            seq = [_call(t, "power_restore")]

        if seq is None:
            gaps.append(f"events[{i}] t={t:.3f}: no conversion for transition "
                        f"{prev} -> {new}")
            continue
        out_events.extend(seq)
        cur = new
        entry_t = seq[-1]["t"] if seq else t
        converted += 1

    # ---- self-verification: replay the produced trace through the live FSM ----
    verified = False
    verify_error = None
    try:
        import trace_replay
        c, _io = trace_replay.replay(out_events,
                                     lane_id=doc.get("lane") or 21)
        verified = c.state.value == expected_final
        if not verified:
            verify_error = (f"replayed final state {c.state.value!r} != dump "
                            f"final state {expected_final!r}")
    except Exception as e:
        verify_error = f"replay raised {type(e).__name__}: {e}"

    report = {
        "states_converted": converted,
        "expected_final_state": expected_final,
        "verified": verified,
        "verify_error": verify_error,
        "gaps": gaps,
        "skipped_kinds": skipped,
        "notes": notes,
    }
    trace_doc = {
        "meta": {
            "converter": "blackbox_to_trace r1",
            "source": source,
            "lane": doc.get("lane"),
            "reason": doc.get("reason"),
            "wall_iso": doc.get("wall_iso"),
            **report,
        },
        "events": out_events,
    }
    return trace_doc, report


# ---- CLI -------------------------------------------------------------------------
USAGE = ("usage: py -3 blackbox_to_trace.py <dump.json> <out.trace> [--lenient]\n"
         "  exit 0 = converted + replay-verified;  1 = unusable dump / IO error;\n"
         "  2 = converted with gaps or failed verification (suppress with --lenient)")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    lenient = "--lenient" in args
    args = [a for a in args if not a.startswith("--")]
    if len(args) != 2:
        print(USAGE)
        return 1
    dump_path, out_path = args
    try:
        with open(dump_path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        print(f"ERROR reading {dump_path}: {e}")
        return 1
    try:
        trace_doc, report = convert(doc, source=os.path.basename(dump_path))
    except ConvertError as e:
        print(f"ERROR: {e}")
        return 1
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(trace_doc, f, indent=2)
    except OSError as e:
        print(f"ERROR writing {out_path}: {e}")
        return 1

    print(f"converted {report['states_converted']} state transitions "
          f"-> {len(trace_doc['events'])} trace events -> {out_path}")
    if report["skipped_kinds"]:
        print(f"  skipped (non-replayable kinds): {report['skipped_kinds']}")
    for n in report["notes"]:
        print(f"  note: {n}")
    for g in report["gaps"]:
        print(f"  GAP: {g}")
    if report["verified"]:
        print(f"  verify: OK — replay reaches {report['expected_final_state']!r}")
    else:
        print(f"  verify: FAILED — {report['verify_error']}")
    if (report["gaps"] or not report["verified"]) and not lenient:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
