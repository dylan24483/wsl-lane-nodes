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
                                  # Refuses hardware unless EXACTLY ONE of
                                  # WSL_LIVE_OUTPUTS=1 / WSL_CONTROLLER_SHADOW=1.
One-board bench rig (D3):         python controller_daemon.py --lanes 21   # or WSL_LANES=21
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import logging
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cycle_control_8270 import CycleController, State, MOTION_STATES
from controller_io import (
    FreshnessGuardIO, LinkFreshnessError, MachineIO, RecordingIO, ShadowIO,
    in_b_map_for, require_positive_actuation_freshness)
from rp2040_link import (
    HEARTBEAT_SCHEMA_FAULT, IDENTITY_MAX_RETRIES, REBOOT_FAULT, RP2040Link)
from identity_evidence import ControllerOwnerLease, IdentityEvidenceStore
from flight_recorder import FlightRecorder
from cam_telemetry import CamTelemetry, CycleShipper
from diag_events import (DiagEvent, DiagWriter, HttpSink, make_event, stamp_delivery,
                         SERVER_URL_ENV)
import health_drop
from health_drop import HEALTH_DROP_FILENAME, SERVICE_CONTROLLER, SERVICE_CAMERA

log = logging.getLogger("controller_daemon")

# One stable process identity shared by every lane heartbeat. A daemon restart
# necessarily produces a new value, letting the server reject stale progress
# counters from the previous controller process.
_CONTROLLER_BOOT_ID = uuid.uuid4().hex

# Shadow/canary soak (idea #11). When WSL_CONTROLLER_SHADOW=1 the FSM runs
# on the REAL inputs but every output is routed to a record-only shim (ShadowIO) and
# the relay-enable ARM is hard-held LOW — no relay is ever energized.
# LIVE is equally explicit: WSL_LIVE_OUTPUTS=1. Bare invocation, approximate
# truthy spellings, and conflicting flags all fail before hardware is opened.
# See ShadowIO in controller_io.py.
SHADOW_ENV = "WSL_CONTROLLER_SHADOW"
LIVE_ENV = "WSL_LIVE_OUTPUTS"
EXPECTED_MODE_ENV = "WSL_CONTROLLER_EXPECTED_MODE"
# General feature/diagnostic flags retain the house truthy/falsey parser.
# Output-mode flags intentionally do not use this set; they require exact 0/1.
_FALSEY = ("0", "false", "no", "off", "")


def _explicit_mode_flag(env_name):
    """Return whether a safety-significant output-mode flag is exactly ``1``.

    Missing/blank/``0`` means not selected. Any other value is rejected instead
    of accepting broad "truthy" spellings: an operator must acknowledge the
    selected physical-output posture exactly and unambiguously.
    """
    raw = os.environ.get(env_name)
    if raw is None or raw in ("", "0"):
        return False
    if raw != "1":
        raise ValueError(f"{env_name} must be exactly 0 or 1 (got {raw!r})")
    return True


def _controller_output_mode():
    """Resolve the explicit startup posture, or fail before hardware opens."""
    shadow = _explicit_mode_flag(SHADOW_ENV)
    live = _explicit_mode_flag(LIVE_ENV)
    if shadow == live:
        raise ValueError(
            f"set exactly one of {LIVE_ENV}=1 (physical outputs) or "
            f"{SHADOW_ENV}=1 (record-only); both/neither is forbidden")
    selected = "shadow" if shadow else "live"
    expected = os.environ.get(EXPECTED_MODE_ENV)
    if expected is not None:
        if expected not in ("live", "shadow"):
            raise ValueError(
                f"{EXPECTED_MODE_ENV} must be exactly live or shadow "
                f"(got {expected!r})")
        if expected != selected:
            raise ValueError(
                f"{EXPECTED_MODE_ENV}={expected} does not match selected "
                f"controller mode {selected}")
    return selected


def _shadow_enabled():
    return _explicit_mode_flag(SHADOW_ENV)


def _live_acknowledged():
    return _explicit_mode_flag(LIVE_ENV)


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
AUX_ROLES_ENV = "WSL_DIAG_AUX_ROLES"          # one-board compatibility only
AUX_ROLES_LANE_ENV_PREFIX = "WSL_DIAG_AUX_ROLES_L"  # e.g. ..._L21
# Codex round-2 (2026-07-21) knobs:
BOARD_REVS_ENV = "WSL_BOARD_REVS"             # R2-6: EXPLICIT per-lane PCB rev, e.g. "revC" or "21=revC,22=revD"
FW_BUILD_ALLOWLIST_ENV = "WSL_RP2040_BUILD_ALLOWLIST"
FW_CFG_ALLOWLIST_ENV = "WSL_RP2040_CFG_ALLOWLIST"
FW_SUPPORTED_BOARD_REVISIONS_ENV = "WSL_RP2040_SUPPORTED_BOARD_REVISIONS"
FW_QUALIFIED_RELEASES_ENV = "WSL_RP2040_QUALIFIED_RELEASES"
ALLOW_LEGACY_REVC_NO_IDENTITY_ENV = "WSL_ALLOW_LEGACY_REVC_NO_IDENTITY"
LEGACY_REVC_NO_IDENTITY_LANES_ENV = \
    "WSL_LEGACY_REVC_NO_IDENTITY_LANES"
PICO_UIDS_ENV = "WSL_RP2040_UIDS"             # optional per-lane pin: "21=UID,22=UID"
IDENTITY_STATE_DIR_ENV = "WSL_CONTROLLER_STATE_DIR"
DEFAULT_IDENTITY_STATE_DIR = "/var/lib/wsl-lane-node"


def _identity_state_dir(*, sim, shadow):
    """Resolve the monotonic identity-evidence store without weakening LIVE.

    LIVE is deliberately pinned to the systemd-managed StateDirectory.  A
    custom absolute directory is useful for simulation and explicit SHADOW
    bench runs, but accepting one in LIVE would let volatile media silently
    turn a permanent capability latch back into a per-boot latch.
    """
    state_dir = os.environ.get(IDENTITY_STATE_DIR_ENV)
    if state_dir is not None and (
            not state_dir
            or state_dir != state_dir.strip()
            or (state_dir != DEFAULT_IDENTITY_STATE_DIR
                and not os.path.isabs(state_dir))):
        raise ValueError(
            f"{IDENTITY_STATE_DIR_ENV} must be an exact non-empty "
            "absolute path")
    if not sim and not shadow:
        if (state_dir is not None
                and state_dir != DEFAULT_IDENTITY_STATE_DIR):
            raise ValueError(
                f"{IDENTITY_STATE_DIR_ENV} is fixed to "
                f"{DEFAULT_IDENTITY_STATE_DIR!r} in LIVE mode; custom "
                "directories are permitted only in simulation or explicit "
                "SHADOW mode")
        return DEFAULT_IDENTITY_STATE_DIR
    if state_dir is None:
        return None if sim else DEFAULT_IDENTITY_STATE_DIR
    return state_dir
V5_MIN_ENV = "WSL_DIAG_V5_MIN_MV"             # R2-11: VCC_5V hb-window min alert floor (mV)
V5_MAX_ENV = "WSL_DIAG_V5_MAX_MV"             # R2-11: VCC_5V hb-window max alert ceiling (mV)
STALE_CYCLES_ENV = "WSL_DIAG_STALE_CHANNEL_CYCLES"  # R2-12: cycles w/o a pulse on a pulse-role channel
BANK_FAIL_N_ENV = "WSL_DIAG_BANK_FAIL_N"      # R2-12: consecutive IN-B read failures before bank_unavailable
RUN_MISMATCH_S_ENV = "WSL_DIAG_RUN_MISMATCH_S"  # R2-12: persistence before run_mismatch promotes to a fault
DEFAULT_V5_MIN_MV = 4500.0
DEFAULT_V5_MAX_MV = 5400.0
DEFAULT_STALE_CYCLES = 20
DEFAULT_BANK_FAIL_N = 25
DEFAULT_RUN_MISMATCH_S = 3.0
# R2-14 Pi platform-health probe knobs (PlatformHealth thread, off-tick):
TEMP_MAX_ENV = "WSL_DIAG_TEMP_MAX_C"          # SoC temp warn threshold (°C)
DISK_MIN_ENV = "WSL_DIAG_DISK_MIN_MB"         # free-disk warn floor (MB)
CLOCK_DRIFT_ENV = "WSL_DIAG_CLOCK_DRIFT_S"    # wall-vs-monotonic step threshold (s)
RESTART_LOOP_N_ENV = "WSL_DIAG_RESTART_LOOP_N"      # starts within the window = loop
RESTART_LOOP_MIN_ENV = "WSL_DIAG_RESTART_LOOP_MIN"  # the window (minutes)
DIR_MAX_MB_ENV = "WSL_DIAG_DIR_MAX_MB"        # diag-dir size cap before pruning
DEFAULT_TEMP_MAX_C = 75.0
DEFAULT_DISK_MIN_MB = 500.0
DEFAULT_CLOCK_DRIFT_S = 5.0
DEFAULT_RESTART_LOOP_N = 3
DEFAULT_RESTART_LOOP_MIN = 10.0
DEFAULT_DIR_MAX_MB = 512.0
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
FOREIGN_DELIVERY_LEDGER_FILENAME = "controller_foreign_delivery.json"
FOREIGN_DELIVERY_LEDGER_VERSION = 1
FOREIGN_RELAY_FUTURE_TOLERANCE_S = 300.0
SQLITE_INT64_MAX = (1 << 63) - 1

# Manual-override inputs (scope §1 mechanic-at-machine discrimination). MAN_* +
# TENTH live on IN-B; PBC is on IN-A (netlist truth — see controller_io maps).
MANUAL_INPUT_NAMES = ("MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR", "TENTH", "PBC")
# Stuck-input rule exemptions: BS asserted at rest is NORMAL (bin stays full);
# MAN_* held is a mechanic session (manual-override rule owns those); AUX
# channels have their own role rules. AUX4-11 (rev-D IN-B GPB bank) included —
# same dormant-unless-mapped posture as AUX1-3 (H3, 2026-07-21).
STUCK_EXEMPT = ("BS", "MAN_T", "MAN_S", "MAN_SWS", "MAN_SWSR") \
    + tuple(f"AUX{i}" for i in range(1, 12))

# ---------------------------------------------------------------------------
# AUX role registry (R2-16, Codex round-2 2026-07-21): roles are REGISTERED,
# not hardwired into a whitelist chain — a new sensor role is one register_
# aux_role() call plus its handler, no edits to the dispatch. Handlers are
# called per tick as handler(diag, t, name, level, in_motion=..., rising=...)
# with the debounced level for the mapped input; they follow every LaneDiag
# rule (enqueue-only, bounded state, never raise — the dispatcher guards).
# Built-in roles are registered below the LaneDiag class body.
# ---------------------------------------------------------------------------
AUX_ROLE_HANDLERS = {}

# The externally-isolated 24 VDC diagnostics supply powers the exit photoeye
# and distributor prox.  Its health contact is a separate dry input; loss
# makes those two signals UNKNOWN, not deasserted.  Keep this list narrow:
# current switches and other dry contacts may be self-powered.
SENSOR_24V_ROLE = "sensor_24v_ok"
SENSOR_24V_DEPENDENT_ROLES = frozenset(("exit_beam", "dist_index"))


def register_aux_role(role, handler):
    """Register (or override) an AUX sensor role handler. Returns handler so
    it can be used as a decorator: @register_aux_role_named('x')."""
    AUX_ROLE_HANDLERS[str(role).strip().lower()] = handler
    return handler


def aux_roles_valid():
    return tuple(sorted(AUX_ROLE_HANDLERS))


# aux1-aux3 = rev-B/C spare channels (GPA); aux4-aux11 = the rev-D GPB bank.
# A role mapped onto a channel the board's DECLARED revision does not carry
# is REJECTED at startup (R2-6 — no revC default silently swallowing the
# AUX4-11 roles; see BoardController.__init__).
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


def _read_contract_state():
    """Return ``(live_json_sha256, loaded_strictly)``.

    The sidecar digest is intentionally not consulted.  Hashing and parsing
    the actual JSON prevents a missing/corrupt live contract from looking
    healthy merely because a stale ``machine_contract.sha256`` still exists.
    """
    try:
        p = Path(__file__).resolve().parent.parent / "server" \
            / "machine_contract.json"
        raw = p.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
        vocab = doc["vocab"]
        if not isinstance(vocab.get("event_types"), list):
            raise ValueError("contract vocab.event_types is not a list")
        return hashlib.sha256(raw).hexdigest(), True
    except Exception:
        return None, False


def _read_contract_sha():
    """Backward-compatible digest accessor for tests/callers."""
    return _read_contract_state()[0]


def _normalize_allowlist(value, env_name):
    """Normalize a config sequence/string or comma-delimited env allowlist."""
    if value is None:
        value = os.environ.get(env_name, "")
    if isinstance(value, str):
        values = value.split(",")
    else:
        try:
            values = list(value)
        except Exception:
            values = []
    return tuple(dict.fromkeys(
        str(v).strip() for v in values if str(v).strip()))


def _normalize_qualified_releases(value):
    """Parse exact ``board_rev|fw_build|fw_cfg`` release tuples.

    Environment values are comma-delimited for systemd ``EnvironmentFile``
    compatibility. Programmatic configuration may supply either those strings
    or 3-item sequences. A non-empty malformed entry is a startup error; an
    absent/empty policy remains empty and therefore fails ARM closed.
    """
    if value is None:
        value = os.environ.get(FW_QUALIFIED_RELEASES_ENV, "")
    if isinstance(value, str):
        if value == "":
            entries = []
        else:
            if value != value.strip() or any(c.isspace() for c in value):
                raise ValueError(
                    f"{FW_QUALIFIED_RELEASES_ENV} cannot contain whitespace")
            entries = value.split(",")
    else:
        try:
            entries = list(value)
        except Exception as exc:
            raise ValueError(
                f"{FW_QUALIFIED_RELEASES_ENV} must contain exact release "
                "tuples") from exc

    out = []
    for entry in entries:
        if isinstance(entry, str):
            raw = entry
            if not raw:
                raise ValueError(
                    f"invalid qualified release {entry!r}; empty entry")
            parts = raw.split("|")
        else:
            try:
                parts = list(entry)
            except Exception as exc:
                raise ValueError(
                    f"invalid qualified release entry {entry!r}") from exc
        if len(parts) != 3:
            raise ValueError(
                f"invalid qualified release {entry!r}; expected "
                "board_rev|fw_build|fw_cfg")
        release = tuple(str(part) for part in parts)
        if any(not part for part in release):
            raise ValueError(
                f"invalid qualified release {entry!r}; fields cannot be empty")
        if any(part != part.strip() or any(c.isspace() for c in part)
               for part in release):
            raise ValueError(
                f"invalid qualified release {entry!r}; whitespace is forbidden")
        if any("," in part or "|" in part for part in release):
            raise ValueError(
                f"invalid qualified release {entry!r}; ',' and '|' are "
                "reserved delimiters")
        if re.fullmatch(r"rev[A-Za-z0-9._-]+", release[0]) is None:
            raise ValueError(
                f"invalid qualified release {entry!r}; bad board revision")
        if release in out:
            raise ValueError(
                f"invalid qualified release {entry!r}; duplicate tuple")
        out.append(release)
    return tuple(out)


def _parse_lane_values(spec):
    """Parse ``lane=value`` pairs used for optional per-Pico UID pinning."""
    out = {}
    if not spec:
        return out
    for item in str(spec).split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"expected lane=value, got {item!r}")
        lane_s, value = item.split("=", 1)
        lane, value = int(lane_s.strip()), value.strip()
        if not (1 <= lane <= 32) or not value:
            raise ValueError(f"invalid lane/value in {item!r}")
        if lane in out:
            raise ValueError(f"duplicate lane {lane} in lane=value mapping")
        out[lane] = value
    return out


