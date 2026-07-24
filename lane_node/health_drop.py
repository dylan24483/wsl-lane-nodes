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
    { "<service>": {
        "written_at": <epoch>,
        "snapshot_id": <stable content identity>,
        "payload_sha256": <digest>,
        "payload": {...}
    }, ... }

Everything here is best-effort and never raises — a health-hand-off bug
must not take down either service. A read-only filesystem (R3-10) makes
write_drop a counted failure; callers promote that failure, and readers
surface an explicit missing/stale foreign-service state.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time

HEALTH_DROP_FILENAME = "health_drop.json"

# Service keys (stable strings — the drop file is keyed by them).
SERVICE_CONTROLLER = "controller"   # Track-B: Pi/controller platform health
SERVICE_CAMERA = "camera"           # Track-A: camera/scoring health

DEFAULT_MAX_AGE_S = 900.0           # a foreign drop older than this is ignored


def parse_required_services(raw):
    """Parse canonical ``21=scoring;22=scoring`` runtime policy strictly."""
    if not isinstance(raw, str) or not raw.strip():
        return {}
    result = {}
    try:
        for entry in raw.split(";"):
            lane_text, services_text = entry.split("=", 1)
            lane = int(lane_text.strip())
            services = tuple(
                part.strip().lower()
                for part in services_text.split(",") if part.strip())
            if (not 1 <= lane <= 32 or lane in result
                    or len(services) != 1
                    or services[0] not in ("controller", "scoring")):
                raise ValueError(entry)
            result[lane] = services
        return result
    except (TypeError, ValueError):
        return {}


def foreign_service_required(raw, service, lanes):
    policy = parse_required_services(raw)
    if service not in ("controller", "scoring") or not policy:
        return False
    return any(
        service in policy.get(int(lane), ())
        for lane in (lanes or ()))

# Track-A uses the common probe without importing the controller daemon. Keep
# the event vocabulary mapping here so live platform faults are transported,
# not merely written into a hand-off file that nobody reads while Track A owns
# the service slot.
PLATFORM_EVENT_MAP = {
    "filesystem_readonly": ("fault", "pi_fs_readonly", "diag_volume"),
    "disk_low": ("warn", "pi_disk_low", "diag_volume"),
    "disk_probe_failed": ("warn", "diag_storage_error", "disk_probe"),
    "thermal": ("warn", "pi_thermal", "soc_temp"),
    "temperature_probe_failed": (
        "warn", "pi_thermal", "soc_temp_unavailable"),
    "pi_power_or_throttle": (
        "warn", "pi_undervoltage", "get_throttled"),
    "pi_power_or_throttle_history": (
        "warn", "pi_undervoltage", "get_throttled_history"),
    "vcgencmd_probe_failed": (
        "warn", "pi_undervoltage", "get_throttled_unavailable"),
}

HEALTH_DROP_UNHEALTHY_EVENT = "health_drop_unhealthy"

# `vcgencmd get_throttled` publishes current conditions in bits 0..3 and
# sticky "has occurred since boot" evidence in bits 16..19.  Preserve both:
# the sticky half is often the only remaining evidence after a transient PSU
# sag has cleared before the next slow platform-health poll.
_THROTTLE_FACT_NAMES = (
    "undervoltage",
    "frequency_capped",
    "throttled",
    "soft_temperature_limit",
)
_THROTTLE_CURRENT_MASK = 0x0000000F
_THROTTLE_HISTORY_MASK = 0x000F0000

_stats_lock = threading.Lock()
_stats = {
    "writes": 0,
    "write_errors": 0,
    "reads": 0,
    "read_errors": 0,
}


def stats():
    with _stats_lock:
        return dict(_stats)


def _bump(name):
    with _stats_lock:
        _stats[name] = _stats.get(name, 0) + 1


