# Rev-D Readiness & Fab-Order-Gate Checklist — Phase 8 Lane Controller Board

Status legend: `[ ]` open · `[~]` blocked on physical verify / owner decision · `[x]` done.
**Do not place a fab order until every PRE-ORDER GATE is `[x]`.**

---

## ⭐ DECISION RECORD — 2026-07-26

Recorded by Claude on the owner's instruction. **Items 1 and 3–5 are Dylan's decisions;
item 2 was expressly delegated to Claude's judgement.** Item 1 needs Dylan's countersignature
on the G15 line to close that gate formally.

| # | Decision | Source | Effect |
|---|---|---|---|
| 1 | **Order at FLEET quantity (34 boards).** FA-9 de-gated as a pre-order blocker (still executed at first article). | Dylan | Closes the G15 question — see G15 for the full margin stack and the countersignature note |
| 2 | **Cams are read as DRY CONTACTS, tapped at the microswitches — NOT by 24 VAC ladder sense. N = 0 driven 24 VAC channels.** | **Delegated to Claude** | Makes both fleet-revision items inert; no firmware change; no cavity mapping needed |
| 3 | **Winford `BRK2x10-DIN` approved** as the C7 board breakout. | Dylan | Replaces an unnamed generic module; unblocks the panel layout |
| 4 | **Machine C1 = female → we supply MALE/pins. Machine C2A = male → we supply FEMALE/sockets.** | Dylan (measured) | Closes the interposer gender question — see §G4/G5 in the backplate BOM |
| 5 | **Enclosure-to-machine run = 6 ft (1829 mm)**, measured. | Dylan | Harness wire list re-issued as **Rev 3** (L1 3200 / L2 3700 / L3 4700) |
| 10 | **OEM DIELL interface board DEPRECATED.** Confirmed at the machine that it feeds/outputs only the DIELL sensors and the camera — nothing else. We power both ourselves. | Dylan, 2026-07-26 | Retires 32 boards + 64 no-NA-distribution sensors + 42 VAC from the ball path. Harness **Rev 4** (+W50–W53); D3 4→6; new isolated 12 V DC-DC. **Closes audit M-21.** Full record: `phase8_diell_board_deprecation_2026-07-26.md` |
| 6 | **WAVE 1 assembly move approved** — J2, J6–J11, J14 to JLC. | Dylan | Fab package **r9**; hand-solder 17 → 9; 646 THT joints eliminated |
| 7 | **FA-4 RISK ACCEPTED** — JLC may place A1 (Pico) without a first article proving USB access. | Dylan, 2026-07-26 | See below. **Conditional on the Pico C-number being confirmed as bare RP2040** |
| 8 | **Pico C-number resolution delegated to Claude.** | Dylan | **UNRESOLVED from public data — escalated to JLC support.** See below |

### Item 9 — J1 keying VERIFIED · 2026-07-26 · the "Candidate" hold is released

Verified against rev-B board #1 (owner observation) plus the rev-B as-ordered CPL and the
rev-D board file. **J1 orientation is geometrically identical between rev-B and rev-D**, so a
part proven to mate on rev-B is proven to mate on rev-D:

| | rev-B (as-ordered CPL) | rev-D (board file) |
|---|---|---|
| Footprint | `IDC-Header_2x10_P2.54mm_Vertical` | **same** |
| Rotation | 90° | **90°** |
| Pad-1 Y | 10.0 mm | **10.0 mm** |
| X | 126.0 | 135.5 *(only this moved)* |

Measured on rev-D: **odd row (pins 1,3…19) at y = 10.000 mm; even row at y = 7.460 mm**, board
edge at y = 0. The pin-1 row is therefore the **interior-facing** row — matching the owner's
rev-B/C observation that *"the notch is on the pin 1 side facing toward the inside of the board
and away from the edge."* Since a 2×10 box header can only be inserted two ways, and both pin 1
and the notch move together, correct pin-1 placement forces correct notch orientation.

**Shroud + polarising notch confirmed present on rev-B/C** (owner, 2026-07-26) — so the part
class is right and the ribbon cannot be mated backwards.

**Disposition: J1 = CNC Tech `3020-20-0100-00` is RELEASED from HOLD.** Basis: 5 pcs were bought
for rev-B (`phase8_revB_preorder_parts_list.md:76`), one is soldered to board #1, and that board
brought up I²C successfully at 0x20/0x21/0x22. The footprint is generic DIN 41651 / IEC 60603-13,
so any conforming 2×10 box header drops in.

