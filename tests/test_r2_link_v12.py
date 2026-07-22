"""test_r2_link_v12.py — Codex round-2 R2-11 (2026-07-21): rp2040_link must
CONSUME every v1.2.x record class (tap state, rail-drop edge ring, epochs,
VCC_5V extrema, warnings, dumps) as typed records instead of silently
ignoring them, with epoch-aware staleness so pre-reboot edges never read as
fresh diagnosis.

Run under pytest or standalone (py -3 tests/test_r2_link_v12.py).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', 'lane_node')))

from rp2040_link import RP2040Link, TAP_BITS, TAPDUMP_ENTRIES_MAX


def mk_link():
    clk = {"t": 1000.0}
    link = RP2040Link(now=lambda: clk["t"], hb_timeout=1.0)
    return link, clk


V12_BOOT = ('{"ev":"boot","fw":"phase8b-rp2040 v1.2.1","wdt_reset":0,'
            '"rp_ok":0,"maxrun_ms":8000,"dbg":0,'
            '"v11":{"sa":"off","ta1":"off","echo":0,"nrun":0},'
            '"tap":{"ep":3,"pre":0,"n":0}}')
V12_HB = ('{"ev":"hb","ok":1,"flt":"","up":12500,"drp":0,"in":0,"run":0,'
          '"tap":5,"rd":7,"ep":3,"v5":4810,"v5n":4650,"v5x":4885}')


def test_v12_hb_fields_stored_and_queryable():
    link, _ = mk_link()
    assert link.tap_levels() is None
    assert link.v5_stats() is None
    assert link.ring_epoch() is None
    link.feed_line(V12_BOOT)
    assert link.ring_epoch() == 3
    link.feed_line(V12_HB)
    taps = link.tap_levels()
    # tap mask 5 = 0b0101 -> NE555 + ARM observed high
    assert taps == {"NE555": True, "KICK": False, "ARM": True, "RPOK": False}
    assert link.v5_stats() == (4810, 4650, 4885)
    assert link.ring_depth() == 7
    assert link.health_ok()   # v1.2 fields must not perturb health semantics


def test_tapdump_collected_into_one_typed_record_with_epoch_staleness():
    link, _ = mk_link()
    link.feed_line(V12_BOOT)                      # epoch 3 current
    link.feed_line('{"ev":"tapdump","n":3,"ep":3,"br":2,"mut":0,'
                   '"cause":"kick_starvation","t":30000}')
    # entry from the PREVIOUS epoch (pre-reboot) + two fresh ones
    link.feed_line('{"ev":"tape","i":0,"t":29450,"p":1,"l":0,"ep":2}')
    link.feed_line('{"ev":"tape","i":1,"t":29900,"p":0,"l":0,"ep":3}')
    link.feed_line('{"ev":"tape","i":2,"t":29950,"p":2,"l":1,"ep":3}')
    link.feed_line('{"ev":"tapdump_end","n":3}')
    recs = link.drain_diag_records()
    dumps = [r for r in recs if r["kind"] == "tapdump"]
    assert len(dumps) == 1
    d = dumps[0]
    assert d["meta"]["cause"] == "kick_starvation"
    assert d["meta"]["boot_reason"] == 2
    assert d["fresh_n"] == 2 and d["stale_n"] == 1
    stale = [e for e in d["entries"] if e["stale"]]
    assert len(stale) == 1 and stale[0]["pin"] == "KICK"
    fresh_pins = {e["pin"] for e in d["entries"] if not e["stale"]}
    assert fresh_pins == {"NE555", "ARM"}
    # drained means drained
    assert link.drain_diag_records() == []


def test_tapdump_without_header_still_surfaces():
    link, _ = mk_link()
    link.feed_line(V12_BOOT)
    link.feed_line('{"ev":"tape","i":0,"t":100,"p":3,"l":1,"ep":3}')
    link.feed_line('{"ev":"tapdump_end","n":1}')
    recs = [r for r in link.drain_diag_records() if r["kind"] == "tapdump"]
    assert len(recs) == 1
    assert recs[0]["meta"].get("headerless") is True
    assert recs[0]["entries"][0]["pin"] == "RPOK"
    assert recs[0]["fresh_n"] == 1


def test_tapdump_entry_bound_is_enforced():
    link, _ = mk_link()
    link.feed_line(V12_BOOT)
    link.feed_line('{"ev":"tapdump","n":999,"ep":3,"br":0,"mut":0,'
                   '"cause":"none","t":1}')
    for i in range(TAPDUMP_ENTRIES_MAX + 10):
        link.feed_line('{"ev":"tape","i":%d,"t":%d,"p":0,"l":0,"ep":3}'
                       % (i, i))
    link.feed_line('{"ev":"tapdump_end","n":999}')
    d = [r for r in link.drain_diag_records() if r["kind"] == "tapdump"][0]
    assert len(d["entries"]) == TAPDUMP_ENTRIES_MAX
    assert d["meta"]["discarded"] == 10


def test_tapwarn_and_uart_drops_become_records():
    link, _ = mk_link()
    link.feed_line(V12_BOOT)
    link.feed_line('{"ev":"tapwarn","code":"rpok_mism","t":30500}')
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":100,"drp":0}')
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":350,"drp":4}')
    recs = link.drain_diag_records()
    kinds = [r["kind"] for r in recs]
    assert "tap_warn" in kinds
    warn = next(r for r in recs if r["kind"] == "tap_warn")
    assert warn["code"] == "rpok_mism"
    drops = next(r for r in recs if r["kind"] == "uart_drops")
    assert drops["lost"] == 4 and drops["total"] == 4


def test_boot_with_preserved_ring_yields_fw_boot_record():
    link, _ = mk_link()
    link.feed_line('{"ev":"boot","fw":"x","wdt_reset":1,"rp_ok":0,'
                   '"tap":{"ep":5,"pre":1,"n":17}}')
    recs = [r for r in link.drain_diag_records() if r["kind"] == "fw_boot"]
    assert len(recs) == 1
    r = recs[0]
    assert r["ring_preserved"] is True and r["ring_entries"] == 17
    assert r["ring_epoch"] == 5 and r["wdt_reset"] is True
    assert link.ring_epoch() == 5


def test_request_tapdump_sends_the_command():
    link, _ = mk_link()
    link.request_tapdump()
    assert "TAPDUMP" in link.sent


def test_v11_firmware_lines_unaffected():
    """A pre-v1.2 firmware (no tap fields) produces NO records and None
    accessors — additive-only consumption."""
    link, _ = mk_link()
    link.feed_line('{"ev":"boot","fw":"x","wdt_reset":0,"rp_ok":0,'
                   '"maxrun_ms":8000}')
    link.feed_line('{"ev":"hb","ok":1,"flt":"","up":100,"in":0,"run":0}')
    assert link.tap_levels() is None
    assert link.v5_stats() is None
    assert link.drain_diag_records() == []
    assert TAP_BITS == ("NE555", "KICK", "ARM", "RPOK")


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    fails = 0
    for name, fn in fns:
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
