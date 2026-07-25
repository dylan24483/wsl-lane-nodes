"""Focused regressions for fail-closed identity and UNKNOWN sensor semantics."""
import builtins
import hashlib
import json
import os
import subprocess
import sys
import threading
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "lane_node")))

import controller_daemon as cd
import controller_io as cio
from controller_daemon import (
    BallReturnTracker, BoardConfig, BoardController, LaneDiag, PlatformHealth)
from cycle_control_8270 import State
from identity_evidence import (
    ControllerOwnerLease, ControllerOwnerLeaseError)
from rp2040_link import IDENTITY_RETRY_S, RP2040Link


BUILD = "release-3024346"
CFG = "73b2c779"
UID = "E66038B713952A31"


class FakeWriter:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)
        return True

    def emit_durable(self, event, timeout=2.0):
        return self.emit(event)

    def of_type(self, event_type):
        return [e for e in self.events if e.event_type == event_type]


def _revd_board(*, writer=None, control_loop_clock=None):
    cfg = BoardConfig(
        21, 1, "sim", 0, 0, board_rev="revD",
        allowed_fw_builds=(BUILD,), allowed_fw_cfgs=(CFG,),
        qualified_fw_releases=(("revD", BUILD, CFG),),
        supported_fw_board_revisions=("revD",),
        expected_uid=UID)
    return BoardController(
        cfg, sim=True, slow_debounce_n=1, diag_writer=writer,
        control_loop_clock=control_loop_clock)


def _legacy_board(*, fsm_debounce_n=1, writer=None):
    return BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev="revC",
            allow_legacy_revc_no_identity=True,
            legacy_revc_no_identity_enrolled=True),
        sim=True, slow_debounce_n=1, fsm_debounce_n=fsm_debounce_n,
        diag_writer=writer)


def _id_line(*, bn=7, build=BUILD, cfg=CFG, uid=UID, fi1=0,
              pcb="revD", rid=1):
    return json.dumps({
        "ev": "id", "fw": "phase8b-rp2040 v1.2.3", "bn": bn,
        "pcb": pcb, "rid": rid, "uid": uid, "build": build,
        "cfg": cfg, "fi1": fi1, "t": 100,
    })


def _modern_hb(*, up=1, bn=7, rid=1, **changes):
    body = {
        "ev": "hb", "ok": 1, "flt": "", "up": up, "drp": 0,
        "in": 0, "run": 0, "tap": 13, "rd": 0, "ep": 1,
        "v5": 5000, "v5n": 4990, "v5x": 5010, "rid": rid, "bn": bn,
    }
    body.update(changes)
    return json.dumps(body)


def test_uid_lane_mapping_rejects_duplicates():
    try:
        cd._parse_lane_values("21=AAA,21=BBB")
        raise AssertionError("duplicate lane UID mapping was accepted")
    except ValueError as exc:
        assert "duplicate lane 21" in str(exc)


def test_heartbeat_ack_must_echo_committed_controller_progress(
        tmp_path, monkeypatch):
    platform = PlatformHealth([], FakeWriter(), dir_path=str(tmp_path))
    platform._hb_url = "http://server"
    body = {
        "lane_id": 21,
        "heartbeat_seq": 7,
        "control_loop_seq": 99,
    }

    class Response:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(self.payload).encode()

    import urllib.request
    good = {
        "ok": True,
        "committed": True,
        "lane": 21,
        "last_seen": "2026-07-23T00:00:00+00:00",
        "heartbeat_seq": 7,
        "control_loop_seq": 99,
    }
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda _req, timeout=None: Response(good))
    platform._post_heartbeat(body)

    bad = dict(good, heartbeat_seq=6)
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda _req, timeout=None: Response(bad))
    with pytest.raises(RuntimeError, match="durably acknowledged"):
        platform._post_heartbeat(body)


def _to_ready(board, *, bn=7):
    hb = {"ev": "hb", "ok": 1, "flt": "", "up": 100}
    if bn is not None:
        hb = json.loads(_modern_hb(up=100, bn=bn))
    board.link.feed_line(json.dumps(hb))
    board.tick()
    board.io.slow["PBZ"] = True
    board.tick()
    board.io.slow["PBZ"] = False
    hb["up"] = 200
    board.link.feed_line(json.dumps(hb))
    board.tick()
    assert board.fsm.state is State.READY


def test_revd_prearm_inhibit_discards_ball_and_requires_fresh_pbz_after_recovery():
    board = _revd_board()
    board.link.feed_line(_modern_hb(up=100))
    board.tick()
    assert board.io.armed is False
    assert board._identity_arm_ok() == (False, "identity_not_received")

    # PBZ and motion edges received during the inhibit are sampled/drained but
    # cannot move the FSM or bank a live output command.
    board.io.slow["PBZ"] = True
    board.link.feed_line('{"ev":"ball","src":"DIELL_L","t":110}')
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))

    # Identity recovery alone — even with the pre-recovery PBZ still held —
    # stays disarmed. The input must be released and pressed again.
    board.link.feed_line(_id_line())
    board.tick()
    assert board.link.identity_ok() is True
    assert board._identity_arm_ok() == (True, None)
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    board.io.slow["PBZ"] = False
    board.tick()
    board.io.slow["PBZ"] = True
    board.tick()
    assert board.fsm.state is State.READY
    assert board.io.armed is True


def test_midcycle_identity_failure_hard_trips_latent_motion_and_needs_pbz():
    writer = FakeWriter()
    board = _revd_board(writer=writer)
    board.link.feed_line(_id_line())
    _to_ready(board)
    assert board.io.armed is True

    board.link.feed_line('{"ev":"ball","src":"DIELL_L","t":210}')
    board.tick()
    assert board.fsm.state is State.SWEEP_TO_GUARD
    assert board.io.outputs["sweep"] is True

    board.link.feed_line(_id_line(build="unapproved"))
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))
    invariant = [
        e for e in writer.of_type("fsm_fault")
        if e.code == "arm_inhibit_with_motion_latched"
    ]
    assert len(invariant) == 1
    assert invariant[0].detail["active_motion_latches"] == ["sweep"]
    assert invariant[0].detail["arm_precondition"] == \
        "identity_qualified_release_not_allowed"

    board.link.feed_line(_id_line())
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False
    board.io.slow["PBZ"] = True
    board.tick()
    assert board.fsm.state is State.READY
    assert board.io.armed is True


def test_revd_identity_enforces_nonce_fields_allowlists_and_uid():
    board = _revd_board()
    board.link.feed_line(_modern_hb())
    for line, expected_reason in (
        (json.dumps({"ev": "id", "fw": "x", "bn": 7, "pcb": "revD",
                     "rid": 1, "build": BUILD, "cfg": CFG, "fi1": 0}),
         "uid_missing"),
        (_id_line(build="other"), "qualified_release_not_allowed"),
        (_id_line(cfg="other"), "qualified_release_not_allowed"),
        (_id_line(uid="OTHER"), "uid_mismatch"),
        (_id_line(fi1=1), "fi1_image"),
        (_id_line(pcb="unknown", rid=255), "pcb_rev_mismatch"),
    ):
        board.link.feed_line(line)
        assert board._identity_arm_ok()[0] is False
        assert board._identity_arm_ok()[1] == expected_reason

    # A legacy identity with no per-boot nonce is visible diagnostically but
    # never satisfies the Rev-D ARM gate.
    legacy = json.loads(_id_line())
    legacy.pop("bn")
    board.link.feed_line(json.dumps(legacy))
    assert board.link.identity_status() == (False, "boot_nonce_missing")


def test_revd_arm_fails_closed_when_release_allowlists_are_unprovisioned(
        monkeypatch):
    monkeypatch.delenv("WSL_RP2040_BUILD_ALLOWLIST", raising=False)
    monkeypatch.delenv("WSL_RP2040_CFG_ALLOWLIST", raising=False)
    monkeypatch.delenv(cd.FW_QUALIFIED_RELEASES_ENV, raising=False)
    board = BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev="revD",
            supported_fw_board_revisions=("revD",)),
        sim=True, slow_debounce_n=1)
    board.link.feed_line(_modern_hb())
    board.link.feed_line(_id_line())
    assert board._identity_arm_ok() == (
        False, "qualified_release_policy_unconfigured")


