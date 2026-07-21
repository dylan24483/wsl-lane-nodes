"""Contract tests for the isolated lane-FX transport and event payload."""

import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
for path in (str(REPO_ROOT), str(SERVER_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

# The production server has websockets==16.0 pinned, but the Windows audit
# interpreter used by this suite may not. These tests exercise the handlers
# directly, so a minimal import stub is sufficient when the dependency is
# absent; the real package path remains untouched when installed.
try:
    from websockets.asyncio.server import serve as _real_serve  # noqa: F401
except ModuleNotFoundError:
    _ws_server = types.ModuleType("websockets.asyncio.server")
    _ws_server.serve = None
    _ws_asyncio = types.ModuleType("websockets.asyncio")
    _ws_asyncio.server = _ws_server
    _ws_root = types.ModuleType("websockets")
    _ws_root.asyncio = _ws_asyncio
    sys.modules["websockets"] = _ws_root
    sys.modules["websockets.asyncio"] = _ws_asyncio
    sys.modules["websockets.asyncio.server"] = _ws_server

# lane_node_server loads persisted state at import time. Point it at an
# isolated path before importing so this suite can never touch live state.
_STATE_TMP = tempfile.TemporaryDirectory()
os.environ["STATE_DB_PATH"] = str(Path(_STATE_TMP.name) / "lane_state.db")
os.environ.pop("LANE_FX_ENABLED", None)

import lane_node_server as server  # noqa: E402
from lane_fx_gateway import GatewayState  # noqa: E402
from lane_fx_protocol import LaneFxPublisher  # noqa: E402
from wsl_scoring_engine import LaneScoring  # noqa: E402

# _reset_server_lane installs fake publishers on the shared server module;
# put the real one back when this module is done so later test modules
# (e.g. test_machine_diagnostics hitting /api/health) see the real object.
_REAL_FX_PUBLISHER = server.fx_publisher


def teardown_module(_module):
    server.fx_publisher = _REAL_FX_PUBLISHER


class CapturePublisher:
    def __init__(self):
        self.events = []

    def emit(self, payload):
        self.events.append(payload)
        return True

    # /api/health calls fx_publisher.status() — a fake without it 500s the
    # health endpoint for any test that runs while a fake is installed.
    def status(self):
        return {"enabled": False, "transport": "capture-fake",
                "target": "none", "schema_version": 0}


class RaisingPublisher:
    def emit(self, payload):
        raise RuntimeError("synthetic FX transport failure")

    def status(self):
        return {"enabled": False, "transport": "raising-fake",
                "target": "none", "schema_version": 0}


class FakeDatagramSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, target):
        self.sent.append((data, target))
        return len(data)


class FakeWebSocket:
    def __init__(self, hello):
        self.hello = hello
        self.sent = []
        self.closed = None

    async def recv(self):
        return json.dumps(self.hello)

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def close(self, code, reason):
        self.closed = (code, reason)

    async def wait_closed(self):
        await asyncio.Future()


class FakeLaneNodeSocket:
    def __init__(self, frames, order):
        self.frames = list(frames)
        self.order = order
        self.remote_address = ("127.0.0.1", 12345)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return json.dumps(self.frames.pop(0))

    async def send(self, message):
        decoded = json.loads(message)
        self.order.append(decoded["type"])

    async def close(self, code, reason):
        self.order.append(f"close:{code}")


def _reset_server_lane(publisher=None):
    with server.state_lock:
        server.lane_scoring.clear()
        server.ball_counters.clear()
        server.pending_foul.clear()
    server.fx_publisher = publisher or CapturePublisher()


def _open_single_bowler_lane(lane=21, name="A"):
    scorer = LaneScoring(lane)
    scorer.add_bowler(name, number=1)
    scorer.start()
    with server.state_lock:
        server.lane_scoring[lane] = scorer
    return scorer


def test_publisher_is_disabled_by_default_and_never_throws():
    sock = FakeDatagramSocket()
    disabled = LaneFxPublisher(enabled=False, sock=sock)
    assert disabled.emit({"type": "ball"}) is False
    assert sock.sent == []
    assert disabled.emit(None) is False


def test_publisher_adds_schema_and_source_timestamp():
    sock = FakeDatagramSocket()
    publisher = LaneFxPublisher(enabled=True,
                                target=("127.0.0.1", 8768), sock=sock)
    assert publisher.emit({"type": "test", "lane": 21}) is True
    raw, target = sock.sent[0]
    event = json.loads(raw)
    assert target == ("127.0.0.1", 8768)
    assert event["schema_version"] == 1
    assert isinstance(event["source_ts"], float)


def test_ball_payload_uses_actual_thrower_and_boolean_split():
    capture = CapturePublisher()
    _reset_server_lane(capture)
    scorer = LaneScoring(21)
    scorer.add_bowler("ALICE", number=1)
    scorer.add_bowler("BOB", number=2)
    scorer.start()
    with server.state_lock:
        server.lane_scoring[21] = scorer

    _, _, _, event = server._process_ball_event(21, pin_mask=0)
    assert event["bowler"]["name"] == "ALICE"
    assert event["next_bowler"] == "BOB"
    assert event["is_strike"] is True
    assert event["split"] is False
    assert event["strike_streak"] == 1

    # Pins 7 and 10 standing is a split. The engine's split contract is bool;
    # standing carries the actual leave rather than a fabricated label.
    _reset_server_lane(capture := CapturePublisher())
    _open_single_bowler_lane()
    _, _, _, event = server._process_ball_event(
        21, pin_mask=(1 << 6) | (1 << 9))
    assert event["split"] is True
    assert event["standing"] == [7, 10]


def test_second_ball_pins_down_is_incremental_not_total_absent():
    capture = CapturePublisher()
    _reset_server_lane(capture)
    _open_single_bowler_lane()
    server._process_ball_event(21, pin_mask=0x1F)  # five down, five standing
    _, _, _, event = server._process_ball_event(
        21, pin_mask=0)                            # remaining five down
    assert event["pins_down"] == 5
    assert event["standing"] == []
    assert event["is_spare"] is True


def test_final_ball_survives_engine_immediate_new_game_reset():
    capture = CapturePublisher()
    _reset_server_lane(capture)
    scorer = _open_single_bowler_lane(name="PERFECT")
    event = None
    for _ in range(12):
        _, _, _, event = server._process_ball_event(21, pin_mask=0)
    assert event["frame_number"] == 10
    assert event["ball_in_frame"] == 3
    assert event["game_over"] is True
    assert event["game_number"] == 1
    assert event["running_total"] == 300
    assert event["strike_streak"] == 12
    assert scorer.game_number == 2  # engine has already rolled over


def test_fx_builder_and_publisher_failures_cannot_block_scoring():
    _reset_server_lane(CapturePublisher())
    scorer = _open_single_bowler_lane()
    original_builder = server._build_ball_fx_payload
    try:
        def broken_builder(*args, **kwargs):
            raise RuntimeError("synthetic FX payload failure")

        server._build_ball_fx_payload = broken_builder
        bowl, _, _, event = server._process_ball_event(21, pin_mask=0x1F)
        assert bowl is not None
        assert event is None
        assert len(scorer.bowlers[0].frames[0].bowls) == 1
    finally:
        server._build_ball_fx_payload = original_builder

    _reset_server_lane(RaisingPublisher())
    scorer = _open_single_bowler_lane()
    bowl, _, _, event = server._process_ball_event(21, pin_mask=0)
    assert bowl is not None
    assert scorer.bowlers[0].frames[0].is_strike is True
    # Even a future publisher regression is contained at this explicit
    # boundary and cannot propagate back into scoring/control.
    assert server._emit_fx_event(event) is False


def test_camera_ball_sends_cycle_before_cosmetic_event():
    async def run_case():
        _reset_server_lane(CapturePublisher())
        _open_single_bowler_lane()
        order = []
        websocket = FakeLaneNodeSocket([
            {"type": "hello", "node": "test-node",
             "lanes": [21], "protocol_version": server.PROTOCOL_VERSION},
            {"type": "ball_event", "lane": 21, "pin_mask": 0},
        ], order)
        original_emit = server._emit_fx_event
        try:
            server._emit_fx_event = lambda payload: order.append("fx")
            await server.handle_node(websocket)
        finally:
            server._emit_fx_event = original_emit
        assert order[-2:] == [server.Msg.CYCLE, "fx"]

    asyncio.run(run_case())


def test_gateway_stream_epoch_and_replay_contract():
    async def run_case():
        state = GatewayState(recent_max=4, token="secret")
        first = state.publish({"type": "ball", "lane": 21})
        ws = FakeWebSocket({
            "type": "hello",
            "token": "secret",
            "stream_id": state.stream_id,
            "last_seq": 0,
        })
        task = asyncio.create_task(state.handle_client(ws))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert ws.sent[0]["type"] == "stream"
        assert ws.sent[0]["resync_required"] is False
        assert ws.sent[1]["seq"] == first["seq"]
        state.publish({"type": "ball", "lane": 22})
        await asyncio.sleep(0.01)
        assert ws.sent[-1]["seq"] == 2
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # A renderer holding a sequence from an old gateway process must reset
        # immediately instead of dropping new low-numbered events forever.
        restarted = GatewayState(recent_max=4, token="secret")
        ws2 = FakeWebSocket({
            "type": "hello",
            "token": "secret",
            "stream_id": state.stream_id,
            "last_seq": 999,
        })
        task2 = asyncio.create_task(restarted.handle_client(ws2))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert ws2.sent[0]["resync_required"] is True
        assert ws2.sent[0]["reason"] == "stream_changed_or_first_connect"
        task2.cancel()
        try:
            await task2
        except asyncio.CancelledError:
            pass

    asyncio.run(run_case())


def test_gateway_requires_separate_read_only_token_when_configured():
    async def run_case():
        state = GatewayState(token="fx-only-secret")
        ws = FakeWebSocket({"type": "hello", "token": "wrong"})
        await state.handle_client(ws)
        assert ws.closed == (4401, "auth failed")

    asyncio.run(run_case())


def test_gateway_marks_replay_window_gap_for_full_resync():
    async def run_case():
        state = GatewayState(recent_max=2, token="secret")
        for lane in (21, 22, 23):
            state.publish({"type": "ball", "lane": lane})
        ws = FakeWebSocket({
            "type": "hello",
            "token": "secret",
            "stream_id": state.stream_id,
            "last_seq": 0,
        })
        task = asyncio.create_task(state.handle_client(ws))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert ws.sent[0]["resync_required"] is True
        assert ws.sent[0]["reason"] == "replay_window_exceeded"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_case())


def test_gateway_disconnects_instead_of_silently_dropping_on_overflow():
    async def run_case():
        state = GatewayState(queue_max=1)
        ws = FakeWebSocket({"type": "hello"})
        state.clients[ws] = asyncio.Queue(maxsize=1)
        state.publish({"type": "ball", "lane": 21})
        state.publish({"type": "ball", "lane": 22})
        await asyncio.sleep(0)
        assert ws not in state.clients
        assert ws.closed == (1013, "lane FX subscriber fell behind")

    asyncio.run(run_case())


def test_transient_heartbeat_and_test_do_not_create_replay_sequence_gaps():
    state = GatewayState(recent_max=4)
    first = state.publish({"type": "ball", "lane": 21})
    heartbeat = state.publish({"type": "heartbeat"})
    test_fire = state.publish({"type": "test", "lane": 21,
                               "event": "strike"})
    second = state.publish({"type": "ball", "lane": 22})
    assert first["seq"] == 1
    assert heartbeat["seq"] is None and heartbeat["transient"] is True
    assert test_fire["seq"] is None and test_fire["transient"] is True
    assert second["seq"] == 2
    assert [event["seq"] for event in state.recent] == [1, 2]
