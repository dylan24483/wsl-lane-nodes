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
                 {"ev":"hb","ok":1,"flt":"","up":..}      {"ev":"rp_ok","v":1,..}
                 {"ev":"boot",..}  {"ev":"flt","code":"motion_timeout","m":"S",..}
  Pi -> RP2040:  RUN <m> | STOP <m|*> | CLEAR | PING

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

        # outbound record (always captured; also written to serial if present)
        self.sent = []

        # state guarded by _lock
        self._lock = threading.Lock()
        self._sc_danger = False
        self._tb_danger = False
        self._rp_ok = False
        self._last_hb = 0.0
        self._fault = ""

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
        self._stop = False
        self._reader = None

    def now(self):
        return self._now()

    # ---- outbound commands -------------------------------------------------
    def _send(self, line):
        self.sent.append(line)
        if self._ser is not None:
            try:
                self._ser.write((line + "\n").encode())
            except Exception as e:  # never let a comms hiccup crash the caller
                log.warning("RP2040 send failed (%s): %s", line, e)

    def run(self, motor):   self._send(f"RUN {motor}")
    def stop(self, motor):  self._send(f"STOP {motor}")
    def stop_all(self):     self._send("STOP *")
    def clear(self):        self._send("CLEAR")
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
            if self.on_health:
                self.on_health(ev)

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
        """True only if the RP2040 is heartbeating, reports rail-permit OK, AND has no
        latched fault. Any flt (even without a paired rp_ok:0) => not healthy."""
        with self._lock:
            alive = bool(self._last_hb) and (self.now() - self._last_hb) <= self._hb_timeout
            return alive and self._rp_ok and not self._fault

    def fault(self):
        with self._lock:
            return self._fault

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
            self._rx += data
            while b"\n" in self._rx:
                line, self._rx = self._rx.split(b"\n", 1)
                self.feed_line(line.decode("ascii", errors="replace"))

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
    check(link.sent == ["CLEAR", "PING", "STOP *"], "CLEAR / PING / STOP * formatting")

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

    print(f"\n{checks['n'] - checks['fail']}/{checks['n']} checks passed"
          + ("  <<< FAILURES" if checks["fail"] else ""))
    sys.exit(1 if checks["fail"] else 0)
