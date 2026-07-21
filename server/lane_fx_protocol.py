"""Fail-open publisher for cosmetic lane-FX events.

The lane-control server owns scoring and hardware commands.  It must never
wait for a projector, renderer, or WebSocket subscriber.  This module keeps
that boundary explicit: events are best-effort UDP datagrams sent to a
separate gateway on loopback.  A missing or failed gateway can only drop a
cosmetic effect; it cannot delay scoring or machine control.
"""

import json
import logging
import os
import socket
import time
from typing import Any, Dict, Optional, Tuple


log = logging.getLogger("lane_fx.publisher")

FX_SCHEMA_VERSION = 1
FX_DEFAULT_UDP_HOST = "127.0.0.1"
FX_DEFAULT_UDP_PORT = 8768
FX_MAX_DATAGRAM_BYTES = 60_000


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class LaneFxPublisher:
    """Best-effort, nonblocking lane-FX event publisher.

    Disabled by default.  Set ``LANE_FX_ENABLED=1`` only when the separate
    ``lane_fx_gateway.py`` process is provisioned.  ``emit`` catches every
    transport/serialization failure and returns False; callers in the live
    scoring path must never see an FX exception.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        target: Optional[Tuple[str, int]] = None,
        sock: Optional[socket.socket] = None,
    ) -> None:
        self.enabled = (_env_enabled("LANE_FX_ENABLED")
                        if enabled is None else bool(enabled))
        if target is None:
            try:
                port = int(os.environ.get("LANE_FX_UDP_PORT",
                                          str(FX_DEFAULT_UDP_PORT)))
            except ValueError:
                port = FX_DEFAULT_UDP_PORT
            # Fixed loopback host is the safety boundary: no LAN client can
            # inject source events into the gateway's replay stream.
            target = (FX_DEFAULT_UDP_HOST, port)
        self.target = target
        self._socket = sock
        self._last_warning_at = 0.0

    def _get_socket(self) -> socket.socket:
        if self._socket is None:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setblocking(False)
        return self._socket

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "transport": "udp-loopback",
            "target": f"{self.target[0]}:{self.target[1]}",
            "schema_version": FX_SCHEMA_VERSION,
        }

    def emit(self, payload: Dict[str, Any]) -> bool:
        """Send one event without blocking or propagating an exception."""
        if not self.enabled:
            return False
        try:
            if not isinstance(payload, dict) or not payload.get("type"):
                raise ValueError("FX payload must be an object with a type")
            event = dict(payload)
            event.setdefault("schema_version", FX_SCHEMA_VERSION)
            event.setdefault("source_ts", time.time())
            raw = json.dumps(event, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")
            if len(raw) > FX_MAX_DATAGRAM_BYTES:
                raise ValueError(
                    f"FX payload is {len(raw)} bytes; max is "
                    f"{FX_MAX_DATAGRAM_BYTES}")
            self._get_socket().sendto(raw, self.target)
            return True
        except Exception as exc:  # cosmetic path must remain fail-open
            now = time.monotonic()
            if now - self._last_warning_at >= 60.0:
                log.warning("Lane FX event dropped (scoring unaffected): %s", exc)
                self._last_warning_at = now
            return False