def test_identity_bearing_revc_requires_supported_revision_and_allowlists():
    cfg = BoardConfig(
        21, 1, "sim", 0, 0, board_rev="revC",
        allowed_fw_builds=(BUILD,), allowed_fw_cfgs=(CFG,),
        qualified_fw_releases=(("revC", BUILD, CFG),),
        supported_fw_board_revisions=("revD",))
    board = BoardController(cfg, sim=True, slow_debounce_n=1)
    board.link.feed_line(_modern_hb(rid=255))
    board.link.feed_line(_id_line(pcb="unknown", rid=255))
    assert board._identity_arm_ok() == (
        False, "board_revision_not_supported")

    supported = BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev="revC",
            allowed_fw_builds=(BUILD,), allowed_fw_cfgs=(CFG,),
            qualified_fw_releases=(("revC", BUILD, CFG),),
            supported_fw_board_revisions=("revC",)),
        sim=True, slow_debounce_n=1)
    supported.link.feed_line(_modern_hb(rid=255))
    supported.link.feed_line(_id_line(pcb="unknown", rid=255))
    assert supported._identity_arm_ok() == (True, None)
    supported.link.feed_line(
        _id_line(pcb="unknown", rid=255, build="unapproved"))
    assert supported._identity_arm_ok() == (
        False, "qualified_release_not_allowed")


def test_truly_legacy_revc_without_identity_remains_explicitly_compatible():
    default_refused = BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev="revC"),
        sim=True, slow_debounce_n=1)
    default_refused.link.feed_line(
        '{"ev":"hb","ok":1,"flt":"","up":1}')
    assert default_refused._identity_arm_ok() == (
        False, "identity_not_received")

    board = BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev="revC",
            allow_legacy_revc_no_identity=True,
            legacy_revc_no_identity_enrolled=True),
        sim=True, slow_debounce_n=1)
    board.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    assert board.link.fw_identity() is None
    assert board._identity_arm_ok() == (True, None)


def test_midcycle_maxrun_failure_clears_motion_and_recovery_needs_pbz():
    writer = FakeWriter()
    board = BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev="revC",
            allow_legacy_revc_no_identity=True,
            legacy_revc_no_identity_enrolled=True),
        sim=True, slow_debounce_n=1, diag_writer=writer)
    with board.link._lock:
        board.link._maxrun_ms = 10_000
    _to_ready(board, bn=None)
    board.link.feed_line('{"ev":"ball","src":"DIELL_L","t":210}')
    board.tick()
    assert board.fsm.state is State.SWEEP_TO_GUARD
    assert board.io.outputs["sweep"] is True

    with board.link._lock:
        board.link._maxrun_ms = 1_000
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))
    invariant = [
        e for e in writer.of_type("fsm_fault")
        if e.code == "arm_inhibit_with_motion_latched"
    ]
    assert len(invariant) == 1
    assert invariant[0].detail["arm_precondition"] == "maxrun_desync"

    with board.link._lock:
        board.link._maxrun_ms = 10_000
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False
    board.io.slow["PBZ"] = True
    board.tick()
    assert board.fsm.state is State.READY
    assert board.io.armed is True


def test_health_recovery_ignores_pbz_held_during_outage():
    board = BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev="revC",
            allow_legacy_revc_no_identity=True,
            legacy_revc_no_identity_enrolled=True),
        sim=True, slow_debounce_n=1)
    _to_ready(board, bn=None)
    assert board.io.armed is True

    board.link.feed_line('{"ev":"rp_ok","v":0}')
    board.io.slow["PBZ"] = True
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False

    board.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":300}')
    board.tick()
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False

    board.io.slow["PBZ"] = False
    board.tick()
    board.io.slow["PBZ"] = True
    board.tick()
    assert board.fsm.state is State.READY
    assert board.io.armed is True


def test_pbz_release_latch_survives_debounce_and_input_read_exception():
    board = _legacy_board(fsm_debounce_n=3)
    board.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    board.tick()

    # Three stable asserted samples are required to enter READY.
    board.io.slow["PBZ"] = True
    for _ in range(3):
        board.tick()
    assert board.fsm.state is State.READY
    board.io.slow["PBZ"] = False
    for _ in range(3):
        board.tick()

    # A press held through inhibit/recovery reaches debounce-stable TRUE but
    # cannot dispatch while the explicit post-inhibit release latch is set.
    board.link.feed_line('{"ev":"rp_ok","v":0}')
    board.io.slow["PBZ"] = True
    board.tick()
    board.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":2}')
    board.tick()
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board._pbz_release_required is True

    # PBZ reads false, but a later watched-input exception makes the sample
    # incomplete. The release must not commit.
    board.io.slow["PBZ"] = False
    original_read = board.io.read_input

    def fail_after_pbz(name):
        if name == "PBC":
            raise OSError("injected watched-input read failure")
        return original_read(name)

    board.io.read_input = fail_after_pbz
    with pytest.raises(OSError, match="watched-input"):
        board.tick()
    assert board._pbz_release_required is True
    board.io.read_input = original_read

    # A complete debounce-stable release clears the latch; only a subsequent
    # stable press may re-arm.
    for _ in range(2):
        board.tick()
        assert board._pbz_release_required is True
    board.tick()
    assert board._pbz_release_required is False
    board.io.slow["PBZ"] = True
    for _ in range(2):
        board.tick()
        assert board.fsm.state is State.MANUAL_INTERVENTION
    board.tick()
    assert board.fsm.state is State.READY
    assert board.io.armed is True


def test_hard_safe_attempts_every_step_and_latches_daemon_fatal():
    board = _legacy_board()
    board._arm_state = True
    board._prev_arm = True
    order = []

    def fail(name):
        def action(*_args, **_kwargs):
            order.append(name)
            raise OSError(name)
        return action

    board.io.arm = fail("arm_low")
    board.link.stop_all = fail("firmware_stop_all")
    board.io.set_sweep = fail("sweep_off")
    board.io.set_table = fail("table_off")
    board.io.set_spot = fail("spot_off")
    board.fsm.power_restore = fail("fsm_relatch")

    class Watchdog:
        def off(self):
            order.append("watchdog_low")

    board._wdog = Watchdog()
    assert board._hard_safe("injected", raise_on_failure=False) is False
    assert order[0] == "arm_low"
    assert order[:6] == [
        "arm_low", "firmware_stop_all", "sweep_off", "table_off",
        "spot_off", "fsm_relatch"]
    assert order[-1] == "watchdog_low"
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board._pbz_release_required is True
    assert board._arm_state is True
    assert board.failed is True
    assert board.fatal is True


def test_run_exits_nonzero_promptly_when_hard_safe_is_incomplete(monkeypatch):
    board = _legacy_board()
    safe_off_calls = []

    def bad_tick():
        raise OSError("tick failed")

    def incomplete_safe(*_args, **_kwargs):
        board.failed = True
        board.fatal = True
        return False

    board.tick = bad_tick
    board._hard_safe = incomplete_safe
    board.safe_off = lambda: safe_off_calls.append(True)
    monkeypatch.setattr(cd.signal, "signal", lambda *_args: None)
    assert cd.run([board], hz=1000.0) == 1
    assert safe_off_calls == [True]


def test_control_transaction_serializes_identity_invalidation_and_dispatch():
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    board.link.feed_line('{"ev":"ball","src":"DIELL_L","t":210}')

    dispatch_entered = threading.Event()
    release_dispatch = threading.Event()
    update_started = threading.Event()
    update_done = threading.Event()
    errors = []
    original_observer = board._edge_observer

    def blocking_observer(*args):
        dispatch_entered.set()
        if not release_dispatch.wait(2.0):
            raise AssertionError("test did not release dispatch")
        original_observer(*args)

    board._edge_observer = blocking_observer

    def tick():
        try:
            board.tick()
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def invalidate():
        update_started.set()
        board.link.feed_line(_id_line(build="unapproved"))
        board.link.feed_line('{"ev":"cam","id":"SB","e":"f","t":220}')
        update_done.set()

    tick_thread = threading.Thread(target=tick)
    tick_thread.start()
    assert dispatch_entered.wait(2.0)
    update_thread = threading.Thread(target=invalidate)
    update_thread.start()
    assert update_started.wait(1.0)
    assert update_done.wait(0.05) is False

    release_dispatch.set()
    tick_thread.join(2.0)
    update_thread.join(2.0)
    assert not errors
    assert not tick_thread.is_alive()
    assert not update_thread.is_alive()
    assert update_done.is_set()

    # The invalidation linearizes after the completed tick. Before any queued
    # event can dispatch again, the next transaction sees it and hard-safes.
    board.tick()
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))


