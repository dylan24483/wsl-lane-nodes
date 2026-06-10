# A2 verification: the 10th-frame running score must NOT be displayed while an
# earlier frame is still unresolved. Bug: _recalc_scores `continue`d past an
# unresolved strike/spare frame, so the 10th printed a cumulative that silently
# skipped it. Fix cascades None to every later frame until the blocker resolves.
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

ls = LaneScoring(1); ls.start(['T'])
b = ls.current_bowler
# frames 1-8: open gutters (0 pins each)
for _ in range(8):
    b.record_ball(GUTTER); b.record_ball(GUTTER)
# frame 9: strike (awaits two bonus balls)
b.record_ball(CLEARED)
# frame 10 ball 1: knock 5 -> only ONE bonus ball exists for frame 9 yet
b.record_ball(FIVE_LEFT)

chk('frame 9 (strike) is unresolved -> score None', b.frames[8].score is None, b.frames[8].score)
chk('frame 10 does NOT print a total skipping the unresolved 9th (None)',
    b.frames[9].score is None, b.frames[9].score)

# frame 10 ball 2: clear the rack -> spare. Now frame 9 has its 2 bonus balls.
b.record_ball(CLEARED)
chk('frame 9 now resolves to 20 (10 + bonus 5+5)', b.frames[8].score == 20, b.frames[8].score)
chk('frame 10 cumulative now includes frame 9 (30)', b.frames[9].score == 30, b.frames[9].score)
chk('game not over yet (10th-frame fill ball pending)', b.game_over is False, b.game_over)

print()
print('ALL A2-prem10 CHECKS PASSED' if not fails else f'{len(fails)} FAILURES: {fails}')
sys.exit(1 if fails else 0)
