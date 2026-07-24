#!/usr/bin/env python3
"""
rp2040_link.py — the Pi side of the RP2040 co-processor link (Phase 8b controller).

The RP2040 firmware (firmware/rp2040/) owns the 8 fast inputs (6 cams + 2 DIELL
ball beams), pushes edge events to the Pi over a UART, and drives the hardware
RP2040_OK rail-permission line. This module is the Pi-side half: it parses those
events, feeds cam/ball events into the cycle FSM (cycle_control_8270), echoes the
SC/TB interlock state, tracks RP2040 health, and sends RUN/STOP/CLEAR/PING
commands back so the firmware's motion max-run backstop knows what's running.

Protocol (newline-delimited JSON, 115200 8N1) — see firmware/rp2040/README.md:
  RP2040 -> Pi:  {"ev":"cam","id":"SA","e":"f","t":..}   {"ev":"ball","src":"L",..}
                 {"ev":"hb","ok":1,"flt":"","up":..,"drp":0,"in":0,"run":0}
                 {"ev":"rp_ok","v":1,..}   {"ev":"boot",..,"maxrun_ms":8000,"dbg":0}
                 {"ev":"flt","code":"motion_timeout","m":"S",..}
                 {"ev":"id","fw":..,"pcb":"revD","rid":1,"uid":..,"build":..,
                  "cfg":..,"fi1":0,..}                       (v1.2.2, R2-6)
  Pi -> RP2040:  RUN <m> | STOP <m|*> | CLEAR | PING | TAPDUMP | ID

v1.2.2 firmware additions (consumed here; all additive):
  "id" line      — firmware/board identity: strap-read PCB revision, Pico
                   unique id, build git-describe + config.h hash, FI-1 posture.
                   Stored (fw_identity()) + emitted as a typed 'fw_identity'
                   diag record; an fi1:1 image is logged as an ERROR (a bench
                   fault-injection build must never run at a lane).
  hb "rid"       — REV_ID strap code every beat (pcb_rev_id(); 255 = floating
                   straps, i.e. a rev-B/rev-C board).

v0.2.0 firmware additions (consumed here; ALL optional — v0.1.0 lines without
them keep working unchanged):
  hb "in"/"run"  — debounced input-level + running-motor bitmasks. The SC/TB
                   interlock danger flags are RESYNCED from "in" on every hb,
                   so a single dropped cam line can no longer latch a stale
                   interlock veto (edge tracking stays for immediacy + v0.1.0).
  hb "up"        — firmware uptime (ms). A regression means the firmware
                   rebooted and we missed the boot line: a synthetic
                   "fw_reboot" fault is latched -> health_ok() False -> the
                   daemon's existing safety trip (motors off, MANUAL_
                   INTERVENTION, operator PBZ re-arm).
  hb "drp"       — TX drop counter; increases are logged as warnings.
  boot "maxrun_ms" — firmware max-run ceiling; stored, and maxrun_ok() answers
                   "is the firmware ceiling >= the FSM's MAX_MOTION_S". The
                   arm-refusal wiring belongs to the daemon/FSM, not here.

v1.1.1 firmware additions (consumed here; both optional/additive):
  boot "v11"     — the v1.1 enforcement posture ({"sa","ta1","echo","nrun"}).
                   Logged at boot (WARNING when any enforcement is armed) and
                   exposed via v11_posture(), so an ARMED image is no longer
                   wire-indistinguishable from a stock one (review finding 37).
  hb "run" reconciliation — the run mask is now COMPARED against the RUN/STOP
                   state we last commanded (review finding 38: a corrupted
                   RUN line silently removes the firmware max-run backstop; a
                   corrupted STOP guarantees a spurious motion_timeout rail
                   drop). On mismatch the command is re-sent (bounded,
                   RUN_RESYNC_RETRIES per episode — safe: the firmware stamps
                   its max-run timer only on a false->true transition) and
                   run_mismatch() exposes any persisting desync for the daemon.

Concurrency: the serial reader runs on a background thread and only UPDATES state
(health, SC/TB) under a lock + QUEUES cam/ball events. The daemon's main loop
drains them via apply_events(controller) so the (non-thread-safe) FSM is only ever
touched from one thread — call it right before controller.poll().

2026-07-19 diagnostics campaign (scope §5 Phase 1.1) — firmware timestamps:
  The firmware stamps every cam/ball line with "t" (ms, uint32, since firmware
  boot — the same timebase as hb "up"). Queue entries carry it: every entry is
  (kind, ident, t_fw_ms, t_pi_mono) — t_fw_ms None on v0.1.0 lines without "t".
  FwClock (below) estimates the fw-ms <-> Pi-monotonic offset (EWMA, resynced on
  any firmware reboot) so pure-edge intervals can be measured at the firmware's
  1 ms resolution instead of the daemon's ~20 ms tick. Mixed-clock intervals
  (fw edge <-> Pi-issued command) get NO precision claim — see the daemon's
  _edge_observer for the call-site notes.

SAFETY: this is the software half. RP2040_OK is a HARDWARE rail line driven by the
firmware; a dead/!ok RP2040 drops the rail in hardware regardless of this module.
Here we additionally surface health so the daemon can fault the FSM + drop ARM.
pyserial is imported lazily so this module loads + tests on any machine.
"""
from __future__ import annotations
import json
import logging
import math
import threading
import time
from contextlib import contextmanager
from collections import deque


def _reject_nonfinite(const):
    """json.loads parse_constant hook (R3-10): a telemetry line carrying NaN /
    Infinity / -Infinity is CORRUPTION, not data. Rejecting it here means
    json.loads raises (caught by feed_line) instead of silently producing a
    float('nan') that then poisons FwClock / extrema / interval math."""
    raise ValueError(f"non-finite JSON constant {const!r}")

log = logging.getLogger("rp2040_link")

# Cam events that map to FSM cam methods. SC/TB are interlock-only (the FSM has no
# cam_SC/cam_TB method) — they feed interlock_ok() via the SC/TB danger echo.
CAM_DISPATCH = ("SA", "SB", "TA1", "TA2")
INTERLOCK_CAMS = ("SC", "TB")
MOTORS = ("S", "T", "SP", "BE", "M", "M1", "M2")

# v0.2.0 heartbeat mask bit orders (firmware/rp2040/README.md "Heartbeat masks").
# NOTE: the hb "run" bit order is NOT the MOTORS tuple order above.
HB_IN_BITS = ("SA", "SB", "SC", "TA1", "TA2", "TB", "DIELL_L", "DIELL_R")
HB_RUN_BITS = ("S", "T", "SP", "M2", "M1", "BE", "M")
_IN_BIT_SC = 1 << HB_IN_BITS.index("SC")
_IN_BIT_TB = 1 << HB_IN_BITS.index("TB")

RX_MAX = 4096        # cap on the no-newline receive buffer (babbling UART)
SENT_MAXLEN = 256    # `sent` is a test/bench record, not an unbounded log
SEND_FAIL_LIMIT = 3  # consecutive serial-write failures => health_ok() False
REBOOT_FAULT = "fw_reboot"  # synthetic fault latched on firmware-reboot detection
RUN_RESYNC_RETRIES = 3  # hb run-mask mismatch: re-sends per motor per episode
# Keep TX lock wait + kernel write inside the controller's 50 ms positive-
# operation return budget. A control line is only a few bytes at 115200 baud.
SERIAL_TX_LOCK_TIMEOUT_S = 0.010
SERIAL_WRITE_TIMEOUT_S = 0.025

# R3-5 (Codex round-3, 2026-07-23): firmware-identity re-request after a
# reboot. A reboot INVALIDATES every cached identity/capability/extrema fact
# (an old v1.2.2 image's identity must never survive into a v0.1 boot). The
# link re-requests the id line and, if none arrives within the budget, reports
# it MISSING once so the daemon inhibits ARM (env-escapable for the bench).
IDENTITY_RETRY_S = 3.0       # seconds between id re-requests after a reboot
IDENTITY_MAX_RETRIES = 3     # re-requests before declaring identity MISSING

# Qualified v1.2.3 ``emit_hb`` wire envelope.  Once identity-capability is
# observed, every heartbeat is an exact release-contract sample: accepting an
# abbreviated record and retaining omitted fields from an older sample can make
# stale RID/tap/run/input evidence look current and renew liveness.
MODERN_HB_FIELDS = frozenset((
    "ev", "ok", "flt", "up", "drp", "in", "run", "tap", "rd", "ep",
    "v5", "v5n", "v5x", "rid", "bn",
))
HEARTBEAT_SCHEMA_FAULT = "heartbeat_schema_invalid"

# v1.2.x tap telemetry (Codex round-2 R2-11, 2026-07-21). The firmware's hb
# "tap" mask + tapdump "p" field use this bit/pin order (README "v1.2 tap
# fields": bit 0..3 = 555, KICK, ARM, RPOK; levels are POST-inversion
# observed-net levels — the 2N7002 stage inversion is already undone fw-side).
TAP_BITS = ("NE555", "KICK", "ARM", "RPOK")
# Bounded typed-record queue drained by the daemon (drain_diag_records) —
# every v1.2.x record (tapdump ring, tapwarn, uart drop increases, boot
# facts) becomes a typed dict here instead of being silently ignored.
DIAG_RECORDS_MAX = 512
# A tapdump from the firmware ring is at most TAP_RING_SZ entries (config.h
# TAP_RING_SZ = 128); anything past this bound in one dump is discarded+counted.
TAPDUMP_ENTRIES_MAX = 128


