#!/usr/bin/env python3
"""SQLite storage for the Machine/Equipment diagnostics domain (Phase 8).

Owner-side store for machine_cycles + machine_events per
docs/phase8_diagnostics_scope_2026-07-19.md §2: the :8766 lane-node
server is the SINGLE OWNER of the machine domain — wsl_api is a pure
proxy and never keeps a second writable copy. These tables share no rows
and no status enums with any other domain (roadmap boundary rule);
machine_events may point at a manual lane_incidents row via incident_id
but never shares its vocabulary.

Schema notes (scope §2 + target-conditions catalog corrections):
- severity is the ONLY CHECK-constrained enum. The 2026-04-17 lesson:
  changing a SQLite CHECK forces a full table rebuild, and the
  event_type / cycle_type taxonomies are guaranteed to grow
  (cam_overrun, motion_no_run, current-switch codes are all queued for
  later phases). event_type / cycle_type / final_state are validated in
  code — extend EVENT_TYPES / CYCLE_TYPES / FINAL_STATES below.
- Timestamps are UTC ISO, normalized to a fixed-width form so
  lexicographic comparison == chronological comparison. business_date is
  computed AT WRITE from the row's own timestamp using the wsl-systems
  business-day precedent: WSL_BUSINESS_DAY_TIMEZONE /
  WSL_BUSINESS_DAY_CUTOFF (default America/Los_Angeles @ 04:00 — the
  same envs wsl_fnb_ext._netsuite_business_day_window reads).
- Durations are integer milliseconds.

Kill-switch: WSL_MACHINE_DIAG (default ON; set 0/false/no/off to
disable — same convention as WSL_FLIGHT_RECORDER). Disabled = ingest
writes refused (StoreDisabled) + retention pruning skipped. Reads keep
working so already-recorded data stays visible, and desk ack/resolve on
existing rows keeps working too.

Retention: machine_events older than WSL_MACHINE_EVENT_RETENTION_DAYS
(default 90) are pruned at startup + daily by a background daemon
thread (start_retention_thread, called from lane_node_server.main).
The loop never raises — failures bump an error counter surfaced via
health_counts() -> /api/health "machine".
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger('machine_store')

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Own DB file, separate from lane_state.db — the scoring snapshot store
# rewrites/deletes whole rows on every save and must never race the
# append-mostly diagnostics tables. Override via MACHINE_DB_PATH (same
# convention as STATE_DB_PATH).
DEFAULT_DB_PATH = _REPO_ROOT / "machine_diag.db"
DB_PATH = Path(os.environ.get("MACHINE_DB_PATH", DEFAULT_DB_PATH))

# Env kill-switch. Default ON; set to "0"/"false"/"no"/"off" to disable.
DISABLE_ENV = "WSL_MACHINE_DIAG"
_FALSEY = ("0", "false", "no", "off", "")

RETENTION_ENV = "WSL_MACHINE_EVENT_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 90

# Business-day envs — shared precedent with wsl-systems (wsl_fnb_ext).
BUSINESS_TZ_ENV = "WSL_BUSINESS_DAY_TIMEZONE"
BUSINESS_CUTOFF_ENV = "WSL_BUSINESS_DAY_CUTOFF"
DEFAULT_BUSINESS_TZ = "America/Los_Angeles"
DEFAULT_BUSINESS_CUTOFF = "04:00"

# Writer-validated vocabularies (NO CHECK constraints — extend freely,
# no table rebuild needed). R3-1a (2026-07-23): these are LOADED from
# server/machine_contract.json — the single source of truth — not
# re-declared here. The three-round drift class (a type emitted by a
# client but absent from this validator, e.g. the fw_identity poison pill
# that 400'd whole batches and stalled the outbox cursor) is now
# structurally impossible: there is exactly one list, and a NEW emit site
# that skips the contract is caught by tests/test_event_type_vocab_coverage.
# Fail posture: a live server must not die because a deploy dropped the JSON
# mid-copy, so a missing file falls back to accept-any-string on the
# taxonomy (never on delivery identity) with a loud warning; the CI vocab
# test still gates development.
import machine_contract as _contract  # noqa: E402

try:
    _VOCAB = _contract.load_vocab()
    _CONTRACT_SHA256_AT_LOAD = _contract.contract_sha256()
    _EVENT_TYPES_STRICT = True
    _CONTRACT_LOAD_ERROR = None
except _contract.ContractUnavailable as exc:
    _VOCAB = _contract.load_vocab(allow_fallback=True)
    _CONTRACT_SHA256_AT_LOAD = None
    _EVENT_TYPES_STRICT = False
    _CONTRACT_LOAD_ERROR = str(exc)
    log.error("machine_contract.json unavailable — diagnostics are using the "
              "frozen fail-closed vocabulary and contract health is DEGRADED. "
              "Restore the live contract and restart before release.")

EVENT_TYPES = set(_VOCAB["event_types"])  # frozen allow-set if live contract failed
SEVERITIES = _VOCAB["severities"]        # the ONLY CHECK enum
CYCLE_TYPES = set(_VOCAB["cycle_types"])
FINAL_STATES = set(_VOCAB["final_states"])
RECORD_KINDS = set(_VOCAB["record_kinds"])

# The six CamTelemetry intervals (scope §2 schema), integer ms.
INTERVAL_COLUMNS = _VOCAB["interval_columns"]


def contract_status():
    """Status of the exact live contract and the vocabulary loaded at start."""
    try:
        live_sha = _contract.contract_sha256()
        loaded = True
        error = None
    except _contract.ContractUnavailable as exc:
        live_sha = None
        loaded = False
        error = str(exc)
    strict = bool(
        loaded
        and _EVENT_TYPES_STRICT
        and _CONTRACT_SHA256_AT_LOAD
        and live_sha == _CONTRACT_SHA256_AT_LOAD
    )
    if loaded and not strict and error is None:
        error = "live contract differs from the contract loaded at service start"
    if _CONTRACT_LOAD_ERROR and error is None:
        error = _CONTRACT_LOAD_ERROR
    return {
        "loaded": loaded,
        "strict": strict,
        "sha256": live_sha if loaded else None,
        "loaded_sha256": _CONTRACT_SHA256_AT_LOAD,
        "error": error,
    }


def diagnostics_contract_ready():
    status = contract_status()
    return status["loaded"] and status["strict"]


# ------------------------------------------------------------------
# Board liveness leases (Codex R2-10, 2026-07-21). Every configured
# machine lane carries an EXPLICIT state in the /api/machine/health
# rollup — a dead board must never look healthy by omission:
#   MAINTENANCE  mechanic flagged the machine (suppresses alerting)
#   OFFLINE      lease expired: nothing heard within the lease window
#   UNKNOWN      never heard from this board (no lease recorded)
#   FAULT        lease fresh + an open fault event latched
#   HEALTHY      lease fresh, no open fault
# Precedence is exactly that order. The lease is touched by the WS
# HELLO/HEARTBEAT path (the Pi daemon's live link, ~5 s cadence) and by
# machine event/cycle ingest — EXCEPT synthetic deploy markers
# (code 'deploy_marker:*'), which are posted by deploy.ps1 on WSL-SRV
# and must not fake board liveness.
# ------------------------------------------------------------------
MACHINE_STATES = _VOCAB["states"]   # R3-1a: loaded from the contract vocab
LEASE_WINDOW_ENV = "WSL_MACHINE_LEASE_S"
DEFAULT_LEASE_WINDOW_S = 90.0
OUTBOX_STALL_ENV = "WSL_MACHINE_OUTBOX_STALL_S"
DEFAULT_OUTBOX_STALL_S = 300.0
PRODUCER_FUTURE_TOLERANCE_S = 300.0
MACHINE_LANES_ENV = "WSL_MACHINE_LANES"
DEFAULT_MACHINE_LANES = "21,22"   # PHASE_8_PAIRS; grows with the rollout
LEASE_FUTURE_TOLERANCE_S = 5.0


def lease_window_s():
    raw = os.environ.get(LEASE_WINDOW_ENV, "").strip()
    if not raw:
        return DEFAULT_LEASE_WINDOW_S
    try:
        val = float(raw)
        if val <= 0:
            raise ValueError(raw)
        return val
    except ValueError:
        _warn_once('lease_window', f"Bad {LEASE_WINDOW_ENV}={raw!r} — "
                                   f"using {DEFAULT_LEASE_WINDOW_S}")
        return DEFAULT_LEASE_WINDOW_S


def outbox_stall_s():
    raw = os.environ.get(OUTBOX_STALL_ENV, "").strip()
    if not raw:
        return DEFAULT_OUTBOX_STALL_S
    try:
        val = float(raw)
        if val <= 0:
            raise ValueError(raw)
        return val
    except ValueError:
        _warn_once('outbox_stall', f"Bad {OUTBOX_STALL_ENV}={raw!r} — "
                                   f"using {DEFAULT_OUTBOX_STALL_S}")
        return DEFAULT_OUTBOX_STALL_S


def configured_lanes():
    """Machine lanes that must ALWAYS appear in the health rollup (with
    state UNKNOWN when never heard from). Env WSL_MACHINE_LANES, comma
    separated, default the Phase 8 pilot pair."""
    raw = os.environ.get(MACHINE_LANES_ENV, "").strip() or DEFAULT_MACHINE_LANES
    lanes = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            lane = int(part)
        except ValueError:
            _warn_once('machine_lanes',
                       f"Bad {MACHINE_LANES_ENV}={raw!r} entry {part!r} — skipped")
            continue
        if 1 <= lane <= 32 and lane not in lanes:
            lanes.append(lane)
    return lanes


def _lease_timestamp_age(raw, now_dt, field):
    """Parse a persisted lease timestamp without making clock rollback green."""
    if not raw:
        return None, None, None
    try:
        text = str(raw).strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("timestamp is not timezone-aware")
        delta = (now_dt - stamp).total_seconds()
        if delta < -LEASE_FUTURE_TOLERANCE_S:
            return None, None, f"{field}_timestamp_future"
        return raw, max(0.0, round(delta, 1)), None
    except (TypeError, ValueError, OverflowError):
        return None, None, f"{field}_timestamp_invalid"

# Bound on one POST /api/machine/events batch (the Pi ships bounded
# queues; anything bigger than this is a bug, not a backlog).
MAX_EVENT_BATCH = 500

# Baseline summary sample size — mirrors cam_telemetry's 30-sample
# minimum before drift alarms are trusted.
BASELINE_SAMPLE_CYCLES = 30

# Fresh connection per call + module lock, same pattern as state_store
# (a sqlite3 connection is not portable across threads; the HTTP handler
# thread and the retention thread both write).
_db_lock = threading.Lock()

_err_lock = threading.Lock()
_error_count = 0
_last_dup_count = 0   # R2-12: identity-deduped rows in the last insert_events
_last_cycle_dup = False

_warned = set()

_retention_started = threading.Event()
_retention_wake = threading.Event()


def acquire_backup_lock(timeout_s):
    """Quiesce every machine-domain DB access for a bounded snapshot."""
    return _db_lock.acquire(timeout=float(timeout_s))


def release_backup_lock():
    """Release a lock acquired by :func:`acquire_backup_lock`."""
    _db_lock.release()


class StoreDisabled(RuntimeError):
    """Raised by ingest writes when WSL_MACHINE_DIAG is switched off."""


class StoreBusy(TimeoutError):
    """Raised when a bounded diagnostics operation cannot acquire the store."""


@contextmanager
def _store_lock(timeout_s=None):
    """Hold the process-local DB lock, optionally against one deadline.

    The bounded form is enforced inside the worker call.  An asyncio timeout
    alone would leave a queued thread free to commit after its caller had
    already failed closed.
    """
    deadline = None
    if timeout_s is None:
        _db_lock.acquire()
    else:
        timeout_s = float(timeout_s)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        deadline = time.monotonic() + timeout_s
        if not _db_lock.acquire(timeout=timeout_s):
            raise StoreBusy("machine diagnostics store lock deadline exceeded")
    try:
        yield deadline
    finally:
        _db_lock.release()


def _sqlite_timeout(deadline):
    if deadline is None:
        return 5.0
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise StoreBusy("machine diagnostics store deadline exceeded")
    return max(0.001, remaining)


def enabled():
    """True unless the kill-switch env var is explicitly falsey."""
    return os.environ.get(DISABLE_ENV, "1").strip().lower() not in _FALSEY


def _bump_error():
    global _error_count
    with _err_lock:
        _error_count += 1


def error_count():
    with _err_lock:
        return _error_count


def last_insert_duplicates():
    """Legacy count from the most recent compatibility ``insert_events`` call.

    It is not request-local; HTTP code uses the transaction return value from
    ``insert_events_with_disposition`` instead.
    """
    with _err_lock:
        return _last_dup_count


def last_cycle_duplicate():
    """Legacy flag from the most recent compatibility ``insert_cycle`` call."""
    with _err_lock:
        return _last_cycle_dup


def _warn_once(key, msg):
    if key not in _warned:
        _warned.add(key)
        log.warning(msg)


def _env_float(name, default):
    """Read a positive float env var; garbage / non-positive -> default."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return float(default)
    try:
        val = float(raw)
        return val if val > 0 else float(default)
    except ValueError:
        return float(default)


# ------------------------------------------------------------------
# Time helpers
# ------------------------------------------------------------------

