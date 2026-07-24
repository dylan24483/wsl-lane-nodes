"""Focused regressions for fail-closed identity and UNKNOWN sensor semantics."""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "lane_node")))

import controller_daemon as cd
from controller_daemon import (
    BallReturnTracker, BoardConfig, BoardController, LaneDiag, PlatformHealth)
from cycle_control_8270 import State
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

    def of_type(self, event_type):
        return [e for e in self.events if e.event_type == event_type]


def _revd_board():
    cfg = BoardConfig(
        21, 1, "sim", 0, 0, board_rev="revD",
        allowed_fw_builds=(BUILD,), allowed_fw_cfgs=(CFG,),
        expected_uid=UID)
    return BoardController(cfg, sim=True, slow_debounce_n=1)


def _id_line(*, bn=7, build=BUILD, cfg=CFG, uid=UID, fi1=0,
             pcb="revD", rid=1):
    return json.dumps({
        "ev": "id", "fw": "phase8b-rp2040 v1.2.3", "bn": bn,
        "pcb": pcb, "rid": rid, "uid": uid, "build": build,
        "cfg": cfg, "fi1": fi1, "t": 100,
    })


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
    board.link.feed_line(json.dumps({
        "ev": "hb", "ok": 1, "flt": "", "up": 100, "bn": bn, "rid": 1,
    }))
    board.tick()
    board.io.slow["PBZ"] = True
    board.tick()
    board.io.slow["PBZ"] = False
    board.link.feed_line(json.dumps({
        "ev": "hb", "ok": 1, "flt": "", "up": 200, "bn": bn, "rid": 1,
    }))
    board.tick()
    assert board.fsm.state is State.READY


def test_revd_arm_is_inhibited_immediately_until_complete_current_identity():
    board = _revd_board()
    _to_ready(board)
    assert board.io.armed is False
    assert board._identity_arm_ok() == (False, "identity_not_received")

    board.link.feed_line(_id_line())
    board.tick()
    assert board.link.identity_ok() is True
    assert board._identity_arm_ok() == (True, None)
    assert board.io.armed is True


def test_revd_identity_enforces_nonce_fields_allowlists_and_uid():
    board = _revd_board()
    board.link.feed_line(
        '{"ev":"hb","ok":1,"flt":"","up":1,"bn":7,"rid":1}')
    for line, expected_reason in (
        (json.dumps({"ev": "id", "fw": "x", "bn": 7, "pcb": "revD",
                     "rid": 1, "build": BUILD, "cfg": CFG, "fi1": 0}),
         "uid_missing"),
        (_id_line(build="other"), "build_not_allowed"),
        (_id_line(cfg="other"), "cfg_not_allowed"),
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
    board = BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev="revD"),
        sim=True, slow_debounce_n=1)
    board.link.feed_line(
        '{"ev":"hb","ok":1,"flt":"","up":1,"bn":7,"rid":1}')
    board.link.feed_line(_id_line())
    assert board._identity_arm_ok() == (
        False, "build_allowlist_unconfigured")


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
    board.link.feed_line(json.dumps({
        "ev": "hb", "ok": 1, "flt": "", "up": 300, "bn": 11, "rid": 1,
    }))
    assert board.link.fw_identity() is None
    board.tick()
    assert board.io.armed is False


def test_bank_unknown_pauses_ball_return_timeout_until_recovery():
    writer = FakeWriter()
    diag = LaneDiag(21, writer=writer, aux_roles={"AUX2": "exit_beam"})
    tracker = BallReturnTracker([21], timeout_s=10.0)
    diag.set_ball_tracker(tracker)

    diag.poll(0.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX2": False})
    diag.on_ball(0.0)
    diag.poll(1.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels=None)
    diag.poll(20.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels=None)
    assert writer.of_type("ball_return_missing") == []
    assert tracker.missing_total[21] == 0

    # Recovery is a baseline, and the 20 s UNKNOWN interval is excluded from
    # the 10 s timeout budget.
    diag.poll(21.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX2": False})
    diag.poll(30.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX2": False})
    assert writer.of_type("ball_return_missing") == []
    diag.poll(30.1, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX2": False})
    assert len(writer.of_type("ball_return_missing")) == 1


def test_missing_role_is_not_coerced_false_and_timer_resumes(monkeypatch):
    monkeypatch.setenv("WSL_DIAG_BE_WINDOW_S", "1")
    writer = FakeWriter()
    diag = LaneDiag(21, writer=writer, aux_roles={"AUX1": "be_current"})
    diag.poll(0.0, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX1": False})
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
    assert [e for e in writer.of_type("recovered")
            if e.code == "configured_role_missing"]
    diag.poll(11.1, ready=True, in_motion=False,
              slow_levels={}, inb_levels={"AUX1": False})
    assert len(writer.of_type("be_no_current")) == 1


def test_heartbeat_proves_live_contract_and_control_loop_progress():
    board = BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev="revC"),
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