def test_identity_protocol_seen_permanently_closes_legacy_fallback():
    board = _legacy_board()
    board.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    assert board._identity_arm_ok() == (True, None)

    board.link.feed_line(_id_line(pcb="unknown", rid=255))
    assert board.link.identity_protocol_seen() is True
    # Firmware reboot/cache invalidation removes the current ID but cannot
    # erase the process-lifetime protocol observation.
    board.link.feed_line('{"ev":"boot","fw":"old","maxrun_ms":8000}')
    assert board.link.fw_identity() is None
    assert board.link.identity_protocol_seen() is True
    assert board._identity_arm_ok() == (
        False, "identity_protocol_required")


def test_modern_partial_heartbeat_invalidates_current_sample_and_liveness():
    board = _revd_board()
    board.link.feed_line(_modern_hb(up=100))
    board.link.feed_line(_id_line())
    board.tick()
    assert board.link.health_ok() is True
    assert board.link.tap_levels()["ARM"] is True
    platform = PlatformHealth([board], FakeWriter())
    platform._hb_url = "http://example.invalid"
    platform._hb_interval = 0
    sent = []
    platform._post_heartbeat = lambda body: sent.append(body)
    platform._maybe_heartbeat()
    assert len(sent) == 1
    before = board.link.parse_health()["parse_errors"]

    # This was the round-5 stale-cache repro: the old parser renewed liveness
    # while retaining RID/taps/run/input/V5 from the prior complete sample.
    board.link.feed_line(
        '{"ev":"hb","ok":1,"flt":"","up":101,"bn":7}')

    assert board.link.parse_health()["parse_errors"] == before + 1
    assert board.link.heartbeat_sample() is None
    assert board.link.health_ok() is False
    assert board.link.tap_levels() is None
    assert board.link.input_levels() is None
    assert board.link.running_motors() is None
    assert board.link.pcb_rev_id() is None
    platform._maybe_heartbeat()
    assert len(sent) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.pop("drp"),
        lambda row: row.update(extra=1),
        lambda row: row.update(**{"in": 0x100}),
        lambda row: row.update(run=0x80),
        lambda row: row.update(tap=0x10),
        lambda row: row.update(rd=129),
        lambda row: row.update(ep=0),
        lambda row: row.update(rid=4),
        lambda row: row.update(v5=4980, v5n=4990, v5x=5010),
    ],
)
def test_modern_heartbeat_exact_schema_and_bounds_fail_closed(mutation):
    row = json.loads(_modern_hb())
    mutation(row)
    link = RP2040Link()
    link.feed_line(json.dumps(row))
    assert link.identity_protocol_seen() is True
    assert link.heartbeat_sample() is None
    assert link.health_ok() is False
    assert link.parse_health()["parse_errors"] == 1


def test_invalid_then_valid_heartbeat_before_tick_still_forces_rearm():
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    assert board.io.armed is True

    prior_discontinuity = \
        board.link.heartbeat_discontinuity_generation()
    board.link.feed_line(
        '{"ev":"hb","ok":1,"flt":"","up":201,"bn":7}')
    # A buffered good record may arrive before the 50 Hz loop gets CPU.
    board.link.feed_line(_modern_hb(up=202))
    assert board.link.health_ok() is True
    assert board.link.heartbeat_discontinuity_generation() == \
        prior_discontinuity + 1

    board.tick()
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))


def test_nonce_reboot_burst_before_tick_still_forces_rearm():
    writer = FakeWriter()
    board = _revd_board(writer=writer)
    board.link.feed_line(_id_line())
    _to_ready(board)
    assert board.io.armed is True
    prior_discontinuity = \
        board.link.heartbeat_discontinuity_generation()

    # The reader consumes an entire missed-boot recovery burst before the
    # controller gets CPU: changed nonce, matching current ID, then a later
    # clean heartbeat. Current health and identity are both green by tick time.
    board.link.feed_line(_modern_hb(up=1, bn=8))
    board.link.feed_line(_id_line(bn=8))
    board.link.feed_line(_modern_hb(up=2, bn=8))
    assert board.link.health_ok() is True
    assert board._identity_arm_ok() == (True, None)
    # Nonce change + uptime regression are one reboot/sample, not two.
    assert board.link.heartbeat_discontinuity_generation() == \
        prior_discontinuity + 1

    board.tick()
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))
    assert len(writer.of_type("fw_reboot")) == 1


def test_id_nonce_reboot_burst_before_tick_still_forces_rearm():
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    prior_discontinuity = \
        board.link.heartbeat_discontinuity_generation()

    # The first record exposing the new boot nonce may be ID rather than HB.
    # A matching clean heartbeat can make every current field green before
    # tick(); the monotonic discontinuity must still preserve the reboot.
    board.link.feed_line(_id_line(bn=8))
    board.link.feed_line(_modern_hb(up=2, bn=8))
    assert board.link.health_ok() is True
    assert board._identity_arm_ok() == (True, None)
    assert board.link.heartbeat_discontinuity_generation() == \
        prior_discontinuity + 1

    board.tick()
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION


def test_legacy_uptime_reboot_burst_before_tick_still_forces_rearm():
    board = _legacy_board()
    _to_ready(board, bn=None)
    prior_discontinuity = \
        board.link.heartbeat_discontinuity_generation()

    board.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    board.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":2}')
    assert board.link.health_ok() is True
    assert board.link.heartbeat_discontinuity_generation() == \
        prior_discontinuity + 1

    board.tick()
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION


def test_explicit_boot_burst_before_tick_still_forces_rearm():
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    prior_discontinuity = \
        board.link.heartbeat_discontinuity_generation()

    board.link.feed_line(json.dumps({
        "ev": "boot", "fw": "phase8b-rp2040 v1.2.3",
        "bn": 9, "rp_ok": 0, "wdt_reset": 0, "maxrun_ms": 8000,
    }))
    board.link.feed_line(_id_line(bn=9))
    board.link.feed_line(_modern_hb(up=2, bn=9))
    assert board.link.health_ok() is True
    assert board._identity_arm_ok() == (True, None)
    assert board.link.heartbeat_discontinuity_generation() == \
        prior_discontinuity + 1

    board.tick()
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION


def test_fresh_reader_heartbeat_cannot_erase_control_loop_gap():
    loop_clock = {"t": 0.0}
    writer = FakeWriter()
    board = _revd_board(
        writer=writer, control_loop_clock=lambda: loop_clock["t"])
    board.link.feed_line(_id_line())
    _to_ready(board)
    assert board.io.armed is True

    # No controller tick completes for far longer than the one-second software
    # continuity bound. The RP2040 reader then receives a perfectly current
    # heartbeat before the main controller thread resumes.
    board.io.advance(cd.CONTROL_LOOP_GAP_MAX_S + 0.25)
    loop_clock["t"] += cd.CONTROL_LOOP_GAP_MAX_S + 0.25
    assert board.link.health_ok() is False
    board.link.feed_line(_modern_hb(up=2000))
    assert board.link.health_ok() is True

    board.tick()
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board._control_loop_gap_latched is False
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))
    gap_events = [
        event for event in writer.of_type("rail_drop")
        if event.code == "controller_loop_gap"
    ]
    assert len(gap_events) == 1
    assert gap_events[0].severity == "fault"
    assert gap_events[0].detail["continuity"]["reason"] == \
        "completion_gap_exceeded"

    # A PBZ already pressed before the mandatory safe recovery sample is
    # discarded. Only a release observed after the trip plus a later fresh
    # press may return READY and reassert ARM.
    board.io.slow["PBZ"] = True
    board.tick()
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False
    board.io.slow["PBZ"] = False
    board.tick()
    board.io.slow["PBZ"] = True
    board.tick()
    assert board.fsm.state is State.READY
    assert board.io.armed is True