def _normalize_utc_iso(value):
    """Return a fixed-width UTC ISO timestamp
    ('YYYY-MM-DDTHH:MM:SS.mmm+00:00') for a datetime or ISO-8601 string.
    Naive input is assumed UTC. Raises ValueError on garbage. The fixed
    width makes lexicographic compare == chronological compare, which
    the retention prune relies on."""
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("timestamp must be an ISO-8601 string")
        text = value.strip()
        if text.endswith(('Z', 'z')):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec='milliseconds')


def _utc_now_iso():
    return _normalize_utc_iso(datetime.now(timezone.utc))


def business_date_for(utc_value=None):
    """Local business date (YYYY-MM-DD) for a UTC timestamp (default:
    now). Rolls at the configured local cutoff — a 1:30 AM fault belongs
    to the previous business day. Same envs + semantics as wsl-systems'
    _netsuite_business_day_window, but never raises: bad config falls
    back to America/Los_Angeles @ 04:00 with a one-time warning (this
    sits on the write path)."""
    tz_name = (os.environ.get(BUSINESS_TZ_ENV, DEFAULT_BUSINESS_TZ).strip()
               or DEFAULT_BUSINESS_TZ)
    cutoff_text = (os.environ.get(BUSINESS_CUTOFF_ENV,
                                  DEFAULT_BUSINESS_CUTOFF).strip()
                   or DEFAULT_BUSINESS_CUTOFF)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        _warn_once('tz', f"Bad {BUSINESS_TZ_ENV}={tz_name!r} — "
                         f"using {DEFAULT_BUSINESS_TZ}")
        tz = ZoneInfo(DEFAULT_BUSINESS_TZ)
    try:
        cutoff = datetime.strptime(cutoff_text, '%H:%M').time()
    except ValueError:
        _warn_once('cutoff', f"Bad {BUSINESS_CUTOFF_ENV}={cutoff_text!r} — "
                             f"using {DEFAULT_BUSINESS_CUTOFF}")
        cutoff = dtime(4, 0)
    if utc_value is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(utc_value, datetime):
        dt = (utc_value if utc_value.tzinfo is not None
              else utc_value.replace(tzinfo=timezone.utc))
    else:
        dt = datetime.fromisoformat(_normalize_utc_iso(utc_value))
    local = dt.astimezone(tz)
    bd = local.date()
    if local.timetz().replace(tzinfo=None) < cutoff:
        bd -= timedelta(days=1)
    return bd.isoformat()


def retention_days():
    raw = os.environ.get(RETENTION_ENV, "").strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        days = int(raw)
        if days < 1:
            raise ValueError(raw)
        return days
    except ValueError:
        _warn_once('retention', f"Bad {RETENTION_ENV}={raw!r} — "
                                f"using {DEFAULT_RETENTION_DAYS}")
        return DEFAULT_RETENTION_DAYS


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------

# Exactly the scope-doc §2 schema. severity carries the ONLY enum CHECK;
# the lane_id range CHECK is structural (1-32 is the house), not a
# status vocabulary, so it stays. Additive-only from here on.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS machine_cycles (
  id            INTEGER PRIMARY KEY,
  lane_id       INTEGER NOT NULL CHECK(lane_id BETWEEN 1 AND 32),
  business_date TEXT NOT NULL,
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  cycle_type    TEXT,
  ball          INTEGER,
  final_state   TEXT NOT NULL,
  aborted       INTEGER NOT NULL DEFAULT 0,
  ss_to_guard_ms INTEGER, guard_to_table_ms INTEGER, table_to_ta2_ms INTEGER,
  ta2_to_sa_ms  INTEGER, sa_to_ta1zero_ms INTEGER, bs_to_ta1zero_ms INTEGER,
  gs_mask       INTEGER,
  cam_mask      INTEGER,
  fw_version    TEXT, shadow INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mc_lane_date
  ON machine_cycles(lane_id, business_date);

