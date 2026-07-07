"""Bench tests for the Phase 8 runtime instrumentation (2026-06-09 audit ideas):
  #10 flight_recorder.py  — fixed-size ring buffer + dump-on-fault
  #11 controller_io.ShadowIO — shadow mode drives NOTHING (records would-be commands)
  #15 cam_telemetry.py    — per-cycle interval extraction + drift alarm

These three modules are OBSERVE-ONLY: they must never drive a relay, never block or
slow the control loop, and never raise into the control path. The tests prove:
  - ring bounds: append is O(1)-bounded to capacity, newest kept, oldest evicted
  - dump-on-fault: a fault flushes a readable, bounded JSON timeline to disk
  - kill-switch: a disabled recorder is an inert no-op (nothing allocated/written)
  - fail-safe: record()/dump() swallow their own exceptions
  - SHADOW: ShadowIO records every FSM output command but NEVER reaches the real io,
    and hard-holds the real ARM LOW — impossible to run live through it
  - telemetry: intervals computed from event timestamps, baseline + drift alarm,
    and the whole chain wired through the daemon's sim self-test with a recorder

Run with:
    py -3 tests/test_flight_recorder.py
(also importable/collectable by pytest: failures call sys.exit(1)).
"""

import json
import logging
import os
import sys
import tempfile

# Make lane_node modules importable when running from anywhere
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lane_node')))

from flight_recorder import (FlightRecorder, NULL_RECORDER, DISABLE_ENV,
                             DEFAULT_CAPACITY, _enabled_from_env)
from cam_telemetry import (CamTelemetry, DISABLE_ENV as CAM_DISABLE_ENV,
                          DRIFT_ALARM_DISABLE_ENV, MIN_SAMPLES_FOR_ALARM)
from controller_io import ShadowIO, MachineIO, RecordingIO


checks = {"n": 0, "fail": 0}


def check(cond, msg):
    checks["n"] += 1
    if cond:
        print(f"  ok:   {msg}")
    else:
        checks["fail"] += 1
        print(f"  FAIL: {msg}")


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []
    def emit(self, record):
        self.records.append(record)
    def msgs(self, level=logging.WARNING):
        return [r.getMessage() for r in self.records if r.levelno >= level]
    def clear(self):
        self.records[:] = []


def no_tmp_left(_d):
    """True if no half-written .tmp dump file remains (atomic replace worked)."""
    return not any(n.endswith(".tmp") for n in os.listdir(_d))


# ---------------------------------------------------------------------------
# [A] Ring buffer bounds + O(1) append semantics
# ---------------------------------------------------------------------------
print("[A] flight recorder ring bounds")
clk = {"t": 0.0}
def now():
    return clk["t"]

d = tempfile.mkdtemp(prefix="fr_test_")
fr = FlightRecorder(21, capacity=10, dump_dir=d, now=now, enabled=True)
for i in range(100):
    clk["t"] = float(i)
    fr.record("out", "S", i % 2 == 0)
snap = fr.snapshot()
check(len(snap) == 10, f"ring is bounded to capacity (got {len(snap)})")
check(snap[0][0] == 90.0 and snap[-1][0] == 99.0, "oldest evicted, newest 10 kept (FIFO)")
check(all(len(e) == 4 for e in snap), "every entry is a 4-tuple (t, kind, name, value)")
check(snap[-1] == (99.0, "out", "S", False), f"newest entry intact: {snap[-1]}")

# capacity guards: zero/negative -> default
fr_def = FlightRecorder(21, capacity=0, dump_dir=d, enabled=True)
check(fr_def.capacity == DEFAULT_CAPACITY, "non-positive capacity falls back to default")


# ---------------------------------------------------------------------------
# [B] Dump-on-fault: readable, bounded JSON file with context
# ---------------------------------------------------------------------------
print("[B] dump-on-fault")
clk["t"] = 0.0
fr = FlightRecorder(22, capacity=2000, dump_dir=d, now=now, enabled=True)
for i in range(5):
    clk["t"] = float(i)
    fr.record("state", "RUNTHROUGH" if i else "READY", "prev")
fr.record("fault", "motion_timeout", "RUNTHROUGH > 8.0s")
path = fr.dump(reason="fsm_fault", extra={"fsm_state": "FAULT", "fw_fault": "motion_timeout"})
check(path is not None and os.path.exists(path), "dump() wrote a file")
check(os.path.basename(path).startswith("blackbox-L22-") and path.endswith(".json"),
      "dump filename is blackbox-L<lane>-<ts>-<reason>.json")
