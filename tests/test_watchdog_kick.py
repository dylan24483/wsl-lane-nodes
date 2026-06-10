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
import os
import sys
import time
import types

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
_ws_asyncio = types.ModuleType('websockets.asyncio')
_ws_asyncio.client = _ws_client
_ws_root = types.ModuleType('websockets')
_ws_root.asyncio = _ws_asyncio
sys.modules['websockets'] = _ws_root
sys.modules['websockets.asyncio'] = _ws_asyncio
sys.modules['websockets.asyncio.client'] = _ws_client


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
    sys.modules.pop('lane_node', None)   # force re-exec: fresh fake devices/state
    import lane_node
    return lane_node


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
        marker = ln.encode(ln.Msg.BALL_EVENT, lane=ln.LANES[0], pin_mask=None,
                           awaiting_manual=True, test_marker="wdog-test-2")
        ln.event_queue.put_nowait(marker)
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


if __name__ == '__main__':
    test_kicks_survive_unreachable_server()
    test_kicks_survive_ws_death_and_no_orphan_sender()
    test_daemon_kill_stops_kicks_and_safes_outputs()
    print("\nALL WATCHDOG-KICK TESTS PASSED")
