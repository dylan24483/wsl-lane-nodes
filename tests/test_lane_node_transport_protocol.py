"""Protocol-level tests for node-side durable event and command handling."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from test_watchdog_kick import fresh_lane_node  # noqa: E402
from reliable_transport import DurableTransport  # noqa: E402


class FiniteDuplex:
    def __init__(self, frames, fail_send=False):
        self._frames = iter(frames)
        self.sent = []
        self.fail_send = fail_send
        self.remote_address = ("test-server", 8765)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._frames)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, raw):
        if self.fail_send:
            raise ConnectionError("forced ACK send failure")
        self.sent.append(json.loads(raw))


def _command(ln, command_type, command_id, **fields):
    frame = {
        "type": command_type,
        "ts": time.time(),
        "lane": ln.LANES[0],
        "command_id": command_id,
        "issued_at": time.time(),
        **fields,
    }
    if ln.LANE_NODE_TOKEN:
        frame["token"] = ln.LANE_NODE_TOKEN
    return json.dumps(frame)


def _install_transport(ln, tmp_path):
    transport = DurableTransport(tmp_path / "transport.sqlite3")
    executor = ThreadPoolExecutor(max_workers=1)
    ln._SCORING_TRANSPORT = transport
    ln._SCORING_EXECUTOR = executor
    ln._lane_cmd_queues.clear()
    ln._lane_cmd_workers.clear()
    ln._pending_scoring_event = None
    return transport, executor


def test_physical_inputs_stay_masked_until_durable_transport_ready(
        tmp_path):
    ln = fresh_lane_node()
    lane = ln.LANES[0]
    assert ln.BALL_DETECT[lane].when_pressed is None
    assert ln.DIELL_LEFT[lane].when_released is None
    assert ln.DIELL_RIGHT[lane].when_released is None
    with pytest.raises(RuntimeError, match="durable transport"):
        ln._enable_scoring_callbacks()
    assert ln.BALL_DETECT[lane].when_pressed is None

    transport, executor = _install_transport(ln, tmp_path)

    async def scenario():
        ln.main_loop = asyncio.get_running_loop()
        ln._scoring_event_wake = asyncio.Event()
        ln._enable_scoring_callbacks()
        assert callable(ln.BALL_DETECT[lane].when_pressed)
        assert callable(ln.DIELL_LEFT[lane].when_released)
        assert await asyncio.to_thread(
            ln.BALL_DETECT[lane].when_pressed) is True
        assert transport.peek_event() is not None
        ln._disable_scoring_callbacks()
        assert ln.BALL_DETECT[lane].when_pressed is None
        assert ln.DIELL_LEFT[lane].when_released is None

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)


def test_gpio_callbacks_commit_before_return_then_wake_sender(tmp_path):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    ln.SCORING_MODE = "manual"
    ln._ball_detect_lockout[lane] = 0.0

    async def scenario():
        ln.main_loop = asyncio.get_running_loop()
        ln._scoring_event_wake = asyncio.Event()

        async def assert_durable_return(callback, expected_type):
            original_put = transport.put_event
            put_started = threading.Event()
            release_put = threading.Event()
            callback_returned = threading.Event()
            result = []

            def gated_put(msg):
                put_started.set()
                if not release_put.wait(timeout=2):
                    raise TimeoutError("test did not release durable commit")
                return original_put(msg)

            def invoke():
                result.append(callback())
                callback_returned.set()

            transport.put_event = gated_put
            task = asyncio.create_task(asyncio.to_thread(invoke))
            try:
                assert await asyncio.to_thread(put_started.wait, 2)
                # The old implementation returned here after
                # call_soon_threadsafe(), while put_event was still pending.
                assert callback_returned.is_set() is False
            finally:
                release_put.set()
            await asyncio.wait_for(task, timeout=2)
            transport.put_event = original_put

            assert result == [True]
            row = transport.peek_event()
            assert row is not None
            frame = json.loads(row["frame_json"])
            assert frame["type"] == expected_type
            assert frame["lane"] == lane
            await asyncio.sleep(0)
            assert ln._scoring_event_wake.is_set()
            assert transport.ack_event(frame["event_id"]) is True
            ln._scoring_event_wake.clear()

        await assert_durable_return(
            ln.make_ball_detect_callback(lane), ln.Msg.BALL_EVENT)
        await assert_durable_return(
            ln.make_foul_callback(lane), ln.Msg.FOUL_EVENT)

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)


def test_async_admission_rejects_event_id_payload_collision(
        tmp_path, monkeypatch):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    diagnostics = []
    monkeypatch.setattr(
        ln, "_record_scoring_event_transport",
        lambda *args: diagnostics.append(args))
    created = time.time()
    original = json.dumps({
        "type": ln.Msg.FOUL_EVENT,
        "ts": created,
        "lane": ln.LANES[0],
        "event_id": "collision-event",
        "event_created_at": created,
        "scoring_epoch": "epoch-1",
    }, sort_keys=True)
    conflicting = json.dumps({
        "type": ln.Msg.FOUL_EVENT,
        "ts": created,
        "lane": ln.LANES[0] + 1,
        "event_id": "collision-event",
        "event_created_at": created,
        "scoring_epoch": "epoch-1",
    }, sort_keys=True)
    assert transport.put_event(original) == "admitted"

    async def scenario():
        ln._scoring_event_wake = asyncio.Event()
        assert await ln._admit_scoring_event(conflicting) is False
        assert ln._scoring_event_wake.is_set() is False

    try:
        asyncio.run(scenario())
        assert diagnostics[-1][1:] == (
            "lost", "durable_event_id_collision_manual_reconciliation")
        assert transport.peek_event()["frame_json"] == original
    finally:
        executor.shutdown(wait=True)


def test_camera_edge_survives_crash_before_capture_task_starts(
        tmp_path, monkeypatch):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    ln.SCORING_MODE = "camera"
    ln._camera_poisoned = False
    ln._capture_in_flight[lane] = False
    ln._ball_detect_lockout[lane] = 0.0

    class NotScheduled:
        def cancel(self):
            return True

    def drop_task(coro, _loop):
        coro.close()
        return NotScheduled()

    async def scenario():
        ln.main_loop = asyncio.get_running_loop()
        monkeypatch.setattr(
            ln.asyncio, "run_coroutine_threadsafe", drop_task)
        assert await asyncio.to_thread(
            ln.make_ball_detect_callback(lane)) is True
        jobs = transport.capture_jobs()
        assert len(jobs) == 1
        assert transport.peek_event() is None

        restarted = DurableTransport(transport.path)
        assert restarted.recover_capture_jobs() == 1
        recovered = json.loads(restarted.peek_event()["frame_json"])
        assert recovered["event_id"] == jobs[0]["event_id"]
        assert recovered["pin_mask"] is None
        assert recovered["awaiting_manual"] is True
        assert recovered["capture_interrupted"] is True

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)


def test_camera_edge_survives_cancellation_during_settle(
        tmp_path, monkeypatch):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    ln.SCORING_MODE = "camera"
    ln._camera_poisoned = False
    ln._capture_in_flight[lane] = False
    ln._ball_detect_lockout[lane] = 0.0
    monkeypatch.setattr(ln.camera, "SETTLE_S", 60.0)

    async def scenario():
        ln.main_loop = asyncio.get_running_loop()
        real_submit = asyncio.run_coroutine_threadsafe
        submitted = []

        def capture_task(coro, loop):
            future = real_submit(coro, loop)
            submitted.append(future)
            return future

        monkeypatch.setattr(
            ln.asyncio, "run_coroutine_threadsafe", capture_task)
        assert await asyncio.to_thread(
            ln.make_ball_detect_callback(lane)) is True
        assert len(transport.capture_jobs()) == 1
        assert len(submitted) == 1
        assert submitted[0].cancel() is True
        await asyncio.sleep(0.05)
        assert len(transport.capture_jobs()) == 1
        assert transport.peek_event() is None

        restarted = DurableTransport(transport.path)
        assert restarted.recover_capture_jobs() == 1
        recovered = json.loads(restarted.peek_event()["frame_json"])
        assert recovered["awaiting_manual"] is True
        assert recovered["capture_interrupted"] is True

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)


def test_camera_edge_survives_cancellation_during_capture(
        tmp_path, monkeypatch):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    ln.SCORING_MODE = "camera"
    ln._camera_poisoned = False
    ln._capture_in_flight[lane] = False
    ln._ball_detect_lockout[lane] = 0.0
    monkeypatch.setattr(ln.camera, "SETTLE_S", 0.0)
    capture_started = threading.Event()
    release_capture = threading.Event()

    def blocked_capture(_lane):
        capture_started.set()
        assert release_capture.wait(timeout=2)
        return 0

    monkeypatch.setattr(ln, "detect_current_pins", blocked_capture)

    async def scenario():
        ln.main_loop = asyncio.get_running_loop()
        real_submit = asyncio.run_coroutine_threadsafe
        submitted = []

        def capture_task(coro, loop):
            future = real_submit(coro, loop)
            submitted.append(future)
            return future

        monkeypatch.setattr(
            ln.asyncio, "run_coroutine_threadsafe", capture_task)
        assert await asyncio.to_thread(
            ln.make_ball_detect_callback(lane)) is True
        assert await asyncio.to_thread(capture_started.wait, 1)
        assert len(transport.capture_jobs()) == 1
        assert submitted[0].cancel() is True
        await asyncio.sleep(0.05)
        assert len(transport.capture_jobs()) == 1
        assert transport.peek_event() is None
        release_capture.set()
        await asyncio.sleep(0.05)

        restarted = DurableTransport(transport.path)
        assert restarted.recover_capture_jobs() == 1
        recovered = json.loads(restarted.peek_event()["frame_json"])
        assert recovered["pin_mask"] is None
        assert recovered["awaiting_manual"] is True
        assert recovered["capture_interrupted"] is True

    try:
        asyncio.run(scenario())
    finally:
        release_capture.set()
        executor.shutdown(wait=True)


def test_physical_command_schema_rejects_bad_envelope_and_roster():
    ln = fresh_lane_node()
    base = json.loads(_command(
        ln, ln.Msg.OPEN_LANE, "strict-open",
        bowlers=[], scoring_epoch="epoch-1"))
    assert ln._valid_command_frame(base) is True

    invalid = [
        {**base, "ts": True},
        {**base, "ts": "now"},
        {**base, "ts": float("nan")},
        {**base, "lane": True},
        {**base, "command_id": " strict-open "},
        {**base, "bowlers": "A"},
        {**base, "bowlers": [""]},
        {**base, "bowlers": [" A "]},
        {**base, "bowlers": [7]},
    ]
    for frame in invalid:
        assert ln._valid_command_frame(frame) is False, frame


def test_duplicate_key_authority_frame_fails_connection_without_gpio():
    ln = fresh_lane_node()
    lane = ln.LANES[0]
    power = ln.PINSETTER_POWER[lane]
    initial_power = power.is_lit
    initial_events = list(power.events)
    raw = (
        '{"type":"power_on","type":"power_off","ts":1,'
        f'"lane":{lane},"command_id":"duplicate-key",'
        f'"issued_at":{time.time()}}}')
    websocket = FiniteDuplex([raw])
    with pytest.raises(
            ConnectionError, match="malformed authoritative server frame"):
        asyncio.run(ln.command_handler(websocket, {}))
    assert websocket.sent == []
    assert power.is_lit == initial_power
    assert power.events == initial_events


def test_clock_rollback_refuses_first_actuation_across_restart_and_reset(
        tmp_path):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    power = ln.PINSETTER_POWER[lane]
    raw = _command(
        ln, ln.Msg.POWER_ON, "clock-guarded-power-on")
    transport.observe_wall_clock(now=time.time() + 120)
    assert transport.observe_wall_clock(
        now=time.time())["anomaly_latched"] is True

    async def scenario():
        first = FiniteDuplex([raw])
        await ln.command_handler(first, {})
        assert first.sent[-1]["status"] == "refused"
        assert power.is_lit is False

        restarted = DurableTransport(transport.path)
        assert restarted.wall_clock_status()["anomaly_latched"] is True
        restarted.reset_wall_clock(
            time.time(), 7, "NTP synchronized; operator verified UTC")
        ln._SCORING_TRANSPORT = restarted
        replay = FiniteDuplex([raw])
        await ln.command_handler(replay, {})
        assert replay.sent[-1]["status"] == "duplicate"
        assert replay.sent[-1]["original_status"] == "refused"
        assert power.is_lit is False

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)


async def _stop_workers(ln):
    workers = list(ln._lane_cmd_workers.values())
    ln._lane_cmd_workers.clear()
    for worker in workers:
        worker.cancel()
    if workers:
        await asyncio.gather(*workers, return_exceptions=True)


def test_open_epoch_changes_only_after_queue_admission_and_replay_is_safe(
        tmp_path):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    ln._scoring_epochs[lane] = "old-epoch"
    executions = []

    async def execute(command_type, command_lane, _msg):
        executions.append((command_type, command_lane))

    ln._execute_command = execute
    raw = _command(
        ln, ln.Msg.OPEN_LANE, "open-1",
        bowlers=["A"], scoring_epoch="new-epoch")

    async def scenario():
        first = FiniteDuplex([raw])
        await ln.command_handler(first, {})
        queue = ln._lane_cmd_queues[None]
        await asyncio.wait_for(queue.join(), timeout=2)
        assert ln._scoring_epochs[lane] == "new-epoch"
        assert [ack["status"] for ack in first.sent] == ["completed"]

        replay = FiniteDuplex([raw])
        await ln.command_handler(replay, {})
        assert [ack["status"] for ack in replay.sent] == ["duplicate"]
        assert replay.sent[0]["original_status"] == "completed"

        collision = FiniteDuplex([_command(
            ln, ln.Msg.OPEN_LANE, "open-1",
            bowlers=["A"], scoring_epoch="collision-epoch")])
        await ln.command_handler(collision, {})
        assert [ack["status"] for ack in collision.sent] == ["refused"]
        assert ln._scoring_epochs[lane] == "new-epoch"
        await _stop_workers(ln)

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)

    assert executions == [(ln.Msg.OPEN_LANE, lane)]
    claim, result = transport.begin_command(
        "open-1", ln.Msg.OPEN_LANE, lane, json.loads(raw))
    assert claim == "completed"
    assert result == {"status": "completed"}


def test_full_queue_refuses_open_without_changing_epoch(tmp_path):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    ln._scoring_epochs[lane] = "old-epoch"
    raw = _command(
        ln, ln.Msg.OPEN_LANE, "open-full",
        bowlers=["A"], scoring_epoch="must-not-stick")

    async def scenario():
        queue = asyncio.Queue(maxsize=ln.CMD_QUEUE_MAX)
        for index in range(ln.CMD_QUEUE_MAX):
            queue.put_nowait(("placeholder", lane, {"index": index},
                              None, "old-epoch"))
        blocker = asyncio.create_task(asyncio.Event().wait())
        ln._lane_cmd_queues[None] = queue
        ln._lane_cmd_workers[None] = blocker
        socket = FiniteDuplex([raw])
        await ln.command_handler(socket, {})
        assert socket.sent[-1]["status"] == "refused"
        assert ln._scoring_epochs[lane] == "old-epoch"
        blocker.cancel()
        await asyncio.gather(blocker, return_exceptions=True)
        ln._lane_cmd_workers.clear()

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)

    claim, result = transport.begin_command(
        "open-full", ln.Msg.OPEN_LANE, lane, json.loads(raw))
    assert claim == "completed"
    assert result == {"status": "refused"}


def test_epoch_sync_is_durable_idempotent_and_payload_bound(tmp_path):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    raw = _command(
        ln, ln.Msg.SCORING_EPOCH_SYNC, "sync-1",
        session_generation=7,
        scoring_epoch="epoch-2")

    async def scenario():
        first = FiniteDuplex([raw])
        await ln.command_handler(first, {})
        assert [ack["status"] for ack in first.sent] == ["completed"]
        assert ln._scoring_epochs[lane] == "epoch-2"

        # issued_at is renewable only for this non-actuating command. The
        # stable lane/generation/epoch identity still deduplicates and a
        # process restart can safely re-apply the state assignment.
        renewed = json.loads(raw)
        renewed["ts"] = time.time()
        renewed["issued_at"] = time.time()
        ln._scoring_epochs[lane] = None
        replay = FiniteDuplex([json.dumps(renewed)])
        await ln.command_handler(replay, {})
        assert [ack["status"] for ack in replay.sent] == ["duplicate"]
        assert replay.sent[0]["original_status"] == "completed"
        assert ln._scoring_epochs[lane] == "epoch-2"

        collision = FiniteDuplex([_command(
            ln, ln.Msg.SCORING_EPOCH_SYNC, "sync-1",
            session_generation=7,
            scoring_epoch=None)])
        await ln.command_handler(collision, {})
        assert collision.sent[-1]["status"] == "refused"
        assert ln._scoring_epochs[lane] == "epoch-2"

        generation_collision = FiniteDuplex([_command(
            ln, ln.Msg.SCORING_EPOCH_SYNC, "sync-1",
            session_generation=8,
            scoring_epoch="epoch-2")])
        await ln.command_handler(generation_collision, {})
        assert generation_collision.sent[-1]["status"] == "refused"

        # Even a completed identity is refused before ledger lookup when its
        # authorization/envelope is stale.
        expired = dict(renewed)
        expired["ts"] = time.time() - ln.COMMAND_MAX_AGE_S - 1
        expired["issued_at"] = time.time() - ln.COMMAND_MAX_AGE_S - 1
        stale = FiniteDuplex([json.dumps(expired)])
        await ln.command_handler(stale, {})
        assert stale.sent[-1]["status"] == "refused"

        future = dict(renewed)
        future["ts"] = time.time() + 301
        future["issued_at"] = time.time() + 301
        premature = FiniteDuplex([json.dumps(future)])
        await ln.command_handler(premature, {})
        assert premature.sent[-1]["status"] == "refused"

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)

    claim, result = transport.begin_command(
        "sync-1", ln.Msg.SCORING_EPOCH_SYNC, lane, json.loads(raw))
    assert claim == "completed"
    assert result == {"status": "completed"}


def test_epoch_sync_started_receipt_is_safely_reclaimable_after_crash(
        tmp_path):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    original = json.loads(_command(
        ln, ln.Msg.SCORING_EPOCH_SYNC, "sync-crash",
        session_generation=11, scoring_epoch="epoch-repair"))

    # Simulate a process crash after the durable claim but before state
    # assignment/completion.
    assert transport.begin_command(
        "sync-crash", ln.Msg.SCORING_EPOCH_SYNC, lane, original
    ) == ("new", None)
    renewed = dict(
        original, ts=time.time(), issued_at=time.time())

    async def scenario():
        socket = FiniteDuplex([json.dumps(renewed)])
        await ln.command_handler(socket, {})
        assert socket.sent[-1]["status"] == "completed"
        assert ln._scoring_epochs[lane] == "epoch-repair"

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)

    claim, result = transport.begin_command(
        "sync-crash", ln.Msg.SCORING_EPOCH_SYNC, lane,
        dict(renewed, issued_at=time.time()))
    assert claim == "completed"
    assert result == {"status": "completed"}


def test_power_off_is_read_and_completed_while_cycle_worker_is_blocked(
        tmp_path):
    ln = fresh_lane_node()
    _transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    cycle_started = None
    release_cycle = None
    calls = []

    cycle_raw = _command(ln, ln.Msg.CYCLE, "cycle-1")
    power_raw = _command(ln, ln.Msg.POWER_OFF, "power-off-1")

    async def scenario():
        nonlocal cycle_started, release_cycle
        cycle_started = asyncio.Event()
        release_cycle = asyncio.Event()

        async def execute(command_type, command_lane, _msg):
            calls.append((command_type, command_lane))
            if command_type == ln.Msg.CYCLE:
                cycle_started.set()
                await release_cycle.wait()

        ln._execute_command = execute
        socket = FiniteDuplex([cycle_raw, power_raw])
        handler = asyncio.create_task(ln.command_handler(socket, {}))
        await asyncio.wait_for(cycle_started.wait(), timeout=2)
        for _ in range(200):
            power_seen = any(
                kind == ln.Msg.POWER_OFF for kind, _ in calls)
            power_acked = any(
                ack["command_id"] == "power-off-1"
                and ack["status"] == "completed"
                for ack in socket.sent)
            if power_seen and power_acked:
                break
            await asyncio.sleep(0.01)
        assert any(kind == ln.Msg.POWER_OFF for kind, _ in calls)
        assert any(
            ack["command_id"] == "power-off-1"
            and ack["status"] == "completed"
            for ack in socket.sent)
        release_cycle.set()
        await handler
        await asyncio.wait_for(
            ln._lane_cmd_queues[None].join(), timeout=2)
        await _stop_workers(ln)

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)

    assert calls[0][0] == ln.Msg.POWER_OFF or {
        call[0] for call in calls[:2]} == {
            ln.Msg.CYCLE, ln.Msg.POWER_OFF}


def test_ack_send_failure_leaves_completed_ledger_not_failed(tmp_path):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    raw = _command(ln, ln.Msg.CYCLE, "cycle-ack-loss")
    executions = []

    async def execute(command_type, command_lane, _msg):
        executions.append((command_type, command_lane))

    async def scenario():
        ln._execute_command = execute
        socket = FiniteDuplex([raw], fail_send=True)
        await ln.command_handler(socket, {})
        await asyncio.wait_for(
            ln._lane_cmd_queues[None].join(), timeout=2)
        await _stop_workers(ln)

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)

    assert executions == [(ln.Msg.CYCLE, lane)]
    claim, result = transport.begin_command(
        "cycle-ack-loss", ln.Msg.CYCLE, lane, json.loads(raw))
    assert claim == "completed"
    assert result == {"status": "completed"}


def test_disconnect_restores_epoch_before_all_queued_topology_transitions(
        tmp_path):
    ln = fresh_lane_node()
    _transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    ln._scoring_epochs[lane] = "original-epoch"

    cycle_raw = _command(ln, ln.Msg.CYCLE, "blocking-cycle")
    open_raw = _command(
        ln, ln.Msg.OPEN_LANE, "queued-open",
        bowlers=["A"], scoring_epoch="intermediate-epoch")
    close_raw = _command(
        ln, ln.Msg.CLOSE_LANE, "queued-close",
        scoring_epoch=None)

    async def scenario():
        cycle_started = asyncio.Event()

        async def execute(command_type, _command_lane, _msg):
            if command_type == ln.Msg.CYCLE:
                cycle_started.set()
                await asyncio.Event().wait()
            raise AssertionError(
                "queued topology command executed before disconnect")

        ln._execute_command = execute
        socket = FiniteDuplex([cycle_raw, open_raw, close_raw])
        await ln.command_handler(socket, {})
        await asyncio.wait_for(cycle_started.wait(), timeout=2)
        assert ln._scoring_epochs[lane] is None

        await ln._flush_lane_cmd_queues("test disconnect")

        assert ln._scoring_epochs[lane] == "original-epoch"
        assert ln._lane_cmd_queues[None].empty()

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)


def test_scoring_event_retires_only_on_matching_server_receipt(tmp_path):
    ln = fresh_lane_node()
    transport, executor = _install_transport(ln, tmp_path)
    lane = ln.LANES[0]
    ln._scoring_epochs[lane] = "epoch-1"
    raw = ln._encode_scoring_event(
        ln.Msg.BALL_EVENT, lane=lane, pin_mask=0,
        awaiting_manual=False)
    event_id = json.loads(raw)["event_id"]
    assert transport.put_event(raw) == "admitted"

    class Sender:
        def __init__(self):
            self.sent = []

        async def send(self, frame):
            self.sent.append(json.loads(frame))

    async def scenario():
        ln._scoring_event_wake = asyncio.Event()
        ack_state = {"event_ack_futures": {}}
        sender = Sender()
        task = asyncio.create_task(ln.event_sender(sender, ack_state))
        for _ in range(200):
            if sender.sent:
                break
            await asyncio.sleep(0.01)
        assert sender.sent[0]["event_id"] == event_id

        wrong = json.dumps({
            "type": ln.Msg.SCORING_EVENT_ACK,
            "ts": time.time(),
            "event_id": "different-event",
            "disposition": "accepted",
            "committed_at": "2026-07-23T00:00:00Z",
        })
        await ln.command_handler(FiniteDuplex([wrong]), ack_state)
        await asyncio.sleep(0)
        assert task.done() is False
        assert transport.peek_event()["event_id"] == event_id

        matching = json.dumps({
            "type": ln.Msg.SCORING_EVENT_ACK,
            "ts": time.time(),
            "event_id": event_id,
            "disposition": "accepted",
            "committed_at": "2026-07-23T00:00:00Z",
        })
        await ln.command_handler(FiniteDuplex([matching]), ack_state)
        for _ in range(200):
            if transport.peek_event() is None:
                break
            await asyncio.sleep(0.01)
        assert transport.peek_event() is None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)