def _parse_lane_set(spec, *, env_name=LEGACY_REVC_NO_IDENTITY_LANES_ENV):
    """Parse an exact comma-separated set of lane integers (1..32)."""
    if spec is None or spec == "":
        return frozenset()
    if not isinstance(spec, str):
        raise ValueError(f"{env_name} must be a comma-separated lane list")
    out = set()
    for raw in spec.split(","):
        if not raw or raw != raw.strip() or not raw.isdecimal():
            raise ValueError(
                f"{env_name} has invalid lane token {raw!r}")
        lane = int(raw)
        if not 1 <= lane <= 32:
            raise ValueError(
                f"{env_name} lane {lane} is outside 1..32")
        if lane in out:
            raise ValueError(f"{env_name} repeats lane {lane}")
        out.add(lane)
    return frozenset(out)


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
    None/blank -> {} (no roles configured — the default, sensors not installed).

    R3-9 (Codex round-3, 2026-07-23): an unrecognized role string, unknown AUX
    key, or malformed token REFUSES startup with a ValueError that PRINTS the
    valid role list — it is never silently skipped. The old skip-and-warn was
    a seed-flag-matched-by-name time bomb: a typo ('be_currnet') logged one
    warning at boot and then the sensor rule sat dormant forever, looking
    exactly like a correctly-configured-but-quiet sensor. Fail loud instead."""
    roles = {}
    if not spec or not str(spec).strip():
        return roles
    for tok in str(spec).replace(",", " ").split():
        if "=" not in tok:
            raise ValueError(
                f"AUX role token {tok!r} is malformed (want 'auxN=role'). "
                f"Valid roles: {list(aux_roles_valid())}")
        k, v = tok.split("=", 1)
        name = _AUX_KEY_TO_INPUT.get(k.strip().lower())
        role = v.strip().lower()
        if name is None:
            raise ValueError(
                f"AUX channel key {k.strip()!r} is not a known input "
                f"(valid keys: {sorted(_AUX_KEY_TO_INPUT)})")
        if role not in AUX_ROLE_HANDLERS:
            raise ValueError(
                f"AUX role {v.strip()!r} on {k.strip()!r} is not a known role "
                f"(valid roles: {list(aux_roles_valid())}) — fix the typo or "
                f"register the role; it will NOT be silently ignored")
        if name in roles:
            raise ValueError(
                f"AUX channel {name} is configured more than once; every "
                "channel must have exactly one role")
        if role in roles.values():
            prior = next(key for key, value in roles.items()
                         if value == role)
            raise ValueError(
                f"AUX role {role!r} is configured on both {prior} and {name}; "
                "each diagnostic role is a singleton per board")
        roles[name] = role
    return roles


def _aux_roles_for_lane(lane, environ=None):
    """Resolve one board's AUX map, preferring its explicit lane override.

    ``WSL_DIAG_AUX_ROLES`` remains a backward-compatible one-board bench
    fallback. Multi-board services must use ``WSL_DIAG_AUX_ROLES_L<lane>`` so
    pair-shared inputs such as ``exit_beam`` never appear on an unwired mate.
    A present-but-blank lane variable explicitly leaves that board unmapped.
    """
    env = os.environ if environ is None else environ
    lane_env = f"{AUX_ROLES_LANE_ENV_PREFIX}{int(lane)}"
    spec = env.get(lane_env) if lane_env in env else env.get(AUX_ROLES_ENV)
    return _parse_aux_roles(spec)


def _validated_aux_role_map(roles, *, context):
    """Validate programmatic role maps as strictly as environment maps."""
    result = dict(roles or {})
    valid_inputs = set(_AUX_KEY_TO_INPUT.values())
    unknown_inputs = sorted(set(result) - valid_inputs)
    if unknown_inputs:
        raise ValueError(
            f"{context} has unknown AUX input(s) {unknown_inputs}; valid "
            f"inputs: {sorted(valid_inputs)}")
    unknown_roles = sorted(set(result.values()) - set(AUX_ROLE_HANDLERS))
    if unknown_roles:
        raise ValueError(
            f"{context} has unknown AUX role(s) {unknown_roles}; valid roles: "
            f"{list(aux_roles_valid())}")
    seen = {}
    for name, role in result.items():
        if role in seen:
            raise ValueError(
                f"{context} maps singleton role {role!r} on both "
                f"{seen[role]} and {name}")
        seen[role] = name
    return result


def _validate_aux_channels_for_revision(roles, *, lane, board_rev):
    """Reject role channels absent from the declared PCB before hardware opens."""
    in_b_map = in_b_map_for(board_rev)
    unsupported = sorted(name for name in roles if name not in in_b_map)
    if unsupported:
        raise ValueError(
            f"L{lane}: AUX role(s) on channel(s) {unsupported} are not "
            f"carried by board_rev={board_rev!r} (IN-B map has "
            f"{sorted(key for key in in_b_map if key.startswith('AUX'))})")


def _validate_exit_beam_topology(configs):
    """Permit zero or one source for the pair-shared exit photoeye."""
    sources = [
        (cfg.lane, name)
        for cfg in configs
        for name, role in (cfg.aux_roles or {}).items()
        if role == "exit_beam"
    ]
    if len(sources) <= 1:
        return
    rendered = ", ".join(f"L{lane}:{name}" for lane, name in sources)
    raise ValueError(
        "exit_beam is one physical source per lane pair, but multiple AUX "
        f"mappings were configured ({rendered}). Remove exit_beam from the "
        f"shared {AUX_ROLES_ENV} fallback and map it on exactly one board via "
        f"{AUX_ROLES_LANE_ENV_PREFIX}<lane>.")


def _provision_aux_roles(configs, environ=None):
    """Return copied configs with explicit, topology-validated per-board maps."""
    env = os.environ if environ is None else environ
    known_lanes = {int(cfg.lane) for cfg in configs}
    try:
        known_lanes.update(int(cfg.lane) for cfg in DEFAULT_BOARDS)
    except NameError:  # helper unit tests can run before defaults are declared
        pass
    for key in env:
        if not str(key).startswith(AUX_ROLES_LANE_ENV_PREFIX):
            continue
        suffix = str(key)[len(AUX_ROLES_LANE_ENV_PREFIX):]
        if not suffix.isdigit():
            raise ValueError(
                f"malformed per-lane AUX variable {key!r}; expected "
                f"{AUX_ROLES_LANE_ENV_PREFIX}<integer lane>")
        lane = int(suffix)
        canonical = f"{AUX_ROLES_LANE_ENV_PREFIX}{lane}"
        if key != canonical or lane not in known_lanes:
            raise ValueError(
                f"unknown/noncanonical per-lane AUX variable {key!r}; "
                f"known lanes are {sorted(known_lanes)}")
    shared = env.get(AUX_ROLES_ENV)
    if (len(configs) > 1 and shared is not None
            and str(shared).strip()):
        raise ValueError(
            f"{AUX_ROLES_ENV} is an unscoped one-board compatibility setting "
            "and cannot be used by a multi-board service. Configure each "
            f"board explicitly with {AUX_ROLES_LANE_ENV_PREFIX}<lane>; this "
            "prevents an unwired mate from becoming a false sensor source.")
    if len(configs) > 1:
        explicit_lanes = {
            int(cfg.lane) for cfg in configs if cfg.aux_roles is not None
        }
        explicit_lanes.update(
            int(cfg.lane) for cfg in configs
            if f"{AUX_ROLES_LANE_ENV_PREFIX}{int(cfg.lane)}" in env
        )
        selected_lanes = {int(cfg.lane) for cfg in configs}
        if explicit_lanes and explicit_lanes != selected_lanes:
            missing = sorted(selected_lanes - explicit_lanes)
            raise ValueError(
                "partial per-board AUX provisioning is forbidden for a "
                f"multi-board service; explicitly configure {missing} with "
                f"{AUX_ROLES_LANE_ENV_PREFIX}<lane> (use an exact blank value "
                "to declare an intentionally unmapped board)")
    provisioned = []
    for cfg in configs:
        if cfg.aux_roles is not None:
            roles = _validated_aux_role_map(
                cfg.aux_roles, context=f"L{cfg.lane} BoardConfig.aux_roles")
        else:
            lane_env = f"{AUX_ROLES_LANE_ENV_PREFIX}{int(cfg.lane)}"
            if lane_env in env:
                roles = _parse_aux_roles(env.get(lane_env))
            elif len(configs) > 1:
                roles = {}
            else:
                roles = _aux_roles_for_lane(cfg.lane, env)
        if cfg.board_rev:
            _validate_aux_channels_for_revision(
                roles, lane=cfg.lane, board_rev=cfg.board_rev)
        provisioned.append(replace(cfg, aux_roles=roles))
    _validate_exit_beam_topology(provisioned)
    return provisioned


def _parse_board_revs(spec, *, known_lanes=None):
    """R2-6: parse WSL_BOARD_REVS / --board-revs. Accepts a single rev for
    every lane ('revC') or per-lane pairs ('21=revC,22=revD'). Returns
    (default_rev_or_None, {lane: rev}). Raises ValueError on garbage —
    a typo must never silently run a board with the wrong channel map."""
    default = None
    per_lane = {}
    allowed_lanes = None if known_lanes is None \
        else {int(lane) for lane in known_lanes}
    if spec is None or not str(spec).strip():
        return None, {}
    for tok in str(spec).replace(",", " ").split():
        if "=" in tok:
            lane_s, rev = tok.split("=", 1)
            if (not lane_s.isdecimal()
                    or str(int(lane_s)) != lane_s
                    or not 1 <= int(lane_s) <= 32):
                raise ValueError(
                    f"invalid/noncanonical lane in board-rev token {tok!r}")
            lane = int(lane_s)
            if allowed_lanes is not None and lane not in allowed_lanes:
                raise ValueError(
                    f"board-rev token {tok!r} names unselected/unknown lane "
                    f"{lane}; selected lanes are {sorted(allowed_lanes)}")
            if lane in per_lane:
                raise ValueError(
                    f"duplicate board-rev assignment for lane {lane}")
            rev = rev.strip()
            in_b_map_for(rev)
            per_lane[lane] = rev
        else:
            if default is not None:
                raise ValueError(f"multiple default revs in {spec!r}")
            default = tok.strip()
            in_b_map_for(default)
    return default, per_lane


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


class HardSafeError(RuntimeError):
    """One or more independent hard-safe actions failed."""


class _InhibitedEventSink:
    """No-op target used to drain firmware motion edges while ARM is inhibited.

    Feeding those edges to the real FSM is unsafe even while ARM is LOW: an
    event could bank a relay latch that becomes live when a prerequisite later
    recovers. The bounded queue is drained, but its control meaning is discarded
    until an operator supplies a fresh PBZ after recovery.
    """

    def on_ball(self):
        pass

    def cam_SB_guard(self):
        pass

    def cam_TA2_runthrough(self):
        pass

    def cam_SA_runthrough(self):
        pass

    def cam_SA_zero(self):
        pass

    def cam_TA1_delayreset(self):
        pass

    def cam_TA1_zero(self):
        pass


_INHIBITED_EVENT_SINK = _InhibitedEventSink()

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

# A controller that stops completing ticks must not silently resume from the
# old FSM/output posture merely because the independent serial reader obtained
# a fresh RP2040 heartbeat first.  One second is deliberately far below the
# board's nominal ~11 s NE555 expiry and ~50x the normal 20 ms tick period.
# Production samples CLOCK_BOOTTIME where Python/Linux expose it so system
# suspend is included.  The fallback monotonic clock may exclude suspend on
# some platforms; the physical NE555/RP_OK/OEM chain remains load-bearing
# there, and this software latch still covers ordinary scheduler/thread gaps.
CONTROL_LOOP_GAP_MAX_S = 1.0


def _suspend_aware_monotonic():
    """Monotonic seconds including system suspend where the host supports it."""
    clock_boottime = getattr(time, "CLOCK_BOOTTIME", None)
    clock_gettime = getattr(time, "clock_gettime", None)
    if clock_boottime is not None and callable(clock_gettime):
        try:
            return clock_gettime(clock_boottime)
        except (OSError, ValueError):
            pass
    return time.monotonic()

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
    # None -> the lane-specific WSL_DIAG_AUX_ROLES_L<lane> env applies; the
    # unscoped WSL_DIAG_AUX_ROLES fallback is accepted only for one-board bench
    # use. Sensors are NOT installed yet, so the shipped default is UNMAPPED
    # and every AUX rule stays dormant (scope §4 shortlist lands here).
    aux_roles: dict = field(default=None)
    # PCB revision driving this lane — selects the IN-B channel map
    # (controller_io.IN_B_MAPS): rev-B/C = 8 GPA channels; rev-D adds the
    # AUX4-11 GPB bank. R2-6 (Codex round-2, 2026-07-21): NO default. The
    # revision MUST be provisioned explicitly — per-config, --board-revs, or
    # WSL_BOARD_REVS (systemd env file) — because a silent revC default
    # swallows every AUX4-11 role on a rev-D board without a single log
    # line. BoardController REFUSES to construct when this is still None
    # (the board is skipped fail-safe: never ticked, NE555 never kicked).
    board_rev: str = None
    # Deprecated independent build/config lists retained for config-loading
    # compatibility and diagnostics only; they never authorize ARM.
    allowed_fw_builds: tuple = field(default=None)
    allowed_fw_cfgs: tuple = field(default=None)
    # Authoritative policy: ARM requires an exact
    # (declared board revision, firmware build, firmware config) tuple. The
    # independent allowlists above remain parseable for rollout compatibility
    # but never authorize their unsafe Cartesian product.
    qualified_fw_releases: tuple = field(default=None)
    # Board revisions the provisioned release allowlists are qualified to run.
    # Required for every identity-bearing board. This prevents an allowlisted
    # Rev-D-only build/config from being treated as safe on unstrapped Rev-C.
    supported_fw_board_revisions: tuple = field(default=None)
    # Explicit installed-base escape for pre-identity Rev-C firmware. Default
    # false: a temporarily missing modern identity must never look "legacy".
    allow_legacy_revc_no_identity: bool = None
    # Positive per-lane enrollment, required in addition to the global legacy
    # acknowledgment. None reads WSL_LEGACY_REVC_NO_IDENTITY_LANES.
    legacy_revc_no_identity_enrolled: bool = None
    expected_uid: str = None


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
        self._clearers = {}     # lane -> callable() for pending-delivery cancel
        # Exit-beam source availability. UNKNOWN invalidates every active
        # absence episode: a ball may return unseen, so no pending timer or
        # attribution evidence may survive the blind interval.
        self._sources = {}          # source lane -> None/True/False
        # Each lane's RP2040 ball edge is also an attribution source.  A blind
        # launch source can hide a ball whose late exit pulse would otherwise
        # consume the first legitimate post-recovery pending ball.
        self._ball_sources = {}     # lane -> None/True/False
        self._rules_enabled = True
        self._pause_since = None
        self._blind_activity = False
        # After a real outage, ignore both balls and exit pulses for one full
        # return timeout. This drains a ball that was launched while blind so a
        # late return cannot be misattributed to the first post-recovery ball.
        self._quarantine_until = None

    def register(self, lane, emit_fn, clear_fn=None):
        self._emitters[lane] = emit_fn
        if clear_fn is not None:
            self._clearers[lane] = clear_fn

    def register_source(self, lane):
        """Declare a lane board that carries the pair's exit-beam input."""
        with self._lock:
            if lane not in self._sources and self._sources:
                raise ValueError(
                    "BallReturnTracker accepts exactly one pair-shared "
                    f"exit_beam source; already registered "
                    f"{sorted(self._sources)}, refused L{lane}")
            if lane not in self._sources:
                was_paused = self._is_paused_locked()
                self._sources[lane] = None
                if not was_paused:
                    # Registration changes a legacy unsupervised tracker into
                    # UNKNOWN. There is no timestamp yet, but pending evidence
                    # still cannot cross that boundary.
                    self._discard_unverifiable_locked()
                    self._quarantine_until = None

    def register_ball_source(self, lane):
        """Declare one lane's RP2040 ball-event observation source."""
        with self._lock:
            if lane not in self._pending:
                raise ValueError(
                    f"BallReturnTracker has no tracked lane L{lane}")
            if lane not in self._ball_sources:
                was_paused = self._is_paused_locked()
                self._ball_sources[lane] = None
                if not was_paused:
                    self._discard_unverifiable_locked()
                    self._quarantine_until = None

    def _is_paused_locked(self):
        return (not self._rules_enabled
                or (bool(self._sources)
                    and any(v is not True for v in self._sources.values()))
                or (bool(self._ball_sources)
                    and any(v is not True
                            for v in self._ball_sources.values())))

    def _discard_unverifiable_locked(self):
        for dq in self._pending.values():
            dq.clear()
        for tracked_lane in self.lanes:
            self._last_return[tracked_lane] = None
            self._last_missing[tracked_lane] = None
            self._warned[tracked_lane] = False
            # Do not clear a retained timeout incident here. The timed-out ball
            # was already conclusively missing before this later blind
            # boundary. A real successful return still invokes the clearer in
            # on_exit_pulse() and may cancel a not-yet-delivered old warning.
        self._transit_ewma = None

    def _enter_blind_locked(self, t):
        if self._pause_since is None:
            self._pause_since = t
        self._blind_activity = True
        self._quarantine_until = None
        self._discard_unverifiable_locked()

    def _recover_locked(self, t):
        # A confirmed outage, a dynamic rule-gate pause, or even one observed
        # ball/pulse while startup state was UNKNOWN can leave an old ball in
        # flight. Drain one full return window before accepting new evidence.
        if self._pause_since is not None or self._blind_activity:
            self._quarantine_until = t + self.timeout_s
        self._pause_since = None
        self._blind_activity = False

    def set_source_available(self, lane, available, t):
        """Set source state; blindness quarantines unverifiable absence data."""
        with self._lock:
            if lane not in self._sources:
                return
            was_paused = self._is_paused_locked()
            self._sources[lane] = bool(available)
            is_paused = self._is_paused_locked()
            if is_paused:
                # The first explicit False sample is a real outage even though
                # the registered source was already UNKNOWN.
                if not was_paused or (not available
                                      and self._pause_since is None):
                    self._enter_blind_locked(t)
            elif was_paused:
                self._recover_locked(t)

    def set_ball_source_available(self, lane, available, t):
        """Set one lane's ball-edge observability for pair attribution."""
        with self._lock:
            if lane not in self._ball_sources:
                return
            was_paused = self._is_paused_locked()
            self._ball_sources[lane] = bool(available)
            is_paused = self._is_paused_locked()
            if is_paused:
                if not was_paused or (not available
                                      and self._pause_since is None):
                    self._enter_blind_locked(t)
            elif was_paused:
                self._recover_locked(t)

    def note_unverifiable_ball(self, t):
        """Drain attribution after a ball edge is intentionally discarded."""
        with self._lock:
            self._discard_unverifiable_locked()
            if self._is_paused_locked():
                self._enter_blind_locked(t)
                return
            # The edge itself proves a potentially in-flight ball even though
            # both sources are currently healthy.  Ignore pair balls/pulses for
            # one complete transit timeout so its late return cannot steal a
            # post-inhibit pending ball.
            until = t + self.timeout_s
            self._quarantine_until = max(
                self._quarantine_until or until, until)

    def set_enabled(self, enabled, t):
        """Dynamically gate tracking without carrying evidence across silence."""
        with self._lock:
            was_paused = self._is_paused_locked()
            self._rules_enabled = bool(enabled)
            is_paused = self._is_paused_locked()
            if is_paused:
                if not was_paused or (not enabled
                                      and self._pause_since is None):
                    self._enter_blind_locked(t)
            elif was_paused:
                self._recover_locked(t)

    def _source_observable(self, t):
        return (
            not self._is_paused_locked()
            and (self._quarantine_until is None
                 or t >= self._quarantine_until)
        )

    def on_ball(self, lane, t):
        with self._lock:
            # A ball observed while the source is UNKNOWN or draining an outage
            # may return without defensible attribution. The source/supply
            # fault is the only evidence for that interval.
            if not self._source_observable(t):
                if self._is_paused_locked():
                    self._enter_blind_locked(t)
                return False
            dq = self._pending.get(lane)
            if dq is not None:
                dq.append(t)
                return True
            return False

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
        clear = None
        with self._lock:
            if not self._source_observable(t):
                if self._is_paused_locked():
                    self._enter_blind_locked(t)
                return
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
            clear = self._clearers.get(lane)
        if clear is not None:
            try:
                clear()
            except Exception:
                log.debug("BallReturnTracker clearer swallowed", exc_info=True)

    def poll(self, t):
        """Expire overdue pending balls; fire ONE 'ball_return_missing' alert per
        dead episode per lane (a successful return re-arms it). Never raises."""
        fired = []
        try:
            with self._lock:
                if not self._source_observable(t):
                    return fired
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
    a narrow allowlist of nuisance warn emissions is DOWNGRADED to info
    events tagged
    {'suppressed': true, 'orig_severity': ...} — the record survives (info
    logging continues), the desk alert does not. One continuous episode of
    manual activity suppresses for at most WSL_DIAG_SUPPRESS_MAX_MIN (a
    shorted/chattering manual opto must not blind the lane's alerts forever);
    crossing the cap emits a 'manual:suppress_cap' warn and re-enables alerts.
    Faults and safety/control/link/rail/identity events are never suppressed.

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
        self._manual_rearm_required = False
        # Bounded retry set for persistent rule conditions.  A nonblocking
        # writer rejection must not permanently consume a once-per-episode
        # latch, and a warn downgraded during mechanic suppression must be
        # reasserted if the condition still exists when suppression ends.
        self._pending_alerts = {}
        self._pending_alerts_max = 64
        self._event_attempts = set()
        self._rule_gate_states = {
            MANUAL_RULE_ENV: None,
            STUCK_RULE_ENV: None,
            BEAM_RULE_ENV: None,
        }
        self._last_activity = None       # t of the last FSM transition (any)
        self._cycle_start_t = None
        self._be_deadline = None         # be_no_current window end
        self._be_quiet_warned = False
        self._be_stuck_warned = False
        self._be_cycle_invalidated = \
            "be_current" in self.aux_roles.values()
        self._dist_last_pulse = None
        self._dist_warned_cycle = False
        # One union-of-unavailability episode for the distributor observation.
        # Bank UNKNOWN, FIELD_WET loss, and external sensor-24V loss may
        # overlap; active absence evidence is invalidated once at entry.
        self._dist_source_available = None
        self._dist_pause_since = None
        self._exit_source_available = None
        self._invalidated_pulse_cycles = {
            role for role in self.aux_roles.values()
            if role in ("exit_beam", "dist_index")
        }
        self._pulse_seen_since_completion = set()
        # FSM transitions precede this tick's IN-B read. Defer absence claims
        # until poll() has current availability and pulse evidence.
        self._pending_cycle_completions = deque(maxlen=16)
        self._aux_rules_suspended = False
        self._all_rules_suspended = False
        # R2-16 field_wet_ok loopback role (AUX11 jumper = harness item; the
        # software side lands now and stays dormant until the role is mapped)
        self._field_wet_input = next(
            (n for n, r in self.aux_roles.items() if r == "field_wet_ok"),
            None)
        self._field_wet_lost = False     # True while the wetting supply is down
        self._field_wet_lost_t = None
        self._field_wet_seen = False     # first-sample baseline taken
        # External sensor-supply supervision. Rev-D reserves AUX10 for an
        # externally isolated undervoltage relay's dry, healthy-when-closed
        # contact. The rule remains dormant until explicitly mapped.
        self._sensor_24v_input = next(
            (n for n, r in self.aux_roles.items() if r == SENSOR_24V_ROLE),
            None)
        self._sensor_24v_lost = False
        self._sensor_24v_lost_t = None
        self._sensor_24v_seen = False
        # R2-12 stale-channel + role-missing bookkeeping
        self._cycles_since_pulse = {}    # pulse-role input -> completed cycles
        self._stale_warned = set()
        self._role_missing_warned = set()
        # A configured AUX role is UNKNOWN until its first actual bank sample.
        # Per-role outage anchors support recovery evidence. Absence-based
        # timers/counters are invalidated on entry, never resumed after a blind
        # interval in which the missing event may actually have happened.
        self._aux_unavailable = set(self.aux_roles)
        self._aux_unknown_since = {}
        self._inb_known_names = set()
        self._diell_known_names = set()

    # ---- emission (enqueue-only; suppression-aware) ------------------------
    _SUPPRESSIBLE_WARN_TYPES = {
        "beam_blocked", "chatter", "stale_channel",
        "stuck_input", "unexpected_edge",
    }

    def emit_event(self, severity, event_type, code=None, detail=None, *, t=None,
                   persistent=False, retain_across_blind=False):
        """Build + enqueue one DiagEvent. Never blocks, never raises; returns
        True only if the event reached the writer queue."""
        if t is None:
            t = time.monotonic()
        original_severity = severity
        original_detail = dict(detail or {})
        key = (event_type, code or "")
        gate_active = _env_on(DIAG_EVENTS_ENV)
        original_event = None
        try:
            original_event = make_event(
                self.lane, original_severity, event_type,
                code=code, detail=original_detail)
            if not gate_active:
                # The master gate suppresses immediate delivery. Current-state
                # rules are discarded and must be re-proven after the blind
                # interval; immutable incidents explicitly marked for retention
                # wait in the bounded retry store with their occurrence stamp.
                if persistent and retain_across_blind:
                    self._retain_pending_alert(
                        key, original_event, t, reason="gated",
                        retain_across_blind=True)
                return False
            self._event_attempts.add(key)
            suppressed = False
            if (severity == "warn"
                    and event_type in self._SUPPRESSIBLE_WARN_TYPES
                    and self.suppress_until and t < self.suppress_until):
                detail = dict(detail or {})
                detail["suppressed"] = True
                detail["orig_severity"] = severity
                severity = "info"
                suppressed = True
                self.suppressed_count += 1
                log.info("L%s: ALERT SUPPRESSED (mechanic window): %s %s",
                         self.lane, event_type, code or "")
            if persistent and key in self._pending_alerts:
                prior_reason = self._pending_alerts[key].get(
                    "reason", "dropped")
                self._retain_pending_alert(
                    key, original_event, t,
                    reason="suppressed" if suppressed else prior_reason,
                    retain_across_blind=retain_across_blind)
                if suppressed:
                    return False
                pending = self._pending_alerts[key]
                pending["next_retry"] = min(pending["next_retry"], t)
                return self._attempt_pending_delivery(key, pending, t)
            ev = original_event
            if suppressed:
                ev = DiagEvent(
                    original_event.ts_utc, original_event.ts_mono,
                    original_event.lane_id, severity,
                    original_event.event_type, code=original_event.code,
                    detail=detail)
            self.emitted += 1
            accepted = False
            if self._writer is not None:
                accepted = bool(self._writer.emit(ev))
            if persistent:
                if suppressed or not accepted:
                    self._retain_pending_alert(
                        key, original_event, t,
                        reason="suppressed" if suppressed else "dropped",
                        retain_across_blind=retain_across_blind)
                else:
                    self._pending_alerts.pop(key, None)
            return accepted
        except Exception:
            self.drops += 1
            if persistent:
                try:
                    if original_event is None:
                        original_event = make_event(
                            self.lane, original_severity, event_type,
                            code=code, detail=original_detail)
                    self._retain_pending_alert(
                        key, original_event, t, reason="dropped",
                        retain_across_blind=retain_across_blind)
                except Exception:
                    pass
            return False

    @staticmethod
    def _pending_priority(event, retain_across_blind):
        # Severity is the primary ordering.  Retention across a blind interval
        # is only a tie-breaker within one severity: an informational incident
        # must never evict an active warning/fault whose once-per-episode latch
        # has already advanced after the writer rejected it.
        severity_rank = {"info": 0, "warn": 2, "fault": 4}
        return severity_rank.get(event.severity, 0) + int(
            bool(retain_across_blind))

    def _retain_pending_alert(self, key, event, t, *, reason,
                              retain_across_blind=False):
        priority = self._pending_priority(event, retain_across_blind)
        if key not in self._pending_alerts \
                and len(self._pending_alerts) >= self._pending_alerts_max:
            # Never let a flood of lower-priority telemetry evict an active
            # warning/fault. Evict only the oldest minimum-priority entry when
            # the new record is strictly more important; equal/lower arrivals
            # are dropped while the older incident remains recoverable.
            minimum = min(
                pending.get("priority", 0)
                for pending in self._pending_alerts.values())
            if priority <= minimum:
                self.drops += 1
                return
            victim = next(
                existing_key
                for existing_key, pending in self._pending_alerts.items()
                if pending.get("priority", 0) == minimum)
            self._pending_alerts.pop(victim, None)
        prior = self._pending_alerts.get(key)
        retries = int((prior or {}).get("retries", 0))
        self._pending_alerts[key] = {
            "event": (prior or {}).get("event", event),
            "latest_event": event,
            "occurrence_count": int(
                (prior or {}).get("occurrence_count", 0)) + 1,
            "reason": reason,
            "was_suppressed": bool(
                reason == "suppressed"
                or (prior or {}).get("was_suppressed", False)),
            "retries": retries,
            "next_retry": (
                t if reason in ("suppressed", "gated") else t + 0.25),
            "priority": max(priority, int((prior or {}).get("priority", 0))),
            # Current-condition warnings are canceled at blind boundaries and
            # re-proven from fresh evidence. One-shot trip/record incidents
            # were already observed and must merely pause until the gate opens.
            "retain_across_blind": bool(
                retain_across_blind
                or (prior or {}).get("retain_across_blind", False)),
        }

    def _cancel_pending_alert(self, event_type, code):
        key = (event_type, code or "")
        self._pending_alerts.pop(key, None)

    def _cancel_pending_alert_types(self, event_types=None):
        allowed = set(event_types) if event_types is not None else None
        for key in list(self._pending_alerts):
            if allowed is None or key[0] in allowed:
                self._pending_alerts.pop(key, None)

    def cancel_pending_event_type(self, event_type, *, preserve_codes=()):
        preserved = {code or "" for code in preserve_codes}
        for key in list(self._pending_alerts):
            if key[0] == event_type and key[1] not in preserved:
                self._pending_alerts.pop(key, None)

    def start_event_generation(self):
        self._event_attempts.clear()

    def event_attempted(self, event_type, code=None):
        if code is None:
            return any(key[0] == event_type for key in self._event_attempts)
        return (event_type, code or "") in self._event_attempts

    def _attempt_pending_delivery(self, key, pending, t):
        first = pending["event"]
        latest = pending.get("latest_event", first)
        detail = dict(latest.detail)
        occurrences = int(pending.get("occurrence_count", 1))
        if occurrences > 1:
            detail["occurrence_count"] = occurrences
            detail["first_occurrence_detail"] = dict(first.detail)
            detail["last_occurrence_ts_utc"] = latest.ts_utc
            detail["last_occurrence_ts_mono"] = latest.ts_mono
        detail["retry_after_suppression"] = bool(
            pending.get("was_suppressed", False))
        detail["delivery_retry"] = pending["retries"] + 1
        retry_event = DiagEvent(
            first.ts_utc, first.ts_mono, first.lane_id,
            first.severity, first.event_type, code=first.code,
            detail=detail)
        accepted = False
        try:
            self.emitted += 1
            self._event_attempts.add(key)
            if self._writer is not None:
                accepted = bool(self._writer.emit(retry_event))
        except Exception:
            self.drops += 1
        if accepted:
            self._pending_alerts.pop(key, None)
            return True
        pending["reason"] = "dropped"
        pending["retries"] += 1
        pending["next_retry"] = t + min(
            30.0, 0.25 * (2 ** min(pending["retries"], 7)))
        return False

    def _retry_pending_alerts(self, t, *, include_suppressible=True):
        """Retry bounded persistent alerts without blocking or per-tick floods."""
        if not _env_on(DIAG_EVENTS_ENV):
            return
        for key, pending in list(self._pending_alerts.items()):
            event = pending["event"]
            suppressible = (
                event.severity == "warn"
                and event.event_type in self._SUPPRESSIBLE_WARN_TYPES
            )
            if suppressible and not include_suppressible:
                continue
            if t < pending["next_retry"]:
                continue
            if (suppressible
                    and self.suppress_until and t < self.suppress_until):
                continue
            self._attempt_pending_delivery(key, pending, t)

    def pump_pending_delivery(self, t=None, *, force=False):
        """Boundedly retry retained events without evaluating sensor rules.

        Failed boards no longer execute ``poll()``, but their final safety trip
        still has to survive a momentarily full writer queue. The daemon loop
        calls this one-pass pump while a mate remains live and during bounded
        shutdown draining. It never blocks and never synthesizes observations.
        """
        try:
            if t is None:
                t = time.monotonic()
            if force:
                for pending in self._pending_alerts.values():
                    pending["next_retry"] = min(pending["next_retry"], t)
            self._retry_pending_alerts(t)
        except Exception:
            self.drops += 1
            log.debug("L%s pending-delivery pump swallowed",
                      self.lane, exc_info=True)
        return len(self._pending_alerts)

    def pending_alert_count(self):
        return len(self._pending_alerts)

    # ---- hooks from the board controller ----------------------------------
    def set_ball_tracker(self, tracker):
        self.ball_tracker = tracker
        tracker.register(
            self.lane,
            lambda detail, t: self.emit_event(
                "warn", "ball_return_missing", code="exit_beam",
                detail=detail, t=t, persistent=True,
                retain_across_blind=True))
        if "exit_beam" in self.aux_roles.values():
            tracker.register_source(self.lane)

    def mark_board_unavailable(self, t):
        """Invalidate board-derived evidence when its control tick cannot run."""
        try:
            for name, role in self.aux_roles.items():
                self._aux_unavailable.add(name)
                self._aux_unknown_since.setdefault(name, t)
                self._prev_levels.pop(name, None)
                self._assert_since.pop(name, None)
                self._invalidate_aux_absence(role)
            self._pending_cycle_completions.clear()
            self._cycle_start_t = None
            self._dist_last_pulse = None
            self._dist_warned_cycle = False
            self._invalidate_field_observation()
            if self.ball_tracker is not None:
                self.ball_tracker.set_ball_source_available(
                    self.lane, False, t)
            if "exit_beam" in self.aux_roles.values():
                self._exit_source_available = False
                if self.ball_tracker is not None:
                    self.ball_tracker.set_source_available(
                        self.lane, False, t)
            if "dist_index" in self.aux_roles.values():
                self._dist_source_available = False
                if self._dist_pause_since is None:
                    self._dist_pause_since = t
        except Exception:
            self.drops += 1
            log.debug("L%s mark_board_unavailable swallowed",
                      self.lane, exc_info=True)

    def rebaseline_input_generation(self, t):
        """Forget input edge/hold evidence without declaring a sensor outage."""
        try:
            self._invalidate_field_observation()
            self._diell_known_names.clear()
            self._cancel_pending_alert_types({
                "stuck_input", "beam_blocked", "stale_channel",
                "be_no_current", "be_stuck_running", "dist_index_stall",
            })
        except Exception:
            self.drops += 1
            log.debug("L%s rebaseline_input_generation swallowed",
                      self.lane, exc_info=True)

    def rebaseline_inputs(self, names, t):
        """Forget only selected shared-input consumers at a rule-gate change."""
        try:
            for name in set(names):
                self._prev_levels.pop(name, None)
                self._assert_since.pop(name, None)
                self._stuck_warned.discard(name)
                self._beam_warned.discard(name)
                self._manual_counts.pop(name, None)
                self._cancel_pending_alert(
                    "stuck_input", f"input:{name}")
                self._cancel_pending_alert(
                    "beam_blocked", f"diell:{name}")
                if name in MANUAL_INPUT_NAMES:
                    self._manual_rearm_required = True
                role = self.aux_roles.get(name)
                if role is not None:
                    self._invalidate_aux_absence(role)
        except Exception:
            self.drops += 1
            log.debug("L%s rebaseline_inputs swallowed",
                      self.lane, exc_info=True)

    def note_activity(self, t):
        """Any FSM transition = cycle activity (feeds the BE stuck-running rule)."""
        self._last_activity = t
        self._cancel_pending_alert(
            "be_stuck_running", "aux:be_current")

    def on_ball(self, t):
        """A cycle started (ball event)."""
        if (not _env_on(DIAG_EVENTS_ENV)
                or not _env_on(AUX_RULE_ENV)
                or self._aux_rules_suspended):
            self._suspend_aux_rules(t)
            return
        # A cycle starting while its supply-backed index sensor is blind has no
        # defensible timer anchor. Skip that one diagnostic episode.
        if self._be_source_is_available():
            self._be_cycle_invalidated = False
        dist_available = self._dist_source_is_available()
        self._cycle_start_t = t if dist_available else None
        if dist_available:
            self._invalidated_pulse_cycles.discard("dist_index")
            for name, role in self.aux_roles.items():
                if role == "dist_index":
                    self._pulse_seen_since_completion.discard(name)
        self._dist_warned_cycle = False
        self._cancel_pending_alert(
            "dist_index_stall", "aux:dist_index")
        if self.ball_tracker is not None:
            if self.ball_tracker.on_ball(self.lane, t):
                self._invalidated_pulse_cycles.discard("exit_beam")
                for name, role in self.aux_roles.items():
                    if role == "exit_beam":
                        self._pulse_seen_since_completion.discard(name)
        elif self._exit_source_is_available():
            self._invalidated_pulse_cycles.discard("exit_beam")
            for name, role in self.aux_roles.items():
                if role == "exit_beam":
                    self._pulse_seen_since_completion.discard(name)

    def note_cycle_complete(self, t):
        """Queue READY completion until this tick's diagnostic sample is known.

        Production observes FSM transitions before reading IN-B. Deferral keeps
        a completion from creating BE/stale evidence just before the same tick
        discovers a bank or supply outage, and lets a same-tick pulse count.
        """
        self._cycle_start_t = None
        self._cancel_pending_alert(
            "dist_index_stall", "aux:dist_index")
        if (not _env_on(DIAG_EVENTS_ENV)
                or not _env_on(AUX_RULE_ENV)
                or self._aux_rules_suspended):
            self._suspend_aux_rules(t)
            return
        self._pending_cycle_completions.append(t)

    def _resolve_cycle_completion(self, completion_t):
        """Create only absence claims proven by the current observed sample."""
        if ("be_current" in self.aux_roles.values()
                and self._be_source_is_available()
                and not self._be_cycle_invalidated):
            names = [name for name, role in self.aux_roles.items()
                     if role == "be_current"]
            if (not self._be_quiet_warned
                    and self._be_deadline is None
                    and not any(self._prev_levels.get(name, False)
                                for name in names)):
                self._be_deadline = completion_t + _env_float(
                    BE_WINDOW_S_ENV, DEFAULT_BE_WINDOW_S)
        if "be_current" in self.aux_roles.values():
            self._be_cycle_invalidated = True
        thr = int(_env_float(STALE_CYCLES_ENV, DEFAULT_STALE_CYCLES))
        for name, role in self.aux_roles.items():
            if role not in ("exit_beam", "dist_index"):
                continue
            if (name in self._aux_unavailable
                    or self._sensor_24v_blocks(role)
                    or role in self._invalidated_pulse_cycles):
                self._pulse_seen_since_completion.discard(name)
                continue
            if name in self._pulse_seen_since_completion:
                self._cycles_since_pulse[name] = 0
                self._pulse_seen_since_completion.discard(name)
                continue
            n = self._cycles_since_pulse.get(name, 0) + 1
            self._cycles_since_pulse[name] = n
            if thr > 0 and n >= thr and name not in self._stale_warned:
                self._stale_warned.add(name)
                self.emit_event(
                    "warn", "stale_channel", code=f"aux:{name}",
                    detail={"input": name, "role": role,
                            "cycles_without_pulse": n,
                            "threshold": thr}, t=completion_t,
                    persistent=True)

    def _resolve_cycle_completions(self, sample_t):
        while self._pending_cycle_completions:
            self._resolve_cycle_completion(
                self._pending_cycle_completions.popleft())
        # Completion may have arrived at firmware-edge time before this poll.
        # If its observation window is already over, evaluate the current
        # sampled BE level now instead of waiting another control tick.
        if self._be_source_is_available():
            for name, role in self.aux_roles.items():
                if role == "be_current":
                    self._be_rule(
                        sample_t, name,
                        bool(self._prev_levels.get(name, False)))

    def _invalidate_field_observation(self):
        """Discard state whose elapsed time is unknowable without FIELD_WET."""
        self._invalidate_aux_absence("be_current")
        self._prev_levels.clear()
        self._assert_since.clear()
        self._stuck_warned.clear()
        self._beam_warned.clear()
        self._manual_counts.clear()
        self._manual_episode_start = None
        self._manual_last_seen = None
        self._manual_cap_warned = False
        self._manual_rearm_required = True
        self.suppress_until = 0.0
        self._pending_cycle_completions.clear()
        self._pulse_seen_since_completion.clear()
        self._cancel_pending_alert_types({
            "stuck_input", "beam_blocked", "stale_channel",
            "be_no_current", "be_stuck_running", "dist_index_stall",
        })

    def _suspend_aux_rules(self, t):
        """Make a dynamic AUX/master gate-off interval explicitly UNKNOWN."""
        if not self._aux_rules_suspended:
            self._aux_rules_suspended = True
            self._pending_cycle_completions.clear()
            self._cycle_start_t = None
            self._dist_last_pulse = None
            self._dist_warned_cycle = False
            for name, role in self.aux_roles.items():
                self._aux_unavailable.add(name)
                self._aux_unknown_since.setdefault(name, t)
                self._prev_levels.pop(name, None)
                self._assert_since.pop(name, None)
                self._invalidate_aux_absence(role)
            self._pulse_seen_since_completion.clear()
            self._role_missing_warned.clear()
            self._field_wet_seen = False
            self._field_wet_lost = False
            self._field_wet_lost_t = None
            self._sensor_24v_seen = False
            self._sensor_24v_lost = False
            self._sensor_24v_lost_t = None
        if self.ball_tracker is not None:
            self.ball_tracker.set_enabled(False, t)
        self._sync_exit_source_availability(t)
        self._sync_dist_source_availability(t)

    def _resume_aux_rules(self, t):
        if not self._aux_rules_suspended:
            return
        self._aux_rules_suspended = False
        if self.ball_tracker is not None:
            # Source state remains UNKNOWN until this poll baselines every
            # configured input and both supply monitors consume the sample.
            self.ball_tracker.set_enabled(True, t)

    def _suspend_all_rules(self, t):
        self._all_rules_suspended = True
        self._suspend_aux_rules(t)
        self._invalidate_field_observation()
        for key, pending in list(self._pending_alerts.items()):
            if not pending.get("retain_across_blind", False):
                self._pending_alerts.pop(key, None)

    def _update_inb_observation(self, inb_levels):
        """Invalidate fixed IN-B input state across bank/key UNKNOWN.

        AUX roles have richer source-specific handling below, but manual and
        TENTH inputs share the same expander. Their held/edge state cannot cross
        an unreadable interval either.
        """
        present = set(inb_levels or ()) if inb_levels is not None else set()
        missing = (set(self._inb_known_names) if inb_levels is None
                   else self._inb_known_names - present)
        for name in missing:
            self._prev_levels.pop(name, None)
            self._assert_since.pop(name, None)
            self._stuck_warned.discard(name)
            self._manual_counts.pop(name, None)
            if name in MANUAL_INPUT_NAMES:
                self._manual_rearm_required = True
        if inb_levels is not None:
            self._inb_known_names.update(present)

    def _sync_nonaux_rule_gates(self, t, slow_levels, inb_levels,
                                diell_levels, rising=None):
        """Rebaseline per-rule elapsed state when a dynamic gate changes."""
        merged = {}
        for levels in (slow_levels, inb_levels):
            if levels:
                merged.update(levels)
        for env_name in (MANUAL_RULE_ENV, STUCK_RULE_ENV, BEAM_RULE_ENV):
            active = _env_on(env_name)
            previous = self._rule_gate_states[env_name]
            self._rule_gate_states[env_name] = active
            if previous is None or previous == active:
                continue
            if env_name == MANUAL_RULE_ENV:
                self._manual_counts.clear()
                self._manual_episode_start = None
                self._manual_last_seen = None
                self._manual_cap_warned = False
                self.suppress_until = 0.0
                if active and rising is not None:
                    # A level change may have occurred anywhere in the blind
                    # interval. The first enabled sample is a baseline, never a
                    # mechanic edge.
                    rising.difference_update(MANUAL_INPUT_NAMES)
                    self._manual_rearm_required = any(
                        bool(merged.get(name, False))
                        for name in MANUAL_INPUT_NAMES)
            elif env_name == STUCK_RULE_ENV:
                self._stuck_warned.clear()
                self._cancel_pending_alert_types({"stuck_input"})
                for name, level in merged.items():
                    if name in STUCK_EXEMPT or name.startswith("DIELL"):
                        continue
                    if active and bool(level):
                        self._assert_since[name] = t
                    elif not active:
                        self._assert_since.pop(name, None)
            else:
                self._beam_warned.clear()
                self._cancel_pending_alert_types({"beam_blocked"})
                for name, level in (diell_levels or {}).items():
                    if active and bool(level):
                        self._assert_since[name] = t
                    else:
                        self._assert_since.pop(name, None)

    # ---- per-tick rule evaluation (enqueue-only, never raises) --------------
    def poll(self, t, *, ready, in_motion, slow_levels=None, inb_levels=None,
             diell_levels=None):
        try:
            if not _env_on(DIAG_EVENTS_ENV):
                self._suspend_all_rules(t)
                return
            self._all_rules_suspended = False
            self._update_inb_observation(inb_levels)
            if not _env_on(AUX_RULE_ENV):
                self._suspend_aux_rules(t)
                non_aux_inb = None if inb_levels is None else {
                    name: level for name, level in inb_levels.items()
                    if name not in self.aux_roles
                }
                edges = self._track_levels(t, slow_levels, non_aux_inb)
                self._sync_nonaux_rule_gates(
                    t, slow_levels, non_aux_inb, diell_levels, edges)
                self._manual_rule(t, edges, slow_levels, non_aux_inb)
                self._stuck_rule(t, ready, slow_levels, non_aux_inb)
                self._beam_rule(t, ready, diell_levels)
                # Evaluate/cancel every current condition before retrying a
                # rejected alert. Otherwise a condition that clears on its
                # retry-due sample can be delivered as a fresh-looking fault
                # immediately before its rule observes the recovery.
                self._retry_pending_alerts(t)
                return
            self._resume_aux_rules(t)
            self._update_aux_availability(t, inb_levels)
            # R2-16 FIELD_WET loopback FIRST: when the field wetting supply is
            # down, every field-side input reads deasserted at once — the
            # cascade of stuck/beam/aux alerts would bury the one real root
            # cause. One field_wet_lost fault, dependents suppressed.
            self._field_wet_rule(t, inb_levels)
            if self._field_wet_input in self._aux_unavailable:
                self._invalidate_field_observation()
                self._sync_exit_source_availability(t)
                self._sync_dist_source_availability(t)
                self._retry_pending_alerts(t)
                return
            if self._field_wet_lost:
                self._invalidate_field_observation()
                self._sync_exit_source_availability(t)
                self._sync_dist_source_availability(t)
                self._retry_pending_alerts(t)
                return
            # This supply is distinct from FIELD_WET_V. Evaluate it before
            # edge tracking so recovery levels cannot become synthetic pulses.
            self._sensor_24v_rule(t, inb_levels)
            # Reconcile once more after both supply monitors have consumed the
            # same sample. This prevents a same-timestamp false recovery when
            # FIELD_WET returns while the external sensor supply remains low.
            self._sync_exit_source_availability(t)
            self._sync_dist_source_availability(t)
            edges = self._track_levels(t, slow_levels, inb_levels)
            self._sync_nonaux_rule_gates(
                t, slow_levels, inb_levels, diell_levels, edges)
            self._manual_rule(t, edges, slow_levels, inb_levels)
            self._stuck_rule(t, ready, slow_levels, inb_levels)
            self._beam_rule(t, ready, diell_levels)
            self._aux_rules(t, in_motion, edges, inb_levels)
            self._resolve_cycle_completions(t)
            self._retry_pending_alerts(t)
        except Exception:
            self.drops += 1
            log.debug("L%s LaneDiag.poll swallowed", self.lane, exc_info=True)

    def _update_aux_availability(self, t, inb_levels):
        """Track UNKNOWN/recovery per configured AUX input.

        Missing keys are not coerced to ``False``. On recovery the observed
        level is installed as a new baseline (never a synthetic rising edge).
        Entering UNKNOWN invalidates absence claims because the event being
        timed may have happened while the input was unreadable.
        """
        if not self.aux_roles:
            return
        present = set(inb_levels or ()) if inb_levels is not None else set()
        for name, role in self.aux_roles.items():
            available = inb_levels is not None and name in present
            was_unavailable = name in self._aux_unavailable
            if not available:
                if not was_unavailable:
                    self._aux_unavailable.add(name)
                    self._aux_unknown_since[name] = t
                    self._invalidate_aux_absence(role)
                else:
                    self._aux_unknown_since.setdefault(name, t)
                # Forget the pre-outage edge/assert baseline. Recovery's first
                # real sample becomes a baseline rather than an edge.
                self._prev_levels.pop(name, None)
                self._assert_since.pop(name, None)
                if (inb_levels is not None
                        and name not in self._role_missing_warned):
                    self._role_missing_warned.add(name)
                    self.emit_event(
                        "warn", "configured_role_missing", code=f"aux:{name}",
                        detail={"input": name, "role": role}, t=t,
                        persistent=True)
                continue

            level = bool(inb_levels[name])
            if was_unavailable:
                since = self._aux_unknown_since.pop(name, None)
                dt = max(0.0, t - since) if since is not None else 0.0
                self._aux_unavailable.discard(name)
                self._prev_levels[name] = level
                if level:
                    self._assert_since[name] = t
                if name in self._role_missing_warned:
                    self._role_missing_warned.discard(name)
                    self._cancel_pending_alert(
                        "configured_role_missing", f"aux:{name}")
                    self.emit_event(
                        "info", "recovered", code="configured_role_missing",
                        detail={"input": name, "role": role,
                                "unknown_s": round(dt, 3),
                                "recovered_event_type":
                                    "configured_role_missing",
                                "recovered_code": f"aux:{name}"}, t=t)
    def _invalidate_aux_absence(self, role):
        """Discard absence evidence that cannot survive an UNKNOWN interval."""
        if role == "be_current":
            self._be_deadline = None
            self._be_quiet_warned = False
            self._be_stuck_warned = False
            self._be_cycle_invalidated = True
            self._cancel_pending_alert_types(
                {"be_no_current", "be_stuck_running"})
        if role in ("exit_beam", "dist_index"):
            self._invalidated_pulse_cycles.add(role)
            for name, mapped_role in self.aux_roles.items():
                if mapped_role == role:
                    self._cycles_since_pulse.pop(name, None)
                    self._stale_warned.discard(name)
                    self._cancel_pending_alert(
                        "stale_channel", f"aux:{name}")
                    self._pulse_seen_since_completion.discard(name)
            if role == "dist_index":
                self._cancel_pending_alert_types(
                    {"dist_index_stall", "stale_channel"})

    def _sensor_24v_blocks(self, role):
        """Whether a supply-backed role must currently be UNKNOWN.

        With no sensor-supply role mapped, legacy behavior is unchanged. Once
        mapped, startup, a missing health channel, lost FIELD_WET_V, or an open
        health contact all fail closed for only exit_beam and dist_index.
        """
        if role not in SENSOR_24V_DEPENDENT_ROLES:
            return False
        if self._aux_rules_suspended:
            return True
        if (self._field_wet_input is not None
                and (self._field_wet_input in self._aux_unavailable
                     or not self._field_wet_seen
                     or self._field_wet_lost)):
            return True
        if self._sensor_24v_input is None:
            return False
        return (self._sensor_24v_input in self._aux_unavailable
                or not self._sensor_24v_seen
                or self._sensor_24v_lost)

    def _be_source_is_available(self):
        names = [name for name, role in self.aux_roles.items()
                 if role == "be_current"]
        if not names or self._aux_rules_suspended:
            return False
        if any(name in self._aux_unavailable for name in names):
            return False
        if self._field_wet_input is None:
            return True
        return (self._field_wet_input not in self._aux_unavailable
                and self._field_wet_seen
                and not self._field_wet_lost)

    def _exit_source_is_available(self):
        """Current effective availability of every exit-photoeye source."""
        names = [n for n, role in self.aux_roles.items()
                 if role == "exit_beam"]
        if not names:
            return True
        return (not self._aux_rules_suspended
                and all(n not in self._aux_unavailable for n in names)
                and not self._sensor_24v_blocks("exit_beam"))

    def _sync_exit_source_availability(self, t):
        """Invalidate blind pair evidence and drive the shared source gate."""
        if "exit_beam" not in self.aux_roles.values():
            return
        available = self._exit_source_is_available()
        previous = self._exit_source_available
        self._exit_source_available = available
        if not available and previous is not False:
            self._invalidate_aux_absence("exit_beam")
        if self.ball_tracker is not None:
            self.ball_tracker.set_source_available(self.lane, available, t)

    def _dist_source_is_available(self):
        """Current effective availability of every distributor-index source."""
        names = [n for n, role in self.aux_roles.items()
                 if role == "dist_index"]
        if not names:
            return True
        return (not self._aux_rules_suspended
                and all(n not in self._aux_unavailable for n in names)
                and not self._sensor_24v_blocks("dist_index"))

    def _sync_dist_source_availability(self, t):
        """Invalidate distributor absence evidence over one union outage."""
        if "dist_index" not in self.aux_roles.values():
            return
        available = self._dist_source_is_available()
        previous = self._dist_source_available
        self._dist_source_available = available
        if available == previous:
            return
        if not available:
            if self._dist_pause_since is None:
                self._dist_pause_since = t
            self._cycle_start_t = None
            self._dist_last_pulse = None
            self._dist_warned_cycle = False
            self._invalidate_aux_absence("dist_index")
            return
        self._dist_pause_since = None

    def _baseline_sensor_24v_dependents(self, t, inb_levels):
        """Make first post-outage sensor samples levels, never edges."""
        levels = inb_levels or {}
        for name, role in self.aux_roles.items():
            if role not in SENSOR_24V_DEPENDENT_ROLES or name not in levels:
                continue
            level = bool(levels[name])
            self._prev_levels[name] = level
            if level:
                self._assert_since[name] = t
            else:
                self._assert_since.pop(name, None)

    def _sensor_24v_rule(self, t, inb_levels):
        """Supervise external sensor 24 VDC through an isolated dry contact.

        Asserted means healthy. The input must be driven only by an external
        undervoltage-monitor relay contact; 24 V must never touch AUX directly.
        Loss inhibits exit_beam/dist_index timers and emits one root-cause
        fault until a healthy sample returns.
        """
        name = self._sensor_24v_input
        if name is None or not _env_on(AUX_RULE_ENV):
            return
        if inb_levels is None or name not in inb_levels:
            return
        level = bool(inb_levels[name])
        detail = {
            "input": name,
            "supply": "external_24vdc",
            "dependent_roles": sorted(SENSOR_24V_DEPENDENT_ROLES),
        }
        if not self._sensor_24v_seen:
            self._sensor_24v_seen = True
            if not level:
                self._sensor_24v_lost = True
                self._sensor_24v_lost_t = t
                detail["at_startup"] = True
                self.emit_event(
                    "fault", "sensor_supply_lost", code=f"aux:{name}",
                    detail=detail, t=t, persistent=True)
            return
        if level and self._sensor_24v_lost:
            since = self._sensor_24v_lost_t
            dt = max(0.0, t - since) if since is not None else 0.0
            self._baseline_sensor_24v_dependents(t, inb_levels)
            self._sensor_24v_lost = False
            self._sensor_24v_lost_t = None
            self._cancel_pending_alert(
                "sensor_supply_lost", f"aux:{name}")
            detail["outage_s"] = None if since is None else round(dt, 1)
            self.emit_event(
                "info", "sensor_supply_restored", code=f"aux:{name}",
                detail=detail, t=t)
        elif not level and not self._sensor_24v_lost:
            self._sensor_24v_lost = True
            self._sensor_24v_lost_t = t
            detail["at_startup"] = False
            self.emit_event(
                "fault", "sensor_supply_lost", code=f"aux:{name}",
                detail=detail, t=t, persistent=True)

    def _field_wet_rule(self, t, inb_levels):
        """R2-16: AUX11 FIELD_WET loopback (a harness jumper wired straight
        from FIELD_WET_V through the AUX11 opto). Asserted == supply up.
        Dormant unless the 'field_wet_ok' role is mapped. Deassertion emits
        ONE 'field_wet_lost' fault and suppresses the dependent field-input
        rules until the supply returns ('field_wet_restored', rule state
        re-baselined so the outage can't fake stuck/beam alerts)."""
        name = self._field_wet_input
        if name is None or not _env_on(AUX_RULE_ENV):
            return
        if inb_levels is None or name not in inb_levels:
            return                      # bank unreadable: judged elsewhere
        level = bool(inb_levels[name])
        if not self._field_wet_seen:
            self._field_wet_seen = True
            if not level:
                # Supply already down at startup — root-cause alert, flagged
                # as a baseline observation (no edge was seen).
                self._field_wet_lost = True
                self._field_wet_lost_t = t
                self._invalidate_aux_absence("be_current")
                self.emit_event("fault", "field_wet_lost", code=f"aux:{name}",
                                detail={"input": name, "at_startup": True},
                                t=t, persistent=True)
            return
        if level and self._field_wet_lost:
            outage = None if self._field_wet_lost_t is None \
                else round(t - self._field_wet_lost_t, 1)
            self._field_wet_lost = False
            self._field_wet_lost_t = None
            self._cancel_pending_alert(
                "field_wet_lost", f"aux:{name}")
            # Re-baseline the input rules: every field input deasserted during
            # the outage; their re-assertion must not read as fresh edges or
            # stale asserts.
            self._prev_levels.clear()
            self._assert_since.clear()
            self._stuck_warned.clear()
            self._beam_warned.clear()
            self.emit_event("info", "field_wet_restored", code=f"aux:{name}",
                            detail={"input": name, "outage_s": outage}, t=t)
        elif not level and not self._field_wet_lost:
            self._field_wet_lost = True
            self._field_wet_lost_t = t
            self._invalidate_aux_absence("be_current")
            self.emit_event("fault", "field_wet_lost", code=f"aux:{name}",
                            detail={"input": name, "at_startup": False}, t=t,
                            persistent=True)

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
                self._cancel_pending_alert(
                    "stuck_input", f"input:{name}")
        return rising

    def _manual_rule(self, t, rising, slow_levels, inb_levels):
        if not _env_on(MANUAL_RULE_ENV):
            return
        window_s = _env_float(SUPPRESS_MIN_ENV, DEFAULT_SUPPRESS_MIN) * 60.0
        max_s = _env_float(SUPPRESS_MAX_MIN_ENV, DEFAULT_SUPPRESS_MAX_MIN) * 60.0
        any_active = any(self._prev_levels.get(n) for n in MANUAL_INPUT_NAMES)
        if self._manual_rearm_required:
            if any_active:
                return
            self._manual_rearm_required = False
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
                                        "threshold_s": thr}, t=t,
                                persistent=True)

    def _beam_rule(self, t, ready, diell_levels):
        """DIELL beam statically blocked (a jammed pin/ball in the beam gives
        ONE edge, not cycling — scope §1 'stuck ball switch' row)."""
        present = set(diell_levels or ()) if diell_levels is not None else set()
        missing = (set(self._diell_known_names) if diell_levels is None
                   else self._diell_known_names - present)
        for name in missing:
            self._assert_since.pop(name, None)
            self._beam_warned.discard(name)
            self._cancel_pending_alert(
                "beam_blocked", f"diell:{name}")
        if diell_levels is not None:
            self._diell_known_names.update(present)
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
                self._cancel_pending_alert(
                    "beam_blocked", f"diell:{name}")
                continue
            if not ready or name in self._beam_warned:
                continue
            held = t - self._assert_since[name]
            if held > thr:
                self._beam_warned.add(name)
                self.emit_event("warn", "beam_blocked", code=f"diell:{name}",
                                detail={"beam": name, "held_s": round(held, 1),
                                        "threshold_s": thr}, t=t,
                                persistent=True)

    def _aux_rules(self, t, in_motion, rising, inb_levels):
        """Config-driven AUX sensor rules — fully dormant for unmapped roles.
        Dispatch is the AUX_ROLE_HANDLERS registry (R2-16): new roles register
        a handler instead of growing this chain. Each handler call is guarded
        so one buggy role degrades to a counted no-op."""
        if not _env_on(AUX_RULE_ENV) or not self.aux_roles:
            return
        # R3-9 (Codex round-3, 2026-07-23): a bank read FAILURE arrives here as
        # inb_levels is None. The old code did `inb_levels or {}` and then fed
        # every AUX handler a level of False — turning an I²C read failure into
        # a FALSE be_no_current / ball_return_missing / dist_index_stall fault.
        # A bank we cannot read is UNKNOWN, not "all sensors deasserted": skip
        # the handlers entirely (the bank_unavailable event carries the real
        # condition) and reset the per-rule episode state so neither a stale
        # latch survives the outage nor a spurious edge fires when the bank
        # answers again.
        if inb_levels is None:
            self._suppress_aux_on_bank_unknown()
            return
        levels = inb_levels
        for name, role in self.aux_roles.items():
            handler = AUX_ROLE_HANDLERS.get(role)
            if handler is None:
                continue
            # R2-12 configured_role_missing: the bank READ but this channel
            # never appears in it — a config/map mismatch, once per input.
            if name not in levels:
                continue
            if self._sensor_24v_blocks(role):
                continue
            try:
                handler(self, t, name, bool(levels[name]),
                        in_motion=in_motion, rising=rising)
            except Exception:
                self.drops += 1
                log.debug("L%s AUX role %s handler swallowed", self.lane,
                          role, exc_info=True)
        if self.ball_tracker is not None:
            self.ball_tracker.poll(t)

    def _suppress_aux_on_bank_unknown(self):
        """R3-9: the IN-B bank is unreadable this tick — hold every bank-derived
        AUX rule in UNKNOWN. _update_aux_availability already discarded active
        absence episodes and recovery will install levels as fresh baselines."""
        return

    def _note_pulse(self, name, t):
        """A pulse-role channel fired: reset its stale-channel episode."""
        role = self.aux_roles.get(name)
        if (self._aux_rules_suspended
                or role in self._invalidated_pulse_cycles):
            return
        self._cycles_since_pulse[name] = 0
        self._stale_warned.discard(name)
        self._cancel_pending_alert(
            "stale_channel", f"aux:{name}")
        self._pulse_seen_since_completion.add(name)
        if role == "dist_index":
            self._cancel_pending_alert(
                "dist_index_stall", "aux:dist_index")

    def _be_rule(self, t, name, level):
        if level:
            # any BE current cancels the quiet watch + re-arms its alert
            self._be_deadline = None
            self._be_quiet_warned = False
            self._cancel_pending_alert(
                "be_no_current", "aux:be_current")
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
                                        "quiet_s": round(t - quiet_since, 1)},
                                t=t, persistent=True)
        else:
            self._be_stuck_warned = False
            self._cancel_pending_alert(
                "be_stuck_running", "aux:be_current")
            if self._be_deadline is not None and t > self._be_deadline:
                self._be_deadline = None
                if not self._be_quiet_warned:
                    self._be_quiet_warned = True
                    self.emit_event(
                        "warn", "be_no_current", code="aux:be_current",
                        detail={"window_s": _env_float(BE_WINDOW_S_ENV,
                                                      DEFAULT_BE_WINDOW_S)},
                        t=t, persistent=True)

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
                                    "threshold_s": gap}, t=t,
                            persistent=True)