def _finite_number(value):
    """True only for a finite real scalar (bool is not a timestamp)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _fsync_parent_dir(path):
    """Best-effort directory fsync after an atomic replace (effective on Pi)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(directory, flags)
    except (OSError, TypeError):
        return False
    try:
        os.fsync(fd)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _entry_integrity_error(service, entry):
    """Return an integrity error string, or None for a self-consistent entry."""
    payload_sha = entry.get("payload_sha256")
    if not isinstance(payload_sha, str) or len(payload_sha) != 64 \
            or any(c not in "0123456789abcdef" for c in payload_sha):
        return "missing_or_invalid_payload_sha256"
    try:
        encoded = json.dumps(
            entry.get("payload"), sort_keys=True, separators=(",", ":"),
            allow_nan=False)
    except Exception:
        return "payload_not_canonical_json"
    actual_sha = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if actual_sha != payload_sha:
        return "payload_sha256_mismatch"
    snapshot_id = entry.get("snapshot_id")
    if not isinstance(snapshot_id, str):
        return "missing_or_invalid_snapshot_id"
    parts = snapshot_id.split("-")
    if len(parts) != 3 or parts[0] != service or not parts[1].isdigit() \
            or parts[2] != payload_sha[:12]:
        return "snapshot_id_mismatch"
    return None


def write_drop(path, service, payload):
    """Atomically merge {service: {written_at, payload}} into the drop file.
    Returns True on success, False on any failure (e.g. read-only FS). Never
    raises. Preserves other services' entries."""
    try:
        data = _read_raw(path)
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload_sha = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        previous = data.get(service)
        previous = previous if isinstance(previous, dict) else {}
        if previous.get("payload_sha256") == payload_sha \
                and _entry_integrity_error(service, previous) is None:
            snapshot_id = previous.get("snapshot_id")
        else:
            snapshot_id = (
                f"{service}-{time.time_ns()}-{payload_sha[:12]}")
        data[service] = {
            "written_at": time.time(),
            "snapshot_id": snapshot_id,
            "payload_sha256": payload_sha,
            "payload": payload,
        }
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".health_drop_", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            _fsync_parent_dir(path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        _bump("writes")
        return True
    except Exception:
        _bump("write_errors")
        return False


def read_foreign_drops(path, this_service, *, max_age_s=DEFAULT_MAX_AGE_S,
                       now=None):
    """Return [(service, payload, age_s), ...] for every service OTHER than
    this_service whose drop is fresher than max_age_s. Never raises; returns
    [] on any problem. The caller ships these to the store flagged with age."""
    out = []
    now = time.time() if now is None else now
    try:
        for status in read_foreign_statuses(
                path, this_service, max_age_s=max_age_s, now=now):
            if status["status"] == "fresh":
                out.append((
                    status["service"], status["payload"], status["age_s"]))
    except Exception:
        return []
    return out


def read_foreign_statuses(path, this_service, *, max_age_s=DEFAULT_MAX_AGE_S,
                          now=None):
    """Return explicit fresh/stale/missing status for the other service.

    Unlike ``read_foreign_drops``, stale and missing hand-offs are observable.
    ``snapshot_id`` is stable while the payload is unchanged, so callers can
    deduplicate without comparing a continuously changing age.
    """
    now = time.time() if now is None else now
    expected = (
        SERVICE_CAMERA if this_service == SERVICE_CONTROLLER
        else SERVICE_CONTROLLER)
    try:
        data = _read_raw(path)
        entry = data.get(expected)
        if not isinstance(entry, dict):
            return [{
                "service": expected,
                "status": "missing",
                "snapshot_id": None,
                "payload": None,
                "age_s": None,
            }]
        written = entry.get("written_at")
        timestamp_error = None
        integrity_error = _entry_integrity_error(expected, entry)
        if not _finite_number(now):
            # The caller's wall clock is itself unusable.  Existing data is
            # not "missing", but freshness cannot be proven.
            status = "stale"
            age = None
            timestamp_error = "invalid_now"
        elif not _finite_number(written):
            # json.loads accepts NaN/Infinity by default.  Treat those and
            # booleans as invalid evidence, never as an accidentally fresh
            # snapshot.
            status = "stale"
            age = None
            timestamp_error = "invalid_written_at"
        elif float(written) > float(now):
            # max(0, now-written) previously converted arbitrary future
            # timestamps (including +Infinity) into a false-fresh age of 0.
            status = "stale"
            age = None
            timestamp_error = "future_written_at"
        else:
            raw_age = float(now) - float(written)
            age = round(raw_age, 1)
            status = "fresh" if raw_age <= max_age_s else "stale"
        if integrity_error is not None:
            # A present-but-corrupt record is stale/invalid evidence, never a
            # fresh snapshot.  Keep the payload attached for forensics but do
            # not allow read_foreign_drops() to relay it as trusted truth.
            status = "stale"
            _bump("read_errors")
        result = {
            "service": expected,
            "status": status,
            "snapshot_id": entry.get("snapshot_id"),
            "payload": entry.get("payload"),
            "age_s": age,
        }
        if timestamp_error is not None:
            result["timestamp_error"] = timestamp_error
        if integrity_error is not None:
            result["integrity_error"] = integrity_error
        return [result]
    except Exception:
        _bump("read_errors")
        return [{
            "service": expected,
            "status": "missing",
            "snapshot_id": None,
            "payload": None,
            "age_s": None,
        }]


def decode_throttled_mask(mask):
    """Return stable, JSON-friendly current + historical throttle facts."""
    if not isinstance(mask, int) or isinstance(mask, bool) or mask < 0:
        return {
            "current_mask": None,
            "historical_mask": None,
            "current": [],
            "historical": [],
            "unknown_mask": None,
        }
    current_mask = mask & _THROTTLE_CURRENT_MASK
    historical_mask = (mask & _THROTTLE_HISTORY_MASK) >> 16
    known_mask = _THROTTLE_CURRENT_MASK | _THROTTLE_HISTORY_MASK
    return {
        "current_mask": current_mask,
        "historical_mask": historical_mask,
        "current": [
            name for bit, name in enumerate(_THROTTLE_FACT_NAMES)
            if current_mask & (1 << bit)
        ],
        "historical": [
            name for bit, name in enumerate(_THROTTLE_FACT_NAMES)
            if historical_mask & (1 << bit)
        ],
        "unknown_mask": mask & ~known_mask,
    }


def _probe_temperature_c():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp",
                  encoding="ascii") as f:
            raw = f.read().strip()
        value = float(raw) / 1000.0
        if not math.isfinite(value):
            raise ValueError("non-finite temperature")
        return round(value, 1), None
    except Exception as exc:
        return None, type(exc).__name__


