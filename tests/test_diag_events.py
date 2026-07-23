"""Tests for lane_node/diag_events.py — the Phase 8 diagnostics event core
(scope doc phase8_diagnostics_scope_2026-07-19.md §2/§3).

Proves the standing safety rules for anything near the control loop:
  - DiagEvent validates severity/event_type AT construction; detail is coerced
    JSON-safe (bounded) so serialization can never fail downstream
  - DiagQueue is bounded and emit() NEVER blocks or raises; overflow drops +
    counts
  - JsonlSink batches writes (N events / T seconds — the SD-wear rule), rotates
    daily, prunes to max_files, and swallows its own errors
  - HttpSink posts bounded-retry batches, drops + counts on persistent failure,
    is inert without a server URL, and never raises (HTTP layer faked — no
    network in tests)
  - DiagWriter drains on a single daemon thread, survives a raising sink,
    honors the WSL_DIAG_ENABLED kill-switch, and stop() flushes everything

Hardware-free by construction (pure stdlib module). Run standalone with:
    py -3 tests/test_diag_events.py
"""
import json
import os
import sys
import tempfile

# Make lane_node modules importable when running from anywhere
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lane_node')))

import diag_events as de
from diag_events import (DiagEvent, DiagQueue, DiagWriter, HttpSink, JsonlSink,
                         make_event, SEVERITIES, ENABLE_ENV, QUEUE_MAX_ENV,
                         DIR_ENV, SERVER_URL_ENV, DEFAULT_QUEUE_MAX)


def _raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    except Exception:
        return False
    return False


class _Env:
    """Set/unset env vars with guaranteed restore (tests may run in any order)."""
    def __init__(self, **kv):
        self.kv = kv
        self.saved = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        return False


class FakeSink:
    """Collects rows; counts flushes. maybe_flush is a no-op (writer cadence
    is exercised via real sinks)."""
    def __init__(self, boom_on_emit=False):
        self.rows = []
        self.flushes = 0
        self.boom = boom_on_emit

    def emit(self, row):
        if self.boom:
            raise RuntimeError("sink exploded")
        self.rows.append(row)

    def maybe_flush(self):
        pass

    def flush(self):
        self.flushes += 1


# ---------------------------------------------------------------------------
# DiagEvent / make_event
# ---------------------------------------------------------------------------
def test_make_event_shape():
    ev = make_event(21, "warn", "beam_blocked", code="diell:L",
                    detail={"held_s": 12.4}, now=lambda: 42.5)
    d = ev.to_dict()
    assert d["lane_id"] == 21
    assert d["severity"] == "warn"
    assert d["event_type"] == "beam_blocked"
    assert d["code"] == "diell:L"
    assert d["detail"] == {"held_s": 12.4}
    assert d["ts_mono"] == 42.5
    # UTC ISO stamp, tz-aware
    assert "T" in d["ts_utc"] and ("+00:00" in d["ts_utc"] or d["ts_utc"].endswith("Z"))
    json.dumps(d)   # must always serialize


def test_severity_validated_at_construction():
    for s in SEVERITIES:
        make_event(1, s, "recovered")
    assert _raises(ValueError, make_event, 1, "catastrophic", "x")
    assert _raises(ValueError, make_event, 1, "INFO", "x")   # case-sensitive vocab
    assert _raises(ValueError, make_event, 1, None, "x")


def test_event_type_validated():
    assert _raises(ValueError, make_event, 1, "info", "")
    assert _raises(ValueError, make_event, 1, "info", "   ")
    assert _raises(ValueError, make_event, 1, "info", None)
    assert _raises(ValueError, make_event, 1, "info", 42)
    # R3-1a: the event-type allow-set is load-bearing on the CLIENT — a type
    # absent from the contract vocab raises at the emitter (not only after a
    # server round-trip); a valid contract type constructs fine.
    assert _raises(ValueError, make_event, 1, "info", "definitely_not_a_type")
    make_event(1, "info", "recovered")
    # detail must be a dict (or None)
    assert _raises(ValueError, make_event, 1, "info", "recovered", detail=[1, 2])


