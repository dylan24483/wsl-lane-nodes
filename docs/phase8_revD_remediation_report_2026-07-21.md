# Phase 8 Rev-D — Codex NO-GO Remediation Report (2026-07-21)

> **HISTORICAL CAMPAIGN RECORD — current hardware/fab pointer changed
> 2026-07-23.** The live board now uses exactly 40 × 47 kΩ PC817 collector
> pull-ups. Current electrical acceptance is remediation spec §R4 and current
> immutable fabrication output is `kicad/fab_revD_2026-07-23_r5/`; `_r4/`
> is superseded because it predates the binding RP2040/MCP internal-pull-zero gate.

> **SUPERSESSION NOTE (2026-07-21, later):** Codex re-audited this campaign under a
> fabrication-readiness bar and issued round-2 findings (R2-1…R2-17); the 15/2/1
> tally below is therefore the ROUND-1 closing state, not the final word.
> **The round-2 campaign's closing record — final R2-1…R2-17 statuses (16 CLOSED ·
> 1 DISPOSITIONED), the round-3 fix batch, recorded HEADs, and the definitive
> open-gates list — is `phase8_revD_round2_report_2026-07-21.md`. Read THAT for
> current state.** Board is now 271 parts / 223 nets, the as-current fab package is
> `kicad/fab_revD_2026-07-21_r3/` (`_r2/` and the round-1 dir are tombstoned
> in-directory), and the release DRC evidence is `DRC-revD-round3-r1.rpt`
> (0/0/0). §3 "OPEN GATES" and §4 mirror-table below are superseded by that
> report's §4/§5.

**Scope:** the 2026-07-21 Codex NO-GO audit against the routed rev-D lane-controller board
and its software/release chain — 3 critical / 8 high / 7 medium findings. Dylan's
instruction: remediate ALL issues. This report is the campaign's closing record: final
status per finding with evidence, the recorded repo states for clean-clone reproduction,
and the gates that remain open (all owner decisions, physical/powered sessions, or
scheduled first-article work — no open design or software work).

**Campaign spec:** `docs/phase8_revD_remediation_spec_2026-07-21.md` (R1–R4, FMEA,
first-article procedures). Companions: `phase8_revD_change_list.md` (STATUS banner),
`phase8_revD_readiness_checklist.md` (gates G1–G14 + first-article §2),
`phase8_revD_run_log.md` (FR/COR/RV/OG records, mirror records, FINALIZE record).

**Verification posture:** every closure below was independently re-verified from scratch
by a separate verification pass (nothing trusted from working summaries), followed by a
post-remediation review batch (RV-1…RV-10, run log) that fixed everything the review
found. Load-bearing guards were proven load-bearing by mutation, not by inspection.

---

## 0. Verdict

| # | Finding (short) | Final status |
|---|---|---|
| C1 | Bidirectional rail taps can hold the pass-FET | **CLOSED** |
| C2 | Firmware "never outputs" was accidental non-use | **CLOSED** |
| C3 | No coherent clean revision across the two repos | **CLOSED** |
| H1 | NE555 tap rides an unguaranteed VOH assumption | **CLOSED** |
| H2 | Isolation minima at zero manufacturing margin | **CLOSED** |
| H3 | AUX4–11 unreadable (GPA-only read path), no debounce | **CLOSED** |
| H4 | Cycle POST contract mismatch masked by fake-vs-fake tests | **CLOSED** |
| H5 | deploy.ps1 ignores the lane repo; smoke-checks 5000 only | **PARTIAL** (see §2.H5) |
| H6 | No executable rev-D fab/BOM/harness package | **CLOSED** |
| H7 | Coding-profile install reversed; harness termination data wrong | **CLOSED** (FA-8 proof executes at first article, as the gate specifies) |
| H8 | Enclosure spec still 250×225 / MK 242×217 | **CLOSED** |
| M1 | Diff/audit scripts validate names/counts only | **CLOSED** |
| M2 | route_revD.py --check-only crashes on KiCad 10.0.2 | **CLOSED** |
| M3 | KEYED silk 0.8 mm < JLC 1.0 mm minimum | **CLOSED** |
| M4 | J15 drill 1.2 mm vs Phoenix-recommended 1.4 mm | **CLOSED** |
| M5 | PC817B CTR margin undocumented at ~1.7 mA | **DISPOSITIONED** (no change; rev-C field evidence + 4 reopen triggers) |
| M6 | Powered-test docs wrong for rev-D refdes | **CLOSED** |
| M7 | Backups on one physical disk; change-list doc rot | **DISPOSITIONED** (doc rot closed; off-disk copy is an OPEN Dylan item) |

**Tally: 15 CLOSED · 2 DISPOSITIONED-with-evidence (M5, M7) · 1 PARTIAL (H5).**
The two dispositions and the H5 residuals are itemized in §3 (open gates) — nothing is
silently dropped.

---

## 1. Recorded repo states (clean-clone reproduction)

