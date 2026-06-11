# Phase 8 — Bench Session 1 FINDINGS (spare cabinet photos, 2026-06-01)

**Source:** 6 photos `Downloads/Cabinet images/20260601_09*.jpg` (16320×12240). Downsized + region crops in `Downloads/Cabinet images/_small/`. This maps the Omega-Tek Fig-1 drawing to the REAL spare cabinet so session-2 probe instructions are exact.

## ✅ What's confirmed in the physical cabinet
Matches `OmegaTek_Fig1_chassis_map.png` well. Cabinet is the SS chassis + Omega-Tek retrofit.

### Chassis rail stamps (top edge, photo 090449) — orientation anchor
Reading left→right along the top rail: **T1 · OLL · T2 · S · T** (stamped in the metal). These are position labels from the Fig-1 map → confirms cabinet orientation matches the drawing. (KX top-left, S/T relays upper-right, BE lower-left, M2/M/SP lower-center.)

### Relays / contactors (photos 090437, 090449, 090502, 090524)
- **Upper-right cluster:** two units — a **Siemens control relay** (aux-contact block stamped **22E, 21NC, 31NC, 32NC, 44NO, 43NO** = 2 NC + 2 NO aux contacts; body likely **3TH40-series**, coil V on the front face — NEED the head-on coil-voltage read) + a second contactor beside it (the S/T motor relays per Fig-1).
- **Lower-center (photo 090502/090524):** 3 clear **plug-in ice-cube relays** (M2, M, SP per Fig-1) in sockets, + the two big **CP2/CP3 filter caps** (the round cans), + the back-end (BE) relay lower-left (photo 090524, "BE" stamped on the rail).
- **One relay socket label fully read (photo 090841):** **"POTTER & BRUMFIELD, DIVISION A.M.F. U.S.A., JRM-10110, 12V DC"** — a **12 VDC** relay; socket diagram shows pin pairs (2↔23, 24↔21, 22↔19, 20↔17 …) with a "12V DC" coil tag. ⭐ First hard coil-voltage data point: **at least one control relay is 12 VDC.**

### ⭐ C1 / C2A connectors — FOUND (photo 090953, right of the Omega-Tek board)
Two **side-by-side edge-card connectors**, stamped **AMP "1-0 series" 67209 / 67211** (vertical text between them). These are the machine-harness connectors. Per the AMF convention C1=34-pin (motor/relay/power), C2A=50-pin (switches/control) — **need a pin count per connector to label which is which** (count the contacts in each strip; the wider one with more positions = C2A/50, the other = C1/34). A THIRD connector (photo 090841 bottom, ~25-pos edge connector near the P&B relay) may be the Mask/BPP plug — count it too.

### The Omega-Tek board edge legend (photo 090953) — the board's own pin map
Black label on the board reads **"...LIFT HERE / [OMEGA-TEK] SHELBY, OHIO / MADE IN U.S.A. / PIN LAMPS"** with edge-finger labels: **T, S** (table/sweep relay drives), **X, 2B, 1B** (2nd-ball / 1st-ball status?), **2, F, 4, 6, 8, 10, 1** (PIN LAMPS group — the mask pin-lamp outputs + Foul). This is the BOARD-side functional labeling → directly useful for mapping board edge → C1/C2A.

## ✅ FOLLOW-UP PHOTOS IN (3 more, 091852/091904/091907) — C1/C2A + contactor RESOLVED