# ---- built-in AUX role handlers (R2-16 registry) ------------------------------
def _role_be_current(diag, t, name, level, *, in_motion, rising):
    diag._be_rule(t, name, level)


def _role_exit_beam(diag, t, name, level, *, in_motion, rising):
    if name in rising:
        diag._note_pulse(name, t)
        if diag.ball_tracker is not None:
            diag.ball_tracker.on_exit_pulse(t)


def _role_dist_index(diag, t, name, level, *, in_motion, rising):
    if name in rising:
        diag._note_pulse(name, t)
        diag._dist_last_pulse = t
    diag._dist_rule(t, in_motion)


def _role_field_wet(diag, t, name, level, *, in_motion, rising):
    # The field_wet rule runs FIRST in poll() (it gates the other rules), so
    # the registry handler is a no-op — registration exists so the role name
    # validates and maps like any other.
    return


def _role_sensor_24v(diag, t, name, level, *, in_motion, rising):
    # The supply rule runs before edge tracking and gates dependent roles.
    return


register_aux_role("be_current", _role_be_current)
register_aux_role("exit_beam", _role_exit_beam)
register_aux_role("dist_index", _role_dist_index)
register_aux_role("field_wet_ok", _role_field_wet)
register_aux_role(SENSOR_24V_ROLE, _role_sensor_24v)

# Back-compat alias: some tests/docs referenced the old whitelist tuple.
AUX_ROLE_VALID = aux_roles_valid()


class _PreparedRelayEvent:
    """A validated event row with a restart-stable delivery identity.

    ``DiagWriter`` normally stamps source/boot/sequence while dispatching. A
    foreign relay obligation must instead carry that identity in its WAL before
    the first offer, so replay after an ambiguous crash is server-idempotent.
    The attribute properties retain the small DiagEvent surface used by tests
    and writer stubs.
    """

    _BASE_FIELDS = {
        "ts_utc", "ts_mono", "lane_id", "severity", "event_type",
        "code", "detail",
    }
    _IDENTITY_FIELDS = {"source_id", "boot_id", "seq"}

    def __init__(self, row):
        if not isinstance(row, dict) \
                or set(row) != self._BASE_FIELDS | self._IDENTITY_FIELDS:
            raise ValueError("prepared relay row has an invalid field set")
        ts_utc = row.get("ts_utc")
        ts_mono = row.get("ts_mono")
        lane_id = row.get("lane_id")
        if (not isinstance(ts_utc, str) or not ts_utc.strip()
                or len(ts_utc) > 64):
            raise ValueError("prepared relay UTC stamp is invalid")
        try:
            parsed_utc = datetime.fromisoformat(
                ts_utc[:-1] + "+00:00" if ts_utc.endswith("Z") else ts_utc)
            if parsed_utc.tzinfo is None:
                raise ValueError
            if ((parsed_utc.astimezone(timezone.utc)
                 - datetime.now(timezone.utc)).total_seconds()
                    > FOREIGN_RELAY_FUTURE_TOLERANCE_S):
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("prepared relay UTC stamp is invalid") from None
        if (not isinstance(ts_mono, (int, float))
                or isinstance(ts_mono, bool)
                or not math.isfinite(float(ts_mono))
                or float(ts_mono) < 0):
            raise ValueError("prepared relay monotonic stamp is invalid")
        if (not isinstance(lane_id, int) or isinstance(lane_id, bool)
                or not 1 <= lane_id <= 32):
            raise ValueError("prepared relay lane is invalid")
        normalized = DiagEvent(
            ts_utc, ts_mono, lane_id, row.get("severity"),
            row.get("event_type"), code=row.get("code"),
            detail=row.get("detail")).to_dict()
        if any(normalized[field] != row.get(field)
               for field in self._BASE_FIELDS):
            raise ValueError("prepared relay payload is not canonical/bounded")
        for field, max_len in (("source_id", 120), ("boot_id", 80)):
            value = row.get(field)
            if (not isinstance(value, str) or not value.strip()
                    or len(value) > max_len):
                raise ValueError(
                    f"prepared relay {field} is invalid")
        seq = row.get("seq")
        if (not isinstance(seq, int) or isinstance(seq, bool)
                or not 0 < seq <= SQLITE_INT64_MAX):
            raise ValueError("prepared relay sequence is invalid")
        self._row = copy.deepcopy(row)

    @classmethod
    def from_event(cls, event):
        row = event.to_dict()
        stamp_delivery(row)
        return cls(row)

    def to_dict(self):
        return copy.deepcopy(self._row)

    @property
    def ts_utc(self):
        return self._row["ts_utc"]

    @property
    def ts_mono(self):
        return self._row["ts_mono"]

    @property
    def lane_id(self):
        return self._row["lane_id"]

    @property
    def severity(self):
        return self._row["severity"]

    @property
    def event_type(self):
        return self._row["event_type"]

    @property
    def code(self):
        return self._row["code"]

    @property
    def detail(self):
        return self._row["detail"]


