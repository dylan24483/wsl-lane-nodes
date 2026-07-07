#!/usr/bin/env python3
"""SQLite-backed persistence for server-side lane scoring state.

Without this, every server restart wipes all in-progress games. With
this, the server reloads the most recent state for every lane on
startup. Players don't lose their scores if we have to bounce the
server during a game.

Storage: a single SQLite database at the configured path, one snapshot
row holding the whole lane_scoring + ball_counters state as versioned
JSON (see _snapshot_to_json). JSON replaced the original pickle format
in 2026-06: pickle.loads on a corrupted or attacker-substituted DB file
is arbitrary code execution, and pickle silently broke whenever the
LaneScoring class shape changed. The JSON schema serializes every field
explicitly, so engine refactors fail loudly (load logs + starts fresh)
instead of executing whatever is in the blob.

BACKWARD COMPAT: if the snapshot row still holds a legacy pickle blob
(written by a pre-JSON build), load_lanes() unpickles it ONE time —
logging loudly — and immediately rewrites it as JSON. After that the
pickle path is never taken again for that DB.

NOTES:
- The save path is a write-through pattern: every state change calls
  save_lanes(). For high-frequency updates (rapid bowling) this is
  fine — SQLite handles ~1000 transactions/sec on commodity SD cards.
  If save latency ever shows up in profiles, batch saves with a
  background flush task.
- Save failures are tracked (consecutive count + last-ok timestamp)
  and surfaced via get_save_status() → /api/health "state_save", so a
  quietly-failing disk shows up in monitoring instead of losing games
  at the next restart. Repeated failures escalate to log.error.
"""

from __future__ import annotations

import json
import logging
import os
import pickle  # legacy load only — saves are JSON (see module docstring)
import sqlite3
import sys
import threading
import time
from pathlib import Path

# Make wsl_scoring_engine importable regardless of how this module is
# entered. lane_node_server.py adds the same path before importing us,
# but the state_store.py __main__ CLI is a separate entry point that
# doesn't.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from wsl_scoring_engine import (Bowl, Frame, BowlerGame,  # noqa: E402
                                LaneScoring, CrossLaneScoring)

log = logging.getLogger('state_store')

# Default DB location — sits alongside the repo for easy inspection.
# Override via STATE_DB_PATH env var if you want it elsewhere.
DEFAULT_DB_PATH = _REPO_ROOT / "lane_state.db"
DB_PATH = Path(os.environ.get("STATE_DB_PATH", DEFAULT_DB_PATH))

# Threading lock for SQLite write access. The server runs the HTTP
# handler in a worker thread + asyncio in the main thread; both can
# trigger save_lanes(). SQLite itself is thread-safe but a connection
# is not portable across threads, so we guard with a lock and use a
# fresh connection per call.
_db_lock = threading.Lock()

# Save-health tracking (see get_save_status). Guarded by its own lock
# so a status read never waits on a slow SQLite write.
_status_lock = threading.Lock()
_save_status = {
    "last_ok_ts": None,        # time.time() of the last successful save
    "consecutive_failures": 0,
    "last_error": None,
}


def _record_save_ok():
    with _status_lock:
        _save_status["last_ok_ts"] = time.time()
        _save_status["consecutive_failures"] = 0
        _save_status["last_error"] = None


def _record_save_failure(e):
    with _status_lock:
        _save_status["consecutive_failures"] += 1
        _save_status["last_error"] = str(e)
        n = _save_status["consecutive_failures"]
    msg = f"save_lanes failed ({n} consecutive): {e}"
    if n >= 3:
        log.error(msg)
    else:
        log.warning(msg)


def get_save_status() -> dict:
    """Snapshot of persistence health for /api/health. Shape:
    {ok, consecutive_failures, last_error, last_ok_ts, last_ok_age_sec}."""
    with _status_lock:
        st = dict(_save_status)
    st["ok"] = st["consecutive_failures"] == 0
    st["last_ok_age_sec"] = (round(time.time() - st["last_ok_ts"], 1)
                             if st["last_ok_ts"] is not None else None)
    return st


