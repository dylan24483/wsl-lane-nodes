# Phase 8 Rev-D — Codex ROUND-2 Remediation Report (2026-07-21, closing record)

**Scope.** Codex re-audited the remediated rev-D package (2026-07-21 PM) under a
**fabrication-readiness bar**, rejected the round-1 15/2/1 tally (its re-grade: 7
closed / 9 partial / 2 open), and issued 17 concrete findings **R2-1 … R2-17**.
Dylan's standing instruction: incorporate all agreed findings. This report is the
**closing record of the round-2 campaign**: final status per finding with evidence,
the two nuanced dispositions stated plainly, the round-3 fix batch (Codex re-review
of the round-2 package — 8 further findings, all fixed), the independent
re-verification pass and the finalize batch that closed its residuals, the recorded
repo states, and the definitive open-gates list.

**Companions:** `phase8_revD_remediation_report_2026-07-21.md` (round-1 closing
record — SUPERSEDED as "final word" by this report), `phase8_revD_remediation_spec_2026-07-21.md`
(R1–R4 + new §R4-A), `phase8_revD_change_list.md`, `phase8_revD_readiness_checklist.md`,
`phase8_revD_run_log.md` (ROUND-2 / ROUND-3 / FINALIZE-round-2 records),
`phase8_revD_first_article_pack.md` (generated — FA-1…FA-12), `docs/HANDOFF.md` addenda.

---

## 0. Verdict

| # | Finding (short) | Final status |
|---|---|---|
| R2-1 | Pad-level OEOVER bypass of the input-only invariant | **CLOSED** (fw v1.2.2 + round-3 boot-order fix; NOT flashed) |
| R2-2 | Stale "~825 k" R_TAPIN guidance survived the correction | **CLOSED** (both-repo sweep; 3 live occurrences → 1 M / ≥917 k floor) |
| R2-3 | Q17–Q20 locked to an under-documented MPN | **CLOSED** (onsemi 2N7002LT1G, LCSC C16338; export hard-assert; FR-10) |
| R2-4 | J16 unprotected (raw rails, no ESD, wedgeable bus) | **CLOSED** (F1/JP1/U46/U47 stack + FA-12 short test; severity = availability) |
| R2-5 | First-article pack untestable (blank nets, wrong hb names, no probe discipline) | **CLOSED** (fail-closed parser; v5/v5n/v5x; TP17–24 + silk; ≥100 MΩ probe rule; pad-directed FA-7) |
| R2-6 | No board-rev identity; revC-default config swallowed AUX roles | **CLOSED** (REV_ID straps 0b01; fw id line; mandatory explicit per-lane board_rev; round-3 ID-request fix) |
| R2-7 | PC817B margin rests on typical-curve reads | **DISPOSITIONED-WITH-EVIDENCE** (§2, spec §R4-A + FA-9 per-channel qualification; NO redesign) |
| R2-8 | deploy.ps1 blind to the lane server; no identity check | **CLOSED** (restart proof FATAL + authed POST smoke + build-hash compare; separation disposition in §2) |
| R2-9 | HTTP diagnostics leg unshipped by default | **CLOSED** (systemd EnvironmentFile provisioning; JSONL-only = degraded mode) |
| R2-10 | Dead board indistinguishable from healthy | **CLOSED** (5-state leases end-to-end; OFFLINE alerts; drill 12/12) |
| R2-11 | v1.2.x telemetry unconsumed on the Pi | **CLOSED** (full record consumption; epoch-aware stale-edge exclusion) |
| R2-12 | Lossy event delivery; no dedup/replay | **CLOSED** (JSONL-as-outbox, (source_id,boot_id,seq), cursor-ack, idempotent inserts) |
| R2-13 | fw v1.2.2: OEOVER + epoch classifier + FI-1 + identity | **CLOSED** (built, host-tested, ARM-verified; round-3 amendments; **NOT flashed**) |
| R2-14 | Camera self-checks unscheduled; Pi health shallow | **CLOSED** (production-path scheduling; GS-vs-camera counter; disk/thermal/clock/restart/retention) |
| R2-15 | Fab-artifact defects (MATCH-AT-UPLOAD, rev mislabel, coding qty) | **CLOSED** (C26108 pin; --rev-derived paths; qty 4/board; round-3 tombstones + gbrjob "D") |
| R2-16 | Catalog/docs gaps (P0/P1 conditions, AUX priority, SC/TB, banner, H2) | **CLOSED** (catalog v1.1; field_wet_ok implemented in software; H2 citation + waiver line) |
| R2-17 | Machine diagnostics data outside backup scope | **CLOSED** (diag DB + JSONL/blackbox in deploy.ps1 backup section + NAS gate doc) |

