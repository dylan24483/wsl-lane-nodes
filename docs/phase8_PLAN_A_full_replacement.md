# Phase 8 — PLAN A: Full Controller Replacement on 21/22 (retire ZOT/Omega-Tek)

**One-line:** the Pi node becomes the pinsetter's complete controller — it retires the ZOT + Omega-Tek boards and runs the machine end to end. This is the zero-EOL-hardware endgame.

**Reality check (from the field dive):** the existing controllers do FAR more than "pulse a cycle." To replace them the Pi must replicate the **entire** control job:
- **Cycle sequencing** (DIELL ball-detect → run the cycle motor)
- **Cam-stop / home detection** (stop the cycle at home ~355-360°; on this machine the manual override runs continuous, so the stop is NOT a simple hardwired motor latch — it's in the controller logic and must be reverse-engineered/replicated)
- **Pin detection** (read the machine's gripper GS / off-spot OS / bin BS sensors)
- **Masking / pindication lights** (drive the overhead pin-indicator display)
- **1st/2nd-ball logic** (PBZ Zero Switch)
- **Foul handling**, scoring, display
- **Safety:** the C.I.S./stop interlock must physically gate the cycle, in hardware, independent of Pi software; NE555 watchdog drops relays on Pi death.

Plus: it's a **hybrid** (Omega-Tek MK Omniboard + ZOT WIZARD + modern relays + Stancor 12/24V) — so the control circuit must be mapped as-built, not from any single manual.

## Hard prerequisite — do NOT reverse-engineer this live
Remote multimeter probing on a live revenue machine (by a beginner) is the wrong tool for mapping a multi-board control circuit. **Plan A requires a controlled bench environment:**
- A **pulled spare board set** and/or a **spare/non-revenue 82-70** to instrument safely, OR strictly-supervised off-hours sessions with the machine locked out.
- Proper gear: scope (not just a multimeter) to catch the cam/cycle timing + control pulses; the ZOT + Omega-Tek manuals (have them); patience.

## Phases
- **A0 — Acquire + bench-instrument** a spare board set / spare machine. Map the full control circuit: how DIELL triggers a cycle, how the cam/home stops it, how pin-detect feeds masking, the 1st/2nd-ball + foul logic, and where the safety interlock sits. Output: as-built control schematic for THIS hybrid.
- **A1 — Redesign the control model** (the `cycle_control.py` "pulse SS" model is void — no SS switch; DIELL is the trigger and the stop is controller-logic). New model: read DIELL → drive cycle motor → detect home (cam) → stop; + pin-detect read + masking drive + ball-state + foul.
- **A2 — Build the controller** (daemon): cycle + cam-stop + pin-detect + masking + sequencing + safety + watchdog. Bench-validate on the spare with simulated + real sensor I/O.
- **A3 — Interface hardware:** AEDIKO drives the motor/power; opto reads DIELL/foul/cam/pin-sensors; outputs to masking lights; hardware interlock in series. Enclosure.
- **A4 — Off-live validation** on 21/22 (Omega-Tek/ZOT disconnected but retained for rollback): every cycle + safety case, 50-100 unattended cycles.
- **A5 — Cutover + soak**, rollback = reconnect the old boards.

## Timeline & risk
- **Timeline:** months (full controls project, gated on acquiring a bench specimen + scope-level reverse-engineering).
- **Risk:** HIGH — safety-critical (a mistimed cycle can wreck the machine or injure someone), complex hybrid, and the controls reverse-engineering is beyond beginner multimeter work. Mitigated ONLY by bench-first development + hardware interlocks + watchdog + off-live validation.

## Pros / Cons
- **Pros:** achieves the Phase 8 thesis (zero EOL hardware — retires the aging ZOT/Omega-Tek/VDB stack); one unified Pi node owns the lane.
- **Cons:** big, slow, safety-critical; needs a bench specimen + better instrumentation + skills ramp; high consequence of error on a revenue lane.

## Recommended sequencing even if you choose A
Do **Plan B first anyway** (scoring pilot — days, low risk, delivers value, proves the node) and run Plan A as a parallel, deliberate, bench-based track. Plan B's running system + machine knowledge directly de-risk Plan A. They are not mutually exclusive; B is the on-ramp to A.

## Decision factors (choose A now if…)
- Retiring the EOL controller boards is urgent (e.g., they're failing / unobtainable).
- You can get a spare board / spare machine + scope and treat this as a months-long bench project.
- You're prepared to own the machine's safety-critical real-time control.
