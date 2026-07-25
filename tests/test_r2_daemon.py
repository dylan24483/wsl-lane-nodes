"""test_r2_daemon.py — Codex round-2 daemon-side items (2026-07-21):
  R2-6  explicit board revision (no silent revC default; role-vs-revision
        rejection at startup; provisioning parser)
  R2-11 link v1.2.x records -> typed machine events (tapdump/tap_warn/
        uart_drops) + VCC_5V window rule
  R2-12 bank_unavailable / configured_role_missing / stale_channel /
        run_mismatch / fw_config_mismatch promotions; delivery identity on
        shipped cycle rows
  R2-14 PlatformHealth probes (clock drift, restart loop, storage retention,
        writer-drop promotion)
  R2-16 field_wet_ok loopback role + cascade suppression; extensible role
        registry

Run under pytest or standalone (py -3 tests/test_r2_daemon.py).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', 'lane_node')))

import controller_daemon as cd
from controller_daemon import (BoardController, BoardConfig, PlatformHealth,
                               _parse_board_revs, register_aux_role,
                               AUX_ROLE_HANDLERS)
from cycle_control_8270 import State
from diag_events import DiagWriter, JsonlSink, OutboxReplayer


class FakeWriter:
    def __init__(self):
        self.events = []

    def emit(self, ev):
        self.events.append(ev)
        return True

    def emit_durable(self, ev, timeout=2.0):
        return self.emit(ev)

    def of_type(self, et):
        return [e for e in self.events if e.event_type == et]


class FakeShipper:
    def __init__(self):
        self.rows = []

    def offer(self, row):
        self.rows.append(row)
        return True


class FakeBoardIdentity:
    """Minimal board shape used by service-topology relay tests."""

    def __init__(self, lane):
        self.cfg = type("Cfg", (), {"lane": lane})()


def mk_board(roles=None, writer=None, shipper=None, board_rev="revC"):
    return BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev=board_rev,
            allowed_fw_builds=("abc1234",),
            allowed_fw_cfgs=("aa4ff333",),
            qualified_fw_releases=(
                (board_rev, "abc1234", "aa4ff333"),),
            supported_fw_board_revisions=(board_rev,),
            allow_legacy_revc_no_identity=(board_rev == "revC"),
            legacy_revc_no_identity_enrolled=(board_rev == "revC")),
        sim=True,
        diag_writer=writer, cycle_shipper=shipper, aux_roles=roles or {},
        slow_debounce_n=1)


def hb(bc, extra=""):
    fields = json.loads("{" + extra.lstrip(",") + "}") if extra else {}
    if "up" not in fields:
        fields["up"] = max(
            getattr(bc, "_test_hb_up", 0),
            int(bc.io.now() * 1000))
    bc._test_hb_up = max(
        getattr(bc, "_test_hb_up", 0), int(fields["up"]))
    fields.update({"ev": "hb", "ok": 1})
    modern = (
        bc.cfg.board_rev == "revD"
        or "bn" in fields
        or "rid" in fields
    )
    if modern:
        fields.setdefault("bn", 123)
        fields.setdefault("rid", 1 if bc.cfg.board_rev == "revD" else 255)
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
    bc.tick()
    bc.io.slow["PBZ"] = True
    bc.tick()
    bc.io.slow["PBZ"] = False
    hb(bc)
    bc.tick()


# ── R2-6: explicit board revision ──────────────────────────────────────────

def test_unprovisioned_board_rev_is_refused():
    try:
        BoardController(BoardConfig(21, 1, "sim", 0, 0), sim=True)
        raise AssertionError("board_rev=None must refuse construction")
    except ValueError as e:
        assert "UNPROVISIONED" in str(e) or "board_rev" in str(e)


def test_rev_unsupported_role_is_rejected_at_startup():
    try:
        mk_board(roles={"AUX7": "exit_beam"}, board_rev="revC")
        raise AssertionError("AUX7 role on a revC board must be rejected")
    except ValueError as e:
        assert "AUX7" in str(e)
    # the same role on a rev-D board is fine
    bc = mk_board(roles={"AUX7": "exit_beam"}, board_rev="revD")
    assert bc.diag.aux_roles == {"AUX7": "exit_beam"}


def test_parse_board_revs():
    assert _parse_board_revs(None) == (None, {})
    assert _parse_board_revs("revC") == ("revC", {})
    d, per = _parse_board_revs("21=revC,22=revD")
    assert d is None and per == {21: "revC", 22: "revD"}
    try:
        _parse_board_revs("revC revD")
        raise AssertionError("two defaults must raise")
    except ValueError:
        pass
    try:
        _parse_board_revs("x=revC")
        raise AssertionError("non-int lane must raise")
    except ValueError:
        pass
    for bad in ("21=revC,21=revD", "21=", "021=revC", "21=revZ"):
        try:
            _parse_board_revs(bad)
            raise AssertionError(f"{bad!r} must fail closed")
        except ValueError:
            pass
    try:
        _parse_board_revs(
            "21=revD,23=revD", known_lanes={21, 22})
        raise AssertionError("unselected board-rev lane must raise")
    except ValueError:
        pass


# ── R2-16: field_wet_ok role + suppression ─────────────────────────────────

def test_field_wet_lost_suppresses_cascade_and_restores():
    w = FakeWriter()
    bc = mk_board(roles={"AUX3": "field_wet_ok"}, writer=w)
    bc.io.slow["AUX3"] = True          # supply up at baseline
    to_ready(bc)
    assert w.of_type("field_wet_lost") == []
    # supply drops: every field input goes low together
    bc.io.slow["AUX3"] = False
    hb(bc)
    bc.tick()
    lost = w.of_type("field_wet_lost")
    assert len(lost) == 1 and lost[0].severity == "fault"
    assert lost[0].detail.get("at_startup") is False
    # while lost: stuck-input rule (etc.) must stay silent
    bc.io.slow["Foul"] = True
    for _ in range(5):
        bc.io.advance(30.0)
        hb(bc)
        bc.tick()
    assert w.of_type("stuck_input") == []
    # supply returns
    bc.io.slow["Foul"] = False
    bc.io.slow["AUX3"] = True
    hb(bc)
    bc.tick()
    rest = w.of_type("field_wet_restored")
    assert len(rest) == 1 and rest[0].detail.get("outage_s") is not None


def test_field_wet_down_at_startup_alerts_as_baseline():
    w = FakeWriter()
    bc = mk_board(roles={"AUX3": "field_wet_ok"}, writer=w)
    to_ready(bc)   # AUX3 never asserted
    lost = w.of_type("field_wet_lost")
    assert len(lost) == 1 and lost[0].detail.get("at_startup") is True


def test_field_wet_outage_invalidates_pair_exit_absence_evidence():
    w = FakeWriter()
    lane21 = cd.LaneDiag(
        21, writer=w,
        aux_roles={"AUX2": "exit_beam", "AUX11": "field_wet_ok"})
    lane22 = cd.LaneDiag(22, writer=w, aux_roles={})
    tracker = cd.BallReturnTracker([21, 22], timeout_s=5.0)
    lane21.set_ball_tracker(tracker)
    lane22.set_ball_tracker(tracker)

    healthy = {"AUX2": False, "AUX11": True}
    wet_lost = {"AUX2": False, "AUX11": False}
    lane21.poll(0.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=healthy)
    assert tracker._sources == {21: True}

    # Queue one pre-outage timer, then make the shared source blind.
    lane21.on_ball(0.0)
    lane21.poll(1.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=wet_lost)
    assert tracker._sources == {21: False}
    assert tracker._pause_since == 1.0
    assert list(tracker._pending[21]) == []

    # A pair-mate ball during the blind interval may return unseen, so it must
    # not be queued and later blamed on lane 22.
    lane22.on_ball(2.0)
    assert list(tracker._pending[22]) == []
    lane21.poll(9.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=wet_lost)
    assert w.of_type("ball_return_missing") == []

    # Restoration never resumes the unverifiable pre-outage timer. One full
    # timeout is a drain quarantine for a late return from the blind interval.
    lane21.poll(10.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=healthy)
    assert tracker._sources == {21: True}
    assert tracker._quarantine_until == 15.0
    assert list(tracker._pending[21]) == []
    lane21.on_ball(12.0)
    assert list(tracker._pending[21]) == []
    lane21.poll(20.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=healthy)
    assert w.of_type("ball_return_missing") == []
    lane21.on_ball(20.0)
    lane21.poll(25.1, ready=True, in_motion=False,
                slow_levels={}, inb_levels=healthy)
    missing = w.of_type("ball_return_missing")
    assert len(missing) == 1 and missing[0].lane_id == 21
    assert tracker.missing_total[22] == 0


def test_sensor_24v_loss_invalidates_exit_and_index_absence_evidence():
    old_gap = os.environ.get("WSL_DIAG_DIST_GAP_S")
    old_stale = os.environ.get("WSL_DIAG_STALE_CHANNEL_CYCLES")
    os.environ["WSL_DIAG_DIST_GAP_S"] = "3"
    os.environ["WSL_DIAG_STALE_CHANNEL_CYCLES"] = "1"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w,
            aux_roles={"AUX2": "exit_beam", "AUX3": "dist_index",
                       "AUX10": "sensor_24v_ok"})
        tracker = cd.BallReturnTracker([21], timeout_s=5.0)
        diag.set_ball_tracker(tracker)
        healthy = {"AUX2": False, "AUX3": False, "AUX10": True}
        lost = dict(healthy, AUX10=False)

        diag.poll(0.0, ready=True, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        diag.on_ball(0.0)
        diag.poll(0.5, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        diag.poll(1.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=lost)
        events = w.of_type("sensor_supply_lost")
        assert len(events) == 1
        assert events[0].severity == "fault"
        assert events[0].detail["at_startup"] is False

        # Blindness invalidates every active absence claim. The ball may have
        # returned and the distributor may have indexed while unreadable.
        assert list(tracker._pending[21]) == []
        assert diag._cycle_start_t is None
        assert diag._dist_last_pulse is None
        assert diag._cycles_since_pulse == {}
        for t in (10.0, 50.0, 100.0):
            diag.note_cycle_complete(t)
            diag.poll(t, ready=False, in_motion=True,
                      slow_levels={}, inb_levels=lost)
        assert w.of_type("dist_index_stall") == []
        assert w.of_type("ball_return_missing") == []
        assert w.of_type("stale_channel") == []

        # Recovery is only a level baseline. No pre-outage absence timer or
        # stale count may resume; exit tracking also drains one timeout window.
        diag.poll(101.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        restored = w.of_type("sensor_supply_restored")
        assert len(restored) == 1
        assert restored[0].detail["outage_s"] == 100.0
        assert tracker._quarantine_until == 106.0
        assert diag._cycle_start_t is None
        diag.poll(105.1, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert w.of_type("dist_index_stall") == []
        assert w.of_type("ball_return_missing") == []
        assert w.of_type("stale_channel") == []

        # Only a wholly post-recovery ball creates fresh absence evidence.
        diag.on_ball(106.0)
        diag.poll(109.1, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert len(w.of_type("dist_index_stall")) == 1
        assert w.of_type("ball_return_missing") == []
        diag.poll(111.1, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert len(w.of_type("ball_return_missing")) == 1
    finally:
        if old_gap is None:
            os.environ.pop("WSL_DIAG_DIST_GAP_S", None)
        else:
            os.environ["WSL_DIAG_DIST_GAP_S"] = old_gap
        if old_stale is None:
            os.environ.pop("WSL_DIAG_STALE_CHANNEL_CYCLES", None)
        else:
            os.environ["WSL_DIAG_STALE_CHANNEL_CYCLES"] = old_stale


def test_dist_evidence_invalidated_once_across_sensor_then_bank_union():
    old_gap = os.environ.get("WSL_DIAG_DIST_GAP_S")
    os.environ["WSL_DIAG_DIST_GAP_S"] = "3"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w,
            aux_roles={"AUX3": "dist_index",
                       "AUX10": "sensor_24v_ok"})
        healthy = {"AUX3": False, "AUX10": True}
        supply_lost = {"AUX3": False, "AUX10": False}
        diag.poll(0.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        diag.on_ball(0.0)

        # External supply is lost first, then the whole bank is UNKNOWN.
        diag.poll(1.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=supply_lost)
        diag.poll(2.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=None)
        diag.poll(100.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=supply_lost)
        assert diag._dist_pause_since == 1.0
        assert diag._cycle_start_t is None
        assert w.of_type("dist_index_stall") == []

        # Final recovery closes the union but cannot revive the blind cycle.
        diag.poll(101.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert diag._dist_pause_since is None
        assert diag._cycle_start_t is None
        diag.poll(110.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert w.of_type("dist_index_stall") == []

        # A wholly post-recovery cycle starts the next defensible gap timer.
        diag.on_ball(110.0)
        diag.poll(113.1, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert len(w.of_type("dist_index_stall")) == 1
    finally:
        if old_gap is None:
            os.environ.pop("WSL_DIAG_DIST_GAP_S", None)
        else:
            os.environ["WSL_DIAG_DIST_GAP_S"] = old_gap


def test_dist_evidence_invalidated_across_field_bank_sensor_union():
    old_gap = os.environ.get("WSL_DIAG_DIST_GAP_S")
    os.environ["WSL_DIAG_DIST_GAP_S"] = "3"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w,
            aux_roles={"AUX3": "dist_index",
                       "AUX10": "sensor_24v_ok",
                       "AUX11": "field_wet_ok"})
        healthy = {"AUX3": False, "AUX10": True, "AUX11": True}
        all_low = {"AUX3": False, "AUX10": False, "AUX11": False}
        sensor_low = {"AUX3": False, "AUX10": False, "AUX11": True}
        diag.poll(0.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        diag.on_ball(0.0)

        # FIELD_WET loss starts the union; bank UNKNOWN overlaps it. On bank
        # recovery FIELD_WET is still low, so no timer can resume.
        diag.poll(1.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=all_low)
        diag.poll(2.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=None)
        diag.poll(50.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=all_low)
        assert diag._dist_pause_since == 1.0
        assert diag._cycle_start_t is None

        # FIELD_WET returns while external sensor 24 V remains low. The single
        # union state stays blind; no partial recovery may restart evidence.
        diag.poll(60.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=sensor_low)
        assert diag._dist_pause_since == 1.0
        assert diag._cycle_start_t is None
        assert w.of_type("dist_index_stall") == []

        # The final source recovers at t=100 without reviving the old cycle.
        diag.poll(100.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert diag._dist_pause_since is None
        assert diag._cycle_start_t is None
        diag.poll(110.0, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert w.of_type("dist_index_stall") == []

        diag.on_ball(110.0)
        diag.poll(113.1, ready=False, in_motion=True,
                  slow_levels={}, inb_levels=healthy)
        assert len(w.of_type("dist_index_stall")) == 1
    finally:
        if old_gap is None:
            os.environ.pop("WSL_DIAG_DIST_GAP_S", None)
        else:
            os.environ["WSL_DIAG_DIST_GAP_S"] = old_gap


def test_sensor_24v_blind_interval_does_not_create_ball_timer():
    w = FakeWriter()
    diag = cd.LaneDiag(
        21, writer=w,
        aux_roles={"AUX2": "exit_beam", "AUX10": "sensor_24v_ok"})
    tracker = cd.BallReturnTracker([21], timeout_s=1.0)
    diag.set_ball_tracker(tracker)
    diag.poll(0.0, ready=True, in_motion=False, slow_levels={},
              inb_levels={"AUX2": False, "AUX10": True})
    diag.poll(1.0, ready=True, in_motion=False, slow_levels={},
              inb_levels={"AUX2": False, "AUX10": False})
    diag.on_ball(2.0)
    assert list(tracker._pending[21]) == []
    diag.poll(20.0, ready=True, in_motion=False, slow_levels={},
              inb_levels={"AUX2": False, "AUX10": True})
    diag.poll(30.0, ready=True, in_motion=False, slow_levels={},
              inb_levels={"AUX2": False, "AUX10": True})
    assert w.of_type("ball_return_missing") == []


def test_initial_false_exit_source_requires_recovery_drain():
    tracker = cd.BallReturnTracker([21], timeout_s=5.0)
    tracker.register_source(21)

    tracker.set_source_available(21, False, 0.0)
    assert tracker._pause_since == 0.0
    assert tracker.on_ball(21, 1.0) is False

    tracker.set_source_available(21, True, 2.0)
    assert tracker._quarantine_until == 7.0
    assert tracker.on_ball(21, 3.0) is False
    tracker.on_exit_pulse(4.0)
    assert list(tracker._pending[21]) == []

    assert tracker.on_ball(21, 7.0) is True
    tracker.poll(13.0)
    assert tracker.missing_total[21] == 1


def test_startup_unknown_activity_also_requires_recovery_drain():
    tracker = cd.BallReturnTracker([21], timeout_s=4.0)
    tracker.register_source(21)
    assert tracker.on_ball(21, 0.0) is False
    tracker.set_source_available(21, True, 1.0)
    assert tracker._quarantine_until == 5.0


def test_unknown_interval_resets_stale_counter_until_fresh_cycles():
    old_stale = os.environ.get("WSL_DIAG_STALE_CHANNEL_CYCLES")
    os.environ["WSL_DIAG_STALE_CHANNEL_CYCLES"] = "2"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w,
            aux_roles={"AUX3": "dist_index",
                       "AUX10": "sensor_24v_ok"})
        healthy = {"AUX3": False, "AUX10": True}
        lost = {"AUX3": False, "AUX10": False}
        diag.poll(0.0, ready=False, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        diag.on_ball(0.1)
        diag.note_cycle_complete(0.5)
        diag.poll(0.5, ready=False, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        assert diag._cycles_since_pulse["AUX3"] == 1

        diag.poll(1.0, ready=False, in_motion=False,
                  slow_levels={}, inb_levels=lost)
        assert "AUX3" not in diag._cycles_since_pulse
        assert "dist_index" in diag._invalidated_pulse_cycles
        diag.note_cycle_complete(5.0)
        assert w.of_type("stale_channel") == []

        diag.poll(10.0, ready=False, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        # A completion spanning the blind interval is still unverifiable.
        diag.note_cycle_complete(10.5)
        assert w.of_type("stale_channel") == []

        for start in (11.0, 13.0):
            diag.on_ball(start)
            diag.note_cycle_complete(start + 1.0)
            diag.poll(start + 1.0, ready=False, in_motion=False,
                      slow_levels={}, inb_levels=healthy)
        stale = w.of_type("stale_channel")
        assert len(stale) == 1
        assert stale[0].detail["cycles_without_pulse"] == 2
    finally:
        if old_stale is None:
            os.environ.pop("WSL_DIAG_STALE_CHANNEL_CYCLES", None)
        else:
            os.environ["WSL_DIAG_STALE_CHANNEL_CYCLES"] = old_stale


def test_field_wet_unknown_cancels_be_no_current_absence_window():
    old_window = os.environ.get("WSL_DIAG_BE_WINDOW_S")
    os.environ["WSL_DIAG_BE_WINDOW_S"] = "3"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w,
            aux_roles={"AUX1": "be_current", "AUX11": "field_wet_ok"})
        healthy = {"AUX1": False, "AUX11": True}
        lost = {"AUX1": False, "AUX11": False}
        diag.poll(0.0, ready=True, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        diag.on_ball(0.0)
        diag.note_cycle_complete(0.0)
        diag.poll(0.0, ready=True, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        assert diag._be_deadline == 3.0

        diag.poll(1.0, ready=True, in_motion=False,
                  slow_levels={}, inb_levels=lost)
        assert diag._be_deadline is None
        diag.poll(100.0, ready=True, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        diag.poll(200.0, ready=True, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        assert w.of_type("be_no_current") == []

        diag.on_ball(200.0)
        diag.note_cycle_complete(200.0)
        diag.poll(203.1, ready=True, in_motion=False,
                  slow_levels={}, inb_levels=healthy)
        assert len(w.of_type("be_no_current")) == 1
    finally:
        if old_window is None:
            os.environ.pop("WSL_DIAG_BE_WINDOW_S", None)
        else:
            os.environ["WSL_DIAG_BE_WINDOW_S"] = old_window


def test_blind_spanning_cycle_cannot_open_be_window_on_recovery():
    old_window = os.environ.get("WSL_DIAG_BE_WINDOW_S")
    os.environ["WSL_DIAG_BE_WINDOW_S"] = "3"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w,
            aux_roles={"AUX1": "be_current", "AUX11": "field_wet_ok"})
        healthy = {"AUX1": False, "AUX11": True}
        lost = {"AUX1": False, "AUX11": False}
        diag.poll(
            0.0, ready=True, in_motion=False,
            slow_levels={}, inb_levels=healthy)
        diag.poll(
            1.0, ready=False, in_motion=True,
            slow_levels={}, inb_levels=lost)

        # Production queues completion before reading this recovery sample.
        diag.note_cycle_complete(2.0)
        diag.poll(
            2.0, ready=True, in_motion=False,
            slow_levels={}, inb_levels=healthy)
        diag.poll(
            6.0, ready=True, in_motion=False,
            slow_levels={}, inb_levels=healthy)
        assert diag._be_deadline is None
        assert w.of_type("be_no_current") == []

        diag.on_ball(7.0)
        diag.note_cycle_complete(7.0)
        diag.poll(
            10.1, ready=True, in_motion=False,
            slow_levels={}, inb_levels=healthy)
        assert len(w.of_type("be_no_current")) == 1
    finally:
        if old_window is None:
            os.environ.pop("WSL_DIAG_BE_WINDOW_S", None)
        else:
            os.environ["WSL_DIAG_BE_WINDOW_S"] = old_window


def test_repeated_cycles_do_not_postpone_active_be_deadline():
    old_window = os.environ.get("WSL_DIAG_BE_WINDOW_S")
    os.environ["WSL_DIAG_BE_WINDOW_S"] = "3"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w, aux_roles={"AUX1": "be_current"})
        levels = {"AUX1": False}
        diag.poll(
            0.0, ready=True, in_motion=False,
            slow_levels={}, inb_levels=levels)
        for t in (0.0, 2.0):
            diag.on_ball(t)
            diag.note_cycle_complete(t)
            diag.poll(
                t, ready=True, in_motion=False,
                slow_levels={}, inb_levels=levels)
        assert diag._be_deadline == 3.0
        diag.poll(
            3.1, ready=True, in_motion=False,
            slow_levels={}, inb_levels=levels)
        assert len(w.of_type("be_no_current")) == 1
    finally:
        if old_window is None:
            os.environ.pop("WSL_DIAG_BE_WINDOW_S", None)
        else:
            os.environ["WSL_DIAG_BE_WINDOW_S"] = old_window


def test_missing_field_wet_health_invalidates_all_field_time_anchors():
    old_stuck = os.environ.get("WSL_DIAG_STUCK_INPUT_S")
    old_beam = os.environ.get("WSL_DIAG_BEAM_BLOCKED_S")
    old_window = os.environ.get("WSL_DIAG_BE_WINDOW_S")
    os.environ["WSL_DIAG_STUCK_INPUT_S"] = "2"
    os.environ["WSL_DIAG_BEAM_BLOCKED_S"] = "2"
    os.environ["WSL_DIAG_BE_WINDOW_S"] = "2"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w,
            aux_roles={"AUX1": "be_current", "AUX11": "field_wet_ok"})
        healthy = {"AUX1": False, "AUX11": True}
        diag.poll(
            0.0, ready=True, in_motion=False,
            slow_levels={"TA2": True}, inb_levels=healthy,
            diell_levels={"DIELL_L": True})
        diag.on_ball(0.0)
        diag.note_cycle_complete(0.0)
        diag.poll(
            0.0, ready=True, in_motion=False,
            slow_levels={"TA2": True}, inb_levels=healthy,
            diell_levels={"DIELL_L": True})
        assert diag._be_deadline == 2.0

        # Only the health channel disappears. Every field-derived timer becomes
        # unverifiable even though the other sampled levels remain asserted.
        diag.poll(
            1.0, ready=True, in_motion=False,
            slow_levels={"TA2": True}, inb_levels={"AUX1": False},
            diell_levels={"DIELL_L": True})
        assert diag._be_deadline is None
        assert diag._assert_since == {}

        diag.poll(
            100.0, ready=True, in_motion=False,
            slow_levels={"TA2": True}, inb_levels=healthy,
            diell_levels={"DIELL_L": True})
        assert w.of_type("be_no_current") == []
        assert w.of_type("stuck_input") == []
        assert w.of_type("beam_blocked") == []
        assert diag._assert_since["TA2"] == 100.0
        assert diag._assert_since["DIELL_L"] == 100.0
    finally:
        for name, old in (
                ("WSL_DIAG_STUCK_INPUT_S", old_stuck),
                ("WSL_DIAG_BEAM_BLOCKED_S", old_beam),
                ("WSL_DIAG_BE_WINDOW_S", old_window)):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def test_completion_waits_for_current_sample_and_same_cycle_pulse():
    old_stale = os.environ.get("WSL_DIAG_STALE_CHANNEL_CYCLES")
    os.environ["WSL_DIAG_STALE_CHANNEL_CYCLES"] = "1"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(
            21, writer=w, aux_roles={"AUX3": "dist_index"})
        diag.poll(
            0.0, ready=False, in_motion=False,
            slow_levels={}, inb_levels={"AUX3": False})

        diag.on_ball(0.1)
        diag.poll(
            0.2, ready=False, in_motion=True,
            slow_levels={}, inb_levels={"AUX3": True})
        diag.note_cycle_complete(0.3)
        diag.poll(
            0.3, ready=True, in_motion=False,
            slow_levels={}, inb_levels={"AUX3": True})
        assert w.of_type("stale_channel") == []

        # Completion is queued before the sample, as in production. UNKNOWN in
        # that same tick must discard it before any threshold-one warning.
        diag.on_ball(1.0)
        diag.note_cycle_complete(1.1)
        diag.poll(
            1.1, ready=True, in_motion=False,
            slow_levels={}, inb_levels=None)
        assert w.of_type("stale_channel") == []
    finally:
        if old_stale is None:
            os.environ.pop("WSL_DIAG_STALE_CHANNEL_CYCLES", None)
        else:
            os.environ["WSL_DIAG_STALE_CHANNEL_CYCLES"] = old_stale


def test_dynamic_diagnostic_gates_invalidate_absence_evidence():
    old_master = os.environ.get("WSL_DIAG_DAEMON_EVENTS")
    old_aux = os.environ.get("WSL_DIAG_AUX_RULES")
    old_stale = os.environ.get("WSL_DIAG_STALE_CHANNEL_CYCLES")
    os.environ["WSL_DIAG_DAEMON_EVENTS"] = "1"
    os.environ["WSL_DIAG_AUX_RULES"] = "1"
    os.environ["WSL_DIAG_STALE_CHANNEL_CYCLES"] = "1"
    try:
        for gate in ("WSL_DIAG_AUX_RULES", "WSL_DIAG_DAEMON_EVENTS"):
            w = FakeWriter()
            diag = cd.LaneDiag(
                21, writer=w,
                aux_roles={"AUX2": "exit_beam", "AUX1": "be_current"})
            tracker = cd.BallReturnTracker([21], timeout_s=3.0)
            diag.set_ball_tracker(tracker)
            healthy = {"AUX1": False, "AUX2": False}
            diag.poll(
                0.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=healthy)
            diag.on_ball(0.1)

            os.environ[gate] = "0"
            diag.note_cycle_complete(0.2)
            diag.poll(
                1.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=healthy)
            diag.on_ball(1.1)

            os.environ[gate] = "1"
            diag.poll(
                2.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=healthy)
            diag.poll(
                20.0, ready=True, in_motion=False,
                slow_levels={}, inb_levels=healthy)
            assert w.of_type("ball_return_missing") == []
            assert w.of_type("stale_channel") == []
            assert w.of_type("be_no_current") == []
    finally:
        for name, old in (
                ("WSL_DIAG_DAEMON_EVENTS", old_master),
                ("WSL_DIAG_AUX_RULES", old_aux),
                ("WSL_DIAG_STALE_CHANNEL_CYCLES", old_stale)):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def test_individual_rule_gates_rebaseline_elapsed_time():
    saved = {
        name: os.environ.get(name)
        for name in (
            "WSL_DIAG_STUCK_INPUT", "WSL_DIAG_STUCK_INPUT_S",
            "WSL_DIAG_BEAM_BLOCKED", "WSL_DIAG_BEAM_BLOCKED_S",
            "WSL_DIAG_MANUAL_OVERRIDE")
    }
    os.environ["WSL_DIAG_STUCK_INPUT"] = "1"
    os.environ["WSL_DIAG_STUCK_INPUT_S"] = "2"
    os.environ["WSL_DIAG_BEAM_BLOCKED"] = "1"
    os.environ["WSL_DIAG_BEAM_BLOCKED_S"] = "2"
    os.environ["WSL_DIAG_MANUAL_OVERRIDE"] = "1"
    try:
        w = FakeWriter()
        diag = cd.LaneDiag(21, writer=w)
        diag.poll(
            0.0, ready=True, in_motion=False,
            slow_levels={"TA2": True, "MAN_T": False}, inb_levels={},
            diell_levels={"DIELL_L": True})

        os.environ["WSL_DIAG_STUCK_INPUT"] = "0"
        os.environ["WSL_DIAG_BEAM_BLOCKED"] = "0"
        os.environ["WSL_DIAG_MANUAL_OVERRIDE"] = "0"
        diag.poll(
            1.0, ready=True, in_motion=False,
            slow_levels={"TA2": True, "MAN_T": False}, inb_levels={},
            diell_levels={"DIELL_L": False})
        diag.poll(
            100.0, ready=True, in_motion=False,
            slow_levels={"TA2": True, "MAN_T": False}, inb_levels={},
            diell_levels={"DIELL_L": True})

        os.environ["WSL_DIAG_STUCK_INPUT"] = "1"
        os.environ["WSL_DIAG_BEAM_BLOCKED"] = "1"
        os.environ["WSL_DIAG_MANUAL_OVERRIDE"] = "1"
        diag.poll(
            101.0, ready=True, in_motion=False,
            slow_levels={"TA2": True, "MAN_T": True}, inb_levels={},
            diell_levels={"DIELL_L": True})
        assert w.of_type("stuck_input") == []
        assert w.of_type("beam_blocked") == []
        assert w.of_type("manual_override") == []
        assert diag.suppress_until == 0.0

        diag.poll(
            104.0, ready=True, in_motion=False,
            slow_levels={"TA2": True, "MAN_T": True}, inb_levels={},
            diell_levels={"DIELL_L": True})
        assert len(w.of_type("stuck_input")) == 1
        assert len(w.of_type("beam_blocked")) == 1
    finally:
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def test_failed_exit_source_board_invalidates_pair_return_evidence():
    w = FakeWriter()
    source = cd.LaneDiag(
        21, writer=w, aux_roles={"AUX2": "exit_beam"})
    mate = cd.LaneDiag(22, writer=w, aux_roles={})
    tracker = cd.BallReturnTracker([21, 22], timeout_s=3.0)
    source.set_ball_tracker(tracker)
    mate.set_ball_tracker(tracker)
    source.poll(
        0.0, ready=True, in_motion=False,
        slow_levels={}, inb_levels={"AUX2": False})
    assert tracker._sources == {21: True}

    mate.on_ball(0.1)
    source.mark_board_unavailable(1.0)
    assert tracker._sources == {21: False}
    assert list(tracker._pending[22]) == []
    mate.on_ball(2.0)
    tracker.poll(10.0)
    assert w.of_type("ball_return_missing") == []


def test_field_wet_loss_owns_cascade_before_sensor_24v():
    w = FakeWriter()
    diag = cd.LaneDiag(
        21, writer=w,
        aux_roles={"AUX2": "exit_beam", "AUX10": "sensor_24v_ok",
                   "AUX11": "field_wet_ok"})
    diag.poll(0.0, ready=True, in_motion=False, slow_levels={},
              inb_levels={"AUX2": False, "AUX10": True, "AUX11": True})
    # FIELD_WET_V loss deasserts every opto even when external 24 V remains
    # healthy. Only the field-wetting root cause may fire.
    diag.poll(1.0, ready=True, in_motion=False, slow_levels={},
              inb_levels={"AUX2": False, "AUX10": False, "AUX11": False})
    assert len(w.of_type("field_wet_lost")) == 1
    assert w.of_type("sensor_supply_lost") == []
    # Once FIELD_WET_V is restored, an actually-open sensor-supply contact is
    # independently visible.
    diag.poll(2.0, ready=True, in_motion=False, slow_levels={},
              inb_levels={"AUX2": False, "AUX10": False, "AUX11": True})
    assert len(w.of_type("field_wet_restored")) == 1
    assert len(w.of_type("sensor_supply_lost")) == 1


def test_role_registry_is_extensible():
    calls = []
    register_aux_role("test_role_x", lambda diag, t, name, level, **kw:
                      calls.append((name, level)))
    try:
        w = FakeWriter()
        bc = mk_board(roles={"AUX2": "test_role_x"}, writer=w)
        to_ready(bc)
        assert calls, "registered role handler must be dispatched"
    finally:
        AUX_ROLE_HANDLERS.pop("test_role_x", None)


# ── R2-12: bank health + promotions ────────────────────────────────────────

def test_bank_unavailable_and_recovery():
    os.environ["WSL_DIAG_BANK_FAIL_N"] = "3"
    try:
        w = FakeWriter()
        bc = mk_board(writer=w)
        to_ready(bc)

        def boom():
            raise OSError("i2c gone")
        real = bc.io.read_inputs_b
        bc.io.read_inputs_b = boom
        for _ in range(4):
            hb(bc)
            bc.tick()
        evs = w.of_type("bank_unavailable")
        assert len(evs) == 1 and evs[0].severity == "warn"
        bc.io.read_inputs_b = real
        hb(bc)
        bc.tick()
        rec = [e for e in w.of_type("recovered")
               if e.code == "bank_unavailable"]
        assert len(rec) == 1
        assert rec[0].detail["recovered_event_type"] == "bank_unavailable"
        assert rec[0].detail["recovered_code"] == "in_b"
    finally:
        os.environ.pop("WSL_DIAG_BANK_FAIL_N", None)


def test_run_mismatch_promotes_to_fault_after_hold():
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    bc.link.run("S")
    bc.link.stop("S")
    for i in range(5):     # firmware keeps showing S running (lost STOP)
        bc.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":%d,"run":1}'
                          % (100 + 250 * i))
        bc.tick()
    assert w.of_type("run_mismatch") == []   # hold time not yet elapsed
    bc.io.advance(4.0)
    bc.link.feed_line(
        '{"ev":"hb","ok":1,"flt":"","up":2000,"run":1}')
    bc.tick()
    evs = w.of_type("run_mismatch")
    assert len(evs) == 1 and evs[0].severity == "fault"
    assert "S" in evs[0].detail["motors"]
    # firmware reconciles -> recovered
    bc.link.feed_line(
        '{"ev":"hb","ok":1,"flt":"","up":2300,"run":0}')
    bc.tick()
    recovered = [
        e for e in w.of_type("recovered") if e.code == "run_mismatch"]
    assert recovered
    assert recovered[0].detail["recovered_event_type"] == "run_mismatch"
    assert recovered[0].detail["recovered_code"] == evs[0].code


def test_run_mismatch_hold_restarts_after_link_unknown():
    old = os.environ.get("WSL_DIAG_RUN_MISMATCH_S")
    os.environ["WSL_DIAG_RUN_MISMATCH_S"] = "2"
    try:
        w = FakeWriter()
        bc = mk_board(writer=w)
        bc.link.run_mismatch = lambda: ["S"]
        bc._run_mm_since = 0.0

        bc._run_mismatch_rule(10.0, link_healthy=False)
        assert bc._run_mm_since is None
        assert w.of_type("run_mismatch") == []

        bc._run_mismatch_rule(10.0, link_healthy=True)
        bc._run_mismatch_rule(11.9, link_healthy=True)
        assert w.of_type("run_mismatch") == []
        bc._run_mismatch_rule(12.1, link_healthy=True)
        assert len(w.of_type("run_mismatch")) == 1
    finally:
        if old is None:
            os.environ.pop("WSL_DIAG_RUN_MISMATCH_S", None)
        else:
            os.environ["WSL_DIAG_RUN_MISMATCH_S"] = old


def test_fw_config_mismatch_fault_on_maxrun_desync():
    w = FakeWriter()
    bc = mk_board(writer=w)
    bc.link.feed_line('{"ev":"boot","fw":"t","maxrun_ms":1000}')
    to_ready(bc)
    assert bc.fsm.state is State.MANUAL_INTERVENTION
    assert bc.io.armed is False
    evs = w.of_type("fw_config_mismatch")
    assert len(evs) == 1 and evs[0].severity == "fault"
    assert evs[0].detail["fw_maxrun_ms"] == 1000
    bc.link.feed_line('{"ev":"boot","fw":"t","maxrun_ms":60000}')
    bc._evaluate_arm_preconditions()
    recovered = [
        e for e in w.of_type("recovered")
        if e.code == "fw_config_mismatch"]
    assert len(recovered) == 1
    assert recovered[0].detail == {
        "recovered_event_type": "fw_config_mismatch",
        "recovered_code": "maxrun_desync",
    }


def test_v5_out_of_range_rule():
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    hb(bc, ',"up":100,"v5":4400,"v5n":4300,"v5x":4500')
    bc.tick()
    evs = w.of_type("v5_out_of_range")
    assert len(evs) == 1 and evs[0].detail["v5_min_mv"] == 4300
    # still bad: no repeat (episode latch)
    hb(bc, ',"up":400,"v5":4400,"v5n":4310,"v5x":4500')
    bc.tick()
    assert len(w.of_type("v5_out_of_range")) == 1
    # back in window: re-arms
    hb(bc, ',"up":700,"v5":4900,"v5n":4800,"v5x":4950')
    bc.tick()
    hb(bc, ',"up":1000,"v5":4400,"v5n":4200,"v5x":4500')
    bc.tick()
    assert len(w.of_type("v5_out_of_range")) == 2


def test_tapdump_and_tapwarn_become_machine_events():
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    bc.link.feed_line('{"ev":"boot","fw":"t","tap":{"ep":2,"pre":0,"n":0}}')
    bc.link.feed_line('{"ev":"tapdump","n":2,"ep":2,"br":2,"mut":0,'
                      '"cause":"kick_starvation","t":30000}')
    bc.link.feed_line('{"ev":"tape","i":0,"t":29450,"p":1,"l":0,"ep":1}')
    bc.link.feed_line('{"ev":"tape","i":1,"t":29900,"p":2,"l":0,"ep":2}')
    bc.link.feed_line('{"ev":"tapdump_end","n":2}')
    bc.link.feed_line('{"ev":"tapwarn","code":"rpok_mism","t":30500}')
    hb(bc)
    bc.tick()
    dumps = w.of_type("tapdump")
    assert len(dumps) == 1
    assert dumps[0].code == "kick_starvation"
    assert dumps[0].detail["fresh_n"] == 1 and dumps[0].detail["stale_n"] == 1
    warns = w.of_type("tap_warn")
    assert len(warns) == 1 and warns[0].code == "rpok_mism"


def test_uart_drops_event():
    w = FakeWriter()
    bc = mk_board(writer=w)
    to_ready(bc)
    hb(bc, ',"up":100,"drp":0')
    bc.tick()
    hb(bc, ',"up":400,"drp":3')
    bc.tick()
    evs = w.of_type("uart_drops")
    assert len(evs) == 1 and evs[0].detail["lost"] == 3


ID_LINE = ('{"ev":"id","fw":"phase8b-rp2040 v1.2.3","bn":123,"pcb":"%s","rid":%s,'
           '"uid":"E66038B713952A31","build":"abc1234","cfg":"aa4ff333",'
           '"fi1":%d,"t":1234}')


def test_fw_identity_reaches_machine_events():
    # Round-3 (Codex 2026-07-21 PM): the fw_identity record was drained and
    # silently DISCARDED by _consume_link_records — no elif branch. It must
    # land in machine_events like every other typed record.
    w = FakeWriter()
    bc = mk_board(writer=w, board_rev="revD")
    to_ready(bc)
    bc.link.feed_line(ID_LINE % ("revD", 1, 0))
    bc.tick()
    evs = w.of_type("fw_identity")
    assert len(evs) == 1
    assert evs[0].severity == "info" and evs[0].code is None
    assert evs[0].detail["pcb"] == "revD"
    assert evs[0].detail["build"] == "abc1234"
    assert evs[0].detail["declared_rev"] == "revD"


def test_fw_identity_fi1_image_is_a_fault():
    w = FakeWriter()
    bc = mk_board(writer=w, board_rev="revD")
    to_ready(bc)
    bc.link.feed_line(ID_LINE % ("revD", 1, 1))
    bc.tick()
    evs = w.of_type("fw_identity")
    assert len(evs) == 1
    assert evs[0].severity == "fault" and evs[0].code == "fi1_image"


def test_fw_identity_pcb_rev_mismatch_is_a_fault():
    # declared revD but the straps read floating/unknown (or another rev)
    w = FakeWriter()
    bc = mk_board(writer=w, board_rev="revD")
    to_ready(bc)
    bc.link.feed_line(ID_LINE % ("unknown", 255, 0))
    bc.tick()
    evs = w.of_type("fw_identity")
    assert len(evs) == 1
    assert evs[0].severity == "fault" and evs[0].code == "pcb_rev_mismatch"
    assert evs[0].detail["declared_rev"] == "revD"


def test_fw_identity_revC_expects_floating_straps():
    # a rev-C-class board HAS no straps: strap read "unknown" is the EXPECTED
    # value there, never a mismatch fault
    w = FakeWriter()
    bc = mk_board(writer=w, board_rev="revC")
    to_ready(bc)
    hb(bc, ',"up":1230,"bn":123,"rid":255')
    bc.link.feed_line(ID_LINE % ("unknown", 255, 0))
    bc.tick()
    evs = w.of_type("fw_identity")
    assert len(evs) == 1
    assert evs[0].severity == "info" and evs[0].code is None


def test_stale_channel_after_quiet_cycles():
    os.environ["WSL_DIAG_STALE_CHANNEL_CYCLES"] = "3"
    try:
        w = FakeWriter()
        bc = mk_board(roles={"AUX2": "exit_beam"}, writer=w)
        to_ready(bc)
        for i in range(3):
            t = float(i)
            bc.diag.on_ball(t)
            bc.diag.note_cycle_complete(t + 0.1)
            bc.diag.poll(
                t + 0.1, ready=True, in_motion=False,
                slow_levels={}, inb_levels={"AUX2": False})
        evs = w.of_type("stale_channel")
        assert len(evs) == 1 and evs[0].detail["role"] == "exit_beam"
        # a pulse resets the episode
        bc.diag.on_ball(10.0)
        bc.diag._note_pulse("AUX2", 10.0)
        bc.diag.note_cycle_complete(10.1)
        bc.diag.poll(
            10.1, ready=True, in_motion=False,
            slow_levels={}, inb_levels={"AUX2": False})
        for i in range(3):
            t = 20.0 + i
            bc.diag.on_ball(t)
            bc.diag.note_cycle_complete(t + 0.1)
            bc.diag.poll(
                t + 0.1, ready=True, in_motion=False,
                slow_levels={}, inb_levels={"AUX2": False})
        assert len(w.of_type("stale_channel")) == 2
    finally:
        os.environ.pop("WSL_DIAG_STALE_CHANNEL_CYCLES", None)


def test_shipped_cycle_rows_carry_delivery_identity():
    from cycle_control_8270 import TIME_DELAY_S
    w, sh = FakeWriter(), FakeShipper()
    bc = mk_board(writer=w, shipper=sh)
    to_ready(bc)
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}')
    bc.tick()
    bc.link.feed_line('{"ev":"cam","id":"SB","e":"f"}')
    bc.tick()
    bc.io.advance(TIME_DELAY_S + 0.1)
    hb(bc)
    bc.tick()
    bc.link.feed_line('{"ev":"cam","id":"TA2","e":"f"}')
    bc.tick()
    bc.link.feed_line('{"ev":"cam","id":"SA","e":"f"}')
    bc.tick()
    bc.io.slow["BS"] = True
    bc.tick()
    bc.io.slow["BS"] = False
    bc.link.feed_line('{"ev":"cam","id":"TA1","e":"f"}')
    bc.tick()
    assert sh.rows, "cycle row must ship on READY"
    row = sh.rows[-1]
    assert row["source_id"] and row["boot_id"] and isinstance(row["seq"], int)


# ── R2-14: PlatformHealth probes ───────────────────────────────────────────

def test_master_gate_covers_platform_and_quarantine_emitters():
    old = os.environ.get("WSL_DIAG_DAEMON_EVENTS")
    try:
        w = FakeWriter()
        ph = PlatformHealth([], w, dir_path=tempfile.mkdtemp(prefix="ph_gate_"))
        notify = cd._make_quarantine_notifier(w)
        os.environ["WSL_DIAG_DAEMON_EVENTS"] = "0"
        ph._emit("warn", "pi_undervoltage")
        notify(1, 21, ["rejected"])
        assert w.events == []

        os.environ["WSL_DIAG_DAEMON_EVENTS"] = "1"
        ph._emit("warn", "pi_undervoltage")
        notify(1, 21, ["rejected"])
        assert len(w.events) == 2
    finally:
        if old is None:
            os.environ.pop("WSL_DIAG_DAEMON_EVENTS", None)
        else:
            os.environ["WSL_DIAG_DAEMON_EVENTS"] = old


def test_platform_clock_drift_probe():
    w = FakeWriter()
    ph = PlatformHealth([], w, dir_path=tempfile.mkdtemp(prefix="ph_"))
    ph._poll_clock_drift()            # baseline
    ph._clock_base -= 10.0            # simulate a 10 s NTP step
    ph._poll_clock_drift()
    evs = w.of_type("pi_clock_drift")
    assert len(evs) == 1 and abs(evs[0].detail["step_s"]) >= 5.0


def test_rejected_clock_step_retries_original_incident_after_step_reverses():
    class ToggleWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.accept = False
            self.attempts = []

        def emit(self, event):
            self.attempts.append(event)
            if not self.accept:
                return False
            self.events.append(event)
            return True

    writer = ToggleWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21)], writer,
        dir_path=tempfile.mkdtemp(prefix="ph_clock_retry_"))
    original_time = cd.time.time
    original_mono = cd.time.monotonic
    clocks = {"wall": 210.0, "mono": 100.0}
    try:
        cd.time.time = lambda: clocks["wall"]
        cd.time.monotonic = lambda: clocks["mono"]
        ph._clock_base = 100.0
        ph._poll_clock_drift()       # offset 110: rejected +10 s incident
        first = writer.attempts[-1]
        assert ph._clock_pending is not None

        clocks["wall"] = 200.0       # offset returned to the old baseline
        writer.accept = True
        ph._poll_clock_drift()
        delivered = writer.of_type("pi_clock_drift")
        assert delivered[0].detail["step_s"] == 10.0
        assert (delivered[0].ts_utc, delivered[0].ts_mono) == (
            first.ts_utc, first.ts_mono)
    finally:
        cd.time.time = original_time
        cd.time.monotonic = original_mono


def test_platform_restart_loop_probe():
    os.environ["WSL_DIAG_RESTART_LOOP_N"] = "3"
    try:
        d = tempfile.mkdtemp(prefix="ph_loop_")
        w = FakeWriter()
        for _ in range(3):
            ph = PlatformHealth([], w, dir_path=d)
            ph._count_service_start()
        assert len(w.of_type("service_restart")) == 3
        assert len(w.of_type("service_restart_loop")) >= 1
        data = json.load(open(os.path.join(d, "service_starts.json"),
                              encoding="utf-8"))
        assert data["count"] == 3 and len(data["recent"]) == 3
    finally:
        os.environ.pop("WSL_DIAG_RESTART_LOOP_N", None)


def test_rejected_startup_events_retry_fault_first_with_original_stamps():
    class ToggleWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.accept = False
            self.attempts = []

        def emit(self, event):
            self.attempts.append(event)
            if not self.accept:
                return False
            self.events.append(event)
            return True

    prior = os.environ.get("WSL_DIAG_RESTART_LOOP_N")
    os.environ["WSL_DIAG_RESTART_LOOP_N"] = "1"
    try:
        writer = ToggleWriter()
        ph = PlatformHealth(
            [FakeBoardIdentity(21)], writer,
            dir_path=tempfile.mkdtemp(prefix="ph_start_retry_"))
        ph._count_service_start()
        assert set(ph._service_start_pending) == {
            (1, "service_restart"), (1, "service_restart_loop")}
        assert writer.attempts[0].event_type == "service_restart_loop"
        original = {
            event.event_type: (event.ts_utc, event.ts_mono, dict(event.detail))
            for event in writer.attempts[:2]
        }

        writer.accept = True
        ph._retry_service_start_events()
        assert [event.event_type for event in writer.events] == [
            "service_restart_loop", "service_restart"]
        for event in writer.events:
            assert (event.ts_utc, event.ts_mono, event.detail) == \
                original[event.event_type]
        assert ph._service_start_pending == {}
        state = json.load(open(
            ph._service_start_path, encoding="utf-8"))
        assert "pending_events" not in state
    finally:
        if prior is None:
            os.environ.pop("WSL_DIAG_RESTART_LOOP_N", None)
        else:
            os.environ["WSL_DIAG_RESTART_LOOP_N"] = prior


def test_track_b_service_start_wal_reuses_exact_delivery_identity_after_crash():
    class AcceptWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.attempts = []

        def emit_durable(self, event, timeout=2.0):
            self.attempts.append(event)
            return True

    prior = os.environ.get("WSL_DIAG_RESTART_LOOP_N")
    os.environ["WSL_DIAG_RESTART_LOOP_N"] = "999"
    original_ack = cd.health_drop.acknowledge_service_start_lane
    cd.health_drop.acknowledge_service_start_lane = lambda *_a, **_k: False
    try:
        directory = tempfile.mkdtemp(prefix="ph_start_exact_wal_")
        first_writer = AcceptWriter()
        first = PlatformHealth(
            [FakeBoardIdentity(21)], first_writer, dir_path=directory)
        first._count_service_start()
        first_event = next(
            event for event in first_writer.attempts
            if event.event_type == "service_restart"
            and event.detail["count"] == 1)
        first_row = first_event.to_dict()
        assert {"source_id", "boot_id", "seq"} <= set(first_row)

        state = json.load(open(
            first._service_start_path, encoding="utf-8"))
        assert state["pending_events"][0][
            "service_restart_deliveries"] == [first_row]

        second_writer = AcceptWriter()
        second = PlatformHealth(
            [FakeBoardIdentity(21)], second_writer, dir_path=directory)
        second._count_service_start()
        replay = next(
            event for event in second_writer.attempts
            if event.event_type == "service_restart"
            and event.detail["count"] == 1)
        assert replay.to_dict() == first_row
    finally:
        cd.health_drop.acknowledge_service_start_lane = original_ack
        if prior is None:
            os.environ.pop("WSL_DIAG_RESTART_LOOP_N", None)
        else:
            os.environ["WSL_DIAG_RESTART_LOOP_N"] = prior


def test_track_b_service_start_mismatched_local_receipt_blocks_ack():
    class AcceptWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.attempts = []

        def emit_durable(self, event, timeout=2.0):
            self.attempts.append(event)
            return True

    prior = os.environ.get("WSL_DIAG_RESTART_LOOP_N")
    os.environ["WSL_DIAG_RESTART_LOOP_N"] = "999"
    original_ack = cd.health_drop.acknowledge_service_start_lane
    cd.health_drop.acknowledge_service_start_lane = lambda *_a, **_k: False
    try:
        directory = tempfile.mkdtemp(prefix="ph_start_bad_receipt_")
        first_writer = AcceptWriter()
        first = PlatformHealth(
            [FakeBoardIdentity(21)], first_writer, dir_path=directory)
        first._count_service_start()
        row = next(
            event.to_dict() for event in first_writer.attempts
            if event.event_type == "service_restart"
            and event.detail["count"] == 1)
        tampered = dict(row)
        tampered["code"] = "lane_node_start"
        with open(
                os.path.join(directory, "diag-20260724.jsonl"),
                "w", encoding="utf-8") as handle:
            handle.write(json.dumps(tampered) + "\n")

        second_writer = AcceptWriter()
        second = PlatformHealth(
            [FakeBoardIdentity(21)], second_writer, dir_path=directory)
        second._count_service_start()
        assert not any(
            event.event_type == "service_restart"
            and event.detail["count"] == 1
            for event in second_writer.attempts)
        assert second._service_start_ledger_error == \
            "service_start_receipt_mismatch"
        state = json.load(open(
            second._service_start_path, encoding="utf-8"))
        old = next(
            item for item in state["pending_events"]
            if item["count"] == 1)
        assert old["service_restart_deliveries"] == [row]
    finally:
        cd.health_drop.acknowledge_service_start_lane = original_ack
        if prior is None:
            os.environ.pop("WSL_DIAG_RESTART_LOOP_N", None)
        else:
            os.environ["WSL_DIAG_RESTART_LOOP_N"] = prior


def test_platform_storage_retention_probe():
    os.environ["WSL_DIAG_DIR_MAX_MB"] = "0.001"    # ~1 KB cap
    try:
        d = tempfile.mkdtemp(prefix="ph_ret_")
        for name in ("diag-20260719.jsonl", "diag-20260720.jsonl",
                     "diag-20260721.jsonl"):
            with open(os.path.join(d, name), "w") as f:
                f.write("x" * 4096)
        sink = JsonlSink(d, flush_n=1, today=lambda: "20260721")
        # Model the production linkage: once a replayer owns this JSONL, no
        # byte-cap retention may delete data without cursor proof.
        replayer = OutboxReplayer(d, "http://unused", sink=sink)
        w = DiagWriter(sinks=[sink], enabled=True)
        w.outbox = replayer
        replayer._writer = w
        recorded = []
        original_emit = w.emit

        def record_emit(event):
            recorded.append(event)
            return original_emit(event)

        w.emit = record_emit
        ph = PlatformHealth([], w, dir_path=d)
        ph._poll_dir_retention()
        left = sorted(n for n in os.listdir(d) if n.endswith(".jsonl"))
        assert len(left) == 3
        assert sink.prune_deferred == 1

        # A validated cursor at the newest file makes only its predecessors
        # eligible and the coordinated cap probe can now prune them.
        assert replayer._save_cursor({
            "file": "diag-20260721.jsonl",
            "pos": 0,
        })
        ph._poll_dir_retention()
        left = sorted(n for n in os.listdir(d) if n.endswith(".jsonl"))
        assert left == ["diag-20260721.jsonl"]
        evs = [event for event in recorded
               if event.event_type == "diag_storage_pruned"]
        assert len(evs) == 1 and evs[0].detail["pruned"]
    finally:
        os.environ.pop("WSL_DIAG_DIR_MAX_MB", None)


def test_platform_writer_drop_promotion():
    class FakeStatsWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.fake = {"queue_drops": 0, "sinks": {}, "outbox": {}}

        def stats(self):
            return self.fake

    w = FakeStatsWriter()
    ph = PlatformHealth([], w, dir_path=tempfile.mkdtemp(prefix="ph_w_"))
    ph._poll_writer_drops()
    assert w.of_type("diag_drops") == []
    w.fake["queue_drops"] = 5
    ph._poll_writer_drops()
    assert len(w.of_type("diag_drops")) == 1
    w.fake["sinks"] = {"HttpSink": {"dropped": 2}}
    ph._poll_writer_drops()
    assert len(w.of_type("http_sink_drops")) == 1

    w.fake["sinks"]["JsonlSink"] = {
        "write_errors": 2,
        "retry_batches": 1,
        "prune_deferred": 3,
        "repaired_tails": 1,
    }
    w.fake["outbox"] = {
        "corrupt_rows": 1,
        "cursor_errors": 1,
        "cursor_resets": 1,
        "quarantine_errors": 1,
        "post_errors": 1,
        "repaired_tails": 1,
    }
    ph._poll_writer_drops()
    assert len(w.of_type("diag_storage_error")) >= 5
    assert len(w.of_type("diag_corrupt_row")) == 3
    # Polling unchanged cumulative counters must not duplicate events.
    count = len(w.events)
    ph._poll_writer_drops()
    assert len(w.events) == count


def test_platform_heartbeat_cadence_decoupled_from_poll():
    # R3-2 review fix: a quiet Track-B controller's ONLY liveness signal is the
    # lease-renewal heartbeat. If the run loop waited the (default 60 s) platform
    # poll period, the 20 s heartbeat guard could never fire more often than 60 s
    # and a single slow/failed POST pushed the next attempt past the 90 s lease
    # window -> false OFFLINE. The loop must WAKE at the heartbeat cadence while
    # the platform probes stay throttled at poll_s.
    import time
    d = tempfile.mkdtemp(prefix="ph_hb_")
    w = FakeWriter()
    ph = PlatformHealth([], w, poll_s=60.0, dir_path=d)   # slow platform poll
    ph._hb_url = "http://x:8766"                          # heartbeat enabled
    ph._hb_interval = 0.01                                # fast lease renewal
    hb = {"n": 0}
    plat = {"n": 0}
    ph._maybe_heartbeat = lambda: hb.__setitem__("n", hb["n"] + 1)
    ph._poll_disk = lambda: plat.__setitem__("n", plat["n"] + 1)
    ph.start()
    time.sleep(0.25)
    ph.stop(timeout=2.0)
    # A 60 s wait would give exactly ONE heartbeat in a 0.25 s window.
    assert hb["n"] >= 3, f"heartbeat ran only {hb['n']}x — loop still waits poll_s"
    # ...while the platform probes stay throttled to poll_s (run ~once).
    assert plat["n"] == 1, f"platform probes not throttled to poll_s (ran {plat['n']}x)"


def test_foreign_camera_health_is_typed_per_lane_and_recovers_once():
    d = tempfile.mkdtemp(prefix="ph_drop_")
    w = FakeWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21), FakeBoardIdentity(22)], w, dir_path=d)
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = (
        "21=scoring;22=scoring")
    try:
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21, 22]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        faults = w.of_type("camera_health")
        assert [(ev.lane_id, ev.severity, ev.code) for ev in faults] == [
            (21, "warn", "frozen"), (22, "warn", "frozen")]
        ph._ship_foreign_health()
        assert len(w.of_type("camera_health")) == 2

        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": True,
                "camera": {
                    "ok": True, "code": "healthy", "lanes": [21, 22]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        recovered = w.of_type("recovered")
        assert [(ev.lane_id, ev.code) for ev in recovered] == [
            (21, "camera_health"), (22, "camera_health")]
        ph._ship_foreign_health()
        assert len(w.of_type("recovered")) == 2
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_foreign_platform_storage_probe_failure_uses_typed_relay():
    directory = tempfile.mkdtemp(prefix="ph_drop_storage_probe_")
    writer = FakeWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21)], writer, dir_path=directory)
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": True, "code": "healthy", "lanes": [21]},
                "platform": {
                    "ok": False, "reasons": ["disk_probe_failed"]},
            })
        ph._ship_foreign_health()
        events = writer.of_type("diag_storage_error")
        assert len(events) == 1
        assert events[0].lane_id == 21
        assert events[0].code == "disk_probe"
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_foreign_relay_partial_acceptance_retries_only_rejected_lane():
    class PartialWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.reject_lane_22 = True
            self.attempts = []

        def emit(self, event):
            self.attempts.append(event)
            if event.lane_id == 22 and self.reject_lane_22:
                return False
            self.events.append(event)
            return True

    d = tempfile.mkdtemp(prefix="ph_drop_partial_")
    writer = PartialWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21), FakeBoardIdentity(22)], writer, dir_path=d)
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring;22=scoring"
    try:
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21, 22]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        assert [event.lane_id for event in writer.of_type(
            "camera_health")] == [21]
        assert len(ph._foreign_pending) == 1
        rejected = [
            event for event in writer.attempts
            if event.lane_id == 22][-1]

        writer.reject_lane_22 = False
        ph._ship_foreign_health()
        assert [event.lane_id for event in writer.of_type(
            "camera_health")] == [21, 22]
        retried = [
            event for event in writer.of_type("camera_health")
            if event.lane_id == 22][0]
        assert (retried.ts_utc, retried.ts_mono) == (
            rejected.ts_utc, rejected.ts_mono)
        assert ph._foreign_pending == {}
        ph._ship_foreign_health()
        assert len(writer.of_type("camera_health")) == 2
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_ambiguous_foreign_fault_completes_before_recovery():
    class ToggleWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.accept = False

        def emit(self, event):
            if not self.accept:
                return False
            self.events.append(event)
            return True

    directory = tempfile.mkdtemp(prefix="ph_drop_causal_")
    writer = ToggleWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21)], writer, dir_path=directory)
    ph._foreign_pending_max = 1
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        assert len(ph._foreign_pending) == 1

        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": True,
                "camera": {
                    "ok": True, "code": "healthy", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        # False from a durable API is ambiguous: the row may have fsynced just
        # before a timeout.  Keep the exact fault identity instead of canceling
        # it and risking an orphan server incident.
        assert len(ph._foreign_pending) == 1

        writer.accept = True
        ph._ship_foreign_health()
        assert len(writer.of_type("camera_health")) == 1
        assert len(writer.of_type("recovered")) == 1
        assert ph._foreign_pending == {}
        assert ph._foreign_delivered_active == set()
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_same_family_recurrence_replays_recovery_then_realert_across_restarts():
    import pytest

    accepted_rows = []
    attempt_rows = []

    class GateWriter(FakeWriter):
        def __init__(self, *, accept_alert, accept_recovery):
            super().__init__()
            self.accept_alert = accept_alert
            self.accept_recovery = accept_recovery

        def emit_durable(self, event, timeout=2.0):
            row = event.to_dict()
            attempt_rows.append(row)
            accepted = (
                self.accept_recovery
                if event.event_type == "recovered"
                else self.accept_alert)
            if accepted:
                self.events.append(event)
                accepted_rows.append(row)
            return accepted

    def write_camera(ph, *, ok, code):
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": ok,
                "camera": {
                    "ok": ok, "code": code, "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })

    def identity(row):
        return row["source_id"], row["boot_id"], row["seq"]

    directory = tempfile.mkdtemp(prefix="ph_drop_realert_wal_")
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        first_writer = GateWriter(
            accept_alert=True, accept_recovery=False)
        first = PlatformHealth(
            [FakeBoardIdentity(21)], first_writer, dir_path=directory)
        write_camera(first, ok=False, code="frozen")
        first._ship_foreign_health()
        assert [row["event_type"] for row in accepted_rows] == [
            "camera_health"]

        # The healthy transition is retained with its original identity after
        # an ambiguous durable timeout.
        write_camera(first, ok=True, code="healthy")
        first._ship_foreign_health()
        assert len(first._foreign_pending) == 1

        # The exact family recurs before that recovery is accepted. Its alert
        # must become a new WAL row *behind* the recovery, never be consumed by
        # planner dedupe or emitted ahead of the clear.
        write_camera(first, ok=False, code="frozen")
        first._ship_foreign_health()
        first_ledger = cd.health_drop.read_delivery_ledger(
            first._foreign_delivery_path,
            version=cd.FOREIGN_DELIVERY_LEDGER_VERSION)
        pending = sorted(
            first_ledger["pending"], key=lambda row: row["sequence"])
        assert [row["event"]["event_type"] for row in pending] == [
            "recovered", "camera_health"]
        recovery_row = pending[0]["diag_event"]
        realert_row = pending[1]["diag_event"]
        assert identity(recovery_row) != identity(realert_row)
        assert identity(accepted_rows[0]) != identity(realert_row)
        assert [
            row["event_type"] for row in accepted_rows
        ] == ["camera_health"]
        corrupt_terminal = json.loads(json.dumps(first_ledger))
        corrupt_terminal["pending"] = [pending[0]]
        with pytest.raises(
                ValueError, match="projected delivery state disagrees"):
            first._restore_foreign_delivery_payload(corrupt_terminal)

        # Restart after both obligations are fsynced. Accept only the recovery:
        # the ledger rewrite must retain the same re-alert identity and remain
        # valid even though delivered-active is temporarily empty.
        second_writer = GateWriter(
            accept_alert=False, accept_recovery=True)
        second = PlatformHealth(
            [FakeBoardIdentity(21)], second_writer, dir_path=directory)
        second._ship_foreign_health()
        assert [row["event_type"] for row in accepted_rows] == [
            "camera_health", "recovered"]
        assert identity(accepted_rows[1]) == identity(recovery_row)
        assert second._foreign_delivered_active == set()
        assert len(second._foreign_pending) == 1
        second_pending = next(iter(second._foreign_pending.values()))
        assert second_pending["event"]["event_type"] == "camera_health"
        assert identity(second_pending["diag_event"].to_dict()) == \
            identity(realert_row)

        # Restart at the second receipt boundary and replay only the re-alert.
        # Final state is active, with no pending clear and no false-green gap.
        third_writer = GateWriter(
            accept_alert=True, accept_recovery=True)
        third = PlatformHealth(
            [FakeBoardIdentity(21)], third_writer, dir_path=directory)
        third._ship_foreign_health()
        assert [row["event_type"] for row in accepted_rows] == [
            "camera_health", "recovered", "camera_health"]
        assert identity(accepted_rows[2]) == identity(realert_row)
        assert len({identity(row) for row in accepted_rows}) == 3
        assert third._foreign_pending == {}
        assert third._foreign_delivered_active == {
            (cd.SERVICE_CAMERA, "camera_health", "frozen", 21)}
        final_ledger = cd.health_drop.read_delivery_ledger(
            third._foreign_delivery_path,
            version=cd.FOREIGN_DELIVERY_LEDGER_VERSION)
        assert final_ledger["pending"] == []
        assert final_ledger["delivered_active"] == [{
            "service": cd.SERVICE_CAMERA,
            "event_type": "camera_health",
            "code": "frozen",
            "lane": 21,
        }]
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_same_family_wal_blocks_later_chain_after_first_failed_receipt():
    class RejectWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.attempts = []

        def emit_durable(self, event, timeout=2.0):
            self.attempts.append(event.to_dict())
            return False

    class DecisionWriter(FakeWriter):
        def __init__(self, decisions):
            super().__init__()
            self.decisions = list(decisions)
            self.attempts = []

        def emit_durable(self, event, timeout=2.0):
            self.attempts.append(event.to_dict())
            accepted = self.decisions.pop(0) \
                if self.decisions else False
            if accepted:
                self.events.append(event)
            return accepted

    def write_healthy(ph):
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": True,
                "camera": {
                    "ok": True, "code": "healthy", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })

    directory = tempfile.mkdtemp(prefix="ph_drop_realert_chain_")
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        first = PlatformHealth(
            [FakeBoardIdentity(21)], FakeWriter(), dir_path=directory)
        # No hand-off file is an explicit camera:missing availability fault.
        first._ship_foreign_health()
        reject = RejectWriter()
        first.writer = reject

        # Build four alternating obligations behind the delivered first alert:
        # R1, A2, R3, A4. Missing snapshots deliberately reuse snapshot_id
        # None, so local occurrence identity is load-bearing here.
        for healthy in (True, False, True, False):
            if healthy:
                write_healthy(first)
            else:
                os.remove(first._health_drop_path)
            first._ship_foreign_health()
        ledger = cd.health_drop.read_delivery_ledger(
            first._foreign_delivery_path,
            version=cd.FOREIGN_DELIVERY_LEDGER_VERSION)
        pending = sorted(
            ledger["pending"], key=lambda row: row["sequence"])
        assert [row["event"]["event_type"] for row in pending] == [
            "recovered", "health_drop_stale",
            "recovered", "health_drop_stale"]
        assert [
            row["event"]["detail"]["snapshot_id"]
            for row in (pending[1], pending[3])
        ] == [None, None]
        assert len({
            row["event"]["detail"]["relay_occurrence_id"]
            for row in pending
        }) == 4

        # Accept R1 but reject A2. R3/A4 must not be attempted merely because
        # their individual state guard happens to pass after R1.
        partial_writer = DecisionWriter([True, False, True, True])
        partial = PlatformHealth(
            [FakeBoardIdentity(21)], partial_writer, dir_path=directory)
        assert partial._ensure_foreign_delivery_loaded() is True
        assert partial._retry_foreign_pending() == 1
        assert [
            row["event_type"] for row in partial_writer.attempts
        ] == ["recovered", "health_drop_stale"]
        assert partial._foreign_delivered_active == set()
        assert len(partial._foreign_pending) == 3

        # A restart proves the post-R1/A2-failure ledger is self-consistent,
        # then finishes A2 -> R3 -> A4 in exact sequence.
        final_writer = FakeWriter()
        final = PlatformHealth(
            [FakeBoardIdentity(21)], final_writer, dir_path=directory)
        assert final._ensure_foreign_delivery_loaded() is True
        assert final._retry_foreign_pending() == 3
        assert [event.event_type for event in final_writer.events] == [
            "health_drop_stale", "recovered", "health_drop_stale"]
        assert final._foreign_pending == {}
        assert final._foreign_delivered_active == {
            (cd.SERVICE_CAMERA, "health_drop_stale",
             f"{cd.SERVICE_CAMERA}:missing", 21)}
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_foreign_delivered_fault_survives_restart_and_recovers_causally():
    class DurableWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.durable_attempts = []

        def emit_durable(self, event):
            self.durable_attempts.append(event)
            self.events.append(event)
            return True

    directory = tempfile.mkdtemp(prefix="ph_drop_restart_delivered_")
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        first_writer = DurableWriter()
        first = PlatformHealth(
            [FakeBoardIdentity(21)], first_writer, dir_path=directory)
        assert cd.health_drop.write_drop(
            first._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        first._ship_foreign_health()
        assert len(first_writer.of_type("camera_health")) == 1
        assert os.path.exists(first._foreign_delivery_path)

        # A new process sees only a fresh healthy source snapshot. Its durable
        # ledger must preserve the earlier delivered-active condition so this
        # recovery is emitted instead of leaving the server incident orphaned.
        second_writer = DurableWriter()
        second = PlatformHealth(
            [FakeBoardIdentity(21)], second_writer, dir_path=directory)
        assert cd.health_drop.write_drop(
            second._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": True,
                "camera": {
                    "ok": True, "code": "healthy", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        second._ship_foreign_health()
        recovered = second_writer.of_type("recovered")
        assert len(recovered) == 1
        assert recovered[0].lane_id == 21
        assert recovered[0].detail["recovered_event_type"] == "camera_health"
        assert recovered[0].detail["recovered_code"] == "frozen"
        assert second._foreign_delivered_active == set()
        ledger = cd.health_drop.read_delivery_ledger(
            second._foreign_delivery_path)
        assert ledger["delivered_active"] == []
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_foreign_ambiguous_fault_survives_restart_then_recovers():
    class RejectWriter(FakeWriter):
        def emit(self, _event):
            return False

    directory = tempfile.mkdtemp(prefix="ph_drop_restart_rejected_")
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        first = PlatformHealth(
            [FakeBoardIdentity(21)], RejectWriter(), dir_path=directory)
        assert cd.health_drop.write_drop(
            first._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        first._ship_foreign_health()
        assert len(first._foreign_pending) == 1

        writer = FakeWriter()
        second = PlatformHealth(
            [FakeBoardIdentity(21)], writer, dir_path=directory)
        assert cd.health_drop.write_drop(
            second._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": True,
                "camera": {
                    "ok": True, "code": "healthy", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        second._ship_foreign_health()
        assert len(writer.of_type("camera_health")) == 1
        assert len(writer.of_type("recovered")) == 1
        assert second._foreign_pending == {}
        assert second._foreign_delivered_active == set()
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_foreign_wal_replays_the_same_identity_after_ambiguous_timeout():
    class AmbiguousWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.attempt_rows = []
            self.reject_first = True

        def emit_durable(self, event, timeout=2.0):
            self.attempt_rows.append(event.to_dict())
            if self.reject_first:
                self.reject_first = False
                return False
            self.events.append(event)
            return True

    directory = tempfile.mkdtemp(prefix="ph_drop_wal_identity_")
    writer = AmbiguousWriter()
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        first = PlatformHealth(
            [FakeBoardIdentity(21)], writer, dir_path=directory)
        assert cd.health_drop.write_drop(
            first._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        first._ship_foreign_health()
        assert len(writer.attempt_rows) == 1
        ledger = cd.health_drop.read_delivery_ledger(
            first._foreign_delivery_path,
            version=cd.FOREIGN_DELIVERY_LEDGER_VERSION)
        saved = ledger["pending"][0]["diag_event"]
        assert set(("source_id", "boot_id", "seq")) <= set(saved)

        # Simulate a process restart after the durable sink may have fsynced but
        # returned a timeout. The same identity is replayed, then cleared.
        second = PlatformHealth(
            [FakeBoardIdentity(21)], writer, dir_path=directory)
        assert cd.health_drop.write_drop(
            second._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": True,
                "camera": {
                    "ok": True, "code": "healthy", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        second._ship_foreign_health()
        identity = lambda row: (
            row["source_id"], row["boot_id"], row["seq"])
        assert identity(writer.attempt_rows[0]) == \
            identity(writer.attempt_rows[1]) == identity(saved)
        assert writer.attempt_rows[0]["event_type"] == "camera_health"
        assert writer.attempt_rows[1]["event_type"] == "camera_health"
        assert writer.attempt_rows[2]["event_type"] == "recovered"
        assert identity(writer.attempt_rows[2]) != identity(saved)
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_foreign_planner_does_not_consume_two_lane_fault_when_wal_is_full():
    class ToggleDurableWriter(FakeWriter):
        def __init__(self):
            super().__init__()
            self.accept = False
            self.attempts = []

        def emit_durable(self, event, timeout=2.0):
            self.attempts.append(event)
            if not self.accept:
                return False
            self.events.append(event)
            return True

    directory = tempfile.mkdtemp(prefix="ph_drop_wal_capacity_")
    writer = ToggleDurableWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21), FakeBoardIdentity(22)],
        writer, dir_path=directory)
    ph._foreign_pending_max = 1
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = \
        "21=scoring;22=scoring"
    try:
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21, 22]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        assert ph._foreign_pending == {}
        assert ph._last_foreign_status == {}
        assert writer.attempts == []
        assert ph._foreign_pending_drops == 1

        # Once capacity is available, the unchanged source fingerprint must
        # still plan and deliver both lanes.
        ph._foreign_pending_max = 2
        writer.accept = True
        ph._ship_foreign_health()
        assert [event.lane_id for event in writer.of_type(
            "camera_health")] == [21, 22]
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_foreign_relay_never_uses_a_volatile_only_writer():
    class VolatileOnlyWriter:
        def __init__(self):
            self.calls = []

        def emit(self, event):
            self.calls.append(event)
            return True

    directory = tempfile.mkdtemp(prefix="ph_drop_no_durable_")
    writer = VolatileOnlyWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21)], writer, dir_path=directory)
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        assert writer.calls == []
        assert len(ph._foreign_pending) == 1
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_delivery_ledger_reader_rejects_oversize_and_deep_documents():
    directory = tempfile.mkdtemp(prefix="ph_drop_ledger_bounds_")
    path = os.path.join(directory, "delivery.json")
    with open(path, "w", encoding="utf-8") as target:
        target.write(" " * (cd.health_drop.DELIVERY_LEDGER_MAX_BYTES + 1))
    assert cd.health_drop.read_delivery_ledger(path) is None

    nested = {"version": 1}
    cursor = nested
    for _ in range(cd.health_drop.DELIVERY_LEDGER_MAX_DEPTH + 1):
        cursor["child"] = {}
        cursor = cursor["child"]
    assert cd.health_drop.write_delivery_ledger(path, nested) is False


def test_foreign_recovery_null_code_cannot_clear_a_coded_fault():
    import pytest

    directory = tempfile.mkdtemp(prefix="ph_drop_exact_family_")
    ph = PlatformHealth(
        [FakeBoardIdentity(21)], FakeWriter(), dir_path=directory)
    recovery = {
        "severity": "info",
        "event_type": "recovered",
        "code": "camera_health",
        "lanes": [21],
        "detail": {
            "from_service": cd.SERVICE_CAMERA,
            "status": "fresh",
            "snapshot_id": "fresh",
            "relay_only": True,
            "recovered_event_type": "camera_health",
            "recovered_code": None,
        },
    }
    prepared = cd._PreparedRelayEvent.from_event(cd.make_event(
        21, "info", "recovered", code="camera_health",
        detail=recovery["detail"]))
    payload = {
        "version": cd.FOREIGN_DELIVERY_LEDGER_VERSION,
        "last_foreign_status": [{
            "service": cd.SERVICE_CAMERA,
            "fingerprint": ["fresh", "fresh"],
            "status": "fresh",
            "active": [],
        }],
        "delivered_active": [{
            "service": cd.SERVICE_CAMERA,
            "event_type": "camera_health",
            "code": "frozen",
            "lane": 21,
        }],
        "pending": [{
            "service": cd.SERVICE_CAMERA,
            "event": recovery,
            "lane": 21,
            "diag_event": prepared.to_dict(),
            "sequence": 1,
        }],
        "pending_drops": 0,
        "pending_drops_reported": 0,
    }
    with pytest.raises(ValueError, match="lacks a causal alert"):
        ph._restore_foreign_delivery_payload(payload)


def test_invalid_foreign_delivery_ledger_blocks_relay_and_marks_health():
    directory = tempfile.mkdtemp(prefix="ph_drop_bad_ledger_")
    writer = FakeWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21)], writer, dir_path=directory)
    assert cd.health_drop.write_delivery_ledger(
        ph._foreign_delivery_path, {
            "version": cd.FOREIGN_DELIVERY_LEDGER_VERSION,
            "last_foreign_status": "not-a-list",
        })
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = "21=scoring"
    try:
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        assert writer.events == []
        assert ph._foreign_delivery_blocked is True
        snapshot = ph._current_platform_snapshot()
        assert snapshot["ok"] is False
        assert "foreign_delivery_ledger_error" in snapshot["reasons"]
        assert snapshot["foreign_delivery_ledger_error"] == "load_invalid"
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


def test_dormant_foreign_service_is_not_reported_as_a_live_fault():
    d = tempfile.mkdtemp(prefix="ph_drop_dormant_")
    w = FakeWriter()
    ph = PlatformHealth(
        [FakeBoardIdentity(21), FakeBoardIdentity(22)], w, dir_path=d)
    old_required = os.environ.get("WSL_PHASE8_REQUIRED_SERVICES")
    os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = (
        "21=controller;22=controller")
    try:
        assert cd.health_drop.write_drop(
            ph._health_drop_path, cd.SERVICE_CAMERA, {
                "ok": False,
                "camera": {
                    "ok": False, "code": "frozen", "lanes": [21, 22]},
                "platform": {"ok": True, "reasons": []},
            })
        ph._ship_foreign_health()
        assert w.of_type("camera_health") == []
        assert w.of_type("health_drop_stale") == []
    finally:
        if old_required is None:
            os.environ.pop("WSL_PHASE8_REQUIRED_SERVICES", None)
        else:
            os.environ["WSL_PHASE8_REQUIRED_SERVICES"] = old_required


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    fails = 0
    for name, fn in fns:
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            fails += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
