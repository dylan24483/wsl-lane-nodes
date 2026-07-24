"""Contract tests for the isolated lane-FX transport and event payload."""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

import pytest


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


@pytest.fixture(autouse=True)
def _isolate_scoring_topology(monkeypatch):
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY", "test-pair-21-22=21,22")


@pytest.fixture(autouse=True)
def _drop_orphaned_background_command_tasks():
    """Cross-module isolation (round-4 audit): each case here runs under its
    own asyncio.run() loop. A ball-cycle finalizer task still pending when
    that loop closes can never complete, so it would sit forever in the
    module-global server._background_command_tasks set and poison a later
    module's gather over that set ("future belongs to a different loop").
    Production has one loop for the process lifetime, so this is test-only
    litter — drop it here, at the polluter."""
    yield
    server._background_command_tasks.clear()


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
        self.sent = []
        self.remote_address = ("127.0.0.1", 12345)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return json.dumps(self.frames.pop(0))

    async def send(self, message):
        decoded = json.loads(message)
        self.sent.append(decoded)
        self.order.append(decoded["type"])
        if decoded.get("command_id"):
            self.frames.append({
                "type": server.Msg.COMMAND_ACK,
                "ts": time.time(),
                "command_id": decoded["command_id"],
                "status": "completed",
                "completed_at": time.time(),
            })
        await asyncio.sleep(0)

    async def close(self, code, reason):
        self.order.append(f"close:{code}")


class MutatingLaneNodeSocket(FakeLaneNodeSocket):
    def __init__(self, frames, order, mutate_before_frame):
        super().__init__(frames, order)
        self.mutate_before_frame = mutate_before_frame
        self._index = 0

    async def __anext__(self):
        if self._index == 1:
            self.mutate_before_frame()
        self._index += 1
        return await super().__anext__()


def node_hello(node="test-node", lanes=None, protocol=None, session=None):
    os.environ["WSL_SCORING_NODE_TOPOLOGY"] = f"{node}=21,22"
    return {
        "type": "hello",
        "node": node,
        "lanes": [21, 22] if lanes is None else lanes,
        "protocol_version": (
            server.PROTOCOL_VERSION if protocol is None else protocol),
        "scoring_boot_id": "test-scoring-boot",
        "scoring_session_id": session or f"{node}-session",
        "heartbeat_seq": 0,
        "scoring_mode": "camera",
        "camera_calibrated": True,
        "camera_ok": True,
        "camera_code": "healthy",
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
            "scoring_event_queue_depth": 0,
            "scoring_event_queue_capacity": 128,
            "scoring_event_oldest_age_s": None,
            "scoring_capture_jobs": 0,
            "scoring_capture_oldest_age_s": None,
            "scoring_clock_observed": True,
            "scoring_clock_anomaly_latched": False,
            "scoring_clock_high_water_epoch": 1.0,
            "scoring_clock_observed_epoch": 1.0,
            "scoring_event_durable": True,
            "scoring_event_error": False,
            "scoring_event_overdue": False,
            "scoring_event_drops": 0,
            "scoring_event_expired": 0,
            "scoring_event_max_age_s": 30.0,
        },
        "node_ball_lockout_s": 8.0,
    }


def fake_scoring_commit(touched):
    def commit(lanes, metadata, **_kwargs):
        touched.append(list(lanes))
        return {
            "committed_at": "2026-07-23T00:00:00+00:00",
            "lanes": list(lanes),
            "scoring_session_id": metadata["scoring_session_id"],
            "heartbeat_seq": metadata["heartbeat_seq"],
        }
    return commit


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
    scorer.scoring_epoch = "test-scoring-epoch"
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
            node_hello(),
            {"type": "ball_event", "ts": time.time(),
             "lane": 21, "pin_mask": 0,
             "event_id": "test-ball-event",
             "event_created_at": time.time(),
             "scoring_epoch": "test-scoring-epoch"},
        ], order)
        original_emit = server._emit_fx_event
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit([]))
            server._emit_fx_event = lambda payload: order.append("fx")
            await server.handle_node(websocket)
        finally:
            server._emit_fx_event = original_emit
            server.machine_store.touch_scoring_lanes = original_touch
        assert order.index(server.Msg.CYCLE) < order.index("fx")
        assert server.Msg.SCORING_EVENT_ACK in order

    asyncio.run(run_case())


