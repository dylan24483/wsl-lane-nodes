"""Watchdog-kick independence regression tests for lane_node.py.

THE BUG THIS GUARDS AGAINST (it shipped once — see memory
project_phase8a_daemon_missing_watchdog_kick, fixed 2026-05-29): the GPIO12
NE555 kick loop must run INDEPENDENT of the WebSocket connection. A server
outage / hang must NOT stop the kicks (the pinsetter would safe-open ~11s
later for no reason); conversely, daemon death MUST stop them (that is the
whole point of the hardware watchdog).

Proves, with a fake gpiozero layer and a scripted fake websockets client
(NO hardware, NO network):

  1. Server unreachable (connect refused, reconnect-backoff loop):
     kicks continue at ~1Hz the whole time.
  2. WS connection dies mid-session: kicks never gap wider than the NE555
     window across the drop + reconnect; the new connection gets a fresh
     event_sender and a queued event is delivered EXACTLY ONCE on the live
     socket (regression: orphaned event_sender from the dead connection).
  3. Daemon kill (SIGTERM path == main_task.cancel()): kicks STOP, the kick
     pin ends LOW and closed, and every relay output is driven LOW before
     its device is closed.

Run with:
    py -3 tests/test_watchdog_kick.py

Pure asyncio + real sleeps (~20s total). The SIGTERM handler itself can't be
registered on Windows (add_signal_handler is Unix-only), so the tests stub it
and trigger the exact same code path: main_task.cancel().
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import types

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LANE_NODE_DIR = os.path.join(REPO, 'lane_node')
sys.path.insert(0, LANE_NODE_DIR)

NE555_WINDOW_S = 2.0   # assert no kick gap ever exceeds this (real window ~11s;
                       # the loop kicks at ~1Hz, so >2s means the loop stalled)


# ---------------------------------------------------------------
# Fake gpiozero — must be in sys.modules BEFORE importing lane_node
# ---------------------------------------------------------------
class FakeLED:
    def __init__(self, pin):
        self.pin = pin
        self.events = []          # (monotonic_ts, 'on'|'off'|'close')
        self.is_lit = False
        self.closed = False

    def on(self):
        self.is_lit = True
        self.events.append((time.monotonic(), 'on'))

    def off(self):
        self.is_lit = False
        self.events.append((time.monotonic(), 'off'))

    def close(self):
        self.closed = True
        self.events.append((time.monotonic(), 'close'))

    def on_times(self):
        return [t for t, e in self.events if e == 'on']


class FakeButton:
    def __init__(self, pin, pull_up=None, bounce_time=None):
        self.pin = pin
        self.when_pressed = None
        self.when_released = None
        self.closed = False

    def close(self):
        self.closed = True


fake_gpiozero = types.ModuleType('gpiozero')
fake_gpiozero.LED = FakeLED
fake_gpiozero.Button = FakeButton
sys.modules['gpiozero'] = fake_gpiozero


# ---------------------------------------------------------------
# Fake websockets.asyncio.client.connect — scripted per test
# ---------------------------------------------------------------
WS_SCRIPT = []          # per-test: FakeWS instances handed out in order
CONNECT_REFUSALS = [0]  # count of refused connect attempts
_TRANSPORT_TMPS = []    # retain each per-import SQLite directory for the test


class FakeWS:
    """Stands in for a live websockets connection.

    send() records messages until kill()ed, then raises (like a send on a
    closed socket). `async for raw in ws` blocks until kill(), then raises
    (like ConnectionClosed surfacing from recv) — which is what ends
    command_handler on a real drop.
    """
    def __init__(self, name):
        self.name = name
        self.sent = []
        self._dead = asyncio.Event()

    async def send(self, msg):
        if self._dead.is_set():
            raise ConnectionError(f"{self.name}: send on dead ws")
        self.sent.append(msg)

    def kill(self):
        self._dead.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self._dead.wait()
        raise ConnectionError(f"{self.name}: connection lost")


class _FakeConnectCM:
    def __init__(self, url):
        self.url = url

    async def __aenter__(self):
        if WS_SCRIPT:
            return WS_SCRIPT.pop(0)
        CONNECT_REFUSALS[0] += 1
        raise ConnectionRefusedError("fake: server unreachable")

    async def __aexit__(self, *exc):
        return False


def fake_connect(url, **kw):
    return _FakeConnectCM(url)


_ws_client = types.ModuleType('websockets.asyncio.client')
_ws_client.connect = fake_connect
_ws_server = types.ModuleType('websockets.asyncio.server')
_ws_server.serve = None
_ws_asyncio = types.ModuleType('websockets.asyncio')
_ws_asyncio.client = _ws_client
_ws_asyncio.server = _ws_server
_ws_root = types.ModuleType('websockets')
_ws_root.asyncio = _ws_asyncio
sys.modules['websockets'] = _ws_root
sys.modules['websockets.asyncio'] = _ws_asyncio
sys.modules['websockets.asyncio.client'] = _ws_client
sys.modules['websockets.asyncio.server'] = _ws_server


# ---------------------------------------------------------------
# Harness
# ---------------------------------------------------------------
def assert_true(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL [{msg}]")


def fresh_lane_node():
    """(Re-)import lane_node with fresh fake devices + module state."""
    WS_SCRIPT.clear()
    CONNECT_REFUSALS[0] = 0
    transport_tmp = tempfile.TemporaryDirectory()
    _TRANSPORT_TMPS.append(transport_tmp)
    os.environ["WSL_SCORING_TRANSPORT_DB"] = os.path.join(
        transport_tmp.name, "reliable_transport.sqlite3")
    sys.modules.pop('lane_node', None)   # force re-exec: fresh fake devices/state
    import lane_node
    return lane_node


def test_physical_node_identity_and_pair_have_no_unsafe_fallback():
    ln = fresh_lane_node()
    assert ln._required_node_id("pi-lane21-22") == "pi-lane21-22"
    assert ln._required_node_id("n" * 121) == "n" * 121
    assert ln._required_node_id("n" * 128) == "n" * 128
    for value in (None, "", "dev", "dev-pair-21-22",
                  "pair-21-22-dev", "lane-node-dev-pair-21-22",
                  "n" * 129, "contains space"):
        with pytest.raises(SystemExit):
            ln._required_node_id(value)
    assert ln._canonical_diag_source(
        "pi-lane21-22", "pi-lane21-22") == "pi-lane21-22"
    assert ln._canonical_diag_source(
        "pi-lane21-22", "") == "pi-lane21-22"
    with pytest.raises(SystemExit):
        ln._canonical_diag_source("pi-lane21-22", "other-node")
    assert ln._scoring_node_token(
        "unique-node-secret", False) == "unique-node-secret"
    with pytest.raises(SystemExit):
        ln._scoring_node_token(
            "shared-control-secret", False, "shared-control-secret")
    assert ln._scoring_node_token("", True) == ""
    with pytest.raises(SystemExit):
        ln._scoring_node_token("", False)
    assert ln._parse_lanes("22,21") == [21, 22]
    for value in (None, "", "21", "21,23", "22,23", "21,22,23"):
        with pytest.raises(SystemExit):
            ln._parse_lanes(value)


def run_scenario(scenario_coro_fn):
    """Run lane_node.main() + a scenario coroutine on a private loop.

    The scenario gets (ln, main_task) and drives/asserts; when it returns,
    main_task is cancelled (the SIGTERM path) and reaped. Returns whatever
    the scenario returned.
    """
    ln = fresh_lane_node()
    loop = asyncio.new_event_loop()
    # add_signal_handler is Unix-only; the handler's body is exactly
    # main_task.cancel(), which the scenarios invoke directly.
    loop.add_signal_handler = lambda *a, **k: None
    asyncio.set_event_loop(loop)
    try:
        async def driver():
            main_task = asyncio.ensure_future(ln.main())
            try:
                return await scenario_coro_fn(ln, main_task)
            finally:
                main_task.cancel()
                try:
                    await main_task
                except (asyncio.CancelledError, Exception):
                    pass
        result = loop.run_until_complete(driver())
        # Let any stragglers (there should be none) surface loudly.
        leftovers = [t for t in asyncio.all_tasks(loop) if not t.done()]
        assert_true(not leftovers, f"tasks leaked past main(): {leftovers}")
        return ln, result
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def max_kick_gap(on_times):
    return max((b - a for a, b in zip(on_times, on_times[1:])), default=0.0)


async def wait_until(cond, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"FAIL [timeout waiting for: {what}]")


# ---------------------------------------------------------------
# Test 1 — server unreachable: kicks continue through refusal/backoff
# ---------------------------------------------------------------
def test_kicks_survive_unreachable_server():
    async def scenario(ln, main_task):
        await asyncio.sleep(3.5)
        wd = ln.WATCHDOG_KICK
        ons = wd.on_times()
        assert_true(len(ons) >= 3,
                    f"expected >=3 kicks in 3.5s of server-down, got {len(ons)}")
        assert_true(max_kick_gap(ons) < NE555_WINDOW_S,
                    f"kick gap {max_kick_gap(ons):.2f}s >= {NE555_WINDOW_S}s "
                    f"while server unreachable")
        assert_true(CONNECT_REFUSALS[0] >= 1,
                    "fake server never refused — WS was not actually down")
        assert_true(not main_task.done(),
                    f"main() died during server outage: {main_task}")

    run_scenario(scenario)
    print("ok  test_kicks_survive_unreachable_server")


# ---------------------------------------------------------------
# Test 2 — WS dies mid-session: kicks bridge the drop; reconnect gets a
#           fresh (single, non-orphaned) event_sender
# ---------------------------------------------------------------
def test_kicks_survive_ws_death_and_no_orphan_sender():
    ws1 = None
    ws2 = None

    async def scenario(ln, main_task):
        nonlocal ws1, ws2
        # asyncio.Event binds to the running loop on first await in 3.9-ish
        # codepaths; construct the fakes inside the loop to be safe.
        ws1 = FakeWS("ws1")
        ws2 = FakeWS("ws2")
        WS_SCRIPT[:] = [ws1, ws2]

        # ws1 connects (hello lands), runs ~1.5s, then dies.
        await wait_until(lambda: len(ws1.sent) >= 1, 3.0, "hello on ws1")
        await asyncio.sleep(1.5)
        ws1.kill()

        # Reconnect happens after the 5s backoff → hello on ws2.
        await wait_until(lambda: len(ws2.sent) >= 1, 10.0, "hello on ws2")

        # Queue one ball event now that ws2 is live. Exactly ONE copy must
        # go out, on ws2. (Pre-fix: the orphaned event_sender from ws1 is
        # first in the queue's waiter list — it steals the event and burns
        # it on the dead socket.)
        marker = ln._encode_scoring_event(
            ln.Msg.BALL_EVENT, lane=ln.LANES[0], pin_mask=None,
            awaiting_manual=True, test_marker="wdog-test-2")
        assert_true(await ln._admit_scoring_event(marker),
                    "marker was not admitted to the durable scoring outbox")
        await wait_until(
            lambda: sum("wdog-test-2" in m for m in ws2.sent) >= 1,
            3.0, "marker event delivered on ws2")
        await asyncio.sleep(0.3)  # would catch a double-send
        n1 = sum("wdog-test-2" in m for m in ws1.sent)
        n2 = sum("wdog-test-2" in m for m in ws2.sent)
        assert_true(n1 == 0, f"event leaked to the DEAD ws1 ({n1} copies)")
        assert_true(n2 == 1, f"expected exactly 1 copy on ws2, got {n2}")

        # Kicks never gapped across death + 5s backoff + reconnect.
        ons = ln.WATCHDOG_KICK.on_times()
        assert_true(max_kick_gap(ons) < NE555_WINDOW_S,
                    f"kick gap {max_kick_gap(ons):.2f}s >= {NE555_WINDOW_S}s "
                    f"across the WS drop/reconnect")
        assert_true(not main_task.done(),
                    f"main() died across the reconnect: {main_task}")

    run_scenario(scenario)
    print("ok  test_kicks_survive_ws_death_and_no_orphan_sender")


# ---------------------------------------------------------------
# Test 3 — daemon kill stops kicks; pin ends LOW + closed; relays
#           driven LOW before their devices close
# ---------------------------------------------------------------
def test_daemon_kill_stops_kicks_and_safes_outputs():
    async def scenario(ln, main_task):
        await asyncio.sleep(2.5)
        wd = ln.WATCHDOG_KICK
        assert_true(len(wd.on_times()) >= 2, "no kicks before the kill")

        # SIGTERM path: the registered handler's body is main_task.cancel().
        main_task.cancel()
        try:
            await main_task
        except asyncio.CancelledError:
            pass

        kicks_at_death = len(wd.on_times())
        await asyncio.sleep(1.5)   # > one kick period
        assert_true(len(wd.on_times()) == kicks_at_death,
                    "kicks CONTINUED after daemon death — watchdog defeated")

        # Kick pin: LOW and closed, in on -> off -> close order.
        assert_true(wd.closed, "watchdog pin not closed on shutdown")
        assert_true(not wd.is_lit, "watchdog pin left HIGH on shutdown")
        wd_last_on = max(t for t, e in wd.events if e == 'on')
        wd_last_off = max(t for t, e in wd.events if e == 'off')
        wd_close = max(t for t, e in wd.events if e == 'close')
        assert_true(wd_last_off >= wd_last_on and wd_close >= wd_last_off,
                    "watchdog pin not off-then-closed after the last kick")

        # Every relay output: driven LOW, then closed (fail-safe order).
        for lane in ln.LANES:
            for name, dev in (("cycle", ln.PINSETTER_CYCLE[lane]),
                              ("power", ln.PINSETTER_POWER[lane])):
                assert_true(not dev.is_lit, f"L{lane} {name} left HIGH")
                assert_true(dev.closed, f"L{lane} {name} not closed")
                evs = [e for _, e in dev.events]
                assert_true('off' in evs and evs.index('off') < evs.index('close'),
                            f"L{lane} {name}: close before off ({evs})")
            for dev in (ln.BALL_DETECT[lane], ln.BALL2_DETECT[lane],
                        ln.DIELL_LEFT[lane], ln.DIELL_RIGHT[lane]):
                assert_true(dev.closed, f"L{lane} input pin {dev.pin} not closed")

        # Relay LOW must precede device-close phase: the LAST 'off' across
        # all relays happens no later than the FIRST 'close' of any device.
        last_off = max(t for lane in ln.LANES
                       for dev in (ln.PINSETTER_CYCLE[lane], ln.PINSETTER_POWER[lane])
                       for t, e in dev.events if e == 'off')
        first_close = min(t for lane in ln.LANES
                          for dev in (ln.PINSETTER_CYCLE[lane], ln.PINSETTER_POWER[lane])
                          for t, e in dev.events if e == 'close')
        assert_true(last_off <= first_close,
                    "a relay device was closed before all relays were driven LOW")

    run_scenario(scenario)
    print("ok  test_daemon_kill_stops_kicks_and_safes_outputs")


def test_camera_init_failure_is_immediately_unhealthy_on_both_lanes():
    ln = fresh_lane_node()

    class CaptureWriter:
        def __init__(self):
            self.events = []

        def emit(self, event):
            self.events.append(event)
            return True

    class FailedCamera:
        def __init__(self, **_kwargs):
            raise RuntimeError("forced init failure")

    ln.SCORING_MODE = "camera"
    ln.camera.PairCamera = FailedCamera
    ln._init_camera()
    assert_true(ln._last_camera_health["ok"] is False,
                "camera init failure started false-green")
    assert_true(ln._last_camera_health["code"] == "dead",
                "camera init failure did not record dead state")

    writer = CaptureWriter()
    ln._DIAG_WRITER = writer
    ln._health_drop_hop = lambda _health: None
    ln._cam_health_warned = False
    asyncio.run(ln._camera_health_probe_once())
    alerts = [event for event in writer.events
              if event.event_type == "camera_health"]
    assert_true(
        [(event.lane_id, event.severity, event.code) for event in alerts]
        == [(21, "warn", "dead"), (22, "warn", "dead")],
        f"pair-wide immediate camera fault missing: {alerts!r}")
    print("ok  test_camera_init_failure_is_immediately_unhealthy_on_both_lanes")


def test_camera_timeout_latches_manual_without_worker_accumulation():
    ln = fresh_lane_node()

    class CaptureWriter:
        def __init__(self):
            self.events = []

        def emit(self, event):
            self.events.append(event)
            return True

    calls = {"score": 0, "health": 0}
    published = []
    loop_errors = []

    def slow_capture(_lane):
        calls["score"] += 1
        time.sleep(0.20)
        raise RuntimeError("late native capture failure")

    class Camera:
        ready = True

        def frame_health(self):
            calls["health"] += 1
            return {"ok": True, "grabbed": True}

    async def scenario():
        ln.SCORING_MODE = "camera"
        ln.camera.SETTLE_S = 0
        ln._PAIR_CAMERA = Camera()
        ln.detect_current_pins = slow_capture
        ln._DIAG_WRITER = CaptureWriter()
        ln._health_drop_hop = lambda health: published.append(dict(health))
        ln._cam_health_warned = False
        ln._camera_poisoned = False
        ln._camera_poison_reason = None
        ln._camera_worker_task = None
        ln.event_queue = asyncio.Queue()
        ln.main_loop = asyncio.get_running_loop()
        ln.main_loop.set_exception_handler(
            lambda _loop, context: loop_errors.append(context))
        os.environ[ln.CAM_CAPTURE_TIMEOUT_ENV] = "0.05"

        ln._capture_in_flight[21] = True
        await ln._settle_capture_emit(21)
        first = json.loads(await ln.event_queue.get())
        assert_true(first["awaiting_manual"] is True,
                    "timed-out ball did not enter manual fallback")
        assert_true(ln._camera_poisoned is True,
                    "camera timeout did not latch camera unavailable")
        assert_true(ln._last_camera_health["ok"] is False
                    and ln._last_camera_health["code"] == "capture_stalled",
                    "timeout left camera health green")
        retained_worker = ln._camera_worker_task
        assert_true(retained_worker is not None,
                    "timed-out native worker was forgotten")

        # A second ball must not submit another native call.
        ln._capture_in_flight[22] = True
        await ln._settle_capture_emit(22)
        second = json.loads(await ln.event_queue.get())
        assert_true(second["awaiting_manual"] is True,
                    "poisoned camera did not keep manual fallback")
        assert_true(calls["score"] == 1,
                    f"camera workers accumulated: {calls['score']}")
        assert_true(ln._camera_worker_task is retained_worker,
                    "timed-out worker supervision was replaced")

        # Health polling must preserve the fault and never race the worker.
        await ln._camera_health_probe_once()
        assert_true(calls["health"] == 0,
                    "health probe raced a timed-out camera worker")
        alerts = [
            event for event in ln._DIAG_WRITER.events
            if event.event_type == "camera_health"
            and event.code == "capture_stalled"]
        assert_true(
            [(event.lane_id, event.severity) for event in alerts]
            == [(21, "warn"), (22, "warn")],
            f"capture-stalled episode was not pair-wide/once: {alerts!r}")
        assert_true(any(not health["ok"] for health in published),
                    "capture timeout was not published to shared health")
        await asyncio.sleep(0.25)  # let finite test worker return cleanly
        assert_true(loop_errors == [],
                    f"late worker exception was not consumed: {loop_errors!r}")

    try:
        import json
        asyncio.run(scenario())
    finally:
        os.environ.pop("WSL_CAM_CAPTURE_TIMEOUT_S", None)
    print("ok  test_camera_timeout_latches_manual_without_worker_accumulation")


def test_scoring_unit_restart_gap_exceeds_watchdog_expiry():
    unit = open(
        os.path.join(REPO, "systemd", "lane-node.service"),
        encoding="utf-8").read()
    assert_true("RestartSec=15" in unit,
                "Track-A restart can resume kicks before NE555 expiry")
    assert_true("StartLimitIntervalSec=120" in unit
                and "StartLimitBurst=4" in unit,
                "Track-A crash loop is not bounded")
    print("ok  test_scoring_unit_restart_gap_exceeds_watchdog_expiry")


class FiniteFrameSocket:
    """Minimal finite inbound stream for command_handler protocol tests."""

    def __init__(self, frames):
        self.frames = iter(frames)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.frames)
        except StopIteration:
            raise StopAsyncIteration


def _ack_frame(ln, session_id, seq, committed_at):
    fields = {
        "type": ln.Msg.HEARTBEAT_ACK,
        "node": ln.NODE_ID,
        "scoring_session_id": session_id,
        "heartbeat_seq": seq,
        "committed_at": committed_at,
        "scoring_epochs": {
            str(lane): ln._scoring_epochs[lane] for lane in ln.LANES
        },
    }
    if ln.LANE_NODE_TOKEN:
        fields["token"] = ln.LANE_NODE_TOKEN
    return json.dumps(fields)


def _fixed_scoring_status(session_id, heartbeat_seq):
    return {
        "scoring_boot_id": "test-boot",
        "scoring_session_id": session_id,
        "heartbeat_seq": heartbeat_seq,
        "scoring_mode": "manual",
        "camera_calibrated": False,
        "camera_ok": False,
        "camera_code": "manual",
        "outbox": {
            "cursor_ok": True,
            "error": False,
            "oldest_unsent_age_s": None,
            "backlog": 0,
            "backlog_bytes": 0,
            "pending_writes": 0,
            "dropped": 0,
            "quarantined": 0,
            "cycles_quarantined": 0,
            "post_errors": 0,
            "write_errors": 0,
            "sink_errors": 0,
        },
        "node_ball_lockout_s": 8.0,
    }


def test_heartbeat_no_ack_trips_connection_deadman_once():
    ln = fresh_lane_node()
    ack_state = {
        "session_id": "no-ack-session",
        "sent_seq": 0,
        # Model a valid HELLO ACK so this proves the steady-state heartbeat
        # boundary, not merely a missing registration receipt.
        "acked_seq": 0,
    }
    sent = []
    diagnostics = []
    original_sleep = ln.asyncio.sleep
    original_payload = ln._scoring_status_payload
    original_diag = ln._diag_emit_lanes

    async def no_delay(_seconds):
        return None

    async def fixed_payload(session_id, heartbeat_seq):
        return _fixed_scoring_status(session_id, heartbeat_seq)

    class SilentServerSocket:
        async def send(self, raw):
            sent.append(json.loads(raw)["heartbeat_seq"])

    async def scenario(state):
        try:
            await ln.heartbeat_loop(SilentServerSocket(), state)
        except ConnectionError as exc:
            assert_true(
                "heartbeat ACK stalled" in str(exc),
                "dead-man raised the wrong connection failure")
            return
        raise AssertionError("heartbeat loop did not fail a no-ACK connection")

    try:
        ln.asyncio.sleep = no_delay
        ln._scoring_status_payload = fixed_payload
        ln._diag_emit_lanes = lambda *a, **kw: diagnostics.append((a, kw))
        ln._scoring_ack_stalled = False
        asyncio.run(scenario(ack_state))
        assert_true(
            sent == [1, 2, 3],
            "dead-man did not allow exactly the bounded three-heartbeat ACK lag")
        # A persistently non-ACKing server causes another connection attempt,
        # but remains the same fault episode and must not flood the outbox.
        asyncio.run(scenario({
            "session_id": "no-ack-session-reconnect",
            "sent_seq": 0,
            "acked_seq": 0,
        }))
    finally:
        ln.asyncio.sleep = original_sleep
        ln._scoring_status_payload = original_payload
        ln._diag_emit_lanes = original_diag

    assert_true(
        sent == [1, 2, 3, 1, 2, 3],
        "reconnect did not retain the same bounded ACK-lag behavior")
    assert_true(len(diagnostics) == 1,
                "one ACK-stall episode must emit exactly one diagnostic")
    args, kwargs = diagnostics[0]
    assert_true(args[:2] == ("fault", "scoring_server_ack_stalled"),
                "ACK stall diagnostic did not use its typed event")
    assert_true(kwargs["code"] == "scoring_server_ack_stalled",
                "ACK stall diagnostic code is not stable")
    assert_true(kwargs["detail"]["ack_lag"] == 3,
                "ACK stall diagnostic omitted the exact sequence lag")
    assert_true(ln._scoring_ack_stalled is True,
                "ACK stall episode latch was not retained across reconnect")
    print("ok  test_heartbeat_no_ack_trips_connection_deadman_once")


def test_heartbeat_delayed_ack_below_threshold_keeps_connection_alive():
    ln = fresh_lane_node()
    ack_state = {
        "session_id": "delayed-ack-session",
        "sent_seq": 0,
        "acked_seq": 0,
    }
    sent = []
    diagnostics = []
    committed_at = "2026-07-23T00:00:00Z"
    original_sleep = ln.asyncio.sleep
    original_payload = ln._scoring_status_payload
    original_diag = ln._diag_emit_lanes

    async def no_delay(_seconds):
        return None

    async def fixed_payload(session_id, heartbeat_seq):
        return _fixed_scoring_status(session_id, heartbeat_seq)

    class DelayedAckSocket:
        async def send(self, raw):
            seq = json.loads(raw)["heartbeat_seq"]
            sent.append(seq)
            if seq == 2:
                await ln.command_handler(FiniteFrameSocket([
                    _ack_frame(
                        ln, ack_state["session_id"], seq, committed_at)
                ]), ack_state)
            if seq == 4:
                raise ConnectionError("test completed below lag threshold")

    async def scenario():
        try:
            await ln.heartbeat_loop(DelayedAckSocket(), ack_state)
        except ConnectionError as exc:
            assert_true(
                str(exc) == "test completed below lag threshold",
                "delayed ACK unexpectedly tripped the dead-man")

    try:
        ln.asyncio.sleep = no_delay
        ln._scoring_status_payload = fixed_payload
        ln._diag_emit_lanes = lambda *a, **kw: diagnostics.append((a, kw))
        ln._scoring_ack_stalled = False
        asyncio.run(scenario())
    finally:
        ln.asyncio.sleep = original_sleep
        ln._scoring_status_payload = original_payload
        ln._diag_emit_lanes = original_diag

    assert_true(sent == [1, 2, 3, 4],
                "delayed valid ACK did not reset the bounded lag")
    assert_true(ack_state["acked_seq"] == 2,
                "delayed valid ACK did not advance ACK state")
    assert_true(not diagnostics,
                "sub-threshold delayed ACK emitted a false stall diagnostic")
    print("ok  test_heartbeat_delayed_ack_below_threshold_keeps_connection_alive")


def test_heartbeat_ack_after_stall_emits_recovery_once():
    ln = fresh_lane_node()
    ack_state = {
        "session_id": "recovered-ack-session",
        "sent_seq": 0,
        "acked_seq": -1,
    }
    committed_at = "2026-07-23T00:00:00Z"
    diagnostics = []
    original_diag = ln._diag_emit_lanes
    try:
        ln._diag_emit_lanes = lambda *a, **kw: diagnostics.append((a, kw))
        ln._scoring_ack_stalled = True
        asyncio.run(ln.command_handler(FiniteFrameSocket([
            _ack_frame(ln, ack_state["session_id"], 0, committed_at),
        ]), ack_state))
    finally:
        ln._diag_emit_lanes = original_diag

    assert_true(ack_state["acked_seq"] == 0,
                "valid reconnect ACK did not advance ACK state")
    assert_true(ln._scoring_ack_stalled is False,
                "valid reconnect ACK did not clear the stall episode latch")
    assert_true(len(diagnostics) == 1,
                "valid reconnect ACK must emit one recovery breadcrumb")
    args, kwargs = diagnostics[0]
    assert_true(args[:2] == ("info", "recovered"),
                "ACK recovery did not use the safe recovery event type")
    assert_true(kwargs["code"] == "scoring_server_ack_stalled",
                "ACK recovery does not bind to the stalled incident code")
    assert_true(
        kwargs["detail"]["recovery"] == "durably_committed_heartbeat_ack",
        "ACK recovery lacks durable-commit evidence")
    print("ok  test_heartbeat_ack_after_stall_emits_recovery_once")


def test_heartbeat_ack_can_interleave_inside_send():
    ln = fresh_lane_node()
    ack_state = {
        "session_id": "ack-race-session",
        "sent_seq": 0,
        "acked_seq": -1,
    }
    committed_at = "2026-07-23T00:00:00+00:00"
    original_sleep = ln.asyncio.sleep
    original_payload = ln._scoring_status_payload

    async def no_delay(_seconds):
        return None

    async def fixed_payload(session_id, heartbeat_seq):
        return {
            "scoring_boot_id": "test-boot",
            "scoring_session_id": session_id,
            "heartbeat_seq": heartbeat_seq,
            "scoring_mode": "manual",
            "camera_calibrated": False,
            "camera_ok": False,
            "camera_code": "manual",
            "outbox": {
                "cursor_ok": True,
                "error": False,
                "oldest_unsent_age_s": None,
                "backlog": 0,
                "backlog_bytes": 0,
                "pending_writes": 0,
                "dropped": 0,
                "quarantined": 0,
                "cycles_quarantined": 0,
                "post_errors": 0,
                "write_errors": 0,
                "sink_errors": 0,
            },
            "node_ball_lockout_s": 8.0,
        }

    class InterleavingSocket:
        async def send(self, raw):
            sent = json.loads(raw)
            assert sent["heartbeat_seq"] == 1
            inbound = FiniteFrameSocket([
                _ack_frame(
                    ln, ack_state["session_id"], 1, committed_at)
            ])
            # Deterministically deliver the ACK while heartbeat_loop is
            # suspended in this send() call.
            await ln.command_handler(inbound, ack_state)
            raise ConnectionError("stop after first heartbeat")

    async def scenario():
        try:
            await ln.heartbeat_loop(InterleavingSocket(), ack_state)
        except ConnectionError:
            pass

    try:
        ln.asyncio.sleep = no_delay
        ln._scoring_status_payload = fixed_payload
        asyncio.run(scenario())
    finally:
        ln.asyncio.sleep = original_sleep
        ln._scoring_status_payload = original_payload

    assert_true(ack_state["acked_seq"] == 1,
                "valid interleaved ACK was rejected as ahead of sent_seq")
    assert_true(ln._last_scoring_ack["committed_at"] == committed_at,
                "accepted interleaved ACK was not retained")
    print("ok  test_heartbeat_ack_can_interleave_inside_send")


def test_heartbeat_ack_requires_strict_utc_committed_at():
    ln = fresh_lane_node()
    ack_state = {
        "session_id": "ack-time-session",
        "sent_seq": 1,
        "acked_seq": -1,
    }
    valid = "2026-07-23T00:00:00Z"
    invalid = [
        None,
        "",
        " 2026-07-23T00:00:00Z",
        "2026-07-23",
        "not-a-timestamp",
        "2026-07-23T01:00:00+01:00",
    ]
    frames = [
        _ack_frame(ln, ack_state["session_id"], 1, value)
        for value in invalid
    ]
    frames.append(_ack_frame(ln, ack_state["session_id"], 1, valid))
    asyncio.run(ln.command_handler(FiniteFrameSocket(frames), ack_state))
    assert_true(ack_state["acked_seq"] == 1,
                "valid UTC committed_at was not accepted")
    assert_true(ln._last_scoring_ack["committed_at"] == valid,
                "invalid committed_at mutated retained ACK state")
    print("ok  test_heartbeat_ack_requires_strict_utc_committed_at")


if __name__ == '__main__':
    test_kicks_survive_unreachable_server()
    test_kicks_survive_ws_death_and_no_orphan_sender()
    test_daemon_kill_stops_kicks_and_safes_outputs()
    test_camera_init_failure_is_immediately_unhealthy_on_both_lanes()
    test_camera_timeout_latches_manual_without_worker_accumulation()
    test_scoring_unit_restart_gap_exceeds_watchdog_expiry()
    test_heartbeat_no_ack_trips_connection_deadman_once()
    test_heartbeat_delayed_ack_below_threshold_keeps_connection_alive()
    test_heartbeat_ack_after_stall_emits_recovery_once()
    test_heartbeat_ack_can_interleave_inside_send()
    test_heartbeat_ack_requires_strict_utc_committed_at()
    print("\nALL WATCHDOG-KICK TESTS PASSED")
