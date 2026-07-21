#!/usr/bin/env python3
"""Isolated UDP-to-WebSocket gateway for the WSL lane-FX renderers.

Run this as a separate process from ``lane_node_server.py``.  The scoring
server sends best-effort datagrams to 127.0.0.1:8768; this process owns all
subscriber queues, replay state, authentication, and WebSocket work on 8767.
Renderer faults therefore cannot consume the lane-control event loop.
"""

import asyncio
import collections
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Deque, Dict, Optional

from websockets.asyncio.server import serve

from lane_fx_protocol import (FX_DEFAULT_UDP_HOST, FX_DEFAULT_UDP_PORT,
                              FX_MAX_DATAGRAM_BYTES, FX_SCHEMA_VERSION)


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("lane_fx.gateway")

FX_WS_HOST = os.environ.get("LANE_FX_WS_HOST", "0.0.0.0").strip()
FX_WS_PORT = int(os.environ.get("LANE_FX_WS_PORT", "8767"))
# Source injection is deliberately loopback-only and not configurable.
FX_UDP_HOST = FX_DEFAULT_UDP_HOST
FX_UDP_PORT = int(os.environ.get("LANE_FX_UDP_PORT",
                                 str(FX_DEFAULT_UDP_PORT)))
FX_TOKEN = os.environ.get("LANE_FX_TOKEN", "").strip()
_origins_raw = os.environ.get("LANE_FX_ALLOWED_ORIGINS", "").strip()
FX_ALLOWED_ORIGINS = ([item.strip() for item in _origins_raw.split(',')
                       if item.strip()] or None)
FX_RECENT_MAX = max(1, int(os.environ.get("LANE_FX_RECENT_MAX", "128")))
FX_CLIENT_QUEUE_MAX = max(1, int(os.environ.get(
    "LANE_FX_CLIENT_QUEUE_MAX", "256")))
FX_MAX_CLIENTS = max(1, int(os.environ.get("LANE_FX_MAX_CLIENTS", "64")))

REPLAYABLE_TYPES = {
    "ball", "lane_open", "lane_close", "league_open", "correction"
}