### ⭐ C1 vs C2A — ASSIGNED (connectors photographed OUT on the bench, 091852)
Both are **AMP M-series** (letter-coded pins, "AMP" + "01" pin-1 mark molded in) — exactly the "AMP M-type, numbered by column/pin" scheme from SYSTEM_REFERENCE §4.
- **LEFT connector = C1 (34-pin).** 3 columns. Row letters read down the body: single A,B,C,D,E,F,G... then **double-letters EE, FF, GG, HH, JJ, KK, LL, MM, NN** at the bottom, **"01"** pin-1 marker, **"AMP"**, + **two large-gauge power pins** at the very bottom. The double-letter rows + 2 power pins = the 34-pin motor/relay/power connector. **CONFIRMED by the pinout doc** which lists C1 pins exactly like `17-DD, 18-JJ, 19-NN, 28-LL, 26-BB` — those double-letters only exist on THIS connector. ✅
- **RIGHT connector = C2A (50-pin).** 4 columns × ~12–13 rows ≈ 50 positions; denser, also AMP-marked. The switches/control + TAC-gripper connector. ✅
- **Pin-1 reference:** the **"01"** molded mark + the AMP logo are at the SAME end on each — that's the pin-1/orientation datum for probe instructions. A THIRD connector (photo 090841, ~25-pos) is the Mask/BPP plug — separate.

### ⭐ Siemens contactor = 3TH4022-0A (091907 + side label 092859)
Full part number read off the side: **SIEMENS 3TH40 22-0A**, contacts **2S+2Ö = 2NO+2NC** (aux markings 13/14 NO, 21/22 NC, 31/32 NC, 43/44 NO all visible on the front face 091907). IEC 947 / VDE 0660, made in Germany, date G/9840. It's a **3TH4 control contactor-relay (4-pole aux, no power poles — a control relay)**.

⚠️ **STILL no coil voltage — and here's why the side label DOESN'T give it:**
- `3TH4022-0A`: the `22` = contact arrangement (2NO+2NC); the `-0A` suffix is a build/variant code, **NOT a coil-voltage code**. On 3TH4 the coil voltage is a **separate explicit line** ("230V 50Hz", "24V~", etc.) printed lower on the front or on the coil body — **not yet captured in any photo.**
- The big table on the side label (`230/240/400/415/500/690 V → 10/10/6/4/4/2 A`, `2.4/2.6/4/4/4 kW`) is the **AC-3 CONTACT load rating** across line voltages + motor ratings — i.e. what the CONTACTS can SWITCH, not what the COIL needs. Useful for design (see below) but it is NOT the coil voltage.
- **To get the coil V:** photograph the explicit "___V ___Hz" line on the front face (lower than the contact markings), OR meter coil **A1–A2** resistance (cold) — a 24 VAC coil reads ~tens of Ω, a 230 VAC coil reads hundreds–thousands of Ω, so the resistance alone narrows it.

**Design takeaways from what IS readable:**
- This 3TH40 is a **control relay** (switches other coils/control circuits, not a motor directly) — consistent with the Fig-1 "control relay" role. Its contacts handle up to 10 A @ 230 V — plenty for whatever coil circuit it switches.
- The cabinet has a **mix**: P&B JRM-10110 = **12 VDC**; this Siemens 3TH40 coil = **TBD** (likely 24 VAC or line-V on these retrofits); plus the heavy power contactor in 091904 = TBD. The AEDIKO (5 V dry contacts) will switch whichever of these coil circuits we drive → **the coil-V mix sets whether the enclosure needs a 12 V and/or 24 V rail beyond the 5 V.** Confirm before PSU finalize.

### Still open (small)
1. **Coil voltages** — 3TH40 (Siemens) + the adjacent power contactor (091904, the one with the heavy motor lugs) + confirm the P&B = 12 VDC. Read the side stickers and/or meter A1–A2.
2. **Paper wire chart** inside the cabinet/door (not seen — may not exist; not blocking).
3. Exact per-pin probe-out happens in session 2 against the now-known C1(left)/C2A(right) + "01" datum.

