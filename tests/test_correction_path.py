# Correction-path regression tests (Fable review findings 15/16/17/18/47).
#
# set_frame_bowls / correct_frame must mirror record_ball's foul semantics
# (a foul SCORES zero and respots the rack — USBC), reject frames the bowler
# hasn't reached, never un-end a finished game on an incomplete past-frame
# correction, and roll the lane over (archive + new game) when a correction
# ends the last active game.
#
# Wire contract: correction `pins_down` is the PHYSICAL pinfall of the ball,
# matching what Bowl.to_dict emits, so an untouched resave is lossless.
#
# pytest-style on purpose (run: py -m pytest tests/test_correction_path.py):
# the sibling script-style tests call sys.exit at import and cannot be
# collected by pytest — run those directly with `py tests/<file>.py`.
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from wsl_scoring_engine import BowlerGame, CrossLaneScoring, LaneScoring

CLEARED = 0x000    # all 10 down
GUTTER = 0x3FF     # none down
FIVE_LEFT = 0x01F  # 5 standing -> ball 1 knocked 5


def single(name='T'):
    ls = LaneScoring(1)
    ls.start([name])
    return ls, ls.current_bowler


def gutter_frames(bowler, n):
    for _ in range(n):
        bowler.record_ball(GUTTER)
        bowler.record_ball(GUTTER)


def displays(frame):
    return [bw.display for bw in frame.bowls]


def bowl_dicts(frame):
    """to_dict per bowl, minus the `modified` audit flag (corrections set it)."""
    out = []
    for bw in frame.bowls:
        d = bw.to_dict()
        d.pop('modified', None)
        out.append(d)
    return out


# ------------------------------------------------------------------
# Finding 15 — correcting a frame containing a foul scores eff=0
# ------------------------------------------------------------------
def test_corrected_foul_scores_zero():
    ls, b = single()
    b.record_ball(FIVE_LEFT)
    b.record_ball(GUTTER)  # frame 1 = 5,0 (miscored; the 3 was really a foul)
    r = ls.correct_frame(0, 0, [{'pins_down': 3, 'foul': True}, {'pins_down': 5}])
    assert r['ok'], r.get('error')
    f = b.frames[0]
    assert f.bowls[0].pins_down == 0          # scored pinfall zeroed
    assert f.bowls[0].pin_map != 0x3FF        # physical 3-count kept in pin_map
    assert f.total_pins_this_frame == 5
    assert f.score == 5                       # USBC: foul credits nothing
    assert displays(f) == ['F', '5']


def test_corrected_foul_respot_validation():
    # foul-6 then 8 is physically legal (foul respots the full rack) — the
    # old raw-pins sum check rejected it with 'Balls 1+2 pins > 10'.
    ls, b = single()
    b.record_ball(FIVE_LEFT)
    b.record_ball(GUTTER)
    r = ls.correct_frame(0, 0, [{'pins_down': 6, 'foul': True}, {'pins_down': 8}])
    assert r['ok'], r.get('error')
    assert b.frames[0].score == 8
    # ...but WITHOUT the foul the same counts are still impossible
    r2 = ls.correct_frame(0, 0, [{'pins_down': 6}, {'pins_down': 8}])
    assert not r2['ok']
    assert '> 10' in r2['error']


def test_corrected_foul_is_never_a_mark():
    # fouled 10-count is NOT a strike: ball 2 must be allowed in frames 1-9
    ls, b = single()
    b.record_ball(FIVE_LEFT)
    b.record_ball(GUTTER)
    r = ls.correct_frame(0, 0, [{'pins_down': 10, 'foul': True}, {'pins_down': 7}])
    assert r['ok'], r.get('error')
    f = b.frames[0]
    assert f.is_strike is False
    assert f.is_spare is False
    assert f.score == 7
    # ball-2 foul clearing the deck is NOT a spare (eff 7+0)
    r2 = ls.correct_frame(0, 0, [{'pins_down': 7}, {'pins_down': 3, 'foul': True}])
    assert r2['ok'], r2.get('error')
    assert b.frames[0].is_spare is False
    assert b.frames[0].score == 7
    # ...while foul then clearing the respotted rack IS a spare (eff 0+10)
    r3 = ls.correct_frame(0, 0, [{'pins_down': 4, 'foul': True}, {'pins_down': 10}])
    assert r3['ok'], r3.get('error')
    assert b.frames[0].is_spare is True
    assert displays(b.frames[0]) == ['F', '/']


def test_corrected_foul_does_not_inflate_bonus():
    # strike in frame 1; correcting frame 2 to [4F, 5] must feed bonus 0+5,
    # not 4+5 (the old code double-counted via raw pins_down)
    ls, b = single()
    b.record_ball(CLEARED)      # frame 1 strike
    b.record_ball(FIVE_LEFT)
    b.record_ball(GUTTER)       # frame 2 = 5,0
    r = ls.correct_frame(0, 1, [{'pins_down': 4, 'foul': True}, {'pins_down': 5}])
    assert r['ok'], r.get('error')
    assert b.frames[0].score == 15   # 10 + (0 + 5)
    assert b.frames[1].score == 20


