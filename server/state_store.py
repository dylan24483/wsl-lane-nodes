#!/usr/bin/env python3
"""SQLite-backed persistence for server-side lane scoring state.

Without this, every server restart wipes all in-progress games. With
this, the server reloads the most recent state for every lane on
startup. Players don't lose their scores if we have to bounce the
server during a game.

Storage: a single SQLite database at the configured path. One row per
lane, replaced on every update. The LaneScoring object is pickled
because it has internal state (frame indices, running scores, etc.)
that's tedious to serialize as JSON.

CAVEATS:
- Pickle is brittle across changes to the LaneScoring class. If you
  modify wsl_scoring_engine.py's internal structure, old saves may
  fail to load. The load_lanes() function logs the failure and
  returns empty dicts in that case — players lose state but the
  server keeps running.
- This is a prototype-grade implementation. Production deployment
  should switch to a JSON-based serialization with explicit schema
  versioning, OR a normalized SQL schema (frames table, bowls table)
  that doesn't depend on Python-class layout.
- The save path is a write-through pattern: every state change calls
  save_lanes(). For high-frequency updates (rapid bowling) this is
  fine — SQLite handles ~1000 transactions/sec on commodity SD cards.
  If save latency ever shows up in profiles, batch saves with a
  background flush task.
"""

from __future__ import annotations

import logging
import os
import pickle
import sqlite3
import sys
import threading
import time
from pathlib import Path

# Make wsl_scoring_engine importable regardless of how this module is
# entered. The pickled blobs reference wsl_scoring_engine.LaneScoring,
# and pickle.loads needs to be able to find that class on sys.path.
# lane_node_server.py adds the same path before importing us, but the
# state_store.py __main__ CLI is a separate entry point that doesn't.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

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


def _ensure_schema():
    """Create the lane_state table if it doesn't exist. Idempotent."""
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


def save_lanes(lane_scoring: dict, ball_counters: dict) -> None:
    """Persist the current state of every lane.

    Called on every BALL_EVENT (write-through) and on graceful
    shutdown. Best-effort — exceptions are logged but don't propagate;
    losing a save shouldn't crash the server.
    """
    try:
        with _db_lock:
            _ensure_schema()
            with sqlite3.connect(DB_PATH) as conn:
                now = time.time()
                for lane_id, ls in lane_scoring.items():
                    blob = pickle.dumps(ls)
                    counter = ball_counters.get(lane_id, 0)
                    conn.execute(
                        "INSERT OR REPLACE INTO lane_state "
                        "(lane_id, state_pickle, ball_counter, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (lane_id, blob, counter, now)
                    )
                conn.commit()
    except Exception as e:
        log.warning(f"save_lanes failed: {e}")


def load_lanes() -> tuple[dict, dict]:
    """Restore the most recent saved state.

    Returns (lane_scoring, ball_counters). Both are empty dicts if
    the DB doesn't exist, the schema is missing, or any saved state
    fails to unpickle (e.g. LaneScoring class changed since the save).
    """
    lane_scoring: dict = {}
    ball_counters: dict = {}
    try:
        if not DB_PATH.exists():
            log.info(f"No saved state found at {DB_PATH}; starting fresh.")
            return lane_scoring, ball_counters

        with _db_lock:
            _ensure_schema()
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.execute(
                    "SELECT lane_id, state_pickle, ball_counter, updated_at "
                    "FROM lane_state ORDER BY lane_id"
                )
                for lane_id, blob, counter, updated_at in cur.fetchall():
                    try:
                        ls = pickle.loads(blob)
                        lane_scoring[lane_id] = ls
                        ball_counters[lane_id] = counter
                        age_min = (time.time() - updated_at) / 60
                        log.info(f"Restored lane {lane_id} from saved state "
                                 f"(updated {age_min:.1f} min ago)")
                    except Exception as e:
                        log.warning(
                            f"Failed to unpickle saved state for lane {lane_id}: {e}. "
                            f"This is usually a LaneScoring class-shape mismatch. "
                            f"Skipping — that lane will start fresh."
                        )
    except Exception as e:
        log.warning(f"load_lanes failed: {e}; starting fresh.")
    return lane_scoring, ball_counters


def clear_state() -> None:
    """Wipe all saved state. Useful for tests + manual recovery from
    a bad save (e.g. corrupted pickle). Doesn't delete the DB file
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
                      f"score {b.frames[-1].running_total if b.frames else 0}")
