# Phase 8 Rev-D — Round-3 Remediation Report (Codex third audit)

> **SKELETON — assembled by the doc-layer / R3-7 / R3-8 task; sibling tasks (software,
> firmware, deploy, diagnostics) fill their own rows and paste their adversarial-reproduction
> evidence.** Closure bar this round is the **adversarial reproduction Codex ran**, not a unit
> test. Every row must end **CLOSED** (survived the reproduction) or **DISPOSITIONED-WITH-
> EVIDENCE**. Companion records: `phase8_revD_round2_report_2026-07-21.md` (round-2 closing),
> `phase8_revD_remediation_report_2026-07-21.md` (round-1), run-log FR-15 (J16), first-article
> pack FA-9 (PC817).

Canonical contract: `server/machine_contract.json` (WSL Systems repo), hash pinned in the
WSL Systems contract test — every contract change updates BOTH repos in lockstep in the SAME
campaign. rev-C snapshot re-hashed after this batch: **189/189 OK** (`scripts/verify_revC_snapshot.py`).

---

## 1. Codex round-3 regrade vs round-2's claims — the honest reconciliation

Codex's third audit **regraded round-2 to 4 CLOSED / 9 PARTIAL / 4 OPEN** with adversarial
reproductions (poison-pill replay, wrong-topology drill, cursor stranding, stale-identity,
CLEAR loophole). The board itself is **sound** — DRC 0/0/0, routed-mode audit ALL PASS, builds
verified; the **only board-adjacent defect is the J16 polyfuse CONTRACT** (a number, not
copper). Every reopened item was a **paper closure**: correct-looking code or a correct board
part whose *end-to-end behavior* was never exercised the way Codex exercised it.