def _ensure_schema():
    """Create the lane_state table if it doesn't exist. Idempotent.

    The blob column is still named state_pickle for schema continuity,
    but new writes store UTF-8 JSON bytes (JSON blobs start with b'{',
    pickle protocol 2+ blobs start with b'\\x80' — load_lanes sniffs
    the first byte to pick the decode path)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lane_state (
                lane_id INTEGER PRIMARY KEY,
                state_pickle BLOB NOT NULL,
                ball_counter INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()


# Sentinel lane_id for the single-snapshot row that holds the whole
# lane_scoring dict serialized together. This preserves Python object
# identity across keys — when a CrossLaneScoring is registered under
# both lane 21 and lane 22, after restart the same object is restored
# under both keys (not two independent copies). The original per-row
# format serialized each lane independently, which broke identity.
_SNAPSHOT_LANE_ID = 0

# Bump when the JSON snapshot schema changes incompatibly. Loads of an
# unknown version log and start fresh (never guess at field meanings).
STATE_FORMAT_VERSION = 1

# Cross-lane bowler attributes set dynamically by CrossLaneScoring
# (BowlerGame has no __slots__, so they live in __dict__).
_BOWLER_EXTRAS = ('starting_physical_lane', 'current_physical_lane',
                  'team_id', 'team_name', 'bowler_id')


# ------------------------------------------------------------------
# JSON round-trip for the scoring objects. Every field is explicit —
# anything the engine adds later must be added here (and the version
# bumped if the change isn't backward-compatible).
# ------------------------------------------------------------------

def _bowl_to_jd(b: Bowl) -> dict:
    return {
        'num': b.num,
        'pin_map': b.pin_map,
        'pins_down': b.pins_down,
        'display': b.display,
        'foul': b.foul,
        'split': b.split,
        'modified': b.modified,
    }


def _bowl_from_jd(d: dict) -> Bowl:
    b = Bowl(num=int(d['num']), pin_map=int(d['pin_map']),
             pins_knocked=int(d['pins_down']),
             display=d.get('display', ''),
             foul=bool(d.get('foul', False)),
             split=bool(d.get('split', False)))
    b.modified = bool(d.get('modified', False))
    return b


def _frame_to_jd(f: Frame) -> dict:
    return {
        'number': f.number,
        'score': f.score,  # None when not yet computable
        'is_strike': f.is_strike,
        'is_spare': f.is_spare,
        'is_complete': f.is_complete,
        'bowls': [_bowl_to_jd(b) for b in f.bowls],
    }


def _frame_from_jd(d: dict) -> Frame:
    f = Frame(int(d['number']))
    score = d.get('score')
    f.score = int(score) if score is not None else None
    f.is_strike = bool(d.get('is_strike', False))
    f.is_spare = bool(d.get('is_spare', False))
    f.is_complete = bool(d.get('is_complete', False))
    f.bowls = [_bowl_from_jd(bd) for bd in d.get('bowls', [])]
    return f


def _bowler_to_jd(b: BowlerGame) -> dict:
    d = {
        'number': b.number,
        'name': b.name,
        'hdcp': b.hdcp,
        'average': b.average,
        'current_frame_idx': b.current_frame_idx,
        'ball_in_frame': b.ball_in_frame,
        'mask_before_ball': b.mask_before_ball,
        # getattr: legacy-pickle-restored bowlers may predate the flag.
        'mask_before_synthetic': bool(getattr(b, 'mask_before_synthetic',
                                              False)),
        'game_over': b.game_over,
        'speed_ball1': b.speed_ball1,
        'speed_ball2': b.speed_ball2,
        'game_number': b.game_number,
        'series_scores': list(b.series_scores),
        'frames': [_frame_to_jd(f) for f in b.frames],
    }
    for attr in _BOWLER_EXTRAS:
        if hasattr(b, attr):
            d[attr] = getattr(b, attr)
    return d


def _bowler_from_jd(d: dict) -> BowlerGame:
    b = BowlerGame(int(d['number']), d['name'],
                   int(d.get('hdcp', 0)), float(d.get('average', 0.0)))
    b.current_frame_idx = int(d.get('current_frame_idx', 0))
    b.ball_in_frame = int(d.get('ball_in_frame', 1))
    b.mask_before_ball = int(d.get('mask_before_ball', 0x3FF))
    b.mask_before_synthetic = bool(d.get('mask_before_synthetic', False))
    b.game_over = bool(d.get('game_over', False))
    b.speed_ball1 = d.get('speed_ball1', 0)
    b.speed_ball2 = d.get('speed_ball2', 0)
    b.game_number = int(d.get('game_number', 1))
    b.series_scores = list(d.get('series_scores', []))
    for fd in d.get('frames', []):
        f = _frame_from_jd(fd)
        if 1 <= f.number <= 10:
            b.frames[f.number - 1] = f
    for attr in _BOWLER_EXTRAS:
        if attr in d:
            setattr(b, attr, d[attr])
    return b


# The engine's _start_new_game caps completed_games at 24 per lane object;
# mirror that bound on restore so a hand-edited / foreign snapshot can't
# balloon the in-memory archive (and every re-save thereafter).
_COMPLETED_GAMES_MAX = 24


def _completed_games_from_jd(d: dict, label: str) -> list:
    """H27 archive with a loud, bounded restore. Old snapshots without the
    field load cleanly as []."""
    cg = d.get('completed_games') or []
    if not isinstance(cg, list):
        log.warning(f"{label}: completed_games is {type(cg).__name__}, "
                    f"not a list — dropping the archive.")
        return []
    if len(cg) > _COMPLETED_GAMES_MAX:
        log.warning(f"{label}: completed_games has {len(cg)} entries; "
                    f"TRUNCATING to the most recent {_COMPLETED_GAMES_MAX}.")
        cg = cg[-_COMPLETED_GAMES_MAX:]
    return list(cg)


def _lane_obj_to_jd(ls) -> dict:
    if isinstance(ls, CrossLaneScoring):
        bowlers = list(ls.bowlers)
        idx = {id(b): i for i, b in enumerate(bowlers)}
        return {
            'kind': 'cross',
            'lane_left': ls.lane_left,
            'lane_right': ls.lane_right,
            'game_number': ls.game_number,
            'is_active': ls.is_active,
            'started_at': ls.started_at,
            # H27 archive — finished scoresheets must survive a restart.
            'completed_games': ls.completed_games,
            'bowlers': [_bowler_to_jd(b) for b in bowlers],
            # Queues hold references into bowlers — serialize as indexes
            # so identity is rebuilt on load.
            'lane_queues': {str(lid): [idx[id(b)] for b in q]
                            for lid, q in ls._lane_queues.items()},
        }
    return {
        'kind': 'lane',
        'lane_id': ls.lane_id,
        'current_bowler_idx': ls.current_bowler_idx,
        'game_number': ls.game_number,
        'is_active': ls.is_active,
        'started_at': ls.started_at,
        # H27 archive — finished scoresheets must survive a restart.
        'completed_games': ls.completed_games,
        'bowlers': [_bowler_to_jd(b) for b in ls.bowlers],
    }


def _lane_obj_from_jd(d: dict):
    if d.get('kind') == 'cross':
        obj = CrossLaneScoring(int(d['lane_left']), int(d['lane_right']))
        obj.game_number = int(d.get('game_number', 1))
        obj.is_active = bool(d.get('is_active', False))
        obj.started_at = d.get('started_at')
        obj.completed_games = _completed_games_from_jd(
            d, f"cross {d.get('lane_left')}/{d.get('lane_right')}")
        bowlers = [_bowler_from_jd(bd) for bd in d.get('bowlers', [])]
        obj.bowlers = bowlers
        queues = {}
        for lid_str, idx_list in (d.get('lane_queues') or {}).items():
            queues[int(lid_str)] = [bowlers[i] for i in idx_list
                                    if 0 <= i < len(bowlers)]
        for lid in (obj.lane_left, obj.lane_right):
            queues.setdefault(lid, [])
        obj._lane_queues = queues
        return obj
    if d.get('kind') == 'lane':
        obj = LaneScoring(int(d['lane_id']))
        obj.current_bowler_idx = int(d.get('current_bowler_idx', 0))
        obj.game_number = int(d.get('game_number', 1))
        obj.is_active = bool(d.get('is_active', False))
        obj.started_at = d.get('started_at')
        obj.completed_games = _completed_games_from_jd(
            d, f"lane {d.get('lane_id')}")
        obj.bowlers = [_bowler_from_jd(bd) for bd in d.get('bowlers', [])]
        return obj
    raise ValueError(f"unknown lane object kind {d.get('kind')!r}")


def _snapshot_to_json(lane_scoring: dict, ball_counters: dict) -> str:
    """Whole-state snapshot. Objects are serialized once and referenced
    by index from the lanes map, preserving cross-lane object identity."""
    objects = []
    obj_index = {}
    lanes = {}
    for lid, ls in lane_scoring.items():
        key = id(ls)
        if key not in obj_index:
            obj_index[key] = len(objects)
            objects.append(_lane_obj_to_jd(ls))
        lanes[str(lid)] = obj_index[key]
    return json.dumps({
        'format': 'wsl-lane-state',
        'version': STATE_FORMAT_VERSION,
        'objects': objects,
        'lanes': lanes,
        'ball_counters': {str(k): v for k, v in ball_counters.items()},
    })


def _snapshot_from_json(text: str) -> tuple[dict, dict]:
    data = json.loads(text)
    if data.get('format') != 'wsl-lane-state':
        raise ValueError(f"unrecognized snapshot format {data.get('format')!r}")
    if data.get('version') != STATE_FORMAT_VERSION:
        raise ValueError(f"unsupported snapshot version {data.get('version')!r} "
                         f"(this build reads v{STATE_FORMAT_VERSION})")
    objects = [_lane_obj_from_jd(od) for od in data.get('objects', [])]
    lane_scoring = {}
    for lid_str, i in (data.get('lanes') or {}).items():
        if 0 <= i < len(objects):
            lane_scoring[int(lid_str)] = objects[i]
    ball_counters = {int(k): int(v)
                     for k, v in (data.get('ball_counters') or {}).items()}
    return lane_scoring, ball_counters


def save_lanes(lane_scoring: dict, ball_counters: dict) -> None:
    """Persist the current state of every lane.

    Called on every BALL_EVENT (write-through) and on graceful
    shutdown. Best-effort — exceptions are logged but don't propagate;
    losing a save shouldn't crash the server. Failures are counted and
    surfaced via get_save_status() so monitoring can alert.

    Format: a single versioned-JSON snapshot stored under lane_id=0.
    This preserves object identity for CrossLaneScoring objects that
    span multiple lane keys.
    """
    try:
        blob = _snapshot_to_json(lane_scoring, ball_counters).encode('utf-8')
        with _db_lock:
            _ensure_schema()
            with sqlite3.connect(DB_PATH) as conn:
                # Replace the snapshot row + remove any legacy per-lane
                # rows from the prior format. Without the DELETE, closed
                # lanes would resurrect on next load because the legacy
                # rows persist independently of the new snapshot.
                conn.execute("DELETE FROM lane_state WHERE lane_id != ?",
                             (_SNAPSHOT_LANE_ID,))
                conn.execute(
                    "INSERT OR REPLACE INTO lane_state "
                    "(lane_id, state_pickle, ball_counter, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (_SNAPSHOT_LANE_ID, blob, 0, time.time())
                )
                conn.commit()
        _record_save_ok()
    except Exception as e:
        _record_save_failure(e)


def _decode_snapshot_blob(blob: bytes) -> tuple[dict, dict, bool]:
    """Decode a snapshot blob. Returns (lane_scoring, ball_counters,
    was_legacy_pickle). JSON blobs start with b'{'; anything else is
    treated as a legacy pickle (pre-2026-06 format) and unpickled ONE
    time — the caller immediately rewrites it as JSON."""
    head = blob.lstrip()[:1] if isinstance(blob, (bytes, bytearray)) else b''
    if head == b'{':
        ls, bc = _snapshot_from_json(blob.decode('utf-8'))
        return ls, bc, False
    log.warning(
        "Snapshot blob is in the LEGACY PICKLE format — loading it one "
        "last time and converting to JSON. If this DB file is not one "
        "this server wrote, delete it instead (pickle can execute code).")
    snapshot = pickle.loads(blob)
    return (snapshot.get('lane_scoring') or {},
            snapshot.get('ball_counters') or {},
            True)


def load_lanes() -> tuple[dict, dict]:
    """Restore the most recent saved state.

    Returns (lane_scoring, ball_counters). Both are empty dicts if
    the DB doesn't exist, the schema is missing, or the saved state
    fails to decode (e.g. snapshot version from a newer build).

    Reads the single-snapshot row (lane_id=0). If only legacy per-lane
    rows exist (from before the snapshot-format change), those are
    ignored — start fresh and the next save_lanes() will overwrite
    them. A legacy PICKLE snapshot row is converted to JSON in place
    (one-time backward compat — see _decode_snapshot_blob).
    """
    lane_scoring: dict = {}
    ball_counters: dict = {}
    was_legacy = False
    try:
        if not DB_PATH.exists():
            log.info(f"No saved state found at {DB_PATH}; starting fresh.")
            return lane_scoring, ball_counters

        with _db_lock:
            _ensure_schema()
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.execute(
                    "SELECT state_pickle, updated_at FROM lane_state "
                    "WHERE lane_id = ?",
                    (_SNAPSHOT_LANE_ID,)
                )
                row = cur.fetchone()
                if row is None:
                    # No snapshot row — either fresh DB or legacy format.
                    # Either way, start fresh.
                    legacy_count = conn.execute(
                        "SELECT COUNT(*) FROM lane_state").fetchone()[0]
                    if legacy_count:
                        log.warning(
                            f"DB at {DB_PATH} has {legacy_count} legacy "
                            f"per-lane row(s) but no snapshot. Ignoring "
                            f"legacy rows (cross-lane identity unreliable); "
                            f"starting fresh.")
                    else:
                        log.info(f"No saved state in {DB_PATH}; starting fresh.")
                    return lane_scoring, ball_counters

                blob, updated_at = row
                try:
                    lane_scoring, ball_counters, was_legacy = \
                        _decode_snapshot_blob(blob)
                except Exception as e:
                    log.warning(
                        f"Failed to decode snapshot: {e}. Usually a schema/"
                        f"class-shape mismatch. Starting fresh.")
                    return {}, {}

                age_min = (time.time() - updated_at) / 60
                log.info(f"Restored {len(lane_scoring)} lane(s) from snapshot "
                         f"(updated {age_min:.1f} min ago).")
                # Confirm cross-lane identity preservation in the log so
                # any future regression is visible at boot.
                shared = {}
                for lid, ls in lane_scoring.items():
                    shared.setdefault(id(ls), []).append(lid)
                for ls_id, lane_ids in shared.items():
                    if len(lane_ids) > 1:
                        log.info(f"  Cross-lane scoring object spans lanes "
                                 f"{sorted(lane_ids)} (identity preserved)")
    except Exception as e:
        log.warning(f"load_lanes failed: {e}; starting fresh.")
        return {}, {}

    if was_legacy:
        # One-time migration: rewrite the legacy pickle as JSON now, so
        # the pickle path is never taken again for this DB (even if the
        # server then idles with no state changes).
        save_lanes(lane_scoring, ball_counters)
        log.info("Legacy pickle snapshot rewritten as JSON.")
    return lane_scoring, ball_counters


def clear_state() -> None:
    """Wipe all saved state. Useful for tests + manual recovery from
    a bad save (e.g. corrupted snapshot). Doesn't delete the DB file
    itself, just the rows."""
    try:
        with _db_lock:
            _ensure_schema()
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM lane_state")
                conn.commit()
        log.info(f"Cleared all saved state from {DB_PATH}")
    except Exception as e:
        log.warning(f"clear_state failed: {e}")


if __name__ == '__main__':
    # Quick CLI for inspection: python3 state_store.py [list|clear]
    import sys
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    if len(sys.argv) > 1 and sys.argv[1] == 'clear':
        clear_state()
    else:
        ls, bc = load_lanes()
        print(f"Loaded {len(ls)} lane(s):")
        for lane_id, lane in ls.items():
            print(f"  Lane {lane_id}: {len(lane.bowlers)} bowlers, "
                  f"ball_counter={bc.get(lane_id, 0)}")
            for b in lane.bowlers:
                print(f"    - {b.name}: frame {b.current_frame_idx + 1}, "
                      f"score {b.current_total}")