class FwClock:
    """EWMA offset estimator between the firmware's millisecond clock (cam/ball
    "t" + hb "up" — one uint32 ms timebase, restarts at 0 on every firmware
    boot) and the Pi's monotonic clock.

    offset = t_pi_seconds - t_fw_ms/1000, smoothed with an EWMA so per-line
    UART jitter averages out (the constant transport latency folds into the
    offset and cancels in any fw-vs-fw interval). resync() forgets the offset —
    call it on every firmware (re)boot; a sample that jumps more than
    RESYNC_JUMP_S from the current estimate also hard-resyncs (missed boot line
    / uint32 wrap at ~49.7 days).

    est_pi_time(t_fw_ms) -> Pi-monotonic seconds, or None before the first
    sample (callers fall back to the Pi receive time). Thread-safe: updated
    from the serial reader thread, read from the daemon tick."""

    ALPHA = 0.1            # EWMA smoothing factor
    RESYNC_JUMP_S = 5.0    # |sample - estimate| beyond this = hard resync

    def __init__(self):
        self._lock = threading.Lock()
        self._offset = None      # pi_seconds - fw_ms/1000.0
        self.samples = 0
        self.resyncs = 0

    def update(self, t_fw_ms, t_pi_s):
        """Fold one (fw ms, Pi monotonic seconds) observation into the offset."""
        try:
            sample = float(t_pi_s) - float(t_fw_ms) / 1000.0
        except Exception:
            return
        with self._lock:
            if self._offset is None or abs(sample - self._offset) > self.RESYNC_JUMP_S:
                if self._offset is not None:
                    self.resyncs += 1
                self._offset = sample
            else:
                self._offset += self.ALPHA * (sample - self._offset)
            self.samples += 1

    def est_pi_time(self, t_fw_ms):
        """Map a firmware ms timestamp onto the Pi monotonic scale, or None if
        no offset has been learned yet (v0.1.0 firmware / pre-first-sample)."""
        with self._lock:
            if self._offset is None or t_fw_ms is None:
                return None
            try:
                return self._offset + float(t_fw_ms) / 1000.0
            except Exception:
                return None

    def offset(self):
        with self._lock:
            return self._offset

    def resync(self):
        """Forget the offset (firmware rebooted — its ms clock restarted at 0)."""
        with self._lock:
            if self._offset is not None:
                self.resyncs += 1
            self._offset = None


def _fsm_max_motion_s():
    """The FSM's MAX_MOTION_S (seconds), READ-ONLY, or None if cycle_control_8270
    isn't importable on this host (bench/test machines). Imported lazily so this
    module stays standalone."""
    try:
        from cycle_control_8270 import MAX_MOTION_S
        return MAX_MOTION_S
    except Exception:
        return None


def dispatch_cam(controller, cam_id):
    """Map an RP2040 cam TRIP event to FSM call(s). The FSM guards each handler by
    state, so calling both angle-variants of a dual-trip cam is safe — only the
    state-matching one acts (e.g. SA@270 in RUNTHROUGH vs SA@360 in TABLE_FINISH)."""
    if cam_id == "SB":
        controller.cam_SB_guard()
    elif cam_id == "TA2":
        controller.cam_TA2_runthrough()
    elif cam_id == "SA":
        controller.cam_SA_runthrough()
        controller.cam_SA_zero()
    elif cam_id == "TA1":
        controller.cam_TA1_delayreset()
        controller.cam_TA1_zero()


