"""Guards for the positive-actuation return bound (round-5 audit follow-up).

`controller_io.POSITIVE_ACTUATION_MAX_S` bounds how long a safety-positive
actuation may take to return. Exceeding it turns a motor OFF mid-motion and
escalates to hard-safe + MANUAL_INTERVENTION, which needs a physical PBZ.

Two properties are load-bearing and are asserted here:

1. The bound has an EXPLICIT env escape that fails LOUD. A safety deadline
   that silently reverts to its default when the operator typos the override
   is worse than no override at all — the operator believes a measured value
   is in force when it is not. (Contrast `controller_daemon._env_float`, which
   swallows garbage by design; that is fine for cosmetic knobs, not for this.)

2. The watchdog kick gets its OWN budget. Its body deliberately BLOCKS for
   `WDOG_PULSE_S` between the two monotonic samples, so charging that
   deliberate sleep against a bound sized for non-blocking register writes is
   a category error.

NOTE: these tests deliberately do NOT `importlib.reload(controller_io)`.
Reloading rebinds `LinkFreshnessError` to a new class object while
`controller_daemon` still holds the old one, which silently breaks
`except LinkFreshnessError` in every other suite. The env parser is exercised
directly instead.

See scripts/measure_actuation_bound.py for producing a measured value.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lane_node"))

import controller_daemon  # noqa: E402
import controller_io  # noqa: E402

PARSE = controller_io._env_bounded_seconds
LO = controller_io._ACTUATION_BOUND_LO_S
HI = controller_io._ACTUATION_BOUND_HI_S
KNOB = "WSL_POSITIVE_ACTUATION_MAX_S"


def _parse(monkeypatch, raw, default=0.050):
    if raw is None:
        monkeypatch.delenv(KNOB, raising=False)
    else:
        monkeypatch.setenv(KNOB, raw)
    return PARSE(KNOB, default, lo=LO, hi=HI)


# --- 1. the env escape exists and fails LOUD -------------------------------

def test_shipped_default_is_the_documented_value():
    assert controller_io.POSITIVE_ACTUATION_MAX_S == pytest.approx(0.050)


def test_unset_uses_the_default(monkeypatch):
    assert _parse(monkeypatch, None) == pytest.approx(0.050)


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_blank_uses_the_default(monkeypatch, raw):
    """Blank means "not set" — it cannot mislead, the operator wrote nothing."""
    assert _parse(monkeypatch, raw) == pytest.approx(0.050)


@pytest.mark.parametrize("raw,expected", [
    ("0.080", 0.080), (" 0.080 ", 0.080), ("0.1", 0.1), ("5e-2", 0.05),
])
def test_valid_override_is_honoured(monkeypatch, raw, expected):
    assert _parse(monkeypatch, raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["abc", "0.05s", "50ms", "1e", "None", "0,05"])
def test_non_numeric_override_raises_and_names_the_variable(monkeypatch, raw):
    with pytest.raises(ValueError) as excinfo:
        _parse(monkeypatch, raw)
    message = str(excinfo.value)
    assert KNOB in message
    assert "is not a number" in message


@pytest.mark.parametrize("raw", ["0.0", "0.001", "0.6", "5", "-0.05"])
def test_out_of_range_override_is_rejected_loudly(monkeypatch, raw):
    """Never silently clamp: too low guarantees false trips, too high lets a
    positive actuation outlive its heartbeat lease."""
    with pytest.raises(ValueError) as excinfo:
        _parse(monkeypatch, raw)
    assert "outside the permitted range" in str(excinfo.value)


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "Infinity"])
def test_non_finite_override_is_rejected(monkeypatch, raw):
    with pytest.raises(ValueError):
        _parse(monkeypatch, raw)


def test_bad_override_never_silently_returns_the_default(monkeypatch):
    """The regression this whole file exists to prevent.

    If this ever starts returning 0.050 instead of raising, an operator who
    measured 0.080 and typo'd the value is running on the unmeasured default
    while believing otherwise.
    """
    with pytest.raises(ValueError):
        _parse(monkeypatch, "50ms")


def test_boundaries_are_inclusive(monkeypatch):
    assert _parse(monkeypatch, str(LO)) == pytest.approx(LO)
    assert _parse(monkeypatch, str(HI)) == pytest.approx(HI)


# --- 2. the watchdog kick has its own, larger budget -----------------------

def test_watchdog_budget_exceeds_the_write_budget():
    assert (controller_io.WATCHDOG_KICK_MAX_S
            > controller_io.POSITIVE_ACTUATION_MAX_S)


def test_daemon_derives_the_kick_budget_from_the_real_pulse_width():
    """The budget must account for the deliberate NE555 pulse."""
    derived = (controller_daemon.WDOG_PULSE_S
               + controller_io.POSITIVE_ACTUATION_MAX_S)
    assert derived > controller_daemon.WDOG_PULSE_S
    assert derived > controller_io.POSITIVE_ACTUATION_MAX_S
    assert LO <= derived <= HI


def test_guard_rejects_an_out_of_range_injected_watchdog_budget():
    with pytest.raises(ValueError):
        controller_io.FreshnessGuardIO(
            object(), _FakeLink(), watchdog_kick_max_s=9.0)


# --- 3. the guard actually applies the separate budget ---------------------

class _FakeLink:
    """Monotonic clock we control, always reporting a fresh lease."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def actuation_freshness_status(self):
        return True, 10.0


class _FakeIO:
    def __init__(self, link, cost):
        self._link = link
        self._cost = cost
        self.kicks = 0

    def watchdog_kick(self):
        self.kicks += 1
        self._link.t += self._cost


def test_kick_costing_more_than_the_write_budget_but_under_its_own_passes():
    """A kick that legitimately blocks for its pulse must NOT trip the guard.

    This is the false-trip the separate budget exists to prevent.
    """
    link = _FakeLink()
    cost = controller_io.POSITIVE_ACTUATION_MAX_S + 0.001
    io = _FakeIO(link, cost)
    guard = controller_io.FreshnessGuardIO(
        io, link, watchdog_kick_max_s=cost + 0.001)
    guard.watchdog_kick()
    assert io.kicks == 1


def test_kick_over_its_own_budget_still_trips():
    """Widening the budget must not disable the guard."""
    link = _FakeLink()
    budget = controller_io.POSITIVE_ACTUATION_MAX_S + 0.002
    io = _FakeIO(link, budget + 0.010)
    guard = controller_io.FreshnessGuardIO(
        io, link, watchdog_kick_max_s=budget)
    with pytest.raises(controller_io.LinkFreshnessError):
        guard.watchdog_kick()


def test_motion_on_still_uses_the_tighter_write_budget():
    """Only the kick gets the wider budget; motion is unchanged."""
    link = _FakeLink()

    class _MotionIO:
        def __init__(self):
            self.calls = []

        def set_sweep(self, on):
            self.calls.append(on)
            if on:
                link.t += controller_io.POSITIVE_ACTUATION_MAX_S + 0.010

    io = _MotionIO()
    guard = controller_io.FreshnessGuardIO(
        io, link, watchdog_kick_max_s=controller_io.WATCHDOG_KICK_MAX_S)
    with pytest.raises(controller_io.LinkFreshnessError):
        guard.set_sweep(True)
    # Rollback must have issued the OFF command.
    assert io.calls == [True, False]


def test_default_guard_construction_still_works():
    """Omitting the budget must fall back to the module constant, not crash."""
    guard = controller_io.FreshnessGuardIO(object(), _FakeLink())
    assert guard._wdog_max_s == pytest.approx(
        controller_io.WATCHDOG_KICK_MAX_S)
