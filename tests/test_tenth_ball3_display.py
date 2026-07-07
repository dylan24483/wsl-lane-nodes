# A2 verification: corrected 10th-frame ball-3 display symbols. Bug in
# set_frame_bowls: ball 3 completing ball 2's remainder showed the digit
# ('6' / '4' instead of '/'), and a 10 thrown at a full deck left by a
# gutter/fouled ball 2 leaked a literal '10'. Rules now mirror record_ball:
# all ten on this ball = X, completing the pair to 10 = /, else digit/-.
import os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from wsl_scoring_engine import LaneScoring

fails = []
def chk(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name + (f'   [{extra}]' if (extra and not cond) else ''))
    if not cond: fails.append(name)

def corrected_tenth(balls):
    """Fresh bowler; rewrite the 10th via set_frame_bowls. Returns (res, frame)."""
    ls = LaneScoring(1); ls.start(['T'])
    b = ls.current_bowler
    res = b.set_frame_bowls(9, balls)
    return res, b.frames[9]

def displays(frame):
    return [bw.display for bw in frame.bowls]

# --- X, 6, 4: ball 3 completes ball 2's remainder -> '/' (was '6'-style digit bug) ---
res, f = corrected_tenth([{'pins_down': 10}, {'pins_down': 6}, {'pins_down': 4}])
chk('X,6,4 accepted', res['ok'], res.get('error'))
chk("X,6,4 -> ['X','6','/']", displays(f) == ['X', '6', '/'], displays(f))
chk('X,6,4 frame pins total 20', f.total_pins_this_frame == 20, f.total_pins_this_frame)
chk('X,6,4 does not set is_spare (10th spare = balls 1+2 only)',
    f.is_spare is False, f.is_spare)

# --- X, X, X: triple in the 10th ---
res, f = corrected_tenth([{'pins_down': 10}, {'pins_down': 10}, {'pins_down': 10}])
chk("X,X,X -> ['X','X','X']", res['ok'] and displays(f) == ['X', 'X', 'X'], displays(f))

# --- X, X, 7: fresh rack after double -> digit ---
res, f = corrected_tenth([{'pins_down': 10}, {'pins_down': 10}, {'pins_down': 7}])
chk("X,X,7 -> ['X','X','7']", res['ok'] and displays(f) == ['X', 'X', '7'], displays(f))

# --- 7, 3, 10: spare then a strike on the fill ball ---
res, f = corrected_tenth([{'pins_down': 7}, {'pins_down': 3}, {'pins_down': 10}])
chk("7,3,10 -> ['7','/','X']", res['ok'] and displays(f) == ['7', '/', 'X'], displays(f))

# --- 7, 3, 5: spare then a 5 fill -> digit ---
res, f = corrected_tenth([{'pins_down': 7}, {'pins_down': 3}, {'pins_down': 5}])
chk("7,3,5 -> ['7','/','5']", res['ok'] and displays(f) == ['7', '/', '5'], displays(f))

# --- X, 0, 10: gutter leaves the full deck; clearing it is X, NEVER '10' ---
res, f = corrected_tenth([{'pins_down': 10}, {'pins_down': 0}, {'pins_down': 10}])
chk("X,0,10 -> ['X','-','X'] (no literal '10')",
    res['ok'] and displays(f) == ['X', '-', 'X'], displays(f))
chk("no bowl anywhere displays '10'", all(d != '10' for d in displays(f)), displays(f))

# --- X, 6, 0: nothing on ball 3 -> '-' ---
res, f = corrected_tenth([{'pins_down': 10}, {'pins_down': 6}, {'pins_down': 0}])
chk("X,6,0 -> ['X','6','-']", res['ok'] and displays(f) == ['X', '6', '-'], displays(f))

# --- 7, 3, foul: foul always shows 'F' regardless of pins ---
res, f = corrected_tenth([{'pins_down': 7}, {'pins_down': 3},
                          {'pins_down': 0, 'foul': True}])
chk("7,3,F -> ['7','/','F']", res['ok'] and displays(f) == ['7', '/', 'F'], displays(f))

# --- Sanity: the same sequences via record_ball produce the same symbols ---
def played_tenth(deliveries):
    """deliveries: list of (mask, foul) applied after 9 open gutter frames."""
    ls = LaneScoring(1); ls.start(['T'])
    b = ls.current_bowler
    GUTTER = 0x3FF
    for _ in range(9):
        b.record_ball(GUTTER); b.record_ball(GUTTER)
    for mask, foul in deliveries:
        b.record_ball(mask, foul)
    return b.frames[9]

# X (mask 0), 6 down (4 standing = 0x00F), then clear those 4 (mask 0)
f = played_tenth([(0x000, False), (0x00F, False), (0x000, False)])
chk("record_ball X,6,4 also shows ['X','6','/'] (corrections mirror live play)",
    displays(f) == ['X', '6', '/'], displays(f))

print()
print('ALL A2-ball3-display CHECKS PASSED' if not fails else f'{len(fails)} FAILURES: {fails}')
sys.exit(1 if fails else 0)