def _probe_throttled_mask():
    try:
        proc = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True,
            timeout=2, check=False)
        if proc.returncode != 0 or "=" not in proc.stdout:
            return None, (
                f"returncode_{proc.returncode}"
                if proc.returncode != 0 else "invalid_output")
        value = int(proc.stdout.strip().split("=", 1)[1], 16)
        if value < 0:
            raise ValueError("negative throttle mask")
        return value, None
    except Exception as exc:
        return None, type(exc).__name__


def collect_platform_health(dir_path, *, disk_low_bytes=512 * 1024 * 1024,
                            require_pi_probes=False):
    """Small live platform probe shared by Track A and Track B services.

    ``require_pi_probes=False`` keeps developer/CI hosts compatible: absent
    Raspberry Pi sysfs and ``vcgencmd`` are recorded as unavailable facts but
    do not make the host unhealthy.  Production Pi callers must explicitly
    pass ``require_pi_probes=True``; either missing/invalid probe then becomes
    a typed unhealthy reason instead of silently reading green.
    """
    reasons = []
    root = dir_path or "."
    writable = False
    free_bytes = None
    try:
        os.makedirs(root, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".platform_health_", dir=root)
        os.close(fd)
        os.remove(probe)
        writable = True
    except Exception:
        reasons.append("filesystem_readonly")
    try:
        free_bytes = int(shutil.disk_usage(root).free)
        if free_bytes < disk_low_bytes:
            reasons.append("disk_low")
    except Exception:
        reasons.append("disk_probe_failed")
    temp_c, temperature_probe_error = _probe_temperature_c()
    if temp_c is not None:
        if temp_c >= 80.0:
            reasons.append("thermal")
    elif require_pi_probes:
        reasons.append("temperature_probe_failed")

    throttled, throttled_probe_error = _probe_throttled_mask()
    throttle_facts = decode_throttled_mask(throttled)
    if throttled is None:
        if require_pi_probes:
            reasons.append("vcgencmd_probe_failed")
    else:
        if throttle_facts["current"]:
            reasons.append("pi_power_or_throttle")
        if throttle_facts["historical"]:
            reasons.append("pi_power_or_throttle_history")
    return {
        "ok": not reasons,
        "reasons": sorted(set(reasons)),
        "filesystem_writable": writable,
        "disk_free_bytes": free_bytes,
        "temperature_c": temp_c,
        "temperature_probe_ok": temp_c is not None,
        "temperature_probe_error": temperature_probe_error,
        "throttled_mask": throttled,
        "throttled_probe_ok": throttled is not None,
        "throttled_probe_error": throttled_probe_error,
        "throttle_facts": throttle_facts,
        "pi_probes_required": bool(require_pi_probes),
    }


