# Phase 8 — Session Close / Handoff (2026-06-03)

> **READ THIS FIRST next session.** Live state + next action per thread, as of end-of-2026-06-03. The exhaustive detail is in the linked docs; this is the map + the state that only existed in the conversation. Supersedes `phase8_session_close_2026-06-01.md` for current state.

## 0. Cold-start orientation
- **Project:** Westside Lanes, 32 lanes / 16 pairs of AMF 82-70 pinsetters. Phase 8 = one Raspberry Pi per lane-pair replacing QubicaAMF scoring + (Track B) the pinsetter controller. Repo: `C:\Users\Dylan DeYoung\wsl-lane-nodes\` (separate from the main WSL app).
- **Two tracks:** **A = camera scoring** (near-term, code-complete, parked-ready). **B = controller replacement** (the active work this session — PCB rev-B + at-machine field characterization).
- **Three-way collaboration model (important):** Dylan = hands (fieldwork, soldering, KiCad runs). **Codex** = drives the PCB (SKiDL netlist, placement, routing) in its own context. **Claude** = independent auditor + field-guide author + decision arbiter. The working loop: Codex does → Claude re-verifies against the LIVE files (not Codex's report) → corrections logged in the docs. This loop has caught real bugs both directions; keep it.

---

## 1. TRACK A — camera scoring — CODE-COMPLETE, PARKED (untouched this session)
Not dead, just not the active thread. State unchanged since session-1 close: detection calibrated + validated, `MIRROR` confirmed, `DECK_TO_LANE={L:21,R:22}`, `camera.py` + rewired `lane_node.py`, server unchanged, safe-fallback to manual. **Single next action when resumed:** run `phase8_trackA_golive_runbook.md` on the Pi at 21/22 (capture empty ref → `--test` → `WSL_LANE_SCORING_MODE=camera` → soak). No code work left.

**✅ Claude pre-check 2026-06-03 (code GREEN):** `pin_detect.py` self-test passes on the real calibrated spots (20 PIN_SPOTS_PX, MIRROR, DECK_TO_LANE={L:21,R:22}, DET_THR=38); `camera.py` integration test (injected frame) passes — correct lane↔deck map + safe `None`→manual fallback; daemon camera path verified (settle→capture→emit, awaiting_manual on None, 200 ms L/R lockout, `WSL_LANE_CAMERA_STUB` real not drift, runbook log strings match the code). **One blocker found + FIXED:** the runbook pointed the Pi at the DEAD `192.168.86.36`; updated all URLs to **192.168.4.103** (eero swap) + added a banner — **still must confirm/reserve the WSL-SRV IP on the eero before the lane trip** (DHCP reservation TODO). Remaining are runbook soak-tune items, not code: the empty-ref capture (the one must-do install step), SETTLE_S=2.5 tune, pins 2&3 watch-first, MIRROR confirm with a deliberate 7/10.

---

## 2. TRACK B — PCB rev-B — BARE PCB FAB PACKAGE GENERATED

> **2026-06-03 route audit + fab-prep resolved.** Claude correctly caught a false-green 0-DRC where the routed `wsl-phase8b.routed-manual.kicad_pro` had lost netclass assignments, making `.dru` `hasNetclass()` rules inert. Codex fixed the route workflow, re-routed the class-aware failures, reran the live gates, then added `scripts/export_fab_revB.py` and generated the bare-PCB fab package. Current proof: `kicad/DRC-revB-routed-manual-classed.rpt` = **0 DRC violations / 0 unconnected pads / 0 footprint errors**, `scripts/audit_revB_board.py kicad\wsl-phase8b.routed-manual.kicad_pcb` = **ALL PASS**, and `kicad/fab_revB_routed_manual/reports/DRC-revB-routed-manual-fab.rpt` + `reports/audit-revB-board.log` repeat the same green gates inside the fab package. Claude independently re-verified route correctness before fab export: fresh DRC 0/0/0; netclasses LIVE (`GetEffectiveNetClass` = 80/4/13/66/21, not `Default:184`); `.dru` byte-unchanged (re-routed to the contract, NOT relaxed); routed `.kicad_pro` = 103 class refs = source; safety rail->K1-K7+pass-FET+TP16; J_MOTION split clean. **Current status:** bare PCB fab-ready under the conservative DRC contract; not assembly/cutover-ready. Detail: `phase8b_revB_route_pass1_findings.md` top block.
**Decision (locked):** ONE fully-integrated single-lane board per lane (no COTS AEDIKO/AL-ZARD). Self-contained: 3× MCP23017 + RP2040 (Pico stamp) + on-board opto-in (PC817) + on-board relay outputs (G5LE) + NE555 watchdog + isolated wetting (TMA-0505S). Function-named connectors + per-chassis adapter harness (so the machine-gated C2A bindings never touch copper).

### Where the board IS (current live truth)
- **Source board `kicad/wsl-phase8b.kicad_pcb`:** clean, re-banded, **DRC 0 / 488 unconnected** (unrouted). This is the canonical unrouted board — Codex routes onto a WORKING COPY, source stays clean.
- **Routed working board `kicad/wsl-phase8b.routed-manual.kicad_pcb`:** deterministic manual route is now **0 DRC / 0 unconnected / 0 footprint errors** with custom rules and netclasses active. Audit confirms safety-rail topology, OUT/Pico isolation, GND/FIELD_GND separation, keepout rule areas, and M1 DNP.
- **Fab package `kicad/fab_revB_routed_manual/`:** generated from the routed board with `scripts/export_fab_revB.py`. Use `wsl-phase8b-revB-gerber-drill.zip` for the bare-PCB upload and `wsl-phase8b-revB-fab-package.zip` for the full handoff. Package includes README, manifest/SHA256s, review PDF, DRC/audit logs, IPC-D-356, non-DNP BOM, CPL, DNP/excluded CSV, and the new front silkscreen labels for board ID/rev, domains, connectors, and M1 DNP.
- **Routing method:** `scripts/manual_route_revB.py` (deterministic, tiered) — NOT full-board FreeRouting (that was tried 4×, rejected: DSN can't carry the `.kicad_dru` creepage intent, and it failed to produce a `.ses` headless). Manual/scripted tiered routing + KiCad DRC gate is the accepted path.

### Board architecture facts (verified, don't relitigate)
- **5 net classes** (Logic_Signal 80 / Logic_Power 4 / Safety_Rail 13 / Field_Sense 66 / Machine_Output 21), all 184 nets classified, 0 anonymous N$.
- **3 domains physically banded** with no-copper gutter keepouts: FIELD (left, ~X74) │ gutter X76.8–80 │ LOGIC (center, X104–151) │ gutter X181–184 │ MACHINE (right, X176–178). Pairwise overlap = 0 (verified). Keepouts sit BETWEEN pad columns (Codex's catch — earlier version sat on the PC817 field column, blocking routes).
- **Isolation:** GND/FIELD_GND share 0 nodes. Barriers cross only inside opto/relay/PhotoMOS packages.
- **DNP state:** M1 channel remains DNP (8 parts; ball-return unverified), and the fab-prep pass also flags all value-DNP RC snubber/MOV suppression footprints. Current fab package count: **27 DNP refs**, all excluded from BOM/POS.
- **Board 250×225mm, 4-layer.** 216 schematic components / 236 board footprints including test pads and mounting holes / 184 named nets.

### QUEUED after bare-PCB fab package
1. **Vendor upload preview / order decision** — upload `kicad/fab_revB_routed_manual/wsl-phase8b-revB-gerber-drill.zip`, inspect every layer/drill/board-outline preview, then order the bare PCB if the preview matches the review PDF.
2. **Optional future `.kicad_dru` creepage relax 250VAC→24VAC** — A1 measured 24 VAC, so LOGIC↔MACHINE/FIELD barriers can drop from ≥3.2/2.5mm toward ~0.5–1mm. The current routed/fab package intentionally keeps the wide conservative rule; relaxing is optional for a later shrink/spin, not needed to order this bare PCB.
3. **Gripper chassis-return board note** — grippers are chassis-referenced (not the assumed TAC-common bus); confirm the opto-input front-end handles chassis-referenced returns. Flagged in `phase8_bench_JOB3_C2A_inputs.md`. Likely fine (still contact-to-a-reference); reference node identity just changed. Does NOT change isolation domains.
4. **RP2040 firmware** — ✅ v0.1.0 WRITTEN 2026-06-03: `firmware/rp2040/` (Pico C SDK). Pin map verified against the LIVE netlist (`block_rp2040`): fast inputs **GP6–GP13**, RP_OK **GP2**, UART **GP0/GP1** — NOT the stale draft in `phase8_channel_allocation.md` §2 (which said GP0–GP7). Fail-safe-low RP_OK supervisor, fast-input edge push over UART, motion max-run backstop, non-blocking TX ring. Cam-stop *overrun* + SC/TB collision echo deferred to **v1.1** (pending bench cam edge→angle polarity — a deferred cutover field item). **Both firmware verifications GREEN (2026-06-03):** host logic test **24/24** + a **clean Pico-SDK ARM cross-build → `.uf2`** (~24KB flash / 2.6KB RAM). Toolchain bootstrapped on the laptop scriptably (no MSI/admin): xpack arm-none-eabi-gcc + WinLibs cmake/ninja + cloned pico-sdk; `firmware/rp2040/build.ps1` = one-command rebuild. **Pi-side DONE + sim-tested:** `rp2040_link.py` reader **29/29**, `controller_io.py` generator-drift guard green, and `controller_daemon.py --selftest` **22/22** (per-board assembly: link+io+FSM tick loop, power-down rule, arm policy, watchdog-via-poll, health-loss safety trip). NEEDS: on-hardware bench bring-up (spec §12.9) + real pin/bus/port config (# CONFIRM in `controller_daemon.DEFAULT_BOARDS`) + unify with the Track-A scoring/server path (TODO(server)). **Codex audit of firmware+Pi-side DONE 2026-06-03 — 5 findings, all addressed:** daemon health-loss safety trip (motors off + MANUAL_INTERVENTION + require PBZ); `controller_io` bit-maps realigned to the netlist generator (BS/OS + M1/M2 + strike/foul were swapped) + ast drift-guard; link `flt`→unhealthy; IN-B 0x21 instantiated; firmware reconciled to **NOT cutover-ready** (G3 cam-stop gate needs v1.1 cam-stop overrun, bench-gated on §3.2 cam polarity).
5. **Cutover runbook** — ✅ DRAFTED 2026-06-03: `phase8_trackB_controller_cutover_runbook.md` (Track-B controller swap; consolidates the deferred field items as a cutover-day capture procedure + lockout/tagout + staged rail-disabled bring-up + go/no-go gates + rollback). Refine after unit-#1 bench bring-up.

---

## 3. FIELD SESSION — COMPLETE (all design-gating data extracted)
Full results table in `phase8b_at_machine_fieldsheet.md` (top) + `phase8b_pcb_revB_BOM_power.md`. Summary:
| item | result | impact |
|---|---|---|
| A1 working voltage | **24 VAC** (all relays; SP presumed) | creepage can shrink → smaller board |
| A3 lamp supply | **15 VDC** → **replaced by board-driven LEDs** (Dylan decision) | −4 PhotoMOS, lamps now logic-domain |
| A4 cam input | **dry contact, normally-closed** | cam front-end = dry-contact wetting |
| B3 Stop/CIS | **parallel, cut master breaker** (from OEM svc manual p11 — no probing) | preserve upstream chain |
| B1 TB/SC interlock | **parallel into 24V control path** (OEM); exact terminals → cutover | J_SAFETY = NC series loop |
| B2 cam-stop logic/HW | leans LOGIC; → cutover cam-flip | not a design gate |
| Grippers | **chassis-return; gripped = CLOSED to ground** (corrects OEM TAC-common model) | gripper input = chassis-referenced, FIELD-side |

**Deferred to cutover (deliberately — NOT worth bench time; easier with machine apart + live feed):** per-gripper GS#→pin labels (drop a pin, watch the feed), per-cam→cavity labels, exact C1/C2A + TB/SC terminal landings. **None gate the PCB** (function-named + harness-resolved).

---

## 4. KEY DECISIONS LOCKED THIS SESSION (don't relitigate)
- Status lamps → **our own LEDs in the mask housings, driven from our 5V logic** (not the machine 15V). PhotoMOS removed, lamps off the machine domain. IMPLEMENTED in netlist/board.
- Creepage will relax to **24 VAC** numbers (measured) — pending explicit policy numbers before final lock.
- Grippers are **chassis-return, gripped=closed** — corrects the schematic's TAC-common assumption (our SS+Omega-Tek chassis differs from OEM 9800-MP, same divergence as M2/S-cavities).
- Full-board autoroute is **abandoned**; manual/scripted tiered routing is the path.
- M1 stays **DNP** until verified at-machine.

---

## 5. THE CLAUDE↔CODEX LOOP — discipline that's working
- **Codex implements, Claude audits against LIVE files** (parse the .net/.kicad_pcb, re-run DRC) — never just trust the report. This caught: the islanded first netlist, the N$*-misclassification, the keepout-on-pad-column, and corrected Claude's own wrong "zero dnp" claim.
- **Claude's recurring failure mode (note-to-self):** over-broad generalizations ("generates=wired", "N$*=logic", "SAFE_*=machine-domain", "zero dnp"). On this board: **enumerate the actual cases + verify exact syntax; don't pattern-match a convenient default.**
- **Corrections live in the docs**, not just chat — so they survive. Every audit verdict is logged in `phase8b_revB_route_pass1_findings.md` or the spec.

---

## 6. AUTHORITATIVE DOC INDEX (where the real detail lives)
- `phase8b_pcb_revB_spec.md` — the hard electrical contract (the audit-trail header blocks are the decision history).
- `phase8b_pcb_revB_BOM_power.md` — parts + power rails + the field-result fab-lock inputs + LED decision.
- `phase8b_pcb_revB_netclass_creepage.md` — net classes + creepage policy (the routing contract).
- `phase8b_revB_netclass_inventory.md` — all 184 nets → domains.
- `phase8b_revB_route_pass1_findings.md` — routing status + every Claude/Codex audit verdict + FreeRouting rejection log.
- `phase8b_at_machine_fieldsheet.md` + `phase8b_at_machine_HOWTO_companion.md` + `phase8b_field_concepts_primer.md` — the field session (now complete) + the PDFs in `Downloads/`.
- `phase8_bench_session1_FINDINGS.md` — bench (spare cabinet) characterization: C1/C2A roles, coil voltages, relay IDs.
- `phase8_oem_doc_audit_2026-06-02.md` — OEM manual mining + OEM-vs-bench reconciliation.
- `phase8_trackB_controller_cutover_runbook.md` — the lane 21/22 controller-swap cutover (deferred-field capture + lockout/tagout + staged rail-disabled bring-up + go/no-go + rollback). Track-A scoring go-live is the separate `phase8_trackA_golive_runbook.md`.
- `firmware/rp2040/README.md` — the RP2040 co-processor firmware v0.1.0: authoritative pin map (from the live netlist), UART event/command protocol, Pi-side integration contract, fail-safe RP_OK safety model, and the bench bring-up checklist.
- Scripts: `scripts/generate_kicad_netlist_revB.py`, `place_components_revB.py`, `apply_netclasses_revB.py`, `manual_route_revB.py`, `export_fab_revB.py`, `export_specctra_revB.py`.

---

## 7. START-HERE NEXT SESSION
1. Read this + skim `phase8b_revB_route_pass1_findings.md` (routing/fab). Current bare-PCB artifact is `kicad/fab_revB_routed_manual/wsl-phase8b-revB-gerber-drill.zip`.
2. Before ordering: upload-preview the gerber/drill zip in the fab vendor UI and compare against `kicad/fab_revB_routed_manual/review/wsl-phase8b-revB-review-layers.pdf`.
3. If any board edit happens, rerun `scripts/export_fab_revB.py`; it re-runs DRC + audit and regenerates all package files.
4. **Track A** can go live independently anytime via its runbook (parallel, Pi-side, not blocked by B).
5. Field session is CLOSED — remaining field items are cutover-day, now consolidated in `phase8_trackB_controller_cutover_runbook.md` §3 (DRAFTED 2026-06-03).
