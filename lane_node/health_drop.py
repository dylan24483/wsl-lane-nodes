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

import copy
from datetime import datetime, timezone
import json
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

HEALTH_DROP_FILENAME = "health_drop.json"
DELIVERY_LEDGER_MAX_BYTES = 2 * 1024 * 1024
DELIVERY_LEDGER_MAX_DEPTH = 12
DELIVERY_LEDGER_MAX_STRING = 4096
DELIVERY_LEDGER_MAX_NODES = 50000
SERVICE_START_STATE_MAX_BYTES = 3 * 1024 * 1024
SERVICE_START_EVENT_MAX_BYTES = 16 * 1024
SERVICE_START_MAX_LANES = 32
SERVICE_START_MAX_RECENT = 4096
SERVICE_START_MAX_PENDING = 128
DELIVERY_RECEIPT_MAX_FILES = 256
DELIVERY_RECEIPT_MAX_BYTES = 64 * 1024 * 1024
DELIVERY_RECEIPT_MAX_LINES = 1_000_000
DELIVERY_RECEIPT_MAX_LINE_BYTES = 65536
DELIVERY_RECEIPT_EXACT = "exact"
DELIVERY_RECEIPT_ABSENT = "absent"
DELIVERY_RECEIPT_MISMATCH = "mismatch"
DELIVERY_RECEIPT_AMBIGUOUS = "ambiguous"
SERVICE_START_FUTURE_TOLERANCE_S = 300.0
SQLITE_INT64_MAX = (1 << 63) - 1
_service_start_lock = threading.RLock()

# Service keys (stable strings — the drop file is keyed by them).
SERVICE_CONTROLLER = "controller"   # Track-B: Pi/controller platform health
SERVICE_CAMERA = "camera"           # Track-A: camera/scoring health

DEFAULT_MAX_AGE_S = 900.0           # a foreign drop older than this is ignored
CONTROLLER_MODES = frozenset(("live", "shadow"))
IDENTITY_ASSURANCES = frozenset(
    ("verified", "legacy_unverified", "invalid"))
CONTROLLER_FSM_STATES = frozenset((
    "power_off", "manual_intervention", "ready", "sweep_to_guard",
    "guard_delay", "table_detect", "runthrough", "spotting",
    "table_finish", "fault",
))
SAFETY_TAP_FIELDS = frozenset(
    ("ne555", "wdog_kick", "arm_permit", "rp2040_ok"))
EXPECTED_CONTROLLER_MODE_ENV = "WSL_CONTROLLER_EXPECTED_MODE"
QUALIFIED_RELEASES_ENV = "WSL_RP2040_QUALIFIED_RELEASES"
CONTROLLER_BOARD_REQUIRED_FIELDS = frozenset((
    "lane_id", "controller_boot_id", "control_loop_seq", "board_rev",
    "fw_build", "fw_cfg", "identity_ok", "identity_reason",
    "controller_mode", "live_outputs_acknowledged", "arm_state", "fsm_state",
    "manual_rearm_required", "legacy_identity_mode", "identity_assurance",
    "arm_prerequisite_reason", "safety_taps",
))


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