## Session-2 bench readings (in progress, 2026-06-01) — relay inventory
Dylan's first metering pass + the gotcha it exposed (now fixed in the session-2 doc: **read actual ohms, don't sort low/none — NC contacts ALSO read ~0 Ω**):
- **Siemens 3TH4022:** terminals seen = 13NO,14NO / 21NC / 31NC,32NC / 43NO,44NO (the 4 aux contacts). "Multiple low-resistance pairs on S and T" = the **NC contacts (~0 Ω at rest)**, NOT coils. **Coil = A1/A2** (top/bottom, mid-resistance) — TO RE-METER.
- **"The other relay" (adjacent, upper-R): 4 unlabeled terminals** — likely the power contactor; identify coil = mid-resistance pair.
- **M2, M, SP = "ancient", 3 terminals each, P/N `82-70-5515`** ⚠️ NOT a standard ice-cube relay. 3 terminals + "no low-resistance pairs on M2" → possibly a solenoid, a 3-pin relay, or a semiconductor. **NEED: photo + all-pair ohms + DIODE-mode check** (0.4–0.7 V one-way ⇒ SSR/SCR, not a coil relay). `82-70-5515` = an AMF 82-70 part number (un-decoded — research/ask).
- **BE = 6 unlabeled terminals** — typical of a relay w/ coil + 2 contact sets, OR a multi-pole. Mid-resistance pair = coil. **NEED: photo + all-pair ohms.**
- **Takeaway:** the simple "S/T are contactors, M2/M/SP/BE are ice-cubes" assumption is wrong — this is a **mixed bag incl. a 3-terminal AMF part (82-70-5515)**. Re-meter with the ohms-number method; photograph the 82-70-5515 + BE. Coil-voltage default for AMF-native parts = **24 V** (T2/T3/T4); confirm the retrofit Siemens explicitly.

### JOB-1 PROBE RESULTS (2026-06-01, Dylan — scans Scan_20260601_175631/47)
**Method note discovered mid-read:** Dylan recorded RESISTANCE, not just beep. A cavity hit at **0 Ω = direct wire**; a hit at **~55 Ω = connected THROUGH a coil winding** (shares a node via the coil, not a direct wire). Must distinguish these — the worksheet's beep-only method didn't.

**S relay (Siemens 3TH4022) → C1 cavities: C, D, N, T** (terminals 1–4). Expected S set was {D,J,N,T} → **D,N,T match; T1 reads C (not J)**. C↔J easily confused on the connector OR a real wiring detail — treat C as measured. **S = SWEEP, confirmed.** (Corrects the earlier "Siemens isn't S" guess — Dylan: **Siemens IS S.**)

**T relay → C1 cavities:** T-table terminals = **A, K, L, H, E** (expected {A,E,K,P,H}). Notable: **terminal at H reads CLOSED (0 Ω); a terminal also hits L at 55 Ω (through-coil); T3=L@55Ω.** So A,K,H,E match expected; **L appears (55 Ω, through-coil) where P was predicted.** **T = TABLE, confirmed** (4 of 5 on predicted set; P↔L + the 55 Ω through-coil path to sort out).

**M2 (sweep-rev), SP (spot), BE (back-end): terminals beep to C2A or NO-MATCH — NOT to the predicted C1 cavities.** Dylan CONFIRMED this explicitly. BE specifically: DD→C2A, W→C2A, F→C2A. M2: mostly no-match, one cell FF. SP: no-match.
- ✅ **TENSION RESOLVED (Dylan confirmed): MIXED ROUTING is the real model.** The M2/SP/BE→C2A hits are **all 0 Ω = direct wires** (not through-coil artifacts; the one exception is FF→BE-coil at 66 Ω on C1). So:

### ✅ CONFIRMED HARNESS MAP (2026-06-01) — relay → connector
| relay | drives | connector | cavities (measured) | notes |
|---|---|---|---|---|
| **S** sweep | sweep MOTOR (high-current) | **C1** | C, D, N, T | expected {D,J,N,T}; T1=C not J |
| **T** table | table MOTOR (high-current) | **C1** | A, K, H, E (+ L @55Ω through-coil) | expected {A,E,K,P,H}; L where P predicted |
| **M2** sweep-rev | sweep-reverse (low-power) | **C2A** | direct 0 Ω | |
| **SP** spot | spot SOLENOID (low-power) | **C2A** | direct 0 Ω | |
| **BE** back-end | back-end (low-power) | **C1 + C2A (straddles)** | **C1: KK, C, L** (T1) + coil **FF @66Ω** (T2); also C2A from prior page | back-end touches several circuits |
| **M** master | master/power | **C2A** | T1=FF, T2=U, T3=B+U (all C2A) | confirms M routes via C2A like M2/SP |