| Round-2 claim | What round-2 recorded | Why it was paper | Round-3 item |
|---|---|---|---|
| R2-6 / R2-12 CLOSED — durable idempotent outbox delivery | fw identity chain + JSONL outbox | daemon emits `fw_identity`; contract vocabulary omitted it → server rejects the WHOLE batch, cursor never advances (replay: acked=0, all later events blocked) | **R3-1** |
| R2-10 CLOSED — offline drill passed | lease OFFLINE at 90 s proven | drill drove the **Track-A** WS heartbeat; a quiet **Track-B** controller sends no heartbeat → healthy board expires OFFLINE | **R3-2** |
| R2-12 CLOSED — outbox replay | cursor-based replay | missing/invalid cursor starts at the **newest** daily file, stranding older unsent records; `machine_cycles` ship via a lossy shipper with no replay | **R3-3** |
| R2-8 / R2-9 CLOSED — deploy proves the lane leg | deploy POST smoke + build-hash compare | bridge maps missing/invalid upstream → HEALTHY or FAULT (should be UNKNOWN); deploy **warns-not-fails** on missing tasks/auth unless SMS armed; accepts any nonempty protocol/hash | **R3-4** |
| R2-6 / R2-11 CLOSED — fw identity surfaced | identity chain | rp2040 reboot does **not** invalidate cached identity/capability; stale RID/hashes survive a reboot; missing identity not surfaced as UNKNOWN | **R3-5** |
| (fw) CLEAR path | v1.2.2 fault handling | CLEAR unconditionally clears the fault and can reassert RP_OK **inside** the 250 ms window without revalidating input-only pins | **R3-6** |
| **R2-4 CLOSED — J16 protected** | F1/JP1/U46/U47 stack + FA-12 | **board stack is sound**; the *contract* "100 mA with ≥2× hold margin" used the polyfuse **23 °C** hold — false at temperature (90 mA hold @85 °C ⇒ no margin) | **R3-7 (this task)** |
| **R2-7 DISPOSITIONED — PC817 margin** | spec §R4-A + FA-9 per-channel | the empirical gate was **digital pass/fail** (reads active-low y/n); the bounded arithmetic was never anchored by **numeric** V_CE / capability data with an aging reserve | **R3-8 (this task)** |
| R2-16 CLOSED — bank-unavailable / robustness | catalog v1.1 | bank read failure false-faults dependent rules; unknown AUX role strings do not refuse startup; NaN/garbage telemetry can kill the reader | **R3-9 / R3-10** |
| R2-11 CLOSED — camera/Pi health | diag sinks | camera + Pi diagnostics split across mutually-exclusive services — one class is lost whichever service runs | **R3-11** |
| R2-17 CLOSED — backup scope | NAS gate | the NAS gate doc referenced by `deploy.ps1:341` is **untracked** (clean clone can't reproduce) | **R3-12** |

**Structural root cause across all three rounds: cross-contract vocabulary drift** — a
producer emits a token (`fw_identity`, a state string, an event kind, a health class) that a
consumer/contract does not know, and the mismatch fails silently or fails closed on the whole
batch. **R3-1a is the primary structural goal: move the event-type vocabulary into the single
contract and make a test enumerate every emitted `event_type` and fail if any is absent.**

---

## 2. Round-3 criteria table (R3-1 … R3-12)

Status: **CLOSED** = survived Codex's adversarial reproduction · **DISPOSITIONED** = evidence-
backed, no redesign · **IN-PROGRESS** = owner working · **PENDING** = not yet started.

| # | Finding (one line) | Owner task | Status | Evidence |
|---|---|---|---|---|
| R3-1 | fw_identity poison pill — contract vocabulary + per-record ingest + client quarantine | software (lane/server) | _(owner)_ | contract test enumerates emitted event_types; replay: fw_identity + valid → valid acked, cursor advances, invalid quarantined |
| R3-2 | OFFLINE drill wrong topology — authenticated identity-heartbeat / lease renewal from controller_daemon | software (lane) | _(owner)_ | Track-B drill: healthy-quiet stays HEALTHY, killed controller → OFFLINE |
| R3-3 | outbox loses records — recover from OLDEST unacked file; durable cycles; outbox health telemetry | software (lane) | _(owner)_ | 2-file repro: older file ships; cycles replay; heartbeat carries oldest-unsent age / backlog / cursor health / quarantined count |
| R3-4 | deploy/bridge residuals — missing/invalid → UNKNOWN; expected-topology fatality; contract-digest + feature-set check | deploy (WSL Systems) | _(partial inherited)_ | bridge maps missing→UNKNOWN; deploy fatal on expected-phase8 manifest; dedup capability REQUIRED |
| R3-5 | stale firmware identity — invalidate ALL cached identity on reboot; missing→UNKNOWN; inhibit ARM on mismatch (env-escapable) | firmware + lane | _(owner)_ | reboot clears RID/MAXRUN/masks/V5; re-request; mismatch inhibits ARM unless WSL_ALLOW_IDENTITY_MISMATCH |
| R3-6 | firmware v1.2.3 — CLEAR revalidates input-only pins before clearing / RP_OK; FI-1 timeouts + dead-man; host tests | firmware | _(owner)_ | built + host-tested (NOT flashed); CHANGELOG + version bump |
| **R3-7** | **J16 polyfuse contract re-derivation (no copper)** | **doc-layer (this task)** | **CLOSED** | **§3 below; run-log FR-15; allowance 100 mA → 45 mA @85 °C, ≥2× hold; all doc/comment sites corrected; rev-C 189/189** |
| **R3-8** | **PC817 FA-9 numeric V_CE / aging-reserve; EXPERIMENTAL first-article framing** | **doc-layer (this task)** | **CLOSED** | **§4 below; FA-9 rewritten numeric; G15 acceptance line; pack regenerated (fail-on-blank gates intact)** |
| R3-9 | bank-unavailable → UNKNOWN (suppressed) not false-fault; unknown AUX role REFUSES startup; coverage events | diagnostics (lane) | _(owner)_ | bank read fail suppresses dependent rules; typo role → loud refuse |
| R3-10 | robustness — NaN/garbage never kills reader; RO-filesystem still heartbeats; maintenance expiry | diagnostics (lane) | _(owner)_ | hardened parse + quarantine counter; ro-detection flag; maintenance overdue alert |
| R3-11 | camera/Pi service split — shared health-drop-file so both classes reach the store | diagnostics (lane) | _(owner)_ | shared drop-file topology documented |
| R3-12 | NAS gate doc untracked — commit it; backup disposition rationale/fatality flag per R3-4 | deploy (WSL Systems) | _(owner)_ | doc committed; rationale recorded or fatality flag consistent with expected-topology model |

---

## 3. R3-7 — J16 polyfuse contract re-derivation (CLOSED, docs/contract only, NO COPPER)

**Finding (Codex):** the documented "1206L020 100 mA with ≥2× hold margin" is false at
temperature. PPTC hold derates steeply; PPTC *trip* is not a hard limit.

**Datasheet basis — Littelfuse POLYFUSE Resettable PTCs, 1206L Series (1206L020-C = 1206L020YR):**
I_hold 0.20 A / I_trip 0.42 A / V_max 24 V / I_max 100 A @ 23 °C. Still-air hold-current
derating (A): −40 °C 0.28 · −20 °C 0.25 · 0 °C 0.23 · **23 °C 0.20** · 40 °C 0.17 · 50 °C 0.15 ·
60 °C 0.14 · **70 °C 0.12** · **85 °C 0.09** (matches Codex's "~120 mA @70 °C, ~90 mA @85 °C").

**Declared worst-case F1 body temperature: 85 °C.** Source: `phase8_pair_enclosure_spec.md`
(2026-07-14) — sealed, no-vent, ΔT ≈ 8 °C over 35 °C summer ambient → internal *bulk* air
≤ ~48 °C. F1 sits in that sealed volume next to the dominant heat sources (Pi + heatsink,
TMA-0505S brick, energized relay coils); the datasheet derating references ambient at the
device, so a local hotspot can exceed bulk air. We derate at the datasheet's **characterized
ceiling (85 °C)** to envelope any realistic in-box rise rather than model an uncertain
hotspot (the 48 °C bulk point interpolates to ~0.154 A hold, for reference only).

**Re-derivation:** I_hold(85 °C) = 0.090 A; required ≥ 2× hold margin →
**sanctioned J16 module 5 V allowance = 0.090 / 2 = 45 mA** (was 100 mA). Expect-range from
the finding (≤ 45–50 mA) satisfied.

**Consequences:**
- **F1 part UNCHANGED** — 1206L020YR still trips a shorted module (~420 mA @23 °C, ~250 mA hot)
  INSIDE the FR-3 SS34 3 A budget; only the quoted *steady-draw* allowance is corrected.
- **D17 budget IMPROVES** — worst case with 45 mA ≈ **0.775–0.975 A** (was ~1.03 A at 100 mA);
  SS34 keeps comfortable margin, SS14 stays retired. No copper motion either way.
- **NO copper / netlist / DRU change.** F1 footprint, MPN (C207035), placement, and the four
  J16_* nets are byte-identical. Verified: **no executable audit/export assert encodes 100 mA**
  (grep of `audit_revD_board.py` / `export_fab_revD.py` — only comment/prose + one BOM NOTE
  string). All prose corrected in source.

**Locations corrected (every 100 mA site):** generator SS34 comment (`generate_kicad_netlist_revD.py`
~L557) + J16 protection docstring (~L804); `diff_netlist_revC_to_revD.py` comment; change-spec §F
table + §H.4 (full derivation added); change-list items F + H; run-log FR-3 + R2-4 + new **FR-15**
(full derivation record); readiness-checklist G14; first-article pack FA-12 (regenerated); export
BOM note string (`export_fab_revD.py` L188).

**Frozen fab-package residual (disclosed, no action):** `kicad/fab_revD_2026-07-21_r3/` (and
`..._r2/`) are hashed atomic exports (manifest.json + zips). Their assembly BOM/part-lock F1 rows
carry the legacy "100 mA" text in a **human-readable NOTE field only** — MPN/footprint/qty/
designator identical, and F1's 200 mA hold amply satisfies even the corrected "hold ≥ 2× 45 mA"
substitution rule. The r3 package is **NOT regenerated** (that would re-hash an as-exported
package and churn gerbers for a comment); the corrected string lives in `export_fab_revD.py` and
flows into the next regeneration. **Zero hardware consequence.**

**rev-D.1 upgrade path (recorded, needs copper → not this spin):** replace the PPTC + SRV05-4
with a current-limiting **eFuse / e-load-switch carrying a hardware-programmable current limit
AND an open-drain FAULT flag** routed to a spare RP2040 GPIO — part class TI **TPS2660**
(industrial eFuse, adj. ILIM, /FLT) · TI **TPS25200** (5 V eFuse, FAULT) · Nexperia
**NX5P3290** class — so a wedged/over-drawing J16 module becomes a firmware-diagnosable event
instead of a silent trip with a long PPTC reset tail.

---

## 4. R3-8 — PC817 experimental framing + numeric FA-9 (CLOSED, disposition-with-evidence)

**Finding (Codex):** the round-2 PC817 closure was arithmetic (§R4-A) anchored only by a
*digital* pass/fail FA-9 (channel reads active-low, y/n). The margin still rests on bounded
reads of typical curves (Sharp publishes no minimum CTR at the fleet's ~1.7 mA I_F).

**Resolution — Codex's alternative implemented:**
1. **FA-9 upgraded to NUMERIC per-channel qualification.** Every populated channel is
   characterized (not a 3-channel sample) with **in-circuit V_CE(sat)** AND a **non-rail-
   limited capability measurement I_C(cap)** (diagnostic pull-up / µA meter at the collector),
   at the **loaded-minimum FIELD_WET (≈ 4.5 V)** across the declared temperature range
   (25 °C ambient → **≥ 70 °C case**).
2. **Aging-reserve pass criterion** (spec R4 end-of-life CTR ×0.70): the in-circuit front-end
   is rail-limited by the 3.3 V/10 k pull-up (flip 0.26 mA, pull-up max 0.33 mA — a fixed 1.25×
   native window). The gate demands capability that keeps hard saturation after a 30 % CTR loss:
   **PASS ⟺ I_C(cap, hot, min-I_F) × 0.70 ≥ 0.33 mA ⟹ I_C(cap) ≥ 0.47 mA.** A channel that
   only just flips today (no reserve) FAILS. Numeric V_CE(sat) alone cannot express the reserve
   (it pins low once CTR×I_F exceeds the pull-up limit) — hence the explicit capability read.
3. **Order labelled EXPERIMENTAL first-article.** Pack header + FA-9 heading carry the ⚗️
   EXPERIMENTAL banner; the fab-order framing in the readiness checklist is
   "EXPERIMENTAL FIRST-ARTICLE ONLY" until the physical gates clear.
4. **Blank EXPERIMENTAL-ORDER acceptance line for Dylan** added to the readiness checklist as
   new gate **G15**, beside the blank OG-1 and H2 lines:
   `EXPERIMENTAL-ORDER ACCEPTANCE: ____ (date / decision — fleet-release gated on FA-9 numeric V_CE + OG-4 at-temp)`.

**Pack regenerated** via `scripts/generate_first_article_docs_revD.py` (271 rows, 46 shifts, 24
TPs, 8 GPB rows) — the fail-on-blank TP-net and 46-shift gates still enforce, and the sign-off
table now scores the numeric FA-9 rows.

---

## 5. What this task did NOT touch (owned by sibling round-3 tasks)

R3-1/R3-2/R3-3/R3-5/R3-9/R3-10/R3-11 (software + firmware + diagnostics, both repos),
R3-4/R3-12 (deploy + NAS gate), R3-6 (firmware v1.2.3). Those rows above are placeholders for
their owners' adversarial-reproduction evidence. The **contract-vocabulary single-source
structural fix (R3-1a)** is the campaign's primary goal and is a software-task deliverable —
this doc-layer task only records the reconciliation that motivates it.

---

## 6. Batch bookkeeping

- rev-C sacred snapshot re-hashed: **189/189 OK**.
- Board copper / netlist / DRU: **UNTOUCHED** this round (J16 fix is docs/contract/BOM-note
  only; no assert encoded 100 mA, so none changed). Safety_Rail count unchanged (13).
- Firmware: not touched by this task (R3-6 is the firmware owner's).
- Commits: explicit staging, both repos, never `git add -A`, never push.
