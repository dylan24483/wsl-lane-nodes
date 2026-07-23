#!/usr/bin/env python3
"""health_drop.py — shared health hand-off file (Codex round-3 R3-11).

THE PROBLEM this closes: the Pi runs TWO systemd services that are
mutually exclusive (lane-node-controller.service `Conflicts=`
lane-node.service — see systemd/README). Camera/Track-A health
(camera_health, camera_ref_drift, gs_camera_disagree) is emitted by
lane_node.py; Pi/controller health (service_restart, pi_thermal,
pi_disk_low, pi_fs_readonly, pi_undervoltage, uart_drops, …) is emitted
by controller_daemon.py. Whichever service is running, the OTHER
service's health class never reaches the store — so in the deployed
Track-B (controller) topology the desk never saw camera health, and on a
Track-A box it never saw Pi/controller platform health.

THE FIX: a small shared drop file. Each service atomically writes its
own last-known health block here (write_drop, tmp+os.replace — a reader
never sees a half-written file). The service that currently has transport
(the one that is running) also reads the OTHER service's drop
(read_foreign_drops) and ships it to the store, explicitly flagged with
its age so the desk knows it is a last-known snapshot, not live. Because
only one service runs at a time, the drop is how the quiet concern's
health survives the hand-off.

Format: one JSON object per service key:
    { "<service>": { "written_at": <epoch>, "payload": {...} }, ... }

Everything here is best-effort and never raises — a health-hand-off bug
must not take down either service. A read-only filesystem (R3-10) makes
write_drop a counted no-op; the reader simply finds no fresh foreign drop.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

HEALTH_DROP_FILENAME = "health_drop.json"

# Service keys (stable strings — the drop file is keyed by them).
SERVICE_CONTROLLER = "controller"   # Track-B: Pi/controller platform health
SERVICE_CAMERA = "camera"           # Track-A: camera/scoring health

DEFAULT_MAX_AGE_S = 900.0           # a foreign drop older than this is ignored


def write_drop(path, service, payload):
    """Atomically merge {service: {written_at, payload}} into the drop file.
    Returns True on success, False on any failure (e.g. read-only FS). Never
    raises. Preserves other services' entries."""
    try:
        data = _read_raw(path)
        data[service] = {"written_at": time.time(), "payload": payload}
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".health_drop_", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return True
    except Exception:
        return False


def read_foreign_drops(path, this_service, *, max_age_s=DEFAULT_MAX_AGE_S,
                       now=None):
    """Return [(service, payload, age_s), ...] for every service OTHER than
    this_service whose drop is fresher than max_age_s. Never raises; returns
    [] on any problem. The caller ships these to the store flagged with age."""
    out = []
    now = time.time() if now is None else now
    try:
        data = _read_raw(path)
        for service, entry in data.items():
            if service == this_service or not isinstance(entry, dict):
                continue
            written = entry.get("written_at")
            if not isinstance(written, (int, float)):
                continue
            age = now - written
            if age < 0 or age > max_age_s:
                continue
            payload = entry.get("payload")
            if payload is not None:
                out.append((service, payload, round(age, 1)))
    except Exception:
        return []
    return out


def _read_raw(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