class PlatformHealth(threading.Thread):
    """Background platform-health emitter (scope Phase 1.6) + the off-tick pump
    for cam-telemetry baseline persistence. ALL file/subprocess I/O lives on
    THIS thread — never the tick. Absent-binary tolerant (a laptop/bench host
    without vcgencmd polls once, logs once, and stops trying). Daemon thread;
    stop() joins with a bounded timeout."""

    def __init__(self, boards, writer, *, poll_s=None, dir_path=None):
        super().__init__(name="platform-health", daemon=True)
        self.boards = list(boards)
        self._foreign_lanes = frozenset(
            int(board.cfg.lane) for board in self.boards)
        self.writer = writer
        self.poll_s = float(poll_s if poll_s is not None
                            else _env_float(PLATFORM_POLL_S_ENV, DEFAULT_PLATFORM_POLL_S))
        self.dir = (dir_path or os.environ.get("WSL_DIAG_DIR", "").strip()
                    or "./diag_logs")
        self.start_count = None
        # Host/no-board probes still need a contract-valid representative lane;
        # lane 0 would create an undeliverable startup obligation.
        self._lane = self.boards[0].cfg.lane if self.boards else 1
        self._stop_ev = threading.Event()
        self._vcgencmd_missing = False
        self._last_throttled = 0
        self._current_throttled = 0
        self.errors = 0
        # R2-14 probe state (episode latches + baselines)
        self._thermal_missing = False
        self._thermal_warned = False
        self._disk_warned = False
        self._readonly_warned = False
        self._thermal_active = False
        self._disk_low_active = False
        self._readonly_active = False
        self._clock_base = None       # time.time() - time.monotonic() baseline
        # A clock step is an immutable occurrence, not merely a current state.
        # Keep the original event/stamp until the writer accepts it; otherwise
        # a step that reverses before the next poll disappears permanently.
        self._clock_pending = None
        self._service_start_path = os.path.join(
            self.dir, "service_starts.json")
        self._service_start_pending = {}
        self._service_start_pending_overflow = 0
        self._service_start_ledger_error = None
        # R2-12: writer-stats promotion baselines (diag/http drop counters)
        self._prev_queue_drops = 0
        self._prev_http_drops = 0
        self._prev_diag_counters = {}
        # R3-2: periodic authenticated heartbeat/lease-renewal POST. Track-B
        # controller sends NO scoring WS heartbeat, so without this a healthy
        # quiet controller expired OFFLINE at the 90 s lease window.
        self._hb_url = os.environ.get(SERVER_URL_ENV, "").strip().rstrip("/")
        self._hb_token = os.environ.get("LANE_NODE_TOKEN", "").strip()
        self._hb_interval = _env_float("WSL_MACHINE_HEARTBEAT_S", 20.0)
        self._hb_last = 0.0
        self._heartbeat_seq = 0
        # R3-2 review fix: the heartbeat cadence must be INDEPENDENT of the
        # (slow, default 60 s) platform-poll period. If the run loop only wakes
        # every poll_s, the 20 s _hb_interval guard can never fire more often
        # than poll_s, so a single slow/failed POST at t=poll_s pushes the next
        # attempt to t=2*poll_s — past the 90 s lease window — and a healthy
        # quiet Track-B lane false-expires OFFLINE. The loop now wakes on the
        # SHORTER of the two and throttles the platform probes separately.
        self._last_platform = 0.0
        self._contract_sha, self._contract_loaded = _read_contract_state()
        self._prev_link_parse_errors = {}
        self._prev_link_diag_drops = {}
        self._health_drop_write_warned = False
        self._common_platform = {
            "ok": False,
            "reasons": ["platform_not_probed"],
            "pi_probes_required": True,
        }
        # R3-11: shared health-drop file (whichever mutually-exclusive service
        # runs writes its own health class; whoever has transport ships both).
        self._health_drop_path = os.path.join(self.dir, HEALTH_DROP_FILENAME)
        # Per-service relay episode state (fingerprint + active typed faults).
        # health_drop.plan_foreign_relay owns the shape.
        self._last_foreign_status = {}
        self._foreign_pending = {}
        self._foreign_pending_max = 128
        self._foreign_pending_sequence = 0
        self._foreign_delivered_active = set()
        self._foreign_pending_drops = 0
        self._foreign_pending_drops_reported = 0
        # A delivered foreign fault must survive a process restart. Otherwise
        # the first fresh/healthy snapshot in the new process has no causal
        # memory and cannot clear the open machine incident. The ledger is
        # loaded on this background thread before the first foreign sample and
        # is updated only after local JSONL durability is acknowledged.
        self._foreign_delivery_path = os.path.join(
            self.dir, FOREIGN_DELIVERY_LEDGER_FILENAME)
        self._foreign_delivery_loaded = False
        self._foreign_delivery_blocked = False
        self._foreign_delivery_dirty = False
        self._foreign_delivery_ledger_error = None
        self._foreign_delivery_ledger_errors = 0
        # The master event gate is intentionally runtime-observable.  A disabled
        # interval is an UNKNOWN observation interval, not permission for probes
        # to consume episode latches/baselines whose initiating event is dropped.
        self._event_gate_state = _env_on(DIAG_EVENTS_ENV)
        self._identity_missing_pending = {}

    def _emit(self, severity, event_type, code=None, detail=None, lane=None):
        try:
            if not self._diagnostic_events_enabled():
                return False
            if self.writer is not None:
                return bool(self.writer.emit(
                    make_event(lane or self._lane, severity, event_type,
                               code=code, detail=detail)))
        except Exception:
            self.errors += 1
        return False

    def _emit_prebuilt(self, event):
        """Offer an already-stamped platform incident without restamping it."""
        try:
            if not self._diagnostic_events_enabled():
                return False
            if self.writer is not None:
                durable = getattr(self.writer, "emit_durable", None)
                if callable(durable):
                    return bool(durable(event))
                # Foreign/start/clock occurrences drive causal delivery state.
                # A volatile queue acceptance is not evidence of local
                # persistence, so a writer without the durable API fails closed.
                self.errors += 1
                return False
        except Exception:
            self.errors += 1
        return False

    def _diagnostic_events_enabled(self):
        """Return the live master-gate state and invalidate episode evidence.

        Platform-health probes run on a slow background cadence and several own
        once-per-episode latches.  If those latches advance while the master
        gate is off, a persistent fault that starts in the blind interval never
        emits after the gate comes back.  Re-arm current-condition latches and
        rebaseline elapsed state at each transition; cumulative writer
        counters deliberately stay frozen while disabled and are promoted on
        the first enabled poll.
        """
        active = _env_on(DIAG_EVENTS_ENV)
        previous = self._event_gate_state
        self._event_gate_state = active
        if previous != active:
            self._thermal_warned = False
            self._disk_warned = False
            self._readonly_warned = False
            self._last_throttled = 0
            self._clock_base = None
            self._health_drop_write_warned = False
            if active:
                # Capability probes are re-tried after a blind interval; a
                # transient/mocked absence must not permanently disable them.
                self._thermal_missing = False
                self._vcgencmd_missing = False
        return active

    # ---- R3-5: firmware-identity re-request after a reboot -----------------
    def _poll_identity(self):
        """Drive each board's link.poll_identity() off-tick. When the budget
        is spent with no id line on a board that should report it, emit ONE
        fw_identity_missing (the tick's ARM gate inhibits arming in parallel)."""
        events_enabled = self._diagnostic_events_enabled()
        for b in self.boards:
            try:
                if b.link.poll_identity() == "missing":
                    self._identity_missing_pending[b.cfg.lane] = {
                        "board_rev": b.cfg.board_rev,
                        "retries": IDENTITY_MAX_RETRIES,
                    }
                # A later identity response (valid or faulted) conclusively
                # ends the *missing* condition; the board's typed fw_identity
                # path owns any content/policy fault. The legacy Rev-C policy
                # can likewise make absence acceptable. Never ship an old
                # missing alert after either recovery.
                policy_ok = False
                try:
                    policy_ok = bool(
                        b._identity_arm_ok(
                            allow_shadow_bypass=False)[0])
                except (AttributeError, TypeError):
                    policy_ok = bool(b.link.identity_status()[0])
                if b.link.fw_identity() is not None or policy_ok:
                    self._identity_missing_pending.pop(b.cfg.lane, None)
            except Exception:
                self.errors += 1
        if events_enabled:
            for lane, detail in list(self._identity_missing_pending.items()):
                if self._emit(
                        "fault", "fw_identity_missing", code="no_id_line",
                        detail=detail, lane=lane):
                    self._identity_missing_pending.pop(lane, None)

    # ---- R3-11: shared health-drop hand-off between the two services -------
    def _poll_common_platform(self):
        """Cache the strict Pi probe used by health-drop and heartbeat truth."""
        self._common_platform = health_drop.collect_platform_health(
            self.dir, require_pi_probes=True)

    def _current_platform_snapshot(self):
        snapshot = dict(self._common_platform)
        reasons = list(snapshot.get("reasons") or [])
        if self._readonly_active:
            reasons.append("filesystem_readonly")
        if self._thermal_active:
            reasons.append("thermal")
        if self._disk_low_active:
            reasons.append("disk_low")
        if self._current_throttled & 0xF:
            reasons.append("pi_power_or_throttle")
        if self._foreign_pending_drops:
            reasons.append("foreign_pending_overflow")
        if self._foreign_delivery_ledger_error:
            reasons.append("foreign_delivery_ledger_error")
        if self._service_start_pending_overflow:
            reasons.append("service_start_pending_overflow")
        if self._service_start_ledger_error:
            reasons.append("service_start_ledger_error")
        snapshot["reasons"] = sorted(set(reasons))
        snapshot["ok"] = not snapshot["reasons"]
        snapshot.update({
            "readonly_fs": self._readonly_active,
            "thermal_warned": self._thermal_active,
            "disk_low": self._disk_low_active,
            "last_throttled": self._current_throttled,
            "foreign_pending": len(self._foreign_pending),
            "foreign_pending_drops": self._foreign_pending_drops,
            "foreign_delivery_ledger_error":
                self._foreign_delivery_ledger_error,
            "foreign_delivery_ledger_errors":
                self._foreign_delivery_ledger_errors,
            "service_start_pending": len(self._service_start_pending),
            "service_start_pending_overflow":
                self._service_start_pending_overflow,
            "service_start_ledger_error": self._service_start_ledger_error,
        })
        return snapshot

    def _write_health_drop(self):
        """Write this (controller/Track-B) service's platform-health snapshot
        to the shared drop file so a Track-A run can ship it later."""
        events_enabled = self._diagnostic_events_enabled()
        try:
            board_health = []
            for b in self.boards:
                board = b.telemetry_snapshot()
                if board is None:
                    board = b.unavailable_telemetry_snapshot()
                board.pop("_link_hb_generation", None)
                board.pop("_link_discontinuity_generation", None)
                # Health-drop has a narrower board envelope than the HTTP
                # heartbeat; retain only its accepted/current evidence.
                for field in (
                        "observed_pcb", "observed_rid", "observed_uid",
                        "fw_version"):
                    board.pop(field, None)
                board_health.append(board)
            platform = self._current_platform_snapshot()
            platform_reasons = platform["reasons"]
            board_policy_ok = all(
                not health_drop.controller_board_policy_reasons(board)
                for board in board_health)
            payload = {
                "ok": not platform_reasons and board_policy_ok,
                "service_starts": self.start_count,
                "vcgencmd_missing": self._vcgencmd_missing,
                "last_throttled": self._current_throttled,
                "readonly_fs": self._readonly_active,
                "thermal_warned": self._thermal_active,
                "disk_low": self._disk_low_active,
                "platform": platform,
                "lanes": [b.cfg.lane for b in self.boards],
                "boards": board_health,
                "contract_sha256": self._contract_sha,
                "contract_loaded": self._contract_loaded,
                "writer": (self.writer.stats()
                           if self.writer is not None
                           and hasattr(self.writer, "stats") else None),
            }
            ok = health_drop.write_drop(
                self._health_drop_path, SERVICE_CONTROLLER, payload)
            if not ok:
                self.errors += 1
                if events_enabled and not self._health_drop_write_warned:
                    self._health_drop_write_warned = self._emit(
                        "warn", "diag_drops", code="health_drop_write",
                        detail={"path": self._health_drop_path,
                                "stats": health_drop.stats()})
            elif events_enabled and self._health_drop_write_warned:
                if self._emit(
                        "info", "recovered", code="health_drop_write",
                        detail={
                            "recovered_event_type": "diag_drops",
                            "recovered_code": "health_drop_write",
                        }):
                    self._health_drop_write_warned = False
        except Exception:
            self.errors += 1

    def _emit_foreign_relay(self, event, lane, prepared_event=None):
        """Emit a planned relay event through literal, contract-auditable sites."""
        severity = event["severity"]
        event_type = event["event_type"]
        code = event.get("code")
        detail = event.get("detail")
        if prepared_event is not None:
            if event_type not in {
                    "camera_health", "pi_fs_readonly", "pi_disk_low",
                    "pi_thermal", "pi_undervoltage",
                    "diag_storage_error",
                    "health_drop_unhealthy", "health_drop_stale",
                    "recovered"}:
                self.errors += 1
                log.warning("ignored unsupported foreign health event %r",
                            event_type)
                return False
            return self._emit_prebuilt(prepared_event)
        if event_type == "camera_health":
            return self._emit(severity, "camera_health", code=code,
                              detail=detail, lane=lane)
        elif event_type == "pi_fs_readonly":
            return self._emit(severity, "pi_fs_readonly", code=code,
                              detail=detail, lane=lane)
        elif event_type == "pi_disk_low":
            return self._emit(severity, "pi_disk_low", code=code,
                              detail=detail, lane=lane)
        elif event_type == "pi_thermal":
            return self._emit(severity, "pi_thermal", code=code,
                              detail=detail, lane=lane)
        elif event_type == "pi_undervoltage":
            return self._emit(severity, "pi_undervoltage", code=code,
                              detail=detail, lane=lane)
        elif event_type == "diag_storage_error":
            return self._emit(severity, "diag_storage_error", code=code,
                              detail=detail, lane=lane)
        elif event_type == "health_drop_unhealthy":
            return self._emit(severity, "health_drop_unhealthy", code=code,
                              detail=detail, lane=lane)
        elif event_type == "health_drop_stale":
            return self._emit(severity, "health_drop_stale", code=code,
                              detail=detail, lane=lane)
        elif event_type == "recovered":
            return self._emit(severity, "recovered", code=code,
                              detail=detail, lane=lane)
        else:
            self.errors += 1
            log.warning("ignored unsupported foreign health event %r",
                        event_type)
            return False

    @staticmethod
    def _foreign_priority(event):
        if event.get("event_type") == "recovered":
            # Clearing an alert already delivered to the desk is causally part
            # of that alert, not disposable informational telemetry.
            return 3
        return {"info": 0, "warn": 1, "fault": 2}.get(
            event.get("severity"), 0)

    def _validate_foreign_plan_event(self, event, *, active=False):
        """Return a bounded copy of one relay-plan event or raise ValueError."""
        if not isinstance(event, dict):
            raise ValueError("foreign event is not an object")
        allowed = (
            {"severity", "event_type", "code", "lanes", "evidence"}
            if active else
            {"severity", "event_type", "code", "detail", "lanes"})
        required = {"severity", "event_type", "code", "lanes"}
        if set(event) - allowed or not required <= set(event):
            raise ValueError("foreign event has unknown fields")
        severity = event.get("severity")
        event_type = event.get("event_type")
        code = event.get("code")
        detail = event.get("detail")
        lanes = event.get("lanes")
        if detail is None:
            detail = {}
        if lanes is None:
            lanes = []
        if severity not in {"info", "warn", "fault"}:
            raise ValueError("invalid foreign severity")
        if event_type not in {
                "camera_health", "pi_fs_readonly", "pi_disk_low",
                "pi_thermal", "pi_undervoltage", "diag_storage_error",
                "health_drop_unhealthy", "health_drop_stale", "recovered"}:
            raise ValueError("invalid foreign event type")
        if active and (
                severity not in {"warn", "fault"}
                or event_type in {"recovered", "health_drop_stale"}):
            raise ValueError("invalid planner-active foreign event")
        if event_type == "recovered" and severity != "info":
            raise ValueError("foreign recovery must be informational")
        if code is not None and not isinstance(code, str):
            raise ValueError("invalid foreign code")
        if isinstance(code, str) and len(code) > 120:
            raise ValueError("oversized foreign code")
        if not isinstance(detail, dict):
            raise ValueError("invalid foreign detail")
        snapshot_id = detail.get("snapshot_id")
        if (snapshot_id is not None
                and (not isinstance(snapshot_id, str)
                     or len(snapshot_id) > 200)):
            raise ValueError("invalid foreign snapshot identity")
        occurrence_id = detail.get("relay_occurrence_id")
        if (occurrence_id is not None
                and (
                    not isinstance(occurrence_id, str)
                    or re.fullmatch(r"[0-9a-f]{32}", occurrence_id) is None)):
            raise ValueError("invalid foreign relay occurrence identity")
        if not isinstance(lanes, (list, tuple)) or len(lanes) > 32:
            raise ValueError("invalid foreign lane set")
        normalized_lanes = []
        for lane in lanes:
            if (not isinstance(lane, int) or isinstance(lane, bool)
                    or lane not in self._foreign_lanes
                    or lane in normalized_lanes):
                raise ValueError("invalid/duplicate foreign lane")
            normalized_lanes.append(lane)
        representative_lane = min(self._foreign_lanes) \
            if self._foreign_lanes else 1
        if active:
            evidence = event.get("evidence")
            if evidence is not None and not isinstance(evidence, dict):
                raise ValueError("invalid planner-active evidence")
            canonical = DiagEvent(
                "1970-01-01T00:00:00+00:00", 0.0,
                representative_lane, severity, event_type, code=code,
                detail={"evidence": evidence} if evidence is not None else {})
            result = {
                "severity": severity,
                "event_type": event_type,
                "code": canonical.code,
                "lanes": normalized_lanes,
            }
            if evidence is not None:
                result["evidence"] = copy.deepcopy(
                    canonical.detail["evidence"])
            return result
        from_service = detail.get("from_service")
        if from_service != SERVICE_CAMERA:
            raise ValueError("foreign event names an unexpected source service")
        recovered_fields = {
            "recovered_event_type", "recovered_code"} & set(detail)
        if event_type == "recovered":
            if recovered_fields != {
                    "recovered_event_type", "recovered_code"}:
                raise ValueError("foreign recovery lacks an exact fault family")
            recovered_type = detail.get("recovered_event_type")
            recovered_code = detail.get("recovered_code")
            if (recovered_type not in {
                    "camera_health", "pi_fs_readonly", "pi_disk_low",
                    "pi_thermal", "pi_undervoltage", "diag_storage_error",
                    "health_drop_unhealthy", "health_drop_stale"}
                    or code != recovered_type
                    or (recovered_code is not None
                        and (not isinstance(recovered_code, str)
                             or len(recovered_code) > 120))):
                raise ValueError("foreign recovery family is invalid")
        elif recovered_fields:
            raise ValueError("foreign fault carries recovery metadata")
        canonical = DiagEvent(
            "1970-01-01T00:00:00+00:00", 0.0, representative_lane,
            severity, event_type, code=code, detail=detail)
        result = copy.deepcopy(event)
        result["severity"] = severity
        result["event_type"] = event_type
        result["code"] = canonical.code
        result["detail"] = copy.deepcopy(canonical.detail)
        result["lanes"] = normalized_lanes
        return result

    @staticmethod
    def _restore_diag_event(payload):
        """Rebuild one immutable, restart-idempotent retry event."""
        return _PreparedRelayEvent(payload)

    def _foreign_delivery_payload(self):
        """Serialize planner, retry, and delivered-active state without tuple keys."""
        statuses = []
        for service in sorted(self._last_foreign_status):
            record = self._last_foreign_status[service]
            fingerprint = record.get("fingerprint")
            if fingerprint is None:
                serialized_fingerprint = None
            else:
                serialized_fingerprint = list(fingerprint)
            statuses.append({
                "service": service,
                "fingerprint": serialized_fingerprint,
                "status": record.get("status"),
                "active": [
                    copy.deepcopy(event)
                    for _key, event in sorted(
                        (record.get("active") or {}).items(),
                        key=lambda item: repr(item[0]))
                ],
            })
        delivered = [
            {
                "service": service,
                "event_type": event_type,
                "code": code,
                "lane": lane,
            }
            for service, event_type, code, lane
            in sorted(self._foreign_delivered_active, key=repr)
        ]
        pending = [
            {
                "service": pending["condition"][0],
                "event": copy.deepcopy(pending["event"]),
                "lane": pending["lane"],
                "diag_event": pending["diag_event"].to_dict(),
                "sequence": pending["sequence"],
            }
            for _key, pending in sorted(
                self._foreign_pending.items(), key=lambda item: repr(item[0]))
        ]
        return {
            "version": FOREIGN_DELIVERY_LEDGER_VERSION,
            "last_foreign_status": statuses,
            "delivered_active": delivered,
            "pending": pending,
            "pending_drops": self._foreign_pending_drops,
            "pending_drops_reported": self._foreign_pending_drops_reported,
        }

    def _restore_foreign_delivery_payload(self, payload):
        """Validate a complete ledger before replacing any in-memory state."""
        if not isinstance(payload, dict):
            raise ValueError("delivery ledger is not an object")
        if set(payload) != {
                "version", "last_foreign_status", "delivered_active",
                "pending", "pending_drops", "pending_drops_reported"}:
            raise ValueError("delivery ledger field set is invalid")
        if payload.get("version") != FOREIGN_DELIVERY_LEDGER_VERSION:
            raise ValueError("delivery ledger version is invalid")
        statuses_raw = payload.get("last_foreign_status", [])
        delivered_raw = payload.get("delivered_active", [])
        pending_raw = payload.get("pending", [])
        if (not isinstance(statuses_raw, list) or len(statuses_raw) > 2
                or not isinstance(delivered_raw, list)
                or len(delivered_raw) > self._foreign_pending_max
                or not isinstance(pending_raw, list)
                or len(pending_raw) > self._foreign_pending_max):
            raise ValueError("delivery ledger collection is invalid/oversized")

        statuses = {}
        for entry in statuses_raw:
            if (not isinstance(entry, dict)
                    or set(entry) != {
                        "service", "fingerprint", "status", "active"}):
                raise ValueError("foreign status entry is not an object")
            service = entry.get("service")
            status = entry.get("status")
            fingerprint = entry.get("fingerprint")
            active_raw = entry.get("active", [])
            if service != SERVICE_CAMERA \
                    or service in statuses:
                raise ValueError("foreign status service is invalid/duplicate")
            if status not in {None, "fresh", "stale", "missing"}:
                raise ValueError("foreign status value is invalid")
            if fingerprint is not None:
                if (not isinstance(fingerprint, list)
                        or len(fingerprint) != 2
                        or fingerprint[0] != status
                        or (fingerprint[1] is not None
                            and (not isinstance(fingerprint[1], str)
                                 or len(fingerprint[1]) > 200))):
                    raise ValueError("foreign status fingerprint is invalid")
                fingerprint = tuple(fingerprint)
            if not isinstance(active_raw, list) \
                    or len(active_raw) > self._foreign_pending_max:
                raise ValueError("foreign active set is invalid/oversized")
            active = {}
            for raw_event in active_raw:
                event = self._validate_foreign_plan_event(
                    raw_event, active=True)
                key = (
                    event["event_type"], event.get("code"),
                    tuple(event.get("lanes") or ()))
                if key in active:
                    raise ValueError("duplicate foreign active condition")
                active[key] = event
            statuses[service] = {
                "fingerprint": fingerprint,
                "status": status,
                "active": active,
            }

        delivered = set()
        for entry in delivered_raw:
            if (not isinstance(entry, dict)
                    or set(entry) != {
                        "service", "event_type", "code", "lane"}):
                raise ValueError("delivered condition is not an object")
            condition = (
                entry.get("service"), entry.get("event_type"),
                entry.get("code"), entry.get("lane"))
            service, event_type, code, lane = condition
            if service != SERVICE_CAMERA:
                raise ValueError("delivered condition service is invalid")
            if event_type not in {
                    "camera_health", "pi_fs_readonly", "pi_disk_low",
                    "pi_thermal", "pi_undervoltage", "diag_storage_error",
                    "health_drop_unhealthy", "health_drop_stale"}:
                raise ValueError("delivered condition event type is invalid")
            if (code is not None
                    and (not isinstance(code, str) or len(code) > 120)):
                raise ValueError("delivered condition code is invalid")
            if (not isinstance(lane, int) or isinstance(lane, bool)
                    or lane not in self._foreign_lanes
                    or condition in delivered):
                raise ValueError("delivered condition lane/identity is invalid")
            delivered.add(condition)

        pending_entries = {}
        pending_sequences = set()
        for entry in pending_raw:
            if (not isinstance(entry, dict)
                    or set(entry) != {
                        "service", "event", "lane", "diag_event",
                        "sequence"}):
                raise ValueError("pending condition is not an object")
            service = entry.get("service")
            lane = entry.get("lane")
            if service != SERVICE_CAMERA \
                    or not isinstance(lane, int) or isinstance(lane, bool) \
                    or lane not in self._foreign_lanes:
                raise ValueError("pending service/lane is invalid")
            sequence = entry.get("sequence")
            if (not isinstance(sequence, int) or isinstance(sequence, bool)
                    or not 0 < sequence <= SQLITE_INT64_MAX
                    or sequence in pending_sequences):
                raise ValueError("pending sequence is invalid/duplicate")
            pending_sequences.add(sequence)
            event = self._validate_foreign_plan_event(entry.get("event"))
            diag_event = self._restore_diag_event(entry.get("diag_event"))
            if (diag_event.lane_id != lane
                    or (event.get("lanes")
                        and lane not in event.get("lanes"))
                    or diag_event.severity != event["severity"]
                    or diag_event.event_type != event["event_type"]
                    or diag_event.code != event.get("code")
                    or diag_event.detail != event.get("detail")):
                raise ValueError("pending event and diagnostic row disagree")
            condition = self._foreign_condition_key(service, event, lane)
            key = self._foreign_pending_key(service, event, lane)
            if key in pending_entries:
                raise ValueError("duplicate pending delivery identity")
            pending_entries[key] = {
                "event": event,
                "lane": lane,
                "diag_event": diag_event,
                "priority": self._foreign_priority(event),
                "condition": condition,
                "sequence": sequence,
            }

        drops = payload.get("pending_drops", 0)
        drops_reported = payload.get("pending_drops_reported", 0)
        if (not isinstance(drops, int) or isinstance(drops, bool)
                or not isinstance(drops_reported, int)
                or isinstance(drops_reported, bool)):
            raise ValueError("pending drop counters are invalid")
        if (not 0 <= drops <= SQLITE_INT64_MAX
                or not 0 <= drops_reported <= SQLITE_INT64_MAX
                or drops_reported > drops):
            raise ValueError("pending drop counters are inconsistent")

        planner_conditions = set()
        for service, record in statuses.items():
            for event in record["active"].values():
                for lane in event.get("lanes") or self._foreign_lanes:
                    planner_conditions.add(
                        self._foreign_condition_key(service, event, lane))
        pending_alerts = {
            entry["condition"] for entry in pending_entries.values()
            if entry["event"].get("event_type") != "recovered"
        }
        pending_recoveries = {
            entry["condition"] for entry in pending_entries.values()
            if entry["event"].get("event_type") == "recovered"
        }

        def recovery_matches(recovery_condition, alert_condition):
            return (
                recovery_condition[0] == alert_condition[0]
                and recovery_condition[1] == alert_condition[1]
                and recovery_condition[2] == alert_condition[2]
                and recovery_condition[3] == alert_condition[3]
            )

        # Replay each exact family as an alternating delivery state machine.
        # A delivered alert may legitimately have both a pending recovery and
        # a later recurrence alert.  Sequence, rather than event severity,
        # proves the only safe order: alert -> recovery -> re-alert.  Reject a
        # ledger that would ever clear an absent alert or repeat an already
        # active one.
        projected_delivery = set(delivered)
        for pending in sorted(
                pending_entries.values(),
                key=lambda entry: entry["sequence"]):
            condition = pending["condition"]
            is_recovery = (
                pending["event"].get("event_type") == "recovered")
            currently_active = condition in projected_delivery
            if is_recovery:
                if not currently_active:
                    raise ValueError(
                        "pending recovery lacks a causal alert earlier "
                        "in sequence")
                projected_delivery.discard(condition)
            else:
                if currently_active:
                    raise ValueError(
                        "pending alert lacks an earlier causal recovery")
                projected_delivery.add(condition)
        camera_status = statuses.get(SERVICE_CAMERA, {}).get("status")
        if camera_status in {"stale", "missing"}:
            unavailable_conditions = {
                (SERVICE_CAMERA, "health_drop_stale",
                 f"{SERVICE_CAMERA}:{status}", lane)
                for status in ("stale", "missing")
                for lane in self._foreign_lanes
            }
            required_unavailable = {
                (SERVICE_CAMERA, "health_drop_stale",
                 f"{SERVICE_CAMERA}:{camera_status}", lane)
                for lane in self._foreign_lanes
            }
            if not (
                    planner_conditions | required_unavailable
                    <= projected_delivery
                    <= planner_conditions | unavailable_conditions):
                raise ValueError(
                    "projected delivery state disagrees with unavailable "
                    "planner state")
        elif projected_delivery != planner_conditions:
            raise ValueError(
                "projected delivery state disagrees with planner state")
        delivery_evidence = delivered | pending_alerts
        missing_planner = planner_conditions - delivery_evidence
        if missing_planner:
            raise ValueError(
                "planner-active fault lacks a durable delivery obligation")
        if camera_status in {"stale", "missing"}:
            expected_stale = {
                (SERVICE_CAMERA, "health_drop_stale",
                 f"{SERVICE_CAMERA}:{camera_status}", lane)
                for lane in self._foreign_lanes
            }
            if not expected_stale <= delivery_evidence:
                raise ValueError(
                    "foreign unavailable state lacks a delivery obligation")
        for alert in pending_alerts:
            has_pending_recovery = any(
                recovery_matches(recovery, alert)
                for recovery in pending_recoveries)
            if (alert not in planner_conditions
                    and not has_pending_recovery
                    and not (
                        alert[1] == "health_drop_stale"
                        and camera_status in {"stale", "missing"})):
                raise ValueError("pending alert lacks active planner evidence")
        for alert in delivered:
            has_pending_recovery = any(
                recovery_matches(recovery, alert)
                for recovery in pending_recoveries)
            if (alert not in planner_conditions
                    and not has_pending_recovery
                    and not (
                        alert[1] == "health_drop_stale"
                        and camera_status in {"stale", "missing"})):
                raise ValueError(
                    "delivered alert lacks active or clearing planner state")

        self._last_foreign_status = statuses
        self._foreign_delivered_active = delivered
        self._foreign_pending = pending_entries
        self._foreign_pending_sequence = max(pending_sequences, default=0)
        self._foreign_pending_drops = drops
        self._foreign_pending_drops_reported = drops_reported

    def _ensure_foreign_delivery_loaded(self):
        """Load once, before sampling; invalid evidence blocks relay fail-closed."""
        if self._foreign_delivery_loaded:
            return not self._foreign_delivery_blocked
        self._foreign_delivery_loaded = True
        payload = health_drop.read_delivery_ledger(
            self._foreign_delivery_path,
            version=FOREIGN_DELIVERY_LEDGER_VERSION)
        if payload == {}:
            return True
        try:
            if payload is None:
                raise ValueError("unreadable/version-mismatched ledger")
            self._restore_foreign_delivery_payload(payload)
            self._foreign_delivery_ledger_error = None
            return True
        except Exception as exc:
            self.errors += 1
            self._foreign_delivery_ledger_errors += 1
            self._foreign_delivery_ledger_error = "load_invalid"
            self._foreign_delivery_blocked = True
            log.error(
                "foreign diagnostic relay blocked: invalid delivery ledger %s "
                "(manual preservation/reconciliation required): %s",
                self._foreign_delivery_path, exc)
            return False

    def _persist_foreign_delivery_state(self):
        """Atomically commit a dirty relay state; retain it for later retry."""
        if (not self._foreign_delivery_loaded
                or self._foreign_delivery_blocked
                or not self._foreign_delivery_dirty):
            return not self._foreign_delivery_ledger_error
        if health_drop.write_delivery_ledger(
                self._foreign_delivery_path,
                self._foreign_delivery_payload()):
            self._foreign_delivery_dirty = False
            self._foreign_delivery_ledger_error = None
            return True
        self.errors += 1
        self._foreign_delivery_ledger_errors += 1
        self._foreign_delivery_ledger_error = "write_failed"
        return False

    @staticmethod
    def _foreign_condition_key(service, event, lane):
        if event.get("event_type") == "recovered":
            detail = event.get("detail") or {}
            recovered_type = (
                detail.get("recovered_event_type") or event.get("code"))
            recovered_code = detail.get("recovered_code")
            return (service, recovered_type, recovered_code, lane)
        return (
            service, event.get("event_type"), event.get("code"), lane)

    @staticmethod
    def _foreign_pending_key(service, event, lane):
        """Uniquely identify one concrete fault/recovery WAL occurrence."""
        detail = event.get("detail") or {}
        return (
            service, event.get("event_type"), event.get("code"), lane,
            detail.get("snapshot_id"), detail.get("recovered_event_type"),
            detail.get("recovered_code"),
            detail.get("relay_occurrence_id"))

    def _matching_foreign_conditions(self, condition):
        service, event_type, code, lane = condition
        candidates = set(self._foreign_delivered_active)
        candidates.update(
            pending.get("condition")
            for pending in self._foreign_pending.values())
        candidates.discard(None)
        return {
            item for item in candidates
            if item[0] == service and item[1] == event_type
            and item[2] == code and item[3] == lane
        }

    def _mark_foreign_accepted(self, pending):
        event = pending["event"]
        condition = pending["condition"]
        if event.get("event_type") == "recovered":
            for matched in self._matching_foreign_conditions(condition):
                self._foreign_delivered_active.discard(matched)
        else:
            self._foreign_delivered_active.add(condition)
        self._foreign_delivery_dirty = True

    def _retain_foreign_event(self, key, service, event, lane, diag_event):
        """Keep one rejected concrete relay occurrence in a bounded outbox."""
        if not isinstance(diag_event, _PreparedRelayEvent):
            raise ValueError(
                "foreign relay obligation lacks a prepared delivery identity")
        if key != self._foreign_pending_key(service, event, lane):
            raise ValueError("foreign relay obligation key is inconsistent")
        priority = self._foreign_priority(event)
        existing = self._foreign_pending.get(key)
        if key not in self._foreign_pending \
                and len(self._foreign_pending) >= self._foreign_pending_max:
            self._foreign_pending_drops += 1
            self.errors += 1
            self._foreign_delivery_dirty = True
            # Do not evict an older obligation whose planner transition was
            # already committed. The new source fingerprint remains uncommitted
            # and is therefore planned again after capacity returns.
            return False
        if existing is None:
            if self._foreign_pending_sequence >= SQLITE_INT64_MAX:
                raise OverflowError(
                    "foreign delivery ordering sequence exhausted")
            self._foreign_pending_sequence += 1
            sequence = self._foreign_pending_sequence
        else:
            sequence = existing["sequence"]
        retained_event = copy.deepcopy(event)
        retained_event["severity"] = diag_event.severity
        retained_event["event_type"] = diag_event.event_type
        retained_event["code"] = diag_event.code
        retained_event["detail"] = copy.deepcopy(diag_event.detail)
        self._foreign_pending[key] = {
            "event": retained_event,
            "lane": lane,
            "diag_event": diag_event,
            "priority": priority,
            "condition": self._foreign_condition_key(
                service, retained_event, lane),
            "sequence": sequence,
        }
        self._foreign_delivery_dirty = True
        return True

    def _retry_foreign_pending(self):
        """Complete WAL obligations in causal order, persisting each receipt."""
        if self._foreign_delivery_dirty \
                and not self._persist_foreign_delivery_state():
            return 0
        accepted = 0
        ordered = sorted(
            self._foreign_pending.items(),
            key=lambda item: item[1].get("sequence", 0))
        blocked_conditions = set()
        for key, pending in ordered:
            if self._foreign_pending.get(key) is not pending:
                continue
            condition = pending["condition"]
            if condition in blocked_conditions:
                continue
            if pending["event"].get("event_type") == "recovered":
                if not (
                        self._matching_foreign_conditions(condition)
                        & self._foreign_delivered_active):
                    # The causal alert may be immediately ahead of this row in
                    # the same WAL. Never emit a recovery first.
                    blocked_conditions.add(condition)
                    continue
            elif condition in self._foreign_delivered_active:
                # This is a recurrence retained behind an ambiguous recovery.
                # Do not offer it until that exact recovery has durably cleared
                # the prior alert; otherwise server incident grouping could let
                # the recovery close both occurrences and leave a false green.
                blocked_conditions.add(condition)
                continue
            if not self._emit_foreign_relay(
                    pending["event"], pending["lane"],
                    prepared_event=pending["diag_event"]):
                # Preserve per-family FIFO even when another event type would
                # currently pass its state guard.  A later recurrence must
                # never leapfrog an unaccepted alert/recovery receipt.
                blocked_conditions.add(condition)
                continue
            self._mark_foreign_accepted(pending)
            self._foreign_pending.pop(key, None)
            if not self._foreign_pending:
                self._foreign_pending_sequence = 0
            self._foreign_delivery_dirty = True
            accepted += 1
            # If this write fails, the old WAL still contains the same fully
            # stamped row. Stop offering; restart/retry is server-idempotent.
            if not self._persist_foreign_delivery_state():
                break
        return accepted

    def _report_foreign_pending_drops(self):
        if self._foreign_pending_drops <= \
                self._foreign_pending_drops_reported:
            return
        if self._emit(
                "warn", "diag_drops", code="foreign_pending_overflow",
                detail={
                    "new": (
                        self._foreign_pending_drops
                        - self._foreign_pending_drops_reported),
                    "total": self._foreign_pending_drops,
                    "pending": len(self._foreign_pending),
                    "capacity": self._foreign_pending_max,
                }):
            self._foreign_pending_drops_reported = \
                self._foreign_pending_drops
            self._foreign_delivery_dirty = True

    def _ship_foreign_health(self):
        """Relay Track-A health through a restart-safe write-ahead outbox.

        A planner transition and every concrete per-lane occurrence are one
        transaction: all rows must fit and reach the fsynced ledger before the
        first durable writer offer.  Ambiguous writer failures therefore leave
        the same stamped identity available for replay, and capacity pressure
        cannot advance the source fingerprint past an unrecorded lane.
        """
        if not self._diagnostic_events_enabled():
            return
        try:
            if not self._ensure_foreign_delivery_loaded():
                return
            # Never offer while memory is ahead of disk.  Then replay older WAL
            # rows before planning a newer source snapshot so causal alerts can
            # make room for their eventual recoveries.
            if (self._foreign_delivery_dirty
                    and not self._persist_foreign_delivery_state()):
                return
            self._retry_foreign_pending()
            if self._foreign_delivery_dirty:
                return

            configured_lanes = sorted(self._foreign_lanes)
            required = os.environ.get(
                "WSL_PHASE8_REQUIRED_SERVICES", "")
            if not health_drop.foreign_service_required(
                    required, "scoring", configured_lanes):
                self._report_foreign_pending_drops()
                self._persist_foreign_delivery_state()
                return
            statuses = health_drop.read_foreign_statuses(
                self._health_drop_path, SERVICE_CONTROLLER)
            for item in statuses:
                service = item.get("service")
                if service != SERVICE_CAMERA:
                    raise ValueError("unexpected foreign relay service")
                candidate_state = copy.deepcopy(self._last_foreign_status)
                planned = health_drop.plan_foreign_relay(
                    item, candidate_state)
                staged = []
                staged_keys = set()
                staged_alerts = set()
                existing_alerts = set(self._foreign_delivered_active)
                existing_alerts.update(
                    pending["condition"]
                    for pending in self._foreign_pending.values()
                    if pending["event"].get("event_type") != "recovered")

                for raw_event in planned:
                    event = self._validate_foreign_plan_event(raw_event)
                    lanes = event.get("lanes") or configured_lanes
                    if not lanes:
                        raise ValueError(
                            "foreign relay has no configured destination lane")
                    for lane in lanes:
                        condition = self._foreign_condition_key(
                            service, event, lane)
                        if event.get("event_type") == "recovered":
                            # The planner deliberately offers exact clears for
                            # every unavailable code it may have observed.
                            # Commit only those backed by a fault obligation.
                            matches = self._matching_foreign_conditions(
                                condition)
                            matches.update(
                                alert for alert in staged_alerts
                                if alert[0] == condition[0]
                                and alert[1] == condition[1]
                                and alert[2] == condition[2]
                                and alert[3] == condition[3]
                            )
                            if not (matches & (
                                    existing_alerts | staged_alerts)):
                                continue
                        elif condition in self._foreign_delivered_active:
                            # A same-family recurrence is new evidence only
                            # when an earlier exact recovery is already in the
                            # WAL. Retain the recurrence behind that recovery;
                            # its distinct prepared identity must survive a
                            # crash at either receipt boundary.
                            has_pending_recovery = any(
                                pending["condition"] == condition
                                and pending["event"].get("event_type")
                                == "recovered"
                                for pending in self._foreign_pending.values())
                            if not has_pending_recovery:
                                continue

                        concrete_event = copy.deepcopy(event)
                        concrete_detail = dict(
                            concrete_event.get("detail") or {})
                        # Source snapshot ids intentionally repeat while a
                        # payload is unchanged and unavailable states use None.
                        # A local occurrence id distinguishes later causal
                        # episodes of the same exact family in one WAL.
                        concrete_detail["relay_occurrence_id"] = \
                            uuid.uuid4().hex
                        concrete_event["detail"] = concrete_detail
                        concrete_event = self._validate_foreign_plan_event(
                            concrete_event)
                        key = self._foreign_pending_key(
                            service, concrete_event, lane)
                        if key in self._foreign_pending \
                                or key in staged_keys:
                            continue
                        prepared = _PreparedRelayEvent.from_event(make_event(
                            lane, concrete_event["severity"],
                            concrete_event["event_type"],
                            code=concrete_event.get("code"),
                            detail=concrete_event.get("detail")))
                        staged.append((
                            key, service, concrete_event, lane, prepared))
                        staged_keys.add(key)
                        if concrete_event.get("event_type") != "recovered":
                            staged_alerts.add(condition)

                available = (
                    self._foreign_pending_max - len(self._foreign_pending))
                if len(staged) > available:
                    self._foreign_pending_drops = min(
                        SQLITE_INT64_MAX,
                        self._foreign_pending_drops + len(staged) - max(
                            available, 0))
                    self.errors += 1
                    self._foreign_delivery_dirty = True
                    # Do not commit candidate_state: the unchanged source
                    # fingerprint will deterministically re-plan every lane.
                    if not self._persist_foreign_delivery_state():
                        return
                    continue

                pending_before = dict(self._foreign_pending)
                sequence_before = self._foreign_pending_sequence
                for key, staged_service, event, lane, prepared in staged:
                    if not self._retain_foreign_event(
                            key, staged_service, event, lane, prepared):
                        self._foreign_pending = pending_before
                        self._foreign_pending_sequence = sequence_before
                        self._foreign_delivery_dirty = True
                        if not self._persist_foreign_delivery_state():
                            return
                        break
                else:
                    self._last_foreign_status = candidate_state
                    self._foreign_delivery_dirty = True
                    if not self._persist_foreign_delivery_state():
                        return
                    self._retry_foreign_pending()
                    if self._foreign_delivery_dirty:
                        return

            self._report_foreign_pending_drops()
            self._persist_foreign_delivery_state()
        except Exception:
            self.errors += 1
            log.exception("foreign diagnostic relay poll failed")

    # ---- R3-2: periodic authenticated heartbeat / lease renewal ------------
    def _maybe_heartbeat(self):
        """POST /api/machine/heartbeat per board on a fixed cadence WELL under
        the lease window. Carries board revision + firmware build/config hashes
        + the contract digest + outbox health. Never raises; a POST failure is
        counted (self.errors) and retried next cadence."""
        if not self._hb_url:
            return
        now = time.monotonic()
        if now - self._hb_last < self._hb_interval:
            return
        self._hb_last = now
        self._heartbeat_seq += 1
        # Re-evaluate the live JSON every cadence. Removing/corrupting it after
        # startup must turn contract_loaded false rather than leaving a cached
        # sidecar-derived green value.
        self._contract_sha, self._contract_loaded = _read_contract_state()
        outbox = {
            "cursor_ok": False,
            "write_errors": 1,
            "sink_errors": 0,
            "dropped": 0,
            "health_unavailable": True,
        }
        try:
            if self.writer is not None and self.writer.outbox is not None:
                health = self.writer.outbox.health()
                if isinstance(health, dict):
                    outbox = health
        except Exception:
            pass
        for b in self.boards:
            try:
                body = b.telemetry_snapshot()
                if body is None:
                    # No exact current link/control generation: do not renew
                    # remote liveness from a stale or partial sample.
                    continue
                body.pop("_link_hb_generation", None)
                body.pop("_link_discontinuity_generation", None)
                body.update({
                    "heartbeat_seq": self._heartbeat_seq,
                    "contract_sha256": self._contract_sha,
                    "contract_loaded": self._contract_loaded,
                    # R3-10: a read-only FS blocks the JSONL outbox, so the
                    # pi_fs_readonly EVENT can't be persisted — the heartbeat
                    # (direct network POST, no disk) is the only channel left
                    # to surface it. Pre-allocated flag, always sent.
                    "ro_fs": bool(self._readonly_active),
                    "outbox": outbox,
                    "platform": self._current_platform_snapshot(),
                    "serial_parse_errors": body.pop("parse_errors"),
                    "diag_record_drops": body.pop("diag_record_drops"),
                })
                body.pop("quarantined_lines", None)
                body.pop("pending_diag_records", None)
                self._post_heartbeat(body)
            except Exception:
                self.errors += 1

    def _post_heartbeat(self, body):
        import urllib.request
        data = json.dumps({"heartbeat": body}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._hb_token:
            headers["X-Lane-Token"] = self._hb_token
        req = urllib.request.Request(self._hb_url + "/api/machine/heartbeat",
                                     data=data, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            raw = resp.read(4096)
            status = int(getattr(resp, "status", 200) or 200)
            if status >= 300:
                raise RuntimeError(f"heartbeat HTTP {status}")
            try:
                ack = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise RuntimeError("heartbeat response is not JSON") from exc
            if (not isinstance(ack, dict)
                    or ack.get("ok") is not True
                    or ack.get("committed") is not True
                    or ack.get("lane") != body["lane_id"]
                    or ack.get("heartbeat_seq") != body["heartbeat_seq"]
                    or ack.get("control_loop_seq") != body["control_loop_seq"]
                    or not isinstance(ack.get("last_seen"), str)
                    or not ack["last_seen"].strip()):
                raise RuntimeError(f"heartbeat not durably acknowledged: {ack!r}")

    def stop(self, timeout=5.0):
        try:
            self._stop_ev.set()
            if self.is_alive():
                self.join(timeout)
            self._retry_service_start_events()
        except Exception:
            pass

    def run(self):
        try:
            # File I/O stays on this background thread, but continuity state is
            # restored before the first platform/foreign-health observation.
            self._ensure_foreign_delivery_loaded()
        except Exception:
            self.errors += 1
        try:
            self._count_service_start()
        except Exception:
            self.errors += 1
            log.debug("PlatformHealth service-start count swallowed", exc_info=True)
        while not self._stop_ev.is_set():
            now = time.monotonic()
            try:
                self._retry_service_start_events()
            except Exception:
                self.errors += 1
            # Platform probes stay on the slow poll_s cadence (they own their
            # own baselines/latches and some spawn subprocesses — vcgencmd —
            # that must NOT run 3x more often just because the loop woke early
            # for a heartbeat). Throttled here rather than per-probe so the one
            # guard covers them all.
            if now - self._last_platform >= self.poll_s:
                self._last_platform = now
                for probe in (self._poll_throttled, self._poll_thermal,
                               self._poll_disk, self._poll_clock_drift,
                               self._poll_writer_drops, self._poll_dir_retention,
                               self._poll_identity, self._poll_common_platform,
                               self._write_health_drop,
                              self._ship_foreign_health):
                    try:
                        probe()
                    except Exception:
                        self.errors += 1
                for b in self.boards:
                    try:
                        b.telemetry.maybe_persist()
                    except Exception:
                        self.errors += 1
            # R3-2: the lease-renewal heartbeat runs on its OWN cadence
            # (_hb_interval, default 20 s << the 90 s lease window). It is
            # self-throttled internally, so calling it every wake is cheap; the
            # point is that the loop WAKES often enough for it to fire ~3x per
            # lease window and tolerate a couple of missed POSTs.
            try:
                self._maybe_heartbeat()
            except Exception:
                self.errors += 1
            wait = self.poll_s
            if self._hb_url:
                wait = min(wait, self._hb_interval)
            # small floor guards a misconfigured near-zero heartbeat interval
            # from busy-looping; the real default (20 s) is far above it.
            self._stop_ev.wait(max(0.05, wait))
        # final persistence flush on the way out (still off-tick)
        for b in self.boards:
            try:
                b.telemetry.stop()
            except Exception:
                pass

    def _count_service_start(self):
        """Increment the service-start counter file + emit 'service_restart'.
        Both past field incidents (missing watchdog kick, not-enabled systemd
        unit) would have shown up here first (scope §1 platform row).
        R2-14: also keeps a bounded recent-start list and emits ONE
        'service_restart_loop' fault when N starts land within the window —
        systemd's StartLimitBurst latches the unit silently; this makes the
        crash loop visible on the desk before that."""
        loop_n = int(_env_float(RESTART_LOOP_N_ENV, DEFAULT_RESTART_LOOP_N))
        window_s = _env_float(RESTART_LOOP_MIN_ENV,
                              DEFAULT_RESTART_LOOP_MIN) * 60.0
        facts = health_drop.record_service_start(
            self._service_start_path,
            window_s=window_s,
            threshold=(loop_n if loop_n > 0 else 2 ** 31 - 1),
            track_delivery=True,
            monotonic_now=time.monotonic())
        self.start_count = int(facts.get("count", 0) or 0)
        self._service_start_pending_overflow = int(
            facts.get("pending_delivery_overflow", 0) or 0)
        if not facts.get("persisted"):
            self._service_start_ledger_error = (
                facts.get("error") or "service_start_state_not_persisted")
            self.errors += 1
            self._emit(
                "warn", "diag_storage_error",
                code="service_start_counter", detail={
                    key: value for key, value in facts.items()
                    if key != "pending_events"
                })
            return
        self._service_start_ledger_error = None
        for item in facts.get("pending_events", []):
            if not self._restore_service_start_obligation(item):
                if not self._service_start_ledger_error:
                    self._service_start_ledger_error = (
                        "service_start_delivery_prepare_failed")
                self.errors += 1
        self._retry_service_start_events()

    def _restore_service_start_obligation(self, item):
        """Restore or prepare one exact, restart-stable startup occurrence.

        The concrete delivery row is fsynced into the counter WAL before its
        first writer offer.  If a previous process died after the JSONL fsync
        but before the WAL acknowledgement, the exact local receipt is
        reconciled without offering even an idempotent duplicate.
        """
        try:
            count = int(item["count"])
            epoch = float(item["started_at_epoch"])
            mono = float(item["started_at_monotonic"])
            stamp = datetime.fromtimestamp(
                epoch, timezone.utc).isoformat(timespec="milliseconds")
            detail = {
                "count": count,
                "started_at_epoch": epoch,
                "starts_in_window": int(item["starts_in_window"]),
                "window_s": float(item["window_s"]),
                "threshold": int(item["threshold"]),
                "restart_loop": bool(item["restart_loop"]),
                "replayed_start_evidence": count != self.start_count,
            }
            for event_type, severity in (
                    ("service_restart_loop", "fault"),
                    ("service_restart", "info")):
                if not item.get(f"{event_type}_pending"):
                    continue
                delivery_field = f"{event_type}_deliveries"
                rows = item.get(delivery_field)
                if rows is None:
                    prepared = _PreparedRelayEvent.from_event(DiagEvent(
                        stamp, mono, self._lane, severity,
                        event_type, code="daemon_start", detail=detail))
                    rows = health_drop.prepare_service_start_deliveries(
                        self._service_start_path, count, event_type,
                        [prepared.to_dict()])
                if not isinstance(rows, list) or len(rows) != 1:
                    return False
                prepared = _PreparedRelayEvent(rows[0])
                if (
                        prepared.lane_id != self._lane
                        or prepared.code != "daemon_start"):
                    return False
                receipt_status = health_drop.delivery_receipt_status(
                    self.dir, prepared.to_dict())
                if receipt_status not in {
                        health_drop.DELIVERY_RECEIPT_EXACT,
                        health_drop.DELIVERY_RECEIPT_ABSENT}:
                    self._service_start_ledger_error = (
                        "service_start_receipt_" + receipt_status)
                    return False
                key = (count, event_type)
                existing = self._service_start_pending.get(key)
                if existing is not None \
                        and existing["event"].to_dict() != prepared.to_dict():
                    return False
                self._service_start_pending.setdefault(key, {
                    "event": prepared,
                    "accepted": (
                        receipt_status
                        == health_drop.DELIVERY_RECEIPT_EXACT),
                })
            return True
        except Exception:
            return False

    def _retry_service_start_events(self):
        if self._service_start_ledger_error:
            obligations = health_drop.read_service_start_pending(
                self._service_start_path)
            if obligations is not None:
                restored = all(
                    self._restore_service_start_obligation(item)
                    for item in obligations)
                if restored:
                    self._service_start_ledger_error = None
        # Fault evidence goes first when queue capacity is constrained.
        ordered = sorted(
            list(self._service_start_pending.items()),
            key=lambda pair: (
                0 if pair[1]["event"].severity == "fault" else 1,
                pair[0][0],
            ))
        for key, pending in ordered:
            if not pending["accepted"]:
                if not self._diagnostic_events_enabled():
                    continue
                durable_emit = getattr(
                    self.writer, "emit_durable", None)
                if callable(durable_emit):
                    pending["accepted"] = bool(
                        durable_emit(pending["event"], timeout=2.0))
                else:
                    # Test/minimal writer doubles have no persistence receipt;
                    # their boolean is their complete acceptance contract.
                    pending["accepted"] = self._emit_prebuilt(
                        pending["event"])
            if not pending["accepted"]:
                continue
            count, event_type = key
            event = pending["event"]
            row = event.to_dict()
            if health_drop.acknowledge_service_start_lane(
                    self._service_start_path, count, event_type,
                    event.lane_id, row["source_id"], row["boot_id"],
                    row["seq"]):
                self._service_start_pending.pop(key, None)
            else:
                # Do not enqueue duplicates in this process while durable
                # acknowledgement is retried.
                self.errors += 1

    def _poll_thermal(self):
        """R2-14: SoC temperature via sysfs (millidegrees C). Warn once per
        over-threshold episode; 5 °C hysteresis re-arms. Absent path (non-Pi
        host) disables the probe after one info log."""
        events_enabled = self._diagnostic_events_enabled()
        if self._thermal_missing:
            return
        path = "/sys/class/thermal/thermal_zone0/temp"
        try:
            with open(path) as f:
                temp_c = int(f.read().strip()) / 1000.0
        except FileNotFoundError:
            self._thermal_missing = True
            log.info("PlatformHealth: %s not present (non-Pi host) — thermal "
                     "probe disabled", path)
            return
        except Exception:
            self.errors += 1
            return
        thr = _env_float(TEMP_MAX_ENV, DEFAULT_TEMP_MAX_C)
        if self._thermal_active:
            self._thermal_active = temp_c >= thr - 5.0
        else:
            self._thermal_active = temp_c >= thr
        if (self._thermal_active and events_enabled
                and not self._thermal_warned):
            self._thermal_warned = self._emit(
                "warn", "pi_thermal", code="soc_temp",
                detail={"temp_c": round(temp_c, 1),
                        "threshold_c": thr})
        elif not self._thermal_active:
            self._thermal_warned = False

    def _poll_disk(self):
        """R2-14: free space on the diag volume + a read-only-filesystem
        write probe (the classic SD-card end-of-life mode: the card silently
        remounts ro and every 'successful' write vanishes)."""
        events_enabled = self._diagnostic_events_enabled()
        import shutil
        try:
            os.makedirs(self.dir, exist_ok=True)
            free_mb = shutil.disk_usage(self.dir).free / (1024.0 * 1024.0)
            floor = _env_float(DISK_MIN_ENV, DEFAULT_DISK_MIN_MB)
            if self._disk_low_active:
                self._disk_low_active = free_mb < floor * 1.2
            else:
                self._disk_low_active = free_mb < floor
            if (self._disk_low_active and events_enabled
                    and not self._disk_warned):
                self._disk_warned = self._emit(
                    "warn", "pi_disk_low", code="diag_volume",
                    detail={"free_mb": round(free_mb, 1),
                            "floor_mb": floor})
            elif not self._disk_low_active:
                self._disk_warned = False
        except Exception:
            self.errors += 1
        try:
            probe = os.path.join(self.dir, ".diag_write_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            self._readonly_active = False
            self._readonly_warned = False
        except Exception:
            self._readonly_active = True
            if events_enabled and not self._readonly_warned:
                self._readonly_warned = self._emit(
                    "fault", "pi_fs_readonly", code="diag_volume",
                    detail={"dir": self.dir})

    def _poll_clock_drift(self):
        """R2-14: wall-clock vs monotonic step detection. A big jump in
        (time.time() - time.monotonic()) is an NTP step / RTC-less cold boot
        correction — every UTC-stamped record around it is suspect. Warn per
        step, then re-baseline."""
        if not self._diagnostic_events_enabled():
            return
        if self._clock_pending is not None:
            if not self._emit_prebuilt(self._clock_pending["event"]):
                return
            self._clock_base = self._clock_pending["new_base"]
            self._clock_pending = None
        cur = time.time() - time.monotonic()
        if self._clock_base is None:
            self._clock_base = cur
            return
        thr = _env_float(CLOCK_DRIFT_ENV, DEFAULT_CLOCK_DRIFT_S)
        delta = cur - self._clock_base
        if abs(delta) >= thr:
            event = make_event(
                self._lane, "warn", "pi_clock_drift", code="wall_step",
                detail={"step_s": round(delta, 3),
                        "threshold_s": thr})
            if self._emit_prebuilt(event):
                self._clock_base = cur
            else:
                self._clock_pending = {
                    "event": event,
                    "new_base": cur,
                }

    def _poll_writer_drops(self):
        """R2-12: promote DiagQueue overflow drops + HTTP/outbox delivery
        drops to structured events (they were counters nobody read). Emits
        the DELTA once per poll; the event itself rides the same pipe, so a
        totally dead pipe is caught by the server-side lease going OFFLINE
        (R2-10), not by this."""
        if not self._diagnostic_events_enabled():
            return
        w = self.writer
        if w is None or not hasattr(w, "stats"):
            return
        s = w.stats()
        qd = int(s.get("queue_drops", 0) or 0)
        if qd > self._prev_queue_drops:
            if self._emit(
                    "warn", "diag_drops", code="queue_overflow",
                    detail={"new_drops": qd - self._prev_queue_drops,
                            "total": qd}):
                self._prev_queue_drops = qd
        elif qd < self._prev_queue_drops:
            self._prev_queue_drops = qd
        http_dropped = 0
        for name, sink in (s.get("sinks") or {}).items():
            http_dropped += int(sink.get("dropped", 0) or 0)
        ob = s.get("outbox") or {}
        http_dropped += int(ob.get("post_errors", 0) or 0)
        if http_dropped > self._prev_http_drops:
            if self._emit(
                    "warn", "http_sink_drops", code="delivery",
                    detail={"new": http_dropped - self._prev_http_drops,
                            "total": http_dropped,
                            "outbox": ob or None}):
                self._prev_http_drops = http_dropped
        elif http_dropped < self._prev_http_drops:
            self._prev_http_drops = http_dropped

        # R4: every persistence/replay honesty counter must be observable as a
        # delta. Cumulative counters remain useful forensic evidence, but a
        # recovered retry is not itself a permanently-active health fault.
        # Current health is derived separately from cursor_ok, pending_writes,
        # irrecoverable drops, and oldest-unsent age in machine_store.
        counter_sources = {}
        for sink_name, sink in (s.get("sinks") or {}).items():
            for field in ("write_errors", "retry_batches", "dropped",
                          "prune_deferred", "repaired_tails"):
                value = int(sink.get(field, 0) or 0)
                counter_sources[f"sink:{sink_name}:{field}"] = (
                    field, value, {"sink": sink_name})
        for field in ("corrupt_rows", "cursor_errors", "cursor_resets",
                      "quarantine_errors", "post_errors", "repaired_tails"):
            value = int(ob.get(field, 0) or 0)
            counter_sources[f"outbox:{field}"] = (
                field, value, {"outbox": ob or None})

        for key, (field, total, context) in counter_sources.items():
            prior = self._prev_diag_counters.get(key, 0)
            if total > prior:
                accepted = self._emit_diag_counter(
                    field, {
                        "counter": field,
                        "new": total - prior,
                        "total": total,
                        **context,
                    })
                if accepted:
                    self._prev_diag_counters[key] = total
            else:
                self._prev_diag_counters[key] = total

        for b in self.boards:
            health = b.link.parse_health()
            lane = b.cfg.lane
            parse_errors = int(health["parse_errors"])
            prior = self._prev_link_parse_errors.get(lane, 0)
            if parse_errors > prior:
                accepted = self._emit(
                    "warn", "diag_drops", code="uart_parse",
                    detail={"new_drops": parse_errors - prior,
                            "total": parse_errors,
                            "quarantined_lines":
                                health["quarantined_lines"]},
                    lane=lane)
                if accepted:
                    self._prev_link_parse_errors[lane] = parse_errors
            else:
                self._prev_link_parse_errors[lane] = parse_errors

            record_drops = int(health["diag_record_drops"])
            prior = self._prev_link_diag_drops.get(lane, 0)
            if record_drops > prior:
                accepted = self._emit(
                    "warn", "diag_drops", code="link_record_queue",
                    detail={"new_drops": record_drops - prior,
                            "total": record_drops,
                            "pending": health["pending_diag_records"]},
                    lane=lane)
                if accepted:
                    self._prev_link_diag_drops[lane] = record_drops
            else:
                self._prev_link_diag_drops[lane] = record_drops

    def _emit_diag_counter(self, field, detail):
        """Promote one known diagnostic counter with literal event types.

        Literal call sites are intentional: the vocabulary coverage gate can
        prove every emitted type belongs to machine_contract.json.
        """
        if field == "write_errors":
            return self._emit("warn", "diag_storage_error",
                              code="jsonl_write", detail=detail)
        elif field == "retry_batches":
            return self._emit("warn", "diag_storage_error",
                              code="jsonl_retry", detail=detail)
        elif field == "dropped":
            return self._emit(
                "warn", "diag_drops", code="sink_drop", detail=detail)
        elif field == "prune_deferred":
            return self._emit("warn", "diag_storage_error",
                              code="retention_deferred", detail=detail)
        elif field == "repaired_tails":
            return self._emit("warn", "diag_corrupt_row",
                              code="partial_tail_repaired", detail=detail)
        elif field == "corrupt_rows":
            return self._emit("warn", "diag_corrupt_row",
                              code="outbox_row", detail=detail)
        elif field == "cursor_errors":
            return self._emit(
                "warn", "diag_storage_error", code="cursor", detail=detail)
        elif field == "cursor_resets":
            return self._emit("warn", "diag_storage_error",
                              code="cursor_reset", detail=detail)
        elif field == "quarantine_errors":
            return self._emit("fault", "diag_storage_error",
                              code="quarantine", detail=detail)
        elif field == "post_errors":
            return self._emit("warn", "http_sink_drops",
                              code="outbox_post", detail=detail)
        return False

    def _poll_dir_retention(self):
        """R2-14: bound the diag dir (JSONL outbox + blackboxes live here).
        Retention is delegated to the writer's JSONL sink so its append lock
        and acknowledgement cursor protect every unshipped outbox record."""
        cap_mb = _env_float(DIR_MAX_MB_ENV, DEFAULT_DIR_MAX_MB)
        if cap_mb <= 0:
            return
        try:
            sink = getattr(getattr(self.writer, "outbox", None),
                           "_sink", None)
            if sink is None:
                for candidate in getattr(self.writer, "sinks", ()):
                    if (os.path.abspath(str(getattr(candidate, "dir", "")))
                            == os.path.abspath(self.dir)
                            and callable(getattr(
                                candidate, "prune_to_size", None))):
                        sink = candidate
                        break
            prune = getattr(sink, "prune_to_size", None)
            if not callable(prune):
                # Never fall back to an uncoordinated os.remove: the directory
                # may be a durable outbox whose cursor is owned by another
                # thread/process.
                self._emit(
                    "warn", "diag_storage_error",
                    code="retention_uncoordinated",
                    detail={"cap_mb": cap_mb})
                return
            result = prune(cap_mb * 1024.0 * 1024.0)
            if result["pruned"]:
                self._emit("info", "diag_storage_pruned", code="jsonl",
                           detail={"pruned": result["pruned"],
                                   "freed_mb": round(
                                       result["freed_bytes"] / 1048576.0, 1),
                                   "cap_mb": cap_mb})
        except Exception:
            self.errors += 1

    def _poll_throttled(self):
        """`vcgencmd get_throttled` -> 'pi_undervoltage' warn on a nonzero,
        CHANGED bitmask (bit 0 undervoltage now, 16 undervoltage occurred...)."""
        events_enabled = self._diagnostic_events_enabled()
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
        self._current_throttled = val
        if val and val != self._last_throttled and events_enabled:
            if self._emit(
                    "warn", "pi_undervoltage", code="get_throttled",
                    detail={"throttled": hex(val)}):
                self._last_throttled = val
        elif not val:
            self._last_throttled = 0


class BoardController:
    """One lane/board: link + io + FSM + the arm/watchdog GPIOs, plus the per-tick
    control logic. `sim=True` uses RecordingIO + a no-serial link so the assembly
    runs + self-tests off-Pi."""

    def __init__(self, cfg: BoardConfig, *, sim: bool = False, shadow=None,
                 cam_sink=None, diag_writer=None, cycle_shipper=None,
                 aux_roles=None, slow_debounce_n=None, fsm_debounce_n=None,
                 control_loop_clock=None):
        self.cfg = cfg
        self.sim = sim
        self.shadow = _shadow_enabled() if shadow is None else bool(shadow)
        # R2-6: the PCB revision is load-bearing config (it selects the IN-B
        # channel map). REFUSE to construct without an explicit one — the
        # board is then skipped by _build_boards (fail-safe: never ticked,
        # NE555 never kicked, rail stays down) with a loud log.
        if not cfg.board_rev:
            raise ValueError(
                f"L{cfg.lane}: board_rev is UNPROVISIONED — set it explicitly "
                f"(--board-revs '21=revC,22=revD' / {BOARD_REVS_ENV} in the "
                f"systemd env file / BoardConfig.board_rev). A silent revC "
                f"default would swallow AUX4-11 roles on a rev-D board.")
        roles = aux_roles
        if roles is None:
            roles = cfg.aux_roles if cfg.aux_roles is not None \
                else _aux_roles_for_lane(cfg.lane)
        roles = _validated_aux_role_map(
            roles, context=f"L{cfg.lane} AUX provisioning")
        _validate_aux_channels_for_revision(
            roles, lane=cfg.lane, board_rev=cfg.board_rev)
        self._allowed_fw_builds = _normalize_allowlist(
            cfg.allowed_fw_builds, FW_BUILD_ALLOWLIST_ENV)
        self._allowed_fw_cfgs = _normalize_allowlist(
            cfg.allowed_fw_cfgs, FW_CFG_ALLOWLIST_ENV)
        self._qualified_fw_releases = _normalize_qualified_releases(
            cfg.qualified_fw_releases)
        self._supported_fw_board_revisions = _normalize_allowlist(
            cfg.supported_fw_board_revisions,
            FW_SUPPORTED_BOARD_REVISIONS_ENV)
        if cfg.allow_legacy_revc_no_identity is not None:
            if type(cfg.allow_legacy_revc_no_identity) is not bool:
                raise ValueError(
                    "allow_legacy_revc_no_identity must be a bool when "
                    "provided programmatically")
            self._allow_legacy_revc_no_identity = \
                cfg.allow_legacy_revc_no_identity
        else:
            self._allow_legacy_revc_no_identity = _explicit_mode_flag(
                ALLOW_LEGACY_REVC_NO_IDENTITY_ENV)
        if cfg.legacy_revc_no_identity_enrolled is not None:
            if type(cfg.legacy_revc_no_identity_enrolled) is not bool:
                raise ValueError(
                    "legacy_revc_no_identity_enrolled must be a bool when "
                    "provided programmatically")
            self._legacy_revc_no_identity_enrolled = \
                cfg.legacy_revc_no_identity_enrolled
        else:
            enrolled = _parse_lane_set(os.environ.get(
                LEGACY_REVC_NO_IDENTITY_LANES_ENV))
            self._legacy_revc_no_identity_enrolled = cfg.lane in enrolled
        uid_map = _parse_lane_values(os.environ.get(PICO_UIDS_ENV))
        self._expected_uid = (str(cfg.expected_uid).strip()
                              if cfg.expected_uid is not None
                              else uid_map.get(cfg.lane))
        # Production preflights a writable, strict durable record before any
        # GPIO/I2C/UART hardware is opened. LIVE is bound to the systemd-owned
        # persistent directory; only simulation/explicit SHADOW may override
        # it for an isolated bench. Tests/simulation stay in-memory unless
        # they explicitly provide an override.
        state_dir = _identity_state_dir(sim=sim, shadow=self.shadow)
        self._identity_store = None
        self._controller_owner_lease = None
        identity_protocol_seen = False
        identity_evidence_callback = None
        if state_dir:
            self._identity_store = IdentityEvidenceStore(
                state_dir, cfg.lane)
            # All physical modes, including SHADOW, own a nonblocking
            # process-lifetime per-lane lease. Acquire it BEFORE loading
            # legacy authorization and before any GPIO/I2C/UART import/open.
            # safe_off()/mid-run trips deliberately do not release it.
            if not sim:
                lease = ControllerOwnerLease(state_dir, cfg.lane)
                lease.acquire()
                self._controller_owner_lease = lease
            try:
                identity_state = self._identity_store.load_or_initialize()
            except Exception:
                if self._controller_owner_lease is not None:
                    self._controller_owner_lease.release()
                    self._controller_owner_lease = None
                raise
            identity_protocol_seen = identity_state["identity_capable"]
            identity_evidence_callback = \
                self._identity_store.mark_identity_capable
        # Incremented only after a complete tick() return. PlatformHealth
        # reports it so an independent heartbeat thread cannot make a stalled
        # 50 Hz controller loop look alive.
        self.control_loop_seq = 0
        self._wdog = None
        self._arm_led = None

        # Flight recorder (idea #10): observe-only, bounded, default ON. Injected into
        # the io so every output change + arm is captured; dumped on a safety trip.
        self.recorder = FlightRecorder(cfg.lane)

        if sim:
            # The link shares the io's (fake, advanceable) clock so fw-estimated
            # edge times and Pi-side telemetry times live on ONE timebase — the
            # lambda resolves self.io lazily (io is built on the next line).
            self.link = RP2040Link(
                now=lambda: self.io.now(),
                identity_protocol_seen=identity_protocol_seen,
                identity_evidence_callback=identity_evidence_callback)
            self.io = RecordingIO(rp2040=self.link, recorder=self.recorder,
                                  board_rev=cfg.board_rev)
        else:
            from gpiozero import LED                       # lazy: Pi-only
            self._arm_led = LED(cfg.arm_pin)               # de-asserted by default
            self._wdog = LED(cfg.wdog_pin)
            self.link = RP2040Link(
                port=cfg.uart_port,
                identity_protocol_seen=identity_protocol_seen,
                identity_evidence_callback=identity_evidence_callback)
            self.io = MachineIO(
                cfg.lane, cfg.i2c_bus, rp2040=self.link,
                watchdog_kick=self._kick_wdog,             # poll() calls this
                arm_relays=self._set_arm,
                recorder=self.recorder,
                board_rev=cfg.board_rev,
            )
            self.link.start()                              # background serial reader

        # Even while the link lock freezes mutations, its monotonic heartbeat
        # deadline can expire during a slow I2C/event operation. Guard every
        # safety-positive physical actuation at the call site.
        self.io = FreshnessGuardIO(self.io, self.link)

        # SHADOW/CANARY SOAK (idea #11): wrap the real io so the FSM drives NOTHING.
        # The wrapper records every command the FSM WOULD have issued and hard-holds
        # the real ARM LOW. main() permits construction only after exactly one
        # explicit LIVE/SHADOW acknowledgment; direct test construction may inject
        # `shadow=` without consulting process environment.
        if self.shadow:
            self.io = ShadowIO(self.io, recorder=self.recorder)
            log.warning("L%s: SHADOW MODE active (%s set) — FSM runs on real inputs but "
                        "drives NOTHING; ARM hard-held LOW", cfg.lane, SHADOW_ENV)

        # Separate from RP2040 heartbeat freshness: the reader thread can keep
        # receiving heartbeats while the control thread is descheduled.  Keep a
        # per-board completion clock so that fresh link state cannot erase a
        # control-loop discontinuity. Production and ordinary simulation use
        # the suspend-aware host clock above; tests that model scheduler gaps
        # inject a dedicated fake clock so advancing machine/FSM time does not
        # accidentally model a stopped controller thread.
        self._control_loop_clock = (
            control_loop_clock if control_loop_clock is not None
            else _suspend_aware_monotonic
        )
        self._last_control_tick_complete_at = None
        self._control_loop_gap_latched = False
        self._control_loop_gap_detail = None

        # Diagnostics event pipe (2026-07-19 scope): per-lane rules + suppression
        # over the shared DiagWriter. writer=None (sim/tests default) keeps the
        # rules running but emission local-only; main() wires the real writer.
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
                sev, et, code=code, detail=detail, t=self.io.now(),
                persistent=True, retain_across_blind=True))

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
        self._diag_deb = {}     # diagnostics debounce for IN-A watched inputs
        self._diag_inb_deb = {} # IN-B state is discarded on bank/key UNKNOWN
        self._diag_health_inputs = {
            role: next((name for name, mapped in roles.items()
                        if mapped == role), None)
            for role in ("field_wet_ok", SENSOR_24V_ROLE)
        }
        self._diag_missing_health = set()
        self._diag_health_levels = {}
        self._diag_sensor_dependents = {
            name for name, role in roles.items()
            if role in SENSOR_24V_DEPENDENT_ROLES
        }
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
        self._identity_refused = False  # R3-5: one-time log latch for id arm refusal
        self._identity_escape_logged = False  # R3-5: bench-escape warned once
        # A failed identity/max-run prerequisite is a latched safe-state episode.
        # Recovery only re-enables PBZ processing; it never re-arms by itself.
        self._arm_prereq_latched = False
        self._arm_prereq_reason = None
        # A safety inhibit requires a successfully sampled, debounce-stable PBZ
        # release before any later press may dispatch. Set by _hard_safe before
        # its first hardware action and cleared only after a complete input
        # sample succeeds; exceptions cannot erase it.
        self._pbz_release_required = False
        self._pbz_release_samples = 0
        self._was_healthy = True
        self._prev_arm = False     # rail_drop emitter: last commanded arm value
        # Last successfully commanded PHYSICAL ARM posture. In shadow mode a
        # successful `io.arm(True)` is only a recorded wish, so this stays False.
        self._arm_state = False
        self._live_outputs_acknowledged = bool(
            not self.shadow and _live_acknowledged())
        # machine_cycles row bookkeeping (assembled at cycle completion, shipped
        # via the CycleShipper thread — scope §2 schema)
        self._cycle_open = False
        self._telemetry_baseline_cycle_eligible = False
        self._cycle_started_utc = None
        self._cycle_ball = None
        self.failed = False        # set by run() when TICK_ERROR_BUDGET is exhausted
        # Any incomplete hard-safe action is daemon-fatal: exiting nonzero lets
        # systemd ExecStopPost retry both lanes' GPIO safe-off.
        self.fatal = False
        self.tick_errors = 0       # consecutive tick() exceptions (reset on success)
        # R2-12 promotion state (all edge-triggered, once per episode)
        self._bank_fail_n = 0      # consecutive IN-B read failures
        self._bank_warned = False
        self._run_mm_since = None  # first t the link reported a run mismatch
        self._run_mm_warned = False
        self._run_mm_fault_code = None
        self._v5_warned = False
        self._diag_gate_states = {
            name: _env_on(name)
            for name in (DIAG_EVENTS_ENV, AUX_RULE_ENV, MANUAL_RULE_ENV,
                         STUCK_RULE_ENV, BEAM_RULE_ENV)
        }
        self._diag_master_reconcile_pending = False
        self._diag_identity_reconcile_pending = False
        self._unexpected_edge_gate_state = _env_on(DIAG_EVENTS_ENV)
        self._unexpected_edge_blind_keys = set()
        self._tapdump_requested_ep = None  # one TAPDUMP request per boot epoch
        # Immutable-generation report committed only after a complete control
        # tick. PlatformHealth never assembles a mixed-time view from mutable
        # board/link fields.
        self._runtime_snapshot_lock = threading.Lock()
        self._runtime_snapshot = None
        discontinuity = self.link.heartbeat_discontinuity_status()
        self._seen_link_discontinuity = discontinuity["generation"]
        self._seen_reboot_discontinuity = \
            discontinuity["reboot_generation"]
        self._seen_wdt_reboot_discontinuity = \
            discontinuity["wdt_reboot_generation"]

    # ---- real-hardware GPIO callbacks -------------------------------------
    def _kick_wdog(self):
        if self._wdog is not None:
            # Bounded pulse, resting LOW (see WDOG_PULSE_S). Never toggle(): a
            # stall with the pin latched HIGH would defeat the NE555 forever.
            require_positive_actuation_freshness(
                self.link, "watchdog-kick-gpio")
            try:
                self._wdog.on()
                time.sleep(WDOG_PULSE_S)
            finally:
                # Also runs if gpiozero reports an error after changing the pad.
                self._wdog.off()

    def _set_arm(self, on):
        if self._arm_led is not None:
            if on:
                require_positive_actuation_freshness(
                    self.link, "arm-high-gpio")
            self._arm_led.value = 1 if on else 0

    # ---- per-tick control logic -------------------------------------------
    def _slow_edges(self, *, dispatch_actions=True):
        """Read the watched IN-A slow inputs, fire FSM actions on rising edges,
        and return this tick's RAW {name: level} so the diagnostics rules reuse
        the SAME reads (no duplicate I²C traffic; _diag_poll applies the
        diagnostics-path debounce to these raw levels).

        FSM action edges go through the FSM debouncer — n=1 by default, which
        is EXACT legacy raw behavior; see SLOW_DEBOUNCE_FSM_ENV (safety-path
        semantics only change when that knob is deliberately raised)."""
        levels = {}
        # Snapshot the gate for the whole sample. A release may clear it only
        # after every watched input read succeeds; the same tick never turns a
        # release into a dispatch.
        pbz_blocked = self._pbz_release_required
        for name in self._watched:
            raw = bool(self.io.read_input(name))
            levels[name] = raw
            cur = self._fsm_deb[name].update(raw)          # n=1 -> cur == raw
            action = self._actions.get(name)
            if (dispatch_actions and action is not None
                    and not (name == "PBZ" and pbz_blocked)
                    and cur and not self._prev_slow[name]):
                action()                                   # rising (debounce-stable) edge
            self._prev_slow[name] = cur
        # Commit the release only after the complete read batch. If any later
        # read above raises, this line is unreachable and the latch survives.
        if self._pbz_release_required:
            if levels.get("PBZ") is False:
                self._pbz_release_samples += 1
                if self._pbz_release_samples >= max(1, self._fsm_deb_n):
                    self._pbz_release_required = False
                    self._pbz_release_samples = 0
            else:
                self._pbz_release_samples = 0
        return levels

    def _legacy_identity_mode(self):
        """Whether this lane is currently eligible for unverified legacy Rev-C.

        Both explicit acknowledgments are required and durable per-lane
        evidence permanently closes the escape once a modern protocol record
        is observed, including after daemon restart.
        """
        return bool(
            self.cfg.board_rev == "revC"
            and self._allow_legacy_revc_no_identity
            and self._legacy_revc_no_identity_enrolled
            and not self.link.identity_protocol_seen()
            and self.link.fw_identity() is None)

    def _identity_arm_ok(self, *, allow_shadow_bypass=True):
        """Return whether firmware identity is trustworthy enough to ARM.

        Every identity-bearing board requires current nonce evidence, PCB/RID
        agreement, an exact qualified revision/build/config tuple, an explicitly supported
        declared board revision, non-FI1 posture, and (when provisioned) its
        expected Pico UID. A truly legacy Rev-C image that emits no identity is
        the sole compatibility exception, and only behind the explicit
        WSL_ALLOW_LEGACY_REVC_NO_IDENTITY=1 installed-base acknowledgment. The
        old mismatch escape is honored only in SHADOW mode, where physical ARM
        is already held low.
        """
        if _env_on("WSL_ALLOW_IDENTITY_MISMATCH", default="0"):
            if not self._identity_escape_logged:
                log.warning("L%s: identity bypass requested; only SHADOW mode "
                            "may bypass because it hard-holds physical ARM low",
                            self.cfg.lane)
                self._identity_escape_logged = True
            if self.shadow and allow_shadow_bypass:
                return True, None

        if self.link.identity_evidence_error() is not None:
            return False, "identity_evidence_persist_failed"
        ident = self.link.fw_identity()
        declared = self.cfg.board_rev
        if ident is None:
            # Rev-C predates the identity protocol. Keep that installed-base
            # path available, but do not generalize the exception to Rev-B or
            # Rev-D, and never use it once an identity-bearing image responds.
            if self._legacy_identity_mode():
                return True, None
            if (declared == "revC"
                    and self.link.identity_protocol_seen()):
                return False, "identity_protocol_required"
            return False, "identity_not_received"

        link_ok, reason = self.link.identity_status()
        if not link_ok:
            return False, reason
        expected_pcb = "unknown" if declared == "revC" else declared
        if ident.get("pcb") != expected_pcb:
            return False, "pcb_rev_mismatch"
        expected_rid = 255 if declared == "revC" else 1
        if ident.get("rid") != expected_rid:
            return False, "rid_mismatch"
        hb_rid = self.link.pcb_rev_id()
        if hb_rid is not None and hb_rid != ident.get("rid"):
            return False, "rid_heartbeat_mismatch"
        if declared not in self._supported_fw_board_revisions:
            return False, "board_revision_not_supported"

        build = ident.get("build")
        if build == "unknown" or str(build).endswith("-dirty"):
            return False, "build_unreleaseable"

        fw_cfg = ident.get("cfg")
        if fw_cfg == "unknown":
            return False, "cfg_unreleaseable"
        if not self._qualified_fw_releases:
            return False, "qualified_release_policy_unconfigured"
        if (declared, build, fw_cfg) not in self._qualified_fw_releases:
            return False, "qualified_release_not_allowed"

        if self._expected_uid is not None:
            if str(ident.get("uid", "")).casefold() != \
                    self._expected_uid.casefold():
                return False, "uid_mismatch"
        return True, None

    def tick(self):
        tick_started_at = self._latch_control_loop_gap_before_tick()
        # Same-tick reconciliation dedupe is a per-control-sample scratch set,
        # not a session-long cache. Bound it and allow later real episodes with
        # the same type/code to reconcile independently.
        self.diag.start_event_generation()
        # Observe a dynamic diagnostic master-gate transition before any
        # safety/identity producer in this tick can emit. This defines one
        # attempt-generation so the later current-state reconciliation cannot
        # duplicate a naturally emitted transition event in the same sample.
        self._sync_diag_gate_generation(self.io.now())
        # One bounded transaction freezes health/identity/max-run facts and
        # snapshots inbound motion before the precheck. No identity
        # invalidation can race event dispatch while ARM remains permitted.
        try:
            with self.link.control_transaction() as events:
                # Acquiring the link transaction can itself be delayed (for
                # example, if the serial reader is descheduled while holding
                # the state lock). Re-sample only after ownership is obtained:
                # a fresh heartbeat admitted just before lock release must not
                # hide a stopped controller thread and permit one resumed
                # positive tick. No event has been dispatched at this point.
                locked_started_at = \
                    self._latch_control_loop_gap_before_tick()
                tick_started_at = locked_started_at
                entered_healthy = self.link.health_ok()
                self._tick_once(events)
                self.control_loop_seq += 1
                try:
                    self._commit_runtime_snapshot()
                    # Observe/report work runs after the final positive
                    # command. If it stalls past a heartbeat deadline, do not
                    # return with ARM asserted or expose its snapshot.
                    # Initially-unhealthy safe-drain ticks remain non-raising.
                    if entered_healthy:
                        self._require_link_fresh("tick_completion")
                except Exception:
                    # The public progress counter advances only for a fully
                    # completed, freshness-checked control tick.
                    self.control_loop_seq -= 1
                    raise
            # Commit continuity only after the complete, freshness-checked tick
            # returned from its transaction.  A raised/partial tick cannot move
            # the baseline forward and hide the next gap.
            if tick_started_at is not None:
                self._last_control_tick_complete_at = tick_started_at
        except LinkFreshnessError:
            # A point-of-actuation deadline guard is an immediate safety trip,
            # not an ordinary transient tick error that may consume a budget.
            with self._runtime_snapshot_lock:
                self._runtime_snapshot = None
            self._was_healthy = False
            self._hard_safe("rp2040_heartbeat_expired_during_tick")
            raise
        except Exception:
            with self._runtime_snapshot_lock:
                self._runtime_snapshot = None
            raise

    def _latch_control_loop_gap_before_tick(self):
        """Latch a control-thread discontinuity before any positive operation.

        Returns the valid entry-clock sample for commit after a complete tick,
        or ``None`` when the clock itself is invalid.  Once set, the latch is
        cleared only after `_tick_once` completes the hard-safe/drain path.
        """
        try:
            raw_now = self._control_loop_clock()
            valid = (
                isinstance(raw_now, (int, float))
                and not isinstance(raw_now, bool)
                and math.isfinite(float(raw_now))
            )
            now = float(raw_now) if valid else None
        except Exception as exc:
            now = None
            raw_now = f"{type(exc).__name__}: {exc}"

        previous = self._last_control_tick_complete_at
        if now is None:
            self._control_loop_gap_latched = True
            self._control_loop_gap_detail = {
                "reason": "clock_invalid",
                "sample": str(raw_now)[:120],
            }
            return None
        if previous is not None:
            gap = now - previous
            if (
                    not math.isfinite(gap)
                    or gap < 0.0
                    or gap > CONTROL_LOOP_GAP_MAX_S):
                self._control_loop_gap_latched = True
                self._control_loop_gap_detail = {
                    "reason": (
                        "clock_regressed" if gap < 0.0
                        else "completion_gap_exceeded"),
                    "gap_s": gap,
                    "limit_s": CONTROL_LOOP_GAP_MAX_S,
                }
        return now

    def _commit_runtime_snapshot(self):
        """Commit one exact, immutable-generation controller report.

        Called only after a complete tick while the link transaction lock is
        still held. A reporting thread can therefore never combine identity,
        taps, posture, and progress from different heartbeat generations.
        """
        hb = self.link.heartbeat_sample()
        if hb is None:
            sample = None
        else:
            ident = self.link.fw_identity() or {}
            identity_ok, identity_reason = self._identity_arm_ok(
                allow_shadow_bypass=False)
            sample = {
                "lane_id": self.cfg.lane,
                "controller_boot_id": _CONTROLLER_BOOT_ID,
                "control_loop_seq": self.control_loop_seq,
                "board_rev": self.cfg.board_rev,
                "observed_pcb": ident.get("pcb"),
                "observed_rid": (
                    str(ident.get("rid"))
                    if ident.get("rid") is not None else None),
                "observed_uid": ident.get("uid"),
                "fw_build": ident.get("build"),
                "fw_cfg": ident.get("cfg"),
                "fw_version": ident.get("fw") or self.link.fw_version(),
                "identity_ok": identity_ok,
                "identity_reason": identity_reason,
                **self.runtime_diagnostics(
                    (identity_ok, identity_reason)),
                **self.link.parse_health(),
                "_link_hb_generation": hb["generation"],
                "_link_discontinuity_generation":
                    self.link.heartbeat_discontinuity_generation(),
            }
        with self._runtime_snapshot_lock:
            self._runtime_snapshot = sample

    @staticmethod
    def _copy_runtime_snapshot(snapshot):
        result = dict(snapshot)
        result["safety_taps"] = dict(snapshot["safety_taps"])
        return result

    def telemetry_snapshot(self):
        """Return a current exact-generation report, or ``None`` fail-closed."""
        with self.link.state_transaction():
            hb = self.link.heartbeat_sample()
            if hb is None:
                return None
            with self._runtime_snapshot_lock:
                snapshot = self._runtime_snapshot
                if snapshot is None:
                    return None
                if (
                        snapshot["_link_hb_generation"] != hb["generation"]
                        or snapshot["_link_discontinuity_generation"]
                        != self.link.heartbeat_discontinuity_generation()):
                    return None
                return self._copy_runtime_snapshot(snapshot)

    def unavailable_telemetry_snapshot(self, reason="runtime_sample_unavailable"):
        """Build a schema-complete red health-drop board without stale taps."""
        state = getattr(self.fsm.state, "value", str(self.fsm.state))
        return {
            "lane_id": self.cfg.lane,
            "controller_boot_id": _CONTROLLER_BOOT_ID,
            "control_loop_seq": self.control_loop_seq,
            "board_rev": self.cfg.board_rev,
            "fw_build": None,
            "fw_cfg": None,
            "identity_ok": False,
            "identity_reason": reason,
            "controller_mode": "shadow" if self.shadow else "live",
            "live_outputs_acknowledged":
                bool(self._live_outputs_acknowledged),
            "arm_state": bool(self._arm_state),
            "fsm_state": str(state),
            "manual_rearm_required": True,
            "legacy_identity_mode": False,
            "identity_assurance": "invalid",
            "arm_prerequisite_reason": reason,
            "safety_taps": {
                "ne555": None,
                "wdog_kick": None,
                "arm_permit": None,
                "rp2040_ok": None,
            },
            **self.link.parse_health(),
        }

    def _command_arm(self, on, reason):
        """Command ARM and update diagnostics only after the write succeeds."""
        self.io.arm(bool(on))
        self._note_arm(bool(on), reason)
        self._arm_state = bool(on) and not self.shadow

    def _hard_safe(self, reason, *, raise_on_failure=True):
        """Best-effort hard-safe sequence with independent failure handling.

        ARM-low is always attempted first. Firmware STOP, physical all-off, and
        FSM relatch each run even when a prior action failed. Any failed action
        immediately retires this board and forces its watchdog pin low so the
        shared run loop cannot resume/kick a board whose safe state is unknown.
        """
        self._pbz_release_required = True
        self._pbz_release_samples = 0
        errors = []

        def attempt(name, action, *, require_truthy=False):
            try:
                result = action()
                if require_truthy and result is not True:
                    raise RuntimeError(f"{name} was not acknowledged")
            except Exception as exc:
                errors.append((name, exc))
                log.exception("L%s hard-safe %s failed", self.cfg.lane, name)

        # Order is safety-significant: cut the external permit before any
        # serial/I2C work, logging, recorder dump, or logical state repair.
        attempt("arm_low", lambda: self._command_arm(False, reason))
        attempt("firmware_stop_all", self.link.stop_all, require_truthy=True)

        all_off = getattr(self.io, "all_off", None)
        if callable(all_off):
            attempt("physical_outputs_off", all_off)
        else:
            # RecordingIO/older adapters expose only per-output methods. Keep
            # these independent so one injected failure cannot skip the rest.
            attempt("physical_sweep_off", lambda: self.io.set_sweep(False))
            attempt("physical_table_off", lambda: self.io.set_table(False))
            attempt("physical_spot_off", lambda: self.io.set_spot(False))

        attempt("fsm_relatch", self.fsm.power_restore)
        # power_restore sets state only after its output calls. If one of those
        # calls raised, force the in-memory safety latch anyway; the board is
        # retired below because physical state is no longer provable.
        def force_fsm_latch():
            self.fsm.state = State.MANUAL_INTERVENTION
            for motor in getattr(self.fsm, "_energized_since", {}):
                self.fsm._energized_since[motor] = None
        attempt("fsm_memory_relatch", force_fsm_latch)

        if errors:
            self.failed = True
            self.fatal = True
            try:
                if self._wdog is not None:
                    self._wdog.off()
            except Exception as exc:
                errors.append(("watchdog_low", exc))
                log.exception("L%s hard-safe watchdog-low failed",
                              self.cfg.lane)
            message = ", ".join(
                f"{name}: {type(exc).__name__}: {exc}"
                for name, exc in errors)
            if raise_on_failure:
                raise HardSafeError(
                    f"L{self.cfg.lane} hard-safe incomplete ({message})")
        return not errors

    def _active_motion_latches(self):
        """Return motion outputs active in either FSM tracking or IO state."""
        energized = getattr(self.fsm, "_energized_since", {})
        active = {name for name, since in energized.items()
                  if since is not None}
        # RecordingIO exposes human-readable keys; MachineIO retains the last
        # commanded relay state under firmware motor names. Inspect both so an
        # FSM/IO bookkeeping divergence cannot hide a latent physical command.
        outputs = getattr(self.io, "outputs", {})
        for name in ("sweep", "table", "spot"):
            if bool(outputs.get(name, False)):
                active.add(name)
        out_state = getattr(self.io, "_out_state", {})
        for raw, name in (("S", "sweep"), ("T", "table"), ("SP", "spot")):
            if bool(out_state.get(raw, False)):
                active.add(name)
        return sorted(active)

    def _evaluate_arm_preconditions(self):
        """Evaluate and episode-log every non-FSM prerequisite for ARM."""
        mr_ok = self.link.maxrun_ok()
        if not mr_ok and not self._maxrun_refused:
            log.error("L%s: REFUSING to arm — firmware maxrun_ms=%s is below the "
                      "FSM's MAX_MOTION_S (constants desynchronized; reconcile + "
                      "reflash before arming)", self.cfg.lane,
                      self.link.maxrun_ms())
            self.diag.emit_event(
                "fault", "fw_config_mismatch", code="maxrun_desync",
                detail={"fw_maxrun_ms": self.link.maxrun_ms(),
                        "fw_version": self.link.fw_version()},
                t=self.io.now(), persistent=True)
        elif mr_ok and self._maxrun_refused:
            log.info("L%s: max-run ceiling reconciled; a fresh First-Ball-Zero "
                     "is still required", self.cfg.lane)
            self.diag.emit_event("info", "recovered",
                                 code="fw_config_mismatch",
                                 detail={
                                     "recovered_event_type":
                                         "fw_config_mismatch",
                                     "recovered_code": "maxrun_desync",
                                 },
                                 t=self.io.now())
        if mr_ok:
            self.diag.cancel_pending_event_type("fw_config_mismatch")
        self._maxrun_refused = not mr_ok

        id_ok, id_reason = self._identity_arm_ok()
        prior_id_reason = getattr(self, "_identity_refusal_reason", None)
        if not id_ok and (not self._identity_refused
                          or prior_id_reason != id_reason):
            log.error("L%s: REFUSING to arm — firmware identity %s "
                      "(no live-output bypass)", self.cfg.lane, id_reason)
        elif id_ok and self._identity_refused:
            log.info("L%s: firmware identity resolved; a fresh First-Ball-Zero "
                     "is still required", self.cfg.lane)
        if id_ok:
            # Clear superseded fault-coded identity retries, but keep a
            # rejected healthy provenance record (code=None) deliverable.
            self.diag.cancel_pending_event_type(
                "fw_identity", preserve_codes=(None,))
            self.diag.cancel_pending_event_type("fw_identity_missing")
        self._identity_refused = not id_ok
        self._identity_refusal_reason = id_reason if not id_ok else None

        if not mr_ok:
            return False, "maxrun_desync"
        if not id_ok:
            return False, "identity_" + str(id_reason)
        return True, None

    def _latch_arm_precondition(self, reason):
        """Hard-safe an identity/max-run inhibit and require a new PBZ edge."""
        active = self._active_motion_latches()
        prior_state = getattr(self.fsm.state, "value", "?")
        first_episode = not self._arm_prereq_latched
        self._arm_prereq_reason = reason
        self._arm_prereq_latched = True
        self._last_inhibit_active = list(active)

        if first_episode or active or \
                self.fsm.state is not State.MANUAL_INTERVENTION:
            hard_safe_error = None
            try:
                self._hard_safe(reason)
            except HardSafeError as exc:
                hard_safe_error = exc
            if active:
                log.critical(
                    "L%s: ARM prerequisite %s failed with motion latch(es) %s "
                    "active -> HARD SAFETY TRIP", self.cfg.lane, reason, active)
                self._on_safety_trip("arm_inhibit_with_motion_latched")
            if hard_safe_error is not None:
                raise hard_safe_error
            if not active:
                log.error("L%s: ARM prerequisite %s failed -> motors off, "
                          "MANUAL_INTERVENTION; fresh First-Ball-Zero required",
                          self.cfg.lane, reason)
        return prior_state, active

    def _drain_inhibited_control_inputs(self, events):
        """Discard motion/PBZ control edges while preserving input baselines."""
        discarded_ball = any(event[0] == "ball" for event in events)
        discarded = self.link.apply_event_batch(
            events, _INHIBITED_EVENT_SINK)
        if discarded_ball and self.diag.ball_tracker is not None:
            self.diag.ball_tracker.note_unverifiable_ball(self.io.now())
        slow_levels = self._slow_edges(dispatch_actions=False)
        if discarded:
            log.warning("L%s: discarded %d firmware control edge(s) while ARM "
                        "prerequisite was inhibited", self.cfg.lane, discarded)
        return slow_levels

    def _finish_inhibited_tick(self, slow_levels):
        """Keep the watchdog and observe-only diagnostics alive while safe-off."""
        if self.link.health_ok():
            self.fsm.poll()
        self._observe()
        self._diag_poll(slow_levels)

    def _require_link_fresh(self, stage):
        if not self.link.health_ok():
            raise LinkFreshnessError(
                f"RP2040 heartbeat/health expired during {stage}")

    def _tick_once(self, events):
        discontinuity_status = self.link.heartbeat_discontinuity_status()
        discontinuity = discontinuity_status["generation"]
        link_discontinuity = discontinuity != self._seen_link_discontinuity
        reboot_discontinuity = (
            discontinuity_status["reboot_generation"]
            != self._seen_reboot_discontinuity)
        wdt_reboot_discontinuity = (
            discontinuity_status["wdt_reboot_generation"]
            != self._seen_wdt_reboot_discontinuity)
        if link_discontinuity or self._control_loop_gap_latched:
            # A malformed sample followed by a good sample can be buffered and
            # parsed before the 50 Hz loop runs. Firmware reboot and local
            # control-loop gap generations obey the same rule: current good
            # health can never erase an intervening loss before a hard-safe
            # sample/drain and fresh operator PBZ.
            # No diagnostic debounce candidate or absence/attribution timer may
            # cross the same blind interval.  Invalidate before hard-safe so an
            # exception cannot preserve apparently-continuous evidence; the
            # inhibited sample below then establishes fresh raw baselines.
            self._mark_diagnostics_unavailable(self.io.now())
            reasons = []
            if link_discontinuity:
                # Preserve the established rail-drop reason: the monotonic
                # generation proves an intervening unhealthy episode even if
                # current heartbeat fields have already recovered.
                reasons.append("rp2040_link_unhealthy")
            if self._control_loop_gap_latched:
                reasons.append("controller_loop_gap")
                log.error(
                    "L%s: controller-loop continuity LOST (%s) -> hard-safe; "
                    "fresh First-Ball-Zero required",
                    self.cfg.lane, self._control_loop_gap_detail)
            hard_safe_error = None
            try:
                self._hard_safe("+".join(reasons))
            except HardSafeError as exc:
                hard_safe_error = exc
            self._was_healthy = False
            if link_discontinuity:
                self._on_safety_trip(
                    "rp2040_link_lost",
                    fw_fault_override=(
                        REBOOT_FAULT if reboot_discontinuity
                        else HEARTBEAT_SCHEMA_FAULT),
                    reboot_wdt_override=wdt_reboot_discontinuity)
            if self._control_loop_gap_latched:
                # Record the discontinuity even if ARM was already low.  The
                # arm-transition rail_drop event is useful when asserted, but
                # it cannot be the only durable evidence of a stopped control
                # thread because a disarmed/maintenance lane can still suffer
                # the same scheduler, suspend, or clock fault.
                self._on_safety_trip("controller_loop_gap")
            if hard_safe_error is not None:
                raise hard_safe_error
            slow_levels = self._drain_inhibited_control_inputs(events)
            self._finish_inhibited_tick(slow_levels)
            # Commit only after the complete safe sample/drain. Any exception
            # above leaves both discontinuities pending for the retry.
            self._seen_link_discontinuity = discontinuity
            self._seen_reboot_discontinuity = \
                discontinuity_status["reboot_generation"]
            self._seen_wdt_reboot_discontinuity = \
                discontinuity_status["wdt_reboot_generation"]
            self._control_loop_gap_latched = False
            self._control_loop_gap_detail = None
            return
        healthy = self.link.health_ok()

        if not healthy:
            # RP2040 unhealthy: RP_OK has already dropped the HARDWARE rail. Make it a real
            # SOFTWARE safety trip too — force motion outputs OFF (clears the relay latches)
            # and latch the FSM into MANUAL_INTERVENTION so recovery REQUIRES a deliberate
            # First-Ball-Zero. Without this, a heartbeat blip drops ARM while sweep is still
            # latched, then silently re-arms with the stale latch -> uncommanded motion.
            first_loss = self._was_healthy
            self._was_healthy = False
            if first_loss:
                hard_safe_error = None
                try:
                    self._hard_safe("rp2040_link_unhealthy")
                except HardSafeError as exc:
                    hard_safe_error = exc
                self.io.log(f"L{self.cfg.lane}: RP2040 link LOST "
                            f"(fault={self.link.fault()!r} alive={self.link.is_alive()} "
                            f"rp_ok={self.link.rp_ok()}) -> SAFETY TRIP: motors off, require First-Ball-Zero")
                self._on_safety_trip("rp2040_link_lost")
                if hard_safe_error is not None:
                    raise hard_safe_error
            slow_levels = self._drain_inhibited_control_inputs(events)
            self._finish_inhibited_tick(slow_levels)
            return

        if not self._was_healthy:
            # One safe recovery tick baselines PBZ and discards any queued
            # motion edge. A PBZ pressed/held during the outage cannot become a
            # synthetic recovery edge on the first healthy sample.
            self._hard_safe("rp2040_link_recovered_wait_pbz")
            slow_levels = self._drain_inhibited_control_inputs(events)
            self._finish_inhibited_tick(slow_levels)
            # Commit recovery only after the whole safe sample/poll completed;
            # an input-read exception leaves the outage latch intact.
            self._was_healthy = True
            self.io.log(f"L{self.cfg.lane}: RP2040 link recovered -> awaiting First-Ball-Zero")
            return
        self._was_healthy = True

        prereq_ok, prereq_reason = self._evaluate_arm_preconditions()
        if not prereq_ok:
            self._latch_arm_precondition(prereq_reason)
            slow_levels = self._drain_inhibited_control_inputs(events)
            self._finish_inhibited_tick(slow_levels)
            return

        if self._arm_prereq_latched:
            # Recovery is deliberately one safe tick: drain any edge that raced
            # the prerequisite transition and baseline PBZ. A PBZ already held
            # before recovery therefore cannot count; release + re-press it.
            prior_reason = self._arm_prereq_reason
            self._hard_safe("arm_prerequisite_recovered_wait_pbz")
            slow_levels = self._drain_inhibited_control_inputs(events)
            self._finish_inhibited_tick(slow_levels)
            # Commit recovery only after the complete input batch succeeds.
            self._arm_prereq_latched = False
            self._arm_prereq_reason = None
            log.info("L%s: ARM prerequisite %s recovered -> still DISARMED; "
                     "awaiting a fresh First-Ball-Zero", self.cfg.lane,
                     prior_reason)
            return

        self.link.apply_event_batch(
            events, self.fsm, self._edge_observer)
        self._require_link_fresh("event_dispatch")
        slow_levels = self._slow_edges()      # PBZ/BS/Foul -> FSM (+ levels for diagnostics)
        self._require_link_fresh("slow_input_sample")
        self.fsm.poll()                       # advance FSM + kick NE555 via io
        self._require_link_fresh("fsm_poll")

        # Recheck immediately before ARM assertion. The link transaction keeps
        # the safety snapshot stable; this second check also catches any
        # controller-side mutation introduced by dispatch/poll.
        prereq_ok, prereq_reason = self._evaluate_arm_preconditions()
        self._require_link_fresh("pre_arm_evaluation")
        if not prereq_ok:
            self._latch_arm_precondition(prereq_reason)
            self._observe()
            self._diag_poll(slow_levels)
            return

        want_arm = self.fsm.state not in DISARMED_STATES
        reason = None
        if not want_arm:
            reason = ("fsm_" + self.fsm.state.value
                      if self.fsm.state in DISARMED_STATES else "unknown")
            # A disarmed FSM must never retain a logical motion command. Treat
            # this as the same hard invariant even if a future FSM change
            # creates the impossible state outside a prerequisite episode.
            if self._active_motion_latches():
                self._latch_arm_precondition(reason)
                self._observe()
                self._diag_poll(slow_levels)
                return
        self._command_arm(want_arm, reason)
        self._observe()                       # instrumentation (idea #10/#15): never affects control
        self._diag_poll(slow_levels)          # diagnostics rules (enqueue-only, never raises)

    def runtime_diagnostics(self, identity_verdict=None):
        """Snapshot safety-relevant controller posture for remote diagnosis."""
        if identity_verdict is None:
            identity_verdict = self._identity_arm_ok(
                allow_shadow_bypass=False)
        identity_ok, identity_reason = identity_verdict
        legacy_mode = self._legacy_identity_mode()
        if identity_ok and not legacy_mode and \
                self.link.fw_identity() is not None:
            assurance = "verified"
        elif identity_ok and legacy_mode:
            assurance = "legacy_unverified"
        else:
            assurance = "invalid"

        prereq_reason = self._arm_prereq_reason
        if prereq_reason is None:
            if not self.link.maxrun_ok():
                prereq_reason = "maxrun_desync"
            elif not identity_ok:
                prereq_reason = "identity_" + str(identity_reason)

        tap_levels = self.link.tap_levels()
        def tap(name):
            if tap_levels is None or name not in tap_levels:
                return None
            return bool(tap_levels[name])
        safety_taps = {
            "ne555": tap("NE555"),
            "wdog_kick": tap("KICK"),
            "arm_permit": tap("ARM"),
            "rp2040_ok": tap("RPOK"),
        }
        state = getattr(self.fsm.state, "value", str(self.fsm.state))
        return {
            "controller_mode": "shadow" if self.shadow else "live",
            "live_outputs_acknowledged":
                bool(self._live_outputs_acknowledged),
            "arm_state": bool(self._arm_state),
            "fsm_state": str(state),
            "manual_rearm_required": bool(
                self._pbz_release_required
                or self.fsm.state in DISARMED_STATES),
            "legacy_identity_mode": bool(legacy_mode),
            "identity_assurance": assurance,
            "arm_prerequisite_reason": (
                str(prereq_reason)[:120]
                if prereq_reason is not None else None),
            "safety_taps": safety_taps,
        }

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
                    self._telemetry_baseline_cycle_eligible = _env_on(
                        DIAG_EVENTS_ENV)
                    self._cycle_started_utc = _utc_now_iso()
                    self._cycle_ball = getattr(self.fsm.ball, "value", None)
                    self.diag.on_ball(t)
            # 3) cycle boundary: arriving back at READY finalizes the cycle's intervals
            if new is State.READY and prev not in (State.MANUAL_INTERVENTION, State.POWER_OFF):
                durations = self.telemetry.end_cycle(
                    fold_baseline=(
                        self._telemetry_baseline_cycle_eligible
                        and _env_on(DIAG_EVENTS_ENV)))
                self._telemetry_baseline_cycle_eligible = False
                self.diag.note_cycle_complete(t)
                self._ship_cycle("READY", durations=durations)
            # 3b) aborted cycle: a FAULT / safety trip / power-off abandons the
            # cycle mid-flight, and its recovery path (MANUAL_INTERVENTION ->
            # READY) is excluded from end_cycle above — discard the open
            # intervals WITHOUT folding, so a stale 'ball' timestamp can't fold
            # a minutes-long garbage sample into the drift baselines (observe-only).
            elif new in (State.FAULT, State.MANUAL_INTERVENTION, State.POWER_OFF):
                self.telemetry.abort_cycle()
                self._telemetry_baseline_cycle_eligible = False
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
            # R2-12: delivery identity at the PRODUCER — a re-POST after a
            # lost ack dedupes server-side instead of duplicating the cycle.
            stamp_delivery(row)
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
                    t=self.io.now(), persistent=True,
                    retain_across_blind=True)
            self._prev_arm = bool(want)
        except Exception:
            log.debug("L%s _note_arm swallowed", self.cfg.lane, exc_info=True)

    def _invalidate_diag_debounce_generation(self):
        """Discard diagnostic debounce candidates across an UNKNOWN interval."""
        self._diag_deb.clear()
        self._diag_inb_deb.clear()
        self._diag_missing_health.clear()
        self._diag_health_levels.clear()

    def _invalidate_diag_input_names(self, names):
        """Drop debounce candidates only for the named diagnostic inputs."""
        names = set(names)
        for name in names:
            self._diag_deb.pop(name, None)
            self._diag_inb_deb.pop(name, None)
        for role, health_name in self._diag_health_inputs.items():
            if health_name in names:
                self._diag_health_levels.pop(role, None)
                self._diag_missing_health.discard(health_name)

    def _reset_board_diag_episodes(self):
        """Clear controller-owned current-fault evidence at a blind boundary."""
        self._bank_fail_n = 0
        self._bank_warned = False
        self._v5_warned = False
        self._run_mm_since = None
        self._run_mm_warned = False
        self._run_mm_fault_code = None
        for event_type in (
                "bank_unavailable", "v5_out_of_range", "run_mismatch"):
            self.diag.cancel_pending_event_type(event_type)

    def _mark_diagnostics_unavailable(self, t):
        """One board-level observation discontinuity, used by every path."""
        self._invalidate_diag_debounce_generation()
        self._reset_board_diag_episodes()
        self.diag.mark_board_unavailable(t)

    def _sync_diag_gate_generation(self, t):
        """Apply dynamic gate transitions before sampling this tick.

        A transition can begin while an N-sample debouncer has only part of an
        edge.  Keeping that candidate would release a synthetic edge after the
        gate re-opens.  Treat every diagnostic gate transition as a new sample
        generation and baseline all diagnostic inputs from the first raw sample.
        Board-level episode latches are controlled by the master gate and must
        likewise restart from fresh post-gate evidence.
        """
        current = {
            name: _env_on(name)
            for name in self._diag_gate_states
        }
        changed = {
            name for name, active in current.items()
            if self._diag_gate_states.get(name) != active
        }
        if DIAG_EVENTS_ENV in changed:
            self.diag.start_event_generation()
            if self._cycle_open:
                self._telemetry_baseline_cycle_eligible = False
            self._mark_diagnostics_unavailable(t)
            self._unexpected_edge_gate_state = current[DIAG_EVENTS_ENV]
            if current[DIAG_EVENTS_ENV]:
                # Incidents retained while the gate was closed own the original
                # occurrence timestamp/detail. Retry them before same-tick
                # current-state reconciliation can report a newer duplicate.
                self.diag.pump_pending_delivery(t, force=True)
                self._diag_master_reconcile_pending = True
                self._diag_identity_reconcile_pending = True
        else:
            selected = set()
            if AUX_RULE_ENV in changed:
                selected.update(self.diag.aux_roles)
            if MANUAL_RULE_ENV in changed:
                selected.update(MANUAL_INPUT_NAMES)
            if STUCK_RULE_ENV in changed:
                candidates = set(self._watched)
                candidates.update(in_b_map_for(self.cfg.board_rev))
                selected.update(
                    name for name in candidates
                    if name not in STUCK_EXEMPT
                    and not name.startswith("DIELL"))
            # BEAM_RULE_ENV consumes firmware DIELL levels directly; LaneDiag
            # resets those anchors and no MCP debounce state is shared.
            if selected:
                self._invalidate_diag_input_names(selected)
                self.diag.rebaseline_inputs(selected, t)
        self._diag_gate_states = current
        return current[DIAG_EVENTS_ENV]

    def _reconcile_current_diagnostic_faults(self, t, link_healthy):
        """Emit current persistent states after a master-gate blind interval."""
        reconcile_all = self._diag_master_reconcile_pending
        if not reconcile_all and not self._diag_identity_reconcile_pending:
            return
        if reconcile_all:
            self._diag_master_reconcile_pending = False

        if (reconcile_all and not link_healthy
                and not self.diag.event_attempted("link_lost")):
            self.diag.emit_event(
                "fault", "link_lost", code=self.link.fault() or None,
                detail={"alive": self.link.is_alive(),
                        "rp_ok": self.link.rp_ok(),
                        "reconciled_after_gate": True},
                t=t, persistent=True)
        fw_fault = self.link.fault()
        # Reboot has its own typed event. Every other live firmware/link fault,
        # including heartbeat-schema failure, is also a fw_fault just as it is
        # when first observed with diagnostics enabled.
        if (reconcile_all and fw_fault and fw_fault != REBOOT_FAULT
                and not self.diag.event_attempted("fw_fault", fw_fault)):
            self.diag.emit_event(
                "fault", "fw_fault", code=fw_fault,
                detail={"reconciled_after_gate": True},
                t=t, persistent=True)

        if (reconcile_all and not self.link.maxrun_ok()
                and not self.diag.event_attempted(
                    "fw_config_mismatch", "maxrun_desync")):
            self.diag.emit_event(
                "fault", "fw_config_mismatch", code="maxrun_desync",
                detail={"fw_maxrun_ms": self.link.maxrun_ms(),
                        "fw_version": self.link.fw_version(),
                        "reconciled_after_gate": True},
                t=t, persistent=True)

        identity_ok, identity_reason = self._identity_arm_ok(
            allow_shadow_bypass=False)
        identity = self.link.fw_identity()
        identity_conclusive = (
            link_healthy
            and (identity is not None or self.link.identity_missing())
        )
        if identity_conclusive and identity_ok:
            self._diag_identity_reconcile_pending = False
        if not identity_ok and identity_conclusive:
            identity = identity or {}
            event_type = ("fw_identity_missing"
                          if self.link.identity_missing()
                          else "fw_identity")
            code = ("no_id_line" if event_type == "fw_identity_missing"
                    else identity_reason)
            # Dedupe only the exact current verdict.  An informational identity
            # provenance record (code="") retained across the blind interval
            # cannot satisfy a later rid/build/policy fault.
            if not self.diag.event_attempted(event_type, code):
                detail = {
                    key: identity.get(key)
                    for key in ("fw", "bn", "pcb", "rid", "uid",
                                "build", "cfg", "fi1")
                }
                detail.update({
                    "declared_rev": self.cfg.board_rev,
                    "identity_ok": False,
                    "identity_reason": identity_reason,
                    "reconciled_after_gate": True,
                })
                self.diag.emit_event(
                    "fault", event_type, code=code, detail=detail, t=t,
                    persistent=True)
            if self.diag.event_attempted(event_type, code):
                self._diag_identity_reconcile_pending = False

        if (reconcile_all and self.fsm.state is State.FAULT
                and not self.diag.event_attempted("fsm_fault")):
            last_fault = self.fsm.last_fault or {}
            self.diag.emit_event(
                "fault", "fsm_fault", code=last_fault.get("code"),
                detail={"why": last_fault.get("why"),
                        "state": last_fault.get("state"),
                        "reconciled_after_gate": True},
                t=t, persistent=True)

    def _debounce_for_diag(self, levels, *, source="slow"):
        """Apply the diagnostics-path stable-time debounce (H3) to a raw
        {name: level} dict. Per-input SlowDebounce state is created on first
        sight, BASELINED to the first observed level (never an edge — the
        review-#28 startup rule extended to every diagnostics input).

        IN-B has a separate state table: a failed bank read or omitted channel
        deletes its debouncer. The first recovered raw sample is therefore a
        new baseline instead of a delayed synthetic edge from the blind period.
        """
        states = self._diag_inb_deb if source == "inb" else self._diag_deb
        if levels is None:
            if source == "inb":
                states.clear()
                self._diag_health_levels.clear()
                self._diag_missing_health = {
                    name for name in self._diag_health_inputs.values()
                    if name is not None
                }
                if self._diag_health_inputs["field_wet_ok"] is not None:
                    self._diag_deb.clear()
            return None
        if source == "inb":
            missing_health = {
                name for name in self._diag_health_inputs.values()
                if name is not None and name not in levels
            }
            for role, name in self._diag_health_inputs.items():
                if name is not None and name in missing_health:
                    self._diag_health_levels.pop(role, None)
            changed_health = missing_health ^ self._diag_missing_health
            field_name = self._diag_health_inputs["field_wet_ok"]
            sensor_name = self._diag_health_inputs[SENSOR_24V_ROLE]
            if field_name is not None and (
                    field_name in missing_health
                    or field_name in changed_health):
                # FIELD_WET health UNKNOWN makes every field input's debounce
                # history unusable, including the separately-read IN-A bank.
                states.clear()
                self._diag_deb.clear()
            elif sensor_name is not None and (
                    sensor_name in missing_health
                    or sensor_name in changed_health):
                for name in self._diag_sensor_dependents:
                    states.pop(name, None)
            self._diag_missing_health = missing_health
            for name in set(states) - set(levels):
                states.pop(name, None)
        out = {}
        for name, raw in levels.items():
            deb = states.get(name)
            if deb is None:
                deb = states[name] = SlowDebounce(
                    self._diag_deb_n, initial=raw)
            out[name] = deb.update(raw)
        return out

    def _rebaseline_on_supply_transition(self, raw_levels, debounced_levels):
        """Reset affected debounce candidates when a health level changes.

        Missing health keys already reset candidates in ``_debounce_for_diag``.
        A real, debounce-qualified FIELD_WET or external-sensor-supply level
        transition is the same observation boundary: inputs may have changed
        anywhere in the blind interval and must use the current raw sample as a
        baseline rather than release a delayed synthetic edge.
        """
        if raw_levels is None or debounced_levels is None:
            return debounced_levels
        transitions = set()
        for role, name in self._diag_health_inputs.items():
            if name is None or name not in debounced_levels:
                self._diag_health_levels.pop(role, None)
                continue
            current = bool(debounced_levels[name])
            previous = self._diag_health_levels.get(role)
            self._diag_health_levels[role] = current
            if previous is not None and previous != current:
                transitions.add(role)

        if "field_wet_ok" in transitions:
            self._diag_inb_deb.clear()
            for name, raw in raw_levels.items():
                self._diag_inb_deb[name] = SlowDebounce(
                    self._diag_deb_n, initial=raw)
                debounced_levels[name] = bool(raw)
            self._diag_deb.clear()
            for role, name in self._diag_health_inputs.items():
                if name is not None and name in debounced_levels:
                    self._diag_health_levels[role] = bool(
                        debounced_levels[name])
            return debounced_levels

        if SENSOR_24V_ROLE in transitions:
            for name in self._diag_sensor_dependents:
                self._diag_inb_deb.pop(name, None)
                if name in raw_levels:
                    self._diag_inb_deb[name] = SlowDebounce(
                        self._diag_deb_n, initial=raw_levels[name])
                    debounced_levels[name] = bool(raw_levels[name])
        return debounced_levels

    def _diag_poll(self, slow_levels):
        """Feed this tick's levels to the diagnostics rules. IN-B is 1-2 extra
        I²C register reads; a failing IN-B read is swallowed (diagnostics must
        never trip the lane — observe-only). All MCP-sampled levels pass the
        stable-time debounce (WSL_SLOW_DEBOUNCE_N consecutive 50 Hz samples)
        before any rule sees them; DIELL levels arrive pre-sampled from the
        firmware heartbeat and feed a 30 s-threshold rule, so they are used
        as-is."""
        try:
            t = self.io.now()
            master_enabled = self._sync_diag_gate_generation(t)
            inb = None
            reader = getattr(self.io, "read_inputs_b", None)
            if reader is not None:
                try:
                    inb = reader()
                except Exception:
                    log.debug("L%s IN-B read failed (diagnostics skipped)",
                              self.cfg.lane, exc_info=True)
            if master_enabled:
                self._bank_health(t, reader is not None, inb is not None)
            link_healthy = self.link.health_ok()
            # Drain typed records before gate reconciliation. If an identity
            # record itself reports the current state in this generation,
            # reconciliation observes the attempt and does not duplicate it.
            self._consume_link_records()
            if master_enabled:
                self._reconcile_current_diagnostic_faults(t, link_healthy)
            if self.diag.ball_tracker is not None:
                self.diag.ball_tracker.set_ball_source_available(
                    self.cfg.lane, link_healthy, t)
            diell = None
            lv = self.link.input_levels() if link_healthy else None
            if lv is not None:
                diell = {k: lv[k] for k in ("DIELL_L", "DIELL_R") if k in lv}
            debounced_inb = self._debounce_for_diag(inb, source="inb")
            debounced_inb = self._rebaseline_on_supply_transition(
                inb, debounced_inb)
            debounced_slow = self._debounce_for_diag(slow_levels)
            self.diag.poll(t,
                           ready=self.fsm.state is State.READY,
                           in_motion=self.fsm.state in MOTION_STATES,
                           slow_levels=debounced_slow,
                           inb_levels=debounced_inb,
                           diell_levels=diell)
            if master_enabled:
                if link_healthy:
                    self._v5_rule(t)
                self._run_mismatch_rule(t, link_healthy=link_healthy)
        except Exception:
            log.debug("L%s _diag_poll swallowed", self.cfg.lane, exc_info=True)

    def _bank_health(self, t, have_reader, read_ok):
        """R2-12 bank_unavailable: the IN-B expander stops answering (I²C
        failure class) — one warn per dead episode, 'recovered' info when the
        bank answers again. Threshold = N consecutive failed reads (~N*20 ms)
        so a single transient NAK stays a debug line."""
        if not have_reader:
            return
        if read_ok:
            self.diag.cancel_pending_event_type("bank_unavailable")
            if self._bank_warned:
                self.diag.emit_event("info", "recovered",
                                     code="bank_unavailable",
                                     detail={
                                         "failed_reads": self._bank_fail_n,
                                         "recovered_event_type":
                                             "bank_unavailable",
                                         "recovered_code": "in_b",
                                     },
                                     t=t)
            self._bank_fail_n = 0
            self._bank_warned = False
            return
        self._bank_fail_n += 1
        thr = int(_env_float(BANK_FAIL_N_ENV, DEFAULT_BANK_FAIL_N))
        if self._bank_fail_n >= thr and not self._bank_warned:
            self._bank_warned = True
            self.diag.emit_event(
                "warn", "bank_unavailable", code="in_b",
                detail={"consecutive_failures": self._bank_fail_n,
                        "threshold": thr}, t=t, persistent=True)

    def _v5_rule(self, t):
        """R2-11: VCC_5V hb-window extrema out of the allowed window (v1.2
        firmware, rev-D ADC). Edge-triggered once per excursion episode."""
        stats = self.link.v5_stats()
        if stats is None:
            return
        v5, v5n, v5x = stats
        lo = _env_float(V5_MIN_ENV, DEFAULT_V5_MIN_MV)
        hi = _env_float(V5_MAX_ENV, DEFAULT_V5_MAX_MV)
        bad = ((v5n is not None and v5n < lo) or
               (v5x is not None and v5x > hi))
        if bad and not self._v5_warned:
            self._v5_warned = True
            self.diag.emit_event(
                "warn", "v5_out_of_range", code="adc_vcc5",
                detail={"v5_mv": v5, "v5_min_mv": v5n, "v5_max_mv": v5x,
                        "floor_mv": lo, "ceiling_mv": hi}, t=t,
                persistent=True)
        elif not bad:
            self.diag.cancel_pending_event_type("v5_out_of_range")
            self._v5_warned = False

    def _run_mismatch_rule(self, t, *, link_healthy=None):
        """R2-12: promote a PERSISTING firmware/commanded run-state desync to
        a structured fault (the link already re-sends bounded; a mismatch
        that outlives the retries means the UART is eating lines and the
        firmware max-run backstop may be desynced for those motors)."""
        if link_healthy is None:
            link_healthy = self.link.health_ok()
        if not link_healthy:
            # Cached commanded/firmware state is not evidence during a
            # heartbeat outage. A mismatch that had not yet matured must hold
            # for a fresh full interval after observability returns.
            self._run_mm_since = None
            return
        mm = self.link.run_mismatch()
        if not mm:
            self.diag.cancel_pending_event_type("run_mismatch")
            if self._run_mm_warned:
                self.diag.emit_event(
                    "info", "recovered", code="run_mismatch",
                    detail={
                        "recovered_event_type": "run_mismatch",
                        "recovered_code": self._run_mm_fault_code,
                    },
                    t=t)
            self._run_mm_since = None
            self._run_mm_warned = False
            self._run_mm_fault_code = None
            return
        if self._run_mm_since is None:
            self._run_mm_since = t
            return
        hold = _env_float(RUN_MISMATCH_S_ENV, DEFAULT_RUN_MISMATCH_S)
        if (t - self._run_mm_since) >= hold and not self._run_mm_warned:
            self._run_mm_warned = True
            self._run_mm_fault_code = ",".join(mm)
            self.diag.emit_event(
                "fault", "run_mismatch", code=self._run_mm_fault_code,
                detail={"motors": list(mm),
                        "held_s": round(t - self._run_mm_since, 1)}, t=t,
                persistent=True)

    def _consume_link_records(self):
        """R2-11: drain the link's typed v1.2.x records into DiagEvents.
        Enqueue-only; every record kind maps to a machine_events type. A
        preserved pre-reboot ring advertised in a boot record triggers ONE
        bounded TAPDUMP request (telemetry read-back, not an actuation) so
        the black-box evidence reaches the store without an operator."""
        try:
            for rec in self.link.drain_diag_records():
                kind = rec.get("kind")
                t = rec.get("t_pi")
                if kind == "uart_drops":
                    self.diag.emit_event(
                        "warn", "uart_drops", code="fw_tx",
                        detail={"lost": rec.get("lost"),
                                "total": rec.get("total")}, t=t,
                        persistent=True, retain_across_blind=True)
                elif kind == "tap_warn":
                    self.diag.emit_event(
                        "warn", "tap_warn", code=rec.get("code") or None,
                        detail={"t_fw_ms": rec.get("t_fw")}, t=t,
                        persistent=True, retain_across_blind=True)
                elif kind == "tapdump":
                    meta = rec.get("meta") or {}
                    self.diag.emit_event(
                        "warn", "tapdump",
                        code=meta.get("cause") or "ring",
                        detail={"meta": meta,
                                "fresh_n": rec.get("fresh_n"),
                                "stale_n": rec.get("stale_n"),
                                # fresh entries ONLY drive diagnosis; stale
                                # (pre-reboot epoch) entries ride along
                                # explicitly flagged (R2-11 epoch rule).
                                "entries": rec.get("entries")}, t=t,
                        persistent=True, retain_across_blind=True)
                elif kind == "fw_boot":
                    if rec.get("ring_preserved") and (rec.get("ring_entries")
                                                      or 0) > 0:
                        ep = rec.get("ring_epoch")
                        if ep != self._tapdump_requested_ep:
                            self._tapdump_requested_ep = ep
                            self.link.request_tapdump()
                elif kind == "fw_identity":
                    # Round-3 fix (Codex 2026-07-21 PM): this record used to be
                    # drained and silently DISCARDED — an FI-1 bench image or a
                    # wrong-revision board at a live lane degraded to a single
                    # Pi log line. Now it reaches machine_events (and the SMS
                    # gate via fault severity) like every other typed record.
                    fi1 = bool(rec.get("fi1"))
                    pcb = rec.get("pcb")
                    declared = self.cfg.board_rev
                    # A rev-C-class board HAS no straps: the strap read reports
                    # "unknown" (floating) — that IS the expected value there.
                    expected = "unknown" if declared == "revC" else declared
                    rid_expected = 1 if declared == "revD" else 255
                    mismatch = bool(declared and
                                    (pcb != expected
                                     or rec.get("rid") != rid_expected))
                    link_identity_ok, link_reason = self.link.identity_status()
                    policy_ok, policy_reason = self._identity_arm_ok(
                        allow_shadow_bypass=False)
                    sev = ("fault" if (fi1 or mismatch or not policy_ok
                                       or (declared == "revD"
                                           and not link_identity_ok))
                           else "info")
                    code = ("fi1_image" if fi1
                            else ("pcb_rev_mismatch" if mismatch
                                  else ((policy_reason or link_reason)
                                        if sev == "fault" else None)))
                    detail = {k: rec.get(k) for k in
                              ("fw", "bn", "pcb", "rid", "uid", "build",
                               "cfg", "fi1")}
                    detail["declared_rev"] = declared
                    detail["identity_ok"] = policy_ok
                    detail["identity_reason"] = policy_reason
                    self.diag.emit_event(sev, "fw_identity", code=code,
                                         detail=detail, t=t,
                                         persistent=True,
                                         retain_across_blind=True)
        except Exception:
            log.debug("L%s _consume_link_records swallowed", self.cfg.lane,
                      exc_info=True)

    def _on_fsm_diag(self, event):
        """Wave-1 FSM on_diag hook. Runs INSIDE the tick (synchronous from the
        FSM) — bounded-queue enqueue only, never raises. unexpected_edge
        observations are emitted log-scale (count 1, 10, 100, ...) so the
        routine dual-lobe artifact keys can't flood the pipe; fault kinds are
        skipped here (_on_safety_trip owns the structured fault emission)."""
        try:
            if event.get("kind") != "unexpected_edge":
                return
            key = f"{event.get('event')}:{event.get('state')}"
            gate_active = _env_on(DIAG_EVENTS_ENV)
            if gate_active != self._unexpected_edge_gate_state:
                self._unexpected_edge_gate_state = gate_active
            if not gate_active:
                self._unexpected_edge_blind_keys.add(key)
                return
            n = int(event.get("count", 1))
            force_after_blind = key in self._unexpected_edge_blind_keys
            if (force_after_blind
                    or n == 1
                    or (n > 1 and n in (10, 100, 1000))
                    or (n >= 10000 and n % 10000 == 0)):
                self._unexpected_edge_blind_keys.discard(key)
                self.diag.emit_event(
                    "info", "unexpected_edge",
                    code=key,
                    detail={"count": n,
                            "reconciled_after_gate": force_after_blind},
                    t=event.get("t"), persistent=True,
                    retain_across_blind=True)
        except Exception:
            pass

    def _on_safety_trip(
            self, reason, *, fw_fault_override=None,
            reboot_wdt_override=None):
        """Flush the flight recorder on a safety trip / fault. Best-effort, bounded,
        never raises. Captures FSM state + the firmware fault for the dump context.
        dump_async (review #21/#54): the snapshot copy happens here (microseconds);
        the disk write runs on a writer thread — an SD-card stall during one
        board's dump must not freeze the shared tick loop (the OTHER lane's cam
        dispatch, fsm.poll() backstops and NE555 kick)."""
        trip_fw_fault = (
            self.link.fault() if fw_fault_override is None
            else fw_fault_override)
        try:
            self.recorder.dump_async(reason=reason, extra={
                "fsm_state": getattr(self.fsm.state, "value", "?"),
                "fsm_cycle": getattr(getattr(self.fsm, "cycle", None), "value", None),
                "fsm_ball": getattr(getattr(self.fsm, "ball", None), "name", None),
                "fw_fault": trip_fw_fault,
                "rp_ok": self.link.rp_ok(),
                "shadow": self.shadow,
            })
        except Exception:
            log.debug("L%s _on_safety_trip swallowed", self.cfg.lane, exc_info=True)
        # Diagnostics events for the trip (scope §3.1: this is the single choke
        # point every fault path funnels through). Enqueue-only, never raises.
        try:
            t = self.io.now()
            fw_flt = trip_fw_fault
            if reason == "fsm_fault":
                lf = self.fsm.last_fault or {}
                self.diag.emit_event("fault", "fsm_fault",
                                     code=lf.get("code"),
                                     detail={"why": lf.get("why"),
                                             "state": lf.get("state")}, t=t,
                                     persistent=True,
                                     retain_across_blind=True)
            elif reason == "rp2040_link_lost":
                self.diag.emit_event("fault", "link_lost", code=fw_flt or None,
                                     detail={"alive": self.link.is_alive(),
                                             "rp_ok": self.link.rp_ok()}, t=t,
                                     persistent=True,
                                     retain_across_blind=True)
                if fw_flt == REBOOT_FAULT:
                    reboot_wdt = (
                        self.link.boot_wdt_reset()
                        if reboot_wdt_override is None
                        else bool(reboot_wdt_override))
                    et = ("rp2040_wdt_reset" if reboot_wdt
                          else "fw_reboot")
                    self.diag.emit_event(
                        "fault", et, code=fw_flt, t=t, persistent=True,
                        retain_across_blind=True)
                elif fw_flt:
                    # explicit firmware fault (motion_timeout / chatter / ...)
                    self.diag.emit_event(
                        "fault", "fw_fault", code=fw_flt, t=t,
                        persistent=True, retain_across_blind=True)
            elif reason == "tick_error_budget":
                self.diag.emit_event(
                    "fault", "rail_drop", code="tick_error_budget",
                    detail={"reason": "tick error budget exhausted; NE555 kick "
                                      "stops for this board"}, t=t,
                    persistent=True, retain_across_blind=True)
            elif reason == "controller_loop_gap":
                self.diag.emit_event(
                    "fault", "rail_drop", code="controller_loop_gap",
                    detail={
                        "reason": "controller-loop continuity lost; hard-safe "
                                  "latched and a fresh PBZ is required",
                        "continuity": dict(
                            self._control_loop_gap_detail or {}),
                    },
                    t=t, persistent=True, retain_across_blind=True)
            elif reason == "arm_inhibit_with_motion_latched":
                self.diag.emit_event(
                    "fault", "fsm_fault",
                    code="arm_inhibit_with_motion_latched",
                    detail={
                        "why": "ARM prerequisite failed while a motion output "
                               "latch was active",
                        "state": getattr(self.fsm.state, "value", "?"),
                        "arm_precondition": self._arm_prereq_reason,
                        "active_motion_latches":
                            list(getattr(
                                self, "_last_inhibit_active",
                                self._active_motion_latches())),
                    },
                    t=t, persistent=True, retain_across_blind=True)
        except Exception:
            log.debug("L%s _on_safety_trip diag emit swallowed", self.cfg.lane,
                      exc_info=True)

    # ---- shutdown ----------------------------------------------------------
    def safe_off(self):
        # ARM/STOP/all-off/relatch first via the shared runtime routine. Then
        # force the NE555 kick pin LOW and close transport independently.
        self._hard_safe("shutdown", raise_on_failure=False)
        for name, step in (
            ("watchdog_low",
             lambda: self._wdog.off() if self._wdog is not None else None),
            ("link_close", self.link.close),
        ):
            try:
                step()
            except Exception as e:
                self.failed = True
                self.fatal = True
                log.warning("L%s shutdown %s failed: %s",
                            self.cfg.lane, name, e)


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
                    try:
                        b._mark_diagnostics_unavailable(b.io.now())
                        b.diag.pump_pending_delivery(b.io.now())
                    except Exception:
                        pass
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
                    # Fail safe on the FIRST exception through the same
                    # independent ARM/STOP/all-off/FSM routine used by every
                    # trip. An incomplete safe-off is pair/daemon-fatal so
                    # systemd ExecStopPost gets a prompt chance to force both
                    # GPIOs low; it must never be isolated as one skipped lane.
                    safe_complete = b._hard_safe(
                        "tick_exception", raise_on_failure=False)
                    try:
                        b._mark_diagnostics_unavailable(b.io.now())
                    except Exception:
                        pass
                    if b.fatal or not safe_complete:
                        log.critical(
                            "L%s hard-safe incomplete -> DAEMON-FATAL pair "
                            "shutdown", b.cfg.lane)
                        b._on_safety_trip("tick_error_budget")
                        rc = 1
                        stop["flag"] = True
                        break
                    if b.tick_errors >= TICK_ERROR_BUDGET:
                        log.error("L%s tick error budget exhausted -> SAFETY TRIP "
                                  "this board (outputs off, ARM dropped, kick stops); "
                                  "other board continues", b.cfg.lane)
                        b._on_safety_trip("tick_error_budget")   # dump black box
                        b.failed = True
                        b.safe_off()
                        if b.fatal:
                            rc = 1
                            stop["flag"] = True
                            break
            if stop["flag"] and rc:
                break
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
        # No control deadline remains after safe-off. Give final retained safety
        # events a small bounded chance to enter a writer queue that may have
        # been full at the trip instant. A permanently failed writer can delay
        # shutdown by at most 175 ms.
        for attempt in range(8):
            pending = 0
            for b in boards:
                try:
                    pending += b.diag.pump_pending_delivery(
                        b.io.now(), force=True)
                except Exception:
                    pass
            if not pending:
                break
            if attempt < 7:
                time.sleep(0.025)
        if any(getattr(b, "fatal", False) for b in boards):
            rc = 1
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


