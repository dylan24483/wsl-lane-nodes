# A2 verification: max_possible must simulate the REMAINING deliveries from
# the actual frame/ball position. Bug: _max_possible used a fixed 12-ball
# budget (12 - balls_thrown), which is only right for a perfect game — any
# non-strike frame consumes 2 balls, so the simulation was starved of future
# strikes (e.g. 18 gutter balls left ZERO simulated balls for the whole 10th).
# pin_mask = pins REMAINING after the ball (0 = deck cleared).
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from wsl_scoring_engine import LaneScoring

CLEARED = 0x000     # all pins down (strike / spare ball)
GUTTER = 0x3FF      # all 10 still standing -> 0 knocked
FIVE_LEFT = 0x01F   # 5 standing -> ball knocks 5
THREE_LEFT = 0x007  # 3 standing -> ball knocks 7
FOUR_LEFT = 0x00F   # 4 standing -> 6 knocked on a fresh rack

fails = []
def chk(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name + (f'   [{extra}]' if (extra and not cond) else ''))
    if not cond: fails.append(name)

def fresh():
    ls = LaneScoring(1); ls.start(['T'])
    return ls.current_bowler

# --- Fresh game: nothing thrown -> 300 ---
b = fresh()
chk('fresh game max is 300', b.max_possible == 300, b.max_possible)

# --- One strike thrown -> still 300 ---
b = fresh()
b.record_ball(CLEARED)
chk('after 1 strike max is 300', b.max_possible == 300, b.max_possible)

# --- Mid-frame: ball 1 knocks 5 -> best is spare + all strikes = 290 ---
b = fresh()
b.record_ball(FIVE_LEFT)
chk('frame 1 ball 1 = 5 -> max 290 (5/ then 11 strikes)',
    b.max_possible == 290, b.max_possible)

# --- Open frame 1 (5,2 = 7) -> 7 + 8x30 + 30 = 277 (old math said 267) ---
b = fresh()
b.record_ball(FIVE_LEFT)
b.record_ball(FIVE_LEFT & ~0x018)  # knock 2 of the 5 standing -> open 7
chk('open 7 in frame 1 -> max 277', b.max_possible == 277, b.max_possible)

# --- 18 gutter balls (frames 1-9 open) -> 10th alone can still score 30 ---
# Old math: 12 - 18 = negative remaining -> ZERO simulated balls -> max 0.
b = fresh()
for _ in range(9):
    b.record_ball(GUTTER); b.record_ball(GUTTER)
chk('after 9 open-gutter frames max is 30 (the 10th)',
    b.max_possible == 30, b.max_possible)

# --- Ball-1 foul (scored 0, rack respotted) -> spare still possible = 290 ---
b = fresh()
b.record_ball(FIVE_LEFT, foul=True)  # physical 5 down, scored 0
chk('frame 1 ball-1 foul -> max 290 (foul/spare then strikes)',
    b.max_possible == 290, b.max_possible)

# --- 10th frame in progress: 9 strikes then 10th ball 1 = 7 ---
# Best: 7 + 3 + 10 in the 10th -> 210 + 27 + 20 + 20 = 277
b = fresh()
for _ in range(9):
    b.record_ball(CLEARED)
b.record_ball(THREE_LEFT)
chk('9 strikes + 10th ball1=7 -> max 277', b.max_possible == 277, b.max_possible)

# --- 10th: X then 6 -> ball 3 continues the rack, max 4 more -> 286 ---
b = fresh()
for _ in range(9):
    b.record_ball(CLEARED)
b.record_ball(CLEARED)     # 10th ball 1: strike
b.record_ball(FOUR_LEFT)   # 10th ball 2: 6 down, 4 standing
chk('10th X,6 -> max 286 (ball 3 capped at the 4 standing)',
    b.max_possible == 286, b.max_possible)

# --- 10th: spare then fill pending -> fill max 10 ---
# 9 opens of 5 (5,gutter) = 45, then 10th 5/ + best fill 10 -> 45 + 20 = 65
b = fresh()
for _ in range(9):
    b.record_ball(FIVE_LEFT); b.record_ball(GUTTER)
b.record_ball(FIVE_LEFT)   # 10th ball 1: 5
b.record_ball(CLEARED)     # 10th ball 2: spare
chk('open-5 frames + 10th 5/ -> max 65 (fill ball 10)',
    b.max_possible == 65, b.max_possible)

# --- Finished game: max equals the actual final score ---
b = fresh()
for _ in range(10):
    b.record_ball(GUTTER); b.record_ball(GUTTER)
chk('finished all-gutter game -> game over', b.game_over is True, b.game_over)
chk('finished game max equals final total (0)', b.max_possible == 0, b.max_possible)

b = fresh()
for _ in range(12):
    b.record_ball(CLEARED)
chk('perfect game -> max 300 and game over',
    b.max_possible == 300 and b.game_over is True,
    (b.max_possible, b.game_over))

print()
print('ALL A2-maxpossible CHECKS PASSED' if not fails else f'{len(fails)} FAILURES: {fails}')
sys.exit(1 if fails else 0)
