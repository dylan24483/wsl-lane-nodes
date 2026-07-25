# Phase 8 — Diagnostics Target-Conditions Catalog **v1.3** (2026-07-19, rev. 2026-07-24)

> **Status: v1.3 reconciliation — companion to `phase8_diagnostics_scope_2026-07-19.md`.** The 2026-07-24 working trees include the software platform and fail-visible delivery/backup controls described in that document’s current status banner. §§1–6 remain the condition inventory; a listed condition is not field-proven merely because its transport or event vocabulary exists. Cam polarity/lobes, post-spot camera/gripper cross-checks, OS tracing, external motor-current sensing, the physically open J14.3–4 Stop/control-power landing, demand-to-control-power-drop proof, the lane-21/22 C.I.S.-absent/pit-entry-interlock disposition, protective-earth/supply-polarity commissioning, and assembled-board first-article evidence remain open. See `phase8_revD_round4_remediation_report_2026-07-23.md` for the current source/physical boundary.
> **Rev-D r5 electrical/configuration amendment (2026-07-23):** the §4 IN-B GPB expansion now records the released 47k PC817 collector pull-up value and its every-channel loaded-minimum/hot qualification gate; the earlier 10k planning value is superseded. The external pull-up is authoritative only with RP2040 GP6–GP13 pulls disabled and both input MCP23017 GPPUA/GPPUB registers commanded/read back `0x00`.
> Provenance: 3-agent deep dive (82-70 failure-mode mining from the full AMF service/operation manual text extracts · rev-D delta grounded in the netlist generator · machine-sensor survey) → synthesis → adversarial critic. The critic's 10 findings are **integrated** below (notably: a rev-D item that would have loaded RELAY_ENABLE_RAIL was removed; rudder/lift attribution was inverted and is fixed; foul-detector, shorted-cycle-button, and welded-M-relay failure modes were missing and are added; coverage arithmetic recounted).
> Ground truth follows the scope doc throughout: zero ADC on rev-C · motor current never crosses the PCB · the harness exposes one non-isolatable live-ladder region at C2A-U with no independent TB/dry J_SAFE landing · J14.3–4 is physically OPEN in the authoritative harness, so the rail cannot arm until a validated Stop/control-power design is landed · physical inspection found no C.I.S. device/wiring on lanes 21/22 and another pit-entry interlock is unconfirmed · powered OEM behavior is **parallel closed-when-safe**, danger = both levers BACK/open, and Candidate C’s OEM ladder is the primary guard · per-cam interlock attribution is unavailable on this chassis · remaining cam polarity/lobe calibration is not physical proof · AUX1-3 = the only spare populated inputs · GP11 vacant but contested · camera pin-mask + GS map field-validated · safety/status taps observe-only · board/control power does not prove protective-earth continuity or hot/neutral polarity.
> **Round-5 release-candidate amendment (2026-07-24; locally tested, not deployed):** the daemon now has an exact-one SHADOW/LIVE startup contract, a lifetime controller-owner lease before hardware access, fail-safe ARM prerequisite latching with fresh-PBZ recovery, exact `board|build|cfg` qualified-release authorization (no independent-list cross-product), and expanded identity/tap/platform heartbeat truth. Diagnostic incidents, exact-family recoveries, service-start obligations, and cross-service relays retain restart-stable identities in bounded fail-closed ledgers. The server exposes unresolved warning/fault conditions without hiding them behind the single legacy fault latch. The WSL release path validates those conditions strictly, includes every restart-critical Pi ledger in backup/restore, and requires signed identity-bound per-lane FA-13/FA-14 commissioning evidence before the overall Phase-8 monitor can be healthy. These remain source/test claims pending committed-release verification, Pi deployment, and Rev-D first-article/bench proof; an attestation records qualified evidence but does not create it.

**Capture-class legend:**
`existing-signal` = fires on deployed code today · `firmware-rule` = new software/firmware rule on already-wired signals (Phase 1-3) · `timing-trend` = cam_telemetry baseline drift (needs Phase 1.7 persistence) · `camera` = T-Camera cross-check detector (Phase 3) · `add-on-sensor` = new machine-side sensor, no respin · `rev-D-dependent` = requires a board spin · `human-only` = no proposed capture; **(final)** = stays human-only even with every proposed addition.

---

## 1. Target-condition catalog

### 1.1 Cushion & cycle start (SS → DIELL)

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Pin jam under cushion (OEM: continuous recycle) | DIELL `beam_blocked` rule (level asserted > N s while READY, GP12/13) + inter-cycle-gap < baseline-p1 cadence rule — the classic AMF signature does NOT transfer to beam sensing | firmware-rule | Medium — signature must be re-derived (scope §1; svc_text.txt:4246-4248) |
| Shorted cycle button / 10th-frame button → continuous cycling | Machine cycles with **no DIELL ball events** = the discriminating signature (a real ball always breaks the beam first); PBC/10th land on IN-B → stuck-input rule must extend to IN-B when its read path lands (Phase 1) | firmware-rule | High once IN-B read path exists (svc_text.txt:4249-4257) |
| Start sensor dead (DIELL misaligned/dead/unpowered) | Absence-of-signal: lane-occupied-but-no-ball-events heuristic (wsl_api occupancy cross-reference); open circuit reads "condition absent" by design | firmware-rule (weak) | Low — absence faults always need cross-evidence (svc_text.txt:4215-4232) |
| Cushion leather stretched / rivets broken / bounce-plate loose | Ball-return exit beam: per-ball return-time trend (T0=DIELL, T1=exit) | add-on-sensor (human-only today) | Medium once sensor lands (svc_text.txt:4182-4189) |
| Shock absorber bind/faulty | None — manual inspection per remedy; SS retired from read path | **human-only (final)** | — (svc_text.txt:4230-4232) |

### 1.2 Ball lift, kicker, rudder & exit — the fully uninstrumented class

Every mode below is customer-report-only today. **One shared exit photoeye per pair** (the lift is shared between both machines via overrunning clutches, svc_text.txt:117-125) + per-lane DIELL T0 correlation covers the whole class *as a class*; component attribution stays human. **Attribution logic (corrected):** the rudder alternately blocks one machine's ball opening while admitting the other's — a jammed rudder kills **ONE** lane's returns; a lift/belt/drive failure kills **BOTH**. **Pilot-topology caveat:** the shared lift may be driven by *either* machine's BE through the overrunning clutches — during the pilot (pair-mate still on the OEM chassis), machine 22's BE dying does not stop the lift, and lift mechanical load can ride the other motor. BE-current and return-time inferences must account for the pair-mate.

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Ball-lift clutch slipping/worn/broken | Shared exit beam: returns counted vs per-lane DIELL ball events; missing return = fault; BOTH-lanes-dead pattern | add-on-sensor | High detection, human attribution (svc_text.txt:4257-4292) |
| Lift belt tension low / V-belt slip / tightener spring broken | Exit-beam return-time rising trend (the 4-4.5 in spring spec is a PM measurement, not a signal) | add-on-sensor | Medium (svc_text.txt:4276-4302) |
| Ball idles at exit / won't enter lift (kicker, guide plate, exit assembly) | Exit beam: that lane's return absent/delayed, pair-mate healthy | add-on-sensor | High detection, no attribution (svc_text.txt:4190-4214) |
| Rudder jam / rudder drive faults | Exit beam + DIELL correlation: **one lane's returns dead, other healthy** | add-on-sensor | Medium (svc_text.txt:117-125) |
| Drive-pulley set screw loose | Exit beam (intermittent return failures) | add-on-sensor | Medium (svc_text.txt:4262-4265) |