**Tally: 16 CLOSED · 1 DISPOSITIONED-WITH-EVIDENCE (R2-7).** Nothing is silently
dropped: the disposition and every remaining physical/owner gate are itemized below.

---

## 1. Recorded repo states

| Repo | Branch | Round-2 end-state (pre-finalize) | Commits in this campaign |
|---|---|---|---|
| `wsl-lane-nodes` | `fable-audit-fixes` | `c4502b3` | `123fb9b` (R2-8/R2-10 lane slice: leases, /api/health build identity, contract v1.1→1.2) → `55b2bf5` (software slice: R2-11/12/6/9/14/16-sw/5-gen) → `dc56964` (board/BOM/export: R2-2/3/4/5/6/15) → `10c3a26` (mirror record) → `5590483` + `3aae5b8` (fw v1.2.2: R2-1/13/6) → `c4502b3` (round-3 fix batch, 8 findings) → **finalize commits** (this report + R2-4/5/7 residual closure + doc sync + mirror record; the definitive HEAD is pinned by the run-log FINALIZE-round-2 mirror record and the round2_final mirror MANIFEST) |
| `WSL Systems` | `fable-audit-fixes` | `d12a09a` | `79993cf` (R2-8 deploy.ps1 + R2-10 bridge/alerts + R2-16 docs + R2-17 backup scope) → `d12a09a` (round-3 finding 6: lanefx tests tracked + fail-closed guard) |

Neither branch is pushed. `wsl-lane-nodes` has the standing push blocker (160 MB PDF
in history); `WSL Systems` deploys by AnyDesk copy + `git checkout` on WSL-SRV.

**Independent re-verification (clean clones, canonical sibling dir names):** at lane
`3aae5b8` / WSL `79993cf`: lane 226 pytest + 9 standalones + rp2040_link self-test
45/45 + firmware host suites 64/64 + 32/32 + 111/111 + 28/28 green; WSL 547 pytest +
72 standalones + 4 node smokes green. Full board chain re-ran in-clone (generator
271/223, ERC gate PASS, byte-identical netlist modulo date/source-path, audits ALL
PASS, diff vs rev-C CLEAN, fresh DRC 0/0/0, fab package hash-verified 45/45,
isolation re-measured 2.650 / 3.350 mm at the recorded worst points). **Four demanded
mutations proven load-bearing:** OEOVER enforcement neutered two ways → test_v12
fails; machine_contract.json mutated → lane contract test AND WSL bridge standalone
fail fatally; Safety_Rail 13→12 → audit exit-1 stop-ship; export refuses an existing
dir AND refuses `--rev C` mislabeling (live-run). End-to-end offline drill 12/12
(real lease lifecycle UNKNOWN→HEALTHY→OFFLINE; real wsl_api with the lane server
STOPPED → `/api/lanes` still 200 with machine.state=UNKNOWN present; alerts latched +
consumed). The verify pass found **3 residuals** — R2-7 not done, R2-5 partial
(probe spec + pad-directed FA-7 text), R2-4 partial (no SDA/SCL short test) — all
three are **closed in the finalize batch** (spec §R4-A; FA-7 probe rule; FA-9
steps 2–3; FA-12). Round-3 (`c4502b3`/`d12a09a`) then fixed the 8 Codex re-review
findings on top.

---

## 2. The two nuanced dispositions — stated plainly

### R2-7 (M5) — PC817B margin: bounded arithmetic + per-channel empirical closure, NO redesign

