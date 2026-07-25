"""No-hardware safety regressions for the first-article output utility."""
from __future__ import annotations

from pathlib import Path
import sys
import threading
import time

import pytest


LANE_DIR = Path(__file__).resolve().parents[1] / "lane_node"
if str(LANE_DIR) not in sys.path:
    sys.path.insert(0, str(LANE_DIR))

import bench_first_article as bench  # noqa: E402


BUILD = "release-build"
CFG = "cfg-hash"
RELEASES = (("revD", BUILD, CFG),)


class FakeLED:
    def __init__(self, pin=None, log=None):
        self.pin = pin
        self.log = [] if log is None else log
        self.value = 0

    def on(self):
        self.value = 1
        self.log.append(("led_on", self.pin))

    def off(self):
        self.value = 0
        self.log.append(("led_off", self.pin))

    def close(self):
        self.log.append(("led_close", self.pin))


class FakeIO:
    def __init__(self, log=None, fail_output=None):
        self.log = [] if log is None else log
        self.fail_output = fail_output

    def arm(self, enabled):
        self.log.append(("arm", bool(enabled)))

    def _set_out(self, name, enabled):
        self.log.append(("out", name, bool(enabled)))
        if name == self.fail_output:
            raise OSError("injected output failure")

    def all_off(self):
        self.log.append(("all_off",))

    def close(self):
        self.log.append(("io_close",))


class FakeLink:
    def __init__(self, log=None, *, healthy=True, identity_ok=True,
                 maxrun_ms=8000):
        self.log = [] if log is None else log
        self.healthy = healthy
        self.identity_ok_value = identity_ok
        self.maxrun_value = maxrun_ms

    def stop_all(self):
        self.log.append(("stop_all",))
        return True

    def clear(self):
        self.log.append(("clear",))
        return True

    def health_ok(self):
        return self.healthy

    def identity_status(self):
        return (
            (True, None) if self.identity_ok_value
            else (False, "identity_missing"))

    def fw_identity(self):
        return {
            "pcb": "revD", "rid": 1, "build": BUILD, "cfg": CFG,
            "fi1": False,
        }

    def pcb_rev_id(self):
        return 1

    def maxrun_ms(self):
        return self.maxrun_value

    def maxrun_ok(self):
        return self.maxrun_value == 8000

    def rp_ok(self):
        return self.healthy

    def fault(self):
        return None

    def is_alive(self):
        return self.healthy

    def running_motors(self):
        return ()

    def close(self):
        self.log.append(("link_close",))


def _session(*, link=None, allow_no_rp2040=False, fail_output=None):
    log = []
    kick = threading.Event()
    kick.set()
    io = FakeIO(log, fail_output=fail_output)
    if link is None and not allow_no_rp2040:
        link = FakeLink(log)
    elif link is not None:
        link.log = log
    return bench.BenchSession(
        io, link, FakeLED(26, log), FakeLED(12, log), kick,
        board_rev="revD", qualified_releases=RELEASES,
        allow_no_rp2040=allow_no_rp2040,
        output=lambda _message: None), log


def test_arm_proves_every_latch_low_before_asserting_arm():
    session, log = _session()
    session.arm()
    assert log[0] == ("arm", False)
    assert log[1] == ("stop_all",)
    assert {
        entry[1] for entry in log
        if entry[:1] == ("out",) and entry[2] is False
    } == set(bench.MOTION + bench.LAMPS)
    assert log[-2:] == [("all_off",), ("arm", True)]
    assert session.armed is True


def test_disarm_and_rearm_cannot_reuse_a_stale_motion_latch():
    session, log = _session()
    session.arm()
    session.set_output("S", True)
    log.clear()
    session.disarm()
    assert log[0] == ("arm", False)
    assert ("out", "S", False) in log
    assert ("stop_all",) in log
    assert session.armed is False

    log.clear()
    session.arm()
    assert ("out", "S", False) in log
    assert log[-1] == ("arm", True)


def test_clear_safes_physical_and_firmware_state_before_clearing_fault():
    session, log = _session()
    session.armed = True
    session.clear()
    assert log[0] == ("arm", False)
    assert log.index(("stop_all",)) < log.index(("clear",))
    assert log.index(("all_off",)) < log.index(("clear",))
    assert session.armed is False


def test_kick_resume_safes_latches_before_watchdog_can_repermit_rail():
    session, log = _session()
    session.armed = True
    session.kick_on.clear()
    session.set_kick(True)
    assert log[0] == ("arm", False)
    assert ("out", "S", False) in log
    assert log[-1] == ("all_off",)
    assert session.kick_on.is_set()
    assert session.armed is False


