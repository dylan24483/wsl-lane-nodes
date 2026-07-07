# Machine Test Session — Field Guide (post-review remaining reads)

Covers everything left that needs the machine: **Part 1** cold quick wins (GS8, GP) · **Part 2** the POWERED interlock characterization (redesign doc §4 — this is what unblocks your A/B/C decision) · **Part 3** optional same-session powered cam mapping + front-end class. Written 2026-07-07; reads-with `phase8_interlock_redesign.md` §4 and the metering guide's measured record.

**The safety trick that makes Part 2/3 easy: UNPLUG THE MOTORS.** The machine has per-motor **disconnect plugs** (labeled on the svc p29 / p15 diagrams, near the Russell-Stoll main plug at the back). With the S (sweep) and T (table) motor plugs separated, the **control circuits stay live** — contactors still pull in and click — but **nothing on the machine can move.** Every powered answer we need lives in the *coil/control* domain, not the motor domain, so you can take every reading with the mechanism dead. Verify before starting: press manual Sweep for a half-second — you should hear the contactor **click** but see **no motion**.

## Tools
DMM with **LoZ** mode (kills ghost AC readings — use LoZ for every powered voltage read) · back-probe pins · the ~25 ft clip lead · 2 small **spring clamps or clothespins** (to hold cam levers — never fingers) · phone camera · this sheet + a pen.

## Safety rules (Part 2/3)
1. **Motors unplugged** (S + T disconnect plugs) before any powered test. Re-verify after any plug re-seat.
2. One deliberate test at a time; power OFF between test setups.
3. **Never cut or lift the safety-loop wiring to measure — bridge/probe across it.**
4. Levers get clamped, not held; body clear of the mechanism whenever power is on (even unplugged — habits).
5. Caps CP2/CP3 ~0 V before reaching into the cabinet.

---

## PART 1 — Cold (machine OFF). ~15 minutes.

### 1A. GS8 re-drop (the missing gripper)
1. Black lead clipped to bare **chassis/frame**.
2. Set one pin into **cup 8** (back row, second from left when facing the machine from the pit: 7-**8**-9-10).
3. Red lead: back-probe C2A cavities. The one that reads **closed to chassis** = GS8.
4. Sanity: it must NOT be C, H, M, S, W, a, e, r, v (taken) or J/F/U/N (commons). Expect a fresh letter.

**Record: GS8 = C2A-____**

