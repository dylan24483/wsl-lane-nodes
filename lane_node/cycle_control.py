#!/usr/bin/env python3
"""VOID / SUPERSEDED — do NOT use, do NOT import, do NOT graft into the daemon.

This module's "SS-pulse" cycle model (one momentary trigger runs exactly one
self-sequencing cycle) was DISPROVEN against the AMF 82-70 service manual: the
82-70 has NO one-pulse-per-cycle trigger. The controller must DRIVE the sweep
and table motors and read CAM switches for position, de-energizing each motor at
its target degree — an event-driven FSM, not a pulse.

The live model is `cycle_control_8270.py` (same directory). See also:
  docs/phase8_8270_SYSTEM_REFERENCE.md   (authoritative sequence/cams/I-O/safety)
  docs/manual_src/03_machine-sequence.md (declares this draft void)

The original draft (including its passing-but-wrong simulator) is preserved in
git history — `git log --follow lane_node/cycle_control.py`. It is removed from
the working tree so a runnable simulator attached to a disproven machine model
cannot sit in the safety-critical source tree inviting reuse.
"""

raise RuntimeError(
    "lane_node/cycle_control.py is VOID: the 'SS-pulse' one-pulse-per-cycle model "
    "was disproven against the AMF 82-70 manuals. Use cycle_control_8270.py "
    "(event-driven cam FSM) instead. See docs/phase8_8270_SYSTEM_REFERENCE.md."
)
