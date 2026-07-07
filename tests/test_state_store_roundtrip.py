"""Round-trip tests for server/state_store.py (versioned-JSON snapshot).

Makes permanent the three behaviors the 2026-06-10 sprint verified with a
throwaway script:
  1. JSON round-trip of single-lane AND cross-lane scoring state
     (scores, cursor, queues, cross-lane object identity, byte-stable
     re-save).
  2. One-time legacy pickle -> JSON migration: a pre-2026-06 pickle blob
     loads once, is immediately rewritten as versioned JSON, and the
     pickle path is never taken again.
  3. Corrupted / unknown-version blobs start fresh (empty state, no
     exception) instead of crashing the server at boot.

READ-ONLY consumer of server/state_store.py and wsl_scoring_engine.py —
each test points state_store.DB_PATH at a throwaway temp file, so the
real lane_state.db is never touched.

Run with:
    py -3 tests/test_state_store_roundtrip.py
"""

import json
import logging
import os
import pickle
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Make wsl_scoring_engine (repo root) + state_store (server/) importable
# when running from anywhere. server/lane_node_server.py imports
# state_store as a top-level module the same way.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, 'server'))

import state_store  # noqa: E402
from wsl_scoring_engine import LaneScoring, CrossLaneScoring  # noqa: E402

# The store logs loudly on the legacy/corrupt paths by design; keep the
# test output readable.
logging.getLogger('state_store').setLevel(logging.CRITICAL)

# Pin-mask helpers (pin_mask is bits-of-pins-STANDING after the ball)
ALL_DOWN = 0          # strike / spare-completing ball
ALL_UP = 0x3FF        # gutter — all 10 pins still standing
ONE_LEFT = 0x001      # 9 down, head pin still standing
HALF_LEFT = 0x01F     # 5 standing


def assert_eq(actual, expected, msg):
    if actual != expected:
        raise AssertionError(f"FAIL [{msg}]: expected {expected!r}, got {actual!r}")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL [{msg}]")


# ---------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------
def make_single_lane(lane_id=21):
    """Mid-game single lane: 2 bowlers, 4 balls in, DEE mid-frame."""
    ls = LaneScoring(lane_id)
    ls.start(['DEE', 'JAY'])
    ls.record_ball(ALL_DOWN)    # DEE strike -> frame 2, JAY up
    ls.record_ball(ONE_LEFT)    # JAY 9, ball 2 pending
    ls.record_ball(ALL_DOWN)    # JAY spare -> DEE up
    ls.record_ball(HALF_LEFT)   # DEE 5 -> mid-frame, ball 2 pending
    return ls


def make_cross_lane(lane_left=23, lane_right=24):
    """Mid-game cross-lane match: 4 bowlers, 5 balls in, BRIAN mid-frame."""
    cls = CrossLaneScoring(lane_left, lane_right)
    cls.add_bowler("ALICE", number=1, team_id=10, team_name="HOOKS",
                   bowler_id=101, starting_lane=lane_left)
    cls.add_bowler("ANDREW", number=2, team_id=10, team_name="HOOKS",
                   bowler_id=102, starting_lane=lane_left)
    cls.add_bowler("BARB", number=3, team_id=20, team_name="SPLITS",
                   bowler_id=201, starting_lane=lane_right)
    cls.add_bowler("BRIAN", number=4, team_id=20, team_name="SPLITS",
                   bowler_id=202, starting_lane=lane_right)
    cls.start()
    cls.record_ball_for_lane(lane_left, ALL_DOWN)    # ALICE strike -> moves right
    cls.record_ball_for_lane(lane_right, ONE_LEFT)   # BARB 9
    cls.record_ball_for_lane(lane_right, ALL_DOWN)   # BARB spare -> moves left
    cls.record_ball_for_lane(lane_left, HALF_LEFT)   # ANDREW 5
    cls.record_ball_for_lane(lane_right, ALL_UP)     # BRIAN gutter, mid-frame
    return cls


def strip_ts(resp):
    """to_scoring_response embeds datetime.now() — drop it for compares."""
    d = dict(resp)
    d.pop('timestamp', None)
    return d


def read_blob():
    """Raw snapshot blob (lane_id=0 row) from the test DB."""
    with sqlite3.connect(state_store.DB_PATH) as conn:
        row = conn.execute(
            "SELECT state_pickle FROM lane_state WHERE lane_id = ?",
            (state_store._SNAPSHOT_LANE_ID,)).fetchone()
    return row[0] if row else None