- The spec-R4 derate stack (worst-case effective CTR ≈ 48 %) mixes ONE published
  datasheet minimum (B-rank CTR floor 130 % at I_F = 5 mA) with three **conservative
  reads of typical curves** (I_F derate ×0.70, temperature ×0.75, aging ×0.70) —
  Sharp publishes **no minimum CTR at 1.7 mA**. The arithmetic is therefore bounded
  evidence, not a datasheet guarantee, and is now labeled as exactly that
  (spec **§R4-A**).
- The threshold condition is made exact: the MCP23017 input flips at
  **I_C ≈ 0.26 mA** (pulling the 10 k pull-up below V_IL ≈ 0.66 V), giving ≈ 3.2×
  margin against the worst-stack 0.83 mA of drive (2.5× at the stricter 0.33 mA
  dead-short target the spec keeps as its design number).
- The residual uncertainty is closed **empirically at first article**: FA-9 now
  qualifies **every populated input channel** (not a 3-channel sample) at the
  loaded-minimum field voltage AND at ≥ 70 °C case — the hot + low-I_F corner the
  curves can't guarantee. Any failure reopens the disposition via R4 trigger 1.
- **Why NO redesign:** raising I_F to the 5 mA datasheet point costs 40+ channels ×
  5 mA ≈ 200+ mA of LED current alone — meeting/exceeding the **TMA-0505S wetting-rail
  budget of 200 mA** (fleet worst case today: 73.7 mA at 1.73 mA/channel). The low
  wetting current is a hard system constraint; margin is **proven per channel, not
  bought per channel**. The empirical anchor stands: the identical 1.73 mA front-end
  runs on the physical rev-C board (40 channels, GS map 10/10, machine-22 field PASS).

### R2-8 (H5) — lane-deploy separation, with identity verification

- **The separation is BY DESIGN and remains:** `deploy.ps1` deploys the WSL Systems
  tree to WSL-SRV; the **Pi lane fleet is provisioned separately** (systemd units +
  `/etc/wsl-lane-node.env`, R2-9). deploy.ps1 does not and should not push code to
  the Pis.
- **What changed — the deploy now PROVES the lane leg it depends on instead of
  assuming it:** (a) FATALLY verifies the WSL-SRV lane task actually restarted
  (schtasks Running + :8766 listening — the schtasks-orphan history is why failure
  is fatal, not a warning); (b) runs an **authenticated POST smoke** (auth binds on
  POST, not GET): posts a synthetic deploy-marker `machine_event` with the lane
  token, asserts 2xx, POSTs it again and verifies **server-side dedup** against the
  live lane tree (delivery-identity path proven live, and the marker is proven NOT
  to fake board liveness — deploy markers are excluded from lease touch); (c)
  records and compares the lane server's **git/build hash** from the new
  `/api/health` `git_hash`/`build` identity (lane-repo change, `123fb9b`) — a
  version-skewed lane server is caught at deploy time, closing the identity gap the
  separation used to hide.
- Residual (recorded, not a defect): the Pi-fleet deploy path itself still has no
  automated verifier — it is a provisioning procedure (R2-9 doc), and arming
  `WSL_MACHINE_DIAG`/SMS on prod remains a go-live step, not a code gap.

---

## 3. Evidence per finding (condensed — full detail in the run log / commit messages)

- **R2-1:** `force_pad_input_only()` (CTRL.OEOVER=DISABLE) at every pin-config choke
  point; OEOVER-field + live `STATUS.OETOPAD` readback at init + every heartbeat on
  every input-contract pin (GP16-19, GP26, GP6-13, GP20-21); fail-safe `pad_oe`
  fault; mandated OEOVER **mutation tests** (test_v12 §M, proven load-bearing by the
  verify pass). Round-3 fixed the boot-order regression (first pass ran before
  `init_inputs()` → spurious boot fault) with an `inputs_inited` gate + second pass +
  test_v12 §R replicating main()'s literal boot order. **NOT flashed.**
