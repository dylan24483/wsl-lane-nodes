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


class FakeWriter:
    def __init__(self):
        self.events = []

    def emit(self, ev):
        self.events.append(ev)
        return True

    def of_type(self, et):
        return [e for e in self.events if e.event_type == et]


class FakeShipper:
    def __init__(self):
        self.rows = []

    def offer(self, row):
        self.rows.append(row)
        return True


def mk_board(roles=None, writer=None, shipper=None, board_rev="revC"):
    return BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev=board_rev), sim=True,
        diag_writer=writer, cycle_shipper=shipper, aux_roles=roles or {},
        slow_debounce_n=1)


def hb(bc, extra=""):
    bc.link.feed_line('{"ev":"hb","ok":1%s}' % extra)


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
    bc.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":2000,"run":1}')
    bc.tick()
    evs = w.of_type("run_mismatch")
    assert len(evs) == 1 and evs[0].severity == "fault"
    assert "S" in evs[0].detail["motors"]
    # firmware reconciles -> recovered
    bc.link.feed_line('{"ev":"hb","ok":1,"flt":"","up":2300,"run":0}')
    bc.tick()
    assert [e for e in w.of_type("recovered") if e.code == "run_mismatch"]


def test_fw_config_mismatch_fault_on_maxrun_desync():
    w = FakeWriter()
    bc = mk_board(writer=w)
    bc.link.feed_line('{"ev":"boot","fw":"t","maxrun_ms":1000}')
    to_ready(bc)
    assert bc.io.armed is False
    evs = w.of_type("fw_config_mismatch")
    assert len(evs) == 1 and evs[0].severity == "fault"
    assert evs[0].detail["fw_maxrun_ms"] == 1000


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


ID_LINE = ('{"ev":"id","fw":"phase8b-rp2040 v1.2.2","pcb":"%s","rid":%s,'
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
            bc.diag.note_cycle_complete(float(i))
        evs = w.of_type("stale_channel")
        assert len(evs) == 1 and evs[0].detail["role"] == "exit_beam"
        # a pulse resets the episode
        bc.diag._note_pulse("AUX2", 10.0)
        for i in range(3):
            bc.diag.note_cycle_complete(20.0 + i)
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

def test_platform_clock_drift_probe():
    w = FakeWriter()
    ph = PlatformHealth([], w, dir_path=tempfile.mkdtemp(prefix="ph_"))
    ph._poll_clock_drift()            # baseline
    ph._clock_base -= 10.0            # simulate a 10 s NTP step
    ph._poll_clock_drift()
    evs = w.of_type("pi_clock_drift")
    assert len(evs) == 1 and abs(evs[0].detail["step_s"]) >= 5.0


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


def test_platform_storage_retention_probe():
    os.environ["WSL_DIAG_DIR_MAX_MB"] = "0.001"    # ~1 KB cap
    try:
        d = tempfile.mkdtemp(prefix="ph_ret_")
        for name in ("diag-20260719.jsonl", "diag-20260720.jsonl",
                     "diag-20260721.jsonl"):
            with open(os.path.join(d, name), "w") as f:
                f.write("x" * 4096)
        w = FakeWriter()
        ph = PlatformHealth([], w, dir_path=d)
        ph._poll_dir_retention()
        left = sorted(n for n in os.listdir(d) if n.endswith(".jsonl"))
        assert "diag-20260721.jsonl" in left       # newest never pruned
        assert len(left) < 3
        evs = w.of_type("diag_storage_pruned")
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