def platform_fault_events(platform):
    """Return typed diagnostic tuples for a common platform probe result."""
    reasons = platform.get("reasons") if isinstance(platform, dict) else ()
    out = []
    for reason in sorted(set(reasons or ())):
        mapped = PLATFORM_EVENT_MAP.get(reason)
        if mapped is not None:
            out.append((reason, *mapped))
    return out


class WallMonotonicDriftMonitor:
    """Reusable detector for wall-clock steps relative to monotonic time.

    ``sample()`` returns a small fact dictionary.  Callers emit
    ``pi_clock_drift`` only when ``drifted`` is true (or when ``ok`` is false),
    which keeps episode policy outside this measurement helper.
    """

    def __init__(self, threshold_s=5.0, *, wall_clock=None,
                 monotonic_clock=None):
        if not _finite_number(threshold_s) or float(threshold_s) <= 0:
            raise ValueError("threshold_s must be finite and positive")
        self.threshold_s = float(threshold_s)
        self.wall_clock = wall_clock or time.time
        self.monotonic_clock = monotonic_clock or time.monotonic
        self._baseline_offset = None

    def reset(self):
        self._baseline_offset = None

    def sample(self, *, wall=None, monotonic=None):
        wall = self.wall_clock() if wall is None else wall
        monotonic = self.monotonic_clock() if monotonic is None else monotonic
        if not _finite_number(wall) or not _finite_number(monotonic):
            return {
                "ok": False,
                "drifted": False,
                "baseline": False,
                "code": "clock_probe_invalid",
                "step_s": None,
                "threshold_s": self.threshold_s,
            }
        offset = float(wall) - float(monotonic)
        if self._baseline_offset is None:
            self._baseline_offset = offset
            return {
                "ok": True,
                "drifted": False,
                "baseline": True,
                "code": None,
                "step_s": 0.0,
                "threshold_s": self.threshold_s,
            }
        step = offset - self._baseline_offset
        drifted = abs(step) >= self.threshold_s
        if drifted:
            # Re-baseline after reporting one wall step so an unchanged clock
            # offset does not generate the same event on every poll.
            self._baseline_offset = offset
        return {
            "ok": True,
            "drifted": drifted,
            "baseline": False,
            "code": "wall_step" if drifted else None,
            "step_s": round(step, 3),
            "threshold_s": self.threshold_s,
        }