| Repo | Branch | Final HEAD (this campaign) |
|---|---|---|
| `wsl-lane-nodes` | `fable-audit-fixes` | the FINALIZE commits recorded in the run-log FINALIZE record (this report + doc sync, then the mirror record). Last pre-finalize HEAD: `97ba04c1a83ff49d028cf8d074ce7dc1b4450bf5`. The definitive HEAD is `git log -1` on the branch; the FINALIZE mirror record and the r3 mirror MANIFEST both pin it. |
| `WSL Systems` | `fable-audit-fixes` | `f1bd3266feeee6d2ed7f6ee3d39fa947a8cd47f8` |

Neither branch is pushed. `wsl-lane-nodes` has a standing push blocker (160 MB PDF in
history, recorded since the rev-B campaign); `WSL Systems` deploys by AnyDesk file copy +
`git checkout` on WSL-SRV, per standing practice.

**Clean-clone evidence:**
- `wsl-lane-nodes` at `2450cf2` (verification pass): fresh clone runs **181 pytest-native
  + 9/9 standalone suites ALL GREEN**; generator reproduces 262 parts / 217 nets with the
  ERC waiver exactly 1 error + 40 warnings; regenerated netlist content-identical to the
  committed one; deep diff CLEAN (46/46 parts, 33/33 nets, 11/11 touch-points); netlist +
  routed-board audits ALL PASS; netclasses 97/4/13/82/21 = 217 with Safety_Rail exactly 13.
  The post-2450cf2 commits touch firmware/doc/test files only (board chain untouched;
  `kicad/` git-clean through the review batch).
- `WSL Systems` at `f1bd326` (finalize, today): fresh clone with Git-for-Windows' default
  `core.autocrlf=true` — `wsl_api.py` imports clean with the previously-dirty-tree-only
  symbols present; `tests/public_checkout_identity_smoke.node.js` **PASSES** (the one
  genuine clean-clone failure found by verification — CRLF checkout of `website.html`
  breaking a `\n`-bearing extraction marker — reproduced at `03feec5`, fixed by the
  `.gitattributes` LF pin in `f1bd326`, re-proven green post-fix);
  `tests/test_phase8_bridge_contract.py` ALL PASS against the canonical contract.
  Full-suite runs recorded green earlier in the campaign (538 passed at the `b38cc54`
  commit point; 38 diagnostics tests green from a detached worktree at `d1eb105`).

**Campaign commit map (wsl-lane-nodes, `fable-audit-fixes`, all explicit staging):**
`a3a52bc` (2026-07-19 diagnostics software campaign committed coherently) → `d79ccab` /
`8e3946e` (run-log records) → `27b9bfc` (firmware v1.2.0, C2) → `f96ad87` (H3 + M1) →
`6c7a078` (H4 lane half + canonical contract) → `9fd2566` (LF pin on the contract) →
`592993d` (doc sync) → `496d8c2` (board chain: R1 taps + R2 rules/silk/drill + M2 router
fix — C1/H1/H2/M2/M3/M4) → `b6a6ab6` + `a6502ef` (release artifacts — H6/H7/H8/M6/M7)
→ `2450cf2` (mirror record) → `541dd5c` (post-remediation review batch RV-1…RV-10, fw
v1.2.1) → `97ba04c` (r2 mirror record) → the FINALIZE commits (this report).

**WSL Systems:** `b38cc54` (diagnostics campaign committed coherently + H5 deploy smokes)
→ `d4baf68` / `d1eb105` (H4 consumer-side contract pin at the settled hash) → `03feec5`
(H4 guard fail-closed when the contract file is absent, RV-9) → `f1bd326` (C3 EOL pin).

---

## 2. Per-finding record

### C1 — Bidirectional rail taps (R_TAP_ARM / R_TAP_RPOK, 680k direct to GPIO) — CLOSED

