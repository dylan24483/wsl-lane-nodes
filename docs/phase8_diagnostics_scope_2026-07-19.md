# Phase 8 — Machine Diagnostics & Condition-Monitoring Scope (2026-07-19)

> **Status: SCOPING — nothing here is implemented or committed.**
> Provenance: 5-subsystem multi-agent deep dive (hardware capacity / FSM+firmware / telemetry / WSL-Systems ops surfaces / 82-70 domain), all load-bearing claims adversarially verified against code, then a completeness-critic pass whose 10 findings are integrated below. Follows code over docs; known-stale docs are flagged in §6.
> Motivating question (Dylan, 2026-07-19): *do common faults (pin jams etc.) produce identifiable electrical states, and can the controller notify desk/mechanic before the customer reports it? Can diagnostics be improved by matching current state against a library of known problem-state signatures?* Short answer: **yes and yes** — most faults are a *sequence + duration + command disagreement*, not a unique instantaneous state, and roughly half the needed machinery already exists in the repo.

---

## 1. Fault-detection capability matrix

Availability tiers: **A** = software-only on current hardware · **B** = firmware+daemon work · **C** = new sensing hardware · **D** = camera-based.

| Fault mode | Detection rule (state + sequence + duration + command) | Signals used | Confidence | Tier |
|---|---|---|---|---|
| **Table stall / jam** | State ∈ {TABLE_DETECT, SPOTTING, TABLE_FINISH} AND elapsed > MAX_MOTION_S=8.0 → latched FAULT (`cycle_control_8270.py:66-69,400-422`); mirrored UART-independently by firmware MAX_MOTION_MS=8000 on guarded motor T (`config.h:82`, `main.c:404-413`). Refined rule: per-interval baseline breach (guard_to_table, table_to_ta2, sa_to_ta1zero) at 4σ (`cam_telemetry.py:87-94,266-284`). | TA1/TA2 cam edges (GP9/GP10), FSM state, T relay command | **High** — this is the fault class the wired inputs were designed for (`manual_src/22_troubleshooting.md:324-347`). **Caveat (H-02, CONFIRMED):** the FSM resets its motion timer on EVERY state transition — a table energized continuously across TABLE_DETECT→RUNTHROUGH→TABLE_FINISH ran 23.7 s with no software timeout (`hardware_independence_audit_2026-07-09_VERIFICATION.md:49`). Per-MOTOR energized-time tracking closes this (Phase 1). | A |
| **Sweep stall** | State = SWEEP_TO_GUARD or RUNTHROUGH AND elapsed > 8 s → FAULT; firmware backstop on motor S; drift precursor via ss_to_guard / ta2_to_sa baselines. | SB/SA cam edges (GP7/GP6), S relay command | **High**, same H-02 caveat. "Sweep 15% slower week-over-week = stretching belt" is the explicit design intent of cam_telemetry (`cam_telemetry.py:3-14`). | A |
| **Cam switch failure (dead)** | Motion commanded, expected cam edge never arrives → 8 s timeout fires with the *state name* identifying which cam died. Cannot distinguish "cam dead" from "motion stalled" without cross-evidence (motor current = Tier C). | Cam edge absence + motor command | **Medium** — detects that *something* failed, attributes weakly. | A |
| **Cam switch chattering** | >8 debounced edges from one cam input in any 100 ms window (>30 for DIELL) → latched `chatter` fault, RP_OK drops (`main.c:211-234`, `config.h:67-76`). Gap: per-input bounce counts are NOT exported — pre-failure chatter *trends* are invisible until counters ride the heartbeat. | Per-input edge rate in firmware | **High** for the binary fault; **zero** for trending until export (Phase 1). | A / B |
| **Cam out-of-order / unexpected edge** | Currently **invisible**: cam events in a non-matching FSM state are silent no-ops — every cam handler is a bare `if state is X` with no else (`cycle_control_8270.py:259-263,290-302`). Rule to add: log+count any cam edge outside its expected state. Firmware cam_overrun (stop-cam trip + no STOP within 150 ms) is implemented but compiled OFF (`config.h:84-174`, `main.c:419-446`). | All 6 cam edges vs FSM state | **Blocked on cam polarity**: per-cam trip-edge polarity unmeasured for all six cams; trip edges default to the `'?'` never-fires sentinel (`config.h:125`). TA1/SA dual-lobe ambiguity (fable review finding 6) corrupts sequence signatures until lobes are disambiguated. **Low until powered-session polarity capture, then High.** | B |
| **Stuck ball switch (DIELL beam stuck blocked)** | SS is replaced by DIELL beams; a statically blocked beam gives ONE edge, not continuous cycling — the classic AMF signature doesn't transfer (`manual_src/04_machine-io.md:155-179`). Startup-time stuck-input detection **already exists and is correct** — the daemon baselines `_prev_slow` from actual input levels, logs already-asserted inputs loudly, and requires deassert-then-reassert (`controller_daemon.py:260-279`, tagged "review #28"). The genuine gaps: **mid-session** stuck-input detection and a **beam-blocked-duration** rule (DIELL level asserted > N s while lane READY → `beam_blocked` event). | DIELL level (GP12/13), PBZ/BS/Foul levels | **High once built** — pure software. | A |
| **Continuous cycling (pin jam under cushion)** | AMF signature = jam holds SS closed → machine recycles. Our FSM ignores balls outside READY (`cycle_control_8270.py:226-231`), so the failure re-expresses as repeated ball events with abnormal inter-cycle spacing, or beam_blocked above. Rule: >N cycles with inter-cycle gap < baseline p1, or ball events during motion states (already logged, `:228-233`). | Ball events + cycle cadence | **Medium** — signature must be re-derived for beam sensing (Phase 3 distillation). | A |
| **Gripper / spotting faults (dead gripper switch)** | **Invisible electrically**: unwired/dead gripper reads not-standing (active-LOW, open = "condition absent", `03_machine-sequence.md:220`); a pin-8-only leave becomes mask==0 → STRIKE → fresh rack sweeps a standing pin (fable review finding 24). Rule: per-pin persistent disagreement counter between GS mask (latched at TA2) and camera standing-pin mask. Requires the camera-health anchor (below) to attribute disagreement to the gripper rather than to ROI shift / lighting drift / frozen frame. | GS1-10 (MCP IN-A) × camera pin_mask | **High once built** — both sensors validated (GS map 10/10 read live 2026-07-18). Chassis-return contacts are a documented dirt/oxide wear surface worth per-pin watching (`04_machine-io.md:75-102`). | D |
| **Short rack / spotting failure (full-rack verification)** | Post-spot camera capture asserting "10 pins standing after a fresh rack." Doubles as the **camera self-check anchor**: if the full-rack assert starts failing on known-good racks, the camera (not the machine) has drifted. Partially closes the bin-fill attribution gap below. Needs a Track-B post-cycle capture trigger — today capture is once per ball, 2.5 s post-DIELL, pre-sweep only (`lane_node.py:221-260`). | Camera pin_mask at cycle-complete | **High once the post-cycle capture point exists.** | D |
| **Bin-fill class faults (elevator/distributor/pin-feed starvation)** | BS (#9 bin switch) never closes → TABLE_FINISH exceeds 8 s → FAULT (`cycle_control_8270.py:325`; BS at C2A-CC). Trend precursor: bs_to_ta1zero interval drift. Root-cause attribution (elevator vs distributor vs bin) is NOT possible from this input set; full-rack verification narrows it from the output side. | BS level, TABLE_FINISH duration | **Medium** — detects starvation reliably, attributes poorly. BE-motor causes invisible (next row). | A |
| **Motor/contactor electrical failure** | (1) **BE/M stuck or overloaded — INVISIBLE**: BE and M are NOT max-run-guarded (`config.h:80-81`), BE isn't driven by the current FSM, and there is **zero analog sensing on the board** — Pico ADC pins 31/32/34/35 are wired to nothing (verified against the netlist generator AND the generated `.net`). (2) **Welded relay contact — INVISIBLE today**: firmware `motion_no_run` (cam edges while nothing commanded) is implemented but default-OFF, gated on cam polarity + per-board bench confirmation (§12.9), with known nuisance-trip paths (finding 57). (3) **Coil open / contactor not pulling in**: expressible only as motion-timeout. Motor current never crosses the PCB (relays switch ~24 VAC control circuits; machine contactors switch the 115 VAC motors — `09_relay-outputs.md:15-25`) → current sensing = CT/hall clamp at machine contactor wiring feeding an AUX opto (digital threshold) or external ADC module. | (today) motion timeouts; (future) CT/hall on BE + S/T | (1) **None → Tier C.** (2) **Low → Medium** after polarity capture arms motion_no_run. (3) Medium. | C / B / A |
| **Offspot pin** | OS switch is allocated on MCP IN-A GPB3 but NOT consumed by the FSM and its C2A cavity is unmeasured — effectively unreadable today (`04_machine-io.md:113`; metering guide). Camera partially covers it: a badly off-spot pin shifts off its cap ROI and reads not-standing/low-confidence (`pin_detect.py:88-133`) — a flag, one ball late. **Doc trap:** OS/BS bit order was swapped in the channel-allocation draft; netlist truth is OS=GPB3, BS=GPB4 — use `controller_io.IN_A_MAP`. | OS (after cavity trace) + camera margins | **Blocked on OS cavity trace** (powered-session item); then High. | B / D |
| **Slow-cycle degradation trends** | Already prototyped: 6 named per-cycle intervals, Welford baselines, 4σ + 0.15 s absolute drift alarms after 30 samples, aborted-cycle hygiene (`cam_telemetry.py:87-131,249-284`) — running in the production daemon tick (`controller_daemon.py:254,357-389`). But: entirely in-memory, sink never wired, `baselines()` has no caller, resets on restart (all CONFIRMED). Interval resolution is ~20 ms daemon-tick because the Pi **discards the firmware's 1 ms edge timestamps** (`rp2040_link.py:245-263` queues only `('cam', id)`). | 6 intervals (+ fw `t` after plumbing) | **High** mechanism, **zero** persistence today. | A |
| **Platform / power health** | A whole telemetry class that costs almost nothing: rail-drop-reason tap (which of the observable gates — WDOG_KICK TP8, ARM TP13, RP2040_OK TP14 — went away first, read from existing high-impedance points); `rp2040_wdt_reset` (250 ms hw watchdog → chip reset, `config.h:60`) as a **distinct code** from generic `fw_reboot`; Pi undervoltage/throttling via `vcgencmd get_throttled`; SD wear; lane-node service restart counts. Both of this project's past field incidents (the missing watchdog kick; the not-enabled systemd unit) would have surfaced here first. | TP/J1 status lines, fw reboot reason, Pi host stats | **High** — all Tier A. | A |
| **Mechanic-intervention discrimination** | MAN_T/S/SWS/SWSR + PBC + 10th are wired to MCP IN-B but IN-B is initialized, never read — `controller_io.py` has no IN_B_MAP (hardware-complete, needs a small read path). Manual-override activity is the strongest "machine being serviced — suppress alerts" signal; without it every mechanic session becomes an alert storm. | IN-B GPA0-7 | High once the read path exists. | A/B |

**Cross-cutting: SC+TB and cam polarity (measured ground truth beats the manuals).** SC+TB form a SERIES interlock on one shared node (C2A-U); TB has no standalone cavity; GP11/J3-6 has nothing to observe (`04_machine-io.md:41-48`). Consequences: (a) per-cam interlock attribution ("which cam opened the interlock") is **impossible as wired** on this chassis; (b) `interlock_ok()` must NOT be used as a fault signal — the two-input SC∧TB echo "as measured can never assert" (`phase8_interlock_redesign.md:127`), and Candidate C delegates collision protection to the OEM ladder with the engineered J_SAFE jumper; manual chapters 16/19 describing a wired J14 NC loop are STALE; (c) `interlock_collision` firmware detection is blocked on bench-confirming SC/TB danger windows — a *different* prerequisite than the §3.2 polarity capture that blocks cam_overrun/motion_no_run; (d) all six cams' cavities and edge polarities are unmapped until the powered session (cold reads invalidated by the C2A-N shared common + ~21 Ω sneak paths). Every cam-sequence signature above starts at reduced confidence until that capture lands.

---

## 2. Three-layer architecture mapped to real components

### Layer 1 — Deterministic rules (hard faults, act-now)
**Hosts (existing):**
- **RP2040 firmware** (source v1.1.1; **which image is flashed on the machine-22 board is unverified** — resolve at the powered session): motion_timeout + chatter active; cam_overrun / motion_no_run / interlock_collision implemented but compiled OFF. Emits typed `{"ev":"flt","code":...}` JSON + drops RP_OK (`main.c:404-446`).
- **cycle_control_8270 FSM**: MAX_MOTION_S, GUARD_DELAY_MAX_S, two-press PBZ recovery (`cycle_control_8270.py:159-214,400-422`). ⚠️ The "refused-energize → FAULT" and "mid-motion interlock veto" paths (`:175,194-205,404-410`) are **inert under Candidate C on the 21/22 chassis** — the SC∧TB echo they depend on can never assert both inputs. Do not count them as live detection capacity.
- **controller_daemon**: startup stuck-input detection (`:260-279`), link health → `_on_safety_trip` — the single choke point every fault path already funnels through (`controller_daemon.py:306-330,391-408`) = the one place to attach an emitter.
- **rp2040_link**: fw_reboot detection, `run_mismatch()` (an unconsumed signal), TX-drop warnings (`rp2040_link.py:313-457`).

**New code needed:** structured fault codes — `_fault(why)` is free-text that never reaches the recorder (`cycle_control_8270.py:209-214`); else-branch logging/counting of unexpected cam edges; per-MOTOR energized-time (H-02); mid-session stuck-input + beam-blocked rules; IN_B read path; platform_health emitters. All must obey the established pattern: observe-only, bounded, **never raises into the 50 Hz tick that kicks the NE555** (`controller_daemon.py:26-30,286-292` — blocking work in any tick stalls BOTH lanes' kicks).

### Layer 2 — Fault-signature library (typed events + forensics)
**Hosts (existing):** FlightRecorder (2000-event ring, blackbox JSON on FAULT/link-loss/tick-error, 50-file local retention — `flight_recorder.py:47-55,107-118,300-316`); trace_replay for deterministic off-hardware FSM replay (`trace_replay.py:14-46`) — but **no blackbox→trace converter exists** (formats differ), so "replay a real fault in CI" needs that converter.
**Signature source:** the AMF troubleshooting content is **already extracted** — full TABLE TROUBLES / sweep / ball-lift cause-remedy tables (jam, Klixon-overload) sit in `Downloads/svc_text.txt` (+ `8270_text.txt`), referenced by `phase8_8270_SYSTEM_REFERENCE.md:60`. The missing pass is **distillation into a repo signature table**, not PDF mining.
**New code:** signature matcher over machine_events sequences (state, duration, input pattern → probable cause + mechanic hint), plus dump shipping off-Pi.

### Layer 3 — Fleet anomaly + trend detection
**Hosts (existing):** CamTelemetry (baselines + drift alarms, already in the tick loop). **Transport:** the Pi already runs a proven production websocket to the :8766 server's WS port (`lane_node.py:19,42`) — the work is the deliberately-deferred TODO(server) unification bridging the synchronous daemon into that async path (or an interim local HTTP POST), an *integration* task, not a new transport. **:8766 server:** `/api/health` is already a rich self-diagnostic surface (uptime, per-lane scoring summaries, save-persistence health — `lane_node_server.py:759-806`) — extend it, don't invent a parallel one. WS ingest currently accepts only HELLO/BALL_EVENT/FOUL_EVENT/HEARTBEAT (`lane_node_server.py:256-266`); add TELEMETRY/FAULT types. **wsl_api** pulls via the test-pinned bridge (`wsl_phase8_bridge.py:170-226`; contract test `tests/test_phase8_bridge_contract.py` — lockstep cross-repo change). **Analytics :5002** = read-only trend reporting per the roadmap rule (owns no schema — `RMS_ARCHITECTURE_ROADMAP_2026-07-10.md:116-120`).

### Data schema — new Machine/Equipment domain
The roadmap's 10 domains contain no Machine domain → this is a **new domain**: own tables, own vocabulary, never sharing rows or status enums with Fulfillment/Reporting. **Single owner: the lane-node server (:8766, its SQLite store).** wsl_api is a **pure proxy** — no second writable copy in wsl.db (a periodic *read-model* sync is allowed only if explicitly one-way; never a second writer). Desk ack/resolve is a **wsl_api-initiated POST to :8766** (the bridge stays strictly wsl_api-initiated; no inbound push). `acknowledged_by` stores the wsl.db staff id as an opaque reference across the domain boundary.

Timestamps UTC; explicit `business_date` (roadmap tier 3; precedent `tip_runs`); durations integer ms.

```sql
CREATE TABLE machine_cycles (
  id            INTEGER PRIMARY KEY,
  lane_id       INTEGER NOT NULL CHECK(lane_id BETWEEN 1 AND 32),
  business_date TEXT NOT NULL,
  started_at    TEXT NOT NULL,               -- UTC ISO
  ended_at      TEXT,
  cycle_type    TEXT,                        -- writer-validated; NO CHECK (taxonomy will grow)
  ball          INTEGER,
  final_state   TEXT NOT NULL,               -- READY | FAULT | MANUAL_INTERVENTION
  aborted       INTEGER NOT NULL DEFAULT 0,
  -- the six CamTelemetry intervals, integer ms, NULL when not observed:
  ss_to_guard_ms INTEGER, guard_to_table_ms INTEGER, table_to_ta2_ms INTEGER,
  ta2_to_sa_ms  INTEGER, sa_to_ta1zero_ms INTEGER, bs_to_ta1zero_ms INTEGER,
  gs_mask       INTEGER,                     -- 10-bit gripper mask latched at TA2
  cam_mask      INTEGER,                     -- 10-bit camera standing-pin mask (when available)
  fw_version    TEXT, shadow INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_mc_lane_date ON machine_cycles(lane_id, business_date);

CREATE TABLE machine_events (
  id            INTEGER PRIMARY KEY,
  lane_id       INTEGER NOT NULL CHECK(lane_id BETWEEN 1 AND 32),
  business_date TEXT NOT NULL,
  created_at    TEXT NOT NULL,               -- UTC
  severity      TEXT NOT NULL CHECK(severity IN ('info','warn','fault')),  -- the ONLY CHECK enum
  event_type    TEXT NOT NULL,               -- writer-validated, NO CHECK: fsm_fault, fw_fault,
                                             -- drift_alarm, chatter, link_lost, fw_reboot,
                                             -- rp2040_wdt_reset, rail_drop, pi_undervoltage,
                                             -- service_restart, stuck_input, beam_blocked,
                                             -- gripper_disagree, short_rack, run_mismatch,
                                             -- manual_override, recovered, ...
  code          TEXT,                        -- typed, e.g. 'motion_timeout:S'
  cycle_id      INTEGER REFERENCES machine_cycles(id),
  detail_json   TEXT,
  blackbox_file TEXT,
  acknowledged_at TEXT, acknowledged_by INTEGER, resolved_at TEXT,
  incident_id   INTEGER                      -- optional link to manual lane_incidents; no shared enum
);
CREATE INDEX idx_me_open ON machine_events(acknowledged_at, created_at);
```

Rationale for no CHECK on `event_type`/`cycle_type`: this project's own 2026-04-17 lesson — SQLite CHECK changes force a full table rebuild, and this taxonomy is guaranteed to grow (cam_overrun, motion_no_run, current-switch, camera cross-checks are all queued for later phases). `lane_incidents` (manual, `schema_analytics.sql:86-103`) stays as-is; machine_events may link via `incident_id` but never shares its vocabulary. Note the existing `lane_incidents` write endpoints live on password-gated :5002 and are dormant (zero UI callers) — machine ingestion inverts that: writes land on the operational side.

---

## 3. Alerting path

1. **Pi, off-tick:** attach an emitter at `_on_safety_trip` + CamTelemetry `cam_sink` + drift-alarm hook. Events → bounded in-memory queue; a writer thread (dump_async pattern, `flight_recorder.py:173-195`) ships them — **never from the tick thread**.
2. **Pi → server:** bridge into the existing lane_node.py websocket (the TODO(server) unification) or interim HTTP POST to :8766. New WS message types beyond the current 4.
3. **:8766 server (owner):** persists machine_cycles/machine_events, exposes `GET /api/lane/<N>/diagnostics`, enriches `/api/health`. Accepts the ack/resolve POST from wsl_api.
4. **wsl_api (:5000):** pure proxy via the existing bridge pattern (`_proxy_phase8_get`); machine fault state rides the **bulk `/api/lanes` payload** — mandatory, because the per-lane scoring fanout polls OPEN lanes only (`desk.html:6157-6159`) and idle-machine faults would otherwise be invisible. Contract test updated in lockstep.
5. **Desk (≤5 s via existing poll, `desk.html:6224-6228`; polling is the house pattern — no WS/SSE anywhere):** extend the shipped `__scoringOffline` trouble primitive (`desk.html:6173-6180`) with fault badges ("TABLE STALLED", "PIN JAM?"); toast on new fault (`.dv-toast`); persistent banner for unresolved faults (CONNECTION LOST pattern); ack/resolve queue copied from shoe_requests. **Desk UI is Design's deliverable via a `DESIGN_HANDOFF_machine_health.md`** (endpoints/shapes/acceptance) per the standing front-end split — backend + handoff doc are in-scope here, the UI build is not.
6. **Mechanic SMS:** `from wsl_customer_app import _send_sms` — module-level, provider-agnostic, zero auth coupling (`wsl_customer_app.py:95-118`). Run off-thread (synchronous 10 s Twilio timeout); throttle + dedupe (one text per latched fault, not per poll). **Recipient resolution is NOT solvable from existing data**: `labor_schedule` is a DOW×hour×role×headcount *forecast template* with no staff identity — no roster, no time clock exists anywhere. v1 = an explicit **on-call contact** (config row, or `staff.role='mechanic'` + designated-contact flag + new `staff.phone` column — no staff phone exists today). A real shift roster is future work. **Verify TWILIO_* env on WSL-SRV at deploy** — machine-scoped env, and the Stripe incident proves deploys silently strip env vars; bake it into deploy verify.

**PUBLIC_PATHS — never expose:** `/api/machine/*`, `/api/lanes/*/diagnostics`, the :8766 server, ack endpoints, blackbox dump contents. Internal-LAN surfaces exactly like `/desk`/`/kds`. machine_events writes stay off :5002 (read-only per roadmap).

---

## 4. Hardware gaps and add-ons

**Actual spare capacity (verified against the netlist generator + generated .net):**
- **Immediately usable: exactly 3 input channels** — AUX1/AUX2/AUX3, J5 pins 9-11, IN-B GPA5-7, full PC817B front-ends, explicitly reserved to avoid a respin. "Usable" = hardware-complete; needs the IN_B_MAP software read path.
- **One vacant fast, edge-capable, isolated input:** TB/GP11 (J3 pin 6) — nothing to observe there on the 21/22 chassis (SC+TB series) → the only no-new-hardware candidate for a **once-per-rev encoder index pulse**. Must be coordinated with the pending single-node SC∧TB echo redesign (competing consumer of that harness row). Full quadrature has **no compliant path** — all 8 fast inputs committed; PC817B bandwidth unspecified. AUX channels can take a low-rate index at ms-class MCP-interrupt latency.
- **Respin-only spares:** 8 IN-B GPB pins (no optos/connector), 5 OUT-A bits (no drivers), ~15 RP2040 GPIOs (unrouted), 0x23 OUT-B address (no footprint).
- **ADC: none.** Pico ADC pins connect to nothing. No rail monitor, no voltage sense. The 24VAC-sense front-end is a documented population *option* with unverified footprints.
- **Pi GPIO headroom: UNKNOWN** — the per-pair Pi budget is a DRAFT full of `# assign` placeholders (`phase8_channel_allocation.md:137-150`). A USB ADC dodges the question entirely.

**Current sensing (the BE/M blind spot):** motor current never crosses the PCB → sensors clamp at machine contactor wiring regardless of board revision. Options: (1) **digital-threshold hall/CT current switch** → dry contact into AUX1/AUX2 — gets "BE running yes/no" + "above overload threshold"; closes the BE-invisible gap and detects welded-contact stuck-running. Budget wetting against the TMA-0505S 1W rail (~2 mA/channel; rail floats ~14 V unloaded — rev-C item 5 bleed NOT implemented). (2) **External isolated ADC module** (USB preferred) for real amplitude/trend data. Priority: **BE motor first** (unguarded, invisible, drives the whole bin-fill fault class), then S/T (stall-vs-dead-cam disambiguation, brake wear trending).

**Rev-D wishlist (do NOT spin the board for diagnostics alone — everything pilot-critical fits the external-module path):** ADC front-end or isolated-ADC connector; populate GPB optos + connector (+8 inputs); 24VAC-sense interposer footprints; FIELD_WET_V bleed (item 5); Pico USB clearance (item 3); OUT-B footprint.

**Non-negotiables:** isolation contract §5.3 — no machine signal touches Pi/RP2040/MCP pins directly; LOGIC↔FIELD barrier only inside PC817s (≥2.5 mm), LOGIC↔MACHINE only inside G5LE relays (≥3.2 mm); never bridge GND/FIELD_GND. The safety rail (6-condition hardware AND gating the pass-FET feeding all relay coils, not Pi-bypassable) is **observe-only**: read TP1-TP16 / J1 status lines; never load, jumper, or re-reference SAFE_*/RELAY_ENABLE_RAIL. A "why did the rail drop" diagnostics tap from those existing high-impedance points is legitimate and is scheduled (Phase 1).

---

## 5. Phased build plan

Sequenced against real state: rev-C validated bench 6/6 + field input-side on **machine 22** (config rename queued); powered session pending; interlock Candidate C decided; ONE pilot machine now.

### Phase 0 — Powered-session ride-alongs (honest cost: several hours of probing, not zero; ranked so it's explicit what gets cut first)
Hard sequencing rule: **meter tapped-lead live voltages FIRST, board disconnected** (the standing session gate). Shadow-mode collection comes strictly *after* the metering→reconnect gate.
1. **§3.2 per-cam edge→angle polarity capture** (already a cutover-runbook item) — unblocks cam_overrun, motion_no_run, and every cam-sequence signature. Resolve TA1/SA lobe identities. *(Highest value — protect this one.)*
2. **Per-motion duration measurement** (stopwatch/scope over a few cycles) → seeds MAX_MOTION_S = measured+margin and initial baselines; today's only numbers are 12.1 RPM nominal, 3 s settle, and a "~8-10 s" code comment.
3. **Record which firmware image is flashed** (v0.1.0 vs v1.1.1 — behavior differs materially). Trivial, do it while connected.
4. **Cavity traces while metering anyway:** OS (promote it — it's the offspot detector), GP, PBC/10th/manual switches; cam front-end electrical class (dry vs 24 VAC).
5. **SC∧TB danger-window observation** at C2A-U — the separate prerequisite for interlock_collision.
6. **After reconnect gate:** run controller_daemon in **SHADOW mode** (`WSL_CONTROLLER_SHADOW` — FSM on real inputs, outputs record-only, ARM held LOW; default is LIVE, set the env explicitly) during any remaining powered time → first real cam_timing rows + blackbox-format data.

### Phase 1 — Software-only hardening on the Pi (Tier A; ~1 week)
1. **Firmware-timestamp telemetry redesign** (was "carry ev['t'] through" — it is a design task, not a pass-through): re-plumb the CamTelemetry feed off the cam event queue instead of FSM `_observe()` transitions; add a fw-ms ↔ Pi-monotonic offset estimator resynced on fw_reboot; accept that mixed-clock intervals (fw edge → Pi command, e.g. guard_to_table) get no precision win. Still the biggest single accuracy improvement (~20 ms → ~1 ms on pure-edge intervals).
2. Structured fault codes: `_fault(why)` → typed code into recorder + dump extra.
3. Else-branch logging + counters for unexpected cam edges; export firmware chatter/bounce counters via heartbeat.
4. Per-MOTOR energized-time tracking (closes H-02).
5. Mid-session stuck-input + DIELL beam-blocked rules; IN_B read path + IN_B_MAP (manual-override visibility → alert suppression).
6. **platform_health basics:** rail-drop-reason tap (existing observable points), rp2040_wdt_reset as distinct code, Pi `vcgencmd get_throttled` poll, service-restart counter.
7. Persist cam_sink locally (append-only jsonl/sqlite on Pi) so baselines survive restarts; blackbox→trace converter for CI replay.

### Phase 2 — Transport + storage + surfacing (backend + Design handoff; ~1-2 weeks, cross-repo)
1. Daemon→server event bridge (TODO(server) unification via existing WS, or interim :8766 POST). 2. machine_cycles/machine_events on the :8766 store (single owner) + ingest + `/api/lane/<N>/diagnostics` + ack/resolve POST endpoint. 3. wsl_api proxy sub-path + machine state in the bulk `/api/lanes` payload (update the pinned contract test in lockstep). 4. **`DESIGN_HANDOFF_machine_health.md`** for the desk UI (badges/toast/banner/ack-queue — Design builds it). 5. On-call-contact config + `staff.phone` migration + `_send_sms` mechanic alert with throttle; TWILIO env check added to deploy verify.

### Phase 3 — Fault-signature library (~1 week)
1. **Distill** `Downloads/svc_text.txt` troubleshooting tables (TABLE TROUBLES, sweep, ball-lift, jam/Klixon) into a repo signature doc + event-code mapping (extraction is already done; distillation never happened). 2. Signature matcher over event sequences. 3. Camera detectors: **full-rack verification** (post-spot 10-standing assert = short-rack detector + camera self-check anchor), gripper-vs-camera popcount disagreement, post-cycle capture point triggered by Track-B cycle-complete, spot_divergence dead-wood probe. 4. Arm cam_overrun/motion_no_run per §12.9 bench procedure (needs Phase 0 polarity; soak in log-only posture first). 5. OS consumption (needs Phase 0 cavity).

### Phase 4 — Fleet + predictive (32 machines, post-cutover scale)
1. :5002 read-only machine-health dashboard (existing route-registration + collector-thread patterns). 2. Cross-machine baselines (machine-22 priors seed new machines; per-machine re-learn). 3. BE current switch on AUX (per-machine install at contactor). 4. Encoder index on GP11 if the echo redesign frees it. 5. Rev-D decision from field data, not speculation.

---

## 6. Risks and honest limits

- **False-positive cost during league play.** A latched FAULT drops motors and needs two deliberate PBZ presses to recover — a false trip mid-league is a lane down and a mechanic walk. Therefore: Layer 2/3 detections are **alert-only, never actuate** — only the existing Layer-1 backstops keep trip authority. Drift alarms need 30 samples and today reset blind on every restart — persistence (Phase 1.7) is a precondition for trusting them. Armed firmware detectors (motion_no_run has known nuisance paths: settle-back re-trip, MP manual buttons) soak in shadow/log-only first. Manual-override (IN-B) gates alert suppression.
- **Single-machine baseline limits.** Everything calibrates on machine 22 — also the *newest-maintained* machine, so its baselines will be optimistic. Signatures learned on 22 are priors, not thresholds, for the fleet.
- **Faults invisible to this input set (do not promise them):** BE/M overload/failure (Tier C only); welded contacts until motion_no_run is armed; dead gripper switches without the camera cross-check; offspot until OS is traced+consumed; per-cam interlock attribution (permanent on this chassis); anything mechanical that doesn't perturb cam timing, switch state, or the camera view. Open-circuit inputs read "condition absent" by design — absence-of-signal faults always need cross-evidence.
- **Safety non-negotiables.** No blocking I/O in the 50 Hz tick (a stall drops BOTH lanes' NE555 kicks); all diagnostics inherit observe-only/bounded/never-raise/async-write with env kill-switches; no new ARM or rail authority; never bridge GND/FIELD_GND; never weaken the watchdog — including "just this once" during debugging. NE555 timeout is bench-measured (~10 s), not source-declared.
- **Data volume.** Trivial by design (~low-thousands rows/day at 32 lanes), but: keep machine writes off the shared wsl.db hot path (wsl_api is a proxy, not a writer); blackbox dumps are 50 files/lane on Pi SD cards — batched local writes for SD wear, shipping + pruning matters at scale; raw 1 ms edge streams stay in the Pi ring buffer, only per-cycle aggregates + events go upstream.
- **Truth drift to watch:** docs stale against code in known places (IN-B channel count, GPIO maps, manual ch. 16 FSM / ch. 19 safety vs Candidate C, main.c version banner says v0.1.0). This doc follows code + decision records; implementers must do the same, and the flashed-firmware unknown must be resolved before assuming v1.1 features exist on the board.
