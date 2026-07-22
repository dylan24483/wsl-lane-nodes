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
import os
import sqlite3
import threading
from contextlib import closing
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
# no table rebuild needed). Initial event set is the scope §2 list.
EVENT_TYPES = {
    'fsm_fault', 'fw_fault', 'drift_alarm', 'chatter', 'link_lost',
    'fw_reboot', 'rp2040_wdt_reset', 'rail_drop', 'pi_undervoltage',
    'service_restart', 'stuck_input', 'beam_blocked', 'gripper_disagree',
    'short_rack', 'run_mismatch', 'manual_override', 'recovered',
    # 2026-07-19 wave-2 daemon-integration additions (Pi-side emitters):
    'unexpected_edge',                       # FSM out-of-state cam/ball counts
    'be_stuck_running', 'be_no_current',     # AUX be_current rules
    'ball_return_missing',                   # AUX exit_beam rule (catalog §1.2)
    'dist_index_stall',                      # AUX dist_index rule
    # 2026-07-21 Codex round-2 additions:
    # R2-11 — firmware v1.2.x record consumption (tap ring / warns / VCC_5V):
    'tapdump',                               # aggregated rail-drop edge ring
    'tap_warn',                              # fw tapwarn (e.g. rpok_mism)
    'v5_out_of_range',                       # VCC_5V hb extrema out of window
    # R2-12 — bank health + promoted infrastructure faults:
    'bank_unavailable', 'stale_channel', 'configured_role_missing',
    'uart_drops', 'diag_drops', 'http_sink_drops',
    'service_restart_loop', 'fw_config_mismatch',
    # R2-16 — FIELD_WET loopback role (AUX11):
    'field_wet_lost', 'field_wet_restored',
    # R2-14 — camera + Pi platform health:
    'camera_health', 'camera_ref_drift', 'gs_camera_disagree',
    'pi_disk_low', 'pi_fs_readonly', 'pi_thermal', 'pi_clock_drift',
    'diag_storage_pruned',
}
SEVERITIES = ('info', 'warn', 'fault')  # the ONLY CHECK enum
CYCLE_TYPES = {'ball', 'reset', 'power_on', 'manual', 'test'}
FINAL_STATES = {'READY', 'FAULT', 'MANUAL_INTERVENTION'}

# The six CamTelemetry intervals (scope §2 schema), integer ms.
INTERVAL_COLUMNS = ('ss_to_guard_ms', 'guard_to_table_ms', 'table_to_ta2_ms',
                    'ta2_to_sa_ms', 'sa_to_ta1zero_ms', 'bs_to_ta1zero_ms')

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
MACHINE_STATES = ('HEALTHY', 'FAULT', 'OFFLINE', 'UNKNOWN', 'MAINTENANCE')
LEASE_WINDOW_ENV = "WSL_MACHINE_LEASE_S"
DEFAULT_LEASE_WINDOW_S = 90.0
MACHINE_LANES_ENV = "WSL_MACHINE_LANES"
DEFAULT_MACHINE_LANES = "21,22"   # PHASE_8_PAIRS; grows with the rollout


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

_warned = set()

_retention_started = threading.Event()
_retention_wake = threading.Event()


class StoreDisabled(RuntimeError):
    """Raised by ingest writes when WSL_MACHINE_DIAG is switched off."""


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
    """Identity-deduped row count from the most recent insert_events call
    (the ingest handler reports it as 'duplicates' — replay honesty)."""
    with _err_lock:
        return _last_dup_count


def _warn_once(key, msg):
    if key not in _warned:
        _warned.add(key)
        log.warning(msg)


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