- **R2-2:** grep-sweep of BOTH repos + fab package: 3 live occurrences
  (`generate_kicad_netlist_revD.py:701`-era guidance + part-lock CSV) corrected to
  the **1 M / ≥ 917 k derated floor**; WSL Systems had zero; dated retraction records
  intentionally keep the old figure as history.
- **R2-3:** Q17–Q20 value-field locked to **onsemi 2N7002LT1G** (LCSC C16338,
  fetch-verified); export hard-assert; FR-10 footprint/datasheet review in the run log.
- **R2-4:** J16 stack — F1 Littelfuse 1206L020YR 200 mA polyfuse (pin 1), JP1
  default-OPEN solder link (3.3 V pin ships NC), U46 TI TCA4307 stuck-bus-recovery
  buffer + 4.7 k card-side pull-ups + bypass, U47 Semtech SRV05-4 ESD (round-3: VP
  moved UPSTREAM of the polyfuse onto VCC_5V; fused pin keeps ESD via ex-spare IO3).
  Audit fail-closed asserts J16 never touches a raw rail/bus, SDAIN/SCLIN not
  swapped, U47.5 on VCC_5V. Severity recorded as **availability, not safety** (wedged
  tick-I2C → `_on_safety_trip` → ARM drop → rail de-energizes). All parts
  LOGIC-domain — isolation-barrier inventory untouched. **Finalize adds FA-12**, the
  first-article SDA/SCL external-short test (deterministic bus + safety + outputs;
  autonomous TCA4307 recovery; > 60 s sustained wedge).
- **R2-5:** TP-net parser fixed (KiCad-10 net form) + **generation fails closed on
  any blank TP net** (24/24 rows non-blank, verified); heartbeat names corrected to
  the actual firmware emit string `v5`/`v5n`/`v5x`; firmware version generated from
  `config.h`; TP silk legend fabricated for TP1–16 + **TP2 "LOGIC GND" / TP5 "FIELD
  GND" / DO-NOT-BRIDGE** marks; **TP17–TP24** paired gate/drain probe pads per tap
  stage (no SOT-23 pin probing; ~15 mm pair separation dispositioned as the accepted
  layout). **Finalize adds** the **≥ 100 MΩ probe-impedance rule** (10 MΩ probes load
  the 1 M/10 M network) and re-points FA-7 steps 1/3 at the TP pads explicitly.
- **R2-6:** REV_ID straps GP20/GP21 (**rev-D = 0b01**; 0b00/floating = UNKNOWN, never
  assumed rev-D); firmware `id` line (fw ver, strap-read pcb rev, Pico unique id,
  build git-describe + config-sha via build-time `build_id.h`, FI-1 posture) + hb
  `rid`; daemon `BoardConfig.board_rev` **mandatory explicit** (CLI/env/systemd; no
  revC default; rev-unsupported AUX roles rejected loudly at startup). Round-3
  completed the chain: `rp2040_link.start()` sends `ID`; daemon emits `fw_identity`
  machine events with `fi1_image`/`pcb_rev_mismatch` at FAULT severity.
- **R2-9:** systemd units load `EnvironmentFile=-/etc/wsl-lane-node.env`
  (`WSL_DIAG_SERVER_URL` + token); template + provisioning doc; default deployment
  ships the HTTP leg configured — JSONL-only is a degraded mode.
- **R2-10:** explicit **HEALTHY/FAULT/OFFLINE/UNKNOWN/MAINTENANCE** end-to-end:
  `machine_leases` (WS HELLO/heartbeat + ingest touch; deploy markers excluded;
  window `WSL_MACHINE_LEASE_S=90`), maintenance endpoint, lease-derived
  state/last_seen/age in `/api/machine/health`; WSL bridge `get_machine_states()`
  never omits a Phase 8 lane (stale → UNKNOWN with age); `/api/lanes` always carries
  `machine.state`; `wsl_machine_alerts` OFFLINE class (`machine_offline`, 300 s
  persistence, own 60 m throttle, MAINTENANCE suppresses, stale data never touches
  fault latches). Offline drill 12/12 in the verify pass.