class RP2040Link:
    """One link per board (per lane). Open with a real serial `port`, or inject a
    `serial_obj` (anything with read()/write()/close()), or neither (feed lines by
    hand via feed_line() — used in tests and the host bench).

    Wire-up in the daemon:
        link = RP2040Link(port="/dev/serial0")
        link.start()                         # background reader
        io = MachineIO(lane, bus, rp2040=link, ...)   # interlock_ok + RUN/STOP
        ...main loop...
        link.apply_events(controller)        # cam/ball -> FSM (single-threaded)
        controller.poll()
        if not link.health_ok(): controller_fault_and_disarm()
    """

    def __init__(self, port=None, baud=115200, *, serial_obj=None,
                 hb_timeout=1.0, trip_edge="f", now=None,
                 identity_protocol_seen=False,
                 identity_evidence_callback=None):
        self._trip = trip_edge          # which edge ('f'/'r') is the cam's angular trip
        self._hb_timeout = hb_timeout
        self._now = now or time.monotonic

        # callbacks (optional; daemon may set on_health for logging/alerts)
        self.on_health = None           # (event dict) -> None

        # outbound record (always captured; also written to serial if present).
        # Bounded: it exists for tests/bench, not as an unbounded production log.
        self.sent = deque(maxlen=SENT_MAXLEN)

        # TX serialization: with v1.1.1 run-mask reconciliation, the reader
        # thread can re-send RUN/STOP while the daemon thread sends its own
        # commands — interleaved serial writes would tear lines (the exact
        # corruption the reconciliation exists to heal). One lock, write-only.
        self._tx_lock = threading.Lock()

        # State guarded by _lock. Re-entrant because the daemon holds this lock
        # across one bounded control transaction, while normal query/command
        # methods entered inside that transaction also take it.
        self._lock = threading.RLock()
        self._sc_danger = False
        self._tb_danger = False
        self._rp_ok = False
        self._last_hb = None     # None until the first line (0.0 is a valid fake-clock time)
        self._hb_generation = 0
        self._hb_discontinuity_generation = 0
        self._reboot_discontinuity_generation = 0
        self._wdt_reboot_discontinuity_generation = 0
        self._heartbeat_sample = None
        self._fault = ""
        self._send_fails = 0     # consecutive serial-write failures (health gate)
        # v0.2.0 telemetry (None until a firmware that sends it is heard)
        self._in_mask = None     # last hb "in" (debounced input levels)
        self._run_mask = None    # last hb "run" (running-motor mask)
        self._last_up = None     # last hb "up" (firmware uptime, ms)
        self._last_drp = None    # last hb "drp" (TX drop counter)
        self._maxrun_ms = None   # boot "maxrun_ms" (firmware max-run ceiling)
        # v1.1.1 telemetry (None/empty until a firmware that sends it is heard)
        self._v11 = None         # boot "v11" enforcement posture dict
        self._cmd_run = {}       # motor -> bool: RUN/STOP state WE last commanded
        self._resync_tries = {}  # motor -> re-sends this mismatch episode
        self._run_mismatch = ()  # motors mismatched as of the last hb "run" mask
        # diagnostics campaign (2026-07-19): fw timestamp clock + boot facts
        self.fw_clock = FwClock()   # fw-ms <-> Pi-monotonic offset (resynced on reboot)
        self._fw_version = None     # boot "fw" string (None until a boot is heard)
        self._boot_wdt = False      # last boot event carried wdt_reset (hw watchdog fired)
        # v1.2.x telemetry (R2-11; None until a v1.2 firmware is heard)
        self._tap_mask = None       # last hb "tap" (post-inversion net levels)
        self._ring_depth = None     # last hb "rd" (tap edge-ring depth)
        self._ring_epoch = None     # CURRENT ring epoch (boot tap.ep / hb "ep")
        self._v5 = None             # (v5, v5n, v5x) mV from the last hb window
        self._tapdump = None        # open tapdump collection (header + entries)
        # v1.2.2 identity (R2-6; None until an "id" line / hb "rid" is heard)
        self._identity = None       # last "id" line, sanitized dict
        # Process-lifetime downgrade guard.  Once ANY identity-protocol record
        # is observed, cache invalidation/reboot may clear _identity but must
        # never make this link look like a pre-identity legacy board again.
        self._identity_protocol_seen = bool(identity_protocol_seen)
        self._identity_evidence_callback = identity_evidence_callback
        self._identity_evidence_error = None
        self._rid = None            # last hb "rid" (REV_ID strap code; 255 = floating)
        # v1.2.3 (R3-5): per-boot nonce "bn". Firmware emits it on the boot
        # line, the id line AND every hb specifically so the Pi can detect a
        # reboot even when the boot line itself was dropped and the uptime did
        # NOT visibly regress (a quick double-reboot after a short uptime, or
        # several missed hbs). A change in bn (from a non-None cached value)
        # invalidates ALL cached identity/capability/extrema state. None until
        # a v1.2.3 firmware is heard; older images simply never trip it.
        self._boot_nonce = None
        # A boot/hb observation (not an ID line by itself) confirms that the
        # nonce belongs to the currently live firmware stream. This prevents a
        # buffered/stale ID response from establishing trust on its own after a
        # daemon restart.
        self._confirmed_boot_nonce = None
        # R3-5 identity-after-reboot re-request bookkeeping
        # A daemon/service restart normally leaves the Pico powered, so
        # identity acquisition must begin at PROCESS start rather than waiting
        # for a firmware boot event that may never arrive.
        self._identity_boot_seen = True        # current process requires an id
        self._identity_req_at = None           # monotonic of the last id request
        self._identity_retries = 0             # re-requests this reboot
        self._identity_missing_reported = False  # 'missing' returned once
        # typed diag records for the daemon (bounded; drained off-lock)
        self._dr_lock = threading.Lock()
        self._diag_records = deque(maxlen=DIAG_RECORDS_MAX)
        self.diag_record_drops = 0  # records lost to the deque cap
        # R3-10: hardened-parse bookkeeping (NaN/Infinity/garbage lines)
        self.parse_errors = 0
        self._quar_lines = deque(maxlen=32)   # bounded sample of bad raw lines

        # queued cam/ball events, drained by apply_events()
        self._evlock = threading.Lock()
        self._events = deque()

        # transport
        if serial_obj is not None:
            self._ser = serial_obj
        elif port is not None:
            import serial  # pyserial, lazy
            self._ser = serial.Serial(
                port, baud, timeout=0.1,
                write_timeout=SERIAL_WRITE_TIMEOUT_S)
        else:
            self._ser = None
        self._rx = b""
        self._rx_discard = False   # swallowing bytes until the next newline
        self._stop = False
        self._reader = None

    def now(self):
        return self._now()

    # ---- outbound commands -------------------------------------------------
    def _send(self, line):
        self.sent.append(line)
        if self._ser is not None:
            try:
                # daemon + reader threads both send (v1.1.1). Bound the lock
                # wait as well as pyserial's kernel write; write_timeout alone
                # does not cover a peer stalled while holding this mutex.
                if not self._tx_lock.acquire(
                        timeout=SERIAL_TX_LOCK_TIMEOUT_S):
                    raise TimeoutError("serial TX lock acquisition timed out")
                try:
                    payload = (line + "\n").encode()
                    written = self._ser.write(payload)
                    # pyserial's contract is an exact byte count. Treat None
                    # and short writes alike as unacknowledged transport.
                    if written != len(payload):
                        raise IOError(
                            f"short serial write {written}/{len(payload)}")
                finally:
                    self._tx_lock.release()
            except Exception as e:  # never let a comms hiccup crash the caller
                with self._lock:
                    self._send_fails += 1
                    n = self._send_fails
                log.warning("RP2040 send failed x%d (%s): %s", n, line, e)
                return False
            else:
                with self._lock:
                    self._send_fails = 0
        return True

    # run/stop/stop_all/clear also track the COMMANDED run-state so the hb "run"
    # mask can be reconciled against it (_reconcile_run). CLEAR mirrors the
    # firmware's motors_all_stop() (main.c handle_line).
    def run(self, motor):
        with self._lock:
            self._cmd_run[motor] = True
        return self._send(f"RUN {motor}")

    def stop(self, motor):
        with self._lock:
            self._cmd_run[motor] = False
        return self._send(f"STOP {motor}")

    def stop_all(self):
        with self._lock:
            self._cmd_run.clear()
        return self._send("STOP *")

    def clear(self):
        with self._lock:
            self._cmd_run.clear()
        return self._send("CLEAR")

    def ping(self):         self._send("PING")

    def request_tapdump(self):
        """Ask a v1.2+ firmware to drip its rail-drop edge ring (telemetry
        read-back only — TAPDUMP never actuates and never clears; TAPCLR is
        the only clear and is deliberately NOT wrapped here)."""
        self._send("TAPDUMP")

    def request_identity(self):
        """Ask a v1.2.2+ firmware to (re-)emit its identity line (`ID`).
        Round-3 fix (Codex 2026-07-21 PM): the firmware volunteers the id line
        only at ITS boot — a daemon that starts/restarts AFTER the RP2040
        booted (the common case: service restart while the board stays up)
        would otherwise never hear one and fw_identity() stayed None
        indefinitely. start() sends this automatically; pre-v1.2.2 firmware
        ignores the unknown line (no fault, no reply — identity stays None,
        which the daemon reports as such)."""
        self._send("ID")

    # ---- inbound parsing ---------------------------------------------------
    def feed_line(self, line):
        """Parse one received protocol line. Safe to call from the reader
        thread. R3-10 hardened: NaN/Infinity/garbage never raise and never
        reach the handlers — a corrupt/hostile UART line is counted
        (parse_errors), a bounded sample is quarantined (_quar_lines), and the
        line is dropped. The serial reader keeps running regardless."""
        line = line.strip()
        if not line:
            return
        try:
            ev = json.loads(line, parse_constant=_reject_nonfinite)
        except (ValueError, TypeError, RecursionError):
            self._note_parse_error(line)
            return
        if not isinstance(ev, dict):
            self._note_parse_error(line)
            return
        try:
            self._handle(ev)
        except Exception:
            # A malformed-but-parseable object (wrong types in a field) must
            # never crash the reader thread (R3-10 "never raises").
            self._note_parse_error(line)
            log.debug("RP2040 handler swallowed for line %r", line,
                      exc_info=True)

    def _note_parse_error(self, line):
        """Bounded quarantine of a bad line (R3-10). Never raises."""
        try:
            with self._lock:
                self.parse_errors += 1
                self._quar_lines.append(str(line)[:200])
        except Exception:
            pass

    def _handle(self, ev):
        kind = ev.get("ev")
        if kind == "cam":
            cid = ev.get("id")
            trip = (ev.get("e") == self._trip)
            # fw timestamp: every fw-stamped line feeds the FwClock (more
            # samples = tighter offset), queued entries carry it (Phase 1.1).
            t_fw = self._num(ev, "t")
            t_pi = self.now()
            if t_fw is not None:
                self.fw_clock.update(t_fw, t_pi)
            if cid in INTERLOCK_CAMS:
                # Edge tracking kept for immediacy + v0.1.0 firmware; on v0.2.0
                # the hb "in" mask resyncs these every ~250 ms (self-healing).
                with self._lock:
                    if cid == "SC":
                        self._sc_danger = trip
                    else:
                        self._tb_danger = trip
            elif trip and cid in CAM_DISPATCH:
                # Serialize event admission with the same safety-state lock
                # used by the daemon's control transaction.  Lock order is
                # always _lock -> _evlock.
                with self._lock:
                    with self._evlock:
                        self._events.append(("cam", cid, t_fw, t_pi))
        elif kind == "ball":
            t_fw = self._num(ev, "t")
            t_pi = self.now()
            if t_fw is not None:
                self.fw_clock.update(t_fw, t_pi)
            with self._lock:
                with self._evlock:
                    self._events.append(("ball", ev.get("src"), t_fw, t_pi))
        elif kind in ("hb", "boot", "rp_ok", "flt", "ack"):
            notes = []   # (log_fn, msg, args) — emitted AFTER the lock is released
            resends = []  # (motor, desired) resync intents; revalidated before send
            records = []  # typed diag records — pushed AFTER the lock is released
            with self._lock:
                if kind == "hb":
                    # ``bn``/``rid`` are themselves monotonic evidence that
                    # this is not a pre-identity legacy image. Persist that
                    # evidence before accepting or rejecting the sample.
                    if (
                            self._identity_uint(
                                ev.get("bn"), nonzero=True) is not None
                            or self._identity_uint(ev.get("rid")) is not None):
                        self._mark_identity_capable_locked()
                    try:
                        self._validate_hb(ev)
                    except Exception:
                        self._reject_heartbeat_sample_locked()
                        raise
                elif kind == "rp_ok":
                    if self._status_bit(ev.get("v")) is None:
                        raise ValueError(
                            "rp_ok v must be JSON bool or integer 0/1")
                elif kind == "boot":
                    if ("rp_ok" in ev
                            and self._status_bit(ev.get("rp_ok")) is None):
                        raise ValueError(
                            "boot rp_ok must be JSON bool or integer 0/1")
                    if ("wdt_reset" in ev
                            and self._status_bit(ev.get("wdt_reset")) is None):
                        raise ValueError(
                            "boot wdt_reset must be JSON bool or integer 0/1")
                elif kind == "flt" and not isinstance(ev.get("code"), str):
                    raise ValueError("fault code must be a string")
                # Modern identity-capability evidence closes the legacy escape
                # even when the ID response itself is lost. ``rid`` arrived
                # with the identity protocol and ``bn`` strengthens it in
                # v1.2.3. This monotonic, durably seeded latch is never
                # invalidated by a firmware reboot or cache reset.
                if (kind in ("hb", "boot")
                        and (self._identity_uint(
                                 ev.get("bn"), nonzero=True) is not None
                             or self._identity_uint(
                                 ev.get("rid")) is not None)):
                    self._mark_identity_capable_locked()
                if kind == "flt":
                    # An explicit firmware fault => NOT healthy, immediately — even if the
                    # paired rp_ok:0 line is delayed or dropped on a lossy UART. Cleared by
                    # the next hb that carries flt="" (i.e. after a CLEAR).
                    self._fault = ev.get("code", "")
                    self._rp_ok = False
                else:
                    if kind == "rp_ok":
                        self._rp_ok = self._status_bit(ev["v"])
                    elif kind == "hb":
                        self._rp_ok = self._status_bit(ev["ok"])
                    elif kind == "boot" and "rp_ok" in ev:
                        self._rp_ok = self._status_bit(ev["rp_ok"])
                    if kind == "hb" and "flt" in ev:
                        self._fault = ev.get("flt", "")
                    if kind == "boot":
                        self._on_boot(ev, notes, records)
                    elif kind == "hb":
                        self._on_hb(ev, notes, resends, records)
                        # ACK/boot/rp_ok/fault traffic proves bytes are moving,
                        # not that the supervised heartbeat loop is alive.
                        received_at = self.now()
                        self._last_hb = received_at
                        self._hb_generation += 1
                        self._heartbeat_sample = {
                            "generation": self._hb_generation,
                            "received_monotonic": received_at,
                            "modern": bool(self._identity_protocol_seen),
                            "wire": dict(ev),
                        }
            for log_fn, msg, args in notes:
                log_fn(msg, *args)
            for motor, desired, fw_running in resends:
                self._send_reconcile(
                    motor, desired, fw_running=fw_running)
            self._push_records(records)
            if self.on_health:
                self.on_health(ev)
        elif kind in ("tapdump", "tape", "tapdump_end", "tapwarn"):
            # v1.2.x tap telemetry (R2-11): consume the rail-drop edge ring +
            # warnings into typed records instead of silently ignoring them.
            records = []
            with self._lock:
                self._on_tap_event(kind, ev, records)
            self._push_records(records)
        elif kind == "id":
            # v1.2.2 identity line (R2-6): PCB revision (REV_ID strap read),
            # Pico unique id, build git-describe + config.h hash, FI-1 posture.
            # Stored (fw_identity()) + promoted to a typed 'fw_identity' record
            # so the daemon can persist it and alert on mismatches (board rev
            # vs configured BoardConfig revision, unknown build, FI-1 image).
            fi1_raw = ev.get("fi1")
            fi1 = (bool(fi1_raw)
                   if isinstance(fi1_raw, (bool, int))
                   and fi1_raw in (False, True, 0, 1) else None)
            ident = {
                "fw":    self._identity_text(ev.get("fw"), 80),
                "bn":    self._identity_uint(ev.get("bn"), nonzero=True),
                "pcb":   self._identity_text(ev.get("pcb"), 16),
                "rid":   self._identity_uint(ev.get("rid")),
                "uid":   self._identity_text(ev.get("uid"), 32),
                "build": self._identity_text(ev.get("build"), 64),
                "cfg":   self._identity_text(ev.get("cfg"), 32),
                "fi1":   fi1,
                "t_fw":  self._num(ev, "t"),
            }
            with self._lock:
                self._mark_identity_capable_locked()
                # R3-5: the id line also carries the per-boot nonce. If it
                # changed from a known value we missed a reboot (no boot line,
                # no uptime regression) — invalidate the stale caches + latch
                # the safe-state relatch BEFORE adopting the fresh identity this
                # same line carries. On the normal boot->id sequence the nonce
                # already matches (boot cached it), so this is a no-op there.
                nonce_reboot = self._nonce_reboot(ev)
                if nonce_reboot:
                    self._note_heartbeat_discontinuity_locked("reboot")
                    self._invalidate_identity_cache()
                    self._last_up = None
                    self._last_drp = None
                    self._fault = REBOOT_FAULT
                    self._rp_ok = False
                    self.fw_clock.resync()
                self._identity = ident
                # Acquisition clears only when the ID is complete and its
                # nonce has also been observed on a current boot/heartbeat.
                if self._identity_status_locked()[0]:
                    self._identity_missing_reported = False
                    self._identity_req_at = None
                    self._identity_retries = 0
            if nonce_reboot:
                log.error("RP2040 boot nonce changed on id line (0x%08x) — a "
                          "reboot was missed; identity refreshed from this line "
                          "and safe-state relatched; operator re-arm required",
                          self._boot_nonce)
            if ident["fi1"]:
                # An FI-1 bench fault-injection image must NEVER run at a lane
                # (R1.9 / FA-11 step 3) — loudest available signal short of a trip.
                log.error("RP2040 reports an FI-1 BENCH fault-injection image "
                          "(%s build %s) — never allowed on a live lane",
                          ident["fw"], ident["build"])
            self._push_records([{"kind": "fw_identity", "t_pi": self.now(),
                                 **ident}])

    # ---- v0.2.0 telemetry (helpers called with self._lock HELD; they log via
    # `notes` so no logging handler can ever block under the lock) -------------
    @staticmethod
    def _num(ev, key):
        """ev[key] if it is a FINITE real number (bool excluded), else None —
        additive fields from unknown/fuzzed senders must never throw here.
        R3-10: NaN / Infinity are rejected (they should never survive
        feed_line's parse_constant guard, but this is the belt to that
        suspenders — a non-finite value in extrema/interval math is poison)."""
        v = ev.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if isinstance(v, float) and not math.isfinite(v):
                return None
            return v
        return None

    @staticmethod
    def _identity_text(value, max_len):
        """Return an exact bounded wire identity string, or ``None``.

        Identity is authorization evidence, not display text.  Never trim or
        truncate it before tuple/UID comparison: padding and overlength input
        must be distinguishable from the provisioned value and fail closed.
        """
        if not isinstance(value, str):
            return None
        if (
                not value
                or len(value) > max_len
                or value != value.strip()
                or any(ord(char) < 0x20 or ord(char) > 0x7E
                       for char in value)):
            return None
        return value

    @staticmethod
    def _identity_uint(value, *, nonzero=False):
        """Return an exact uint32 JSON integer, else None (bool excluded)."""
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        if value < (1 if nonzero else 0) or value > 0xFFFFFFFF:
            return None
        return int(value)

    @staticmethod
    def _status_bit(value):
        """Strict JSON boolean/0-or-1 decoder; strings never become true."""
        if isinstance(value, bool):
            return bool(value)
        if (isinstance(value, int) and not isinstance(value, bool)
                and value in (0, 1)):
            return bool(value)
        return None

    def _validate_hb(self, ev):
        """Validate the only record allowed to renew heartbeat liveness."""
        if self._status_bit(ev.get("ok")) is None:
            raise ValueError("heartbeat ok must be JSON bool or integer 0/1")
        if self._identity_uint(ev.get("up")) is None:
            raise ValueError("heartbeat up must be uint32")
        if "flt" in ev and not isinstance(ev.get("flt"), str):
            raise ValueError("heartbeat flt must be a string")
        for key in ("drp", "in", "run", "tap", "rd", "ep",
                    "v5", "v5n", "v5x", "rid"):
            if key in ev and self._identity_uint(ev.get(key)) is None:
                raise ValueError(f"heartbeat {key} must be uint32")
        if "bn" in ev:
            if self._identity_uint(ev.get("bn"), nonzero=True) is None:
                raise ValueError("heartbeat bn must be a nonzero uint32")
        elif self._boot_nonce is not None:
            raise ValueError("heartbeat omitted the known boot nonce")

        modern = bool(
            self._identity_protocol_seen
            or "bn" in ev
            or "rid" in ev
        )
        if not modern:
            return
        fields = set(ev)
        if fields != MODERN_HB_FIELDS:
            missing = sorted(MODERN_HB_FIELDS - fields)
            unknown = sorted(fields - MODERN_HB_FIELDS)
            raise ValueError(
                "modern heartbeat schema mismatch "
                f"(missing={missing}, unknown={unknown})")
        fault = ev["flt"]
        if (
                len(fault) > 64
                or fault != fault.strip()
                or any(ord(char) < 0x20 or ord(char) > 0x7E
                       for char in fault)):
            raise ValueError("heartbeat flt must be a bounded wire token")
        bounds = {
            "in": 0xFF,
            "run": 0x7F,
            "tap": 0x0F,
            "rd": 128,
            "v5": 0xFFFF,
            "v5n": 0xFFFF,
            "v5x": 0xFFFF,
        }
        for key, maximum in bounds.items():
            if ev[key] > maximum:
                raise ValueError(
                    f"heartbeat {key} exceeds qualified schema bound")
        if ev["ep"] == 0:
            raise ValueError("heartbeat ep must be nonzero")
        if ev["rid"] not in (0, 1, 2, 3, 255):
            raise ValueError("heartbeat rid is not a defined strap code")
        if not ev["v5n"] <= ev["v5"] <= ev["v5x"]:
            raise ValueError("heartbeat v5 extrema are inconsistent")

    def _mark_identity_capable_locked(self):
        """Commit the monotonic capability latch with ``_lock`` held."""
        if self._identity_protocol_seen:
            return
        try:
            if self._identity_evidence_callback is not None:
                self._identity_evidence_callback()
        except Exception as exc:
            # The in-process latch still closes in the safe direction.  The
            # durable failure is separately exposed so ARM cannot proceed.
            self._identity_protocol_seen = True
            self._identity_evidence_error = (
                f"{type(exc).__name__}: {exc}")[:240]
            self._rp_ok = False
            self._fault = "identity_evidence_persist_failed"
            self._last_hb = None
            self._heartbeat_sample = None
            raise
        self._identity_protocol_seen = True

    def _reject_heartbeat_sample_locked(self):
        """Invalidate all current-sample facts after a malformed heartbeat."""
        self._note_heartbeat_discontinuity_locked("schema")
        self._last_hb = None
        self._heartbeat_sample = None
        self._rp_ok = False
        self._fault = HEARTBEAT_SCHEMA_FAULT
        self._rid = None
        self._tap_mask = None
        self._ring_depth = None
        self._v5 = None
        self._in_mask = None
        self._run_mask = None
        self._run_mismatch = ()

    def _note_heartbeat_discontinuity_locked(
            self, cause, *, wdt_reset=False):
        """Advance control-visible loss generations with ``_lock`` held.

        The generic generation is the safety authority consumed by the daemon.
        Subtype generations preserve diagnostic attribution even when a later
        clean heartbeat has already replaced the current fault fields before
        the controller thread gets CPU.
        """
        self._hb_discontinuity_generation += 1
        if cause == "reboot":
            self._reboot_discontinuity_generation += 1
            if wdt_reset:
                self._wdt_reboot_discontinuity_generation += 1

    def _mask_danger(self, mask, bit):
        # hb "in" bits are debounced ASSERTED levels. Map level -> danger flag the
        # same way cam edges do: trip_edge 'f' => asserted == in-window (default,
        # matches the active-low board); 'r' inverts (bench-confirm knob).
        lvl = bool(mask & bit)
        return lvl if self._trip == "f" else not lvl

    def _invalidate_identity_cache(self, *, clear_nonce=False):
        """R3-5: drop ALL cached identity / capability / extrema state so a
        post-reboot image can never be read through the previous image's
        identity (revision, build/config hashes, RID, MAXRUN, tap masks, V5
        extrema, run/in masks, v1.1 posture). Callers repopulate from the boot
        event and/or re-request the id line. Also re-arms the identity
        re-request state machine (poll_identity, driven off-lock by the daemon,
        issues the first ID request immediately and retries on a bounded
        schedule — sending here on the reader thread mid-parse is avoided)."""
        self._identity = None
        self._rid = None
        self._maxrun_ms = None
        self._v5 = None
        self._tap_mask = None
        self._ring_depth = None
        self._in_mask = None
        self._run_mask = None
        self._v11 = None
        self._confirmed_boot_nonce = None
        if clear_nonce:
            self._boot_nonce = None
        self._identity_boot_seen = True
        self._identity_req_at = None
        self._identity_retries = 0
        self._identity_missing_reported = False

    def _nonce_reboot(self, ev):
        """v1.2.3 (R3-5): update the cached per-boot nonce from ev's "bn" and
        return True iff it CHANGED from a previously-known value — i.e. the
        firmware rebooted since our last cache even though the boot line and any
        uptime regression were both missed. Returns False on the first nonce
        seen (nothing to compare) and when the firmware sends no bn (older
        image). Never raises."""
        bn = self._identity_uint(ev.get("bn"), nonzero=True)
        if bn is None:
            return False
        prev = self._boot_nonce
        self._boot_nonce = bn
        return prev is not None and bn != prev

    def _confirm_boot_nonce(self, ev):
        """Confirm a nonce observed on a boot/heartbeat line."""
        bn = self._identity_uint(ev.get("bn"), nonzero=True)
        if bn is not None and bn == self._boot_nonce:
            self._confirmed_boot_nonce = bn
            if self._identity_status_locked()[0]:
                self._identity_missing_reported = False
                self._identity_req_at = None
                self._identity_retries = 0

    def _on_boot(self, ev, notes, records=None):
        # A boot record is a control-authority discontinuity even if a complete
        # new ID + clean heartbeat are already buffered behind it.  The daemon
        # consumes this monotonic generation and forces its existing hard-safe
        # + fresh-PBZ recovery path.  Current health fields must never erase the
        # fact that RP_OK dropped and the firmware's command state restarted
        # between two controller ticks.
        self._note_heartbeat_discontinuity_locked(
            "reboot", wdt_reset=bool(ev.get("wdt_reset")))
        rebooted = self._last_up is not None    # we had heartbeats before this boot
        self._last_up = None                    # fresh uptime/drp baselines
        self._last_drp = None
        # R3-5 (Codex round-3): a reboot INVALIDATES all cached identity /
        # capability / extrema state. Codex's repro flashed a v1.2.2 image,
        # then rebooted into a v0.1 image that sends no id line — the STALE
        # v1.2.2 identity survived and the daemon armed against a board it could
        # no longer identify. Clear it all here; the fresh boot event's own
        # fields repopulate below, and the id line is re-requested so a firmware
        # that still speaks v1.2.2 re-announces. What it CANNOT do is keep
        # reading as the old image.
        self._invalidate_identity_cache(clear_nonce=True)
        # Cache this boot's nonce so a LATER hb (whose boot line we DID see) is
        # only flagged if the nonce changes again.
        self._nonce_reboot(ev)
        self._confirm_boot_nonce(ev)
        # fw ms clock restarted at 0 -> the learned offset is garbage. Resync on
        # EVERY boot event (first boot included: offset may predate a missed boot).
        self.fw_clock.resync()
        fw = ev.get("fw")
        if isinstance(fw, str) and fw.strip():
            self._fw_version = fw.strip()[:80]
        self._boot_wdt = bool(ev.get("wdt_reset"))
        # v1.2 boot tap facts: ring epoch + preservation state (R2-11). The
        # epoch is the staleness anchor — tape entries from an EARLIER epoch
        # are pre-reboot edges and must never read as fresh diagnosis.
        tap = ev.get("tap")
        if isinstance(tap, dict):
            ep = self._num(tap, "ep")
            if ep is not None:
                self._ring_epoch = int(ep)
            if records is not None:
                records.append({
                    "kind": "fw_boot", "t_pi": self.now(),
                    "fw": self._fw_version, "wdt_reset": self._boot_wdt,
                    "ring_epoch": self._ring_epoch,
                    "ring_preserved": bool(self._num(tap, "pre")),
                    "ring_entries": self._num(tap, "n"),
                    "rebooted": rebooted,
                })
        # Fresh firmware = motors all stopped; let the run-mask reconciliation
        # start a fresh episode (it re-sends RUN for anything still commanded).
        #
        # DELIBERATE: _cmd_run is NOT cleared on a firmware reboot. The MCP23017
        # outputs are latched by the Pi, so a motor commanded ON is still
        # PHYSICALLY running through an RP2040 reboot — re-sending RUN restores
        # the max-run/motion-no-run backstop for exactly those motors. Clearing
        # instead (pre-flash review 2026-07-07 finding 2 proposed it) would leave
        # a still-running motor unsupervised until the daemon's next transition.
        # Heartbeat reconciliation revalidates each captured intent under
        # _lock at send time, so it cannot issue stale STOP after a new RUN or
        # stale RUN after hard-safe STOP.
        self._resync_tries = {}
        self._run_mismatch = ()
        v11 = ev.get("v11")
        if isinstance(v11, dict):
            # v1.1.1 enforcement posture — log it so an ARMED image at a lane is
            # visible on the wire (finding 37: FW_VERSION is identical for armed
            # and stock builds). WARNING when anything is armed, INFO when stock.
            self._v11 = dict(v11)
            armed = (v11.get("sa") not in (None, "off")
                     or v11.get("ta1") not in (None, "off")
                     or bool(v11.get("echo")) or bool(v11.get("nrun")))
            notes.append((log.warning if armed else log.info,
                          "RP2040 v1.1 enforcement posture (%s): sa=%s ta1=%s "
                          "echo=%s nrun=%s",
                          ("ARMED" if armed else "stock/off", v11.get("sa"),
                           v11.get("ta1"), v11.get("echo"), v11.get("nrun"))))
        mr = self._num(ev, "maxrun_ms")
        if mr is not None:
            self._maxrun_ms = int(mr)
            fsm_s = _fsm_max_motion_s()
            if fsm_s is not None and fsm_s * 1000.0 > self._maxrun_ms:
                notes.append((log.error,
                              "RP2040 firmware maxrun_ms=%d < FSM MAX_MOTION_S=%.1fs — "
                              "constants have desynchronized; maxrun_ok() is False, "
                              "do not arm until reconciled",
                              (self._maxrun_ms, fsm_s)))
        if ev.get("wdt_reset"):
            notes.append((log.error, "RP2040 hardware-watchdog reset (boot %r)", (ev,)))
        if rebooted:
            # Mid-session reboot: latch the synthetic fault so health_ok() goes
            # False and the daemon's existing safety trip runs (motors off,
            # MANUAL_INTERVENTION, operator PBZ re-arm). Cleared by the next
            # clean hb (flt:""), by which time a health_ok() poller faster than
            # the ~4 Hz hb rate (the daemon ticks at ~50 Hz) has observed it —
            # the daemon's trip itself latches until PBZ.
            self._fault = REBOOT_FAULT
            self._rp_ok = False
            notes.append((log.error,
                          "RP2040 firmware REBOOTED mid-session (boot event %r) — "
                          "safe-state relatch; operator re-arm required", (ev,)))

    def _on_hb(self, ev, notes, resends, records=None):
        # v1.2.3 (R3-5): FIRST, before any of this hb's fields repopulate the
        # cache, check the per-boot nonce. A changed "bn" means the firmware
        # rebooted since our last cache even though we NEVER saw the boot line
        # (dropped) AND the uptime may NOT have regressed (a quick double-reboot,
        # or several missed hbs leaving up >= last). This is the exact gap the
        # uptime-regression test below cannot cover. Treat it as a full reboot:
        # invalidate the stale identity/capability cache and latch the same
        # safe-state relatch a boot event would. The rest of this hb (rid/v5/in/
        # run) then repopulates from the NEW image.
        reboot_discontinuity_noted = False
        if self._nonce_reboot(ev):
            # Preserve the reboot even when the reader consumes this heartbeat,
            # the matching ID, and a later clean heartbeat before the 50 Hz
            # controller gets CPU.  `_fault`/`_rp_ok` are current-state fields;
            # only this monotonic generation makes the intervening loss
            # impossible to erase.
            self._note_heartbeat_discontinuity_locked("reboot")
            reboot_discontinuity_noted = True
            self._invalidate_identity_cache()
            self._last_up = None
            self._last_drp = None
            self._fault = REBOOT_FAULT
            self._rp_ok = False
            self.fw_clock.resync()
            if records is not None:
                records.append({"kind": "fw_boot", "t_pi": self.now(),
                                "fw": self._fw_version, "wdt_reset": False,
                                "ring_epoch": self._ring_epoch,
                                "rebooted": True, "via": "nonce"})
            notes.append((log.error,
                          "RP2040 boot nonce changed to 0x%08x on hb — firmware "
                          "REBOOTED (boot line missed, uptime did not regress); "
                          "identity cache invalidated + safe-state relatch; "
                          "operator re-arm required", (self._boot_nonce,)))
        self._confirm_boot_nonce(ev)
        # v1.2 hb fields (R2-11): tap levels, ring depth/epoch, VCC_5V window
        # extrema. Store-only at ~4 Hz — thresholding/alerting is the daemon's
        # job (v5_stats/tap_levels/ring_epoch accessors), so the hb path stays
        # allocation-light and no event floods at heartbeat rate.
        tapm = self._num(ev, "tap")
        if tapm is not None:
            self._tap_mask = int(tapm)
        rd = self._num(ev, "rd")
        if rd is not None:
            self._ring_depth = int(rd)
        ep = self._num(ev, "ep")
        if ep is not None:
            self._ring_epoch = int(ep)
        v5 = self._num(ev, "v5")
        if v5 is not None:
            self._v5 = (int(v5), self._num(ev, "v5n"), self._num(ev, "v5x"))
        rid = self._num(ev, "rid")
        if rid is not None:
            self._rid = int(rid)    # v1.2.2 (R2-6): REV_ID strap code, store-only
        m = self._num(ev, "in")
        if m is not None:
            m = int(m)
            self._in_mask = m
            sc = self._mask_danger(m, _IN_BIT_SC)
            tb = self._mask_danger(m, _IN_BIT_TB)
            if sc != self._sc_danger or tb != self._tb_danger:
                notes.append((log.warning,
                              "SC/TB interlock echo resynced from hb in-mask 0x%02x: "
                              "SC %s->%s TB %s->%s (edge history drifted — dropped line?)",
                              (m, self._sc_danger, sc, self._tb_danger, tb)))
            self._sc_danger = sc
            self._tb_danger = tb
        r = self._num(ev, "run")
        if r is not None:
            self._run_mask = int(r)
            self._reconcile_run(int(r), notes, resends)
        drp = self._num(ev, "drp")
        if drp is not None:
            if self._last_drp is not None and drp > self._last_drp:
                notes.append((log.warning,
                              "RP2040 dropped %d TX line(s) (drp %d -> %d) — UART "
                              "congested; cam/ball events may have been lost",
                              (drp - self._last_drp, self._last_drp, drp)))
                if records is not None:
                    # R2-12: UART drops become a structured fault stream, not
                    # just a log line — the daemon promotes this record to a
                    # 'uart_drops' machine event.
                    records.append({"kind": "uart_drops", "t_pi": self.now(),
                                    "lost": int(drp - self._last_drp),
                                    "total": int(drp)})
            self._last_drp = drp
        up = self._num(ev, "up")
        if up is not None:
            if self._last_up is None or up >= self._last_up:
                # hb "up" shares the fw event timebase — free FwClock samples at
                # the ~4 Hz hb rate even on quiet lanes. Skipped on a regression
                # (the resync below must happen first).
                self.fw_clock.update(up, self.now())
            if self._last_up is not None and up < self._last_up:
                # Uptime went BACKWARDS => the firmware rebooted and we missed the
                # boot line. Same safety trip as a boot event. Applied LAST so this
                # hb's own ok/flt fields can't mask it. NOTE: firmware up is uint32
                # ms — a wrap at ~49.7 days reads as a regression too; that false
                # trip is in the SAFE direction (nuisance PBZ) and is accepted.
                self._fault = REBOOT_FAULT
                self._rp_ok = False
                # A nonce-changing modern heartbeat has already recorded this
                # same reboot above.  Older/no-nonce firmware reaches only this
                # path, so record it here without double-counting one sample.
                if not reboot_discontinuity_noted:
                    self._note_heartbeat_discontinuity_locked("reboot")
                self.fw_clock.resync()     # fw ms clock restarted; offset is garbage
                # R3-5: an uptime-regression reboot must ALSO invalidate the
                # cached identity/capability state (the nonce path already did
                # this above; this covers OLDER firmware that sends no "bn").
                # Harmless if the nonce path just ran (double invalidation).
                self._invalidate_identity_cache(clear_nonce=True)
                self._nonce_reboot(ev)
                self._confirm_boot_nonce(ev)
                notes.append((log.error,
                              "RP2040 uptime regressed %s -> %s ms: firmware REBOOTED "
                              "(boot line missed) — identity cache invalidated + "
                              "safe-state relatch; operator re-arm required",
                              (self._last_up, up)))
            self._last_up = up

    def _reconcile_run(self, mask, notes, resends):
        """Compare the firmware's hb "run" mask against the RUN/STOP state WE
        commanded and heal any desync (finding 38: RUN/STOP have no ACK/CRC —
        a lost STOP deterministically latches motion_timeout at 8 s and drops
        the rail; a lost RUN silently removes the firmware's max-run backstop
        for that motion). Called with self._lock HELD; corrective
        ``(motor, desired)`` intents are appended to `resends`, then rechecked
        against current command intent at send time.

        Re-sending is safe with current firmware: main.c stamps the max-run
        timer only on a false->true transition, so a duplicate (the benign
        race with an hb that snapshotted just before our command landed) is a
        no-op. Bounded: RUN_RESYNC_RETRIES per motor per mismatch episode; a
        mismatch that outlives the retries is logged as an ERROR once and
        stays visible via run_mismatch() for the daemon to poll."""
        mismatched = []
        for i, name in enumerate(HB_RUN_BITS):
            fw_running = bool(mask & (1 << i))
            cmd = self._cmd_run.get(name, False)
            if fw_running == cmd:
                if name in self._resync_tries:
                    del self._resync_tries[name]   # episode over
                    notes.append((log.info,
                                  "RP2040 run-state for %s reconciled (commanded %s)",
                                  (name, "RUN" if cmd else "STOP")))
                continue
            mismatched.append(name)
            tries = self._resync_tries.get(name, 0)
            if tries < RUN_RESYNC_RETRIES:
                # Do not consume a retry yet. The controller may change intent
                # after this heartbeat snapshot; _send_reconcile rechecks and
                # increments only for an actual current-intent send attempt.
                resends.append((name, cmd, fw_running))
            elif tries == RUN_RESYNC_RETRIES:
                self._resync_tries[name] = tries + 1   # log the exhaustion once
                notes.append((log.error,
                              "RP2040 run-state mismatch for %s persists after %d "
                              "re-sends — UART eating lines? run_mismatch() stays "
                              "latched; the firmware max-run backstop may be "
                              "desynced for this motor",
                              (name, RUN_RESYNC_RETRIES)))
        self._run_mismatch = tuple(mismatched)

    def _send_reconcile(self, motor, desired, *, fw_running=None):
        """Send a heartbeat reconciliation only if its intent is still current.

        The heartbeat reader must not emit a captured stale STOP after the
        controller has physically turned a motor ON and sent RUN, nor a stale
        RUN after hard-safe STOP. Holding ``_lock`` across the bounded send
        makes either the reconciliation or the controller's later command
        definitively last on the wire.
        """
        attempted = False
        attempt_no = None
        line = f"RUN {motor}" if desired else f"STOP {motor}"
        with self._lock:
            if self._cmd_run.get(motor, False) is not bool(desired):
                return False
            tries = self._resync_tries.get(motor, 0)
            if tries >= RUN_RESYNC_RETRIES:
                return False
            attempt_no = tries + 1
            self._resync_tries[motor] = attempt_no
            attempted = True
            result = self._send(line)
        if attempted:
            log.warning(
                "RP2040 run-state MISMATCH for %s: firmware=%s "
                "commanded=%s (lost/corrupt RUN/STOP line?) — "
                "re-sending %r (retry %d/%d)",
                motor,
                ("unknown" if fw_running is None
                 else ("running" if fw_running else "stopped")),
                "RUN" if desired else "STOP", line,
                attempt_no, RUN_RESYNC_RETRIES)
        return result

    # ---- v1.2.x tap ring / warnings (R2-11; called with self._lock HELD) ----
    def _on_tap_event(self, kind, ev, records):
        """Consume tapdump/tape/tapdump_end/tapwarn lines. The full ring is
        collected between the tapdump header and tapdump_end, then emitted as
        ONE typed 'tapdump' record with per-entry epoch staleness already
        judged (entry.ep != the dump's epoch => stale pre-reboot edge —
        excluded from fresh diagnosis, reported separately). Bounded:
        TAPDUMP_ENTRIES_MAX entries per dump, overflow counted."""
        if kind == "tapwarn":
            records.append({"kind": "tap_warn", "t_pi": self.now(),
                            "code": str(ev.get("code", ""))[:80],
                            "t_fw": self._num(ev, "t")})
            return
        if kind == "tapdump":
            ep = self._num(ev, "ep")
            if ep is not None:
                self._ring_epoch = int(ep)
            self._tapdump = {
                "n": self._num(ev, "n"),
                "epoch": self._ring_epoch,
                "boot_reason": self._num(ev, "br"),
                "muted_mask": self._num(ev, "mut"),
                "cause": str(ev.get("cause", ""))[:40] or None,
                "t_fw": self._num(ev, "t"),
                "entries": [],
                "discarded": 0,
            }
            return
        if kind == "tape":
            dump = self._tapdump
            if dump is None:
                # missed header (dropped line): collect into an implicit dump
                # so the entries still surface rather than vanish.
                dump = self._tapdump = {
                    "n": None, "epoch": self._ring_epoch, "boot_reason": None,
                    "muted_mask": None, "cause": None, "t_fw": None,
                    "entries": [], "discarded": 0, "headerless": True,
                }
            if len(dump["entries"]) >= TAPDUMP_ENTRIES_MAX:
                dump["discarded"] += 1
                return
            p = self._num(ev, "p")
            entry_ep = self._num(ev, "ep")
            cur_ep = dump["epoch"]
            dump["entries"].append({
                "i": self._num(ev, "i"),
                "t_fw": self._num(ev, "t"),
                "pin": (TAP_BITS[int(p)] if p is not None
                        and 0 <= int(p) < len(TAP_BITS) else f"?{p}"),
                "level": self._num(ev, "l"),
                "epoch": entry_ep,
                # Epoch-aware staleness (R2-11): a pre-reboot edge must never
                # influence fresh diagnosis. Unknown epochs are treated STALE
                # (fail toward exclusion).
                "stale": (entry_ep is None or cur_ep is None
                          or int(entry_ep) != int(cur_ep)),
            })
            return
        if kind == "tapdump_end":
            dump, self._tapdump = self._tapdump, None
            if dump is None:
                return
            entries = dump.pop("entries")
            fresh = [e for e in entries if not e["stale"]]
            records.append({
                "kind": "tapdump", "t_pi": self.now(),
                "meta": dump,
                "entries": entries,
                "fresh_n": len(fresh),
                "stale_n": len(entries) - len(fresh),
                "end_n": self._num(ev, "n"),
            })

    def _push_records(self, records):
        """Append typed records to the bounded drain queue. Never raises."""
        if not records:
            return
        try:
            with self._dr_lock:
                for r in records:
                    if len(self._diag_records) == self._diag_records.maxlen:
                        self.diag_record_drops += 1
                    self._diag_records.append(r)
        except Exception:
            log.debug("_push_records swallowed", exc_info=True)

    def drain_diag_records(self):
        """Drain the typed v1.2.x record queue (daemon tick side — the
        consumer turns these into DiagEvents; enqueue-only downstream)."""
        with self._dr_lock:
            out = list(self._diag_records)
            self._diag_records.clear()
        return out

    # ---- FSM bridge --------------------------------------------------------
    @contextmanager
    def control_transaction(self):
        """Freeze safety facts and snapshot inbound motion for one control tick.

        The bounded critical section is owned by the daemon tick.  Identity,
        max-run, health, run-mask, and event admission all serialize on
        ``_lock``; the event queue is copied under the fixed
        ``_lock -> _evlock`` order.  Events arriving after the snapshot wait
        for the next tick, whose prerequisite check runs before dispatch.
        """
        with self._lock:
            with self._evlock:
                evs = list(self._events)
                self._events.clear()
            yield evs

    @contextmanager
    def state_transaction(self):
        """Freeze link state without draining/dispatching the event queue."""
        with self._lock:
            yield

    @staticmethod
    def apply_event_batch(evs, controller, observer=None):
        """Dispatch a previously snapshotted event batch into the FSM."""
        for kind, ident, t_fw, t_pi in evs:
            if kind == "cam":
                dispatch_cam(controller, ident)
            elif kind == "ball":
                controller.on_ball()
            if observer is not None:
                try:
                    observer(kind, ident, t_fw, t_pi)
                except Exception:
                    log.debug("apply_events observer swallowed", exc_info=True)
        return len(evs)

    def apply_events(self, controller, observer=None):
        """Drain queued cam/ball events into the FSM. Call from the daemon's main
        loop only (keeps FSM access single-threaded). Returns the count applied.

        Queue entries are (kind, ident, t_fw_ms, t_pi_mono): t_fw_ms is the
        firmware's 1 ms edge timestamp (None on v0.1.0 lines without "t"),
        t_pi_mono the Pi-monotonic receive time. `observer`, when given, is
        called AFTER each event is dispatched with exactly those four fields —
        the daemon uses it to timestamp cam-timing telemetry off the firmware
        clock (via fw_clock.est_pi_time). Observer exceptions are swallowed:
        this runs inside the 50 Hz tick and must never raise or block."""
        with self._evlock:
            evs = list(self._events)
            self._events.clear()
        return self.apply_event_batch(evs, controller, observer)

    # ---- queries -----------------------------------------------------------
    def interlock_ok(self):
        """TB/SC collision echo: a collision course is SC AND TB both in their
        danger window at once (SYSTEM_REFERENCE §5). Software echo of the hardware
        J_SAFETY loop — returns True (no veto) unless both are simultaneously bad."""
        with self._lock:
            return not (self._sc_danger and self._tb_danger)

    def rp_ok(self):
        with self._lock:
            return self._rp_ok

    def _actuation_freshness_locked(self):
        """Return ``(health_ok, exact_remaining_seconds)`` with _lock held."""
        remaining = (
            None if self._last_hb is None
            else self._hb_timeout - (self.now() - self._last_hb)
        )
        alive = remaining is not None and remaining >= 0.0
        healthy = (
            alive and self._rp_ok and not self._fault
            and self._send_fails < SEND_FAIL_LIMIT
        )
        return bool(healthy), remaining

    def heartbeat_freshness_remaining(self):
        """Exact heartbeat lease remainder, sampled while holding link state.

        ``None`` means no qualifying heartbeat has been accepted. A negative
        value is the amount by which the deadline has already been exceeded.
        This is intentionally not clamped: positive-actuation guards need the
        real budget, not only a boolean alive/dead answer.
        """
        with self._lock:
            return self._actuation_freshness_locked()[1]

    def actuation_freshness_status(self):
        """Atomically return ``(full_link_health, heartbeat_remaining_s)``."""
        with self._lock:
            return self._actuation_freshness_locked()

    def is_alive(self):
        with self._lock:
            _healthy, remaining = self._actuation_freshness_locked()
            return remaining is not None and remaining >= 0.0

    def health_ok(self):
        """True only if the RP2040 is heartbeating, reports rail-permit OK, has no
        latched fault, AND our serial TX path works. Any flt (even without a paired
        rp_ok:0) => not healthy; >= SEND_FAIL_LIMIT consecutive write failures (our
        RUN/STOP may not be reaching the firmware) => not healthy."""
        with self._lock:
            return self._actuation_freshness_locked()[0]

    def fault(self):
        with self._lock:
            return self._fault

    def input_levels(self):
        """{name: asserted} decoded from the last hb "in" mask (v0.2.0+ firmware),
        or None if this firmware has never sent one (v0.1.0)."""
        with self._lock:
            m = self._in_mask
        if m is None:
            return None
        return {n: bool(m & (1 << i)) for i, n in enumerate(HB_IN_BITS)}

    def running_motors(self):
        """Tuple of motor names the firmware believes are RUNNING, from the last hb
        "run" mask (v0.2.0+ firmware), or None if never sent (v0.1.0)."""
        with self._lock:
            m = self._run_mask
        if m is None:
            return None
        return tuple(n for i, n in enumerate(HB_RUN_BITS) if m & (1 << i))

    def run_mismatch(self):
        """Motors whose firmware run-state (last hb "run" mask, v0.2.0+) disagreed
        with the RUN/STOP state we commanded — () when in sync, or with v0.1.0
        firmware that never sends the mask. The link re-sends the command up to
        RUN_RESYNC_RETRIES times per episode, so a persistently non-empty tuple
        means the UART is eating lines; the daemon may treat it as a health
        concern (today it is exposure-only — no automatic trip)."""
        with self._lock:
            return self._run_mismatch

    def fw_version(self):
        """The boot event's "fw" string, or None if no boot has been heard.
        (Trustworthy only as a label — see v11_posture() for what's ARMED.)"""
        with self._lock:
            return self._fw_version

    def boot_wdt_reset(self):
        """True when the LAST boot event carried wdt_reset (the RP2040's 250 ms
        hardware watchdog fired -> chip reset). The diagnostics campaign emits
        this as the distinct 'rp2040_wdt_reset' code vs a generic fw_reboot."""
        with self._lock:
            return self._boot_wdt

    def v11_posture(self):
        """The firmware's v1.1 enforcement posture from the boot event
        ({"sa","ta1","echo","nrun"}, v1.1.1+ firmware), or None if never
        reported (stock <= v1.1.0 images). Lets cutover tooling verify WHICH
        image is flashed instead of trusting the FW_VERSION string (finding 37)."""
        with self._lock:
            return dict(self._v11) if self._v11 else None

    def tap_levels(self):
        """{net: observed level} decoded from the last hb "tap" mask (v1.2+
        firmware, rev-D board), or None if never sent. Levels are the
        POST-inversion observed-net levels (firmware already undid the
        2N7002 stage inversion)."""
        with self._lock:
            m = self._tap_mask
        if m is None:
            return None
        return {n: bool(m & (1 << i)) for i, n in enumerate(TAP_BITS)}

    def v5_stats(self):
        """(latest, min, max) VCC_5V millivolts over the last hb window
        (v1.2+ firmware), or None if never sent."""
        with self._lock:
            return self._v5

    def ring_epoch(self):
        """Current tap edge-ring epoch (v1.2+), or None. Entries from an
        earlier epoch are pre-reboot edges (stale)."""
        with self._lock:
            return self._ring_epoch

    def ring_depth(self):
        """Last hb "rd" tap edge-ring depth (v1.2+), or None."""
        with self._lock:
            return self._ring_depth

    def fw_identity(self):
        """The firmware identity line, sanitized: {"fw","bn","pcb","rid",
        "uid","build","cfg","fi1","t_fw"} — or None if never heard (<= v1.2.1
        firmware). pcb is the STRAP-read board revision ("revD"/"legacy"/
        "future"/"unknown"), independent of what image is flashed; fi1 True
        means a BENCH fault-injection image is running (never allowed at a
        lane — logged as an error on receipt)."""
        with self._lock:
            return dict(self._identity) if self._identity else None

    def identity_protocol_seen(self):
        """Whether durable or current-process modern evidence has been seen.

        The initial value may be loaded from the per-lane durable evidence
        record. It is never cleared by reboot/cache invalidation.
        """
        with self._lock:
            return bool(self._identity_protocol_seen)

    def identity_evidence_error(self):
        """Return a bounded persistence failure, if durable evidence failed."""
        with self._lock:
            return self._identity_evidence_error

    def heartbeat_sample(self):
        """Return the current immutable-generation heartbeat sample, or None.

        A sample ceases to be current on timeout or immediately when a
        malformed modern heartbeat arrives.  Callers receive copies so they
        cannot mutate the link's committed generation.
        """
        with self._lock:
            if (
                    self._heartbeat_sample is None
                    or self._last_hb is None
                    or (self.now() - self._last_hb) > self._hb_timeout):
                return None
            sample = dict(self._heartbeat_sample)
            sample["wire"] = dict(sample["wire"])
            return sample

    def heartbeat_discontinuity_generation(self):
        """Monotonic heartbeat/reboot generation for control-loop relatching."""
        with self._lock:
            return self._hb_discontinuity_generation

    def heartbeat_discontinuity_status(self):
        """Atomically snapshot generic and diagnostic subtype generations."""
        with self._lock:
            return {
                "generation": self._hb_discontinuity_generation,
                "reboot_generation":
                    self._reboot_discontinuity_generation,
                "wdt_reboot_generation":
                    self._wdt_reboot_discontinuity_generation,
            }

    def pcb_rev_id(self):
        """Last hb "rid" REV_ID strap code (v1.2.2+): 0-3, 255 = floating/
        unread straps (rev-B/rev-C board), or None if never sent."""
        with self._lock:
            return self._rid

    def identity_ok(self):
        """True only for a complete, non-FI1 identity bound to this boot nonce."""
        with self._lock:
            return self._identity_status_locked()[0]

    def _identity_status_locked(self):
        """Return the protocol-level ``(ok, reason)`` with ``_lock`` held."""
        if self._identity_evidence_error is not None:
            return False, "identity_evidence_persist_failed"
        ident = self._identity
        if ident is None:
            return False, ("identity_missing" if self._identity_missing_reported
                           else "identity_not_received")
        for key in ("fw", "pcb", "uid", "build", "cfg"):
            if not ident.get(key):
                return False, f"{key}_missing"
        if ident.get("rid") is None:
            return False, "rid_missing"
        if ident.get("fi1") is None:
            return False, "fi1_missing"
        if ident.get("fi1") is True:
            return False, "fi1_image"
        nonce = ident.get("bn")
        if nonce is None:
            return False, "boot_nonce_missing"
        if self._boot_nonce is None or nonce != self._boot_nonce:
            return False, "boot_nonce_mismatch"
        if nonce != self._confirmed_boot_nonce:
            return False, "boot_nonce_unconfirmed"
        return True, None

    def identity_status(self):
        """Public protocol-level identity verdict as ``(ok, reason)``."""
        with self._lock:
            return self._identity_status_locked()

    def parse_health(self):
        """Snapshot parser/typed-record loss counters for health reporting."""
        with self._lock:
            parse_errors = int(self.parse_errors)
            quarantined = len(self._quar_lines)
        with self._dr_lock:
            record_drops = int(self.diag_record_drops)
            pending_records = len(self._diag_records)
        return {
            "parse_errors": parse_errors,
            "quarantined_lines": quarantined,
            "diag_record_drops": record_drops,
            "pending_diag_records": pending_records,
        }

    def identity_missing(self):
        """True once poll_identity has exhausted its re-request budget after a
        reboot with no id line (a firmware too old to answer ID, or a dead
        UART). Latched until the next successful id line / reboot."""
        with self._lock:
            return (self._identity_missing_reported
                    and not self._identity_status_locked()[0])

    def poll_identity(self, now=None):
        """Off-tick driver for identity acquisition. Issues an ID request from
        process start and after every reboot, then retries on a bounded
        schedule; returns
        'missing' EXACTLY ONCE when the budget is spent with no id line (the
        daemon turns that into an 'fw_identity_missing' event + ARM inhibit),
        else None. Never raises. Safe to call every platform-health tick."""
        if now is None:
            now = self._now()
        send = False
        result = None
        try:
            with self._lock:
                if (self._identity_status_locked()[0]
                        or not self._identity_boot_seen
                        or self._identity_missing_reported):
                    return None
                if self._identity_req_at is None:
                    send = True
                    self._identity_req_at = now
                elif now - self._identity_req_at >= IDENTITY_RETRY_S:
                    if self._identity_retries < IDENTITY_MAX_RETRIES:
                        self._identity_retries += 1
                        self._identity_req_at = now
                        send = True
                    else:
                        self._identity_missing_reported = True
                        result = "missing"
            if send:
                self.request_identity()   # sends outside the lock
        except Exception:
            log.debug("poll_identity swallowed", exc_info=True)
        return result

    def maxrun_ms(self):
        """Firmware max-run ceiling advertised in the boot event (v0.2.0+), or None
        (v0.1.0 firmware, or no boot event heard yet)."""
        with self._lock:
            return self._maxrun_ms

    def maxrun_ok(self, max_motion_s=None):
        """False ONLY on a KNOWN mismatch: the firmware advertised maxrun_ms (v0.2.0
        boot event) and it is below the FSM's MAX_MOTION_S (or the explicit
        `max_motion_s` argument) — the two are independently-maintained constants,
        and a field-tuned FSM limit above the firmware ceiling means the firmware
        backstop would kill legitimate motions. Unknown (v0.1.0 firmware with no
        maxrun_ms, or cycle_control_8270 not importable on this host) returns True
        so v0.1.0 boards keep working unchanged — use maxrun_ms() to distinguish
        "checked OK" from "couldn't check".

        Wiring this into arm-refusal belongs to the daemon/FSM (call it before
        arming); this link only answers the question."""
        with self._lock:
            mr = self._maxrun_ms
        if mr is None:
            return True
        if max_motion_s is None:
            max_motion_s = _fsm_max_motion_s()
            if max_motion_s is None:
                return True
        return max_motion_s * 1000.0 <= mr

    # ---- reader thread (real serial) --------------------------------------
    def start(self):
        if self._ser is None:
            return
        self._reader = threading.Thread(target=self._read_loop, name="rp2040-rx", daemon=True)
        self._reader.start()
        # Round-3: learn the board's identity even when WE are the one that
        # (re)started — the firmware only volunteers `id` at its own boot.
        self.poll_identity(now=self._now())

    def _read_loop(self):
        while not self._stop:
            try:
                data = self._ser.read(256)
            except Exception as e:
                log.warning("RP2040 serial read error: %s", e)
                time.sleep(0.5)
                continue
            # The serial reader exists regardless of the optional diagnostics
            # platform thread, so it owns the retry cadence as a backstop.
            # poll_identity is lock-bounded and sends only every retry interval.
            self.poll_identity()
            if not data:
                continue
            self._ingest(data)

    def _ingest(self, data):
        """Buffer raw RX bytes and dispatch complete lines. BOUNDED: a babbling
        UART that never sends a newline cannot grow memory past RX_MAX — the
        buffer is dropped whole and bytes are discarded until the next newline
        (mirrors the firmware's v0.2.0 oversized-line whole-discard, so a trimmed
        tail can never re-parse as a fresh event)."""
        self._rx += data
        while b"\n" in self._rx:
            line, self._rx = self._rx.split(b"\n", 1)
            if self._rx_discard:        # swallow the tail of an oversized line
                self._rx_discard = False
                continue
            self.feed_line(line.decode("ascii", errors="replace"))
        if len(self._rx) > RX_MAX:
            if not self._rx_discard:    # log once per overflow episode
                log.warning("RP2040 RX overflow: %d bytes with no newline — "
                            "discarding until the next line break", len(self._rx))
            self._rx = b""
            self._rx_discard = True

    def close(self):
        self._stop = True
        ser = self._ser
        self._ser = None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


