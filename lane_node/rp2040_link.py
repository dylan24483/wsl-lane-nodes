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
  Pi -> RP2040:  RUN <m> | STOP <m|*> | CLEAR | PING

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

SAFETY: this is the software half. RP2040_OK is a HARDWARE rail line driven by the
firmware; a dead/!ok RP2040 drops the rail in hardware regardless of this module.
Here we additionally surface health so the daemon can fault the FSM + drop ARM.
pyserial is imported lazily so this module loads + tests on any machine.
"""
from __future__ import annotations
import json
import logging
import threading
import time
from collections import deque

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
                 hb_timeout=1.0, trip_edge="f", now=None):
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

        # state guarded by _lock
        self._lock = threading.Lock()
        self._sc_danger = False
        self._tb_danger = False
        self._rp_ok = False
        self._last_hb = 0.0
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

        # queued cam/ball events, drained by apply_events()
        self._evlock = threading.Lock()
        self._events = deque()

        # transport
        if serial_obj is not None:
            self._ser = serial_obj
        elif port is not None:
            import serial  # pyserial, lazy
            self._ser = serial.Serial(port, baud, timeout=0.1)
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
                with self._tx_lock:   # daemon + reader threads both send (v1.1.1)
                    self._ser.write((line + "\n").encode())
            except Exception as e:  # never let a comms hiccup crash the caller
                with self._lock:
                    self._send_fails += 1
                    n = self._send_fails
                log.warning("RP2040 send failed x%d (%s): %s", n, line, e)
            else:
                with self._lock:
                    self._send_fails = 0

    # run/stop/stop_all/clear also track the COMMANDED run-state so the hb "run"
    # mask can be reconciled against it (_reconcile_run). CLEAR mirrors the
    # firmware's motors_all_stop() (main.c handle_line).
    def run(self, motor):
        with self._lock:
            self._cmd_run[motor] = True
        self._send(f"RUN {motor}")

    def stop(self, motor):
        with self._lock:
            self._cmd_run[motor] = False
        self._send(f"STOP {motor}")

    def stop_all(self):
        with self._lock:
            self._cmd_run.clear()
        self._send("STOP *")

    def clear(self):
        with self._lock:
            self._cmd_run.clear()
        self._send("CLEAR")

    def ping(self):         self._send("PING")

    # ---- inbound parsing ---------------------------------------------------
    def feed_line(self, line):
        """Parse one received protocol line. Safe to call from the reader thread."""
        line = line.strip()
        if not line:
            return
        try:
            ev = json.loads(line)
        except ValueError:
            log.debug("RP2040 unparseable line: %r", line)
            return
        if not isinstance(ev, dict):
            return
        self._handle(ev)

    def _handle(self, ev):
        kind = ev.get("ev")
        if kind == "cam":
            cid = ev.get("id")
            trip = (ev.get("e") == self._trip)
            if cid in INTERLOCK_CAMS:
                # Edge tracking kept for immediacy + v0.1.0 firmware; on v0.2.0
                # the hb "in" mask resyncs these every ~250 ms (self-healing).
                with self._lock:
                    if cid == "SC":
                        self._sc_danger = trip
                    else:
                        self._tb_danger = trip
            elif trip and cid in CAM_DISPATCH:
                with self._evlock:
                    self._events.append(("cam", cid))
        elif kind == "ball":
            with self._evlock:
                self._events.append(("ball", ev.get("src")))
        elif kind in ("hb", "boot", "rp_ok", "flt", "ack"):
            notes = []   # (log_fn, msg, args) — emitted AFTER the lock is released
            resends = []  # run-state resync commands — sent AFTER the lock is released
            with self._lock:
                self._last_hb = self.now()
                if kind == "flt":
                    # An explicit firmware fault => NOT healthy, immediately — even if the
                    # paired rp_ok:0 line is delayed or dropped on a lossy UART. Cleared by
                    # the next hb that carries flt="" (i.e. after a CLEAR).
                    self._fault = ev.get("code", "")
                    self._rp_ok = False
                else:
                    if "v" in ev:
                        self._rp_ok = bool(ev["v"])
                    elif "ok" in ev:
                        self._rp_ok = bool(ev["ok"])
                    elif "rp_ok" in ev:
                        self._rp_ok = bool(ev["rp_ok"])
                    if "flt" in ev:
                        self._fault = ev.get("flt", "")
                    if kind == "boot":
                        self._on_boot(ev, notes)
                    elif kind == "hb":
                        self._on_hb(ev, notes, resends)
            for log_fn, msg, args in notes:
                log_fn(msg, *args)
            for line in resends:   # _send takes the lock itself; must run unlocked
                self._send(line)
            if self.on_health:
                self.on_health(ev)

    # ---- v0.2.0 telemetry (helpers called with self._lock HELD; they log via
    # `notes` so no logging handler can ever block under the lock) -------------
    @staticmethod
    def _num(ev, key):
        """ev[key] if it is a real number (bool excluded), else None — additive
        fields from unknown/fuzzed senders must never throw here."""
        v = ev.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        return None

    def _mask_danger(self, mask, bit):
        # hb "in" bits are debounced ASSERTED levels. Map level -> danger flag the
        # same way cam edges do: trip_edge 'f' => asserted == in-window (default,
        # matches the active-low board); 'r' inverts (bench-confirm knob).
        lvl = bool(mask & bit)
        return lvl if self._trip == "f" else not lvl

    def _on_boot(self, ev, notes):
        rebooted = self._last_up is not None    # we had heartbeats before this boot
        self._last_up = None                    # fresh uptime/drp baselines
        self._last_drp = None
        # Fresh firmware = motors all stopped; let the run-mask reconciliation
        # start a fresh episode (it re-sends RUN for anything still commanded).
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

    def _on_hb(self, ev, notes, resends):
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
            self._last_drp = drp
        up = self._num(ev, "up")
        if up is not None:
            if self._last_up is not None and up < self._last_up:
                # Uptime went BACKWARDS => the firmware rebooted and we missed the
                # boot line. Same safety trip as a boot event. Applied LAST so this
                # hb's own ok/flt fields can't mask it. NOTE: firmware up is uint32
                # ms — a wrap at ~49.7 days reads as a regression too; that false
                # trip is in the SAFE direction (nuisance PBZ) and is accepted.
                self._fault = REBOOT_FAULT
                self._rp_ok = False
                notes.append((log.error,
                              "RP2040 uptime regressed %s -> %s ms: firmware REBOOTED "
                              "(boot line missed) — safe-state relatch; operator "
                              "re-arm required", (self._last_up, up)))
            self._last_up = up

    def _reconcile_run(self, mask, notes, resends):
        """Compare the firmware's hb "run" mask against the RUN/STOP state WE
        commanded and heal any desync (finding 38: RUN/STOP have no ACK/CRC —
        a lost STOP deterministically latches motion_timeout at 8 s and drops
        the rail; a lost RUN silently removes the firmware's max-run backstop
        for that motion). Called with self._lock HELD; the corrective command
        lines are appended to `resends` and written AFTER the lock drops.

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
                self._resync_tries[name] = tries + 1
                cmdline = f"RUN {name}" if cmd else f"STOP {name}"
                resends.append(cmdline)
                notes.append((log.warning,
                              "RP2040 run-state MISMATCH for %s: firmware=%s commanded=%s "
                              "(lost/corrupt RUN/STOP line?) — re-sending %r (retry %d/%d)",
                              (name, "running" if fw_running else "stopped",
                               "RUN" if cmd else "STOP", cmdline,
                               tries + 1, RUN_RESYNC_RETRIES)))
            elif tries == RUN_RESYNC_RETRIES:
                self._resync_tries[name] = tries + 1   # log the exhaustion once
                notes.append((log.error,
                              "RP2040 run-state mismatch for %s persists after %d "
                              "re-sends — UART eating lines? run_mismatch() stays "
                              "latched; the firmware max-run backstop may be "
                              "desynced for this motor",
                              (name, RUN_RESYNC_RETRIES)))
        self._run_mismatch = tuple(mismatched)

    # ---- FSM bridge --------------------------------------------------------
    def apply_events(self, controller):
        """Drain queued cam/ball events into the FSM. Call from the daemon's main
        loop only (keeps FSM access single-threaded). Returns the count applied."""
        with self._evlock:
            evs = list(self._events)
            self._events.clear()
        for kind, payload in evs:
            if kind == "cam":
                dispatch_cam(controller, payload)
            elif kind == "ball":
                controller.on_ball()
        return len(evs)

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

    def is_alive(self):
        with self._lock:
            return bool(self._last_hb) and (self.now() - self._last_hb) <= self._hb_timeout

    def health_ok(self):
        """True only if the RP2040 is heartbeating, reports rail-permit OK, has no
        latched fault, AND our serial TX path works. Any flt (even without a paired
        rp_ok:0) => not healthy; >= SEND_FAIL_LIMIT consecutive write failures (our
        RUN/STOP may not be reaching the firmware) => not healthy."""
        with self._lock:
            alive = bool(self._last_hb) and (self.now() - self._last_hb) <= self._hb_timeout
            return (alive and self._rp_ok and not self._fault
                    and self._send_fails < SEND_FAIL_LIMIT)

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

    def v11_posture(self):
        """The firmware's v1.1 enforcement posture from the boot event
        ({"sa","ta1","echo","nrun"}, v1.1.1+ firmware), or None if never
        reported (stock <= v1.1.0 images). Lets cutover tooling verify WHICH
        image is flashed instead of trusting the FW_VERSION string (finding 37)."""
        with self._lock:
            return dict(self._v11) if self._v11 else None

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

    def _read_loop(self):
        while not self._stop:
            try:
                data = self._ser.read(256)
            except Exception as e:
                log.warning("RP2040 serial read error: %s", e)
                time.sleep(0.5)
                continue
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
        if self._ser is not None:
            try:
                self._ser.close()
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
    check(link.is_alive(), "boot counts as a sign of life")
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
    link.feed_line('{"ev":"hb","ok":1}')
    check(link.health_ok(), "(setup) healthy after hb ok:1")
    link.feed_line('{"ev":"flt","code":"motion_timeout","m":"S"}')   # NO paired rp_ok:0
    check(not link.health_ok(), "bare flt event -> NOT healthy")
    check(link.rp_ok() is False, "flt also clears rp_ok")
    link.feed_line('{"ev":"hb","ok":1,"flt":""}')                    # post-CLEAR heartbeat
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

    print(f"\n{checks['n'] - checks['fail']}/{checks['n']} checks passed"
          + ("  <<< FAILURES" if checks["fail"] else ""))
    sys.exit(1 if checks["fail"] else 0)
