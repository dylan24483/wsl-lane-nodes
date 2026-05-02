"""
WSL Scoring Engine — Pure Python Bowling Scorer
=================================================
Westside Lanes · Chehalis, WA

Replaces ConquerorServer's Score.dll with a standalone Python implementation.
Accepts 10-bit pin masks per ball (from BPP_LANE via vdb.py), tracks frame
state, computes running totals with bonus handling, and outputs JSON in the
exact same structure as the .NET Remoting sidecar's /lane/N/scoring endpoint.

Pin mask encoding (QubicaAMF standard):
  - 10-bit value, pins REMAINING (1 = still standing, 0 = knocked down)
  - Bit 0 = pin 1 (headpin), Bit 1 = pin 2, ... Bit 9 = pin 10
  - 0    = strike (all down)
  - 1023 = gutter (none down)
  - Mask after ball 2: only remaining pins from ball 1 can still be standing

Pin layout (standard 10-pin):
       7   8   9  10        bit positions: 6  7  8  9
         4   5   6                          3  4  5
           2   3                             1  2
             1                                0

Author: Dylan DeYoung / The DeYoung Group
Date: April 2026
"""

from datetime import datetime
from typing import List, Optional, Dict, Any

# ============================================================
# PIN GEOMETRY (for split detection)
# ============================================================
# Adjacency map: pin N -> set of pins adjacent to N
# Two pins are adjacent if they touch in the triangle layout.
PIN_ADJACENT = {
    1:  {2, 3},
    2:  {1, 3, 4, 5},
    3:  {1, 2, 5, 6},
    4:  {2, 5, 7, 8},
    5:  {2, 3, 4, 6, 8, 9},
    6:  {3, 5, 9, 10},
    7:  {4, 8},
    8:  {4, 5, 7, 9},
    9:  {5, 6, 8, 10},
    10: {6, 9},
}


def mask_to_standing(mask: int) -> List[int]:
    """Convert 10-bit mask to list of standing pin numbers (1-10)."""
    return [p + 1 for p in range(10) if mask & (1 << p)]


def pins_down(mask: int) -> int:
    """Count pins knocked down (0 standing bits)."""
    return 10 - bin(mask & 0x3FF).count('1')


def pins_down_between(mask_before: int, mask_after: int) -> int:
    """Count pins knocked down between two masks (ball 2+)."""
    # Pins that were standing before but not after
    newly_down = mask_before & ~mask_after & 0x3FF
    return bin(newly_down).count('1')


def is_split(mask: int) -> bool:
    """
    Detect if remaining pins form a split.
    Split = headpin (pin 1) is DOWN, and remaining pins form 2+ disconnected groups.
    """
    standing = mask_to_standing(mask)
    if not standing or len(standing) < 2:
        return False
    # Headpin must be down for it to be a split
    if 1 in standing:
        return False

    # BFS connectivity check on standing pins
    visited = set()
    queue = [standing[0]]
    visited.add(standing[0])
    standing_set = set(standing)

    while queue:
        pin = queue.pop(0)
        for adj in PIN_ADJACENT.get(pin, set()):
            if adj in standing_set and adj not in visited:
                visited.add(adj)
                queue.append(adj)

    return len(visited) < len(standing)


# ============================================================
# FRAME / BOWL DATA STRUCTURES
# ============================================================
class Bowl:
    """Single ball delivery."""
    __slots__ = ('num', 'pin_map', 'pins_down', 'display', 'foul', 'split', 'modified')

    def __init__(self, num: int, pin_map: int, pins_knocked: int,
                 display: str = '', foul: bool = False, split: bool = False):
        self.num = num
        self.pin_map = pin_map
        self.pins_down = pins_knocked
        self.display = display
        self.foul = foul
        self.split = split
        self.modified = False

    def to_dict(self) -> Dict[str, Any]:
        mask = self.pin_map & 0x3FF
        standing = mask_to_standing(mask)
        return {
            'num': self.num,
            'display': self.display,
            'pin_map': self.pin_map,
            'pin_map_bin': format(mask, '010b'),
            'pins_standing': len(standing),
            'pins_down': 10 - len(standing),
            'standing_pins': standing,
            'foul': self.foul,
            'split': self.split,
            'modified': self.modified,
        }


