"""Bench tests for Phase 7 cross-lane scoring (wsl-lane-nodes mirror).

Exercises CrossLaneScoring's per-frame lane-flip behavior in isolation
(no Flask, no Pi, no HTTP) so regressions surface in a few seconds
instead of mid-league-night.

Run with:
    py -3 tests/test_cross_lane.py

Identical to the wsl-systems copy at tests/test_cross_lane.py — keep
them in sync when wsl_scoring_engine.py changes in either repo.
"""

import os
import sys

# Make wsl_scoring_engine importable when running from tests/ dir
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from wsl_scoring_engine import CrossLaneScoring


# ---------------------------------------------------------------
# Pin-mask helpers (pin_mask is bits-of-pins-STANDING after the ball)
# ---------------------------------------------------------------
ALL_DOWN = 0          # strike — no pins standing
ALL_UP = 0x3FF        # gutter — all 10 pins still standing
ONE_LEFT = 0x001      # 9 down, head pin still standing
HALF_LEFT = 0x01F     # 5 standing (any half-rack value works for "open frame")


def assert_eq(actual, expected, msg):
    if actual != expected:
        raise AssertionError(f"FAIL [{msg}]: expected {expected!r}, got {actual!r}")


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(f"FAIL [{msg}]")


# ---------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------
def make_match(lane_left=21, lane_right=22):
    """Build a 4-bowler match: 2 per team, team1 on left, team2 on right."""
    cls = CrossLaneScoring(lane_left, lane_right)
    cls.add_bowler("ALICE",   number=1, team_id=10, team_name="HOOKS",  bowler_id=101,
                   starting_lane=lane_left)
    cls.add_bowler("ANDREW",  number=2, team_id=10, team_name="HOOKS",  bowler_id=102,
                   starting_lane=lane_left)
    cls.add_bowler("BARB",    number=3, team_id=20, team_name="SPLITS", bowler_id=201,
                   starting_lane=lane_right)
    cls.add_bowler("BRIAN",   number=4, team_id=20, team_name="SPLITS", bowler_id=202,
                   starting_lane=lane_right)
    cls.start()
    return cls


# ---------------------------------------------------------------
# Tests
# ---------------------------------------------------------------
def test_initial_state():
    cls = make_match()
    assert_eq(cls.current_bowler_for_lane(21).name, "ALICE", "L21 first up is ALICE")
    assert_eq(cls.current_bowler_for_lane(22).name, "BARB",  "L22 first up is BARB")
    assert_true(cls.is_active, "match should be active after start()")
    assert_eq(cls.game_number, 1, "starts on game 1")


def test_strike_advances_to_other_lane():
    cls = make_match()
    cls.record_ball_for_lane(21, ALL_DOWN, foul=False)
    assert_eq(cls.current_bowler_for_lane(21).name, "ANDREW",
              "after Alice strike, Andrew up on L21")
    assert_eq(cls.current_bowler_for_lane(22).name, "BARB",
              "Barb still up on L22 after Alice's strike on L21")
    alice = [b for b in cls.bowlers if b.name == "ALICE"][0]
    assert_eq(alice.current_physical_lane, 22, "Alice moved to lane 22 after strike")


def test_open_frame_ball_1_stays_then_ball_2_advances():
    cls = make_match()
    cls.record_ball_for_lane(21, HALF_LEFT, foul=False)
    assert_eq(cls.current_bowler_for_lane(21).name, "ALICE",
              "Alice still up after open ball 1")
    cls.record_ball_for_lane(21, ALL_DOWN, foul=False)
    assert_eq(cls.current_bowler_for_lane(21).name, "ANDREW",
              "Andrew up after Alice's open frame closes")
    alice = [b for b in cls.bowlers if b.name == "ALICE"][0]
    assert_eq(alice.current_physical_lane, 22, "Alice moved to L22 after open frame")


def test_frame_10_strike_stays_on_same_lane_through_fills():
    cls = CrossLaneScoring(21, 22)
    cls.add_bowler("ALICE", number=1, starting_lane=21)
    cls.start()
    alice = cls.bowlers[0]

    for _ in range(9):
        cls.record_ball_for_lane(alice.current_physical_lane, ALL_DOWN, foul=False)

    assert_eq(alice.current_frame_idx, 9, "Alice in frame 10 (idx 9) after 9 strikes")
    lane_for_10th = alice.current_physical_lane

    cls.record_ball_for_lane(lane_for_10th, ALL_DOWN, foul=False)
    assert_eq(alice.current_physical_lane, lane_for_10th,
              "10th-frame ball 1 strike: Alice stays on same lane")
    assert_eq(cls.game_number, 1, "still game 1 after 10th ball 1")

    cls.record_ball_for_lane(lane_for_10th, ALL_DOWN, foul=False)
    assert_eq(alice.current_physical_lane, lane_for_10th,
              "10th-frame ball 2 strike: Alice stays on same lane")
    assert_eq(cls.game_number, 1, "still game 1 after 10th ball 2")

    cls.record_ball_for_lane(lane_for_10th, ALL_DOWN, foul=False)
    assert_eq(cls.game_number, 2,
              "after 10th-frame ball 3: game advances to 2 (single bowler)")
    assert_eq(alice.current_frame_idx, 0, "Alice reset to frame 1 in game 2")
    assert_eq(alice.current_physical_lane, alice.starting_physical_lane,
              "Alice back to starting lane in game 2")


