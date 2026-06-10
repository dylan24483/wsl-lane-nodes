"""Bench tests for the Pi side of the RP2040 link (lane_node/rp2040_link.py).

Covers the 2026-06-10 audit items (P3 Pi-side, firmware v0.2.0 contract in
firmware/rp2040/README.md "Pi-side integration"):
  - feed_line fuzz: truncated JSON, garbage/binary bytes, duplicate events,
    unknown fields tolerated; the v0.2.0 additive fields MUST parse
  - hb "in"/"run" mask consumption + SC/TB danger-flag resync
  - reboot detection via hb "up" regression (and a mid-session boot event)
  - bounded RX buffer (babbling no-newline UART), bounded `sent` history,
    consecutive send-failure health gate
  - boot "maxrun_ms" storage + maxrun_ok()
  - hb "drp" increases logged as warnings

Backward compat is pinned: v0.1.0 firmware lines (no in/run/drp/maxrun_ms)
must keep working unchanged.

Run with:
    py -3 tests/test_rp2040_link.py
"""

import logging
import os
import random
import sys

# Make lane_node modules importable when running from anywhere
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lane_node')))

from rp2040_link import (RP2040Link, dispatch_cam, RX_MAX, SENT_MAXLEN,
                         SEND_FAIL_LIMIT, REBOOT_FAULT, HB_IN_BITS, HB_RUN_BITS)


checks = {"n": 0, "fail": 0}


def check(cond, msg):
    checks["n"] += 1
    # ascii-sanitize: fuzz payloads include bytes a cp1252 Windows console can't print
    msg = msg.encode("ascii", errors="backslashreplace").decode("ascii")
    if cond:
        print(f"  ok:   {msg}")
    else:
        checks["fail"] += 1
        print(f"  FAIL: {msg}")


# deterministic clock so health/timeout checks never flake
clk = {"t": 1000.0}
def fake_now():
    return clk["t"]


def mklink(**kw):
    kw.setdefault("now", fake_now)
    kw.setdefault("hb_timeout", 1.0)
    return RP2040Link(**kw)


class LogCapture(logging.Handler):
    """Collects records from the rp2040_link logger so warning/error
    side-effects (drp increases, resyncs, reboots) can be asserted."""
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def msgs(self, level=logging.WARNING):
        return [r.getMessage() for r in self.records if r.levelno >= level]

    def clear(self):
        self.records[:] = []


cap = LogCapture()
_linklog = logging.getLogger("rp2040_link")
_linklog.addHandler(cap)
_linklog.setLevel(logging.DEBUG)
_linklog.propagate = False          # keep fuzz noise off the console


class StubFSM:
    """Counts dispatch calls; the real FSM is exercised by rp2040_link's own
    host self-test — here we only need the queue/dispatch plumbing."""
    def __init__(self):
        self.calls = []
    def cam_SA_runthrough(self): self.calls.append("SA_rt")
    def cam_SA_zero(self):       self.calls.append("SA_z")
    def cam_SB_guard(self):      self.calls.append("SB")
    def cam_TA1_delayreset(self): self.calls.append("TA1_dr")
    def cam_TA1_zero(self):      self.calls.append("TA1_z")
    def cam_TA2_runthrough(self): self.calls.append("TA2")
    def on_ball(self):           self.calls.append("ball")


class FlakySerial:
    """write() raises while .fail is True; read() always idles."""
    def __init__(self):
        self.fail = False
        self.writes = []
    def write(self, b):
        if self.fail:
            raise OSError("EIO: simulated UART write failure")
        self.writes.append(b)
    def read(self, n):
        return b""
    def close(self):
        pass


SC_BIT = 1 << HB_IN_BITS.index("SC")    # bit 2
TB_BIT = 1 << HB_IN_BITS.index("TB")    # bit 5

print("== rp2040_link bench test (audit P3 Pi-side) ==")

# [A] v0.1.0 backward compat — old-format lines keep working unchanged ---------
print("[A] v0.1.0 backward compat")
link = mklink()
link.feed_line('{"ev":"boot","fw":"phase8b-rp2040 v0.1.0","wdt_reset":0,"rp_ok":0}')
check(link.rp_ok() is False and link.is_alive(), "v0.1.0 boot parses (rp_ok False, alive)")
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":10}')
check(link.health_ok(), "v0.1.0 hb (no in/run/drp) -> healthy")
check(link.input_levels() is None, "no in-mask ever heard -> input_levels() None")
check(link.running_motors() is None, "no run-mask ever heard -> running_motors() None")
check(link.maxrun_ms() is None, "v0.1.0 boot advertises no maxrun_ms")
check(link.maxrun_ok() is True, "maxrun_ok() True when unknown (v0.1.0 must still arm)")
link.feed_line('{"ev":"cam","id":"SC","e":"f"}')
link.feed_line('{"ev":"cam","id":"TB","e":"f"}')
check(not link.interlock_ok(), "edge-tracked SC+TB veto still works without masks")
fsm = StubFSM()
link.feed_line('{"ev":"cam","id":"SB","e":"f"}')
link.feed_line('{"ev":"ball","src":"L"}')
check(link.apply_events(fsm) == 2 and fsm.calls == ["SB", "ball"],
      "v0.1.0 cam/ball dispatch unchanged")

