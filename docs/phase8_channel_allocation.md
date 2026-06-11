# Phase 8 — Lane-Node Channel Allocation (the PCB/firmware bridge)

**What this is:** the concrete per-channel map that turns `phase8_io_board_spec.md` (architecture) into something a **PCB tool** and the **firmware** can both consume — every signal assigned to a device + port-pin, with its electrical domain, its C1/C2A source, and the `cycle_control_8270.py` `io.*` method that uses it. **This doc gates rev-B PCB (#21) and the gpiozero/io-wrapper layer.**

**Reads-with:** `phase8_io_board_spec.md` (why), `phase8_C1_C2A_pinout_p288.md` (where the machine pins are), `cycle_control_8270.py` (the io contract), `phase8_8270_SYSTEM_REFERENCE.md` (the system).

> **Status: DRAFT (2026-05-31 session 5).** Channel COUNTS + bank structure are firm. Exact MCP port-pin assignments are a clean first cut (rearrange freely for layout). The three architecture refinements in §6 are **DECIDED/ADOPTED (Dylan, 2026-05-31)** → self-contained identical single-lane boards. C1/C2A pin digits are 225-DPI best-effort → bench-verify.

---

> **Companion code (session 5):** `lane_node/controller_io.py` implements this map as the concrete FSM `io` object — `MachineIO` (3× MCP23017 over the per-board I²C bus, using the OUT_A_MAP / IN_A_MAP bit assignments below + the GS1–10 mask) and `RecordingIO` (no-hardware fake). Its smoke test drives the real `cycle_control_8270` FSM through a full strike cycle off-Pi (exit 0). Hardware path needs `smbus2` on the Pi; the RP2040 link (fast cam/ball + cam-stop) is injected, still `# CONFIRM`.

## 0. Scope unit = ONE LANE = ONE BOARD
A pair = 2 lanes = **2 identical single-lane boards** stacked on one Pi (io-board spec §9 Option B, recommended). Develop+validate one board, clone. All tables below are **per lane/board**; the pair is ×2.

This matches: one camera→both decks (Track A), one Pi→both lanes, but **one board per lane** for clean bring-up + rework. (The camera is the only truly shared part; everything wired to the machine is per-lane.)

---

## 1. The FSM's actual I/O surface (the minimum viable controller)
Straight from `cycle_control_8270.py`'s `io` interface — this is what MUST exist; everything else in the spec is future/optional.

| io method | dir | signal(s) | count |
|---|---|---|---|
| `set_sweep` | OUT | **S** relay | 1 |
| `set_table` | OUT | **T** relay | 1 |
| `set_spot` | OUT | **SP** relay (solenoid) | 1 |
| `set_light` | OUT | 1st-ball, 2nd-ball, strike, foul lamps | 4 |
| `set_pin_lamps` | OUT | pin lamps 1–10 | 10 *(OPTIONAL — camera drives, §3)* |
| `read_grippers` | IN | **GS1–GS10** | 10 |
| `gp_closed` | IN | **GP** | 1 |
| `bs_closed` | IN | **BS** | 1 |
| `interlock_ok` | IN | TB+SC (software echo; HW interlock is separate) | (2) |
| cam events¹ | IN | **SA, SB, SC, TA1, TA2, TB** | 6 |
| `on_ball` | IN | **SS / DIELL** | 1 (2 beams) |
| `on_foul` | IN | **Foul** (Radaray) | 1 |
| `first_ball_zero` | IN | **PBZ** | 1 |
| `watchdog_kick` | OUT | NE555 kick (board-level, 1/pair) | — |

¹ cam events arrive as method calls (`cam_SB_guard()` …), not pin polls — so they can come from direct GPIO IRQ **or** from the RP2040 over the link (see §6 refinement #1).

**FSM-required minimum:** 12 outputs (S,T,SP + 4 lamps + …) and ~21 inputs. The spec's **M, BE, M1, M2** relays and **OS, PBC, 10th, manual T/S/SWS/SWSR** inputs are NOT yet used by the FSM — they're wired on the board (spare-allocated) for when the FSM grows to full machine control. Marked ⊕ below.

---

## 2. INPUT allocation (per lane)

### FAST inputs → RP2040 co-processor (latency-critical: cam-stops)

> **⛔ SUPERSEDED (2026-06-10) — the `RP2040 GPIO` column below is the pre-layout DRAFT and is WRONG vs the as-built rev-B board.** Authoritative pin map = `scripts/generate_kicad_netlist_revB.py` `block_rp2040()` (the live netlist) and `firmware/rp2040/config.h` / `firmware/rp2040/README.md`: **UART to the Pi on GP0/GP1, `RP2040_OK` (rail permission) on GP2, and the 8 fast inputs on GP6–GP13** (SA=GP6 · SB=GP7 · SC=GP8 · TA1=GP9 · TA2=GP10 · TB=GP11 · DIELL-L=GP12 · DIELL-R=GP13). Note in particular: the draft puts SC on GP2 — on the real board GP2 is `RP2040_OK`. Table kept only for the signal / front-end / C2A-source / used-by columns.

| ch | signal | RP2040 GPIO | front-end | C2A src | used by |
|---|---|---|---|---|---|
| 1 | SA (sweep 270/360°) | GP0 | opto-in | C2A-31N | cam_SA_* |
| 2 | SB (guard 66/186°) | GP1 | opto-in | C2A-31H | cam_SB_guard |
| 3 | SC (interlock 86–243°) | GP2 | opto-in | C2A-? | interlock (HW + echo) |
| 4 | TA1 (table 355/185°) | GP3 | opto-in | C2A-34N | cam_TA1_* |
| 5 | TA2 (run-through 260°) | GP4 | opto-in | C2A-21A/30N | cam_TA2_runthrough |
| 6 | TB (interlock 105–255°) | GP5 | opto-in | C2A-? | interlock (HW + echo) |
| 7 | DIELL-L (ball) | GP6 | opto-in (proven) | (DIELL) | on_ball |
| 8 | DIELL-R (ball) | GP7 | opto-in (proven) | (DIELL) | on_ball |

The RP2040 enforces the cam-position **motor-relay drop in hardware** (cam edge → pull the relay-enable rail) independent of Pi scheduling, AND forwards cam/ball EVENTS to the Pi for the FSM. SC+TB also feed the **hardware** TB/SC interlock directly (§5) — the RP2040 read is the software echo only.

> **⚠️ Correction (2026-06-10):** "enforces … in hardware" is the **target** design, not what's shipped. Firmware **v0.1.0/v0.2.0 explicitly does NOT enforce per-cam-edge cam-stops** — that is deferred to **v1.1**, because it needs the bench-confirmed per-cam edge→angle polarity (a deliberately-deferred cutover field item, `phase8_trackB_controller_cutover_runbook.md` §3.2). Shipped firmware provides health/heartbeat (`RP2040_OK`) plus the **8 s motion max-run backstop** only — see `firmware/rp2040/README.md`. This note applies everywhere this doc says the RP2040 cam-stop "enforces"/"acts on" the rail (§5, §6 #1, §7).

### SLOW inputs → MCP23017 #IN-A (I²C 0x20) + #IN-B (0x21)
| ch | signal | chip.port.pin | front-end | C2A src | used by |
|---|---|---|---|---|---|
| GS1 | gripper 1 | IN-A.A0 | opto, dry→TAC-GND | C2A-41C | read_grippers |
| GS2 | gripper 2 | IN-A.A1 | opto | C2A-42H | " |
| GS3 | gripper 3 | IN-A.A2 | opto | C2A-43M | " |
| GS4 | gripper 4 | IN-A.A3 | opto | C2A-44S | " |
| GS5 | gripper 5 | IN-A.A4 | opto | C2A-45W | " |
| GS6 | gripper 6 | IN-A.A5 | opto | C2A-46Z | " |
| GS7 | gripper 7 | IN-A.A6 | opto | C2A-47? | " |
| GS8 | gripper 8 | IN-A.A7 | opto | C2A-48H | " |
| GS9 | gripper 9 | IN-A.B0 | opto | C2A-49? | " |
| GS10 | gripper 10 | IN-A.B1 | opto | C2A-410U | " |
| GP | gripper-protect | IN-A.B2 | opto | C2A-412DD | gp_closed |
| BS | bin/#9 | IN-A.B3 | opto | C2A-112cc | bs_closed |
| OS ⊕ | off-spot | IN-A.B4 | opto | C2A-? | (future) |
| PBZ | zero/1st-2nd/manual-int | IN-A.B5 | opto, momentary | C2A-21EE | first_ball_zero |
| PBC ⊕ | cycle pushbutton | IN-A.B6 | opto, momentary | C2A-21EE area | (future) |
| Foul | Radaray | IN-A.B7 | opto, edge | (foul det) | on_foul |
| 10th ⊕ | 10th-frame | IN-B.A0 | opto | C2A-? | (future) |
| man-T ⊕ | manual table | IN-B.A1 | opto | C2A (T-2) | (future) |
| man-S ⊕ | manual sweep | IN-B.A2 | opto | C2A (S-1/4) | (future) |
| man-SWS ⊕ | manual sweep-sw | IN-B.A3 | opto | C2A (SWS-4) | (future) |
| man-SWSR ⊕ | sweep reverse | IN-B.A4 | opto | C2A-? | (future) |

IN-A INT→Pi GPIO (change-interrupt, not polling); IN-B same. **IN-B has 11 spare pins** (B-bank free) → expansion headroom.

> **Front-end is jumper-selectable DC-dry-contact ↔ AC/voltage-sense per channel** (io-board spec §3) — each input's real rail (5 VDC vs 24 VAC) is bench-verified per the fieldsheet; the board doesn't hard-assume.

---

## 3. OUTPUT allocation (per lane) → MCP23017 #OUT-A (0x22)
Baseline assumes **camera drives the mask pin-data** (Track A), so the 10 pin-lamp outputs are **depopulated** (optional OUT-B board, §3a). That trims outputs to 11 → one MCP23017.

> **⚠️ HARNESS UPDATE (bench-confirmed 2026-06-01): outputs are SPLIT across C1 + C2A** — see `phase8_bench_session1_FINDINGS.md`. This does NOT change the board's OUT-A channel table (the board drives AEDIKO coils; the AEDIKO *contacts* wire to whichever machine connector). It DOES change the field-wiring "machine connector" column:
> - **S, T (high-current main motors) → C1** (heavy-pin connector w/ power cavities). Measured C1 cavities: **S = C,D,N,T · T = A,K,H,E (+L through-coil)** — note S-T1=**C** (predicted J) and T=**L** where P was predicted; measured wins, predicted-codes below are the 225-DPI guesses.
> - **M2 (sweep-rev), SP (spot solenoid), BE (back-end) — low-power loads → C2A** (all direct 0 Ω; BE coil also taps C1-FF @66Ω).

| ch | signal | chip.port.pin | driver | load | machine connector (bench) | used by |
|---|---|---|---|---|---|---|
| S | sweep relay | OUT-A.A0 | opto→ULN→AEDIKO | 24V coil→115V motor | **C1: C,D,N,T** ✅ | set_sweep |
| T | table relay | OUT-A.A1 | " | " | **C1: A,K,H,E (+L)** ✅ | set_table |
| SP | spot solenoid | OUT-A.A2 | " | 24V coil→solenoid | **C2A** (0 Ω) ✅ | set_spot |
| BE ⊕ | back-end relay | OUT-A.A3 | " | continuous motor | **C2A** (+C1-FF→coil) ✅ | (future; runs continuous) |
| M ⊕ | master relay | OUT-A.A4 | " | power/halo/pit | TBD (bench) | (future) |
| M1 ⊕ | ball return | OUT-A.A5 | " | ball-return motor | TBD (bench) | (future) |
| M2 ⊕ | sweep reverse | OUT-A.A6 | " | sweep-rev | **C2A** (0 Ω) ✅ | (future) |
| L-1st | 1st-ball lamp | OUT-A.A7 | opto→MOSFET | 12V (PM-E24) | mask | set_light('first_ball') |
| L-2nd | 2nd-ball lamp | OUT-A.B0 | " | 12V (PM-E25) | mask | set_light('second_ball') |
| L-foul | foul lamp | OUT-A.B1 | " | 12V (PM-E27) | mask | set_light('foul') |
| L-strike | strike lamp | OUT-A.B2 | " | 12V (PM-E26) | mask | set_light('strike') |

OUT-A.B3–B7 spare (5 pins). **Every motion-relay coil sits downstream of the relay-enable rail** (§5) — watchdog/arm/interlock can always drop them. **Note:** since outputs span C1+C2A, the enclosure harness needs leads to BOTH machine connectors from the relay bank (not just C1) — minor field-wiring note, no board change.

### 3a. OPTIONAL OUT-B (0x23) — physical mask pindicator (only if NOT camera-driven)
pin lamps 1–10 (opto→MOSFET/SSR + series D1–D10, 12V) on OUT-B.A0–B1, + neon (SSR, 125VAC) on OUT-B.B2. **Depopulate if the camera supplies mask pin-data** (the convergence win — io-board spec §1). Baseline build OMITS this chip.

---

## 4. Device/bus summary (per lane board)
| device | I²C addr | role | pins used / 16 |
|---|---|---|---|
| MCP23017 IN-A | 0x20 | grippers + GP/BS/OS/PB/foul | 16 / 16 (full) |
| MCP23017 IN-B | 0x21 | 10th + manual + spare | 5 / 16 |
| MCP23017 OUT-A | 0x22 | 7 relays + 4 status lamps | 11 / 16 |
| MCP23017 OUT-B | 0x23 | pin lamps + neon | OPTIONAL (camera-driven → omit) |
| RP2040 | — | 8 fast in + cam-stop enforce + Pi link | 8 in / 30 |

**Baseline = 3 MCP23017 + 1 RP2040 per lane/board** (OUT-B omitted; §6 adopted = one RP2040 + own I²C bus per board). Full physical-mask build = 4 MCP23017/board.

### Pi GPIO budget (per pair, both boards on one Pi) — reflects §6 adopted
Two **independent I²C buses**, one per board; each board repeats 0x20–0x23. Each board has its own RP2040 + INT lines + arm GPIO.

| Pi GPIO | use |
|---|---|
| GPIO2/3 | **I²C bus-1 (SDA/SCL)** → board-21's 3× MCP23017 (0x20–0x23) |
| GPIO?/? | **I²C bus-2** (software/GPIO i2c via `dtoverlay=i2c-gpio`) → board-22's MCP23017 (0x20–0x23) `# assign pins` |
| GPIO12 | NE555 watchdog kick — board-level (existing — `lane_node.WATCHDOG_KICK_PIN`)² |
| GPIO23,24 | board-21 IN-A/IN-B INT `# assign` |
| GPIO25,16 | board-22 IN-A/IN-B INT `# assign` |
| GPIO?,? | per-board "arm" GPIO → relay-enable rail (§5), one each |
| GPIO?,? | per-board RP2040 event/IRQ line (if link is UART/IRQ not I²C) |

² Watchdog: today one kick pin is board-level. With two boards each having a relay-enable rail, decide one NE555-per-board (two kick pins) vs one shared — `# CONFIRM` at layout; per-board matches the independence goal.

> **Migration from the Phase-8a node:** today `lane_node.py` `LANE_GPIO` drives `cycle`+`power` as single direct-GPIO relays per lane (existing controller still runs the machine; we just pulse it). The Track-B controller **replaces** that with this full relay set. The Phase-8a `foul/ball2/diell/cycle/power` GPIO map stays valid for the scoring pilot; the controller board supersedes it at Track-B cutover (the cam/relay/gripper channels here did not exist in the 8a node).

---

## 5. Relay-enable rail (safety — the one rail that matters)
ALL motion-relay coils (S,T,SP,BE,M,M1,M2) are powered through a series **relay-enable rail** gated by the AND of:
1. **NE555 watchdog OK** (Pi kicks GPIO12 < ~10 s, else rail drops) — bench-validated.
2. **Pi "arm" GPIO** asserted (de-asserts on power-down rule until operator First-Ball-Zero).
3. **Hardware TB+SC interlock** closed (the two cams in parallel in the 24 V control path — io-board spec §6 / SYSTEM_REFERENCE §5).
4. **Master breaker** on (stop/CIS chain).
Any one false → all motors drop. The RP2040 cam-stop also acts on this rail *(target design — cam-stop enforcement is firmware **v1.1**, not yet shipped; v0.1.0/v0.2.0 = health + 8 s max-run only — see the 2026-06-10 correction in §2)*. **None of this is bypassable by the Pi in software.**

---

## 6. ✅ THREE refinements vs `phase8_io_board_spec.md` — ADOPTED (Dylan, 2026-05-31)
All three adopted → **self-contained identical single-lane boards** (develop one, clone). The tables in §2–§4 already reflect them.

**#1 — RP2040 OWNS the fast inputs + forwards events** (vs spec's "Pi GPIO IRQ AND mirror to RP2040"). The RP2040 owns cams+DIELL, enforces cam-stops in **hardware** (cam edge → drop the relay-enable rail, independent of Pi scheduling) *(cam-stop enforcement = firmware **v1.1**, not yet shipped — see §2 correction)*, and forwards cam/ball *events* to the Pi for the FSM **over UART** (see §7 — chosen because the RP2040 can PUSH events; an I²C/SPI slave can't initiate). The FSM consumes events not pin-polls → nothing lost, and the Pi 40-pin header isn't blown by 16 fast inputs across the pair. Safety note: cam-STOPS are hardware on the RP2040 and do NOT depend on the link; only the FSM's event *notification* rides the link.

**#2 — Per-board I²C bus.** Each board gets its own bus (Pi `i2c-1` + a second via `dtoverlay=i2c-gpio`), so **each board uses 0x20–0x23 identically**. Avoids the zero-headroom 0x20–0x27 shared-bus fill; makes the two boards electrically identical ("clone the board").

**#3 — One RP2040 per board.** Each board is self-contained with its own cam-stop enforcement; the two lanes are decoupled. (Costs one extra RP2040 vs one-per-pair — worth it for independence + identical boards.)

**Consequence for layout:** design ONE single-lane board (3 MCP23017 @ 0x20–0x23 + 1 RP2040 + opto-in/relay-out banks + the NE555 watchdog/AC-interposer that already exist), bring it up fully on the spare, then build a second identical board. The Pi runs two I²C buses, one per board. **This is what PCB rev-B (#21) lays out.**

---

## 7. Finalization items

### ✅ RP2040 ↔ Pi link — DECIDED: **UART** (session 5)
Evaluated UART vs I²C-peripheral vs SPI for the cam/ball-event link:
- **UART (chosen).** Dedicated point-to-point, async, no shared-bus contention with the MCP23017s. The RP2040 PUSHES events the instant a cam/DIELL edge fires (no Pi polling) — exactly the event-forwarding model #1 wants. Only 2 Pi pins per board (TXD/RXD); the per-board buses are different UARTs (Pi has multiple PL011/mini-UARTs, or `uart-gpio`-style soft UARTs). Dead-simple framing (newline-delimited JSON or a 1-byte event code). Failure is detectable (RP2040 can heartbeat over the same line; Pi sees silence).
- ✗ **I²C-peripheral:** the RP2040 would be a *slave* → the Pi must POLL it (I²C slaves can't initiate), defeating push-events; and it'd share the board's I²C bus with 3 MCP23017s → contention on the latency-critical path. Reject.
- ✗ **SPI:** also Pi-master-polled (RP2040 as SPI slave can't initiate); more pins (4); overkill bandwidth we don't need. Reject.
- **Note:** the link carries EVENTS only. The safety-critical **cam-STOP stays entirely on the RP2040** (cam edge → relay-enable rail) *(v1.1 — see §2 correction; shipped firmware = health + 8 s max-run backstop)*, so a dead UART can't cause unsafe motion — it just means the FSM stops getting event notifications (→ motion-timeout FAULT, fail-safe). Protocol spec = a future small doc; baseline = newline-JSON `{"ev":"SB_guard"}` / `{"ev":"ball"}` at 115200.

### ✅ AEDIKO relay specs — FOUND in `pcb_design_spec.md` (no sourcing needed)
Captured during Phase-8a watchdog work:
- **Coil:** ~**70 mA each @ 5 V** (8ch → 560 mA worst case); coil rail spec **4.5–6 V**. (So the board's relay-coil rail is **5 V**, not 24 V — simpler than the io-spec's generic "24 V coil" placeholder; the AEDIKO is a 5 V module.)
- **Flyback:** the AEDIKO module has its own onboard relays + opto inputs (it's a complete relay HAT, not bare coils) → flyback handled on-module; the Pi GPIO drives its IN pins through the module's optos. **No external ULN2803 needed** for the AEDIKO path — that simplifies OUT-A (the spec's "opto→ULN→coil" collapses to "GPIO/MCP→AEDIKO IN").
- **Watchdog gating:** proven — NE555→AO3400 low-side MOSFET gates the AEDIKO **V− return** (5.7 A FET, 560 mA load = massive margin). Already bench-validated.
- **Contact rating vs motor inrush:** ⚠️ the AEDIKO switches the **contactor COIL circuit**, NOT the motor directly (the machine's existing contactors switch the 115 V motor). So the AEDIKO contact only needs to handle the contactor-coil current — small. **The motor inrush is the existing contactor's job, preserved.** This is the key safety/simplicity win: we drive coils, the machine's iron switches the motors. *(Confirm each contactor's coil voltage/current at the bench — `phase8_8270_replacement_plan.md` Stage notes A1/A2 coil reads.)*

### Bench-gated (the remaining unknowns — need the spare cabinet)
- **Fieldsheet pass** (`phase8_controller_interface_fieldsheet.md`): exact C1/C2A pin digits + each input's real rail (5 VDC / 24 VAC / dry) → confirms the `?` pins + jumper defaults. **This is the one true blocker for finalizing the board.**
- **Contactor coil voltages** (label/meter read, A1/A2) → confirms what the AEDIKO contacts switch.
- §3a: physical mask retained (build OUT-B) vs camera-driven (omit). **Track A is live-bound → omit** (baseline already omits).

None of these block the channel COUNTS or bank structure — so PCB rev-B placement can start on this draft once §6 is decided.