- **Fix (spec R1, commit `496d8c2`):** the resistive taps are GONE. Each of the four taps
  is now a **unidirectional 2N7002 common-source inverter** (SOT-23 — the board's existing
  proven `Qled_*` class, FR-8): observed net → R_TAPIN 1 M → gate (+ R_TAPG 10 M to GND on
  the three 3.3 V taps; the 555's push-pull output is never high-Z, asymmetry deliberate);
  VCC_3V3 → R_TAPPU 10 k → drain → GPIO. **The GPIO touches only the drain** — a
  stuck-high GPIO injects zero DC into the observed net in unfaulted hardware; C1's
  headline scenario dies at the netlist, not at a procedure.
- **FMEA-grade math (spec R1.4–R1.6, re-derived independently in the verify pass):** worst
  double fault (D–G short + stuck-high GPIO + legitimate driver high-Z + 85 °C) injects
  ≤ 0.56 µA → 0.056 V on RAIL_GATE, ≥ 8× below the 5 µA partial-hold onset; transistor-free
  absolute ceiling 3.3 V / 1.01 MΩ = 3.3 µA. Post-review correction RV-5
  temperature-scoped the ceiling argument (clears 5 µA at 25 °C; ~9 % under the derated
  3.6 µA 85 °C onset) and re-derived the R_TAPIN floor against the derated onset
  (≥ 917 k ⇒ 1 M minimum; the old "~825 k" sentence retracted). FMEA rows incl. F7b
  (555-tap floating-gate detectability = accepted diagnostic-trust residual — zero-injection
  safety unchanged) and the F11 rewrite (R_pu short ⇒ fail-SAFE whole-lane brownout, field
  triage signature documented).
- **Board deltas:** 262 parts / 217 nets; netclasses 97/4/13/82/21 exact; **Safety_Rail
  EXACTLY 13** (stop-ship invariant, held); no new copper on SAFE_* / RELAY_ENABLE_RAIL /
  RAIL_GATE; diff vs rev-C CLEAN with zero rev-C removals; 680k out of the BOM, 1M/10M in.
- **Gate coverage:** the at-temperature (≥ 70 °C thermocouple-held) high-Z fault-injection
  procedure the finding demanded is spec R1.9, reproduced verbatim in the generated
  first-article pack (FA procedures) and readiness checklist §2 — it includes physically
  inserted D–G shorts, driver-high-Z with GPIO stuck high, and the driven-disarm proof.
  Execution is a first-article step (§3).

### C2 — Firmware never referenced GP16–19/GP26 ("never outputs" accidental) — CLOSED

- **Fix (firmware v1.2.0 `27b9bfc`, corrected to v1.2.1 in `541dd5c`):**
  `firmware/rp2040/main.c` —
  - **Enforced input-only invariant:** `tap_init()` (main.c:578) is the single choke-point
    configuring GP16–19 (input, Schmitt on, pulls off); `tap_assert_input_only()`
    (main.c:601) reads back the SIO OE and IO-bank FUNCSEL **registers** at init and on
    every heartbeat tick, latching a fail-safe `tap_dir` fault (RP_OK refused) on any
    drift. Inverted-tap decode (2N7002 stage: raw 0 = observed HIGH) lives in exactly one
    `tap_read()` accessor.
  - **Timestamped rail-drop capture:** 1 ms edge ring, 128 × {t_ms, pin, level, epoch} in
    `__uninitialized_ram` with magic-pair validity + epoch counter — survives a Pico
    reboot (epoch++), zeroed on true power loss, cleared only by the new TAPCLR command;
    TAPDUMP drips the ring + an advisory cause code with a free-space check so it can
    never starve hb/flt.
  - **ADC:** VCC_5V divider on GP26 sampled at 10 Hz; latest/min/max mV in every heartbeat.
- **Direction tests proven load-bearing by mutation (verify pass):** injecting
  `gpio_set_dir(GP17, OUT)` fails 6 host checks incl. the explicit C2-gate check, rc 1.
  Host suites at v1.2.1: **64/64 + 32/32 + 71/71**.
- **v1.2.1 (RV-1):** `TAP_KICK_STARVE_MS` 300 → 2000 ms — the 300 was sized against
  `HB_INTERVAL_MS` mistaken for the Pi kick cadence; the real kick is 1 Hz
  (`lane_node.py::watchdog_kick_loop`). Host test G(a) now simulates the real cadence,
  G(a2) pins that a 555 fall inside the normal inter-kick gap classifies `555_drop`.
- **Unfreeze scope respected:** all wire changes additive; safety-critical paths (motion
  max-run, chatter, RP_OK drop semantics, v1.1 default-OFF flags) logic-identical;
  `rp2040_link.py` verified compatible unmodified.
- **Open (scheduled, §3):** bench flash + on-hardware validation of v1.2.1 — firmware has
  only host-level proof so far.

### C3 — No coherent clean revision — CLOSED

- **WSL Systems half:** the 2026-07-19 diagnostics campaign committed coherently in
  `b38cc54` (bridge server-post refactor + TTL-cached `get_machine_health`,
  `wsl_machine_alerts.py` + migration, tests, deploy.ps1) — HEAD no longer imports
  symbols that exist only in the dirty tree; proven from a detached worktree (import OK,
  bridge-contract script ALL PASSED, 38 diagnostics tests green).
- **Lane half:** the entire uncommitted diagnostics campaign committed coherently in
  `a3a52bc` (explicit staging; `kicad/.history` excluded), followed by the remediation
  commits (§1 map).
- **Clean-clone reproduction:** lane-nodes fully green at `2450cf2` (§1). The one genuine
  WSL Systems clean-clone failure (CRLF checkout of `website.html` under default
  `core.autocrlf=true` breaking the checkout-identity smoke's byte-exact marker — found
  by verification, which is why this finding was held PARTIAL until today) was reproduced
  at `03feec5` and closed by the `.gitattributes` LF pin in **`f1bd326`**; the clean-clone
  smoke + bridge-contract suite re-run green post-fix. The lane repo's contract files were
  already LF-pinned (`9fd2566`) for the same reason.

### H1 — NE555 tap unguaranteed light-load VOH vs RP2040 limits — CLOSED

- Killed by the same R1 topology as C1: the observed net now drives a **2N7002 gate**
  (V_GS abs max ±20 V — FR-8), not a GPIO pad. No divider, no clamp current into the pad,
  no dependence on the 555's VOH curve at any corner. The old "≤ 3.27 V" divider claim is
  tombstoned in the change list (no live text carries it).

### H2 — Isolation minima 2.501/2.5 and 3.200/3.2 mm, zero margin — CLOSED

- **Requirement derivation (spec R2, in-file in the `.kicad_dru`):** working voltages
  derived — FIELD ≤ 14 V populated / 34 Vpk design basis; MACHINE ≤ 37 Vpk (24 VAC, A1
  fieldsheet); IPC-2221B B1 minimum 0.6 mm; requirement retained at **2.5 / 3.2 mm**
  (≥ 4× margin over B1).
- **Fab tolerance embedded:** JLC ±20 % etch → 0.11 mm worst-case gap loss → 0.15 mm
  allowance → **rule values 2.65 / 3.35 / 1.6 mm** in `kicad/revD/wsl-phase8b-revD.kicad_dru`.
- **Re-routed + measured (commit `496d8c2`):** kicad-cli DRC **0 / 0 / 0** with the new
  rules live (`kicad/revD/DRC-revD-remediation-r3.rpt`); routed-mode audit ALL PASS.
  Measured minima (independently re-measured in the verify pass by DRC-rule bracketing):
  **LOGIC↔FIELD ∈ [2.650, 2.660) mm · LOGIC↔MACHINE 3.3505 mm · machine ch↔ch
  ∈ [2.320, 2.330) mm** — all ≥ rule minima and ≥ the 2.5/3.2 as-fabbed requirement after
  worst-case etch loss (arithmetic re-derived and confirmed). Straddler 3.580, relay rows
  3.559, opto rows and J15 region ≥ 6.
- **Fab-tolerance citation (added 2026-07-21, Codex R2-16):** the ±20 % figure is JLCPCB's
  **published** capability limit — "Minimum trace width/spacing tolerance: ±20 %" for
  standard 1–2 layer/multilayer outer copper (JLCPCB *PCB Manufacturing Capabilities*
  page, jlcpcb.com/capabilities, as read 2026-07-21) — not an in-house assumption. The
  0.11 mm worst-case gap-loss arithmetic derives from that published bound at the routed
  geometry; re-derive against the chosen fab's current published numbers on any re-order.
- **PROTOTYPE-ONLY WAIVER (explicit, for Dylan to sign):** the 2.65 / 3.35 / 1.6 mm rule
  values embed the JLC ±20 % allowance for **this prototype run only**. This is NOT a
  certified-creepage claim under IPC-2221B pollution-degree/material assumptions beyond
  the derivation recorded above, and it does NOT transfer to a different fab, a different
  layer stack, or a production respin — any of those re-opens the H2 derivation from the
  working voltages up. Accepted for first-article/prototype use: ☐ Dylan DeYoung (date).

### H3 — AUX4–11 unreadable (GPA-only read), rev-B drift pin, no debounce — CLOSED

- **Read path (commit `f96ad87`):** `lane_node/controller_io.py` — `IN_B_MAP_REVD`
  (AUX4–11 on MCP_IN_B GPB0–7, controller_io.py:119–123) with **explicit per-board
  revision selection** (`IN_B_MAPS` / `board_rev`; unknown rev = hard error; default
  `revC` = the machine-22 pilot), two-port `read_inputs_b`.
- **Drift guard:** parametrized over BOTH generators (rev-B/C and rev-D) in the
  `controller_io` `__main__` guard AND `tests/test_pin_map_drift.py`.
- **Debounce:** `controller_daemon` `SlowDebounce` — diagnostics-path inputs at
  `WSL_SLOW_DEBOUNCE_N` (default 3 consecutive 50 Hz samples ≈ 60 ms); FSM action inputs
  (PBZ/BS/Foul) stay RAW by default behind the flagged `WSL_SLOW_DEBOUNCE_FSM_N` knob
  (raising it logs a safety-path warning banner). AUX1–11 are dormant-unless-mapped
  and stuck-exempt.
- **2026-07-24 R5 supersession:** the controller daemon has no board-revision
  default even though the lower-level direct-I/O bench constructor retains its
  legacy rev-C default. A paired daemon must use complete
  `WSL_DIAG_AUX_ROLES_L<lane>` maps; once either board is configured, its mate
  must be present (an exact blank declares intentionally unmapped).
  `WSL_DIAG_AUX_ROLES` is accepted only in one-board bench mode. Unsupported
  role/revision channels, duplicate or unknown board-revision assignments, and
  partial pair maps are rejected before threads or hardware open.
- **2026-07-24 R5 physical/diagnostic supersession:** the generated
  first-article pack is now FA-1…FA-14. FA-13 records that J14.3–4 is physically
  open until a measured, approved Stop/control-power interface exists. Physical
  inspection found no C.I.S. device or wiring on lanes 21/22, so C.I.S. is N/A,
  not passed. FA-13 requires Stop→master/control-power plus TP16-drop proof,
  resolution of whether another pit-entry interlock exists, and an approved
  install-versus-Stop+LOTO-only disposition. Any new final pit interlock acts
  upstream; a J14-only contact is not an equivalent safety disconnect.
  FA-14 assigns protective-earth and hot/neutral polarity verification to a
  qualified electrician with a listed external tester; neither is a Rev-D
  input. Command-off CT/Hall evidence is
  `uncommanded_motor_current`/`external-feed-or-welded`, not conclusive weld
  attribution.

### H4 — Cycle POST contract mismatch; fake-vs-fake tests — CLOSED

- **Fix (`6c7a078`):** the lane server's `_handle_machine_post` now unwraps the canonical
  `{"cycle": row}` shape `HttpSink` always sent (bare row tolerated for compatibility) —
  the mismatch was reproduced live before fixing.
- **Single source of truth:** `server/machine_contract.json` (contract_version 1, incl.
  `examples.machine_health_response`), sha256
  `2618f6ee4f80fd53de2cf14f6ba03c34aaef83dd1285b00441f63e826388da8b` in
  `server/machine_contract.sha256`. **Both** suites verify the same bytes: the lane suite
  POSTs the contract examples verbatim at the real loopback handler (the wrapped shape is
  the pre-fix repro) and proves HttpSink wire shapes byte-for-byte; the WSL Systems suite
  (`tests/test_phase8_bridge_contract.py`) loads the same file, pins the hash, and
  cross-checks the bridge whitelist / URLs / auth header / severity vocab. `.gitattributes`
  LF pins (`9fd2566`) keep the hashed bytes stable across platforms.
- **Proven load-bearing by mutation (verify pass):** mutating the canonical contract fails
  the WSL side (rc 1 on hash-pin drift) AND 2 lane-side tests. RV-9 hardened the WSL guard
  fail-closed when the contract file is absent (`$WSL_MACHINE_CONTRACT` path / explicit
  `skip` / sibling-repo lookup; none found ⇒ suite FAILS) — verified in all three modes
  (`03feec5`).

### H5 — deploy.ps1 lane-repo blindness; :5000-only smoke — PARTIAL

- **Done (`b38cc54`, WSL Systems `deploy.ps1`):** authenticated **:8766** smoke — GET
  `/api/health` with `X-Lane-Token` (Machine/process env), asserting ok + machine section
  healthy + `auth_enabled` + `protocol_version` — plus a GET `/api/machine/health`
  diagnostics-reachability line. WARN-only by default; **fatal when `WSL_MACHINE_DIAG` is
  explicitly armed**.
- **Residual (recorded in-script and in the run log, not silently closed):**
  1. **Build identity:** the lane server exposes no git/build hash endpoint — identity is
     smoked via `protocol_version` only. Real closure needs a lane-repo server change
     (out of the finalize scope; queued).
  2. deploy.ps1 still does not update the lane repo — lane-node code deploys to the Pis
     through its own path, not WSL-SRV's deploy.ps1; the gap between "WSL-SRV deployed"
     and "lane fleet current" remains procedural.
  3. WARN-only default until `WSL_MACHINE_DIAG` is armed on WSL-SRV (arming is a deploy-
     time decision for Dylan once the diagnostics stack is in production).

### H6 — No executable rev-D fab/BOM/harness package — CLOSED

- **`scripts/export_fab_revD.py`** (commits `b6a6ab6` + `a6502ef`) written and RUN →
  **`kicad/fab_revD_2026-07-21/`**: hashed as-ordered package (45-file sha256 manifest
  incl. source board/netlist hashes), parameterized REV/out-dir, **refuses-if-exists
  proven live** (second run exit 1, no deletion — the rev-C rmtree incident is
  structurally impossible). In-process re-gates before export: DRC 0/0/0 + routed audit
  ALL PASS.
- **Equality asserts, not samples:** BOM↔CPL↔netlist per-refdes with matching
  value+footprint at pinned counts **262 parts / 27 DNP / 235 placed / 218 JLC-placed /
  22 JLC lines / 17 hand-solder**. (The audit tasking's "252" was the pre-R1 count; spec
  R1.7 moved it to 262 — recorded, not silently adjusted.)
- **D_PROT hard-locked: MDD SS34, LCSC C8678, SMA/DO-214AC** at netlist + board + JLC-BOM
  level; any SS14 anywhere fails the export. (10M 0805 R_TAPG is match-at-upload by MPN
  0805W8F1005T5E; 1M locked to C17514 — instruction in the part-lock CSV.)
- Hand-solder BOM (rev-D refs incl. J15/J16 + the U37→U45 shift) and the **harness BOM**
  (`docs/phase8_revD_harness_bom.csv`, also in the package) ship in-package. Fresh-export
  reproduction: all 10 assembly CSVs byte-identical to the as-ordered package;
  fresh-worktree manifest verification 45/45 OK (verify pass).

### H7 — Coding-profile install reversed; harness termination data wrong — CLOSED

- **Install rule corrected everywhere** (change spec §C.3+§F, run log OG-3/COR-5/COR-6,
  checklist G13 + §2, change list items C/F, harness BOM CSV, first-article pack): the
  CP-MSTB 1734634 profile fits the **PLUG** (or an inverted header) — never pressed into
  a standard MCV G-3.5 header; header side = remove the coding rib at the matching pole.
- **Termination data corrected** to Phoenix 1840447/MC 1,5 reality: **7 mm strip /
  0.22–0.25 N·m / ≤ 0.5 mm² with insulated ferrule** (was 8 mm / 0.5 N·m / 0.75–1.0 mm²).
  Lane-21 build sheet corrected with a dated banner + inline strikethroughs (no silent
  edits); RV-7 also fixed its Tools row to a 0.22–0.25 N·m torque-limiting driver; MKDS
  flagged as a different series to verify separately.
- **Sacrificial-pair proof** is numbered first-article step **FA-8** (readiness checklist
  §2 + generated pack) — per the finding's own gate wording it executes at first article
  (§3), before any production part is coded.

### H8 — Enclosure spec stale (250×225 / MK 242×217) — CLOSED

- `phase8_pair_enclosure_spec.md` re-specced for the 250×240 rev-D board (`b6a6ab6`):
  board zones 225→240, panel stack 640→670 mm, MK pattern **242×232** (bottom holes
  y=236), new §1.1 dimensioned panel table (D1–D13, per-board panel-coordinate MK holes),
  new §1.2 **row-39 bottom-edge copper constraint** (1.28 mm to routed edge) binding on
  any lip/clamp/backplate design, SCE-30P24 margin re-mathed to 16 mm and flagged thin.
  Sourcing brief reissued at ≥ 310×670 mm usable panel; 700-mm-class candidates marked
  marginal.

### M1 — Diff/audit validated names/counts only — CLOSED

- `scripts/diff_netlist_revC_to_revD.py` (`f96ad87`) deepened with expected-delta tables
  pinning **every added part's value+footprint (46), every added net's exact pad
  membership (33), every touched rev-C net's exact added nodes (11 + never-arrived
  detection)**, import-time lockstep asserts. CLEAN against the current netlists;
  **negative-tested live** (1M→100k mutation → DEEP_PART_MISMATCH, exit 1 — re-proven in
  the verify pass with R133).