# [B] v0.2.0 additive fields MUST parse (README examples, verbatim) ------------
print("[B] v0.2.0 lines parse")
link = mklink()
link.feed_line('{"ev":"boot","fw":"phase8b-rp2040 v0.2.0","wdt_reset":0,"rp_ok":0,"maxrun_ms":8000,"dbg":0}')
check(link.maxrun_ms() == 8000, "boot maxrun_ms stored")
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":12500,"drp":0,"in":0,"run":0}')
check(link.health_ok(), "v0.2.0 hb with drp/in/run -> healthy")
check(link.input_levels() == {n: False for n in HB_IN_BITS}, "in:0 -> all levels deasserted")
check(link.running_motors() == (), "run:0 -> no motors running")
link.feed_line('{"ev":"flt","code":"chatter","m":"SA","t":20000}')
check(link.fault() == "chatter" and not link.health_ok(), "v0.2.0 chatter fault parses + trips")
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":12750,"drp":0,"in":0,"run":0}')
check(link.health_ok(), "clean hb clears the fault again")
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":13000,"drp":0,"in":37,"run":5}')
lv = link.input_levels()
check(lv["SA"] and lv["SC"] and lv["TB"] and not lv["SB"], "in-mask 37 decodes per HB_IN_BITS")
check(link.running_motors() == ("S", "SP"), "run-mask 5 decodes per HB_RUN_BITS (S,T,SP,M2,M1,BE,M)")
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":13250,"drp":0,"in":0,"run":0,"zzz":42,"new_field":[1,2]}')
check(link.health_ok(), "unknown extra fields tolerated (future-additive)")

# [C] feed_line fuzz -----------------------------------------------------------
print("[C] fuzz")
link = mklink()
link.feed_line('{"ev":"hb","ok":1,"up":100}')
for bad in (
    '{"ev":"hb","ok"',                    # truncated JSON
    '{"ev":"hb","ok":1,"up":',            # truncated mid-value
    'not json at all',
    '\x00\x01\x02��',           # binary garbage post-decode
    '[1,2,3]', '42', '"string"', 'null',  # valid JSON, not a dict
    '{}', '{"no_ev":1}',                  # dict without ev
    '{"ev":"wat","x":1}',                 # unknown event kind
    '{"ev":"cam"}', '{"ev":"cam","id":"NOPE","e":"f"}',   # malformed cam
    '{"ev":"hb","ok":1,"in":"junk","run":[],"drp":null,"up":true}',  # wrong-typed v0.2.0 fields
    '{"ev":"boot","maxrun_ms":"soon"}',   # wrong-typed maxrun_ms
):
    try:
        link.feed_line(bad)
        check(True, f"tolerated: {bad[:40]!r}")
    except Exception as e:
        check(False, f"feed_line raised on {bad[:40]!r}: {e}")
check(link.maxrun_ms() is None, "wrong-typed maxrun_ms not stored")
random.seed(8270)
try:
    for _ in range(500):
        chunk = bytes(random.randrange(256) for _ in range(random.randrange(1, 120)))
        if random.random() < 0.3:
            chunk += b"\n"
        link._ingest(chunk)
    check(True, "500 random binary chunks ingested without raising")
except Exception as e:
    check(False, f"random-byte ingest raised: {e}")
link._ingest(b'\n{"ev":"hb","ok":1,"flt":"","up":40000}\n')   # newline flushes fuzz residue
check(link.health_ok(), "still functional after fuzz (clean hb -> healthy)")
# duplicate events are queued as-is (dedup is the FSM state-guard's job)
fsm = StubFSM()
link.feed_line('{"ev":"cam","id":"TA2","e":"f"}')
link.feed_line('{"ev":"cam","id":"TA2","e":"f"}')
link.feed_line('{"ev":"ball","src":"L"}')
link.feed_line('{"ev":"ball","src":"L"}')
check(link.apply_events(fsm) == 4 and fsm.calls == ["TA2", "TA2", "ball", "ball"],
      "duplicate cam/ball events pass through without crash")