with open(path, encoding="utf-8") as f:
    doc = json.load(f)
check(doc["lane"] == 22 and doc["reason"] == "fsm_fault", "dump payload has lane + reason")
check(doc["event_count"] == 6 and len(doc["events"]) == 6, "all ring events serialized")
check(doc["events"][-1] == {"t": 4.0, "kind": "fault", "name": "motion_timeout",
                            "value": "RUNTHROUGH > 8.0s"}, "fault event present + ordered")
check(doc["context"]["fsm_state"] == "FAULT" and doc["context"]["fw_fault"] == "motion_timeout",
      "context dict carried into the dump")
check(no_tmp_left(d), "dump leaves no .tmp turd (atomic replace)")

# dump is bounded to capacity even after huge traffic
clk["t"] = 0.0
fr2 = FlightRecorder(23, capacity=50, dump_dir=d, now=now, enabled=True)
for i in range(10000):
    fr2.record("out", "T", i)
p2 = fr2.dump(reason="bound")
with open(p2, encoding="utf-8") as f:
    doc2 = json.load(f)
check(doc2["event_count"] == 50, f"dump bounded to capacity after 10k records (got {doc2['event_count']})")


# ---------------------------------------------------------------------------
# [C] Kill-switch + fail-safety (must never raise into the control path)
# ---------------------------------------------------------------------------
print("[C] kill-switch + fail-safety")
fr_off = FlightRecorder(24, dump_dir=d, enabled=False)
fr_off.record("out", "S", True)
check(fr_off.snapshot() == [], "disabled recorder records nothing")
check(fr_off.dump(reason="x") is None, "disabled recorder dump() is a no-op (None)")

# env kill-switch parsing
for val, exp in [("0", False), ("false", False), ("off", False), ("", False),
                 ("1", True), ("true", True), ("yes", True)]:
    os.environ[DISABLE_ENV] = val
    check(_enabled_from_env() is exp, f"env {DISABLE_ENV}={val!r} -> enabled={exp}")
os.environ.pop(DISABLE_ENV, None)
check(_enabled_from_env() is True, "absent env -> default ON")

# record() with an unwritable dump dir / bad value must not raise
fr_bad = FlightRecorder(25, dump_dir="/this/does/not/exist/and/is/unwritable\0", now=now, enabled=True)
fr_bad.record("out", "S", object())                 # weird value
got = fr_bad.dump(reason="bad")                       # bad dir -> None, no raise
check(got is None, "dump() to an unwritable dir returns None, never raises")

# a recorder whose clock blows up still doesn't propagate
def boom():
    raise RuntimeError("clock exploded")
fr_clk = FlightRecorder(26, dump_dir=d, now=boom, enabled=True)
try:
    fr_clk.record("out", "S", True)                   # _now() raises inside record()
    check(True, "record() swallows an exploding clock (no raise)")
except Exception:
    check(False, "record() swallows an exploding clock (no raise)")

# NULL_RECORDER is a safe inert shared object
NULL_RECORDER.record("out", "S", True)
check(NULL_RECORDER.snapshot() == [] and NULL_RECORDER.dump() is None and NULL_RECORDER.enabled is False,
      "NULL_RECORDER is an inert no-op")

# dump retention prune (max_dumps)
dd = tempfile.mkdtemp(prefix="fr_prune_")
frp = FlightRecorder(27, capacity=4, dump_dir=dd, now=now, enabled=True, max_dumps=3)
for i in range(6):
    frp.record("out", "S", i)
    frp.dump(reason=f"d{i}")
kept = [n for n in os.listdir(dd) if n.startswith("blackbox-L27-") and n.endswith(".json")]
check(len(kept) <= 3, f"dump retention pruned to max_dumps (got {len(kept)})")


# ---------------------------------------------------------------------------
# [D] SHADOW MODE drives NOTHING (the safety-critical property)
# ---------------------------------------------------------------------------
print("[D] shadow mode drives nothing")