### M2 — route_revD.py --check-only crash on KiCad 10.0.2 — CLOSED

- Root-caused to `BOARD.Remove()` corrupting SWIG container state (reproduced as both
  AttributeError and segfault); fixed with `BOARD.Delete()` (`496d8c2`). `--check-only`
  exits 0, SELF-CHECK 0 problems, on the installed KiCad 10.0.2. Minimal repro promoted
  from gitignored tmp/ to **`scripts/repro_m2_getisrulearea.py`** (RV-8, verified PASS,
  board file untouched). Determinism restored end-to-end: the full
  regenerate→netclass→route→netclass→DRC→audit pipeline reproduces the routed artifact
  from scripts alone, incl. the RD-VIA-1 power-via twins now emitted deterministically by
  `route_power_via_redundancy()` (retiring the G9 re-run trap).

### M3 — KEYED silk below JLC minimum — CLOSED

- KEYED cross-mate warnings at **1.2 mm / 0.20 mm stroke**; a hard 1.0 mm / 0.15 mm floor
  enforced in the router's `add_text()`; verify pass confirmed zero silkscreen text below
  the floor board-wide (`496d8c2`).

### M4 — J15 drill 1.2 mm vs Phoenix 1.4 mm — CLOSED

- All **7** MCV connector instances moved to project-local `_D1.4` footprints
  (`kicad/wsl_footprints.pretty/`): drill 1.4 mm per the Phoenix drilling plan, pad
  2.0×3.6 mm, annular 0.30 mm vs the JLC 0.20 floor; system KiCad library untouched;
  FR-9 recorded; first-article includes an insertion/solder-fill check on one connector
  before the rest (`496d8c2`).