# [D] hb in-mask resyncs the SC/TB interlock echo -------------------------------
print("[D] hb mask resync")
link = mklink()
link.feed_line('{"ev":"cam","id":"SC","e":"f"}')
link.feed_line('{"ev":"cam","id":"TB","e":"f"}')
check(not link.interlock_ok(), "(setup) edge-latched SC+TB veto")
# the TB 'release' line was DROPPED on the wire; the next hb carries the truth
cap.clear()
link.feed_line('{"ev":"hb","ok":1,"up":500,"in":%d,"run":0}' % SC_BIT)
check(link.interlock_ok(), "hb in-mask heals a dropped TB release (veto lifted)")
check(any("resync" in m for m in cap.msgs()), "resync drift is logged as a warning")
cap.clear()
link.feed_line('{"ev":"hb","ok":1,"up":750,"in":%d,"run":0}' % SC_BIT)
check(not any("resync" in m for m in cap.msgs()), "agreeing hb does NOT log (no 4 Hz spam)")
# boot-in-window: no edges ever seen, mask alone must set the danger flags
link = mklink()
link.feed_line('{"ev":"hb","ok":1,"up":250,"in":%d,"run":0}' % (SC_BIT | TB_BIT))
check(not link.interlock_ok(), "mask alone (boot-in-window) sets SC+TB veto")
link.feed_line('{"ev":"hb","ok":1,"up":500}')   # v0.1.0-style hb: no "in" key
check(not link.interlock_ok(), "hb WITHOUT in-mask leaves flags untouched")
link.feed_line('{"ev":"hb","ok":1,"up":750,"in":0,"run":0}')
check(link.interlock_ok(), "in:0 clears both danger flags")
# trip_edge='r' inverts the level->danger mapping consistently with cam edges
link = mklink(trip_edge="r")
link.feed_line('{"ev":"hb","ok":1,"up":250,"in":0,"run":0}')
check(not link.interlock_ok(), "trip_edge='r': deasserted levels == danger (inverted)")
link.feed_line('{"ev":"hb","ok":1,"up":500,"in":%d,"run":0}' % (SC_BIT | TB_BIT))
check(link.interlock_ok(), "trip_edge='r': asserted levels == clear")

# [E] reboot detection ----------------------------------------------------------
print("[E] uptime regression / reboot")
link = mklink()
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":10000}')
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":10250}')
check(link.health_ok(), "(setup) healthy with increasing uptime")
cap.clear()
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":50}')      # up went BACKWARDS
check(not link.health_ok(), "up regression -> NOT healthy (despite ok:1)")
check(link.fault() == REBOOT_FAULT, "up regression latches the synthetic fw_reboot fault")
check(link.rp_ok() is False, "up regression clears rp_ok")
check(any("REBOOTED" in m for m in cap.msgs(logging.ERROR)), "reboot is logged LOUDLY (error)")
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":300}')     # next clean hb
check(link.health_ok(), "recovery: next clean hb clears the synthetic fault")
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":550}')
check(link.health_ok(), "no repeated trip on normal post-reboot uptime")
# a mid-session boot EVENT takes the same trip (even if it carried rp_ok:1)
cap.clear()
link.feed_line('{"ev":"boot","fw":"x","wdt_reset":1,"rp_ok":1,"maxrun_ms":8000}')
check(not link.health_ok() and link.fault() == REBOOT_FAULT,
      "mid-session boot event -> same fw_reboot safety trip")
check(any("watchdog" in m for m in cap.msgs(logging.ERROR)), "wdt_reset:1 logged as error")
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":200}')
check(link.health_ok(), "recovery after boot event via clean hb")
# first boot of a session is NOT a trip (no prior heartbeats)
link = mklink()
link.feed_line('{"ev":"boot","fw":"x","wdt_reset":0,"rp_ok":0,"maxrun_ms":8000}')
check(link.fault() == "", "session-start boot does NOT latch fw_reboot")

# [F] RX buffer bound ------------------------------------------------------------
print("[F] RX bound")
link = mklink()
cap.clear()
link._ingest(b"x" * (RX_MAX + 500))                  # babble, no newline
check(len(link._rx) == 0 and link._rx_discard, "overflowed buffer dropped whole")
for _ in range(50):
    link._ingest(b"y" * 1000)                        # keep babbling
    check_len = len(link._rx)
    if check_len > RX_MAX + 1000:
        break