**The engineering logic (why it's NOT a contradiction):** the two **high-current main motors (S, T) use C1** (the heavy-pin connector w/ 2 power cavities). The **lower-power loads (M2 sweep-rev, SP solenoid, BE) use C2A.** This matches Dylan's visual ("C1=thick S/T wires; C2A=many thinner wires" — the thin C2A wires include these smaller loads). **The earlier "all 7 relays on C1/OUT-A" assumption in `phase8_channel_allocation.md` §3 was too coarse → corrected: split outputs across C1 (S,T) + C2A (M2,SP,BE).**
- **Still to verify (minor):** S T1=C-vs-J and T's P-vs-L (225-DPI predicted codes vs measured — measured wins; just note the predicted-table needs these 2 edits). The FF→BE-coil@66Ω is a coil-path detail, not a contradiction.

### JOB-1 DONE (2026-06-01) — output/connector map COMPLETE
All 7 output relays now mapped to connector by bench probe:
- **C1 (main motors):** S (C,D,N,T), T (A,K,H,E+L)
- **C2A (low-power loads):** M2, SP, M (FF/U/B)
- **Straddles:** BE (C1: KK/C/L + coil FF@66Ω; also C2A)
- **Not tested / skipped:** L→T2 (couldn't access — minor); the "2 big C1 power cavities" = the oversized round contacts on the C1 connector body (main mains feed) — **SKIP, not Pi-driven, will be obvious from the harness.** (Dylan asked if these were the front-panel button fuses — they are NOT; they're the 2 big cavities ON C1 in photo 150321.)
- **Net:** the output-side harness map is bench-confirmed enough to lock the channel-allocation §3 (done). Remaining bench work = INPUT side (C2A cams/switches/grippers) + §B cam-stop topology.

### JOB 2 probe results (2026-06-01) — LEANS LOGIC, not airtight; + a clean C1/C2A reframe
**Big clean finding (JOB1+JOB2 together): C1 = motor/CONTACT side (heavy 115V to motors); C2A = COIL/control side + cams (light wiring).** Sensible split; reconciles "S/T contacts→C1" (JOB1) with "S/T coils→C2A" (JOB2) — different terminals of the same relay.

**Probe data:**
- Test A1: S A1-landing↔A2-landing = **5 Ω** ✅ (coil's two ends).
- Test A2: S-coil tag → C2A = **cavity Z @ 0 Ω, "all 0 Ω"**.
- Test B2: **T switched-side → board (0 Ω via middle of 3 pins into the Omega board)** — coil's controlled side runs to the board.
- Test B3: T switched-side → C2A **cavity P @ 5 Ω** (through-coil).
- Test C: S-supply ↔ T-supply ↔ M2/SP-supply all **beep (common 24 V rail)** ✅.

**⚠️ The elimination test was DEFEATED by the shared supply rail (my test-design flaw, not a probing error):** Test C proves all coils share a common 24 V rail, and that rail is also distributed to C2A (cam reference). So "coil tag → C2A @ 0 Ω" is EXPECTED even in pure-logic — it's the supply rail, not a cam-in-series. The S "all 0 Ω to C2A" was almost certainly the SUPPLY side (bussed everywhere) → uninformative on logic-vs-hardwired.

**What leans LOGIC:** (1) T switched-side → board (0 Ω) = coil controlled side runs to the board; (2) board = triac+CMOS driver bank (photo); (3) T→C2A @5Ω is through-coil, not a hardwired contact. **Best read: LOGIC stops** — but NOT airtight because S's switched-vs-supply side wasn't cleanly separated.

**Definitive resolution = either (a) one more bench probe** (discriminate S switched-vs-supply: the supply side beeps to M2/SP coils, the switched side does NOT; then check if S switched-side → board like T) **OR (b) the at-machine cam-flip test** (§B-machine: open a cam, watch if the coil drops with no board involvement).

**DESIGN IMPACT: NONE that blocks us.** We add hardware end-stops + TB/SC interlock + RP2040 cam-stop timing REGARDLESS (never trust software alone near motors). Logic-vs-hardwired only decides whether an *existing* hardwired cam-stop is preserved as a bonus backstop at cutover — a wiring detail, not a design gate.

### (superseded) earlier inspection note — LOGIC by board inspection (2026-06-01)
Omega-Tek board top-rail photo = the **driver stage**: bank of **`S2003LS2` sensitive-gate TRIACs** (one per output terminal) + **`MM74C…` CMOS logic** + SIP gate-resistor networks + **`LM340T5`/7805** 5 V reg. → outputs (S/T/SP/lamps) are **logic-gated triacs**, so **cams → logic → triac → coil = LOGIC stops** (NOT hardwired cam-in-series). Matches the manual's MP-chassis model.
- **Design implication (CONFIRMS the plan):** the Pi-controller must **time the cam-stops itself** (read cam → drop relay) — exactly what `cycle_control_8270.py` + the **RP2040 cam-stop co-processor** do. We ADD hardware end-stops + the TB/SC interlock since the machine doesn't hardwire the stops. No change to the FSM/board plan; it's now bench-confirmed rather than assumed.
- **Probe caveat noted:** board triac outputs read OPEN when off (semiconductors, not wires) → "coil tag shows no 0 Ω to board" is expected. Dylan running the coil-tag→C2A elimination test to confirm no hardwired cam exception.

### ✅ COIL RESISTANCES MEASURED (2026-06-01, Dylan)
| coil | unit | coil Ω | reading |
|---|---|---|---|
| **S or T** | Siemens **3TH4022-0AC2** | **5 Ω** (A1–A2) | ✅ **24 VAC — CONFIRMED.** Datasheet: 3TH4022-0A suffix = coil V (C2=24V, K6=120V, P6=240V); 5 Ω only fits 24 V (120 V≈40–80 Ω, 240 V≈150–300 Ω). Matches AMF 24 V transformers. |
| **M** | 82-70-5515 | 80 Ω | ~24 V native coil |
| **M2** | 82-70-5515 (identical to M) | 80 Ω | ~24 V native coil |
| **SP** | separate P/N | 100 Ω | ~24 V native coil |
| **BE** | — | 22 Ω | ~24 V native coil (low R leans AC) |
| **KX** | — | **SKIP** | KX = pin-data-to-OLD-scorer relay; **camera (Track A) replaces its function** → not needed for the Pi controller |

**Method correction baked in:** DC-resistance→voltage rule only holds for **DC coils**; **AC coils read far lower** (current is reactance-limited at 60 Hz, not R-limited). The Siemens 5 Ω is the proof it's AC. Resistance alone CANNOT give an AC coil's voltage → need the label or a live read.

**⚠️ T coil candidate reads <1 Ω (2026-06-01) — SUSPECT, verify before trusting.** Lower than the Siemens 24VAC coil (5 Ω), and <1 Ω overlaps with a closed NC-contact (~0 Ω) + lead resistance (~0.2–0.5 Ω on 200 Ω range). May be on a CONTACT pair, not the coil. **Verify via armature-press test** (steady = coil; jumps open↔closed = contact) + zero the leads. Don't run the coil→C2A test until confirmed it's the coil. (Note: user recalled Siemens as "<1 Ω" — actual was **5 Ω**; T at <1 Ω is therefore LOWER, hence more suspect.)

**Open gaps (minor):** (1) the OTHER upper-R relay (4 unlabeled terminals = S/T partner to the Siemens) coil Ω — not yet read. (2) Siemens explicit coil VOLTAGE (label/full P/N). (3) AC-vs-DC per native coil — from transformer secondaries / rectifier presence, NOT from R; affects snubber only, low priority.

### ✅ CONNECTOR IDENTITY RESOLVED (2026-06-01 pm) — original map CONFIRMED
A mid-session "C1 carries thin wires" scare turned out to be an **orientation mix-up, now cleared.** Dylan was first tracing under the presumption "C1 = the bottom connector," so the thick S/T leads looked like they went to "the connector above C1." Once the **"C1" stencil was positively located** (photo 150321 + crops; cabinet on its side, stencil rotated 90°, sits beside the 3-column connector), the picture is unambiguous and matches the schematic all along:

| connector | = | physical (photo 150321) | carries |
|---|---|---|---|
| **C1** (34-pin) | motor/relay + power output | **LEFT** — 3-column, round pins, "01"+AMP, rows A…NN, **2 big power cavities**, stencil beside it | **thick S/T motor wires** + M2/SP/BE + power |
| **C2A** (50-pin) | switches/control + grippers | **RIGHT** — 4-column, denser | **many thin wires** (cams, switches, 10 grippers) |

So: **C1 = motor/relay output** (original assumption + pinout-doc C1 table = CORRECT). The earlier bench-out ID (left=C1-34 / right=C2A-50) also holds. **No third connector** (Dylan confirmed exactly 2). The JOB-1 C1 cavity→relay map (S→D/J/N/T, T→A/E/K/P/H, etc.) is VALID as written.

**The one durable fix from the detour:** S and T = the **heavy-lug copper CONTACTORS** (NOT the Siemens — see next entry). Probe THOSE against C1.

### ⚠️ CORRECTION (2026-06-01): the Siemens is NOT a motor relay
Bench attempt to beep Siemens contacts → C1 found **no connection** (2 terminals, both open). Photos confirm WHY: the **Siemens 3TH4022 has only THIN control wires — no heavy motor leads** (it's a 4-pole CONTROL relay per its datasheet, no power poles). So it does NOT drive S or T and does NOT land on C1's motor cavities. **The real motor relays = the heavy-COPPER-LUG contactor(s)** immediately to its right (visible in 090449 / 091904: big saddle terminals + heavy-gauge motor leads). 
- **Revised roles:** Siemens 3TH4022 (24 VAC coil, 2NO+2NC) = likely the **interlock / control relay**, NOT S/T. Motor S & T = the heavy-lug contactor(s). 
- **JOB 1 worksheet assumption "S/T are the two upper-R relays incl. the Siemens" was WRONG** → rewrite JOB 1 to target the heavy-lug contactors once their count + layout is photographed.
- **Dylan's "open" reads were VALID data**, not a meter problem. (Meter on 200 Ω: real wire <2 Ω; "1"/"OL" = open. No beep needed.)
- **NEED PHOTOS:** the heavy-lug contactor area — how many contactors, each one's terminal layout + which carry the heavy motor leads.

**Design implication:** all coils are fed 24 V by the machine's own T2/T3/T4 → the board most likely just **switches** each coil circuit (AEDIKO dry contact in series), NOT supplies coil power → enclosure PSU stays simple (mostly 5 V). **Confirm via §C topology** (does each coil terminal go to a transformer/C1 pin vs. only to the Omega-Tek board driver?).

## NEXT
Session 2 = exact probe-point list, but it needs items 1–3 above first (a 10-min photo follow-up):
- count pins on each edge connector,
- head-on shot of each contactor's coil-voltage face,
- close shot of each connector's pin-1 end marking.
Then I produce "black on chassis, red on C1 pin N, expect X" for: safety chain → motor-stop wiring (hardwired vs logic) → C1 map → coil voltages.

**Coil-voltage note for the board design:** at least one relay is **12 VDC** (P&B). The AEDIKO drives the contactor COIL circuits; the mix of coil voltages here (12 VDC P&B + the Siemens/contactor AC or DC) sets what the AEDIKO contacts switch + whether we need a 12 V and/or 24 V coil rail in the enclosure. Confirm all coil voltages before finalizing the PSU pick (currently HDR-15-5 for 5 V; may also need 12 V).