def _make_quarantine_notifier(diag_writer):
    """R3-1c: build the OutboxReplayer.on_quarantine callback that turns a
    server per-record reject into an 'outbox_quarantine' warn event. Bounded,
    never raises, log-throttled by the writer's own queue. The event carries
    the reject count + a sample error; lane comes from the rejected row (falls
    back to lane 1 so the event — which needs a valid 1-32 lane_id — still
    lands and is visibly attributed to 'the outbox', not a machine)."""
    def _notify(count, sample_lane, errors):
        try:
            if not _env_on(DIAG_EVENTS_ENV):
                return
            lane = sample_lane if isinstance(sample_lane, int) \
                and 1 <= sample_lane <= 32 else 1
            ev = make_event(lane, "warn", "outbox_quarantine",
                            code="server_reject",
                            detail={"count": int(count),
                                    "sample_errors": (errors or [])[:3]})
            diag_writer.emit(ev)
        except Exception:
            log.debug("quarantine notify swallowed", exc_info=True)
    return _notify


def _wire_pair_diagnostics(boards):
    """Share ONE BallReturnTracker across the pair when any board maps an
    exit_beam AUX (the exit photoeye is one per PAIR — catalog §1.2). Every
    lane registers its emitter so per-lane attribution alerts land on the
    right lane regardless of which board carries the sensor. Returns the
    tracker, or None (roles unmapped -> rule fully dormant)."""
    sources = [
        (b.cfg.lane, name)
        for b in boards
        for name, role in b.diag.aux_roles.items()
        if role == "exit_beam"
    ]
    if not sources:
        return None
    if len(sources) != 1:
        rendered = ", ".join(f"L{lane}:{name}" for lane, name in sources)
        raise ValueError(
            "refusing ambiguous pair-shared exit_beam sources at runtime: "
            f"{rendered}")
    tracker = BallReturnTracker([b.cfg.lane for b in boards])
    for b in boards:
        tracker.register_ball_source(b.cfg.lane)
        b.diag.set_ball_tracker(tracker)
    return tracker


