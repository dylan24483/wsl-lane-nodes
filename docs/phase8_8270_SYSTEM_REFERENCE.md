# AMF 82-70 Controller — Complete System Reference (for Pi reproduction)

**Sources, both mined in full 2026-05-31:** *8270 MP Operation Training Manual* (PN 610000009, 67 pp) + *8270 Service & Parts Manual* (PN 610007028, 290 pp, AMF 82-70C Instruction & Service Manual, rev 8/95). This is the authoritative understanding of the system we are reproducing.

> **SC/TB field reconciliation (2026-07-24):** the 2026-07-07 powered test, not the 2026-06-27 cold continuity trace, controls topology and polarity. OEM contacts behave **parallel closed-when-safe**; both levers BACK/open kill both S and T coils. The cold session proved only that C2A-U is a non-isolatable live-ladder region, TB has no standalone/dry J_SAFE landing, and ~21 Ω sneak paths prevent topology inference. Candidate C uses the controlled J_SAFE1-2 jumper, delegates the primary guard to the OEM ladder, and requires the per-lane G3 S/T coil-drop insertion proof. The firmware SC∧TB echo is default-off, secondary, and unvalidated.
>
> **Stop / pit-entry field reconciliation (2026-07-24):** OEM history below
> describes Stop + C.I.S., but physical inspection found no C.I.S. device or
> wiring on lanes 21/22. Their installed chain is Stop-only; whether another
> pit-entry interlock exists is unresolved. J14.3–4 remains OPEN/no-arm pending
> an approved isolated Stop/control-power interface and actual Stop→master/
> control-power→TP16 demand proof. Do not treat the generic OEM model below as
> installed-hardware evidence.