def test_motion_requires_explicit_arm_and_m1_is_never_addressable():
    session, _log = _session()
    with pytest.raises(RuntimeError, match="ARM"):
        session.set_output("S", True)
    with pytest.raises(ValueError, match="unsupported"):
        session.set_output("M1", True)
    with pytest.raises(ValueError, match="commands"):
        session.handle("m1 on")


def test_firmware_gate_requires_exact_policy_identity_and_known_maxrun():
    no_policy, _ = _session()
    no_policy.qualified_releases = ()
    with pytest.raises(RuntimeError, match="policy is unconfigured"):
        no_policy.arm()

    unknown_maxrun, _ = _session(link=FakeLink(maxrun_ms=None))
    with pytest.raises(RuntimeError, match="advertisement is missing"):
        unknown_maxrun.arm()

    no_link, _ = _session(link=None, allow_no_rp2040=True)
    no_link.arm()
    assert no_link.armed is True
    status = no_link.status()
    assert status["arm_gate_ok"] is False
    assert status["firmware_maxrun_qualified"] is False
    assert status["relay_only_override_enabled"] is True
    no_link.disarm()


def test_relay_only_override_has_bounded_automatic_hard_off():
    session, log = _session(link=None, allow_no_rp2040=True)
    session.relay_only_deadline_s = 0.02
    session.arm()
    session.set_output("S", True)
    deadline = time.monotonic() + 1.0
    while session.armed and time.monotonic() < deadline:
        time.sleep(0.005)
    assert session.armed is False
    assert ("arm", False) in log
    assert ("out", "S", False) in log
    assert ("all_off",) in log
    assert session.background_failures == []


def test_relay_only_timer_start_failure_rolls_back_safe(monkeypatch):
    session, log = _session(link=None, allow_no_rp2040=True)

    def fail_timer_start():
        raise RuntimeError("timer unavailable")

    monkeypatch.setattr(
        session, "_start_relay_only_deadline", fail_timer_start)
    with pytest.raises(
            RuntimeError, match="deadline could not start.*rolled safe"):
        session.arm()

    assert session.armed is False
    assert ("arm", False) in log
    assert ("all_off",) in log


def test_relay_only_cli_requires_explicit_dummy_load_confirmation():
    with pytest.raises(SystemExit):
        bench._parse_args(["--relay-only-without-rp2040"])
    args = bench._parse_args([
        "--relay-only-without-rp2040",
        "--confirm-off-machine-dummy-load",
    ])
    assert args.relay_only_without_rp2040 is True
    assert args.confirm_off_machine_dummy_load is True


def test_safe_state_attempts_every_channel_after_one_clear_failure():
    session, log = _session(fail_output="S")
    failures = session.safe_state()
    assert any(failure.startswith("S_off:") for failure in failures)
    assert ("out", "foul", False) in log
    assert ("all_off",) in log
    assert session.armed is False


def test_main_acquires_owner_lease_before_loading_hardware(monkeypatch):
    monkeypatch.delenv(bench.STATE_DIR_ENV, raising=False)
    monkeypatch.delenv(bench.QUALIFIED_RELEASES_ENV, raising=False)
    order = []

    class FakeLease:
        def __init__(self, directory, lane):
            order.append(("lease_init", directory, lane))

        def acquire(self):
            order.append(("lease_acquire",))

        def release(self):
            order.append(("lease_release",))

    class NoUart:
        def __init__(self, **_kwargs):
            raise OSError("no UART in host test")

    class MainIO(FakeIO):
        def __init__(self, lane, bus, **_kwargs):
            order.append(("io_init", lane, bus))
            super().__init__(order)

    def loader():
        order.append(("hardware_load",))
        assert ("lease_acquire",) in order
        return (
            lambda pin: FakeLED(pin, order),
            MainIO,
            {name: (0, index) for index, name in enumerate(
                bench.MOTION + bench.LAMPS)},
            NoUart,
        )

    assert bench.main(
        [
            "--relay-only-without-rp2040",
            "--confirm-off-machine-dummy-load",
        ],
        input_fn=lambda _prompt: "q",
        output_fn=lambda _message: None,
        hardware_loader=loader,
        lease_factory=FakeLease) == 0
    assert order.index(("lease_acquire",)) < order.index(("hardware_load",))
    assert order[-1] == ("lease_release",)