def test_duplicate_committed_ball_retries_same_cycle_before_receipt():
    async def run_case():
        _reset_server_lane(CapturePublisher())
        scorer = _open_single_bowler_lane()
        created = time.time()
        frame = {
            "type": "ball_event",
            "ts": created,
            "lane": 21,
            "pin_mask": 0,
            "event_id": "committed-ball-cycle-retry",
            "event_created_at": created,
            "scoring_epoch": "test-scoring-epoch",
        }
        server.record_scoring_event_receipt(
            server._scoring_receipt("cycle-retry-node", frame, "accepted"))
        order = []
        websocket = FakeLaneNodeSocket([
            node_hello(
                node="cycle-retry-node",
                session="cycle-retry-session"),
            frame,
        ], order)
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit([]))
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
        assert len(scorer.bowlers[0].frames[0].bowls) == 0
        assert order.count(server.Msg.CYCLE) == 1
        assert order.index(server.Msg.CYCLE) < order.index(
            server.Msg.SCORING_EVENT_ACK)
        cycle = next(
            item for item in websocket.sent
            if item["type"] == server.Msg.CYCLE)
        assert cycle["command_id"] == (
            "ball-cycle:" + hashlib.sha256(
                frame["event_id"].encode("utf-8")).hexdigest())
        assert len(cycle["command_id"]) <= 128
        assert cycle["issued_at"] == created

    asyncio.run(run_case())


def test_old_committed_ball_opens_incident_instead_of_stale_cycle(
        monkeypatch, tmp_path):
    async def run_case():
        monkeypatch.setattr(
            server.state_store_module, "DB_PATH",
            tmp_path / "lane_state.db")
        _reset_server_lane(CapturePublisher())
        _open_single_bowler_lane()
        created = time.time() - (
            server.SCORING_EVENT_AUTO_APPLY_MAX_AGE_S + 1)
        frame = {
            "type": "ball_event",
            "ts": created,
            "lane": 21,
            "pin_mask": 0,
            "event_id": "committed-ball-cycle-expired",
            "event_created_at": created,
            "scoring_epoch": "test-scoring-epoch",
        }
        server.record_scoring_event_receipt(
            server._scoring_receipt("cycle-expired-node", frame, "accepted"))
        order = []
        websocket = FakeLaneNodeSocket([
            node_hello(
                node="cycle-expired-node",
                session="cycle-expired-session"),
            frame,
        ], order)
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit([]))
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
        assert server.Msg.CYCLE not in order
        assert server.Msg.SCORING_EVENT_ACK in order
        incidents = (
            server.state_store_module.pending_diagnostic_incidents())
        assert len(incidents) == 1
        event = json.loads(incidents[0]["payload_json"])
        assert event["severity"] == "fault"
        assert event["code"] == "cycle_delivery_indeterminate"
        assert event["detail"]["reason"] == (
            "authorization_window_expired")
        assert event["detail"]["requires_manual_reconciliation"] is True

    asyncio.run(run_case())


def test_duplicate_ball_ignored_while_closed_never_gains_cycle_side_effect():
    async def run_case():
        _reset_server_lane(CapturePublisher())
        created = time.time()
        frame = {
            "type": "ball_event",
            "ts": created,
            "lane": 21,
            "pin_mask": 0,
            "event_id": "closed-ball-duplicate",
            "event_created_at": created,
            "scoring_epoch": None,
        }
        server.record_scoring_event_receipt(server._scoring_receipt(
            "closed-ball-node", frame, "ignored_lane_closed"))
        order = []
        incidents = []
        websocket = FakeLaneNodeSocket([
            node_hello(
                node="closed-ball-node",
                session="closed-ball-session"),
            frame,
        ], order)
        original_touch = server.machine_store.touch_scoring_lanes
        original_insert = server.machine_store.insert_events
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit([]))
            server.machine_store.insert_events = (
                lambda events: incidents.extend(events))
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
            server.machine_store.insert_events = original_insert
        assert server.Msg.CYCLE not in order
        assert server.Msg.SCORING_EVENT_ACK in order
        assert incidents == []

    asyncio.run(run_case())


def test_first_ball_while_closed_is_persisted_and_never_cycles():
    async def run_case():
        _reset_server_lane(CapturePublisher())
        created = time.time()
        frame = {
            "type": "ball_event",
            "ts": created,
            "lane": 21,
            "pin_mask": 0,
            "event_id": "closed-ball-first-seen",
            "event_created_at": created,
            "scoring_epoch": None,
        }
        order = []
        websocket = FakeLaneNodeSocket([
            node_hello(
                node="closed-first-node",
                session="closed-first-session"),
            frame,
        ], order)
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit([]))
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
        assert server.Msg.CYCLE not in order
        assert server.Msg.SCORING_EVENT_ACK in order
        receipt = server.scoring_event_receipt(frame["event_id"])
        assert receipt["disposition"] == "ignored_lane_closed"

    asyncio.run(run_case())