def test_detail_coerced_json_safe():
    class Weird:
        def __repr__(self):
            return "<weird>"
    deep = {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}
    ev = make_event(3, "fault", "recovered", detail={
        "obj": Weird(), "deep": deep, "big": "x" * 2000,
        "list": list(range(100)),
    })
    s = json.dumps(ev.to_dict())          # never raises
    assert "truncated" in s               # bounded strings/containers
    assert isinstance(ev.detail["obj"], str)


# ---------------------------------------------------------------------------
# DiagQueue
# ---------------------------------------------------------------------------
def test_queue_bounded_drops_and_counts():
    q = DiagQueue(maxsize=5)
    ok = [q.emit(make_event(1, "info", "recovered", code=str(i))) for i in range(10)]
    assert ok == [True] * 5 + [False] * 5
    assert q.drops == 5
    got = []
    while True:
        ev = q.get(timeout=0)
        if ev is None:
            break
        got.append(ev)
    assert len(got) == 5
    assert got[0].code == "0"             # FIFO, oldest kept


def test_queue_env_sizing():
    with _Env(**{QUEUE_MAX_ENV: "7"}):
        assert DiagQueue().maxsize == 7
    with _Env(**{QUEUE_MAX_ENV: "garbage"}):
        assert DiagQueue().maxsize == DEFAULT_QUEUE_MAX
    with _Env(**{QUEUE_MAX_ENV: "-3"}):
        assert DiagQueue().maxsize == DEFAULT_QUEUE_MAX
    with _Env(**{QUEUE_MAX_ENV: None}):
        assert DiagQueue().maxsize == DEFAULT_QUEUE_MAX


# ---------------------------------------------------------------------------
# JsonlSink
# ---------------------------------------------------------------------------
def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f.read().splitlines() if ln]


def test_jsonl_batches_by_count():
    d = tempfile.mkdtemp(prefix="diag_jsonl_")
    clk = {"t": 0.0}
    sink = JsonlSink(d, flush_n=3, flush_s=9999.0, now=lambda: clk["t"],
                     today=lambda: "20260719")
    sink.emit({"n": 1})
    sink.emit({"n": 2})
    assert not os.listdir(d), "must buffer below flush_n (batched writes)"
    sink.emit({"n": 3})                    # hits flush_n -> one batched write
    rows = _read_jsonl(os.path.join(d, "diag-20260719.jsonl"))
    assert [r["n"] for r in rows] == [1, 2, 3]
    assert sink.written == 3 and sink.write_errors == 0


def test_jsonl_flushes_by_time():
    d = tempfile.mkdtemp(prefix="diag_jsonl_")
    clk = {"t": 0.0}
    sink = JsonlSink(d, flush_n=100, flush_s=5.0, now=lambda: clk["t"],
                     today=lambda: "20260719")
    sink.emit({"n": 1})
    clk["t"] = 3.0
    sink.maybe_flush()
    assert not os.listdir(d), "below flush_s -> still buffered"
    clk["t"] = 6.0
    sink.maybe_flush()
    rows = _read_jsonl(os.path.join(d, "diag-20260719.jsonl"))
    assert len(rows) == 1


def test_jsonl_daily_rotation_and_prune():
    d = tempfile.mkdtemp(prefix="diag_jsonl_")
    day = {"v": "20260701"}
    sink = JsonlSink(d, max_files=2, flush_n=1, today=lambda: day["v"])
    for v in ("20260701", "20260702", "20260703"):
        day["v"] = v
        sink.emit({"day": v})              # flush_n=1 -> immediate write
    names = sorted(os.listdir(d))
    assert names == ["diag-20260702.jsonl", "diag-20260703.jsonl"], names