> ⚠️ **Two-minute confirmation still worth doing** (closes the owner's "red conductor or the one
> to its right" uncertainty definitively). **J1 pin 1 = `VCC_5V`, pin 2 = `GND`.** With the board
> UNPOWERED and the ribbon seated in J1, beep continuity from the **red conductor** at the free
> end to **TP1** (the 5 V rail). Continuity ⇒ red = conductor 1 = pin 1. If instead it beeps to
> GND, the ribbon was assembled with red on contact 2 and every downstream pin map is off by one.
>
> ⛔ **Standing rule, unchanged:** never land J1 pin 1 (`VCC_5V`) or pin 11 (`VCC_3V3`) on the Pi —
> the board is powered from J2 and the rails would fight. Only pins 2/3/4 (GND/SDA/SCL) go across.

**Consequence:** J1 is now a **wave-2 candidate**. If JLC can source a conforming 2×10 box header,
that is another 20 THT joints/board — **680 fleet-wide**. Added to the JLC sourcing question.

### Item 7 — FA-4 risk acceptance (recorded verbatim)

Under decision 1 (fleet quantity) there is no first article, so JLC placing A1 commits 34 Picos
before anyone physically confirms a micro-B cable seats with the J1 ribbon mated.

**Accepted by Dylan on 2026-07-26: *"Agreed. Risk accepted."*** Basis:

- **Geometry measured clear on rev-D.** A1 sits at (100, 33) rot 0 with the micro-USB facing the
  board's own y=0 edge and **5.70 mm of empty board** in front of it. J1 moved to (135.5, 10) —
  **25.4 mm** of lateral separation, with J2 physically interposed. Nothing occupies x 88–114
  below y 5.7. The rev-C jam condition does not exist on this board.
- **Pre-flashing buys exactly one flash cycle, then expires.** The cam-arming flags
  (`CAM_*_STOP_ENABLED`, `CAM_*_TRIP`, `INTERLOCK_ECHO_ENABLED`, `MOTION_NO_RUN_ENABLED`) are
  compile-time, and the cutover image does not exist yet. **Post-assembly USB reflash is already
  mandatory fleet-wide**, so hand-soldering A1 postpones the problem by one flash and leaves the
  identical exposure.
- **Two independent recovery paths survive reflow:** the shaved right-angle micro-B cable
  (proven on a rev-B board whose geometry was strictly worse), and the Pico's own SWCLK/GND/SWDIO
  castellated pads at the end opposite the USB, nearest neighbour 14 mm away.
- **Cost of refusing:** 34 hand-soldered 40-pad castellated modules — the highest-risk soldering
  operation on the board — to protect a mitigation that expires at the Phase-0 reflash anyway.

⚠️ **This acceptance is CONDITIONAL and does not authorise placing A1 yet.** It is void unless
JLC confirms the exact part is a **bare RP2040 Pico with no pre-soldered headers**. See item 8.

### Item 8 — Pico C-number: NOT RESOLVED, escalated

Delegated to Claude and **deliberately not guessed.** Both candidates are ambiguous on JLC's
public pages:

| Candidate | Reads right | Reads wrong |
|---|---|---|
| **C9900019762** | MPN `SC0915` (correct bare-Pico order code); package `LCC-43` matches the Pico's 40 edge + 3 debug pads | manufacturer field says "JLCPCB Assembly", not Raspberry Pi; no published stock or price |
| **C7203002** | manufacturer is Raspberry Pi; Standard PCBA | MPN string is just "Pico" — does **not** distinguish Pico / Pico H (headers fitted) / **Pico 2 (RP2350)** |

JLC's library also carries **Pico 2 / RP2350** entries, and this project's firmware is
**RP2040-only** (`build_options.pico_board = "pico"`, UF2 `d5570efd…`). Pinning the wrong
variant would put unusable silicon on 34 boards, discovered only at flash time.

**Resolution: question 2 of `docs/phase8_jlc_support_email_2026-07-26.md`.** Until JLC confirms
in writing, **A1 stays hand-solder** and no Pico C-number enters `PART_LOCK`. When it is
confirmed, add a G12 **silkscreen photo gate** — a photograph showing the module reads
"Raspberry Pi Pico" (RP2040) — before payment.

### Item 2 — the 24 VAC population decision, reasoning

The choice was: sense the motion cams by reading the machine's 24 VAC control ladder, or tap
the cam microswitches directly as dry contacts wetted by `FIELD_WET_V`.

**Decision: dry-contact tap at the switches.** It is the only option that works with the board
as designed:

- **Firmware.** 60 Hz through the r6 front end produces ~12 edges per 100 ms chatter window
  against `CHATTER_MAX_CAM = 8`. 24 VAC sense needs a firmware change; dry contact does not.
- **No filter route exists.** The cams are FAST channels, which carry the 10 nF `Cflt` option,
  not the 2.2 µF one — and the 60 Hz floor is 951 nF. A cap cannot fix an AC cam channel.
- **Cavity mapping.** SA/SB/SC/TA1/TA2 have **no confirmed C2A cavity**. Cold mapping failed
  twice (C2A-N is a shared motion-cam common bus; ~21 Ω relay-coil sneak paths invalidate cold
  continuity). Dry-contact tapping needs no cavity map at all.
- **Board risk.** N = 0 keeps the 0.4807 mm field-pin clearance at ~5 V instead of ±33.9 V, and
  keeps the zero-bulk-capacitance `FIELD_WET_V` rail inside its proven envelope. **This is what
  lets 34 boards ship against the current revision.**

**Cost accepted:** higher install labour — physical access to each cam microswitch on the
mechanism — and longer cam leads. Harness Rev 3 already builds W01–W05 at **4.7 m (class L3)**
for exactly this.

**This decision is reversible only by a board revision.** If 24 VAC cam sensing is ever wanted,
it requires the clearance fix, `FIELD_WET_V` bulk capacitance, and a firmware chatter change —
i.e. a new spin. Re-open it deliberately, never by field improvisation.

---

> **2026-07-23 — REV-D INPUT-MARGIN HARDENING (CURRENT BOARD/FAB RECORD).**
> Exactly the 40 PC817 collector pull-ups `Rpu_*` (`R4,R6,…,R82`) are now
> **47 kΩ**; all unrelated 10 kΩ networks are unchanged. At 3.3 V this lowers
> the MCP23017 guaranteed-LOW sink requirement to
> `(3.3 − 0.66)/47 kΩ = 56.2 µA`. Worst MCP input leakage leaves the idle node
> at 3.253 V versus V_IH(min) 2.64 V, and the 50 pF first-order node RC is
> 2.35 µs. These figures require the external 47 kΩ to be the sole pull:
> production RP2040 GP6–GP13 must have PUE/PDE disabled, and U1/U2 MCP23017
> GPPUA/GPPUB must command and read back `0x00`. Any mismatch is STOP-SHIP.
> `R_TAPPU_*` remains a separate, intentionally unchanged 10 kΩ tap-drain
> network. The current immutable package is
> **`kicad/fab_revD_2026-07-27_r10/`**; every older rev-D package — including
> `_r5/` and `_r6/` — is superseded
> for ordering. ⚠️ **The FA-9 operating point below is PRE-r6 and superseded:**
> r6 inserted a series blocking diode in every channel, so the point is
> **1.34 mA at Vw = 5.0 V / ~1.12 mA at the FA-9 loaded minimum**, not ~1.7 mA.
> This is still an **EXPERIMENTAL FIRST-ARTICLE**: UMW C5692981
> does not guarantee minimum CTR at that current, so the revised FA-9 requires
> every populated channel to pass loaded-minimum FIELD_WET, ≥70 °C,
> idle-leakage, capability, and transition-time measurements before fleet
> release. Current electrical basis: remediation spec §R4.

> **⚗️ THIS ORDER IS AN EXPERIMENTAL FIRST-ARTICLE ONLY (R3-8, 2026-07-21).** Until
> the physical first-article gates clear — chiefly **FA-9 numeric PC817 V_CE / margin
> qualification** (the input front-end margin is improved by the 47 kΩ change, but the
> selected lot still lacks a guarantee at ~1.7 mA/hot; spec §R4) plus the OG-4
> at-temperature tap gate — this board
> is a prototype validation run, not a fleet-release build. The fab-order line item in
> G15 is labelled accordingly and carries a **blank EXPERIMENTAL-ORDER acceptance line
> for Dylan**, mirroring the blank OG-1 and H2 lines. Do not scale to fleet quantity or
> field-deploy a lane on these boards until FA-9 + OG-4 pass and the acceptance line is
> signed.
Written 2026-07-20 at the end of the rev-D design campaign. Companions:
`phase8_revD_change_list.md` (what changed and why), `phase8_revD_change_spec.md` (electrical
detail), `phase8_revD_run_log.md` (gate records FR-1…FR-7, WVR-ERC-1, COR-1, OG-1/OG-3).

> **2026-07-21 — Codex NO-GO remediation campaign CLOSED.** Per-finding final status,
> evidence, recorded repo HEADs, and the definitive open-gates list:
> **`phase8_revD_remediation_report_2026-07-21.md`**. The gates below remain the
> operational checklist; where wording differs, the remediation spec + report govern
> the remediated items (taps R1.9, DRU R2, firmware R3).

> **2026-07-21 (later) — ROUND-2 remediation batch (Codex R2-*) landed on top,
> then the ROUND-3 fix batch (Codex re-review findings 1–8), then the FINALIZE
> batch. The round-2 CLOSING RECORD — final R2-1…R2-17 statuses (16 CLOSED · 1
> DISPOSITIONED), both nuanced dispositions, recorded HEADs, and the definitive
> open-gates list — is `phase8_revD_round2_report_2026-07-21.md`.** The
> first-article pack was then FA-1…**FA-12** (adds the ≥ 100 MΩ tap-probe rule +
> TP-pad-only probing, FA-9 per-channel PC817B qualification at min FIELD_WET +
> ≥ 70 °C [R2-7], FA-12 J16 SDA/SCL short recovery [R2-4]); the PC817B
> disposition is remediation spec §R4 (revised 2026-07-23).
> Board figures anywhere below are superseded: **271 parts / 223 nets, netclasses
> 103/4/13/82/21, 24 test pads (TP17-24 tap probe pads), ERC baseline 1+39
> (WVR-ERC-2, pin-pair order-insensitive since round 3)**; release DRC =
> `kicad/fab_revD_2026-07-27_r10/reports/DRC-revD-fab-export.rpt`; as-current fab package =
> **`kicad/fab_revD_2026-07-27_r10/`** (47 kΩ PC817 pull-ups plus the J16
> protection stack with ESD VP moved
> UPSTREAM of the polyfuse — round-3 finding 2, REV_ID straps rev-D=0b01,
> Q17-Q20 = onsemi 2N7002LT1G C16338, 10M = C2933281 (r8 re-pin), gbrjob Revision "D").
> `fab_revD_2026-07-21/`, `..._r2/`, `..._r3/`, `..._r4/`, `..._r5/`, and
> `kicad/fab_revD_2026-07-25_r6/` are superseded — never
> upload from them. Full record:
> run-log "ROUND-2 BOARD/BOM/EXPORT BATCH" + "ROUND-3 FIX BATCH" +
> "FINALIZE (ROUND 2)" entries.
>
> **2026-07-24 R5 safety/diagnostics supersession:** the generated pack is now
> **FA-1…FA-14**. FA-13 is a system-level P0 gate: J14.3–4 remains physically
> OPEN and the field rail cannot arm until an approved Stop/control-power
> interface is landed. Physical inspection found no C.I.S. on lanes 21/22;
> C.I.S. is N/A, not passed. Resolve whether another pit-entry interlock exists,
> approve install-versus-Stop+LOTO-only disposition, and prove Stop plus every
> installed/new pit interlock independently. A final pit interlock acts
> upstream—J14-only permission gating is not equivalent. FA-14 requires
> qualified-electrician/listed-instrument protective-earth and hot/neutral
> polarity proof. These tests add no mains or SAFE_* copper to Rev-D.

> **⚠️ GATE SCOPE NOTE (the rev-C lesson, applied up front).** The rev-C checklist went green
> on G1–G5 while change-list items 3/5/6–8 were unresolved, and the order shipped without
> them. This checklist therefore gates the fab order on EVERYTHING: the design gates (G1–G6),
> the owner/physical gates (G7–G8), the routing/export gates (G9–G12), and the review gate
> (G13). Green design gates alone do NOT authorize an order.

---

## 1. PRE-ORDER GATES

### G1 — Change spec written + independently verified  `[x]`
- `phase8_revD_change_spec.md` items A–G (2026-07-19, corrected 2026-07-20). Independent
  verify pass re-derived all electrical math (bleed dissipation, ADC margins, tap hold-off
  ladders, wetting 73.7/200 mA, D17 budget) and confirmed it; zero critical findings. One
  optimistic prose bound on the NE555 tap margin was noted and has since been CORRECTED in
  spec §E.2 (run-log COR-2, 2026-07-20): honest worst-case light-load read ≈ 3.53 V — above
  VDD 3.3 V but below the RP2040 3.6 V absolute max, clamp current bounded to single-digit µA
  by the ≥ 100k source impedance. Electrically safe; the old ≤ 3.27 V figure is retired.
- Review-fix pass closed 6 distinct findings (item-E temperature qualification, two
  cross-mate hazards, SS34 swap, OG-1 surfaced, ERC waiver + run log formalized); the full
  tool chain was re-run green afterward.

### G2 — Footprint-vs-datasheet review per new part class  `[x]`  (rev-C process item 10 — scripture)
- FR-1 PC817B vs DIP-4_W7.62 — PASS (40 proven instances on the physical rev-C board).
- FR-2 MCV 1×10 / 1×06 vs Phoenix plugs 1840447 / 1840405 — PASS (proven pairs J3 / J13).
- FR-3 D_PROT SS34 — PASS with the package trap checked: **MDD SS34, LCSC C8678, SMA
  (DO-214AC) verified; SS34 from other vendors ships in SMB/SMC — any MPN substitution
  re-runs this review.**
- FR-6 0805 passives — PASS. **2026-07-21 update (remediation R1): 680k is GONE (new
  values 1M + 10M, same footprint class).**
- FR-7 regression: K1–K7 relay map unchanged (coil pads 2/5, COM 1, NO 3, NC 4 unused —
  identical to the rev-C meter-confirmed G1/G2 map) — PASS.
- **FR-8 (2026-07-21): 2N7002 tap FETs in SOT-23 — PASS** (Q_NMOS_GSD 1=G/2=S/3=D matches
  the 2N7002 pinout; same proven class as the Qled_* drivers; V_GS ±20 V abs max confirmed).
- **FR-9 (2026-07-21): MCV headers → project-local `_D1.4` footprints — PASS** (drill
  1.4 mm per Phoenix drilling plan, pad 2.0×3.6, annular 0.30 mm; all 7 instances;
  first-article insertion/solder-fill check on one connector before the rest).
- Records live in `phase8_revD_run_log.md` (backfilled 2026-07-20 with genuinely-performed
  reviews — the gate had initially run without a written artifact; do not let that recur).

### G3 — Rev-D netlist regenerated + ERC waiver gate green  `[x]`  (re-run 2026-07-21, remediation R1)
- `py -3 scripts/generate_kicad_netlist_revD.py` → `kicad/wsl-phase8b-revD.net`:
  **262 parts, 217 nets, 0 netlist-generation errors** (remediation spec R1.7: −5 resistive
  tap parts, +15 unidirectional-stage parts, +4 `TAP_GATE_*` nets); regeneration is
  deterministic (only date + cwd-dependent source-path lines vary; sklib byte-identical).
- ERC baseline **WVR-ERC-1** (exactly 1 error — the benign Pico AGND/GND POWER-OUT pin-type
  artifact — + 40 warnings) is enforced fail-closed by the generator's `check_erc_waiver()`;
  any drift aborts. Rev-C never ran ERC, so this defines the baseline.
- J15/J16 refdes confirmed landed as specified.

### G4 — Netlist diff vs rev-C CLEAN  `[x]`  (re-run 2026-07-21, remediation R1 + M1 deep tables)
- `py -3 scripts/diff_netlist_revC_to_revD.py` → **RESULT CLEAN**: 46 added parts, 33 added
  nets, 11 touch-point nets additions-only, 173 nets unchanged, **0 removals**;
  CHANGED_PARTs all whitelisted-and-documented (D_PROT SS14→SS34 per FR-3; the five MCV
  connectors' `_D1.4` local-footprint repoint per FR-9/R2.5). M1 deep tables (exact
  value/footprint/pad membership per addition) all green.
- Every delta traces to spec items A/C/D/E/F; item G confirmed absent; forbidden absences
  confirmed (no SAFE_ tap, no RELAY_ENABLE_RAIL divider, no new barrier class).

### G5 — Placement + netclasses + placement-stage DRC + audit  `[x]`
- `kicad/revD/wsl-phase8b-revD.kicad_pcb` — 250×240 mm, 262 parts placed (2026-07-21
  regeneration; tap-stage cluster added in LOGIC x 114–127 / y 52–64), banding FIELD
  left / LOGIC center / MACHINE right with the established gutters, opto column re-pitched
  to 5.7 mm × 40 rows, USB keep-out envelope (16×12×40 mm) drawn on Dwgs_User, cross-mate
  silk warnings placed, TP strip relocated.
- Sidecars `wsl-phase8b-revD.kicad_pro/.kicad_prl/.kicad_dru` copied with the board; the
  `.dru` `hasNetclass()` isolation rules confirmed LIVE (not the 2026-06-03 false-green).
- `apply_netclasses_revD.py --write`: **97 / 4 / 13 / 82 / 21 exact** (2026-07-21 counts,
  remediation R1.7), zero unknown/overlap.
- Placement DRC (`kicad-cli pcb drc`): **0 violations**; 499 unconnected pads = expected at
  the unrouted placement stage.
- `audit_revD_board.py`: **ALL PASS in both netlist and board (--pre-route) modes**, and
  proven to fail closed (a rev-C-count mutant exits 1 with 3 FAILs). Carried invariants all
  green: Default==0, zero anonymous nets, rail reaches exactly 7 K-coils + pass-FET, no
  OUT_* on the Pico, GND/FIELD_GND zero shared nodes, SAFE_ pad membership frozen at
  rev-C's, M1 channel still DNP. **Safety_Rail == 13 is a stop-ship invariant.**

### G6 — Rev-C sacred-file integrity  `[x]`
- 189/189 files in the tracked, clone-portable
  `release_evidence/revC_design_snapshot_2026-07-19.zip` hash-verified internally;
  the 173 release-tracked paths are separately compared by
  `scripts/verify_revC_snapshot.py --compare-checkout`: binary content is byte-exact,
  UTF-8 text is compared independent of checkout line endings, and the historical
  Rev-B spec permits one exact additive non-authority safety notice while its frozen body
  remains exact. Current result is 173/173 with zero failures; no Rev-C electrical or
  fabrication body differs from the archive. Re-verify once more immediately before the
  fab order.

### G7 — Rev-C carried verify-items 6–7 resolved OR explicitly waived  `[~]`  **(owner + powered-session)**
- **Item 6 — per-channel front-end (dry-contact vs 24 VAC-rectified): CLOSED IN COPPER (r6,
  2026-07-25).**
  **RETRACTION — read this before acting on any older copy of G7.** Between 2026-07-21 and
  2026-07-25 this gate read: *"all 40 `FIELD_LED_*` nets have exactly two nodes and no
  series-diode / clamp / filter-cap footprints exist on any input channel… A non-dry-contact
  outcome therefore REQUIRES COPPER and is deferred to the fleet revision. Closing this gate
  for the first article means accepting the dry-contact default AND not landing PBZ /
  DIELL_L / DIELL_R on bare board inputs."* **Every clause of that is now FALSE.** Dylan
  reopened copper on 2026-07-25 and r6 landed the provisions:
  - Every `FIELD_LED_<n>` now has **three** nodes — `Dser_<n>.1` (series block, cathode) +
    `Dclamp_<n>.1` (anti-parallel clamp, cathode) + `PC817.1`.
  - `Dser_*` and `Dclamp_*` (1N4148WS, SOD-323, D18–D97) are **POPULATED on all 40 channels
    by default**. There is no per-channel stuffing decision and no per-lane record to lose.
  - `Cflt_*` (C17–C56, 0805) are **DNP** logic-side filter caps, fitted at commissioning
    only on a channel *measured* to carry a 60 Hz pulse train.
  - **PBZ, DIELL_L and DIELL_R MAY now be landed directly on board inputs**, and the harness
    1N4007 interposer for them is **SUPERSEDED — do not build it.** Prove the clamp per
    board with **FA-15** first (LED reverse must read **0.35 V ± 0.1 V**).
  - Authority: `docs/phase8_revD_r6_input_protection_spec_2026-07-25.md`;
    **current package `kicad/fab_revD_2026-07-27_r10/`** (release build of the r6 design —
    same copper, `_r6/` tombstoned so exactly one package is current). Per-channel
    stuffing table: `docs/phase8_revD_r6_channel_stuffing.csv`.
  **STILL OPEN (r6 does NOT close these) — the powered at-machine metering session is still
  required** (**meter tapped-lead live voltages BEFORE reconnecting any board** — standing
  queue item):
  1. **Cam-channel AC/DC class.** SA/SB/SC/TA1/TA2/TB are still UNMEASURED. r6 makes a
     24 VAC cam channel **electrically survivable, NOT functionally usable** — 60 Hz gives
     12 debounced edges per 100 ms against `CHATTER_MAX_CAM` = 8, so it **faults
     continuously**. Closing that needs a **firmware** change, not a cap. Record DC-or-AC,
     RMS/peak and frequency per channel.
  2. **`FIELD_WET_V` rail headroom under driven channels.** The isolated field rail has
     **zero bulk capacitance** (43 nodes, no capacitor) and a driven 24 VAC channel draws
     **16.8 mA peak** vs 1.34 mA dry. The board is budgeted for **N = 0** driven AC
     channels; **N ≥ 1 reopens the budget** (r6 spec §F.1 / J10b). Scope TP4, do not DMM it.
  3. **Field-pin ↔ field-pin clearance.** Measured minimum **0.4807 mm** against the
     IPC-2221B B1 requirement of 0.6 mm, on nets the clamp now holds at the same potential
     as the 0.6 mm-governed `FIELD_LED_*` nets. Pre-existing geometry, dispositioned as an
     OPEN fleet-revision item (r6 spec §D.5.1) — **not** silently compliant.
- **Item 7 — arc suppression sizing:** snubber positions carry DNP; size from the measured
  inductive load in the same powered session before populating.
- Item 8 (5 V budget) is discharged on paper: spec §H.4 + SS34 swap; bench PSU ≥1 A stands.
- **To close this gate: either the powered session resolves 6–7, or Dylan records an
  explicit waiver in `phase8_revD_run_log.md` accepting the rev-C-validated defaults for
  this spin.** Do not silently repeat rev-C's gate-scope mistake.

### G8 — OG-1: board growth 250×225 → 250×240 signed off + enclosure re-checked  `[~]`  **enclosure re-check RESOLVED (evidence, 2026-07-20); formal sign-off pending (Dylan — rides G14)**
- Spec §C.4 fallback 3 was executed in `place_components_revD.py` (BOARD_H=240) with the
  required owner sign-off **not yet given**. Arithmetic verified honest: true DIP-4_W7.62
  courtyard 5.59–5.68 mm → 40 rows cannot fit 225 mm; fallbacks 1–2 are dead.
- **Enclosure re-check RESOLVED 2026-07-20 — verdict: 240 mm is a spec update, not a
  conflict** (full evidence in the change-list STATUS + run-log OG-1 record):
  - **Nothing is committed to 225 mm in hardware:** no fleet enclosure, subpanel, or
    backplate has been purchased — purchases were explicitly frozen pending this gate;
    `phase8_pair_enclosure_spec.md` (2026-07-14) is a spec/sourcing document; the sourcing
    brief is still an open research task; HANDOFF task #12 is still open. The only
    purchased boxes are two Ogrmar 8×6×4 (already disqualified even at 225 mm) and the
    pilot Saginaw SCE-24EL2008LP, whose ~578×428 mm panel class takes one 250×240 board
    trivially.
  - **Layout D re-math at 240 mm:** 20+240+150+240+20 = 670 mm panel height × 310 mm width
    — fits the incumbent SCE-30EL2408LP's SCE-30P24 subpanel (686×533 mm usable) with
    16 mm to spare (was 46 mm at 225 mm).
  - **COR-3 J_PI +9.5 mm move:** non-issue — the J1 ribbon is internal (board→Pi inside
    the box; glands are all bottom-face field/Cat6), production ribbons are order-later
    pre-made IDC assemblies with no committed length, and 9.5 mm of lateral shift is noise
    against the ~80–150 mm ribbon budget.
- **Row-39 bottom-edge copper (SLOW_AUX11) — CARRIED CONSTRAINT, not yet checkable:** routed
  copper reaches y=238.72 (1.28 mm from the y=240 routed edge — legal vs the 0.5 mm rule
  and typical ±0.3 mm routed-edge tolerance, but any enclosure lip, panel clamp, or edge
  chamfer along the bottom edge contacts row-39 copper first, and a depanel/handling nick
  lands on live AUX11 copper). Since no enclosure/backplate is purchased or designed yet,
  this is a **binding requirement on the eventual bottom-edge lip/clamp design** (keep ≥
  the panel tolerance clear of the edge), to be verified at enclosure-design/purchase time
  — or the 36-row alternative removes row 39 entirely.
- **Alternative if the 240 mm sign-off is declined: 36 opto rows (AUX4–AUX7 only) fits
  225 mm** — requires a placement re-run and netlist/audit-count changes (a mini spin of
  steps I.1–I.6) **and a full re-route (the routed artifact below is 240 mm-specific)**.
- **To close this gate:** Dylan appends the sign-off line in `phase8_revD_run_log.md` gate
  OG-1 (still blank — the evidence record is there waiting for his decision; folded into
  the G14 review packet).

### G9 — Routing complete  `[x]`  **⚠️ EXECUTED OUT OF ORDER — see run-log PV-1; artifact CONDITIONAL on G8**
- Board fully routed 2026-07-20 by `scripts/route_revD.py` (+ `route_revD_lib.py`,
  `route_revD_logic.py`) — manual/deterministic, rev-C house style, all passes re-derived
  for the rev-D placement. Layer discipline + machine-side pattern per the run log.
- **Process violation on record:** this gate's own line said "Do not start routing before
  G8 resolves" and routing ran anyway with G8 still open. That was NOT sanctioned — run-log
  **PV-1** records it. Consequence stands: if Dylan declines the 240 mm growth, the routed
  artifact is DISCARDED (re-place + full re-route). Routing-before-G8 is not precedent.
- 2026-07-20 review-fix RD-VIA-1: the five single-point power vias (VCC_5V feed ×2,
  SAFE_STOP_RETURN ×2, RELAY_ENABLE_RAIL spine entry) were doubled with parallel twin
  barrels + same-net stubs (copper-only; no netlist/pad/netclass change).
- **Re-run trap RETIRED (2026-07-21, remediation batch):** the RD-VIA-1 twins are now
  emitted by the router itself (`route_power_via_redundancy()`), the M2 `BOARD.Delete()`
  fix removed the swig-crash failure mode, and the sanctioned pipeline regenerates the
  placement board from the netlist first — `place_components_revD.py --force` →
  `apply_netclasses_revD.py --write` → `route_revD.py` → `apply_netclasses_revD.py
  --write` → kicad-cli DRC → `audit_revD_board.py`. The routed artifact reproduces from
  scripts alone (proven 2026-07-21 on KiCad 10.0.2).
- **2026-07-21 (remediation R1/R2): board REGENERATED + FULLY RE-ROUTED** — 262 parts,
  new tap stages, new DRU minima 2.65/3.35/1.6 mm. See the change-list remediation banner
  + run-log board-chain record.

### G10 — Post-route DRC + routed-mode audit + zone fills  `[x]`  (re-run 2026-07-21, remediation R2 rules)
- KiCad DRC with the NEW `.dru` (2.65/3.35/1.6 mm — requirement + JLC etch allowance,
  remediation spec R2.3): **0 violations / 0 unconnected / 0 footprint errors** —
  `kicad/revD/DRC-revD-remediation-r3.rpt` (supersedes `DRC-revD-routed-r3.rpt`, which
  was against the old 2.5/3.2/1.5 rules; netclasses re-applied via
  `apply_netclasses_revD.py --write` before each DRC). Measured isolation minima:
  **L↔F 2.650 mm / L↔M 3.350 mm / machine ch↔ch 2.325 mm** (as-fabbed worst case ≥ the
  2.5/3.2 requirement with the ±20 % etch loss included).
- `audit_revD_board.py` in routed board mode (without `--pre-route`): **ALL PASS**,
  including zone-fill checks (F.Cu GND zone filled, no orphan islands — an early RD-VIA-1
  stub placement severed a zone neck at (160, 83–84) and was caught and re-placed north)
  and the Safety_Rail==13 stop-ship invariant.

### G11 — Fab export to a NEW dated directory  `[x]`  (re-run 2026-07-25, r6 release build = package **r7**)
- `scripts/export_fab_revD.py` RUN → **`kicad/fab_revD_2026-07-27_r10/`** (hashed
  as-ordered package, `manifest.json` with sha256 per file + source board/netlist hashes;
  46 members). REV and output-dir are parameters; the script **refuses to run if the output
  dir exists** (verified live — second run refused; no rmtree anywhere). `_r1`…`_r6` all
  carry `_SUPERSEDED_DO_NOT_UPLOAD.txt`; `_r6/` is the **same copper** as r7 (identical
  `source_board_sha256` `695cd7b1…3de7`) and is tombstoned only so exactly one package is
  current. *(Historical: the 2026-07-23 run produced `_r5/`, counts 271/28/243/226.)*
- In-process re-gates before exporting: kicad-cli DRC **0/0/0** with the live remediation
  `.kicad_dru`; `audit_revD_board.py` routed mode **ALL PASS**.
- **BOM↔CPL↔netlist equality ASSERTED** (not sampled): every placed refdes present in all
  three with matching value+footprint; pinned counts **391 parts / 68 DNP / 323 placed /
  306 JLC-placed / 27 JLC lines / 17 hand-solder**. Since r7 the equality is also asserted
  **per part class, per channel** for the 120 r6 parts — see **G17**.
- **PC817 pull-up scope hard-locked:** `R4,R6,…,R82` are exactly 40 × 47 kΩ,
  UNI-ROYAL `0805W8F4702T5E`, LCSC **C17713**. The exporter rejects a missing
  channel, an unrelated 47 kΩ part, or a merge back into the 10 kΩ BOM line.
- **Bias configuration and firmware identity carried in-package:** RP2040 GP6–GP13
  PUE/PDE disabled; U1/U2 MCP23017 GPPUA/GPPUB commanded/read back `0x00`;
  build `rel-0c746b5747143b8011b01d43`, cfg `05d808411db4bb0d`, release UF2
  SHA-256 `d5570efd19c374d9ca4532b78ef36577ae93b88160b5c1775e92d1ef88c40aae`.
  Any internal-pull or identity mismatch blocks FA-9. The package explicitly
  distinguishes the unchanged `R_TAPPU_*` 10 kΩ diagnostic-tap drain pulls.
- **D_PROT hard-locked**: D17 = **MDD SS34, LCSC C8678, SMA/DO-214AC** (FR-3) asserted at
  netlist, board, and JLC-BOM level; any SS14 anywhere fails the export.
- 10M 0805 (R_TAPG_*) is pinned to FOJAN `FRC0805F1005TS`, LCSC **C2933281**
  (**r8 re-pin, 2026-07-26** — the former UNI-ROYAL `0805W8F1005T5E` / C26108 went
  permanently OOS; a 26-line LCSC sweep found only three 10M 0805 1% parts with any
  stock and only C2933281 had headroom against the 102-piece fleet need). 1M remains
  C17514. Any future substitute must be ≥10M 0805 1% with its C-number **fetch-verified
  on the LCSC product page** — never from a search result alone (run-log H6).
- Package also carries the hand-solder BOM (rev-D refs incl. J15/J16 + the U37→U45 shift)
  and the **harness BOM** (see G13).

### G12 — Manual Gerber inspection + JLC preview  `[~]`  (rev-C G5 pattern)
**PART A — design-side inspection: `[x]` CLOSED 2026-07-26** (verified by Claude against
`kicad/revD/wsl-phase8b-revD.kicad_pcb` + `kicad/wsl-phase8b-revD.net`, evidence below).

| Item | Result |
|---|---|
| K1–K7 pad-net map regression | **PASS** — all 7: coil on **2/5** (`RELAY_ENABLE_RAIL` / `COIL_LO_*`), **COM=1** (`OUT_*_A`), **NO=3** (`OUT_*_B`), **NC=4 unconnected on all seven**. The rev-B G5LE-1/G5LE-14 killer cannot recur. |
| 8 new AUX4–11 opto-bank channels | **PASS** — routed-mode audit ALL PASS, 40/40 r6 channels |
| J15 / J16 pads (1.4 mm drill, FR-9) | **PASS** — drill report T8 = **1.400 mm, 62 holes** |
| "KEYED: NOT …" silk | **PASS** — all four present: `NOT J3`, `NOT J15`, `NOT J13 LAMP`, `NOT J16` |
| Board audit, routed + netlist mode | **ALL PASS** both modes, exit 0 |
| Review plots exist | `kicad/fab_revD_2026-07-27_r10/review/wsl-phase8b-revD-review-layers.pdf` (3.5 MB) |

**PART B — JLC upload preview: `[ ]` STILL OPEN. Cannot be closed before the upload session —
it requires JLC's rendered preview, which does not exist until the files are uploaded.**
Do these at the upload screen, before paying:

- `[ ]` Preview reads **250 × 240 mm** — rev-D is 240 mm tall, not rev-C's 225.
- `[ ]` ⚠️ **EDGE RAIL — PUT IT IN THE PCBA REMARK, do not assume.** JLC confirmed 2026-07-27 that their engineers add process rails when a board is under 70 × 70 mm (ours is 250 × 240, so rails should not be needed) **but they did NOT confirm none will be added** — they said they will follow instructions *if written in the PCBA remark*. Required remark text:
  > *"Board is 250 × 240 mm. No process rails should be required. If any process rail IS added, it must be on the LEFT or RIGHT edge ONLY — never the top or bottom edge. Components sit within 5 mm of the top and bottom edges (nearest 0.52 mm at U45, 0.63 mm at U43) and depanelisation there would damage them. A left/right rail changes the outline; this is pre-approved."*
- `[ ]` **Original wording, retained:** if a rail is proposed it must go on the LEFT or RIGHT edge, never the BOTTOM. Three JLC-placed parts sit inside the usual 5 mm bottom keep-out —
  `U43` at **1.360 mm**, `D97` at 1.860, `R82` at 2.200. V-scoring 1.36 mm from a DIP-4 body
  risks cracked joints fleet-wide. Left/right edges are >56 mm clear.
  **Pre-approve the resulting outline change** so a side rail does not read as a 250 × 240 mismatch.
- `[ ]` **Part rotation** on the four classes new in rev-D — F1 (1206L020YR), U46 (TCA4307,
  VSSOP-8), U47 (SRV05-4, SOT-23-6), Q17–Q20 (2N7002LT1G). The CPL ships raw KiCad rotations
  and the exporter has no rotation-correction table; prior-build inference covers only the
  optos/diodes/relays. FA-16 is the backstop, but catch it here if JLC shows rotations.
- `[ ]` USB keep-out clear; row-39 bottom-edge copper (1.28 mm) acknowledged on **both** edges.
- `[ ]` Confirm **C2933281** (10 M) is matched and in JLC assembly stock at the moment of upload.
- `[ ]` **Re-verify `source_board_sha256`** against `manifest.json` immediately before upload —
  `kicad/revD/~wsl-phase8b-revD.kicad_pro.lck` is stale and any KiCad save silently breaks it.

### G13 — Harness/assembly BOM order carries every mating + coding part  `[ ]` ORDER still to place — **BOM itself now EXISTS** (2026-07-21: `docs/phase8_revD_harness_bom.csv`, also in the fab package assembly/ dir, with corrected MC 1,5 termination data — 7 mm strip / 0.22–0.25 N·m / ≤ 0.5 mm² insulated ferrule — and the corrected coding-install rule)  (OG-3; ship WITH the boards)
| Item | PN | Qty note |
|---|---|---|
| J15 mating plug (MC 1,5/10-ST-3,5) | Phoenix **1840447** | same PN as J3's plug — coding is what tells them apart |
| J16 mating plug (MC 1,5/6-ST-3,5) | Phoenix **1840405** | same PN as J13's plug — ditto |
| Coding profiles | Phoenix **CP-MSTB 1734634** | 6 per coding star; code J3@pole 1, J15@pole 10, J13@pole 1, J16@pole 6. **Install corrected 2026-07-21 (H7): profile fits the PLUG (or an inverted header), never pressed into a standard G-3.5 header; header side = remove the coding rib at the matching pole. Sacrificial-pair proof (FA-8) before coding production parts.** |
| Harness band colors | — | J3 white · J15 yellow · J13 white · J16 blue |
- Plus the rev-C mating set (J1 IDC socket candidate, J3/J4/J5/J13/J14 plugs) — carry the
  rev-C §3 table; the BOM gap does not get a third occurrence.
- **Coding profiles must be FITTED before first article** — the first-article gate includes
  the physical cross-mate refusal test.

### G14 — Overall review of the rev-D docs + spec  `[x]` **CLOSED 2026-07-26**
- Change list + spec + this checklist + run log — **plus** `phase8_revD_r6_input_protection_spec_2026-07-25.md`,
  which postdates this gate's original wording and is now part of its scope.
- **Review performed by Claude on the owner's instruction (2026-07-26), on top of the
  10-dimension pre-order audit** (`phase8_revD_PREORDER_FINAL_AUDIT_2026-07-25.md`, 51 findings
  independently verified, 33 confirmed / 18 refuted). Everything the review found actionable
  has been fixed and committed, not just noted:
  - Ten live files pointed at the superseded `_r5/` package (bare opto inputs) — **corrected**.
  - The rev-C `JLC_UPLOAD_READY/` packet had no tombstone and `phase8b_revB_fab_order_checklist.md`
    pointed at it — **tombstoned and bannered**.
  - 520 board-side connectors were on no purchase list — **backplate BOM §A′ added**.
  - Harness wire list lengths were short and J14 ferrules unbuildable — **Rev 3 issued**.
  - The 10 M pin (C26108) was OOS and export-fatal — **re-pinned to C2933281, r8 exported**.
  - The stale ~1.7 mA FA-9 operating point was still quoted alongside the r6 design — **corrected
    to 1.34 mA / 1.12 mA** in this checklist and the manual's opto chapter.
- **Open decisions previously parked here, now resolved** (see the DECISION RECORD at the head
  of this file): OG-1/G8 enclosure purchase, the 24 VAC population question, FA-9 disposition.
  **Still parked:** the G7 waiver-or-session choice and the deferred OUT-B override
  (change-list item G) — neither blocks the fab order.
- **J16 polyfuse is FITTED** (F1, Codex R2-4) — no longer an open option; the module
  allowance was re-derived **100 mA → 45 mA @ 85 °C worst case** (R3-7, run-log FR-15).
  A substitute is accepted only if its **minimum Ihold at 85 °C is ≥90 mA**;
  trip-current equivalence is never sufficient because PPTC trip is not a hard clamp.

### G15 — EXPERIMENTAL FIRST-ARTICLE order acceptance  `[x]`  **SIGNED 2026-07-27 (Dylan)**
- This spin ships as an **experimental first-article validation build**, not a fleet
  release (R3-8). The 47 kΩ input hardening reduces required sink current to
  56.2 µA, but the UMW PC817 lot is proven empirically only AT first article by
  the upgraded **FA-9** hot/min-voltage capability, leakage, and timing
  qualification, after the RP2040/MCP internal-pull-zero runtime proof
  (spec §R4); the tap safety gate is proven only by the
  at-temperature **OG-4** repeat.
  Both are physical gates that cannot be discharged before boards exist.
- **To close this gate — Dylan appends the acceptance line below** (mirrors the blank
  OG-1 sign-off line in the run log). Signing accepts placing an EXPERIMENTAL order whose
  fleet-release status is contingent on FA-9 + OG-4 passing on the physical boards.

  `EXPERIMENTAL-ORDER ACCEPTANCE:` **SIGNED OFF — Dylan DeYoung, 2026-07-27.**
  Accepted at **FLEET quantity (34 boards)**, experimental first-article status understood,
  fleet-release gated on **FA-9** numeric V_CE and **OG-4** at-temperature tap injection.
  FA-9 de-gated as a *pre-order* blocker on the ~5x worst-case-stacked CTR margin (see the
  margin table above); it is still to be executed at first article. OG-4 remains OPEN and is
  **not** de-gated. Both fleet-revision items (0.4807 mm field-pin clearance, zero
  `FIELD_WET_V` bulk capacitance) are inert under the N = 0 driven-24-VAC decision recorded
  as DECISION RECORD item 2.

> **⚠️ OWNER DECISION RECORDED 2026-07-26 — ENTERED BY CLAUDE ON THE OWNER'S INSTRUCTION,
> NOT A SIGNATURE. Dylan should countersign the line above to close this gate formally.**
>
> **Decision: proceed at FLEET quantity (34 boards), not a staged first article.**
> Instructed by Dylan on 2026-07-26 ("we want to order fleet now"), reaffirmed after the
> exposure was laid out in full.
>
> **FA-9 dispositioned to FALL as a pre-order gate** (Dylan, 2026-07-26: *"we will allow this
> gate to fall"*), on this margin stack:
>
> | Step | Value |
> |---|---|
> | Required sink, 47 kΩ at 3.3 V to V_OL 0.66 V | 56.2 µA |
> | I_F at the FA-9 loaded minimum | 1.12 mA |
> | **Required CTR** | **5.0 %** |
> | PC817**B** rank at 5 mA | 130–260 % |
> | × low-current derate (~1.1 mA, ~0.5×) | ~65 % |
> | × hot derate (70–85 °C, ~0.8×) | ~52 % |
> | × end-of-life LED degradation (~0.5×) | ~26 % |
> | **Worst-case-stacked margin** | **~5×** |
>
> Failing needs roughly a **10× miss against the rank spec** — a mismarked/counterfeit-part
> scenario, not a design-margin one. Even un-ranked A-grade (80–160 %) still lands ~3×.
> The gate existed because the UMW datasheet lacks a *guaranteed* minimum at this operating
> point — a documentation gap, not an engineering red flag.
>
> **FA-9 is NOT cancelled — it is de-gated.** Still run it on the first articles as the formal
> close, and record the numbers. A zero-lead-time pre-check is available and recommended:
> rev-B board #1 and the rev-C boards carry the same PC817 in the same DIP-4 footprint, and
> their **10 kΩ pull-up sinks 264 µA versus the real 47 kΩ's 56 µA — a 4.7× harder test.**
> Passing in-situ on existing hardware is therefore a conservative proof of the r6 design,
> needing only a bench supply, a DMM and a hot-air gun.
>
> **OG-4 (at-temperature tap fault injection) remains OPEN** and cannot be discharged before
> boards exist. It is not de-gated — execute it on the first articles.
>
> **What makes fleet quantity defensible:** both "fleet revision" items — the 0.4807 mm
> field-pin clearance and the zero `FIELD_WET_V` bulk capacitance — are **conditional on
> driven 24 VAC channels**, and the 2026-07-26 population decision (see DECISION RECORD, item 2)
> sets **N = 0**. With no channel in 24 VAC sense mode both items are inert, so these 34 boards
> are **not** copies of a revision already committed to change.

### G16 — Positive-actuation return bound MEASURED on the target Pi  `[ ]`  **(software; blocks LIVE, not fab)**

`controller_io.POSITIVE_ACTUATION_MAX_S` (default **0.050 s**) bounds how long a
safety-positive actuation — sweep-on / table-on / spot-on / arm-high / the NE555 watchdog
kick — may take to return. **Exceeding it turns the motor OFF mid-motion and escalates to
`_hard_safe` + MANUAL_INTERVENTION, which requires a physical PBZ to clear.**

**The 0.050 s default is an ASSERTION, not a measurement.** Nothing measured actuation
return time on a Raspberry Pi. The sample is taken with wall-clock `link.now()` around a
call made from a thread competing under the CPython GIL with the serial reader, DiagWriter,
PlatformHealth (which forks `vcgencmd` every 60 s), CycleShipper, and async recorder dumps —
so it includes **scheduling preemption**, not just I²C/GPIO transport. Exposure is roughly
2 boards × 50 Hz ≈ 100 evaluations/s (~8.6 M/day/Pi) for the watchdog kick alone, so a
per-event probability above ~1e-7 is a **daily lane stoppage**.

This project has already shipped this exact bug twice — `TAP_KICK_STARVE_MS` set below the
real kick cadence, and a PlatformHealth poll cadence that false-expired healthy lanes. Do
not ship a third guessed timing constant.

**To close this gate:**

```bash
# ON THE PI, with the daemon's peer threads running (or matched via --threads):
python3 scripts/measure_actuation_bound.py --seconds 900 --json /tmp/actuation.json
```

- `[ ]` Report attached to `phase8_revD_run_log.md` (paste the JSON).
- `[ ]` If the recommendation exceeds the 0.050 s default, set **both** env vars in
  `/etc/wsl-lane-node.env` before LIVE:
  `WSL_POSITIVE_ACTUATION_MAX_S` and `WSL_WATCHDOG_KICK_MAX_S`.
  Both **fail LOUD** (ValueError at import, before hardware opens) on garbage or
  out-of-range values — they never silently restore the default.
- `[ ]` If the recommendation exceeds the permitted ceiling (0.500 s), **do NOT raise the
  ceiling.** The platform is too jittery to run the control loop as-is; fix the jitter
  (thread count, fork cadence, CPU governor, `isolcpus`) and re-measure.

**Already fixed in code (2026-07-25):** the watchdog kick no longer shares the write budget.
Its body deliberately blocks for `WDOG_PULSE_S`, so `BoardController` now passes a derived
`WDOG_PULSE_S + POSITIVE_ACTUATION_MAX_S` budget — charging a deliberate sleep against a
transport budget was a category error. Note also that a genuinely late kick is already
handled **in hardware**: the NE555 simply does not get its pulse and drops the rail. The
software bound is defense in depth and must not be the thing that stops the lane on
scheduler jitter alone.

### G17 — r6 input protection: release-gate integrity + the stuffing decision  `[~]`  **(new 2026-07-25)**

r6 put 120 parts on 40 channels and the whole safety case is *which* part is *where*.
This gate collects the checks that make that verifiable rather than assumed, and records
the one stuffing decision the crew is allowed to make.

- `[x]` **Per-channel equality gate in the export, not just totals.** The pre-r6 gate
  asserted counts (391 / 68 / 323 / 306). Totals cannot distinguish *40 series diodes +
  40 clamps* from *80 clamps and no series diode* — the exact failure the design rejects.
  `export_fab_revD.assert_r6_input_protection()` now proves, per channel:
  `FIELD_RIN_<n>` = `Rin.2` + `Dser` **anode**; `FIELD_LED_<n>` = `Dser.K` + `Dclamp.K` +
  PC817 anode; the field pin carries the `Dclamp` **anode** + PC817 cathode; every
  `Dser`/`Dclamp` POPULATED and present in placed **and** CPL **and** JLC; every `Cflt`
  DNP and absent from all three; 8 × 10 nF fast / 32 × 2.2 µF slow; and **no r6 part on
  `FIELD_WET_V`, `RELAY_ENABLE_RAIL`, `RAIL_GATE`, `SAFE_STOP_RETURN` or
  `SAFE_TBSC_RETURN`** (standing prohibition X3). A DNP `Dser` is an explicit STOP-SHIP
  message, not a count mismatch.
- `[x]` **One diode line, hard-locked.** All 88 placed `1N4148` (8 pre-r6 + 80 r6) must map
  to a single onsemi 1N4148WS / `D_SOD-323` / LCSC **C118873** line with the exact
  designator string. This is what makes "zero new JLC-assembled part classes"
  (`EXPECTED_JLC_LINES` = 27) a checked claim instead of a comment. `D13` (`Dfly_M1`) is a
  1N4148 too but is DNP, so it is compared against the **placed** set — that asymmetry is
  deliberate and is the one bug this gate already caught on itself.
- `[x]` **Field-stuffed MPNs locked.** `PART_LOCK` only ever covered parts *JLC* fits, so
  the 40 `Cflt` lands had no bought identity at all. `FIELD_STUFF_LOCK` now pins
  2.2 µF = Samsung **CL21B225KAFNNNE** / LCSC **C19110** (FR-17) and 10 nF = TORCH
  **C0805B103K500NT** / LCSC **C17702767** (FR-18), and those identities are emitted into
  `assembly/*-dnp-excluded.csv` **in the same row as the "do not fit" reason**. 1 µF
  (C28323) is REJECTED on the record: 749 nF effective < the 951 nF 60 Hz floor.
- `[x]` **The stuffing decision is written down and is one line long.** All 40 channels take
  `Dser` + `Dclamp` **POPULATED — uniform, no per-channel decision, no per-lane record to
  lose across 32 lanes.** The *only* decision is the DNP `Cflt`, and it is
  **measure-then-stuff**: `docs/phase8_revD_r6_channel_stuffing.csv` (also in the package)
  carries, per channel, the connector pin, all five refdes, the evidence class
  (MEASURED / UNMEASURED / SPARE), the measured value or the machine-side prior, and the
  exact measurement that decides it.
  - **MEASURED, decided:** GS1–GS10 + BS (11 VDC dry) · **PBZ** (33 VDC) ·
    **DIELL_L / DIELL_R** (15.4–16 V). All DC ⇒ **`Cflt` stays UNFITTED**; `Dser` +
    `Dclamp` are what make PBZ and DIELL landable at all.
  - **UNMEASURED, measure-then-stuff:** cams **SA/SB/SC/TA1/TA2/TB** · **FOUL** · **GP** ·
    **PBC** · **OS** · TENTH + the four MAN_* · AUX1–AUX11 (spares).
  - **The decision rule, in full:** V_AC < 1 V rms ⇒ DC class, leave unfitted whatever
    V_DC reads. V_AC ≥ 5 V rms on a **SLOW** channel with a ≥ 200 ms release budget ⇒ fit
    2.2 µF and re-run FA-9 edge timing. V_AC ≥ 5 V rms on a **FAST** channel ⇒ **never fit
    a cap**: 60 Hz integration needs ≥ 951 nF ⇒ 183 ms de-assert against a 1 ms edge
    budget. That channel is *survivable, not usable* — tap it at the switch or change
    firmware (r6 spec §B.4).
- `[ ]` **FA-16 unpowered orientation + continuity census, 40/40, volts recorded.** New
  first-article gate (pack §4). Two-direction DMM probe per channel: forward
  ≈ 1.75–1.95 V (`Dser` + LED in series) and reverse ≈ 0.60–0.75 V (`Dclamp` alone). Run
  **before FA-1**, on the bare board. This is the only gate that catches a **reversed
  `Dser`** before the channel is silently dead, and it catches a **missing `Dclamp`**
  without needing a live machine.
- `[ ]` **FA-15 driven reverse-bias proof** on every channel that can go reverse-biased
  (PBZ at 33 VDC is canonical): LED node must read **0.35 V ± 0.1 V** reverse — and
  **> 1 V means the clamp is missing/open/reversed, STOP.** Record millivolts, not "PASS".
- `[ ]` **Record N**, the count of channels metered as *driven* 24 VAC. The `FIELD_WET_V`
  budget assumes **N = 0**; **N ≥ 1 reopens it** (16.8 mA peak/channel, zero bulk
  capacitance, ≤ 11 coincident channels before the TMA-0505S runs out). Scope TP4.

---

## 2. FIRST-ARTICLE QUALITY GATE (per assembled rev-D board, before trusting it)

Carry the rev-C §4 gate wholesale (rails → i2cdetect → one relay → all six), then add the
rev-D extensions. One channel of each NEW I/O type must pass before trusting the board
(process item 11).

- `[x]` **⛔ Per-board test documents for rev-D refdes — REGENERATED (2026-07-21, Codex
  M6):** `docs/phase8_revD_first_article_pack.md` + `docs/phase8_revD_first_article_
  refdes_map.csv`, generated programmatically from the rev-D netlist + routed board by
  `scripts/generate_first_article_docs_revD.py` (re-run it after ANY netlist/placement
  change — derived docs, never hand-edit). The pack carries the 46-row REFDES_SHIFT
  table (ISO_WET U37→U45, U_WDOG U36→U44, rail-gate pullup R106→R124 …), the relocated
  TP map, the FA-1…FA-14 procedures (incl. the R1.9 tap fault injection with the
  ≥ 70 °C repeat, the GPB poke, the ADC read, cross-mate refusal + sacrificial-pair
  coding proof, and R4 V_CE sampling). **Every rev-C bench artifact still names WRONG
  parts on a rev-D board — use ONLY the rev-D pack at the bench.**

- `[ ]` **FA-13 Stop / pit-interlock system gate (P0):** do not jumper J14.3–4
  at the machine. Approve and meter the fail-safe Stop/control-power interface,
  determine whether another pit-entry interlock exists on lanes 21/22, and
  obtain the qualified install-versus-Stop+LOTO-only disposition. Prove Stop
  drops master/control power and TP16 within the recorded bounds. Prove every
  installed/new pit interlock separately in its approved upstream
  safety-disconnect path; a J14-only switch is not sufficient. Exercise every
  monitor open-wire/proof control. Execute the per-lane Candidate-C TB/SC G3
  insertion proof: command S and T separately from the board with both levers
  BACK/open, prove each coil dead, verify the OEM ladder was not bypassed, and
  capture the exact result in the signed commissioning latch. Record the
  periodic retest owner; the manifest-controlled interval is **365 days
  maximum**, and expired evidence blocks healthy monitor status.
- `[ ]` **FA-14 mains-integrity gate:** a qualified electrician verifies
  protective-earth continuity/bonding and hot/neutral polarity with a listed,
  in-calibration external tester. Board rails and `control_power_ok` do not
  satisfy this gate; mains/PE test current stay outside Rev-D. Repeat at the
  manifest-controlled interval of **365 days maximum**, and sooner after
  relevant electrical service; expired evidence blocks healthy monitor status.

- `[ ]` Rails at TPs — **NEW: TP4 unloaded reads ≤ ~6 V** (item A landed; 11–14 V float
  gone — if TP4 still floats high the bleed is missing/open). TP4 under opto load ≥ ~4.5 V.
  Regression: TP5↔TP2 still OPEN (isolation).
- `[ ]` `i2cdetect -y 1` → 0x20 / 0x21 / 0x22.
- `[ ]` **FA-9 input-bias runtime proof:** with the exact production release,
  record RP2040 GP6–GP13 pad readback and require PUE=0/PDE=0 on every fast
  input. Read U1/0x20 and U2/0x21 MCP23017 `GPPUA`/`GPPUB` and require all four
  bytes `0x00`; `MachineIO` must refuse startup on a write/readback mismatch.
  Do not apply the 47 kΩ numeric limits if this gate is not green.
- `[ ]` 6-relay make/break via `lane_node/bench_first_article.py` (K7 DNP for M1).
- `[ ]` **USB (item B):** ordinary unmodified micro-B cable fully seats with the J1 ribbon
  MATED; BOOTSEL reachable; UF2 drag-drop flash succeeds WITHOUT the hand-shaved cable.
- `[ ]` **GPB bank read test (item C):** poke each of J15 pins 1–8 to FIELD_GND; the
  matching GPB0–7 bit on 0x21 reads active-low; all 8 channels, no cross-talk between
  adjacent rows.
- `[ ]` **Divider ADC read (item D):** GP26 reads VCC_5V/2 within ±3 % of the TP1 DMM
  value; energize 6 coils and confirm the sag is visible in the ADC trend.
- `[ ]` **Rail-tap test (item E — REDESIGNED per remediation spec R1; full procedure =
  spec R1.9, which GOVERNS this line item):**
  - **level survey (cold):** scope each `TAP_GATE_*` gate node and `TAP_*` drain node
    through the full signal swing; gate-high ≥ 3.0 V typical expected (worst-stack
    margins per spec R1.5); reads are INVERTED (observed HIGH ⇒ pad LOW);
  - **unidirectionality proof (cold):** FI-1 bench build drives each GP16–19 output-high
    with J1 unmated (driver high-Z) — each observed net must not move > 1 mV; rail must
    not arm;
  - **fault insertion (cold):** clip-short each tap FET drain-gate (F3/F4), repeat; then
    with the emulator arming normally, go high-Z with the short applied — rail must drop
    within the normal watchdog window;
  - **AT-TEMPERATURE repeat (gate OG-4 — MANDATORY, a cold-only pass does not discharge
    it):** heat the Q_AND_ARM / Q_AND_RP_OK / Q_RAIL region AND the four tap FETs to
    ≥ 70 °C case (thermocouple-verified, hold ≥ 2 min); repeat the high-Z + D-G-short +
    stuck-high-GPIO stack — rail must neither arm nor hold, and a driven ARM_PERMIT
    disarm must still drop it;
  - **edge-order proof (fw v1.2):** forced Pi-death and forced kick-starvation each
    produce the documented edge ORDER in the 1 ms ring, and the record survives a Pico
    reboot (epoch semantics, spec R3.3).
- `[ ]` **J16 bus check (item F):** scrap ADS1115/INA219 module on J16 → module AND
  0x20/0x21/0x22 all still ACK; bus rise-time spot-check with the module attached.
- `[ ]` **Cross-mate refusal test (OG-3 / first-article pack FA-8):** FIRST the
  **sacrificial-pair proof** (spare plug + scrap header: coded pair seats, coded plug
  refuses an uncoded header, no adjacent-pole damage — the CP-MSTB profile fits the
  PLUG, never a standard header; corrected 2026-07-21, H7), THEN each production coded
  plug physically REFUSES the wrong header — J3-plug vs J15 header, J15-plug vs J3,
  J13-plug vs J16, J16-plug vs J13.
- `[ ]` Firmware review assert (item E binding, now fw v1.2 / remediation spec R3):
  GP6–GP13 internal pulls disabled (the external 47 kΩ is authoritative);
  GP16–GP19 inputs-only ENFORCED (`tap_assert_input_only()` register-readback + the
  build-failing host direction test), Schmitt enabled, inversion in exactly one
  `tap_read()` accessor; deliberate disarm drives ARM_PERMIT low, never tristates; the
  FI-1 fault-injection build is excluded from the release artifact and refuses to run
  without its physical jumper. (Firmware is the separate C2 task; this line refuses a
  first-article pass without the check.)

---

## 3. WHAT REMAINS BEFORE A FAB ORDER (plain-English summary)

1. **Dylan signs off (or declines) the 240 mm board** — G8/OG-1. The enclosure re-check
   half is **RESOLVED with evidence (2026-07-20: nothing purchased, Layout D re-math fits
   the incumbent SCE-30P24 with 16 mm to spare, ribbon shift is noise)** — what remains is
   his decision itself. Declining means a 36-row re-spin of placement + counts **and
   discarding the routed artifact (full re-route)**. Row-39 bottom-edge copper proximity
   is a carried constraint on the eventual enclosure lip/backplate design.
2. **Resolve or waive rev-C items 6–7** — G7 (powered at-machine metering session, which is
   already the queued next field step for machine 22).
3. ~~Route the board~~ **DONE 2026-07-20 (G9+G10: DRC 0/0/0, routed-mode audit ALL PASS,
   RD-VIA-1 power-via redundancy, independent 8-check verification pass) — but routed OUT
   OF ORDER while G8 was open (run-log PV-1); the artifact is conditional on Dylan's G8
   sign-off.**
4. ~~Write `export_fab_revD.py` and export~~ **DONE 2026-07-21 (G11 `[x]`:
   `kicad/fab_revD_2026-07-21/` hashed package, equality asserts 262/27/235/218, D_PROT
   locked to MDD SS34 C8678)**; inspect Gerbers + JLC preview — G12 still open (include
   the five doubled power vias + the row-39 bottom edge in the visual pass).
5. **Order the harness/coding parts with the boards** — G13 (the BOM now exists:
   `docs/phase8_revD_harness_bom.csv`; the order itself is still to be placed).
6. **Final sacred-file hash re-verify + Dylan's review** — G6 (re-run) + G14, **plus the
   G15 EXPERIMENTAL-ORDER acceptance line** (R3-8: this is a prototype validation build,
   not a fleet release, until FA-9 numeric V_CE + OG-4 at-temp pass on real boards).
7. **After assembly, the §2 first-article gate** — the per-board test docs are already
   generated for rev-D refdes (M6, 2026-07-21: `docs/phase8_revD_first_article_pack.md`;
   re-run the generator if the design moves), and the gate includes the MANDATORY
   at-temperature (≥70 °C) rail-tap repeat (OG-4) plus the FA-8 sacrificial-pair coding
   proof AND the upgraded **FA-9 numeric per-channel PC817 V_CE / margin qualification**
   (R3-8 — the experimental-order gate). The characterization session (analog population,
   DC1–DC3) is scheduled but not fab-blocking.

Not fab-blocking but scheduled: the **characterization session** that decides external
analog population (CT current channels, 24 VAC sense, temp channels — all on the external
module path, never on-board), and the software companions (IN_B_MAP + self-test extension,
heartbeat adc field, tap edge-capture firmware) which live in the separate 2026-07-19
diagnostics software campaign and its own review gates.