### 1B. GP (gripper-protect) toggle-delta
GP closes when the grippers are **fully open** (it's what tells the brain the table is safe to descend). It's on the table/gripper mechanism — no OEM photo exists; find the one microswitch that moves when you work the gripper linkage.
1. Clip the long lead to one GP switch wire. Sweep C2A, note what beeps.
2. **Actuate the gripper mechanism by hand** (work the respot/release linkage so the grippers open and close) and watch: the cavity whose beep **appears/disappears with the linkage** is GP. Everything that doesn't move with it is common/sneak-path — ignore.
3. Nothing toggling? Move to the switch's other wire and repeat.

**Record: GP = C2A-____ (and which linkage state = closed: ____)**

---

## PART 2 — POWERED interlock characterization (redesign §4). ~45 min, the decision-maker.

**Setup for all of Part 2:** S + T motor disconnect plugs **separated** · machine powered · a helper is nice but clamps make it a one-person job.

**"Forcing the danger state"** = both interlock cam switches closed at once, exactly what happens when sweep and table are on a collision course: **clamp the SC lever pressed AND the TB lever pressed** (their N.O. contacts close in-window — you proved SC's N.O. is the pink wire on 06-27). Two spring clamps; hands away.

### 2A. THE BIG ONE — does the ladder alone kill the motors? (Candidate-C premise, §4.2)
The MP manual claims the rear-panel **manual Sweep/Table controls bypass all brain logic *except* this interlock** — which makes them the perfect probe: if the interlock still stops a *manual* command, the protection lives in the **ladder**, not the Omega-Tek brain.

**What "manual Sweep" is:** a switch on the **REAR CONTROL PANEL** — the small operator box at the back of the machine, the same box carrying the PBZ zero button you mapped to EE. Op-manual p11 legend: **S** = manual sweep, **T** = manual table (plus SWS/SWSR run/reverse). It is **NOT any cam switch** — SA/SB/SC on the shaft are sensors, they command nothing.

**Finding the right coil + the exact probe points:**
1. Motors unplugged, machine powered. Flip manual **S** ON for a second, OFF. **Something in the cabinet CLACKS** — that device is the S chain; no label-hunting needed. If TWO devices click (small relay driving a big one), use the **bigger one — the one with THICK motor wires on its terminals** (the motor contactor: the thing the interlock must kill).
2. On that device: the **two SMALL screw terminals with THIN control wires** are the coil — Siemens marks them **A1 / A2** (top + bottom corner, or both on front). This is the **same 5 Ω pair from the 06-01 bench read**. The FAT lugs with thick wires are motor contacts — stay off them.
3. **Power OFF → alligator-clip one meter lead to A1, one to A2** (clips, hands-free — never held probes on a live cabinet). Meter to **VAC, LoZ**. Power ON, read from a step back.
4. "Dead" vs "energized" is read **ACROSS A1–A2** (a differential read — chassis/ground is NOT involved): energized ≈ **24 VAC + a loud clack**; dead ≈ **0 V + silence**. Don't read coil-to-chassis — ladder nodes can float at odd voltages and fake an "energized." **The clack alone is a valid answer**; the meter just gives you a number to write down.

**The test:**
1. **Baseline:** manual **S** ON — clack, ~24 VAC across A1–A2, no motion (motor unplugged). Record the coil V (this also closes the old "heavy-lug contactor coil V" straggler). Switch OFF.
2. **Force the danger state** (clamp SC + TB levers pressed). Manual **S** ON again:
   - **No clack / ~0 V across A1–A2 → LADDER PROTECTION IS REAL** — strong evidence for candidate C.
   - **Clacks anyway / ~24 VAC → premise FALSE** — the interlock is brain-mediated on this retrofit; **candidate C is dead → candidate A** (aux switches).
3. **Drop-test variant:** manual S ON first (contactor in), *then* clamp both levers → coil should **drop to 0 V** if the ladder protects.
4. Repeat 1–3 for **T** (manual Table switch; re-find its contactor by the clack, move the clips to ITS A1/A2).
5. **Control:** unclamp ONE lever (either) → manual command should work normally again. If it doesn't, note which lever alone blocks it.

**Record (each of S and T): baseline V ____ · forced-command result ____ · drop-test result ____ · single-lever control ____**

> Interpreting a MIXED result (e.g. S protected, T not): record it exactly — the interlock may sit in only one coil path, which changes the harness plan. Don't force a clean answer.

### 2B. Where does the danger signal appear? (§4.1 — feeds candidate B′ + the software echo)
With the mechanism at rest, then with the danger state clamped (power ON, motors unplugged, machine idle — no cycle commanded):
1. LoZ meter **C2A-U → chassis**: record V at rest ____ and clamped ____.
2. LoZ meter the **TB ladder-feed side** — the TB switch wire that did NOT ring to SC's pink on 06-27 (the "upper" wire, → TSA-5): record V at rest ____ and clamped ____.
3. Whichever point shows a **clean, repeatable voltage change** between safe and danger is the usable tap. If neither changes, the observable may only exist mid-cycle — note that and stop (that itself is an answer: no static tap → B is dead too).

### 2C. Window angles (§4.3 — feeds candidate A alignment + echo timing)
Motors still unplugged. Hand-rotate the sweep shaft, then the table shaft, slowly through a revolution while watching (or beeping, power OFF for this one if easier) the SC then TB switch:
- Note where each **closes** and **re-opens** against any degree markings on the shaft/cam; no markings → photograph the cam lobe at each transition point (4 photos: SC close, SC open, TB close, TB open).
- Expected ballpark: SC ≈ 86–243° of sweep, TB ≈ 105–255° of table. Ballpark disagreement is fine — record what the iron says.

---

## PART 3 — Optional, same setup: powered cam mapping + front-end class. ~30 min.
Only if the session is going well — this is cutover-prep work, and the setup (powered, motors unplugged) is already paid for.

### 3A. Motion-cam cavities (SA / SB / TA1 / TA2) — the cold-impossible read
1. Back-probe a candidate C2A cavity; LoZ meter cavity → chassis.
2. **Hand-rotate the sweep shaft** through a revolution: a cavity whose voltage **toggles at SA's angles** (two spots: ~270° and ~360°) = SA; at ~66°/186° = SB. Repeat on the **table shaft** for TA1 (~355°/185°) and TA2 (~260°).
3. Faster variant: clip the meter to the cam's **switch wire** (colors from the p257 legend: SA white/blue · SB brown/red · TA1 pink/purple · TA2 blue/gray) → chassis, confirm which rotation angle toggles it, THEN find the one cavity that toggles in sync.
4. **Record: SA=____ SB=____ TA1=____ TA2=____** (ignore N — that's the common).

### 3B. Front-end class (dry vs 24 VAC) — decides the opto jumpers
At each mapped input (the 4 cams + SC tap + GP + BS + PBZ/EE), machine powered + idle, **LoZ** cavity → FIELD_GND/chassis:
- **< 2 V or dead** = dry contact (default opto front-end, no change).
- **~12–24 VAC** = live channel → that channel needs the 24 VAC-rectified front-end variant.
- **Record a voltage per channel** — even "0" is data.

### 3C. PBZ specifically
LoZ **EE → chassis**, idle: ____ V. Held pressed: ____ V. (You measured EE shorts to common U when pressed — this read tells us whether EE sits at a live potential when released, which decides its front-end.)

---

## What to send back
Photos of this sheet's blanks (or typed). **2A's answer alone settles the interlock decision** — everything else refines the harness. I'll fold the results into the redesign doc §7 decision record, Section F, and the firmware echo redesign the moment you send them.

## Priority if time is short
**2A → 1A → 1B → 2B → 2C → Part 3.** 2A is twenty minutes including setup and it's the one gating your architecture decision.