def test_malformed_scoring_events_have_zero_side_effects():
    now = time.time()
    ball_base = {
        "type": "ball_event",
        "ts": now,
        "lane": 21,
        "pin_mask": 0,
    }
    invalid_ball_frames = [
        {**ball_base, "lane": True},
        {**ball_base, "awaiting_manual": "true"},
        {**ball_base, "pin_mask": True},
        {**ball_base, "pin_mask": "0"},
        {**ball_base, "pin_mask": -1},
        {**ball_base, "pin_mask": 0x400},
        {**ball_base, "pin_mask": None},
        {**ball_base, "pin_mask": 0, "awaiting_manual": True},
        {**ball_base, "unknown": "field"},
        {**ball_base, "ts": now + 301.0},
    ]
    foul_base = {"type": "foul_event", "ts": now, "lane": 21}
    invalid_foul_frames = [
        {**foul_base, "lane": True},
        {**foul_base, "unknown": "field"},
        {**foul_base, "ts": now + 301.0},
    ]

    async def run_case(frame, index):
        publisher = CapturePublisher()
        _reset_server_lane(publisher)
        scorer = _open_single_bowler_lane()
        order = []
        node = f"invalid-event-node-{index}"
        websocket = FakeLaneNodeSocket([
            node_hello(node=node, session=f"invalid-session-{index}"),
            frame,
        ], order)
        original_boot = server.machine_store.accept_scoring_boot
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.accept_scoring_boot = (
                lambda *_args, **_kwargs: None)
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit([]))
            await server.handle_node(websocket)
        finally:
            server.machine_store.accept_scoring_boot = original_boot
            server.machine_store.touch_scoring_lanes = original_touch

        assert order == [server.Msg.HEARTBEAT_ACK]
        assert len(scorer.bowlers[0].frames[0].bowls) == 0
        assert server.ball_counters == {}
        assert server.pending_foul == {}
        assert publisher.events == []

    async def run_all():
        frames = invalid_ball_frames + invalid_foul_frames
        for index, frame in enumerate(frames):
            await run_case(frame, index)

    asyncio.run(run_all())


def test_lane_command_routing_is_current_fresh_owner_only():
    class CountingSocket:
        def __init__(self):
            self.sent = []

        async def send(self, message):
            self.sent.append(message)
            frame = json.loads(message)
            waiter = server._command_ack_waiters[frame["command_id"]]
            waiter["future"].set_result({
                "command_id": frame["command_id"],
                "status": "completed",
                "original_status": None,
                "completed_at": time.time(),
            })

    async def run_case():
        server._routing_lock = None
        no_owner = CountingSocket()
        stale = CountingSocket()
        older = CountingSocket()
        newest = CountingSocket()
        try:
            with server.clients_lock:
                server.clients.clear()
                server.client_metadata.clear()

            assert await server._send_to_current_lane(21, "no-owner") == 0
            assert no_owner.sent == []

            old = time.time() - server.HEARTBEAT_FRESH_S - 1.0
            with server.clients_lock:
                server.clients["stale-node"] = stale
                server.client_metadata["stale-node"] = {
                    "lanes": [21],
                    "connected_at": old,
                    "last_heartbeat": old,
                }
            assert await server._send_to_current_lane(21, "stale") == 0
            assert stale.sent == []

            now = time.time()
            with server.clients_lock:
                server.clients.clear()
                server.client_metadata.clear()
                server.clients.update({
                    "older-node": older,
                    "newest-node": newest,
                })
                server.client_metadata.update({
                    "older-node": {
                        "lanes": [21],
                        "connected_at": now - 2.0,
                        "last_heartbeat": now,
                    },
                    "newest-node": {
                        "lanes": [21],
                        "connected_at": now - 1.0,
                        "last_heartbeat": now,
                    },
                })
            command = server.encode_command(
                server.Msg.RESET, 21, command_id="route-test")
            assert await server._send_to_current_lane(21, command) == 0
            assert older.sent == []
            assert newest.sent == []
        finally:
            with server.clients_lock:
                server.clients.clear()
                server.client_metadata.clear()
            # Never retain a lock bound to asyncio.run()'s now-closed loop.
            server._routing_lock = None

    asyncio.run(run_case())