# --------------------------------------------------------------------------
# Host tests (no hardware): python rp2040_link.py   (exit 0 = all pass)
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cycle_control_8270 import CycleController, State, Ball, Cycle, TIME_DELAY_S
    from controller_io import RecordingIO

    checks = {"n": 0, "fail": 0}

    def check(cond, msg):
        checks["n"] += 1
        if cond:
            print(f"  ok:   {msg}")
        else:
            checks["fail"] += 1
            print(f"  FAIL: {msg}")

    # fake monotonic clock for deterministic health/timeout tests
    clk = {"t": 1000.0}
    def fake_now():
        return clk["t"]

    print("== rp2040_link host test ==")

    # [A] inbound parsing: health + rp_ok variants -------------------------
    print("[A] parsing / health")
    link = RP2040Link(now=fake_now, hb_timeout=1.0)
    link.feed_line('{"ev":"boot","fw":"x","wdt_reset":0,"rp_ok":0}')
    check(link.rp_ok() is False, "boot sets rp_ok False")
    check(not link.is_alive(), "boot cannot renew supervised heartbeat liveness")
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":10}')
    check(link.rp_ok() is True and link.health_ok(), "hb ok:1 -> rp_ok True + health_ok")
    link.feed_line('{"ev":"rp_ok","v":0}')
    check(link.rp_ok() is False, "rp_ok v:0 -> rp_ok False")
    clk["t"] += 2.0                                  # exceed hb_timeout
    check(not link.is_alive(), "stale heartbeat -> not alive")
    link.feed_line('not json'); link.feed_line('')   # must not throw
    check(True, "malformed/empty lines ignored")

    # [B] interlock echo (SC ∧ TB) -----------------------------------------
    print("[B] interlock echo")
    link = RP2040Link(now=fake_now)
    check(link.interlock_ok(), "default interlock_ok True")
    link.feed_line('{"ev":"cam","id":"SC","e":"f"}')
    check(link.interlock_ok(), "SC danger alone -> still OK")
    link.feed_line('{"ev":"cam","id":"TB","e":"f"}')
    check(not link.interlock_ok(), "SC AND TB danger -> interlock veto")
    link.feed_line('{"ev":"cam","id":"SC","e":"r"}')
    check(link.interlock_ok(), "SC clears -> OK again")
    check(len(link._events) == 0, "interlock cams are NOT queued as FSM cam events")

    # [C] cam/ball events drive the FSM through a full cycle ----------------
    print("[C] FSM dispatch via apply_events")
    io = RecordingIO()
    c = CycleController(21, io)
    c.power_restore(); c.first_ball_zero()
    check(c.state is State.READY, "FSM ready after power_restore + first_ball_zero")
    link = RP2040Link(now=fake_now)
    io.grippers = 0                                  # strike (no pins)
    link.feed_line('{"ev":"ball","src":"L"}')
    link.apply_events(c)
    check(c.state is State.SWEEP_TO_GUARD, "ball event -> SWEEP_TO_GUARD")
    link.feed_line('{"ev":"cam","id":"SB","e":"f"}'); link.apply_events(c)
    check(c.state is State.GUARD_DELAY, "SB trip -> GUARD_DELAY")
    io.advance(TIME_DELAY_S + 0.1); c.poll()
    check(c.state is State.TABLE_DETECT, "delay elapsed -> TABLE_DETECT")
    link.feed_line('{"ev":"cam","id":"TA2","e":"f"}'); link.apply_events(c)
    check(c.cycle is Cycle.STRIKE and c.state is State.RUNTHROUGH, "TA2 trip -> strike + RUNTHROUGH")
    link.feed_line('{"ev":"cam","id":"SA","e":"f"}'); link.apply_events(c)
    check(c.state is State.TABLE_FINISH, "SA trip -> TABLE_FINISH")
    io.advance(0.3); c.bin_full()                    # BS is a slow MCP input, not the RP2040 link
    check(c.state is State.SPOTTING, "BS -> SPOTTING (fresh rack)")
    link.feed_line('{"ev":"cam","id":"TA1","e":"f"}'); link.apply_events(c)
    check(c.state is State.READY and c.ball is Ball.FIRST, "TA1 trip -> cycle complete, READY")

    # the trip edge is configurable; a non-trip edge must NOT dispatch
    link2 = RP2040Link(now=fake_now, trip_edge="f")
    link2.feed_line('{"ev":"cam","id":"SB","e":"r"}')
    check(len(link2._events) == 0, "non-trip ('r') cam edge is not dispatched")

    # [D] RUN/STOP emission via the io integration --------------------------
    print("[D] RUN/STOP emission")
    link = RP2040Link(now=fake_now)
    io = RecordingIO(rp2040=link)
    io.set_sweep(True)
    check("RUN S" in link.sent, "set_sweep(True) -> RUN S")
    io.set_sweep(False)
    check("STOP S" in link.sent, "set_sweep(False) -> STOP S")
    io.set_table(True); io.set_spot(True)
    check("RUN T" in link.sent and "RUN SP" in link.sent, "table/spot -> RUN T / RUN SP")
    # io.interlock_ok() now echoes the link
    link.feed_line('{"ev":"cam","id":"SC","e":"f"}')
    link.feed_line('{"ev":"cam","id":"TB","e":"f"}')
    check(io.interlock_ok() is False, "RecordingIO.interlock_ok echoes the link veto")

    # [E] outbound command formatting --------------------------------------
    print("[E] commands")
    link = RP2040Link(now=fake_now)
    link.clear(); link.ping(); link.stop_all()
    check(list(link.sent) == ["CLEAR", "PING", "STOP *"], "CLEAR / PING / STOP * formatting")

    # [F] a bare firmware fault marks unhealthy without a paired rp_ok:0 (P2 fix) ----
    print("[F] fault -> unhealthy")
    link = RP2040Link(now=fake_now, hb_timeout=1.0)
    link.feed_line('{"ev":"hb","ok":1,"up":10}')
    check(link.health_ok(), "(setup) healthy after hb ok:1")
    link.feed_line('{"ev":"flt","code":"motion_timeout","m":"S"}')   # NO paired rp_ok:0
    check(not link.health_ok(), "bare flt event -> NOT healthy")
    check(link.rp_ok() is False, "flt also clears rp_ok")
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":20}')          # post-CLEAR heartbeat
    check(link.health_ok(), "hb ok:1 flt:'' clears the fault -> healthy again")

    # [G] v1.1.1: boot v11 posture + hb run-mask reconciliation ---------------
    print("[G] v11 posture / run-mask reconciliation")
    link = RP2040Link(now=fake_now)
    check(link.v11_posture() is None, "no boot heard -> v11_posture() None")
    link.feed_line('{"ev":"boot","fw":"x","wdt_reset":0,"rp_ok":0,"maxrun_ms":8000,'
                   '"v11":{"sa":"off","ta1":"off","echo":0,"nrun":0}}')
    check(link.v11_posture() == {"sa": "off", "ta1": "off", "echo": 0, "nrun": 0},
          "boot v11 posture stored + queryable")
    check(link.run_mismatch() == (), "no run mask heard -> run_mismatch() empty")
    # lost STOP: we commanded STOP but the firmware still shows S running
    link.run("S"); link.stop("S")
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":100,"run":1}')   # S = bit 0
    check(link.run_mismatch() == ("S",), "fw-running vs commanded-STOP -> mismatch flagged")
    check(list(link.sent).count("STOP S") == 2, "mismatch re-sends the STOP")
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":350,"run":0}')   # firmware caught up
    check(link.run_mismatch() == (), "agreeing hb clears the mismatch")
    # lost RUN: we commanded RUN but the firmware never marked it
    link2g = RP2040Link(now=fake_now)
    link2g.run("T")
    for i in range(6):                                               # persistent desync
        link2g.feed_line('{"ev":"hb","ok":1,"flt":"","up":%d,"run":0}' % (100 + 250 * i))
    check(link2g.run_mismatch() == ("T",), "persistent desync stays flagged")
    check(list(link2g.sent).count("RUN T") == 1 + 3,
          "re-sends are bounded (1 original + RUN_RESYNC_RETRIES)")
    link2g.feed_line('{"ev":"hb","ok":1,"flt":"","up":9000}')        # v0.1.0-style hb: no run
    check(link2g.run_mismatch() == ("T",), "hb without a run mask leaves the flag untouched")

    # [H] v1.2.2 identity line + hb rid (R2-6) ------------------------------
    print("[H] v1.2.2 identity")
    link = RP2040Link(now=fake_now)
    check(link.fw_identity() is None and link.pcb_rev_id() is None,
          "no id/rid heard -> fw_identity()/pcb_rev_id() None")
    link.feed_line('{"ev":"id","fw":"phase8b-rp2040 v1.2.2","pcb":"revD","rid":1,'
                   '"uid":"E66038B713952A31","build":"10c3a26-dirty","cfg":"aa4ff333",'
                   '"fi1":0,"t":123}')
    ident = link.fw_identity()
    check(ident is not None and ident["pcb"] == "revD" and ident["rid"] == 1
          and ident["uid"] == "E66038B713952A31" and ident["build"] == "10c3a26-dirty"
          and ident["cfg"] == "aa4ff333" and ident["fi1"] is False,
          "id line stored + queryable (sanitized)")
    recs = link.drain_diag_records()
    check(any(r["kind"] == "fw_identity" and r.get("pcb") == "revD" for r in recs),
          "id line emitted as a typed fw_identity record")
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":500,"rid":1}')
    check(link.pcb_rev_id() == 1, "hb rid stored (pcb_rev_id)")
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":750,"rid":255}')
    check(link.pcb_rev_id() == 255, "floating strap code (255) passes through")
    # FI-1 image: flagged in the identity + record (log.error fires; no throw)
    link.feed_line('{"ev":"id","fw":"phase8b-rp2040 v1.2.2","pcb":"revD","rid":1,'
                   '"uid":"X","build":"bench","cfg":"c","fi1":1}')
    check(link.fw_identity()["fi1"] is True, "FI-1 bench image flagged")
    # malformed identity fields must never throw (additive-parser contract)
    link.feed_line('{"ev":"id","fw":123,"rid":"one","fi1":"yes","uid":null}')
    check(link.fw_identity() is not None, "malformed id line sanitized, not thrown")

    print(f"\n{checks['n'] - checks['fail']}/{checks['n']} checks passed"
          + ("  <<< FAILURES" if checks["fail"] else ""))
    sys.exit(1 if checks["fail"] else 0)