- **R2-11:** `rp2040_link` consumes ALL v1.2.x records (tap state, rail-drop ring,
  epochs, v5 extrema, warnings, dumps) → typed records → machine events; **epoch-aware
  stale-edge exclusion** (unknown epoch ⇒ stale, fail-toward-exclusion); one bounded
  TAPDUMP read-back per preserved pre-reboot ring. Firmware-side classifier fix rode
  v1.2.2 (+ round-3 16-bit alias guard, test_v12 §S).
- **R2-12:** JSONL-as-outbox: every record stamped `(source_id, boot_id, seq)`; the
  daily JSONL IS the outbox; `OutboxReplayer` cursor advances only on 2xx
  (cursor-ack replay); server dedup via UNIQUE partial index + INSERT OR IGNORE —
  **ONE write path, no second Pi DB**. Bank health (`bank_unavailable`,
  `configured_role_missing`, `stale_channel`) + `run_mismatch`, UART/queue/HTTP
  drops, restart loops, `fw_config_mismatch` promoted to structured faults.
- **R2-13:** firmware v1.2.2 built/host-tested/ARM-verified — additive protocol only;
  suites 64/64 + 32/32 + 119/119 (after round-3 §R/§S) + 28/28 (FI-1); FI-1 build
  compile-flag gated, BOOTSEL-jumper + arm-command gated, separately-named artifact,
  zero FI-1 code in release (host-pinned); boot procedure documented (README + FA-7
  step 0). **NOT flashed** — bench flash is an open gate.
- **R2-14:** camera dead/frozen/dark/blur self-checks scheduled in the production
  daemon (off the scoring path, skipped mid-capture); throttled post-strike
  `self_check_empty` → `camera_ref_drift`; GS-vs-camera per-pin disagreement counter
  at cycle ingest; Pi health: disk-free + read-only-FS probe, SoC thermal, clock
  step, restart loops, diag-storage retention pruning.
- **R2-15:** R135/R138/R141 pinned **LCSC C26108** (MATCH-AT-UPLOAD anywhere is
  export-fatal; C26108 OOS at retail 2026-07-21 — order-time stock check recorded);
  exporter derives source paths from `--rev` (mislabeling structurally impossible,
  negative-tested live); coding-profile qty corrected to **4/board**; round-3 added
  in-directory `_SUPERSEDED_DO_NOT_UPLOAD.txt` tombstones to the two dead packages
  and the title-block/gbrjob **Revision "D"** (asserted at export). As-current
  package: **`kicad/fab_revD_2026-07-21_r3/`** (hashed, all export gates PASS).
- **R2-16:** catalog v1.1 (P0 diagnostic-system + P1 machine conditions incl.
  interlock-alert-only, motion-while-permission-false, per-stage output-chain
  mismatch, BE-branch-stopped, distributor pin-spacing per AMF 24_8270.txt:2666,
  cushion-SS-as-passive-observer option); **AUX4-11 role priority recorded with
  `field_wet_ok` first — and the AUX11 FIELD_WET loopback role + cascade-suppression
  semantics IMPLEMENTED in software now** (jumper is a harness item; extensible
  AUX-role registry); SC/TB reconciliation note (2026-06-27 measurement supersedes;
  code already encodes the shared fact); scope-doc "nothing implemented" banner
  fixed; H2 record gains the JLC published-tolerance citation + the explicit
  **prototype-only waiver line for Dylan**.
- **R2-17:** machine diagnostics DB + JSONL/blackbox dirs added to the documented
  backup scope (deploy.ps1 backup section + NAS gate doc, WSL Systems `79993cf`).

---

## 4. OPEN GATES (definitive list — nothing here is design or software work)

**Dylan (owner decisions):**
1. **OG-1 / G8 / G14** — 250×240 board-growth sign-off + overall rev-D docs review.
2. **Commit-chain review** — the full unpushed chain on both `fable-audit-fixes`
   branches (lane `123fb9b…` + finalize; WSL `79993cf`/`d12a09a`).