def test_fresh_heartbeat_after_prelock_stall_cannot_get_one_positive_tick():
    loop_clock = {"t": 0.0}
    board = _revd_board(control_loop_clock=lambda: loop_clock["t"])
    board.link.feed_line(_id_line())
    _to_ready(board)
    assert board.io.armed is True

    original_transaction = board.link.control_transaction

    @contextmanager
    def delayed_transaction():
        # tick() has already taken its first continuity sample. Model the
        # controller blocking on the link lock while the reader completes a
        # fresh heartbeat immediately before releasing it.
        delay = cd.CONTROL_LOOP_GAP_MAX_S + 0.25
        loop_clock["t"] += delay
        board.io.advance(delay)
        board.link.feed_line(_modern_hb(up=3000))
        with original_transaction() as events:
            yield events

    board.link.control_transaction = delayed_transaction
    board.tick()

    # The same resumed tick must consume the post-lock continuity latch before
    # event dispatch, ARM assertion, or motor-on. The already-disarmed
    # inhibited path may continue its deliberate safe-state watchdog service.
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board.io.armed is False
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))


def test_identity_capability_evidence_survives_daemon_restart(
        tmp_path, monkeypatch):
    monkeypatch.setenv(cd.IDENTITY_STATE_DIR_ENV, str(tmp_path))
    first = _legacy_board()
    assert first.link.identity_protocol_seen() is False
    first.link.feed_line(_id_line(pcb="unknown", rid=255))
    assert first.link.identity_protocol_seen() is True

    state_path = tmp_path / "identity-capability-lane-21.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {
        "schema_version": 1,
        "lane_id": 21,
        "identity_capable": True,
        "generation": 1,
    }

    restarted = _legacy_board()
    assert restarted.link.identity_protocol_seen() is True
    restarted.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":200}')
    assert restarted.link.health_ok() is False
    assert restarted._identity_arm_ok() == (
        False, "identity_protocol_required")


def test_corrupt_identity_capability_state_refuses_board_startup(
        tmp_path, monkeypatch):
    monkeypatch.setenv(cd.IDENTITY_STATE_DIR_ENV, str(tmp_path))
    first = _legacy_board()
    state_path = Path(first._identity_store.path)
    state_path.write_text('{"schema_version":', encoding="utf-8")

    with pytest.raises(RuntimeError, match="unreadable or corrupt"):
        _legacy_board()


@pytest.mark.parametrize("bad_path", ["", " relative", "relative"])
def test_identity_state_directory_requires_exact_absolute_path(
        bad_path, monkeypatch):
    monkeypatch.setenv(cd.IDENTITY_STATE_DIR_ENV, bad_path)
    with pytest.raises(ValueError, match="exact non-empty absolute path"):
        _legacy_board()


def test_live_identity_state_directory_is_pinned_to_systemd_path(
        tmp_path, monkeypatch):
    monkeypatch.setenv(cd.IDENTITY_STATE_DIR_ENV, str(tmp_path))
    with pytest.raises(ValueError, match="fixed to.*LIVE mode"):
        cd._identity_state_dir(sim=False, shadow=False)

    monkeypatch.setenv(
        cd.IDENTITY_STATE_DIR_ENV, cd.DEFAULT_IDENTITY_STATE_DIR)
    assert cd._identity_state_dir(sim=False, shadow=False) == \
        cd.DEFAULT_IDENTITY_STATE_DIR


def test_custom_identity_state_directory_is_bench_only(
        tmp_path, monkeypatch):
    custom = str(tmp_path)
    monkeypatch.setenv(cd.IDENTITY_STATE_DIR_ENV, custom)
    assert cd._identity_state_dir(sim=True, shadow=False) == custom
    assert cd._identity_state_dir(sim=False, shadow=True) == custom


def test_physical_controller_owner_lease_precedes_hardware_import(
        tmp_path, monkeypatch):
    monkeypatch.setenv(cd.IDENTITY_STATE_DIR_ENV, str(tmp_path))
    original_import = builtins.__import__
    observed = {"contended": False}

    def import_gate(name, *args, **kwargs):
        if name == "gpiozero":
            contender = ControllerOwnerLease(str(tmp_path), 21)
            with pytest.raises(ControllerOwnerLeaseError):
                contender.acquire()
            observed["contended"] = True
            raise RuntimeError("hardware-import-order-proven")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_gate)
    cfg = BoardConfig(21, 1, "/dev/never-opened", 12, 16,
                      board_rev="revC")
    with pytest.raises(RuntimeError, match="hardware-import-order-proven"):
        BoardController(cfg, sim=False, shadow=True)
    assert observed["contended"] is True


def test_simulation_does_not_take_physical_controller_owner_lease(
        tmp_path, monkeypatch):
    monkeypatch.setenv(cd.IDENTITY_STATE_DIR_ENV, str(tmp_path))
    first = _legacy_board()
    second = _legacy_board()
    assert first._controller_owner_lease is None
    assert second._controller_owner_lease is None


def test_midrun_safe_off_does_not_release_controller_owner_lease(tmp_path):
    board = _legacy_board()
    lease = ControllerOwnerLease(str(tmp_path), 21)
    lease.acquire()
    board._controller_owner_lease = lease
    try:
        board.safe_off()
        assert lease.acquired is True
        assert board._controller_owner_lease is lease
    finally:
        lease.release()