CREATE TABLE IF NOT EXISTS machine_events (
  id            INTEGER PRIMARY KEY,
  lane_id       INTEGER NOT NULL CHECK(lane_id BETWEEN 1 AND 32),
  business_date TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  severity      TEXT NOT NULL CHECK(severity IN ('info','warn','fault')),
  event_type    TEXT NOT NULL,
  code          TEXT,
  cycle_id      INTEGER REFERENCES machine_cycles(id),
  detail_json   TEXT,
  blackbox_file TEXT,
  acknowledged_at TEXT, acknowledged_by INTEGER, resolved_at TEXT,
  resolved_by INTEGER,
  incident_id   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_me_open
  ON machine_events(acknowledged_at, created_at);

-- 2026-07-19 review: every hot query here leads on lane_id, but no index
-- did — lane_diagnostics + the machine_health rollup full-scanned the table
-- under _db_lock on the single-threaded :8766 HTTPServer (which also serves
-- the desk's hard-fail scoring proxy). Additive CREATE INDEX IF NOT EXISTS
-- runs on every connect, so existing DBs pick these up with no migration.
CREATE INDEX IF NOT EXISTS idx_me_lane_created
  ON machine_events(lane_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_me_open_fault
  ON machine_events(lane_id, id)
  WHERE severity = 'fault' AND resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS lane_incidents (
  id             INTEGER PRIMARY KEY,
  lane_id        INTEGER NOT NULL CHECK(lane_id BETWEEN 1 AND 32),
  event_type     TEXT NOT NULL,
  code           TEXT,
  opened_at      TEXT NOT NULL,
  last_seen_at   TEXT NOT NULL,
  repeat_count   INTEGER NOT NULL DEFAULT 1,
  state          TEXT NOT NULL
                 CHECK(state IN ('open','override_pending','closed')),
  recovery_event_id INTEGER REFERENCES machine_events(id),
  closed_at      TEXT,
  closed_by      INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_incident_one_open
  ON lane_incidents(lane_id,event_type,COALESCE(code,''))
  WHERE state IN ('open','override_pending');

CREATE TABLE IF NOT EXISTS machine_resolution_audit (
  id                INTEGER PRIMARY KEY,
  event_id          INTEGER NOT NULL REFERENCES machine_events(id),
  incident_id       INTEGER REFERENCES lane_incidents(id),
  action            TEXT NOT NULL
                    CHECK(action IN ('recovery','override_requested')),
  actor_id           INTEGER NOT NULL,
  reason             TEXT,
  recovery_event_id  INTEGER REFERENCES machine_events(id),
  created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resolution_audit_event
  ON machine_resolution_audit(event_id,created_at,id);
CREATE INDEX IF NOT EXISTS idx_mc_lane_started
  ON machine_cycles(lane_id, started_at, id);

-- Board liveness leases (R2-10). One row per machine lane; last_seen is
-- the newest 'the board's daemon was heard from' timestamp. maintenance
-- is a mechanic-set flag that overrides state derivation (and gates
-- alerting on the WSL side). Additive table — no migration needed.
CREATE TABLE IF NOT EXISTS machine_leases (
  lane_id       INTEGER PRIMARY KEY CHECK(lane_id BETWEEN 1 AND 32),
  last_seen     TEXT,
  maintenance   INTEGER NOT NULL DEFAULT 0,
  maintenance_note TEXT,
  maintenance_changed_at TEXT
);

-- Controller boot nonces are append-only replay history. Keeping only the
-- current nonce in machine_leases lets a delayed heartbeat from a retired
-- process flip the lease back to an old boot and renew liveness. This table
-- makes every previously-observed (lane, boot) nonce permanently recognizable.
CREATE TABLE IF NOT EXISTS machine_controller_boots (
  lane_id       INTEGER NOT NULL CHECK(lane_id BETWEEN 1 AND 32),
  controller_boot_id TEXT NOT NULL,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  last_heartbeat_seq INTEGER NOT NULL,
  PRIMARY KEY (lane_id, controller_boot_id)
);

-- Track-A node boot identities use the same append-only retirement rule as
-- controller boots. Once node N advances A -> B, boot A can never regain a
-- lease with a fresh session id after a delayed reconnect.
CREATE TABLE IF NOT EXISTS scoring_node_boots (
  node_id       TEXT NOT NULL,
  scoring_boot_id TEXT NOT NULL,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  last_session_id TEXT NOT NULL,
  retired       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (node_id, scoring_boot_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_node_current_boot
  ON scoring_node_boots(node_id) WHERE retired = 0;

CREATE TABLE IF NOT EXISTS machine_maintenance_audit (
  id            INTEGER PRIMARY KEY,
  lane_id       INTEGER NOT NULL CHECK(lane_id BETWEEN 1 AND 32),
  maintenance   INTEGER NOT NULL,
  note          TEXT,
  changed_at    TEXT NOT NULL,
  changed_by    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_maintenance_audit_lane
  ON machine_maintenance_audit(lane_id, changed_at, id);
"""


# R2-12 (Codex round-2, 2026-07-21): delivery identity for the Pi's
# JSONL-as-outbox shipping. Additive ALTER TABLE (SQLite house rule) +
# partial UNIQUE indexes so a replayed batch after a drop / lost ack is
# an idempotent INSERT OR IGNORE no-op instead of a duplicate row.
# Rows without identity (legacy live-sink era) stay insertable as before.
_IDENTITY_COLUMNS = (('source_id', 'TEXT'), ('boot_id', 'TEXT'),
                     ('seq', 'INTEGER'))
_IDENTITY_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_me_delivery
  ON machine_events(source_id, boot_id, seq)
  WHERE source_id IS NOT NULL AND boot_id IS NOT NULL AND seq IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mc_delivery
  ON machine_cycles(source_id, boot_id, seq)
  WHERE source_id IS NOT NULL AND boot_id IS NOT NULL AND seq IS NOT NULL;
"""


def _migrate_identity(conn):
    """Additive migration: identity columns on both tables + the UNIQUE
    partial indexes. Safe to run on every connect (ALTER failures on
    already-present columns are swallowed)."""
    for table in ('machine_events', 'machine_cycles'):
        have = {r['name'] for r in
                conn.execute(f"PRAGMA table_info({table})")}
        for col, ctype in _IDENTITY_COLUMNS:
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")
    conn.executescript(_IDENTITY_INDEXES)
    event_columns = {
        row['name'] for row in conn.execute(
            "PRAGMA table_info(machine_events)")}
    if 'resolved_by' not in event_columns:
        conn.execute(
            "ALTER TABLE machine_events ADD COLUMN resolved_by INTEGER")


# R3-2 / R3-5 (2026-07-23): the periodic authenticated heartbeat the
# controller_daemon POSTs carries board + firmware + contract identity so a
# healthy-but-quiet Track-B controller keeps its lease fresh AND the desk can
# see WHICH board/firmware/contract each lane is running. Additive columns.
_LEASE_IDENTITY_COLUMNS = (
    ('scoring_seen_at', 'TEXT'),     # distinct Track-A scoring WS lease
    ('scoring_boot_id', 'TEXT'),
    ('scoring_session_id', 'TEXT'),
    ('scoring_heartbeat_seq', 'INTEGER'),
    ('scoring_mode', 'TEXT'),
    ('scoring_camera_calibrated', 'INTEGER'),
    ('scoring_camera_ok', 'INTEGER'),
    ('scoring_camera_code', 'TEXT'),
    ('scoring_outbox_json', 'TEXT'),
    ('scoring_node_lockout_s', 'REAL'),
    ('heartbeat_at', 'TEXT'),        # last accepted controller heartbeat
    ('controller_seen_at', 'TEXT'),  # distinct Track-B controller lease
    ('controller_boot_id', 'TEXT'),  # process identity for monotonic sequences
    ('heartbeat_seq', 'INTEGER'),    # monotonic within controller_boot_id
    ('control_loop_seq', 'INTEGER'), # incremented by the 50 Hz control loop
    ('control_loop_progress_at', 'TEXT'), # changes only when loop seq advances
    ('board_rev', 'TEXT'),           # configured board revision
    ('observed_pcb', 'TEXT'),        # firmware-reported PCB identity
    ('observed_rid', 'TEXT'),        # resistor/strap identity
    ('observed_uid', 'TEXT'),        # per-Pico silicon UID
    ('fw_build', 'TEXT'),            # firmware build id (git describe)
    ('fw_cfg', 'TEXT'),              # firmware config.h sha256[:8]
    ('fw_version', 'TEXT'),          # firmware semantic version
    ('contract_sha256', 'TEXT'),     # contract digest the daemon shipped with
    ('contract_loaded', 'INTEGER'),  # daemon parsed live JSON, not sidecar
    ('contract_match', 'INTEGER'),   # daemon digest == server live digest
    ('identity_ok', 'INTEGER'),      # daemon self-report: identity resolved?
    ('identity_reason', 'TEXT'),     # explicit fail-closed reason, if any
    ('ro_fs', 'INTEGER'),            # explicit even if outbox cannot be written
    ('heartbeat_valid', 'INTEGER'),  # schema/sequence/contract verdict
    ('heartbeat_error', 'TEXT'),     # bounded degradation reason
    ('serial_parse_errors', 'INTEGER'),
    ('diag_record_drops', 'INTEGER'),
    ('outbox_json', 'TEXT'),         # last outbox health block (R3-3)
    ('platform_json', 'TEXT'),       # strict common Pi platform probe
    ('maintenance_changed_by', 'INTEGER'),
    ('overdue_alerted_at', 'TEXT'),  # R3-10 maintenance_overdue idempotency
)


def _migrate_leases(conn):
    """Additive lease-identity columns (R3-2/R3-5/R3-10). Safe every connect."""
    have = {r['name'] for r in conn.execute("PRAGMA table_info(machine_leases)")}
    for col, ctype in _LEASE_IDENTITY_COLUMNS:
        if col not in have:
            conn.execute(f"ALTER TABLE machine_leases ADD COLUMN {col} {ctype}")


def _ensure_schema(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _migrate_identity(conn)
    _migrate_leases(conn)


def _connect(deadline=None):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=_sqlite_timeout(deadline))
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


# ------------------------------------------------------------------
# Validation (writer-side, in place of CHECK constraints)
# ------------------------------------------------------------------

def _lane_id(value):
    if isinstance(value, bool) or not isinstance(value, int) \
            or not (1 <= value <= 32):
        raise ValueError("lane_id must be an integer 1-32")
    return value


def _opt_int(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _opt_str(value, name, max_len=2000):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if len(value) > max_len:
        raise ValueError(f"{name} too long (max {max_len})")
    return value


def _opt_mask(value, name):
    v = _opt_int(value, name)
    if v is not None and not (0 <= v <= 0x3FF):
        raise ValueError(f"{name} out of range (10-bit mask, 0-1023)")
    return v


def _timestamp(value, name, default_now):
    if value is None:
        if default_now:
            return _utc_now_iso()
        raise ValueError(f"{name} required (UTC ISO-8601)")
    try:
        normalized = _normalize_utc_iso(value)
        stamp = datetime.fromisoformat(normalized)
        if ((stamp - datetime.now(timezone.utc)).total_seconds()
                > PRODUCER_FUTURE_TOLERANCE_S):
            raise ValueError(
                f"{name} is more than {PRODUCER_FUTURE_TOLERANCE_S:.0f}s "
                "in the future")
        return normalized
    except (ValueError, TypeError):
        raise ValueError(f"{name} is not a valid ISO-8601 timestamp: "
                         f"{value!r}") from None


def validate_event(ev):
    """Normalize one inbound event dict. Raises ValueError with a
    caller-safe message on any bad field; returns the row dict ready
    for insert (business_date stamped from the event's own created_at
    so late-shipped batches land on the right business day)."""
    if not isinstance(ev, dict):
        raise ValueError("each event must be a JSON object")
    allowed = {
        'lane_id', 'severity', 'event_type', 'code', 'cycle_id',
        'detail', 'detail_json', 'blackbox_file', 'incident_id',
        'created_at', 'ts_utc', 'ts_mono', 'source_id', 'boot_id', 'seq',
    }
    unknown = sorted(set(ev) - allowed)
    if unknown:
        raise ValueError(f"unknown event fields: {unknown}")
    if 'detail' in ev and 'detail_json' in ev:
        raise ValueError("event cannot carry both detail and detail_json")
    ts_mono = ev.get('ts_mono')
    if (ts_mono is not None
            and (isinstance(ts_mono, bool)
                 or not isinstance(ts_mono, (int, float))
                 or not math.isfinite(float(ts_mono))
                 or float(ts_mono) < 0)):
        raise ValueError("ts_mono must be a finite nonnegative number")
    row = {}
    row['lane_id'] = _lane_id(ev.get('lane_id'))
    severity = ev.get('severity')
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {list(SEVERITIES)}")
    row['severity'] = severity
    event_type = ev.get('event_type')
    if not isinstance(event_type, str) or not event_type:
        raise ValueError(f"event_type must be a non-empty string, got "
                         f"{event_type!r}")
    # EVENT_TYPES is None only in the fail-open degraded mode (contract JSON
    # unreadable at runtime) — accept any non-empty string then, so a live
    # board keeps delivering; strict membership is the normal path.
    if EVENT_TYPES is not None and event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {event_type!r} "
                         f"(allowed: {sorted(EVENT_TYPES)})")
    row['event_type'] = event_type
    row['code'] = _opt_str(ev.get('code'), 'code', max_len=200)
    row['cycle_id'] = _opt_int(ev.get('cycle_id'), 'cycle_id')
    detail = ev.get('detail_json')
    if detail is None:
        detail = ev.get('detail')
    if detail is None or isinstance(detail, str):
        row['detail_json'] = detail
    else:
        try:
            row['detail_json'] = json.dumps(detail)
        except (TypeError, ValueError):
            raise ValueError("detail must be JSON-serializable") from None
    row['blackbox_file'] = _opt_str(ev.get('blackbox_file'), 'blackbox_file',
                                    max_len=500)
    row['incident_id'] = _opt_int(ev.get('incident_id'), 'incident_id')
    # The Pi's DiagEvent.to_dict ships its wall-clock time as 'ts_utc', not
    # 'created_at' (2026-07-19 review: ignoring it stamped every event with
    # server RECEIVE time, so late-shipped batches landed on the wrong
    # business day and chronology reflected shipping latency). created_at
    # wins when both are present; server receive time is the last resort.
    ts = ev.get('created_at')
    if ts is None:
        ts = ev.get('ts_utc')
    row['created_at'] = _timestamp(ts, 'created_at', default_now=True)
    row['business_date'] = business_date_for(row['created_at'])
    _validate_identity(ev, row)
    return row


def _validate_identity(src, row):
    """R2-12 delivery identity (optional; all-or-nothing). A row carrying
    (source_id, boot_id, seq) is deduped by the UNIQUE partial index —
    replays after drops become idempotent no-ops."""
    sid = _opt_str(src.get('source_id'), 'source_id', max_len=120)
    bid = _opt_str(src.get('boot_id'), 'boot_id', max_len=80)
    seq = _opt_int(src.get('seq'), 'seq')
    if seq is not None and seq < 0:
        raise ValueError("seq must be a non-negative integer")
    present = [v is not None for v in (sid, bid, seq)]
    if any(present) and not all(present):
        raise ValueError("delivery identity requires all of "
                         "source_id, boot_id, seq (or none)")
    row['source_id'] = sid
    row['boot_id'] = bid
    row['seq'] = seq


def validate_cycle(c):
    """Normalize one inbound cycle dict; ValueError on bad fields."""
    if not isinstance(c, dict):
        raise ValueError("cycle must be a JSON object")
    allowed = {
        'lane_id', 'started_at', 'ended_at', 'cycle_type', 'ball',
        'final_state', 'aborted', *INTERVAL_COLUMNS, 'gs_mask', 'cam_mask',
        'fw_version', 'shadow', 'source_id', 'boot_id', 'seq',
    }
    unknown = sorted(set(c) - allowed)
    if unknown:
        raise ValueError(f"unknown cycle fields: {unknown}")
    row = {}
    row['lane_id'] = _lane_id(c.get('lane_id'))
    row['started_at'] = _timestamp(c.get('started_at'), 'started_at',
                                   default_now=True)
    ended = c.get('ended_at')
    row['ended_at'] = (_timestamp(ended, 'ended_at', default_now=False)
                       if ended is not None else None)
    if (row['ended_at'] is not None
            and row['ended_at'] < row['started_at']):
        raise ValueError("ended_at cannot precede started_at")
    cycle_type = c.get('cycle_type')
    if cycle_type is not None and cycle_type not in CYCLE_TYPES:
        raise ValueError(f"unknown cycle_type {cycle_type!r} "
                         f"(allowed: {sorted(CYCLE_TYPES)})")
    row['cycle_type'] = cycle_type
    row['ball'] = _opt_int(c.get('ball'), 'ball')
    if row['ball'] is not None and not 1 <= row['ball'] <= 3:
        raise ValueError("ball must be 1, 2, or 3")
    final_state = c.get('final_state')
    if final_state not in FINAL_STATES:
        raise ValueError(f"final_state must be one of {sorted(FINAL_STATES)}")
    row['final_state'] = final_state
    aborted = c.get('aborted', False)
    if type(aborted) is not bool:
        raise ValueError("aborted must be a JSON boolean")
    row['aborted'] = int(aborted)
    if aborted and final_state == 'READY':
        raise ValueError("an aborted cycle cannot have final_state READY")
    for col in INTERVAL_COLUMNS:
        value = c.get(col)
        if value is None:
            row[col] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{col} must be a number (integer ms)")
        ms = int(round(value))
        if not (0 <= ms <= 10 ** 9):
            raise ValueError(f"{col} out of range (0..1e9 ms)")
        row[col] = ms
    row['gs_mask'] = _opt_mask(c.get('gs_mask'), 'gs_mask')
    row['cam_mask'] = _opt_mask(c.get('cam_mask'), 'cam_mask')
    row['fw_version'] = _opt_str(c.get('fw_version'), 'fw_version', max_len=100)
    shadow = c.get('shadow', False)
    if type(shadow) is not bool:
        raise ValueError("shadow must be a JSON boolean")
    row['shadow'] = int(shadow)
    row['business_date'] = business_date_for(row['started_at'])
    _validate_identity(c, row)
    return row


# ------------------------------------------------------------------
# Writes
# ------------------------------------------------------------------

_EVENT_COLS = ('lane_id', 'business_date', 'created_at', 'severity',
               'event_type', 'code', 'cycle_id', 'detail_json',
               'blackbox_file', 'incident_id',
               'source_id', 'boot_id', 'seq')

_CYCLE_COLS = ('lane_id', 'business_date', 'started_at', 'ended_at',
               'cycle_type', 'ball', 'final_state', 'aborted',
               'ss_to_guard_ms', 'guard_to_table_ms', 'table_to_ta2_ms',
               'ta2_to_sa_ms', 'sa_to_ta1zero_ms', 'bs_to_ta1zero_ms',
               'gs_mask', 'cam_mask', 'fw_version', 'shadow',
               'source_id', 'boot_id', 'seq')


_LEASE_UPSERT = ("INSERT INTO machine_leases (lane_id, last_seen) "
                 "VALUES (?, ?) ON CONFLICT(lane_id) DO UPDATE SET "
                 "last_seen = excluded.last_seen "
                 "WHERE excluded.last_seen > COALESCE(machine_leases.last_seen, '')")

_SCORING_LEASE_UPSERT = """
INSERT INTO machine_leases (
  lane_id, last_seen, scoring_seen_at, scoring_boot_id,
  scoring_session_id, scoring_heartbeat_seq, scoring_mode,
  scoring_camera_calibrated, scoring_camera_ok, scoring_camera_code,
  scoring_outbox_json, scoring_node_lockout_s
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(lane_id) DO UPDATE SET
  last_seen = excluded.last_seen,
  scoring_seen_at = excluded.scoring_seen_at,
  scoring_boot_id = excluded.scoring_boot_id,
  scoring_session_id = excluded.scoring_session_id,
  scoring_heartbeat_seq = excluded.scoring_heartbeat_seq,
  scoring_mode = excluded.scoring_mode,
  scoring_camera_calibrated = excluded.scoring_camera_calibrated,
  scoring_camera_ok = excluded.scoring_camera_ok,
  scoring_camera_code = excluded.scoring_camera_code,
  scoring_outbox_json = excluded.scoring_outbox_json,
  scoring_node_lockout_s = excluded.scoring_node_lockout_s
WHERE machine_leases.scoring_session_id IS NULL
   OR excluded.scoring_session_id != machine_leases.scoring_session_id
   OR excluded.scoring_heartbeat_seq > machine_leases.scoring_heartbeat_seq
"""


def accept_scoring_boot(
        node_id, boot_id, session_id, when=None, *, timeout_s=None):
    """Accept the current Track-A boot or retire it on a genuine new boot.

    Retirement is durable. A delayed A -> B -> A reconnect is rejected even
    when the stale process invents a new WebSocket session id.
    """
    for value, name in (
            (node_id, 'node_id'), (boot_id, 'scoring_boot_id'),
            (session_id, 'scoring_session_id')):
        if (not isinstance(value, str) or not value.strip()
                or len(value.strip()) > 128):
            raise ValueError(f"{name} must be 1..128 chars")
    node_id = node_id.strip()
    boot_id = boot_id.strip()
    session_id = session_id.strip()
    ts = _normalize_utc_iso(when) if when is not None else _utc_now_iso()
    with _store_lock(timeout_s) as deadline:
        with closing(_connect(deadline)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT scoring_boot_id FROM scoring_node_boots "
                "WHERE node_id = ? AND retired = 0",
                (node_id,)).fetchone()
            known = conn.execute(
                "SELECT retired FROM scoring_node_boots "
                "WHERE node_id = ? AND scoring_boot_id = ?",
                (node_id, boot_id)).fetchone()
            if known is not None and known['retired']:
                conn.rollback()
                raise ValueError("retired scoring_boot_id replayed")
            if current is not None and current['scoring_boot_id'] != boot_id:
                conn.execute(
                    "UPDATE scoring_node_boots SET retired = 1, "
                    "last_seen = ? WHERE node_id = ? AND retired = 0",
                    (ts, node_id))
            conn.execute(
                "INSERT INTO scoring_node_boots "
                "(node_id, scoring_boot_id, first_seen, last_seen, "
                "last_session_id, retired) VALUES (?,?,?,?,?,0) "
                "ON CONFLICT(node_id, scoring_boot_id) DO UPDATE SET "
                "last_seen = excluded.last_seen, "
                "last_session_id = excluded.last_session_id "
                "WHERE scoring_node_boots.retired = 0",
                (node_id, boot_id, ts, ts, session_id))
            conn.commit()
    return {
        'node_id': node_id,
        'scoring_boot_id': boot_id,
        'scoring_session_id': session_id,
        'accepted_at': ts,
    }


def touch_lanes(lane_ids, when=None):
    """Record non-authoritative diagnostic activity for these lanes.

    Event/cycle ingest calls this, but it renews neither the strict Track-B
    controller lease nor the separate Track-A scoring-service lease.
    """
    try:
        ids = sorted({int(l) for l in (lane_ids or [])
                      if isinstance(l, (int, float)) and 1 <= int(l) <= 32})
    except Exception:
        ids = []
    if not ids:
        return
    try:
        ts = _normalize_utc_iso(when) if when is not None else _utc_now_iso()
        with _db_lock:
            with closing(_connect()) as conn:
                for lid in ids:
                    conn.execute(_LEASE_UPSERT, (lid, ts))
                conn.commit()
    except Exception as e:
        _bump_error()
        _warn_once('lease_touch', f"machine lease touch failed: {e}")


def touch_scoring_lanes(
        lane_ids, metadata, when=None, *, timeout_s=None):
    """Durably renew Track-A liveness plus current scoring capability.

    A renewal is accepted only for a new session or a strictly increasing
    heartbeat sequence within the current session. Unlike best-effort
    diagnostic activity, failure raises so the WebSocket handler can close
    rather than advertise a lease that was never committed.
    """
    try:
        ids = sorted({
            int(lane) for lane in (lane_ids or [])
            if isinstance(lane, int) and not isinstance(lane, bool)
            and 1 <= lane <= 32})
        if not ids:
            raise ValueError("scoring lease has no valid lanes")
        if not isinstance(metadata, dict):
            raise ValueError("scoring metadata must be an object")
        boot_id = metadata.get('scoring_boot_id')
        session_id = metadata.get('scoring_session_id')
        seq = metadata.get('heartbeat_seq')
        mode = metadata.get('scoring_mode')
        calibrated = metadata.get('camera_calibrated')
        camera_ok = metadata.get('camera_ok')
        camera_code = metadata.get('camera_code')
        outbox = metadata.get('outbox')
        lockout = metadata.get('node_ball_lockout_s')
        if (not isinstance(boot_id, str) or not boot_id.strip()
                or len(boot_id) > 128):
            raise ValueError("scoring_boot_id must be 1..128 chars")
        if (not isinstance(session_id, str) or not session_id.strip()
                or len(session_id) > 128):
            raise ValueError("scoring_session_id must be 1..128 chars")
        if (not isinstance(seq, int) or isinstance(seq, bool) or seq < 0):
            raise ValueError("heartbeat_seq must be a nonnegative integer")
        if mode not in ('camera', 'manual', 'disabled'):
            raise ValueError("scoring_mode is invalid")
        if type(calibrated) is not bool or type(camera_ok) is not bool:
            raise ValueError("camera capability fields must be JSON booleans")
        if (not isinstance(camera_code, str) or not camera_code.strip()
                or len(camera_code) > 120):
            raise ValueError("camera_code must be 1..120 chars")
        if camera_ok is not (camera_code.strip() == 'healthy'):
            raise ValueError(
                "camera_ok must be true exactly when camera_code is healthy")
        if not isinstance(outbox, dict):
            raise ValueError("scoring outbox health must be an object")
        required_outbox = {
            'cursor_ok', 'error', 'oldest_unsent_age_s',
            'backlog', 'backlog_bytes',
            'pending_writes', 'dropped', 'quarantined',
            'cycles_quarantined', 'post_errors', 'write_errors',
            'sink_errors', 'scoring_event_queue_depth',
            'scoring_event_queue_capacity',
            'scoring_event_oldest_age_s',
            'scoring_capture_jobs', 'scoring_capture_oldest_age_s',
            'scoring_clock_observed',
            'scoring_clock_anomaly_latched',
            'scoring_clock_high_water_epoch',
            'scoring_clock_observed_epoch',
            'scoring_event_durable', 'scoring_event_error',
            'scoring_event_overdue', 'scoring_event_drops',
            'scoring_event_expired', 'scoring_event_max_age_s',
        }
        missing_outbox = sorted(required_outbox - set(outbox))
        if missing_outbox:
            raise ValueError(
                f"scoring outbox missing fields: {missing_outbox}")
        if type(outbox.get('cursor_ok')) is not bool \
                or type(outbox.get('error')) is not bool:
            raise ValueError(
                "scoring outbox cursor_ok/error must be JSON booleans")
        for field in (
                "scoring_event_durable", "scoring_event_error",
                "scoring_event_overdue", "scoring_clock_observed",
                "scoring_clock_anomaly_latched"):
            if type(outbox.get(field)) is not bool:
                raise ValueError(
                    f"scoring outbox {field} must be a JSON boolean")
        age = outbox.get('oldest_unsent_age_s')
        if (age is not None
                and (isinstance(age, bool)
                     or not isinstance(age, (int, float))
                     or not math.isfinite(float(age))
                     or float(age) < 0)):
            raise ValueError(
                "scoring outbox oldest_unsent_age_s is invalid")
        for field in (
                'backlog', 'backlog_bytes',
                'pending_writes', 'dropped', 'quarantined',
                'cycles_quarantined', 'post_errors', 'write_errors',
                'sink_errors', 'scoring_event_queue_depth',
                'scoring_event_queue_capacity', 'scoring_capture_jobs',
                'scoring_event_drops',
                'scoring_event_expired'):
            value = outbox.get(field)
            if (not isinstance(value, int) or isinstance(value, bool)
                    or value < 0):
                raise ValueError(
                    f"scoring outbox {field} must be a nonnegative integer")
        if outbox['scoring_event_queue_capacity'] < 1:
            raise ValueError(
                "scoring event queue capacity must be positive")
        if (outbox['scoring_event_queue_depth']
                > outbox['scoring_event_queue_capacity']):
            raise ValueError(
                "scoring event queue depth exceeds capacity")
        max_age = outbox.get('scoring_event_max_age_s')
        if (isinstance(max_age, bool)
                or not isinstance(max_age, (int, float))
                or not math.isfinite(float(max_age))
                or not 1.0 <= float(max_age) <= 3600.0):
            raise ValueError(
                "scoring event max age must be finite 1..3600 seconds")
        scoring_age = outbox.get("scoring_event_oldest_age_s")
        if (scoring_age is not None
                and (isinstance(scoring_age, bool)
                     or not isinstance(scoring_age, (int, float))
                     or not math.isfinite(float(scoring_age))
                     or float(scoring_age) < 0)):
            raise ValueError(
                "scoring event oldest age must be null or nonnegative")
        if ((outbox["scoring_event_queue_depth"] == 0)
                is not (scoring_age is None)):
            raise ValueError(
                "scoring event oldest age must match queue depth")
        capture_age = outbox.get("scoring_capture_oldest_age_s")
        if (capture_age is not None
                and (isinstance(capture_age, bool)
                     or not isinstance(capture_age, (int, float))
                     or not math.isfinite(float(capture_age))
                     or float(capture_age) < 0)):
            raise ValueError(
                "scoring capture oldest age must be null or nonnegative")
        if ((outbox["scoring_capture_jobs"] == 0)
                is not (capture_age is None)):
            raise ValueError(
                "scoring capture oldest age must match capture jobs")
        if (outbox["scoring_capture_jobs"]
                > outbox["scoring_event_queue_depth"]):
            raise ValueError(
                "scoring capture jobs exceed scoring event queue depth")
        if (capture_age is not None
                and scoring_age is not None
                and float(capture_age) > float(scoring_age) + 0.001):
            raise ValueError(
                "scoring capture age exceeds overall oldest event age")
        clock_observed = outbox["scoring_clock_observed"]
        clock_anomaly = outbox["scoring_clock_anomaly_latched"]
        clock_high = outbox["scoring_clock_high_water_epoch"]
        clock_now = outbox["scoring_clock_observed_epoch"]
        for field, value in (
                ("scoring_clock_high_water_epoch", clock_high),
                ("scoring_clock_observed_epoch", clock_now)):
            if (value is not None
                    and (isinstance(value, bool)
                         or not isinstance(value, (int, float))
                         or not math.isfinite(float(value)))):
                raise ValueError(
                    f"scoring outbox {field} must be null or finite")
        if clock_observed:
            if clock_high is None or clock_now is None:
                raise ValueError(
                    "observed scoring clock requires epoch evidence")
            if float(clock_now) > float(clock_high) + 0.001:
                raise ValueError(
                    "scoring clock observation exceeds high-water")
        elif clock_high is not None or clock_now is not None or clock_anomaly:
            raise ValueError(
                "unobserved scoring clock cannot carry epoch/anomaly")
        if clock_anomaly and outbox["scoring_event_error"] is not True:
            raise ValueError(
                "clock anomaly requires scoring transport error")
        if outbox["scoring_event_overdue"] is not (
                scoring_age is not None
                and float(scoring_age) > float(max_age)):
            raise ValueError(
                "scoring_event_overdue does not match age threshold")
        backlog_bytes = outbox['backlog_bytes']
        if backlog_bytes > 0 and age is None:
            raise ValueError(
                "scoring outbox with backlog_bytes requires "
                "oldest_unsent_age_s")
        if backlog_bytes == 0 and age is not None:
            raise ValueError(
                "scoring outbox without backlog_bytes requires null "
                "oldest_unsent_age_s")
        outbox_json = json.dumps(
            outbox, separators=(',', ':'), sort_keys=True, allow_nan=False)
        if len(outbox_json.encode('utf-8')) > 32768:
            raise ValueError("scoring outbox health is too large")
        if (isinstance(lockout, bool)
                or not isinstance(lockout, (int, float))
                or not math.isfinite(float(lockout))
                or not 0.0 <= float(lockout) <= 120.0):
            raise ValueError("node_ball_lockout_s must be finite 0..120")

        ts = _normalize_utc_iso(when) if when is not None else _utc_now_iso()
        values = (
            ts, ts, boot_id.strip(), session_id.strip(), seq, mode,
            int(calibrated), int(camera_ok), camera_code.strip(),
            outbox_json, float(lockout))
        with _store_lock(timeout_s) as deadline:
            with closing(_connect(deadline)) as conn:
                changed = 0
                for lane_id in ids:
                    cur = conn.execute(
                        _SCORING_LEASE_UPSERT, (lane_id,) + values)
                    changed += cur.rowcount
                if changed != len(ids):
                    conn.rollback()
                    raise ValueError(
                        "scoring heartbeat sequence did not advance")
                conn.commit()
        return {
            'committed_at': ts,
            'lanes': ids,
            'scoring_session_id': session_id.strip(),
            'heartbeat_seq': seq,
        }
    except Exception:
        _bump_error()
        raise


def _staff_actor_id(value, field):
    if (not isinstance(value, int) or isinstance(value, bool)
            or value <= 0):
        raise ValueError(f"{field} must be a positive staff id")
    return value


def set_maintenance(lane_id, on, note=None, changed_by=None):
    """Mechanic maintenance flag for one lane (state MAINTENANCE wins
    over everything and suppresses WSL-side alerting). Returns the lease
    row as a dict. Raises ValueError on a bad lane id."""
    lane_id = _lane_id(lane_id)
    if type(on) is not bool:
        raise ValueError("maintenance on must be a JSON boolean")
    note = _opt_str(note, 'maintenance_note', max_len=500)
    changed_by = _staff_actor_id(changed_by, 'changed_by')
    now = _utc_now_iso()
    with _db_lock:
        with closing(_connect()) as conn:
            # overdue_alerted_at is reset on EVERY toggle (R3-10): turning
            # maintenance off clears a prior alert; turning it on starts a
            # fresh window that can alert once when it expires.
            conn.execute(
                "INSERT INTO machine_leases (lane_id, maintenance, "
                "maintenance_note, maintenance_changed_at, "
                "maintenance_changed_by, overdue_alerted_at) "
                "VALUES (?,?,?,?,?,NULL) "
                "ON CONFLICT(lane_id) DO UPDATE SET maintenance = ?, "
                "maintenance_note = ?, maintenance_changed_at = ?, "
                "maintenance_changed_by = ?, "
                "overdue_alerted_at = NULL",
                (lane_id, 1 if on else 0, note, now, changed_by,
                 1 if on else 0, note, now, changed_by))
            conn.execute(
                "INSERT INTO machine_maintenance_audit "
                "(lane_id, maintenance, note, changed_at, changed_by) "
                "VALUES (?,?,?,?,?)",
                (lane_id, int(on), note, now, changed_by))
            conn.commit()
            row = conn.execute("SELECT * FROM machine_leases WHERE lane_id = ?",
                               (lane_id,)).fetchone()
    return dict(row) if row is not None else {'lane_id': lane_id}


# R3-10 (2026-07-23): a machine left in MAINTENANCE forever silently
# suppresses every alert. Once maintenance has been on longer than this,
# the server emits ONE maintenance_overdue warn (state stays MAINTENANCE —
# only the mechanic clears it — but the desk is told).
MAINTENANCE_MAX_ENV = "WSL_MACHINE_MAINTENANCE_MAX_S"
DEFAULT_MAINTENANCE_MAX_S = 43200.0   # 12 h


def maintenance_max_s():
    raw = os.environ.get(MAINTENANCE_MAX_ENV, "").strip()
    if not raw:
        return DEFAULT_MAINTENANCE_MAX_S
    try:
        val = float(raw)
        return val if val > 0 else DEFAULT_MAINTENANCE_MAX_S
    except ValueError:
        return DEFAULT_MAINTENANCE_MAX_S


# The controller lease has a strict envelope. Replay/event ingest and the
# Track-A scoring WebSocket updates scoring_seen_at plus activity last_seen;
# it can never renew controller_seen_at or control_loop_progress_at.
_HEARTBEAT_REQUIRED_FIELDS = {
    'lane_id', 'controller_boot_id', 'heartbeat_seq', 'control_loop_seq',
    'board_rev', 'contract_sha256', 'contract_loaded', 'identity_ok',
    'ro_fs', 'outbox', 'platform',
}
_HEARTBEAT_OPTIONAL_FIELDS = {
    'observed_pcb', 'observed_rid', 'observed_uid',
    'fw_build', 'fw_cfg', 'fw_version', 'identity_reason',
    'serial_parse_errors', 'diag_record_drops',
}
_HEARTBEAT_STR_FIELDS = (
    'controller_boot_id', 'board_rev', 'observed_pcb', 'observed_rid',
    'observed_uid', 'fw_build', 'fw_cfg', 'fw_version', 'contract_sha256',
    'identity_reason',
)


def _heartbeat_nonnegative_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def validate_heartbeat(body):
    """Validate the required controller lease envelope, fail-closed."""
    if not isinstance(body, dict):
        raise ValueError("heartbeat must be an object")
    missing = sorted(_HEARTBEAT_REQUIRED_FIELDS - set(body))
    if missing:
        raise ValueError(f"heartbeat missing required fields: {missing}")
    unknown = sorted(
        set(body) - _HEARTBEAT_REQUIRED_FIELDS - _HEARTBEAT_OPTIONAL_FIELDS)
    if unknown:
        raise ValueError(f"heartbeat has unknown fields: {unknown}")
    row = dict(body)
    row['lane_id'] = _lane_id(row['lane_id'])
    for field in ('contract_loaded', 'identity_ok', 'ro_fs'):
        if type(row[field]) is not bool:
            raise ValueError(f"{field} must be boolean")
    for field in ('heartbeat_seq', 'control_loop_seq',
                  'serial_parse_errors', 'diag_record_drops'):
        if field in row:
            row[field] = _heartbeat_nonnegative_int(row[field], field)
    for field in _HEARTBEAT_STR_FIELDS:
        value = row.get(field)
        if value is None and field in ('observed_pcb', 'observed_rid',
                                       'observed_uid', 'fw_build', 'fw_cfg',
                                       'fw_version'):
            continue
        row[field] = _opt_str(value, field, max_len=200)
    if not row['controller_boot_id']:
        raise ValueError("controller_boot_id must be non-empty")
    if not row['board_rev']:
        raise ValueError("board_rev must be non-empty")
    if row['board_rev'] == 'revD' and row['identity_ok']:
        required_identity = (
            'observed_pcb', 'observed_rid', 'observed_uid',
            'fw_build', 'fw_cfg', 'fw_version',
        )
        absent = [field for field in required_identity if not row.get(field)]
        if absent:
            raise ValueError(
                f"approved revD identity missing evidence: {absent}")
        if row['observed_pcb'] != row['board_rev']:
            raise ValueError(
                "approved revD observed_pcb must match board_rev")
    if not row['identity_ok'] and not row.get('identity_reason'):
        raise ValueError(
            "identity_reason is required when identity_ok=false")
    digest = row.get('contract_sha256')
    digest_ok = (
        isinstance(digest, str)
        and len(digest) == 64
        and all(c in '0123456789abcdefABCDEF' for c in digest)
    )
    if row['contract_loaded'] and not digest_ok:
        raise ValueError("contract_sha256 must be 64 hex characters")
    if not row['contract_loaded'] and digest not in (None, ''):
        raise ValueError("contract_sha256 must be null when contract_loaded=false")
    if not isinstance(row['outbox'], dict):
        raise ValueError("outbox must be an object")
    try:
        encoded = json.dumps(
            row['outbox'], separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"outbox must be finite JSON: {exc}") from exc
    if len(encoded) > 4000:
        raise ValueError("outbox exceeds 4000 encoded characters")
    row['_outbox_json'] = encoded
    platform = row['platform']
    if not isinstance(platform, dict):
        raise ValueError("platform must be an object")
    if type(platform.get('ok')) is not bool:
        raise ValueError("platform.ok must be a JSON boolean")
    reasons = platform.get('reasons')
    if (not isinstance(reasons, list) or len(reasons) > 32
            or any(not isinstance(reason, str) or not reason.strip()
                   or len(reason) > 120 for reason in reasons)
            or len(reasons) != len(set(reasons))):
        raise ValueError("platform.reasons must be unique bounded strings")
    if platform['ok'] is not (len(reasons) == 0):
        raise ValueError("platform.ok must equal an empty reasons list")
    try:
        platform_json = json.dumps(
            platform, separators=(',', ':'), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"platform must be finite JSON: {exc}") from exc
    if len(platform_json) > 8000:
        raise ValueError("platform exceeds 8000 encoded characters")
    row['_platform_json'] = platform_json
    return row


def _outbox_degraded_reasons(outbox):
    reasons = []
    if not isinstance(outbox, dict):
        return ['outbox_missing']
    if type(outbox.get('cursor_ok')) is not bool:
        reasons.append('outbox_cursor_invalid')
    elif outbox.get('cursor_ok') is not True:
        reasons.append('outbox_cursor')
    # write_errors/sink_errors/post_errors are cumulative forensic counters.
    # They produce structured events, but a recovered retry must not leave the
    # lane permanently DEGRADED. pending_writes is the live persistence
    # condition; dropped is irrecoverable loss and remains health-relevant for
    # the lifetime of this controller process.
    for field in (
            'backlog', 'backlog_bytes', 'pending_writes',
            'dropped', 'quarantined',
            'cycles_quarantined'):
        value = outbox.get(field)
        if (not isinstance(value, int) or isinstance(value, bool)
                or value < 0):
            reasons.append(f'outbox_{field}_invalid')
        elif value > 0 and field not in ('backlog', 'backlog_bytes'):
            reasons.append(f'outbox_{field}')
    transport_fields = {
        'scoring_event_queue_depth', 'scoring_event_queue_capacity',
        'scoring_event_oldest_age_s', 'scoring_capture_jobs',
        'scoring_capture_oldest_age_s', 'scoring_clock_observed',
        'scoring_clock_anomaly_latched',
        'scoring_clock_high_water_epoch',
        'scoring_clock_observed_epoch', 'scoring_event_durable',
        'scoring_event_error', 'scoring_event_overdue',
        'scoring_event_drops', 'scoring_event_expired',
        'scoring_event_max_age_s',
    }
    if transport_fields & set(outbox):
        for field in (
                'scoring_event_queue_depth',
                'scoring_event_queue_capacity',
                'scoring_capture_jobs',
                'scoring_event_drops', 'scoring_event_expired'):
            value = outbox.get(field)
            if (not isinstance(value, int) or isinstance(value, bool)
                    or value < 0):
                reasons.append(f'{field}_invalid')
        depth = outbox.get('scoring_event_queue_depth')
        capacity = outbox.get('scoring_event_queue_capacity')
        if isinstance(capacity, int) and capacity < 1:
            reasons.append('scoring_event_queue_capacity_invalid')
        if (isinstance(depth, int) and isinstance(capacity, int)
                and depth > capacity):
            reasons.append('scoring_event_queue_depth_invalid')
        if isinstance(depth, int) and depth > 0:
            reasons.append('scoring_event_backlog')
        capture_jobs = outbox.get('scoring_capture_jobs')
        if isinstance(capture_jobs, int) and capture_jobs > 0:
            reasons.append('scoring_capture_pending')
        if (isinstance(capture_jobs, int) and isinstance(depth, int)
                and capture_jobs > depth):
            reasons.append('scoring_capture_jobs_invalid')
        for field in (
                "scoring_event_durable", "scoring_event_error",
                "scoring_event_overdue"):
            if type(outbox.get(field)) is not bool:
                reasons.append(f"{field}_invalid")
        if outbox.get("scoring_event_durable") is not True:
            reasons.append("scoring_event_not_durable")
        if outbox.get("scoring_event_error") is True:
            reasons.append("scoring_event_transport_error")
        if outbox.get("scoring_event_overdue") is True:
            reasons.append("scoring_event_overdue")
        scoring_age = outbox.get("scoring_event_oldest_age_s")
        if scoring_age is not None and (
                isinstance(scoring_age, bool)
                or not isinstance(scoring_age, (int, float))
                or not math.isfinite(float(scoring_age))
                or float(scoring_age) < 0):
            reasons.append("scoring_event_oldest_age_invalid")
        capture_age = outbox.get("scoring_capture_oldest_age_s")
        if capture_age is not None and (
                isinstance(capture_age, bool)
                or not isinstance(capture_age, (int, float))
                or not math.isfinite(float(capture_age))
                or float(capture_age) < 0):
            reasons.append("scoring_capture_oldest_age_invalid")
        if (isinstance(capture_jobs, int)
                and ((capture_jobs == 0) is not (capture_age is None))):
            reasons.append("scoring_capture_oldest_age_invalid")
        if (capture_age is not None and scoring_age is not None
                and isinstance(capture_age, (int, float))
                and not isinstance(capture_age, bool)
                and isinstance(scoring_age, (int, float))
                and not isinstance(scoring_age, bool)
                and math.isfinite(float(capture_age))
                and math.isfinite(float(scoring_age))
                and float(capture_age) > float(scoring_age) + 0.001):
            reasons.append("scoring_capture_oldest_age_invalid")
        clock_observed = outbox.get("scoring_clock_observed")
        clock_anomaly = outbox.get("scoring_clock_anomaly_latched")
        if type(clock_observed) is not bool:
            reasons.append("scoring_clock_observed_invalid")
        elif not clock_observed:
            reasons.append("scoring_clock_unobserved")
        if type(clock_anomaly) is not bool:
            reasons.append("scoring_clock_anomaly_invalid")
        elif clock_anomaly:
            reasons.append("scoring_clock_anomaly_latched")
        clock_high = outbox.get("scoring_clock_high_water_epoch")
        clock_now = outbox.get("scoring_clock_observed_epoch")
        for field, value in (
                ("scoring_clock_high_water", clock_high),
                ("scoring_clock_observed_epoch", clock_now)):
            if (value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)))):
                reasons.append(f"{field}_invalid")
        if (clock_observed is True
                and (clock_high is None or clock_now is None)):
            reasons.append("scoring_clock_evidence_missing")
        if (clock_observed is False
                and (clock_high is not None or clock_now is not None)):
            reasons.append("scoring_clock_evidence_invalid")
        if (isinstance(clock_high, (int, float))
                and not isinstance(clock_high, bool)
                and isinstance(clock_now, (int, float))
                and not isinstance(clock_now, bool)
                and math.isfinite(float(clock_high))
                and math.isfinite(float(clock_now))
                and float(clock_now) > float(clock_high) + 0.001):
            reasons.append("scoring_clock_evidence_invalid")
        if isinstance(outbox.get('scoring_event_drops'), int) \
                and outbox['scoring_event_drops'] > 0:
            reasons.append('scoring_event_drops')
        if isinstance(outbox.get('scoring_event_expired'), int) \
                and outbox['scoring_event_expired'] > 0:
            reasons.append('scoring_event_expired')
        max_age = outbox.get('scoring_event_max_age_s')
        if (isinstance(max_age, bool)
                or not isinstance(max_age, (int, float))
                or not math.isfinite(float(max_age))
                or not 1.0 <= float(max_age) <= 3600.0):
            reasons.append('scoring_event_max_age_invalid')
    if type(outbox.get('error')) is not bool:
        reasons.append('outbox_error_invalid')
    elif outbox.get('error') is True:
        reasons.append('outbox_health')
    if outbox.get('health_unavailable') is True:
        reasons.append('outbox_health')
    age = outbox.get('oldest_unsent_age_s')
    backlog_bytes = outbox.get('backlog_bytes')
    if age is not None:
        if (isinstance(age, bool) or not isinstance(age, (int, float))
                or not math.isfinite(float(age)) or age < 0):
            reasons.append('outbox_age_invalid')
        elif (isinstance(backlog_bytes, int)
              and not isinstance(backlog_bytes, bool)
              and backlog_bytes == 0):
            reasons.append('outbox_age_invalid')
        elif age > outbox_stall_s():
            reasons.append('outbox_stalled')
    elif (isinstance(backlog_bytes, int)
          and not isinstance(backlog_bytes, bool)
          and backlog_bytes > 0):
        reasons.append('outbox_age_invalid')
    return reasons


def record_heartbeat(body, *, when=None):
    """Commit one strict controller heartbeat or raise.

    Returning success is proof that the database commit completed. A store
    failure is never converted into a 200-shaped row.
    """
    if not enabled():
        raise StoreDisabled(f"{DISABLE_ENV} is off")
    hb = validate_heartbeat(body)
    lane_id = hb['lane_id']
    now = _normalize_utc_iso(when) if when is not None else _utc_now_iso()
    cstatus = contract_status()
    contract_match = bool(
        hb['contract_loaded']
        and cstatus['strict']
        and hb.get('contract_sha256')
        and hb['contract_sha256'].lower() == cstatus['sha256']
    )
    try:
        with _db_lock:
            with closing(_connect()) as conn:
                previous = conn.execute(
                    "SELECT * FROM machine_leases WHERE lane_id = ?",
                    (lane_id,)).fetchone()
                previous = dict(previous) if previous is not None else {}
                same_boot = (
                    previous.get('controller_boot_id') == hb['controller_boot_id'])
                errors = []
                seen_boot = conn.execute(
                    "SELECT last_heartbeat_seq FROM machine_controller_boots "
                    "WHERE lane_id = ? AND controller_boot_id = ?",
                    (lane_id, hb['controller_boot_id'])).fetchone()
                if not same_boot and seen_boot is not None:
                    raise ValueError(
                        "controller_boot_id was already retired for this lane")
                if same_boot:
                    prior_hb = previous.get('heartbeat_seq')
                    prior_loop = previous.get('control_loop_seq')
                    if prior_hb is not None and hb['heartbeat_seq'] <= prior_hb:
                        raise ValueError(
                            "heartbeat_seq must advance within controller boot")
                    if prior_loop is not None and hb['control_loop_seq'] < prior_loop:
                        raise ValueError(
                            "control_loop_seq must not regress within controller boot")
                if not contract_match:
                    errors.append('contract_mismatch')
                progress = (
                    not same_boot
                    or previous.get('control_loop_seq') is None
                    or hb['control_loop_seq'] > previous['control_loop_seq']
                )
                controller_seen = now
                progress_at = (
                    now if progress
                    else previous.get('control_loop_progress_at'))
                vals = {
                    'last_seen': now,
                    'heartbeat_at': now,
                    'controller_seen_at': controller_seen,
                    'controller_boot_id': hb['controller_boot_id'],
                    'heartbeat_seq': hb['heartbeat_seq'],
                    'control_loop_seq': hb['control_loop_seq'],
                    'control_loop_progress_at': progress_at,
                    'board_rev': hb['board_rev'],
                    'observed_pcb': hb.get('observed_pcb'),
                    'observed_rid': hb.get('observed_rid'),
                    'observed_uid': hb.get('observed_uid'),
                    'fw_build': hb.get('fw_build'),
                    'fw_cfg': hb.get('fw_cfg'),
                    'fw_version': hb.get('fw_version'),
                    'contract_sha256': hb.get('contract_sha256'),
                    'contract_loaded': 1 if hb['contract_loaded'] else 0,
                    'contract_match': 1 if contract_match else 0,
                    'identity_ok': 1 if hb['identity_ok'] else 0,
                    'identity_reason': hb.get('identity_reason'),
                    'ro_fs': 1 if hb['ro_fs'] else 0,
                    'heartbeat_valid': 0 if errors else 1,
                    'heartbeat_error': ','.join(errors)[:500] if errors else None,
                    'serial_parse_errors': hb.get('serial_parse_errors', 0),
                    'diag_record_drops': hb.get('diag_record_drops', 0),
                    'outbox_json': hb['_outbox_json'],
                    'platform_json': hb['_platform_json'],
                }
                if same_boot:
                    updated = conn.execute(
                        "UPDATE machine_controller_boots "
                        "SET last_seen = ?, last_heartbeat_seq = ? "
                        "WHERE lane_id = ? AND controller_boot_id = ?",
                        (now, hb['heartbeat_seq'], lane_id,
                         hb['controller_boot_id'])).rowcount
                    if updated != 1:
                        # Additive migration compatibility: a lease created by
                        # an older build has no boot-history row yet.
                        conn.execute(
                            "INSERT INTO machine_controller_boots "
                            "(lane_id, controller_boot_id, first_seen, "
                            "last_seen, last_heartbeat_seq) VALUES (?,?,?,?,?)",
                            (lane_id, hb['controller_boot_id'], now, now,
                             hb['heartbeat_seq']))
                else:
                    conn.execute(
                        "INSERT INTO machine_controller_boots "
                        "(lane_id, controller_boot_id, first_seen, last_seen, "
                        "last_heartbeat_seq) VALUES (?,?,?,?,?)",
                        (lane_id, hb['controller_boot_id'], now, now,
                         hb['heartbeat_seq']))
                cols = ['lane_id'] + list(vals)
                placeholders = ','.join('?' * len(cols))
                updates = ', '.join(
                    f"{column} = excluded.{column}" for column in vals)
                conn.execute(
                    f"INSERT INTO machine_leases ({','.join(cols)}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT(lane_id) DO UPDATE SET {updates}",
                    [lane_id] + list(vals.values()))
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM machine_leases WHERE lane_id = ?",
                    (lane_id,)).fetchone()
        if row is None:
            raise RuntimeError("heartbeat commit produced no lease row")
        return dict(row)
    except Exception:
        _bump_error()
        raise


def sweep_maintenance_overdue(now=None):
    """R3-10: emit ONE 'maintenance_overdue' warn per lane whose maintenance
    flag has been on longer than maintenance_max_s(). Idempotent via
    overdue_alerted_at — re-cleared when maintenance is turned off. Returns
    the number of overdue events emitted this sweep. Never raises."""
    base = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    limit = maintenance_max_s()
    emitted = 0
    try:
        if not enabled():
            return 0
        stamp = _normalize_utc_iso(base)
        with _db_lock:
            with closing(_connect()) as conn:
                rows = conn.execute(
                    "SELECT lane_id, maintenance, maintenance_changed_at, "
                    "maintenance_note, overdue_alerted_at "
                    "FROM machine_leases WHERE maintenance = 1").fetchall()
                for lease in rows:
                    if lease['overdue_alerted_at'] is not None:
                        continue
                    changed = lease['maintenance_changed_at']
                    timestamp_error = None
                    age = None
                    try:
                        if not changed:
                            raise ValueError("missing maintenance timestamp")
                        text = str(changed).strip()
                        if text.endswith(("Z", "z")):
                            text = text[:-1] + "+00:00"
                        changed_at = datetime.fromisoformat(text)
                        if (changed_at.tzinfo is None
                                or changed_at.utcoffset() is None):
                            raise ValueError(
                                "maintenance timestamp is not aware")
                        age = (base - changed_at).total_seconds()
                        if age < -LEASE_FUTURE_TOLERANCE_S:
                            timestamp_error = (
                                'maintenance_timestamp_future')
                    except (TypeError, ValueError, OverflowError):
                        timestamp_error = 'maintenance_timestamp_invalid'
                    if timestamp_error is None and age < limit:
                        continue
                    row = validate_event({
                        'lane_id': lease['lane_id'],
                        'severity': 'warn',
                        'event_type': 'maintenance_overdue',
                        'code': 'maintenance',
                        'created_at': stamp,
                        'detail': {
                            'age_s': (
                                round(age, 1)
                                if timestamp_error is None else None),
                            'limit_s': limit,
                            'note': lease['maintenance_note'],
                            'timestamp_error': timestamp_error,
                        },
                    })
                    values = [row.get(column) for column in _EVENT_COLS]
                    conn.execute(
                        f"INSERT INTO machine_events "
                        f"({', '.join(_EVENT_COLS)}) VALUES "
                        f"({', '.join('?' * len(_EVENT_COLS))})",
                        values)
                    conn.execute(
                        "UPDATE machine_leases SET overdue_alerted_at = ? "
                        "WHERE lane_id = ? AND overdue_alerted_at IS NULL",
                        (stamp, lease['lane_id']))
                    emitted += 1
                # Event row and latch commit together. Any insert/commit error
                # rolls both back, so the next sweep retries.
                conn.commit()
    except Exception as e:
        _bump_error()
        _warn_once('maint_overdue', f"maintenance overdue sweep failed: {e}")
        return 0
    return emitted


def insert_events_with_disposition(rows, *, timeout_s=None):
    """Insert validated events and return ``(new_ids, duplicate_count)``.

    The disposition comes directly from the transaction that performed the
    inserts. A concurrent request therefore cannot replace the duplicate
    count before an HTTP handler constructs its strict cursor acknowledgment.
    """
    if not enabled():
        raise StoreDisabled(f"{DISABLE_ENV} is off")
    sql = (f"INSERT OR IGNORE INTO machine_events ({', '.join(_EVENT_COLS)}) "
           f"VALUES ({', '.join('?' * len(_EVENT_COLS))})")
    dups = 0
    rows = list(rows)
    with _store_lock(timeout_s) as deadline:
        with closing(_connect(deadline)) as conn:
            ids = []
            for row in rows:
                cur = conn.execute(sql, tuple(row[c] for c in _EVENT_COLS))
                if cur.rowcount == 0:
                    dups += 1          # identity already stored: replay no-op
                else:
                    event_id = cur.lastrowid
                    ids.append(event_id)
                    if row["severity"] == "fault":
                        incident = conn.execute(
                            "SELECT id FROM lane_incidents "
                            "WHERE lane_id=? AND event_type=? "
                            "AND COALESCE(code,'')=COALESCE(?, '') "
                            "AND state IN ('open','override_pending')",
                            (row["lane_id"], row["event_type"],
                             row.get("code"))).fetchone()
                        if incident is None:
                            incident_cur = conn.execute(
                                "INSERT INTO lane_incidents "
                                "(lane_id,event_type,code,opened_at,"
                                "last_seen_at,repeat_count,state) "
                                "VALUES (?,?,?,?,?,1,'open')",
                                (row["lane_id"], row["event_type"],
                                 row.get("code"), row["created_at"],
                                 row["created_at"]))
                            incident_id = incident_cur.lastrowid
                        else:
                            incident_id = incident["id"]
                            conn.execute(
                                "UPDATE lane_incidents SET "
                                "last_seen_at=?,repeat_count=repeat_count+1 "
                                "WHERE id=?",
                                (row["created_at"], incident_id))
                        conn.execute(
                            "UPDATE machine_events SET incident_id=? "
                            "WHERE id=?",
                            (incident_id, event_id))
            activity_at = _utc_now_iso()
            for lane_id in sorted({
                    row['lane_id'] for row in rows
                    if not str(row.get('code') or '').startswith(
                        'deploy_marker')}):
                conn.execute(_LEASE_UPSERT, (lane_id, activity_at))
            conn.commit()
    # Ingest proves the board-side pipeline is alive — EXCEPT synthetic
    # Deploy markers are excluded above and cannot fake board liveness.
    return ids, dups


def insert_events(rows, *, timeout_s=None):
    """Compatibility wrapper returning only newly inserted ids.

    Request/response code must use :func:`insert_events_with_disposition`.
    ``last_insert_duplicates`` remains for legacy in-process callers only and
    is intentionally not used to form an HTTP acknowledgment.
    """
    global _last_dup_count
    ids, dups = insert_events_with_disposition(
        rows, timeout_s=timeout_s)
    with _err_lock:
        _last_dup_count = dups
    return ids


def insert_cycle_with_disposition(row):
    """Insert one cycle and return ``(stored_id, duplicate)`` request-locally."""
    if not enabled():
        raise StoreDisabled(f"{DISABLE_ENV} is off")
    sql = (f"INSERT OR IGNORE INTO machine_cycles ({', '.join(_CYCLE_COLS)}) "
           f"VALUES ({', '.join('?' * len(_CYCLE_COLS))})")
    with _db_lock:
        with closing(_connect()) as conn:
            cur = conn.execute(sql, tuple(row[c] for c in _CYCLE_COLS))
            if cur.rowcount == 0 and row.get('source_id') is not None:
                duplicate = True
                existing = conn.execute(
                    "SELECT id FROM machine_cycles WHERE source_id = ? "
                    "AND boot_id = ? AND seq = ?",
                    (row['source_id'], row['boot_id'],
                     row['seq'])).fetchone()
                conn.commit()
                cycle_id = existing['id'] if existing is not None else None
            else:
                duplicate = False
                conn.commit()
                cycle_id = cur.lastrowid
    touch_lanes([row['lane_id']])
    return cycle_id, duplicate


def insert_cycle(row):
    """Compatibility wrapper returning only the stored cycle id."""
    global _last_cycle_dup
    cycle_id, duplicate = insert_cycle_with_disposition(row)
    with _err_lock:
        _last_cycle_dup = duplicate
    return cycle_id


def ack_event(event_id, by):
    """Acknowledge an event (desk action). Idempotent: the first ack
    wins; a repeat returns the row unchanged with
    already_acknowledged=True. Returns None when the id doesn't exist.
    `by` is the wsl.db staff id — an OPAQUE int across the domain
    boundary (never joined against here)."""
    by = _staff_actor_id(by, 'acknowledged_by')
    now = _utc_now_iso()
    with _db_lock:
        with closing(_connect()) as conn:
            cur = conn.execute(
                "UPDATE machine_events SET acknowledged_at = ?, "
                "acknowledged_by = ? WHERE id = ? AND acknowledged_at IS NULL",
                (now, by, event_id))
            changed = cur.rowcount
            row = conn.execute("SELECT * FROM machine_events WHERE id = ?",
                               (event_id,)).fetchone()
            conn.commit()
    if row is None:
        return None
    out = dict(row)
    out['already_acknowledged'] = (changed == 0)
    return out


def _resolve_event_legacy(event_id, by):
    """Mark an event resolved. Idempotent (first resolve wins).
    Returns None when the id doesn't exist. Independent of ack — a
    fault can be resolved un-acked and vice versa."""
    by = _staff_actor_id(by, 'resolved_by')
    now = _utc_now_iso()
    with _db_lock:
        with closing(_connect()) as conn:
            cur = conn.execute(
                "UPDATE machine_events SET resolved_at = ?, resolved_by = ? "
                "WHERE id = ? AND resolved_at IS NULL",
                (now, by, event_id))
            changed = cur.rowcount
            row = conn.execute("SELECT * FROM machine_events WHERE id = ?",
                               (event_id,)).fetchone()
            conn.commit()
    if row is None:
        return None
    out = dict(row)
    out['already_resolved'] = (changed == 0)
    return out


def resolve_event(event_id, by, *, recovery_event_id=None,
                  override_reason=None):
    """Resolve only from later recovery evidence.

    A privileged override is durable and visible but intentionally leaves the
    fault open (incident state ``override_pending``); it cannot make a lane
    falsely green.
    """
    by = _staff_actor_id(by, 'resolved_by')
    if (recovery_event_id is None) == (override_reason is None):
        raise ValueError(
            "provide exactly one of recovery_event_id or override_reason")
    if recovery_event_id is not None:
        recovery_event_id = _opt_int(
            recovery_event_id, "recovery_event_id")
        if recovery_event_id <= 0:
            raise ValueError("recovery_event_id must be positive")
    if override_reason is not None:
        if (not isinstance(override_reason, str)
                or not 10 <= len(override_reason.strip()) <= 1000):
            raise ValueError(
                "override_reason must be 10..1000 characters")
        override_reason = override_reason.strip()
    now = _utc_now_iso()
    with _db_lock:
        with closing(_connect()) as conn:
            target = conn.execute(
                "SELECT * FROM machine_events WHERE id=?",
                (event_id,)).fetchone()
            if target is None:
                return None
            incident_id = target["incident_id"]
            if target["resolved_at"] is not None:
                if override_reason is not None:
                    raise ValueError(
                        "fault is already resolved; override is unavailable")
                if incident_id is not None:
                    prior = conn.execute(
                        "SELECT recovery_event_id FROM lane_incidents "
                        "WHERE id=? AND state='closed'",
                        (incident_id,)).fetchone()
                else:
                    prior = conn.execute(
                        "SELECT recovery_event_id "
                        "FROM machine_resolution_audit "
                        "WHERE event_id=? AND action='recovery' "
                        "ORDER BY id DESC LIMIT 1",
                        (event_id,)).fetchone()
                prior_recovery_id = (
                    prior["recovery_event_id"]
                    if prior is not None else None)
                if prior_recovery_id is None:
                    raise ValueError(
                        "resolved fault lacks verifiable recovery evidence")
                if prior_recovery_id != recovery_event_id:
                    raise ValueError(
                        "resolution replay conflicts with stored "
                        "recovery_event_id")
                out = dict(target)
                out["already_resolved"] = True
                out["override_pending"] = False
                out["recovery_event_id"] = prior_recovery_id
                return out
            if target["severity"] != "fault":
                raise ValueError("only fault events require resolution")
            if override_reason is not None:
                existing = conn.execute(
                    "SELECT id FROM machine_resolution_audit "
                    "WHERE event_id=? AND action='override_requested' "
                    "AND actor_id=? AND reason=?",
                    (event_id, by, override_reason)).fetchone()
                if existing is None:
                    conn.execute(
                        "INSERT INTO machine_resolution_audit "
                        "(event_id,incident_id,action,actor_id,reason,"
                        "created_at) VALUES (?,?,"
                        "'override_requested',?,?,?)",
                        (event_id, incident_id, by,
                         override_reason, now))
                if incident_id is not None:
                    conn.execute(
                        "UPDATE lane_incidents SET state='override_pending' "
                        "WHERE id=? AND state='open'",
                        (incident_id,))
                conn.commit()
                out = dict(conn.execute(
                    "SELECT * FROM machine_events WHERE id=?",
                    (event_id,)).fetchone())
                out["already_resolved"] = False
                out["override_pending"] = True
                return out
            recovery = conn.execute(
                "SELECT * FROM machine_events WHERE id=?",
                (recovery_event_id,)).fetchone()
            if recovery is None:
                raise ValueError("recovery_event_id not found")
            try:
                detail = json.loads(recovery["detail_json"] or "{}")
                explicit_target = detail.get("recovery_of_event_id")
            except (TypeError, ValueError):
                explicit_target = None
            code_match = (
                target["code"] is not None
                and recovery["code"] == target["code"])
            valid_recovery = (
                recovery["lane_id"] == target["lane_id"]
                and recovery["severity"] == "info"
                and recovery["id"] > target["id"]
                and (explicit_target == event_id or code_match))
            if not valid_recovery:
                raise ValueError(
                    "recovery event must be a later same-lane info event "
                    "with matching code or explicit recovery_of_event_id")
            if incident_id is None:
                cur = conn.execute(
                    "UPDATE machine_events SET resolved_at=?,resolved_by=? "
                    "WHERE id=? AND resolved_at IS NULL",
                    (now, by, event_id))
                changed = cur.rowcount
            else:
                cur = conn.execute(
                    "UPDATE machine_events SET resolved_at=?,resolved_by=? "
                    "WHERE incident_id=? AND severity='fault' "
                    "AND resolved_at IS NULL",
                    (now, by, incident_id))
                changed = cur.rowcount
                conn.execute(
                    "UPDATE lane_incidents SET state='closed',"
                    "recovery_event_id=?,closed_at=?,closed_by=? "
                    "WHERE id=?",
                    (recovery_event_id, now, by, incident_id))
            conn.execute(
                "INSERT INTO machine_resolution_audit "
                "(event_id,incident_id,action,actor_id,"
                "recovery_event_id,created_at) "
                "VALUES (?,?,'recovery',?,?,?)",
                (event_id, incident_id, by,
                 recovery_event_id, now))
            row = conn.execute(
                "SELECT * FROM machine_events WHERE id=?",
                (event_id,)).fetchone()
            conn.commit()
    out = dict(row)
    out["already_resolved"] = changed == 0
    out["override_pending"] = False
    return out


# ------------------------------------------------------------------
# Reads
# ------------------------------------------------------------------

def lane_diagnostics(lane_id, events_limit=50):
    """Per-lane diagnostics payload for GET /api/lane/<N>/diagnostics:
    unresolved faults, last N events, the latest cycle (with its six
    intervals), and a baseline summary over the last
    BASELINE_SAMPLE_CYCLES clean (non-aborted, non-shadow) cycles."""
    events_limit = max(1, min(int(events_limit), 500))
    with _db_lock:
        with closing(_connect()) as conn:
            open_faults = [dict(r) for r in conn.execute(
                "SELECT * FROM machine_events WHERE lane_id = ? "
                "AND severity = 'fault' AND resolved_at IS NULL "
                "ORDER BY created_at DESC, id DESC LIMIT 100",
                (lane_id,))]
            events = [dict(r) for r in conn.execute(
                "SELECT * FROM machine_events WHERE lane_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (lane_id, events_limit))]
            incidents = [dict(r) for r in conn.execute(
                "SELECT * FROM lane_incidents WHERE lane_id=? "
                "AND state IN ('open','override_pending') "
                "ORDER BY last_seen_at DESC,id DESC LIMIT 100",
                (lane_id,))]
            resolution_audit = [dict(r) for r in conn.execute(
                "SELECT a.* FROM machine_resolution_audit a "
                "JOIN machine_events e ON e.id=a.event_id "
                "WHERE e.lane_id=? ORDER BY a.created_at DESC,a.id DESC "
                "LIMIT 100",
                (lane_id,))]
            latest = conn.execute(
                "SELECT * FROM machine_cycles WHERE lane_id = ? "
                "ORDER BY started_at DESC, id DESC LIMIT 1",
                (lane_id,)).fetchone()
            latest_cycle = dict(latest) if latest is not None else None
            base_rows = conn.execute(
                "SELECT * FROM machine_cycles WHERE lane_id = ? "
                "AND aborted = 0 AND shadow = 0 "
                "ORDER BY started_at DESC, id DESC LIMIT ?",
                (lane_id, BASELINE_SAMPLE_CYCLES)).fetchall()
    baseline = None
    if base_rows:
        intervals = {}
        for col in INTERVAL_COLUMNS:
            vals = [r[col] for r in base_rows if r[col] is not None]
            if vals:
                intervals[col] = {
                    'n': len(vals),
                    'mean_ms': round(sum(vals) / len(vals), 1),
                    'min_ms': min(vals),
                    'max_ms': max(vals),
                }
        if intervals:
            baseline = {'sample_cycles': len(base_rows),
                        'intervals': intervals}
    return {
        'ok': True,
        'lane': lane_id,
        'open_faults': open_faults,
        'events': events,
        'open_incidents': incidents,
        'resolution_audit': resolution_audit,
        'latest_cycle': latest_cycle,
        'baseline': baseline,
    }


def _empty_lane_rollup():
    return {
        'open_faults': 0,
        'fault': False,
        'code': None,
        'since': None,
        'acked': False,
        'last_event_at': None,
        'last_event_type': None,
        'last_event_code': None,
        'last_cycle_at': None,
        'last_cycle_final_state': None,
        # R2-10 lease/state fields — recomputed for every entry in
        # machine_health(); UNKNOWN is the fail-honest default.
        'state': 'UNKNOWN',
        'last_seen': None,
        'age_s': None,
        'activity_seen_at': None,
        'scoring_seen_at': None,
        'scoring_age_s': None,
        'scoring_state': 'UNKNOWN',
        'scoring_reason': None,
        'scoring_reasons': [],
        'scoring_mode': None,
        'scoring_camera_calibrated': None,
        'scoring_camera_ok': None,
        'scoring_camera_code': None,
        'scoring_outbox': None,
        'scoring_boot_id': None,
        'scoring_session_id': None,
        'scoring_heartbeat_seq': None,
        'scoring_node_lockout_s': None,
        'heartbeat_at': None,
        'controller_boot_id': None,
        'heartbeat_seq': None,
        'control_loop_seq': None,
        'control_loop_progress_at': None,
        'control_loop_age_s': None,
        'board_rev': None,
        'observed_pcb': None,
        'observed_rid': None,
        'observed_uid': None,
        'fw_build': None,
        'fw_cfg': None,
        'fw_version': None,
        'contract_sha256': None,
        'contract_loaded': False,
        'contract_match': False,
        'identity_ok': False,
        'identity_reason': None,
        'ro_fs': None,
        'outbox': None,
        'platform': None,
        'serial_parse_errors': 0,
        'diag_record_drops': 0,
        'maintenance_overdue': False,
        'degraded': False,
        'degraded_reasons': [],
    }


def machine_health():
    """Per-lane rollup for GET /api/machine/health — the bulk shape
    wsl_api polls so idle-machine faults surface without a per-lane
    fanout.

    ⚠️ CROSS-REPO CONTRACT (2026-07-19 review): each lane entry carries the
    keys wsl_phase8_bridge._parse_machine_health whitelists —
    {fault, code, since, acked, event_id, severity} — pinned by
    WSL Systems tests/test_phase8_bridge_contract.py and
    tests/test_pytest_machine_health.py, and consumed by
    wsl_machine_alerts.observe_health (desk badge + mechanic SMS). Change
    them in lockstep only. 'code'/'since'/'acked'/'event_id' come from the
    NEWEST OPEN FAULT event (severity='fault', unresolved) — deliberately
    NOT last_event_code, which rolls forward on every info event and would
    turn each routine event into a "new latch" that bypasses the SMS
    throttle. The last_event_*/last_cycle_* keys are informational extras
    ('last' = newest event/cycle time, id-tiebroken).

    Query shape: bounded per-lane point lookups (lanes 1-32, indexed) plus
    the tiny partial open-fault index — never a full table scan under
    _db_lock (the :8766 HTTP thread also serves the desk scoring proxy)."""
    lanes = {}
    with _db_lock:
        with closing(_connect()) as conn:
            # Open-fault count + newest open fault — both ride the partial
            # index idx_me_open_fault (rows shrink to the open-fault set).
            for r in conn.execute(
                    "SELECT lane_id, COUNT(*) AS n FROM machine_events "
                    "WHERE severity = 'fault' AND resolved_at IS NULL "
                    "GROUP BY lane_id"):
                lanes.setdefault(str(r['lane_id']),
                                 _empty_lane_rollup())['open_faults'] = r['n']
            for r in conn.execute(
                    "SELECT e.lane_id AS lane_id, e.id AS id, "
                    "e.created_at AS created_at, e.code AS code, "
                    "e.severity AS severity, "
                    "e.acknowledged_at AS acknowledged_at "
                    "FROM machine_events e JOIN (SELECT lane_id, MAX(id) AS m "
                    "FROM machine_events WHERE severity = 'fault' "
                    "AND resolved_at IS NULL GROUP BY lane_id) open "
                    "ON e.id = open.m"):
                d = lanes.setdefault(str(r['lane_id']), _empty_lane_rollup())
                d['fault'] = True
                d['code'] = r['code']
                d['since'] = r['created_at']
                d['acked'] = r['acknowledged_at'] is not None
                d['event_id'] = r['id']
                d['severity'] = r['severity']
            for lane_id in range(1, 33):
                r = conn.execute(
                    "SELECT created_at, event_type, code FROM machine_events "
                    "WHERE lane_id = ? ORDER BY created_at DESC, id DESC "
                    "LIMIT 1", (lane_id,)).fetchone()
                if r is not None:
                    d = lanes.setdefault(str(lane_id), _empty_lane_rollup())
                    d['last_event_at'] = r['created_at']
                    d['last_event_type'] = r['event_type']
                    d['last_event_code'] = r['code']
                c = conn.execute(
                    "SELECT started_at, final_state FROM machine_cycles "
                    "WHERE lane_id = ? ORDER BY started_at DESC, id DESC "
                    "LIMIT 1", (lane_id,)).fetchone()
                if c is not None:
                    d = lanes.setdefault(str(lane_id), _empty_lane_rollup())
                    d['last_cycle_at'] = c['started_at']
                    d['last_cycle_final_state'] = c['final_state']
            lease_rows = {r['lane_id']: dict(r) for r in conn.execute(
                "SELECT * FROM machine_leases")}
    # R2-10: every configured machine lane gets an explicit board state —
    # a lane the store has never heard from must appear as UNKNOWN, not
    # be omitted (omission is exactly how a dead board looks healthy).
    now_dt = datetime.now(timezone.utc)
    window = lease_window_s()
    lane_ids = set(configured_lanes()) | {int(k) for k in lanes}
    for lane_id in sorted(lane_ids):
        entry = lanes.setdefault(str(lane_id), _empty_lane_rollup())
        lease = lease_rows.get(lane_id) or {}
        # Only the strict controller heartbeat renews the controller lease.
        # Event/cycle replay and Track-A WS traffic update activity_seen_at but
        # can never make a stalled Track-B controller look healthy.
        activity_seen = lease.get('last_seen')
        scoring_seen, scoring_age_s, scoring_error = _lease_timestamp_age(
            lease.get('scoring_seen_at'), now_dt, 'scoring')
        last_seen, age_s, controller_time_error = _lease_timestamp_age(
            lease.get('controller_seen_at'), now_dt, 'controller')
        progress_at, progress_age_s, progress_time_error = (
            _lease_timestamp_age(
                lease.get('control_loop_progress_at'), now_dt,
                'control_loop'))
        try:
            outbox = json.loads(lease['outbox_json']) \
                if lease.get('outbox_json') else None
        except (TypeError, ValueError):
            outbox = None
        try:
            platform = json.loads(lease['platform_json']) \
                if lease.get('platform_json') else None
        except (TypeError, ValueError):
            platform = None
        try:
            scoring_outbox = json.loads(lease['scoring_outbox_json']) \
                if lease.get('scoring_outbox_json') else None
        except (TypeError, ValueError):
            scoring_outbox = None
        reasons = [
            reason for reason in (
                controller_time_error, progress_time_error)
            if reason is not None]
        if last_seen is not None and age_s <= window:
            if not enabled():
                reasons.append('diagnostics_disabled')
            if lease.get('heartbeat_valid') != 1:
                reasons.append(lease.get('heartbeat_error')
                               or 'heartbeat_invalid')
            if progress_at is None or progress_age_s > window:
                reasons.append('control_loop_stalled')
            if lease.get('identity_ok') != 1:
                reasons.append('identity')
            if lease.get('contract_loaded') != 1:
                reasons.append('contract_unloaded')
            if lease.get('contract_match') != 1:
                reasons.append('contract_mismatch')
            if lease.get('ro_fs') == 1:
                reasons.append('read_only_filesystem')
            reasons.extend(_outbox_degraded_reasons(outbox))
            if not isinstance(platform, dict):
                reasons.append('platform_health_missing')
            elif platform.get('ok') is not True:
                platform_reasons = platform.get('reasons')
                if isinstance(platform_reasons, list) and platform_reasons:
                    reasons.extend(
                        f"platform_{reason}" for reason in platform_reasons)
                else:
                    reasons.append('platform_health_invalid')
            if (lease.get('serial_parse_errors') or 0) > 0:
                reasons.append('rp2040_serial_corrupt')
            if (lease.get('diag_record_drops') or 0) > 0:
                reasons.append('diagnostic_record_drops')
        reasons = sorted(set(reasons))
        if lease.get('maintenance'):
            state = 'MAINTENANCE'
        elif last_seen is None:
            state = 'UNKNOWN'
        elif age_s > window:
            state = 'OFFLINE'
        elif entry['fault']:
            state = 'FAULT'
        elif reasons:
            state = 'DEGRADED'
        else:
            state = 'HEALTHY'
        entry['state'] = state
        entry['last_seen'] = last_seen
        entry['age_s'] = age_s
        entry['activity_seen_at'] = activity_seen
        entry['scoring_seen_at'] = scoring_seen
        entry['scoring_age_s'] = scoring_age_s
        scoring_reasons = []
        if scoring_seen is not None and scoring_age_s <= window:
            mode = lease.get('scoring_mode')
            if (not isinstance(lease.get('scoring_heartbeat_seq'), int)
                    or lease.get('scoring_heartbeat_seq') < 1):
                scoring_reasons.append(
                    'scoring_heartbeat_not_established')
            if mode != 'camera':
                scoring_reasons.append(f"scoring_mode_{mode or 'missing'}")
            if lease.get('scoring_camera_calibrated') != 1:
                scoring_reasons.append('camera_not_calibrated')
            if lease.get('scoring_camera_ok') != 1:
                scoring_reasons.append(
                    lease.get('scoring_camera_code')
                    or 'camera_unhealthy')
            if 'LANE_BALL_DEDUP_S' in os.environ:
                try:
                    expected_lockout = float(
                        os.environ['LANE_BALL_DEDUP_S'])
                    observed_lockout = float(
                        lease.get('scoring_node_lockout_s'))
                    if (not math.isfinite(expected_lockout)
                            or expected_lockout <= 0
                            or abs(observed_lockout - expected_lockout)
                            > 1e-6):
                        scoring_reasons.append(
                            'ball_lockout_policy_mismatch')
                except (TypeError, ValueError):
                    scoring_reasons.append(
                        'ball_lockout_policy_invalid')
            scoring_reasons.extend(_outbox_degraded_reasons(scoring_outbox))
        if scoring_error is not None:
            scoring_reasons.insert(0, scoring_error)
        scoring_reasons = sorted(set(scoring_reasons))
        entry['scoring_state'] = (
            'UNKNOWN' if scoring_seen is None
            else ('OFFLINE' if scoring_age_s > window
                  else ('DEGRADED' if scoring_reasons else 'HEALTHY')))
        entry['scoring_reason'] = (
            scoring_reasons[0] if scoring_reasons else None)
        entry['scoring_reasons'] = scoring_reasons
        entry['scoring_mode'] = lease.get('scoring_mode')
        entry['scoring_camera_calibrated'] = (
            None if lease.get('scoring_camera_calibrated') is None
            else lease.get('scoring_camera_calibrated') == 1)
        entry['scoring_camera_ok'] = (
            None if lease.get('scoring_camera_ok') is None
            else lease.get('scoring_camera_ok') == 1)
        entry['scoring_camera_code'] = lease.get('scoring_camera_code')
        entry['scoring_outbox'] = scoring_outbox
        entry['scoring_boot_id'] = lease.get('scoring_boot_id')
        entry['scoring_session_id'] = lease.get('scoring_session_id')
        entry['scoring_heartbeat_seq'] = lease.get(
            'scoring_heartbeat_seq')
        entry['scoring_node_lockout_s'] = lease.get(
            'scoring_node_lockout_s')
        entry['heartbeat_at'] = lease.get('heartbeat_at')
        entry['controller_boot_id'] = lease.get('controller_boot_id')
        entry['heartbeat_seq'] = lease.get('heartbeat_seq')
        entry['control_loop_seq'] = lease.get('control_loop_seq')
        entry['control_loop_progress_at'] = progress_at
        entry['control_loop_age_s'] = progress_age_s
        for field in (
                'board_rev', 'observed_pcb', 'observed_rid', 'observed_uid',
                'fw_build', 'fw_cfg', 'fw_version', 'contract_sha256',
                'identity_reason'):
            entry[field] = lease.get(field)
        entry['contract_loaded'] = lease.get('contract_loaded') == 1
        entry['contract_match'] = lease.get('contract_match') == 1
        entry['identity_ok'] = lease.get('identity_ok') == 1
        entry['ro_fs'] = (
            None if lease.get('ro_fs') is None else lease.get('ro_fs') == 1)
        entry['outbox'] = outbox
        entry['platform'] = platform
        entry['serial_parse_errors'] = lease.get('serial_parse_errors') or 0
        entry['diag_record_drops'] = lease.get('diag_record_drops') or 0
        entry['maintenance_overdue'] = bool(lease.get('overdue_alerted_at'))
        entry['degraded'] = bool(reasons)
        entry['degraded_reasons'] = reasons
    return {
        'ok': enabled() and diagnostics_contract_ready(),
        'generated_at': _utc_now_iso(),
        'lanes': lanes,
    }


def health_counts():
    """Counts-only section for /api/health enrichment. NEVER raises —
    a broken diagnostics DB must not take down the health endpoint."""
    contract = contract_status()
    out = {
        'enabled': enabled(),
        'retention_days': retention_days(),
        'errors': error_count(),
        'contract': contract,
    }
    try:
        with _db_lock:
            with closing(_connect()) as conn:
                out['events_total'] = conn.execute(
                    "SELECT COUNT(*) AS n FROM machine_events").fetchone()['n']
                out['open_faults'] = conn.execute(
                    "SELECT COUNT(*) AS n FROM machine_events "
                    "WHERE severity = 'fault' AND resolved_at IS NULL"
                ).fetchone()['n']
                out['cycles_total'] = conn.execute(
                    "SELECT COUNT(*) AS n FROM machine_cycles").fetchone()['n']
        reasons = []
        if not enabled():
            reasons.append('diagnostics_disabled')
        if not contract.get('loaded'):
            reasons.append('contract_unloaded')
        elif not contract.get('strict'):
            reasons.append('contract_unstrict')
        out['reasons'] = reasons
        out['ok'] = not reasons
    except Exception as e:
        _bump_error()
        out['ok'] = False
        out['error'] = str(e)
    return out


# ------------------------------------------------------------------
# Retention
# ------------------------------------------------------------------

def prune_events(now=None):
    """Delete expired history while preserving every unresolved fault.

    An unresolved fault is active operational state, not merely historical
    telemetry. It remains visible regardless of age and becomes eligible for
    normal retention only after ``resolved_at`` is set. Returns the deleted
    count and is a no-op when the kill-switch is off.
    """
    if not enabled():
        return 0
    base = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    cutoff = _normalize_utc_iso(base - timedelta(days=retention_days()))
    with _db_lock:
        with closing(_connect()) as conn:
            cur = conn.execute(
                "DELETE FROM machine_events WHERE created_at < ? "
                "AND NOT (severity = 'fault' AND resolved_at IS NULL) "
                "AND id NOT IN (SELECT event_id "
                "FROM machine_resolution_audit) "
                "AND id NOT IN (SELECT recovery_event_id "
                "FROM machine_resolution_audit "
                "WHERE recovery_event_id IS NOT NULL) "
                "AND id NOT IN (SELECT recovery_event_id "
                "FROM lane_incidents WHERE recovery_event_id IS NOT NULL)",
                (cutoff,))
            deleted = cur.rowcount
            conn.commit()
    if deleted:
        log.info(f"Retention: pruned {deleted} machine_events older than "
                 f"{cutoff} ({retention_days()} days)")
    return deleted


def _retention_loop(interval_s):
    # R3-10: the maintenance-overdue sweep needs a finer cadence than the
    # daily prune (a 12 h flag left on should alert the same day, not on the
    # next prune tick). Wake at most every MAINT_SWEEP_S; run the (cheap)
    # overdue sweep every wake and the prune only once per interval_s.
    sweep_s = min(interval_s, _env_float(
        "WSL_MACHINE_MAINT_SWEEP_S", 900.0))   # 15 min default
    last_prune = 0.0
    while True:
        try:
            now = time.monotonic()
            if now - last_prune >= interval_s:
                prune_events()
                last_prune = now
        except Exception as e:
            _bump_error()
            log.warning(f"machine_events retention prune failed: {e}")
        try:
            sweep_maintenance_overdue()
        except Exception as e:
            _bump_error()
            log.warning(f"maintenance overdue sweep failed: {e}")
        if _retention_wake.wait(sweep_s):
            _retention_wake.clear()


def start_retention_thread(interval_s=86400.0):
    """Start the startup + daily prune on a daemon thread (the server's
    background pattern — same shape as http_thread). Idempotent; never
    raises. The first prune runs immediately ON the background thread,
    so startup is never blocked on a large delete."""
    if _retention_started.is_set():
        return None
    _retention_started.set()
    t = threading.Thread(target=_retention_loop, args=(interval_s,),
                         daemon=True, name='machine-diag-retention')
    t.start()
    return t


def clear_state():
    """Wipe both tables. Tests + manual recovery only."""
    try:
        with _db_lock:
            with closing(_connect()) as conn:
                conn.execute("DELETE FROM machine_resolution_audit")
                conn.execute("DELETE FROM lane_incidents")
                conn.execute("DELETE FROM machine_events")
                conn.execute("DELETE FROM machine_cycles")
                conn.commit()
        log.info(f"Cleared machine diagnostics state in {DB_PATH}")
    except Exception as e:
        log.warning(f"machine_store.clear_state failed: {e}")


if __name__ == '__main__':
    # Quick CLI: python3 machine_store.py [health|prune|clear]
    import sys
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'health'
    if cmd == 'clear':
        clear_state()
    elif cmd == 'prune':
        print(f"pruned {prune_events()} event(s)")
    else:
        print(json.dumps({'health': health_counts(),
                          'rollup': machine_health()}, indent=2))