def test_corrected_tenth_foul_entitlement():
    # 10th: fouled 10-count earns no 3rd ball unless ball 2 spares it (eff).
    # BowlerGame directly — a LaneScoring correction completing the last
    # game triggers the finding-47 rollover and wipes the frame under test.
    bg = BowlerGame(1, 'T')
    for _ in range(18):
        bg.record_ball(GUTTER)   # frames 1-9 open gutters
    bg.record_ball(FIVE_LEFT)
    bg.record_ball(GUTTER)       # open 10th, game over
    # eff 0 + 3 -> no mark -> 3rd ball must be rejected
    r = bg.set_frame_bowls(9, [{'pins_down': 10, 'foul': True},
                               {'pins_down': 3}, {'pins_down': 5}])
    assert not r['ok']
    assert '3rd ball' in r['error']
    # eff 0 + 10 -> spare -> 3rd ball allowed; scores 0 + 10 + 7 = 17
    r2 = bg.set_frame_bowls(9, [{'pins_down': 10, 'foul': True},
                                {'pins_down': 10}, {'pins_down': 7}])
    assert r2['ok'], r2.get('error')
    assert bg.frames[9].total_pins_this_frame == 17
    assert displays(bg.frames[9]) == ['F', '/', '7']
    assert bg.game_over is True


# ------------------------------------------------------------------
# Finding 16 — fouled 10-count round-trip (to_dict -> correction) is lossless
# ------------------------------------------------------------------
def test_fouled_ten_untouched_resave_is_lossless():
    ls, b = single()
    b.record_ball(CLEARED, foul=True)   # fouled 10-count (physical 10, scored 0)
    b.record_ball(FIVE_LEFT)            # respotted rack, 5 knocked
    before = bowl_dicts(b.frames[0])
    score_before = b.frames[0].score
    payload = [{'pins_down': d['pins_down'], 'foul': d['foul']} for d in before]
    assert payload[0] == {'pins_down': 10, 'foul': True}  # JSON stays physical
    r = ls.correct_frame(0, 0, payload)
    assert r['ok'], r.get('error')
    assert bowl_dicts(b.frames[0]) == before   # pin_map/display/foul identical
    assert b.frames[0].score == score_before == 5
    assert b.frames[0].is_strike is False
    assert len(b.frames[0].bowls) == 2         # ball 2 not sliced away


def test_fouled_ten_in_progress_resave_keeps_respot_cursor():
    # fouled 10-count with ball 2 still pending: resave must leave the bowler
    # on ball 2 facing a respotted full rack
    ls, b = single()
    b.record_ball(CLEARED, foul=True)
    r = ls.correct_frame(0, 0, [{'pins_down': 10, 'foul': True}])
    assert r['ok'], r.get('error')
    assert b.current_frame_idx == 0
    assert b.ball_in_frame == 2
    assert b.mask_before_ball == 0x3FF
    b.record_ball(CLEARED)   # clears the respotted rack -> spare (eff 0+10)
    assert b.frames[0].is_spare is True


# ------------------------------------------------------------------
# Finding 17 — future-frame corrections are rejected
# ------------------------------------------------------------------
def test_future_frame_correction_rejected():
    ls, b = single()
    b.record_ball(FIVE_LEFT)   # bowler is on frame 1
    r = ls.correct_frame(0, 5, [{'pins_down': 7}, {'pins_down': 2}])
    assert not r['ok']
    assert 'frame 6' in r['error']
    assert b.frames[5].bowls == []   # frame untouched
    # ...and a later real ball still lands in the right place
    b.record_ball(GUTTER)
    assert b.current_frame_idx == 1
    assert len(b.frames[0].bowls) == 2


def test_current_and_past_frame_corrections_still_allowed():
    ls, b = single()
    b.record_ball(CLEARED)     # frame 1 strike -> cursor on frame 2
    b.record_ball(FIVE_LEFT)   # frame 2 ball 1
    assert ls.correct_frame(0, 0, [{'pins_down': 9}, {'pins_down': 1}])['ok']  # past
    assert ls.correct_frame(0, 1, [{'pins_down': 7}])['ok']                    # current
    assert not ls.correct_frame(0, 2, [{'pins_down': 7}])['ok']                # future


def test_future_frame_correction_rejected_cross_lane():
    cls = CrossLaneScoring(21, 22)
    cls.add_bowler('T')
    cls.start()
    cls.record_ball_for_lane(21, FIVE_LEFT)
    r = cls.correct_frame(0, 5, [{'pins_down': 7}, {'pins_down': 2}])
    assert not r['ok']
    assert cls.bowlers[0].frames[5].bowls == []