### M5 — PC817B CTR margin at ~1.7 mA — DISPOSITIONED, no change

- Spec R4: worst-stack CTR 48 % → **2.5× margin at 1.73 mA**; the dominant evidence is
  that **rev-C runs the identical current on 40 field channels on machine 22** — exactly
  the audit's own suggested mitigation. Disposition carries **4 explicit reopen
  triggers** (spec R4) and a first-article V_CE ≤ 0.3 V 3-channel sampling step (pack
  procedure). No component change.

### M6 — Powered-test docs wrong for rev-D refdes — CLOSED

- **`scripts/generate_first_article_docs_revD.py`** (`b6a6ab6`) generates
  `docs/phase8_revD_first_article_pack.md` + the 262-row refdes-map CSV programmatically
  from netlist + routed board + diff: 46-row REFDES_SHIFT table (ISO_WET U37→U45, U_WDOG
  U36→U44, rail-gate pullup R106→R124 …), relocated TP1–16 map with coordinates,
  FA-1…FA-11 procedures (R1.9 tap fault injection verbatim, GPB poke table
  J15-pin↔GPB-bit↔opto-ref, ADC ±3 % + 6-coil sag, cross-mate refusal matrix, R4 V_CE
  sampling, FR-9 first-connector check, firmware v1.2 posture assert). Derived docs —
  re-run the generator after ANY netlist/placement change; every rev-C bench artifact
  still names wrong parts on a rev-D board.