check(len(link._rx) <= RX_MAX + 1000, "sustained babble stays bounded")
check(len([m for m in cap.msgs() if "overflow" in m]) == 1, "overflow logged once per episode")
link._ingest(b'tail-of-oversized-line\n{"ev":"hb","ok":1,"flt":"","up":60000}\n')
check(link.health_ok(), "post-overflow: partial tail discarded, next full line parses")
link2 = mklink()
link2._ingest(b'{"ev":"hb",')
link2._ingest(b'"ok":1,"up":5}\n')
check(link2.is_alive(), "normal split-across-chunks line still reassembles")

# [G] sent bound + send-failure health gate --------------------------------------
print("[G] sent bound / send failures")
link = mklink()
for i in range(SENT_MAXLEN + 50):
    link.ping()
check(len(link.sent) == SENT_MAXLEN, f"sent history bounded at {SENT_MAXLEN}")
ser = FlakySerial()
link = mklink(serial_obj=ser)
link.feed_line('{"ev":"hb","ok":1,"flt":"","up":100}')
check(link.health_ok(), "(setup) healthy with working serial")
ser.fail = True
for i in range(SEND_FAIL_LIMIT - 1):
    link.run("S")
check(link.health_ok(), f"{SEND_FAIL_LIMIT - 1} consecutive send failures: still healthy")
link.stop("S")
check(not link.health_ok(), f"{SEND_FAIL_LIMIT} consecutive send failures -> NOT healthy")
ser.fail = False
link.stop_all()
check(link.health_ok(), "one successful write resets the failure count -> healthy")
link3 = mklink()                                      # no serial at all (tests/bench)
for i in range(10):
    link3.ping()
link3.feed_line('{"ev":"hb","ok":1,"up":100}')
check(link3.health_ok(), "serial-less link never accrues send failures")

# [H] maxrun_ok -------------------------------------------------------------------
print("[H] maxrun_ok")
link = mklink()
check(link.maxrun_ok() and link.maxrun_ok(99.0), "no boot heard -> True (can't check)")
link.feed_line('{"ev":"boot","fw":"x","wdt_reset":0,"rp_ok":0,"maxrun_ms":8000}')
check(link.maxrun_ok(8.0) is True, "8.0s vs 8000ms ceiling -> OK")
check(link.maxrun_ok(8.5) is False, "8.5s vs 8000ms ceiling -> mismatch")
try:
    from cycle_control_8270 import MAX_MOTION_S
    check(link.maxrun_ok() is (MAX_MOTION_S * 1000.0 <= 8000),
          f"no-arg maxrun_ok() reads FSM MAX_MOTION_S={MAX_MOTION_S}")
except ImportError:
    check(link.maxrun_ok() is True, "FSM module absent -> no-arg maxrun_ok() True")
cap.clear()
link.feed_line('{"ev":"hb","ok":1,"up":100}')         # establish prior life
link.feed_line('{"ev":"boot","fw":"x","wdt_reset":0,"rp_ok":0,"maxrun_ms":5000}')
check(link.maxrun_ms() == 5000 and link.maxrun_ok(8.0) is False,
      "weaker firmware ceiling (5000ms) stored + flagged")
check(any("maxrun" in m for m in cap.msgs(logging.ERROR)),
      "maxrun_ms < FSM MAX_MOTION_S logged as error at boot")

# [I] drp warnings ----------------------------------------------------------------
print("[I] drp warnings")
link = mklink()
cap.clear()
link.feed_line('{"ev":"hb","ok":1,"up":100,"drp":0}')
link.feed_line('{"ev":"hb","ok":1,"up":350,"drp":0}')
check(not any("dropped" in m for m in cap.msgs()), "steady drp -> no warnings")
link.feed_line('{"ev":"hb","ok":1,"up":600,"drp":3}')
check(any("dropped 3 TX" in m for m in cap.msgs()), "drp 0->3 warned with the delta")
cap.clear()
link.feed_line('{"ev":"hb","ok":1,"up":850,"drp":3}')
check(not any("dropped" in m for m in cap.msgs()), "unchanged drp does not re-warn")
link.feed_line('{"ev":"hb","ok":1,"up":1100}')        # v0.1.0-style hb mid-stream
link.feed_line('{"ev":"hb","ok":1,"up":1350,"drp":4}')
check(any("dropped 1 TX" in m for m in cap.msgs()), "drp tracking survives a no-drp hb")

print(f"\n{checks['n'] - checks['fail']}/{checks['n']} checks passed"
      + ("  <<< FAILURES" if checks["fail"] else ""))
sys.exit(1 if checks["fail"] else 0)