class Frame:
    """Single frame (1-10) for a bowler."""
    __slots__ = ('number', 'bowls', 'score', 'is_complete', 'is_strike', 'is_spare')

    def __init__(self, number: int):
        self.number = number
        self.bowls: List[Bowl] = []
        self.score: Optional[int] = None  # Running total (None = not yet computable)
        self.is_strike = False
        self.is_spare = False
        self.is_complete = False

    @property
    def ball_count(self) -> int:
        return len(self.bowls)

    @property
    def first_ball_down(self) -> int:
        return self.bowls[0].pins_down if self.bowls else 0

    @property
    def total_pins_this_frame(self) -> int:
        return sum(b.pins_down for b in self.bowls)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'frame': self.number,
            'points': self.score if self.score is not None else 0,
            'incomplete': self.score is None,
            'bowls': [b.to_dict() for b in self.bowls],
        }


# ============================================================
# BOWLER STATE
# ============================================================
class BowlerGame:
    """Complete scoring state for one bowler in one game."""

    def __init__(self, number: int, name: str, hdcp: int = 0,
                 average: float = 0.0):
        self.number = number
        self.name = name
        self.hdcp = hdcp
        self.average = average
        self.frames: List[Frame] = [Frame(i + 1) for i in range(10)]
        self.current_frame_idx = 0  # 0-based index into self.frames
        self.ball_in_frame = 1  # 1 or 2 (or 3 in 10th)
        self.mask_before_ball = 0x3FF  # All pins standing at start of frame
        self.game_over = False
        # Speed tracking (populated externally if available)
        self.speed_ball1 = 0
        self.speed_ball2 = 0
        # Series tracking
        self.game_number = 1
        self.series_scores: List[int] = []  # Previous game totals

    @property
    def current_frame(self) -> Frame:
        return self.frames[self.current_frame_idx]

    @property
    def current_total(self) -> int:
        """Current running score (last computed frame score)."""
        for i in range(9, -1, -1):
            if self.frames[i].score is not None:
                return self.frames[i].score
        return 0

    @property
    def current_total_with_hdcp(self) -> int:
        return self.current_total + self.hdcp

    @property
    def prog_scratch(self) -> int:
        """Progressive scratch total across series."""
        return sum(self.series_scores) + self.current_total

    @property
    def prog_with_hdcp(self) -> int:
        return self.prog_scratch + self.hdcp * (len(self.series_scores) + 1)

    @property
    def max_possible(self) -> int:
        """Maximum possible score from current position."""
        return _max_possible(self.frames, self.current_frame_idx)

    @property
    def strike_count(self) -> int:
        return sum(1 for f in self.frames if f.is_strike)

    @property
    def spare_count(self) -> int:
        return sum(1 for f in self.frames if f.is_spare)

    @property
    def spare_conversion_pct(self) -> float:
        """Spare conversion percentage (spares / non-strike frames with 2+ balls)."""
        attempts = sum(1 for f in self.frames
                       if not f.is_strike and f.ball_count >= 2 and f.number <= 10)
        if attempts == 0:
            return 0.0
        conversions = sum(1 for f in self.frames
                          if f.is_spare and f.number <= 10)
        return round(conversions / attempts * 100, 1)

    def record_ball(self, pin_mask: int, foul: bool = False) -> Optional[Bowl]:
        """
        Record a single ball delivery.

        Args:
            pin_mask: 10-bit mask of pins REMAINING after the ball
            foul: True if foul line was crossed

        Returns:
            Bowl object, or None if game is over
        """
        if self.game_over:
            return None

        mask = pin_mask & 0x3FF
        frame = self.current_frame
        is_tenth = frame.number == 10

        # Calculate pins knocked down this ball
        if self.ball_in_frame == 1:
            knocked = 10 - bin(mask).count('1')
            self.mask_before_ball = 0x3FF  # Full rack
        else:
            knocked = pins_down_between(self.mask_before_ball, mask)

        # Determine display character
        if foul:
            display = 'F'
        elif self.ball_in_frame == 1 and knocked == 10:
            display = 'X'
        elif not is_tenth and self.ball_in_frame == 2 and mask == 0:
            display = '/'
        elif is_tenth and self.ball_in_frame >= 2 and mask == 0:
            # 10th frame: spare or strike on fill balls
            if self.ball_in_frame == 2 and not frame.is_strike:
                display = '/'
            elif knocked == 10:
                display = 'X'
            else:
                display = '/'
        elif knocked == 0:
            display = '-'
        else:
            display = str(knocked)

        # Detect split (only on ball 1, after first delivery)
        split = False
        if self.ball_in_frame == 1 and knocked > 0 and knocked < 10:
            split = is_split(mask)

        bowl = Bowl(
            num=self.ball_in_frame,
            pin_map=mask,
            pins_knocked=knocked,
            display=display,
            foul=foul,
            split=split,
        )
        frame.bowls.append(bowl)

        # --- Frame completion logic ---
        if is_tenth:
            self._handle_tenth_frame(frame, mask, knocked, bowl)
        else:
            self._handle_normal_frame(frame, mask, knocked, bowl)

        # Recalculate running scores
        self._recalc_scores()

        return bowl

    def _handle_normal_frame(self, frame: Frame, mask: int, knocked: int, bowl: Bowl):
        """Handle frame advancement for frames 1-9."""
        if self.ball_in_frame == 1:
            if knocked == 10:
                # Strike
                frame.is_strike = True
                frame.is_complete = True
                self.current_frame_idx += 1
                self.ball_in_frame = 1
                self.mask_before_ball = 0x3FF
            else:
                # Not a strike, go to ball 2
                self.ball_in_frame = 2
                self.mask_before_ball = mask
        elif self.ball_in_frame == 2:
            if mask == 0:
                frame.is_spare = True
            frame.is_complete = True
            self.current_frame_idx += 1
            self.ball_in_frame = 1
            self.mask_before_ball = 0x3FF

    def _handle_tenth_frame(self, frame: Frame, mask: int, knocked: int, bowl: Bowl):
        """Handle the 10th frame (up to 3 balls)."""
        bc = frame.ball_count  # After appending bowl

        if bc == 1:
            if knocked == 10:
                frame.is_strike = True
                self.ball_in_frame = 2
                self.mask_before_ball = 0x3FF  # Reset pins for ball 2
            else:
                self.ball_in_frame = 2
                self.mask_before_ball = mask
        elif bc == 2:
            if frame.is_strike:
                # Had strike on ball 1
                if knocked == 10:
                    # Double in 10th
                    self.ball_in_frame = 3
                    self.mask_before_ball = 0x3FF
                else:
                    self.ball_in_frame = 3
                    self.mask_before_ball = mask
            else:
                # No strike on ball 1
                if mask == 0:
                    # Spare
                    frame.is_spare = True
                    self.ball_in_frame = 3
                    self.mask_before_ball = 0x3FF  # Reset for fill ball
                else:
                    # Open frame in 10th — game over, no fill ball
                    frame.is_complete = True
                    self.game_over = True
        elif bc == 3:
            frame.is_complete = True
            self.game_over = True

    def _recalc_scores(self):
        """Recalculate all running frame scores with bonus logic."""
        running = 0
        for i, frame in enumerate(self.frames):
            if not frame.bowls:
                break

            if frame.number < 10:
                base = frame.total_pins_this_frame

                if frame.is_strike:
                    bonus = self._get_bonus_balls(i, 2)
                    if bonus is None:
                        frame.score = None
                        continue
                    running += 10 + bonus
                elif frame.is_spare:
                    bonus = self._get_bonus_balls(i, 1)
                    if bonus is None:
                        frame.score = None
                        continue
                    running += 10 + bonus
                else:
                    if not frame.is_complete:
                        frame.score = None
                        continue
                    running += base

                frame.score = running
            else:
                # 10th frame: just sum all pins (no bonus from future frames)
                running += frame.total_pins_this_frame
                frame.score = running

    def _get_bonus_balls(self, frame_idx: int, count: int) -> Optional[int]:
        """
        Get total pins for the next `count` balls after the given frame.
        Returns None if those balls haven't been thrown yet.
        """
        bonus = 0
        remaining = count
        for i in range(frame_idx + 1, 10):
            f = self.frames[i]
            for bowl in f.bowls:
                bonus += bowl.pins_down
                remaining -= 1
                if remaining == 0:
                    return bonus
            if remaining > 0 and f.is_complete:
                continue  # Frame done, keep looking
            if remaining > 0 and not f.bowls:
                return None  # Not thrown yet

        return None if remaining > 0 else bonus

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to sidecar-compatible JSON structure."""
        return {
            'number': self.number,
            'name': self.name,
            'hdcp': self.hdcp,
            'average': round(self.average, 1),
            'current_total': self.current_total_with_hdcp,
            'prog_scratch': self.prog_scratch,
            'prog_with_hdcp': self.prog_with_hdcp,
            'speed_ball1': self.speed_ball1,
            'speed_ball2': self.speed_ball2,
            'frames': [f.to_dict() for f in self.frames if f.bowls],
            'frame_history': {
                'total': len(self.series_scores) + 1,
                'last_fpf': self.current_total,
            },
        }

    # ------------------------------------------------------------------
    # MANUAL CORRECTION — used by desk staff to fix miscored frames.
    # ------------------------------------------------------------------
    # The VDB sensor misreads pin-fall occasionally (sticky pin, camera
    # flare, rolling pin). When that happens we need a way to rewrite a
    # specific frame's bowls without disturbing the rest of the game state
    # or the VDB poller (which only appends on rising-edge ball-detect,
    # so a server-side edit survives until the next real ball is thrown).
    #
    # The pin_map we reconstruct is topologically arbitrary — we only know
    # pins_down counts, not which specific pins remain — so split detection
    # on corrected balls may be wrong. `Bowl.modified = True` tags each
    # corrected bowl so reports can distinguish manual fixes from auto
    # scores. If a league needs split-accurate corrections, operator
    # should enter pin-maps explicitly (future enhancement).
    def set_frame_bowls(self, frame_idx: int, bowls_data):
        """Rewrite one frame's bowls. bowls_data is a list of dicts:
        [{'pins_down': 0-10, 'foul': bool?}]. Returns {ok, error?, frame?}.

        Does NOT move current_frame_idx — correcting frame 3 while the
        bowler is on frame 7 keeps the bowler on frame 7."""
        if frame_idx < 0 or frame_idx >= len(self.frames):
            return {'ok': False, 'error': f'frame_idx {frame_idx} out of range (0-9)'}
        if not bowls_data:
            return {'ok': False, 'error': 'bowls cannot be empty'}

        frame = self.frames[frame_idx]
        is_tenth = frame.number == 10

        # Normalize + pin-count validation
        norm = []
        for i, bd in enumerate(bowls_data):
            try:
                p = int(bd.get('pins_down', 0))
            except (TypeError, ValueError):
                return {'ok': False, 'error': f'Ball {i+1}: pins_down must be an integer'}
            if p < 0 or p > 10:
                return {'ok': False, 'error': f'Ball {i+1}: pins_down must be 0-10 (got {p})'}
            norm.append({'pins_down': p, 'foul': bool(bd.get('foul', False))})

        # Frame-shape validation
        if is_tenth:
            if len(norm) < 1 or len(norm) > 3:
                return {'ok': False, 'error': '10th frame needs 1-3 balls'}
            # 10th frame: ball 2 only limited by ball 1 if ball 1 wasn't a strike
            if len(norm) >= 2 and norm[0]['pins_down'] != 10:
                if norm[0]['pins_down'] + norm[1]['pins_down'] > 10:
                    return {'ok': False, 'error':
                            f"Balls 1+2 pins ({norm[0]['pins_down']}+{norm[1]['pins_down']}) > 10"}
            # 3 balls require strike on ball 1 OR spare on balls 1+2
            if len(norm) == 3:
                ball1_strike = norm[0]['pins_down'] == 10
                balls12_spare = (not ball1_strike) and (norm[0]['pins_down'] + norm[1]['pins_down'] == 10)
                if not (ball1_strike or balls12_spare):
                    return {'ok': False,
                            'error': '10th frame 3rd ball only allowed after strike or spare'}
            # Ball 3 pins validation: depends on state after balls 1-2
            if len(norm) == 3:
                b3 = norm[2]['pins_down']
                if norm[0]['pins_down'] == 10 and norm[1]['pins_down'] != 10:
                    # Strike → fresh rack for ball 2. Ball 3 continues from ball-2 state.
                    if norm[1]['pins_down'] + b3 > 10:
                        return {'ok': False, 'error': f"10th frame ball 3 ({b3}) + ball 2 ({norm[1]['pins_down']}) > 10"}
        else:
            if len(norm) < 1 or len(norm) > 2:
                return {'ok': False, 'error': 'Frames 1-9 need 1-2 balls'}
            if norm[0]['pins_down'] == 10 and len(norm) > 1:
                return {'ok': False, 'error': 'No 2nd ball after strike in frames 1-9'}
            if len(norm) == 2 and norm[0]['pins_down'] + norm[1]['pins_down'] > 10:
                return {'ok': False,
                        'error': f"Balls 1+2 pins ({norm[0]['pins_down']}+{norm[1]['pins_down']}) > 10"}

        # Rebuild the frame. We reconstruct a plausible pin_map for each
        # bowl — this is topologically arbitrary (we don't know which
        # specific pins are left) but preserves pins_down counts.
        frame.bowls = []
        frame.is_strike = False
        frame.is_spare = False
        frame.is_complete = False
        frame.score = None

        for i, bd in enumerate(norm):
            pins = bd['pins_down']
            foul = bd['foul']

            # Compute pin_map: after a fresh rack, knocking `pins` pins
            # leaves a mask with (10 - pins) low bits set. After continuing
            # from a previous bowl, knock `pins` pins off the previous
            # remaining mask.
            fresh_rack = (
                i == 0
                or (is_tenth and frame.is_strike and i == 1)
                or (is_tenth and i == 2 and frame.bowls[-1].display in ('/', 'X'))
            )
            if fresh_rack:
                mask = 0 if pins == 10 else ((1 << (10 - pins)) - 1)
            else:
                prev_mask = frame.bowls[-1].pin_map
                new_mask = prev_mask
                to_knock = pins
                for bit in range(10):
                    if to_knock == 0:
                        break
                    if new_mask & (1 << bit):
                        new_mask &= ~(1 << bit)
                        to_knock -= 1
                mask = new_mask

            # Display + strike/spare detection
            if foul:
                display = 'F'
            elif i == 0 and pins == 10:
                display = 'X'
                frame.is_strike = True
            elif i == 1 and not frame.is_strike and pins > 0 and mask == 0:
                display = '/'
                frame.is_spare = True
            elif is_tenth and i == 1 and frame.is_strike:
                display = 'X' if pins == 10 else ('-' if pins == 0 else str(pins))
            elif is_tenth and i == 2:
                # Ball 3 — fresh rack if ball 2 was strike/spare, else continues
                if frame.bowls[-1].display in ('X', '/') and pins == 10:
                    display = 'X'
                elif fresh_rack and pins > 0 and mask == 0:
                    display = '/'
                else:
                    display = '-' if pins == 0 else str(pins)
            elif pins == 0:
                display = '-'
            else:
                display = str(pins)

            bowl = Bowl(num=i + 1, pin_map=mask, pins_knocked=pins,
                        display=display, foul=foul)
            bowl.modified = True
            frame.bowls.append(bowl)

        # Frame completion
        if is_tenth:
            if len(frame.bowls) == 3:
                frame.is_complete = True
            elif len(frame.bowls) == 2:
                # 2-ball completion only when no strike on ball 1 and no
                # spare on balls 1+2
                ball1_strike = frame.bowls[0].display == 'X'
                ball2_spare = (not ball1_strike) and (frame.bowls[0].pins_down + frame.bowls[1].pins_down == 10)
                if not ball1_strike and not ball2_spare:
                    frame.is_complete = True
        else:
            if len(frame.bowls) == 1 and frame.is_strike:
                frame.is_complete = True
            elif len(frame.bowls) == 2:
                frame.is_complete = True

        # Recalculate all running scores (this frame may now feed strike/spare
        # bonuses into earlier frames, or have its own bonus resolved)
        self._recalc_scores()
        # Update game_over based on 10th frame completion — a correction
        # that un-completes the 10th un-ends the game.
        self.game_over = bool(self.frames[9].is_complete
                              and self.frames[9].score is not None)
        return {'ok': True, 'frame': frame.to_dict()}


# ============================================================
# MAX POSSIBLE SCORE CALCULATOR
# ============================================================
def _max_possible(frames: List[Frame], current_idx: int) -> int:
    """Calculate the maximum possible score from current game state."""
    # Simulate: fill remaining balls with strikes
    sim_balls = []
    for f in frames:
        for b in f.bowls:
            sim_balls.append(b.pins_down)

    # How many more balls can be thrown?
    total_balls_possible = 12  # max in a perfect game
    # Count balls already thrown
    thrown = len(sim_balls)
    remaining = total_balls_possible - thrown

    # Quick check: if all strikes possible
    future_balls = [10] * remaining
    all_balls = sim_balls + future_balls

    # Score the full sequence
    return _score_ball_sequence(all_balls)


def _score_ball_sequence(balls: List[int]) -> int:
    """Score a complete ball sequence (for max possible calc)."""
    score = 0
    bi = 0  # ball index

    for frame_num in range(1, 11):
        if bi >= len(balls):
            break

        if frame_num < 10:
            if balls[bi] == 10:
                # Strike
                b1 = balls[bi + 1] if bi + 1 < len(balls) else 0
                b2 = balls[bi + 2] if bi + 2 < len(balls) else 0
                score += 10 + b1 + b2
                bi += 1
            else:
                b1 = balls[bi]
                b2 = balls[bi + 1] if bi + 1 < len(balls) else 0
                if b1 + b2 == 10:
                    # Spare
                    b3 = balls[bi + 2] if bi + 2 < len(balls) else 0
                    score += 10 + b3
                else:
                    score += b1 + b2
                bi += 2
        else:
            # 10th frame: sum up to 3 balls
            for _ in range(3):
                if bi < len(balls):
                    score += balls[bi]
                    bi += 1
    return score


# ============================================================
# LANE STATE MANAGER
# ============================================================
class LaneScoring:
    """
    Manages scoring state for a single lane.
    Tracks multiple bowlers and their games.
    """

    def __init__(self, lane_id: int):
        self.lane_id = lane_id
        self.bowlers: List[BowlerGame] = []
        self.current_bowler_idx = 0
        self.game_number = 1
        self.is_active = False
        self.started_at: Optional[str] = None

    def add_bowler(self, name: str, number: int = 0, hdcp: int = 0,
                   average: float = 0.0) -> BowlerGame:
        if number == 0:
            number = len(self.bowlers) + 1
        bg = BowlerGame(number, name, hdcp, average)
        bg.game_number = self.game_number
        self.bowlers.append(bg)
        return bg

    def start(self, bowler_names: List[str] = None):
        """Start a new game with optional bowler list."""
        self.is_active = True
        self.started_at = datetime.now().isoformat()
        if bowler_names:
            for i, name in enumerate(bowler_names):
                self.add_bowler(name, number=i + 1)

    @property
    def current_bowler(self) -> Optional[BowlerGame]:
        if not self.bowlers:
            return None
        return self.bowlers[self.current_bowler_idx]

    def record_ball(self, pin_mask: int, foul: bool = False) -> Optional[Bowl]:
        """
        Record a ball for the current bowler and advance turn.
        Returns the Bowl, or None if all games are complete.
        """
        bowler = self.current_bowler
        if bowler is None or bowler.game_over:
            # Current bowler done — skip to next non-finished bowler
            self._advance_to_next_active()
            bowler = self.current_bowler
            if bowler is None or bowler.game_over:
                return None

        # Snapshot state BEFORE the ball
        frame_before = bowler.current_frame_idx
        ball_before = bowler.ball_in_frame

        bowl = bowler.record_ball(pin_mask, foul)

        # Determine if the bowler's turn for this frame is done.
        # Turn is done when:
        #   - The frame index advanced (strike in frames 1-9)
        #   - The game ended (10th frame complete)
        #   - Ball 2 was thrown in a non-strike frame (frame completed, idx advanced)
        frame_after = bowler.current_frame_idx
        turn_done = (frame_after != frame_before) or bowler.game_over

        if turn_done:
            self._advance_bowler()

        return bowl

    def correct_frame(self, bowler_idx: int, frame_idx: int, bowls_data):
        """Wrap BowlerGame.set_frame_bowls for desk corrections. Returns the
        same shape as set_frame_bowls: {ok, error?, frame?}."""
        if bowler_idx < 0 or bowler_idx >= len(self.bowlers):
            return {'ok': False,
                    'error': f'bowler_idx {bowler_idx} out of range (0-{len(self.bowlers)-1})'}
        return self.bowlers[bowler_idx].set_frame_bowls(frame_idx, bowls_data)

    def _advance_to_next_active(self):
        """Skip past any game-over bowlers to find the next active one."""
        if not self.bowlers:
            return
        start = self.current_bowler_idx
        for _ in range(len(self.bowlers)):
            self.current_bowler_idx = (self.current_bowler_idx + 1) % len(self.bowlers)
            if not self.bowlers[self.current_bowler_idx].game_over:
                return
        # All done
        self.current_bowler_idx = start

        return bowl

    def _advance_bowler(self):
        """Move to the next bowler, or start new game if all done."""
        self.current_bowler_idx = (self.current_bowler_idx + 1) % len(self.bowlers)

        # Check if all bowlers have finished the game
        if all(b.game_over for b in self.bowlers):
            self._start_new_game()

    def _start_new_game(self):
        """All bowlers finished — start a new game in the series."""
        self.game_number += 1
        for b in self.bowlers:
            b.series_scores.append(b.current_total)
            # Reset for new game
            old_number = b.number
            old_name = b.name
            old_hdcp = b.hdcp
            old_avg = b.average
            old_series = b.series_scores
            old_speeds = (b.speed_ball1, b.speed_ball2)

            b.__init__(old_number, old_name, old_hdcp, old_avg)
            b.series_scores = old_series
            b.game_number = self.game_number
            b.speed_ball1, b.speed_ball2 = old_speeds

        self.current_bowler_idx = 0

    def to_scoring_response(self) -> Dict[str, Any]:
        """
        Build the same JSON response as sidecar /lane/N/scoring.
        """
        total_strikes = sum(b.strike_count for b in self.bowlers)
        total_spares = sum(b.spare_count for b in self.bowlers)
        total_gutters = sum(
            1 for b in self.bowlers
            for f in b.frames
            for bowl in f.bowls
            if bowl.pin_map == 0x3FF
        )

        return {
            'ok': True,
            'lane': self.lane_id,
            'timestamp': datetime.now().isoformat(),
            'open': self.is_active,
            'game': self.game_number,
            'players': [b.to_dict() for b in self.bowlers],
            'stats': {
                'strikes': total_strikes,
                'spares': total_spares,
                'gutters': total_gutters,
            },
        }


# ============================================================
# BPP_LANE PARSER
# ============================================================
def parse_bpp_lane_ball_event(sector_data: bytes) -> Optional[Dict]:
    """
    Parse a BPP_LANE sector for ball event data.

    The normal status page (0x00/0x0f00) returns:
      byte[6]: flags — 0x60 = idle, 0xC0 = ball detected (bit 7)

    Args:
        sector_data: 512-byte sector from read_page(vdb, sect, 0x00, b'\\x0f\\x00')

    Returns:
        dict with 'ball_detected' bool and raw data, or None if invalid
    """
    if not sector_data or len(sector_data) < 16:
        return None

    flags = sector_data[6]
    ball_detected = bool(flags & 0x80)

    return {
        'ball_detected': ball_detected,
        'flags': flags,
        'raw_first16': sector_data[:16].hex(),
    }


def parse_bpp_lane_pin_mask(mask_data: bytes) -> Optional[int]:
    """
    Parse MASK1_U pin data from read_page(vdb, sect, 0x00, b'\\x00\\x88').

    When MASK1_U is present:
      bytes[18:25] = b'MASK1_U'
      bytes[8:10]  = first pin mask pair (little-endian uint16)

    The 10-bit pin mask is in the lower 10 bits.

    Returns:
        10-bit pin mask (pins remaining), or None if no valid data
    """
    if not mask_data or len(mask_data) < 25:
        return None

    if mask_data[18:25] != b'MASK1_U':
        return None

    # Pin mask is a little-endian uint16 at offset 8
    raw = mask_data[8] | (mask_data[9] << 8)
    return raw & 0x3FF