def test_jsonl_errors_swallowed():
    d = tempfile.mkdtemp(prefix="diag_jsonl_")
    blocker = os.path.join(d, "notadir")
    with open(blocker, "w") as f:
        f.write("x")
    sink = JsonlSink(blocker, flush_n=1)   # dir path is a FILE -> writes fail
    sink.emit({"n": 1})                    # must not raise
    sink.flush()
    sink.maybe_flush()
    assert sink.write_errors >= 1
    # unserializable row is replaced, not fatal
    d2 = tempfile.mkdtemp(prefix="diag_jsonl_")
    sink2 = JsonlSink(d2, flush_n=1, today=lambda: "20260719")
    sink2.emit({"bad": object()})
    rows = _read_jsonl(os.path.join(d2, "diag-20260719.jsonl"))
    assert len(rows) == 1 and sink2.write_errors == 0


def test_jsonl_env_dir():
    d = tempfile.mkdtemp(prefix="diag_envdir_")
    with _Env(**{DIR_ENV: d}):
        sink = JsonlSink(flush_n=1, today=lambda: "20260719")
        assert sink.dir == d
        sink.emit({"n": 1})
    assert os.path.exists(os.path.join(d, "diag-20260719.jsonl"))


# ---------------------------------------------------------------------------
# HttpSink (HTTP layer faked — no network)
# ---------------------------------------------------------------------------
def test_http_posts_batches():
    posts = []
    sink = HttpSink("http://192.168.4.50:8766/", flush_n=2, flush_s=9999.0,
                    post=lambda url, payload: posts.append((url, payload)))
    assert sink.enabled
    sink.emit({"n": 1})
    assert posts == [], "must buffer below flush_n"
    sink.emit({"n": 2})
    assert len(posts) == 1
    url, payload = posts[0]
    assert url == "http://192.168.4.50:8766/api/machine/events"
    assert payload == {"events": [{"n": 1}, {"n": 2}]}
    assert sink.posted == 2 and sink.dropped == 0


def test_http_post_cycle():
    posts = []
    sink = HttpSink("http://x:8766", post=lambda url, payload: posts.append((url, payload)))
    ok = sink.post_cycle({"lane_id": 22, "final_state": "READY", "ball": 1})
    assert ok is True
    url, payload = posts[0]
    assert url == "http://x:8766/api/machine/cycles"
    assert payload["cycle"]["lane_id"] == 22


def test_http_bounded_retry_then_drop():
    calls = {"n": 0}

    def bad_post(url, payload):
        calls["n"] += 1
        raise OSError("connection refused")

    sink = HttpSink("http://x:8766", retries=2, flush_n=3, post=bad_post)
    for i in range(3):
        sink.emit({"n": i})                # 3rd emit -> flush -> fails, never raises
    assert calls["n"] == 2, "bounded retry: exactly `retries` attempts"
    assert sink.dropped == 3 and sink.post_errors == 2
    assert sink.post_cycle({"x": 1}) is False
    assert sink.dropped == 4


def test_http_inert_without_url():
    with _Env(**{SERVER_URL_ENV: None}):
        sink = HttpSink()
        assert sink.enabled is False
        sink.emit({"n": 1})
        sink.flush()
        assert sink._buf == [] and sink.posted == 0
        assert sink.post_cycle({"x": 1}) is False


def test_http_sends_lane_token_when_armed():
    """2026-07-19 review: lane_node_server gates EVERY POST — machine ingest
    included — behind X-Lane-Token when LANE_NODE_TOKEN is set (the
    production posture), but HttpSink sent no header: every batch 401'd and
    was silently dropped. The token now rides the same env as lane_node.py
    and the wsl_api bridge."""
    class _FakeUrlopen:
        def __init__(self):
            self.reqs = []

        def __call__(self, req, timeout=None):
            self.reqs.append(req)
            class _Resp:
                status = 200
                def read(self, n=-1):
                    return b"{}"
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False
            return _Resp()

    import urllib.request as ur
    fake = _FakeUrlopen()
    old = ur.urlopen
    ur.urlopen = fake
    try:
        with _Env(LANE_NODE_TOKEN="sekret-tok"):
            sink = HttpSink("http://x:8766", flush_n=1)
            assert sink.token == "sekret-tok", "token read from LANE_NODE_TOKEN"
            sink.emit({"n": 1})
        assert len(fake.reqs) == 1
        req = fake.reqs[0]
        assert req.get_header("X-lane-token") == "sekret-tok", req.headers
        # explicit token param beats env; no env + no param -> no header
        with _Env(LANE_NODE_TOKEN=None):
            sink2 = HttpSink("http://x:8766", flush_n=1, token="param-tok")
            sink2.emit({"n": 2})
            sink3 = HttpSink("http://x:8766", flush_n=1)
            assert sink3.token == ""
            sink3.emit({"n": 3})
        assert fake.reqs[1].get_header("X-lane-token") == "param-tok"
        assert fake.reqs[2].get_header("X-lane-token") is None, \
            "no token configured -> no header leaked"
    finally:
        ur.urlopen = old