def test_scoring_hello_must_match_protocol_before_renewing_lease():
    async def run_case():
        order = []
        touched = []
        websocket = FakeLaneNodeSocket([
            node_hello(
                node="wrong-protocol",
                protocol=server.PROTOCOL_VERSION + 1)
        ], order)
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit(touched))
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
        assert order == ["close:4400"]
        assert touched == []
        assert "wrong-protocol" not in server.clients

    asyncio.run(run_case())


def test_scoring_heartbeat_is_bound_to_registered_connection_identity():
    async def run_case():
        order = []
        touched = []
        websocket = FakeLaneNodeSocket([
            node_hello(node="bound-node"),
            {"type": "heartbeat", "node": "spoofed-node"},
        ], order)
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit(touched))
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
        # Valid HELLO renews once; the spoofed heartbeat renews nothing.
        assert touched == [[21, 22]]
        assert order == [server.Msg.HEARTBEAT_ACK]

    asyncio.run(run_case())


def test_superseded_same_id_socket_cannot_renew_scoring_lease():
    async def run_case():
        order = []
        touched = []
        replacement = object()

        def supersede():
            with server.clients_lock:
                server.clients["bound-node"] = replacement

        websocket = MutatingLaneNodeSocket([
            node_hello(node="bound-node"),
            {"type": "heartbeat", "node": "bound-node"},
        ], order, supersede)
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit(touched))
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
            with server.clients_lock:
                server.clients.pop("bound-node", None)
                server.client_metadata.pop("bound-node", None)
        assert touched == [[21, 22]]
        assert order == [server.Msg.HEARTBEAT_ACK, "close:4400"]

    asyncio.run(run_case())


def test_newest_lane_claimant_is_only_inbound_ball_owner():
    async def run_case():
        order = []
        newer_socket = object()

        def add_newer_claimant():
            with server.clients_lock:
                server.clients["newer-node"] = newer_socket
                server.client_metadata["newer-node"] = {
                    "lanes": [21],
                    "protocol_version": server.PROTOCOL_VERSION,
                    "connected_at": time.time() + 10.0,
                    "last_heartbeat": time.time(),
                }

        websocket = MutatingLaneNodeSocket([
            node_hello(node="older-node"),
            {"type": "ball_event", "ts": time.time(),
             "lane": 21, "pin_mask": 0},
        ], order, add_newer_claimant)
        try:
            await server.handle_node(websocket)
        finally:
            with server.clients_lock:
                server.clients.pop("newer-node", None)
                server.client_metadata.pop("newer-node", None)
        assert server.Msg.CYCLE not in order

    asyncio.run(run_case())


def test_scoring_hello_rejects_duplicate_or_out_of_scope_lane_claims():
    async def run_case(lanes):
        order = []
        touched = []
        websocket = FakeLaneNodeSocket([
            node_hello(node="bad-lanes", lanes=lanes)
        ], order)
        original_touch = server.machine_store.touch_scoring_lanes
        try:
            server.machine_store.touch_scoring_lanes = (
                fake_scoring_commit(touched))
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
        assert order == ["close:4400"]
        assert touched == []

    asyncio.run(run_case([21, 21]))
    asyncio.run(run_case([21, 33]))


def test_scoring_lease_commit_failure_closes_connection_fail_closed():
    async def run_case(fail_heartbeat):
        order = []
        calls = {"n": 0}
        hello = node_hello(node="commit-node")
        frames = [hello]
        if fail_heartbeat:
            heartbeat = dict(hello)
            heartbeat.update({"type": "heartbeat", "heartbeat_seq": 1})
            frames.append(heartbeat)
        websocket = FakeLaneNodeSocket(frames, order)
        original_touch = server.machine_store.touch_scoring_lanes

        def commit(lanes, metadata, **_kwargs):
            calls["n"] += 1
            if not fail_heartbeat or calls["n"] > 1:
                raise OSError("simulated SQLite commit failure")
            return {
                "committed_at": "2026-07-23T00:00:00+00:00",
                "lanes": list(lanes),
                "scoring_session_id": metadata["scoring_session_id"],
                "heartbeat_seq": metadata["heartbeat_seq"],
            }

        try:
            server.machine_store.touch_scoring_lanes = commit
            await server.handle_node(websocket)
        finally:
            server.machine_store.touch_scoring_lanes = original_touch
        expected = (
            [server.Msg.HEARTBEAT_ACK, "close:1011"]
            if fail_heartbeat else ["close:1011"])
        assert order == expected
        assert "commit-node" not in server.clients

    asyncio.run(run_case(False))
    asyncio.run(run_case(True))


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
