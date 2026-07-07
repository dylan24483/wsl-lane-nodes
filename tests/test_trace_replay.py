"""Pytest wiring for the trace-replay tripwire (2026-06-27 review finding 49).

The goldens in tests/fixtures/trace_*.json are CHECKED-IN recordings of the 8270
FSM's control-output sequence; replay_fixture() re-runs each event timeline
through the live CycleController and asserts the outputs still match. This file
exists so the tripwire actually runs under pytest — trace_replay's __main__
selftest only runs when executed by hand.

A MISSING golden must FAIL, never regenerate: writing a fresh golden from the
live FSM and then verifying the FSM against it is a guaranteed self-blessing
pass. If you deliberately intend to re-freeze current FSM behavior, run:
    py -3 lane_node/trace_replay.py --write

Run standalone with:
    py -3 tests/test_trace_replay.py
"""
import os
import sys

# Make lane_node modules importable when running from anywhere
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lane_node')))

import trace_replay


def test_fixtures_present():
    missing = [n for n in trace_replay._BUILDERS
               if not (trace_replay.FIXTURES / f"trace_{n}.json").exists()]
    assert not missing, (
        f"missing golden fixture(s) {missing} in {trace_replay.FIXTURES}; goldens "
        f"are checked in — do NOT auto-regenerate (self-blessing pass). If the "
        f"re-freeze is deliberate: py -3 lane_node/trace_replay.py --write")


def test_replay_first_ball_respot():
    trace_replay.replay_fixture("first_ball_respot")


def test_replay_strike():
    trace_replay.replay_fixture("strike")


def test_replay_foul():
    trace_replay.replay_fixture("foul")


def test_replay_deterministic():
    doc = trace_replay.load_fixture("strike")
    _, io1 = trace_replay.replay(doc["events"])
    _, io2 = trace_replay.replay(doc["events"])
    assert io1.outputs == io2.outputs, "replay is not deterministic"


if __name__ == "__main__":
    test_fixtures_present()
    test_replay_first_ball_respot()
    test_replay_strike()
    test_replay_foul()
    test_replay_deterministic()
    print("trace_replay pytest wiring OK (all fixtures present + replayed)")
