# Hardware Independence Audit — Independent Verification

**Verification date:** 2026-07-09
**Verifies:** `docs/hardware_independence_audit_2026-07-09.md` (Codex audit, 58 findings)
**Method:** 23-agent adversarial re-check (Fable) against the exact commits Codex used —
wsl-lane-nodes `82feed6`, WSL Systems `4732e3b` — plus re-execution of all 6 of the audit's
reproducible claims. Read-only; no source, firmware, PCB, or config was modified.

---

## Bottom line

The Codex audit is **legitimate and accurate**. Of 58 findings: **53 CONFIRMED, 5 PARTIAL
(overstated, not wrong), 0 REFUTED.** All 6 executable claims reproduced byte-for-byte. The
NO-GO verdict for live Track-B cutover is **correct and should stand.**

Two framing corrections apply to how the findings are acted on:

1. **Almost nothing is an *active* hazard today.** The rev-B board's relays are dead (footprint
   bug), no v1.1.1 firmware is flashed, and no machine is live. The audit's severity labels are
   calibrated to a live machine that does not yet exist — they are correct as **cutover release
   gates**, not as present dangers. The one exception is the credential (§ Credential below),
   which is exposed now, independent of the hardware timeline.

2. **~75% of the flagship findings were already documented open gates**, mostly from the
   2026-06-27 Fable review and the 2026-06-09 audit, or in the source comments themselves. Of 21
   headline findings novelty-checked: **9 KNOWN, 7 PARTIALLY_KNOWN, 5 genuinely NEW.** The audit
   is a valuable re-consolidation of the existing backlog into one clean gate document, but it
   presents known items as fresh discovery without crediting existing tracking.

| Verdict | Count |
|---|---:|
| CONFIRMED | 53 |
| PARTIAL (overstated) | 5 |
| REFUTED | 0 |
| **Total** | **58** |

Executable claims re-run: **6 / 6 CONFIRMED.**

---

## The 5 genuinely NEW bugs (the audit's real value-add)

Not present in any prior review doc; worth engineering attention before bench-live work.

| ID | Sev | What's new | Why it matters |
|---|---|---|---|
| **C-02** | Crit | `controller_io.py:120-124` caches the OLAT bit **before** the I2C write; a NACK on a de-energize is consumed as the one-shot stop, and a later unrelated write re-asserts the stale bit | **Priority.** A *failed energize* path yields uncommanded motor energize with FSM in READY, where neither `MAX_MOTION_S` nor the firmware backstop covers it. Cache/hardware divergence reproduced. |
| **H-02** | High | `cycle_control_8270.py:216-219` resets the motion timer on **every** FSM state transition | Falsifies the "8s per-motor backstop" the source comment (`:67`) claims — a table energized continuously across TABLE_DETECT→RUNTHROUGH→TABLE_FINISH ran **23.7s** with no timeout. |
| **H-04** | High | Unhealthy branch at `controller_daemon.py:306-326` returns before `_slow_edges()`, so PBZ can never emit CLEAR after a firmware-latched fault | Breaks the code's own recovery contract (`:152-156`) → operator-unrecoverable lane, invites improvised resets. Fails safe (motors off) but no clean recovery. |
| **H-08** | High | Q14 (AO3401A rail pass-FET) is a single unmonitored point; a drain-source short bypasses watchdog+ARM+RP_OK, and nothing reads back `RELAY_ENABLE_RAIL` | Manual markets the rail as "non-bypassable" (`10_watchdog-rail.md:153-156`) while analyzing only the fail-open direction. No rail-drop feedback. |
| **H-19** | High | `provision_wsl_tasks.ps1:43` installs a **nonexistent** flat `lane_node_server.py` path with global Python; `requirements.txt` lacks `websockets` | A reprovision produces a lane server that can't start; the Unregister-then-Register (`:51-52`) replaces a correct manual task; `deploy.ps1` kills the running server and the smoke test stays green (never checks port 8766). |

C-02 and H-02 both directly falsify safety claims made in the code's own comments.

---

## The 5 PARTIAL findings (Codex overstated — corrections)

- **M-01** (MCP init order) — **misattributes the exposure.** The brief output window comes from
  *register retention* across a warm restart, not the IODIR-before-OLAT ordering; the ordering
  only delays remediation by ~4 sub-ms writes, and the rail is nominally down during init anyway.
  Reorder-OLAT-first is fine hardening, but it is not the mechanism claimed. → hardening, not a
  live init exposure.