class FakeIO:
    """A stand-in 'real' io that LOUDLY records any output / arm that reaches it —
    so the test can assert the shadow wrapper NEVER lets a command through to it.
    Provides realistic inputs for the FSM."""
    def __init__(self):
        self.lane = 21
        self.recorder = NULL_RECORDER
        self.real_outputs = []     # any output that leaked to the real hardware
        self.real_arms = []        # every arm() the wrapper forwarded
        self.kicks = 0
        self.grippers = 0
        self.gp = True
        self.bs = False
        self.interlock = True
        self.slow = {}
        self._t = 100.0
    # OUTPUTS — if any of these is ever called, shadow LEAKED
    def set_sweep(self, on): self.real_outputs.append(("sweep", on))
    def set_table(self, on): self.real_outputs.append(("table", on))
    def set_spot(self, on):  self.real_outputs.append(("spot", on))
    def set_light(self, n, on): self.real_outputs.append(("light", n, on))
    def set_pin_lamps(self, m): self.real_outputs.append(("pin_lamps", m))
    def arm(self, on): self.real_arms.append(bool(on))
    # INPUTS / housekeeping — these SHOULD be delegated
    def read_grippers(self): return self.grippers
    def gp_closed(self): return self.gp
    def bs_closed(self): return self.bs
    def read_input(self, n): return bool(self.slow.get(n, False))
    def interlock_ok(self): return self.interlock
    def watchdog_kick(self): self.kicks += 1
    def now(self): return self._t
    def log(self, m): pass


real = FakeIO()
sh = ShadowIO(real)
check(real.real_arms == [False], "construction forces the real ARM LOW exactly once")

# every FSM output command must be RECORDED but NEVER reach the real io
sh.set_sweep(True)
sh.set_table(True)
sh.set_spot(True)
sh.set_light("strike", True)
sh.set_pin_lamps(0b1010101010)
check(real.real_outputs == [], "NO FSM output ever reaches the real io in shadow mode")
check(sh.would_drive["S"] is True and sh.would_drive["T"] is True and sh.would_drive["SP"] is True,
      "shadow records the motor commands the FSM issued")
check(sh.would_drive["strike"] is True and sh.would_drive["pin_lamps"] == 0b1010101010,
      "shadow records lamp + pin-lamp commands")
check([c[1] for c in sh.commands][:3] == ["S", "T", "SP"], "ordered command stream captured")

# arm(True) from the FSM is recorded as intent but the real ARM stays hard LOW
real.real_arms.clear()
sh.arm(True)
check(sh.armed is True, "shadow records the FSM's ARM intent")
check(real.real_arms == [False], "arm(True) STILL forces the real ARM LOW (hard-disarmed)")
sh.arm(False)
check(real.real_arms == [False, False], "every arm() call re-forces the real ARM LOW")

# inputs + watchdog are delegated to the real machine
real.grippers = 0b0000000101
real.interlock = False
check(sh.read_grippers() == 0b0000000101, "read_grippers delegates to the real machine")
check(sh.interlock_ok() is False, "interlock_ok delegates to the real machine")
sh.watchdog_kick()
check(real.kicks == 1, "watchdog_kick delegates (the Pi is alive, just not moving)")
check(sh.now() == 100.0, "now() delegates to the real clock")

# Shadow drives the FSM through a full strike cycle with ZERO real outputs.
print("[D2] shadow: full FSM cycle, zero real outputs")
from cycle_control_8270 import CycleController, State, Ball, Cycle, TIME_DELAY_S

real2 = FakeIO()
shio = ShadowIO(real2)
fsm = CycleController(21, shio)
fsm.power_restore()
fsm.first_ball_zero()
check(fsm.state is State.READY, "FSM reaches READY under ShadowIO")
real2.grippers = 0                              # strike
fsm.on_ball()
check(fsm.state is State.SWEEP_TO_GUARD and shio.would_drive.get("S") is True,
      "ball -> sweep COMMAND recorded (not driven)")
fsm.cam_SB_guard()
real2._t += TIME_DELAY_S + 0.1
fsm.poll()
fsm.cam_TA2_runthrough()
check(fsm.cycle is Cycle.STRIKE, "strike classified under shadow")
fsm.cam_SA_runthrough()
real2.bs = True
fsm.bin_full()
fsm.cam_TA1_zero()
check(fsm.state is State.READY and fsm.ball is Ball.FIRST, "full cycle completes under shadow")
check(real2.real_outputs == [], "ENTIRE shadow cycle drove ZERO real outputs")
check(all(a is False for a in real2.real_arms), "real ARM never went HIGH for the whole cycle")
check(len(shio.commands) > 0, "shadow captured a non-empty would-be command stream")


