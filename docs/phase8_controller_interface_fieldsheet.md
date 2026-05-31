# AMF 82-70 — Controller-Replacement Interface Map (Track B field sheet)

**Goal:** produce the **interface contract** the Pi-controller must satisfy at the **C1 machine harness** — every signal it must READ (machine → Pi) and DRIVE (Pi → machine), plus **which motor stops are hardwired** and the **safety chain**. That spec is what lets a Pi replace the Omega-Tek / Ultra-98 brain on *any* 82-70 lane.

**Approach = recover-then-verify.** The tables below are pre-seeded from the Omega-Tek Omniboard + Expander manuals (their theory-of-operation names every signal). You **verify + fill the gaps** on the spare cabinet — don't trace blind.

> **Shortcut:** if you can find the **AMF 82-70 machine wiring diagram**, it maps the C1 harness straight to the machine devices and saves most of the tracing below. Look for it before you start buzzing pins.

## ⚠️ Safety
- The spare cabinet on your bench is **disconnected from the machine and from mains**, so **cold work (continuity, tracing, label-reading) is 100% safe.** Most of this sheet is cold.
- If it's been powered recently, **CP-3 holds ~150 V** for a minute — don't bridge its terminals.
- The few powered readings (contactor-coil + rail voltages): GFCI, one hand in pocket, probe the **low-voltage side** only.
- **Black probe = chassis frame = ground** (no dedicated GND lug).
- **Load your AC readings** (1 kΩ across the probes, or LoZ mode) — a bare high-Z meter gives ghost voltages on floating pins (the trap from the scoring test).

**Tag key — [C]** = do it cold on the spare now. **[M]** = machine-side device (not in the cabinet): identify its C1 pin + expected type here; confirm real rest/active at a live machine (or from the 82-70 wiring diagram).

## Setup
- [ ] Boards reseated: Omniboard in PC-4, Expander in PC-1.
- [ ] Identify + label + photograph the connectors: **C1** (main machine harness), **Mask** (ELCO), **BPP**, scoring, Russell-Stoll power-in.
- [ ] Meter for continuity + DC/AC volts; a 1 kΩ resistor on hand for loaded AC reads.

---

## PART 1 — C1 pinout map  [C]  *(cold continuity — the physical interface)*
For each used C1 pin: **signal**, **direction** (IN = machine→chassis, OUT = chassis→machine), **where it lands**.
Method: buzz continuity from each C1 pin → board / contactor coil / lamp driver. **IN** = lands on a board *input* (buffer/debouncer chip). **OUT** = lands on a board *driver* (transistor / SCR / relay / contactor coil).
Pre-seeded from the Expander manual (verify these first):
- C1-17-DD (red) → TSA-2 (sweep) · C1-18-JJ (blk) → TSA-3 (sweep)
- C1-26-BB (org) → Sweep Motor Plug SMP-Z · C1-27-FF (wht) → SMP-Y
- Sweep Contactor Coil terminal 6 (yel)

## PART 2 — INPUTS the Pi must READ  [M]  *(machine → controller)*
The controller reads these; the Pi must too. Roles/levels are *per manual* — verify on a live machine. For each: **C1 pin**, **type** (switch-to-ground? pulled to 12 V? logic?), **rest/active**.

| Signal | role (per manual) | C1 pin | type | rest | active |
|---|---|---|---|---|---|
| Start switch (cushion) | cycle trigger (DIELL on our lanes) | | momentary closure | | |
| SA | sweep cam ~270° (stops sweep) | | | | |
| SB | sweep cam | | | | |
| SC | sweep cam | | | | |
| TA-1 | table cam 185–355° | | | | |
| TA-2 | table cam ~260° (grippers read / ball flip) | | | | |
| Bin switch (BS) | table/bin position | | | | |
| Gripper-protect | enables time delay | | | | |
| Off-spot (OS) | inhibit | | | | |
| Foul | inhibit + foul lamp | | | | |
| Instructomat | inhibit | | | | |
| 2nd-ball | ball state | | | | |
| Grippers x10 | pin sense (CMOS-level at U27/U28) | | | | |

## PART 3 — OUTPUTS the Pi must DRIVE  [C]  *(controller → machine; measure drive type + voltage)*

| Signal | where | drive type | voltage | notes |
|---|---|---|---|---|
| Sweep motor | contactor coil | coil (read label) | | Pi energizes the coil; motor + contactor stay |
| Table motor | contactor coil | coil | | " |
| Sweep-reverse relay | coil | coil | | gutter / 7-10 |
| Spot relay | coil | coil | | |
| Pin lamps x10 | mask | AC, SCR-driven | ~weak/floating | see convergence note |
| Status lamps (strike/1st/2nd/foul) | mask | | | |
| Gripper drivers | | | | if used |

- **Coil voltages:** read the contactor labels (Siemens 3TH40 / 3TB4102, Schneider CAD32) → coil voltage (AC or DC). That's what the Pi's relay output energizes.
- **Convergence note:** we don't have to reproduce the pin-lamp electronics — **the camera (Track A) already gives us pin data**, so the unified node can drive the mask pindication from *our* detection. Characterize the lamp drive (voltage/type) only enough to drive the lamps; don't over-invest in replicating the SCR scheme.

## PART 4 — WHICH STOPS ARE HARDWIRED  [C]  ⭐ *(decides the Pi's real-time burden)*
Does a cam limit **physically** cut the motor contactor, or only tell the board?
- [ ] **SWEEP stop ~270° (SA):** cold-trace — is SA's contact in the **sweep-contactor coil circuit** (hardwired), or only a board input? Hardwired? **Y / N** ____
- [ ] **TABLE stop (TA cams):** same trace. Hardwired? **Y / N** ____
- **If Y:** Pi only *starts* motors; hardware *stops* them → low real-time burden, much safer.
- **If N:** Pi must *time* the stop → needs the MCU co-processor **and** we ADD hardware end-stops before any live motor. **FLAG.**

## PART 5 — SAFETY CHAIN  [C]  ⚠️ *(highest priority)*
- [ ] Locate the **stop switch** + **C.I.S.** (1981 safety switch).
- [ ] Cold-trace: **in series with the motor contactors?** **Y / N** ____
- [ ] If **N** → FLAG: a hardware interlock must go in series before any motor runs under Pi control.

## PART 6 — POWER  [C / brief powered]
- [ ] Power-in: chassis is fed 110 VAC via the Russell-Stoll (on the machine frame). Identify the chassis power-in leads (line / neutral / ground). The Pi node reuses this feed or supplies its own.
- [ ] Rails (powered, brief): raw ~35 V / 12 V (7812) / 5 V (7805). REC ___ / ___ / ___
- [ ] Contactor-coil supply: which rail / AC the coils run on.

## Priorities
**First bench session:** Parts **4 (stops) + 5 (safety) + 1 (C1 map)** — these decide the whole control architecture. Then Part 3 (coil voltages). Part 2 inputs lean on the manual; confirm at a live machine. Part 6 is quick.

## What this produces
The filled sheet = the Pi-controller's **I/O spec**: every C1 signal, its direction + electrical type, the motor-drive (coil) requirements, and the stops/safety architecture. That drives the I/O-board design (MCP23017 + opto-in + SSR/relay-out) and the control FSM. Plan: `phase8_PLAN_A_full_replacement.md`.
