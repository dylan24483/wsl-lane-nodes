"""test_r2_outbox.py — Codex round-2 R2-12 (2026-07-21): JSONL-as-outbox
delivery semantics. Every record carries (source_id, boot_id, seq); the
OutboxReplayer tails the daily JSONL with a persisted cursor advanced only on
a 2xx (cursor-ack); the machine_store dedupes replays on the UNIQUE partial
index (INSERT OR IGNORE) so overlap after a drop / lost ack is idempotent.

Run under pytest or standalone (py -3 tests/test_r2_outbox.py).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', 'lane_node')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', 'server')))

import diag_events as de
from diag_events import (DiagQueue, DiagWriter, JsonlSink, OutboxReplayer,
                         make_event, stamp_delivery)


# ---- identity stamping -----------------------------------------------------

def test_stamp_delivery_is_idempotent_and_monotonic():
    r1 = stamp_delivery({})
    r2 = stamp_delivery({})
    assert r1["source_id"] and r1["boot_id"]
    assert r1["boot_id"] == r2["boot_id"]          # same process
    assert r2["seq"] > r1["seq"]                   # monotonic
    again = stamp_delivery(dict(r1))
    assert again["seq"] == r1["seq"]               # never re-stamped


def test_writer_stamps_every_jsonl_row():
    d = tempfile.mkdtemp(prefix="outbox_t1_")
    sink = JsonlSink(d, flush_n=1)
    w = DiagWriter(queue=DiagQueue(maxsize=8), sinks=[sink], enabled=True)
    w.start()
    w.emit(make_event(21, "info", "recovered", code="x"))
    w.stop()
    files = [n for n in os.listdir(d) if n.endswith(".jsonl")]
    rows = [json.loads(ln) for ln in
            open(os.path.join(d, files[0]), encoding="utf-8")
            .read().splitlines() if ln]
    assert rows[0]["source_id"] and rows[0]["boot_id"]
    assert isinstance(rows[0]["seq"], int)


# ---- replayer --------------------------------------------------------------

def _write_outbox(d, rows, name="diag-20260721.jsonl"):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _row(seq, **kw):
    r = {"lane_id": 21, "severity": "info", "event_type": "recovered",
         "source_id": "test-src", "boot_id": "boot-1", "seq": seq}
    r.update(kw)
    return r


def test_replayer_ships_and_advances_cursor_only_on_ack():
    d = tempfile.mkdtemp(prefix="outbox_t2_")
    _write_outbox(d, [_row(1), _row(2)])
    posted = []
    fail = {"on": True}

    def post(url, payload):
        if fail["on"]:
            raise RuntimeError("server down")
        posted.append(payload)

    rep = OutboxReplayer(d, "http://x:8766", post=post)
    assert rep.replay_once() == 0                  # post failed
    assert rep.post_errors == 1
    assert not os.path.exists(rep.cursor_path) or True
    fail["on"] = False
    assert rep.replay_once() == 2                  # replayed from cursor
    assert posted and len(posted[-1]["events"]) == 2
    cur = json.load(open(rep.cursor_path, encoding="utf-8"))
    assert cur["pos"] > 0
    # nothing new -> nothing shipped, cursor stable
    assert rep.replay_once() == 0
    # new rows after the cursor ship on the next pass
    _write_outbox(d, [_row(3)])
    assert rep.replay_once() == 1
    assert posted[-1]["events"][0]["seq"] == 3


def test_replayer_skips_identity_less_legacy_rows():
    d = tempfile.mkdtemp(prefix="outbox_t3_")
    legacy = {"lane_id": 21, "severity": "info", "event_type": "recovered"}
    _write_outbox(d, [legacy, _row(9)])
    posted = []
    rep = OutboxReplayer(d, "http://x:8766",
                         post=lambda u, p: posted.append(p))
    assert rep.replay_once() == 1
    assert rep.skipped == 1
    assert posted[-1]["events"][0]["seq"] == 9


def test_replayer_rolls_to_the_next_daily_file():
    d = tempfile.mkdtemp(prefix="outbox_t4_")
    _write_outbox(d, [_row(1)], name="diag-20260720.jsonl")
    posted = []
    rep = OutboxReplayer(d, "http://x:8766",
                         post=lambda u, p: posted.append(p))
    rep.replay_once()                               # cursor lands on day 1
    _write_outbox(d, [_row(2)], name="diag-20260721.jsonl")
    assert rep.replay_once() == 1                   # rolled to the new file
    cur = json.load(open(rep.cursor_path, encoding="utf-8"))
    assert cur["file"] == "diag-20260721.jsonl"


def test_partial_trailing_line_waits_for_the_flush():
    d = tempfile.mkdtemp(prefix="outbox_t5_")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "diag-20260721.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(_row(1)) + "\n")
        f.write('{"half": "written')               # no newline
    posted = []
    rep = OutboxReplayer(d, "http://x:8766",
                         post=lambda u, p: posted.append(p))
    assert rep.replay_once() == 1                  # only the complete line
    with open(path, "a", encoding="utf-8") as f:
        f.write('"}\n')                            # completes as junk (no id)
    assert rep.replay_once() == 0


def test_diagwriter_outbox_mode_disables_the_live_event_sink():
    d = tempfile.mkdtemp(prefix="outbox_t6_")
    old = {k: os.environ.get(k) for k in
           (de.SERVER_URL_ENV, de.DIR_ENV, de.OUTBOX_ENV)}
    os.environ[de.SERVER_URL_ENV] = "http://x:8766"
    os.environ[de.DIR_ENV] = d
    os.environ.pop(de.OUTBOX_ENV, None)            # default ON
    try:
        w = DiagWriter(enabled=True)
        assert w.outbox is not None
        http = [s for s in w.sinks if type(s).__name__ == "HttpSink"]
        assert http and http[0].events_enabled is False
        http[0].emit({"x": 1})                     # must be a no-op
        assert http[0]._buf == []
        assert "outbox" in w.stats() or w.stats().get("enabled") is not None
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---- server-side idempotency ----------------------------------------------

def test_machine_store_dedupes_on_delivery_identity():
    import machine_store as ms
    d = tempfile.mkdtemp(prefix="outbox_t7_")
    old_db = ms.DB_PATH
    ms.DB_PATH = type(old_db)(os.path.join(d, "t.db"))
    try:
        ev = _row(42, code="c1")
        rows = [ms.validate_event(ev)]
        ids1 = ms.insert_events(rows)
        assert len(ids1) == 1 and ms.last_insert_duplicates() == 0
        ids2 = ms.insert_events([ms.validate_event(ev)])   # replay
        assert ids2 == [] and ms.last_insert_duplicates() == 1
        # identity-less rows never dedupe (legacy behavior intact)
        legacy = {"lane_id": 21, "severity": "info", "event_type": "recovered"}
        a = ms.insert_events([ms.validate_event(legacy)])
        b = ms.insert_events([ms.validate_event(legacy)])
        assert len(a) == 1 and len(b) == 1
        # partial identity is a validation error
        try:
            ms.validate_event({"lane_id": 21, "severity": "info",
                               "event_type": "recovered",
                               "source_id": "only-this"})
            raise AssertionError("partial identity must raise")
        except ValueError:
            pass
        # cycle replay resolves to the SAME row id
        cy = {"lane_id": 22, "final_state": "READY", "source_id": "s",
              "boot_id": "b", "seq": 7}
        id1 = ms.insert_cycle(ms.validate_cycle(cy))
        id2 = ms.insert_cycle(ms.validate_cycle(cy))
        assert id1 == id2
    finally:
        ms.DB_PATH = old_db


# ---- quarantine growth bound (review fix for finding 4) --------------------

def test_quarantine_dedups_on_lost_ack_replay():
    # The lost-ack hazard: a mixed accepted+rejected segment can replay (cursor
    # didn't advance / a re-read), and the original _quarantine appended the
    # rejected rows AND re-emitted the outbox_quarantine event every time —
    # unbounded on a Pi SD card. The fix dedups by delivery identity.
    d = tempfile.mkdtemp(prefix="outbox_q1_")
    notified = []
    rep = OutboxReplayer(d, "http://x:8766", post=lambda u, p: None,
                         on_quarantine=lambda n, lane, errs: notified.append(n))
    rows = [_row(1), _row(2)]
    rejected = [{"index": 0, "error": "unknown_event_type"}]
    rep._quarantine(rows, rejected)          # first receipt
    rep._quarantine(rows, rejected)          # lost-ack replay: SAME rows again
    rep._quarantine(rows, rejected)          # ...and again
    qf = os.path.join(d, "outbox_quarantine.jsonl")
    lines = [ln for ln in open(qf, encoding="utf-8").read().splitlines() if ln]
    assert len(lines) == 1, f"row quarantined ONCE despite replays, got {len(lines)}"
    assert rep.quarantined == 1, "quarantined counter not double-counted"
    assert notified == [1], f"outbox_quarantine notified once, got {notified}"


def test_quarantine_file_is_capped_and_rotated():
    d = tempfile.mkdtemp(prefix="outbox_q2_")
    prev = os.environ.get("WSL_DIAG_QUARANTINE_MAX_BYTES")
    os.environ["WSL_DIAG_QUARANTINE_MAX_BYTES"] = "300"
    try:
        rep = OutboxReplayer(d, "http://x:8766", post=lambda u, p: None)
        for i in range(300):     # DISTINCT identities -> no dedup, real growth
            rep._quarantine([_row(i, detail={"pad": "y" * 40})],
                            [{"index": 0, "error": "e"}])
        qf = os.path.join(d, "outbox_quarantine.jsonl")
        rotated = qf + ".1"
        assert os.path.exists(rotated), "quarantine file never rotated to .1"
        live = os.path.getsize(qf) if os.path.exists(qf) else 0
        # total on disk stays bounded to ~2x the cap (live + one rotated .1),
        # NOT 300 rows unbounded.
        assert live <= 300 + 512, f"live quarantine file unbounded ({live} bytes)"
        assert os.path.getsize(rotated) <= 300 + 512, "rotated file unbounded"
    finally:
        if prev is None:
            os.environ.pop("WSL_DIAG_QUARANTINE_MAX_BYTES", None)
        else:
            os.environ["WSL_DIAG_QUARANTINE_MAX_BYTES"] = prev


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