# ---------------------------------------------------------------------------
# [E] cam-timing telemetry: interval extraction + baseline + drift alarm
# ---------------------------------------------------------------------------
print("[E] cam-timing telemetry")
camlog = LogCapture()
_cl = logging.getLogger("cam_telemetry")
_cl.addHandler(camlog)
_cl.setLevel(logging.DEBUG)
_cl.propagate = False

tel = CamTelemetry(31, enabled=True)
# one nominal cycle
t = 0.0
tel.on_event("ball", t)
tel.on_event("cam:SB", t + 0.6)
tel.on_event("table_start", t + 3.7)
tel.on_event("cam:TA2", t + 4.9)
tel.on_event("cam:SA", t + 5.8)
tel.on_event("cam:TA1", t + 7.1)
durs = tel.end_cycle()
check(abs(durs["ss_to_guard"] - 0.6) < 1e-6, "ss_to_guard interval = SB - ball")
check(abs(durs["ta2_to_sa"] - 0.9) < 1e-6, "ta2_to_sa interval = SA - TA2")
check("bs_to_ta1zero" not in durs, "interval with a missing endpoint is simply absent (no error)")

# duplicate/out-of-order edges must not corrupt the first-seen interval
tel2 = CamTelemetry(31, enabled=True)
tel2.on_event("ball", 0.0)
tel2.on_event("ball", 0.5)          # duplicate START — first wins
tel2.on_event("cam:SB", 0.6)
tel2.on_event("cam:SB", 0.9)        # duplicate END — first wins
d2 = tel2.end_cycle()
check(abs(d2["ss_to_guard"] - 0.6) < 1e-6, "duplicate edges: first start + first end win")

# build a baseline, then a clear drift must alarm
tel3 = CamTelemetry(31, enabled=True, drift_sigma=4.0)
camlog.clear()
base_t = 0.0
for _ in range(MIN_SAMPLES_FOR_ALARM + 20):
    tel3.on_event("ball", base_t)
    tel3.on_event("cam:SB", base_t + 0.60 + (0.001 if _ % 2 else -0.001))  # ~0.6s, tiny jitter
    tel3.end_cycle()
    base_t += 20.0
check(not any("DRIFT" in m for m in camlog.msgs()), "stable timing does NOT alarm")
bl = tel3.baselines()
check(bl["ss_to_guard"]["n"] == MIN_SAMPLES_FOR_ALARM + 20, "baseline accumulated all samples")
check(abs(bl["ss_to_guard"]["mean"] - 0.60) < 0.01, "baseline mean tracks the nominal timing")

camlog.clear()
tel3.on_event("ball", base_t)
tel3.on_event("cam:SB", base_t + 1.20)     # 2x nominal: a belt/pivot drift
tel3.end_cycle()
check(any("DRIFT" in m and "ss_to_guard" in m for m in camlog.msgs()),
      "a large week-over-week drift raises a DRIFT alarm")

# drift alarm respects its kill-switch
os.environ[DRIFT_ALARM_DISABLE_ENV] = "0"
tel4 = CamTelemetry(31, enabled=True, drift_sigma=4.0)
for _ in range(MIN_SAMPLES_FOR_ALARM + 5):
    tel4.on_event("ball", 0.0); tel4.on_event("cam:SB", 0.60); tel4.end_cycle()
camlog.clear()
tel4.on_event("ball", 0.0); tel4.on_event("cam:SB", 5.0); tel4.end_cycle()   # huge drift
check(not any("DRIFT" in m for m in camlog.msgs()), "alarm kill-switch silences drift WARNINGs")
os.environ.pop(DRIFT_ALARM_DISABLE_ENV, None)

# telemetry kill-switch -> fully inert
os.environ[CAM_DISABLE_ENV] = "0"
tel_off = CamTelemetry(31)
tel_off.on_event("ball", 0.0); tel_off.on_event("cam:SB", 0.6)
check(tel_off.end_cycle() == {}, "disabled telemetry produces no intervals")
check(all(v["n"] == 0 for v in tel_off.baselines().values()), "disabled telemetry has empty baselines")
os.environ.pop(CAM_DISABLE_ENV, None)

# telemetry never raises into the caller (bad sink)
def bad_sink(*a, **k):
    raise RuntimeError("sink blew up")
