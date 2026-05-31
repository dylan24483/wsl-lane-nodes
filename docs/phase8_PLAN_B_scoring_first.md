# Phase 8 — PLAN B: Scoring-First on 21/22 (defer controller replacement)

**One-line:** Pi replaces the VDB scoring + overhead display on lanes 21/22. The machine keeps cycling on its existing ZOT/Omega-Tek controllers — we don't touch machine control at all. Read-only, reversible, fast.

**Why this is the recommended near-term path:** the field dive showed the existing controllers do the *entire* machine job (cycle + cam-stop + pin detection + masking lights + ball-state). Replacing all of that is a big controls project (Plan A). Meanwhile the one thing scoring needs — the **DIELL ball-detect — is already fully characterized** (~16V rest / 0.7V broken, NPN active-low), and the machine cycles itself fine. So we can deliver a working pilot in days, prove the whole Pi-node + scoring + display chain in prod, and bank knowledge toward Plan A later.

## What the Pi does
- **Read DIELL ball-detect** (done — tap the 16V/0.7V signal wire → opto → GPIO, active-low). "A ball was thrown."
- **Read foul** (tap the foul-lamp wire — cleaner than the 5V logic harble; TBD which wire).
- **Get pin counts**, choose one:
  - **B1 (start here): manual mode** — `WSL_LANE_SCORING_MODE=manual` (already the default). Pi detects the ball; desk operator enters pins. Zero pin-sensing needed. Fastest, safest first cut.
  - **B2 (later): auto** — add pin detection via our own T-Camera (Phase 8a plan; needs PIN_SPOTS calibration), or tap the existing masking/pin-detect data.
- **Compute scores** (wsl_scoring_engine — built) and **serve to desk + a new overhead display** (Phase 8b proxy + display — built).

## What we DO NOT touch
Cycle, motor, contactors, cam, masking lights, the ZOT/Omega-Tek controllers. The machine runs exactly as it does today. **No watchdog needed** (no machine control). Fully reversible: unplug the read taps.

## Work items
1. Tap **DIELL ball-detect** read (signal wire → opto → Pi GPIO; daemon Button active-low). Per lane, both beams.
2. Tap **foul** (find the foul-lamp wire; opto/level-shift → GPIO).
3. **Mount the Pi** at 21/22 + power (PoE) + network — pull Cat6 (task #14), mount NETGEAR switch.
4. Wire reads into the Pi enclosure (lightweight — no AEDIKO/cycle drive needed for B1).
5. Bring up scoring in **manual mode**; confirm ball-detect → frame advance on the desk + new display.
6. **Soak** under real play; monitor scoring accuracy + uptime. Rollback = unplug taps (VDB still present).
7. (B2, later) Add pin-detect (T-Camera) for auto-scoring.

## Timeline & risk
- **Timeline:** days to ~1 week (uses already-built code; read-only wiring).
- **Risk:** LOW. Read-only, reversible, no machine-control responsibility, no safety-critical path. The machine's own controller + safety stay intact.

## Pros / Cons
- **Pros:** fast value (kills the EOL VDB scoring + display now); safe + reversible; proves the Pi-node architecture in prod; builds machine knowledge for Plan A; needs almost nothing new (DIELL read is done).
- **Cons:** does NOT retire the aging ZOT/Omega-Tek controllers yet — that's deferred to a later phase. Auto pin-scoring (B2) still needs the T-Camera.

## What this leaves for "someday" (Plan A territory)
Full controller replacement (retire ZOT/Omega-Tek) — tackled later, deliberately, with bench reverse-engineering. Plan B does not block Plan A; it de-risks it (running system + more knowledge first).

## Decision factors (choose B if…)
- You want a working, revenue-safe pilot on 21/22 soon.
- You're not comfortable doing live controls reverse-engineering as a beginner right now.
- Retiring the controller boards is a "nice eventually," not an urgent need (they work today).
