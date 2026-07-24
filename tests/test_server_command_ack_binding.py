"""The server accepts a command receipt only from its exact live owner."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
for entry in (str(REPO_ROOT), str(SERVER_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

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

import lane_node_server as server  # noqa: E402


class QueueWebSocket:
    def __init__(self, name):
        self.name = name
        self.remote_address = (name, 1234)
        self.inbound = asyncio.Queue()
        self.sent = []
        self.closed = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.inbound.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def close(self, code=None, reason=None):
        self.closed.append((code, reason))


def _hello(node, lane):
    return json.dumps({
        "type": server.Msg.HELLO,
        "ts": time.time(),
        "node": node,
        "lanes": [lane, lane + 1],
        "protocol_version": server.PROTOCOL_VERSION,
        "scoring_boot_id": f"{node}-boot",
        "scoring_session_id": f"{node}-session",
        "heartbeat_seq": 0,
        "scoring_mode": "manual",
        "camera_calibrated": False,
        "camera_ok": False,
        "camera_code": "manual",
        "outbox": {},
        "node_ball_lockout_s": 8.0,
    })


def _ack(
        command_id, status="completed", original_status=None,
        completed_at=None):
    frame = {
        "type": server.Msg.COMMAND_ACK,
        "ts": time.time(),
        "command_id": command_id,
        "status": status,
        "completed_at": (
            time.time() if completed_at is None else completed_at),
    }
    if original_status is not None:
        frame["original_status"] = original_status
    return json.dumps(frame)


def test_duplicate_key_websocket_frame_closes_before_registration(
        monkeypatch):
    accepted = []
    monkeypatch.setattr(
        server.machine_store, "accept_scoring_boot",
        lambda *_args, **_kwargs: accepted.append(True))
    websocket = QueueWebSocket("duplicate-json")

    async def scenario():
        task = asyncio.create_task(server.handle_node(websocket))
        await websocket.inbound.put(
            '{"type":"hello","type":"ball_event","node":"bad"}')
        await websocket.inbound.put(None)
        await task

    asyncio.run(scenario())
    assert websocket.closed == [(4400, "invalid JSON control frame")]
    assert accepted == []


def test_scoring_topology_parser_requires_exact_disjoint_pairs(monkeypatch):
    monkeypatch.setattr(server, "AUTH_TOKEN", "shared-control-secret")
    monkeypatch.setattr(
        server.machine_store, "configured_lanes", lambda: [21, 22, 23, 24])

    monkeypatch.delenv("WSL_SCORING_NODE_TOPOLOGY", raising=False)
    topology, error = server._scoring_node_topology()
    assert topology is None
    assert "not configured" in error

    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY",
        "node-a=21,22;node-b=22,23")
    topology, error = server._scoring_node_topology()
    assert topology is None
    assert "invalid" in error

    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY",
        "node-a=21,22;node-b=23,24")
    topology, error = server._scoring_node_topology()
    assert error is None
    assert topology == {"node-a": (21, 22), "node-b": (23, 24)}

    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOKENS",
        "node-a=aaaaaaaaaaaaaaaa;node-b=bbbbbbbbbbbbbbbb")
    credentials, error = server._scoring_node_tokens()
    assert error is None
    assert set(credentials) == {"node-a", "node-b"}

    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOKENS", "node-a=aaaaaaaaaaaaaaaa")
    credentials, error = server._scoring_node_tokens()
    assert credentials is None
    assert "keys must exactly match" in error

    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOKENS",
        "node-a=shared-secret-123;node-b=shared-secret-123")
    credentials, error = server._scoring_node_tokens()
    assert credentials is None
    assert "tokens must be distinct per node" in error

    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOKENS",
        "node-a=shared-control-secret;"
        "node-b=bbbbbbbbbbbbbbbb")
    credentials, error = server._scoring_node_tokens()
    assert credentials is None
    assert "must not reuse LANE_NODE_TOKEN" in error
    assert "shared-control-secret" not in error


def test_scoring_topology_node_ids_match_production_policy(monkeypatch):
    monkeypatch.setattr(
        server.machine_store, "configured_lanes", lambda: [21, 22])

    for length in (121, 128):
        node_id = "n" * length
        monkeypatch.setenv(
            "WSL_SCORING_NODE_TOPOLOGY", f"{node_id}=21,22")
        topology, error = server._scoring_node_topology()
        assert error is None
        assert topology == {node_id: (21, 22)}

    for node_id in (
            "n" * 129,
            "dev",
            "dev-pair",
            "pair-dev",
            "pair-dev-node"):
        monkeypatch.setenv(
            "WSL_SCORING_NODE_TOPOLOGY", f"{node_id}=21,22")
        topology, error = server._scoring_node_topology()
        assert topology is None
        assert "invalid" in error


def test_scoring_topology_health_requires_every_fresh_exact_node(monkeypatch):
    monkeypatch.setattr(
        server.machine_store, "configured_lanes", lambda: [21, 22])
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY", "expected-node=21,22")
    now = time.time()
    healthy = {
        "expected-node": {
            "lanes": [21, 22],
            "connected_at": now,
            "last_heartbeat": now,
        }}
    assert server._scoring_node_topology_status(healthy, now)["ok"] is True

    missing = server._scoring_node_topology_status({}, now)
    assert missing["ok"] is False
    assert "node_expected-node:missing" in missing["reasons"]

    stale = {
        "expected-node": {
            "lanes": [21, 22],
            "connected_at": now - server.HEARTBEAT_FRESH_S - 1,
            "last_heartbeat": now - server.HEARTBEAT_FRESH_S - 1,
        }}
    assert "node_expected-node:heartbeat_stale" in (
        server._scoring_node_topology_status(stale, now)["reasons"])


def test_unknown_or_partial_node_claim_never_touches_scoring_lease(
        monkeypatch):
    calls = []
    monkeypatch.setattr(server, "AUTH_TOKEN", "")
    monkeypatch.setattr(
        server.machine_store, "configured_lanes", lambda: [21, 22])
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY", "expected-node=21,22")
    monkeypatch.setattr(
        server.machine_store, "accept_scoring_boot",
        lambda *_args, **_kwargs: calls.append("boot"))
    monkeypatch.setattr(
        server.machine_store, "touch_scoring_lanes",
        lambda *_args, **_kwargs: calls.append("lease"))
    monkeypatch.setattr(
        server.state_store_module, "observe_control_wall_clock",
        lambda: {"observed": True, "anomaly_latched": False})

    async def run_case(node, lane):
        websocket = QueueWebSocket(node)
        task = asyncio.create_task(server.handle_node(websocket))
        await websocket.inbound.put(_hello(node, lane))
        await websocket.inbound.put(None)
        await task
        return websocket

    unknown = asyncio.run(run_case("unknown-node", 21))
    partial_raw = json.loads(_hello("expected-node", 21))
    partial_raw["lanes"] = [21]

    async def run_partial():
        websocket = QueueWebSocket("partial")
        task = asyncio.create_task(server.handle_node(websocket))
        await websocket.inbound.put(json.dumps(partial_raw))
        await websocket.inbound.put(None)
        await task
        return websocket

    partial = asyncio.run(run_partial())
    assert unknown.closed == [(4400, "invalid HELLO contract")]
    assert partial.closed == [(4400, "invalid HELLO contract")]
    assert calls == []


def test_missing_server_auth_rejects_valid_manifest_node_before_lease(
        monkeypatch):
    calls = []
    monkeypatch.setattr(server, "AUTH_TOKEN", "")
    monkeypatch.setattr(server, "ALLOW_UNAUTHENTICATED_BENCH", False)
    monkeypatch.setattr(
        server.machine_store, "configured_lanes", lambda: [21, 22])
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY", "expected-node=21,22")
    monkeypatch.setattr(
        server.machine_store, "accept_scoring_boot",
        lambda *_args, **_kwargs: calls.append("boot"))
    monkeypatch.setattr(
        server.state_store_module, "observe_control_wall_clock",
        lambda: {"observed": True, "anomaly_latched": False})

    async def scenario():
        websocket = QueueWebSocket("no-auth")
        task = asyncio.create_task(server.handle_node(websocket))
        await websocket.inbound.put(_hello("expected-node", 21))
        await websocket.inbound.put(None)
        await task
        assert websocket.closed == [
            (4401, "server auth is not configured")]

    asyncio.run(scenario())
    assert calls == []


def test_per_node_hello_credential_is_bound_to_manifest_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "AUTH_TOKEN", "shared-http-command-token")
    monkeypatch.setattr(server, "ALLOW_UNAUTHENTICATED_BENCH", False)
    monkeypatch.setattr(
        server.machine_store, "configured_lanes", lambda: [21, 22])
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY", "expected-node=21,22")
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOKENS",
        "expected-node=unique-node-secret-21")
    monkeypatch.setattr(
        server.machine_store, "accept_scoring_boot",
        lambda *_args, **_kwargs: calls.append("boot"))
    monkeypatch.setattr(
        server.machine_store, "touch_scoring_lanes",
        lambda _lanes, metadata, **_kwargs: {
            "scoring_session_id": metadata["scoring_session_id"],
            "heartbeat_seq": metadata["heartbeat_seq"],
            "committed_at": "2026-07-23T00:00:00Z",
        })
    monkeypatch.setattr(
        server.state_store_module, "observe_control_wall_clock",
        lambda: {"observed": True, "anomaly_latched": False})
    server.clients.clear()
    server.client_metadata.clear()
    server._routing_lock = None

    async def attempt(token):
        websocket = QueueWebSocket(token)
        hello = json.loads(_hello("expected-node", 21))
        hello["token"] = token
        task = asyncio.create_task(server.handle_node(websocket))
        await websocket.inbound.put(json.dumps(hello))
        for _ in range(100):
            if websocket.sent or websocket.closed:
                break
            await asyncio.sleep(0.01)
        await websocket.inbound.put(None)
        await task
        return websocket

    wrong = asyncio.run(attempt("shared-http-command-token"))
    assert wrong.closed == [(4401, "node authentication failed")]
    assert calls == []

    correct = asyncio.run(attempt("unique-node-secret-21"))
    assert correct.sent[0]["type"] == server.Msg.HEARTBEAT_ACK
    assert calls == ["boot"]


def test_duplicate_live_node_is_rejected_before_second_lease_commit(
        monkeypatch):
    commits = []
    monkeypatch.setattr(server, "AUTH_TOKEN", "")
    monkeypatch.setattr(
        server.machine_store, "configured_lanes", lambda: [21, 22])
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY", "expected-node=21,22")
    monkeypatch.setattr(
        server.machine_store, "accept_scoring_boot",
        lambda *_args, **_kwargs: commits.append("boot"))
    monkeypatch.setattr(
        server.machine_store, "touch_scoring_lanes",
        lambda _lanes, metadata, **_kwargs: {
            "scoring_session_id": metadata["scoring_session_id"],
            "heartbeat_seq": metadata["heartbeat_seq"],
            "committed_at": "2026-07-23T00:00:00Z",
        })
    monkeypatch.setattr(
        server.state_store_module, "observe_control_wall_clock",
        lambda: {"observed": True, "anomaly_latched": False})
    server.clients.clear()
    server.client_metadata.clear()
    server._routing_lock = None

    async def scenario():
        owner = QueueWebSocket("owner")
        duplicate = QueueWebSocket("duplicate")
        owner_task = asyncio.create_task(server.handle_node(owner))
        await owner.inbound.put(_hello("expected-node", 21))
        deadline = asyncio.get_running_loop().time() + 2.0
        while asyncio.get_running_loop().time() < deadline:
            if server.clients.get("expected-node") is owner:
                break
            await asyncio.sleep(0.01)
        assert server.clients.get("expected-node") is owner

        duplicate_task = asyncio.create_task(server.handle_node(duplicate))
        await duplicate.inbound.put(_hello("expected-node", 21))
        await duplicate.inbound.put(None)
        await duplicate_task
        assert duplicate.closed == [
            (4409, "node identity already connected")]
        assert server.clients.get("expected-node") is owner
        assert commits == ["boot"]

        await owner.inbound.put(None)
        await owner_task

    asyncio.run(scenario())


def test_command_ack_is_bound_to_id_lane_owner_and_websocket(monkeypatch):
    committed_at = "2026-07-23T00:00:00Z"
    monkeypatch.setattr(server, "AUTH_TOKEN", "")
    monkeypatch.setattr(
        server.machine_store, "configured_lanes", lambda: [21, 22, 23, 24])
    monkeypatch.setenv(
        "WSL_SCORING_NODE_TOPOLOGY",
        "node-21=21,22;node-23=23,24")
    monkeypatch.setattr(
        server.machine_store, "accept_scoring_boot",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        server.machine_store, "touch_scoring_lanes",
        lambda _lanes, metadata, **_kwargs: {
            "scoring_session_id": metadata["scoring_session_id"],
            "heartbeat_seq": metadata["heartbeat_seq"],
            "committed_at": committed_at,
        })
    monkeypatch.setattr(
        server, "_record_command_transport",
        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        server.state_store_module, "observe_control_wall_clock",
        lambda: {
            "observed": True,
            "anomaly_latched": False,
            "high_water_epoch": time.time(),
            "observed_epoch": time.time(),
        })
    server.clients.clear()
    server.client_metadata.clear()
    server._command_ack_waiters.clear()
    server._routing_lock = None

    async def scenario():
        owner = QueueWebSocket("owner")
        other_lane = QueueWebSocket("other")
        owner_task = asyncio.create_task(server.handle_node(owner))
        other_task = asyncio.create_task(server.handle_node(other_lane))
        await owner.inbound.put(_hello("node-21", 21))
        await other_lane.inbound.put(_hello("node-23", 23))
        deadline = asyncio.get_running_loop().time() + 2.0
        while asyncio.get_running_loop().time() < deadline:
            if set(server.clients) == {"node-21", "node-23"}:
                break
            await asyncio.sleep(0.01)
        assert set(server.clients) == {"node-21", "node-23"}

        command = server.encode_command(
            server.Msg.CYCLE, 21, command_id="bound-command",
            issued_at=time.time())
        delivery = asyncio.create_task(
            server._send_command_and_wait(owner, command))
        waiter_deadline = asyncio.get_running_loop().time() + 2.0
        while asyncio.get_running_loop().time() < waiter_deadline:
            if (
                    "bound-command" in server._command_ack_waiters
                    or delivery.done()):
                break
            await asyncio.sleep(0.01)
        assert "bound-command" in server._command_ack_waiters

        # Correct ID from a socket that does not own lane 21 is ignored.
        await other_lane.inbound.put(_ack("bound-command"))
        await asyncio.sleep(0)
        assert delivery.done() is False

        # Correct owner but wrong ID is also ignored.
        await owner.inbound.put(_ack("different-command"))
        await asyncio.sleep(0)
        assert delivery.done() is False

        # original_status belongs only to duplicate receipts.  A completed
        # frame carrying it is malformed and cannot satisfy the waiter.
        await owner.inbound.put(_ack(
            "bound-command", status="completed",
            original_status="failed"))
        await asyncio.sleep(0)
        assert delivery.done() is False

        # An old matching receipt cannot be rebound to this delivery attempt.
        await owner.inbound.put(_ack(
            "bound-command", completed_at=time.time() - 301))
        await asyncio.sleep(0)
        assert delivery.done() is False

        await owner.inbound.put(_ack("bound-command"))
        result = await asyncio.wait_for(delivery, timeout=2)
        assert result["command_id"] == "bound-command"
        assert result["status"] == "completed"
        assert "bound-command" not in server._command_ack_waiters

        await owner.inbound.put(None)
        await other_lane.inbound.put(None)
        await asyncio.gather(owner_task, other_task)
        assert server.clients == {}

    asyncio.run(scenario())


def test_only_completed_or_duplicate_completed_counts_as_success():
    assert server._command_ack_succeeded({"status": "completed"})
    assert server._command_ack_succeeded({
        "status": "duplicate", "original_status": "completed"})
    assert not server._command_ack_succeeded({
        "status": "duplicate", "original_status": "refused"})
    assert not server._command_ack_succeeded({
        "status": "duplicate", "original_status": "failed"})
    assert not server._command_ack_succeeded({"status": "failed"})
    assert not server._command_ack_succeeded({"status": "ambiguous"})


def test_background_ball_cycle_refusal_opens_event_bound_reconciliation(
        monkeypatch, tmp_path):
    monkeypatch.setattr(
        server.state_store_module, "DB_PATH", tmp_path / "lane_state.db")
    command_id = "ball-cycle:abc"
    server.state_store_module.begin_background_command_delivery({
        "command_id": command_id,
        "event_id": "ball-event-1",
        "lane_id": 21,
        "command_type": server.Msg.CYCLE,
        "owner_boot_id": server.SERVER_BOOT_ID,
        "issued_at": time.time(),
        "deadline_monotonic": time.monotonic() + 10.0,
    })

    async def scenario():
        task = asyncio.create_task(asyncio.sleep(
            0, result={"status": "refused"}))
        await task
        server._consume_ball_cycle_task(
            task, 21, "ball-event-1", command_id)
        await asyncio.gather(*list(server._background_command_tasks))

    asyncio.run(scenario())
    delivery = server.state_store_module.background_command_delivery(
        command_id)
    assert delivery["state"] == "indeterminate"
    incidents = server.state_store_module.pending_diagnostic_incidents()
    assert len(incidents) == 1
    event = json.loads(incidents[0]["payload_json"])
    assert event["lane_id"] == 21
    assert event["severity"] == "fault"
    assert event["code"] == "cycle_delivery_indeterminate"
    detail = event["detail"]
    assert detail["event_id"] == "ball-event-1"
    assert detail["command_id"] == "ball-cycle:abc"
    assert detail["command_status"] == "refused"
    assert detail["automatic_retry_forbidden"] is True


def test_ball_cycle_duplicate_inflight_fails_without_stranding_reader(
        monkeypatch):
    monkeypatch.setattr(
        server.state_store_module, "observe_control_wall_clock",
        lambda: {
            "observed": True,
            "anomaly_latched": False,
            "high_water_epoch": time.time(),
            "observed_epoch": time.time(),
        })
    async def scenario():
        websocket = QueueWebSocket("duplicate-inflight")
        event_id = "duplicate-event"
        command_id = (
            "ball-cycle:"
            + hashlib.sha256(event_id.encode("utf-8")).hexdigest())
        server._command_ack_waiters[command_id] = {"existing": True}
        try:
            try:
                await asyncio.wait_for(
                    server._send_ball_cycle_before_receipt(
                        websocket, 21, event_id, time.time()),
                    timeout=0.25)
            except RuntimeError as exc:
                assert str(exc) == "duplicate in-flight command_id"
            else:
                raise AssertionError(
                    "duplicate in-flight identity did not fail")
            assert websocket.sent == []
        finally:
            server._command_ack_waiters.pop(command_id, None)

    asyncio.run(scenario())