tel_sink = CamTelemetry(31, enabled=True, sink=bad_sink)
tel_sink.on_event("ball", 0.0); tel_sink.on_event("cam:SB", 0.6)
try:
    tel_sink.end_cycle()
    check(True, "a raising sink is swallowed (telemetry never breaks the loop)")
except Exception:
    check(False, "a raising sink is swallowed (telemetry never breaks the loop)")


# ---------------------------------------------------------------------------
# [F] end-to-end: recorder + telemetry wired through the daemon sim, observe-only
# ---------------------------------------------------------------------------
print("[F] daemon integration (recorder + telemetry, observe-only)")
import controller_daemon as cd

# recorder dumps to a temp dir; force telemetry alarms quiet for the run
runlog = LogCapture()
logging.getLogger("flight_recorder").addHandler(runlog)
logging.getLogger("flight_recorder").setLevel(logging.INFO)

bc = cd.BoardController(cd.BoardConfig(21, 1, "sim", 0, 0), sim=True)
bc.recorder._dump_dir = tempfile.mkdtemp(prefix="fr_daemon_")
check(bc.recorder.enabled, "daemon builds an enabled flight recorder by default")
check(bc.telemetry.enabled, "daemon builds enabled cam telemetry by default")
check(bc.shadow is False, "daemon is NOT in shadow mode by default (env unset)")

# drive a full strike cycle through tick() and confirm the recorder captured outputs
bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
bc.io.slow["PBZ"] = True; bc.tick(); bc.io.slow["PBZ"] = False
bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()
bc.io.grippers = 0
bc.link.feed_line('{"ev":"ball","src":"L"}'); bc.tick()   # READY -> SWEEP_TO_GUARD (sweep ON)
check(bc.fsm.state.value == "sweep_to_guard", "ball started a cycle (setup)")
snap = bc.recorder.snapshot()
kinds = {e[1] for e in snap}
check("out" in kinds, "recorder captured relay/lamp OUTPUT changes from the cycle")
check("state" in kinds, "recorder captured FSM STATE transitions")
check(any(e[1] == "out" and e[2] == "S" and e[3] is True for e in snap),
      "the sweep energize (RUN S) is in the black box")

# force a FAULT (stuck motion: no SB cam ever arrives) and confirm a dump file lands.
# In SWEEP_TO_GUARD the MAX_MOTION_S backstop in poll() latches FAULT.
from cycle_control_8270 import MAX_MOTION_S
bc.io.advance(MAX_MOTION_S + 1.0)
bc.link.feed_line('{"ev":"hb","ok":1}'); bc.tick()       # poll backstop -> FAULT -> observe() dumps
check(bc.fsm.state.value == "fault", "stuck motion faults (setup)")
bc.recorder.flush()   # daemon dumps via dump_async (review #21/#54) — join the writer first
dumps = [n for n in os.listdir(bc.recorder._dump_dir) if "fsm_fault" in n]
check(len(dumps) >= 1, "FSM FAULT triggered a flight-recorder dump file")
with open(os.path.join(bc.recorder._dump_dir, dumps[0]), encoding="utf-8") as f:
    fdoc = json.load(f)
check(fdoc["context"]["fsm_state"] == "fault", "fault dump context records the FSM state")

# telemetry recorded at least the ss_to_guard interval for the cycle we ran
# (READY was reached after the first PBZ; a full cycle interval needs a completed
# cycle — here we just assert the telemetry object advanced without error)
check(isinstance(bc.telemetry.baselines(), dict), "telemetry baselines queryable after daemon ticks")

# SHADOW gate: a BoardController with shadow=True wraps io in ShadowIO and drives nothing
bc_sh = cd.BoardController(cd.BoardConfig(21, 1, "sim", 0, 0), sim=True, shadow=True)
check(isinstance(bc_sh.io, ShadowIO), "shadow=True wraps the io in ShadowIO")
bc_sh.link.feed_line('{"ev":"hb","ok":1}'); bc_sh.tick()
bc_sh.io.slow = {}                                  # ShadowIO delegates slow to underlying RecordingIO
# In shadow, the underlying RecordingIO must show NO motor outputs driven on:
under = bc_sh.io._io
check(under.outputs.get("sweep") in (None, False), "shadow daemon: underlying sweep never driven ON")


print(f"\n{checks['n'] - checks['fail']}/{checks['n']} checks passed"
      + ("  <<< FAILURES" if checks["fail"] else ""))
sys.exit(1 if checks["fail"] else 0)