# ------------------------------------------------------------------
# Finding 18 — incomplete past-frame correction must not un-end the game
# ------------------------------------------------------------------
def test_incomplete_past_frame_correction_keeps_game_over():
    bg = BowlerGame(1, 'T')
    for _ in range(20):
        bg.record_ball(GUTTER)   # full game of open gutters
    assert bg.game_over is True
    r = bg.set_frame_bowls(3, [{'pins_down': 4}])   # operator saves ball 1 only
    assert r['ok'], r.get('error')
    assert bg.frames[9].score is None       # cascade blocks the running total
    assert bg.game_over is True             # ...but the game stays ENDED
    assert bg.record_ball(GUTTER) is None   # stray ball is dropped, no phantom
    assert len(bg.frames[9].bowls) == 2
    # finishing the correction resolves the sheet without re-ending anything
    r2 = bg.set_frame_bowls(3, [{'pins_down': 4}, {'pins_down': 5}])
    assert r2['ok'], r2.get('error')
    assert bg.frames[9].score == 9
    assert bg.game_over is True


def test_rewriting_tenth_itself_incomplete_still_unends():
    # The legit un-end path must survive: correcting the 10th ITSELF to an
    # incomplete state re-opens the game for the missing ball(s).
    bg = BowlerGame(1, 'T')
    for _ in range(20):
        bg.record_ball(GUTTER)
    assert bg.game_over is True
    r = bg.set_frame_bowls(9, [{'pins_down': 5}])
    assert r['ok'], r.get('error')
    assert bg.game_over is False
    bowl = bg.record_ball(GUTTER)            # ball 2 of the reopened 10th
    assert bowl is not None and bowl.num == 2
    assert bg.game_over is True              # open 10th complete again


def test_mid_game_past_correction_does_not_end_game():
    ls, b = single()
    gutter_frames(b, 4)   # bowler on frame 5
    r = ls.correct_frame(0, 1, [{'pins_down': 4}, {'pins_down': 5}])
    assert r['ok']
    assert b.game_over is False
    assert b.current_frame_idx == 4


def test_finished_bowler_stays_finished_in_rotation():
    # Multi-bowler: A done, B behind. Correcting A's past frame to 1 ball must
    # not re-enter A into the rotation; the next ball belongs to B.
    ls = LaneScoring(1)
    ls.start(['A', 'B'])
    a, bb = ls.bowlers
    for _ in range(9):                      # rounds 1-9: two gutters each
        for _ in range(4):
            ls.record_ball(GUTTER)
    ls.record_ball(GUTTER)
    ls.record_ball(GUTTER)                  # A's open 10th -> A game over
    assert a.game_over and not bb.game_over
    r = ls.correct_frame(0, 3, [{'pins_down': 4}])   # incomplete past frame
    assert r['ok']
    assert a.game_over is True
    ls.record_ball(GUTTER)                  # must be B's 10th ball 1
    assert len(a.frames[9].bowls) == 2      # no phantom ball in A's closed 10th
    assert len(bb.frames[9].bowls) == 1
    # finish A's correction, then B — the archive must be clean
    assert ls.correct_frame(0, 3, [{'pins_down': 4}, {'pins_down': 5}])['ok']
    ls.record_ball(GUTTER)                  # B's open 10th -> all done -> rollover
    assert ls.game_number == 2
    assert len(ls.completed_games) == 1
    archived = {p['name']: p['current_total'] for p in ls.completed_games[0]['players']}
    assert archived == {'A': 9, 'B': 0}


# ------------------------------------------------------------------
# Finding 47 — a correction ending the last game rolls over + archives
# ------------------------------------------------------------------
def test_correction_ending_last_game_rolls_over():
    ls, b = single()
    gutter_frames(b, 9)
    b.record_ball(FIVE_LEFT)   # 10th ball 1 = 5; camera missed ball 2
    r = ls.correct_frame(0, 9, [{'pins_down': 5}, {'pins_down': 2}])
    assert r['ok'], r.get('error')
    assert ls.game_number == 2                    # rolled over
    assert len(ls.completed_games) == 1           # H27 archive captured
    assert ls.completed_games[0]['game_number'] == 1
    assert b.series_scores == [7]
    assert b.game_over is False                   # fresh game
    bowl = ls.record_ball(CLEARED)                # lane is alive again
    assert bowl is not None
    assert b.frames[0].is_strike is True


def test_correction_ending_last_game_rolls_over_cross_lane():
    cls = CrossLaneScoring(21, 22)
    cls.add_bowler('T', starting_lane=21)
    cls.start()
    b = cls.bowlers[0]
    for _ in range(9):
        lane = b.current_physical_lane
        cls.record_ball_for_lane(lane, GUTTER)
        cls.record_ball_for_lane(lane, GUTTER)
    cls.record_ball_for_lane(b.current_physical_lane, FIVE_LEFT)  # 10th ball 1
    r = cls.correct_frame(0, 9, [{'pins_down': 5}, {'pins_down': 2}])
    assert r['ok'], r.get('error')
    assert cls.game_number == 2
    assert len(cls.completed_games) == 1
    assert b.series_scores == [7]
    # queues rebuilt: the bowler is live again on their starting lane
    assert cls.current_bowler_for_lane(21) is b
    assert cls.record_ball_for_lane(21, GUTTER) is not None


def test_correction_not_ending_game_does_not_roll_over():
    ls, b = single()
    gutter_frames(b, 3)   # bowler on frame 4
    r = ls.correct_frame(0, 1, [{'pins_down': 4}, {'pins_down': 5}])
    assert r['ok']
    assert ls.game_number == 1
    assert ls.completed_games == []