### M7 — Single-disk backups; change-list rot — DISPOSITIONED

- **Doc rot: CLOSED.** The obsolete 3.27 V claim is tombstoned (live only inside dated
  correction records); coding is no longer called "closed" anywhere it isn't; the
  "cited J15 harness BOM that does not exist" now exists
  (`docs/phase8_revD_harness_bom.csv`, H6). Change list / spec / checklist / run log /
  HANDOFF.md all synced (incl. RV-2's HANDOFF rewrite and RV-6's sklib/erc sync with the
  backwards-drift note corrected).
- **Off-disk half: OPEN Dylan item (recorded, not closable from this laptop).**
  Enumeration proved a **single physical volume** (one NVMe = C:; USB reader empty; no
  NAS/UNC exists). All WSL_Backups mirrors + zips are hash-verified but co-located with
  the originals. Standing instruction in the run log: copy `WSL_Backups` to WSL-SRV via
  AnyDesk or USB media, hash-verify at the destination against the recorded zip sha256
  values, never cloud.

---

## 3. OPEN GATES (what remains — none of it is design or software work)

1. **OG-1 / G8 / G14 — Dylan's sign-offs.** The 250×225 → 250×240 growth (enclosure
   re-check already RESOLVED with evidence; declining = 36-row re-spin + full re-route)
   and the overall rev-D docs review. Parked decisions: G7 waiver-or-session, J16
   polyfuse, OUT-B override.