def test_controller_owner_lease_contends_and_is_crash_released(tmp_path):
    lane_node_dir = str(Path(cd.__file__).resolve().parent)
    child = (
        "import sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from identity_evidence import ControllerOwnerLease\n"
        "lease = ControllerOwnerLease(sys.argv[2], int(sys.argv[3]))\n"
        "lease.acquire()\n"
        "print('READY', flush=True)\n"
        "sys.stdin.buffer.read(1)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", child,
         lane_node_dir, str(tmp_path), "21"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    reacquired = None
    try:
        assert proc.stdout.readline().strip() == "READY"
        contender = ControllerOwnerLease(str(tmp_path), 21)
        with pytest.raises(ControllerOwnerLeaseError):
            contender.acquire()

        # Simulate an ungraceful daemon death. The OS, not application cleanup,
        # must release the lifetime lease.
        proc.kill()
        assert proc.wait(timeout=5) != 0
        reacquired = ControllerOwnerLease(str(tmp_path), 21)
        reacquired.acquire()
        assert reacquired.acquired is True
    finally:
        if reacquired is not None:
            reacquired.release()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_two_stale_identity_stores_cannot_overwrite_monotonic_true(tmp_path):
    first = cd.IdentityEvidenceStore(str(tmp_path), 21)
    delayed = cd.IdentityEvidenceStore(str(tmp_path), 21)
    assert first.load_or_initialize()["identity_capable"] is False
    assert delayed.load_or_initialize()["identity_capable"] is False

    assert first.mark_identity_capable()["generation"] == 1
    # This instance still has generation 0 cached. It must re-read/merge the
    # on-disk generation under the process lock, not issue any stale write.
    delayed._write = lambda _state: pytest.fail(
        "stale store attempted to overwrite monotonic true evidence")
    merged = delayed.mark_identity_capable()
    assert merged["identity_capable"] is True
    assert merged["generation"] == 1
    on_disk = json.loads(Path(first.path).read_text(encoding="utf-8"))
    assert on_disk["identity_capable"] is True
    assert on_disk["generation"] == 1


def test_two_store_first_initialization_is_serialized_without_false_clobber(
        tmp_path):
    first = cd.IdentityEvidenceStore(str(tmp_path), 21)
    second = cd.IdentityEvidenceStore(str(tmp_path), 21)
    entered_write = threading.Event()
    release_write = threading.Event()
    second_started = threading.Event()
    second_done = threading.Event()
    errors = []
    original_write = first._write

    def blocked_first_write(state):
        entered_write.set()
        if not release_write.wait(2.0):
            raise AssertionError("test did not release first state write")
        return original_write(state)

    first._write = blocked_first_write

    def initialize(store, *, started=None, done=None):
        try:
            if started is not None:
                started.set()
            store.load_or_initialize()
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            if done is not None:
                done.set()

    t1 = threading.Thread(target=initialize, args=(first,))
    t1.start()
    assert entered_write.wait(2.0)
    t2 = threading.Thread(
        target=initialize, args=(second,),
        kwargs={"started": second_started, "done": second_done})
    t2.start()
    assert second_started.wait(1.0)
    # The second instance cannot independently observe FileNotFound while the
    # first owns the cross-process read/modify/write lock.
    assert second_done.wait(0.1) is False
    release_write.set()
    t1.join(2.0)
    t2.join(2.0)
    assert not errors
    assert not t1.is_alive() and not t2.is_alive()
    assert first._state["generation"] == 0
    assert second._state["generation"] == 0
    assert json.loads(Path(first.path).read_text(
        encoding="utf-8"))["identity_capable"] is False


@pytest.mark.parametrize(
    "field,bad,reason",
    [
        ("fw", "", "fw_missing"),
        ("pcb", " revD", "pcb_missing"),
        ("uid", UID + " ", "uid_missing"),
        ("build", "\t" + BUILD, "build_missing"),
        ("cfg", CFG + "\x00", "cfg_missing"),
        ("build", "x" * 65, "build_missing"),
        ("uid", "é" + UID, "uid_missing"),
    ],
)
def test_identity_wire_strings_are_exact_ascii_not_trimmed_or_truncated(
        field, bad, reason):
    board = _revd_board()
    board.link.feed_line(_modern_hb())
    ident = json.loads(_id_line())
    ident[field] = bad
    board.link.feed_line(json.dumps(ident))

    assert board.link.fw_identity()[field] is None
    assert board._identity_arm_ok() == (False, reason)


@pytest.mark.parametrize(
    "modern_field",
    [{"bn": 7}, {"rid": 255}, {"bn": 7, "rid": 255}],
)
def test_modern_heartbeat_capability_cannot_fall_back_to_legacy(
        modern_field):
    board = _legacy_board()
    hb = {"ev": "hb", "ok": 1, "flt": "", "up": 1, **modern_field}
    board.link.feed_line(json.dumps(hb))
    assert board.link.fw_identity() is None
    assert board.link.identity_protocol_seen() is True
    assert board._identity_arm_ok() == (
        False, "identity_protocol_required")


def test_legacy_requires_exact_global_and_positive_lane_enrollment(monkeypatch):
    monkeypatch.setenv(cd.ALLOW_LEGACY_REVC_NO_IDENTITY_ENV, "1")
    monkeypatch.setenv(cd.LEGACY_REVC_NO_IDENTITY_LANES_ENV, "21")
    board = BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev="revC"),
        sim=True)
    assert board._identity_arm_ok() == (True, None)

    monkeypatch.setenv(cd.LEGACY_REVC_NO_IDENTITY_LANES_ENV, "22")
    not_enrolled = BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev="revC"),
        sim=True)
    assert not_enrolled._identity_arm_ok() == (
        False, "identity_not_received")

    monkeypatch.setenv(cd.LEGACY_REVC_NO_IDENTITY_LANES_ENV, "21")
    monkeypatch.setenv(cd.ALLOW_LEGACY_REVC_NO_IDENTITY_ENV, "0")
    refused = BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev="revC"),
        sim=True)
    assert refused._identity_arm_ok() == (
        False, "identity_not_received")

    monkeypatch.setenv(cd.ALLOW_LEGACY_REVC_NO_IDENTITY_ENV, "true")
    with pytest.raises(ValueError, match="exactly 0 or 1"):
        BoardController(
            BoardConfig(21, 1, "sim", 0, 0, board_rev="revC"),
            sim=True)

    monkeypatch.setenv(cd.ALLOW_LEGACY_REVC_NO_IDENTITY_ENV, "1")
    monkeypatch.setenv(cd.LEGACY_REVC_NO_IDENTITY_LANES_ENV, "21,21")
    with pytest.raises(ValueError, match="repeats lane 21"):
        BoardController(
            BoardConfig(21, 1, "sim", 0, 0, board_rev="revC"),
            sim=True)


def test_qualified_release_policy_rejects_allowlist_cross_product():
    board = BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev="revD",
            allowed_fw_builds=("build-a", "build-b"),
            allowed_fw_cfgs=("cfg-a", "cfg-b"),
            qualified_fw_releases=(
                ("revD", "build-a", "cfg-a"),
                ("revD", "build-b", "cfg-b")),
            supported_fw_board_revisions=("revD",)),
        sim=True)
    board.link.feed_line(_modern_hb())
    board.link.feed_line(
        _id_line(build="build-a", cfg="cfg-b"))
    assert board._identity_arm_ok() == (
        False, "qualified_release_not_allowed")


@pytest.mark.parametrize(
    "value",
    [
        "revD|build-only",
        "revD||cfg",
        "revD|build|cfg|extra",
        " revD|build|cfg",
        "revD|build|cfg,revD|build|cfg",
    ],
)
def test_qualified_release_env_rejects_malformed_entries(
        monkeypatch, value):
    monkeypatch.setenv(cd.FW_QUALIFIED_RELEASES_ENV, value)
    with pytest.raises(ValueError):
        BoardController(
            BoardConfig(21, 1, "sim", 0, 0, board_rev="revD"),
            sim=True)