- **C-09** (live-default) — code is confirmed live-by-default, but "a reboot alone moves
  hardware" is wrong: the daemon boots **disarmed into MANUAL_INTERVENTION** and the systemd unit
  ships **disabled** until §12.9 sign-off. It is a documented deliberate decision (review #52,
  `controller_daemon.py:71-72` "flip into a hard gate at/after §12.9"), not an unnoticed defect.
  Critical-as-release-gate is fair; critical-as-live-hazard is not.

- **H-24** (TMA0505S isolation) — real doc bug (`06_board-power.md:176` says ~1.5kV, but the
  selected part is 1000VDC **functional**, and BOM requires ≥1.5kV), but the docs never claim
  "protective" isolation — that framing is the auditor's — and `:176` already self-flags the
  number with a VERIFY note. → spec-number correction + part-vs-BOM mismatch, not a High.

- **M-18** (pair validation) — non-adjacent pairing is an **intentional** desk feature ("link two
  lanes for parties", `desk.html:1521-1526`); the recommendation would break it. The team-to-lane
  sort reversal is real but **unreachable** in the deployed config (the sole schedule writer
  `genRoundRobin` always emits ascending lanes). The stronger real defect the audit *missed*:
  transfer at `wsl_api.py:1084-1088` silently re-pairs to the adjacent lane. → low-medium.

- **H-22** (relay suppression) — accurate that load/suppression is unqualified, but "a guide says
  the 10A rating makes measurement optional" is not in the docs — every "10A is ample" line sits
  inside a VERIFY/open-item marker, and "keep suppression DNP until engineered" (the audit's own
  recommendation) is already the shipped state. → project-tracked gated open item, not a High gap.

---

## Credential exposure — the only item exposed *now*

**CONFIRMED and actionable today, independent of the hardware timeline.**

- `WSL Systems/wsl_env.bat` holds a live `sk_live_` secret (git-ignored locally — good) **and it
  is in committed history at `aef294a`, which is pushed to `origin/main` and
  `origin/fable-audit-fixes`.** The historical key is **byte-identical to the one still in use** →
  history-scrubbing is insufficient; **rotate at Stripe.**
- 4 stale copies exist under `.claude/worktrees/*/wsl_env.bat` — rotation/removal must cover them.
- **Mitigating fact the audit missed:** the `wsl-systems` remote is **private** (GitHub API →
  404). The public `wsl-lane-nodes` repo is **clean** — no credential in history or tree
  (`SEC-CRED-HISTORY-LN` REFUTED). So this is a private-repo exposure, not an open leak. Still
  rotate — private history + 4 worktree copies is too much surface for a live payment key.
- The other 4 pickaxe hits (`IMPLEMENTATION_PLAN.md`, `VERIFICATION_2026-06-14.md`,
  `test_l14_l15_stripe_guards.py`, `wsl_technical_documentation.docx`) are harmless `sk_live_`
  prefix references, not keys.

---

## Recommended response sequence

1. **Now:** rotate the Stripe live key; purge the 4 worktree copies; decide on scrubbing
   `aef294a` from remote (private repo lowers urgency, doesn't eliminate it).
2. **This sprint, before any bench-live work:** fix the 5 NEW bugs. **C-02 first**
   (disarm-on-first-I/O-exception + cache-after-confirmed-write + OLAT readback), then H-02
   (per-actuator energized-since timers independent of FSM state), H-04, H-19.
3. **Fold the rest into the existing §12.9 / `IMPLEMENTATION_PLAN.md` gate list** — most criticals
   (C-01, C-04, C-05, C-06, C-07, C-08, C-10, C-11) are already tracked there. Adopt the audit's
   Section 11 gate checklist wholesale as the cutover sign-off sheet.
4. **Adopt the §8.2 target architecture** — one local actuator-owner process per board,
   authenticated idempotent intents, restart-emits-zero-commands. Resolves C-05, C-06,
   H-13/14/15, H-16 as a family.

---

## Full per-finding verification table

Novelty column (for the 21 headline findings checked): **K**=already documented / **PK**=adjacent
issue documented, this mechanism not / **N**=new discovery / blank=not novelty-checked.

| ID | Codex sev | Verdict | Nov | Verification note |
|---|---|---|:--:|---|
| C-01 | Crit | CONFIRMED | K | Stock build has no enforcement — but README:179 says exactly this; documented gate, not latent. |
| C-02 | Crit | CONFIRMED | N | Cache-before-write → stale-bit assert → unbounded energize while armed. Reproduced. **New.** |
| C-03 | Crit | CONFIRMED | PK | Stuck-HIGH kick defeats NE555 — the designated "Pi died" backstop fails permissive. Freeze must land in the high window; per-event probability low. |
| C-04 | Crit | CONFIRMED | K | Single TA1 edge / dual-lobe — re-discovery of review-#6 (`fable_review_2026-06-27:90-102`); fires every fresh-rack. |
| C-05 | Crit | CONFIRMED | PK | HTTP-200 = live → restart POSTs CLOSE pulse. Reverse-reconcile was designed (IMPL_PLAN:667); the classifier defect is new. Restarts routine. |
| C-06 | Crit | CONFIRMED | PK | No durable event/command identity; dedup default-off; POWER_OFF doesn't flush queue. Components known; full chain re-consolidated. |
| C-07 | Crit | CONFIRMED | K | Unauth control plane, ownership theft — documented twice (addendum:192/265, review #51). No provisioning artifact sets the token → prod runs open. |
| C-08 | Crit | CONFIRMED | PK | lane-nodes display copy lacks `esc()`; raw innerHTML of names/team → same-origin hardware-control XSS. Documented 06-09 (U118), fixed in WSL Systems copy only. |
| C-09 | Crit | **PARTIAL** | K | Live-by-default confirmed, but boots disarmed + unit ships disabled; "reboot moves hardware" overstated. Deliberate deferred gate. |
| C-10 | Crit | CONFIRMED | K | No safe direct-24VAC front end; FOUL channel class open. Rev-A external interposer exists off-board; docs record the gap. |
| C-11 | Crit | CONFIRMED | K | FSM defaults preserve behavior docs call wrong — but they are labeled bench-gated switches (`:71-88`), not silent drift. |
| H-01 | High | CONFIRMED | PK | `run_mismatch` excluded from `health_ok`; persistent lost-RUN silently removes 8s backstop, no daemon-visible fault. |
| H-02 | High | CONFIRMED | N | Motion timer resets per FSM transition → 23.7s continuous table-on. **New.** Overstated for integrated stack (fw backstop bounds at 8s) → arguably Medium. |
| H-03 | High | CONFIRMED | | Motion-without-RUN faults only if no guarded motor runs — but the check is entirely inert in every shipped build; overstated for today. |
| H-04 | High | CONFIRMED | N | Unhealthy branch returns before slow-edge handling → PBZ CLEAR unreachable. **New.** Fails safe but breaks documented recovery contract. |
| H-05 | High | CONFIRMED | | PBZ no debounce; True/False/True bounce ends armed in SECOND. Functional mis-cycling, interlock still guards. |
| H-06 | High | CONFIRMED | | Attestation stale across boots; legacy v0.1 arms (test-pinned `:127`). Needs firmware swap under a running daemon; no v1.1.1 flashed yet. |
| H-07 | High | CONFIRMED | PK | RP2040 supervises UART intent, not physical relay state; welded contact unaddressed. Structural point justified; routine lost-RUN is time-bounded. |
| H-08 | High | CONFIRMED | N | Q14 single-point rail bypass; no `RELAY_ENABLE_RAIL` feedback. **New.** Requires a FET D-S short (real failure mode); NC loops still effective. |
| H-09 | High | CONFIRMED | | RP_OK raw on J1.13; J1.1=5V, J1.11=3V3 rail-tie risk on a hand-built dupont harness. Conditional on miswire. |
| H-10 | High | CONFIRMED | K | SC/TB echo models two inputs; machine has one node, opposite polarity. Redesign open (`interlock_redesign.md:126-127`). Candidate C makes OEM ladder primary. |
| H-11 | High | CONFIRMED | | Two lanes, one sync loop + blocking I2C; lane-21 hang stalls lane-22 kick/cam. ~11s NE555 the only backstop during a stall. |
| H-12 | High | CONFIRMED | K | Track A/B systemd units Conflict; cutover loses scoring. Deliberate anti-GPIO-overlap engineering; scheduled-integration gap. |
| H-13 | High | CONFIRMED | | WSL commits DB state before hardware ACK; `hardware_command_sent=true` even when `sent_to=0`. Success reported on commands that may never reach a node. |
| H-14 | High | CONFIRMED | | Blind retry after any exception duplicates non-idempotent OPEN/CLOSE. Narrow window (only on raised exception; non-2xx NOT retried). |
| H-15 | High | CONFIRMED | | Transfer = close-old/open-new across two commits; wipes in-progress Phase-8 scorer state on a routine desk transfer of 21/22. |
| H-16 | High | CONFIRMED | | Legacy VDB + Phase 8 both command a lane; `vdb.py` supplies a nonempty default host. Currently latent (see H-17). |
| H-17 | High | CONFIRMED | | Phase-8 reconciliation nested under `HAS_VDB_BRIDGE`; retiring the legacy bridge silently disables crash recovery — the audit's own theme. |
| H-18 | High | CONFIRMED | | No end-to-end session generation; open/closed is the only identity; a reopened lane keeps a stale roster silently. |
| H-19 | High | CONFIRMED | N | Provision installs nonexistent flat lane-server path w/ global python; `requirements.txt` lacks websockets; smoke test misses 8766. **New.** |
| H-20 | High | CONFIRMED | PK | Monitor requires only DB; `/health` unconditionally 200/ok even with zero Pis. `WSL_MONITOR_REQUIRE` opt-in only detects process-down. Watchdog task not provisioned. |
| H-21 | High | CONFIRMED | | Manuals §9/§12/§13 still teach the historical wrong G5LE pad map on the safety output stage; §11 corrected via checklist D2 but not the rest. |
| H-22 | High | **PARTIAL** | | Load/suppression unqualified — but project-tracked gated open item; "keep suppression DNP until engineered" is already shipped. Inflated to High. |
| H-23 | High | CONFIRMED | | 5V entry: J2 + SS14 only; no fuse/PTC/TVS/bulk; 3A-recommended source + 1A diode = genuine fault/fire path in an unattended cabinet. |
| H-24 | High | **PARTIAL** | | TMA0505S is 1000VDC functional, not the ~1.5kV `:176` states / BOM requires — but "protective isolation" is the auditor's framing; doc self-flags with VERIFY. |
| H-25 | High | CONFIRMED | | `export_fab_revB.py` hardcodes Rev-B names + recursively overwrites; loose README hash/size drift (2067/fbcd7214 → 2107/b0e32644); toolchain unpinned. |
| H-26 | High | CONFIRMED | | UART accepts bare RUN/STOP/CLEAR/PING; no CRC/seq/session. **Overstated:** forged CLEAR alone can't re-permit (ARM stays LOW in FAULT); loss is the fault latch, not motion. |
| H-27 | High | CONFIRMED | K | Coil-permission removal can't open a welded contact. Documented review #57. Inherent to any coil-switched relay (OEM chain shares it), not board-introduced. |
| M-01 | Med | **PARTIAL** | | Init-order exposure misattributed to write order; real cause is register retention. Hardening only. |
| M-02 | Med | CONFIRMED | | Non-atomic gripper read; open wire → no-pin. Mis-rack/mis-score, not motion hazard. |
| M-03 | Med | CONFIRMED | | Event drain can lose remainder after one exception. Needs ≥2 events/tick + exception; narrow but real (SA/TA1 bursts cluster). |
| M-04 | Med | CONFIRMED | | Track-A ball debounce uses `time.time` + unsynchronized check/set. µs window; backstopped by server dedup once set (dedup 0 today). |
| M-05 | Med | CONFIRMED | | Single-thread HTTPServer, unbounded Content-Length; can delay POWER_OFF. WS plane is separate loop; Pi safety paths unaffected. |
| M-06 | Med | CONFIRMED | | `state_store.py:404-420` auto-unpickles legacy blobs = code-exec path. Requires local write to `lane_state.db`. |
| M-07 | Med | CONFIRMED | | `RestartSec=5` < ~11s watchdog → resume without rail drop. Also needs cleanup failure for worst case. |
| M-08 | Med | CONFIRMED | | `relay_cleanup.py`/`controller_cleanup.py` duplicate pin maps; drift test covers MCP maps only, not RP2040/UART/RP_OK. In sync today. |
| M-09 | Med | CONFIRMED | | Empty roster opens DB state, skips hardware mirror. Deployed clients can't produce the input → API-robustness gap; medium-to-low. |
| M-10 | Med | CONFIRMED | | Sync bridge stalls desk 10-24s / startup ~16s per pair when lane server down. Only 21/22; degrades, doesn't corrupt. |
| M-11 | Med | CONFIRMED | | Contract test pins `/scoring/correct`; real route is `/correct`. Prod works today; false-confidence test gap. |
| M-12 | Med | CONFIRMED | | Tenth-frame max-possible: X,6 shows 26 vs engine 20. Cosmetic MAX projection; only when max≤300. |
| M-13 | Med | CONFIRMED | | Series math double-counts cumulative `prog_scratch`; wrong footer totals in multi-game league. Display-only (engine correct). |
| M-14 | Med | CONFIRMED | | Live SQLite defaults into repo, not gitignored, `STATE_DB_PATH` unprovisioned. Data-lifecycle gap. |
| M-15 | Med | CONFIRMED | | DRC lacks FIELD↔MACHINE rule; doc says 1.0mm edge clearance, project rule 0.5mm. Rules-encoding gap; FIELD/MACHINE placed at opposite edges. |
| M-16 | Med | CONFIRMED | | Compiled manual stale re J5; sources corrected. Dangerous only if the compiled manual is used at bench; staleness itself recorded. |
| M-17 | Med | CONFIRMED | | Rev-B filenames for a Rev-C board; name-identical dead-relay rev-B zips exist. Mix-up risk, documented at tree root. |
| M-18 | Med | **PARTIAL** | | Non-adjacent pairing is intentional; sort reversal unreachable (schedule writer always ascending). Real defect: transfer re-pairs adjacent (`wsl_api.py:1084-1088`). Low-med. |
| M-19 | Med | CONFIRMED | | Paired-lane open across separate commits; crash → orphan session (staff-recoverable). |
| M-20 | Med | CONFIRMED | | Bridge doesn't strip token whitespace; server/Pi do. Latent (token default-off/unset); surfaces at rollout. |

---

## Executable claims re-run (6 / 6 CONFIRMED)

| Check | Result |
|---|---|
| `EXEC-SHA-PCB` | `wsl-phase8b.routed-manual.kicad_pcb` SHA-256 = `7E7ACFAA…891EC97C` — byte-identical to audit line 890. Audited board = board on disk. |
| `EXEC-ENGINE-PARITY` | Both `wsl_scoring_engine.py` copies = `48EF3054…84FD0445`. Identical, matching audit §10.1. |
| `EXEC-PYTEST-COLLECT` | `pytest --collect-only -q` in wsl-lane-nodes dies with `INTERNALERROR SystemExit: 0` from `tests/test_cursor_resync.py:55` after 29 tests. Matches audit §10.3. |
| `EXEC-DISPLAY-DIFF` | WSL Systems `wsl_scoring_display.html:202` defines `esc()` (used :309/329/375); lane-nodes copy has zero escaping, raw concat at :305/:325 → innerHTML :379. Copy-drift confirmed. |
| `EXEC-FAB-MANIFEST` | `manifest.json` expects README 2067 bytes / `fbcd7214`; loose file is 2107 bytes / `b0e32644`. Both values match audit lines 712-713 exactly. |
| `EXEC-PINMAP-TEST` | `tests/test_pin_map_drift.py` → 2 passed. Matches audit §10.1. |

---

## Verification method & limits

- 20 subsystem batches (one Fable agent each) traced the cited code paths and grepped for
  callers, config gates, and prior-tracking docs; 3 special agents handled executable re-runs,
  the credential search, and the novelty cross-check against `phase8_fable_review_2026-06-27.md`
  / `IMPLEMENTATION_PLAN.md` / source comments.
- Same limitation as the original: **no energized-machine test.** Hardware-conditional findings
  (cam edge/lobe semantics, Stop/CIS landing, Candidate-C insertion proof, input voltage class,
  relay load/suppression, first-article operation) remain mandatory bench/machine measurements —
  they are neither confirmed nor waived by this software verification.
- WSL Systems working tree had uncommitted edits at verification time; agents were instructed to
  grep for the referenced identifier when a cited line number drifted. No cited mechanism failed
  to locate.
