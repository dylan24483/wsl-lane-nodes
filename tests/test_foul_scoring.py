# FOUL scoring regression (mirror of WSL Systems tests/test_a2_foul_scoring.py).
# A foul counts as a delivery but credits ZERO pins (USBC), respots the rack, and
# is never a strike or spare. Bug: the engine scored the physical pinfall, so a
# fouled 10-count registered as a strike and a ball-2 foul that cleared the deck
# registered as a spare. pin_mask = pins REMAINING after the ball (0 = cleared).
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from wsl_scoring_engine import LaneScoring

CLEARED = 0x000
GUTTER = 0x3FF
FIVE_LEFT = 0x01F

fails = []
def chk(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name + (f'   [{extra}]' if (extra and not cond) else ''))
    if not cond: fails.append(name)

def playf(deliveries):
    ls = LaneScoring(1); ls.start(['Tester'])
    for mask, foul in deliveries:
        ls.record_ball(mask, foul=foul)
    b = ls.current_bowler
    return (b.series_scores[-1] if b.series_scores else b.current_total), b

def gutter_frames(n):
    return [(GUTTER, False), (GUTTER, False)] * n

ls = LaneScoring(1); ls.start(['T'])
ls.record_ball(CLEARED, foul=True)
b = ls.current_bowler
chk('fouled 10-count is NOT a strike', b.frames[0].is_strike is False, b.frames[0].is_strike)
chk('fouled ball credits 0 pins', b.frames[0].bowls[0].pins_down == 0, b.frames[0].bowls[0].pins_down)
ls.record_ball(CLEARED, foul=False)
chk('foul then clearing respotted rack IS a spare', b.frames[0].is_spare is True, b.frames[0].is_spare)

ls2 = LaneScoring(1); ls2.start(['T'])
ls2.record_ball(FIVE_LEFT, foul=False)
ls2.record_ball(CLEARED, foul=True)
chk('ball-2 foul clearing the deck is NOT a spare', ls2.current_bowler.frames[0].is_spare is False)

chk('perfect game still 300 (no regression)', playf([(CLEARED, False)] * 12)[0] == 300)
chk('A: ball-1 foul + spare, rest gutters = 10', playf([(CLEARED, True), (CLEARED, False)] + gutter_frames(9))[0] == 10)
chk('B: a foul credits zero pins (total 0)', playf([(CLEARED, True), (GUTTER, False)] + gutter_frames(9))[0] == 0)
chk('C: ball-2 foul is an open frame, not a spare (total 5)', playf([(FIVE_LEFT, False), (CLEARED, True)] + gutter_frames(9))[0] == 5)
chk('D: foul on the 10th-frame fill ball credits 0 (total 10)',
    playf(gutter_frames(9) + [(FIVE_LEFT, False), (CLEARED, False), (CLEARED, True)])[0] == 10)

print()
print('ALL foul CHECKS PASSED' if not fails else f'{len(fails)} FAILURES: {fails}')
sys.exit(1 if fails else 0)