@pytest.mark.parametrize(
    "live,shadow,expected",
    [
        ("1", None, "live"),
        (None, "1", "shadow"),
    ],
)
def test_output_mode_requires_one_exact_explicit_flag(
        monkeypatch, live, shadow, expected):
    monkeypatch.delenv(cd.EXPECTED_MODE_ENV, raising=False)
    for name, value in ((cd.LIVE_ENV, live), (cd.SHADOW_ENV, shadow)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert cd._controller_output_mode() == expected


@pytest.mark.parametrize(
    "live,shadow",
    [(None, None), ("1", "1"), ("true", None), (None, "yes")],
)
def test_output_mode_rejects_missing_conflicting_or_approximate_flags(
        monkeypatch, live, shadow):
    monkeypatch.delenv(cd.EXPECTED_MODE_ENV, raising=False)
    for name, value in ((cd.LIVE_ENV, live), (cd.SHADOW_ENV, shadow)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        cd._controller_output_mode()


@pytest.mark.parametrize("expected", ["shadow", "LIVE", " live"])
def test_expected_mode_must_be_exact_and_match_selected(
        monkeypatch, expected):
    monkeypatch.setenv(cd.LIVE_ENV, "1")
    monkeypatch.setenv(cd.SHADOW_ENV, "0")
    monkeypatch.setenv(cd.EXPECTED_MODE_ENV, expected)
    with pytest.raises(ValueError):
        cd._controller_output_mode()


def test_expected_mode_optional_match_is_accepted(monkeypatch):
    monkeypatch.setenv(cd.LIVE_ENV, "1")
    monkeypatch.setenv(cd.SHADOW_ENV, "0")
    monkeypatch.setenv(cd.EXPECTED_MODE_ENV, "live")
    assert cd._controller_output_mode() == "live"


def test_main_refuses_output_mode_before_opening_hardware(monkeypatch):
    monkeypatch.delenv(cd.LIVE_ENV, raising=False)
    monkeypatch.delenv(cd.SHADOW_ENV, raising=False)
    monkeypatch.delenv(cd.EXPECTED_MODE_ENV, raising=False)
    monkeypatch.setattr(
        cd, "_build_boards",
        lambda *_args, **_kwargs: pytest.fail("hardware construction reached"))
    assert cd.main([]) == 1


def test_main_refuses_unscoped_pair_aux_roles_before_opening_hardware(
        monkeypatch):
    monkeypatch.setenv(cd.LIVE_ENV, "0")
    monkeypatch.setenv(cd.SHADOW_ENV, "1")
    monkeypatch.setenv(cd.EXPECTED_MODE_ENV, "shadow")
    monkeypatch.setenv(cd.BOARD_REVS_ENV, "revD")
    monkeypatch.setenv(cd.AUX_ROLES_ENV, "aux3=dist_index")
    monkeypatch.delenv(
        f"{cd.AUX_ROLES_LANE_ENV_PREFIX}21", raising=False)
    monkeypatch.delenv(
        f"{cd.AUX_ROLES_LANE_ENV_PREFIX}22", raising=False)
    monkeypatch.setattr(
        cd, "_build_boards",
        lambda *_args, **_kwargs: pytest.fail("hardware construction reached"))
    assert cd.main([]) == 1


def test_service_restart_starts_identity_retry_state_immediately():
    clock = {"t": 0.0}
    link = RP2040Link(now=lambda: clock["t"])
    assert link.identity_status() == (False, "identity_not_received")
    link.poll_identity()
    assert list(link.sent) == ["ID"]
    result = None
    for n in range(1, 5):
        clock["t"] = n * (IDENTITY_RETRY_S + 0.1)
        result = link.poll_identity()
    assert result == "missing"
    assert link.identity_missing() is True


def test_nonce_change_invalidates_an_allowlisted_identity_before_arm():
    board = _revd_board()
    board.link.feed_line(_id_line(bn=10))
    _to_ready(board, bn=10)
    assert board.io.armed is True
    # Missed boot and non-regressing uptime: the changed heartbeat nonce alone
    # invalidates every cached identity fact and drops health/ARM.
    board.link.feed_line(_modern_hb(up=300, bn=11))
    assert board.link.fw_identity() is None
    board.tick()
    assert board.io.armed is False


def test_bank_unknown_invalidates_ball_return_timeout_until_fresh_ball():
    writer = FakeWriter()
    diag = LaneDiag(21, writer=writer, aux_roles={"AUX2": "exit_beam"})
    tracker = BallReturnTracker([21], timeout_s=10.0)
    diag.set_ball_tracker(tracker)

    diag.poll(0.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX2": False})
    diag.on_ball(0.0)
    diag.poll(1.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels=None)
    assert list(tracker._pending[21]) == []
    diag.poll(20.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels=None)
    assert writer.of_type("ball_return_missing") == []
    assert tracker.missing_total[21] == 0

    # Recovery is only a baseline; the old pending timer is gone. A full
    # timeout drains any ball that may return late from the blind interval.
    diag.poll(21.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX2": False})
    assert tracker._quarantine_until == 31.0
    diag.on_ball(30.0)
    assert list(tracker._pending[21]) == []
    diag.poll(40.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX2": False})
    assert writer.of_type("ball_return_missing") == []
    diag.on_ball(40.0)
    diag.poll(50.1, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX2": False})
    assert len(writer.of_type("ball_return_missing")) == 1


def test_missing_role_is_not_coerced_false_and_old_absence_is_canceled(
        monkeypatch):
    monkeypatch.setenv("WSL_DIAG_BE_WINDOW_S", "1")
    writer = FakeWriter()
    diag = LaneDiag(21, writer=writer, aux_roles={"AUX1": "be_current"})
    diag.poll(0.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX1": False})
    diag.on_ball(0.0)
    diag.note_cycle_complete(0.0)

    diag.poll(0.5, ready=True, in_motion=False,
              slow_levels={}, inb_levels={})
    diag.poll(10.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={})
    assert writer.of_type("be_no_current") == []
    assert len(writer.of_type("configured_role_missing")) == 1

    diag.poll(10.5, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX1": False})
    assert writer.of_type("be_no_current") == []
    recovered = [
        e for e in writer.of_type("recovered")
        if e.code == "configured_role_missing"]
    assert recovered
    assert recovered[0].detail["recovered_event_type"] == \
        "configured_role_missing"
    assert recovered[0].detail["recovered_code"] == "aux:AUX1"
    diag.poll(11.1, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX1": False})
    assert writer.of_type("be_no_current") == []

    # Only a fully observed post-recovery cycle creates a new current window.
    diag.on_ball(11.1)
    diag.note_cycle_complete(11.1)
    diag.poll(12.2, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX1": False})
    assert len(writer.of_type("be_no_current")) == 1


def test_heartbeat_proves_live_contract_and_control_loop_progress(monkeypatch):
    monkeypatch.delenv(cd.LIVE_ENV, raising=False)
    monkeypatch.delenv(cd.SHADOW_ENV, raising=False)
    board = BoardController(
        BoardConfig(
            21, 1, "sim", 0, 0, board_rev="revC",
            allow_legacy_revc_no_identity=True,
            legacy_revc_no_identity_enrolled=True),
        sim=True, slow_debounce_n=1)
    board.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    board.tick()
    assert board.control_loop_seq == 1

    platform = PlatformHealth([board], FakeWriter(), poll_s=60.0)
    platform._hb_url = "http://example.invalid"
    platform._hb_interval = 0
    sent = []
    platform._post_heartbeat = lambda body: sent.append(dict(body))
    platform._maybe_heartbeat()
    platform._maybe_heartbeat()

    assert [b["heartbeat_seq"] for b in sent] == [1, 2]
    assert {b["controller_boot_id"] for b in sent} == {
        cd._CONTROLLER_BOOT_ID}
    assert all(b["control_loop_seq"] == 1 for b in sent)
    assert all(b["contract_loaded"] is True for b in sent)
    contract = Path(cd.__file__).resolve().parent.parent / \
        "server" / "machine_contract.json"
    expected = hashlib.sha256(contract.read_bytes()).hexdigest()
    assert all(b["contract_sha256"] == expected for b in sent)
    assert all("serial_parse_errors" in b and "diag_record_drops" in b
               for b in sent)
    for body in sent:
        assert body["controller_mode"] == "live"
        assert body["live_outputs_acknowledged"] is False
        assert body["arm_state"] is False
        assert body["fsm_state"] == "manual_intervention"
        assert body["manual_rearm_required"] is True
        assert body["legacy_identity_mode"] is True
        assert body["identity_assurance"] == "legacy_unverified"
        assert body["arm_prerequisite_reason"] is None
        assert body["safety_taps"] == {
            "ne555": None,
            "wdog_kick": None,
            "arm_permit": None,
            "rp2040_ok": None,
        }


def test_verified_runtime_fields_and_safety_taps_reach_both_payloads(
        monkeypatch, tmp_path):
    monkeypatch.setenv(cd.LIVE_ENV, "1")
    monkeypatch.setenv(cd.SHADOW_ENV, "0")
    board = _revd_board()
    board.link.feed_line(_id_line())
    board.link.feed_line(_modern_hb(up=50))
    _to_ready(board)
    assert board.io.armed is True

    platform = PlatformHealth(
        [board], FakeWriter(), poll_s=60.0, dir_path=str(tmp_path))
    platform._hb_url = "http://example.invalid"
    platform._hb_interval = 0
    heartbeats = []
    platform._post_heartbeat = lambda body: heartbeats.append(dict(body))
    platform._maybe_heartbeat()

    drops = []
    monkeypatch.setattr(
        cd.health_drop, "write_drop",
        lambda path, service, payload: (
            drops.append((path, service, payload)) or True))
    platform._write_health_drop()

    assert len(heartbeats) == 1
    assert len(drops) == 1
    heartbeat = heartbeats[0]
    health_board = drops[0][2]["boards"][0]
    expected_runtime = {
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
            "wdog_kick": False,
            "arm_permit": True,
            "rp2040_ok": True,
        },
    }
    for key, value in expected_runtime.items():
        assert heartbeat[key] == value
        assert health_board[key] == value
    assert health_board["lane_id"] == 21
    assert health_board["board_rev"] == "revD"
    assert health_board["fw_build"] == BUILD
    assert health_board["fw_cfg"] == CFG
    assert health_board["identity_ok"] is True
    assert health_board["identity_reason"] is None
    assert "parse_errors" in health_board


def test_heartbeat_deadline_crossed_mid_tick_cannot_rekick_or_rearm():
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    assert board.io.armed is True
    prior_kicks = board.io.kicks
    original_read = board.io.read_input
    advanced = {"done": False}

    def slow_successful_read(name):
        if not advanced["done"]:
            advanced["done"] = True
            board.io.advance(2.0)
        return original_read(name)

    board.io.read_input = slow_successful_read
    with pytest.raises(cd.LinkFreshnessError):
        board.tick()

    assert board.link.health_ok() is False
    assert board.io.kicks == prior_kicks
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))


def test_post_arm_diagnostics_stall_cannot_return_with_expired_arm():
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    assert board.io.armed is True
    original_diag_poll = board._diag_poll

    def delayed_diag_poll(levels):
        result = original_diag_poll(levels)
        board.io.advance(2.0)
        return result

    board._diag_poll = delayed_diag_poll
    with pytest.raises(cd.LinkFreshnessError, match="tick_completion"):
        board.tick()
    assert board.link.health_ok() is False
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board._runtime_snapshot is None


def test_runtime_snapshot_stall_cannot_escape_final_freshness_check():
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    assert board.io.armed is True
    prior_seq = board.control_loop_seq
    original_commit = board._commit_runtime_snapshot

    def delayed_commit():
        board.io.advance(2.0)
        return original_commit()

    board._commit_runtime_snapshot = delayed_commit
    with pytest.raises(cd.LinkFreshnessError, match="tick_completion"):
        board.tick()
    assert board.link.health_ok() is False
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert board._runtime_snapshot is None
    assert board.control_loop_seq == prior_seq


def test_exact_heartbeat_freshness_remaining_is_sampled_atomically():
    clock = {"t": 10.0}
    link = RP2040Link(now=lambda: clock["t"], hb_timeout=1.0)
    assert link.heartbeat_freshness_remaining() is None
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    assert link.actuation_freshness_status() == (True, 1.0)

    clock["t"] += 0.375
    healthy, remaining = link.actuation_freshness_status()
    assert healthy is True
    assert remaining == pytest.approx(0.625)

    clock["t"] += 0.75
    healthy, remaining = link.actuation_freshness_status()
    assert healthy is False
    assert remaining == pytest.approx(-0.125)


def test_real_serial_constructor_sets_bounded_write_timeout(monkeypatch):
    captured = {}

    class FakeSerial:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            pass

    monkeypatch.setitem(
        sys.modules, "serial", types.SimpleNamespace(Serial=FakeSerial))
    link = RP2040Link(port="/dev/fake")
    try:
        assert captured["args"] == ("/dev/fake", 115200)
        assert captured["kwargs"]["timeout"] == 0.1
        assert captured["kwargs"]["write_timeout"] > 0.0
        assert captured["kwargs"]["write_timeout"] <= \
            cio.POSITIVE_ACTUATION_MAX_S
    finally:
        link.close()


def test_serial_tx_lock_wait_and_short_write_fail_closed():
    class ShortSerial:
        def write(self, payload):
            return len(payload) - 1

        def close(self):
            pass

    link = RP2040Link(serial_obj=ShortSerial())
    assert link._send("PING") is False
    assert link._send_fails == 1

    class NoneSerial(ShortSerial):
        def write(self, _payload):
            return None

    link._ser = NoneSerial()
    assert link._send("PING") is False
    assert link._send_fails == 2

    # A peer stalled in the transport mutex must consume only the bounded
    # acquisition timeout, then count as another send failure.
    assert link._tx_lock.acquire(blocking=False) is True
    try:
        assert link._send("PING") is False
    finally:
        link._tx_lock.release()
    assert link._send_fails == 3


@pytest.mark.parametrize("operation", ["motor", "arm", "watchdog"])
def test_positive_operation_requires_conservative_remaining_margin(operation):
    clock = {"t": 0.0}
    link = RP2040Link(now=lambda: clock["t"], hb_timeout=1.0)
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    base = cio.RecordingIO(now=lambda: clock["t"], rp2040=link)
    guarded = cio.FreshnessGuardIO(base, link)
    clock["t"] = 1.0 - (cio.POSITIVE_ACTUATION_MIN_REMAINING_S / 2.0)
    assert link.health_ok() is True

    with pytest.raises(cd.LinkFreshnessError, match="margin"):
        if operation == "motor":
            guarded.set_sweep(True)
        elif operation == "arm":
            guarded.arm(True)
        else:
            guarded.watchdog_kick()

    assert base.outputs.get("sweep") is not True
    assert base.armed is not True
    assert base.kicks == 0


def test_machineio_inner_i2c_boundary_recheck_refuses_delayed_positive():
    clock = {"t": 0.0}
    link = RP2040Link(now=lambda: clock["t"], hb_timeout=1.0)
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    physical_writes = []

    class DelayedOutput:
        def write_bit(self, port, bit, value, *, positive_guard=None):
            if value:
                # Delay after all MachineIO staging but before its final guard
                # at the bus-write boundary.
                clock["t"] = 1.0 - (
                    cio.POSITIVE_ACTUATION_MIN_REMAINING_S / 2.0)
                positive_guard()
            physical_writes.append((port, bit, bool(value)))

    machine = object.__new__(cio.MachineIO)
    machine.lane = 21
    machine._rp2040 = link
    machine._out_state = {}
    machine.recorder = cio.NULL_RECORDER
    machine.out_a = DelayedOutput()
    guarded = cio.FreshnessGuardIO(machine, link)

    with pytest.raises(cd.LinkFreshnessError, match="margin"):
        guarded.set_sweep(True)
    assert physical_writes == []
    assert machine._out_state == {}
    assert link.health_ok() is True


def test_uncertain_positive_i2c_write_is_rolled_back_and_trips_immediately():
    clock = {"t": 0.0}
    link = RP2040Link(now=lambda: clock["t"], hb_timeout=1.0)
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')

    class UncertainOutput:
        def __init__(self):
            self.state = False
            self.writes = []

        def write_bit(self, port, bit, value, *, positive_guard=None):
            if value and positive_guard is not None:
                positive_guard()
            self.state = bool(value)
            self.writes.append(bool(value))
            if value:
                # Models an OLAT write that reached hardware before readback
                # failed: software cannot call it successful or leave it ON.
                raise IOError("readback mismatch after physical write")

    machine = object.__new__(cio.MachineIO)
    machine.lane = 21
    machine._rp2040 = link
    machine._out_state = {}
    machine.recorder = cio.NULL_RECORDER
    machine.out_a = UncertainOutput()
    guarded = cio.FreshnessGuardIO(machine, link)

    with pytest.raises(cd.LinkFreshnessError, match="rolled back"):
        guarded.set_sweep(True)
    assert machine.out_a.writes == [True, False]
    assert machine.out_a.state is False
    assert machine._out_state["S"] is False
    assert link._cmd_run["S"] is False


def test_failed_run_transport_rolls_back_relay_and_command_intent():
    clock = {"t": 0.0}

    class FailingSerial:
        def write(self, _payload):
            raise TimeoutError("injected UART timeout")

        def close(self):
            pass

    link = RP2040Link(
        serial_obj=FailingSerial(), now=lambda: clock["t"],
        hb_timeout=1.0)
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')

    class RelayOutput:
        def __init__(self):
            self.state = False
            self.writes = []

        def write_bit(self, port, bit, value, *, positive_guard=None):
            if value and positive_guard is not None:
                positive_guard()
            self.state = bool(value)
            self.writes.append(bool(value))

    machine = object.__new__(cio.MachineIO)
    machine.lane = 21
    machine._rp2040 = link
    machine._out_state = {}
    machine.recorder = cio.NULL_RECORDER
    machine.out_a = RelayOutput()
    guarded = cio.FreshnessGuardIO(machine, link)

    with pytest.raises(cd.LinkFreshnessError, match="max-run"):
        guarded.set_sweep(True)
    assert machine.out_a.writes == [True, False]
    assert machine.out_a.state is False
    assert machine._out_state["S"] is False
    assert link._cmd_run["S"] is False
    # This is why the immediate exception matters: the generic consecutive-
    # failure health threshold has not necessarily opened yet.
    assert link.health_ok() is True


def test_run_reconciliation_never_sends_stale_captured_intent():
    link = RP2040Link()
    assert link.run("S") is True
    before = list(link.sent)
    # Models a STOP captured from an older heartbeat before the main thread
    # changed physical/command intent to RUN.
    assert link._send_reconcile("S", False) is False
    assert list(link.sent) == before

    assert link.stop("S") is True
    before = list(link.sent)
    # The inverse ordering must not re-issue RUN after hard-safe STOP.
    assert link._send_reconcile("S", True) is False
    assert list(link.sent) == before


def test_skipped_stale_reconciliations_do_not_consume_retry_budget():
    link = RP2040Link()
    for _ in range(3):
        with link._lock:
            link._cmd_run["S"] = False
            pending = []
            link._reconcile_run(
                1, [], pending)  # firmware RUN, captured desired STOP
            assert pending == [("S", False, True)]
            # Controller changes to RUN before the deferred send.
            link._cmd_run["S"] = True
        assert link._send_reconcile(
            "S", False, fw_running=True) is False
        assert link._resync_tries.get("S", 0) == 0

    # Once command intent settles at RUN while firmware is stopped, the full
    # retry budget remains and the first corrective RUN is actually sent.
    with link._lock:
        pending = []
        link._reconcile_run(0, [], pending)
    assert pending == [("S", True, False)]
    assert link._send_reconcile(
        "S", True, fw_running=False) is True
    assert link._resync_tries["S"] == 1
    assert list(link.sent)[-1] == "RUN S"


def test_firmware_reboot_retains_physical_run_intent_for_resync():
    link = RP2040Link()
    assert link.run("S") is True
    assert link._cmd_run["S"] is True
    link.feed_line(
        '{"ev":"boot","fw":"test","wdt_reset":1,"rp_ok":0,'
        '"maxrun_ms":8000}')
    assert link._cmd_run["S"] is True


@pytest.mark.parametrize("operation", ["arm", "watchdog"])
def test_machineio_inner_gpio_boundary_recheck_refuses_delayed_positive(
        operation):
    clock = {"t": 0.0}
    link = RP2040Link(now=lambda: clock["t"], hb_timeout=1.0)
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    physical = []
    machine = object.__new__(cio.MachineIO)
    machine.lane = 21
    machine._rp2040 = link
    machine.recorder = cio.NULL_RECORDER
    machine._armed = None
    machine._arm = lambda on: physical.append(("arm", bool(on)))
    machine._kick = lambda: physical.append(("watchdog", True))
    original_require = machine._require_positive_fresh

    def delay_then_check(action):
        clock["t"] = 1.0 - (
            cio.POSITIVE_ACTUATION_MIN_REMAINING_S / 2.0)
        return original_require(action)

    machine._require_positive_fresh = delay_then_check
    guarded = cio.FreshnessGuardIO(machine, link)
    with pytest.raises(cd.LinkFreshnessError, match="margin"):
        if operation == "arm":
            guarded.arm(True)
        else:
            guarded.watchdog_kick()
    assert physical == []


def test_watchdog_gpio_failure_still_forces_kick_pad_low():
    link = RP2040Link()
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')

    class AmbiguousWatchdog:
        def __init__(self):
            self.high = False
            self.off_calls = 0

        def on(self):
            self.high = True
            raise IOError("reported after pad change")

        def off(self):
            self.high = False
            self.off_calls += 1

    board = object.__new__(BoardController)
    board.link = link
    board._wdog = AmbiguousWatchdog()
    with pytest.raises(IOError, match="pad change"):
        board._kick_wdog()
    assert board._wdog.high is False
    assert board._wdog.off_calls == 1


def test_positive_operation_duration_bound_rolls_back_while_still_fresh():
    clock = {"t": 0.0}
    link = RP2040Link(now=lambda: clock["t"], hb_timeout=1.0)
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1}')
    base = cio.RecordingIO(now=lambda: clock["t"], rp2040=link)
    guarded = cio.FreshnessGuardIO(base, link)
    original = base.set_sweep

    def slow_but_not_expired(on):
        result = original(on)
        if on:
            clock["t"] += cio.POSITIVE_ACTUATION_MAX_S + 0.001
        return result

    base.set_sweep = slow_but_not_expired
    with pytest.raises(cd.LinkFreshnessError, match="outside"):
        guarded.set_sweep(True)
    assert link.health_ok() is True
    assert base.outputs["sweep"] is False
    assert ("sweep", True) in base.events
    assert base.events[-1] == ("sweep", False)


@pytest.mark.parametrize(
    "method,state_name",
    [
        ("set_sweep", "sweep"),
        ("set_table", "table"),
        ("set_spot", "spot"),
    ],
)
def test_slow_motor_on_crossing_deadline_is_rolled_back(
        method, state_name):
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    base = board.io._io
    original = getattr(base, method)

    def slow_write(on):
        result = original(on)
        if on:
            base.advance(2.0)
        return result

    setattr(base, method, slow_write)
    with pytest.raises(cd.LinkFreshnessError):
        getattr(board.io, method)(True)
    assert board.io.outputs[state_name] is False


def test_slow_arm_high_crossing_deadline_is_rolled_back_low():
    board = _revd_board()
    board.link.feed_line(_id_line())
    board.link.feed_line(_modern_hb())
    base = board.io._io
    original = base.arm

    def slow_arm(on):
        result = original(on)
        if on:
            base.advance(2.0)
        return result

    base.arm = slow_arm
    with pytest.raises(cd.LinkFreshnessError):
        board.io.arm(True)
    assert board.io.armed is False


def test_slow_watchdog_kick_postcheck_hard_safes_before_tick_returns():
    board = _revd_board()
    board.link.feed_line(_id_line())
    _to_ready(board)
    base = board.io._io
    original = base.watchdog_kick

    def slow_kick():
        result = original()
        base.advance(2.0)
        return result

    base.watchdog_kick = slow_kick
    with pytest.raises(cd.LinkFreshnessError):
        board.tick()
    assert board.io.armed is False
    assert board.fsm.state is State.MANUAL_INTERVENTION
    assert not any(board.io.outputs.get(k, False)
                   for k in ("sweep", "table", "spot"))


def test_controller_health_drop_top_level_ok_covers_all_board_policy_classes(
        monkeypatch, tmp_path):
    monkeypatch.setenv(cd.EXPECTED_MODE_ENV, "live")
    monkeypatch.setenv(
        cd.FW_QUALIFIED_RELEASES_ENV,
        f"revD|{BUILD}|{CFG}")
    base = {
        "lane_id": 21,
        "controller_boot_id": "boot",
        "control_loop_seq": 10,
        "board_rev": "revD",
        "fw_build": BUILD,
        "fw_cfg": CFG,
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
            "wdog_kick": False,
            "arm_permit": True,
            "rp2040_ok": True,
        },
        "parse_errors": 0,
        "quarantined_lines": 0,
        "diag_record_drops": 0,
        "pending_diag_records": 0,
    }

    class Board:
        cfg = type("Cfg", (), {"lane": 21})()

        def __init__(self, sample):
            self.sample = sample

        def telemetry_snapshot(self):
            sample = dict(self.sample)
            sample["safety_taps"] = dict(self.sample["safety_taps"])
            return sample

        def unavailable_telemetry_snapshot(self):
            raise AssertionError("current sample unexpectedly unavailable")

    captured = []
    monkeypatch.setattr(
        cd.health_drop, "write_drop",
        lambda _path, _service, payload: captured.append(payload) or True)

    def write(sample):
        platform = PlatformHealth(
            [Board(sample)], FakeWriter(), dir_path=str(tmp_path))
        platform._common_platform = {"ok": True, "reasons": []}
        platform._write_health_drop()
        return captured.pop()

    assert write(base)["ok"] is True
    mutations = [
        {"controller_mode": "shadow"},
        {"live_outputs_acknowledged": False},
        {
            "identity_ok": False,
            "identity_reason": "identity_not_received",
            "identity_assurance": "invalid",
        },
        {"manual_rearm_required": True},
        {"fsm_state": "fault"},
        {"arm_prerequisite_reason": "maxrun_desync"},
        {"safety_taps": {
            "ne555": True, "wdog_kick": False,
            "arm_permit": False, "rp2040_ok": True}},
        {"safety_taps": {
            "ne555": False, "wdog_kick": False,
            "arm_permit": True, "rp2040_ok": True}},
        {"safety_taps": {
            "ne555": True, "wdog_kick": False,
            "arm_permit": True, "rp2040_ok": False}},
        {"fw_build": "unqualified"},
    ]
    for mutation in mutations:
        sample = dict(base)
        sample.update(mutation)
        assert write(sample)["ok"] is False, mutation