def test_all_bowlers_finished_triggers_new_game():
    cls = make_match()
    safety = 0
    while cls.game_number < 2:
        safety += 1
        if safety > 200:
            raise AssertionError(
                f"safety break — game stuck at {cls.game_number}, "
                f"frames: {[b.current_frame_idx for b in cls.bowlers]}")
        for lane in (21, 22):
            bw = cls.current_bowler_for_lane(lane)
            if bw is not None and not bw.game_over:
                cls.record_ball_for_lane(lane, ALL_DOWN, foul=False)
                break

    assert_eq(cls.game_number, 2, "advanced to game 2 after all done")
    for b in cls.bowlers:
        assert_true(not b.game_over, f"{b.name} reset for game 2 (game_over False)")
        assert_eq(b.current_frame_idx, 0, f"{b.name} back to frame 1 in game 2")
        assert_eq(b.current_physical_lane, b.starting_physical_lane,
                  f"{b.name} back to starting lane {b.starting_physical_lane}")

    alice = [b for b in cls.bowlers if b.name == "ALICE"][0]
    assert_eq(alice.team_id, 10, "Alice team_id preserved")
    assert_eq(alice.team_name, "HOOKS", "Alice team_name preserved")
    assert_eq(alice.bowler_id, 101, "Alice bowler_id preserved")
    assert_eq(len(alice.series_scores), 1, "Alice has 1 game in series after game 1 ends")


def test_ball_on_empty_lane_returns_none():
    cls = make_match()
    barb  = [b for b in cls.bowlers if b.name == "BARB"][0]
    brian = [b for b in cls.bowlers if b.name == "BRIAN"][0]
    barb.game_over = True
    brian.game_over = True
    cls._lane_queues[22] = []

    bowl = cls.record_ball_for_lane(22, ALL_DOWN, foul=False)
    assert_eq(bowl, None, "ball on empty lane returns None")


def test_to_scoring_response_view_lane_id():
    cls = make_match()
    resp_left  = cls.to_scoring_response(view_lane_id=21)
    resp_right = cls.to_scoring_response(view_lane_id=22)
    assert_eq(resp_left['current_bowler'],  "ALICE", "L21 view current_bowler = ALICE")
    assert_eq(resp_right['current_bowler'], "BARB",  "L22 view current_bowler = BARB")
    assert_eq(resp_left['active_bowlers']['21'], "ALICE", "active_bowlers[21] = ALICE")
    assert_eq(resp_left['active_bowlers']['22'], "BARB",  "active_bowlers[22] = BARB")
    assert_eq(resp_left['mode'], 'cross_lane', "mode is cross_lane")


def test_players_dict_includes_phase7_fields():
    cls = make_match()
    resp = cls.to_scoring_response(view_lane_id=21)
    alice = [p for p in resp['players'] if p['name'] == 'ALICE'][0]
    assert_eq(alice['team_id'], 10, "team_id flows to dict")
    assert_eq(alice['team_name'], 'HOOKS', "team_name flows to dict")
    assert_eq(alice['bowler_id'], 101, "bowler_id flows to dict")
    assert_eq(alice['current_physical_lane'], 21, "current_physical_lane flows to dict")
    assert_eq(alice['starting_physical_lane'], 21, "starting_physical_lane flows to dict")
    assert_true(alice['is_current'], "Alice is is_current on L21 view")


# ---------------------------------------------------------------
# Runner
# ---------------------------------------------------------------
TESTS = [
    test_initial_state,
    test_strike_advances_to_other_lane,
    test_open_frame_ball_1_stays_then_ball_2_advances,
    test_frame_10_strike_stays_on_same_lane_through_fills,
    test_all_bowlers_finished_triggers_new_game,
    test_ball_on_empty_lane_returns_none,
    test_to_scoring_response_view_lane_id,
    test_players_dict_includes_phase7_fields,
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