def _ensure_schema(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _migrate_identity(conn)


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
        return _normalize_utc_iso(value)
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
    row = {}
    row['lane_id'] = _lane_id(ev.get('lane_id'))
    severity = ev.get('severity')
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {list(SEVERITIES)}")
    row['severity'] = severity
    event_type = ev.get('event_type')
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
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
    row = {}
    row['lane_id'] = _lane_id(c.get('lane_id'))
    row['started_at'] = _timestamp(c.get('started_at'), 'started_at',
                                   default_now=True)
    ended = c.get('ended_at')
    row['ended_at'] = (_timestamp(ended, 'ended_at', default_now=False)
                       if ended is not None else None)
    cycle_type = c.get('cycle_type')
    if cycle_type is not None and cycle_type not in CYCLE_TYPES:
        raise ValueError(f"unknown cycle_type {cycle_type!r} "
                         f"(allowed: {sorted(CYCLE_TYPES)})")
    row['cycle_type'] = cycle_type
    row['ball'] = _opt_int(c.get('ball'), 'ball')
    final_state = c.get('final_state')
    if final_state not in FINAL_STATES:
        raise ValueError(f"final_state must be one of {sorted(FINAL_STATES)}")
    row['final_state'] = final_state
    row['aborted'] = 1 if c.get('aborted') else 0
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
    row['shadow'] = 1 if c.get('shadow') else 0
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


def touch_lanes(lane_ids, when=None):
    """Record 'the machine-side daemon was heard from' for these lanes
    (WS HELLO/HEARTBEAT + machine ingest call this). NEVER raises — it
    runs on the asyncio WS thread and liveness bookkeeping must not take
    down scoring. Deliberately NOT gated on WSL_MACHINE_DIAG: switching
    diagnostics ingest off must not make live boards read OFFLINE."""
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


def set_maintenance(lane_id, on, note=None):
    """Mechanic maintenance flag for one lane (state MAINTENANCE wins
    over everything and suppresses WSL-side alerting). Returns the lease
    row as a dict. Raises ValueError on a bad lane id."""
    lane_id = _lane_id(lane_id)
    note = _opt_str(note, 'maintenance_note', max_len=500)
    now = _utc_now_iso()
    with _db_lock:
        with closing(_connect()) as conn:
            conn.execute(
                "INSERT INTO machine_leases (lane_id, maintenance, "
                "maintenance_note, maintenance_changed_at) VALUES (?,?,?,?) "
                "ON CONFLICT(lane_id) DO UPDATE SET maintenance = ?, "
                "maintenance_note = ?, maintenance_changed_at = ?",
                (lane_id, 1 if on else 0, note, now,
                 1 if on else 0, note, now))
            conn.commit()
            row = conn.execute("SELECT * FROM machine_leases WHERE lane_id = ?",
                               (lane_id,)).fetchone()
    return dict(row) if row is not None else {'lane_id': lane_id}


def insert_events(rows):
    """Insert validated event rows in one transaction. Returns the new ids
    (rows deduped by delivery identity are SKIPPED, not re-inserted — the
    R2-12 idempotent-replay semantics: INSERT OR IGNORE rides the
    uq_me_delivery partial UNIQUE index). Duplicate counts are exposed via
    last_insert_duplicates(). Raises StoreDisabled when the kill-switch
    is off."""
    global _last_dup_count
    if not enabled():
        raise StoreDisabled(f"{DISABLE_ENV} is off")
    sql = (f"INSERT OR IGNORE INTO machine_events ({', '.join(_EVENT_COLS)}) "
           f"VALUES ({', '.join('?' * len(_EVENT_COLS))})")
    dups = 0
    with _db_lock:
        with closing(_connect()) as conn:
            ids = []
            for row in rows:
                cur = conn.execute(sql, tuple(row[c] for c in _EVENT_COLS))
                if cur.rowcount == 0:
                    dups += 1          # identity already stored: replay no-op
                else:
                    ids.append(cur.lastrowid)
            conn.commit()
    with _err_lock:
        _last_dup_count = dups
    # Ingest proves the board-side pipeline is alive — EXCEPT synthetic
    # deploy markers, which deploy.ps1 posts from WSL-SRV (R2-8 smoke)
    # and must not fake liveness for a dark board.
    touch_lanes([row['lane_id'] for row in rows
                 if not str(row.get('code') or '').startswith('deploy_marker')])
    return ids


def insert_cycle(row):
    """Insert one validated cycle row; returns the row id. Idempotent on
    delivery identity (R2-12): a replayed cycle POST after a lost ack
    resolves to the ALREADY-stored row's id via the uq_mc_delivery index
    instead of inserting a duplicate. Raises StoreDisabled when the
    kill-switch is off."""
    if not enabled():
        raise StoreDisabled(f"{DISABLE_ENV} is off")
    sql = (f"INSERT OR IGNORE INTO machine_cycles ({', '.join(_CYCLE_COLS)}) "
           f"VALUES ({', '.join('?' * len(_CYCLE_COLS))})")
    with _db_lock:
        with closing(_connect()) as conn:
            cur = conn.execute(sql, tuple(row[c] for c in _CYCLE_COLS))
            if cur.rowcount == 0 and row.get('source_id') is not None:
                existing = conn.execute(
                    "SELECT id FROM machine_cycles WHERE source_id = ? "
                    "AND boot_id = ? AND seq = ?",
                    (row['source_id'], row['boot_id'],
                     row['seq'])).fetchone()
                conn.commit()
                cycle_id = existing['id'] if existing is not None else None
            else:
                conn.commit()
                cycle_id = cur.lastrowid
    touch_lanes([row['lane_id']])
    return cycle_id


def ack_event(event_id, by):
    """Acknowledge an event (desk action). Idempotent: the first ack
    wins; a repeat returns the row unchanged with
    already_acknowledged=True. Returns None when the id doesn't exist.
    `by` is the wsl.db staff id — an OPAQUE int across the domain
    boundary (never joined against here)."""
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


def resolve_event(event_id):
    """Mark an event resolved. Idempotent (first resolve wins).
    Returns None when the id doesn't exist. Independent of ack — a
    fault can be resolved un-acked and vice versa."""
    now = _utc_now_iso()
    with _db_lock:
        with closing(_connect()) as conn:
            cur = conn.execute(
                "UPDATE machine_events SET resolved_at = ? "
                "WHERE id = ? AND resolved_at IS NULL",
                (now, event_id))
            changed = cur.rowcount
            row = conn.execute("SELECT * FROM machine_events WHERE id = ?",
                               (event_id,)).fetchone()
            conn.commit()
    if row is None:
        return None
    out = dict(row)
    out['already_resolved'] = (changed == 0)
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
            latest = conn.execute(
                "SELECT * FROM machine_cycles WHERE lane_id = ? "
                "ORDER BY id DESC LIMIT 1", (lane_id,)).fetchone()
            latest_cycle = dict(latest) if latest is not None else None
            base_rows = conn.execute(
                "SELECT * FROM machine_cycles WHERE lane_id = ? "
                "AND aborted = 0 AND shadow = 0 ORDER BY id DESC LIMIT ?",
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
        last_seen = lease.get('last_seen')
        age_s = None
        if last_seen:
            try:
                age_s = max(0.0, round(
                    (now_dt - datetime.fromisoformat(last_seen)).total_seconds(), 1))
            except ValueError:
                last_seen, age_s = None, None
        if lease.get('maintenance'):
            state = 'MAINTENANCE'
        elif last_seen is None:
            state = 'UNKNOWN'
        elif age_s > window:
            state = 'OFFLINE'
        elif entry['fault']:
            state = 'FAULT'
        else:
            state = 'HEALTHY'
        entry['state'] = state
        entry['last_seen'] = last_seen
        entry['age_s'] = age_s
    return {
        'ok': True,
        'generated_at': _utc_now_iso(),
        'lanes': lanes,
    }


def health_counts():
    """Counts-only section for /api/health enrichment. NEVER raises —
    a broken diagnostics DB must not take down the health endpoint."""
    out = {
        'enabled': enabled(),
        'retention_days': retention_days(),
        'errors': error_count(),
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
        out['ok'] = True
    except Exception as e:
        _bump_error()
        out['ok'] = False
        out['error'] = str(e)
    return out


# ------------------------------------------------------------------
# Retention
# ------------------------------------------------------------------

def prune_events(now=None):
    """Delete machine_events older than the retention window. Returns
    the deleted count. No-op (0) when the kill-switch is off. Cycles
    are kept — they're the small per-cycle aggregate the trend tier
    reads; only the event stream is pruned (scope task 4)."""
    if not enabled():
        return 0
    base = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    cutoff = _normalize_utc_iso(base - timedelta(days=retention_days()))
    with _db_lock:
        with closing(_connect()) as conn:
            cur = conn.execute(
                "DELETE FROM machine_events WHERE created_at < ?", (cutoff,))
            deleted = cur.rowcount
            conn.commit()
    if deleted:
        log.info(f"Retention: pruned {deleted} machine_events older than "
                 f"{cutoff} ({retention_days()} days)")
    return deleted


def _retention_loop(interval_s):
    while True:
        try:
            prune_events()
        except Exception as e:
            _bump_error()
            log.warning(f"machine_events retention prune failed: {e}")
        if _retention_wake.wait(interval_s):
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
