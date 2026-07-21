#!/usr/bin/env python3
"""
controller_daemon.py — Phase 8b Track-B per-pair machine-control daemon (SKELETON).

Assembles, per lane/board, the three pieces that already exist + are tested:
    RP2040Link (rp2040_link.py)  +  MachineIO(rp2040=link) (controller_io.py)  +
    CycleController (cycle_control_8270.py)
and runs the real-time control loop:

    each tick (~50 Hz):
      link.apply_events(fsm)     # cam/ball edges from the RP2040 -> FSM
      read slow-input edges      # PBZ/BS/Foul from the MCP23017 -> FSM methods
      fsm.poll()                 # advance FSM + KICK THE NE555 (poll() kicks via io)
      io.arm(armed)              # power-down rule + RP2040 health gate the arm GPIO

⚠️ SKELETON / BENCH-GATED. Do NOT run against a live machine until the full
hardware safety chain is validated per docs/phase8b_pcb_revB_spec.md §12.9 and the
controller cutover runbook. Items marked  # CONFIRM  (pin numbers, I2C bus ids,
UART ports, slow-input polarity/debounce) are set at bench/cutover.

NOT yet wired: server/scoring reporting (Track A camera + lane_node.py websocket).
The controller (this daemon) and the scoring/server path must be unified at bench
— see TODO(server). This file deliberately stays a tight synchronous control loop;
scoring/IO-to-server is async and lives elsewhere.

DIAGNOSTICS (2026-07-19 scope, Phase 1 — wave-2 integration): per-lane rules
(manual-override suppression, stuck-input/beam-blocked, config-driven AUX sensor
rules) + typed events into the wave-1 diag_events pipe, per-cycle machine_cycles
rows via CycleShipper, and a PlatformHealth thread (vcgencmd/restart counter/
telemetry-baseline persistence pump). ALL of it is observe/alert-only and
enqueue-only on the tick path — file/HTTP/subprocess I/O runs exclusively on the
background threads; every rule/emitter has a WSL_DIAG_* kill-switch and a
catch-all so a diagnostics bug degrades to a counted no-op, never a tick stall.

SAFETY notes:
  * The NE555 watchdog is kicked ONLY from fsm.poll() inside the tick loop, so if
    the control loop stalls the kick stops -> NE555 drops the rail -> motion stops.
    That coupling is intentional (unlike the Track-A scoring node, where scoring
    must NOT be able to stop the machine).
  * RP2040_OK is a HARDWARE rail line driven by the firmware; a dead/!ok RP2040
    drops the rail regardless of this daemon. We additionally fault-safe in software
    (drop ARM, log) so the FSM and operator see it.

Run the off-hardware self-test:   python controller_daemon.py --selftest
Run for real (on the Pi):         python controller_daemon.py        # needs gpiozero/smbus/pyserial
                                  # ⚠️ LIVE by default (shadow is opt-in) — see the
                                  # WSL_CONTROLLER_SHADOW / WSL_LIVE_OUTPUTS notes below.
One-board bench rig (D3):         python controller_daemon.py --lanes 21   # or WSL_LANES=21
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cycle_control_8270 import CycleController, State, MOTION_STATES
from controller_io import MachineIO, RecordingIO, ShadowIO
from rp2040_link import RP2040Link, REBOOT_FAULT
from flight_recorder import FlightRecorder
from cam_telemetry import CamTelemetry, CycleShipper
from diag_events import DiagWriter, HttpSink, make_event

log = logging.getLogger("controller_daemon")

# Shadow/canary soak (idea #11). When WSL_CONTROLLER_SHADOW is truthy the FSM runs
# on the REAL inputs but every output is routed to a record-only shim (ShadowIO) and
# the relay-enable ARM is hard-held LOW — no relay is ever energized.
# ⚠️ SHADOW IS OPT-IN — THE DEFAULT IS LIVE (review #52): a bare
# `python controller_daemon.py` on wired hardware drives REAL outputs. main()
# logs an unmissable LIVE-vs-SHADOW banner at startup either way.
# See ShadowIO in controller_io.py.
SHADOW_ENV = "WSL_CONTROLLER_SHADOW"
# Explicit live acknowledgment (review #52). NOT a gate — the default stays
# live-when-shadow-off so existing bench workflows are byte-for-byte unchanged;
# it only selects which startup banner prints: LIVE-acknowledged vs a loud
# LIVE-BY-DEFAULT warning. Flip this into a hard gate at/after the §12.9 bench
# sign-off if the accidental-run posture must match the bench-gated claims.
LIVE_ENV = "WSL_LIVE_OUTPUTS"
_FALSEY = ("0", "false", "no", "off", "")


def _shadow_enabled():
    return os.environ.get(SHADOW_ENV, "0").strip().lower() not in _FALSEY


def _live_acknowledged():
    return os.environ.get(LIVE_ENV, "0").strip().lower() not in _FALSEY


# ---------------------------------------------------------------------------
# Diagnostics campaign env knobs (2026-07-19 scope; WSL_* house pattern:
# default ON, falsey string disables; read at rule-eval time so a soak can be
# silenced without a restart). Every rule below is ALERT-ONLY — nothing in the
# diagnostics stack drives an output, and every emit is an enqueue
# (DiagWriter.emit -> put_nowait): no file/HTTP/subprocess ever runs on the
# 50 Hz tick that kicks the NE555.
# ---------------------------------------------------------------------------
DIAG_EVENTS_ENV = "WSL_DIAG_DAEMON_EVENTS"    # master gate for daemon emitters+rules
SUPPRESS_MIN_ENV = "WSL_DIAG_SUPPRESS_MIN"    # mechanic-window alert suppression (minutes)
SUPPRESS_MAX_MIN_ENV = "WSL_DIAG_SUPPRESS_MAX_MIN"  # cap on ONE continuous suppression episode (minutes)
MANUAL_RULE_ENV = "WSL_DIAG_MANUAL_OVERRIDE"  # manual-override events + suppression refresh
STUCK_RULE_ENV = "WSL_DIAG_STUCK_INPUT"       # mid-session stuck-input rule
STUCK_S_ENV = "WSL_DIAG_STUCK_INPUT_S"        # default per-input held-asserted threshold (s)
BEAM_RULE_ENV = "WSL_DIAG_BEAM_BLOCKED"       # DIELL beam-blocked rule
BEAM_S_ENV = "WSL_DIAG_BEAM_BLOCKED_S"        # beam held-blocked threshold (s)
AUX_RULE_ENV = "WSL_DIAG_AUX_RULES"           # all AUX sensor rules
BE_STUCK_MIN_ENV = "WSL_DIAG_BE_STUCK_MIN"    # BE current w/ no cycle activity (minutes)
BE_WINDOW_S_ENV = "WSL_DIAG_BE_WINDOW_S"      # post-cycle window the BE run must show in (s)
BALL_RETURN_S_ENV = "WSL_DIAG_BALL_RETURN_S"  # ball-return timeout (s)
DIST_GAP_S_ENV = "WSL_DIAG_DIST_GAP_S"        # dist-index pulse gap during a cycle (s)
PLATFORM_ENV = "WSL_DIAG_PLATFORM"            # platform-health background thread
PLATFORM_POLL_S_ENV = "WSL_DIAG_PLATFORM_POLL_S"
AUX_ROLES_ENV = "WSL_DIAG_AUX_ROLES"          # e.g. "aux1=be_current,aux2=exit_beam,aux3=dist_index"
# Stable-time debounce (H3, Codex audit 2026-07-21): a slow-input LEVEL is
# accepted only after N consecutive identical samples at the 50 Hz tick cadence
# (N*20 ms of stability). Two independent knobs:
#   WSL_SLOW_DEBOUNCE_N     — the DIAGNOSTICS rules' inputs (IN-A watched +
#                             IN-B AUX/manual banks). Default 3 (~60 ms) —
#                             opto/contact bounce must not fake rule edges.
#   WSL_SLOW_DEBOUNCE_FSM_N — the FSM ACTION inputs (PBZ/BS/Foul rising edges
#                             -> first_ball_zero/bin_full/on_foul). Default 1
#                             (= RAW, byte-for-byte legacy semantics).
#     ⚠️ SAFETY-PATH FLAG: raising this ALTERS cycle-input timing (each accepted
#     edge lags the physical edge by (N-1)..N ticks, 20-60 ms at N=2-3). That is
#     mechanically negligible for PBZ (operator button), BS (bin microswitch)
#     and Foul (>100 ms beam events), but it is a deliberate, bench-signed-off
#     change — set it at §12.9 bench validation, not casually. Default stays 1
#     precisely so this remediation does NOT silently change safety semantics.
SLOW_DEBOUNCE_ENV = "WSL_SLOW_DEBOUNCE_N"
SLOW_DEBOUNCE_FSM_ENV = "WSL_SLOW_DEBOUNCE_FSM_N"
DEFAULT_SLOW_DEBOUNCE_N = 3
DEFAULT_SLOW_DEBOUNCE_FSM_N = 1

DEFAULT_SUPPRESS_MIN = 10.0
# Episode cap (2026-07-19 review): a MAN_* opto failed shorted-on (or
# chattering) would otherwise refresh the suppression window FOREVER and
# silently blind every warn/fault alert on that lane. One continuous episode
# of manual activity may suppress for at most this long; crossing the cap
# emits a warn ('manual:suppress_cap') and lets alerts through again. A real
# mechanic session that goes quiet for SUPPRESS_MIN starts a fresh episode.
DEFAULT_SUPPRESS_MAX_MIN = 60.0
DEFAULT_STUCK_S = 60.0
DEFAULT_BEAM_S = 30.0
DEFAULT_BE_STUCK_MIN = 5.0
DEFAULT_BE_WINDOW_S = 60.0
DEFAULT_BALL_RETURN_S = 45.0
DEFAULT_DIST_GAP_S = 5.0
DEFAULT_PLATFORM_POLL_S = 60.0

# Manual-override inputs (scope §1 mechanic-at-machine discrimination). MAN_* +
# TENTH live on IN-B; PBC is on IN-A (netlist truth — see controller_io maps).
MANUAL_INPUT_NAMES = ("MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR", "TENTH", "PBC")
# Stuck-input rule exemptions: BS asserted at rest is NORMAL (bin stays full);
# MAN_* held is a mechanic session (manual-override rule owns those); AUX
# channels have their own role rules. AUX4-11 (rev-D IN-B GPB bank) included —
# same dormant-unless-mapped posture as AUX1-3 (H3, 2026-07-21).
STUCK_EXEMPT = ("BS", "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR") \
    + tuple(f"AUX{i}" for i in range(1, 12))

AUX_ROLE_VALID = ("be_current", "exit_beam", "dist_index")
# aux1-aux3 = rev-B/C spare channels (GPA); aux4-aux11 = the rev-D GPB bank.
# On a rev-B/C board a mapped aux4+ role simply never sees a level (the
# channel is absent from that board's IN-B map) — dormant, not an error.
_AUX_KEY_TO_INPUT = {f"aux{i}": f"AUX{i}" for i in range(1, 12)}


def _env_on(name, default="1"):
    return os.environ.get(name, default).strip().lower() not in _FALSEY


def _env_float(name, default):
    try:
        return float(os.environ.get(name, "").strip() or default)
    except Exception:
        return float(default)


def _env_int(name, default, lo=1, hi=50):
    """Bounded positive int env knob; garbage/out-of-range -> default."""
    try:
        v = int(os.environ.get(name, "").strip() or default)
        return v if lo <= v <= hi else int(default)
    except Exception:
        return int(default)


class SlowDebounce:
    """Stable-time debouncer for the 50 Hz slow-input samples (H3, Codex
    audit 2026-07-21): a NEW level is accepted only after `n` CONSECUTIVE
    identical samples (n * tick period of stability — n=3 @ 50 Hz = ~60 ms).
    n=1 is exact passthrough (legacy raw behavior). The initial level is a
    BASELINE, never an edge (mirrors the daemon's startup rule, review #28).
    Bounded state (three scalars per input); update() never raises."""

    __slots__ = ("n", "stable", "_cand", "_count")

    def __init__(self, n, initial=False):
        self.n = max(1, int(n))
        self.stable = bool(initial)
        self._cand = self.stable
        self._count = 0

    def update(self, raw):
        raw = bool(raw)
        if raw == self.stable:
            self._count = 0                     # agreement -> reset any streak
        else:
            self._count = self._count + 1 if raw == self._cand else 1
            if self._count >= self.n:
                self.stable = raw               # n consecutive samples: accept
                self._count = 0
        self._cand = raw
        return self.stable


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse_aux_roles(spec):
    """'aux1=be_current,aux2=exit_beam' -> {'AUX1': 'be_current', ...}.
    Unknown keys/roles are logged + skipped (never raises). None/blank -> {}."""
    roles = {}
    if not spec or not str(spec).strip():
        return roles
    for tok in str(spec).replace(",", " ").split():
        try:
            k, v = tok.split("=", 1)
        except ValueError:
            log.warning("aux role token %r has no '=' — skipped", tok)
            continue
        name = _AUX_KEY_TO_INPUT.get(k.strip().lower())
        role = v.strip().lower()
        if name is None or role not in AUX_ROLE_VALID:
            log.warning("aux role %r=%r not recognized — skipped", k, v)
            continue
        roles[name] = role
    return roles


# One-board bench mode (readiness item D3). WSL_LANES env / --lanes CLI select a
# SUBSET of DEFAULT_BOARDS *before* construction, so a single-board rig never
# opens the absent board's I2C bus / UART. CLI beats env; unset/empty = all.
LANES_ENV = "WSL_LANES"


def _parse_lanes(spec):
    """'21' / '21,22' -> [21, 22] (deduped, order kept). None/blank -> None (= all).
    Raises ValueError on a non-integer token."""
    if spec is None or not spec.strip():
        return None
    lanes = []
    for tok in spec.replace(",", " ").split():
        n = int(tok)
        if n not in lanes:
            lanes.append(n)
    return lanes


def _select_boards(configs, lanes):
    """Filter board configs to the requested lanes (None = all). An unknown lane
    is a hard error — a typo must not silently run the wrong board."""
    if lanes is None:
        return list(configs)
    by_lane = {c.lane: c for c in configs}
    unknown = sorted(set(lanes) - set(by_lane))
    if unknown:
        raise ValueError(f"unknown lane(s) {unknown}; available: {sorted(by_lane)}")
    return [by_lane[n] for n in lanes]


# Map an FSM state TRANSITION to the discrete mechanical event it represents, for the
# cam-timing telemetry (idea #15). Observe-only. Keyed by (prev_state, new_state) ->
# telemetry event name; the READY arrival closes the cycle. Since the 2026-07-19
# fw-timestamp replumb, edge-caused transitions (ball/SB/TA2/SA) are detected
# per-edge in _edge_observer and stamped with the FIRMWARE's 1 ms edge time via
# FwClock; poll/slow-input-caused transitions (table_start, bs) are caught by
# _observe at tick end with Pi time — those mixed-clock intervals carry no
# precision claim (see _edge_observer).
_STATE_EVENTS = {
    (State.READY,           State.SWEEP_TO_GUARD): "ball",         # SS / ball thrown
    (State.SWEEP_TO_GUARD,  State.GUARD_DELAY):    "cam:SB",       # sweep@66 guard
    (State.GUARD_DELAY,     State.TABLE_DETECT):   "table_start",  # settle done, table down
    (State.TABLE_DETECT,    State.RUNTHROUGH):     "cam:TA2",      # table@260, runthrough
    (State.RUNTHROUGH,      State.TABLE_FINISH):   "cam:SA",       # sweep@270 stop
    (State.TABLE_FINISH,    State.SPOTTING):       "bs",           # bin full -> spot
}

# States in which the relay-enable ARM must stay de-asserted (power-down rule §5).
DISARMED_STATES = (State.POWER_OFF, State.MANUAL_INTERVENTION, State.FAULT)

# Sanity bound on a FwClock-mapped edge time vs its Pi receive time. Events are
# drained within ~1 tick of receipt, so a legitimate mapping never strays more
# than transport jitter from t_pi. A bigger gap means the mapping used the
# WRONG timebase — e.g. an edge queued before a firmware reboot mapped through
# the post-boot offset (2026-07-19 review: that fed a timestamp off by the
# previous firmware uptime into the Welford baselines / drift alarms). Fall
# back to the Pi receive time instead.
FW_EST_MAX_SKEW_S = 2.0

# NE555 kick pulse width per tick. The kick pin must REST LOW so a stalled/frozen
# daemon (SIGSTOP, scheduler wedge, GC pause at the wrong moment) can never hold
# the line HIGH and permanently defeat the watchdog — the old toggle() left the
# pin latched HIGH 50% of the time. A bounded on->sleep->off pulse guarantees a
# frozen process leaves the pin LOW (or HIGH for at most one pulse width).
# CONFIRM @ bench (§12.9): 2 ms must discharge C11 through Q12+D15 (8a proved
# 50 ms works; 50 ms is NOT usable inline at 50 Hz). If 2 ms turns out too short
# the failure mode is fail-SAFE: the NE555 expires and drops the rail.
WDOG_PULSE_S = 0.002

# Consecutive tick() exceptions tolerated per board before that board alone is
# safety-tripped (safe_off + skipped); the healthy board keeps running. A tripped
# board also stops getting its NE555 kick -> its hardware rail drops by itself.
TICK_ERROR_BUDGET = 3

# Slow inputs the daemon edge-detects on the MCP and turns into FSM method calls.
# (Cams + ball arrive via the RP2040 link; grippers/GP are polled inside the FSM.)
#   name -> FSM action on a rising (asserted) edge
def _slow_actions(fsm, link):
    def _pbz():
        # Operator re-arm. FAULT-aware: PBZ in FAULT now recovers via the FSM
        # (FAULT -> MANUAL_INTERVENTION; second press -> READY). The firmware
        # fault latch is cleared ONLY when the FSM actually leaves FAULT, so the
        # two fault latches can never be made to disagree; the firmware fault
        # code is logged BEFORE it is cleared.
        was_fault = fsm.state is State.FAULT
        fw_flt = link.fault()
        fsm.first_ball_zero()
        if was_fault:
            if fsm.state is State.FAULT:
                fsm.io.log(f"L{fsm.lane}: PBZ in FAULT did not transition — "
                           f"firmware latch NOT cleared (flt={fw_flt!r})")
                return
            fsm.io.log(f"L{fsm.lane}: PBZ acknowledged FAULT (fw flt={fw_flt!r}) "
                       f"-> {fsm.state.value}; clearing firmware latch")
        link.clear()

    return {
        "PBZ":  _pbz,                                           # operator re-arm (+ FW CLEAR, gated)
        "BS":   fsm.bin_full,                                   # 10th pin to bin -> spot (fresh rack)
        "Foul": fsm.on_foul,                                    # Radaray foul beam
        # "PBC", "OS", "TENTH", "MAN_*" -> future (no FSM handler yet)
    }


@dataclass
class BoardConfig:
    lane: int
    i2c_bus: int        # /dev/i2c-N to this board's 3x MCP23017 (0x20/0x21/0x22)
    uart_port: str      # serial device to THIS board's RP2040 (115200 8N1)
    arm_pin: int        # Pi BCM GPIO -> relay-enable ARM for this board (HIGH=permit)
    wdog_pin: int       # Pi BCM GPIO -> this board's NE555 watchdog kick
    # AUX sensor role map for the diagnostics rules ({'AUX1': 'be_current',
    # 'AUX2': 'exit_beam', 'AUX3': 'dist_index'; rev-D boards add AUX4-11}).
    # None -> the WSL_DIAG_AUX_ROLES env applies. Sensors are NOT installed
    # yet, so the shipped default is UNMAPPED and every AUX rule stays dormant
    # (scope §4 shortlist lands here).
    aux_roles: dict = field(default=None)
    # PCB revision driving this lane — selects the IN-B channel map
    # (controller_io.IN_B_MAPS): rev-B/C = 8 GPA channels; rev-D adds the
    # AUX4-11 GPB bank. EXPLICIT per board (H3): the pilot rev-C board on
    # machine 22 and a future rev-D board can coexist in one daemon.
    board_rev: str = "revC"


# Per-pair Pi pin plan.  Source of truth: docs/phase8_channel_allocation.md §4
# ("Pi GPIO budget").  The two non-default devices below only EXIST once the Pi
# boot config is applied (2nd I2C bus via dtoverlay=i2c-gpio + a 2nd UART enabled)
# -> see docs/phase8_pi_provisioning.md for the exact config.txt + the full,
# deconflicted per-pin table.
#
# Per-field confidence:
#   FIRM     board-21 i2c_bus=1  -> Pi hardware I2C on GPIO2/3 (present on every Pi).
#   FIRM     board-21 wdog_pin=12 -> the existing, bench-validated kick pin
#            (lane_node.WATCHDOG_KICK_PIN / relay_cleanup.WATCHDOG_KICK_PIN).
#   CONFIRM  @ bench bring-up (spec 12.9): the 2nd I2C bus number + its i2c-gpio
#            SDA/SCL pins, BOTH RP2040 UART device names, the two arm GPIOs, and
#            per-board-vs-shared watchdog.  The values below are the *planned*
#            assignment -- free BCM pins chosen to avoid the INT lines (GPIO23/24/25/16)
#            and the 8a relay pins (GPIO23/24/25/27) -- NOT yet verified on the wired Pi.
DEFAULT_BOARDS = [
    # FIRM: i2c_bus=1 (Pi hw I2C, GPIO2/3) + wdog_pin=12 (existing bench-validated kick).
    BoardConfig(lane=21, i2c_bus=1, uart_port="/dev/ttyAMA0", arm_pin=26, wdog_pin=12),
    # CONFIRM: bus-3 = the dtoverlay=i2c-gpio bus; uart/arm/wdog are planned free pins.
    BoardConfig(lane=22, i2c_bus=3, uart_port="/dev/ttyAMA1", arm_pin=13, wdog_pin=6),
]


class BallReturnTracker:
    """Shared-exit-photoeye ball-return watch (target-conditions catalog §1.2).

    ONE exit beam per lane PAIR (the lift is shared via overrunning clutches);
    returns are matched FIFO within a lane and by learned transit time across
    the pair (see on_exit_pulse). Per-lane attribution per the CORRECTED §1.2 logic: one lane's
    returns dead while the pair-mate returns fine = the rudder side; BOTH dead
    = shared lift/belt/drive; no pair-mate evidence = unknown (single-lane
    pilot). ALERT-ONLY, bounded, thread-tolerant (its own lock; emitters are
    called OUTSIDE the lock and are enqueue-only).

    Wiring: each lane's LaneDiag registers itself via register(); on_ball()
    comes from that lane's cycle start, on_exit_pulse() from whichever board
    has the exit_beam AUX mapped. Dormant unless constructed (role unmapped)."""

    PENDING_MAX = 16   # bounded per-lane pending-ball memory

    def __init__(self, lanes, timeout_s=None):
        self.lanes = list(lanes)
        self.timeout_s = float(timeout_s if timeout_s is not None
                               else _env_float(BALL_RETURN_S_ENV, DEFAULT_BALL_RETURN_S))
        self._lock = threading.Lock()
        self._pending = {l: deque(maxlen=self.PENDING_MAX) for l in self.lanes}
        self._last_return = {l: None for l in self.lanes}
        self._last_missing = {l: None for l in self.lanes}
        self._warned = {l: False for l in self.lanes}
        self.missing_total = {l: 0 for l in self.lanes}
        self.returned_total = {l: 0 for l in self.lanes}
        self._transit_ewma = None   # learned typical throw->return transit (s)
        self._emitters = {}     # lane -> callable(detail_dict, t)

    def register(self, lane, emit_fn):
        self._emitters[lane] = emit_fn

    def on_ball(self, lane, t):
        with self._lock:
            dq = self._pending.get(lane)
            if dq is not None:
                dq.append(t)

    def on_exit_pulse(self, t):
        """One exit-beam pulse = one ball back; a stray pulse with nothing
        pending is ignored.

        Matching (2026-07-19 review): pure oldest-first across the pair
        INVERTED attribution in exactly the fault the rule exists to catch —
        a dead lane's stale pendings stole the healthy lane's pulses, so the
        dead lane looked healthy and the healthy lane got flagged
        'rudder_side'. Now: until a typical transit time is learned, oldest
        pending across the pair wins (FIFO — the only defensible cold-start
        rule); once matched returns have taught a transit EWMA, the pulse
        matches the lane whose oldest pending AGE is closest to that transit,
        so a lane whose balls stopped coming back ages out and alerts instead
        of silently absorbing the pair-mate's returns. Per-lane order stays
        FIFO. Attribution is still a heuristic (catalog §1.2: component
        attribution is human)."""
        with self._lock:
            best = None      # (key, lane, age) — smallest key wins
            for lane in self.lanes:
                dq = self._pending[lane]
                if not dq:
                    continue
                age = t - dq[0]
                key = (-age if self._transit_ewma is None
                       else abs(age - self._transit_ewma))
                if best is None or key < best[0]:
                    best = (key, lane, age)
            if best is None:
                return
            _, lane, age = best
            self._pending[lane].popleft()
            if 0 <= age <= self.timeout_s:
                self._transit_ewma = (age if self._transit_ewma is None
                                      else self._transit_ewma
                                      + 0.25 * (age - self._transit_ewma))
            self._last_return[lane] = t
            self.returned_total[lane] += 1
            self._warned[lane] = False   # healthy again -> re-arm the alert

    def poll(self, t):
        """Expire overdue pending balls; fire ONE 'ball_return_missing' alert per
        dead episode per lane (a successful return re-arms it). Never raises."""
        fired = []
        try:
            with self._lock:
                for lane in self.lanes:
                    dq = self._pending[lane]
                    newly = None
                    while dq and (t - dq[0]) > self.timeout_s:
                        newly = dq.popleft()
                        self.missing_total[lane] += 1
                        self._last_missing[lane] = t
                    if newly is None or self._warned[lane]:
                        continue
                    self._warned[lane] = True
                    others = [l for l in self.lanes if l != lane]
                    if any(self._last_return[o] is not None
                           and self._last_return[o] >= newly for o in others):
                        attribution = "rudder_side"    # pair-mate still returning
                    elif any(self._last_missing[o] is not None
                             and (t - self._last_missing[o]) <= 2 * self.timeout_s
                             for o in others):
                        attribution = "shared_lift"    # both lanes dead
                    else:
                        attribution = "unknown"        # no pair-mate evidence
                    fired.append((lane, {
                        "timeout_s": self.timeout_s,
                        "attribution": attribution,
                        "missing_total": self.missing_total[lane],
                    }))
            for lane, detail in fired:      # emit OUTSIDE the lock (enqueue-only)
                emit = self._emitters.get(lane)
                if emit is not None:
                    try:
                        emit(detail, t)
                    except Exception:
                        log.debug("BallReturnTracker emit swallowed", exc_info=True)
        except Exception:
            log.debug("BallReturnTracker.poll swallowed", exc_info=True)
        return fired


class LaneDiag:
    """Per-board diagnostics rules + event emission (scope §3.1, Phase 1).

    OBSERVE/ALERT-ONLY: nothing here touches a relay, ARM, the FSM, or the
    watchdog. Called from the tick, so every emission is an ENQUEUE
    (DiagWriter.emit -> put_nowait, never blocks); all real I/O happens on the
    DiagWriter/PlatformHealth threads. Every public method is catch-all
    guarded — a diagnostics bug degrades to a counted no-op (self.drops).

    Alert suppression (scope §6 alert-storm rule): manual-override activity
    (MAN_*/PBC/TENTH) opens a WSL_DIAG_SUPPRESS_MIN-minute window during which
    warn/fault-severity emissions are DOWNGRADED to info events tagged
    {'suppressed': true, 'orig_severity': ...} — the record survives (info
    logging continues), the desk alert does not. One continuous episode of
    manual activity suppresses for at most WSL_DIAG_SUPPRESS_MAX_MIN (a
    shorted/chattering manual opto must not blind the lane's alerts forever);
    crossing the cap emits a 'manual:suppress_cap' warn and re-enables alerts.

    AUX sensor rules are config-driven via aux_roles ({'AUX1': 'be_current',
    ...}); sensors are not installed yet, so every role defaults UNMAPPED and
    its rule stays fully dormant (no state, no events)."""

    def __init__(self, lane, *, writer=None, aux_roles=None):
        self.lane = lane
        self._writer = writer            # DiagWriter (or any .emit(ev) duck)
        self.aux_roles = dict(aux_roles or {})   # input name -> role
        self.ball_tracker = None
        self.suppress_until = 0.0        # monotonic deadline (io.now() domain)
        self.suppressed_count = 0
        self.emitted = 0
        self.drops = 0
        # rule state (all bounded, per-input scalars)
        self._prev_levels = {}           # name -> level (edge detection; first sight = baseline)
        self._assert_since = {}          # name -> t of the current continuous assert
        self._stuck_warned = set()
        self._beam_warned = set()
        # manual-override episode state (suppression cap + chatter throttle)
        self._manual_counts = {}         # input -> rising edges this episode
        self._manual_episode_start = None
        self._manual_last_seen = None    # t of the last tick with manual activity
        self._manual_cap_warned = False
        self._last_activity = None       # t of the last FSM transition (any)
        self._cycle_start_t = None
        self._be_deadline = None         # be_no_current window end
        self._be_quiet_warned = False
        self._be_stuck_warned = False
        self._dist_last_pulse = None
        self._dist_warned_cycle = False

    # ---- emission (enqueue-only; suppression-aware) ------------------------
    def emit_event(self, severity, event_type, code=None, detail=None, *, t=None):
        """Build + enqueue one DiagEvent. Never blocks, never raises; returns
        True only if the event reached the writer queue."""
        if not _env_on(DIAG_EVENTS_ENV):
            return False
        try:
            if t is None:
                t = time.monotonic()
            if severity != "info" and self.suppress_until and t < self.suppress_until:
                detail = dict(detail or {})
                detail["suppressed"] = True
                detail["orig_severity"] = severity
                severity = "info"
                self.suppressed_count += 1
                log.info("L%s: ALERT SUPPRESSED (mechanic window): %s %s",
                         self.lane, event_type, code or "")
            ev = make_event(self.lane, severity, event_type, code=code,
                            detail=detail)
            self.emitted += 1
            if self._writer is not None:
                return bool(self._writer.emit(ev))
            return False
        except Exception:
            self.drops += 1
            return False

    # ---- hooks from the board controller ----------------------------------
    def set_ball_tracker(self, tracker):
        self.ball_tracker = tracker
        tracker.register(
            self.lane,
            lambda detail, t: self.emit_event(
                "warn", "ball_return_missing", code="exit_beam",
                detail=detail, t=t))

    def note_activity(self, t):
        """Any FSM transition = cycle activity (feeds the BE stuck-running rule)."""
        self._last_activity = t

    def on_ball(self, t):
        """A cycle started (ball event)."""
        self._cycle_start_t = t
        self._dist_warned_cycle = False
        if self.ball_tracker is not None:
            self.ball_tracker.on_ball(self.lane, t)

    def note_cycle_complete(self, t):
        """Cycle finished -> READY. Opens the be_no_current watch window (the
        intentional ~30 s post-cycle BE run should show current inside it)."""
        if "be_current" in self.aux_roles.values():
            self._be_deadline = t + _env_float(BE_WINDOW_S_ENV, DEFAULT_BE_WINDOW_S)

    # ---- per-tick rule evaluation (enqueue-only, never raises) --------------
    def poll(self, t, *, ready, in_motion, slow_levels=None, inb_levels=None,
             diell_levels=None):
        if not _env_on(DIAG_EVENTS_ENV):
            return
        try:
            edges = self._track_levels(t, slow_levels, inb_levels)
            self._manual_rule(t, edges, slow_levels, inb_levels)
            self._stuck_rule(t, ready, slow_levels, inb_levels)
            self._beam_rule(t, ready, diell_levels)
            self._aux_rules(t, in_motion, edges, inb_levels)
        except Exception:
            self.drops += 1
            log.debug("L%s LaneDiag.poll swallowed", self.lane, exc_info=True)

    def _track_levels(self, t, slow_levels, inb_levels):
        """Merge the tick's level reads, update assert-since bookkeeping, and
        return the set of RISING edges. First sight of a name is a BASELINE,
        never an edge (mirrors the daemon's startup rule, review #28)."""
        rising = set()
        merged = {}
        for src in (slow_levels, inb_levels):
            if src:
                merged.update(src)
        for name, level in merged.items():
            level = bool(level)
            prev = self._prev_levels.get(name)
            if prev is not None and level and not prev:
                rising.add(name)
            self._prev_levels[name] = level
            if level:
                self._assert_since.setdefault(name, t)
            else:
                self._assert_since.pop(name, None)
                self._stuck_warned.discard(name)
        return rising

    def _manual_rule(self, t, rising, slow_levels, inb_levels):
        if not _env_on(MANUAL_RULE_ENV):
            return
        window_s = _env_float(SUPPRESS_MIN_ENV, DEFAULT_SUPPRESS_MIN) * 60.0
        max_s = _env_float(SUPPRESS_MAX_MIN_ENV, DEFAULT_SUPPRESS_MAX_MIN) * 60.0
        any_active = any(self._prev_levels.get(n) for n in MANUAL_INPUT_NAMES)
        if any_active:
            # Episode bookkeeping (2026-07-19 review): a quiet gap longer
            # than the suppress window since the last observed activity
            # starts a FRESH episode (fresh cap, fresh chatter counters).
            # A stuck/chattering input never goes quiet, so it stays ONE
            # episode and hits the cap below instead of suppressing forever.
            if (self._manual_episode_start is None
                    or (self._manual_last_seen is not None
                        and t - self._manual_last_seen > window_s)):
                self._manual_episode_start = t
                self._manual_cap_warned = False
                self._manual_counts.clear()
            self._manual_last_seen = t
        for name in MANUAL_INPUT_NAMES:
            if name in rising:
                # Log-scale per-input emission (1, 10, 100, ...): a
                # chattering MAN_* opto can rise at up to tick rate — one
                # event per edge would flood the JSONL/machine_events.
                n = self._manual_counts.get(name, 0) + 1
                self._manual_counts[name] = n
                if n in (1, 10, 100, 1000) or (n >= 10000 and n % 10000 == 0):
                    self.emit_event("info", "manual_override",
                                    code=f"manual:{name}",
                                    detail={"input": name, "count": n}, t=t)
        if not any_active or window_s <= 0:
            return
        # refresh while HELD, not just on the edge — the window ends
        # SUPPRESS_MIN after the mechanic's last observed activity — but
        # never past the per-episode cap.
        cap_end = (self._manual_episode_start + max_s) if max_s > 0 else None
        if cap_end is None or t < cap_end:
            new_until = max(self.suppress_until, t + window_s)
            if cap_end is not None:
                new_until = min(new_until, cap_end)
            self.suppress_until = new_until
        elif not self._manual_cap_warned:
            # Cap crossed with the input still active: the counter-alert.
            # suppress_until == cap_end <= t here, so this warn (and every
            # later warn/fault) passes through un-downgraded.
            self._manual_cap_warned = True
            held = [n for n in MANUAL_INPUT_NAMES if self._prev_levels.get(n)]
            self.emit_event(
                "warn", "manual_override", code="manual:suppress_cap",
                detail={"inputs": held,
                        "episode_s": round(t - self._manual_episode_start, 1),
                        "cap_min": round(max_s / 60.0, 1),
                        "stuck_suspected": True}, t=t)

    def _stuck_rule(self, t, ready, slow_levels, inb_levels):
        if not _env_on(STUCK_RULE_ENV) or not ready:
            return
        thr = _env_float(STUCK_S_ENV, DEFAULT_STUCK_S)
        for name, since in self._assert_since.items():
            if name in STUCK_EXEMPT or name.startswith("DIELL"):
                continue
            if name in self._stuck_warned:
                continue
            held = t - since
            if held > thr:
                self._stuck_warned.add(name)
                self.emit_event("warn", "stuck_input", code=f"input:{name}",
                                detail={"input": name,
                                        "held_s": round(held, 1),
                                        "threshold_s": thr}, t=t)

    def _beam_rule(self, t, ready, diell_levels):
        """DIELL beam statically blocked (a jammed pin/ball in the beam gives
        ONE edge, not cycling — scope §1 'stuck ball switch' row)."""
        if not _env_on(BEAM_RULE_ENV) or diell_levels is None:
            return
        thr = _env_float(BEAM_S_ENV, DEFAULT_BEAM_S)
        for name, level in diell_levels.items():
            level = bool(level)
            if level:
                self._assert_since.setdefault(name, t)
            else:
                self._assert_since.pop(name, None)
                self._beam_warned.discard(name)
                continue
            if not ready or name in self._beam_warned:
                continue
            held = t - self._assert_since[name]
            if held > thr:
                self._beam_warned.add(name)
                self.emit_event("warn", "beam_blocked", code=f"diell:{name}",
                                detail={"beam": name, "held_s": round(held, 1),
                                        "threshold_s": thr}, t=t)

    def _aux_rules(self, t, in_motion, rising, inb_levels):
        """Config-driven AUX sensor rules — fully dormant for unmapped roles."""
        if not _env_on(AUX_RULE_ENV) or not self.aux_roles:
            return
        levels = inb_levels or {}
        for name, role in self.aux_roles.items():
            level = bool(levels.get(name, False))
            if role == "be_current":
                self._be_rule(t, name, level)
            elif role == "exit_beam":
                if name in rising and self.ball_tracker is not None:
                    self.ball_tracker.on_exit_pulse(t)
            elif role == "dist_index":
                if name in rising:
                    self._dist_last_pulse = t
                self._dist_rule(t, in_motion)
        if self.ball_tracker is not None:
            self.ball_tracker.poll(t)

    def _be_rule(self, t, name, level):
        if level:
            # any BE current cancels the quiet watch + re-arms its alert
            self._be_deadline = None
            self._be_quiet_warned = False
            since = self._assert_since.get(name, t)
            # stuck-running: current flowing with NO cycle activity for the
            # whole threshold (post-cycle run-on is covered by note_activity —
            # the cycle that triggered it counts as activity at its start).
            quiet_since = max(since, self._last_activity or since)
            thr = _env_float(BE_STUCK_MIN_ENV, DEFAULT_BE_STUCK_MIN) * 60.0
            if (t - quiet_since) > thr and not self._be_stuck_warned:
                self._be_stuck_warned = True
                self.emit_event("fault", "be_stuck_running", code="aux:be_current",
                                detail={"running_s": round(t - since, 1),
                                        "quiet_s": round(t - quiet_since, 1)}, t=t)
        else:
            self._be_stuck_warned = False
            if self._be_deadline is not None and t > self._be_deadline:
                self._be_deadline = None
                if not self._be_quiet_warned:
                    self._be_quiet_warned = True
                    self.emit_event(
                        "warn", "be_no_current", code="aux:be_current",
                        detail={"window_s": _env_float(BE_WINDOW_S_ENV,
                                                       DEFAULT_BE_WINDOW_S)}, t=t)

    def _dist_rule(self, t, in_motion):
        if not in_motion or self._cycle_start_t is None or self._dist_warned_cycle:
            return
        gap = _env_float(DIST_GAP_S_ENV, DEFAULT_DIST_GAP_S)
        anchor = self._cycle_start_t
        if self._dist_last_pulse is not None:
            anchor = max(anchor, self._dist_last_pulse)
        if (t - anchor) > gap:
            self._dist_warned_cycle = True
            self.emit_event("warn", "dist_index_stall", code="aux:dist_index",
                            detail={"gap_s": round(t - anchor, 1),
                                    "threshold_s": gap}, t=t)


class PlatformHealth(threading.Thread):
    """Background platform-health emitter (scope Phase 1.6) + the off-tick pump
    for cam-telemetry baseline persistence. ALL file/subprocess I/O lives on
    THIS thread — never the tick. Absent-binary tolerant (a laptop/bench host
    without vcgencmd polls once, logs once, and stops trying). Daemon thread;
    stop() joins with a bounded timeout."""

    def __init__(self, boards, writer, *, poll_s=None, dir_path=None):
        super().__init__(name="platform-health", daemon=True)
        self.boards = list(boards)
        self.writer = writer
        self.poll_s = float(poll_s if poll_s is not None
                            else _env_float(PLATFORM_POLL_S_ENV, DEFAULT_PLATFORM_POLL_S))
        self.dir = (dir_path or os.environ.get("WSL_DIAG_DIR", "").strip()
                    or "./diag_logs")
        self.start_count = None
        self._lane = self.boards[0].cfg.lane if self.boards else 0
        self._stop_ev = threading.Event()
        self._vcgencmd_missing = False
        self._last_throttled = 0
        self.errors = 0

    def _emit(self, severity, event_type, code=None, detail=None):
        try:
            if self.writer is not None:
                self.writer.emit(make_event(self._lane, severity, event_type,
                                            code=code, detail=detail))
        except Exception:
            self.errors += 1

    def stop(self, timeout=5.0):
        try:
            self._stop_ev.set()
            if self.is_alive():
                self.join(timeout)
        except Exception:
            pass

    def run(self):
        try:
            self._count_service_start()
        except Exception:
            self.errors += 1
            log.debug("PlatformHealth service-start count swallowed", exc_info=True)
        while not self._stop_ev.is_set():
            try:
                self._poll_throttled()
            except Exception:
                self.errors += 1
            for b in self.boards:
                try:
                    b.telemetry.maybe_persist()
                except Exception:
                    self.errors += 1
            self._stop_ev.wait(self.poll_s)
        # final persistence flush on the way out (still off-tick)
        for b in self.boards:
            try:
                b.telemetry.stop()
            except Exception:
                pass

    def _count_service_start(self):
        """Increment the service-start counter file + emit 'service_restart'.
        Both past field incidents (missing watchdog kick, not-enabled systemd
        unit) would have shown up here first (scope §1 platform row)."""
        path = os.path.join(self.dir, "service_starts.json")
        count = 0
        try:
            with open(path, encoding="utf-8") as f:
                count = int(json.load(f).get("count", 0))
        except Exception:
            count = 0
        count += 1
        self.start_count = count
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"count": count, "last_start": _utc_now_iso()}, f)
            os.replace(tmp, path)
        except Exception:
            self.errors += 1
        self._emit("info", "service_restart", code="daemon_start",
                   detail={"count": count})

    def _poll_throttled(self):
        """`vcgencmd get_throttled` -> 'pi_undervoltage' warn on a nonzero,
        CHANGED bitmask (bit 0 undervoltage now, 16 undervoltage occurred...)."""
        if self._vcgencmd_missing:
            return
        try:
            out = subprocess.run(["vcgencmd", "get_throttled"],
                                 capture_output=True, timeout=2.0, text=True)
        except FileNotFoundError:
            self._vcgencmd_missing = True
            log.info("PlatformHealth: vcgencmd not present (non-Pi host) — "
                     "throttling poll disabled")
            return
        except Exception:
            self.errors += 1
            return
        try:
            txt = (out.stdout or "").strip()          # "throttled=0x50000"
            val = int(txt.split("=", 1)[1], 16)
        except Exception:
            return
        if val and val != self._last_throttled:
            self._emit("warn", "pi_undervoltage", code="get_throttled",
                       detail={"throttled": hex(val)})
        self._last_throttled = val


class BoardController:
    """One lane/board: link + io + FSM + the arm/watchdog GPIOs, plus the per-tick
    control logic. `sim=True` uses RecordingIO + a no-serial link so the assembly
    runs + self-tests off-Pi."""

    def __init__(self, cfg: BoardConfig, *, sim: bool = False, shadow=None,
                 cam_sink=None, diag_writer=None, cycle_shipper=None,
                 aux_roles=None, slow_debounce_n=None, fsm_debounce_n=None):
        self.cfg = cfg
        self.sim = sim
        self._wdog = None
        self._arm_led = None
        self.shadow = _shadow_enabled() if shadow is None else bool(shadow)

        # Flight recorder (idea #10): observe-only, bounded, default ON. Injected into
        # the io so every output change + arm is captured; dumped on a safety trip.
        self.recorder = FlightRecorder(cfg.lane)

        if sim:
            # The link shares the io's (fake, advanceable) clock so fw-estimated
            # edge times and Pi-side telemetry times live on ONE timebase — the
            # lambda resolves self.io lazily (io is built on the next line).
            self.link = RP2040Link(now=lambda: self.io.now())
            self.io = RecordingIO(rp2040=self.link, recorder=self.recorder,
                                  board_rev=cfg.board_rev)
        else:
            from gpiozero import LED                       # lazy: Pi-only
            self._arm_led = LED(cfg.arm_pin)               # de-asserted by default
            self._wdog = LED(cfg.wdog_pin)
            self.link = RP2040Link(port=cfg.uart_port)
            self.io = MachineIO(
                cfg.lane, cfg.i2c_bus, rp2040=self.link,
                watchdog_kick=self._kick_wdog,             # poll() calls this
                arm_relays=self._set_arm,
                recorder=self.recorder,
                board_rev=cfg.board_rev,
            )
            self.link.start()                              # background serial reader

        # SHADOW/CANARY SOAK (idea #11): wrap the real io so the FSM drives NOTHING.
        # The wrapper records every command the FSM WOULD have issued and hard-holds
        # the real ARM LOW. Shadow is OPT-IN (env gate, default off) — a run WITHOUT
        # it is LIVE on wired hardware; see the mode banner in main() (review #52).
        if self.shadow:
            self.io = ShadowIO(self.io, recorder=self.recorder)
            log.warning("L%s: SHADOW MODE active (%s set) — FSM runs on real inputs but "
                        "drives NOTHING; ARM hard-held LOW", cfg.lane, SHADOW_ENV)

        # Diagnostics event pipe (2026-07-19 scope): per-lane rules + suppression
        # over the shared DiagWriter. writer=None (sim/tests default) keeps the
        # rules running but emission local-only; main() wires the real writer.
        roles = aux_roles
        if roles is None:
            roles = cfg.aux_roles if cfg.aux_roles is not None \
                else _parse_aux_roles(os.environ.get(AUX_ROLES_ENV))
        self.diag = LaneDiag(cfg.lane, writer=diag_writer, aux_roles=roles)
        self.shipper = cycle_shipper       # CycleShipper (or None): machine_cycles rows

        # Cam-timing telemetry (idea #15): observe-only, bounded. Fed per cam EDGE
        # (fw 1 ms timestamps via FwClock — see _edge_observer) plus the poll-driven
        # transitions the daemon holds. Shares the flight recorder so timing rows +
        # drift land in dumps too; drift alarms also route into the diagnostics
        # event pipe (enqueue-only). Baselines persist across restarts on real
        # hardware (Phase 1.7) — the PlatformHealth thread pumps the file writes.
        self.telemetry = CamTelemetry(
            cfg.lane, recorder=self.recorder, sink=cam_sink,
            persist=not sim,
            diag_emit=lambda sev, et, code, detail: self.diag.emit_event(
                sev, et, code=code, detail=detail, t=self.io.now()))

        self.fsm = CycleController(cfg.lane, self.io)
        # FSM diagnostics hook (wave-1 R3): unexpected-edge observations ->
        # info events. Enqueue-only (it runs inside the daemon tick); fault
        # kinds are skipped here — _on_safety_trip owns the fault emission.
        self.fsm.on_diag = self._on_fsm_diag
        self.fsm.power_restore()                           # power-down rule: come up disarmed
        self._prev_state = self.fsm.state                  # for telemetry transition edges
        self._actions = _slow_actions(self.fsm, self.link)
        # Baseline the slow-input edge detector from the ACTUAL input levels at
        # startup (review #28): an input already asserted when the daemon comes
        # up (stuck/shorted/miswired PBZ, inverted polarity) must NEVER be
        # synthesized into a rising edge on tick 1 — a phantom PBZ would walk
        # MANUAL_INTERVENTION -> READY and auto-arm the lane on every restart,
        # defeating the power-down rule the systemd auto-restart policy relies
        # on. Only a transition OBSERVED while running counts as an edge; an
        # initially-asserted input is logged LOUDLY and must deassert then
        # re-assert to act. A read failure here propagates -> _build_boards
        # skips the board (never ticked, NE555 never kicked = fail-safe).
        # Sim rigs (RecordingIO.slow starts empty) baseline all-False as before.
        # _watched extends the FSM inputs with PBC (manual-override visibility —
        # it has no FSM action, only the diagnostics rules consume it).
        self._watched = list(self._actions) + ["PBC"]
        # Stable-time debounce (H3, 2026-07-21): two knobs, read at
        # construction (debouncers hold per-input state, so a restart applies
        # a new value). Constructor args beat env (tests); see the env-block
        # comment up top for the safety-path flag on the FSM knob.
        self._diag_deb_n = (int(slow_debounce_n) if slow_debounce_n is not None
                            else _env_int(SLOW_DEBOUNCE_ENV,
                                          DEFAULT_SLOW_DEBOUNCE_N))
        self._fsm_deb_n = (int(fsm_debounce_n) if fsm_debounce_n is not None
                           else _env_int(SLOW_DEBOUNCE_FSM_ENV,
                                         DEFAULT_SLOW_DEBOUNCE_FSM_N))
        if self._fsm_deb_n > 1:
            log.warning("L%s: FSM slow-input debounce ACTIVE (n=%d, ~%d ms) — "
                        "PBZ/BS/Foul edges lag the physical edge; this is a "
                        "deliberate bench-signed-off safety-path change (%s)",
                        cfg.lane, self._fsm_deb_n, self._fsm_deb_n * 20,
                        SLOW_DEBOUNCE_FSM_ENV)
        self._prev_slow = {}
        self._fsm_deb = {}
        self._diag_deb = {}     # lazily per-name (IN-A watched + IN-B channels)
        for name in self._watched:
            cur = bool(self.io.read_input(name))
            if cur:
                log.error("L%s: slow input %r ALREADY ASSERTED at daemon start "
                          "(stuck button / miswire / inverted polarity?) — NO edge "
                          "synthesized; it must deassert then re-assert to act",
                          cfg.lane, name)
            self._prev_slow[name] = cur
            # baseline the debouncers from the same startup read (no edge)
            self._fsm_deb[name] = SlowDebounce(self._fsm_deb_n, initial=cur)
            self._diag_deb[name] = SlowDebounce(self._diag_deb_n, initial=cur)
        self._maxrun_refused = False   # review #30: one-time log latch for the arm refusal
        self._was_healthy = True
        self._prev_arm = False     # rail_drop emitter: last commanded arm value
        # machine_cycles row bookkeeping (assembled at cycle completion, shipped
        # via the CycleShipper thread — scope §2 schema)
        self._cycle_open = False
        self._cycle_started_utc = None
        self._cycle_ball = None
        self.failed = False        # set by run() when TICK_ERROR_BUDGET is exhausted
        self.tick_errors = 0       # consecutive tick() exceptions (reset on success)

    # ---- real-hardware GPIO callbacks -------------------------------------
    def _kick_wdog(self):
        if self._wdog is not None:
            # Bounded pulse, resting LOW (see WDOG_PULSE_S). Never toggle(): a
            # stall with the pin latched HIGH would defeat the NE555 forever.
            self._wdog.on()
            time.sleep(WDOG_PULSE_S)
            self._wdog.off()

    def _set_arm(self, on):
        if self._arm_led is not None:
            self._arm_led.value = 1 if on else 0

    # ---- per-tick control logic -------------------------------------------
    def _slow_edges(self):
        """Read the watched IN-A slow inputs, fire FSM actions on rising edges,
        and return this tick's RAW {name: level} so the diagnostics rules reuse
        the SAME reads (no duplicate I²C traffic; _diag_poll applies the
        diagnostics-path debounce to these raw levels).

        FSM action edges go through the FSM debouncer — n=1 by default, which
        is EXACT legacy raw behavior; see SLOW_DEBOUNCE_FSM_ENV (safety-path
        semantics only change when that knob is deliberately raised)."""
        levels = {}
        for name in self._watched:
            raw = bool(self.io.read_input(name))
            levels[name] = raw
            cur = self._fsm_deb[name].update(raw)          # n=1 -> cur == raw
            action = self._actions.get(name)
            if action is not None and cur and not self._prev_slow[name]:
                action()                                   # rising (debounce-stable) edge
            self._prev_slow[name] = cur
        return levels

    def tick(self):
        healthy = self.link.health_ok()

        if not healthy:
            # RP2040 unhealthy: RP_OK has already dropped the HARDWARE rail. Make it a real
            # SOFTWARE safety trip too — force motion outputs OFF (clears the relay latches)
            # and latch the FSM into MANUAL_INTERVENTION so recovery REQUIRES a deliberate
            # First-Ball-Zero. Without this, a heartbeat blip drops ARM while sweep is still
            # latched, then silently re-arms with the stale latch -> uncommanded motion.
            if self._was_healthy:
                self.io.log(f"L{self.cfg.lane}: RP2040 link LOST "
                            f"(fault={self.link.fault()!r} alive={self.link.is_alive()} "
                            f"rp_ok={self.link.rp_ok()}) -> SAFETY TRIP: motors off, require First-Ball-Zero")
                self.fsm.power_restore()      # _all_motors_off() (clears latches) + MANUAL_INTERVENTION
                self._on_safety_trip("rp2040_link_lost")   # flight-recorder dump (observe-only)
            self._was_healthy = False
            self._note_arm(False, "rp2040_link_unhealthy")
            self.io.arm(False)
            self.link.apply_events(self.fsm, self._edge_observer)  # drain; FSM ignores when not READY
            self.fsm.poll()                   # keep kicking the NE555 (the Pi itself is alive)
            self._observe()                   # instrumentation (idea #10/#15): never affects control
            return

        if not self._was_healthy:
            self.io.log(f"L{self.cfg.lane}: RP2040 link recovered -> awaiting First-Ball-Zero")
        self._was_healthy = True

        self.link.apply_events(self.fsm, self._edge_observer)  # cam/ball -> FSM (single-threaded here)
        slow_levels = self._slow_edges()      # PBZ/BS/Foul -> FSM (+ levels for diagnostics)
        self.fsm.poll()                       # advance FSM + kick NE555 via io
        # Arm gate (review #30): a KNOWN firmware/FSM max-run desync (firmware
        # maxrun_ms below the FSM's MAX_MOTION_S) means the firmware backstop
        # would kill legitimate motions mid-cycle — REFUSE to arm until the
        # constants are reconciled, exactly as maxrun_ok()'s contract specifies.
        # Unknown (v0.1.0 firmware / sim) returns True, so behavior is unchanged
        # unless a desync is positively known. Safe direction = refuse.
        want_arm = self.fsm.state not in DISARMED_STATES
        if want_arm:
            mr_ok = self.link.maxrun_ok()
            if not mr_ok and not self._maxrun_refused:
                log.error("L%s: REFUSING to arm — firmware maxrun_ms=%s is below the "
                          "FSM's MAX_MOTION_S (constants desynchronized; reconcile + "
                          "reflash before arming)", self.cfg.lane, self.link.maxrun_ms())
            elif mr_ok and self._maxrun_refused:
                log.info("L%s: max-run ceiling reconciled — arm no longer refused",
                         self.cfg.lane)
            self._maxrun_refused = not mr_ok
            want_arm = mr_ok
        reason = None
        if not want_arm:
            reason = (("fsm_" + self.fsm.state.value)
                      if self.fsm.state in DISARMED_STATES
                      else ("maxrun_desync" if self._maxrun_refused else "unknown"))
        self._note_arm(want_arm, reason)
        self.io.arm(want_arm)
        self._observe()                       # instrumentation (idea #10/#15): never affects control
        self._diag_poll(slow_levels)          # diagnostics rules (enqueue-only, never raises)

    # ---- instrumentation (OBSERVE-ONLY; idea #10 flight recorder + #15 cam timing) --
    def _edge_observer(self, kind, ident, t_fw, t_pi):
        """Called by link.apply_events AFTER each cam/ball dispatch (still the
        tick thread — everything downstream is enqueue-only). Detects the FSM
        transition the edge just caused and timestamps it with the FIRMWARE's
        1 ms edge time mapped through FwClock (falling back to the Pi receive
        time on v0.1.0 lines / a cold clock).

        CLOCK-DOMAIN NOTE (scope Phase 1.1): only the pure-edge intervals
        (ss_to_guard, ta2_to_sa, sa_to_ta1zero — both endpoints fw-stamped)
        gain the ~1 ms resolution. Intervals anchored on a Pi-issued command
        or MCP slow input (guard_to_table, table_to_ta2, bs_to_ta1zero —
        table_start/bs are stamped io.now() in _observe) MIX the two clocks and
        carry NO precision claim beyond the daemon's ~20 ms tick."""
        t = None
        if t_fw is not None:
            t = self.link.fw_clock.est_pi_time(t_fw)
            # Reboot-resync race guard: a stale-timebase t_fw mapped through
            # a freshly-retrained offset lands far from the receive time —
            # clamp to the Pi receive time (see FW_EST_MAX_SKEW_S).
            if (t is not None and t_pi is not None
                    and abs(t - t_pi) > FW_EST_MAX_SKEW_S):
                t = None
        if t is None:
            t = t_pi
        new = self.fsm.state
        if new is not self._prev_state:
            self._handle_transition(self._prev_state, new, t)

    def _observe(self):
        """Post-tick observation: catch the transitions NOT caused by a queued
        cam/ball edge (poll-driven table_start / motion timeouts, slow-input BS,
        PBZ recovery), Pi-tick timestamped. Drives NOTHING and never raises into
        the control loop."""
        try:
            new = self.fsm.state
            if new is not self._prev_state:
                self._handle_transition(self._prev_state, new, self.io.now())
        except Exception:
            log.debug("L%s observe() swallowed", self.cfg.lane, exc_info=True)

    def _handle_transition(self, prev, new, t):
        """One FSM state transition (from the edge observer at fw-edge time, or
        from _observe at tick time): flight-recorder timeline, cam-timing
        telemetry, cycle-row assembly, fault dump. Observe-only, never raises."""
        try:
            self._prev_state = new
            # 1) record the transition in the flight recorder (forensics timeline)
            self.recorder.record("state", new.value, prev.value)
            self.diag.note_activity(t)
            # 2) cam-timing telemetry: map the transition to a discrete event
            ev = _STATE_EVENTS.get((prev, new))
            if ev is not None:
                self.telemetry.on_event(ev, t)
                if ev == "ball":
                    self._cycle_open = True
                    self._cycle_started_utc = _utc_now_iso()
                    self._cycle_ball = getattr(self.fsm.ball, "value", None)
                    self.diag.on_ball(t)
            # 3) cycle boundary: arriving back at READY finalizes the cycle's intervals
            if new is State.READY and prev not in (State.MANUAL_INTERVENTION, State.POWER_OFF):
                durations = self.telemetry.end_cycle()
                self.diag.note_cycle_complete(t)
                self._ship_cycle("READY", durations=durations)
            # 3b) aborted cycle: a FAULT / safety trip / power-off abandons the
            # cycle mid-flight, and its recovery path (MANUAL_INTERVENTION ->
            # READY) is excluded from end_cycle above — discard the open
            # intervals WITHOUT folding, so a stale 'ball' timestamp can't fold
            # a minutes-long garbage sample into the drift baselines (observe-only).
            elif new in (State.FAULT, State.MANUAL_INTERVENTION, State.POWER_OFF):
                self.telemetry.abort_cycle()
                self._ship_cycle("FAULT" if new is State.FAULT
                                 else "MANUAL_INTERVENTION", aborted=True)
            # 4) FAULT entry: dump the black box (best-effort)
            if new is State.FAULT and prev is not State.FAULT:
                self._on_safety_trip("fsm_fault")
        except Exception:
            log.debug("L%s _handle_transition swallowed", self.cfg.lane,
                      exc_info=True)

    def _ship_cycle(self, final_state, durations=None, aborted=False):
        """Assemble one machine_cycles row (scope §2 schema) and offer it to the
        CycleShipper — offer() is put_nowait; the HTTP POST happens on the
        shipper thread, never here. No-op when no cycle is open / no shipper."""
        if not self._cycle_open:
            return
        self._cycle_open = False
        if self.shipper is None:
            return
        try:
            row = {
                "lane_id": self.cfg.lane,
                "final_state": final_state,
                "cycle_type": "ball",
                "started_at": self._cycle_started_utc,
                "ended_at": _utc_now_iso(),
                "ball": self._cycle_ball,
                "aborted": bool(aborted),
                "gs_mask": getattr(self.fsm, "pins", None),
                "shadow": bool(self.shadow),
            }
            fw = self.link.fw_version()
            if fw:
                row["fw_version"] = fw
            for name, secs in (durations or {}).items():
                row[f"{name}_ms"] = int(round(secs * 1000.0))
            self.shipper.offer(row)
        except Exception:
            log.debug("L%s _ship_cycle swallowed", self.cfg.lane, exc_info=True)

    def _note_arm(self, want, reason):
        """rail_drop emitter: the daemon KNOWS the rail is about to drop when it
        deasserts ARM (Pi-visible facts only — no new hardware taps). Emits on
        the asserted->deasserted transition; updates the tracker."""
        try:
            if self._prev_arm and not want:
                self.diag.emit_event(
                    "info", "rail_drop", code="arm_drop",
                    detail={"reason": reason,
                            "fsm_state": getattr(self.fsm.state, "value", "?"),
                            "fw_fault": self.link.fault(),
                            "rp_ok": self.link.rp_ok()},
                    t=self.io.now())
            self._prev_arm = bool(want)
        except Exception:
            log.debug("L%s _note_arm swallowed", self.cfg.lane, exc_info=True)

    def _debounce_for_diag(self, levels):
        """Apply the diagnostics-path stable-time debounce (H3) to a raw
        {name: level} dict. Per-input SlowDebounce state is created on first
        sight, BASELINED to the first observed level (never an edge — the
        review-#28 startup rule extended to every diagnostics input)."""
        if levels is None:
            return None
        out = {}
        for name, raw in levels.items():
            deb = self._diag_deb.get(name)
            if deb is None:
                deb = self._diag_deb[name] = SlowDebounce(self._diag_deb_n,
                                                          initial=raw)
            out[name] = deb.update(raw)
        return out

    def _diag_poll(self, slow_levels):
        """Feed this tick's levels to the diagnostics rules. IN-B is 1-2 extra
        I²C register reads; a failing IN-B read is swallowed (diagnostics must
        never trip the lane — observe-only). All MCP-sampled levels pass the
        stable-time debounce (WSL_SLOW_DEBOUNCE_N consecutive 50 Hz samples)
        before any rule sees them; DIELL levels arrive pre-sampled from the
        firmware heartbeat and feed a 30 s-threshold rule, so they are used
        as-is."""
        try:
            inb = None
            reader = getattr(self.io, "read_inputs_b", None)
            if reader is not None:
                try:
                    inb = reader()
                except Exception:
                    log.debug("L%s IN-B read failed (diagnostics skipped)",
                              self.cfg.lane, exc_info=True)
            diell = None
            lv = self.link.input_levels()
            if lv:
                diell = {k: lv[k] for k in ("DIELL_L", "DIELL_R") if k in lv}
            self.diag.poll(self.io.now(),
                           ready=self.fsm.state is State.READY,
                           in_motion=self.fsm.state in MOTION_STATES,
                           slow_levels=self._debounce_for_diag(slow_levels),
                           inb_levels=self._debounce_for_diag(inb),
                           diell_levels=diell)
        except Exception:
            log.debug("L%s _diag_poll swallowed", self.cfg.lane, exc_info=True)

    def _on_fsm_diag(self, event):
        """Wave-1 FSM on_diag hook. Runs INSIDE the tick (synchronous from the
        FSM) — bounded-queue enqueue only, never raises. unexpected_edge
        observations are emitted log-scale (count 1, 10, 100, ...) so the
        routine dual-lobe artifact keys can't flood the pipe; fault kinds are
        skipped here (_on_safety_trip owns the structured fault emission)."""
        try:
            if event.get("kind") != "unexpected_edge":
                return
            n = int(event.get("count", 1))
            if n == 1 or (n > 1 and n in (10, 100, 1000)) or (n >= 10000 and n % 10000 == 0):
                self.diag.emit_event(
                    "info", "unexpected_edge",
                    code=f"{event.get('event')}:{event.get('state')}",
                    detail={"count": n}, t=event.get("t"))
        except Exception:
            pass

    def _on_safety_trip(self, reason):
        """Flush the flight recorder on a safety trip / fault. Best-effort, bounded,
        never raises. Captures FSM state + the firmware fault for the dump context.
        dump_async (review #21/#54): the snapshot copy happens here (microseconds);
        the disk write runs on a writer thread — an SD-card stall during one
        board's dump must not freeze the shared tick loop (the OTHER lane's cam
        dispatch, fsm.poll() backstops and NE555 kick)."""
        try:
            self.recorder.dump_async(reason=reason, extra={
                "fsm_state": getattr(self.fsm.state, "value", "?"),
                "fsm_cycle": getattr(getattr(self.fsm, "cycle", None), "value", None),
                "fsm_ball": getattr(getattr(self.fsm, "ball", None), "name", None),
                "fw_fault": self.link.fault(),
                "rp_ok": self.link.rp_ok(),
                "shadow": self.shadow,
            })
        except Exception:
            log.debug("L%s _on_safety_trip swallowed", self.cfg.lane, exc_info=True)
        # Diagnostics events for the trip (scope §3.1: this is the single choke
        # point every fault path funnels through). Enqueue-only, never raises.
        try:
            t = self.io.now()
            fw_flt = self.link.fault()
            if reason == "fsm_fault":
                lf = self.fsm.last_fault or {}
                self.diag.emit_event("fault", "fsm_fault",
                                     code=lf.get("code"),
                                     detail={"why": lf.get("why"),
                                             "state": lf.get("state")}, t=t)
            elif reason == "rp2040_link_lost":
                self.diag.emit_event("fault", "link_lost", code=fw_flt or None,
                                     detail={"alive": self.link.is_alive(),
                                             "rp_ok": self.link.rp_ok()}, t=t)
                if fw_flt == REBOOT_FAULT:
                    et = ("rp2040_wdt_reset" if self.link.boot_wdt_reset()
                          else "fw_reboot")
                    self.diag.emit_event("fault", et, code=fw_flt, t=t)
                elif fw_flt:
                    # explicit firmware fault (motion_timeout / chatter / ...)
                    self.diag.emit_event("fault", "fw_fault", code=fw_flt, t=t)
            elif reason == "tick_error_budget":
                self.diag.emit_event(
                    "fault", "rail_drop", code="tick_error_budget",
                    detail={"reason": "tick error budget exhausted; NE555 kick "
                                      "stops for this board"}, t=t)
        except Exception:
            log.debug("L%s _on_safety_trip diag emit swallowed", self.cfg.lane,
                      exc_info=True)

    # ---- shutdown ----------------------------------------------------------
    def safe_off(self):
        # FIRST: force the NE555 kick pin LOW (review #26). _kick_wdog is
        # on() -> sleep -> off(); if the exception that tripped this board fired
        # between on() and off() (the same GPIO-write fault class that exhausts
        # the error budget), the pad latches HIGH and level-holds the NE555
        # alive forever — a tripped board inside a still-running daemon never
        # reaches controller_cleanup.py, so this is the only place to drop it.
        for step in (
            lambda: self._wdog.off() if self._wdog is not None else None,
            lambda: self.io.arm(False),
            lambda: self.io.all_off() if hasattr(self.io, "all_off") else None,
            self.link.stop_all,
            self.link.close,
        ):
            try:
                step()
            except Exception as e:
                log.warning("L%s shutdown step failed: %s", self.cfg.lane, e)


def run(boards, hz: float = 50.0):
    """Tick loop. Returns the process exit code: 0 on an operator stop
    (SIGTERM/SIGINT), 1 when ALL boards safety-tripped — the unit is
    Restart=on-failure, so only a NONZERO exit gets the promised systemd
    restart (review #27; matches the D3 zero-boards return 1)."""
    period = 1.0 / hz
    stop = {"flag": False}
    rc = 0

    def _sig(_signum, _frame):
        stop["flag"] = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    log.info("controller_daemon up: lanes=%s @ %.0f Hz", [b.cfg.lane for b in boards], hz)
    try:
        while not stop["flag"]:
            t0 = time.monotonic()
            for b in boards:
                # Per-board fault isolation: a transient I2C/serial exception on
                # one board must not crash the daemon and safety-trip BOTH lanes.
                # On budget exhaustion, trip ONLY this board (safe_off + skip;
                # its NE555 kick stops too, so its hardware rail drops by itself)
                # and keep the healthy board running.
                if b.failed:
                    continue
                try:
                    b.tick()
                    b.tick_errors = 0
                except Exception as e:
                    b.tick_errors += 1
                    log.exception("L%s tick raised (%d/%d consecutive)",
                                  b.cfg.lane, b.tick_errors, TICK_ERROR_BUDGET)
                    # flight recorder: capture the exception in the timeline (observe-only)
                    try:
                        b.recorder.record("tick_error", type(e).__name__, str(e)[:120])
                    except Exception:
                        pass
                    # C-02 (hw-independence audit 2026-07-09): fail safe on the FIRST
                    # I/O exception, not the third. A failed write may have desynced
                    # commanded vs physical output state, so treat all software output
                    # state as invalid: motors off + MANUAL_INTERVENTION (recovery
                    # requires a deliberate First-Ball-Zero) + ARM dropped. A bare
                    # arm(False) is not enough — the next healthy tick would re-arm
                    # from FSM state with possibly-stale latches.
                    try:
                        b.fsm.power_restore()
                        b.io.arm(False)
                    except Exception:
                        log.exception("L%s post-exception safe-state attempt raised "
                                      "(budget/trip path still runs)", b.cfg.lane)
                    if b.tick_errors >= TICK_ERROR_BUDGET:
                        log.error("L%s tick error budget exhausted -> SAFETY TRIP "
                                  "this board (outputs off, ARM dropped, kick stops); "
                                  "other board continues", b.cfg.lane)
                        b._on_safety_trip("tick_error_budget")   # dump black box
                        b.failed = True
                        b.safe_off()
            if all(b.failed for b in boards):
                log.error("ALL boards safety-tripped -> exiting 1 "
                          "(Restart=on-failure restarts only on nonzero)")
                rc = 1
                break
            dt = time.monotonic() - t0
            if dt < period:
                time.sleep(period - dt)
    finally:
        # Stop kicking (loop already exiting) -> NE555 drops the rail; plus explicit safe-off.
        log.info("controller_daemon shutting down -> safe-off all boards")
        for b in boards:
            b.safe_off()
        # After safe-off: give any in-flight async black-box writers a moment to
        # land before the process (and its daemon threads) dies. Observe-only.
        for b in boards:
            try:
                b.recorder.flush(timeout=2.0)
            except Exception:
                pass
        # Final telemetry-baseline save (Phase 1.7). Runs AFTER the loop has
        # exited — no tick can be stalled by this file write; deliberately NOT
        # in safe_off (a tripped board's safe_off runs inline in the loop and a
        # file write there could stall the healthy board's NE555 kicks).
        for b in boards:
            try:
                b.telemetry.stop()
            except Exception:
                pass
    return rc


def _build_boards(configs, *, diag_writer=None, cycle_shipper=None):
    """Construct a BoardController per config, isolating open failures (D3): a
    board whose hardware won't open (missing I2C bus / UART on a partial bench
    rig) is logged LOUDLY and skipped. A skipped board is never ticked -> its
    NE555 never gets kicked -> its safety rail stays down = fail-safe by hardware."""
    boards = []
    for cfg in configs:
        try:
            boards.append(BoardController(cfg, diag_writer=diag_writer,
                                          cycle_shipper=cycle_shipper))
        except Exception:
            log.exception("L%s: board bring-up FAILED (i2c_bus=%s uart=%s) -> SKIPPED; "
                          "never ticked, NE555 never kicked, rail stays down (fail-safe)",
                          cfg.lane, cfg.i2c_bus, cfg.uart_port)
    return boards


def _wire_pair_diagnostics(boards):
    """Share ONE BallReturnTracker across the pair when any board maps an
    exit_beam AUX (the exit photoeye is one per PAIR — catalog §1.2). Every
    lane registers its emitter so per-lane attribution alerts land on the
    right lane regardless of which board carries the sensor. Returns the
    tracker, or None (roles unmapped -> rule fully dormant)."""
    if not any("exit_beam" in b.diag.aux_roles.values() for b in boards):
        return None
    tracker = BallReturnTracker([b.cfg.lane for b in boards])
    for b in boards:
        b.diag.set_ball_tracker(tracker)
    return tracker


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 8b Track-B controller daemon (skeleton)")
    ap.add_argument("--selftest", action="store_true", help="run the off-hardware assembly self-test and exit")
    ap.add_argument("--hz", type=float, default=50.0, help="control loop rate")
    ap.add_argument("--lanes", default=None,
                    help=f"comma-separated lane subset (e.g. '21'); overrides {LANES_ENV}; "
                         "default = all of DEFAULT_BOARDS")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.selftest:
        return _selftest()

    # LIVE/SHADOW mode banner (review #52): one unmissable line BEFORE any
    # hardware is opened. Shadow is opt-in; a run without WSL_CONTROLLER_SHADOW
    # IS live on wired hardware — the banner makes that explicit every start.
    if _shadow_enabled():
        log.warning("=== MODE: SHADOW (%s set) — FSM runs on real inputs; outputs "
                    "are record-only, ARM hard-held LOW; no relay can energize ===",
                    SHADOW_ENV)
    elif _live_acknowledged():
        log.warning("=== MODE: LIVE (%s acknowledged) — outputs DRIVE REAL RELAYS "
                    "on wired hardware ===", LIVE_ENV)
    else:
        log.warning("=== MODE: LIVE **BY DEFAULT** — outputs DRIVE REAL RELAYS on "
                    "wired hardware. Set %s=1 to acknowledge a deliberate live run, "
                    "or %s=1 for a no-actuation shadow soak ===",
                    LIVE_ENV, SHADOW_ENV)

    spec = args.lanes if args.lanes is not None else os.environ.get(LANES_ENV)
    try:
        configs = _select_boards(DEFAULT_BOARDS, _parse_lanes(spec))
    except ValueError as e:
        log.error("bad lane selection %r: %s", spec, e)
        return 1

    # Diagnostics stack (2026-07-19 scope §3): one shared DiagWriter thread
    # (JSONL always; HTTP when WSL_DIAG_SERVER_URL is set), a CycleShipper for
    # machine_cycles rows, and the PlatformHealth thread. All optional + env-
    # killable; boards run identically with the whole stack absent.
    diag_writer = None
    cycle_shipper = None
    platform = None
    if _env_on(DIAG_EVENTS_ENV):
        diag_writer = DiagWriter()          # WSL_DIAG_ENABLED gates internally
        diag_writer.start()
        http = next((s for s in diag_writer.sinks
                     if isinstance(s, HttpSink) and s.enabled), None)
        if http is not None:
            cycle_shipper = CycleShipper(http.post_cycle)
            cycle_shipper.start()

    boards = _build_boards(configs, diag_writer=diag_writer,
                           cycle_shipper=cycle_shipper)         # real hardware
    if not boards:
        log.error("ZERO boards came up (requested lanes=%s) -> exiting 1",
                  [c.lane for c in configs])
        if diag_writer is not None:
            diag_writer.stop()
        if cycle_shipper is not None:
            cycle_shipper.stop()
        return 1
    _wire_pair_diagnostics(boards)
    if diag_writer is not None and _env_on(PLATFORM_ENV):
        platform = PlatformHealth(boards, diag_writer)
        platform.start()

    try:
        return run(boards, hz=args.hz)   # nonzero on all-boards-tripped (review #27)
    finally:
        # background diagnostics threads drain + flush on the way out
        if platform is not None:
            platform.stop()
        if cycle_shipper is not None:
            cycle_shipper.stop()
        if diag_writer is not None:
            diag_writer.stop()


# --------------------------------------------------------------------------
# Off-hardware self-test: assemble in sim mode + drive a full strike cycle
# entirely through the daemon's tick() (RP2040 events + MCP slow inputs).
# --------------------------------------------------------------------------
def _selftest():
    from cycle_control_8270 import Cycle, Ball, TIME_DELAY_S
    n = {"c": 0, "f": 0}

    def chk(cond, msg):
        n["c"] += 1
        print(("  ok:   " if cond else "  FAIL: ") + msg)
        if not cond:
            n["f"] += 1

    print("== controller_daemon self-test (sim) ==")
    bc = BoardController(BoardConfig(21, 1, "sim", 0, 0), sim=True)
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "boots into MANUAL_INTERVENTION (power-down rule)")

    bc.link.feed_line('{"ev":"hb","ok":1}')              # RP2040 healthy
    bc.tick()
    chk(bc.io.armed is False, "stays DISARMED before First-Ball-Zero")

    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.READY, "PBZ -> READY")
    chk("CLEAR" in bc.link.sent, "PBZ also sends CLEAR to the firmware")
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
    chk(bc.io.armed is True, "ARMED once READY + RP2040 healthy")

    bc.io.grippers = 0                                    # strike (no pins standing)
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    chk(bc.fsm.state is State.SWEEP_TO_GUARD, "ball event -> SWEEP_TO_GUARD")
    chk("RUN S" in bc.link.sent, "sweep energize -> RUN S sent to firmware")

    bc.link.feed_line('{"ev":"cam","id":"SB","e":"f"}'); bc.tick()
    chk(bc.fsm.state is State.GUARD_DELAY, "SB trip -> GUARD_DELAY")
    chk("STOP S" in bc.link.sent, "sweep stop at guard -> STOP S sent")

    bc.io.advance(TIME_DELAY_S + 0.1)
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
    chk(bc.fsm.state is State.TABLE_DETECT, "3s delay -> TABLE_DETECT")

    bc.link.feed_line('{"ev":"cam","id":"TA2","e":"f"}'); bc.tick()
    chk(bc.fsm.cycle is Cycle.STRIKE and bc.fsm.state is State.RUNTHROUGH, "TA2 -> strike + RUNTHROUGH")
    bc.link.feed_line('{"ev":"cam","id":"SA","e":"f"}'); bc.tick()
    chk(bc.fsm.state is State.TABLE_FINISH, "SA -> TABLE_FINISH")

    bc.io.slow["BS"] = True; bc.tick(); bc.io.slow["BS"] = False
    chk(bc.fsm.state is State.SPOTTING, "BS -> SPOTTING (fresh rack)")
    bc.link.feed_line('{"ev":"cam","id":"TA1","e":"f"}'); bc.tick()
    chk(bc.fsm.state is State.READY and bc.fsm.ball is Ball.FIRST, "TA1 -> cycle complete, READY")

    # --- P1 safety: RP2040 health loss mid-cycle must force motors OFF + require re-arm ---
    # (Codex repro: mid-cycle rp_ok:0 left armed=False with sweep latched True, then silently
    #  re-armed with the stale latch on recovery. Fixed: health loss = full safety trip.)
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
    chk(bc.io.armed is True, "(setup) READY + armed before mid-cycle test")
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    chk(bc.io.outputs.get("sweep") is True, "(setup) mid-cycle: sweep ON")
    bc.link.feed_line('{"ev":"rp_ok","v":0}'); bc.tick()            # health loss mid-cycle
    chk(bc.io.outputs.get("sweep") is False, "health loss forces sweep OFF (clears relay latch)")
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "health loss latches FSM -> MANUAL_INTERVENTION")
    chk(bc.io.armed is False, "health loss drops ARM")
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()             # heartbeat returns OK
    chk(bc.fsm.state is State.MANUAL_INTERVENTION and bc.io.armed is False,
        "recovery does NOT auto-rearm; stays MANUAL_INTERVENTION + disarmed")
    chk(bc.io.outputs.get("sweep") is False, "sweep stays OFF after recovery (no stale-latch resume)")
    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False  # deliberate re-arm
    chk(bc.fsm.state is State.READY and bc.io.armed is True, "deliberate PBZ recovers -> READY + armed")

    # --- P2/P4: FSM FAULT is recoverable from the daemon via double-PBZ ---
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    chk(bc.fsm.state is State.SWEEP_TO_GUARD, "(setup) cycle started for FAULT-recovery test")
    bc.io.advance(9.0)                                              # exceed MAX_MOTION_S
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
    chk(bc.fsm.state is State.FAULT, "stuck motion -> FAULT via the poll backstop")
    chk(bc.io.armed is False, "FAULT drops ARM (DISARMED_STATES)")
    clears = bc.link.sent.count("CLEAR")
    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "PBZ in FAULT -> MANUAL_INTERVENTION")
    chk(bc.link.sent.count("CLEAR") == clears + 1,
        "firmware latch cleared exactly once, AFTER the FSM left FAULT")
    bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()              # PBZ released (edge re-arms)
    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.READY and bc.io.armed is True, "second PBZ -> READY + armed")

    # --- review #30: a KNOWN firmware/FSM max-run desync must REFUSE to arm ---
    bc2 = BoardController(BoardConfig(21, 1, "sim", 0, 0), sim=True)
    bc2.link.feed_line('{"ev":"boot","fw":"test","maxrun_ms":1000}')   # << MAX_MOTION_S
    bc2.link.feed_line('{"ev":"hb","ok":1}')
    bc2.io.slow["PBZ"] = True; bc2.tick(); bc2.io.slow["PBZ"] = False
    chk(bc2.fsm.state is State.READY, "(setup) maxrun-desync rig reaches READY")
    bc2.link.feed_line('{"ev":"hb","ok":1}'); bc2.tick()
    chk(bc2.io.armed is False,
        "maxrun desync (fw 1000ms < FSM MAX_MOTION_S) REFUSES to arm despite READY")

    print(f"\n{n['c'] - n['f']}/{n['c']} checks passed" + ("  <<< FAILURES" if n["f"] else ""))
    return 1 if n["f"] else 0


if __name__ == "__main__":
    sys.exit(main())