# ---------------------------------------------------------------------------
# DiagWriter
# ---------------------------------------------------------------------------
def test_writer_end_to_end():
    fake = FakeSink()
    w = DiagWriter(queue=DiagQueue(maxsize=64), sinks=[fake], enabled=True,
                   poll_s=0.02)
    assert w.start() is True
    assert w.start() is True               # idempotent
    for i in range(5):
        assert w.emit(make_event(21, "info", "recovered", code=str(i))) is True
    w.stop(timeout=5.0)
    assert len(fake.rows) == 5, f"writer must deliver every event (got {len(fake.rows)})"
    assert fake.rows[0]["code"] == "0" and fake.rows[-1]["code"] == "4"
    assert all(isinstance(r, dict) for r in fake.rows), "sinks receive plain dicts"
    assert fake.flushes >= 1, "stop() must flush the sinks"
    st = w.stats()
    assert st["queue_drops"] == 0 and st["sink_errors"] == 0


def test_writer_kill_switch():
    with _Env(**{ENABLE_ENV: "0"}):
        fake = FakeSink()
        w = DiagWriter(sinks=[fake])
        assert w.enabled is False
        assert w.start() is False
        assert w.emit(make_event(1, "info", "recovered")) is False
        w.stop()
        assert fake.rows == []
    # default (env absent) is ON — local logging is safe-on
    with _Env(**{ENABLE_ENV: None}):
        assert DiagWriter(sinks=[FakeSink()]).enabled is True


def test_writer_raising_sink_isolated():
    bad = FakeSink(boom_on_emit=True)
    good = FakeSink()
    w = DiagWriter(queue=DiagQueue(maxsize=16), sinks=[bad, good], enabled=True,
                   poll_s=0.02)
    w.start()
    for i in range(3):
        w.emit(make_event(1, "warn", "chatter", code=str(i)))
    w.stop(timeout=5.0)
    assert len(good.rows) == 3, "a raising sink must not starve the others"
    assert w.sink_errors >= 3


def test_writer_stop_without_start_still_flushes():
    fake = FakeSink()
    w = DiagWriter(queue=DiagQueue(maxsize=16), sinks=[fake], enabled=True)
    w.emit(make_event(1, "info", "recovered"))
    w.emit(make_event(1, "info", "recovered"))
    w.stop()                               # never started -> synchronous drain
    assert len(fake.rows) == 2 and fake.flushes >= 1


def test_writer_queue_overflow_counted():
    fake = FakeSink()
    w = DiagWriter(queue=DiagQueue(maxsize=2), sinks=[fake], enabled=True)
    for i in range(5):
        w.emit(make_event(1, "info", "recovered", code=str(i)))   # never blocks
    assert w.stats()["queue_drops"] == 3
    w.stop()
    assert len(fake.rows) == 2             # the queued two still delivered


def test_writer_default_sinks_follow_env():
    d = tempfile.mkdtemp(prefix="diag_defaults_")
    with _Env(**{DIR_ENV: d, SERVER_URL_ENV: None, ENABLE_ENV: None}):
        w = DiagWriter()
        assert [type(s).__name__ for s in w.sinks] == ["JsonlSink"]
    with _Env(**{DIR_ENV: d, SERVER_URL_ENV: "http://192.168.4.103:8766", ENABLE_ENV: None}):
        w2 = DiagWriter()
        assert [type(s).__name__ for s in w2.sinks] == ["JsonlSink", "HttpSink"]
        assert w2.sinks[1].base_url == "http://192.168.4.103:8766"