def _drain_final_diagnostics(diag_writer, boards):
    """Persist every bounded lane incident after stopping network replay."""
    writer_stopped = diag_writer.stop()
    if not writer_stopped:
        return sum(board.diag.pending_alert_count() for board in boards)
    # Interleave offer and local drain. A queue may be smaller than the retained
    # incident set (including queue_max=1); one pump cannot admit every event.
    max_rounds = 1 + sum(
        int(getattr(board.diag, "_pending_alerts_max", 64))
        for board in boards)
    for _ in range(max_rounds):
        for board in boards:
            try:
                board.diag.pump_pending_delivery(
                    board.io.now(), force=True)
            except Exception:
                pass
        if not diag_writer.drain_local():
            break
        try:
            queue_empty = diag_writer.queue.empty()
        except Exception:
            queue_empty = False
        pending = sum(
            board.diag.pending_alert_count() for board in boards)
        if pending == 0 and queue_empty:
            return 0
    return sum(board.diag.pending_alert_count() for board in boards)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 8b Track-B controller daemon (skeleton)")
    ap.add_argument("--selftest", action="store_true", help="run the off-hardware assembly self-test and exit")
    ap.add_argument("--hz", type=float, default=50.0, help="control loop rate")
    ap.add_argument("--lanes", default=None,
                    help=f"comma-separated lane subset (e.g. '21'); overrides {LANES_ENV}; "
                         "default = all of DEFAULT_BOARDS")
    ap.add_argument("--board-revs", default=None,
                    help=f"R2-6: EXPLICIT per-lane PCB revision — 'revC' (all) or "
                         f"'21=revC,22=revD'; overrides {BOARD_REVS_ENV}. A board "
                         "without a provisioned revision is REFUSED (fail-safe skip)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.selftest:
        return _selftest()

    # LIVE/SHADOW is a hard, mutually-exclusive acknowledgment gate checked
    # before diagnostics threads or GPIO/I2C/UART hardware are opened.
    try:
        output_mode = _controller_output_mode()
    except ValueError as exc:
        log.critical("OUTPUT MODE REFUSED: %s", exc)
        return 1
    if output_mode == "shadow":
        log.warning("=== MODE: SHADOW (%s set) — FSM runs on real inputs; outputs "
                    "are record-only, ARM hard-held LOW; no relay can energize ===",
                    SHADOW_ENV)
    else:
        log.warning("=== MODE: LIVE (%s acknowledged) — outputs DRIVE REAL RELAYS "
                    "on wired hardware ===", LIVE_ENV)

    spec = args.lanes if args.lanes is not None else os.environ.get(LANES_ENV)
    try:
        configs = _select_boards(DEFAULT_BOARDS, _parse_lanes(spec))
    except ValueError as e:
        log.error("bad lane selection %r: %s", spec, e)
        return 1

    # R2-6: apply the EXPLICIT per-lane board-revision provisioning (CLI beats
    # env; systemd installs the env via /etc/wsl-lane-node.env). A config left
    # unprovisioned is refused at BoardController construction and skipped
    # fail-safe by _build_boards with a loud log.
    rev_spec = (args.board_revs if args.board_revs is not None
                else os.environ.get(BOARD_REVS_ENV))
    try:
        default_rev, per_lane_rev = _parse_board_revs(
            rev_spec, known_lanes={cfg.lane for cfg in configs})
    except (ValueError, TypeError) as e:
        log.error("bad board-rev spec %r: %s", rev_spec, e)
        return 1
    for cfg in configs:
        rev = per_lane_rev.get(cfg.lane, default_rev)
        if rev:
            if cfg.board_rev and cfg.board_rev != rev:
                log.warning("L%s: board_rev %r overridden to %r by provisioning",
                            cfg.lane, cfg.board_rev, rev)
            cfg.board_rev = rev
        log.info("L%s: board_rev=%s", cfg.lane,
                 cfg.board_rev or "UNPROVISIONED (will be refused)")

    # Resolve every AUX map before diagnostics threads or physical hardware
    # open. Multi-board services require per-lane maps; otherwise the old
    # shared env silently cloned pair-scoped sensors onto an unwired board.
    try:
        configs = _provision_aux_roles(configs)
    except (ValueError, TypeError) as e:
        log.error("bad per-board AUX role provisioning: %s", e)
        return 1
    for cfg in configs:
        log.info("L%s: AUX roles=%s", cfg.lane, cfg.aux_roles or "UNMAPPED")

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
        # R3-3 (2026-07-23): when the JSONL-as-outbox owns delivery, cycles
        # ride the SAME durable file+replay path as events (emit_cycle tags
        # them '_kind: cycle'; the OutboxReplayer routes them to
        # /api/machine/cycles). This retires the lossy CycleShipper->post_cycle
        # path, which had NO replay — a crash/outage between the tick and the
        # POST lost the cycle outright. Only when the outbox is absent (a lone
        # live sink, no durable file to replay) do we keep the direct POST.
        if diag_writer.outbox_active():
            cycle_shipper = CycleShipper(diag_writer.emit_cycle)
            cycle_shipper.start()
            # R3-1c: turn server per-record rejects into an outbox_quarantine
            # event so a poison record is visible on the desk, not just counted.
            diag_writer.outbox._on_quarantine = _make_quarantine_notifier(
                diag_writer)
        elif http is not None:
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
            # First drain releases any queue capacity that was unavailable to
            # a board's final retained trip. Re-offer those bounded in-memory
            # incidents, then synchronously drain once more; stop() is
            # intentionally idempotent and drains even with a dead thread.
            remaining = _drain_final_diagnostics(diag_writer, boards)
            if remaining:
                log.error(
                    "shutdown diagnostic drain exhausted with %d retained "
                    "incidents still in memory", remaining)


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
    bc = BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev="revC",
                    allow_legacy_revc_no_identity=True,
                    legacy_revc_no_identity_enrolled=True),
        sim=True)
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "boots into MANUAL_INTERVENTION (power-down rule)")

    bc.link.feed_line('{"ev":"hb","ok":1,"up":250}')     # RP2040 healthy
    bc.tick()
    chk(bc.io.armed is False, "stays DISARMED before First-Ball-Zero")

    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.READY, "PBZ -> READY")
    chk("CLEAR" in bc.link.sent, "PBZ also sends CLEAR to the firmware")
    bc.link.feed_line('{"ev":"hb","ok":1,"up":500}'); bc.tick()
    chk(bc.io.armed is True, "ARMED once READY + RP2040 healthy")

    bc.io.grippers = 0                                    # strike (no pins standing)
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    chk(bc.fsm.state is State.SWEEP_TO_GUARD, "ball event -> SWEEP_TO_GUARD")
    chk("RUN S" in bc.link.sent, "sweep energize -> RUN S sent to firmware")

    bc.link.feed_line('{"ev":"cam","id":"SB","e":"f"}'); bc.tick()
    chk(bc.fsm.state is State.GUARD_DELAY, "SB trip -> GUARD_DELAY")
    chk("STOP S" in bc.link.sent, "sweep stop at guard -> STOP S sent")

    bc.io.advance(TIME_DELAY_S + 0.1)
    bc.link.feed_line('{"ev":"hb","ok":1,"up":750}'); bc.tick()
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
    bc.link.feed_line('{"ev":"hb","ok":1,"up":1000}'); bc.tick()
    chk(bc.io.armed is True, "(setup) READY + armed before mid-cycle test")
    bc.io.grippers = 0
    bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()
    chk(bc.io.outputs.get("sweep") is True, "(setup) mid-cycle: sweep ON")
    bc.link.feed_line('{"ev":"rp_ok","v":0}'); bc.tick()            # health loss mid-cycle
    chk(bc.io.outputs.get("sweep") is False, "health loss forces sweep OFF (clears relay latch)")
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "health loss latches FSM -> MANUAL_INTERVENTION")
    chk(bc.io.armed is False, "health loss drops ARM")
    bc.link.feed_line('{"ev":"hb","ok":1,"up":1250}'); bc.tick()  # heartbeat returns OK
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
    bc.link.feed_line('{"ev":"hb","ok":1,"up":1500}'); bc.tick()
    chk(bc.fsm.state is State.FAULT, "stuck motion -> FAULT via the poll backstop")
    chk(bc.io.armed is False, "FAULT drops ARM (DISARMED_STATES)")
    clears = bc.link.sent.count("CLEAR")
    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.MANUAL_INTERVENTION, "PBZ in FAULT -> MANUAL_INTERVENTION")
    chk(bc.link.sent.count("CLEAR") == clears + 1,
        "firmware latch cleared exactly once, AFTER the FSM left FAULT")
    bc.link.feed_line('{"ev":"hb","ok":1,"up":1750}'); bc.tick()   # PBZ released (edge re-arms)
    bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
    chk(bc.fsm.state is State.READY and bc.io.armed is True, "second PBZ -> READY + armed")

    # --- review #30: a KNOWN firmware/FSM max-run desync must REFUSE to arm ---
    bc2 = BoardController(
        BoardConfig(21, 1, "sim", 0, 0, board_rev="revC",
                    allow_legacy_revc_no_identity=True,
                    legacy_revc_no_identity_enrolled=True),
        sim=True)
    bc2.link.feed_line('{"ev":"boot","fw":"test","maxrun_ms":1000}')   # << MAX_MOTION_S
    bc2.link.feed_line('{"ev":"hb","ok":1,"up":250}')
    bc2.io.slow["PBZ"] = True; bc2.tick(); bc2.io.slow["PBZ"] = False
    chk(bc2.fsm.state is State.MANUAL_INTERVENTION,
        "maxrun desync blocks PBZ and latches MANUAL_INTERVENTION")
    bc2.link.feed_line('{"ev":"hb","ok":1,"up":500}'); bc2.tick()
    chk(bc2.io.armed is False,
        "maxrun desync (fw 1000ms < FSM MAX_MOTION_S) REFUSES to arm")

    print(f"\n{n['c'] - n['f']}/{n['c']} checks passed" + ("  <<< FAILURES" if n["f"] else ""))
    return 1 if n["f"] else 0


if __name__ == "__main__":
    sys.exit(main())
