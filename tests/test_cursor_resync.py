# A2 verification: set_frame_bowls must resync the live cursor when it rewrites
# the IN-PROGRESS frame. Before the fix, ball_in_frame / current_frame_idx were
# left stale, so the next real ball landed in the wrong slot (e.g. a 3rd bowl in
# a 2-ball frame) and corrupted subsequent scoring. Correcting a PAST frame must
# still leave the cursor where the bowler actually is.
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from wsl_scoring_engine import LaneScoring

CLEARED = 0x000
GUTTER = 0x3FF
FIVE_LEFT = 0x01F   # ball1 knocks 5

fails = []
def chk(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name + (f'   [{extra}]' if (extra and not cond) else ''))
    if not cond: fails.append(name)

# === A: correct the in-progress frame to COMPLETE -> cursor advances ===
ls = LaneScoring(1); ls.start(['T'])
b = ls.current_bowler
b.record_ball(FIVE_LEFT)                      # frame1 ball1 = 5; cursor: idx0, ball2
b.set_frame_bowls(0, [{'pins_down': 5}, {'pins_down': 3}])  # frame1 -> 5,3 open (complete)
chk('cursor advanced to frame 2 after completing frame 1', b.current_frame_idx == 1, b.current_frame_idx)
chk('ball_in_frame reset to 1', b.ball_in_frame == 1, b.ball_in_frame)
b.record_ball(CLEARED)                        # should be a STRIKE in FRAME 2
chk('next ball landed in frame 2 (2 bowls in frame1, not 3)', len(b.frames[0].bowls) == 2, len(b.frames[0].bowls))
chk('frame 2 recorded the strike', b.frames[1].is_strike is True, b.frames[1].bowls)
chk('frame 1 still totals 8 pins', b.frames[0].bowls[0].pins_down + b.frames[0].bowls[1].pins_down == 8)

# === B: correct in-progress frame, still INCOMPLETE -> cursor stays, mask resync ===
ls2 = LaneScoring(1); ls2.start(['T'])
b2 = ls2.current_bowler
b2.record_ball(FIVE_LEFT)                     # frame1 ball1 = 5
b2.set_frame_bowls(0, [{'pins_down': 7}])     # rewrite ball1 to 7, frame still open
chk('cursor stays on frame 1', b2.current_frame_idx == 0, b2.current_frame_idx)
chk('ball_in_frame points to ball 2', b2.ball_in_frame == 2, b2.ball_in_frame)
b2.record_ball(CLEARED)                       # clear the 3 remaining -> SPARE on ball 2
chk('ball landed as ball 2 (frame1 has exactly 2 bowls)', len(b2.frames[0].bowls) == 2, len(b2.frames[0].bowls))
chk('frame 1 is a spare (7 + 3)', b2.frames[0].is_spare is True, b2.frames[0].is_spare)

# === C: correcting a PAST frame must NOT move the cursor ===
ls3 = LaneScoring(1); ls3.start(['T'])
b3 = ls3.current_bowler
b3.record_ball(CLEARED)                       # frame1 strike -> cursor advances to frame2
b3.record_ball(FIVE_LEFT)                     # frame2 ball1 = 5; cursor idx1, ball2
idx_before, bif_before = b3.current_frame_idx, b3.ball_in_frame
b3.set_frame_bowls(0, [{'pins_down': 9}, {'pins_down': 0}])  # fix the PAST frame 1
chk('correcting a past frame leaves current_frame_idx', b3.current_frame_idx == idx_before, b3.current_frame_idx)
chk('correcting a past frame leaves ball_in_frame', b3.ball_in_frame == bif_before, b3.ball_in_frame)

print()
print('ALL A2-cursor CHECKS PASSED' if not fails else f'{len(fails)} FAILURES: {fails}')
sys.exit(1 if fails else 0)