def _controller_board_schema_error(board):
    """Return a stable error for an invalid controller health-drop board."""
    if not isinstance(board, dict):
        return "controller_board_not_object"
    missing = CONTROLLER_BOARD_REQUIRED_FIELDS - set(board)
    if missing:
        return "controller_board_missing_" + sorted(missing)[0]
    lane = board.get("lane_id")
    if type(lane) is not int or not 1 <= lane <= 32:
        return "controller_board_lane_invalid"
    if (
            not isinstance(board.get("controller_boot_id"), str)
            or not board["controller_boot_id"].strip()
            or len(board["controller_boot_id"]) > 200):
        return "controller_board_boot_id_invalid"
    if (
            type(board.get("control_loop_seq")) is not int
            or board["control_loop_seq"] < 0):
        return "controller_board_control_loop_seq_invalid"
    for field in (
            "identity_ok", "live_outputs_acknowledged", "arm_state",
            "manual_rearm_required", "legacy_identity_mode"):
        if type(board.get(field)) is not bool:
            return f"controller_board_{field}_invalid"
    if board.get("controller_mode") not in CONTROLLER_MODES:
        return "controller_board_mode_invalid"
    if board.get("identity_assurance") not in IDENTITY_ASSURANCES:
        return "controller_board_identity_assurance_invalid"
    fsm_state = board.get("fsm_state")
    if (
            not isinstance(fsm_state, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", fsm_state) is None):
        return "controller_board_fsm_state_invalid"
    for field in (
            "board_rev", "fw_build", "fw_cfg", "identity_reason",
            "arm_prerequisite_reason"):
        value = board.get(field)
        if value is not None and (
                not isinstance(value, str)
                or len(value) > 200
                or (field in ("board_rev", "fw_build", "fw_cfg")
                    and not value.strip())
                or (field in ("identity_reason", "arm_prerequisite_reason")
                    and not value.strip())):
            return f"controller_board_{field}_invalid"
    if not isinstance(board.get("board_rev"), str):
        return "controller_board_board_rev_invalid"
    if not board["identity_ok"] and not board.get("identity_reason"):
        return "controller_board_identity_reason_missing"
    taps = board.get("safety_taps")
    if (
            not isinstance(taps, dict)
            or set(taps) != SAFETY_TAP_FIELDS
            or any(value is not None and type(value) is not bool
                   for value in taps.values())):
        return "controller_board_safety_taps_invalid"
    if (
            board["board_rev"] == "revD"
            and board["identity_assurance"] == "verified"
            and (
                not isinstance(board.get("fw_build"), str)
                or not isinstance(board.get("fw_cfg"), str)
                or any(type(taps[field]) is not bool
                       for field in SAFETY_TAP_FIELDS))):
        return "controller_board_verified_revd_evidence_incomplete"
    return None


def _payload_schema_error(service, payload):
    if service != SERVICE_CONTROLLER:
        return None
    if not isinstance(payload, dict):
        return "controller_payload_not_object"
    boards = payload.get("boards")
    if not isinstance(boards, list) or not boards:
        return "controller_boards_missing"
    lanes = []
    for board in boards:
        error = _controller_board_schema_error(board)
        if error is not None:
            return error
        lanes.append(board["lane_id"])
    if len(lanes) != len(set(lanes)):
        return "controller_board_lane_duplicate"
    return None


def write_drop(path, service, payload):
    """Atomically merge {service: {written_at, payload}} into the drop file.
    Returns True on success, False on any failure (e.g. read-only FS). Never
    raises. Preserves other services' entries."""
    try:
        schema_error = _payload_schema_error(service, payload)
        if schema_error is not None:
            raise ValueError(schema_error)
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
        schema_error = _payload_schema_error(expected, entry.get("payload"))
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
        if integrity_error is not None or schema_error is not None:
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
        if schema_error is not None:
            result["schema_error"] = schema_error
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


_SERVICE_START_DELIVERY_FIELDS = {
    "service_restart": "service_restart_deliveries",
    "service_restart_loop": "service_restart_loop_deliveries",
}
_SERVICE_START_DESTINATION_FIELDS = {
    event_type: f"{event_type}_destinations"
    for event_type in _SERVICE_START_DELIVERY_FIELDS
}
_SERVICE_START_ACKED_FIELDS = {
    event_type: f"{event_type}_acked_lanes"
    for event_type in _SERVICE_START_DELIVERY_FIELDS
}
_SERVICE_START_PENDING_REQUIRED = {
    "count", "started_at_epoch", "started_at_monotonic",
    "starts_in_window", "window_s", "threshold", "restart_loop",
    "service_restart_pending", "service_restart_loop_pending",
}
_SERVICE_START_PENDING_ALLOWED = (
    _SERVICE_START_PENDING_REQUIRED
    | set(_SERVICE_START_DELIVERY_FIELDS.values())
    | set(_SERVICE_START_DESTINATION_FIELDS.values())
    | set(_SERVICE_START_ACKED_FIELDS.values())
)
_SERVICE_START_EVENT_FIELDS = {
    "ts_utc", "ts_mono", "lane_id", "severity", "event_type",
    "code", "detail", "source_id", "boot_id", "seq",
}


def _service_start_event_row_valid(row, event_type=None, item=None):
    if not isinstance(row, dict) or set(row) != _SERVICE_START_EVENT_FIELDS:
        return False
    lane = row.get("lane_id")
    seq = row.get("seq")
    expected_severity = {
        "service_restart": "info",
        "service_restart_loop": "fault",
    }.get(event_type)
    # Track-A and Track-B share this exact service-start WAL.  Their event
    # families are identical, while ``code`` preserves the producing service:
    # Track-A uses lane_node_start/lane_node and Track-B uses daemon_start.
    # Keep the accepted set explicit so a corrupt or cross-purpose row cannot
    # be "repaired" into a new delivery identity after a restart.
    expected_codes = {
        "service_restart": {"lane_node_start", "daemon_start"},
        "service_restart_loop": {"lane_node", "daemon_start"},
    }.get(event_type, set())
    if (not isinstance(lane, int) or isinstance(lane, bool)
            or not 1 <= lane <= SERVICE_START_MAX_LANES
            or not isinstance(seq, int) or isinstance(seq, bool)
            or not 0 < seq <= SQLITE_INT64_MAX
            or not isinstance(row.get("ts_utc"), str)
            or not 0 < len(row["ts_utc"]) <= 64
            or not _finite_number(row.get("ts_mono"))
            or float(row["ts_mono"]) < 0
            or not isinstance(row.get("source_id"), str)
            or not 0 < len(row["source_id"]) <= 120
            or not isinstance(row.get("boot_id"), str)
            or not 0 < len(row["boot_id"]) <= 80
            or row.get("event_type") != event_type
            or row.get("severity") != expected_severity
            or row.get("code") not in expected_codes
            or not isinstance(row.get("detail"), dict)):
        return False
    try:
        stamp = row["ts_utc"]
        parsed = datetime.fromisoformat(
            stamp[:-1] + "+00:00" if stamp.endswith(("Z", "z")) else stamp)
        if (parsed.tzinfo is None or parsed.utcoffset() is None
                or parsed.astimezone(timezone.utc).timestamp()
                > time.time() + SERVICE_START_FUTURE_TOLERANCE_S):
            return False
        if item is not None:
            detail = row["detail"]
            if set(detail) != {
                    "count", "started_at_epoch", "starts_in_window",
                    "window_s", "threshold", "restart_loop",
                    "replayed_start_evidence"}:
                return False
            if (not isinstance(detail["count"], int)
                    or isinstance(detail["count"], bool)
                    or not _finite_number(detail["started_at_epoch"])
                    or not isinstance(detail["starts_in_window"], int)
                    or isinstance(detail["starts_in_window"], bool)
                    or not _finite_number(detail["window_s"])
                    or not isinstance(detail["threshold"], int)
                    or isinstance(detail["threshold"], bool)
                    or not isinstance(detail["restart_loop"], bool)
                    or not isinstance(
                        detail["replayed_start_evidence"], bool)
                    or detail["count"] != item["count"]
                    or detail["started_at_epoch"]
                    != item["started_at_epoch"]
                    or detail["starts_in_window"]
                    != item["starts_in_window"]
                    or detail["window_s"] != item["window_s"]
                    or detail["threshold"] != item["threshold"]
                    or detail["restart_loop"] != item["restart_loop"]
                    or row["ts_mono"] != item["started_at_monotonic"]
                    or abs(
                        parsed.astimezone(timezone.utc).timestamp()
                        - float(item["started_at_epoch"])) > 0.0011):
                return False
        encoded = json.dumps(
            row, allow_nan=False, sort_keys=True, separators=(",", ":"))
        return len(encoded.encode("utf-8")) <= SERVICE_START_EVENT_MAX_BYTES
    except (OSError, OverflowError, TypeError, ValueError):
        return False


def _service_start_delivery_rows_valid(rows, event_type, item=None):
    if (not isinstance(rows, list)
            or not 0 < len(rows) <= SERVICE_START_MAX_LANES):
        return False
    lanes = set()
    identities = set()
    for row in rows:
        if not _service_start_event_row_valid(row, event_type, item):
            return False
        lane = row["lane_id"]
        identity = (row["source_id"], row["boot_id"], row["seq"])
        if lane in lanes or identity in identities:
            return False
        lanes.add(lane)
        identities.add(identity)
    return True


def _service_start_pending_item_valid(item):
    if (not isinstance(item, dict)
            or not _SERVICE_START_PENDING_REQUIRED <= set(item)
            or set(item) - _SERVICE_START_PENDING_ALLOWED):
        return False
    if (not isinstance(item["count"], int)
            or isinstance(item["count"], bool)
            or not 0 < item["count"] <= SQLITE_INT64_MAX
            or not _finite_number(item["started_at_epoch"])
            or float(item["started_at_epoch"]) < 0
            or not _finite_number(item["started_at_monotonic"])
            or float(item["started_at_monotonic"]) < 0
            or not isinstance(item["starts_in_window"], int)
            or isinstance(item["starts_in_window"], bool)
            or not 0 <= item["starts_in_window"] <= SQLITE_INT64_MAX
            or not _finite_number(item["window_s"])
            or float(item["window_s"]) < 0
            or not isinstance(item["threshold"], int)
            or isinstance(item["threshold"], bool)
            or not 1 <= item["threshold"] <= SQLITE_INT64_MAX
            or not isinstance(item["restart_loop"], bool)
            or not isinstance(item["service_restart_pending"], bool)
            or not isinstance(
                item["service_restart_loop_pending"], bool)):
        return False
    try:
        started_at = datetime.fromtimestamp(
            float(item["started_at_epoch"]), timezone.utc)
        if started_at.timestamp() \
                > time.time() + SERVICE_START_FUTURE_TOLERANCE_S:
            return False
    except (OverflowError, OSError, ValueError):
        return False
    if (item["restart_loop"]
            != (item["starts_in_window"] >= item["threshold"])
            or item["service_restart_loop_pending"]
            and not item["restart_loop"]
            or not (
                item["service_restart_pending"]
                or item["service_restart_loop_pending"])):
        return False
    for event_type, field in _SERVICE_START_DELIVERY_FIELDS.items():
        rows = item.get(field)
        destinations = item.get(
            _SERVICE_START_DESTINATION_FIELDS[event_type])
        acked_lanes = item.get(_SERVICE_START_ACKED_FIELDS[event_type])
        pending_field = f"{event_type}_pending"
        metadata_present = (
            destinations is not None or acked_lanes is not None)
        if rows is None:
            if metadata_present:
                return False
            continue
        if (
                not item[pending_field]
                or not _service_start_delivery_rows_valid(
                    rows, event_type, item)
                or not isinstance(destinations, list)
                or not 0 < len(destinations) <= SERVICE_START_MAX_LANES
                or not isinstance(acked_lanes, list)
                or len(acked_lanes) > SERVICE_START_MAX_LANES):
            return False
        destination_set = set()
        for lane in destinations:
            if (
                    not isinstance(lane, int) or isinstance(lane, bool)
                    or not 1 <= lane <= SERVICE_START_MAX_LANES
                    or lane in destination_set):
                return False
            destination_set.add(lane)
        acked_set = set()
        for lane in acked_lanes:
            if (
                    not isinstance(lane, int) or isinstance(lane, bool)
                    or lane not in destination_set or lane in acked_set):
                return False
            acked_set.add(lane)
        row_lanes = {row["lane_id"] for row in rows}
        if (
                row_lanes & acked_set
                or row_lanes | acked_set != destination_set):
            return False
    return True


def _read_service_start_state(path, *, reject_nonfinite=True):
    if os.path.getsize(path) > SERVICE_START_STATE_MAX_BYTES:
        raise ValueError("service-start state is oversized")
    with open(path, encoding="utf-8") as source:
        encoded = source.read(SERVICE_START_STATE_MAX_BYTES + 1)
    if len(encoded.encode("utf-8")) > SERVICE_START_STATE_MAX_BYTES:
        raise ValueError("service-start state is oversized")
    kwargs = {}
    if reject_nonfinite:
        kwargs["parse_constant"] = lambda value: (_ for _ in ()).throw(
            ValueError(f"invalid JSON constant {value}"))
    state = json.loads(encoded, **kwargs)
    if not isinstance(state, dict):
        raise ValueError("service-start state is not an object")
    return state


def _validated_service_start_pending(state):
    """Return a strictly bounded pending list or raise on any ambiguity."""
    if set(state) - {
            "count", "last_start_epoch", "recent", "pending_events",
            "delivery_overflow_count"}:
        raise ValueError("unknown service-start state field")
    count = state.get("count")
    recent = state.get("recent")
    if (not isinstance(count, int) or isinstance(count, bool)
            or not 0 <= count <= SQLITE_INT64_MAX
            or not isinstance(recent, list)
            or len(recent) > SERVICE_START_MAX_RECENT
            or any(not _finite_number(value) for value in recent)):
        raise ValueError("invalid service-start state")
    if "last_start_epoch" in state \
            and not _finite_number(state["last_start_epoch"]):
        raise ValueError("invalid service-start last-start time")
    overflow_count = state.get("delivery_overflow_count", 0)
    if (
            not isinstance(overflow_count, int)
            or isinstance(overflow_count, bool)
            or not 0 <= overflow_count <= SQLITE_INT64_MAX):
        raise ValueError("invalid service-start delivery-overflow count")
    pending = state.get("pending_events", [])
    if (not isinstance(pending, list)
            or len(pending) > SERVICE_START_MAX_PENDING):
        raise ValueError("invalid service-start pending list")
    counts = set()
    identities = set()
    for item in pending:
        if (not _service_start_pending_item_valid(item)
                or item["count"] > count
                or item["count"] in counts):
            raise ValueError("invalid service-start pending item")
        counts.add(item["count"])
        for delivery_field in _SERVICE_START_DELIVERY_FIELDS.values():
            for row in item.get(delivery_field, []):
                identity = (
                    row["source_id"], row["boot_id"], row["seq"])
                if identity in identities:
                    raise ValueError(
                        "duplicate service-start delivery identity")
                identities.add(identity)
    return pending


def _write_service_start_state(path, state, prefix):
    tmp = None
    try:
        encoded = json.dumps(
            state, allow_nan=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > SERVICE_START_STATE_MAX_BYTES:
            return False
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=prefix, dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, path)
        tmp = None
        _fsync_parent_dir(path)
        return True
    except Exception:
        return False
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


def record_service_start(path, *, now=None, window_s=300.0, threshold=3,
                         max_recent=20, track_delivery=False,
                         monotonic_now=None, max_pending=128):
    with _service_start_lock:
        return _record_service_start_unlocked(
            path, now=now, window_s=window_s, threshold=threshold,
            max_recent=max_recent, track_delivery=track_delivery,
            monotonic_now=monotonic_now, max_pending=max_pending)


def _record_service_start_unlocked(
        path, *, now=None, window_s=300.0, threshold=3,
        max_recent=20, track_delivery=False,
        monotonic_now=None, max_pending=128):
    """Durably record one service start and classify a restart-loop window.

    The state file uses the controller's existing ``count``/``recent`` shape,
    but writes via fsync + replace + parent-directory fsync.  Corrupt,
    non-finite, and future prior timestamps are discarded and counted.
    Ambiguous delivery obligations are never repaired or overwritten.  Never
    raises; ``persisted`` tells the caller whether durable evidence was
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
        "pending_delivery_overflow": 0,
        "pending_delivery_overflow_new": 0,
        "error": None,
    }
    if not _finite_number(now):
        result["error"] = "invalid_now"
        return result
    if float(now) < 0:
        result["error"] = "invalid_now"
        return result
    if not _finite_number(window_s) or float(window_s) < 0:
        result["error"] = "invalid_window_s"
        return result
    if not isinstance(threshold, int) or isinstance(threshold, bool) \
            or not 1 <= threshold <= SQLITE_INT64_MAX:
        result["error"] = "invalid_threshold"
        return result
    if not isinstance(max_recent, int) or isinstance(max_recent, bool) \
            or not 1 <= max_recent <= SERVICE_START_MAX_RECENT:
        result["error"] = "invalid_max_recent"
        return result
    if not isinstance(max_pending, int) or isinstance(max_pending, bool) \
            or not 1 <= max_pending <= SERVICE_START_MAX_PENDING:
        result["error"] = "invalid_max_pending"
        return result
    if not isinstance(track_delivery, bool):
        result["error"] = "invalid_track_delivery"
        return result

    count = 0
    raw_recent = []
    pending_events = []
    delivery_overflow_count = 0
    try:
        previous = _read_service_start_state(
            path, reject_nonfinite=False)
        if set(previous) - {
                "count", "last_start_epoch", "recent", "pending_events",
                "delivery_overflow_count"}:
            result["error"] = "previous_state_invalid"
            return result
        raw_count = previous.get("count", 0)
        if (not isinstance(raw_count, int)
                or isinstance(raw_count, bool)
                or not 0 <= raw_count <= SQLITE_INT64_MAX):
            result["error"] = "previous_state_invalid"
            return result
        count = raw_count
        raw_overflow_count = previous.get("delivery_overflow_count", 0)
        if (
                not isinstance(raw_overflow_count, int)
                or isinstance(raw_overflow_count, bool)
                or not 0 <= raw_overflow_count <= SQLITE_INT64_MAX):
            result["error"] = "previous_state_invalid"
            return result
        delivery_overflow_count = raw_overflow_count
        candidate = previous.get("recent", [])
        if isinstance(candidate, list):
            raw_recent = candidate
        else:
            result["error"] = "previous_state_invalid"
        if "last_start_epoch" in previous \
                and not _finite_number(previous["last_start_epoch"]):
            result["error"] = "previous_state_invalid"
        if "pending_events" in previous:
            candidate_pending = previous["pending_events"]
            try:
                probe = {
                    "count": count,
                    "recent": [],
                    "pending_events": candidate_pending,
                }
                pending_events = copy.deepcopy(
                    _validated_service_start_pending(probe))
            except Exception:
                # Delivery rows are an exact-once write-ahead record.  Never
                # discard or rewrite malformed rows because doing so could
                # create a second identity for an already accepted event.
                result["error"] = "previous_delivery_state_invalid"
                return result
    except FileNotFoundError:
        pass
    except Exception:
        # A corrupt document may contain an accepted-but-unacknowledged
        # delivery identity.  Preserve it for forensic/manual recovery.
        result["error"] = "previous_state_invalid"
        return result

    if count >= SQLITE_INT64_MAX:
        result["count"] = count
        result["error"] = "count_overflow"
        return result

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
    pending_overflow = 0
    if track_delivery:
        mono = time.monotonic() if monotonic_now is None else monotonic_now
        if not _finite_number(mono) or float(mono) < 0:
            result["error"] = "invalid_monotonic_now"
            return result
        new_obligation = {
            "count": count,
            "started_at_epoch": float(now),
            "started_at_monotonic": float(mono),
            "starts_in_window": len(in_window),
            "window_s": float(window_s),
            "threshold": threshold,
            "restart_loop": bool(result["restart_loop"]),
            "service_restart_pending": True,
            "service_restart_loop_pending": bool(result["restart_loop"]),
        }
        if len(pending_events) < max_pending:
            pending_events.append(new_obligation)
        else:
            # Never evict an existing obligation: it may already carry exact
            # rows accepted by one lane.  The new unrepresented start is
            # surfaced as explicit bounded-store loss instead.
            pending_overflow = 1
            if delivery_overflow_count >= SQLITE_INT64_MAX:
                result["error"] = "delivery_overflow_counter_saturated"
                return result
            delivery_overflow_count += 1
    result["pending_delivery_overflow"] = delivery_overflow_count
    result["pending_delivery_overflow_new"] = pending_overflow
    if track_delivery:
        result["pending_events"] = copy.deepcopy(pending_events)

    state = {
        "count": count,
        "last_start_epoch": float(now),
        "recent": valid_recent,
    }
    if pending_events:
        state["pending_events"] = pending_events
    if delivery_overflow_count:
        # This is a monotonic manual-reconciliation latch.  Clearing pending
        # rows cannot erase proof that an earlier startup occurrence could not
        # be represented in the bounded WAL.
        state["delivery_overflow_count"] = delivery_overflow_count
    if _write_service_start_state(
            path, state, ".service_starts_"):
        result["persisted"] = True
    else:
        result["error"] = "write_failed"
    return result


def prepare_service_start_deliveries(path, count, event_type, rows):
    """Persist exact Track-A per-lane rows before any transport offer.

    If a prior preparation already exists, its immutable rows win.  Returning
    ``None`` means no row may be offered because durable preparation was not
    proven.
    """
    pending_field = {
        "service_restart": "service_restart_pending",
        "service_restart_loop": "service_restart_loop_pending",
    }.get(event_type)
    delivery_field = _SERVICE_START_DELIVERY_FIELDS.get(event_type)
    if (pending_field is None
            or not isinstance(count, int) or isinstance(count, bool)
            or not 0 < count <= SQLITE_INT64_MAX
            or not isinstance(rows, list)):
        return None
    with _service_start_lock:
        try:
            state = _read_service_start_state(path)
            pending = _validated_service_start_pending(state)
            for item in pending:
                if item["count"] != count:
                    continue
                if not item[pending_field]:
                    return None
                existing = item.get(delivery_field)
                if existing is not None:
                    return copy.deepcopy(existing)
                if not _service_start_delivery_rows_valid(
                        rows, event_type, item):
                    return None
                item[delivery_field] = copy.deepcopy(rows)
                item[_SERVICE_START_DESTINATION_FIELDS[event_type]] = sorted(
                    row["lane_id"] for row in rows)
                item[_SERVICE_START_ACKED_FIELDS[event_type]] = []
                if not _service_start_pending_item_valid(item):
                    return None
                if not _write_service_start_state(
                        path, state, ".service_starts_prepare_"):
                    return None
                return copy.deepcopy(item[delivery_field])
        except Exception:
            return None
    return None


def read_service_start_pending(path):
    """Return a validated copy of startup obligations, or ``None`` on defect."""
    with _service_start_lock:
        try:
            state = _read_service_start_state(path)
            return copy.deepcopy(_validated_service_start_pending(state))
        except Exception:
            return None


def delivery_receipt_status(directory, row):
    """Classify an exact prepared row in bounded local ``diag-*.jsonl``.

    Identity-only matching is insufficient: if a corrupted/tampered row carries
    the same delivery identity with a different payload, the server will dedupe
    the intended row behind it.  Such a mismatch, any unreadable/corrupt line,
    or a scan that exceeds the explicit bounds is therefore ``ambiguous`` or
    ``mismatch`` and must block automatic acknowledgement.
    """
    if not isinstance(directory, str) or not isinstance(row, dict):
        return DELIVERY_RECEIPT_AMBIGUOUS
    try:
        wanted = (row["source_id"], row["boot_id"], row["seq"])
        if (
                not isinstance(wanted[0], str) or not wanted[0]
                or not isinstance(wanted[1], str) or not wanted[1]
                or not isinstance(wanted[2], int)
                or isinstance(wanted[2], bool)
                or not 0 < wanted[2] <= SQLITE_INT64_MAX):
            return DELIVERY_RECEIPT_AMBIGUOUS
        entries = sorted(
            (
                entry for entry in os.scandir(directory)
                if entry.is_file()
                and entry.name.startswith("diag-")
                and entry.name.endswith(".jsonl")
            ),
            key=lambda entry: entry.name,
            reverse=True)
    except FileNotFoundError:
        return DELIVERY_RECEIPT_ABSENT
    except Exception:
        return DELIVERY_RECEIPT_AMBIGUOUS
    if len(entries) > DELIVERY_RECEIPT_MAX_FILES:
        return DELIVERY_RECEIPT_AMBIGUOUS

    total_bytes = 0
    total_lines = 0
    found = False
    for entry in entries:
        try:
            size = entry.stat().st_size
            if size < 0:
                return DELIVERY_RECEIPT_AMBIGUOUS
            total_bytes += size
            if total_bytes > DELIVERY_RECEIPT_MAX_BYTES:
                return DELIVERY_RECEIPT_AMBIGUOUS
            with open(entry.path, "rb") as handle:
                while True:
                    raw = handle.readline(DELIVERY_RECEIPT_MAX_LINE_BYTES + 2)
                    if not raw:
                        break
                    total_lines += 1
                    if (
                            total_lines > DELIVERY_RECEIPT_MAX_LINES
                            or len(raw) > DELIVERY_RECEIPT_MAX_LINE_BYTES
                            or not raw.endswith(b"\n")):
                        return DELIVERY_RECEIPT_AMBIGUOUS
                    try:
                        candidate = json.loads(
                            raw.decode("utf-8"),
                            parse_constant=lambda value: (
                                _ for _ in ()).throw(ValueError(value)))
                    except Exception:
                        return DELIVERY_RECEIPT_AMBIGUOUS
                    if not isinstance(candidate, dict):
                        return DELIVERY_RECEIPT_AMBIGUOUS
                    identity = (
                        candidate.get("source_id"),
                        candidate.get("boot_id"),
                        candidate.get("seq"),
                    )
                    if identity != wanted:
                        continue
                    if candidate != row:
                        return DELIVERY_RECEIPT_MISMATCH
                    found = True
        except Exception:
            return DELIVERY_RECEIPT_AMBIGUOUS
    return DELIVERY_RECEIPT_EXACT if found else DELIVERY_RECEIPT_ABSENT


def acknowledge_service_start_lane(
        path, count, event_type, lane, source_id, boot_id, seq):
    """Durably acknowledge one exact Track-A lane row.

    Other lanes and the other event family remain untouched.  The identity
    comparison prevents a delayed receipt from clearing a newly prepared row.
    """
    pending_field = {
        "service_restart": "service_restart_pending",
        "service_restart_loop": "service_restart_loop_pending",
    }.get(event_type)
    delivery_field = _SERVICE_START_DELIVERY_FIELDS.get(event_type)
    destination_field = _SERVICE_START_DESTINATION_FIELDS.get(event_type)
    acked_field = _SERVICE_START_ACKED_FIELDS.get(event_type)
    if (pending_field is None
            or not isinstance(count, int) or isinstance(count, bool)
            or not 0 < count <= SQLITE_INT64_MAX
            or not isinstance(lane, int) or isinstance(lane, bool)
            or not 1 <= lane <= SERVICE_START_MAX_LANES
            or not isinstance(source_id, str)
            or not 0 < len(source_id) <= 120
            or not isinstance(boot_id, str)
            or not 0 < len(boot_id) <= 80
            or not isinstance(seq, int) or isinstance(seq, bool)
            or not 0 < seq <= SQLITE_INT64_MAX):
        return False
    identity = (source_id, boot_id, seq)
    with _service_start_lock:
        try:
            state = _read_service_start_state(path)
            pending = _validated_service_start_pending(state)
            found_count = False
            changed = False
            kept = []
            for item in pending:
                current = copy.deepcopy(item)
                if current["count"] == count:
                    found_count = True
                    if not current[pending_field]:
                        kept.append(current)
                        continue
                    deliveries = current.get(delivery_field)
                    if deliveries is None:
                        # A boolean obligation without a prepared WAL cannot
                        # prove which concrete event was accepted.
                        return False
                    matching_lane = [
                        row for row in deliveries
                        if row["lane_id"] == lane]
                    if not matching_lane:
                        # The exact lane was already durably removed.
                        kept.append(current)
                        continue
                    row = matching_lane[0]
                    if (row["source_id"], row["boot_id"], row["seq"]) \
                            != identity:
                        return False
                    remaining = [
                        row for row in deliveries
                        if row["lane_id"] != lane]
                    if remaining:
                        current[delivery_field] = remaining
                        current[acked_field] = sorted(
                            set(current.get(acked_field, [])) | {lane})
                    else:
                        current.pop(delivery_field, None)
                        current.pop(destination_field, None)
                        current.pop(acked_field, None)
                        current[pending_field] = False
                    changed = True
                if (current["service_restart_pending"]
                        or current["service_restart_loop_pending"]):
                    kept.append(current)
            if not found_count:
                # The whole occurrence was already durably acknowledged.
                return True
            if not changed:
                # Idempotent repeat after this lane's row was removed.
                return True
            for item in kept:
                if not _service_start_pending_item_valid(item):
                    return False
            if kept:
                state["pending_events"] = kept
            else:
                state.pop("pending_events", None)
            return _write_service_start_state(
                path, state, ".service_starts_lane_ack_")
        except Exception:
            return False


def acknowledge_service_start_event(path, count, event_type):
    """Durably clear one accepted startup-event obligation.

    The start counter and its delivery obligations share one atomic state file,
    so a restart cannot forget a rejected ``service_restart`` or
    ``service_restart_loop`` occurrence.  Never raises; False leaves the
    obligation intact for retry.
    """
    pending_field = {
        "service_restart": "service_restart_pending",
        "service_restart_loop": "service_restart_loop_pending",
    }.get(event_type)
    delivery_field = _SERVICE_START_DELIVERY_FIELDS.get(event_type)
    if (pending_field is None
            or not isinstance(count, int) or isinstance(count, bool)
            or not 0 < count <= SQLITE_INT64_MAX):
        return False
    with _service_start_lock:
        try:
            state = _read_service_start_state(path)
            pending = _validated_service_start_pending(state)
            found = False
            kept = []
            for item in pending:
                current = copy.deepcopy(item)
                if current["count"] == count:
                    found = True
                    # Track-B owns one lane and uses the legacy whole-event
                    # acknowledgement.  A Track-A per-lane WAL may never be
                    # bypassed by this compatibility API.
                    if current.get(delivery_field):
                        return False
                    current[pending_field] = False
                if (current["service_restart_pending"]
                        or current["service_restart_loop_pending"]):
                    kept.append(current)
            if not found:
                # Idempotent acknowledgement: an already-cleared record is
                # success.
                return True
            if kept:
                state["pending_events"] = kept
            else:
                state.pop("pending_events", None)
            return _write_service_start_state(
                path, state, ".service_starts_ack_")
        except Exception:
            return False


def write_delivery_ledger(path, payload):
    """Atomically fsync a bounded diagnostics-delivery state document."""
    if not isinstance(payload, dict):
        return False
    tmp = None
    try:
        encoded = json.dumps(
            payload, allow_nan=False, sort_keys=True, separators=(",", ":"))
        if (len(encoded.encode("utf-8")) > DELIVERY_LEDGER_MAX_BYTES
                or not _delivery_ledger_shape_ok(payload)):
            return False
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".diag_delivery_", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, path)
        tmp = None
        _fsync_parent_dir(path)
        return True
    except Exception:
        return False
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _delivery_ledger_shape_ok(payload):
    """Reject pathological nesting/strings before a relay ledger is trusted."""
    remaining = [DELIVERY_LEDGER_MAX_NODES]

    def visit(value, depth):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > DELIVERY_LEDGER_MAX_DEPTH:
            return False
        if isinstance(value, str):
            return len(value) <= DELIVERY_LEDGER_MAX_STRING
        if value is None or isinstance(value, (bool, int, float)):
            return not isinstance(value, float) or math.isfinite(value)
        if isinstance(value, list):
            return all(visit(item, depth + 1) for item in value)
        if isinstance(value, dict):
            return all(
                isinstance(key, str)
                and len(key) <= DELIVERY_LEDGER_MAX_STRING
                and visit(item, depth + 1)
                for key, item in value.items())
        return False

    return visit(payload, 0)


def read_delivery_ledger(path, *, version=1):
    """Read one exact-version delivery ledger; return None on any defect."""
    try:
        if os.path.getsize(path) > DELIVERY_LEDGER_MAX_BYTES:
            return None
        with open(path, encoding="utf-8") as source:
            encoded = source.read(DELIVERY_LEDGER_MAX_BYTES + 1)
        if len(encoded.encode("utf-8")) > DELIVERY_LEDGER_MAX_BYTES:
            return None
        payload = json.loads(
            encoded,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {value}")))
        if (not isinstance(payload, dict)
                or payload.get("version") != version
                or not _delivery_ledger_shape_ok(payload)):
            return None
        return payload
    except FileNotFoundError:
        return {}
    except Exception:
        return None


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


def _qualified_release_tuples():
    raw = os.environ.get(QUALIFIED_RELEASES_ENV)
    if raw is None or raw == "":
        return frozenset(), "qualified_release_policy_missing"
    if raw != raw.strip() or any(char.isspace() for char in raw):
        return frozenset(), "qualified_release_policy_invalid"
    tuples = []
    for item in raw.split(","):
        parts = item.split("|")
        if (
                len(parts) != 3
                or any(not part for part in parts)
                or re.fullmatch(r"rev[A-Za-z0-9._-]+", parts[0]) is None):
            return frozenset(), "qualified_release_policy_invalid"
        tuples.append(tuple(parts))
    if len(tuples) != len(set(tuples)):
        return frozenset(), "qualified_release_policy_invalid"
    return frozenset(tuples), None


def _controller_board_policy_reasons(board):
    """Return diagnostic-only safety reasons for one validated board block."""
    reasons = []
    expected_mode_raw = os.environ.get(EXPECTED_CONTROLLER_MODE_ENV)
    expected_mode = (
        "live" if expected_mode_raw is None or expected_mode_raw == ""
        else expected_mode_raw)
    if expected_mode_raw is None or expected_mode_raw == "":
        reasons.append("controller_mode_policy_missing")
    elif expected_mode not in CONTROLLER_MODES:
        reasons.append("controller_mode_policy_invalid")
    elif board["controller_mode"] != expected_mode:
        reasons.append("controller_mode_mismatch")
    if (
            expected_mode == "live"
            and board["live_outputs_acknowledged"] is not True):
        reasons.append("live_outputs_not_acknowledged")
    if board["identity_assurance"] != "verified":
        reasons.append(
            "identity_assurance_" + board["identity_assurance"])
    if (
            (
                board["legacy_identity_mode"]
                and board["identity_assurance"] != "legacy_unverified"
            )
            or (
                not board["legacy_identity_mode"]
                and board["identity_assurance"] == "legacy_unverified"
            )
            or (
                board["identity_assurance"] == "verified"
                and board["identity_ok"] is not True
            )):
        reasons.append("identity_assurance_inconsistent")
    if board["manual_rearm_required"]:
        reasons.append("manual_rearm_required")

    arm_state = board["arm_state"]
    fsm_state = board["fsm_state"]
    disarmed_states = {"power_off", "manual_intervention", "fault"}
    if fsm_state not in CONTROLLER_FSM_STATES:
        reasons.append("fsm_state_unknown")
    if (
            (arm_state and fsm_state in disarmed_states)
            or (arm_state and board["manual_rearm_required"])
            or (board["controller_mode"] == "shadow" and arm_state)
            or (
                board["controller_mode"] == "live"
                and not arm_state
                and not board["manual_rearm_required"]
                and fsm_state in CONTROLLER_FSM_STATES - disarmed_states
            )):
        reasons.append("arm_fsm_inconsistent")
    if (
            board.get("arm_prerequisite_reason")
            and not board["manual_rearm_required"]):
        reasons.append("arm_prerequisite_inconsistent")

    taps = board["safety_taps"]
    if (
            board["controller_mode"] == "live"
            and type(taps["arm_permit"]) is bool
            and arm_state is not taps["arm_permit"]):
        reasons.append("arm_permit_mismatch")
    if arm_state and taps["ne555"] is not True:
        reasons.append("arm_without_ne555")
    if arm_state and taps["rp2040_ok"] is not True:
        reasons.append("arm_without_rp2040_ok")

    qualified, qualified_error = _qualified_release_tuples()
    if qualified_error is not None:
        reasons.append(qualified_error)
    elif (
            board["board_rev"], board["fw_build"], board["fw_cfg"]) not in qualified:
        reasons.append("firmware_release_not_qualified")
    return sorted(set(reasons))


def controller_board_policy_reasons(board):
    """Public exact policy verdict shared by writers and relay consumers."""
    error = _controller_board_schema_error(board)
    if error is not None:
        return [error]
    return _controller_board_policy_reasons(board)


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
            if _controller_board_schema_error(board) is not None:
                continue
            lane = board.get("lane_id")
            affected = [lane] if isinstance(lane, int) and 1 <= lane <= 32 \
                else lanes
            if board.get("identity_ok") is False:
                reason = board.get("identity_reason")
                code = (
                    reason.strip()
                    if isinstance(reason, str) and reason.strip()
                    else "identity_unavailable")
                add("fault", "fw_identity", code, affected=affected,
                    evidence={"lane_id": lane, "identity_reason": reason})
            policy_evidence = {
                field: board.get(field)
                for field in (
                    "lane_id", "controller_mode",
                    "live_outputs_acknowledged", "arm_state", "fsm_state",
                    "manual_rearm_required", "legacy_identity_mode",
                    "identity_assurance", "arm_prerequisite_reason",
                    "safety_taps", "board_rev", "fw_build", "fw_cfg")
            }
            for reason in controller_board_policy_reasons(board):
                add(
                    "fault", HEALTH_DROP_UNHEALTHY_EVENT,
                    f"controller:{lane}:{reason}",
                    affected=affected, evidence=policy_evidence)

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
        # A process may have observed both missing and stale episodes before a
        # fresh hand-off returns.  Offer exact-family clears for both possible
        # codes; the delivery ledger stages only those with a causal alert.
        for unavailable_status in ("missing", "stale"):
            detail = dict(base_detail)
            detail["recovered_event_type"] = "health_drop_stale"
            detail["recovered_code"] = (
                f"{service}:{unavailable_status}")
            planned.append({
                "severity": "info",
                "event_type": "recovered",
                "code": "health_drop_stale",
                "lanes": lanes,
                "detail": detail,
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