3. **H2 prototype-vs-waiver decision** — the readiness-checklist H2 record now cites
   JLC's published etch tolerance and carries an explicit prototype-only waiver
   line; Dylan decides pilot-on-waiver vs. wait.
4. Parked from round 1: G7 waiver-or-session call, OUT-B override decision.

**Physical / powered sessions:**
5. **First-article gate** (generated pack FA-1…FA-12): incl. **FA-7 with the FI-1
   build** (step 0 boot procedure; ≥ 100 MΩ probe rule; TP-pad-only probing) + the
   **≥ 70 °C high-Z / D-G-short / stuck-GPIO leg (OG-4 — cold-only does NOT
   discharge it)**, **FA-8 sacrificial coding pair + 4-way cross-mate refusal**,
   **FA-9 per-channel PC817B qualification at min FIELD_WET + ≥ 70 °C (R2-7
   closure)**, **FA-12 J16 SDA/SCL short recovery (R2-4 closure)**.
6. **Firmware v1.2.2 bench flash** + on-silicon validation (BOOTSEL read, REV_ID
   strap levels vs the real divider, FA-7 OEOVER/pad behavior). Board #1 still runs
   the v1.x image.
7. **G7 powered at-machine session** (machine 22 — meter tapped-lead live voltages
   BEFORE reconnecting any board) — or an explicit recorded waiver.
8. **Characterization session (DC1–DC3)** — external-module analog population,
   thresholds; scheduled, not fab-blocking.
9. **G12** manual Gerber/JLC upload inspection from `fab_revD_2026-07-21_r3/` (never
   the tombstoned dirs) · **G13** harness/coding order (2 stars of profiles min).

**Ops:**
10. **M7 off-disk backup** — copy `WSL_Backups` to a second physical volume
    (WSL-SRV or USB), hash-verify against the recorded zip sha256 values.
11. **Lane push blocker** — 160 MB PDF in history; history rewrite is a separate
    deliberate task; until then the WSL_Backups mirrors are the off-repo record.
12. Production arming: `WSL_MACHINE_DIAG` + SMS config on WSL-SRV at diagnostics
    go-live; deploy of the WSL Systems round-2 slice per normal deploy practice
    (re-verify Stripe after deploy, per standing memory).

---

## 5. Backups / mirrors + sacred-file rule

- As-current external mirror: **`C:\Users\Dylan DeYoung\WSL_Backups\2026-07-21_phase8_revD_round2_final\`**
  (+ `.zip` + `.zip.sha256`, MANIFEST.json with per-file sha256, source HEAD = the
  finalize commit) — supersedes `2026-07-21_phase8_revD_round2_hw` as the as-current
  record; all older mirrors stay untouched. The zip hash is recorded in the run-log
  FINALIZE-round-2 mirror record for M7's off-disk verification.
- **Rev-C sacred snapshot: 189/189 hash-verified** before and after every batch of
  this campaign, including at finalize (`scripts/verify_revC_snapshot.py`). Zero
  rev-B/rev-C design files touched anywhere.

## 6. Standing invariants — held throughout round 2 + round 3 + finalize

Safety_Rail netclass **exactly 13** at every audit (netclasses 103/4/13/82/21 = 223);
no copper on SAFE_*/RELAY_ENABLE_RAIL/RAIL_GATE; no new isolation-barrier component
classes (TCA4307/SRV05-4/polyfuse are LOGIC-domain — verified); banding/gutters
preserved; `.kicad_dru` 2.65/3.35/1.6 untouched; wetting/D17 budgets re-run on every
current change (+~6 mA VCC_3V3 in round 2; VP rewire moved no load current);
FR-10…FR-14 footprint-vs-datasheet reviews for every new part class; diff vs rev-C
CLEAN with whitelists, zero rev-C removals; ERC waiver ledger (WVR-ERC-2, round-3
order-insensitive amendment — baseline 1 waived + 39); exports refuse-if-exists into
NEW dated dirs; explicit per-file staging on every commit, **nothing pushed**;
firmware **NOT flashed**; docs synced with reality (this report, change list,
checklist, run log, HANDOFF).