def write_blob(blob):
    """Plant an arbitrary snapshot blob (legacy pickle / corruption)."""
    state_store._ensure_schema()
    with sqlite3.connect(state_store.DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lane_state "
            "(lane_id, state_pickle, ball_counter, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (state_store._SNAPSHOT_LANE_ID, blob, 0, time.time()))
        conn.commit()


class fresh_db:
    """Context manager: point state_store at a throwaway temp DB."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = state_store.DB_PATH
        state_store.DB_PATH = Path(self._tmp.name) / 'lane_state_test.db'
        return state_store.DB_PATH

    def __exit__(self, *exc):
        state_store.DB_PATH = self._old
        try:
            self._tmp.cleanup()
        except OSError:
            pass  # Windows can hold the dir briefly; temp dir reaps it
        return False


# ---------------------------------------------------------------
# 1. JSON round-trip
# ---------------------------------------------------------------
def test_json_roundtrip_single_and_cross():
    with fresh_db():
        ls21 = make_single_lane(21)
        cross = make_cross_lane(23, 24)
        lane_scoring = {21: ls21, 23: cross, 24: cross}
        ball_counters = {21: 4, 23: 3, 24: 2}

        state_store.save_lanes(lane_scoring, ball_counters)
        st = state_store.get_save_status()
        assert_true(st['ok'], "save reported ok")

        blob = read_blob()
        assert_eq(blob.lstrip()[:1], b'{', "stored blob is JSON, not pickle")

        loaded, counters = state_store.load_lanes()
        assert_eq(set(loaded), {21, 23, 24}, "all lane keys restored")
        assert_eq(counters, ball_counters, "ball counters restored")

        # Cross-lane object identity preserved (one object, two keys)
        assert_true(loaded[23] is loaded[24],
                    "lanes 23/24 share ONE CrossLaneScoring object")
        assert_true(loaded[21] is not loaded[23],
                    "lane 21 restored as an independent object")

        # Scoring responses deep-equal (modulo embedded timestamp)
        for lid in (21, 23, 24):
            assert_eq(strip_ts(loaded[lid].to_scoring_response(lid)),
                      strip_ts(lane_scoring[lid].to_scoring_response(lid)),
                      f"lane {lid} scoring response identical after restore")

        # Cursor state survives (mid-frame bowler)
        assert_eq(loaded[21].current_bowler_idx, ls21.current_bowler_idx,
                  "single-lane cursor index survives")
        assert_eq(loaded[21].current_bowler.name, ls21.current_bowler.name,
                  "single-lane current bowler survives")
        assert_eq(loaded[21].current_bowler.ball_in_frame,
                  ls21.current_bowler.ball_in_frame,
                  "mid-frame ball_in_frame survives")

        # Cross-lane queues rebuilt in order, referencing the restored bowlers
        for lane in (23, 24):
            assert_eq([b.name for b in loaded[23]._lane_queues[lane]],
                      [b.name for b in cross._lane_queues[lane]],
                      f"lane {lane} queue order survives")
        for q in loaded[23]._lane_queues.values():
            for b in q:
                assert_true(any(b is bb for bb in loaded[23].bowlers),
                            "queue entries reference restored bowler objects")

        # save -> load -> save is byte-stable
        state_store.save_lanes(loaded, counters)
        assert_eq(read_blob(), blob, "re-save of the loaded state is byte-stable")


# ---------------------------------------------------------------
# 2. One-time legacy pickle -> JSON migration
# ---------------------------------------------------------------
def test_legacy_pickle_migrates_to_json_once():
    with fresh_db():
        ls21 = make_single_lane(21)
        cross = make_cross_lane(23, 24)
        legacy = pickle.dumps({
            'lane_scoring': {21: ls21, 23: cross, 24: cross},
            'ball_counters': {21: 4, 23: 3, 24: 2},
        })
        write_blob(legacy)
        assert_true(read_blob().lstrip()[:1] != b'{', "planted blob is pickle")

        loaded, counters = state_store.load_lanes()
        assert_eq(set(loaded), {21, 23, 24}, "legacy pickle state restored")
        assert_eq(counters, {21: 4, 23: 3, 24: 2},
                  "legacy ball counters restored")
        assert_true(loaded[23] is loaded[24],
                    "cross-lane identity preserved through migration")

        # The blob must have been rewritten as versioned JSON immediately
        new_blob = read_blob()
        assert_eq(new_blob.lstrip()[:1], b'{', "blob rewritten as JSON")
        data = json.loads(new_blob.decode('utf-8'))
        assert_eq(data['format'], 'wsl-lane-state', "rewritten format tag")
        assert_eq(data['version'], state_store.STATE_FORMAT_VERSION,
                  "rewritten format version")

        # Second load takes the JSON path and yields identical state
        loaded2, counters2 = state_store.load_lanes()
        assert_eq(counters2, counters, "counters identical on JSON re-load")
        for lid in (21, 23, 24):
            assert_eq(strip_ts(loaded2[lid].to_scoring_response(lid)),
                      strip_ts(loaded[lid].to_scoring_response(lid)),
                      f"lane {lid} identical on JSON re-load")
        assert_eq(read_blob(), new_blob, "no second rewrite on JSON re-load")


# ---------------------------------------------------------------
# 3. Corrupted / unknown blobs -> fresh start, never an exception
# ---------------------------------------------------------------
def test_corrupted_blob_starts_fresh():
    cases = [
        ("garbage pickle-ish bytes",
         b'\x80\x04garbage that is not a valid pickle stream'),
        ("truncated JSON",
         b'{"format": "wsl-lane-state", "version": 1, "objects": ['),
        ("wrong format tag",
         json.dumps({'format': 'someone-elses-db', 'version': 1}).encode()),
        ("future snapshot version",
         json.dumps({'format': 'wsl-lane-state', 'version': 999,
                     'objects': [], 'lanes': {},
                     'ball_counters': {}}).encode()),
        ("unknown lane object kind",
         json.dumps({'format': 'wsl-lane-state',
                     'version': state_store.STATE_FORMAT_VERSION,
                     'objects': [{'kind': 'hovercraft'}],
                     'lanes': {'21': 0},
                     'ball_counters': {}}).encode()),
        ("empty blob", b''),
    ]
    for label, blob in cases:
        with fresh_db():
            write_blob(blob)
            try:
                loaded, counters = state_store.load_lanes()
            except Exception as e:  # noqa: BLE001 — the assertion IS "no raise"
                raise AssertionError(
                    f"FAIL [{label}]: load_lanes raised {type(e).__name__}: {e}")
            assert_eq(loaded, {}, f"{label}: lanes start fresh")
            assert_eq(counters, {}, f"{label}: counters start fresh")

            # And the store still works after the bad load: a save then a
            # clean load must round-trip (server keeps running).
            ls = make_single_lane(21)
            state_store.save_lanes({21: ls}, {21: 4})
            loaded2, counters2 = state_store.load_lanes()
            assert_eq(set(loaded2), {21}, f"{label}: save/load works after corruption")
            assert_eq(counters2, {21: 4}, f"{label}: counters saved after corruption")


def test_missing_db_starts_fresh():
    with fresh_db():
        # No DB file at all (fresh_db only sets the path; nothing wrote it)
        loaded, counters = state_store.load_lanes()
        assert_eq(loaded, {}, "missing DB: lanes start fresh")
        assert_eq(counters, {}, "missing DB: counters start fresh")


# ---------------------------------------------------------------
# 4. H27 completed_games archive survives a restart (review #46)
# ---------------------------------------------------------------
def make_finished_single(lane_id=25):
    """Single lane where game 1 finished (perfect game) and rolled over —
    completed_games holds one archived scoresheet."""
    ls = LaneScoring(lane_id)
    ls.start(['AMY'])
    for _ in range(12):
        ls.record_ball(ALL_DOWN)
    return ls


def make_finished_cross(lane_left=27, lane_right=28):
    cls = CrossLaneScoring(lane_left, lane_right)
    cls.add_bowler('ZOE', starting_lane=lane_left)
    cls.start()
    b = cls.bowlers[0]
    for _ in range(12):
        cls.record_ball_for_lane(b.current_physical_lane, ALL_DOWN)
    return cls


def test_completed_games_survive_roundtrip():
    with fresh_db():
        ls = make_finished_single(25)
        cls = make_finished_cross(27, 28)
        assert_eq(len(ls.completed_games), 1, "single archived one game")
        assert_eq(len(cls.completed_games), 1, "cross archived one game")
        assert_eq(ls.completed_games[0]['players'][0]['current_total'], 300,
                  "archived scoresheet holds the finished score")

        state_store.save_lanes({25: ls, 27: cls, 28: cls}, {})
        loaded, _ = state_store.load_lanes()

        assert_eq(loaded[25].completed_games, ls.completed_games,
                  "single-lane completed_games survive restart")
        assert_eq(loaded[27].completed_games, cls.completed_games,
                  "cross-lane completed_games survive restart")
        assert_eq(loaded[25].game_number, 2, "game_number survives with archive")
        assert_eq(strip_ts(loaded[25].to_scoring_response(25)),
                  strip_ts(ls.to_scoring_response(25)),
                  "scoring response (incl. completed_games) identical")


def test_old_snapshot_without_new_fields_loads_cleanly():
    # A snapshot written BEFORE completed_games / mask_before_synthetic
    # were serialized must load with the defaults ([], False).
    with fresh_db():
        ls = make_finished_single(25)
        state_store.save_lanes({25: ls}, {25: 12})
        blob = read_blob()
        data = json.loads(blob.decode('utf-8'))
        for od in data['objects']:
            od.pop('completed_games', None)
            for bd in od.get('bowlers', []):
                bd.pop('mask_before_synthetic', None)
        write_blob(json.dumps(data).encode('utf-8'))

        loaded, counters = state_store.load_lanes()
        assert_eq(counters, {25: 12}, "old snapshot still loads")
        assert_eq(loaded[25].completed_games, [],
                  "missing completed_games defaults to []")
        assert_eq(loaded[25].bowlers[0].mask_before_synthetic, False,
                  "missing mask_before_synthetic defaults to False")


def test_oversized_completed_games_truncated_on_load():
    # Foreign / hand-edited snapshots can't balloon the in-memory archive:
    # restore keeps only the most recent _COMPLETED_GAMES_MAX entries.
    with fresh_db():
        ls = make_finished_single(25)
        state_store.save_lanes({25: ls}, {})
        data = json.loads(read_blob().decode('utf-8'))
        for od in data['objects']:
            od['completed_games'] = [{'game_number': i, 'players': []}
                                     for i in range(1, 31)]
        write_blob(json.dumps(data).encode('utf-8'))

        loaded, _ = state_store.load_lanes()
        cg = loaded[25].completed_games
        assert_eq(len(cg), state_store._COMPLETED_GAMES_MAX,
                  "oversized archive truncated on load")
        assert_eq(cg[-1]['game_number'], 30, "most recent games kept")
        assert_eq(cg[0]['game_number'],
                  31 - state_store._COMPLETED_GAMES_MAX,
                  "oldest surplus games dropped")


def test_mask_before_synthetic_survives_roundtrip():
    # Review #45: a correction seeds a synthetic (count-only) mask. If the
    # server restarts between the correction and the next ball, the flag
    # must survive or the next camera mask mis-diffs positionally.
    with fresh_db():
        ls = LaneScoring(21)
        ls.start(['DEE'])
        ls.record_ball(0x3E0)                       # 5 down, mid-frame
        r = ls.correct_frame(0, 0, [{'pins_down': 5}])
        assert_true(r['ok'], "in-progress correction applied")
        assert_true(ls.bowlers[0].mask_before_synthetic,
                    "correction seeded a synthetic mask")

        state_store.save_lanes({21: ls}, {21: 1})
        loaded, _ = state_store.load_lanes()
        b = loaded[21].bowlers[0]
        assert_eq(b.mask_before_synthetic, True,
                  "synthetic flag survives restart")
        # The restored engine must diff the next REAL mask by count (3),
        # not against the fictional reconstruction (5 -> bogus spare).
        bowl = b.record_ball(0x300)
        assert_eq(bowl.pins_down, 3, "post-restart ball diffs by count")
        assert_eq(b.frames[0].is_spare, False, "no bogus spare after restart")


# ---------------------------------------------------------------
# Runner
# ---------------------------------------------------------------
TESTS = [
    test_json_roundtrip_single_and_cross,
    test_legacy_pickle_migrates_to_json_once,
    test_corrupted_blob_starts_fresh,
    test_missing_db_starts_fresh,
    test_completed_games_survive_roundtrip,
    test_old_snapshot_without_new_fields_loads_cleanly,
    test_oversized_completed_games_truncated_on_load,
    test_mask_before_synthetic_survives_roundtrip,
]


def main():
    passed = 0
    failed = 0
    for t in TESTS:
        name = t.__name__
        try:
            t()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed += 1

    print()
    print(f"  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