### 1.3 Sweep assembly

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Sweep stall (drive bind, motor failure, linkage jam) | SWEEP_TO_GUARD/RUNTHROUGH > MAX_MOTION_S=8.0 → latched FAULT (`cycle_control_8270.py:66-69,400-422`) + firmware MAX_MOTION_MS backstop; SB/SA edges GP7/GP6 | existing-signal | High — the designed-for class; H-02 caveat (timer resets per transition) until per-motor energized-time lands |
| SA cam maladjustment (continuous run / double-sweep) | Unexpected-SA-edge counting (else-branch rule) + motion timeout; ta2_to_sa baseline precursor | firmware-rule + timing-trend | Low until §3.2 polarity capture + TA1/SA lobe disambiguation, then High (svc_text.txt:3982-3996) |
| SB cam maladjustment (won't hold guard / parks in table path) | State-named motion timeout; guard-interval drift precursor. Which OEM interlock contact blocked motion is **permanently unattributable from this harness** (one live-ladder region, no independent TB signal) | existing-signal (degraded) | Medium (svc_text.txt:4015-4029) |
| SC cam maladjustment (table half-down, both motors dead) | Expresses only as TABLE_DETECT timeout. Candidate C’s OEM parallel-safe ladder is primary; the default-off two-input firmware echo has no independently wired TB observation and is not validated protection. | existing-signal (weak) | Low attribution, permanent (svc_text.txt:4030-4036) |
| Sweep linkage / connecting rods out of adjustment (wrong stops, frame strikes, plausible cam signals) | None reliable — cams can read normal with wrong geometry; camera FOV over the sweep is **unverified** (one annotated frame resolves it) | **human-only** (conditionally camera) | — (svc_text.txt:4037-4044, 4088-4112) |
| Sweep hits gutter at 66° (worn bumper 7283) | None — audible/visual only | **human-only (final)** | — (svc_text.txt:4003-4009) |
| Sweep drive degradation (belt stretch, gear-lube loss) | ss_to_guard / ta2_to_sa Welford baselines, 4σ + 0.15 s drift — the explicit cam_telemetry design intent | timing-trend | High mechanism, zero persistence until Phase 1.7 |

### 1.4 Table — respot cells & gripper switches

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Respot cell won't pick up / drops pins (rod, finger gauge, linkage) | Per-pin GS-mask (latched at TA2) vs camera standing-pin-mask disagreement counter; camera-health anchor required for cell-vs-camera attribution | camera | High once built — both sensors field-validated (svc_text.txt:3871-3883) |
| GS stuck asserted (wire grounded — phantom standing pin) | GS-vs-camera disagreement + mid-session stuck-input rule (startup detection already live, `controller_daemon.py:260-279`) | camera + firmware-rule | High (svc_text.txt:3919-3927) |
| GS dead / wire open (pin-8-only leave → mask==0 → false STRIKE → rack swept onto standing pin) | Camera is the ONLY cross-evidence — open contact reads "condition absent" by design; per-pin persistent-disagreement counter | camera | High once built (03_machine-sequence.md:220; svc_text.txt:3928-3941) |
| GS contact oxidation/dirt (documented wear surface) | Per-pin disagreement-RATE trending | camera (trend) | Medium — months-scale (04_machine-io.md:75-102) |
| GP switch/cable open ("will not feel for pins") | GUARD_DELAY held past GUARD_DELAY_MAX_S → state-named timeout | existing-signal | High (svc_text.txt:3859-3863) |
| Respot-cell protection switch out of adjustment | Same GUARD_DELAY timeout path — indistinguishable from GP-proper without inspection | existing-signal | High detection, human attribution (svc_text.txt:2230-2238) |

### 1.5 Table — spotting cups, yoke, spot solenoid & drive

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Pin falls during spotting (worn base, linkage wear, bent cup, yoke) | Post-spot full-rack camera assert ("10 standing after fresh rack") — doubles as the camera self-check anchor; needs the Track-B post-cycle capture trigger (doesn't exist yet) | camera | High once capture point exists (svc_text.txt:3953-3972) |
| Spot solenoid failure (coil/plunger/linkage) | SPOTTING > 8 s timeout (SP commanded, TA-cam progress absent); cups-fail-to-release lands on camera short-rack. SP pulse-vs-continuous still #CONFIRM | existing-signal + camera | Medium until SP timing bench-confirmed |
| TA1 cam maladjustment (continuous run / stops before zero) | Continuous-run → timeout/unexpected-edge; **stop-before-zero is the nasty case** (edge arrives, table physically off-zero) → sa_to_ta1zero drift is the tell | firmware-rule + timing-trend | Low until polarity capture, then High (svc_text.txt:3894-3903) |
| TA2 cam maladjustment (table never descends / runs past latch) | TABLE_DETECT timeout names the missing cam; mis-latch variant (mask latched at wrong height) → camera disagreement | existing-signal + camera | Medium-High (svc_text.txt:3905-3918) |
| TB cam maladjustment (hard interlock lock-up, pins in air, crank to clear) | Motion timeout only; cam-level attribution **permanently impossible**; crank recovery becomes visible via the IN-B manual-override read path | existing-signal (weak) + firmware-rule | Low attribution, permanent (svc_text.txt:3942-3950) |
| Table connection plug loose | Intermittent GUARD_DELAY timeouts + **bursty multi-pin** GS-vs-camera disagreement (many-at-once = cable, not one cell) | firmware-rule + camera composite | Medium (svc_text.txt:3868-3870) |
| Off-spot pin engagement / OS misadjusted | OS allocated on IN-A GPB3, cavity unmeasured, FSM never consumes it — promote at the Phase-0 cavity trace, then existing-signal; camera partially covers now (off-spot pin drifts off cap ROI, one ball late) | firmware-rule (post-Phase-0) + camera partial | Blocked on cavity trace, then High (svc_text.txt:2258-2272) |
| Table drive / torque tube / support wear | guard_to_table + table_to_ta2 baselines; spotting-accuracy component via camera full-rack | timing-trend + camera | Medium (svc_text.txt:1773-1779) |

### 1.6 Cam position switches (SA/SB/SC/TA1/TA2/TB)

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Cam switch dead | Motion commanded, expected edge absent → 8 s timeout with state name. "Cam dead" vs "motion stalled" needs motor-current cross-evidence (USB-ADC CT on S/T) | existing-signal; add-on-sensor for attribution | Medium today, High with current sense |
| Cam switch chattering | Firmware latched `chatter` fault (>8 debounced edges/100 ms) drops RP_OK — live today; pre-failure chatter TRENDS need bounce-counter export on heartbeat (Phase 1) | existing-signal (binary) / firmware-rule (trend) | High binary, zero trend until export |
| Cam adjustment drift (all six screws) | The six cam_telemetry intervals at 4σ — this IS the trend system; per-edge angle verification blocked on polarity | timing-trend | Medium until polarity + persistence, then High |
| SC+TB interlock trip (both motors dead, crank to clear) | Motion timeout only; the harness produces **no dedicated independently attributable signal**. Powered truth is OEM parallel closed-when-safe contacts; Candidate C + per-lane G3 coil-drop proof is primary. `interlock_collision` remains a default-off secondary diagnostic blocked on observable-window validation. | existing-signal (weak) | Low attribution, partially permanent (8270_text.txt:711-719) |

### 1.7 Bin & shuttle

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| BS switch/lever dead (bins loaded, pins never drop) | BS never closes → TABLE_FINISH > 8 s → FAULT; state name points directly at BS (C2A-CC) | existing-signal | High (svc_text.txt:4068-4074) |
| Shuttle misadjusted / pin holders worn (bad transfer → short rack) | Camera full-rack verification — nothing electrical distinguishes shuttle faults from other short-rack causes | camera | High detection, human attribution (svc_text.txt:2676-2688) |

### 1.8 Distributor

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Won't feed at correct position (cam/pinion mismatch, off-center) | Today: bin-fill class only (BS-late timeout, attributes poorly); bs_to_ta1zero drift precursor; **distributor index prox → AUX3** detects failure-to-index in seconds | existing-signal (weak) → add-on-sensor | Medium → High with prox (svc_text.txt:4121-4132) |
| Continuous feed at one pocket (clutch spring relaxed) | Index-cadence anomaly on the prox; otherwise human-only until starvation | add-on-sensor | Medium (svc_text.txt:4133-4141) |
| Head-first pins to pockets (orienting, dirty wheel, pin rail) | Bin-fill timeout class + camera short-rack on the output side; **upstream cause** stays uninstrumented | existing-signal (weak) + camera; cause **human-only (final)** | Low attribution (svc_text.txt:4142-4164) |
| Front end hits bin (loose hardware, support low) | None committed (USB mic = research channel only, never a detector) | **human-only (final)** | — (svc_text.txt:4165-4173) |

### 1.9 Pin elevator wheel

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Pin jam in elevator (oversized/split pin, seating rod) | Today: downstream BS timeout only; **BE current switch → AUX1** gives the jam-overload signature directly (pair-mate caveat §1.2 applies to lift-load inference, not to the elevator itself — the elevator is per-machine) | add-on-sensor | High with sensor (svc_text.txt:4149-4155) |
| Ring tube / bearing wear (wick-oiled, PM item) | BE current **trend — USB-ADC CT required** (a threshold switch cannot see load creep) and/or gearbox temp; zero visibility today | add-on-sensor (analog) | Medium — trend instrument, weeks of baseline (svc_text.txt:3382-3385) |
| Elevator drive V-belt slip | BE current signature — **USB-ADC-dependent** (slip = load *drop*, jam = load *rise*; a single-setpoint dry contact cannot distinguish); carpet-shaft pulse pickup cross-check later | add-on-sensor (analog) | Medium (svc_text.txt:4279-4283) |

### 1.10 Carpet & pit

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| BE overload → Klixon trip (ENTIRE back end stops; machine looks alive) | **BE current switch on AUX1 — the priority-one sensor add.** Today invisible until the next fresh-rack BS timeout. Debounce the intentional ~30 s post-off BE run (8270_text.txt:467-469) | add-on-sensor | High with sensor; **none today** (svc_text.txt:4270-4306) |
| Carpet belt / roller wear (PM item) | Belt itself human-only; indirect bs_to_ta1zero trend | timing-trend (indirect) / human-only | Low (svc_text.txt:3217-3222) |

### 1.11 Motors, capacitors, Klixons & contactors

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Capacitor open (motor hums, Klixon trips) | S/T: motion timeout with zero cam edges = strong "never started" signature. BE: **none** without current sense | existing-signal (S/T); add-on-sensor (BE) | High S/T, none→High BE (svc_text.txt:4466-4468) |
| Capacitor shorted (braking dead — coasts past every stop) | Firmware `cam_overrun` (stop-cam trip, no STOP in 150 ms) — implemented, **compiled OFF**, gated on polarity capture; interim: post-stop settle drift trend | firmware-rule (armed post-Phase-0) + timing-trend | Low until armed, then High (svc_text.txt:4468-4470) |
| Centrifugal switch open (won't start) | S/T motion timeout (as cap-open) | existing-signal | High (svc_text.txt:4472-4475) |
| Centrifugal switch fails to open (silent overheat, caps may explode) | **USB-ADC amplitude required** (start winding never drops out → running current stays high — a threshold switch set for overload may or may not catch it) or housing temperature | add-on-sensor (analog) | Medium; **invisible without sensors** (8270_text.txt:971-974) |
| Klixon thermal trip (manual reset at motor) | Today: repeated identical same-state timeouts (weak); current switch sees pre-trip overload AND post-trip zero-current; direct Klixon aux-contact sensing unverified (check `8270parts 13-Electrical (1).pdf` — not done) | existing-signal (weak) → add-on-sensor | Medium → High (svc_text.txt:508-511, 3997-4002) |
| Burnt/loose connections (relay contacts, C1/motor plugs) | Rising per-interval variance + intermittent-timeout clustering; physical diagnosis human | timing-trend | Low-Medium (svc_text.txt:4471-4475) |
| Uncommanded motor current (welded relay/contactor, OEM test cable, external feed, or wiring bypass) | Firmware `motion_no_run` (cam edges while nothing commanded) — implemented, default-OFF, nuisance paths, gated on polarity; a current switch detects current with command off. Current proves the unsafe energized state but not its cause. **The safety rail cannot open a welded downstream contact, and the OEM BE test cable can run indefinitely outside desk control — the master breaker remains the physical stop** | firmware-rule (armed) + add-on-sensor | Low today → High state detection, Medium causal attribution (svc_text.txt:4321-4324) |
| Contactor coil open / not pulling in | Motion timeout; current sense separates coil-fault from mechanism-stall | existing-signal | Medium |
| Gear-motor oil degradation (J-156, 5-yr life) | S/T: cam-interval baselines; BE: current/temp trend (USB-ADC) | timing-trend + add-on-sensor | Medium (svc_text.txt:3386-3390) |

### 1.12 Machine wiring, connectors, power & protection

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Wire open on any input circuit | Cams → state-named timeouts; GS → camera cross-check; GP/BS → timeouts; **genuinely silent** for OS and unread IN-B channels until their read paths land | existing-signal (partial) | Medium (8270_text.txt:1018-1045) |
| Wire shorted/grounded (input reads permanently asserted) | Startup stuck-input detection **already live** (`controller_daemon.py:260-279`); mid-session rule = Phase 1 gap; GS shorts also land on camera disagreement | existing-signal + firmware-rule | High |
| Machine dead (M relay open, breakers, manager's switch, no power) | Commands issued + zero cam/beam activity + platform-health tier; **which breaker = human** | existing-signal | High detection; attribution human-only (final) (svc_text.txt:4333-4348) |
| **M path energized after command-off — machine cannot be turned off** | Cam/beam/BE-current activity persisting after power-off command; `motion_no_run` class once armed; BE current switch sees the state immediately. Report `uncommanded_motor_current` with cause `external-feed-or-welded` until independent evidence separates a welded board relay/contactor, OEM test cable, wiring bypass, or external feed. | firmware-rule (armed) + add-on-sensor | Medium → High state detection; causal attribution remains Medium (svc_text.txt:4319-4322) |
| Control-power loss as a distinct fault (blown F1-F3, T1/T2, machine CB) | 24 VAC control-rail sense via the USB-ADC module — turns an indistinguishable timeout cascade into one named fault | add-on-sensor | High with sensor (svc_text.txt:686) |
| C1/C2A/table plug terminal degradation | Variance growth + intermittency clustering; diagnosis human | timing-trend | Low (8270_text.txt:814-816) |

### 1.13 Foul detector unit (machine-external, but in the new signal set)

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Foul input dead (open reads absent — fouls silently never register; league-rules impact) | Weak absence heuristic ("no fouls over N league sessions" vs house baseline) + periodic at-machine test; no strong signal exists | firmware-rule (weak) | Low-Medium (svc_text.txt:412-425, 1138-1153) |
| Foul input stuck asserted (every ball becomes a foul cycle) | Mid-session stuck-input rule on the Foul level + "foul asserted with no DIELL ball event" cross-check | firmware-rule | High (svc_text.txt:412-425) |

### 1.14 Pins (consumable media)

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Splintered/split/oversized pins (machine-handling constraint) | Elevated jam/bin-fill fault RATE metric (indirect); per-pin condition = inspection/rotation | firmware-rule (indirect); **human-only (final)** for the pins | Low (svc_text.txt:208-211) |
| Chipped/worn pin base (falls during spotting) | Camera full-rack catches the fall; pin-vs-machine **attribution needs per-incident pin identity we don't have** | camera (detect); **human-only (final)** attribution | Medium (svc_text.txt:3954-3966) |

### 1.15 Controller platform (scope-doc rows, carried through)

| Condition | Capture method | Class | Confidence |
|---|---|---|---|
| Rail drop / watchdog / service failures | Rail-drop-reason from **existing** high-impedance points (TP8/TP13/TP14), `rp2040_wdt_reset` as distinct code, `vcgencmd get_throttled`, restart counters — both historical field incidents land here | firmware-rule (Phase 1); per-loop gate ordering = rev-D-dependent AND safety-gated (§2 item 6) | High |
| Mechanic-at-machine (alert suppression) | IN-B read path for MAN_T/S/SWS/SWSR + PBC + 10th (hardware-complete, no IN_B_MAP today) | firmware-rule | High once read path exists |
| Camera drift (ROI/lighting/frozen frame) | Full-rack assert failing on known-good racks = camera, not machine (self-check anchor) | camera | High |
| Runtime mode / ARM / firmware identity / tap-heartbeat posture | Working-tree daemon requires exactly one explicit SHADOW/LIVE mode, latches identity/max-run failures safe with fresh-PBZ recovery, requires an exact `board|build|cfg` qualified-release tuple, and includes expanded identity/tap/platform truth in periodic heartbeat processing | **software-in-progress** | Source/tests only; not deployed or physically proven |

**Explicitly excluded:** OEM chassis-internal failures (time-delay PC board, triacs — the "replace P.C. board" rows) — that chassis is what Phase 8 replaces. The foul *detector unit* is NOT excluded (it is machine-external and feeds the new Foul input — §1.13). "Moving deck" is not an 82-70 assembly (deck functions belong to the table). M1/M2 (ball-return relay, sweep-reverse) fault behavior is unknowable until those outputs are commissioned.

**Cross-cutting blocker:** every cam-sequence signature runs at reduced confidence until the Phase-0 powered-session polarity capture lands (all six trip edges default to the `'?'` never-fires sentinel; TA1/SA lobes unresolved; cold reads invalidated by the C2A-N shared common + ~21 Ω sneak paths).

---

## 2. Rev-D delta — what actually has to change on the board

**Framing rule (scope §4): do NOT respin the released Rev-D geometry for diagnostics alone.** Everything pilot-critical fits the AUX-input / external-module path. Rev-D/R5 now exists as geometry evidence, but fabrication, assembly, first-article qualification, and pilot evidence remain open; none of the list below is permission for an unreviewed copper change.

**The motor-current fact, stated plainly:** motor current physically cannot route to the board on ANY revision. The board's G5LE relays switch ~24 VAC control circuits; the machine's contactors switch the 115 VAC motors (phase8b spec §1 "Motor power: Never routed through the PCB"). Current sensors clamp at machine contactor wiring regardless of board design — a rev-D analog front-end could only move the *digitizer* on-board, never the current path. That caps the on-board-analog case at "convenience integration of a signal that already works via AUX dry contact or USB ADC."

### Earns its place (ranked)

| # | Item | Diagnostics unlocked | Design notes | Complexity |
|---|---|---|---|---|
| 1 | **FIELD_WET_V bleed resistor** (rev-C item 5, confirmed absent — `block_supplies()` wires only the TMA-0505S + bulk cap) | Prerequisite for reliable field-side sensor wetting; kills the unloaded float (change list says ~14 V; board #1 measured ~11 V — sources disagree, use per-board measurement) and the TP4 bring-up confusion | 1k-2.2k ≥¼ W across FIELD_WET_V→FIELD_GND in the generator; 2-5 mA of the 200 mA budget. **Interim: external resistor at a field connector — no spin needed** | Trivial |
| 2 | **Pico USB clearance from J1** (rev-C item 3, never landed — placement script still hardcodes the jamming positions) | Field-flashability. The compiled-OFF detectors (cam_overrun, motion_no_run, interlock_collision) and the `'?'` polarity sentinels **guarantee at least one reflash per board after Phase 0**, possibly in-enclosure | Placement move + regional re-route (re-gates DRC + audit). SWD stays dropped per the 2026-06-25 decision — do not silently re-add | Trivial-moderate |
| 3 | **Populate the 8 IN-B GPB opto channels** (PC817B + 2k2 + 47k ×8, new Phoenix connector; GPB0-7 verified unconnected) | Breaks the channel-contention deadlock: ≥5 dry-contact sensor candidates compete for exactly 3 AUX channels. Lands S/T current switches, Klixon aux contacts (if they exist), door/service switches, low-rate index pulses | Standard `opto_input()` pattern; J5 is full so a new left-band connector; +8 channels ≈ 8-16 mA wetting, inside budget; IN_B_MAP + self-test extension ship with the spin. The 47k collector pull-up is the rev-D r4 value and remains subject to every-channel loaded-minimum/hot qualification. | Moderate (~24 parts, zero new topology) |
| 4 | **Board-self-health ADC — VCC_5V only** — route Pico GP26 + ADC_VREF to a LOGIC-domain divider on VCC_5V | Platform tier: 5 V sag under 6-coil load, brownout trending. **Cannot see any FIELD/MACHINE quantity** — complements, never replaces, machine-side sensing | 2-3 resistors + cap in the center band; divider mandatory (5 V net, 3.3 V GPIO rule); heartbeat gains an adc read. ⚠️ **The originally-proposed RELAY_ENABLE_RAIL divider is DELETED** — a divider is a permanent load on the rail and its high-side short would re-reference it, violating the observe-only rule (critic finding 1) | Trivial |
| 5 | **Rail-drop-cause ordering, existing predicate points only** — 1 ms edge-ordered capture of TP8 (WDOG_KICK), TP13 (ARM_PERMIT), TP14 (RP2040_OK), NE555_OUT via spare RP2040 GPIOs | Orders watchdog/ARM/RP_OK cause evidence (wdt_reset vs pi_death vs arm_drop) — both historical field incidents land here. It does **not** read the actual `RELAY_ENABLE_RAIL` outcome. | All LOGIC-domain, existing observable points only (the scope's tap grant). **Per-loop attribution and Q14/J14/output-rail feedback are NOT included** — see items 6–7 | Moderate |
| 6 | **SAFE_* loop taps — heaviest gate, separate decision** | Per-loop attribution (TBSC vs STOP loop) on rail drops. SAFE_TBSC_RETURN has **no test pad at all today**, so this means new copper on a SAFE_ net | Requires a dedicated safety-invariant amendment + FMEA (resistor-short failure mode must be shown incapable of asserting or holding the rail), buffered series-only, downstream-of-pass-FET sensing preferred. **Not a "moderate" line item — do not bundle it silently into a spin** | Major (review burden) |
| 7 | **Actual `RELAY_ENABLE_RAIL` feedback** | Detects pass-FET Q14 stuck-open/stuck-on, J14 source-path mismatch, or a predicate stack that says “safe” while the relay-coil rail disagrees. The present four taps cannot see this outcome. | Keep off the current frozen Rev-D rail copper unless a dedicated observe-only FMEA proves every component/pad/short fault cannot assert or hold the rail. Pilot alternative: a separately protected, galvanically isolated external voltage monitor at the approved rail test interface, returned through a dry diagnostic contact and proof-tested for stuck-healthy behavior. | Major (safety review + physical proof) |

### Nice-to-have

| Item | Why only nice | Complexity |
|---|---|---|
| **24VAC-sense interposer footprints** (1N4007 + 10 µF/63 V + 100 k, DNP, ahead of selected channels) | Enables "machine control power present" as a dedicated channel. Honest status: these parts **do not exist as placed footprints today** — `opto_input()` emits only the dry path; 08_opto-inputs.md §8.3 calls the AC parts "a documented per-channel manual-population option, not separate placed footprints." Interim: external interposer at the harness, or the 24 VAC sense lands on the USB-ADC module anyway (§3 item 6) | Moderate (DNP copper ×N) |
| **OUT-B MCP23017 footprint at 0x23** | Pindicator lamps only — **zero diagnostics yield**; no condition in §1 consumes OUT-B. Capacity insurance | Trivial (chip) / moderate (drivers + connector) |

### Do NOT put on the board (belongs external / at-machine)

- **Isolated machine-analog front-end** — introduces a third isolation-barrier component class requiring new `.kicad_dru` rules (the barrier is currently defined as crossing only inside PC817/G5LE packages), FIELD-room area, and unbudgeted field supply — for a signal whose source (CT clamp) is at the machine anyway. **A USB ADC on the Pi dodges the whole question. Verdict: external, permanently.**
- **True quadrature encoder path** — all 8 fast RP2040 inputs committed; PC817B bandwidth unspecified in every source, so anything faster than once-per-rev likely forces a 6N137-class fast isolator = another new barrier class. The useful fallback — a **once-per-rev index pulse** — needs NO spin (GP11 if the interlock-echo redesign frees it, or an AUX/GPB channel at ms-class latency). Full quadrature duplicates cam-timing trends anyway.
- **Any "current sensing on the board"** — physically impossible, per the framing fact above.

### Constraints (binding on every item)

1. Isolation contract: no machine signal touches Pi/RP2040/MCP pins; LOGIC↔FIELD only inside PC817s (≥2.5 mm), LOGIC↔MACHINE only inside G5LEs (≥3.2 mm); new barrier-crossing part classes need new `.kicad_dru` rules, not just placement.
2. GND and FIELD_GND share zero nodes (audit invariant 5) — including through measurement circuitry.
3. Safety rail observe-only: never load/jumper/re-reference SAFE_*/RELAY_ENABLE_RAIL/RAIL_GATE; no new ARM or rail authority; any tap must be provably incapable of asserting or holding the rail (see item 6's gate).
4. 3.3 V GPIO rule — SAFE_*, RELAY_ENABLE_RAIL, NE555_OUT, VCC_5V are 5 V-domain; every tap needs a divider.
5. Net-class discipline: zero anonymous nets; `audit_revB_board.py` asserts exact class counts and fails closed — apply_netclasses + audit asserts move in lockstep; `.kicad_pro`/`.kicad_dru` sidecars travel with the board.
6. Physical banding: FIELD left / LOGIC center / MACHINE right; planes stay out of FIELD/MACHINE rooms.
7. Power budgets: D17 (SS14) is a 1 A part at ~0.7-0.9 A worst case today; TMA-0505S is 5 V/200 mA/1 W; any field-powered addition must be explicitly budgeted.
8. Fast-input integrity: no slow RC or masking debounce on edge-capable channels — debounce lives in firmware.
9. Rev-C process gates carry forward: footprint-vs-datasheet review per new part (the G5LE-1/-14 bug class); first-article bench test per new I/O type; export to a NEW dated directory.
10. Economics: the 250×225 mm 4-layer is already flagged large and the pre-fleet plan is to relax creepage and SHRINK — diagnostics additions push the other way and must be weighed against the shrink.

---

## 3. Add-on machine sensors — verdict

**Direct answer: YES — sensors on the machine identify fault classes the harness signals + camera can never see**, and they map one-to-one onto the scope doc's invisible list:

1. **The BE electrical/mechanical class** — Klixon trips, open BE capacitor, stuck centrifugal switch, jam-overload, belt slip. BE is unguarded, not FSM-driven, and no analog sensing exists anywhere. Today the whole back end can die and nothing knows until the next fresh rack times out. *(Pilot caveat: the shared lift can be driven by the pair-mate's BE — coverage claims are per-machine for the elevator/carpet, pair-shared for the lift.)*
2. **The ball-return class** — lift clutch, belt tension, kicker, rudder, exit. Zero instrumentation in both the OEM design and rev-C; purely customer-complaint today.
3. **Distributor jams and clutch slip before the BS timeout**, with attribution the BS-only path structurally cannot give.
4. **Belt slip below the cam-timing threshold, bearing wear, lubrication degradation** — nothing back-end has cams, so timing trends can't reach it. *(USB-ADC amplitude data required — threshold switches can't see load creep or load drop.)*
5. **Control-power loss as a distinct fault** (blown F1-F3, T1/T2, machine CB) instead of an indistinguishable timeout cascade.
6. **Centrifugal-switch fails-to-open** (silent thermal damage — USB-ADC) and **uncommanded motor current detected NOW**, without waiting for cam polarity to arm `motion_no_run`; the current channel alone does not prove which contact/feed caused it.
7. **Cushion-degradation slow-return** via return-time trending (a bonus of #2).

What sensors do **not** add: detection on the S/T motion path — stalls, cam faults, GP/BS faults are the wired inputs' home turf. Current sensing there buys *attribution* (stall vs dead-cam vs coil vs welded), not detection.

### Shortlist (ranked; AUX allocation is final: AUX1/AUX2/AUX3 as below, S/T current rides the USB ADC)

| # | Sensor | New coverage | Landing | Cost class |
|---|---|---|---|---|
| 1 | **BE-motor digital current switch** (NK AS1 / Veris H708 class, isolated dry contact; clamp at machine contactor — never the board) | BE hard-fault blind spot: Klixon trip, cap open, overload/jam, and command-off current. The latter is `external-feed-or-welded`, not proof of a welded BE relay; it also covers the OEM test cable. Root-causes most of the bin-fill class (pair-mate lift caveat noted). Debounce the intentional ~30 s post-off BE run. | **AUX1** (J5-9). Threshold sized from a live clamp-meter reading at the powered session (nameplate FLA not in the manuals — gap) | $$ (~$60-150 + ~1 h install) |
| 2 | **Ball-return exit photoeye — ONE per pair** (retroreflective/NPN, same electrical class as the proven DIELL front-end) | The entire ball-return class; per-ball return-time (T0=per-lane DIELL → T1=shared exit) with per-lane attribution via DIELL correlation; rudder-vs-lift discrimination per §1.2 (one lane dead = rudder side; both dead = lift/belt) | **AUX2** | $ ($20-60) |
| 3 | **Distributor index prox** (M12/M18 IP67 at the cam gear / 62 RPM shaft) | Distributor failure-to-index in seconds; clutch-slip cadence; a mechanism entirely outside camera view | **AUX3** (~1 Hz pulse, ms-class MCP latency fine). Target feasibility gap: the cam gear is nylon — inductive prox needs a bolted metal flag (or use a diffuse photoeye) | $ ($15-40 + bracket) |
| 4 | **Analog CTs + isolated USB ADC module** — BE first, then S/T | The trend tier a threshold switch cannot give: load creep before Klixon trips, belt-slip load *drop*, start-transient growth = cap aging, centrifugal fails-to-open, bearing drag. **This is also the assigned landing for S/T current** (AUX is full; Rev-D GPB is the only dry-contact alternative) → stall-vs-dead-cam attribution and command-off current detection before polarity capture. Cause remains `external-feed-or-welded` until separately proven. | **USB on the Pi — the mandatory analog path** (zero ADC on rev-C; Pi GPIO budget unknown) | $$ (CTs $15-40 ea + shared DAQ $50-150) |
| 5 | **24 VAC control-rail sense** | Control-power loss as its own named fault; brownout logging; voltage context for current readings | Same USB-ADC module (pilot); tap a C2A-side 24 VAC node, never C1 115 V cavities | $ ($10-30) |
| 6 | **Motor/gearbox contact temperature** (DS18B20/NTC adjacent to each Klixon) | Minutes-ahead pre-trip warning on every "hums, gets hot, Klixon trips" mode; the only practical lubrication-degradation proxy | Same USB-ADC/1-wire module (never the Pi header directly) | $ ($3-15 ×4-5) |

**Sensor power (critic finding 10):** a **shared isolated 24 VDC sensor supply at the machine** (DIELL precedent — it runs its own supply) powers the prox and photoeye; sensor outputs are dry/NPN into the AUX optos wetted by FIELD_WET_V. Never power sensors from FIELD_WET_V itself (5 V nominal, unbudgeted, floats until the bleed exists), never from the Pi.

**Deferred/research:** carpet-shaft pulse pickup (slip localization once BE current exists; take it when GPB channels exist) · vibration accelerometer (honest trend instrument, real commissioning cost; only clean if gated to READY-idle windows) · USB mic (zero-isolation research channel for the Layer-3 anomaly stack — never a committed detector).

**Supply supervision amendment (2026-07-24):** Rev-D **AUX10 / J15-7** is reserved for `sensor_24v_ok`. The canonical contact type, field landing, multi-board isolation rule, and powered open/restore acceptance test are in `phase8_revD_first_article_pack.md` FA-5. In short: use only an external voltage monitor's galvanically isolated, energize-to-prove, healthy-when-closed dry contact returning to J15-9/10 FIELD_GND; never apply 24 V to J15. Loss/open-wire emits `sensor_supply_lost` and invalidates dependent exit/index absence evidence; restoration emits `sensor_supply_restored`, establishes a level baseline, and starts no new timer until a wholly post-recovery observation (plus one return-timeout drain window for the shared exit beam). Sense downstream of the sensor branch fuse/common. A simple undervoltage contact cannot continuously prove a welded/shorted-healthy contact and cannot detect overvoltage; FA-5 therefore requires a contact proof test and records whether an under/over-voltage window relay was selected. Software and contract transport are implemented; hardware remains uninstalled/unproven, and AUX10 stays unmapped until the first-article plus harness gate passes.

### Skip these (reasons)

- **Table/sweep shaft encoders** — duplicate the six cam-timing intervals cam_telemetry already trends; the only vacant fast input is contested; full quadrature has no compliant path.
- **Per-bin pin-presence switches** — 10 inputs = a respin by themselves; BS + camera full-rack verification already covers the outcome.
- **Cushion shock-absorber accelerometer** — DIELL + camera already cover ball detection; the residual (absorber bind) is a hands-on item.
- **Spot/respot solenoid sensing** — camera full-rack assert covers the outcome end-to-end.
- **Direct Klixon-state taps** — live-115 V with no compliant front-end; no aux contact documented (checking `8270parts 13-Electrical (1).pdf` is an open item); the compliant substitute is inference (commanded + no current + housing hot).

---

## 4. Coverage accounting (recounted per critic finding 8)

Basis: **64 mechanical failure modes** across §1.1-1.14 (5+5+7+6+8+4+2+4+3+2+9+6+2+2 — includes the four modes the critic added) **+ 3 platform conditions** (§1.15) = **67 target conditions**. "Detectable" = the condition's occurrence produces an alertable signal; attribution quality is noted separately. S/T-current-dependent conditions are assigned to the **USB-ADC stage** (sensor shortlist item 4), not rev-D — counted once.

| Stage | Detectable | Delta | Notes |
|---|---|---|---|
| **Today** (deployed: FSM 8 s timeouts, firmware chatter, startup stuck-input) | **~23 / 67** | — | Only ~11 attribute to a named component; ~12 collapse into undifferentiated timeout classes (the whole bin-fill chain reads as one "BS late"). Camera detectors and trend persistence do not exist yet. |
| **+ Phase 0-3 software** (polarity capture → armed cam_overrun/motion_no_run; camera full-rack + GS-disagreement; beam_blocked; trend persistence; OS consumption; IN-B read path incl. PBC/10th stuck + foul rules) | **~49 / 67** | +26 | Adds the gripper/spotting-quality class, cam maladjustment/drift, shorted-cap coasting, welded contacts (armed), off-spot, foul faults, stuck-button cycling, wear trends. All gated on the powered session + Phase-1.7 persistence. |
| **+ Sensor shortlist** (BE switch, exit photoeye, distributor prox, USB-ADC CTs incl. S/T, 24VAC sense, temps) | **~59 / 67** | +10 | The ONLY stage that touches the BE class, ball-return class, distributor slip, bearing/lube wear, centrifugal fails-to-open, control-power loss — plus attribution upgrades on ~8 earlier rows. AUX fits items 1-3; everything analog rides the USB module. |
| **+ Rev-D** | **~59-60 / 67** | +0-1 | Rev-D unlocks almost no NEW fault modes — it relieves channel contention (dry-contact S/T switches, Klixon aux, door switches on GPB), adds ordered rail-drop attribution, and improves flashability. This is exactly why the don't-spin-for-diagnostics rule holds. |
| **Invisible regardless** | **~7 / 67** + attribution residues | — | Hard human-only-final: shock-absorber bind, sweep-hits-gutter, distributor front-end impact, head-first upstream cause, pin condition ×2, machine-dead breaker attribution. Conditionally recoverable: sweep-linkage geometry IF the camera FOV includes the sweep (one annotated frame resolves it). Permanent attribution residues: per-cam interlock attribution (no independent TB harness signal / no dry landing), ball-return component-level attribution, pin-vs-machine blame. |

**Honesty flags:** (a) ~⅓ of "today"/"Phase 0-3" rows are weak-attribution timeout expressions, not named diagnoses; (b) every cam-sequence number assumes the Phase-0 polarity capture succeeds; (c) machine-22 baselines are optimistic priors, not fleet thresholds; (d) all Layer 2/3 detections are alert-only — trip authority stays with the existing Layer-1 backstops; (e) analog-signature rows (slip-vs-jam, centrifugal, load creep) are USB-ADC-dependent — a threshold switch alone does not deliver them.

**Known source disagreements:** 24VAC-sense "footprints" are a manual-population *option*, not placed copper (refines scope:124); FIELD_WET_V unloaded float is ~14 V per the change list vs ~11 V measured on board #1 — no source reconciles them; use per-board measurement.

**SC/TB reconciliation note (corrected 2026-07-24).** The 2026-06-27 cold continuity session established only the **harness-level** facts: C2A-U is a shared live-ladder region, TB never isolates to a standalone cavity, no dry NC pair can land on J_SAFE, and ~21 Ω relay-coil sneak paths invalidate topology inference. Its tentative “series / closes-on-danger” interpretation is superseded. The 2026-07-07 powered test is the topology/polarity authority: the OEM ladder behaves as **parallel closed-when-safe** contacts; danger is both levers BACK/open and independently kills both S and T coils. Candidate C formally delegates the primary guard to that ladder through the controlled J_SAFE1-2 jumper and mandatory per-lane G3 insertion-point proof. Firmware echo remains default-off, secondary, and unvalidated because the harness supplies no independent TB observation. Any document claiming either a landable dry TB/SC pair or a powered-proven series topology is stale.

---

## 5. Diagnostic-SYSTEM conditions — P0 (added v1.1, Codex R2-16)

The §1 catalog watches the *machine*; nothing watched the *watcher*. These conditions are about the diagnostics/control chain itself and are **P0 — the monitoring system must fail visible, never silent**. Status keys: `shipped` = live in the 2026-07-19→21 campaign code · `source implemented` = present and locally tested in the round-5 release candidate but not deployed/field-proven · `blocked` = needs hardware, commissioning, or guarded bench work first.

| # | Condition | Detection / surfacing | Status |
|---|---|---|---|
| P0-1 | **Board OFFLINE / UNKNOWN** (Pi daemon or :8766 store dark; dead board must not look healthy by omission) | machine_leases (last_seen + WSL_MACHINE_LEASE_S window) → explicit per-board state HEALTHY/FAULT/OFFLINE/UNKNOWN/MAINTENANCE in `/api/machine/health`; WSL bridge degrades an unrefreshable snapshot to UNKNOWN-with-age; `/api/lanes` always carries state for Phase 8 lanes; SMS offline class (`machine_offline`, own throttle) | **shipped** (R2-10) |
| P0-2 | **Telemetry loss / duplication / reordering** (dropped diag records, replay double-counts, out-of-order arrival corrupting baselines) | Delivery identity `source_id/boot_id/seq` on every record; JSONL-as-outbox with cursor-ack replay; server dedupe on UNIQUE(source_id,boot_id,seq); drop counters promoted to structured events (`diag_drops`, `http_sink_drops`, `uart_drops`) | **shipped** (R2-12) |
| P0-3 | **TB/SC interlock failed-or-bypassed** (protection jumpered/failed with no detection — the predicted field escape) | ALERT-ONLY: needs final-member sensing (coil-circuit observation or the G3/Stage-6b per-cutover coil-drop proof as the procedural gate); no compliant continuously attributable TB/SC sensor exists on this chassis today — recorded as a standing gap, per-cutover proof REQUIRED | **blocked** (procedural backstop only) |
| P0-4 | **Motion while permission false** (cam/ball edges arriving while the FSM asserts no motion should occur) | FSM else-branch unexpected-edge counting → `unexpected_edge` events; epoch-aware classifier (fw v1.2.2, R2-13) excludes stale pre-reboot edges | **shipped** (events) / **source implemented** (epoch rule; firmware NOT flashed) |
| P0-5 | **Output-chain per-stage mismatch** (commanded relay vs RP_OK vs rail vs observed motion disagreeing at a specific stage) | `run_mismatch` promotion plus v1.2.x predicate-tap edge ordering are implemented in source. The four taps do not measure `RELAY_ENABLE_RAIL`; actual Q14/J14/coil-rail feedback and machine-current/contact evidence remain separate physical sensors/gates. | **source implemented / physical rail feedback blocked** |
| P0-6 | **Identity / cross-lane mismatch** (board thinks it's lane 21 while wired to 22; config/firmware/contract hash drift) | REV_ID strap + firmware identity line (PCB rev, unique id, build hash, config hash — R2-6); BoardConfig requires an explicit per-lane board revision, rejects unsupported roles loudly; `fw_config_mismatch` events; deploy-time git-hash record/compare (R2-8) | **source implemented** (firmware/daemon; firmware NOT flashed and physical identity unqualified) / **shipped** (deploy hash compare) |
| P0-7 | **Per-sensor open / short / stale / out-of-range / supply-lost** | Startup + mid-session stuck-input rules (shipped); SlowDebounce diagnostics path (shipped); FIELD_WET loopback role = supply-lost detection for the field bank (AUX11, software now — see §6 AUX priority); `bank_unavailable` / `stale_channel` / `configured_role_missing` MCP/GPB read-failure events | **source implemented**; physical FIELD_WET/sensor-supply harness remains uninstalled |
| P0-8 | **Stop or installed pit-entry-interlock demand fails to remove master/control power** (open wire, bypass, welded contact, wrong landing) | On every lane, observe `stop_request`, independently observe isolated downstream `control_power_ok`/breaker auxiliary, and require bounded Stop→power-drop during an at-machine functional test. Pilot lanes 21/22 have no C.I.S.; determine whether another pit-entry interlock exists and either test it separately or close the install-vs-Stop-plus-lockout safety decision. On chassis that have C.I.S., observe and demand-test it separately. A J14-only switch cannot replace an upstream final disconnect. J14.3–4 is physically OPEN today; never jumper it merely to arm the rail. | **blocked P0** (architecture + pit-interlock disposition + measured landing + functional proof) |
| P0-9 | **Mains polarity / protective-earth defect** (hot-neutral reversal, missing/high-impedance PE) | Listed external polarity/PE instrument under electrician-controlled commissioning and periodic proof. Board 5 V, 24 VAC, and `control_power_ok` can all be healthy while this fault exists. Never route mains or PE-test current onto Rev-D. | **blocked external proof** (not a PCB input) |
| P0-10 | **Alert/recovery delivery ambiguity or sink rejection** (evidence was durably written but the producer cannot tell; one rejected head poisons the queue; a recovery leapfrogs its alert) | Bounded severity-first retry sets and fsync'd write-ahead ledgers pre-stamp every concrete lane obligation with a restart-stable identity before offer. Per-record dispositions distinguish accepted, duplicate, rejected, and ambiguous writes; replay retains the exact identity. Exact-family alert→recovery→re-alert order is preserved, rejects are quarantined without recursive notification, and sink ownership remains single-threaded through shutdown. | **source implemented**; deployment/forced-crash proof remains |
| P0-11 | **Restart, restore, or corrupt-state discontinuity** (service starts, open conditions, cursors, or retry obligations disappear or false-green after reboot/restore) | Track-A/Track-B service-start, condition-delivery, cross-service, outbox, camera, and baseline state is bounded, strict, and fail-closed. Backup inventory now includes every restart-critical Pi ledger; restore validation proves identity, ledger grammar/terminal state, and exact fault/recovery semantics instead of accepting any same-code info row. | **source implemented**; off-disk backup and restore rehearsal remain operational gates |
| P0-12 | **Clock step, controller reboot, or blind interval fabricates continuity** (old edges/baselines look current; an absence timer resumes across a period in which the event could have happened unseen) | Firmware epoch + boot nonce, producer timestamp/order bounds, platform clock-step events, and union-of-unavailability handling invalidate affected baselines, debounce candidates, absence timers, and current-condition claims. Recovery establishes a new level baseline and, where required, a full drain window before new evidence begins. | **source implemented**; firmware flash and powered soak remain |
| P0-13 | **Uncommissioned or identity-drifted physical lane appears release-healthy** | The WSL monitor requires a signed per-lane commissioning record bound to fleet policy, lane, Pico UID, and board/harness revision. It must also obtain a hard-deadline controller-originated live observation no more than **90 seconds** old and match that exact live identity. The record must exactly cover Stop→control-power/TP16 drop, sensing-relay proof, pit-interlock disposition, Candidate-C TB/SC G3 insertion proof, PE continuity, and hot/neutral polarity, with a manifest-controlled retest interval no greater than **365 days**. Missing, overdue, tampered, stale-live, or identity-mismatched evidence fails closed. A dormant controller under the current scoring-only unit policy therefore cannot be release-healthy. | **source implemented latch**; physical FA-13/FA-14 evidence and reviewed live-controller policy are intentionally absent/open |
| P0-14 | **Operational warnings disappear behind the legacy single-fault latch** | `/api/machine/health` carries a bounded newest-first `current_conditions` list plus an exact unbounded count for unresolved `warn`/`fault` rows. Strict later `info/recovered` evidence closes warning families; faults retain actor-audited resolution. WSL rejects malformed/count/order/fault-relation drift and surfaces otherwise-fresh warning lanes as DEGRADED while faults retain precedence. | **source implemented** |
| P0-15 | **Ambiguous controller mode, duplicate hardware owner, or stale ARM prerequisite** | Startup requires exactly one explicit SHADOW/LIVE mode and a lifetime cross-process owner lease before GPIO/I²C/UART access. Identity, firmware max-run, tap, storage, and mode failures latch ARM low; recovery requires current evidence plus a fresh PBZ. The first-article tool uses the same ownership boundary and cannot report relay-only override as firmware qualification. | **source implemented**; hardware ownership/fail-safe release still needs bench proof |

## 6. Machine conditions — P1 additions (v1.1) + AUX role priority

P1 machine-side conditions surfaced by the round-2 review, extending §1 (not double-counted in the §4 arithmetic — v1.1 does not re-baseline the 67):

| # | Condition | Capture method | Class |
|---|---|---|---|
| P1-1 | Cam moves, mechanism doesn't (broken linkage downstream of a healthy cam signature) | Interval plausibility vs camera outcome (rack didn't change though cams cycled) | camera + timing-trend |
| P1-2 | Wrong motor / wrong direction / speed out of envelope | Per-motor energized-time (H-02 fix, shipped) + interval envelope vs baseline; current signature once USB-ADC lands | firmware-rule → add-on-sensor |
| P1-3 | Dual-DIELL asymmetry (pair-mate ball-detect rates diverging) | Cross-lane DIELL event-rate comparison over sessions | firmware-rule (server-side) |
| P1-4 | Unsafe-state request promotion (desk/API commands arriving while the machine is in a state where acting is unsafe) | Command-vs-FSM-state gate promoted to a structured warn event instead of a silent drop | firmware-rule |
| P1-5 | Unmatched exit object (ball-return exit event with no preceding DIELL ball) | Exit photoeye vs DIELL T0 correlation | add-on-sensor |
| P1-6 | BE-branch-stopped (carpet/elevator pickups dead while BE runs) | BE current + elevator/carpet correlation (pickup class of §1.7/1.10) | add-on-sensor |
| P1-7 | Distributor pin-spacing drift (pins too close/far on the belt; AMF `24_8270.txt:2666`) | Distributor prox pulse-interval trending | add-on-sensor |
| P1-8 | Rack-quality metrics (off-spot tendency, lean, rack-to-rack repeatability) | Camera standing/full-rack mask statistics per rack | camera (trend) |
| P1-9 | Predictive electrical trends (motor current creep, start-cap degradation signatures) | USB-ADC CT baselines, Welford drift | add-on-sensor (trend) |
| P1-10 | Facility/environment (ambient temp, humidity near electronics, supply sag) | Cheap I²C env sensor in enclosure + 24VAC sense option | add-on-sensor (option) |
| P1-11 | Cushion-SS-as-passive-observer OPTION (SS retired from the read path — re-admit as observe-only edge counter, never a control input) | AUX role, observe-only, stuck-exempt | firmware-rule (option) |
| P1-12 | Command-off motor current / external feed (including OEM BE test cable left active) | BE/M/S/T CT or Hall current evidence correlated with command and control-power state; alarm as `uncommanded_motor_current`, with cause kept explicitly ambiguous | add-on-sensor |
| P1-13 | Voltage outside sensor/control window (overvoltage as well as undervoltage) | Listed isolated under/over-voltage window relay or external ADC; a simple healthy-when-closed undervoltage contact cannot detect this class | add-on-sensor |

**AUX4–11 role priority list (recorded per R2-16; roles are dormant until the board-specific `WSL_DIAG_AUX_ROLES_L<lane>` map enables them — the unscoped map is accepted only for a one-board bench, once either paired board is explicitly mapped its mate must also be present even if exactly blank, and a pair must have zero or one `exit_beam` source):**

1. **AUX4 — provisional `stop_request`.** Separately observe the Stop demand through a listed galvanically isolated dry-contact monitor; do not infer it from rail state.
2. **AUX5 — provisional `pit_interlock_request`, only if such a device exists or is installed.** Pilot lanes 21/22 have no C.I.S. device/wiring, so do not configure a fictitious `cis_request`. On another chassis with a real C.I.S., this channel may observe that demand under a chassis-specific approved name/map.
3. **AUX6 — provisional `control_power_ok` / breaker-aux proof.** Observe a downstream, energize-to-prove isolated contact so each Stop or actually installed pit-interlock demand can be correlated to actual power removal.
4. **AUX7/AUX8 — provisional S/T digital current switches, if selected.** Detect commanded-no-current and command-off-current states; retain USB-ADC CTs where analog trending or cause separation is required.
5. **AUX9 — measured optional dry contact only.** Choose among `s_manual`/`t_manual`, a verified Klixon auxiliary, or a door/service contact after its electrical form and diagnostic value are confirmed.
6. **AUX10 — `sensor_24v_ok`.** External energize-to-prove isolated voltage-monitor contact for the separate sensor supply. Software/contract semantics are implemented; keep unmapped until FA-5 and powered harness proof pass.
7. **AUX11 — `field_wet_ok`.** Loopback of the field wetting supply through the qualified opto input; software semantics are implemented, but the physical loopback remains a harness/first-article item.
8. If any of AUX4–AUX9 is not used by the functions above, preserve it as an uncommitted spare or FI-1 bench channel; do not fill it merely because capacity exists.

The AUX4–AUX9 role names above are **design reservations, not released software mappings**. They must remain unmapped until the signal's voltage/contact form, field landing, isolation, exact event semantics, open-wire behavior, and first-article functional proof are approved. Only volt-free contacts from listed galvanically isolated monitors may enter J15; never land mains, unclassified live ladder voltage, protective earth, or a SAFE_* conductor on an AUX input.