def test_writer_events_reach_jsonl_and_http_together():
    d = tempfile.mkdtemp(prefix="diag_both_")
    posts = []
    jsonl = JsonlSink(d, flush_n=100, flush_s=9999.0, today=lambda: "20260719")
    http = HttpSink("http://x:8766", flush_n=100, flush_s=9999.0,
                    post=lambda url, payload: posts.append((url, payload)))
    w = DiagWriter(queue=DiagQueue(maxsize=32), sinks=[jsonl, http],
                   enabled=True, poll_s=0.02)
    w.start()
    w.emit(make_event(22, "fault", "fsm_fault", code="motion_timeout:S",
                      detail={"state": "sweep_to_guard", "elapsed_s": 8.4}))
    w.stop(timeout=5.0)
    rows = _read_jsonl(os.path.join(d, "diag-20260719.jsonl"))
    assert len(rows) == 1 and rows[0]["code"] == "motion_timeout:S"
    assert len(posts) == 1 and posts[0][1]["events"][0]["lane_id"] == 22


# ── H4 (Codex audit 2026-07-21): cross-repo contract, CLIENT side ──────────────
# server/machine_contract.json is the single source of truth for the machine-
# diagnostics HTTP contract. These tests pin the CLIENT (HttpSink) to it; the
# server suite (test_machine_diagnostics.py) pins the server + store to the
# SAME file, so the two sides can never again drift while their own fakes
# stay green (the exact failure mode behind the H4 cycle-wrapper mismatch).

_CONTRACT_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'server', 'machine_contract.json'))


def _contract():
    with open(_CONTRACT_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_contract_client_paths_and_wrappers():
    c = _contract()
    assert HttpSink.EVENTS_PATH == c["endpoints"]["events_post"]["path"]
    assert HttpSink.CYCLES_PATH == c["endpoints"]["cycles_post"]["path"]
    assert c["endpoints"]["events_post"]["request_wrapper_key"] == "events"
    assert c["endpoints"]["cycles_post"]["request_wrapper_key"] == "cycle"
    # the client's actual wire shapes match the declared wrappers
    posts = []
    sink = HttpSink("http://x:8766", flush_n=1,
                    post=lambda url, payload: posts.append((url, payload)))
    sink.emit({"lane_id": 22, "severity": "info", "event_type": "recovered"})
    sink.flush()
    assert posts[-1][0].endswith(c["endpoints"]["events_post"]["path"])
    assert list(posts[-1][1].keys()) == ["events"]
    sink.post_cycle({"lane_id": 22, "final_state": "READY"})
    assert posts[-1][0].endswith(c["endpoints"]["cycles_post"]["path"])
    assert list(posts[-1][1].keys()) == ["cycle"]
    assert posts[-1][1]["cycle"]["lane_id"] == 22


def test_contract_client_fixture_roundtrip():
    """post_cycle on the contract fixture's inner row produces EXACTLY the
    fixture's canonical POST body — the byte-level wire shape the server
    suite POSTs verbatim at its ingest."""
    c = _contract()
    fixture = c["examples"]["cycle_post_body"]
    posts = []
    sink = HttpSink("http://x:8766",
                    post=lambda url, payload: posts.append(payload))
    assert sink.post_cycle(dict(fixture["cycle"])) is True
    assert posts[-1] == fixture, (posts[-1], fixture)


def test_contract_client_vocab_and_auth():
    c = _contract()
    assert list(de.SEVERITIES) == c["vocab"]["severities"]
    assert de.TOKEN_ENV == c["auth"]["env"]
    import inspect
    assert c["auth"]["header"] in inspect.getsource(HttpSink._urllib_post), \
        "the auth header _urllib_post sets must match the contract"


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
