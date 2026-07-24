"""test_fw_identity_line.py — firmware v1.2.2 identity line (Codex round-2
R2-6 / R2-13, 2026-07-21): rp2040_link must consume the new additive "id"
line (strap-read PCB revision, Pico unique id, build git-describe + config.h
hash, FI-1 posture) and the hb "rid" field instead of silently ignoring them,
and must promote the identity to a typed 'fw_identity' diag record so the
daemon can persist/alert on board-revision or build mismatches.

Run under pytest or standalone (py -3 tests/test_fw_identity_line.py).
"""
import os
import json
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', 'lane_node')))

from rp2040_link import RP2040Link


ID_LINE = ('{"ev":"id","fw":"phase8b-rp2040 v1.2.3","bn":123,"pcb":"revD","rid":1,'
           '"uid":"E66038B713952A31","build":"10c3a26-dirty","cfg":"aa4ff333",'
           '"fi1":0,"t":1234}')


def mk_link():
    clk = {"t": 1000.0}
    return RP2040Link(now=lambda: clk["t"], hb_timeout=1.0), clk


def modern_hb(up, *, rid=1, bn=123):
    return json.dumps({
        "ev": "hb", "ok": 1, "flt": "", "up": up, "drp": 0,
        "in": 0, "run": 0, "tap": 13, "rd": 0, "ep": 1,
        "v5": 5000, "v5n": 4990, "v5x": 5010,
        "rid": rid, "bn": bn,
    })


def test_identity_none_until_heard():
    link, _ = mk_link()
    assert link.fw_identity() is None
    assert link.pcb_rev_id() is None


def test_id_line_stored_sanitized_and_recorded():
    link, _ = mk_link()
    link.feed_line(ID_LINE)
    ident = link.fw_identity()
    assert ident["fw"] == "phase8b-rp2040 v1.2.3"
    assert ident["bn"] == 123
    assert ident["pcb"] == "revD"
    assert ident["rid"] == 1
    assert ident["uid"] == "E66038B713952A31"
    assert ident["build"] == "10c3a26-dirty"
    assert ident["cfg"] == "aa4ff333"
    assert ident["fi1"] is False
    assert ident["t_fw"] == 1234
    recs = [r for r in link.drain_diag_records() if r["kind"] == "fw_identity"]
    assert len(recs) == 1
    assert recs[0]["pcb"] == "revD"
    assert recs[0]["build"] == "10c3a26-dirty"


def test_hb_rid_field_stored():
    link, _ = mk_link()
    link.feed_line(modern_hb(500, rid=1))
    assert link.pcb_rev_id() == 1
    # 255 = floating straps (rev-B/rev-C board under a rev-D-aware image)
    link.feed_line(modern_hb(750, rid=255))
    assert link.pcb_rev_id() == 255
    # Once modern evidence exists, a v1.2.1-width record is a schema
    # discontinuity: it cannot renew liveness or retain stale RID.
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":1000}')
    assert link.pcb_rev_id() is None
    assert link.health_ok() is False


def test_fi1_bench_image_flagged():
    link, _ = mk_link()
    link.feed_line('{"ev":"id","fw":"phase8b-rp2040 v1.2.3","bn":123,"pcb":"revD",'
                   '"rid":1,"uid":"X","build":"bench","cfg":"c","fi1":1}')
    assert link.fw_identity()["fi1"] is True
    recs = [r for r in link.drain_diag_records() if r["kind"] == "fw_identity"]
    assert recs and recs[0]["fi1"] is True


def test_malformed_id_line_never_throws():
    link, _ = mk_link()
    link.feed_line('{"ev":"id","fw":123,"rid":"one","fi1":"yes","pcb":[1,2]}')
    ident = link.fw_identity()
    assert ident is not None
    assert ident["rid"] is None          # non-numeric rid -> None, not a crash
    link.feed_line('{"ev":"id"}')        # empty identity
    assert link.fw_identity() is not None


def test_identity_does_not_perturb_health():
    link, _ = mk_link()
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":100}')
    assert link.health_ok()
    link.feed_line(ID_LINE)
    assert link.health_ok()              # id line is identity-only


def test_request_identity_sends_id():
    # Round-3 (Codex 2026-07-21 PM): nothing Pi-side ever SENT the ID command,
    # so a daemon restarting after the RP2040 booted never re-learned identity.
    link, _ = mk_link()
    link.request_identity()
    assert "ID" in list(link.sent)


def test_start_requests_identity_on_real_serial():
    # start() on a real (fake) serial must ask for the identity line — the
    # firmware only volunteers `id` at ITS boot, not at ours.
    import time as _time

    class FakeSerial:
        def __init__(self):
            self.written = []

        def read(self, n):
            _time.sleep(0.01)
            return b""

        def write(self, data):
            self.written.append(data)
            return len(data)

    ser = FakeSerial()
    link = RP2040Link(serial_obj=ser)
    link.start()
    try:
        assert b"ID\n" in ser.written
        assert "ID" in list(link.sent)
    finally:
        link._stop = True


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok:   {name}")
            except AssertionError:
                fails += 1
                print(f"  FAIL: {name}")
    print("PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
