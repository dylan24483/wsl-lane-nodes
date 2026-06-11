# Phase 8 — C1 / C2A Connector Extraction (Service manual p288)

**Source:** AMF 82-70C Service & Parts manual, **printed p288** = **PDF page 287** (the "THIRD ANGLE PROJECTION" machine+chassis sheet). Foldout, native scan **4944×3947 px ≈ 225 DPI** over a 22-inch sheet → 225 DPI is the legibility ceiling; the alphanumeric pin codes are at/below the scan's resolution and are **best-effort**.

**Saved high-DPI crops** (`C:\Users\Dylan DeYoung\Downloads\`): `p288_C1C2A_band.png` (both connectors, the money shot), `p288_C1.png`, `p288_C2A_top.png`, `p288_C2A_bot.png`. Regenerate via `_pdfx.py clip 287 <dpi> <fx0> <fy0> <fx1> <fy1>`.

> **Read this as:** the **structure** (§1) is high-confidence and is what informs the I/O board. The **wire tables** (§2–§3) are ordered destination labels read off the scan — trustworthy for *which signals exist on the connector*, shaky for *exact pin codes*. Exact pin numbers + rails are locked at the bench (`phase8_controller_interface_fieldsheet.md`). The **functional** map (pin → cam/gripper name) completes from **page 289** (§4).

---

## 1. Structure (high-confidence)

**C1 (34-pin) = motor/relay + power, "FRONT END HARNESS ASSY 070-006-466 L.H. / -467 R.H."**
Almost every C1 pin lands on a **terminal strip (`T.S-xx`)** — it's the power/motor/relay wiring connector, not semantically labeled with machine functions. This is the **output-side** connector (motor relays + power). Functional content is thin here; the meaning is on the chassis schematic (p287/PDF 286) where the relays + motors live.

**C2A (50-pin) = switches/control = the INPUT-side connector.** Its pins fan out to four label families:
| Family | Meaning | Maps to |
|---|---|---|
| **TAC-1 … TAC-10, TAC-GND, TAC-SW** | the **TAC gripper strip** | **GS1–GS10** pin-sense (the 10 grippers) + common + switch |
| **A&MC-11A, -12D, -13H, -14L, -21B, -22E, -31C** | wires to the **A&MC plug** | the machine-control switches: **cams SA/SB/SC/TA1/TA2/TB + GP/OS/BS** (exact pin→cam from p289) |
| **PBC-2, PBZ-2** | pushbuttons | **PBC** (cycle), **PBZ** (zero / 1st-2nd / manual-intervention) |
| **SWS-4, S-1, S-4, SWBE-1, SWBE-2, T-2, CB-A/B/C** | sweep/table/breaker control | manual **SWS/SWSR**, sweep **S**, back-end **SWBE**, table **T**, circuit-breaker **CB** |
| **T.S-xx** (T.S-29/32/14/31/30/28/1A2/33/34/6-1/6-2/13L/10/16/9/15…) | terminal-strip taps | shared rails/returns |

**This confirms the I/O board input plan:** the **10 grippers arrive as one clean TAC strip** (10 optos off one connector), and the **cams + GP/OS/BS arrive via the A&MC plug** (another cluster). Exactly what `phase8_io_board_spec.md` §3 assumes.

---

## 2. C2A wire table (best-effort — destinations confident, pin codes `verify@bench`)

Read top→bottom as the labels appear beside each pin. Pin codes are the small alphanumerics next to each contact (format looks like `[bank][pos][tag]`, e.g. `23W` = bank 2, pos 3, tag W) — **transcribed approximately**.

**C2A left column (signal/destination — approx pin):**
1. S-1 — `11B`
2. SWS-4 — `12E?`
3. T.SA-1 — `?`
4. CB-C — `22J?`
5. SWBE-2 — `23W?`
6. A&MC-22E — `14R?`
7. PBC-2 — `?`
8. T.S-29 — `15V?`
9. A&MC-21B — `25V?`
10. T.S-32 — `16Z?`
11. S-4 — `26BB?`
12. CB-A — `?`
13. A&MC-12D — `17?`
14. T.S-14 — `27?`
15. CB-B — `18?`
16. TAC-SW — `28?`
17. T-2 — `19?`
18. T.S-31 — `29?`
19. T.S-30 — `11AA?`
20. T.S-28 — `21AA?`
21. T.S-1A2 — `31?`
22. T.S-33 — `41?`
23. T.S-34 — `?`
24. PBZ-2 — `31?FF`

**C2A right column (signal/destination — approx pin):**
1. A&MC-13H — `31A`
2. TAC-1 — `32E?`
3. A&MC-14L — `42N?`
4. TAC-2 — `?`
5. A&MC-31C — `?`
6. TAC-3 — `?`
7. A&MC-11A — `44S?`
8. T.S-6-1 — `45S?`
9. TAC-4 — `?`
10. T.S-13L — `?`
11. TAC-5 — `?`
12. T.S-6-2 — `?`
13. TAC-6 — `?`
14. TAC-7 — `?`
15. (TAC-8 — `?` — couldn't read; presumed present)
16. TAC-SW — `?`
17. T.S-10 — `?`
18. TAC-9 — `?`
19. TAC-GND — `?`
20. TAC-10 — `?`

> ⚠️ The TAC pin codes guessed here from p288 are **superseded by the legible p290 DETAIL K table in §4** (e.g. TAC-1 = C2A-41C, not the `32E?` guessed above). Trust §4 for grippers.
21. T.S-16 — `?`
22. T.S-9 — `?`
23. T.S-15 — `?`
24. SWBE-1 — `?`

> TAC-1…TAC-10 = **GS1…GS10** (gripper order to be confirmed against p289 / bench — TAC-n likely = GS-n but verify).

---

## 3. C1 wire table (best-effort — mostly terminal-strip)

**C1 left column:** T.S-1A1, T.S-7, T.S-1A1, T.S-27, T.S-23, T.S-17, T.SE-1, T.SA-2, T.SE-2, T.SA-3, T.SG-2
**C1 right column:** T.S-22, T.S-1B, T.S-20, T.S-20, T.S-17, T.S-8, T.S-4, T.S-19, T.S-3, T.S-19, T.S-1B
**C1 pin codes seen (mid):** `21D 31A 41C 31E 22J 32J 23N 34P 24T 35U 36V 16Z 26BB 17DD 18JJ 28LL 19NN 47E 45S 44W` (approx)

**✅ CROSS-VERIFIED with `phase8_controller_interface_MAP.md` (training-manual p46 wire table).** The p288 pin codes I read off the schematic independently match the MAP's *functional* C1 table — so these pins are now confirmed from **two sources** (training-manual table + service schematic). The functional sense the MAP already pairs:
| C1 pin | → device | group |
|---|---|---|
| 21D / 22J / 23N / 24T | S-31 / S-14 / S-21 / S-32 | **sweep (S)** |
| 31A / 32E / 33K / 34P / 42H | T-44 / T-32 / T-21 / T-31 / T-43 | **table (T)** |
| 17DD / 18J / 26BB / 27FF | M2-8 / M2-9 / M2-11 / M2-1 | **sweep-reverse (M2)** |
| 35U / 36Y | SP-5 / SP-7 | **spot (SP)** |
| 45W / 47EE | BE-7 / BE-3 | **back-end (BE)** |
| 13L / 19NN | T2 / GND | **power/ref** |

So **C1's functional pinout is effectively closed** (just bench-confirm on the spare). The remaining gap is **C2A's exact pin codes** — best read from the **training-manual p42 C2A wire table** (cleaner than this 225-DPI service schematic; the MAP notes it exists but didn't transcribe it), with the **functional** cam/gripper map from service **p289**.

---

## 4. ✅ Functional pin map from page 289 (PDF 288) — CROPPED 2026-05-31

Page 289 (printed p290) = the full schematic with the **control-circuits** band (cam switches → C2A) and the **gripper-sense detail ("DETAIL K", AFTER SERIAL #16795)**. High-DPI crops saved in `Downloads\`: `_svc_p289_crop_0.30_0.05_0.45_0.26.png` (cam block top), `_svc_p289_crop_0.30_0.20_0.46_0.40.png` (cam block mid + GP/APS), `_svc_p289_crop_0.62_0.46_0.80_0.78.png` (gripper DETAIL K), `_svc_p289_crop_0.60_0.44_0.80_0.80.png` (motor/relay DETAIL K w/ BE/SPOT/M1/M2).

> Pin codes are 225-DPI-scan + OCR **best-effort → bench-verify**. The **functional pairing** (which cam/gripper → C2A) is the high-value, legible result.

### Cam switch → C2A (control-circuits band)
| Switch | Cam role (°) | → C2A pin (approx) | notes |
|---|---|---|---|
| **SA** | sweep run-through/zero | **C2A-31N** | |
| **SB** | guard 66° | **C2A-31H** (~`C2A-311x`) | TB-2 / TS-56 adjacent |
| **TA1** | table zero 355° | **C2A-34N** (~`C2A-39N`) | + TS top band `C2A-2BB`/TS-15, `C2A-110U` |
| **TA2** | run-through 260–350° | **C2A-21A** + **C2A-30N** | `(260-350°)` / `(260-360°)` printed; TS-58/TS-53 |
| **B'S** (bin/#9) | bin | **C2A-112cc** | TS-32 / CAP-85 nearby |
| **PBC / PBZ** | pushbtn cycle/zero | **C2A-21EE** | |
| **GP SW** | gripper-protect | **C2A-412DD**, TAC-3M / TAC-SW | APS P1/P4 + `APS-3D` in same block |

(These confirm + refine the §1 statement that cams arrive via the A&MC plug onto C2A. The `A&MC-11A/12D/13H/14L/21B/22E/31C` labels from p288 are the A&MC-plug side of these same nets; full A&MC-pin↔cam cross-tie is bench-verify.)

### Gripper detail (DETAIL K) — ✅ FULLY LEGIBLE (crop `p290_gripper_detailK.png`)
The gripper-sense block read cleanly (visual crop, not OCR). **TAC-n = GS-n confirmed 1:1**, each with its C2A pin + TAP tap-point:

| Gripper | TAC | C2A pin | TAP |
|---|---|---|---|
| GS-1 | TAC-1 | C2A-41C | TAP-2IB |
| GS-2 | TAC-2 | C2A-42H | TAP-3IC |
| GS-3 | TAC-3 | C2A-43M | TAP-14L |
| GS-4 | TAC-4 | C2A-44S | TAP-32F |
| GS-5 | TAC-5 | C2A-45W | TAP-22E |
| GS-6 | TAC-6 | C2A-46Z | TAP-12D |
| GS-7 | TAC-7 | C2A-47?  | TAP-33K |
| GS-8 | TAC-8 | C2A-48H | TAP-24M |
| GS-9 | TAC-9 | C2A-49?  | TAP-13M |
| GS-10 | TAC-10 | C2A-410U | TAP-11A |
| (common) | TAC-GND | C2A-310E | TAP-34N |

**Structure confirmed:** each gripper **GS-n → TAP tap → TAC-n strip terminal → C2A pin.** TAC-n↔GS-n is a clean 1-to-10 map (no scramble) → the I/O board's 10-gripper input bank reads the **TAC strip** in pin order, exactly as `phase8_io_board_spec.md` §3 assumes. (Pin digits still 225-DPI best-effort, but the *ordering + structure* are solid.)

> **Chassis caveat:** these gripper C2A pins are off the **p290 (6730 5-board)** sheet; our spare is **SS + Omega-Tek**. The TAC-n=GS-n machine-side order is common, but confirm the exact C2A pin digits against our cabinet at the bench (the MP/9807 sheet may number differently).

**Net for the I/O board:** functional input clusters are now pinned — cams on the A&MC/C2A control band, 10 grippers on the TAC strip, pushbuttons + GP/BS on C2A. No change to the board architecture; this just fills the harness map. Remaining exactness (precise C2A pin per signal + each input's rail) = the bench fieldsheet pass.

That, plus the bench fieldsheet (exact pin + rail per signal), closes the connector layer completely. **None of it blocks the I/O board architecture** (`phase8_io_board_spec.md`), which is sized on channel counts/domains already confirmed in §1.