2. **G7 — powered at-machine session** (machine 22; **meter tapped-lead live voltages
   BEFORE reconnecting any board**): rev-C carried items 6 (per-channel front-end) and
   7 (arc-suppression sizing) — resolve or record an explicit waiver.
3. **G12 — manual Gerber inspection + JLC upload preview** (five doubled power vias,
   row-39 bottom edge, K1–K7 pad-net regression, KEYED silk legibility) before paying.
4. **G13 — place the harness/coding order** (BOM exists; ship with the boards; record the
   matched 10M LCSC C-number in the order notes).
5. **First-article gate (checklist §2 / generated pack):** rails, GPB poke, ADC, USB,
   J16 bus, cross-mate refusal incl. **FA-8 sacrificial-pair coding proof (H7)**, and the
   **new at-temperature (≥ 70 °C) high-Z + D–G-short + stuck-GPIO rail-tap fault
   injection (spec R1.9 / OG-4 — a cold-only pass does not discharge it; the C1 gate's
   physical half)**.
6. **Firmware v1.2.1 bench flash + on-hardware validation** (C2's physical half): UF2
   flash, tap direction posture assert on real silicon, edge-ring reboot-persistence
   demo, ADC sanity vs DMM.
7. **Characterization session (DC1–DC3):** external-module analog population (CT
   channels, temp), thresholds — scheduled, not fab-blocking.
8. **M7 off-disk backup** — copy WSL_Backups to a second physical volume (WSL-SRV or
   USB), hash-verify at destination (open Dylan item).
9. **H5 residuals:** lane-server build-identity endpoint (lane-repo change, queued);
   arming `WSL_MACHINE_DIAG` on WSL-SRV once diagnostics go to production; lane-fleet
   deploy path remains separate from deploy.ps1 by design — keep the procedural gap in
   mind at every deploy.
10. **Push blocker:** `wsl-lane-nodes` cannot push (160 MB PDF in history at `aef294a`
    era) — history rewrite is a separate, deliberate task; until then the WSL_Backups
    mirrors + zips are the off-repo record. `WSL Systems` push/deploy per normal practice.

---

## 4. Backups / mirrors (all hash-verified at creation)

| Mirror (`C:\Users\Dylan DeYoung\WSL_Backups\`) | Contents | Source HEAD |
|---|---|---|
| `2026-07-20_phase8_revC_revD` (+zip+sha256) | pre-remediation rev-C/rev-D state | 2026-07-20 campaign |
| `2026-07-20_phase8_revD_routed` (+zip+sha256) | routed 2026-07-20 board | `7daf16a` era |
| `2026-07-21_phase8_revD_remediation` (+zip+sha256) | remediation end-state, 116 files | `a6502ef` |
| `2026-07-21_phase8_revD_remediation_r2` (+zip+sha256 `7926…ce51`) | + review batch, 120 files | `541dd5c` |
| `2026-07-21_phase8_revD_remediation_r3` (+zip+sha256) | **FINAL: + this report + doc sync** — supersedes r2 as the as-current record | FINALIZE HEAD (run-log FINALIZE record) |

**Rev-C sacred snapshot** (`backups/revC_design_snapshot_2026-07-19/MANIFEST.json`):
**189/189 hash-verified** before and after every batch of this campaign, including at
finalize (`scripts/verify_revC_snapshot.py`). Zero rev-B/rev-C design files touched
anywhere in the campaign; every rev-C artifact still carries its revB filename.

---

## 5. Standing invariants — held throughout

- Safety_Rail netclass count **exactly 13** at every audit (stop-ship invariant).
- No new copper on SAFE_* / RELAY_ENABLE_RAIL / RAIL_GATE; no load/divider on the rail.
- GND↔FIELD_GND zero shared nodes; LOGIC↔FIELD barrier only inside PC817s;
  LOGIC↔MACHINE only inside G5LEs; banding + gutters preserved.
- Wetting/D17 budgets re-run on the current changes (spec §H; SS34 lock).
- Footprint-vs-datasheet review for every part class touched: FR-8 (2N7002/SOT-23),
  FR-9 (MCV `_D1.4`) recorded in the run log.
- Netlist changes only through `generate_kicad_netlist_revD.py`; audit counts in
  lockstep; diff CLEAN with whitelists; WVR-ERC-1 baseline unchanged (1 error +
  40 warnings — no new waiver needed).
- Explicit per-file staging on every commit; **nothing pushed** from either repo.

---

## 6. Round-2 addendum (2026-07-21 PM) — LANE-NODE SOFTWARE slice

Codex re-audited the remediated package under a fabrication-readiness bar; the
lane-node software findings below are now CLOSED in this repo (fw v1.2.2 items
ride the firmware task; PCB/fab items ride the CAD task):

- **R2-5 (partial — generator):** `scripts/generate_first_article_docs_revD.py`
  pad-net parser accepts the KiCad-10 `(net "NAME")` form (the old int-id regex
  matched nothing → every TP row shipped BLANK); generation now **fails closed**
  on any blank TP net. FA-6 heartbeat fields corrected `adc_vcc5` → `v5`/`v5n`/
  `v5x` (the names the firmware actually emits); every firmware reference in the
  pack is generated from `config.h` FW_VERSION (`phase8b-rp2040 v1.2.1` at this
  regeneration) instead of a hand-typed version. Pack + CSV regenerated.
- **R2-6:** `BoardConfig.board_rev` has **no default** — provisioning is
  explicit (`--board-revs` / `WSL_BOARD_REVS` in `/etc/wsl-lane-node.env` /
  per-config), an unprovisioned board is refused at construction and skipped
  fail-safe, and AUX roles unsupported by the declared revision are rejected
  loudly at startup (`controller_daemon.py`).
- **R2-8 (lane slice):** `/api/health` carries `git_hash` + a `build` object
  (git hash, machine-contract sha256, start time) for deploy.ps1's build-hash
  compare.
- **R2-9:** both systemd units load `EnvironmentFile=-/etc/wsl-lane-node.env`;
  template `systemd/wsl-lane-node.env.example`; provisioning doc §8. Default
  deployment ships the HTTP diagnostics leg configured — JSONL-only is a
  degraded mode.
- **R2-11:** `rp2040_link.py` consumes ALL v1.2.x records — hb `tap`/`rd`/`ep`/
  `v5`/`v5n`/`v5x`, boot `tap{ep,pre,n}`, `tapdump`/`tape`/`tapdump_end`/
  `tapwarn` — into typed records the daemon promotes to machine events
  (`tapdump`, `tap_warn`, `uart_drops`, `v5_out_of_range`). **Epoch-aware:**
  ring entries whose epoch ≠ the current ring epoch are flagged stale and
  excluded from fresh diagnosis (unknown epoch ⇒ stale, fail-toward-exclusion).
  A boot that advertises a preserved pre-reboot ring triggers ONE bounded
  TAPDUMP read-back per epoch.
- **R2-12:** JSONL-as-outbox delivery — every event/cycle record stamped with
  `(source_id, boot_id, seq)` (`diag_events.stamp_delivery`); the daily JSONL
  IS the outbox, shipped by `OutboxReplayer` with a persisted cursor advanced
  only on 2xx (cursor-ack replay after any drop/outage); server dedupes on a
  UNIQUE partial index via INSERT OR IGNORE (additive migration in
  `machine_store`; ingest ack reports `duplicates`). ONE write path, no second
  Pi DB. Bank health promoted: `bank_unavailable` (IN-B read failures),
  `configured_role_missing`, `stale_channel` (pulse-role silent across N
  cycles); `run_mismatch`, UART drops, DiagQueue drops, HTTP/outbox drops,
  restart loops (`service_restart_loop`) and `fw_config_mismatch` (maxrun
  desync) are structured faults now, not log lines.
- **R2-14:** camera self-checks scheduled in the production daemon path
  (`lane_node.py`): periodic `frame_health` poll (dead/frozen/dark/blur →
  `camera_health`), throttled post-strike `self_check_empty` (→
  `camera_ref_drift`), all off the scoring path and skipped while a capture is
  in flight. GS-vs-camera per-pin disagreement counter wired server-side at
  cycle ingest (`gs_camera_disagree`, quiet-period throttled). Pi health beyond
  undervoltage on the PlatformHealth thread: disk-free + read-only-FS write
  probe, SoC thermal, wall-vs-monotonic clock-step, restart-loop detection,
  diag-storage retention (size-capped pruning, `diag_storage_pruned`).
- **R2-16 (software slice):** `field_wet_ok` role implemented now (AUX11
  loopback; jumper is a harness item): supply loss emits ONE `field_wet_lost`
  fault and suppresses the dependent field-input rules (no alert cascade);
  restore re-baselines and emits `field_wet_restored`. AUX role framework is a
  registry (`register_aux_role`) — extensible beyond the built-in four without
  editing the dispatch.

Verification: full lane suite green — pytest-native **199 passed** (this
slice adds 32 new tests across `test_r2_link_v12` / `test_r2_outbox` /
`test_r2_daemon` / `test_r2_server`) plus every standalone (`test_rp2040_link` 93/93, `controller_daemon --selftest`
30/30, `test_flight_recorder` 71/71, safety-rail/FSM/scoring standalones all
pass); rev-C sacred snapshot re-verified 189/189 after the batch. Contract
rev 1.2 sha `a51b95e2…` pinned in lockstep in both repos.
