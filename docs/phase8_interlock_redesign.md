# Phase 8 — TB/SC interlock redesign (the J_SAFETY landing)

**Status: ⚠️ DECISION OPEN — Dylan picks.** Written 2026-07-06 from the 2026-06-27 at-machine metering (lanes 21/22, SS chassis + Omega-Tek) and review findings **#1 (critical)** + **#4 (high)** in `phase8_fable_review_2026-06-27.md`. Nothing in this doc is landed hardware; until one of the candidates below ships, **the software echo is the ONLY TB/SC guard in the replacement stack** — and that echo is itself pending its own single-node redesign (finding #4/#12, separate workstream).

**Reads-with:** `phase8_metering_guide_harness_unknowns.md` (the measured record) · `phase8_trackB_controller_cutover_runbook.md` §3.4 + G3 (rewritten to match this doc) · `scripts/generate_kicad_netlist_revB.py` `block_rail()` (~line 472, the board-side contract — unchanged by this doc).

---

## 1. Measured ground truth (2026-06-27, at the machine)

- **SC reads at C2A cavity U** via its **N.O. (pink)** wire. The N.O. contact **closes during the danger window** (sweep-under-table, ~86–243°).
- **TB has NO standalone cavity.** Both TB wires tie into the same SC/U node; **neither TB wire isolates when the switch is actuated.** TB is interlock-only.
- **SC + TB are a SERIES interlock** sharing node **TSG-1 = C2A-U**, embedded in the machine's **live 24 VAC relay ladder**. The collision-course signal is the series pair *closing* (both cams in their windows simultaneously), which per the MP manual drops both motor relays — the interlock the manual override buttons cannot bypass. (Older docs said "TB + SC in PARALLEL" — **measured: series.** HANDOFF §"Safety" and runbook 3.4 pre-rewrite carried the parallel claim.)
- **U is also a common rail** (gripper/control common — it "rings to everything" cold, and PBZ shorts to U when pressed). So "the interlock node" is not a clean isolated point; the switched side of the series pair (TB's ladder feed, TSA-5 side) is likely the meaningful tap, and **which end carries the observable danger signal is a POWERED question.**
- **Cold continuity tracing is INVALID in this region:** the cam contacts sit in series inside the relay ladder, so locked-out beeps travel **sneak paths through ~21 Ω relay coils** (SA's lower wire reads ~21 Ω to CC ≈ BE's 22 Ω coil). Per-cam SA/SB/TA1/TA2 cavities are deferred to powered cutover for the same reason.
- **Cam edge polarity is unmeasured** (per-cam trip angles/edges are a powered capture item).

## 2. What the rev-B board expects (and can't get)

`block_rail()` (`generate_kicad_netlist_revB.py` ~472–511) builds the relay-enable rail as:

```
VCC5 → J_SAFE1/2  ("TBSC loop"  — EXTERNAL dry NC series contact pair)
     → J_SAFE3/4  (Stop/CIS loop)
     → PMOS source → RAIL_EN
```

The J_SAFE1/2 leg requires an **external, electrically isolated (dry), normally-closed contact pair that opens on a table/sweep interference** — closed-when-safe, open-on-danger, floating with respect to machine power.

**As measured, no such pair exists anywhere on this machine:**

1. **No isolatable contacts.** TB never isolates; SC is reachable only on its N.O. wire at a node that doubles as a common rail. There is no dry NC pair to lift and land.
2. **Wrong polarity even if you could reach it.** The accessible SC contact is N.O. — *closed* in the danger window — the exact inverse of the closed-when-safe loop the rail needs.
3. **Not dry.** The only observable is a node inside the **live 24 VAC ladder**. Landing the board's VCC5 sense loop there ties the 5 V logic domain into a live 24 VAC node — a board-killer and an isolation violation, independent of polarity.
4. **Unverifiable by the planned method.** Runbook 3.4's original "LOCKED OUT, confirm the NC loop by continuity" procedure cannot work: cold reads are poisoned by the ~21 Ω coil sneak paths.

The predictable field escape — jumpering J_SAFE1/2 so the rail comes up — removes collision protection with **no detection anywhere** (no code senses a jumpered loop). That escape is now explicitly forbidden at gate G3 (runbook rewrite), but the design gap it papers over is this doc's subject.

## 3. Candidate designs

All three keep the OEM ladder physically intact (lift, don't cut; never interrupt the safety loop — sectionF rule). All three require the **shared powered characterization** in §4 first.

### Candidate A — auxiliary contacts added at the SC/TB switches, feeding J_SAFE1/2

Add one auxiliary switch at each of the SC and TB cam followers — a second subminiature snap-action lever switch mounted to track the same lobe as the OEM switch — wired as a **dry series pair using the closed-when-outside-the-window throw**, landed on J_SAFE1/2. Fully isolated from the ladder; gives the board exactly the loop it was designed for.

- **Parts (per lane):** 2× subminiature SPDT lever microswitch (same form factor as the existing cam switches — Omron SS-5GL / D2F class, ~$3–8 ea), 2× mounting brackets (fab or bent sheet), hookup wire to J_SAFE1/2, hardware. **~$15–30/lane.**
- **Effort:** mechanical — bracket fab + mounting + lobe alignment at the machine, per lane. Est. **3–5 h for the first lane** (alignment iteration), ~2 h/lane after. Alignment verified against the powered window capture (§4).
- **Failure modes:**
  - *Alignment drift / window skew* — aux switch window offset from the OEM window → protection window narrowed or shifted. Mitigate: align against the powered capture; re-check at soak.
  - *Mechanical interference* — a badly mounted aux switch could foul the cam follower, i.e. **introduces a new failure mode into an OEM safety mechanism.** Mitigate: mount on independent bracket, never load the OEM lever.
  - *Contact/wire failure* → loop opens → **rail drops = fail-safe.** ✅
  - *Wrong throw wired* (closed-in-window) → loop open at rest, rail never arms → **loud, not silent.** ✅
- **Pros:** true independent hardware interlock; matches `block_rail()` unchanged; fail-safe in both dominant failure directions; testable locked-out (it's our own dry switch).
- **Cons:** the only candidate that touches the machine mechanically; per-lane fab labor across the fleet; alignment is a craft step.

### Candidate B — interposing relay sensing the interlock node

Sense the ladder's own interlock electrically and translate it to a dry contact: a small relay (or rectified-opto + relay) whose input is bridged across the interlock signal, with its output contact feeding J_SAFE1/2.

- **Parts (per lane):** 24 VAC-coil ice-cube relay (IDEC RH2B-UAC24 / Omron MY2 24 VAC, ~$10–15) + DIN socket (~$5), or a rectifier+opto front-end + small SSR; bridge-tap leads (bridge across, **never interrupt**, the ladder). **~$15–25/lane.**
- **Effort:** electrical only, ~**1–2 h/lane** — *after* the §4 powered characterization pins down where the danger signal actually appears and with what polarity (U is a common rail; the usable tap is probably the TSA-5/ladder side of the series pair, not U itself).
- **Failure modes — the big one:**
  - The ladder's signal **asserts on danger** (series pair closes). A relay that energizes on danger must use its NC contact to open the J_SAFE loop — so a **broken coil, blown tap wire, or lost 24 VAC to the sensor reads as "safe": loop stays closed, protection silently gone. NOT fail-safe.** Only the G3 machine-side physical-open test would catch it, and only at test time.
  - *B′ variant (partial rescue):* sense the **coil-side effect** instead — the motor-relay coil rail the interlock *removes* power from. That signal is present-when-safe → relay energized-when-safe → contact opens on either danger **or** sensor failure = fail-safe. But it senses "the ladder already dropped the coils," which overlaps candidate C's premise and is only meaningful if the sensed rail is upstream of the board's own contact.
  - *Wrong polarity chosen at install* → loop closed always → silent no-protection (same detection gap).
  - AC sensing needs filtering (half-cycle dropout chatter on the rail).
- **Pros:** no mechanical modification; single-point landing matches the measured single-node reality; cheap.
- **Cons:** simple form is **inherently not fail-safe** (danger-asserted signal); an active component in the safety path; entirely dependent on powered characterization; polarity mistakes are silent.

### Candidate C — documented + powered-verified reliance on the OEM series contacts inside the coil circuits the board switches

The board never sources machine power — its motion relays close dry contacts **in series with the existing 24 VAC coil circuits.** If the SC/TB series interlock contacts remain electrically in series within the S/T coil circuits (i.e. the ladder's own collision protection sits in the same loop the board's contact completes), then OEM protection survives controller replacement with **no J_SAFE landing at all**: even a board commanding motion on a collision course can't energize the coil, because the ladder opens it. J_SAFE1/2 then gets a **documented, labeled jumper plug on the harness** (an engineered decision, not a field improvisation), and the rail's TB/SC condition is formally delegated to the OEM ladder.

- **Parts:** none (one labeled 2-pin jumper plug per lane).
- **Effort:** zero install; all the cost is **verification** — the §4 powered characterization must prove the premise *before cutover is scheduled*, and Stage 6b/7 must re-prove it live per lane (force the interlock into the danger state while the board commands S/T, body clear → **coil must drop even with the board contact closed**, both S and T).
- **Failure modes:**
  - **The premise may simply be false.** Bench JOB-2 already proved the cam *stops* are LOGIC stops (routed through the Omega-Tek triac board, not hardwired) — if the Omega-Tek retrofit also mediates the *interlock* through the brain, removing the brain removes the interlock and C is void. Counter-evidence: the MP manual says the manual override buttons bypass everything *except* BE + this interlock ("the irreducible hardware safety"), and the 2026-06-27 metering found the series pair in the **relay ladder**, not on the logic board. Genuinely open → hence the mandatory pre-cutover powered proof.
  - **Depends on insertion point.** Whether the interlock is in series with the *specific* coil path the board switches depends on where the board contact lands relative to those contacts (C1 cavities per runbook §3.3) — again only determinable powered.
  - **Weakens the board's rail** from 6 AND-conditions to 5, and **normalizes the jumpered-J_SAFE pattern** the review flagged as the predictable escape. Mitigation: the jumper is a labeled harness part + the runbook G3 sub-test makes the machine-side interlock drop a hard gate every cutover.
  - Protection depends on OEM switches/wiring whose condition we don't control; no board-side observability of interlock health.
- **Pros:** zero new hardware, zero OEM modification, keeps the machine's own certified-by-decades protection primary; honest about where protection actually lives.
- **Cons:** unverifiable until powered; if it fails verification late, you're re-planning at the machine; permanent rail-condition delegation must be loudly documented (board silk says TBSC loop; harness says jumper).

## 4. Shared prerequisite — ONE powered characterization session (OEM brain still installed)

All three candidates need the same facts, none of which cold probing can supply. One deliberate powered session (staged per runbook §1 mode B — one test at a time, two people), **before** the candidate decision is final:

1. **Node/tap behavior:** with the mechanism hand-rotated (powered, motors not commanded) into and out of the interference window, meter (LoZ) what appears where — U vs the TSA-5/ladder side of the series pair — and with what polarity. Feeds B/B′ and the software echo redesign.
2. **C's premise:** with the OEM brain still in place, establish whether forcing SC+TB into the danger state kills the S/T motor-relay coil rail via the **ladder alone** (upstream of / independent of the brain's outputs). This can and should be answered **before** cutover day.
3. **Window angles:** capture the actual SC/TB closure angles vs cam rotation. Feeds A's alignment target and the (separate-workstream) single-node software echo.

## 4-RESULTS — §4.2 MEASURED 2026-07-07 (Dylan, at the machine): **PREMISE TRUE — the ladder alone kills both motor coils**

Method: motors unplugged; meter (VAC, LoZ) clipped **across A1–A2** of each motor contactor coil; interlock forced by holding the SC + TB cam-switch levers; motion commanded from the **rear-panel manual S / T switches** (brain-independent path).

| Levers (SC+TB) | Manual S → S-contactor coil | Manual T → T-contactor coil |
|---|---|---|
| **both held BACK (off buttons)** | **0 VAC (0.07 VDC noise) — DEAD** | **0 VAC — DEAD** |
| both pressing buttons | 24 VAC — energized | 24 VAC — energized |
| one back, one pressed | 24 VAC — energized | 24 VAC — energized |
| switch off (control) | 0 V | — |

Findings locked by this session:
1. **Candidate C's premise is TRUE**: a manual (brain-bypassing) motion command is blocked by the ladder when both cams are in the blocking state — for **both S and T**. The OEM collision protection lives in the relay ladder and survives brain removal, **provided the board's contact lands in series with these same coil circuits** (§3-C insertion-point caveat → re-prove per lane at Stage 6b/G3 as already gated).
2. **Contact logic = parallel closed-when-SAFE:** coil dies only when **both** switches release; either one pressed keeps it alive. This is the OEM "TB + SC in PARALLEL" reconciled with the single measured node: two parallel safe-contacts, danger = both open.
3. **Actuation direction INVERTED vs the pre-session assumption:** the blocking/danger state = **levers held BACK (buttons released)**, i.e. on the cams the interference window presents as the follower dropping back, not being pressed. Any software echo / aux-switch design must use this polarity — and the powered cam-window capture (§4.3) should still confirm the lever-back↔in-window mapping on the rotating machine.
4. Bonus: **S and T motor-contactor coils = 24 VAC** (closes the 2026-06-01 "heavy-lug contactor coil V" straggler).

## 5. Recommendation — ⚠️ decision stays OPEN for Dylan

**Recommended path: run §4 first; then C if its premise proves out, else A. B only as a distant fallback, and then only in the B′ (coil-rail-sensing, fail-safe) variant.**

Rationale:

- **C first** because it's the only candidate where the protection is the OEM ladder itself — the mechanism that has guarded this machine for decades — with zero new parts and zero new failure modes *if* the premise holds. The premise is a single measurable fact (§4.2) answerable in one pre-cutover powered session; it is not a cutover-day gamble if the verification is done up front. The cost (rail drops from 6 to 5 conditions, documented jumper) is real but bounded, and the rewritten G3 gate forces the machine-side drop to be re-proven at every cutover regardless.
- **A second** because it's the only candidate that gives the board the loop it was actually designed for, and it fails safe in both dominant failure directions. It costs mechanical craft work per lane and adds a (mitigable) interference risk to an OEM safety mechanism — acceptable if C's premise fails, since at that point the machine has *no* surviving hardware interlock post-brain-removal and building one becomes mandatory, not optional.
- **B last** because its simple form is silently-not-fail-safe (a dead sensor reads "safe"), which is a worse property than either alternative for a collision interlock. B′ fixes the fail-safe direction but converges on C's premise anyway — at which point C is simpler.

**Not decided here.** Dylan picks after the §4 session; record the decision + measurements in this file (§7) and update runbook §3.4/G2/G3 status accordingly.

## 6. What changed alongside this doc (already done)

- **Runbook §3.4 rewritten** — series not parallel; no isolatable NC pair; cold trace invalidated by coil sneak paths; landing BLOCKED on this decision.
- **Runbook Stage 6b + G3** — J_SAFE1/2 jumper forbidden as a way to pass G3 (except as the *documented outcome of candidate C*, in which case the machine-side coil-drop proof replaces the rail-drop proof); new sub-test: physically force the SC/TB interlock at the machine → motion permission must drop.
- **Code comments truthed** (`cycle_control_8270.py`, `controller_io.py`, `firmware/rp2040/main.c`): the hardware interlock is **PLANNED — design open per this doc; until landed, the software echo is the ONLY guard.** No logic changed.
- **Not changed here (separate workstream, finding #4/#12):** the two-input SC∧TB software model in `rp2040_link.py` / `main.c` / `config.h` — as measured it can never assert (TB has no independent input) — and the sectionF J3-3/J3-6 harness rows. The single-input echo redesign should consume §4's captures.

## 7. Decision record

| date | decision | by | notes |
|---|---|---|---|
| 2026-07-06 | **OPEN** | — | doc created; §4 powered session not yet run |
| 2026-07-07 | **OPEN — premise PROVEN, C is now the live recommendation** | measurements: Dylan | §4.2 answered TRUE at the machine (see §4-RESULTS): ladder alone kills S+T coils on manual command, both-levers-back = danger. Remaining before formal C adoption: §4.3 window-angle capture + per-lane Stage-6b insertion-point proof. Dylan to record the formal pick here. |