class GatewayState:
    """Single-event-loop state for ordered fan-out and bounded replay."""

    def __init__(self, recent_max: int = FX_RECENT_MAX,
                 queue_max: int = FX_CLIENT_QUEUE_MAX,
                 token: str = FX_TOKEN,
                 max_clients: int = FX_MAX_CLIENTS) -> None:
        self.stream_id = uuid.uuid4().hex
        self.seq = 0
        self.recent: Deque[Dict[str, Any]] = collections.deque(
            maxlen=recent_max)
        self.clients: Dict[Any, asyncio.Queue] = {}
        self.queue_max = queue_max
        self.token = token
        self.max_clients = max_clients
        self._background_tasks = set()

    def _track_task(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def publish(self, source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate, sequence, retain, and enqueue one source event.

        This method is called only on the gateway event loop.  Sequence
        assignment and queue insertion are therefore structurally ordered;
        no cross-thread lock/callback race can deliver seq N+1 before N.
        """
        if not isinstance(source, dict):
            return None
        event_type = source.get("type")
        if not isinstance(event_type, str) or not event_type:
            return None

        event = dict(source)
        event["schema_version"] = FX_SCHEMA_VERSION
        event["stream_id"] = self.stream_id
        event["ts"] = float(event.get("source_ts") or time.time())

        if event_type in REPLAYABLE_TYPES:
            self.seq += 1
            event["seq"] = self.seq
            event["transient"] = False
            self.recent.append(event)
        else:
            # Heartbeats and test fires are live-only. They must not consume
            # replay sequence numbers; otherwise a reconnect sees artificial
            # gaps for transient messages that were deliberately not retained.
            event["seq"] = None
            event["transient"] = True

        message = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        overflowed = []
        for websocket, queue in list(self.clients.items()):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Never silently create an undetectable sequence gap.  Force
                # a reconnect; the stream handshake will demand a resync if
                # the replay ring can no longer cover the client's last seq.
                overflowed.append(websocket)
        for websocket in overflowed:
            self.clients.pop(websocket, None)
            self._track_task(websocket.close(
                code=1013, reason="lane FX subscriber fell behind"))
        return event

    def _check_token(self, supplied: Any) -> bool:
        if not self.token:
            return True
        return (isinstance(supplied, str)
                and hmac.compare_digest(supplied, self.token))

    async def handle_client(self, websocket) -> None:
        if len(self.clients) >= self.max_clients:
            await websocket.close(code=1013, reason="too many FX subscribers")
            return

        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            hello = json.loads(raw)
        except Exception:
            await websocket.close(code=4400, reason="valid hello required")
            return
        if (not isinstance(hello, dict)
                or hello.get("type") != "hello"):
            await websocket.close(code=4400, reason="valid hello required")
            return
        if not self._check_token(hello.get("token")):
            await websocket.close(code=4401, reason="auth failed")
            return

        try:
            last_seq = max(0, int(hello.get("last_seq") or 0))
        except (TypeError, ValueError):
            last_seq = 0
        client_stream = hello.get("stream_id")
        oldest_seq = self.recent[0]["seq"] if self.recent else self.seq + 1
        same_stream = client_stream == self.stream_id
        replay_covered = (oldest_seq - 1) <= last_seq <= self.seq
        resync_required = not same_stream or not replay_covered
        if not same_stream:
            reason = "stream_changed_or_first_connect"
        elif not replay_covered:
            reason = "replay_window_exceeded"
        else:
            reason = None

        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_max)
        self.clients[websocket] = queue
        replay = ([] if resync_required else
                  [event for event in self.recent
                   if event["seq"] > last_seq])
        stream_message = {
            "type": "stream",
            "schema_version": FX_SCHEMA_VERSION,
            "stream_id": self.stream_id,
            "current_seq": self.seq,
            "oldest_seq": oldest_seq,
            "resync_required": resync_required,
            "reason": reason,
        }

        try:
            await websocket.send(json.dumps(stream_message,
                                            separators=(",", ":")))
            for event in replay:
                await websocket.send(json.dumps(event, separators=(",", ":"),
                                                ensure_ascii=False))
            closed_task = asyncio.create_task(websocket.wait_closed())
            while True:
                message_task = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {message_task, closed_task},
                    return_when=asyncio.FIRST_COMPLETED)
                if closed_task in done:
                    message_task.cancel()
                    break
                await websocket.send(message_task.result())
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            if 'message_task' in locals() and not message_task.done():
                message_task.cancel()
            if 'closed_task' in locals() and not closed_task.done():
                closed_task.cancel()
            self.clients.pop(websocket, None)


class FxDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, state: GatewayState) -> None:
        self.state = state

    def datagram_received(self, data: bytes, addr) -> None:
        if len(data) > FX_MAX_DATAGRAM_BYTES:
            log.warning("Oversize lane-FX datagram dropped from %s", addr)
            return
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            log.warning("Malformed lane-FX datagram dropped from %s", addr)
            return
        if self.state.publish(payload) is None:
            log.warning("Invalid lane-FX event dropped from %s", addr)


async def _heartbeat_loop(state: GatewayState) -> None:
    while True:
        await asyncio.sleep(10.0)
        state.publish({"type": "heartbeat", "source_ts": time.time()})


async def main() -> None:
    loop = asyncio.get_running_loop()
    state = GatewayState()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: FxDatagramProtocol(state),
        local_addr=(FX_UDP_HOST, FX_UDP_PORT))
    heartbeat = asyncio.create_task(_heartbeat_loop(state))
    if FX_TOKEN:
        log.info("LANE_FX_TOKEN set - subscriber hello authentication enabled")
    else:
        log.warning("LANE_FX_TOKEN not set - read-only FX stream is LAN-open")
    if FX_ALLOWED_ORIGINS:
        log.info("Lane-FX browser origins restricted to %s", FX_ALLOWED_ORIGINS)
    else:
        log.warning("LANE_FX_ALLOWED_ORIGINS not set - browser Origin is unrestricted")
    log.info("Lane-FX source: udp://%s:%s (loopback only)",
             FX_UDP_HOST, FX_UDP_PORT)
    log.info("Lane-FX subscribers: ws://%s:%s (stream %s)",
             FX_WS_HOST, FX_WS_PORT, state.stream_id)
    try:
        async with serve(state.handle_client, FX_WS_HOST, FX_WS_PORT,
                         max_size=4096, max_queue=4,
                         ping_interval=20, ping_timeout=20,
                         origins=FX_ALLOWED_ORIGINS):
            await asyncio.Future()
    finally:
        heartbeat.cancel()
        transport.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Lane-FX gateway stopped")