def record_service_start(path, *, now=None, window_s=300.0, threshold=3,
                         max_recent=20):
    """Durably record one service start and classify a restart-loop window.

    The state file uses the controller's existing ``count``/``recent`` shape,
    but writes via fsync + replace + parent-directory fsync.  Corrupt,
    non-finite, and future prior timestamps are discarded and counted in the
    returned forensic facts rather than extending/suppressing the window.
    Never raises; ``persisted`` tells the caller whether durable evidence was
    actually committed.
    """
    now = time.time() if now is None else now
    result = {
        "persisted": False,
        "count": 0,
        "starts_in_window": 0,
        "window_s": window_s,
        "threshold": threshold,
        "restart_loop": False,
        "discarded_timestamps": 0,
        "error": None,
    }
    if not _finite_number(now):
        result["error"] = "invalid_now"
        return result
    if not _finite_number(window_s) or float(window_s) < 0:
        result["error"] = "invalid_window_s"
        return result
    if not isinstance(threshold, int) or isinstance(threshold, bool) \
            or threshold < 1:
        result["error"] = "invalid_threshold"
        return result
    if not isinstance(max_recent, int) or isinstance(max_recent, bool) \
            or max_recent < 1:
        result["error"] = "invalid_max_recent"
        return result

    count = 0
    raw_recent = []
    try:
        with open(path, encoding="utf-8") as f:
            previous = json.load(f)
        if isinstance(previous, dict):
            raw_count = previous.get("count", 0)
            if isinstance(raw_count, int) and not isinstance(raw_count, bool) \
                    and raw_count >= 0:
                count = raw_count
            candidate = previous.get("recent", [])
            if isinstance(candidate, list):
                raw_recent = candidate
    except FileNotFoundError:
        pass
    except Exception:
        # The replacement below repairs a corrupt counter file.  Callers still
        # receive the error fact and can emit a storage diagnostic if desired.
        result["error"] = "previous_state_invalid"

    valid_recent = []
    for value in raw_recent:
        if not _finite_number(value) or float(value) > float(now):
            result["discarded_timestamps"] += 1
            continue
        valid_recent.append(float(value))
    keep_prior = max_recent - 1
    valid_recent = valid_recent[-keep_prior:] if keep_prior else []
    valid_recent.append(float(now))
    count += 1
    in_window = [
        value for value in valid_recent
        if 0.0 <= float(now) - value <= float(window_s)
    ]
    result.update({
        "count": count,
        "starts_in_window": len(in_window),
        "restart_loop": len(in_window) >= threshold,
    })

    directory = os.path.dirname(path) or "."
    tmp = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".service_starts_", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({
                "count": count,
                "last_start_epoch": float(now),
                "recent": valid_recent,
            }, f, allow_nan=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
        _fsync_parent_dir(path)
        result["persisted"] = True
    except Exception as exc:
        result["error"] = f"write_failed:{type(exc).__name__}"
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return result


def _snapshot_lanes(service, payload):
    """Return the explicitly affected lanes carried by a snapshot."""
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("lanes")
    if service == SERVICE_CAMERA and not candidates:
        camera = payload.get("camera")
        if isinstance(camera, dict):
            candidates = camera.get("lanes")
    out = []
    for lane in candidates or ():
        if isinstance(lane, int) and not isinstance(lane, bool) \
                and 1 <= lane <= 32 and lane not in out:
            out.append(lane)
    return out


def snapshot_fault_events(service, payload):
    """Translate explicit snapshot evidence into alert-only event descriptors.

    This never creates control authority: descriptors are diagnostic facts for
    the currently running service to enqueue.  Known source facts retain their
    specific event type; only an aggregate ``ok=false`` with no safely
    attributable condition falls back to ``health_drop_unhealthy``.
    """
    if not isinstance(payload, dict):
        return []
    lanes = _snapshot_lanes(service, payload)
    events = []

    def add(severity, event_type, code, *, affected=None, evidence=None):
        event = {
            "severity": severity,
            "event_type": event_type,
            "code": code,
            "lanes": list(affected if affected is not None else lanes),
        }
        if evidence:
            event["evidence"] = evidence
        key = (event_type, code, tuple(event["lanes"]))
        if not any((e["event_type"], e.get("code"), tuple(e["lanes"])) == key
                   for e in events):
            events.append(event)

    platform = payload.get("platform")
    if isinstance(platform, dict):
        for reason, severity, event_type, code in platform_fault_events(
                platform):
            evidence = {"reason": reason}
            if reason in (
                    "pi_power_or_throttle",
                    "pi_power_or_throttle_history",
                    "vcgencmd_probe_failed"):
                evidence.update({
                    "throttled_mask": platform.get("throttled_mask"),
                    "throttle_facts": platform.get("throttle_facts"),
                    "throttled_probe_error":
                        platform.get("throttled_probe_error"),
                })
            elif reason == "temperature_probe_failed":
                evidence["temperature_probe_error"] = (
                    platform.get("temperature_probe_error"))
            add(severity, event_type, code, evidence=evidence)

    if service == SERVICE_CAMERA:
        camera = payload.get("camera")
        if isinstance(camera, dict) and camera.get("ok") is False:
            code = camera.get("code")
            if not isinstance(code, str) or not code.strip():
                code = "drop_unhealthy"
            add("warn", "camera_health", code.strip(),
                affected=_snapshot_lanes(service, payload),
                evidence={"camera": camera})
    elif service == SERVICE_CONTROLLER:
        # Backward-compatible direct fields plus the normalized platform block
        # written by current controller_daemon.
        direct_platform = []
        if payload.get("readonly_fs") is True:
            direct_platform.append("filesystem_readonly")
        if payload.get("thermal_warned") is True:
            direct_platform.append("thermal")
        if payload.get("disk_low") is True:
            direct_platform.append("disk_low")
        throttled = payload.get("last_throttled")
        throttle_facts = decode_throttled_mask(throttled)
        if throttle_facts["current"]:
            direct_platform.append("pi_power_or_throttle")
        if throttle_facts["historical"]:
            direct_platform.append("pi_power_or_throttle_history")
        for reason, severity, event_type, code in platform_fault_events(
                {"reasons": direct_platform}):
            evidence = {"reason": reason}
            if reason.startswith("pi_power_or_throttle"):
                evidence.update({
                    "throttled_mask": throttled,
                    "throttle_facts": throttle_facts,
                })
            add(severity, event_type, code, evidence=evidence)
        for board in payload.get("boards") or ():
            if not isinstance(board, dict) or board.get("identity_ok") is not False:
                continue
            lane = board.get("lane_id")
            affected = [lane] if isinstance(lane, int) and 1 <= lane <= 32 \
                else lanes
            reason = board.get("identity_reason")
            code = (reason.strip() if isinstance(reason, str) and reason.strip()
                    else "identity_unavailable")
            add("fault", "fw_identity", code, affected=affected,
                evidence={"lane_id": lane, "identity_reason": reason})

    if payload.get("ok") is False and not events:
        add("warn", HEALTH_DROP_UNHEALTHY_EVENT,
            f"{service}:unattributed")
    return events


def plan_foreign_relay(item, state):
    """Return episode-deduplicated relay events for one foreign status.

    ``state`` is a caller-owned mutable dictionary and therefore has no global
    cross-service coupling. Stale/missing periods do not falsely clear the
    last explicit faults. A later *fresh* snapshot is required to emit their
    recovery. Identical snapshots and unchanged fault episodes emit nothing.
    """
    if not isinstance(item, dict):
        return []
    service = item.get("service")
    status = item.get("status")
    if service not in (SERVICE_CAMERA, SERVICE_CONTROLLER) \
            or status not in ("fresh", "stale", "missing"):
        return []
    snapshot_id = item.get("snapshot_id")
    record = state.setdefault(service, {
        "fingerprint": None,
        "status": None,
        "active": {},
    })
    fingerprint = (status, snapshot_id)
    if record.get("fingerprint") == fingerprint:
        return []

    previous_status = record.get("status")
    record["fingerprint"] = fingerprint
    record["status"] = status
    payload = item.get("payload")
    base_detail = {
        "from_service": service,
        "status": status,
        "snapshot_id": snapshot_id,
        "age_s": item.get("age_s"),
        "snapshot": payload,
        "relay_only": True,
    }
    lanes = _snapshot_lanes(service, payload)
    planned = []

    if status != "fresh":
        if previous_status != status:
            planned.append({
                "severity": "warn",
                "event_type": "health_drop_stale",
                "code": f"{service}:{status}",
                "lanes": lanes,
                "detail": base_detail,
            })
        return planned

    if previous_status in ("stale", "missing"):
        planned.append({
            "severity": "info",
            "event_type": "recovered",
            "code": "health_drop_stale",
            "lanes": lanes,
            "detail": base_detail,
        })

    current = {}
    for event in snapshot_fault_events(service, payload):
        key = (event["event_type"], event.get("code"),
               tuple(event.get("lanes") or ()))
        current[key] = event
        if key not in record["active"]:
            detail = dict(base_detail)
            detail["evidence"] = event.get("evidence")
            planned.append({
                "severity": event["severity"],
                "event_type": event["event_type"],
                "code": event.get("code"),
                "lanes": event.get("lanes") or lanes,
                "detail": detail,
            })

    # A stale interval is absence of current proof, not recovery. Only this
    # fresh snapshot can explicitly clear conditions from the last fresh one.
    for key, event in record["active"].items():
        if key in current:
            continue
        detail = dict(base_detail)
        detail["recovered_event_type"] = event["event_type"]
        detail["recovered_code"] = event.get("code")
        planned.append({
            "severity": "info",
            "event_type": "recovered",
            "code": event["event_type"],
            "lanes": event.get("lanes") or lanes,
            "detail": detail,
        })
    record["active"] = current
    return planned


def _read_raw(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _bump("reads")
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        _bump("read_errors")
        return {}
