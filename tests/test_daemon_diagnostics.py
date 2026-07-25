"""test_daemon_diagnostics.py — wave-2 daemon/link/telemetry integration of the
2026-07-19 machine-diagnostics campaign (scope §3/§5 Phase 1).

Covers, hardware-free (BoardController sim mode: RecordingIO + serial-less
RP2040Link on ONE shared fake clock):
  * no tick-path blocking: emit under a FULL DiagQueue returns immediately
  * manual-override events + the alert-suppression window (downgrade-to-info,
    expiry re-enables warns)
  * mid-session stuck-input rule (threshold, once-per-episode, BS exempt)
  * DIELL beam-blocked rule off the hb in-mask levels
  * AUX sensor rules (be_current stuck/no-current, dist_index stall,
    exit_beam ball-return) INCLUDING fully-dormant-when-unmapped
  * BallReturnTracker attribution (rudder_side / shared_lift / unknown)
  * fw timestamp plumbing: two edges drained in ONE tick still measure their
    true fw-clock interval; fw_reboot resyncs the FwClock
  * safety-trip event emission (fsm_fault / link_lost / fw_reboot /
    rp2040_wdt_reset / rail_drop) + machine_cycles row assembly
  * CamTelemetry baseline persistence round-trip (atomic, stale-file tolerant)
  * CycleShipper bounded offer + background shipping; PlatformHealth basics

Run under pytest (py -m pytest tests/test_daemon_diagnostics.py) or standalone
(py -3 tests/test_daemon_diagnostics.py).
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lane_node')))

import controller_daemon as cd
from controller_daemon import (  # noqa: E402
    BoardController, BoardConfig, LaneDiag, BallReturnTracker, PlatformHealth,
    _aux_roles_for_lane, _parse_aux_roles, _provision_aux_roles,
    _wire_pair_diagnostics, _drain_final_diagnostics)
from cam_telemetry import CamTelemetry, CycleShipper
from cycle_control_8270 import State, MAX_MOTION_S, TIME_DELAY_S
from diag_events import DiagQueue, DiagWriter
from rp2040_link import RP2040Link, FwClock, HB_IN_BITS


# ── helpers ─────────────────────────────────────────────────────────────────────

class FakeWriter:
    """Duck-typed DiagWriter: records every emitted DiagEvent."""

    def __init__(self):
        self.events = []

    def emit(self, ev):
        self.events.append(ev)
        return True

    def emit_durable(self, ev, timeout=2.0):
        return self.emit(ev)

    def of_type(self, event_type):
        return [e for e in self.events if e.event_type == event_type]


class ToggleWriter:
    """Writer stub that records attempts and can model a full/recovering queue."""

    def __init__(self, accept=False):
        self.accept = bool(accept)
        self.attempts = []
        self.events = []

    def emit(self, event):
        self.attempts.append(event)
        if not self.accept:
            return False
        self.events.append(event)
        return True

    def emit_durable(self, event, timeout=2.0):
        return self.emit(event)

    def of_type(self, event_type):
        return [e for e in self.events if e.event_type == event_type]


class FakeShipper:
    def __init__(self):
        self.rows = []

    def offer(self, row):
        self.rows.append(row)
        return True


def mk_board(roles=None, writer=None, shipper=None, cam_sink=None,
             board_rev="revC", slow_debounce_n=1, fsm_debounce_n=None):
    # slow_debounce_n=1 keeps the rule-logic tests on raw single-tick pulses
    # (debounce passthrough); the debounce layer itself has dedicated tests
    # below (test_slow_debounce_* / test_diag_debounce_*).
    return BoardController(BoardConfig(
                               21, 1, "sim", 0, 0,
                               board_rev=board_rev,
                               allowed_fw_builds=("test-build",),
                               allowed_fw_cfgs=("test-cfg",),
                               qualified_fw_releases=(
                                   (board_rev, "test-build", "test-cfg"),),
                               supported_fw_board_revisions=(board_rev,),
                               allow_legacy_revc_no_identity=(
                                   board_rev == "revC"),
                               legacy_revc_no_identity_enrolled=(
                                   board_rev == "revC")),
                           sim=True,
                           diag_writer=writer, cycle_shipper=shipper,
                           cam_sink=cam_sink, aux_roles=roles or {},
                           slow_debounce_n=slow_debounce_n,
                           fsm_debounce_n=fsm_debounce_n)


def hb(bc, extra=""):
    fields = json.loads("{" + extra.lstrip(",") + "}") if extra else {}
    if "up" not in fields:
        fields["up"] = max(
            getattr(bc, "_test_hb_up", 0),
            int(bc.io.now() * 1000))
    bc._test_hb_up = max(
        getattr(bc, "_test_hb_up", 0), int(fields["up"]))
    fields.update({"ev": "hb", "ok": 1})
    if bc.cfg.board_rev == "revD":
        fields.setdefault("bn", 123)
        fields.setdefault("rid", 1)
        fields.setdefault("flt", "")
        fields.setdefault("drp", 0)
        fields.setdefault("in", 0)
        fields.setdefault("run", 0)
        fields.setdefault("tap", 13)
        fields.setdefault("rd", 0)
        fields.setdefault("ep", 1)
        fields.setdefault("v5", 5000)
        fields.setdefault("v5n", 4990)
        fields.setdefault("v5x", 5010)
    bc.link.feed_line(json.dumps(fields, separators=(",", ":")))


def to_ready(bc):
    hb(bc)
    if bc.cfg.board_rev == "revD":
        bc.link.feed_line(
            '{"ev":"id","fw":"test","bn":123,"pcb":"revD","rid":1,'
            '"uid":"TEST","build":"test-build","cfg":"test-cfg",'
            '"fi1":0,"t":1}')
    bc.tick()
    bc.io.slow["PBZ"] = True
    bc.tick()
    bc.io.slow["PBZ"] = False
    hb(bc)
    bc.tick()
    assert bc.fsm.state is State.READY, bc.fsm.state


def advance(bc, dt):
    """Advance the shared fake clock and keep the link heartbeat fresh."""
    bc.io.advance(dt)
    hb(bc)


def run_strike_cycle(bc):
    """Drive one full strike cycle through tick() (no fw timestamps; events are
    Pi-receive-time stamped, so the clock advances between ball and SB to give
    ss_to_guard a real nonzero duration)."""
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    advance(bc, 0.5)
    bc.link.feed_line('{"ev":"cam","id":"SB","e":"f"}'); bc.tick()
    advance(bc, TIME_DELAY_S + 0.1); bc.tick()
    bc.link.feed_line('{"ev":"cam","id":"TA2","e":"f"}'); bc.tick()
    bc.link.feed_line('{"ev":"cam","id":"SA","e":"f"}'); bc.tick()
    bc.io.slow["BS"] = True; bc.tick(); bc.io.slow["BS"] = False
    bc.link.feed_line('{"ev":"cam","id":"TA1","e":"f"}'); bc.tick()
    assert bc.fsm.state is State.READY, bc.fsm.state


class _EnvPatch:
    def __init__(self, **kv):
        self.kv = kv
        self.saved = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v

    def __exit__(self, *a):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


# ── no tick-path blocking ───────────────────────────────────────────────────────

def test_emit_under_full_queue_returns_immediately():
    q = DiagQueue(maxsize=2)
    w = DiagWriter(queue=q, sinks=[], enabled=True)   # never started: queue fills
    diag = LaneDiag(21, writer=w)
    assert diag.emit_event("warn", "stuck_input", code="input:PBZ", t=0.0)
    assert diag.emit_event("warn", "stuck_input", code="input:PBZ", t=0.0)
    t0 = time.monotonic()
    results = [diag.emit_event("warn", "stuck_input", code="input:PBZ", t=0.0)
               for _ in range(500)]
    elapsed = time.monotonic() - t0
    assert not any(results), "full queue must DROP, never accept"
    assert q.drops == 500, q.drops
    assert elapsed < 0.5, f"500 emits under a full queue took {elapsed:.3f}s (blocking?)"


# ── manual override + suppression window ───────────────────────────────────────

def test_rejected_current_alert_is_canceled_before_due_retry_on_clear():
    with _EnvPatch(WSL_DIAG_BEAM_BLOCKED_S="1"):
        w = ToggleWriter()
        diag = LaneDiag(21, writer=w)
        levels = {"DIELL_L": True}
        diag.poll(
            0.0, ready=True, in_motion=False,
            slow_levels={}, inb_levels={}, diell_levels=levels)
        diag.poll(
            2.0, ready=True, in_motion=False,
            slow_levels={}, inb_levels={}, diell_levels=levels)
        assert ("beam_blocked", "diell:DIELL_L") in diag._pending_alerts

        w.accept = True
        diag.poll(
            2.3, ready=True, in_motion=False,
            slow_levels={}, inb_levels={},
            diell_levels={"DIELL_L": False})
        assert w.of_type("beam_blocked") == []
        assert ("beam_blocked", "diell:DIELL_L") not in diag._pending_alerts


def test_rejected_supply_fault_is_canceled_before_due_retry_on_restore():
    w = ToggleWriter()
    diag = LaneDiag(
        21, writer=w, aux_roles={"AUX10": "sensor_24v_ok"})
    diag.poll(
        0.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels={"AUX10": True})
    diag.poll(
        1.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels={"AUX10": False})
    assert ("sensor_supply_lost", "aux:AUX10") \
        in diag._pending_alerts

    w.accept = True
    diag.poll(
        1.3, ready=True, in_motion=False,
        slow_levels={}, inb_levels={"AUX10": True})
    assert w.of_type("sensor_supply_lost") == []
    assert len(w.of_type("sensor_supply_restored")) == 1


def test_incident_retry_survives_master_blind_but_current_alert_does_not():
    with _EnvPatch(WSL_DIAG_DAEMON_EVENTS="1"):
        w = ToggleWriter()
        diag = LaneDiag(21, writer=w)
        diag.emit_event(
            "fault", "rail_drop", code="tick_error_budget", t=1.0,
            persistent=True, retain_across_blind=True)
        diag.emit_event(
            "warn", "beam_blocked", code="diell:DIELL_L", t=1.0,
            persistent=True)
        assert len(diag._pending_alerts) == 2

        os.environ["WSL_DIAG_DAEMON_EVENTS"] = "0"
        diag.poll(
            1.1, ready=True, in_motion=False,
            slow_levels={}, inb_levels={},
            diell_levels={"DIELL_L": False})
        assert ("rail_drop", "tick_error_budget") in diag._pending_alerts
        assert ("beam_blocked", "diell:DIELL_L") not in diag._pending_alerts

        os.environ["WSL_DIAG_DAEMON_EVENTS"] = "1"
        w.accept = True
        diag.poll(
            1.3, ready=True, in_motion=False,
            slow_levels={}, inb_levels={},
            diell_levels={"DIELL_L": False})
        delivered = w.of_type("rail_drop")
        assert len(delivered) == 1
        assert delivered[0].detail["delivery_retry"] == 1


def test_failed_board_delivery_pump_preserves_safety_occurrence_timestamp():
    w = ToggleWriter()
    bc = mk_board(writer=w)
    bc._on_safety_trip("tick_error_budget")
    pending = bc.diag._pending_alerts[
        ("rail_drop", "tick_error_budget")]["event"]
    original_stamp = (pending.ts_utc, pending.ts_mono)
    w.accept = True
    assert bc.diag.pump_pending_delivery(
        bc.io.now() + 1.0, force=True) == 0
    delivered = w.of_type("rail_drop")
    assert len(delivered) == 1
    assert delivered[0].code == "tick_error_budget"
    assert delivered[0].detail["delivery_retry"] == 1
    assert (delivered[0].ts_utc, delivered[0].ts_mono) == original_stamp


def test_shutdown_interleaves_small_queue_drains_until_all_incidents_persist():
    class CaptureSink:
        def __init__(self):
            self.rows = []

        def emit(self, row):
            self.rows.append(row)
            return True

        def maybe_flush(self):
            return True

        def flush(self):
            return True

    queue = DiagQueue(maxsize=1)
    sink = CaptureSink()
    writer = DiagWriter(
        queue=queue, sinks=[sink], enabled=True)
    diag = LaneDiag(21, writer=writer)
    assert writer.emit(cd.make_event(
        21, "info", "service_restart", code="prefill"))
    diag.emit_event(
        "fault", "link_lost", code="shutdown-a",
        persistent=True, retain_across_blind=True)
    diag.emit_event(
        "fault", "fsm_fault", code="shutdown-b",
        persistent=True, retain_across_blind=True)
    assert diag.pending_alert_count() == 2
    board = type("Board", (), {
        "diag": diag,
        "io": type("IO", (), {"now": staticmethod(lambda: 10.0)})(),
    })()

    assert _drain_final_diagnostics(writer, [board]) == 0
    assert diag.pending_alert_count() == 0
    assert [row["event_type"] for row in sink.rows] == [
        "service_restart", "link_lost", "fsm_fault"]


def test_low_priority_pending_flood_cannot_evict_safety_fault():
    w = ToggleWriter()
    diag = LaneDiag(21, writer=w)
    diag.emit_event(
        "fault", "rail_drop", code="controller_loop_gap",
        persistent=True, retain_across_blind=True)
    for index in range(diag._pending_alerts_max + 20):
        diag.emit_event(
            "info", "unexpected_edge", code=f"edge-{index}",
            persistent=True, retain_across_blind=True)
    assert len(diag._pending_alerts) == diag._pending_alerts_max
    assert ("rail_drop", "controller_loop_gap") in diag._pending_alerts


def test_retained_info_flood_cannot_evict_active_fault_or_warning():
    for severity, event_type, code in (
            ("fault", "field_wet_lost", "aux:AUX11"),
            ("warn", "beam_blocked", "diell:DIELL_L")):
        writer = ToggleWriter()
        diag = LaneDiag(21, writer=writer)
        diag.emit_event(
            severity, event_type, code=code, persistent=True)
        for index in range(diag._pending_alerts_max + 20):
            diag.emit_event(
                "info", "unexpected_edge", code=f"edge-{index}",
                persistent=True, retain_across_blind=True)
        assert (event_type, code) in diag._pending_alerts
        assert diag._pending_alerts[(event_type, code)]["event"].severity \
            == severity


def test_gate_off_incident_is_delayed_not_discarded():
    with _EnvPatch(WSL_DIAG_DAEMON_EVENTS="0"):
        w = ToggleWriter(accept=True)
        diag = LaneDiag(21, writer=w)
        diag.emit_event(
            "fault", "rail_drop", code="controller_loop_gap",
            detail={"where": "blind"}, t=1.0,
            persistent=True, retain_across_blind=True)
        assert w.events == []
        assert ("rail_drop", "controller_loop_gap") in diag._pending_alerts

        os.environ["WSL_DIAG_DAEMON_EVENTS"] = "1"
        diag.pump_pending_delivery(2.0, force=True)
        delivered = w.of_type("rail_drop")
        assert len(delivered) == 1
        assert delivered[0].detail["where"] == "blind"


def test_same_key_incidents_coalesce_without_losing_first_or_latest_evidence():
    w = ToggleWriter()
    diag = LaneDiag(21, writer=w)
    diag.emit_event(
        "info", "unexpected_edge", code="ball:ready",
        detail={"count": 1}, persistent=True,
        retain_across_blind=True)
    first = diag._pending_alerts[
        ("unexpected_edge", "ball:ready")]["event"]
    diag.emit_event(
        "info", "unexpected_edge", code="ball:ready",
        detail={"count": 10}, persistent=True,
        retain_across_blind=True)

    w.accept = True
    diag.pump_pending_delivery(5.0, force=True)
    delivered = w.of_type("unexpected_edge")
    assert len(delivered) == 1
    assert delivered[0].detail["count"] == 10
    assert delivered[0].detail["occurrence_count"] == 2
    assert delivered[0].detail["first_occurrence_detail"] == {"count": 1}
    assert delivered[0].ts_mono == first.ts_mono


def test_ball_timeout_incident_survives_blindness_and_later_good_return():
    w = ToggleWriter()
    diag = LaneDiag(21, writer=w)
    tracker = BallReturnTracker([21], timeout_s=1.0)
    diag.set_ball_tracker(tracker)
    tracker.set_ball_source_available(21, True, -2.0)
    tracker.on_ball(21, 0.0)
    tracker.poll(1.1)
    assert ("ball_return_missing", "exit_beam") in diag._pending_alerts

    diag._suspend_all_rules(1.2)
    assert ("ball_return_missing", "exit_beam") in diag._pending_alerts
    tracker.set_enabled(True, 2.0)
    tracker.set_ball_source_available(21, True, 2.0)
    tracker.on_ball(21, 4.0)
    tracker.on_exit_pulse(4.5)
    assert ("ball_return_missing", "exit_beam") in diag._pending_alerts

    w.accept = True
    diag.pump_pending_delivery(5.0, force=True)
    assert len(w.of_type("ball_return_missing")) == 1


def test_manual_override_event_and_suppression_gating():
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    # mechanic flips a manual switch -> info event + suppression window opens
    bc.io.slow["MAN_T"] = True
    bc.tick()
    mo = w.of_type("manual_override")
    assert len(mo) == 1 and mo[0].severity == "info" and mo[0].code == "manual:MAN_T"
    assert bc.diag.suppress_until > bc.io.now()
    # a warn during the window is DOWNGRADED to info + tagged (record survives)
    bc.diag.emit_event("warn", "stuck_input", code="input:Foul",
                       detail={"held_s": 99}, t=bc.io.now())
    ev = w.of_type("stuck_input")[-1]
    assert ev.severity == "info" and ev.detail["suppressed"] is True
    assert ev.detail["orig_severity"] == "warn"
    assert bc.diag.suppressed_count == 1
    # Safety/control faults are never hidden by a mechanic nuisance window.
    bc.diag.emit_event(
        "fault", "fsm_fault", code="state:FAULT", t=bc.io.now())
    safety = w.of_type("fsm_fault")[-1]
    assert safety.severity == "fault"
    assert "suppressed" not in (safety.detail or {})
    # held switch keeps refreshing; release + expire -> warns pass again
    bc.io.slow["MAN_T"] = False
    bc.tick()
    advance(bc, 601.0)          # default window = 10 min after last activity
    bc.tick()
    bc.diag.emit_event("warn", "stuck_input", code="input:Foul", t=bc.io.now())
    ev = w.of_type("stuck_input")[-1]
    assert ev.severity == "warn" and "suppressed" not in (ev.detail or {})


def test_manual_override_no_edge_synthesized_on_first_sight():
    # input already asserted at the very first poll = BASELINE, not an edge
    w = FakeWriter()
    bc = mk_board(writer=w)
    bc.io.slow["TENTH"] = True
    to_ready(bc)
    assert w.of_type("manual_override") == [], "first sight must not synthesize an edge"
    bc.io.slow["TENTH"] = False
    bc.tick()
    bc.io.slow["TENTH"] = True
    bc.tick()
    assert len(w.of_type("manual_override")) == 1, "deassert-then-reassert acts"


def test_manual_override_chatter_is_rate_limited_and_episode_resets():
    """2026-07-19 review: a chattering MAN_* opto emitted one manual_override
    event PER RISING EDGE (up to ~25 Hz through the 50 Hz tick) — GBs of
    JSONL across the retention window. Emission is now log-scale per input
    per episode (counts 1, 10, 100, ...); a quiet gap longer than the
    suppress window starts a fresh episode with fresh counters."""
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    for _ in range(150):                     # 150 rising edges, no clock advance
        bc.io.slow["MAN_S"] = True
        bc.tick()
        bc.io.slow["MAN_S"] = False
        bc.tick()
    evs = [e for e in w.of_type("manual_override") if e.code == "manual:MAN_S"]
    assert [e.detail["count"] for e in evs] == [1, 10, 100], \
        [e.detail for e in evs]
    # quiet gap past the suppress window -> new episode -> count restarts at 1
    advance(bc, 700.0)
    bc.tick()
    bc.io.slow["MAN_S"] = True
    bc.tick()
    bc.io.slow["MAN_S"] = False
    bc.tick()
    evs = [e for e in w.of_type("manual_override") if e.code == "manual:MAN_S"]
    assert [e.detail["count"] for e in evs] == [1, 10, 100, 1], \
        [e.detail for e in evs]


def test_manual_suppression_episode_cap():
    """2026-07-19 review: a MAN_* opto failed shorted-on refreshed
    suppress_until FOREVER while held — every warn/fault on the lane was
    silently downgraded for weeks. One continuous episode now suppresses for
    at most WSL_DIAG_SUPPRESS_MAX_MIN, then a 'manual:suppress_cap' warn
    fires (the counter-alert) and alerts pass through again."""
    with _EnvPatch(WSL_DIAG_SUPPRESS_MIN="0.05",       # 3 s window
                   WSL_DIAG_SUPPRESS_MAX_MIN="0.1"):   # 6 s episode cap
        w = FakeWriter()
        bc = mk_board(writer=w)
        to_ready(bc)
        bc.io.slow["MAN_T"] = True                     # stuck ON from here
        bc.tick()
        # inside the window: warns are downgraded
        bc.diag.emit_event("warn", "stuck_input", code="input:Foul",
                           t=bc.io.now())
        ev = w.of_type("stuck_input")[-1]
        assert ev.severity == "info" and ev.detail["suppressed"] is True
        # hold the input past the cap (steps < window keep the episode alive)
        for _ in range(4):
            advance(bc, 2.0)
            bc.tick()
        caps = [e for e in w.of_type("manual_override")
                if e.code == "manual:suppress_cap"]
        assert len(caps) == 1 and caps[0].severity == "warn", \
            [(e.code, e.severity) for e in w.of_type("manual_override")]
        assert caps[0].detail["inputs"] == ["MAN_T"]
        assert "suppressed" not in (caps[0].detail or {}), \
            "the cap warn itself must not be suppressed"
        # alerts flow again while the input is STILL stuck on
        bc.diag.emit_event("warn", "stuck_input", code="input:Foul",
                           t=bc.io.now())
        ev = w.of_type("stuck_input")[-1]
        assert ev.severity == "warn" and "suppressed" not in (ev.detail or {})
        # cap warn fires once per episode, not per tick
        advance(bc, 2.0)
        bc.tick()
        assert len([e for e in w.of_type("manual_override")
                    if e.code == "manual:suppress_cap"]) == 1


# ── stuck-input rule ────────────────────────────────────────────────────────────

def test_stuck_input_fires_once_per_episode_and_bs_exempt():
    with _EnvPatch(WSL_DIAG_STUCK_INPUT_S="5"):
        w = FakeWriter()
        bc = mk_board(writer=w)
        to_ready(bc)
        bc.io.slow["Foul"] = True     # rising edge lights the lamp; lane stays READY
        bc.io.slow["BS"] = True       # BS held = NORMAL (bin full) — exempt
        bc.tick()
        advance(bc, 6.0)
        bc.tick()
        stuck = w.of_type("stuck_input")
        assert len(stuck) == 1 and stuck[0].code == "input:Foul", \
            [ (e.code, e.event_type) for e in w.events ]
        assert stuck[0].severity == "warn"
        advance(bc, 6.0)
        bc.tick()
        assert len(w.of_type("stuck_input")) == 1, "once per episode"
        # deassert clears the episode; a fresh assert re-arms
        bc.io.slow["Foul"] = False
        bc.tick()
        bc.io.slow["Foul"] = True
        bc.tick()
        advance(bc, 6.0)
        bc.tick()
        assert len(w.of_type("stuck_input")) == 2


def test_stuck_input_env_killable():
    with _EnvPatch(WSL_DIAG_STUCK_INPUT_S="5", WSL_DIAG_STUCK_INPUT="0"):
        w = FakeWriter()
        bc = mk_board(writer=w)
        to_ready(bc)
        bc.io.slow["Foul"] = True
        bc.tick()
        advance(bc, 6.0)
        bc.tick()
        assert w.of_type("stuck_input") == []


# ── DIELL beam-blocked rule ─────────────────────────────────────────────────────

def test_beam_blocked_from_hb_in_mask():
    diell_bit = 1 << HB_IN_BITS.index("DIELL_L")
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    hb(bc, extra=',"in":%d' % diell_bit)
    bc.tick()
    advance(bc, 31.0)                          # default threshold 30 s
    hb(bc, extra=',"in":%d' % diell_bit)
    bc.tick()
    beams = w.of_type("beam_blocked")
    assert len(beams) == 1 and beams[0].code == "diell:DIELL_L"
    bc.tick()
    assert len(w.of_type("beam_blocked")) == 1, "once per blocked episode"
    # beam clears -> episode ends
    hb(bc, extra=',"in":0')
    bc.tick()
    assert "DIELL_L" not in bc.diag._beam_warned


def test_beam_unknown_interval_rebaselines_held_time():
    with _EnvPatch(WSL_DIAG_BEAM_BLOCKED_S="1"):
        w = FakeWriter()
        diag = LaneDiag(21, writer=w)
        diag.poll(
            0.0, ready=True, in_motion=False,
            slow_levels={}, inb_levels={},
            diell_levels={"DIELL_L": True})
        diag.poll(
            2.0, ready=False, in_motion=False,
            slow_levels={}, inb_levels={},
            diell_levels=None)
        diag.poll(
            3.0, ready=True, in_motion=False,
            slow_levels={}, inb_levels={},
            diell_levels={"DIELL_L": True})
        assert w.of_type("beam_blocked") == []
        diag.poll(
            4.1, ready=True, in_motion=False,
            slow_levels={}, inb_levels={},
            diell_levels={"DIELL_L": True})
        assert len(w.of_type("beam_blocked")) == 1


def test_board_diag_poll_hides_cached_diell_when_link_is_unhealthy():
    bc = mk_board()
    seen = []
    bc.link.health_ok = lambda: False
    bc.link.input_levels = lambda: {"DIELL_L": True, "DIELL_R": False}
    bc.diag.poll = lambda *_args, **kwargs: seen.append(
        kwargs.get("diell_levels"))
    bc._diag_poll({})
    assert seen == [None]


# ── AUX rules ───────────────────────────────────────────────────────────────────

def test_aux_rules_fully_dormant_when_unmapped():
    w = FakeWriter()
    bc = mk_board(writer=w)          # NO aux roles (the shipped default)
    to_ready(bc)
    bc.io.slow["AUX1"] = True
    bc.io.slow["AUX3"] = True
    bc.tick()
    advance(bc, 400.0)
    bc.tick()
    for et in ("be_stuck_running", "be_no_current", "dist_index_stall",
               "ball_return_missing"):
        assert w.of_type(et) == [], et


def test_be_stuck_running_fault():
    with _EnvPatch(WSL_DIAG_BE_STUCK_MIN="0.05"):   # 3 s for the test
        w = FakeWriter()
        bc = mk_board(roles={"AUX1": "be_current"}, writer=w)
        to_ready(bc)
        bc.io.slow["AUX1"] = True                    # BE current with lane idle
        bc.tick()
        advance(bc, 4.0)
        bc.tick()
        evs = w.of_type("be_stuck_running")
        assert len(evs) == 1 and evs[0].severity == "fault"
        bc.tick()
        assert len(w.of_type("be_stuck_running")) == 1, "latched per episode"


def test_be_no_current_after_cycle_window():
    with _EnvPatch(WSL_DIAG_BE_WINDOW_S="2"):
        w = FakeWriter()
        bc = mk_board(roles={"AUX1": "be_current"}, writer=w)
        to_ready(bc)
        run_strike_cycle(bc)                         # completion opens the window
        advance(bc, 3.0)                             # window passes, BE never showed
        bc.tick()
        evs = w.of_type("be_no_current")
        assert len(evs) == 1 and evs[0].severity == "warn"
        # latched until BE current is actually seen again
        run_strike_cycle(bc)
        advance(bc, 3.0)
        bc.tick()
        assert len(w.of_type("be_no_current")) == 1
        bc.io.slow["AUX1"] = True                    # current seen -> re-arms
        bc.tick()
        bc.io.slow["AUX1"] = False
        bc.tick()
        run_strike_cycle(bc)
        advance(bc, 3.0)
        bc.tick()
        assert len(w.of_type("be_no_current")) == 2


def test_bank_read_failure_suppresses_aux_rules_not_false_faults():
    """R3-9 (Codex round-3): when the IN-B bank read raises, dependent AUX
    rules go UNKNOWN (suppressed) — the outage must NOT be read as 'all
    sensors deasserted' and manufacture a FALSE be_no_current. The real
    condition (bank_unavailable) is what surfaces."""
    with _EnvPatch(WSL_DIAG_BE_WINDOW_S="2", WSL_DIAG_BANK_FAIL_N="1"):
        w = FakeWriter()
        bc = mk_board(roles={"AUX1": "be_current"}, writer=w)
        to_ready(bc)
        run_strike_cycle(bc)                         # opens the be window
        # the bank read now FAILS every tick (I²C NAK / dead expander)
        def _boom():
            raise RuntimeError("i2c read failed")
        bc.io.read_inputs_b = _boom
        advance(bc, 3.0)                             # window would have elapsed
        for _ in range(3):
            bc.tick()
        assert w.of_type("be_no_current") == [], \
            "bank-unknown must NOT fabricate a be_no_current fault (R3-9)"
        assert len(w.of_type("bank_unavailable")) >= 1, \
            "bank_unavailable is emitted instead"


def test_dist_index_stall_during_cycle():
    w = FakeWriter()
    bc = mk_board(roles={"AUX3": "dist_index"}, writer=w)
    to_ready(bc)
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}')
    bc.tick()                                        # SWEEP_TO_GUARD (in motion)
    advance(bc, 6.0)                                 # > 5 s gap, < MAX_MOTION_S
    bc.tick()
    evs = w.of_type("dist_index_stall")
    assert len(evs) == 1 and evs[0].severity == "warn"
    bc.tick()
    assert len(w.of_type("dist_index_stall")) == 1, "once per cycle"


def test_dist_index_pulses_hold_off_the_stall():
    w = FakeWriter()
    bc = mk_board(roles={"AUX3": "dist_index"}, writer=w)
    to_ready(bc)
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}')
    bc.tick()
    for _ in range(4):                               # pulse every 1.5 s < gap
        advance(bc, 1.5)
        bc.io.slow["AUX3"] = True
        bc.tick()
        bc.io.slow["AUX3"] = False
        bc.tick()
    assert w.of_type("dist_index_stall") == []


# ── ball-return tracker ─────────────────────────────────────────────────────────

def test_ball_return_tracker_attribution():
    fired = {21: [], 22: []}
    tr = BallReturnTracker([21, 22], timeout_s=10.0)
    tr.register(21, lambda d, t: fired[21].append(d))
    tr.register(22, lambda d, t: fired[22].append(d))
    # lane 21 returns fine, lane 22's ball never comes back -> rudder side
    tr.on_ball(21, 0.0)
    tr.on_ball(22, 1.0)
    tr.on_exit_pulse(5.0)              # FIFO: matches lane 21 (oldest)
    tr.poll(12.0)
    assert fired[22] and fired[22][0]["attribution"] == "rudder_side"
    assert fired[21] == []
    assert tr.returned_total[21] == 1 and tr.missing_total[22] == 1
    # both lanes dead at once -> the later-processed lane sees shared_lift
    tr2 = BallReturnTracker([21, 22], timeout_s=10.0)
    f2 = {21: [], 22: []}
    tr2.register(21, lambda d, t: f2[21].append(d))
    tr2.register(22, lambda d, t: f2[22].append(d))
    tr2.on_ball(21, 0.0)
    tr2.on_ball(22, 0.0)
    tr2.poll(11.0)
    assert f2[21][0]["attribution"] == "unknown"       # no pair evidence yet
    assert f2[22][0]["attribution"] == "shared_lift"   # 21 just died too
    # once-per-episode: more missing balls don't re-fire until a return lands
    tr2.on_ball(22, 12.0)
    tr2.poll(30.0)
    assert len(f2[22]) == 1
    tr2.on_ball(22, 31.0)
    tr2.on_exit_pulse(33.0)            # healthy return re-arms the alert
    tr2.on_ball(22, 40.0)
    tr2.poll(60.0)
    assert len(f2[22]) == 2


def test_ball_return_dead_lane_cannot_steal_healthy_returns():
    """2026-07-19 review: pure oldest-first matching let a dead lane's stale
    pendings absorb the healthy lane's pulses — the dead lane looked healthy
    and the HEALTHY lane got flagged 'rudder_side' (mechanic sent to the
    wrong lane). Once a typical transit is learned, pulses match the lane
    whose pending age is closest to it."""
    fired = {21: [], 22: []}
    tr = BallReturnTracker([21, 22], timeout_s=30.0)
    tr.register(21, lambda d, t: fired[21].append(d))
    tr.register(22, lambda d, t: fired[22].append(d))
    # warm-up: healthy traffic teaches the ~15 s transit
    tr.on_ball(21, 0.0)
    tr.on_exit_pulse(15.0)
    tr.on_ball(22, 20.0)
    tr.on_exit_pulse(35.0)
    assert tr.returned_total == {21: 1, 22: 1}
    # lane 21's rudder jams: 21 throws (never returns), 22 throws later; 22's
    # return pulse must NOT be stolen by 21's older stale pending
    tr.on_ball(21, 100.0)
    tr.on_ball(22, 110.0)
    tr.on_exit_pulse(125.0)      # ages 21=25, 22=15; learned ~15 -> lane 22
    assert tr.returned_total[22] == 2 and tr.returned_total[21] == 1
    tr.poll(135.0)               # 21's ball (thrown 100) is now overdue
    assert fired[21] and fired[21][0]["attribution"] == "rudder_side"
    assert fired[22] == [] and tr.missing_total[22] == 0
    # subsequent healthy returns keep landing on lane 22
    tr.on_ball(22, 140.0)
    tr.on_exit_pulse(155.0)
    assert tr.returned_total[22] == 3
    tr.poll(200.0)
    assert len(fired[21]) == 1 and fired[22] == []


def test_ball_return_missing_via_daemon_integration():
    with _EnvPatch(WSL_DIAG_BALL_RETURN_S="20"):
        w = FakeWriter()
        bc = mk_board(roles={"AUX2": "exit_beam"}, writer=w)
        tracker = _wire_pair_diagnostics([bc])
        assert tracker is not None and bc.diag.ball_tracker is tracker
        to_ready(bc)
        run_strike_cycle(bc)           # ball thrown, exit pulse never arrives
        advance(bc, 21.0)
        bc.tick()
        evs = w.of_type("ball_return_missing")
        assert len(evs) == 1 and evs[0].severity == "warn"
        assert evs[0].detail["attribution"] == "unknown"   # single-lane pilot
        # exit pulses mark returns: next cycle + prompt pulse -> no new alert
        run_strike_cycle(bc)
        bc.io.slow["AUX2"] = True
        bc.tick()
        bc.io.slow["AUX2"] = False
        bc.tick()
        advance(bc, 21.0)
        bc.tick()
        assert len(w.of_type("ball_return_missing")) == 1


def test_wire_pair_diagnostics_dormant_without_roles():
    bc = mk_board()
    assert _wire_pair_diagnostics([bc]) is None
    assert bc.diag.ball_tracker is None


def test_wire_pair_diagnostics_rejects_multiple_exit_sources():
    def board(lane, roles):
        return type("Board", (), {
            "cfg": type("Cfg", (), {"lane": lane})(),
            "diag": LaneDiag(lane, aux_roles=roles),
        })()

    import pytest
    with pytest.raises(ValueError, match="ambiguous pair-shared exit_beam"):
        _wire_pair_diagnostics([
            board(21, {"AUX2": "exit_beam"}),
            board(22, {"AUX2": "exit_beam"}),
        ])


def test_only_designated_exit_source_can_consume_pair_pending_ball():
    def board(lane, roles):
        return type("Board", (), {
            "cfg": type("Cfg", (), {"lane": lane})(),
            "diag": LaneDiag(lane, aux_roles=roles),
        })()

    source = board(21, {"AUX2": "exit_beam"})
    mate = board(22, {})
    tracker = _wire_pair_diagnostics([source, mate])
    tracker.set_ball_source_available(21, True, 0.0)
    tracker.set_ball_source_available(22, True, 0.0)
    source.diag.poll(
        0.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels={"AUX2": False})
    # Initial UNKNOWN->healthy is deliberately drained for one full return
    # window; exercise attribution only after that startup quarantine.
    settled = tracker.timeout_s + 1.0
    tracker.on_ball(21, settled)
    tracker.on_ball(22, settled + 1.0)

    source.diag.poll(
        settled + 2.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels={"AUX2": True})
    assert sum(tracker.returned_total.values()) == 1
    assert sum(len(queue) for queue in tracker._pending.values()) == 1

    # The unwired mate may still see an unrelated AUX2 level in its bank map,
    # but with no role it cannot consume another shared return.
    mate.diag.poll(
        settled + 2.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels={"AUX2": True})
    assert sum(tracker.returned_total.values()) == 1
    assert sum(len(queue) for queue in tracker._pending.values()) == 1


# ── fw timestamp plumbing ───────────────────────────────────────────────────────

def test_fw_timestamps_survive_single_tick_drain():
    """Two fw-stamped edges received between ticks but DRAINED in one tick must
    still measure their true fw-clock interval (~1 ms resolution win); with
    drain-time stamping the interval would be ~0."""
    durs = {}
    bc = mk_board(cam_sink=lambda lane, idx, d: durs.update(d))
    to_ready(bc)
    hb(bc, extra=',"up":%d' % int(bc.io.now() * 1000))     # pin the FwClock offset
    bc.io.grippers = 0
    t0 = bc.io.now()
    # ball + SB arrive 0.6 s apart on the fw clock, both queued, ONE drain:
    bc.io.advance(0.1)
    bc.link.feed_line('{"ev":"ball","src":"L","t":%d}' % int((t0 + 0.1) * 1000))
    bc.io.advance(0.6)
    bc.link.feed_line('{"ev":"cam","id":"SB","e":"f","t":%d}' % int((t0 + 0.7) * 1000))
    hb(bc)
    bc.tick()                                              # drains BOTH events
    assert bc.fsm.state is State.GUARD_DELAY
    advance(bc, TIME_DELAY_S + 0.1)
    bc.tick()
    assert bc.fsm.state is State.TABLE_DETECT
    t1 = bc.io.now()
    bc.io.advance(1.0)
    bc.link.feed_line('{"ev":"cam","id":"TA2","e":"f","t":%d}' % int((t1 + 1.0) * 1000))
    bc.io.advance(0.85)
    bc.link.feed_line('{"ev":"cam","id":"SA","e":"f","t":%d}' % int((t1 + 1.85) * 1000))
    hb(bc)
    bc.tick()                                              # drains TA2 + SA together
    bc.io.slow["BS"] = True; bc.tick(); bc.io.slow["BS"] = False
    bc.link.feed_line('{"ev":"cam","id":"TA1","e":"f"}')   # no "t": Pi-time fallback
    bc.tick()
    assert bc.fsm.state is State.READY
    assert abs(durs["ss_to_guard"] - 0.6) < 0.02, durs
    assert abs(durs["ta2_to_sa"] - 0.85) < 0.02, durs


def test_fwclock_offset_ewma_and_resync():
    c = FwClock()
    assert c.est_pi_time(1000) is None, "no samples -> None"
    c.update(1000, 101.0)                       # offset = 100.0
    assert abs(c.est_pi_time(2000) - 102.0) < 1e-9
    c.update(2000, 102.010)                     # +10 ms jitter -> EWMA smooths
    assert 102.0 < c.est_pi_time(2000) < 102.005
    off = c.offset()
    c.update(500, 300.0)                        # >5 s jump -> hard resync
    assert abs(c.offset() - 299.5) < 1e-9 and c.resyncs == 1
    c.resync()
    assert c.est_pi_time(1000) is None
    assert off is not None


def test_link_resyncs_fwclock_on_reboot():
    clk = {"t": 50.0}
    link = RP2040Link(now=lambda: clk["t"], hb_timeout=1.0)
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":10000}')
    assert link.fw_clock.offset() is not None
    link.feed_line('{"ev":"boot","fw":"phase8b-rp2040 v1.1.1","wdt_reset":0,"rp_ok":0}')
    assert link.fw_clock.offset() is None, "boot must resync the FwClock"
    assert link.fw_version() == "phase8b-rp2040 v1.1.1"
    # uptime-regression reboot path resyncs too
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":500}')
    assert link.fw_clock.offset() is not None
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":100}')     # regression
    assert link.fault() == "fw_reboot"
    off = link.fw_clock.offset()
    assert off is None or abs(off - (clk["t"] - 0.1)) < 1.0    # fresh baseline only


def test_stale_fw_timestamp_clamped_after_reboot_resync():
    """2026-07-19 review: an edge queued BEFORE a firmware reboot could be
    mapped through the POST-boot FwClock offset (reader thread resyncs +
    retrains between queueing and the daemon's drain) — est_pi_time then
    returns a time wrong by the previous firmware uptime, feeding a garbage
    sample into the Welford baselines. The daemon now clamps any mapping
    that strays more than FW_EST_MAX_SKEW_S from the Pi receive time."""
    captured = []
    bc = mk_board()
    orig = bc.telemetry.on_event
    bc.telemetry.on_event = lambda ev, t: (captured.append((ev, t)),
                                           orig(ev, t))[1]
    to_ready(bc)
    hb(bc, extra=',"up":%d' % int(bc.io.now() * 1000))    # learn offset A
    bc.io.grippers = 0
    # ball edge stamped on the OLD timebase (~2 h firmware uptime), queued...
    bc.link.feed_line('{"ev":"ball","src":"L","t":7200000}')
    # ...then the reader thread processes a reboot resync + one post-boot
    # sample BEFORE the daemon drains the queue (the race window)
    bc.link.fw_clock.resync()
    bc.link.fw_clock.update(100, bc.io.now())             # new timebase B
    hb(bc)
    bc.tick()                                             # drains the stale edge
    assert bc.fsm.state is State.SWEEP_TO_GUARD
    ball_ts = [t for (ev, t) in captured if ev == "ball"]
    assert len(ball_ts) == 1
    assert abs(ball_ts[0] - bc.io.now()) < cd.FW_EST_MAX_SKEW_S, \
        f"stale fw timestamp must clamp to Pi receive time, got {ball_ts[0]} " \
        f"vs now {bc.io.now()}"


def test_queue_entries_carry_fw_and_pi_timestamps():
    clk = {"t": 7.0}
    link = RP2040Link(now=lambda: clk["t"])
    link.feed_line('{"ev":"cam","id":"SB","e":"f","t":1234}')
    link.feed_line('{"ev":"ball","src":"L"}')                  # v0.1.0: no "t"
    with link._evlock:
        entries = list(link._events)
    assert entries[0] == ("cam", "SB", 1234, 7.0)
    assert entries[1] == ("ball", "L", None, 7.0)
    seen = []
    class _FSM:
        def cam_SB_guard(self): pass
        def on_ball(self): pass
    link.apply_events(_FSM(), observer=lambda *a: seen.append(a))
    assert seen == [("cam", "SB", 1234, 7.0), ("ball", "L", None, 7.0)]
    # a raising observer is swallowed (tick safety)
    link.feed_line('{"ev":"ball","src":"L"}')
    def boom(*a):
        raise RuntimeError("observer bug")
    assert link.apply_events(_FSM(), observer=boom) == 1


# ── safety-trip events + cycle rows ────────────────────────────────────────────

def test_fsm_fault_event_and_aborted_cycle_row():
    w = FakeWriter()
    sh = FakeShipper()
    bc = mk_board(writer=w, shipper=sh)
    to_ready(bc)
    run_strike_cycle(bc)
    assert len(sh.rows) == 1
    row = sh.rows[0]
    assert row["lane_id"] == 21 and row["final_state"] == "READY"
    assert row["aborted"] is False and row["cycle_type"] == "ball"
    assert row["gs_mask"] == 0 and row["shadow"] is False
    assert isinstance(row["ss_to_guard_ms"], int) and row["ss_to_guard_ms"] > 0
    assert row["started_at"] and row["ended_at"]
    # stuck motion -> FAULT: fsm_fault event with the structured wave-1 code
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}')
    bc.tick()
    advance(bc, MAX_MOTION_S + 1.0)
    bc.tick()
    assert bc.fsm.state is State.FAULT
    faults = w.of_type("fsm_fault")
    assert len(faults) == 1 and faults[0].severity == "fault"
    assert faults[0].code == "motion_timeout:SWEEP_TO_GUARD"
    assert len(sh.rows) == 2
    assert sh.rows[1]["final_state"] == "FAULT" and sh.rows[1]["aborted"] is True
    assert "ss_to_guard_ms" not in sh.rows[1], "aborted cycle folds no intervals"


def test_link_lost_and_fw_reboot_events():
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    assert bc.io.armed is True
    # uptime regression = fw reboot -> link_lost + fw_reboot + rail_drop
    bc.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":10000}')
    bc.tick()
    bc.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":50}')
    bc.tick()
    assert bc.fsm.state is State.MANUAL_INTERVENTION
    assert len(w.of_type("link_lost")) == 1
    fr = w.of_type("fw_reboot")
    assert len(fr) == 1 and fr[0].code == "fw_reboot" and fr[0].severity == "fault"
    drops = w.of_type("rail_drop")
    assert drops and drops[0].detail["reason"] == "rp2040_link_unhealthy"


def test_wdt_reset_distinct_code():
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    # mid-session boot event carrying wdt_reset -> 'rp2040_wdt_reset', not fw_reboot
    bc.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":10000}')
    bc.tick()
    bc.link.feed_line('{"ev":"boot","fw":"x","wdt_reset":1,"rp_ok":0}')
    bc.tick()
    assert len(w.of_type("rp2040_wdt_reset")) == 1
    assert w.of_type("fw_reboot") == []


def test_unexpected_edge_events_log_scale():
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    # a cam edge in READY = the dangerous uncommanded-motion class
    for _ in range(12):
        bc.link.feed_line('{"ev":"cam","id":"TA2","e":"f"}')
        bc.tick()
    evs = [e for e in w.of_type("unexpected_edge")
           if e.code == "cam_TA2_runthrough:ready"]
    assert [e.detail["count"] for e in evs] == [1, 10], \
        "log-scale emission (1, 10, ...) keeps routine artifacts from flooding"


# ── CamTelemetry persistence ────────────────────────────────────────────────────

def _feed_cycles(tel, n, base=0.0, guard=0.6):
    t = base
    for _ in range(n):
        tel.on_event("ball", t)
        tel.on_event("cam:SB", t + guard)
        tel.end_cycle()
        t += 20.0
    return t


def test_cycle_started_with_master_off_never_folds_after_reenable():
    with _EnvPatch(WSL_DIAG_DAEMON_EVENTS="0"):
        bc = mk_board()
        bc._handle_transition(State.READY, State.SWEEP_TO_GUARD, 0.0)
        bc._handle_transition(
            State.SWEEP_TO_GUARD, State.GUARD_DELAY, 1.0)
        os.environ["WSL_DIAG_DAEMON_EVENTS"] = "1"
        bc._handle_transition(State.GUARD_DELAY, State.READY, 2.0)
        assert bc.telemetry.baselines()["ss_to_guard"]["n"] == 0

        # A wholly enabled cycle still folds normally.
        bc._handle_transition(State.READY, State.SWEEP_TO_GUARD, 3.0)
        bc._handle_transition(
            State.SWEEP_TO_GUARD, State.GUARD_DELAY, 4.0)
        bc._handle_transition(State.GUARD_DELAY, State.READY, 5.0)
        assert bc.telemetry.baselines()["ss_to_guard"]["n"] == 1


def test_any_master_transition_midcycle_invalidates_baseline_sample():
    with _EnvPatch(WSL_DIAG_DAEMON_EVENTS="1"):
        bc = mk_board()
        bc._handle_transition(State.READY, State.SWEEP_TO_GUARD, 0.0)
        os.environ["WSL_DIAG_DAEMON_EVENTS"] = "0"
        bc._sync_diag_gate_generation(0.5)
        os.environ["WSL_DIAG_DAEMON_EVENTS"] = "1"
        bc._sync_diag_gate_generation(0.75)
        bc._handle_transition(
            State.SWEEP_TO_GUARD, State.GUARD_DELAY, 1.0)
        bc._handle_transition(State.GUARD_DELAY, State.READY, 2.0)
        assert bc.telemetry.baselines()["ss_to_guard"]["n"] == 0


def test_baseline_persistence_roundtrip():
    d = tempfile.mkdtemp(prefix="cam_persist_")
    tel = CamTelemetry(21, enabled=True, persist=True, persist_dir=d,
                       persist_every=5)
    _feed_cycles(tel, 6)
    assert tel.maybe_persist() is True
    path = os.path.join(d, "cam_baselines_21.json")
    assert os.path.exists(path)
    assert not os.path.exists(path + ".tmp"), "atomic write leaves no tmp file"
    tel2 = CamTelemetry(21, enabled=True, persist=True, persist_dir=d)
    bl = tel2.baselines()["ss_to_guard"]
    assert bl["n"] == 6 and abs(bl["mean"] - 0.6) < 1e-6, bl
    # restored baselines keep accumulating
    _feed_cycles(tel2, 2, base=1000.0)
    assert tel2.baselines()["ss_to_guard"]["n"] == 8


def test_persistence_stale_file_tolerant():
    d = tempfile.mkdtemp(prefix="cam_persist_bad_")
    path = os.path.join(d, "cam_baselines_21.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not json !!!")
    tel = CamTelemetry(21, enabled=True, persist=True, persist_dir=d)
    assert tel.baselines()["ss_to_guard"]["n"] == 0, "corrupt file -> fresh start"
    # per-interval garbage skipped without poisoning the rest
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"baselines": {
            "ss_to_guard": {"n": "junk"},
            "ta2_to_sa": {"n": 4, "mean": 0.9, "m2": 0.0, "min": 0.9, "max": 0.9},
        }}, f)
    tel2 = CamTelemetry(21, enabled=True, persist=True, persist_dir=d)
    bl = tel2.baselines()
    assert bl["ss_to_guard"]["n"] == 0 and bl["ta2_to_sa"]["n"] == 4, bl


def test_persistence_save_cadence_and_stop():
    d = tempfile.mkdtemp(prefix="cam_persist_cad_")
    tel = CamTelemetry(21, enabled=True, persist=True, persist_dir=d,
                       persist_every=10)
    _feed_cycles(tel, 3)
    assert tel.maybe_persist() is False, "below the N-updates cadence"
    assert not os.path.exists(os.path.join(d, "cam_baselines_21.json"))
    assert tel.stop() is True, "stop() flushes anything dirty"
    assert os.path.exists(os.path.join(d, "cam_baselines_21.json"))
    assert tel.stop() is False, "nothing dirty -> no rewrite"


def test_persistence_concurrent_savers_and_adds_are_safe():
    """2026-07-19 review: run()'s finally and the PlatformHealth thread can
    both call save_baselines() concurrently (shared .tmp path — on Windows
    os.replace of an open file fails, losing the session's final save), and
    a save could snapshot a half-updated Welford triple mid-add. Both are
    now lock-guarded: zero persist_errors and a consistent restorable file
    under deliberate contention."""
    import threading as th
    d = tempfile.mkdtemp(prefix="cam_persist_race_")
    tel = CamTelemetry(21, enabled=True, persist=True, persist_dir=d,
                       persist_every=1)
    stop = {"f": False}

    def adder():
        t = 0.0
        while not stop["f"]:
            tel.on_event("ball", t)
            tel.on_event("cam:SB", t + 0.6)
            tel.end_cycle()
            t += 20.0

    a = th.Thread(target=adder)
    a.start()
    savers = [th.Thread(target=lambda: [tel.save_baselines()
                                        for _ in range(60)])
              for _ in range(2)]
    for s in savers:
        s.start()
    for s in savers:
        s.join()
    stop["f"] = True
    a.join()
    assert tel.persist_errors == 0, f"persist_errors={tel.persist_errors}"
    assert tel.persist_saves >= 120
    # the persisted file restores cleanly and is internally consistent
    tel2 = CamTelemetry(21, enabled=True, persist=True, persist_dir=d)
    bl = tel2.baselines()["ss_to_guard"]
    assert bl["n"] > 0 and abs(bl["mean"] - 0.6) < 1e-6, bl


def test_persistence_env_killswitch():
    d = tempfile.mkdtemp(prefix="cam_persist_off_")
    with _EnvPatch(WSL_CAM_TELEMETRY_PERSIST="0"):
        tel = CamTelemetry(21, enabled=True, persist=True, persist_dir=d)
        assert tel.persist is False
        _feed_cycles(tel, 30)
        assert tel.maybe_persist() is False and not os.listdir(d)


def test_drift_alarm_routes_into_diag_emit():
    calls = []
    tel = CamTelemetry(21, enabled=True, drift_sigma=4.0,
                       diag_emit=lambda *a: calls.append(a))
    for i in range(40):
        tel.on_event("ball", 0.0)
        tel.on_event("cam:SB", 0.60 + (0.001 if i % 2 else -0.001))
        tel.end_cycle()
    tel.on_event("ball", 0.0)
    tel.on_event("cam:SB", 1.5)          # gross drift
    tel.end_cycle()
    assert len(calls) == 1
    sev, et, code, detail = calls[0]
    assert (sev, et, code) == ("warn", "drift_alarm", "drift:ss_to_guard")
    assert detail["n"] >= 30 and detail["dt_s"] == 1.5
    # a raising emitter is swallowed (tick safety)
    tel2 = CamTelemetry(21, enabled=True, drift_sigma=4.0,
                        diag_emit=lambda *a: 1 / 0)
    for i in range(40):
        tel2.on_event("ball", 0.0)
        tel2.on_event("cam:SB", 0.60 + (0.001 if i % 2 else -0.001))
        tel2.end_cycle()
    tel2.on_event("ball", 0.0)
    tel2.on_event("cam:SB", 1.5)
    tel2.end_cycle()                     # must not raise


# ── CycleShipper + PlatformHealth ──────────────────────────────────────────────

def test_cycle_shipper_bounded_and_ships_on_thread():
    posted = []
    sh = CycleShipper(lambda row: (posted.append(row), True)[1], maxsize=2)
    assert sh.offer({"a": 1}) and sh.offer({"a": 2})
    assert sh.offer({"a": 3}) is False and sh.drops == 1, "bounded, never blocks"
    sh.start()
    sh.stop()
    assert len(posted) == 2 and sh.shipped == 2
    # a raising post_cycle is swallowed + counted
    sh2 = CycleShipper(lambda row: 1 / 0)
    sh2.offer({"x": 1})
    sh2.start()
    sh2.stop()
    assert sh2.errors == 1


def test_platform_current_health_is_truthful_when_event_queue_rejects(
        monkeypatch):
    import builtins
    import io

    monkeypatch.setenv("WSL_DIAG_TEMP_MAX_C", "75")
    monkeypatch.setenv("WSL_DIAG_DAEMON_EVENTS", "1")
    writer = ToggleWriter()
    ph = PlatformHealth(
        [], writer, dir_path=tempfile.mkdtemp(prefix="ph_truth_"))
    ph._common_platform = {"ok": True, "reasons": []}
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/sys/class/thermal/thermal_zone0/temp":
            return io.StringIO("77000")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    ph._poll_thermal()
    assert ph._thermal_active is True
    assert ph._thermal_warned is False, "delivery latch follows acceptance"

    captured = {}

    def capture(_path, _service, payload):
        captured["payload"] = payload
        return True

    monkeypatch.setattr(cd.health_drop, "write_drop", capture)
    ph._write_health_drop()
    payload = captured["payload"]
    assert payload["ok"] is False
    assert payload["thermal_warned"] is True
    assert "thermal" in payload["platform"]["reasons"]


def test_platform_probe_samples_gate_off_and_emits_active_fault_on_enable(
        monkeypatch):
    import builtins
    import io

    monkeypatch.setenv("WSL_DIAG_TEMP_MAX_C", "75")
    monkeypatch.setenv("WSL_DIAG_DAEMON_EVENTS", "0")
    writer = ToggleWriter(accept=True)
    ph = PlatformHealth(
        [], writer, dir_path=tempfile.mkdtemp(prefix="ph_gate_truth_"))
    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/sys/class/thermal/thermal_zone0/temp":
            return io.StringIO("77000")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    ph._poll_thermal()
    assert ph._thermal_active is True
    assert writer.events == []

    monkeypatch.setenv("WSL_DIAG_DAEMON_EVENTS", "1")
    ph._poll_thermal()
    assert len(writer.of_type("pi_thermal")) == 1


def test_platform_health_service_start_counter():
    d = tempfile.mkdtemp(prefix="plat_")
    w = FakeWriter()
    bc = mk_board()
    ph = PlatformHealth([bc], w, poll_s=0.05, dir_path=d)
    ph.start()
    time.sleep(0.2)
    ph.stop()
    evs = w.of_type("service_restart")
    assert len(evs) == 1 and evs[0].detail["count"] == 1
    with open(os.path.join(d, "service_starts.json"), encoding="utf-8") as f:
        assert json.load(f)["count"] == 1
    # second start increments (vcgencmd absent on this host must be tolerated)
    w2 = FakeWriter()
    ph2 = PlatformHealth([bc], w2, poll_s=0.05, dir_path=d)
    ph2.start()
    time.sleep(0.2)
    ph2.stop()
    assert w2.of_type("service_restart")[0].detail["count"] == 2


# ── config plumbing ────────────────────────────────────────────────────────────

def test_parse_aux_roles():
    assert _parse_aux_roles(None) == {}
    assert _parse_aux_roles("") == {}
    assert _parse_aux_roles("aux1=be_current,aux2=exit_beam,aux3=dist_index") == {
        "AUX1": "be_current", "AUX2": "exit_beam", "AUX3": "dist_index"}
    # H3 (2026-07-21): aux4-aux11 (rev-D GPB bank) are valid role keys
    assert _parse_aux_roles("aux4=exit_beam,aux11=dist_index") == {
        "AUX4": "exit_beam", "AUX11": "dist_index"}
    assert _parse_aux_roles("aux10=sensor_24v_ok") == {
        "AUX10": "sensor_24v_ok"}
    # R3-9 (Codex round-3, 2026-07-23): an unrecognized role string, unknown
    # AUX key, or malformed token now REFUSES startup loudly — it is NEVER
    # silently skipped (the seed-flag-matched-by-name time bomb). Each raises
    # ValueError with the valid list.
    import pytest
    with pytest.raises(ValueError):
        _parse_aux_roles("aux1=warp_drive")          # typo'd role
    with pytest.raises(ValueError):
        _parse_aux_roles("aux9=be_current,garbage")  # token with no '='
    with pytest.raises(ValueError):
        _parse_aux_roles("aux12=be_current")         # AUX key out of range
    with pytest.raises(ValueError):
        _parse_aux_roles("aux0=exit_beam")           # zero-indexed key
    # the valid part of a mixed spec is irrelevant — one bad entry refuses all
    with pytest.raises(ValueError):
        _parse_aux_roles("aux9=be_current,aux1=warp_drive")
    with pytest.raises(ValueError, match="configured more than once"):
        _parse_aux_roles("aux1=be_current,aux1=dist_index")
    with pytest.raises(ValueError, match="singleton"):
        _parse_aux_roles("aux1=be_current,aux2=be_current")


def test_per_lane_aux_provisioning_is_explicit_for_a_pair():
    configs = [
        BoardConfig(21, 1, "sim21", 0, 0),
        BoardConfig(22, 3, "sim22", 0, 0),
    ]
    env = {
        "WSL_DIAG_AUX_ROLES_L21":
            "aux2=exit_beam,aux3=dist_index,aux10=sensor_24v_ok",
        "WSL_DIAG_AUX_ROLES_L22":
            "aux3=dist_index,aux10=sensor_24v_ok",
    }
    provisioned = _provision_aux_roles(configs, env)
    assert provisioned[0].aux_roles == {
        "AUX2": "exit_beam",
        "AUX3": "dist_index",
        "AUX10": "sensor_24v_ok",
    }
    assert provisioned[1].aux_roles == {
        "AUX3": "dist_index",
        "AUX10": "sensor_24v_ok",
    }
    assert configs[0].aux_roles is None and configs[1].aux_roles is None


def test_partial_pair_map_is_refused_but_explicit_blank_is_unmapped():
    configs = [
        BoardConfig(21, 1, "sim21", 0, 0),
        BoardConfig(22, 3, "sim22", 0, 0),
    ]
    import pytest
    with pytest.raises(ValueError, match="partial per-board"):
        _provision_aux_roles(
            configs, {"WSL_DIAG_AUX_ROLES_L21": "aux2=exit_beam"})
    provisioned = _provision_aux_roles(
        configs, {
            "WSL_DIAG_AUX_ROLES_L21": "aux2=exit_beam",
            "WSL_DIAG_AUX_ROLES_L22": "",
        })
    assert provisioned[0].aux_roles == {"AUX2": "exit_beam"}
    assert provisioned[1].aux_roles == {}
    with pytest.raises(ValueError, match="partial per-board"):
        _provision_aux_roles([
            BoardConfig(
                21, 1, "sim21", 0, 0,
                aux_roles={"AUX2": "exit_beam"}),
            BoardConfig(22, 3, "sim22", 0, 0),
        ], {})


def test_unscoped_aux_roles_refused_for_multi_board_service():
    configs = [
        BoardConfig(21, 1, "sim21", 0, 0),
        BoardConfig(22, 3, "sim22", 0, 0),
    ]
    import pytest
    with pytest.raises(ValueError, match="one-board compatibility"):
        _provision_aux_roles(
            configs, {"WSL_DIAG_AUX_ROLES": "aux3=dist_index"})
    # The backward-compatible one-board bench surface remains deterministic.
    one = _provision_aux_roles(
        configs[:1], {"WSL_DIAG_AUX_ROLES": "aux3=dist_index"})
    assert one[0].aux_roles == {"AUX3": "dist_index"}


def test_pair_provisioning_rejects_two_exit_beam_mappings():
    configs = [
        BoardConfig(21, 1, "sim21", 0, 0),
        BoardConfig(22, 3, "sim22", 0, 0),
    ]
    import pytest
    with pytest.raises(ValueError, match="one physical source"):
        _provision_aux_roles(configs, {
            "WSL_DIAG_AUX_ROLES_L21": "aux2=exit_beam",
            "WSL_DIAG_AUX_ROLES_L22": "aux7=exit_beam",
        })


def test_programmatic_aux_map_rejects_duplicate_singleton_role():
    import pytest
    cfg = BoardConfig(
        21, 1, "sim21", 0, 0,
        aux_roles={"AUX1": "dist_index", "AUX2": "dist_index"})
    with pytest.raises(ValueError, match="singleton role"):
        _provision_aux_roles([cfg], {})


def test_aux_provisioning_rejects_unknown_or_noncanonical_lane_variable():
    import pytest
    cfg = BoardConfig(21, 1, "sim21", 0, 0)
    with pytest.raises(ValueError, match="unknown/noncanonical"):
        _provision_aux_roles(
            [cfg], {"WSL_DIAG_AUX_ROLES_L021": "aux2=exit_beam"})
    with pytest.raises(ValueError, match="unknown/noncanonical"):
        _provision_aux_roles(
            [cfg], {"WSL_DIAG_AUX_ROLES_L23": "aux2=exit_beam"})


def test_direct_lane_aux_resolver_prefers_present_blank_override():
    assert _aux_roles_for_lane(21, {
        "WSL_DIAG_AUX_ROLES": "aux3=dist_index",
        "WSL_DIAG_AUX_ROLES_L21": "",
    }) == {}
    assert _aux_roles_for_lane(
        22, {"WSL_DIAG_AUX_ROLES": "aux3=dist_index"}
    ) == {"AUX3": "dist_index"}


def test_gate_reconcile_dedupes_same_tick_schema_fault_transition():
    w = FakeWriter()
    bc = mk_board(writer=w)
    schema = cd.HEARTBEAT_SCHEMA_FAULT
    bc.link.fault = lambda: schema
    bc.link.is_alive = lambda: False
    bc.link.rp_ok = lambda: False
    bc.link.maxrun_ok = lambda: True
    bc.link.fw_identity = lambda: None
    bc.link.identity_missing = lambda: False
    bc.diag.start_event_generation()
    bc._diag_master_reconcile_pending = True
    bc._diag_identity_reconcile_pending = True

    # Model the normal discontinuity producer that ran earlier in this same
    # first enabled tick.
    bc.diag.emit_event(
        "fault", "link_lost", code=schema, persistent=True,
        retain_across_blind=True)
    bc.diag.emit_event(
        "fault", "fw_fault", code=schema, persistent=True,
        retain_across_blind=True)
    bc._reconcile_current_diagnostic_faults(1.0, False)
    assert len(w.of_type("link_lost")) == 1
    assert len(w.of_type("fw_fault")) == 1


def test_identity_reconcile_waits_for_conclusive_healthy_link():
    w = FakeWriter()
    bc = mk_board(writer=w, board_rev="revD")
    identity = {
        "fw": "test", "bn": 123, "pcb": "unknown", "rid": 255,
        "uid": "TEST", "build": "test-build", "cfg": "test-cfg",
        "fi1": False,
    }
    bc.link.fault = lambda: cd.HEARTBEAT_SCHEMA_FAULT
    bc.link.is_alive = lambda: False
    bc.link.rp_ok = lambda: False
    bc.link.maxrun_ok = lambda: True
    bc.link.fw_identity = lambda: identity
    bc.link.identity_missing = lambda: False
    bc._identity_arm_ok = lambda **_kwargs: (False, "pcb_rev_mismatch")
    bc._diag_master_reconcile_pending = True
    bc._diag_identity_reconcile_pending = True
    bc.diag.start_event_generation()

    bc._reconcile_current_diagnostic_faults(1.0, False)
    assert w.of_type("fw_identity") == []
    assert bc._diag_identity_reconcile_pending is True
    bc._reconcile_current_diagnostic_faults(2.0, True)
    identity_events = w.of_type("fw_identity")
    assert len(identity_events) == 1
    assert identity_events[0].code == "pcb_rev_mismatch"
    assert bc._diag_identity_reconcile_pending is False


def test_identity_reconcile_ignores_unrelated_provenance_attempt():
    writer = FakeWriter()
    bc = mk_board(writer=writer, board_rev="revD")
    identity = {
        "fw": "test", "bn": 123, "pcb": "revD", "rid": 1,
        "uid": "TEST", "build": "test-build", "cfg": "test-cfg",
        "fi1": False,
    }
    bc.link.fw_identity = lambda: identity
    bc.link.identity_missing = lambda: False
    bc.link.maxrun_ok = lambda: True
    bc.link.fault = lambda: cd.HEARTBEAT_SCHEMA_FAULT
    bc._identity_arm_ok = lambda **_kwargs: (
        False, "rid_heartbeat_mismatch")
    bc._diag_identity_reconcile_pending = True
    bc.diag.start_event_generation()
    bc.diag.emit_event(
        "info", "fw_identity", code=None, detail={"pcb": "revD"},
        persistent=True, retain_across_blind=True)

    bc._reconcile_current_diagnostic_faults(1.0, False)
    assert bc._diag_identity_reconcile_pending is True
    bc.diag.start_event_generation()
    bc._reconcile_current_diagnostic_faults(2.0, True)
    faults = [
        event for event in writer.of_type("fw_identity")
        if event.severity == "fault"]
    assert len(faults) == 1
    assert faults[0].code == "rid_heartbeat_mismatch"
    assert bc._diag_identity_reconcile_pending is False


def test_healthy_identity_provenance_retry_is_not_canceled_as_stale_fault():
    w = ToggleWriter()
    bc = mk_board(writer=w, board_rev="revD")
    bc.link.maxrun_ok = lambda: True
    bc._identity_arm_ok = lambda **_kwargs: (True, None)
    bc.diag.emit_event(
        "info", "fw_identity", code=None,
        detail={"pcb": "revD"}, persistent=True,
        retain_across_blind=True)
    assert ("fw_identity", "") in bc.diag._pending_alerts
    bc._evaluate_arm_preconditions()
    assert ("fw_identity", "") in bc.diag._pending_alerts
    w.accept = True
    bc.diag.pump_pending_delivery(1.0, force=True)
    assert len(w.of_type("fw_identity")) == 1


def test_master_killswitch_silences_everything():
    with _EnvPatch(WSL_DIAG_DAEMON_EVENTS="0", WSL_DIAG_STUCK_INPUT_S="5"):
        w = FakeWriter()
        bc = mk_board(writer=w)
        to_ready(bc)
        bc.io.slow["Foul"] = True
        bc.io.slow["MAN_T"] = True
        bc.tick()
        advance(bc, 700.0)
        bc.tick()
        bc.io.grippers = 0
        bc.link.feed_line('{"ev":"ball","src":"L"}')
        bc.tick()
        advance(bc, MAX_MOTION_S + 1.0)
        bc.tick()
        assert bc.fsm.state is State.FAULT, "control behavior unchanged"
        assert w.events == [], "master kill-switch: zero events emitted"


# ── H3 (Codex audit 2026-07-21): IN-B GPB bank + stable-time debounce ──────────

def test_slow_debounce_semantics():
    """SlowDebounce: n=1 passthrough; n=3 needs 3 consecutive identical
    samples; alternating chatter is never accepted; the initial level is a
    baseline, never an edge."""
    d1 = cd.SlowDebounce(1, initial=False)
    assert d1.update(True) is True and d1.update(False) is False, "n=1 = raw"
    d3 = cd.SlowDebounce(3, initial=False)
    assert d3.update(True) is False          # 1st sample of new level
    assert d3.update(True) is False          # 2nd
    assert d3.update(True) is True           # 3rd consecutive -> accepted
    assert d3.update(False) is True          # release needs its own 3 samples
    assert d3.update(False) is True
    assert d3.update(False) is False
    dchat = cd.SlowDebounce(3, initial=False)
    for _ in range(50):                      # 50 Hz contact chatter
        assert dchat.update(True) is False
        assert dchat.update(False) is False
    dinit = cd.SlowDebounce(3, initial=True)
    assert dinit.stable is True, "already-asserted at start = baseline"


def test_diag_debounce_filters_single_tick_glitch():
    """A 1-tick MAN_T glitch never reaches the diagnostics rules at n=3; a
    held level does (after 3 consecutive samples). The FSM path (PBZ) stays
    raw by default in the SAME board."""
    w = FakeWriter()
    bc = mk_board(writer=w, slow_debounce_n=3)
    to_ready(bc)                                     # raw PBZ pulse still works
    bc.io.slow["MAN_T"] = True                       # 1-tick glitch
    bc.tick()
    bc.io.slow["MAN_T"] = False
    for _ in range(5):
        bc.tick()
    assert w.of_type("manual_override") == [], "glitch must not fake an edge"
    bc.io.slow["MAN_T"] = True                       # genuine held input
    for _ in range(4):
        bc.tick()
    evs = w.of_type("manual_override")
    assert len(evs) == 1 and evs[0].detail["input"] == "MAN_T", evs
    bc.io.slow["MAN_T"] = False


def test_inb_debounce_rebaselines_after_bank_or_channel_unknown():
    w = FakeWriter()
    bc = mk_board(
        roles={"AUX3": "dist_index"}, writer=w, slow_debounce_n=3)

    baseline = bc._debounce_for_diag(
        {"AUX3": False}, source="inb")
    bc.diag.poll(
        0.0, ready=False, in_motion=False,
        slow_levels={}, inb_levels=baseline)

    assert bc._debounce_for_diag(None, source="inb") is None
    bc.diag.poll(
        1.0, ready=False, in_motion=True,
        slow_levels={}, inb_levels=None)

    # The physical assertion happened while blind. First recovery raw=True is
    # the new baseline; retained debounce state must not release it as an edge
    # three samples later.
    for t in (2.0, 2.1, 2.2, 2.3):
        recovered = bc._debounce_for_diag(
            {"AUX3": True}, source="inb")
        bc.diag.poll(
            t, ready=False, in_motion=True,
            slow_levels={}, inb_levels=recovered)
    assert bc.diag._dist_last_pulse is None

    # Per-channel omission has the same semantics as a whole-bank failure.
    bc._debounce_for_diag({}, source="inb")
    assert "AUX3" not in bc._diag_inb_deb

    # Fixed IN-B inputs need the same LaneDiag baseline reset, not only AUX.
    manual = mk_board(writer=w, slow_debounce_n=3)
    first = manual._debounce_for_diag(
        {"MAN_T": False, "TENTH": True}, source="inb")
    manual.diag.poll(
        0.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels=first)
    missing = manual._debounce_for_diag(None, source="inb")
    manual.diag.poll(
        1.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels=missing)
    recovered = manual._debounce_for_diag(
        {"MAN_T": True, "TENTH": True}, source="inb")
    manual.diag.poll(
        100.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels=recovered)
    assert w.of_type("manual_override") == []
    assert manual.diag._assert_since["TENTH"] == 100.0


def test_missing_supply_health_rebaselines_dependent_and_field_debounce():
    w = FakeWriter()
    bc = mk_board(
        roles={"AUX3": "dist_index", "AUX10": "sensor_24v_ok",
               "AUX11": "field_wet_ok"},
        writer=w, board_rev="revD", slow_debounce_n=3)
    healthy = {"AUX3": False, "AUX10": True, "AUX11": True}

    deb_inb = bc._debounce_for_diag(healthy, source="inb")
    deb_slow = bc._debounce_for_diag({"TA2": False})
    bc.diag.poll(
        0.0, ready=False, in_motion=False,
        slow_levels=deb_slow, inb_levels=deb_inb)

    # Sensor-health omission: the dependent index changed while UNKNOWN.
    missing_sensor = {"AUX3": True, "AUX11": True}
    deb_inb = bc._debounce_for_diag(missing_sensor, source="inb")
    deb_slow = bc._debounce_for_diag({"TA2": False})
    bc.diag.poll(
        1.0, ready=False, in_motion=True,
        slow_levels=deb_slow, inb_levels=deb_inb)
    for t in (2.0, 2.1, 2.2):
        recovered = {"AUX3": True, "AUX10": True, "AUX11": True}
        deb_inb = bc._debounce_for_diag(recovered, source="inb")
        deb_slow = bc._debounce_for_diag({"TA2": False})
        bc.diag.poll(
            t, ready=False, in_motion=True,
            slow_levels=deb_slow, inb_levels=deb_inb)
    assert bc.diag._dist_last_pulse is None

    # FIELD_WET-health omission also resets the separately-read slow bank.
    missing_wet = {"AUX3": True, "AUX10": True}
    deb_inb = bc._debounce_for_diag(missing_wet, source="inb")
    deb_slow = bc._debounce_for_diag({"TA2": True})
    bc.diag.poll(
        3.0, ready=True, in_motion=False,
        slow_levels=deb_slow, inb_levels=deb_inb)
    recovered = {"AUX3": True, "AUX10": True, "AUX11": True}
    deb_inb = bc._debounce_for_diag(recovered, source="inb")
    deb_slow = bc._debounce_for_diag({"TA2": True})
    bc.diag.poll(
        4.0, ready=True, in_motion=False,
        slow_levels=deb_slow, inb_levels=deb_inb)
    assert bc.diag._assert_since["TA2"] == 4.0


def test_debounce_defaults_and_env_knobs():
    with _EnvPatch(WSL_SLOW_DEBOUNCE_N="5", WSL_SLOW_DEBOUNCE_FSM_N="2"):
        bc = mk_board(slow_debounce_n=None, fsm_debounce_n=None)
        assert bc._diag_deb_n == 5 and bc._fsm_deb_n == 2
    # constructor args beat env; garbage env falls back to defaults
    with _EnvPatch(WSL_SLOW_DEBOUNCE_N="garbage", WSL_SLOW_DEBOUNCE_FSM_N="-3"):
        bc = mk_board(slow_debounce_n=None, fsm_debounce_n=None)
        assert bc._diag_deb_n == cd.DEFAULT_SLOW_DEBOUNCE_N == 3
        assert bc._fsm_deb_n == cd.DEFAULT_SLOW_DEBOUNCE_FSM_N == 1, \
            "FSM path must default RAW (safety-path semantics unchanged)"


def test_fsm_debounce_optin_delays_pbz():
    """With the FLAGGED knob raised, a 1-tick PBZ pulse is rejected and a held
    PBZ acts after n samples — proving the knob works without being default."""
    bc = mk_board(fsm_debounce_n=3)
    hb(bc); bc.tick()
    bc.io.slow["PBZ"] = True                          # 1-tick pulse: too short
    bc.tick()
    bc.io.slow["PBZ"] = False
    hb(bc); bc.tick()
    assert bc.fsm.state is State.MANUAL_INTERVENTION, "glitch PBZ ignored"
    bc.io.slow["PBZ"] = True                          # held: accepted on 3rd tick
    bc.tick(); bc.tick()
    hb(bc); bc.tick()
    assert bc.fsm.state is State.READY, "held PBZ accepted after n samples"
    bc.io.slow["PBZ"] = False


def test_revd_board_reads_gpb_aux_bank():
    """board_rev='revD' selects the 16-channel IN-B map (AUX4-11 on GPB) and
    the aux-role surface drives rules off the new channels; a rev-C board
    keeps the 8-channel map."""
    from controller_io import IN_B_MAP, IN_B_MAP_REVD
    bc_c = mk_board()
    assert set(bc_c.io.read_inputs_b()) == set(IN_B_MAP) and len(IN_B_MAP) == 8
    with _EnvPatch(WSL_DIAG_BE_STUCK_MIN="0.05"):
        w = FakeWriter()
        bc = mk_board(roles={"AUX9": "be_current"}, writer=w, board_rev="revD")
        assert set(bc.io.read_inputs_b()) == set(IN_B_MAP_REVD) \
            and len(IN_B_MAP_REVD) == 16
        to_ready(bc)
        bc.io.slow["AUX9"] = True                    # BE current, lane idle
        bc.tick()
        advance(bc, 4.0)
        bc.tick()
        evs = w.of_type("be_stuck_running")
        assert len(evs) == 1 and evs[0].severity == "fault", \
            "rev-D GPB channel must drive the mapped AUX rule"


def test_stuck_exempt_covers_full_aux_bank():
    for i in range(1, 12):
        assert f"AUX{i}" in cd.STUCK_EXEMPT, f"AUX{i} missing from STUCK_EXEMPT"
    assert "AUX0" not in cd.STUCK_EXEMPT and "AUX12" not in cd.STUCK_EXEMPT


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