## 0. The reproduction thesis (confirmed by the manuals)
We keep the **82-70 machine** (mechanism, motors, cams, grippers, mask lamps) and replace only the **control brain**. AMF already did exactly this: the **MP chassis (#070-009-800) directly replaced the 5-board Solid-State chassis** using the *same machine inputs/outputs* — only the logic medium changed (relay/discrete → microprocessor). **Our Pi-controller = a modern MP chassis.** Critically, the MP schematic (9807) *omits the microprocessor's internal logic* and shows only the machine+chassis interconnections — **so the schematic IS our interface spec, and the omitted logic is exactly the part we write.**

## 1. The machine (what the controller orchestrates)
Nine assemblies: **Cushion** (its shock-absorber actuates the **SS** start switch = cycle trigger), Ball Lift, **Sweep**, Carpet, Pin Elevator, Distributor, Bin (#9 bin has **BS**), **Table** (10 spotting cups + 10 respot cells, each with a **GS** gripper switch). **BE motor runs continuously** (elevator/carpet/distributor/ball-lift). **Table + Sweep motors** run intermittently per cycle (12.1 RPM, cap-induction, 115 VAC).

## 2. Control FSM — sequence of operation (the heart of the rebuild)
- **FIRST BALL:** SS closes → sweep runs to **66° (SB)** guard → **3 s time delay** (gated by **GP** closed) → table descends → **GS** grippers read standing pins (open = strike path) → at **260° (TA2)** pin lamps latch (12 VDC, KX relay sends pin data to scorer) + "machine ready" to computer → sweep runs to **270° (SA)** → table runs through **TA1 (185–355°)**; at 185° the time-delay resets → ball-cycle memory flips (**1st-ball light off, 2nd-ball on**) → sweep returns 270→**360° (SA opens)** stop → table stops at zero.
- **SECOND BALL:** ball-memory inverted. Sweep→66°→delay→**run-through to 270°**. After 10th pin to bin, **BS** closes → **SP spot relay** energizes → table spotting revolution → sweep→360° → ball-memory resets (**→1st ball**).
- **STRIKE:** as first ball but **no pins** → all GS open → at 260° (TA2) **strike memory** sets → strike light on, holds table at 360° for spotting → spot + sweep as 2nd ball → strike memory resets when sweep+table reach zero.
- **FOUL:** foul detector (Radaray) → foul light + logic → sweep→66° → **foul memory** holds table → sweep run-through to 270° → BS → table spotting → ball-memory flips (→2nd ball).

## 3. Cam timing (authoritative — the FSM triggers)
| Cam | Trips at | Role |
|---|---|---|
| **SA** (sweep) | 270° + 360°/zero | stop run-through @270°; stop @zero |
| **SB** (sweep) | 66° + 186° | guard stop @66°; initiate table spotting @186° |
| **SC** (sweep) | 86–243° | sweep-under-table → **interlock** |
| **TA1** (table) | 355° (+185°) | table zero stop; @185° reset time delay |
| **TA2** (table) | 260° | initiate sweep run-through; pin-lamp latch; ball/strike decision |
| **TB** (table) | 105–255° | table-sweep interference zone → **interlock** |
+ **3-second time delay** (pin settle), gated by **GP**.

## 4. I/O interface
**INPUTS** (Pi reads; via **C2A** 50-pin + **TAC** gripper strip; **5 VDC / 24 VAC** on MP):
SS (cushion — **DIELL on our lanes**); cams SA, SB, SC, TA1, TA2, TB; grippers **GS1–GS10**; GP, OS, BS; PBZ (zero / 1st-2nd ball / manual-intervention), PBC (cycle), 10th-frame; manual T, S, SWS, SWSR; **Foul** (Radaray).

**OUTPUTS** (Pi drives; relay coils switch 115 V, + lamps):
Relays **M** (master), **BE**, **S** (sweep), **T** (table), **SP** (spot), **M1** (ball return), **M2** (sweep reverse) — coils ~24 V (T2/T3/T4). Motors via relays: BE continuous; **T/S** main(≈1.5 Ω)+start(≈4.2 Ω) windings, caps + centrifugal switch, **regenerative braking on relay N.C. contacts**. **Spot/respot solenoids** (via SP). Mask: **pin lamps 1–10** (via D1–D10, 12 VDC; KX gates pin data to scorer) + neon ~125 VAC/-160 VDC; **status lamps** 1st/2nd-ball/foul/strike (12 VDC, mask PM-E24/E25/E27/E26).

**CONNECTORS:** **C1 = 34-pin** (motor/relay + power), **C2A = 50-pin** (switches/control), Mask (PM/BPP), Table plug, A&MC, APS (scoring camera). AMP "M" type, numbered by column/pin.

## 5. Safety model — PRESERVE in hardware
- **Stop switch + C.I.S. OEM model:** the manuals describe parallel devices that cut the **rear-panel master circuit breaker**. Pilot lanes 21/22 physically have no C.I.S.; demand-prove their installed Stop, record C.I.S. N/A, and resolve any other pit-entry interlock separately.
- **Table-sweep INTERLOCK:** the **powered 2026-07-07** test proved that TB + SC act as **parallel closed-when-safe contacts** in the OEM 24 VAC relay-control ladder: either pressed lever permits the coil; **both levers BACK/open kill both S and T coils**, including on brain-independent manual commands. The MP's manual Sweep/Table overrides bypass *all* logic **except BE + this interlock**, so it remains the irreducible hardware safety. The **cold 2026-06-27** trace proved no independent TB/dry J_SAFE landing at C2A-U and exposed ~21 Ω coil sneak paths; it did not prove series topology. **Candidate C is decided:** J_SAFE1-2 gets the controlled jumper, primary protection stays in the OEM ladder, and every lane must pass the G3 S-and-T coil-drop insertion proof (`phase8_interlock_redesign.md`). The firmware echo is default-off, secondary, and unvalidated.
- **Motor braking:** regenerative, in the relay N.C. contacts + caps — hardware.
- **MP "Power-Down" feature:** after *any* 115 VAC loss while in "Bowl," **no machine motion on power restore** until a deliberate **"First Ball Zero"** (Manual Intervention). **Our Pi MUST replicate this** — fail-safe-off on restore, require operator zero. (This is the controller-level sibling of our NE555 watchdog.)
- **Cam-position stops are controller LOGIC** (read cam → drop relay), *not* a hardwired motor latch → the **Pi times them**; TB/SC interlock + relay braking are the hardware backstops.

## 6. MP-chassis → Pi-controller mapping (what we build)
The 5 SS boards (PC1 input card → PC2 Nor card → PC3 amplifiers [drive relay/contactor coils + mask lamps + thyristor gates] → PC4 pindicator/cycle lamps → PC5 power supply → PC6 sparemaker) were collapsed into one MP board. **Our Pi does the same job:** read switches → run the §2 FSM → drive relay coils + lamps. Optional **sweep-reverse** (APS + kit #070-011-330): strike → bypass delay + run-through; miss/7-10 → bypass delay + reverse sweep. RPO + 30–60 s pit time-delay are programmed behaviors.

## 7. Build implications
- **I/O:** ~23 inputs (opto-isolated, 5 VDC/24 VAC) + ~22 outputs (7 relay coils @24 V + ~14 lamps + spot) ≈ **45 channels** → MCP23017 expanders + opto-in + relay/SSR-out (watchdog + AEDIKO relays slot in). **Pin lamps can be driven from the camera's pin data** (Track A convergence) — trims outputs.
- **FSM:** implement §2 with §3 cam triggers + the power-down/manual-intervention safety.
- **Safety architecture:** preserve the powered-proven TB/SC interlock and the
  actually installed upstream breaker/Stop/pit-interlock architecture in
  hardware; do not infer a C.I.S. on lanes 21/22. Add the reviewed J14.3–4
  control-power proof interface before field ARM. Keep the NE555 watchdog
  (relays drop on Pi death), MCU co-processor for cam-stop timing, and
  **fail-safe-off + require manual-intervention on power restore.**

## 8. Schematic inventory — Service & Parts manual, pp 287–290 (foldouts)
- **p287** — chassis schematic (PC board + relays + pin lamps + sparemaker) — MP/9807-class.
- **p288** — machine+chassis "three-board projection": **C1 + C2A connectors**, DC control box, relays, pin lamps. *(Best page for the C1/C2A machine-side pinout.)*
- **p289** — mask/pindicator wiring (all masks + Mod V) + connector pinouts.
- **p290** — full schematic (power + control + PC board + pin lamps + sparemaker) — 6730 5-board-class.
- **Action for build phase:** high-DPI crop these region-by-region to extract exact C1/C2A machine-side pins + node topology. The functional interface (§4) + the MP training-manual wire tables already give us the map; these confirm exact pins.

## 9. Still to verify on OUR spare
Our spare is **SS chassis + Omega-Tek Omniboard** (21/22); 11/12 are MP (Ultra 98). The **machine side is common** (cams/motors/grippers via C1/C2A) — everything above applies. Verify machine-side C1/C2A pins on the spare; use the Omega-Tek manuals (on hand) for that board's internals. The 8270 text files: `Downloads\svc_text.txt` (service), the training-manual text in chat history.
