# Westside Lanes — DIY String-Pinsetter: 1-Lane Prototype Scope

**Status:** EXPLORATORY design study, 2026-06-04. This is a "could we build our own?" scoping exercise — **not a commitment, not a budget, not a plan of record.** It exists to answer one question honestly: *if the Phase-8 controller + camera are the brain, what would it take to put a string-pinsetter body under them, and where would it break?* Costs and dimensions are engineering estimates with wide error bars; every real unknown is flagged inline as a risk or open question.

**How this was produced:** a 10-agent design workflow, one engineer-agent per subsystem (operating cycle, string management, lift/set, pins/deck, ball return, rev-C electronics, FSM/scoring, safety, BOM, FMEA/test), each grounded in how real string machines actually work (QubicaAMF EDGE String, Brunswick StringPin, U.S. Bowling, USBC specs — sources cited in the sections), then synthesized here. The ten subsystem sections (§1–§10) are the body; this front matter is the executive read.

---

## The one-paragraph answer

**Yes, it's buildable as a proof-of-mechanism, and the reuse story holds up.** A string pinsetter collapses to a *single vertical degree of freedom* — far simpler than the AMF 82-70 it would replace. The ten subsystem designs converge on one architecture: a **common-lift "string wagon"** (one ~300–400 W BLDC + a timing-belt carriage on linear rails, 0.9 m stroke, ~255 N design load) that lifts all ten pin-strings together; **per-pin selection** ("which pins stand this shot") happens not in the lift but in the string take-up, via **ten solenoid pinch-latches**; pins land on-spot **by cord geometry + a settle dwell, with no spotting cup** (exactly how Brunswick/QubicaAMF do it); and **our camera (Track A) replaces the cord-tension load cells** commercial string machines use to detect pins — strictly more informative, since it sees actual standing pins. Deadwood just hangs from its own string — **no sweep, no spotting table, no distributor, no shark/turret** (the four heaviest, most failure-prone 82-70 subsystems are deleted). The Phase-8 brain drops straight in: **rev-C is ~$40 of board electronics + one ~$190 JLCPCB spin, and is *simpler* than rev-B** (no cams, no grippers, no C1/C2A harness). **New spend ≈ $5,150 for one lane** (range $4–7.5k) on top of the already-owned brain — versus **~$25k/lane** for Brunswick string. So you'd crush them on parts; the real cost is **your time and the reliability risk**, exactly as we said. The whole project reduces to one empirical question — *does a home-built string mechanism survive a string-life interval without tangling or mis-setting?* — answered by a **10,000-cycle bench soak** (~11 hours continuous).

---

## Executive summary

### The architecture the agents converged on
- **One motion primitive:** lift all ten, lower a commanded subset. First-ball partial clear and full re-rack are the *same* mechanical action — only the reel-selection mask differs. Strike/spare/open all funnel into the same "full re-rack" path; the difference is score bookkeeping in software, not mechanism.
- **The string wagon** (Subsystem 3): one belt-driven carriage, one supervised motor — the cleanest possible reuse of the existing "drive a coil, let the machine's iron switch the motor" relay pattern. Selection is pushed downstream into the take-up so the lift stays a single rugged actuator.
- **Per-string latches** (Subsystem 2): ten solenoid pinch-holdbacks decide which pins stay aloft (deadwood) vs. pay back down (standing). **This is where the program's #1 risk lives** — string tangle and latch reliability over thousands of cycles.
- **On-spot landing with no cup** (Subsystems 3/4): accuracy comes purely from per-pin guide-tube geometry + a settle dwell. Target ≤ ±6 mm typical. The dwell length is the only knob and must be tuned on the rig.
- **Camera as the detector** (Subsystems 1/7): two reads per shot — **READ-A** (after impact settle, *before* lift) scores the shot *and* becomes the latch-selection mask; **READ-B** (after set + settle) verifies the commanded pins actually landed. A tangle/mis-set surfaces as a READ-B mismatch — the FSM makes it a **detectable, fault-stopping event, not a silent mis-score.**
- **12-state FSM** (Subsystem 1: S0 POWER_ON → S2 READY → … → S10 READ_B → S11 RECOVERY → S12 FAULT), mapped onto the existing `controller_daemon` / `CycleController` / RP2040-link / `MachineIO` framework — **simpler than the 82-70 cam FSM** (no cam angles; camera mask + wagon limit switches drive every transition).
- **Cycle time:** ~3–4 s mechanism, ~5–7 s end-to-end — in line with commercial string units. **10,000 cycles ≈ 11 h continuous** on the durability rig (skip the ball-traverse wait).

### Cost roll-up (NEW spend, one lane — §9 is authoritative)
| Bucket | Est. new spend | Notes |
|---|---|---|
| A. Frame / cabinet (T-slot extrusion, gantry) | ~$640 | Cheaper if a scrap 82-70 cabinet shell is salvaged |
| B. Lift carriage + drivetrain (BLDC + driver, rails, belt, **custom wagon weldment**) | ~$1,310 | Biggest bucket (~25%); the weldment carries the widest error bar |
| C. String management (constant-force spools, 10 latches, guide tubes, comb) | ~$672 | Latch actuator choice (10 solenoids) is unsettled |
| D. Pins + deck + spots (2 sets of string pins, deck plate, spots, kickbacks, cushion) | ~$510–1,170 | Buy string-pins; don't roll your own |
| E. Ball handling + return (pit, accelerator wheel, ½ HP gearmotor + contactor, track) | ~$1,375 | A real mechanism; powered return optional for the mule |
| F. rev-C board spin + new sensors | ~$190 + ~$45 | One JLCPCB spin; ~$24 required new sensors |
| *(Reused brain: Pi + RP2040 + PCBA + camera)* | *~$225 — excluded* | Already owned/designed |
| **TOTAL NEW SPEND — one lane** | **≈ $5,150** | **Realistic band $4,000 – $7,500** |
| *Brunswick string, for comparison* | *~$25,000 / lane (~$800k / house)* | Certified, supported, productized |

### Where it most likely breaks (the honest part)
1. **String tangle in the pit-slack zone** — the ~54–65″ of slack below the deck is *not* eliminated by the guide tubes; deadwood-on-deadwood crossing still happens (worse with slow/kids' balls). The design makes it **detect-and-recover** (a lower-and-reshake macro + camera), not prevented. **The headline metric of the whole experiment is hard (unrecoverable) tangles per 1,000 frames.**
2. **On-spot landing has no cup to forgive it** — purely cord geometry + dwell; off-spot or still-swinging pins cause READ-B faults or mis-scores. Empirical tuning only.
3. **Settle times are guesses until measured** — post-impact and post-set damping for a 3.5 lb pin on ~80″ of nylon are assumptions; real numbers come off the rig.
4. **10 latches > 6 relays** — the controller's relay bank can't drive ten string-latch solenoids directly; rev-C needs a small (~$40) solenoid-driver bank (a clean reuse of the opto/driver cells, but a real interface gap to close).
5. **Ball rebound into the string curtain** and **hanging-pin false-triggering the cycle beam** — pit geometry must be tuned so deadwood and a rebounding ball stay out of the string zone and the trigger beam.

### The go / no-go gate (Subsystem 10)
- **Run:** 10,000 cycles on the bench / spare cabinet, instrumented (auto cycle-counter, jam log, camera as ground-truth pin-state, scheduled wear inspection).
- **Headline pass criterion:** **hard (unrecoverable, human-required) tangles < 1 per 200 frames.** That's a genuinely strong first-build result — commercial's <1/1000 would be moving the goalposts on a one-off prototype.
- **A clean pass licenses exactly one thing: building a *second* prototype lane.** It does **not** license 32 lanes, USBC certification, or a product — those need multi-lane soak, certification testing, and a real reliability program. This experiment answers one question: *did our own string mechanism, driven by our already-proven brain, survive one string-life interval reliably and safely enough to be worth building a second one?*

### What this confirms about the original question
The reuse thesis holds: the brain + camera transfer cleanly and the new board is a *simpler subset* of rev-B. And designing our own machine **deletes the worst part of Phase 8** — the 82-70 reverse-engineering, the C1/C2A probing, the mixed-fleet harness pain — because the machine is documented-by-construction. The hard part is, as predicted, **100% mechanical: tangle-free string management, repeatable on-spot landing, and durability at cycle count.** Nothing here is electronic.

---

## Top consolidated risk register
| # | Risk | Owner subsystem | The mitigation / what answers it |
|---|---|---|---|
| R1 | **Pit-slack string tangle** over 10k cycles (the #1 program risk) | §2 String mgmt | Detect-and-recover macro + camera; **quantified by the 10k test** (tangles/1000 frames) |
| R2 | **On-spot landing** drifts (no cup; cord stretch/creep) | §3 Lift, §4 Deck | Constant-force spools absorb creep; settle-dwell tuning; guide-tube funnels |
| R3 | **Latch-reliability** — a failed holdback drops a phantom standing pin | §2, §6 | READ-B catches it → re-cycle; latch wear is a logged test item |
| R4 | **Settle/cycle times unknown** until measured | §1, §7 | Camera motion-stable gate; sweep `SETTLE_S` over first few hundred cycles |
| R5 | **10 latch outputs > 6 relay channels** | §6 Electronics | Add a ~$40 solenoid-driver bank to rev-C (reuses opto/driver cells) |
| R6 | **Ball rebound / hanging-pin false-trigger** | §5 Ball | Friction (non-elastic) cushion + full pit-depth separation + low beam placement |
| R7 | **Motor inrush welds a relay** if a contactor isn't used | §5, §6 | Relay drives a contactor coil, never motor current directly (the rev-B pattern) |
| R8 | **Over-travel safety** — no cam feedback like rev-B had | §8 Safety | Wagon over-travel limit must be a **hardwired** cutout into the relay-enable rail, not just sensed |
| R9 | **Custom wagon-weldment fab cost** (loosest line, ~$200–600) | §9 BOM | Salvage 82-70 cabinet; DIY waterjet-from-stock vs. shop weldment |
| R10 | **Camera vs. swinging deadwood cords** in frame | §4, §7 | Joint frame-capture test; difference-from-empty baseline check |

## Resolve-first open questions (highest leverage)
1. **Is a scrap AMF 82-70 cabinet/deck available to salvage?** Swings the frame+deck buckets ±$300–500 — the single highest-leverage cost unknown. (WSL runs 82-70s + has a spare cabinet → likely yes.)
2. **Lift drive: motor-reversing belt (needs a DIR relay) vs. continuous-rotation crank/cam (single ENABLE)?** Decides a relay and simplifies the FSM. (§1/§3)
3. **Latch actuator: 10 solenoids + a driver bank, or a shared declutch?** Resolves the §2↔§6 interface gap and ~$40.
4. **Does the camera tolerate hanging-deadwood cords in frame?** A joint §4↔§7 frame-capture test before committing.
5. **BLDC vs. closed-loop NEMA-34 stepper for the lift** — saves ~$150–200 and simplifies the driver/safety-rail interface if a stepper is acceptable. (§3)
6. **Test policy:** auto-retry on READ-B mismatch, or always hard-fault-and-log? (Durability stats want zero auto-retry; play-mode wants retry.) (§7/§10)

---

## Contents (the ten subsystem designs)
1. Operating Principle & Full Cycle Sequence
2. String Management & Take-Up *(the make-or-break subsystem)*
3. Lift/Set Mechanism & On-Spot Landing
4. Pins, Strings-on-Pins & Deck/Spot Geometry
5. Ball Handling & Return
6. Control Electronics — rev-C Board Spec (the reuse mapping)
7. Detection, Scoring & the String-Setting FSM
8. Safety Architecture
9. Bill of Materials & Cost Estimate
10. Failure Modes (FMEA), Build Plan & the 10,000-Cycle Test

---


## Subsystem 1 — Operating Principle & Full Cycle Sequence

### 1. Operating thesis (one paragraph)

A string pinsetter does not *replace* pins onto the deck each shot — it **never lets them leave**. Each of the 10 pins is permanently tethered by a ~80 in nylon cord running up through a hole in its head to a take-up reel/latch in the carriage (Subsystem 2). The whole machine is a single vertical degree of freedom: a common-lift "string wagon" (Subsystem 3) rides up and down on rails. **All ten strings rise together; only the strings the FSM commands stay paid-out come back down to a spot.** A knocked pin is already hanging from its (now-slack-then-tensioned) string in the pit area; to "clear deadwood" you simply *hold it aloft* by keeping its reel wound. There is **no ball/pin separation, no spotting cup, no sweep, no respot table, no distributor, no shark/turret** — the four heaviest, most failure-prone subsystems of the AMF 82-70 are deleted outright. Detection is camera-based (Track A, given), so unlike a commercial string machine I do **not** need cord-tension load cells; the camera replaces them and is strictly more informative (it sees actual standing pins, not an inferred tension proxy). The cycle reduces to: *read which pins stand → lift everything → lower back the set that should stand → settle → ready.*

This is the spine. Everything the other nine agents build hangs off the **state list (§4)**, the **timing budget (§5)**, and the **transition event table (§7)** below.

### 2. Two cycle variants the spine must support

| | First-ball cycle (PARTIAL clear) | Spare/strike & end-of-frame (FULL re-rack) |
|---|---|---|
| Trigger | Ball-detect, then pins-at-rest | Same |
| Camera read | Yes — count knocked pins → score | Yes — confirm clear / score the spare |
| Strings lifted | **All 10** (common lift; can't lift a subset with one carriage) | All 10 |
| Strings lowered back | **Only the standing-pin set** (knocked pins held up = deadwood removed) | **All 10** to a fresh full rack |
| Pins on deck after | The standing pins, on-spot; deadwood hanging | Full fresh 10-pin triangle, on-spot |
| Frame logic | Stays in same frame, await 2nd ball | Advance frame, new rack |

The mechanical action is **identical** in both cases (lift all, lower a chosen subset); the *only* difference is **which reels are commanded to pay out** on the down-stroke. That is the key simplification — one motion primitive, two reel-selection masks.

### 3. Where the camera read happens (critical interface for Subsystem 7)

There are **two** camera reads per shot, and the agents must not conflate them:

- **READ-A "score read"** — happens **after pins settle from ball impact, BEFORE the lift starts.** This is the gameplay-meaningful frame: it yields the 10-bit standing mask that (a) scores the shot and (b) *becomes the reel-selection mask* for the partial down-stroke. This is the difference-from-empty detection that Track A already does.
- **READ-B "verify read"** — happens **after the down-stroke + settle, BEFORE returning to READY.** Confirms the commanded pins actually landed on-spot and standing. Mismatch → recovery (re-cycle / fault). This read is *new work the FSM agent must add*, but it's the same detector pointed at the same deck at a different time.

So the canonical order is: **ball → settle → READ-A (score + build mask) → lift → lower(mask) → settle → READ-B (verify) → READY.**

### 4. Machine states (hand these verbatim to the electronics rev-C and FSM agents)

```
S0  POWER_ON / SELF_TEST   – home the carriage, MCP23017/RP2040 handshake, watchdog armed, camera alive
S1  HOMING                 – drive carriage to top limit, zero the encoder
S2  READY                  – carriage at SET height, all standing pins on spot, awaiting ball. (idle resting state)
S3  BALL_PENDING           – ball detected at foul/ball sensor; pins in motion; arm settle timer
S4  PIN_SETTLE             – wait for pin motion to damp out before reading
S5  READ_A                 – camera grabs standing mask; compute score delta; decide PARTIAL vs FULL
S6  LIFT                   – carriage drives UP, all 10 reels take up, pins clear the deck
S7  SELECT                 – at top, latch reel mask (standing-set for partial / all-10 for full)
S8  LOWER                  – carriage drives DOWN; masked reels pay out cord, pins descend to spot
S9  SET_SETTLE             – dwell at SET height; let pins stop swinging, cords detension
S10 READ_B                 – camera verify; standing == commanded?  yes→S2 ; no→S11
S11 RECOVERY               – re-attempt (one re-lift/re-lower), bounded retries → S12 on fail
S12 FAULT / E-STOP         – safety rail open, motor disabled, call attendant; manual reset only
```

Notes for the FSM agent:
- **S2 READY is the home/rest state**, carriage parked at SET height (not at the top). Resting at SET means a knocked pin can't drift; the lift is a discrete event.
- S5 and S10 are the **only** states the camera is in the loop. Everywhere else the camera is free.
- **Strike** is just the FULL branch out of S5 where READ-A already shows mask = 0b0000000000 (all down) → go straight to FULL re-rack. **No special strike state needed** — strike, spare, and "open frame complete" all funnel into the same FULL re-rack (S6→S7(all)→S8→S9→S10), differing only in score bookkeeping handled in software, not mechanism.
- Foul: ball-detect with a foul-line crossing → score 0 for the ball but mechanically run the normal cycle.

### 5. Timing budget (per phase; bench target, not certified)

| Phase | State | Target time | What dominates it | Notes |
|---|---|---|---|---|
| Ball traverse + impact | S3 | ~1.5–2.5 s | physics (ball speed) | not machine-controlled; FSM just waits for "at rest" |
| Pin settle | S4 | 0.4–0.8 s | pin/string oscillation damping | tighten via camera motion-detect (read when frame delta stabilizes) instead of fixed timer |
| READ-A | S5 | 0.10–0.30 s | camera frame + diff compute | Track A already in this range |
| Lift stroke | S6 | 0.7–1.1 s | 0.9 m stroke at the BLDC's profiled speed | accel/cruise/decel of the string wagon |
| Select/latch | S7 | 0.05–0.15 s | reel-mask latch settle | electrical, fast |
| Lower stroke | S8 | 0.7–1.1 s | mirror of lift; controlled descent to spot | descent must be *gentle* at the end for on-spot landing |
| Set settle | S9 | 0.6–1.2 s | pins stop swinging + cords slacken | **the on-spot-quality dwell** — don't shortchange it |
| READ-B verify | S10 | 0.10–0.30 s | camera | reuse Track A |
| **Total machine-busy (S5→S10)** | | **≈ 3.0–4.3 s** | | matches the real-world "3–5 s reset" and Wikipedia's "~3 s lag" |

End-to-end from ball release to next READY ≈ **5–7 s**, of which only ~3–4 s is mechanism. This is in line with commercial string units (Brunswick/QubicaAMF quote a 3–5 s reset). For the **10k-cycle durability rig (Subsystem 10)** you can skip the ball-traverse wait and fire S5→S2 back-to-back at ~4 s/cycle → 10,000 cycles ≈ **11 hours of continuous run**, very feasible for an overnight-plus soak.

### 6. Why this cycle is dramatically simpler than the AMF 82-70 free-fall cycle

| AMF 82-70 free-fall does… | String machine does… | Consequence |
|---|---|---|
| Sweep/rake wipes deck of deadwood every ball | **Nothing** — deadwood hangs from its string | Delete the rake, sweep motor, sweep-position cam/switches |
| Spotting cup + respot table place pins into cups | **No cup** — pins land by cord geometry + settle dwell | Delete the entire respot table, table-up/table-down cam |
| Distributor/turret + shark sorts pins by orientation, fills cells | **Never** — pins never detach, so nothing to sort | Delete distributor, pin elevator's sorting, shark |
| Ball must be separated from pins in the pit and sent to return | Ball separated in pit, but pins **aren't down there to entangle** | Ball handling (Subsystem 5) gets *much* simpler — pins never co-mingle with the ball in a pit conveyor |
| Multi-cam timing chain (1st/2nd ball table cycles), many limit switches | **One linear axis**, two limit switches (top/SET) + one encoder | Vastly fewer sensors; FSM is ~12 states not the 82-70's dozens of cam-driven sub-states |
| Cushion/ball-cushion switch triggers the cycle | **Ball-detect (DIELL, already characterized) triggers** | Reuse existing read side; no cushion switch |

The mechanical complexity collapses from "many coordinated rotating cams + heavy reciprocating sweep + sorting machinery" to **"one carriage on rails + ten reels."** That is exactly why string machines are cited as cheaper/easier-maintenance (USBC), at the documented cost of a ~7% lower strike percentage (string drag) — acceptable for a proof-of-mechanism.

### 7. State-transition event/sensor table (the contract for Subsystems 6, 7, 8)

Each transition lists the **event** the FSM waits on and the **sensor/source** that provides it. This is what the electronics agent wires and the detection agent feeds.

| From → To | Trigger event | Sensor / source | Notes |
|---|---|---|---|
| S0→S1 | self-test pass | RP2040 handshake OK, watchdog kicking, camera heartbeat | safety rail must read all-clear |
| S1→S2 | carriage at top then settled at SET | **top limit switch** + **SET limit/encoder** | establishes home |
| S2→S3 | ball detected | **ball detector (DIELL, opto-in)** — existing | also the safety interlock per memory |
| S3→S4 | ball past pins / impact done | same ball sensor de-assert + short delay, or impact heuristic | arm settle timer |
| S4→S5 | pin motion damped | **camera motion-stable** (inter-frame delta < threshold) or fixed 0.6 s timeout | adaptive read beats fixed dwell |
| S5→S6 | READ-A complete, mask computed | **camera (Track A standing mask)** | mask also decides PARTIAL vs FULL and is logged for score |
| S6→S7 | carriage reached top | **top limit switch** + encoder target | hard limit + soft encoder limit (redundant for safety) |
| S7→S8 | reel mask latched | MCP23017 reel-select outputs confirmed (RP2040 echo) | partial = standing set; full = all 10 |
| S8→S9 | carriage reached SET height | **SET limit switch** + encoder | end-of-travel must be speed-limited for soft landing |
| S9→S10 | dwell elapsed / pins stable | settle timer **or** camera motion-stable | quality gate for on-spot |
| S10→S2 | READ-B verify OK (standing == commanded) | **camera** | normal completion → READY |
| S10→S11 | READ-B mismatch | **camera** | e.g., a pin failed to seat / cord snag |
| S11→S6 | retry within budget | retry counter < N (N≈1–2) | one bounded re-cycle attempt |
| S11→S12 | retries exhausted | retry counter ≥ N | hard fault |
| any→S12 | watchdog timeout OR safety rail open OR over-travel OR estop button | **NE555 watchdog / 6-condition safety rail / over-travel limit / E-stop** (Subsystem 8) | non-bypassable; motor de-energized |
| S12→S0 | manual reset | attendant key/button | never auto-clears |

**Minimum sensor set the spine requires** (so the electronics agent can size the rev-C channel mix): 1× ball detector (existing DIELL/opto), 1× top limit, 1× SET-height limit, 1× over-travel limit (safety), 1× carriage encoder (lift/lower position + soft limits), 1× E-stop, the camera (READ-A/READ-B over the existing pipeline), and the watchdog/safety-rail already designed in Subsystem 8. **No per-pin sensors** are needed (the camera subsumes the 10 cord-tension channels a commercial unit would use) — a meaningful channel-count saving for the rev-C board.

### 8. Interfaces I'm explicitly handing off (so I don't redesign others' subsystems)
- **To Subsystem 2 (strings/take-up):** I require a per-string *paid-out vs held* latch addressable by a 10-bit mask, settable during S7, and a known cord slack budget (commercial spec is ≥65 in slack; I assume ~80 in cord) so pins can swing without cross-pulling. The "which reels pay out" decision is mine (the mask); the *how* is theirs.
- **To Subsystem 3 (lift):** I require the carriage to expose **top limit, SET limit, over-travel limit, and an encoder**, and to accept a "go up / go down with end-of-travel speed-limit" command. The motion profile (accel/decel for soft on-spot landing in S8/S9) is theirs.
- **To Subsystem 5 (ball return):** the cycle does **not** gate on ball-return completion (ball clears the pit independently); I only consume the **ball-detect** event. If their up-lane return needs a "safe to fire ball" interlock, expose it and I'll add a guard on S2→S3.
- **To Subsystem 7 (detection/FSM):** the state list (§4) and transition table (§7) are the FSM skeleton; READ-A builds the mask + score, READ-B verifies. I'm asserting the **two-read** model — please implement both, not one.

### Risks
- **Common-lift can only lift ALL pins, never a subset** — so "partial clear" is achieved entirely by *selective lower (reel mask)*, not selective lift. If a held (deadwood) reel fails to hold and a knocked pin descends, it lands as a phantom standing pin. READ-B catches it but the recovery is a full re-cycle (cost: ~4 s + a scoring-correction path). Whole cycle correctness leans on reel-latch reliability (Subsystem 2).
- **On-spot landing has no cup to forgive it** — landing accuracy is purely cord geometry + the S9 settle dwell. If pins land off-spot or still swinging, READ-B may false-fault or the next shot is mis-scored. The S9 dwell is the only knob; too short = bad sets, too long = slow cycle. Needs empirical tuning on the bench (flag for Subsystem 10's test plan).
- **Settle-time is a guess until measured** — S4 (post-impact) and S9 (post-set) damping times for a 3.5 lb pin on ~80 in of nylon are assumptions. Camera motion-stable detection mitigates fixed-timer error but adds latency variance. Real numbers only come off the rig.
- **String tangle over 10k cycles is out-of-scope here but lands in MY cycle as a READ-B mismatch storm** — i.e., the #1 program risk surfaces *through* my state machine. The FSM's recovery/fault bounds (N retries → FAULT) are the only software defense; the real fix is mechanical (Subsystems 2/4). I've made tangle a *detectable, fault-stopping* event rather than a silent mis-set.
- **READ-A timing window vs. pin "dead bounce"** — a pin can be knocked, bounce, and re-stand (or a standing pin can be clipped and fall *after* READ-A). Reading too early mis-scores. Commercial units re-sample the 20–80% tension band after 200–300 ms; I replicate that with the camera motion-stable gate, but rapid post-read settling is a known false-read source.

### Open questions
- **Do we need an independent "ball at rest / pins at rest" sensor, or is camera-motion-stable sufficient to leave S4?** Using the camera for both the settle-gate and the read couples two functions onto one sensor — acceptable for a prototype, but the electronics agent may want a cheap redundant motion cue (e.g., a pit microphone or accelerometer on the deck) to disambiguate "ball still moving" from "pins still swinging."
- **What is the real lift/lower stroke time** at the chosen BLDC profile (Subsystem 3 says 0.9 m, ~250–400 W)? My 0.7–1.1 s/stroke is an estimate; the total cycle and the 10k-soak duration scale directly off it.
- **Should READ-B failures auto-retry or always hard-fault?** I defaulted to N=1–2 bounded retries → FAULT. For a durability experiment you may *want* zero auto-retry (every mismatch logged + stop) to get clean tangle/mis-set statistics. This is a test-mode vs. play-mode policy switch for the FSM agent and Subsystem 10.
- **Frame/score logic ownership:** I keep frame advancement in software (the mechanism is identical for strike/spare/open). Confirm with Subsystem 7 that READ-A's mask is the single source of truth for scoring and that no separate "ball count" sensor is desired.
- **Is there a "garbage shot" mode** (e.g., a pin knocked off its string, or a thrown gutter that hits nothing) that should bypass the lift entirely to save wear? Worth a fast-path S5→S2 when READ-A shows no change AND it's the first ball — but that risks skipping a needed clear. Defer decision to bench observation.

Sources: [QubicaAMF EDGE String](https://www.qubicaamfbowling.com/products/pinspotters/edge-string), [Brunswick StringPin Operations Manual](https://brunswickbowling.nyc3.cdn.digitaloceanspaces.com/production/document-library/Operation-Manuals-User-Guides/Pinsetters/StringPin/Operations_Manual_StringPinV2_55-900004-000_En_Rev-08-19-21.pdf), [Pinsetter — Wikipedia](https://en.wikipedia.org/wiki/Pinsetter), [How a string pinsetter works — Flying Bowling](https://www.flyingbowling.com/article/how-does-a-bowling-string-pinsetter-machine-work.html), [US Bowling string pinsetters](https://usbowling.com/string-pinsetters/).

---

## Subsystem 2 — String Management & Take-Up

**Mandate:** Anchor 10 strings to the pins, route them up, guide them, and take them up / pay them out over 10,000+ cycles **without tangling** — the documented #1 failure mode of every string machine. Subsystem 3 (lift) committed to a **common-lift "string wagon"** that raises all ten strings together and **delegates per-pin "lift vs. set" selection into this subsystem** via a per-string latch/holdback. So I own three things: (1) the string + anchor + routing, (2) the **per-string holdback** that makes a common lift behave selectively, and (3) the **overhead guide-tube geometry** that re-centers each pin on-spot on descent — plus the explicit anti-tangle strategy that ties it all together.

### What the real machines actually do (grounded findings, flagged)

I pulled these from the Brunswick *StringPin* service manual, the QubicaAMF *EDGE String* product pages, US Bowling's Q&A, and the USBC string FAQ — flagged inline:

- **Per-pin string, very long.** Brunswick spec is **16′5″ (5004 mm) of string attached to each pin** [Brunswick StringPin service manual]. USBC certification requires **≥54″ of *unobstructed slack*** below the deck during play; US Bowling cites **≥65″ slack** [USBC FAQ; US Bowling Q&A]. The 5 m total = slack hanging in the pit + the run up to the take-up + winding allowance.
- **Per-pin take-up "spools," not one common drum.** Brunswick routes **spool → string wagon → Pin Motion Interface → setting platform → pin**, with a *separate spool per pin* and a shared lift carriage [Brunswick service manual]. This is the architecture Subsystem 3 already mirrors (common wagon + per-string device). QubicaAMF EDGE uses a **reel arm assembly + string comb + string tray** to keep strings parted and stored [QubicaAMF EDGE].
- **On-spot centering is mechanical, by cones.** Brunswick's setting platform carries **"Pin Centering Cones"** that catch the rising/descending pin and *"stabilize and position them perpendicular to the pindeck so they can be set vertically"* [Brunswick service manual]. **No spotting cup** is needed — exactly what Subsystem 3 assumed. The cord geometry + a funnel does the centering.
- **String separation by routing.** Brunswick physically segregates the bundle: *"strings for pins 4-6 and 7-10 go over the limiting bar; strings for 1-3 route under the limiting bar."* The deck triangle is fanned out at the take-up so neighbors don't share airspace [Brunswick service manual].
- **Tangle handling is reactive, not preventive.** Brunswick uses a **de-tangling bar**: when strings tangle, the lift **motor stalls/over-torques**, the controller **shuts the motor, lowers the pins partially, then re-retracts** to shake the tangle out [Brunswick service manual]. EDGE's marketing claim is "adaptive string length" + tall pin shield, but the underlying recovery is the same stall-detect-and-jog. **This is the key insight: nobody has *eliminated* tangle — they *detect and recover* from it.** My design must do both: minimize *and* recover.
- **Tension is set by pin rest-lift, not a gauge.** Brunswick sets spool tension so the pin's at-rest **travel/lift is ~1–3 mm + 2 mm** off the deck [Brunswick service manual] — i.e., the string is just barely snug, pin essentially weight-on-deck.
- **String is coated/bonded nylon; replace on wear.** "Bonded string coatings function as lubricants to prevent snags"; biweekly wear inspection, replace on fray/discoloration, with a volume-based rule of **~every 10,000 frames** floated in the trade press [US Bowling Q&A; Flying Bowling]. Diameter/material is *not* published by USBC ("only string material from the original design") — **FLAG: exact OEM cord spec is proprietary; I spec a defensible equivalent below.**

### Architecture decision: hybrid (b)+(c)+(d) — per-pin constant-tension spool, guided through a per-pin tube, with mechanical lift-bar pickup

I evaluated the four candidate architectures against *our* constraint (Subsystem 3 already chose a common-lift wagon, so I must put selection in the take-up):

| Architecture | On-spot accuracy | Anti-tangle | Selective lift? | Verdict |
|---|---|---|---|---|
| (a) Common lift-bar / string curtain only | Poor — pins swing | Poor — strings share airspace | No (lifts all) | Reject as sole approach |
| (b) Per-pin powered take-up reel/spool | Good | Medium | Yes (per-reel motor) | 10 motors = cost/complexity; reject |
| (c) Guided tube/conduit per string | Excellent (tube = funnel) | **Excellent** (strings never touch) | No by itself | **Adopt the tubes** |
| (d) Hybrid | **Best** | **Best** | Yes | **ADOPT** |

**Chosen design** = a **per-pin spring-loaded constant-tension spool (continuous take-up)** + a **per-pin rigid guide tube from the spool down through the deck masking to ~6″ above each spot** (the anti-tangle backbone — each string is *physically isolated* in its own conduit for the whole powered length) + a **shared lift-bar on the Subsystem-3 wagon that engages a per-string "button/ferrule" stop**, with the **per-string holdback = a solenoid pinch latch on the tube exit** that decides whether that pin rides up with the wagon or stays seated.

The spool's only job is to **keep slack out of the system continuously** (so a hanging deadwood pin never feeds loose loops back into the airspace — *loose loops are what tangle*). The **wagon does the lifting work**; the **spool does the housekeeping**. This split is exactly why I don't need 10 lift motors.

#### How a cycle works (interface with Subsystem 7 FSM + Subsystem 3 wagon)

1. **At rest:** each pin sits on its spot; spool holds ~1–3 mm of pre-tension (matches Brunswick's rest spec). String runs pin → tube → over a **button ferrule** crimped on the string ~at the tube top → onto the spool.
2. **Detection** (Subsystem 7 camera) yields the 10-bit standing mask.
3. **Sweep/clear phase:** Subsystem 7 commands a **full lift**. All ten **solenoid pinch latches release**; the **wagon rises 0.9 m**, its lift-bar catching every button ferrule → all ten pins lift clear (deadwood hangs from its own string the whole time — never free-falls). Spools pay out under the wagon, staying taut.
4. **Selective set:** for the *re-spot* stroke, the FSM energizes the **pinch latch on every pin that should NOT be re-set** (i.e., pins that were knocked down and shouldn't return on a 2nd-ball spot). A latched string is **clamped at the tube exit**, so when the wagon descends that pin **stays aloft** (held by the clamp) instead of riding the bar down. Unlatched pins ride the wagon's bar down, the **centering cone/funnel at the tube mouth** aligns them, and they **land on-spot**; a **settle dwell** (Subsystem 1 timing) lets the cord plumb them vertical before the bar releases.
5. **Spool re-tensions** to rest. Pinch latches release for the next ball. Tangle watchdog (below) runs throughout.

> Interface note to Subsystem 3: your wagon needs a **lift-bar with 10 capture slots** (one per string button ferrule) on its underside, and it must tolerate **my pinch-latch clamp loads (~30–40 N hold)** at the tube exits without binding the rails. I'm specifying the ferrule + slot; you own the bar's structure.

### String, anchor, and routing — concrete spec

- **Cord:** **1/8″ (3.2 mm) solid-braid bonded nylon**, polyurethane-coated for low-friction/anti-snag (mirrors OEM "bonded coating"). Solid-braid (not hollow/diamond-braid) resists kinking and the abrasion of repeated tube passes. **FLAG:** I'm matching published *behavior* (coated nylon, ~54–65″ slack) since OEM exact denier/coating is proprietary; first-article testing must confirm tube-friction and stretch (USBC cares about "stretch and length").
- **Length per pin:** **16′ (≈4.9 m)** to match Brunswick's proven slack-plus-feed budget; trims to ≥54″ free slack at the pit per USBC.
- **Pin anchor:** drill the existing AMF/Vulcan pin head per USBC's minimal-wood hole, pass cord through, **figure-eight stopper knot + crimped aluminum ferrule** below the head, then **re-introduce head weight** (epoxy/lead-free slug) to keep the pin legal at ~3 lb 6 oz and balanced [USBC: "weight re-introduced into the head"]. Knot choice: figure-eight (not overhand) — it doesn't slip-tighten under 255 N shock loads and is re-tieable by a mechanic.
- **Upper terminator:** **swaged button ferrule** at the tube top = the feature the wagon lift-bar catches and the pinch latch clamps against. Stainless, ~10 mm OD.
- **Routing/separation:** strings **fan out** from the deck triangle to the spool bank so adjacent pins' strings diverge immediately (Brunswick's over/under-the-limiting-bar trick, generalized). **No two strings ever share a tube or an air gap inside the powered envelope.** This is the single most important anti-tangle move.

### The per-pin guide tube + centering cone (on-spot geometry)

- **Tube:** **UHMW-PE or PTFE-lined aluminum tube, 12 mm ID**, one per pin, running from the spool down through the deck masking to a mouth **~150 mm above the pin spot**. UHMW gives a self-lubricating, ~0.1–0.2 µ bore so the coated cord slides for 10k cycles without glazing.
- **Mouth = centering cone:** the tube's lower 60 mm flares to a **45–50 mm funnel** that is the **on-spot centering cone** — the descending pin's neck enters the funnel and is walked to spot center; tube center is jig-aligned to the **regulation 12″ spot grid**. This is precisely Brunswick's "Pin Centering Cone" function, relocated to the tube exit so the *tube* both guides the string and spots the pin (one part, two jobs). Spot accuracy target **±3 mm**, set by the funnel taper + settle dwell.
- **Why this kills tangle:** for the entire length where the string is moving under power, it is **inside a smooth straight conduit** — it cannot wrap a neighbor, cannot loop on itself, cannot catch a hanging pin. Tangle can only occur in the **free pit slack below the deck**, which is unavoidable (the pins must be free to fall) but is exactly where the camera + watchdog can see/recover it.

### Take-up (constant-tension spool) — concrete spec

- **Spool unit (×10):** **constant-force spring spool** (clock-spring / negator-spring drum) sized for **~4 N continuous take-up, 4.9 m capacity**. Constant-force (not a torsion spring) keeps tension flat across the whole 0.9 m wagon stroke so the pin lift force is uniform top-to-bottom. Drum ID sized so 4.9 m of 3.2 mm cord winds in ≤30 wraps (avoid cord-on-cord pinch). **Alternative considered:** small powered take-up motor per pin (true architecture (b)) — rejected for the prototype as 10× cost/wiring with no anti-tangle benefit over a constant-force spring; revisit only if "adaptive string length" (paying out *more* slack for kids' balls, per EDGE) becomes a requirement.
- **Tension calibration:** trim spring or add a **friction-brake thumbwheel** per spool to hit the **1–3 mm rest-lift** Brunswick spec.

### Per-string holdback (the selection element Subsystem 3 punted to me)

I evaluated three holdback mechanisms:

| Mechanism | Hold force | Cycle life | Cost | Verdict |
|---|---|---|---|---|
| **Solenoid pinch (cam-clamp on cord at tube exit)** | 30–40 N | >10⁶ | $9 ea | **ADOPT** — simple, fail-safe-open, clamps the cord not a gear |
| Sprag/one-way clutch on spool | N/A (one-way only) | high | $15 ea | Reject — can't *release* selectively on command |
| Friction clutch on spool shaft | variable | medium (glazes) | $20 ea | Reject — heat + drift over 10k cycles |

**Chosen: a 12 V pull-type solenoid driving a rubber-faced pinch cam** that clamps the cord against an anvil at each tube exit. **De-energized = open (pin free to ride wagon)**, energized = clamped (pin held aloft / left down). Fail-safe direction is correct: a power loss drops all clamps → all pins are free → wagon can lower everything to a safe seated state (aligns with Subsystem 8's safety rail). Each solenoid is one **G5LE relay-driven dry-contact channel** on the rev-C board (Subsystem 6) — 10 channels, well within the 3× MCP23017 budget. Pinching the *cord* (compliant) not a *spool gear* avoids shock-loading a drivetrain and tolerates the cord's coating.

> **FLAG / tradeoff:** clamping a moving-then-static cord at 30–40 N for thousands of cycles will **locally abrade the coating** at the clamp zone. Mitigations: rubber (not metal) clamp face, clamp only on the **static ferrule shoulder** when possible (clamp the button, not bare cord), and make the clamp zone part of the inspection checklist. First-article 1,000-cycle test must measure coating wear at the clamp before committing to the 10k run.

### Anti-tangle strategy (explicit — the make-or-break section)

Layered, because no single measure is sufficient (the OEMs prove this):

1. **Isolation (primary):** every string in its own straight conduit for the entire powered length. Strings physically cannot interact where they move fastest. (Covers ~90% of OEM tangle modes, which happen at the take-up bundle.)
2. **Continuous tension:** constant-force spool removes slack the instant a pin rises, so **no loose loops** form in the airspace. Loose loop = tangle precursor.
3. **Fan-out routing + limiting-bar separation** at the deck so the triangle's strings diverge immediately (Brunswick's proven trick).
4. **Detect-and-recover (the safety net, mirrors Brunswick's de-tangling bar):** the **wagon lift motor is current-sensed** (Subsystem 6 already has the means). A tangle shows up as **over-torque / position-vs-expected mismatch**. On trip, the FSM (Subsystem 7) runs a **jog-recovery macro**: stop, lower pins ~30–50% to slacken, brief reverse-and-re-lift to shake the cross, retry up to N times, then flag the lane for attention. This is exactly the OEM behavior and is **free** given our existing current-sense + camera.
5. **Camera cross-check:** Subsystem 7's overhead camera already sees the deck; a *standing-mask that disagrees with commanded lift* (e.g., a pin that should be up is down, or two pins moved together) is a software tangle flag that can pre-empt the mechanical stall.
6. **Wear management:** coated cord + UHMW tube + scheduled replacement at **~10k frames** (the trade rule) — frayed cord is the other tangle source. Inspection checklist: fray, clamp-zone wear, knot integrity, spool wrap count.

### Parts table (per single lane / 10 strings)

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Bonded nylon cord | 1/8″ (3.2 mm) solid-braid, PU-coated | ~52 m (10×4.9 m + spares) | $35 | OEM-equivalent; ~$0.65/m; FLAG exact spec proprietary |
| Pin head anchor kit | drill + figure-8 knot + Al crimp ferrule + lead-free reweight slug | 10 sets | $30 | Reweight to keep pin legal ~3 lb 6 oz |
| Upper button ferrule | stainless swaged, ~10 mm OD | 10 | $12 | Lift-bar catch + clamp shoulder |
| Per-pin guide tube | UHMW-PE-lined Al, 12 mm ID, ~1.2 m, flared 45–50 mm mouth | 10 | $90 | Funnel mouth = on-spot centering cone, ±3 mm |
| Constant-force spool | clock/negator-spring drum, ~4 N, 4.9 m cap, friction trim | 10 | $180 | $18 ea; flat tension over 0.9 m stroke |
| Solenoid pinch latch | 12 V pull solenoid + rubber cam + anvil, fail-open | 10 | $90 | Per-string holdback = selection element |
| Pinch-latch mount/anvil block | machined Al, jig-located to 12″ spot grid | 1 set (10 stations) | $70 | Also locates tube mouths on-spot |
| Spool bank frame + fan-out routing | Al extrusion, string comb/separators (limiting-bar analog) | 1 | $110 | Keeps strings parted at take-up |
| Current-sense for lift motor | shunt + amp on wagon BLDC (tangle detect) | 1 | $15 | Likely shared w/ Subsystem 3/6 |
| Fasteners / cable / spares | — | — | $40 | — |
| **Subsystem 2 total (1 lane)** | | | **≈ $672** | Holdback solenoids + spools dominate |

(Solenoid relay channels, MCP23017 I/O, and motor driver are **Subsystem 6** scope; the lift motor/wagon/rails are **Subsystem 3** — excluded here to avoid double-counting.)

### Risks
- **Clamp-zone cord abrasion (highest):** repeatedly pinching the moving cord at 30–40 N will glaze/abrade the PU coating locally and shorten cord life or seed fraying → tangle. Mitigation: clamp the static button ferrule not bare cord, rubber face, inspection item; **first-article 1k-cycle wear test is a go/no-go gate**.
- **On-spot accuracy degrades with cord stretch/relax:** coated nylon creeps; after thousands of cycles the rest-lift drifts and pins may land off-spot or lean. Mitigation: constant-force spool absorbs creep; periodic re-tension via friction thumbwheel; USBC explicitly regulates "stretch" so this is also a certification-adjacent risk (we're uncertified, but it predicts real behavior).
- **Pit-slack tangle is *not* eliminated, only recovered:** the free 54–65″ of slack below the deck is where deadwood-on-deadwood crossing still happens (worse with slow/kids' balls, per US Bowling). Our isolation tubes don't reach there. Mitigation: detect-and-recover macro + camera; accept some recovery jogs. **This is the residual #1 risk that 10k-cycle testing must quantify (tangles per 1000 frames).**
- **10 solenoids energized = heat + current:** holding clamps through a full set/clear adds thermal and supply load. Mitigation: latch only during the short descent window, not continuously; size the isolated field-wetting supply (Subsystem 6) accordingly.
- **Constant-force spring fatigue:** clock springs have finite cycle life; 10k cycles × full payout may approach spring fatigue limits. Mitigation: spec spring rated ≥50k cycles; the spool is a wear part on the maintenance schedule.
- **Knot/ferrule pull-out under 255 N shock:** a struck pin yanks the anchor hard. Mitigation: figure-8 + crimp (not overhand); proof-test each anchor to 2× design load at build.

### Open questions
- **Exact OEM cord spec** (denier, coating chemistry, stretch %) is proprietary/unpublished — **need first-article friction + stretch testing** to confirm our 1/8″ PU-coated nylon behaves in-tube and holds USBC-like slack geometry. (Flagged: pulled "≥54″ slack / coated / ~10k-frame replacement" from USBC + US Bowling, not a parts spec.)
- **Does Subsystem 3's wagon stroke (0.9 m) actually clear a hung deadwood pin** plus its slack without the pit slack snagging the wagon? Need the pit-depth geometry from Subsystem 1/5 to confirm tube-mouth height (I assumed 150 mm) and total slack budget.
- **Clamp on cord vs. on button ferrule:** can the wagon timing guarantee the button is always at the clamp anvil when we need to hold? If not, we clamp bare cord and the abrasion risk rises — **a timing/geometry question for Subsystem 3 + 7's FSM.**
- **Adaptive string length** (EDGE's two-length trick for different play styles) — do we need *variable* slack for our prototype, or is fixed-length acceptable for a proof-of-mechanism? Fixed is far simpler; recommend deferring variable payout unless scoring fidelity demands it.
- **Spool friction-brake drift over 10k cycles** — does the rest-lift tension stay in the 1–3 mm band, or do we need a closed-loop tensioner? Answerable only on the bench during the durability run.
- **Recovery-jog success rate** — how often does the Brunswick-style lower-and-reshake actually clear a tangle vs. requiring a human? This number (recoverable vs. hard tangles per 1000 frames) is **the headline metric of the 10k-cycle test** and the real verdict on whether the whole string approach is viable for us.

**Sources:** [Brunswick StringPin Service Manual (ManualsLib)](https://www.manualslib.com/manual/1834268/Brunswick-Stringpin.html) · [Brunswick StringPin Service Manual PDF](https://brunswickbowling.com/uploads/document-library/Service-Manuals/Pinsetters/StringPin/55-900001-SES-String-Pinsetter-Service-2014-and-Prior-Rev-8-14.pdf) · [QubicaAMF EDGE String](https://www.qubicaamfbowling.com/products/pinspotters/edge-string) · [US Bowling — String Pinsetter Q&A](https://usbowling.com/articles/string-pinsetter-q-a/) · [USBC String Pinsetter FAQ](https://bowl.com/getmedia/a8870899-6739-4d7b-b863-983c6aa0cc01/110923_string-pinsetter-faq.pdf) · [Flying Bowling — anti-tangle maintenance](https://www.flyingbowling.com/how-to-make-a-string-pinsetter-not-get-tangled-flying.html) · [Hackaday — string bowling overview](https://hackaday.com/2023/11/28/bowling-with-strings-attached-the-people-are-split/)

---

## Subsystem 3 — Lift / Set Mechanism & On-Spot Landing

### 0. The problem statement, sharpened

After every ball this subsystem must: **(a) raise all ten pin-strings enough to clear standing and fallen pins off the deck, (b) re-lower only the subset that should stand, and (c) land each lowered pin on its 12-inch-spaced regulation spot, repeatably, every cycle, for 10,000 cycles.** The hard, non-negotiable requirement is **(c) — on-spot landing.** USBC/IBF sanction tolerances put a pin within roughly **±0.5 in (±12.7 mm)** of true spot; the proto target is tighter, **≤ ±6 mm radial typical / ±10 mm worst-case**, so we have margin against drift and string stretch.

Two facts from how real string machines actually do this (web-grounded, see flags) shaped every decision below:

1. **Modern string pinsetters use NO spotting cup or funnel.** Brunswick StringPin and QubicaAMF EDGE String land pins to ~±2 mm purely by **cord geometry** — each cord's free length and the angle of its overhead guide tube are calibrated so the pin, lowered on a near-vertical string, arrives on-spot, then a short **settle dwell** lets it stop swinging. The free-fall AMF-82-70 "spotting table with gripper cups + spotting fingers" model (what the existing Phase 8 board controls) is **abandoned** for a string machine.
2. **There are two viable drive architectures**, and they differ mainly in *where pin-selection happens*:
   - **Common-lift "string wagon"** (Brunswick StringPin lineage): **one** motor pulls a carriage/drawbar that lifts **all ten strings together** via a V-belt / lead screw; per-pin "lift vs. set" is decided **downstream in the string take-up (Subsystem 2)**, not by the lift motor.
   - **Ten individual reels** (QubicaAMF EDGE lineage): **ten** independent reel-arm/spool assemblies, each its own small motor; "lift all / set subset" is just "command the ten reels independently." Selection lives in the actuator.

I scope **both** and **recommend the common-lift wagon as the PROTOTYPE primary** (simplest to build, one safety-supervised motor, cleanest reuse of the existing S/T contactor-command pattern), with the **ten-reel design as the documented alternative** for a future fidelity/throughput upgrade. The two share the same landing mechanism (Section 4) and the same FSM contract (interfaces).

---

### 1. Recommended primary: the common-lift "string wagon"

#### 1.1 Mechanism

A horizontal **lift carriage** ("wagon") rides on two parallel linear rails above the pin deck, ~1.0–1.2 m above lane level (clear of the highest standing-pin path plus deadwood hang). All ten pin-strings rise from the deck, pass up through a fixed **string comb / guide-tube array** (Subsystem 2's domain — defines the exit geometry that does the centering), then route over the carriage. When the carriage travels up its stroke it **takes up all ten strings simultaneously**, hoisting every pin clear of the deck. When it travels back down it **pays the strings back out**, and gravity drops the pins back through their guide tubes to the deck.

The "lower only the standing subset" trick in this architecture is **NOT done by the wagon** — the wagon always lifts and lowers all ten. Selection is realized in Subsystem 2 by a **per-string holdback** (a small solenoid-actuated pinch/clutch or a sprag on each string spool): strings whose pins should be *removed from play this cycle* (deadwood, or all ten on a fresh-rack reset before re-set) are **latched at the top** so their pins stay aloft; strings whose pins should **stand** are **released to pay out** as the wagon descends. This is the explicit interface to Subsystem 2 — I define the *requirement* (ten independently latchable strings, latch state set before the wagon descends) and let Subsystem 2 pick the holdback mechanism.

> Why put selection in the string take-up rather than the lift? Because it lets the lift be a **single rugged actuator** — far easier to make survive 10k cycles and far cleaner to safety-supervise (one motor = one existing-style contactor-command relay) than ten coordinated drives. It mirrors the Brunswick "one 3-phase motor + string-wagon drive gear and shaft" design, which is the field-proven low-part-count approach (~40–60 moving parts vs. 150–200 for free-fall).

#### 1.2 Drive options & the pick

| Option | Drive | Pros | Cons | Verdict |
|---|---|---|---|---|
| **A. Timing-belt carriage** | NEMA-34 stepper **or** 250–400 W BLDC gearmotor → HTD-5M / GT3 belt → carriage | Fast (sub-1 s lift), back-drivable check, cheap belt, easy to instrument | Belt stretch/creep over 10k cycles; needs tensioner | **PRIMARY for proto** |
| **B. Lead/ball screw carriage** | NEMA-34 stepper → 12–16 mm ball screw, 10 mm lead | Rigid, precise, holds position un-powered (if leadscrew) | Slower at safe RPM, screw whip at length, costlier | Strong #2; pick if belt creep bites |
| **C. Pneumatic lift** | Air cylinder + flow control | Simple, strong, inherently compliant | No mid-stroke position control, needs compressor, AMF centers rarely have shop air at the lane | Rejected for proto |

**Pick: Option A, timing-belt carriage driven by a ~250–400 W BLDC gearmotor with an integral incremental encoder** (or a closed-loop NEMA-34 if we want step/dir simplicity). Rationale: a belt carriage gives us the **smooth, controlled, non-snap descent** the OEM manuals stress (to prevent cord whip and pin swing), it's trivially instrumented with the encoder for the FSM's position feedback, and a gearmotor with a worm or high-ratio stage gives us **static load-holding** (the wagon won't back-drive and drop ten pins if power is cut mid-lift — important for the fail-safe story in Subsystem 8).

#### 1.3 Force / stroke / speed (computed)

| Quantity | Value | Basis |
|---|---|---|
| Pin weight | **15.6 N** each (3.5 lb = 1.588 kg × 9.81) | given |
| Static 10-pin load | **156 N** (~35 lbf) | 10 × 15.6 |
| Dynamic 10-pin load (a = 3 m/s²) | **203 N** (~46 lbf) | 10 × m(g+a) |
| + guide-tube/string friction margin (25 %) | **≈ 255 N (~57 lbf) design load** | engineering margin |
| Lift stroke | **0.9 m** (≈ 35 in) | clear pin + deadwood hang |
| Lift time (target) | **0.8 s up, 0.8 s down** | within the ~3–5 s OEM reset budget, leaving time for settle |
| Carriage speed (coast) | **≈ 1.1 m/s** | 0.9 m trapezoidal in 0.8 s |
| **Drive pulley** | 40 mm pitch dia → **5.1 N·m** pulley torque, **≈ 540 rpm**, **≈ 290 W peak** | T = F·r; P = T·ω |
| Continuous duty | ~30–40 % (lift only during reset) | duty-cycle motor sizing |

A **250–400 W BLDC gearmotor** covers the ~290 W mechanical peak with margin; a closed-loop NEMA-34 (≈ 4–8 N·m holding) belt-reduced 2:1 is an equivalent stepper path. The design load of 255 N is comfortably inside both.

> **Open question — counterbalance.** A constant-force spring or counterweight sized to ~120–150 N (about half the static load) would roughly halve motor torque and make the *un-powered* state lean toward "pins gently lowered" rather than "pins crash." Worth prototyping; flagged.

---

### 2. Documented alternative: ten individual reel-arm assemblies

This is the QubicaAMF EDGE String topology and the **natural fit for the existing control stack's relay model** — so it's worth fully specifying as the upgrade path.

Each pin gets its own **reel** (a grooved spool, ~30 mm drum dia) on a short **reel arm**, driven by a small geared motor (NEMA-17 + planetary, or a 12/24 V BLDC gearmotor), with the string spooling on/off as the reel turns. A **spring-loaded tension lever** on each spool (exactly the EDGE "String Spool on a spring-loaded Tension Lever") keeps the cord from over-stretching on lift and provides the slack-vs-taut state that doubles as **string-tension pin-sensing** (Subsystem 7's optional secondary detector). Per-pin force is tiny:

| Quantity | Per-reel value |
|---|---|
| Dynamic load (1 pin, a = 3) | **20.3 N** |
| Drum radius | 15 mm |
| **Reel torque** | **≈ 0.31 N·m** (trivial — NEMA-17-class) |
| Lift revs (0.9 m / 94 mm circ) | **≈ 9.6 rev** |
| Reel speed | **≈ 720 rpm** |

**Why it's elegant but deferred:** "lift all / set subset" becomes pure software — turn the chosen reels' motors. It folds lift + selection into one subsystem and removes the per-string holdback clutch from Subsystem 2 entirely. **But** it is **ten precision drives to build, wire, tune, and keep in sync** instead of one, ten times the motor BOM, and ten times the failure surface for a 10k-cycle test. For a *proof-of-mechanism* prototype the common wagon wins; for a *product* the ten-reel design is the right answer and I recommend re-evaluating at the 32-lane decision point.

> **Control-stack note:** the ten-reel design maps cleanly to **10 rev-C relay channels** (one "reel run" command per pin) plus the existing safety rail — see interfaces. The common-wagon design uses **1 motor-run channel + a "selection latch" bus** to Subsystem 2.

---

### 3. How "lift all / lower subset" maps to the cycle (both architectures)

Mechanical sequence the FSM drives (Subsystem 7 owns the state machine; this is the lift/set choreography it commands):

1. **Ball detected** (DIELL, existing) → Track A camera already has the post-ball standing mask.
2. **Latch selection** (wagon: set per-string holdbacks; reel: arm the chosen reels).
3. **LIFT** — wagon ascends / reels wind. All in-play and deadwood strings rise; pins clear the deck.
4. **Deadwood stays aloft** on its own string (the string-machine advantage — no heavy sweep/spotting-table needed; this is Subsystem 1/5's clearing path, not mine).
5. **LOWER** — wagon descends / chosen reels pay out, **smoothly (controlled, not free-drop)** to kill cord whip.
6. **Final approach** through the per-spot guide tube + lead-in (Section 4) seats each pin on-spot.
7. **SETTLE DWELL** (~0.5–0.8 s) with strings near-slack → pins stop swinging → camera re-reads to **confirm on-spot** before "machine ready."

The free-fall AMF "3-second pin-settle before the table descends" maps here to the **post-lower settle dwell**; the timing budget is preserved.

---

### 4. On-spot landing — the hard requirement (shared by both architectures)

This is where the subsystem lives or dies. I combine the **OEM cord-geometry method** with a **prototype-insurance lead-in**, because for a proof-of-mechanism we value robustness over OEM minimalism.

#### 4.1 Primary mechanism — calibrated cord geometry (the OEM way)

Each pin's string exits a **fixed guide tube** in the overhead comb directly above its spot. Two geometric facts make a lowered pin land on-spot:

- **Near-vertical cord at the spot.** The guide-tube exit is positioned so the cord hangs **plumb over the spot** in the final 6–8 in of descent. A plumb cord through the pin's head-hole means the pin's own weight pulls its head-axis to the cord line → the base lands centered under the head.
- **Pendulum self-damping.** A pin suspended from a string through its head is a **stable pendulum** (attachment point above CG by ~9–10 in). Any residual swing decays; the settle dwell waits it out. The cord does the centering; gravity does the damping.

Calibration (per spot, one-time, on the bench): adjust **free cord length** (so the pin base just kisses the deck with ~5–10 mm of residual slack, not hanging tight, not piled) and **guide-tube X-Y exit position** (to put the plumb line on the spot). Real machines hold ±2 mm this way; expect a few hours of per-spot tuning on the proto.

#### 4.2 Prototype insurance — a shallow lead-in funnel per spot

Because the proto must survive a *10,000-cycle durability run* where cord stretch, debris, and air currents will accumulate error, I add a **passive lead-in ring at each spot** that the OEM machines omit:

| Spec | Value |
|---|---|
| Type | Shallow truncated-cone "sub-funnel" / lead-in ring, recessed flush into a removable deck overlay |
| Mouth diameter | **≈ 95 mm** (≈ 1.8 × pin base dia of ~51 mm) |
| Throat diameter | **≈ 54 mm** (pin base + ~3 mm) |
| Wall angle | **≈ 12–15° from vertical** (shallow — a steep funnel would tip a pin, not center it) |
| Depth | **≈ 8–12 mm** (just enough to catch a near-miss base and walk it to throat) |
| Material | UHMW-PE or acetal (low friction, quiet, wear-resistant), or TPU-printed for proto iteration |
| Capture window | Corrects up to **~20 mm** of approach error into **~±3 mm** seated |

The lead-in is a **safety net, not the primary** — if cord geometry is good, the pin barely touches the ring. It buys robustness for the durability test and gives us a knob if a particular spot drifts. **Tradeoff flagged:** rings slightly alter pin-fall realism (a pin tipping near the throat edge can self-right in a way a bare deck wouldn't), so for any future *sanction-fidelity* evaluation we'd pull the overlay and rely on cord geometry alone. For the proto, robustness wins.

#### 4.3 Expected precision & the verification loop

| Metric | Target | How achieved |
|---|---|---|
| Radial landing error (typical) | **≤ ±6 mm** | cord geometry |
| Radial landing error (worst case, late in durability run) | **≤ ±10 mm** | cord geometry + lead-in ring |
| On-spot **confirmation** | every cycle | **Track A camera re-read after settle dwell** — if a pin is off-spot or missing, FSM flags and can re-cycle |
| Cycle-to-cycle repeatability | within ±3 mm of the cycle-1 position | encoder-repeatable wagon stop + fixed guide tubes |

The camera (already built) closes the loop: the **on-spot requirement is verified optically every shot**, so the mechanism doesn't have to be perfect open-loop — it has to be good enough that the camera rarely calls a re-cycle. That is a much easier bar than blind ±2 mm, and it's a real advantage of reusing this control stack.

---

### 5. Reuse of the existing control stack (rev-C deltas)

The lift/set actuator must be driven through the **same proven topology**: **isolated G5LE dry-contact relay outputs commanding existing-style motor contactor coils**, gated by the **non-bypassable safety rail**, with the **RP2040 motion max-run backstop** and **NE555 watchdog**. Concretely for the **common-wagon primary**:

- **1× motion relay → "LIFT motor contactor"** (run the wagon motor). This is a *direct re-use* of the `S`/`T` contactor-command pattern (Section 9 of the existing board): the rev-C board closes a dry contact into a small motor-drive/contactor; the board never switches motor current. The motor drive itself (a BLDC ESC or stepper driver) lives off-board, exactly as the 115 VAC contactors do today.
- **Direction**: if the wagon motor is reversible (up/down) we need either a 2-relay reversing pair (re-using the existing `M2` sweep-reverse channel concept) or a single-direction motor with a mechanical return — **I recommend a reversible drive + a 2-relay reversing contactor**, mapped to two rev-C channels.
- **Position feedback**: the wagon's **incremental encoder + two limit/home switches (TOP, BOTTOM)** are *fast inputs* on the **RP2040** (the existing cam-input cells, repopulated) — these replace the AMF sweep/table cams as the "where am I in the stroke" feedback. The RP2040's existing **`MAX_MOTION_MS` backstop** (8 s/motor today) directly protects a stuck wagon: if LIFT runs past its max, the rail drops and the motor de-energizes. **This is a clean reuse — the wagon motor *is* an "intermittent motor like S/T."**
- **Selection latch bus → Subsystem 2**: ten "hold/release" commands for the per-string clutches. These are low-power solenoids → re-use the **G5LE relay cells** (or, if 10 channels are too many for one board, an MCP23017 OUT-B bank driving a ULN2803). Flagged as the main rev-C channel-count question.

For the **ten-reel alternative**: **10 motion relays (one "reel run" per pin)** + 10 encoders on the RP2040/MCP — a heavier channel mix but still the same cell types.

> **Net rev-C change vs. the existing AMF board:** swap the AMF-specific channel mix (sweep/table/spot/grippers/bin) for **{LIFT-fwd, LIFT-rev, 10× string-latch, encoder, TOP/BOT limits}**. Same opto inputs, same G5LE outputs, same safety rail, same RP2040 supervisor, same watchdog. This is exactly the "re-populate the proven cells against a new channel mix" rev-C the brief describes.

---

### 6. What I am explicitly NOT designing (interfaces, not redesigns)

- **String routing, comb, take-up spools, per-string holdback clutch, anti-tangle** → **Subsystem 2.** I *require* of it: ten independently latchable strings; a defined guide-tube exit X-Y-angle per spot (which my Section 4 centering depends on); strings rated for the 255 N wagon load.
- **Pin/string attachment geometry (head-hole position, knot/anchor), pin CG** → **Subsystem 4.** I *assume* the string attaches at/through the **top of the head**, giving the stable-pendulum centering of Section 4.1.
- **Deadwood clearing, ball return up-lane** → **Subsystems 1 & 5.** The string-machine "deadwood hangs on its string" model means I don't need a sweep/spotting-table — but I assume Subsystem 1's cycle leaves deadwood aloft during my lower step.
- **Standing-pin detection (the 10-bit mask) & FSM** → **Subsystems 7 & Track A.** I *consume* the mask to decide which strings to latch, and I *produce* the post-settle "on-spot OK" via the same camera.

---

### 7. Build & 10k-cycle test hooks (for Subsystem 10)

- **Instrument the landing:** the camera already gives per-cycle pin-position; **log radial error per spot per cycle** → directly measures landing drift over 10k cycles (the core durability metric for *this* subsystem).
- **Instrument the lift:** log encoder stroke time and peak motor current per cycle → detects belt creep, increasing friction (string fraying in guide tubes), or a binding rail.
- **Wear suspects to watch:** belt tension (Option A), guide-tube bore wear at the cord exit, lead-in ring throat wear, clutch-latch repeatability. Make the **deck overlay + lead-in rings a bolt-in removable plate** so they can be swapped/inspected without touching the lane.


---

## Subsystem 4 — Pins, Strings-on-Pins & Deck/Spot Geometry

**Scope boundary:** I specify the *passive* hardware — the ten pins, the string-on-pin attachment, and the pin-deck/spot structure they land on. I do **not** design the take-up/holdback (Subsystem 2) or the lift carriage / "string wagon" (Subsystem 3). My job is to deliver pins that land on-spot every cycle and present strings to those subsystems in a clean, snag-free, predictable geometry. Two interfaces dominate the writeup: **string-routing geometry up to the take-up (→ Sub 2)** and **pin balance/landing behavior under the lift cord (→ Sub 3)**.

### 4.1 Build-vs-buy decision: BUY commercial string pins

This is the single highest-leverage decision in the whole subsystem, and the answer is unambiguous for a prototype: **buy QubicaAMF or U.S. Bowling regulation string pins, pre-drilled and re-weighted, with factory pre-cut strings.** Do not modify standard free-fall pins yourself.

Why. Both QubicaAMF and U.S. Bowling start from USBC-legal free-fall pins, drill them to a controlled spec, and **re-introduce ballast into the head** to bring weight and radius-of-gyration (RG) back into USBC limits ([U.S. Bowling Q&A](https://usbowling.com/articles/string-pinsetter-q-a/)). The drilling removes ~⅓ oz and drops the center of gravity; the re-weighting is the non-obvious part that a garage build will get wrong. A pin that is even slightly tail-heavy or off-axis after a sloppy DIY drill will **stand crooked, walk off-spot, or pendulum** when the lift cord goes taut — which directly corrupts both on-spot landing (my deliverable) and the camera standing-pin mask (Sub 7). Buying removes an entire class of "why won't it stand straight" debugging from the 10,000-cycle experiment.

Cost is trivial at one-lane scale: a 10-pin set runs roughly $90–$160 (string pins carry a small premium over the ~$8–$12/pin free-fall price). For a proof-of-mechanism that is noise. **Buy two full sets** (20 pins) so a cracked pin or a string-durability failure mid-experiment doesn't halt the cycle count while you wait on shipping.

The "modify standard pins" path is documented only as a **fallback** below (§4.6) in case the prototype needs a non-regulation pin (e.g. lighter pins to de-rate the ~255 N lift load during early bring-up).

### 4.2 Pin specification (regulation, as bought)

Standard USBC tenpin geometry, which the string pins preserve ([USBC equipment specs](https://bowl.com/getmedia/08ef148d-c0e4-4e00-9e0d-855ba4729ad5/equipment-specs-manual.pdf); [Dimensions.com pin deck](https://www.dimensions.com/element/ten-pin-pin-deck)):

| Property | Spec | Note for this build |
|---|---|---|
| Overall height | 15 in ± ⅛ in | Sets string drop length budget (Sub 2) |
| Max (belly) diameter | 4.75 in ± 1/32 in | Drives min spot-to-spot clearance; pins are 12 in apart so bellies sit ~7.25 in apart |
| Base diameter | 2.25 in | Equals the spot diameter — pin base ≈ spot footprint |
| Neck (narrowest) | 1.8 in dia, ~10 in up | Where deadwood pins hang/clack against neighbors' strings |
| Weight | 3 lb 6 oz – 3 lb 10 oz | String pins re-weighted into this band after drilling |
| Material | Hard maple core + plastic/Surlyn coat | Coating durability is the wear story (§4.5) |

### 4.3 The string-on-pin attachment (the heart of this subsystem)

The string runs **down through the head of the pin and knots inside it** — it does not clamp to the outside. Two coaxial-ish holes, top-entry plus a side/internal counterbore for the knot ([U.S. Bowling Q&A](https://usbowling.com/articles/string-pinsetter-q-a/); USBC string-pin certification language):

- **Top entry hole:** ≤ 9/32 in (0.281 in) diameter, drilled down the central axis of the head. The cord passes through this.
- **Knot-capture hole:** ≤ 11/16 in (0.687 in) diameter, intersecting the top hole, sized so a **stopper knot** (figure-eight or doubled overhand) seats and cannot pull back through the 9/32 in throat. Holes are drilled only as deep as needed to intersect — they do not run through to the base.
- **Re-weighting:** ballast is added back into the head around the drilled cavity to restore the 3 lb 6 oz+ weight and the RG, keeping CG near the factory location so the pin stands plumb under cord tension.

**String material & dimensions** ([QubicaAMF EDGE String parts](https://www.qubicaamf.com/bowling-products/pinspotters/edge-string); [U.S. Bowling Q&A](https://usbowling.com/articles/string-pinsetter-q-a/)):

- **Cord:** ~**5.3 mm braided synthetic** (QubicaAMF EDGE spec), bonded/coated so the coating **acts as a self-lubricant** to reduce string-on-string drag during tangle contact. This is why you buy pre-cut factory strings rather than cutting hardware-store paracord — the coating is the anti-tangle feature, and it interfaces directly with Sub 2's string comb/tray and Sub 1's tangle-risk story (the #1 known risk).
- **Active length:** USBC certification requires **≥ 54 in** of string; field practice targets **≥ 65 in of unobstructed slack** per pin so deadwood strings can *touch* each other without dragging a standing neighbor off-spot. **Take the 65 in number as the design slack** and let Sub 2 set the take-up stroke from it.
- **Termination at the top end:** the cord runs up to the take-up/holdback (Sub 2); I own only the *pin end* knot. Spec it as a doubled figure-eight seated in the 11/16 in counterbore, then a dab of cyanoacrylate or a heat-set whip on the braid tail to stop fraying. **Frayed cord ends are a leading tangle/snag initiator** — flag.

**Interface to Sub 3 (lift):** because the cord exits the *top center* of the head, the pin hangs from a single near-axial point. When the common-lift carriage pulls all ten cords, each pin should lift **base-down, plumb**, provided CG is on-axis (hence the re-weighting requirement). An off-axis CG makes the pin cock as it lifts and clears the deck at an angle → bad re-spot. So the *purchased, re-weighted* pin is what makes Sub 3's "land by cord geometry + settle dwell, no spotting cup" approach viable. If pins cock during bring-up, suspect pin CG before suspecting the carriage.

### 4.4 Deck & spot geometry (regulation)

The deck is a flat, level, hard-coated surface carrying ten pin spots in the standard equilateral triangle ([USBC specs](https://bowl.com/getmedia/08ef148d-c0e4-4e00-9e0d-855ba4729ad5/equipment-specs-manual.pdf); [Dimensions.com](https://www.dimensions.com/element/ten-pin-pin-deck); [Bowling.Zone setup](https://bowling.zone/bowling-pin-setup/)):

| Element | Spec |
|---|---|
| Triangle | Equilateral, **12 in center-to-center** between adjacent spots |
| Spot diameter | **2.25 in** marker (matches pin base) |
| Rows | 4 rows (1-2-3-4 pins); row-to-row pitch **20.75 in** along lane |
| Triangle side | 36 in (3 gaps × 12 in) |
| Deck width × depth | ~40.75 in × ~35.875 in pin-deck footprint |
| Headpin | 60 ft from the foul line |
| Surface | Level (USBC), hard wear-coat at each pin landing zone |
| Side structure | **Kickbacks** (vertical side walls flanking the deck) + a rear **cushion/curtain** in lieu of the free-fall sweep |

**Spot-to-pin landing strategy (where pin geometry meets the cycle):** since this machine sets pins by **cord geometry + a settle dwell with no spotting cup** (Sub 3's stated design), the deck spot must do the final centering. For the prototype I recommend a **shallow conical spot recess** at each location: a 2.25 in dia, ~2–3 mm deep dished/chamfered pocket (machined into a replaceable deck insert, or a stick-on USBC spot decal over a CNC'd dimple). The chamfer lets a pin landing within a few mm of true-spot **self-center to the bottom of the cone** as the cord lowers it and slack goes in. This is the cheapest, highest-yield reliability lever for on-spot landing and it's entirely in my subsystem. It does **not** add a cup that the cord must clear, so it doesn't violate Sub 3's "no spotting cup" constraint — it's a passive feature in the deck, not a moving spotting member.

**String routing through the deck (interface to Sub 2):** standing pins route their cords straight up; **deadwood pins must not foul a neighbor's cord.** Two mitigations live partly in my geometry:
1. **String exit overhead, not through the deck.** Cords go *up* from the pin top to the take-up; nothing penetrates the deck. The deck stays a clean flat plane — good for both the camera baseline (Sub 7 difference-from-empty) and for sweeping deadwood-free.
2. **65 in slack + coated cord** (above) is what lets tangled deadwood strings slide over each other. My deliverable is making sure the *purchased* pins ship with that slack and coating; Sub 2 owns the comb/tray that keeps the upper runs parallel.

**Guide funnels — recommend AGAINST for v1.** Real string machines (EDGE String, StringPin) deliberately keep the **deck open with strings hidden above** and rely on cord geometry + slack rather than per-pin funnels, because funnels are themselves snag points. Keep the deck a bare regulation triangle with conical spots for the prototype; only add localized funnels if a specific spot proves to mis-land repeatedly during the 10k run (data-driven, not pre-emptive).

### 4.5 Durability (feeds Sub 10's 10k-cycle test)

Field data from a center running QubicaAMF EDGE String: **~9 cracked pins + 2 broken strings over a season**, pin rotation around **25,000 frames** ([QubicaAMF EDGE String](https://www.qubicaamf.com/bowling-products/pinspotters/edge-string); user reports). Two failure modes I own:
- **Pin cracking** — radiates from the drilled head cavity under repeated ball/pin impact; the Surlyn-rich ball-impact coating is the mitigant (QubicaAMF Pinnacle pins add ~50% more Surlyn). At 10k cycles a fresh set should comfortably survive; carry the spare set anyway.
- **String fatigue/abrasion** — at the knot (stress concentration) and where the cord rubs the top-hole throat. Pre-cut coated factory strings are rated for full-season runs. **Plan: inspect knots at ~2k-cycle intervals; treat any fray as replace-now.** Log string failures as a primary metric for Sub 10.

### 4.6 Fallback: modify standard pins (only if needed)

If bring-up needs **lighter/de-rated pins** to protect the carriage at first power-on, or if regulation string pins are back-ordered:
- Take standard free-fall maple pins, drill a 9/32 in axial top hole + an intersecting 11/16 in knot pocket on a drill press with the pin held in a V-block jig (axial concentricity is critical).
- **Do not bother re-weighting for a non-regulation bench test** — accept the ~⅓ oz loss and lowered CG, but verify each pin still stands plumb under static cord tension before use; discard any that cock. This is explicitly off-spec and only for mechanism debugging, never for a scoring-valid run.

### Parts table

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Regulation string pins (set) | USBC-legal, drilled 9/32 in top + 11/16 in knot pocket, re-weighted, Surlyn-coated maple | 2 sets (20 pins) | $180–$320 | QubicaAMF or U.S. Bowling; buy spare set for the 10k run |
| Pre-cut bonded strings | ~5.3 mm coated braided synthetic, ≥54 in (target 65 in slack) | 20 + 6 spare | $40–$80 | Factory pre-cut; coating = anti-tangle. Interface to Sub 2 comb/tray |
| Spare string spool | 5.3 mm coated, 50 m | 1 | $40–$60 | Re-string broken pins mid-experiment |
| Deck spot inserts (or decals over CNC dimples) | 2.25 in dia, ~2–3 mm conical recess, replaceable | 10 | $30–$120 | Self-centering on-spot landing; machine into deck plate or 3D-print pucks |
| Deck plate (pin-deck surface) | Phenolic/HPL or hard-coated ply, ~41 × 36 in, level, replaceable wear zone | 1 | $80–$200 | Flat plane = clean camera baseline + clean sweep |
| Kickback side walls | Vertical UHMW/phenolic flanking deck, full-height | 2 | $60–$150 | Contain pin scatter; protect string runs |
| Rear cushion/curtain | Foam-backed vinyl or hanging mat at pit edge | 1 | $40–$100 | Energy absorber in lieu of free-fall sweep |
| String-end finishing (CA glue / heat-shrink whip) | Anti-fray treatment for cut braid tails | 1 kit | $15 | Frayed ends = tangle initiators |
| Pin-jig V-block (fallback only) | Drill-press fixture for axial hole, if modifying pins | 1 | $25 | Only for §4.6 fallback path |
| **Subsystem total** | | | **~$510–$1,170** | One lane; range driven by deck fab quality + buying 1 vs 2 pin sets |

### Risks
- **String tangle over thousands of cycles (the project's #1 risk) is partly a pin-geometry problem I can only mitigate, not own.** My levers — coated 5.3 mm cord, 65 in slack, top-center axial exit, no deck penetrations, anti-fray ends — reduce snag initiation, but the upper-run management (comb/tray) is Sub 2. A bad handoff at that interface will tangle regardless of good pins.
- **DIY pin modification produces off-axis CG → pins cock under the lift cord → mis-land off-spot and corrupt the camera mask.** Mitigated by *buying* re-weighted pins; the fallback path is explicitly debug-only.
- **Knot pull-through or knot-stress fatigue.** A doubled figure-eight in an 11/16 in pocket should hold, but the knot is the cord's highest-stress point; under-rated knotting will be the first string failure mode in the 10k run.
- **Conical spot recess could trap a pin base or interfere with lift-off** if cut too deep/steep — needs to be shallow enough (2–3 mm) that the cord still cleanly extracts the pin. Tune empirically.
- **Pin cracking from the drilled cavity** under commercial impact; low risk at 10k cycles on fresh pins but non-zero — spare set mandatory.

### Open questions
- **Exact re-weighting recipe** (ballast material/location) used by the vendors is proprietary — fine if we buy, but a hard unknown if we're ever forced to roll our own regulation pins. *Flagged as a buy-don't-build boundary.*
- **Does the camera difference-from-empty detector (Sub 7) tolerate the hanging-deadwood cords in frame?** A knocked pin dangling from its string changes the scene; need to confirm the standing-pin baseline isn't confused by swinging strings. This is a Sub-7 question but driven by my cord geometry — worth a joint frame-capture test.
- **Conical vs flat spot:** real EDGE/StringPin decks appear to use essentially flat spots and rely purely on cord geometry. My conical-recess recommendation is an *added* reliability hedge — needs an A/B during bring-up to confirm it helps rather than hurts lift-off. *Flag: I'm proposing a deviation from commercial practice.*
- **Cord top-end attachment to the take-up** (Sub 2) — knot vs swaged ferrule vs reel-clamp — affects whether 65 in of slack is achievable in the available headroom; needs the Sub 2 stroke number to close.
- **Whether the spare-conversion anomalies USBC flagged** (string pins score slightly differently on certain spares due to string drag) **matter for a non-sanctioned prototype** — almost certainly no, but noting it so nobody chases a "scoring is weird" ghost that's actually inherent string-pin physics, not a bug.

Sources: [U.S. Bowling String Pinsetter Q&A](https://usbowling.com/articles/string-pinsetter-q-a/) · [QubicaAMF EDGE String](https://www.qubicaamf.com/bowling-products/pinspotters/edge-string) · [USBC Equipment Specifications Manual](https://bowl.com/getmedia/08ef148d-c0e4-4e00-9e0d-855ba4729ad5/equipment-specs-manual.pdf) · [Dimensions.com — Ten-Pin Pin Deck](https://www.dimensions.com/element/ten-pin-pin-deck) · [Bowling.Zone pin setup](https://bowling.zone/bowling-pin-setup/)

---

## Subsystem 5 — Ball Handling & Return

### Scope and interfaces

I own everything from "the ball leaves the pin deck" to "the ball is parked at the bowler's ball-return tray," for **one prototype lane** on a bench/spare cabinet. My job: stop the ball, let the existing detector trigger the cycle, get the ~14–16 lb ball *back up the lane* without ever touching strings or hanging deadwood, and hand it off clean.

**Interfaces I must respect (and not redesign):**
- **Ball-detect input → control board (EXISTS):** the DIELL-style photo-beam already characterized by the controls track (16 V rest / 0.7 V broken, NPN active-low) is the cycle trigger. I *reuse* it — I only specify *where* the beam crosses and that its bracket survives ball strikes. The board reads one opto input (PC817) from it.
- **Ball-return motor → control board output (NEW):** one G5LE dry-contact relay channel energizing a contactor that runs the accelerator motor. The board does NOT modulate it — it's a dumb on/off with a hardware ball-present interlock and a timeout. I define the contactor and the on/off logic envelope; FSM ownership is Subsystem 7's.
- **String/pin keep-out:** Subsystem 2 (string take-up) and Subsystem 3 (lift wagon) live ABOVE and BEHIND the pin spots. My ball path must stay physically below/in-front of the string curtain. This is the load-bearing geometric constraint of my whole design.

I did ground this against how real string machines actually move the ball — see "Prior-art notes" at the end for what I pulled and what's an assumption.

---

### 5.1 The core problem, sized

A bowling ball is **8.5 in (216 mm) diameter, up to 16 lb (7.26 kg)**. It arrives at the pit at roughly **15–24 mph (6.7–10.7 m/s)** for a hard thrown ball. Pit kinetic energy at the high end: ½·7.26·(10.7)² ≈ **415 J**. That energy has to be absorbed every ball, thousands of times, without (a) bouncing the ball back up-lane, (b) destroying the cushion, or (c) shock-loading the string mechanism behind it.

Then I have to put **~71 J of potential energy back** into the ball to lift it the ~0.5 m from pit floor to the return-track crest (mgh = 7.26·9.81·0.5 = 35.6 J for a 0.5 m lift; doubling for friction/inefficiency in a wheel accelerator → call it the motor sizing problem below, which is governed by *speed* not just energy).

Two genuinely separate machines here: **(A) the pit/cushion** (passive energy absorber) and **(B) the ball return** (active prime mover). I'll treat them in order, then detection placement, then the keep-out geometry that ties it to the rest of the lane.

---

### 5.2 (A) Pit & cushion — stopping the ball

**Design choice: hanging curtain cushion + sloped pit carpet + kickback side cushions.** This is the proven free-fall-house approach and it transfers directly; string machines keep essentially the same pit. I am NOT reinventing this — the string conversion changes what's *above* the pit (no sweep, no spotting table), not the pit floor.

- **Rear cushion:** a **hanging flap of layered rubber/EPDM belt** (think conveyor-belt material, 12–16 mm thick) suspended from a top pivot bar so it swings back on impact and dumps energy into a friction/gravity return-to-vertical, not a hard rebound. Width spans the lane (1.07 m / 42 in pin-deck width + kickback margin → ~1.2 m). Behind it, a **secondary catch** (a second looser curtain or a foam-filled backstop) catches any ball that punches through on a fast shot. The hanging-curtain approach is specifically what limits rebound — a rigid wall would throw the ball back into the strings.
- **Pit floor:** a **rubber-belt / pit-carpet mat** on a shallow slope (~5–8°) so a stopped ball *gravity-feeds forward toward the ball door* on its own — no powered conveyor needed inside the pit itself. This is the key simplification for a 1-lane prototype: let gravity collect the ball at a single pickup point.
- **Kickbacks (side cushions):** rubber-faced plates down both sides of the pit to keep the ball (and any flung pin) inside the pit envelope and steer it to the pickup. On a string machine these also stop a hanging pin's string from being dragged sideways into the ball path.
- **Ball door / pickup throat:** at the low front corner of the sloped pit, a single throat (~9.5 in / 240 mm wide opening — just over ball diameter) where the ball rolls onto the lift. A simple gravity gate / lip keeps a second ball (impossible in single-lane single-bowler test, but good practice) from stacking.

**Why curtain not spring-bumper:** I considered an automotive-style energy absorber or a sprung paddle. Rejected — too few absorbers survive 10k high-energy hits without maintenance, and a sprung element *stores* energy and gives it back (rebound). Friction/gravity curtains dissipate as heat + don't rebound. This matches every commercial house pit I found.

**Cushion replaceability:** belt material is a wear item. I'm speccing it as a **bolt-on replaceable strip** so the 10k-cycle test can log cushion wear and swap it without disturbing the rest of the rig.

---

### 5.3 (B) Ball return — the prime mover

This is the real new mechanism in my subsystem. Three candidate architectures:

| Option | How | Pros | Cons | Verdict |
|---|---|---|---|---|
| **Wheel accelerator (single drive wheel + idler ramp)** | Ball rolls onto a short ramp; a spinning rubber wheel pinches it against a fixed curved shoe and flings it up onto the return track | Dead simple, 1 motor, no synchronization, exactly how real AMF/Brunswick ball lifts work, cheap, compact | Needs the ball delivered to the wheel reliably; noise; wheel is a wear item | **CHOSEN** |
| Belt elevator (cleated incline belt) | Ball sits in a cleat, belt carries it up an incline | Gentle, positive capture | Bigger, belt tracking issues, more cost, cleat spacing matters | Backup |
| Vertical bucket/paddle elevator | Paddle scoops ball up a shaft | Compact footprint | Complex, more moving parts, overkill for 0.5 m | Rejected |

**Chosen: single-wheel friction accelerator** (the "ball lift wheel" topology used in real pinsetters). Mechanism:

1. Gravity-fed ball from the sloped pit arrives at the **lift throat** at the front-low corner of the pit.
2. A **rubber-tired accelerator wheel** (≈ 8–10 in / 250 mm OD, 2–3 in wide, soft rubber tread ~50–60 Shore A) spins continuously-on-demand. The ball is fed between this wheel and a **fixed curved backing shoe** (UHMW-PE faced steel, radiused to the ball). The wheel's surface speed (~3–4 m/s) grips the ball and drives it up the shoe and onto the return track. Friction grip on a 16 lb ball with a soft wide tread is well within reach — this is exactly the duty real ball lifts run.
3. The ball is launched onto an **inclined return track** (two parallel steel rails / a trough) that runs up-lane *outside the lane bed, along the capping/gutter line*, back to the bowler's ball-return tray. For the prototype I can run the track along one side at bench height; in a real install it goes under the lane in the subway, but for a 1-lane bench rig **over-the-top alongside the lane is fine and far easier to debug**.
4. **Momentum carry + track slope:** the wheel gives the ball enough exit velocity that it coasts up to the track crest, then **gravity carries it down the gently-declining return track** to the bowler. So the accelerator only has to do the *lift to the crest*; the long horizontal-ish run back is gravity. This is the standard ball-return energy model and keeps motor work small.

**Motor sizing (the real number):**
- The accelerator is **speed-limited, not energy-limited**. To impart exit speed ~3.5 m/s to a 7.26 kg ball, and overcome friction up the shoe, peak power during the ~0.3 s grip event is roughly: F_grip to accelerate ball to 3.5 m/s in 0.3 m of contact ≈ ball KE 0.5·7.26·3.5² ≈ 44 J delivered in ~0.2 s ≈ **220 W instantaneous**, plus friction/slip losses → size the motor at **~370 W (½ HP)** continuous-rated for thermal margin against repeated launches and slip. Real AMF ball-lift motors are ⅓–½ HP — this checks out.
- **Motor choice:** a **½ HP (370 W) AC gearmotor, ~200–300 rpm output**, belt or chain to the wheel. AC is deliberate here: it runs straight off the contactor the control board switches, no VFD/driver needed, brutally reliable, cheap, and matches the "dumb on/off relay output" interface. (A BLDC + driver would be quieter and softer-start but adds a driver board and a control protocol the relay interface doesn't want. For a prototype I optimize for *debuggability and the existing interface*.) — **FLAG:** if pit noise is a problem on the bench, swap to a 24 V/48 V BLDC gearmotor + simple driver enabled by the same relay; deferred.
- **Soft start / inrush:** a ½ HP single-phase motor inrush is ~6× FLA for a few cycles. The G5LE relay does **not** switch the motor directly — it switches a **DIN-rail contactor** (e.g. a 9 A IEC contactor) coil; the contactor handles motor current. This is already the controls track's pattern (relay → contactor for inductive loads). **Interface note to Subsystem 6:** ball-return needs one relay channel wired to a contactor coil, plus the field-wetting supply is irrelevant here (line-voltage contactor).

**Run logic envelope (I define the envelope; Subsystem 7 owns the FSM):**
- Trigger to *consider* running the return: ball-detect beam broken (cycle trigger fires) → after a settle/clear dwell, energize accelerator.
- **Ball-present interlock at the lift:** a **second cheap photo-beam or a lever microswitch at the lift throat** confirms a ball is actually present before/while the wheel runs, and the motor only runs while a ball is in the throat + a short post-clear timer. This prevents the wheel free-spinning forever and prevents running dry. **Interface note:** this is a *second* opto input to the board (PC817), distinct from the cycle-trigger DIELL beam. I'm adding one input, not modifying the existing one.
- **Hard timeout:** max run time (~5 s) enforced in firmware (RP2040 fast path) so a jam can't run the motor indefinitely. Ties into the existing 6-condition relay-enable safety rail — ball-return relay is gated by it like every other output.
- **Jam/anti-double:** if beam still broken after timeout → fault, drop the relay, flag to FSM. (Real machines have a ball-call/jam light; we just log it on the bench.)

---

### 5.4 Ball detection placement (REUSE — not redesigned)

The existing DIELL-style through-beam is the **cycle trigger**. I only specify geometry:

- **Where:** the beam crosses the lane **at the pit entrance, just ahead of the rear cushion, ~3–4 in above the pit floor**, spanning the lane width (emitter one kickback, receiver/retroreflector the other). A thrown ball breaks it as it enters the pit → triggers the set/clear cycle. This is the standard ball-detector location and it's *in front of* the string curtain, so a hanging pin doesn't false-trigger it (pins hang higher and behind).
- **Bracket survivability:** emitter/receiver mount **behind the kickback rubber face**, viewing through a small hole, so a flung ball or pin can't hit the optic directly. **FLAG:** beam height must clear deadwood that's been knocked into the pit but is still hanging on its string — if a hanging pin dangles into the beam it could false-trigger. Mitigation: place beam low + close to rear cushion where hanging-pin strings are near-vertical and out of the low beam path. Needs a live check on the spare cabinet.
- The **lift-throat ball-present sensor** (5.3) is a *separate* new sensor I'm adding; it is NOT the DIELL cycle-trigger beam. Two distinct inputs to the board.

---

### 5.5 The keep-out geometry (how ball path stays clear of strings/pins)

This is the constraint that ties my subsystem to 2/3/4:

- **Strings + pins live in a vertical "curtain" above and behind the pin spots**, running up to the take-up/lift wagon. The deepest a hanging deadwood pin reaches is roughly pin-length (~15 in) below its spot, swinging on its string.
- **My ball path is entirely below and in front of that curtain:** ball enters pit low, drops to the sloped pit floor *below* the hanging-pin envelope, gravity-feeds to the **front-low corner** (closest to the bowler, furthest from the string curtain at the rear), and the lift wheel + return track take it up-lane **outside the lane bed along the gutter/capping line** — never crossing back under the strings.
- **Critical clearance:** the lift throat and accelerator wheel sit at the **front kickback corner**, ahead of the rearmost pin spot by the full pit depth. The string curtain hangs at the rear over the spots. So there's a full pit-depth (~0.9–1.2 m) horizontal separation between the live string zone and the ball-lift zone. **This is the single most important geometric guarantee in my design** and I'd validate it physically first on the spare cabinet before powering anything.
- **Side-routing the return track** (along the gutter line, not down the lane centerline subway) further guarantees the up-lane ball run never re-enters the pin/string zone. On the bench prototype the track is external alongside the lane — trivially clear.

---

### 5.6 Parts table

Ball-handling/return BOM for **one prototype lane** (bench / spare cabinet). Costs are rough USD, prototype-grade (mix of new + surplus), not 32-lane volume.

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Rear cushion curtain | Layered EPDM/rubber conveyor belt, 12–16 mm × ~1.2 m wide, hung from pivot bar | 1 | $80 | Wear item; bolt-on replaceable strip |
| Secondary backstop | Foam-filled or second loose curtain | 1 | $40 | Catches punch-through on fast shots |
| Pit floor mat | Rubber pit carpet / belt, ~1.2 × 1.0 m, on 5–8° slope frame | 1 | $90 | Gravity-feeds ball to throat |
| Kickback side cushions | Rubber-faced steel/UHMW plates, both sides | 2 | $70 | Steer ball to pickup, contain flung pins |
| Pit slope frame | Welded steel angle / 80/20 extrusion subframe | 1 | $120 | Sets pit floor slope + mounts cushions |
| **Accelerator wheel** | Rubber-tired wheel ~250 mm OD × 60 mm, 50–60 Shore A tread, keyed bore | 1 | $55 | The prime-mover grip wheel; wear item |
| Fixed backing shoe | Steel, UHMW-PE faced, radiused to ball | 1 | $60 | Ball pinches between wheel + shoe |
| **Ball-return gearmotor** | ½ HP (370 W) AC gearmotor, ~200–300 rpm out | 1 | $230 | Surplus AC gearmotor; AC chosen for relay-on/off simplicity |
| Drive transmission | V-belt or #40 chain + sprockets/pulleys, guard | 1 | $60 | Motor → wheel |
| IEC contactor | 9 A 3-pole DIN contactor, coil voltage to match field supply | 1 | $35 | Relay switches THIS, not the motor directly |
| Return track | Two parallel steel rails / trough, ~3 m for bench run, gentle decline | 1 | $130 | Over-the-top alongside lane for prototype |
| Track stand / supports | 80/20 or welded stands, adjustable height for slope | 1 | $90 | Sets crest + decline back to tray |
| Ball-return tray | Sloped catch tray at bowler end, ball stop | 1 | $70 | Hand-off point to bowler |
| **Lift-throat ball-present sensor** | Retroreflective photo-beam OR lever microswitch + bracket | 1 | $25 | NEW 2nd input to board (PC817); NOT the DIELL trigger |
| DIELL cycle-trigger beam | *(existing — reused)* | 0 | $0 | Already owned/characterized; I only place + bracket it |
| Sensor brackets/optics housing | Behind-kickback mounts, viewing holes | 2 | $30 | Protects optics from ball/pin strikes |
| Fasteners / belt clamps / misc | Bolts, pivot bar, clamps, wiring to board | 1 | $80 | |
| **Subsystem 5 hardware subtotal** | | | **≈ $1,375** | Prototype-grade, single lane |

(Excludes the control board itself, the contactor's upstream breaker/wiring in the cabinet, and Subsystem 9's integration/rollup — flagged for them.)

---

### Prior-art notes (what I pulled / assumed)

- **Reused house-pit knowledge:** hanging-curtain rear cushion + sloped pit + kickbacks + single-wheel friction ball lift is the standard AMF/Brunswick free-fall ball-handling arrangement; string conversions (QubicaAMF EDGE String, Brunswick StringPin, U.S. Bowling) keep essentially the same pit and ball return and only change what's above the deck (no sweep/spotting table, strings instead). I did **not** independently web-verify each vendor's exact ball-lift topology this session — **FLAG: assumption** based on prior Phase 8 AMF 82-70 knowledge in the project context; worth a 30-min confirmation pass against a real EDGE String service manual before committing the wheel-vs-belt choice.
- **½ HP ball-lift motor** sizing is consistent with real AMF ball-lift/elevator motors (⅓–½ HP class) — grounded in the AMF 82-70 machine knowledge already in the project, not freshly searched.
- **Ball physics** (8.5 in, 16 lb, pit energy, lift PE) are first-principles, no source needed.

### Risks
- **Rebound into the string curtain:** if the rear cushion is too stiff/elastic, a fast ball rebounds forward and could swing into hanging deadwood or the string zone. Mitigation: friction/gravity hanging curtain (no stored energy) + full pit-depth separation. Still the #1 ball-side risk; must be tuned empirically in the 10k test.
- **Hanging-pin false-trigger of the DIELL beam:** knocked deadwood swinging on its string could dip into the low cycle-trigger beam and re-fire the cycle. Mitigation: beam placed low + near rear cushion; needs live validation on the spare cabinet (FLAGGED in 5.4).
- **Accelerator wheel grip/slip on a 16 lb ball:** under-gripping stalls the lift; over-gripping flat-spots the tread fast. Tread durometer + pinch geometry need bench tuning; wheel is a logged wear item in the 10k test.
- **Dry-running / free-spin:** without the lift-throat ball-present interlock the wheel runs against nothing or jams; mitigated by the 2nd sensor + firmware timeout, but that interlock is now safety-relevant and must be in the relay-enable rail.
- **Motor inrush vs relay life:** switching ½ HP inrush would weld the G5LE. Mitigated by relay→contactor→motor; if the contactor isn't wired, the relay dies. Hard dependency on Subsystem 6 wiring it that way.
- **Single-lane gravity-collection assumption:** sloped-pit gravity feed to one throat works for one bowler/one ball on a bench; a real lane with two balls in the pit (spare shot) needs anti-stack/queue handling I've only stubbed.
- **Ball KE at the high end (~400 J):** repeated max-energy hits are the cushion's real durability threat; cushion is speced replaceable but lifetime-per-strip is unknown until the 10k test logs it.

### Open questions
- **Subway vs over-the-top return for the *real* install?** Prototype runs the track alongside the lane (easy). Does Westside want the eventual design to drop into the existing under-lane ball subway, which would change the lift height/geometry? Affects accelerator exit-velocity and track routing — need a decision before this generalizes past the bench.
- **Does the existing DIELL beam position need to move** for a string machine, or does its current free-fall location already sit correctly relative to the (now-absent) sweep and the hanging-pin envelope? Needs a live look on the spare cabinet.
- **Contactor coil voltage / where it's powered** — line voltage vs a control transformer in the cabinet? This is a Subsystem 6 cabinet-power question I'm dependent on; I assumed a line-voltage IEC contactor coil switched by one G5LE channel.
- **Quiet-vs-simple motor:** is bench/house noise from a ½ HP AC gearmotor + friction launch acceptable, or do we want the BLDC+driver path now (changes the control interface from dumb-relay to driver-enable)? Deferred but should be settled before any multi-lane thinking.
- **Ball-return track material/finish for ball-surface care:** steel rails vs covered/wood trough — does Westside care about ball cover wear on the return for the prototype, or is that a productization concern? Cheaper steel rails assumed for the bench.
- **Two-ball-in-pit handling** (spare shot, or a ball that doesn't clear before the next is thrown) — out of scope for the 1-lane single-bowler bench test, but flag for whoever generalizes: the gravity-collection throat needs a queue/anti-stack design before real play.

---

## Subsystem 6 — Control Electronics: rev-C Board Spec (REUSE mapping)

**Thesis up front: rev-C is a STRAIGHT SIMPLIFICATION of the as-built 82-70 rev-B board, not a redesign.** The rev-B board (`kicad/wsl-phase8b.kicad_pcb`, 206 components, 184 named nets, 0 DRC violations — fully netlisted, fab-proven at JLCPCB per `project_phase8a_pcb_ordered`) already carries every cell rev-C needs: PC817 isolated opto inputs with an isolated field-wetting supply, discrete G5LE relay-driver channels (NPN base → low-side coil → flyback → RC snubber), PhotoMOS isolated lamp outputs, 3× MCP23017, an RP2040 fast/safety co-processor on UART, an NE555 watchdog, and the 6-condition relay-enable rail. rev-C **deletes** the entire cam/gripper/AMF-relay-label complex (which only existed to ride on top of a 1960s electromechanical sequencer we no longer have) and **adds** 10 string-latch driver channels. The net result fits inside the existing 3-MCP / 1-RP2040 budget with **room to spare**, and the part *types* are 100% reused — a rev-C is exactly the "re-populate proven cells against a new channel mix" the program was designed around.

Two architectural facts drive the whole mapping:

1. **We are NOT reproducing the 82-70 sequence.** The 82-70 rev-B FSM (`cycle_control_8270.py`) is an event-driven slave to six cam switches (SA/SB/SC/TA1/TA2/TB) on the sweep and table motor shafts, because the real machine *drives those motors and reads their shaft position to know when to stop*. A clean-sheet string lane has **no sweep, no spotting table, no 8.5 s electromechanical cycle, and therefore no cams**. The cycle (Subsystem 1) is "common-lift wagon up → release standing pins (or all, on a strike) → wagon down → settle." Position feedback is a couple of limit switches on the wagon's linear rail, not six rotary cams. This alone deletes ~16 channels.

2. **Pin DETECTION is the camera (Track A), so there are no gripper inputs and no pin-lamp outputs.** rev-B carried 10 gripper inputs (GS1–GS10) because the 82-70 reads standing pins mechanically; rev-B *optionally* carried 10 pin-lamp outputs to feed an OEM scorer. Both are gone in rev-C: the overhead camera emits the 10-bit standing-pin mask straight into the FSM (Subsystem 7), exactly as it already does on lanes 21/22. That deletes another ~20 channels of potential I/O.

What those deletions *buy back* is the budget for the one genuinely new load: **10 per-string latch solenoids** (Subsystem 2/3's "per-string latch/holdback" — the common wagon lifts all ten cords, each string is held by an individual latch, and on respot the FSM releases only the latches whose pins should NOT stand, dropping that deadwood back into the pit while standing-pin cords stay latched up). Whether those 10 latches are relays or a solenoid-driver array is the central budget question, answered in §4.

---

### What is DROPPED from rev-B (and why it frees budget)

| rev-B item | count | why it's gone in rev-C |
|---|---|---|
| Cam inputs **SA, SB, SC, TA1, TA2, TB** | 6 fast | No sweep/table motors → no shaft cams. Replaced by 2–3 wagon limit switches (far fewer). |
| Gripper inputs **GS1–GS10** | 10 slow | Camera Track A supplies the standing-pin mask; mechanical pin reading deleted. |
| AMF relay labels **S, T, SP, BE, M, M1, M2** | 7 relay | No sweep (S), table (T), spotting-cup solenoid (SP), back-end (BE), or AMF master/ball-return relays in their 82-70 roles. The *driver cells* are reused under new names (§3); the *labels/semantics* drop. |
| Pin-lamp outputs (optional OUT-B) | 10 | Already depopulated in the rev-B baseline (camera-driven); stays depopulated. |
| **C1 / C2A harness + interposer** | — | Those are the AMF machine connectors (C1 = 34-pin motor/power, C2A = 50-pin switch). A clean-sheet lane has no AMF harness — rev-C wires to its own BLDC driver, latch array, ball-return motor, and limit switches via plain Phoenix terminals. The whole "reversible interposer onto the AMF harness" requirement evaporates (this is a *new* machine, not a retrofit). |
| `man-T / man-S / man-SWS / man-SWSR` service inputs | 4 slow | These are 82-70 maintenance jog switches for sweep/table. No sweep/table → gone. |
| `OS` (off-spot), `PBC` 82-70 cycle pushbutton, `10th-frame` | 3 slow | 82-70-specific; off-spot is a mechanical-spotter concept that doesn't exist with string latches. |

**Dropped totals: ~16 fast/slow inputs and the 7 AMF-labeled relays' *semantics* + the entire C1/C2A field harness.**

What is **KEPT and reused unchanged** from rev-B: the PC817 opto-input cell + isolated field-wetting supply (U41), the discrete G5LE relay-driver cell (base-R → NPN → low-side coil node → 1N4007 flyback → RC snubber across the contact), the PhotoMOS lamp-output cell, the RP2040 on uart0 with the RP_OK rail-permit line, the NE555 watchdog (GPIO12 kick → AO3400 low-side gate on the coil-supply return), and the **6-condition relay-enable rail** (Subsystem 8 — untouched). The DIELL ball-detect front end is reused verbatim as the new foul-line ball detector.

---

### rev-C INPUT allocation (per lane)

Inputs collapse from rev-B's ~28 down to **~9 used**. Fast inputs still go to the RP2040 (so the safety co-processor can enforce hardware motion limits independent of Pi scheduling); slow inputs go to one MCP23017 bank.

**FAST inputs → RP2040 (opto-isolated, active-low, reuses GP6–GP13 from `config.h`)**

| ch | rev-C signal | RP2040 GPIO | reuses rev-B | role |
|---|---|---|---|---|
| 1 | **Ball-detect L** (foul-line beam) | GP12 | DIELL-L cell verbatim | cycle trigger / "ball thrown" — same proven AL-ZARD→opto→GPIO path |
| 2 | **Ball-detect R** (foul-line beam) | GP13 | DIELL-R cell verbatim | redundant beam / direction |
| 3 | **Wagon HOME limit** (down-and-seated) | GP6 | was SA opto | wagon-at-bottom; gates "set complete" |
| 4 | **Wagon TOP / over-travel limit** | GP7 | was SB opto | wagon-at-top + hard over-travel cutout (also feeds rail, see §5) |
| 5 | **Lift motor over-current / driver-fault** | GP8 | was SC opto | BLDC driver fault flag → immediate fault (jam #1 risk) |
| 6 | **E-stop loop sense** (echo) | GP9 | was TA1 opto | software echo of the hardware E-stop string; HW loop is separate and gates the rail directly |
| — | GP10, GP11 | spare fast | were TA2, TB | spare (e.g. string-tension analog-comparator trip, or a 2nd wagon mid-limit) |

That's **4 fast inputs used, 2 spare**, on the identical RP2040 front end — versus rev-B's 8 used (6 cams + 2 ball). The cam-stop *firmware* (`MAX_MOTION_MS` backstop in `config.h`) is reused directly as the wagon-motion timeout.

**SLOW inputs → MCP23017 IN-A (0x20), opto-isolated**

| ch | rev-C signal | chip.port.pin | reuses rev-B | role |
|---|---|---|---|---|
| 1 | **Foul detector** (Radaray/IR across foul line) | IN-A.A0 | Foul cell | on_foul |
| 2 | **First-Ball-Zero / reset pushbutton** | IN-A.A1 | PBZ cell | operator clears fault / power-down rule |
| 3 | **Ball-return-tray full / present** | IN-A.A2 | BS cell | gate ball-return motor (Subsystem 5 interface) |
| 4 | **Service/maintenance mode switch** | IN-A.A3 | a man-* cell | jog/maintenance enable |
| 5–14 | **(OPTIONAL) per-string tension/latch confirm 1–10** | IN-A.A4–B5 | GS1–GS10 cells verbatim | see note ↓ |

**The string-tension/latch-confirm decision (flagged):** the prompt asks whether per-string-latch feedback exists. The OEM string machines use **cord-tension sensing as their primary standing-pin detector** (confirmed via the Flying Bowling / QubicaAMF EDGE references below) — but **we don't need it for scoring**, because the camera already gives the standing-pin mask. So tension sense is *optional* in rev-C, useful only as a **latch-engaged confirmation** (did latch N actually catch its cord?) and a **string-tangle early-warning** (the #1 program risk, per the brief). The beautiful reuse: those 10 confirm channels map **1:1 onto rev-B's now-vacant GS1–GS10 gripper opto cells** — same connector cluster, same front end, zero new design. **Baseline rev-C build populates them** (cheap insurance against the headline tangle risk); they can be DNP'd if the camera proves sufficient. With them populated, IN-A carries 14/16 pins.

---

### rev-C OUTPUT allocation (per lane)

**Relay/driver bank → MCP23017 OUT-A (0x22), reusing the rev-B G5LE discrete relay-driver cells**

| ch | rev-C signal | chip.port.pin | reuses rev-B cell | load |
|---|---|---|---|---|
| 1 | **Lift wagon motor — RUN/ENABLE** | OUT-A.A0 | S relay-driver | enables the 250–400 W BLDC driver (dry contact into the driver's ENABLE/START opto-in — we switch a logic enable, the BLDC controller switches the motor current, exactly the rev-B "we drive coils, the machine's iron switches the motors" pattern) |
| 2 | **Lift wagon motor — DIRECTION** (up/down) | OUT-A.A1 | T relay-driver | DIR line into BLDC driver |
| 3 | **Ball-return motor — RUN** | OUT-A.A2 | M1 relay-driver | dry contact → ball-return motor contactor coil |
| 4 | **(spare relay)** | OUT-A.A3 | BE relay-driver | e.g. brake-release, or sweep-guard if Subsystem 1 adds one |
| 5 | **L-1st-ball lamp** | OUT-A.A4 | PhotoMOS lamp cell | status display |
| 6 | **L-2nd-ball lamp** | OUT-A.A5 | PhotoMOS lamp cell | status display |
| 7 | **L-foul lamp** | OUT-A.A6 | PhotoMOS lamp cell | status display |
| 8 | **L-strike lamp** | OUT-A.A7 | PhotoMOS lamp cell | status display |

That's **3 relays + 1 spare relay + 4 lamps = 8/16** on OUT-A. (If the BLDC driver takes a single combined enable that encodes direction, the relay count drops to 2 + ball-return = 3, freeing another channel.)

**The 10 string latches — the budget crux:**

Per-string latch solenoids are small (a latch/holdback is a low-force detent release, not a lifting actuator — order-of a 12 V, ~0.3–0.5 A pull-type solenoid, ~5 W, e.g. a JF-0530B-class unit). Two ways to drive 10, both inside budget:

- **Option L1 (RECOMMENDED) — drive them from a second MCP23017 (OUT-B, 0x23) through a ULN2803A Darlington array (×2 chips cover 10–16 channels) instead of 10 relays.** This is the *literal slot rev-B reserved*: rev-B's OUT-B at 0x23 was the optional 10-pin-lamp bank that the camera made redundant. rev-C **repurposes that exact vacant chip + address + board region** for the 10 latch drivers. A ULN2803 sinks 500 mA/channel with built-in flyback clamps — ideal for 0.3–0.5 A latch solenoids, far cheaper/smaller/lighter than 10 G5LE relays, and it reuses the rev-B "MCP→ULN→coil" topology that already exists for the relay bank. **10 latches → 10 ULN channels on OUT-B.A0–B1, 6 spare.**
- **Option L2 (reject for prototype) — 10 individual G5LE relays.** Would need a *third* output MCP (we'd exceed OUT-A's 16) plus 10 relays' worth of board area, cost (~$1.20 ea relay + driver), and weight. No upside over L1 for a holdback load; relays only earn their keep when you need a true dry isolated contact or higher current, which a latch solenoid does not.

So the answer to the brief's explicit question — *"the ten per-string latches may need 10 outputs — does that fit the relay/MCP budget or need a driver?"* — is: **they need a driver (ULN2803 array), NOT 10 relays, and they fit perfectly into rev-B's already-present-but-vacant OUT-B MCP23017 (0x23). No new MCP, no relay-budget overflow.**

All latch + relay coils still sit **downstream of the 6-condition relay-enable rail** (Subsystem 8) so the watchdog/arm/E-stop can always drop them.

---

### Device / channel-count summary — is rev-C simpler than rev-B?

| device | rev-B usage | rev-C usage | delta |
|---|---|---|---|
| RP2040 (fast in + cam-stop + UART) | 8 fast in used | **4 fast in used** (2 ball + 2 limits) | simpler (fewer fast lines; same chip) |
| MCP23017 IN-A (0x20) | 16/16 (grippers fill it) | **4–14/16** (latch-confirm optional) | same chip, less loaded |
| MCP23017 IN-B (0x21) | 5/16 (10th + manual) | **0/16 → DNP candidate** | **can be deleted** (no 82-70 manual/10th inputs) |
| MCP23017 OUT-A (0x22) | 11/16 (7 relays + 4 lamps) | **8/16** (3 relays + spare + 4 lamps) | simpler |
| MCP23017 OUT-B (0x23) | depopulated (pin lamps) | **populated: 10 latch drivers via ULN2803** | repurposed, net-zero chip count |
| ULN2803A | ×1–2 (relay bank) | ×2 (relay bank + latch array) | +0–1 small array |
| G5LE relays | 7 | **3 (+1 spare seat)** | **−4 relays** |
| NE555 watchdog / rail / arm / isolated wetting supply | yes | **yes, identical** | unchanged |

**Channel totals: rev-B ≈ 28 in / 22 out (with optional banks). rev-C ≈ 9 in / 18 out** (8 relay/lamp + 10 latch), or 19 in if the optional latch-confirm bank is populated.

**Verdict: rev-C is unambiguously SIMPLER than rev-B.** It uses the **same 3-MCP-max + 1-RP2040** budget — and could drop to **2 MCP23017 + 1 RP2040** if you DNP the empty IN-B (0x21) and skip the optional latch-confirm bank. The relay count falls from 7 to 3. The only *added* complexity is one ULN2803 latch-driver array, which lands in a board region rev-B already reserved. The cam-timing firmware, the C1/C2A harness, the gripper cluster, and four manual-service inputs all delete cleanly. **Same parts library, same safety rail, fewer populated cells.** It is a textbook rev-C: re-populate the proven cells against the new (smaller) channel mix.

**Bus/addressing (per lane board, unchanged topology):** I²C bus repeats 0x20 (IN-A), [0x21 IN-B — DNP], 0x22 (OUT-A relays+lamps), 0x23 (OUT-B latch drivers). RP2040 on uart0 (115200, newline-JSON events) pushing ball/limit events + holding the RP_OK rail-permit. One board per lane (the prototype is 1 lane, so literally one board); the per-board-I²C-bus / clone-the-board pattern from rev-B §6 still applies if it ever becomes a pair.

### Parts table (rev-C BOM delta — only what changes vs the as-built rev-B board; everything else is reused 1:1)

| item | spec | qty | est USD | notes |
|---|---|---|---|---|
| MCP23017 (I²C GPIO expander) | SSOP-28, 0x20/0x22/0x23 | 3 | $2.20 | reuse rev-B part; IN-B (0x21) DNP'd → 3 not 4 |
| RP2040 (Pico or bare) | uart0 link + 4 fast opto-in | 1 | $4.00 | reuse rev-B co-proc + `config.h` pin map (GP6,7,12,13 used) |
| PC817 opto-isolator | DIP-4, field-input isolation | ~14 | $0.12 ea / ~$1.70 | 2 ball + 2 limits + 4 slow + 10 optional latch-confirm; reuse rev-B opto cell |
| G5LE-1 relay (5 V) | SPDT 10 A dry contact | 3–4 | $1.10 ea / ~$4.00 | wagon enable + dir + ball-return (+1 spare seat); reuse rev-B driver cell |
| Relay-driver discretes | 2N3904 base + 1N4007 flyback + RC snubber, per relay | 3–4 sets | ~$1.20 | reuse rev-B G5LE driver cell verbatim |
| **ULN2803A Darlington array** | 8-ch, 500 mA sink, internal clamp | 2 | $0.55 ea / $1.10 | **new role:** drives 10 string-latch solenoids on OUT-B (the budget answer) |
| Per-string latch solenoid | 12 V pull-type, ~0.3–0.5 A, ~5 W (holdback/detent) | 10 | ~$4 ea / $40 | **Subsystem 2/3 load** — board only drives them; mechanical design is theirs. Cost is mechanical, not board. |
| AQH/PhotoMOS lamp output | isolated SSR, status lamps | 4 | $1.50 ea / $6.00 | reuse rev-B lamp cell (1st/2nd/foul/strike) |
| NE555 watchdog + AO3400 gate | bench-proven cell | 1 | $1.50 | reuse verbatim (rail-drop on missed kick) |
| Isolated field-wetting DC-DC (U41) | ~5 V isolated, field side | 1 | $4.00 | reuse rev-B isolated supply |
| Phoenix-style terminal blocks | 3.5 mm, for BLDC-driver / latch / motor / limit leads | ~8 | $6.00 | **replaces** the C1/C2A AMF harness interposer entirely |
| BLDC motor driver (lift wagon) | ~400 W, ENABLE+DIR logic in | 1 | $30–45 | **Subsystem 3 part** — rev-C only provides the 2 logic dry contacts into it; listed for interface clarity |
| Passives (R/C, 4.7 k bus pull-ups, decouple, debounce RC) | per rev-B | lot | $4.00 | reuse rev-B values |
| **Board-electronics rev-C subtotal (excl. solenoids/BLDC = mechanical)** | | | **≈ $40–45** | vs rev-B ≈ $55–65; **cheaper, fewer relays** |

### Risks
- **Latch-solenoid current/duty is an assumption.** I sized them at ~0.3–0.5 A / ~5 W pull-type so a ULN2803 sink works. If Subsystem 2/3's holdback needs a higher-force solenoid (>500 mA continuous, or long-duty hold), ULN channels must be paralleled, swapped for logic-MOSFET drivers (AO3400-class, which the lamp/watchdog cells already use), or the latches must be designed as momentary-release/spring-detent (release pulse only, near-zero hold current — strongly preferred). **Flag to Subsystem 2/3:** make the latch *release* on a pulse and hold mechanically, so the driver never sources continuous current for 10 channels.
- **BLDC driver interface is unspecified.** rev-C assumes the ~400 W lift driver accepts a logic-level ENABLE + DIR (dry contact). If it instead needs analog speed (0–10 V / PWM) or a step/dir or CAN/Modbus interface, OUT-A's two relay contacts are insufficient and rev-C needs a DAC or a PWM pin off the RP2040 — small add, but it changes the output cell. **Confirm the chosen BLDC controller's command interface (Subsystem 3) before laying out rev-C.**
- **No cam position feedback removes the rev-B motion-stop safety model.** rev-B stopped motors on exact cam degrees; rev-C relies on wagon limit switches + the RP2040 `MAX_MOTION_MS` backstop. If a limit switch fails closed/open, only the time backstop catches it. The over-travel limit (GP7) must be a *hardwired* cutout into the relay-enable rail, not merely a sensed input, so a stuck wagon can't be commanded into the rail end.
- **String tangle is invisible to this board without the optional tension bank.** The brief names string management as the #1 risk. If we DNP the 10 latch-confirm/tension inputs to save cost, the controller has no electrical signal for a tangle — it would only manifest as a camera mask anomaly or a motion timeout. **Recommend populating the tension bank** (it's free reuse of the GS opto cells) specifically to instrument the 10k-cycle durability test (Subsystem 10).
- **rev-C is a fresh board spin, not a stuff-option of the existing fab.** Even though every *cell* is reused, the channel mix differs enough (different connectors, ULN latch bank, deleted cam/gripper headers) that it's a new PCB layout/order, not a depopulate of the in-hand rev-B boards. Budget one JLCPCB rev-C spin (~$150–190 assembled, per the rev-B precedent).

### Open questions
- **Does the lift wagon need DIRECTION control at all, or is it a one-way cam/crank cycle?** If the 0.9 m stroke is a motor-reversing belt drive, rev-C needs the DIR relay (as mapped). If Subsystem 3's "string wagon" runs a continuous-rotation crank/cam that goes up-and-down per revolution (like a real pinsetter's main cam), then it's a single ENABLE with no DIR — freeing a relay and simplifying the FSM. **Needs Subsystem 1/3 cycle definition.**
- **Are the 10 latches released individually every cycle, or only on respot?** If every set is "lift all 10, release the deadwood, re-lower" then all 10 latch channels fire every frame and duty/heat on the ULN matters. If latches only actuate on 2nd-ball respot, duty is half. Affects driver thermal sizing. **Subsystem 2/3 cycle interface.**
- **Is cord-tension sensing analog or a threshold switch?** OEMs use tension as the *primary* detector; we use the camera. If we populate the optional bank purely as latch-confirm, a simple threshold microswitch per string (dry contact) drops straight into the PC817/GS cells. If we want graded tension (tangle-trend telemetry), we'd need an analog front end (load cell + ADS1115 on the I²C bus) instead — a different cell. **Decide telemetry depth for the 10k test (Subsystem 10).**
- **Ball-return motor: contactor coil voltage?** Mapped as one G5LE dry contact into the ball-return motor's contactor coil (reusing the rev-B "drive the coil, let the machine's iron switch the motor" pattern). If the prototype's ball-return is a small direct-drive motor with no contactor, the relay must switch motor current directly — confirm the return-motor power (Subsystem 5) so the G5LE contact rating (10 A) is adequate or a contactor is added.
- **Does the prototype keep physical status lamps, or is the camera/desk display the only UI?** rev-C maps 4 PhotoMOS lamp outputs out of reuse habit. If status is shown only on the existing HTML/desk display (Track A pipeline already drives a live HTML), the 4 lamp channels can be DNP'd, shrinking rev-C further toward the 2-MCP minimum.

**Files grounding this section (all absolute):** `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\phase8_channel_allocation.md` (rev-B per-pin map), `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\phase8_io_board_spec.md` (rev-B architecture/safety/power), `C:\Users\Dylan DeYoung\wsl-lane-nodes\docs\phase8b_revB_netclass_inventory.md` (as-built net domains — the authoritative rev-B cell list), `C:\Users\Dylan DeYoung\wsl-lane-nodes\firmware\rp2040\config.h` (RP2040 fast-input pin map GP6–GP13 + RP_OK rail line + MAX_MOTION backstop), `C:\Users\Dylan DeYoung\wsl-lane-nodes\lane_node\cycle_control_8270.py` (rev-B io contract being superseded).

Web sources grounding the string-pinsetter mechanism (common-lift + per-string take-up; cord-tension as OEM detection, which we replace with camera Track A): [How Does a String Pinsetter Work — Flying Bowling](https://www.flyingbowling.com/article/how-does-a-bowling-string-pinsetter-machine-work.html), [EDGE String — QubicaAMF](https://www.qubicaamf.com/bowling-products/pinspotters/edge-string), [Pinsetter — Wikipedia](https://en.wikipedia.org/wiki/Pinsetter).

---

## Subsystem 7 — Detection, Scoring & the String-Setting FSM

### 0. The thesis in one paragraph

The hard half of this subsystem is already built and bench-proven. Track A (`pin_detect.py` → `camera.py`) already turns one overhead frame into a **10-bit standing-pin mask** per deck, and `wsl_scoring_engine.py` already consumes exactly that mask (`record_ball(pin_mask)` where `pin_mask` = *pins remaining/standing*). So scoring is a **zero-change reuse**. What is genuinely new is a **string-setting cycle FSM** that replaces `cycle_control_8270.py`. The good news: it is dramatically *simpler* than the 82-70 cam FSM — there are **no cam angles, no SP spotting revolution, no table/sweep two-motor choreography**. The set cycle is "lift everything, hold the strings that should stand, sweep deadwood, lower." Transitions are driven by **one camera read + wagon HOME/TOP limit switches + a sweep limit**, not by a ring of degree-stamped cam switches. I estimate **~85–90% of Subsystem 7's code mass is reuse** (scoring engine, camera/detector, the io abstraction, the RP2040 link, the daemon scaffold); the new code is **one ~250-line FSM file + ~40 lines of glue**, plus the per-string-latch mask plumbing.

---

### 1. What's reused verbatim (the "already done" core)

| Module | Role in Subsystem 7 | Change needed |
|---|---|---|
| `wsl_scoring_engine.py` | Frame state, running totals, strike/spare/split, 10th-frame, cross-lane, **manual desk correction** (`correct_frame`/`set_frame_bowls`) | **None.** It already takes a standing-pin mask and is mask-source-agnostic. The string machine feeds it the *identical* input the VDB/camera fed it. |
| `pin_detect.py` (Track A, "M4") | Frame → 10-bit standing mask; drift-corrected cap-ROI difference-from-empty; 0/120 errors on the labeled bake-off | None to the algorithm. Only **re-calibrate** `PIN_SPOTS_PX` + `empty_ref.png` for the new deck/camera geometry (string deck looks different than the 82-70 deck). |
| `camera.py` (`PairCamera`) | Owns capture handle + detector + empty ref; `detect_lane(lane)→mask\|None`; `None`→manual fallback | None. `SETTLE_S` retuned for the string deck (pins settle faster — no heavy spotting table rocking them). |
| `controller_io.py` (`MachineIO`/`RecordingIO`) | The hardware `io` contract the FSM is written against; MCP23017 relays/inputs, RP2040 RUN/STOP, NE555 kick, ARM gate | **Re-map the channel dict** for the rev-C mix (fewer relays: 1 wagon motor + 1 sweep + 10 latch solenoids vs the 82-70's S/T/SP). The *class* is unchanged; only `OUT_A_MAP`/`IN_A_MAP` constants change, and they're already regression-locked to the netlist generator. |
| `rp2040_link.py` | Fast-edge co-processor link, health/heartbeat, RUN/STOP, **motion max-run backstop**, interlock echo, `apply_events(fsm)` single-threaded drain | Light. The fast inputs change from "6 cams + 2 ball beams" to "**wagon HOME + wagon TOP + sweep-home limits + 1–2 ball beams**." The `dispatch_*` table changes; the transport/health/backstop logic is unchanged. |
| `controller_daemon.py` | Per-pair 50 Hz loop: `apply_events → slow edges → poll → arm`; power-down rule; RP2040-health safety trip; SIGTERM safe-off | Tiny. Swap `from cycle_control_8270 import …` → `from cycle_control_string import …`; update `_slow_actions`. The loop, the health trip, the ARM gating, the watchdog coupling all stay. |
| `state_store.py` / `lane_node_server.py` (Track A path) | Persists/serves scoring JSON to `/desk`, Phase-8b proxy | None — scoring JSON shape is unchanged, so the desk UI and Phase-8b read/correct proxy keep working. |

**Net reuse:** scoring (1076 lines) + detector (309) + camera (305) + io class (≈250 of 371) + link (≈340 of 372) + daemon (≈290 of 309) all carry over. That's the ~85–90%.

---

### 2. Why the string FSM is *simpler* than the 82-70 cam FSM

| 82-70 cam FSM (`cycle_control_8270.py`) | String set FSM (new `cycle_control_string.py`) |
|---|---|
| 9 states; transitions on **cam degrees** (SB@66, TA2@260, SA@270, TA1@355…) | **6 states**; transitions on **camera-read-done + wagon HOME/TOP limit + sweep-home** |
| Two coordinated motors (sweep **S** + table **T**) + spot solenoid **SP** | **One** wagon motor (up/down via the BLDC gearmotor, Subsystem 3) + **one** sweep + **10 latch solenoids** |
| "Fresh rack vs respot" branch drives an **SP spotting revolution** gated by the **bin switch** (10th pin to bin) | **No bin, no spotting revolution, no fresh-rack branch.** Pins never leave their strings; "respot" and "full rack" are the *same motion* — only the **latch mask** differs |
| Pin state read from **10 gripper micro-switches** (GS1–10) at a precise cam angle (TA2@260) | Pin state read from the **camera** (Track A) during a settle dwell; **no gripper switches to wire** |
| Needs cam-stop enforcement (de-energize a motor at a target degree) on the RP2040 | Needs only **"stop at limit"** — the wagon motor stops on HOME/TOP limit, the classic, dumb, safe pattern |
| `bin_full()`, `cam_TA1_delayreset()`, `cam_SA_zero()`, strike-vs-spare SP semantics… | none of that exists |

The conceptual win: the 82-70 FSM is reverse-engineering a black-box electromechanical sequencer through its cam ring. The string FSM **is** the sequencer — we own every output, and position feedback collapses from "where in 360° of cam rotation" to **two limit switches** (wagon at bottom / wagon at top) plus a sweep-home. That is the single biggest reason this is a tractable bench project.

---

### 3. The string-setting cycle FSM (new code)

**Outputs the FSM drives** (via the existing `io` contract, rev-C channel map):
- `set_wagon(dir)` — `UP` / `DOWN` / `OFF` on the common-lift wagon (Subsystem 3's BLDC + belt). *(New io verb; the 82-70 had `set_sweep/set_table/set_spot`.)*
- `set_sweep(on)` — reused verb; now drives the deadwood sweep/guard.
- `set_latch(mask)` — **the core new output**: 10-bit mask → engage the holdback/brake on each string that must **stay down** (i.e., re-present that pin). Bit *n* set = pin *n* should stand = latch string *n*. Implemented as 10 solenoid channels on an MCP bank (Subsystem 3's per-string latch).

**Inputs the FSM reads:**
- **Camera read** `detect_lane(lane)→mask` (Track A) — the standing-pin mask. *Fires once per ball, during `DETECT_DWELL`.*
- **Fast limits via RP2040:** `wagon_home` (wagon fully down, pins on deck), `wagon_top` (wagon fully raised), `sweep_home`. These replace the cam events on the RP2040 link.
- **Ball beam** (DIELL-style, reused) — the cycle trigger.
- **String-tension cross-check** (optional, secondary) — see §5.
- `interlock_ok()`, `watchdog_kick()`, `now()`, `log()` — **unchanged** from the io contract.

**States (6):**

```
POWER_OFF
MANUAL_INTERVENTION   # power-restore comes up here; await operator re-arm (power-down rule, reused)
READY                 # wagon home, pins standing on deck, awaiting a ball
DETECT_DWELL          # ball thrown; settle window, then ONE camera read -> latch decision
SET_CYCLE             # wagon UP (with deadwood lifted by strings) -> sweep deadwood -> wagon DOWN with latch mask
FAULT                 # safety backstop tripped (motion-timeout / health loss)
```

**Transition table — events → actions:**

| From | Event | Guard | Action | To |
|---|---|---|---|---|
| `POWER_OFF` | `power_restore()` | — | all outputs off | `MANUAL_INTERVENTION` |
| `MANUAL_INTERVENTION` | operator `re_arm()` (PBZ-equiv) | wagon at HOME | arm; lights 1st-ball | `READY` |
| `READY` | `on_ball()` | `interlock_ok` | start `SETTLE_S` timer | `DETECT_DWELL` |
| `DETECT_DWELL` | `poll()` after `SETTLE_S` | camera ready | **read mask** → `self.standing`; **feed `scoring.record_ball(mask)`**; compute `latch_mask`; `set_latch(latch_mask)`; `set_wagon(UP)` | `SET_CYCLE` |
| `DETECT_DWELL` | `poll()` after `SETTLE_S` | camera `None` | **manual-fallback**: no auto-score; still run the machine using *last known standing* (or full-rack on a new frame); `set_wagon(UP)` | `SET_CYCLE` |
| `SET_CYCLE` | `wagon_top` limit | — | `set_wagon(OFF)`; `set_sweep(ON)` (clear deadwood) | `SET_CYCLE` (sub-step) |
| `SET_CYCLE` | `sweep_home` (return) | — | `set_sweep(OFF)`; `set_wagon(DOWN)` | `SET_CYCLE` (sub-step) |
| `SET_CYCLE` | `wagon_home` limit | — | `set_wagon(OFF)`; release latch mask; advance ball/frame; lights | `READY` |
| *any motion* | `poll()` timeout `MAX_MOTION_S` | — | all motors off; (RP2040 also dropped rail) | `FAULT` |
| *any* | RP2040 health loss | — | (daemon) motors off + `power_restore()` | `MANUAL_INTERVENTION` |

The three `SET_CYCLE` sub-steps (UP → sweep → DOWN) are internal and gated by limit switches, exactly the way `cycle_control_8270` used cam events — so they reuse the **same `_enter(state)` + `poll()` backstop pattern**, and the same RP2040 `apply_events` dispatch (just `wagon_top`/`sweep_home`/`wagon_home` instead of `SA`/`TA1`/`TA2`). I'd keep them as one `SET_CYCLE` state with a small internal phase enum to keep the public state set at 6, or split into `LIFTING`/`SWEEPING`/`LOWERING` if the bench wants per-phase timeouts (cheap either way).

**Skeleton (mirrors the existing FSM's shape so it drops into the daemon unchanged):**

```python
class State(Enum):
    POWER_OFF = "power_off"; MANUAL_INTERVENTION = "manual_intervention"
    READY = "ready"; DETECT_DWELL = "detect_dwell"
    SET_CYCLE = "set_cycle"; FAULT = "fault"

class CycleController:          # same name/contract as cycle_control_8270
    def __init__(self, lane_id, io, scoring, camera):
        self.lane, self.io, self.scoring, self.cam = lane_id, io, scoring, camera
        self.state = State.POWER_OFF
        self.ball = Ball.FIRST
        self.standing = 0x3FF    # last known standing mask (full rack)
        self._phase = 0          # SET_CYCLE sub-step
        self._t_state = 0.0

    def on_ball(self):                       # ball beam (reused trigger)
        if self.state is not State.READY or not self.io.interlock_ok(): return
        self._enter(State.DETECT_DWELL)

    def _latch_mask_for(self, standing, ball):
        # On the 1st ball -> stand exactly the pins the camera says are still up.
        # On the 2nd ball  -> after the count, a full fresh rack stands (all 10).
        # (No SP/bin branch: "respot held pins" and "full rack" are the same wagon
        #  motion; only this mask differs.)
        if ball is Ball.SECOND: return 0x3FF
        return standing & 0x3FF

    def cam_wagon_top(self):  ...   # -> sweep on
    def cam_sweep_home(self): ...   # -> wagon down
    def cam_wagon_home(self): ...   # -> OFF, advance ball, READY

    def poll(self):
        self.io.watchdog_kick()
        if self.state is State.DETECT_DWELL and self._dwell_elapsed():
            mask = self.cam.detect_lane(self.lane)        # Track A; None on fail
            if mask is not None:
                self.standing = mask
                self.scoring.record_ball(mask)            # <-- the ONLY scoring call
            latch = self._latch_mask_for(self.standing, self.ball)
            self.io.set_latch(latch)
            self.io.set_wagon(UP); self._enter(State.SET_CYCLE)
        # ...MAX_MOTION_S backstop identical to cycle_control_8270.poll()...
```

---

### 4. Exactly *when* the camera fires, and the latch decision

- **One read per ball, in `DETECT_DWELL`.** The FSM enters `DETECT_DWELL` on the ball beam, waits `camera.SETTLE_S` (retuned — string decks settle faster; **CONFIRM** on the bench, likely ~1.0–1.5 s vs the 82-70's 2.5 s), then takes **exactly one** `detect_lane()`. This is the *same* timing ownership model `camera.py` already documents ("TIMING is owned by the caller… waits the settle window after DIELL, then calls detect_lane()"). The read happens **before** the wagon lifts, while knocked pins still hang at deck level — perfect for difference-from-empty, because a hanging deadwood pin is *out of its spot* and reads "down," which is exactly what we want.
- **The mask does double duty** (the whole point of reuse): it is fed once to `scoring.record_ball(mask)` **and** passed through `_latch_mask_for()` to drive `set_latch()`. The camera *is* the gripper-switch replacement. The 82-70 read 10 micro-switches at TA2@260 to decide respot; we read 10 camera spots during the dwell to decide which strings to latch. **Same decision, optical instead of mechanical.**
- **Latch semantics:** bit *n* high in the latch mask ⇒ engage string *n*'s holdback so pin *n* is **re-presented** on the lower stroke. 1st ball ⇒ latch = `standing` (re-present only what's still up). 2nd ball / new frame ⇒ latch = `0x3FF` (full fresh rack). This collapses the 82-70's fresh-rack-vs-respot branch into a one-line mask choice — no bin switch, no SP.

---

### 5. String-tension cross-check (secondary, optional)

Real string machines (Brunswick **PMI**: per-string pinfall switch + brake; QubicaAMF reads cord state) detect pinfall by **cord slack/tension** ~0.3–0.5 s after impact. I'd add this as a **secondary confirm**, *not* the primary detector (the camera is already proven at 0/120):
- 10 cheap signals — a micro-switch or hall sensor per take-up that reads "string under tension (pin standing)" vs "slack (pin fell/hanging)" — wired to a spare MCP input bank, read by the same `read_grippers()`-style helper that already exists in `MachineIO`.
- Use it three ways: **(a)** disagreement gate — if camera and tension masks disagree by >1 pin, log + flag the frame `modified`-style for desk review (reuses the existing manual-correction path), rather than auto-scoring a contested frame; **(b)** **camera-down fallback** — if `detect_lane()` returns `None`, fall back to the tension mask instead of going fully manual, keeping the machine auto-scoring through a camera glitch; **(c)** a **latch sanity check** before the lower stroke. This is a *nice-to-have*, FLAGGED as optional for the 10k-cycle bench rig — the camera alone satisfies both scoring and latch decisions, and a tension harness is 10 more sensors to maintain. I'd build the hooks (the input map + a `read_tension_mask()`), leave them unpopulated until the bench shows the camera needs a backstop.

---

### 6. Fail-safe & manual fallback (all reused mechanisms)

- **Camera `None` ⇒ never a bogus score.** Already the documented contract: detector-not-ready / capture-fail / lane-not-on-camera all return `None`, and the daemon "treats None as 'no pin data' → falls back to the manual desk-score path… never a bogus auto-score." The machine still cycles (using last-known-standing or full-rack), and desk staff key the count via the existing `correct_frame`/`set_frame_bowls` path.
- **Power-down rule (reused):** power-restore → `MANUAL_INTERVENTION`, drives nothing until a deliberate operator re-arm. Identical to the 82-70 FSM's `power_restore()`/`first_ball_zero()`.
- **RP2040 health-loss safety trip (reused verbatim):** the daemon's existing logic forces motion outputs OFF, clears relay latches, latches `MANUAL_INTERVENTION`, and refuses to auto-rearm — the Codex-found stale-latch fix carries straight over.
- **NE555 watchdog coupling (reused):** `poll()` kicks the watchdog; a stalled control loop stops kicking ⇒ NE555 drops the relay rail ⇒ wagon/sweep/latches de-energize. **Latch fail-safe note:** wire the holdback solenoids so **de-energized = string free to lift** (fail to "pins go up / out of the way"), so a watchdog drop can't strand a pin half-set in the ball's path. **FLAG:** confirm this fail direction with Subsystem 3's latch hardware — it's a safety-relevant polarity choice.
- **Motion backstop (reused):** `MAX_MOTION_S` per motion → FAULT + motors off, exactly as in `cycle_control_8270.poll()`. For the string FSM each sub-step (UP/sweep/DOWN) gets a bound; a wagon that never hits its limit (jam, **string tangle** — the #1 risk) faults fast instead of stalling the motor.
- **Safety rail (Subsystem 8, untouched):** the non-bypassable 6-condition relay-enable rail still gates every motor energize downstream of the FSM; `io.interlock_ok()` stays a *secondary* software echo.

---

### Parts table

This subsystem is software; "parts" are the few sensors the FSM/detection reads and the compute it runs on. Actuators (wagon motor, latch solenoids) and the camera/dongle are owned by Subsystems 3/5/6 — listed here only at the interface, not double-counted in cost.

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Overhead scoring camera | Existing QubicaAMF T-Camera (720×576) **or** USB global-shutter cam (e.g. ELP 1080p) | 1 | $0 (owned) / ~$45 new | One per pair already in the design; Track A calibrated to it. New deck ⇒ re-shoot `empty_ref.png` + refit `PIN_SPOTS_PX`. |
| Capture dongle | VIXLW USB analog-capture (owned) — only if reusing the analog T-Camera | 1 | $0 (owned) | If a USB cam is used instead, dongle drops out. |
| Wagon limit switches | HOME (down) + TOP (up) snap-action, e.g. Omron D4N / SS-5GL | 2 | $8 | Fast inputs on the RP2040; replace the 82-70 cam ring. |
| Sweep-home limit switch | Snap-action lever | 1 | $4 | Sweep return detect. |
| Ball-detect beam | Reuse DIELL/Taiss-through-opto chain (already validated) | 1 | $0 (owned) | Cycle trigger; identical to Phase 8a. |
| String-tension sensors *(optional, §5)* | Micro-switch or hall per take-up | 10 | $20 | Secondary cross-check only; hooks built, populate later. Spare MCP input bank. |
| RP2040 co-processor | Existing rev-C board cell | (incl.) | $0 (Sub 6) | Fast limits + ball beam + motion backstop. Reused. |
| Raspberry Pi (per pair) | Existing Pi 4/5 lane node | (incl.) | $0 (Sub 6) | Runs daemon + FSM + scoring + camera. Reused. |
| **New software** | `cycle_control_string.py` (~250 LOC) + daemon/link glue (~40 LOC) + latch-mask plumbing | — | $0 (labor) | The only genuinely new code; ~1–2 days incl. the `RecordingIO` sim test, mirroring the existing FSM's self-test harness. |
| **Reused software** | scoring engine, `pin_detect`, `camera`, `controller_io`, `rp2040_link`, `controller_daemon`, server/state-store | — | $0 | ~85–90% of subsystem code mass. |

**Subsystem-7-specific new sensor cost: ~$24 (required) / ~$44 (with optional tension harness).** Everything else is owned or counted under Subsystems 3/6.

---

### Risks

- **Settle-window tuning is empirical.** `SETTLE_S` for the string deck is a guess until measured on the rig — too short and the camera reads a still-rocking pin as down; too long and cycle time bloats. Mitigation: instrument the dwell, sweep `SETTLE_S` over the first few hundred cycles. **FLAGGED unknown.**
- **Hanging-deadwood occlusion.** A knocked pin dangling on its string could partly occlude a *standing* pin's cap ROI from the overhead view, flipping a standing pin to "down" in the mask → wrong score *and* wrong latch (machine fails to re-present a pin that's actually up). Track A's tight cap-ROI design mitigates bleed but not hard occlusion. This is the string-specific detection risk the 82-70 didn't have (its grippers touched the pins directly). **Mitigation:** the optional tension cross-check (§5) catches exactly this disagreement.
- **Latch-mask ↔ string mapping must be bulletproof.** A swapped bit re-presents the wrong pin (e.g., stands the 6 instead of the 10). Same failure class as the BS/OS and M1/M2 channel swaps Codex already caught on rev-B. **Mitigation:** reuse the existing netlist-vs-`*_MAP` regression assert (`controller_io.py __main__`) for the 10 latch channels; verify with deliberate single-pin leaves (7-pin, 10-pin) at bring-up.
- **Camera-only auto-score during a tangle.** If a string tangles and a pin sets off-spot but still upright, the camera (fixed spots) may read it "down" or miss it, while the machine thinks it set fine. Scoring drifts from reality silently. **Mitigation:** off-spot detection (a pin present but displaced) is a future detector enhancement; near-term rely on desk correction + tension disagreement flag.
- **Mirror/numbering binding unverified for the new deck.** `MIRROR`/`DECK_TO_LANE` were fixed for the 82-70 camera mount; a new mount can flip handedness, silently mislabeling asymmetric leaves (7 vs 10) — detection unaffected, *reported pins* wrong. **Mitigation:** the `mirror_numbering()` swap already exists; confirm with a known corner leave.

### Open questions

- **Actual string-deck `SETTLE_S` and per-sub-step `MAX_MOTION_S`** — need bench measurement of lift/sweep/lower durations on the rig before these constants are real (currently 82-70 placeholders).
- **Does the bench want the optional tension harness from day one,** or camera-only until a failure mode forces it? My recommendation: build the hooks, run camera-only first; the 10k-cycle test will reveal whether the camera needs the backstop. (Subsystem 10 / FMEA should weigh in.)
- **Latch fail-safe polarity** — confirm with Subsystem 3 that de-energized solenoid = string free to lift (so a watchdog/rail drop never strands a pin in the ball path). Safety-relevant; needs an explicit agreement at the Sub-3↔Sub-7 interface.
- **One camera read enough, or confirm-read?** The 82-70 read pins once at a cam angle. For scoring integrity under a rocking string deck, do we want a 2-frame agreement (read, 150 ms, re-read, require match) before committing the score + latch? Cheap to add in `DETECT_DWELL`; decide after seeing settle behavior.
- **Where does `LaneScoring`/`CrossLaneScoring` get instantiated in the string daemon?** Track A's scoring object lives on the async server/node side, the FSM on the sync control side. For a 1-lane bench rig, simplest is to give the FSM a direct `scoring` handle (as sketched) and let the existing server read the same object; for production this is the same "unify control + scoring path at bench" TODO already flagged in `controller_daemon.py` (`TODO(server)`). Needs an explicit wiring decision, but it's plumbing, not new logic.

**Source grounding (web):** Brunswick StringPin PMI = per-string solenoid + string brake + pinfall switch, tension read ~0.3–0.5 s post-impact, set cycle = lift standing pins / sweep deadwood / lower ([flyingbowling.com](https://www.flyingbowling.com/article/how-does-a-bowling-string-pinsetter-machine-work.html), [Brunswick StringPin Operations Manual](https://brunswickbowling.nyc3.cdn.digitaloceanspaces.com/production/document-library/Operation-Manuals-User-Guides/Pinsetters/StringPin/Operations_Manual_StringPinV2_55-900004-000_En_Rev-08-19-21.pdf)); QubicaAMF EDGE String uses **Q-Vision cameras** for scoring (validates camera-primary) + Adaptive String Length ([qubicaamf.com EDGE String](https://www.qubicaamf.com/bowling-products/pinspotters/edge-string)). These confirmed the cycle shape and the camera-vs-tension detection split; the FSM/channel mapping above is grounded in the repo's own `cycle_control_8270.py`, `controller_io.py`, `pin_detect.py`, and `controller_daemon.py`.

**Relevant files (absolute):** `C:\Users\Dylan DeYoung\wsl-lane-nodes\lane_node\cycle_control_8270.py` (the FSM this replaces), `…\lane_node\controller_io.py` (io contract + channel-map regression guard to reuse for latch channels), `…\lane_node\pin_detect.py` + `…\lane_node\camera.py` (Track A, reused as-is, recalibrate spots), `…\lane_node\rp2040_link.py` (fast-edge link, swap cam dispatch→wagon/sweep limits), `…\lane_node\controller_daemon.py` (per-pair loop, swap the FSM import + `_slow_actions`), `…\wsl_scoring_engine.py` (`record_ball(mask)` consumed unchanged). New file to author: `…\lane_node\cycle_control_string.py`.

---

## Subsystem 8 — Safety Architecture (String Machine, rev-C)

### 0. Framing: what changes, what survives

The team already shipped and bench-validated a hardware safety system for the AMF 82-70 retrofit (Phase 8a/8b): a **non-bypassable, fail-open relay-enable rail** that is a hardware AND of six conditions, an **NE555 monostable watchdog** that watches the *Pi*, an **RP2040_OK** rail-permission line that is fail-safe-LOW (Hi-Z → external 100k pulldown → rail dead), a software **power-restore → MANUAL_INTERVENTION** rule, and an honest **welded-contact limitation** (the rail drops coils; the master breaker is the final stop). That architecture is correct and I am **reusing it wholesale**. The board is the same parameterized KiCad block library; a string machine is a **channel re-mix on the same cells (a "rev-C")**, not a new safety philosophy.

What *changes* for the string machine is the **physical hazard set** and **what feeds the interlock conditions**. The 82-70's irreducible hardware safety was the **TB + SC cam interlock** (two cams wired in parallel in the 24 V relay-control path that drop both motor relays when the sweep and spotting table are on a collision course). A string machine **has no sweep-vs-table collision** — there is no free-fall sweep arm, no heavy spotting table cycling under a moving sweep. So **the TB/SC interlock has no analog and must be *replaced*, not ported.** Section 6 defines its replacements. The rest of the rail (watchdog, ARM, RP2040_OK, E-stop chain, motion-timeout) maps over almost unchanged.

> **Scope honesty:** this is a 1-lane proof-of-mechanism aimed at a 10,000-cycle durability run on a bench / spare cabinet. It is **explicitly not a certified product**. I therefore design to a *defensible, fail-safe, single-operator-bench* standard and **flag every place** where a real 32-lane public install would need third-party functional-safety review (UL 1042 "Bowling Pin Setting Equipment", ISO 13849 / EN 60204-1, a notified body). Building it safely for the bench is in scope; certifying it is not, and I will not pretend otherwise.

---

### 1. Hazard enumeration (the string machine, honestly)

A string machine is *lower-energy* than a free-fall 82-70 (no flying sweep, no 3.5 lb pins free-falling onto a spotting table, no heavy carpet/pit), but it is **not zero-energy**. The lift/take-up motors pull ten strings hard enough to hoist ten 3.5 lb pins plus de-tangle "shake," and the lift bar / take-up mechanism has real pinch points. Below is the hazard register that the interlock conditions in §4–§6 must cover. (Severity/likelihood are bench-prototype judgments, not a certified risk assessment.)

| # | Hazard | Mechanism / energy source | Who's exposed | Sev (bench) | Mitigation owner |
|---|---|---|---|---|---|
| H1 | **Lift-bar / take-up pinch & crush** | Lift bar and string take-up spools/reels moving up under motor torque; fingers/hand between bar and frame, or caught in a string wrap on a spool | Operator reaching into the deck/superstructure during a cycle | High | Deck-access guard interlock (§6.2) + motion-timeout + ARM + E-stop |
| H2 | **String entanglement of a limb** | A hand/sleeve caught in a string as the take-up winds; ten strings under tension converging to the overhead | Operator at deck or pit during motion | High | Deck-access guard interlock (§6.2) + low torque limit / over-current trip (§5) + E-stop |
| H3 | **Reach-into-pit during cycle** | Person reaching over the pit cushion to retrieve a ball / clear a pin while machine cycles | Bowler at foul line is far; operator at pit is the real case | Med-High | Pit/rear guard interlock (§6.3) + E-stop + the cycle only triggers on ball-detect (§7 cross-ref) |
| H4 | **Lift over-travel** | Take-up motor commanded up and **never stopped** (cam/limit miss, FSM hang, relay welded) → strings over-wound, pins jammed into the overhead, mechanism/motor damage, possible string snap-back | Equipment first; snap-back is a projectile risk to nearby person | Med | Up/home limit switches (§6.1) + RP2040 motion-timeout (§5) + over-current trip |
| H5 | **String tangle → jam → over-torque** | Two+ pins tangle on the way up; tension spikes; motor stalls or de-tangle "shake" thrashes | Equipment; secondary snap-back risk | Med | De-tangle bar+switch (§6.4) + over-current/stall trip (§5) + tangle-retry limit then fault |
| H6 | **Stall / motor over-current / over-temp** | Mechanical bind, foreign object, bearing seizure → locked-rotor current, winding heat | Equipment + fire risk on a long stall | Med | Hardware over-current trip + thermal (§5) feeds the rail; FSM motion-timeout |
| H7 | **Unexpected motion on power restore** | Mains blip mid-cycle; on restore a stale relay state or a "resume" drives the lift with someone's hand in it | Operator who reached in *because* it looked dead | **High** | **Power-Down rule** (§3): fail-safe-off, require deliberate operator zero before any motion |
| H8 | **Welded / stuck relay contact** | An output relay welds closed; dropping the coil rail does **not** open it; that motor keeps running | Operator (motion they think is stopped) | Med-High | Master-contactor/breaker as final stop (§4.5) + contact-state telemetry + snubber/MOV to reduce weld odds |
| H9 | **Ball-return / up-lane pinch** | If a powered ball-return / accelerator is in the prototype, its rollers/belt are a pinch/entanglement point | Operator at pit or ball door | Med | Ball-return on the rail + guard interlock on ball-door access (§6.3); *flag*: ball-return mechanism is Subsystem 5's design |
| H10 | **Electrical shock** | Machine control voltages (24 VAC wetting / 12 VDC / mains to the motor contactors); the board's isolated field-wetting supply keeps logic clean but field side is live | Operator/technician at terminals | Med | Reuse rev-B isolation domains (logic / machine-sense / machine-output kept separate, isolated wetting); LOTO before any terminal work |
| H11 | **Stored-energy on stop** | A pin held aloft by string tension; a partially-wound take-up; gravity returns pins when power drops | Operator who opens a guard expecting "frozen" | Low-Med | Pins falling on string is *low* energy (that's the whole point of string); document that "power off = pins may drop to deck" in LOTO |
| H12 | **Two-hand bypass / defeated guard** | Operator tapes the guard switch closed to work faster | Operator | Med | Use a *coded/keyed* guard switch where practical; telemetry logs guard state; bench culture — but honestly, defeat is always possible, hence E-stop + LOTO are the real backstops |

**The #1 *durability* risk (string tangle) is mostly a Subsystem-2/3 mechanical problem, but it has a safety face here: a tangle that over-torques the lift (H5→H6) or causes a string snap-back (H4).** My job is to make sure a tangle **trips to a safe stop** (de-tangle retry → over-current/timeout fault → rail drop), never an open-ended over-torque.

---

### 2. Design principles (carried from the proven rev-B contract)

1. **Fail-open / de-energize-to-safe.** Every safety condition's *de-asserted* state = motion-disabled. Loss of power, loss of a wire, loss of the Pi, loss of the RP2040, loss of an interlock loop → **all motion-output relay coils lose their enable supply → relays drop to mechanical-open → motors can't be commanded on.** No condition requires an active signal to *stop*.
2. **The board is never the only safety device.** The machine's own master contactor / breaker and a hardwired E-stop loop sit upstream of the board and remain the final physical stop (they can open a welded board-relay contact; the board cannot — §4.5).
3. **Software cannot bypass the hardware rail.** The Pi/FSM ARM line is *one input* to a hardware AND. Even a fully compromised Pi can only *drop* the rail, never force it on past a false watchdog/RP2040/interlock condition.
4. **Telemetry must never gate safety.** (Direct carryover of the RP2040 firmware rule: UART TX is a non-blocking ring; RP_OK drive + watchdog kick run every loop pass regardless of UART. A dead link cannot enable unsafe motion.)
5. **Bounded motion.** No guarded motor may run unbounded: a position limit *or* a max-run timer *or* an over-current trip must end every motion. (Strings make this easy — every productive motion is "wind up to the UP limit" or "lower to the DOWN/home limit," both naturally bounded by a switch.)

---

### 3. What replaces the 82-70 cam-stops, and the Power-Down rule

**82-70 cam-position stops were controller LOGIC** (read cam → drop relay), with the TB/SC parallel interlock + regenerative relay-braking as the hardware backstop. On the string machine the equivalent productive motions are **lift-up** and **lower/home**, and the natural stops are **mechanical limit switches** (exactly what Brunswick StringPin uses: *Home switch → Pins-UP switch → Pins-Solenoid switch → Home*, monitored in sequence — see §6.1). So:

- **Position stops** become a small set of **home / up / set (solenoid) limit switches** read fast by the RP2040 (same opto-input cell as the 82-70 cams). The FSM stops a motor when its target limit asserts; the RP2040 enforces a **max-run timeout** if the limit never comes.
- **The collision interlock (TB/SC) is replaced** by §6's deck-access guard + pit/rear guard + the de-tangle/over-torque trips. There is no sweep-vs-table geometry to protect, so the *replacement is human-access protection and over-travel protection*, not machine-vs-machine.

**Power-Down rule — keep it verbatim in behavior.** The 82-70 MP feature: after *any* mains loss while in "Bowl," **no machine motion on restore** until a deliberate **First-Ball-Zero** (manual intervention). The FSM already implements this (`power_restore()` → `State.MANUAL_INTERVENTION`, drives nothing until `first_ball_zero()`), and the rev-B ARM line enforces it in hardware (ARM is de-asserted in MANUAL_INTERVENTION, so the rail is dead regardless of any stale relay command). This directly kills **H7**, the highest-severity "someone reached in because it looked dead" hazard. **Do not weaken it into an auto-resume** for the prototype.

---

### 4. The rev-C relay-enable rail (re-spec)

Same topology as rev-B §4: a **series pull-down chain** (a hardware AND) that supplies/returns the **on-board motion-output relay coils**. If any link opens, the coil enable collapses and every motion relay drops. The Pi commands *which* relay to energize over I²C/MCP; the rail decides *whether any* relay is *allowed* to energize.

**Required series conditions (rev-C):**

| # | Condition | Source | Fail-safe default | Replaces / maps to (82-70) |
|---|---|---|---|---|
| C1 | **Watchdog OK** | NE555 monostable, kicked by Pi GPIO every ~1 s; ~10 s timeout | false (no kick → open) | unchanged (the "controller-level sibling," now formalized in hardware) |
| C2 | **ARM OK** | Pi ARM GPIO, asserted only after operator-safe state (cleared MANUAL_INTERVENTION) | false | the Power-Down / manual-intervention gate |
| C3 | **RP2040 OK** | RP2040 GP2 rail-permission, HIGH only when healthy; Hi-Z→100k pulldown→dead | false on reset/boot/hang/fault | unchanged; also carries motion-timeout (§5) |
| C4 | **Motion-stop OK** | RP2040 immediate-drop path on over-travel/over-run (the rev-B "cam-stop OK") | false on reset/fault | **was** cam-stop enforcement; **now** lift over-travel / motion-timeout enforcement |
| C5 | **Guard interlock OK** | Hardware NC loop: deck-access guard + pit/rear guard + ball-door guard in series | false/open | **REPLACES TB/SC** — human-access guarding instead of sweep-vs-table |
| C6 | **E-stop / master-chain OK** | Hardware NC loop: E-stop button(s) + master contactor/CIS sense, in series | false/open | the Stop/CIS/master-breaker chain (string machines use ≥2 E-stops: front + rear) |

> **Wiring note (carryover from rev-B):** C5 and C6 are *hardware NC loops* landed on `J_SAFETY` and put **in series with the relay-enable rail via a pass-FET**, not merely read as MCP/RP2040 inputs (the rev-B audit explicitly caught and fixed a "false-green" where the interlock was bypassed instead of in-series). The board *also* senses them on inputs for telemetry/FSM-avoid-bad-state, but the **authoritative** drop is the series loop. This is the single most important structural rule and it ports unchanged.

**Per-output rail requirement (rev-C):** every motion output is on the rail. For the string machine the motion outputs are smaller than the 82-70's seven:

| output | string-machine function | on rail? | notes |
|---|---|---|---|
| LIFT (take-up "up") | wind strings to lift pins to the UP limit | **yes** | the primary hazard motor (H1/H2/H4) |
| LOWER / SET | lower/seat pins to deck / drive the set-solenoid | **yes** | bounded by home/set limit |
| SWEEP (guard) | the string-machine sweep/guard bar, if present (light curtain bar) | **yes** | string sweeps are light; still a moving bar |
| BALL_RETURN | up-lane ball return / accelerator, *if* in the prototype | **yes** | H9; *Subsystem 5 owns the mechanism*; DNP until that's decided |
| BE / aux | any continuous back-end (likely none on a string bench) | n/a | 82-70 BE was *not* guarded (continuous); a string bench likely has no BE |

Status lamps (1st/2nd-ball/foul/strike) remain **off-rail** (rev-B §3.3) — not motion-critical.

**Note vs the 82-70:** there is **no regenerative motor braking** to inherit (that was a property of the 82-70's cap-induction motor relays). String take-up motors are typically small DC gearmotors or steppers/servos. **Dropping the rail removes drive; it does not actively brake.** For the lift, that is acceptable because (a) load is light, (b) a gearmotor's gear ratio self-holds, and (c) gravity-return of pins on a string is low-energy (H11). **Flag for Subsystem 3:** if the lift uses a high-inertia or back-drivable mechanism, add a **fail-safe holding brake or self-locking worm gear** so a rail-drop doesn't let the lift bar coast/back-drive onto a hand. I am specifying the *electrical* drop; the *mechanical* hold-on-loss-of-power is their interface (§ interfaces).

---

### 5. Jam / over-current / over-travel trips (the string-specific safety sensing)

These three feed C4 (and latch a fault that also drops C3/RP2040_OK), and are the heart of "a tangle trips safe, never over-torques."

**5.1 Motor over-current / stall trip (hardware-first).**
Each motion motor gets a **hardware current sense** with a fast comparator trip — *independent of firmware*, exactly like the watchdog is independent of the Pi. Implementation: low-side shunt (e.g. 0.05–0.1 Ω) → comparator (LM393 / or an INA-style current monitor with alert) → latches a fault that pulls the rail. This catches **H5/H6** (tangle stall, foreign-object bind, bearing seizure) even if every line of code is wrong. Trip set above worst-case lift current (ten pins + de-tangle shake) with margin, measured on the bench before release. This is the rev-C analog of "motor overload" (Brunswick Error 04) but made a *hardware rail input*, not just an FSM error code.
*Open question:* exact trip current and motor type are Subsystem 3's; I'm specifying the *cell* and that it must be hardware-latching into the rail.

**5.2 RP2040 motion-timeout (firmware backstop, already built).**
The rev-B firmware's **MAX_MOTION_MS** backstop ports directly: the Pi marks a guarded motor RUNNING over UART (`RUN LIFT`), and if it isn't STOPped within the timeout, the RP2040 latches a fault and drops RP_OK → rail dead. For the string machine, **set per-motion timeouts from measured lift/lower times** (a lift to the UP limit is ~1–3 s; pick measured + margin). This catches **H4** (limit-switch miss / FSM hang). Already coded; only the constant changes.

**5.3 Lift over-travel / home limit switches (hardware end-stops).**
Add **hardwired NC limit switches** at the mechanical extremes — at minimum an **UP-limit** (lift fully raised) and a **HOME/DOWN-limit**. These are read fast by the RP2040 *and*, for the UP-limit specifically, I recommend wiring it **directly into the rail's C4 path** (a true hardware end-stop that drops the lift even if firmware misses the edge), because over-winding strings is the failure that produces snap-back. This is the rev-C replacement for the 82-70's cam-position stops, and mirrors Brunswick's *Home / Pins-UP / Pins-Solenoid* switch sequence. The FSM uses the limit *edges* as its normal stop events (same opto-input cell as the cams); the hardware UP-limit is the backstop.

**5.4 De-tangle, bounded.** See §6.4 — the de-tangle "shake" is allowed, but **bounded** (retry count, then fault), so a persistent tangle can never thrash indefinitely into an over-torque.

---

### 6. Interlock conditions in detail (what gates motion)

**6.1 Position / over-travel limits (C4).** Home, UP, and SET limit switches as in §5.3. NC, opto-isolated, fast-read by RP2040; UP-limit also hard-wired into the rail. *FSM stop events; hardware backstop.*

**6.2 Deck-access guard interlock (C5, primary TB/SC replacement).** A **coded/keyed safety interlock switch** (or a safety light-curtain for the prototype if budget allows) on the panel/cover an operator must open to reach the lift bar / take-up / deck. Opening it **opens the C5 NC loop → rail dead → all motion stops**. This is the human-access guard that *replaces* the sweep-vs-table collision interlock. For the bench, a **mechanical guard-door switch wired NC in the C5 loop** is sufficient and matches how EDGE String/StringPin gate access ("guards and covers prevent operator access; all guarding must be in place to operate"). *Recommend a keyed/coded switch (e.g. an interlock that needs the cover present) over a plain microswitch to make casual defeat harder — but acknowledge defeat is always possible (H12), which is why E-stop + LOTO are the real backstops.*

**6.3 Pit / rear / ball-door guard interlock (C5, series).** The pit area and the ball-door/ball-return access also land in the C5 series loop, so reaching into the pit or the ball return (H3/H9) drops the rail. EDGE String's model — *"interventions from behind the machine, from the floor," integrated guarding, machine boundary* — is the target. For the 1-lane bench this can be one guard panel covering the pit/return.

**6.4 De-tangle bar + switch (bounded retry, then fault).** Reuse the standard string-machine **de-tangle bar**: when pins tangle on the way up, string tension lifts a bar that actuates a switch; the FSM runs a **bounded** up/down "shake" sequence (drive motor off/on) to clear it. **Bound it:** N retries (Brunswick uses ~30 before a Tangle fault) then **latch a fault → rail drop** and require operator intervention. The de-tangle motion is itself **still on the rail and still under the over-current trip (§5.1)** — the shake cannot exceed the torque limit. This makes the #1 durability risk *fail safe*.

**6.5 E-stop loop (C6).** **At least two** hardwired E-stop buttons (string machines standardize on front + rear), NC, in series in the C6 loop, latched (twist-to-release). Pressing any E-stop opens C6 → rail dead. For a real install the E-stop should also drop the **master contactor** (so it survives a welded board relay — see §4.5); on the bench, wiring E-stop into both the rail *and* the upstream motor-supply contactor gives that property cheaply.

**6.6 Master / CIS sense (C6).** Sense of the upstream master contactor / control-interlock so the board knows the machine is "live"; in series in C6 so loss of the master chain also drops the rail.

---

### 7. Fail-safe behavior (state-by-state)

| Event | Immediate hardware effect | FSM / software effect |
|---|---|---|
| Pi process dies / hangs | NE555 times out (~10 s) → rail dead → all motion relays open | n/a (Pi is gone) |
| RP2040 hangs / resets / brownout | GP2 Hi-Z → 100k pulldown → RP_OK LOW → rail dead | Pi sees lost heartbeat → drops ARM |
| Over-current / stall (H5/H6) | Hardware comparator latches → rail dead | RP2040 fault telemetry; FSM → FAULT; requires CLEAR from safe state |
| Lift over-travel (H4) | UP-limit (hard-wired) opens lift path; RP2040 motion-timeout latches | FSM → FAULT |
| Guard opened (H1/H2/H3) | C5 loop opens → rail dead **instantly** | FSM notes guard-open; will not re-ARM until closed |
| E-stop pressed | C6 loop opens → rail dead (and master contactor drops, recommended) | FSM → FAULT/STOPPED; latched until release + operator reset |
| Mains blip / power restore (H7) | Rail comes up dead (ARM defaults false) | FSM → MANUAL_INTERVENTION; **no motion** until First-Ball-Zero |
| Welded relay contact (H8) | Rail-drop does **not** open it | Master contactor/breaker = final stop; contact-state telemetry flags it |
| UART link dies | Nothing unsafe (RP_OK + watchdog independent of UART) | FSM faults on lost heartbeat → drops ARM |
| Tangle (H5) | (within torque limit) | Bounded de-tangle retries → if unresolved, FAULT → rail drop |

**Recovery is always operator-gated:** clearing a FAULT requires the FSM to be in a known-safe (zero/home) state, then a deliberate operator action (the RP2040 only accepts `CLEAR` from a safe state; the FSM re-enters MANUAL_INTERVENTION and needs First-Ball-Zero). No fault auto-clears into motion.

---

### 8. Pinch / crush risk — addressed honestly

The lift bar / take-up is a genuine **pinch and entanglement** hazard (H1/H2), and I won't hand-wave it:

- **Primary control is the guard interlock (§6.2): you should not be able to reach the moving lift bar without opening a guard that kills the rail.** That is the correct hierarchy-of-controls answer (guard out the hazard, don't rely on procedure).
- **Where a guard can't fully enclose** (service access during bring-up), the controls are: E-stop within reach, the Power-Down rule (no surprise restart), the over-current trip (a limb in a string spikes torque → trip — though a small limb may not trip before injury, so this is a *backstop, not a primary*), and **LOTO discipline** for anything beyond a Level-1 reach-in. I am explicitly **not** claiming the over-current trip protects fingers — it protects the *machine*; the *guard* protects the *person*.
- **Mechanical hold-on-power-loss is a Subsystem-3 interface** (§4 note / interfaces): if the lift can back-drive, it needs a self-locking gear or fail-safe brake so a rail-drop doesn't let it coast onto a hand. I flag this as a hard requirement on their mechanism, not something the electrical rail can solve.
- **Two-hand / coded guard:** for the prototype I recommend a coded/keyed interlock over a defeatable microswitch, but I state plainly that **any guard can be defeated (H12)** — so E-stop reachability and LOTO are the non-negotiable backstops, and the bench must run a **single-operator, eyes-on** culture during the 10k-cycle run (no reaching in while it's armed).

**For a real 32-lane public deployment** (out of scope here, flagged): this needs a proper ISO 13849 PL-rated assessment, safety-rated interlock switches and a safety relay/controller (not a hobby NC loop), UL 1042 compliance, and a notified-body review. The bench architecture is *designed to be upgradeable to that* (the rail is already fail-open and non-bypassable), but it is not that today.

---

### 9. Reused vs new (summary for the BOM/aggregation)

**Reused unchanged (already designed/bench-proven):** NE555 watchdog cell + Pi kick loop; RP2040_OK fail-safe-low (100k pulldown) + motion-timeout firmware; the series pull-down rail + pass-FET on `J_SAFETY`; isolation domains (logic / machine-sense / machine-output) + isolated field wetting; snubber/MOV on every motion output; power-restore→MANUAL_INTERVENTION + operator-gated CLEAR; welded-contact→master-breaker-final-stop honesty; contact-state + RP_OK telemetry.

**New for rev-C (this subsystem's additions):** hardware **over-current/stall trip per motor** into the rail (the big one); **home/UP/SET limit switches** (UP-limit hard-wired into rail); **deck-access + pit/rear + ball-door guard interlock loop** (replaces TB/SC); **dual latched E-stops** into the master-contactor + rail; **bounded de-tangle** logic; channel re-mix (fewer motion outputs: LIFT/LOWER/SWEEP/[BALL_RETURN]) vs the 82-70's seven.

---

## Subsystem 9 — Bill of Materials & Cost Estimate (one-lane prototype)

**Scope:** Complete parts list for ONE bench/cabinet lane that runs the set-clear cycle well enough to attempt a 10,000-cycle durability experiment. Costs are rough single-unit prototype prices in USD (retail/small-qty, not volume), late-2026. The control stack and camera are **REUSED / already owned** — broken out separately and **excluded from the NEW-spend total**. I stayed in subsystem 9: I price what the other subsystems specified; where they haven't frozen a number, I use a placeholder and flag it.

**Costing ground rules**
- Prototype, single unit, retail-ish. No tooling amortization, no labor (build labor estimated separately, not in cash BOM).
- "Reused" = hardware the team already designed/bought (Pi, RP2040, custom PCBA, camera, capture dongle). Listed at replacement cost for context, **not** added to new-spend.
- Mechanical numbers carry the most uncertainty (±40-60% at this stage) because the lift carriage, string-latch assemblies, and ball-return are custom fab, not catalog drop-ins. I flag the cost drivers explicitly.
- Subsystem 3 (lift/set) and Subsystem 8 (safety) are stated as "already done" in the design — I price the *physical hardware* those subsystems consume (motor, belt, rails, carriage, safety contactor/E-stop), because a BOM must include them even if the engineering is locked. Where Subsystem 3 already named a motor class (250-400 W BLDC + timing belt, 0.9 m stroke, ~255 N), I cost to that spec.

---

### A. Structure / frame (NEW)

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Aluminum extrusion, 40×40 T-slot | 4040 profile, ~12 m total cut for cabinet frame + gantry uprights | 12 m | $220 | ~$15-20/m small-qty (8020/VEVOR/OpenBuilds class). Cabinet is ~1.1 m wide × ~1.2 m deep × ~2.4 m tall. |
| Extrusion, 20×40 secondary | Cross-bracing, deck supports, camera mast | 6 m | $80 | Lighter sections where load is low. |
| Corner brackets / gussets, T-nuts, joining plates | Cast + 90° brackets, ~60 corners; M5/M6 T-nuts ×300; bolt packs | lot | $180 | Connection hardware dominates count, not cost. Buy T-nuts in bulk (100-packs). |
| Floor casters / leveling feet | M12 leveling feet ×4 + locking casters ×4 (bench mobility) | 1 set | $70 | Optional but useful for a bench mule. |
| Steel base channel / unistrut for cabinet feet | If anchoring to a real pinsetter cabinet footprint | lot | $90 | May be free if reusing a scrapped 82-70 cabinet shell — see open questions. |
| **Subtotal — frame** | | | **~$640** | |

---

### B. Lift / set mechanism — the "string wagon" carriage (NEW)

Subsystem 3 froze this as: common-lift carriage on linear rails, ~250-400 W BLDC gearmotor + timing belt, 0.9 m stroke, ~255 N design load, no spotting cup. I cost to that.

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| BLDC gearmotor | 300-400 W, 24-48 V, integrated planetary gearhead, ~50-100 rpm output, holding capable | 1 | $260 | Mid-grade industrial BLDC w/ gearhead. NEMA-34 closed-loop stepper (~$180) is a cheaper alt if Subsystem 3 will accept it — **flag**: their spec says BLDC. |
| BLDC driver / ESC | Matched controller, 24-48 V, with brake/hold, step-dir or PWM, fault output to the safety rail | 1 | $120 | Must expose an enable/fault line the rev-C relay rail can gate (Subsystem 6/8 interface). |
| Linear rail set | 2× profiled rail HGR20, ~1.0 m, with 2 carriage blocks each (4 blocks total) | 1 set | $300 | HGR20/HGH20 class, ~$130-160/rail w/ blocks at this length. 0.9 m stroke needs ~1.0 m rail. |
| Timing belt + pulleys | GT3/HTD-5M closed or open loop, ~2.2 m run, 1 drive + 2 idler pulleys, tensioner | 1 set | $90 | Open-ended belt cut to length + clamp at carriage is simplest for a vertical lift. |
| Carriage plate / "wagon" weldment | Custom — laser-cut + folded 3-4 mm steel or 10 mm Al plate, holds the 10 string-latch assemblies + guides | 1 | $350 | **MAJOR COST-UNCERTAINTY ITEM.** Fab quote, single-piece. Could be $200 (DIY waterjet-from-stock) to $600 (shop weldment). |
| Counterbalance (gas spring or constant-force) | 1-2 gas struts to offload carriage dead weight from the motor on a 0.9 m vertical | 2 | $60 | Reduces motor/belt duty over 10k cycles; cheap insurance. |
| Drag chain / cable carrier | For the string-latch solenoid wiring + sensor cable to the moving carriage | 1 | $45 | Needed because the carriage carries the 10 latch actuators (per Subsystem 2 interface). |
| Limit / home switches | 2× inductive or mechanical end-of-travel + 1 home, feed RP2040 fast path + HW end-stop | 3 | $35 | Subsystem 7/8 interface. |
| **Subtotal — lift/carriage** | | | **~$1,310** | |

---

### C. String management & take-up — the ten latch assemblies (NEW)

This is Subsystem 2's hardware. I price the per-string latch/holdback + reel/guide hardware they specified (per-string latch, NO spotting cup, pins land by cord geometry). Ten identical channels; I cost one and ×10, plus shared guides.

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Per-string latch/holdback actuator | Small pull solenoid OR servo per string to hold/release individual cords (release = "this pin should stand") | 10 | $200 | ~$18-22 ea (24 V pull solenoid, ~10-20 N) or hobby/metal-gear servo. **Cost-uncertainty: depends on Subsystem 2's final holdback choice** — solenoid-per-string vs. one shared declutch. I cost solenoid-per-string (worst case for BOM). |
| String reel / take-up spool + light spring or constant-tension | Per-string take-up so slack is managed each cycle; spring-return or constant-force coil | 10 | $130 | ~$13 ea. **#1 RISK driver (tangle).** Cheap parts, but the geometry/guide design is where the durability risk lives, not the cash. |
| String guide eyelets / ceramic thimbles | Wear-resistant guides at deck head holes + carriage + reel, to fight abrasion over 10k cycles | 30 | $90 | Ceramic fairleads (~$3 ea) strongly recommended for the 10k test — string abrasion is the wear point. |
| Latch mounting sub-plate + hardware | Bracketry to mount 10 latches in regulation 12-in triangle on the carriage | 1 | $120 | Custom laser-cut plate + standoffs; sets on-spot geometry. |
| Cord (see Subsystem 4 also) | Pinsetter string, braided UHMWPE/nylon, ~6 m × 10 + spares | 70 m | $60 | Subsystem 4 owns spec; I carry the consumable cost. Spare cord for the 10k test included. |
| Solenoid drivers (if not on rev-C) | 10× low-side FET drivers + flyback — **check Subsystem 6**: rev-C relay outputs are dry-contact G5LE; 10 fast string solenoids likely need a separate small driver board | 1 | $40 | **INTERFACE FLAG:** the reused board has 6 G5LE relay outputs (motion: S/T/SP/BE/M). 10 string latches at cycle speed probably exceed that → a small dedicated solenoid driver PCB or an MCP23017-driven ULN2803 bank. Coordinate with Subsystem 6/7. |
| **Subtotal — string management** | | | **~$770** | |

---

### D. Pins, strings (consumables) & deck (NEW)

Subsystem 4 owns the spec; I carry the cash. Note: **drilled string pins** are different SKUs from free-fall pins (hole through the head/base for the cord).

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| String pins (drilled) | Regulation ~15 in / ~3.5 lb, coated, head/base-drilled for string, USBC-ish geometry | 10 + 2 spare | $220 | New string-type pins ~$15-20 ea; deadwood spares for the 10k test. Used/2nd-grade pins ~$8 ea is a valid prototype cost-down. |
| Pin deck / spot surface | Synthetic deck panel or hardwood w/ 10 spot locations machined to regulation 12-in spacing | 1 | $250 | Could be cut from a scavenged lane-end panel ($0-100) or new synthetic (~$250). **Cost-uncertainty: salvage vs. new.** |
| String exit holes / bushings in deck head | 10 lined holes for cords to pass up to the carriage | 10 | $40 | Part of deck fab; abrasion-lined. |
| Kickback / side guards (short, bench) | Just enough to contain pins/ball on the bench, not full masking | 1 set | $120 | Plywood + laminate is fine for a mule. |
| **Subtotal — pins/deck** | | | **~$630** | |

---

### E. Ball handling & return (NEW)

Subsystem 5 owns it; I carry hardware cost for a **minimal bench return** (a real 32-lane return is out of scope for a one-lane mule).

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Ball-lift / return motor + wheel | Small AC/DC gearmotor + friction accelerator wheel, OR gravity incline only | 1 | $140 | A bench mule can lean on a gravity ramp (near-$0) and skip powered return; I budget a minimal powered lift in case up-lane return is part of the cycle test. **Flag: Subsystem 5 may descope this to gravity → −$140.** |
| Ball trough / track | Steel or HDPE channel, ~3-4 m loop back to a tee | 1 | $160 | Bench-scale; not the full subway. |
| Ball cushion / pit pad | Foam/rubber backstop behind deck | 1 | $70 | Catches the ball + knocked (string-hung) pins region. |
| 1× house ball | 12-14 lb for repeatable cycle testing (a jig/launcher may drive it — see Subsystem 5) | 1 | $45 | One ball is enough for the durability rig. |
| **Subtotal — ball handling** | | | **~$415** | |

---

### F. Electrical / control — REUSED (already owned, NOT in new-spend)

These are listed at replacement cost for context only. The custom PCBA cost is grounded in the team's actual JLCPCB order history (20 boards fully-assembled ~$160-190 ⇒ ~$8-10 bare-board amortized, but **per-unit small-run replacement** including hand-solder parts is higher; I list a realistic single-unit rebuild cost).

| Item | Spec | Qty | Repl. USD | Notes |
|---|---|---|---|---|
| Custom controller PCB (rev-C) | The parameterized block-library board: 32× PC817 opto in, 6× G5LE relay out, 3× MCP23017, NE555 watchdog, RP2040, isolated wetting DC/DC, 6-condition relay-enable rail | 1 | ~$60 | **OWNED design.** Per-unit single-build: ~$10 PCBA share + ~$30-40 hand-solder parts (Phoenix terminals, TMA-0505S, Pico) + handling. A *new* rev-C respin (NRE for the channel-mix change) is one-time and small — flagged below. |
| Raspberry Pi 4/5 (lane node) | 4 GB, in DIN enclosure | 1 | $80 | OWNED. |
| RP2040 (Pico) co-processor | On-board or stamp module | 1 | $5 | OWNED (part of rev-C). |
| Overhead scoring camera | Existing QubicaAMF T-VISION PAL camera (difference-from-empty "Track A" — DONE) | 1 | $0 | OWNED; reused in place. Pi Camera HQ (~$50) is the drop-in if a fresh camera is wanted for the bench. |
| USB capture dongle | VIXLW composite→USB (Track A pipeline) | 1 | $0 | OWNED. |
| **Subtotal — reused control stack** | | | **~$225 (context only)** | **Excluded from new-spend total.** |

---

### G. Electrical — NEW spend (power, wiring, field I/O the mule still needs)

The board is owned, but a standalone bench lane still needs its own power supplies, motor power, wiring, and field connectors.

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Motor PSU | 48 V / ~10 A switching supply for the BLDC lift | 1 | $90 | Sized to the 300-400 W lift motor + margin. |
| Logic / field PSU | 24 V / 5 A (string solenoids + wetting) + 5 V / 3 A (Pi/logic), DIN-rail | 1 | $80 | The board's isolated wetting DC/DC runs off this 5 V. |
| Solenoid driver board (if needed) | ULN2803/FET bank for the 10 string latches (see C interface flag) | 1 | $40 | May be absorbed into rev-C; carried here so the total is honest. |
| DIN rail, enclosure, terminal blocks, breakers | Control box for a bench mule | 1 lot | $160 | NEMA box + DIN + Phoenix terminals + a 2-pole breaker. |
| Wiring / harness / connectors | Cat-class signal, motor cable, solenoid cabling, the 10-string sensor harness, lugs, ferrules | 1 lot | $180 | Custom harnessing for 10 strings + cams + motor is the bulk of "wiring." |
| Cooling / fans | Driver + enclosure airflow | lot | $25 | |
| **Subtotal — new electrical** | | | **~$575** | |

---

### H. Safety hardware (NEW — Subsystem 8 engineering is done; its parts still cost money)

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| E-stop + safety contactor | Latching mushroom E-stop + force-guided safety relay/contactor that drops motor power independent of the Pi | 1 set | $120 | Hardware embodiment of the "non-bypassable relay-enable rail." Mandatory for a machine that moves near hands during the 10k test. |
| Light curtain or guard interlock | Simple gate interlock switch on the access side of the bench cabinet (a full light curtain is overkill for a mule) | 1 | $60 | Interlock switch ~$30; a basic light curtain is ~$200 if wanted — **flag** as optional upscope. |
| Warning beacon / buzzer | Cycle-active indicator | 1 | $25 | |
| **Subtotal — safety hardware** | | | **~$205** | |

---

### I. Fasteners / misc / consumables (NEW)

| Item | Spec | Qty | Est USD | Notes |
|---|---|---|---|---|
| Fastener kit | Socket-head M3-M8 assortment, lock washers, threadlocker, shims | lot | $120 | Custom builds eat fasteners. |
| Bearings / bushings / shaft collars | For reels, idlers, return wheel | lot | $90 | |
| 3D-print / prototype filament + misc stock | Guides, brackets, jigs printed/iterated during build | lot | $80 | A string mule iterates the guide geometry a lot. |
| Lubricants, cable ties, heat-shrink, labels | Shop consumables | lot | $60 | |
| Contingency on fab/rework | First-build rework on the custom carriage + deck | lot | $250 | A real-but-soft line: the first string mule never goes together once. |
| **Subtotal — misc** | | | **~$600** | |

---

### TOTALS

| Bucket | New-spend USD |
|---|---|
| A. Frame / structure | ~$640 |
| B. Lift / carriage | ~$1,310 |
| C. String management (10 latches) | ~$770 |
| D. Pins / deck | ~$630 |
| E. Ball handling / return | ~$415 |
| F. Control stack | **$0 (reused — ~$225 repl. cost, excluded)** |
| G. New electrical (power/wiring) | ~$575 |
| H. Safety hardware | ~$205 |
| I. Fasteners / misc / contingency | ~$600 |
| **TOTAL NEW SPEND — one lane prototype** | **≈ $5,150** |
| **Realistic range (uncertainty band)** | **$4,000 – $7,500** |

**Plus one-time NRE, not per-lane (flag, separate from BOM):** a rev-C board respin (re-populating the proven cells against the new channel mix) — fab + assembly of a small batch ~$200, already within the team's demonstrated JLCPCB pattern; design labor is internal. Any custom-machined carriage/deck tooling is included in the cash lines above as one-off shop quotes, not amortized.

**Build labor (not in cash BOM):** rough order ~80-150 person-hours for a first string mule (frame assembly, custom carriage fab/iteration, 10-string rigging + guide tuning, wiring, bring-up). The string-rigging + tangle-tuning is the time sink, mirroring the #1 risk.

---

### Cost comparison vs. buying commercial string

| Option | Per-lane | 32-lane house | Source basis |
|---|---|---|---|
| **This prototype (new spend)** | **~$5,150** (range $4-7.5k) | n/a — proof of mechanism, 1 lane | This BOM |
| Brunswick / commercial string (new) | ~$25,000 installed (machine ~$8-20k + install $1-3k + return/scoring separate) | ~$800,000 | Brunswick StringPin / fly­bowling 2026 guide; QubicaAMF EDGE String |
| Commercial string, bulk (30+ lanes) | ~$14,500/unit | ~$465,000 (machines only) | flybowling bulk-rate citation |

**Read:** the one-lane prototype's NEW spend (~$5k) is roughly **20% of a single commercial string lane installed (~$25k)** and well under even the bulk per-unit machine price (~$14.5k). That gap is exactly what "the brain is already built and the camera/scoring is done" buys you — the ~$225 of reused control electronics + owned camera would otherwise be bundled into that $14.5-25k commercial number along with certified mechanicals, masking, full ball return, and warranty. The prototype deliberately omits certification, full masking, a real ball subway, and durability margin — so this is a proof-of-mechanism cost, **not** a per-lane production cost. A realistic *productionized* DIY lane (after the mule proves out) would land meaningfully higher than $5k once you add proper masking, a full ball return, certified pins, and labor — but still plausibly well under the $14.5k bulk commercial figure if the mechanism survives 10k cycles.

---

### What dominates the cost / uncertainty

1. **The lift carriage assembly (~$1,310, ~25% of total)** is the single biggest bucket, and the custom "wagon" weldment + linear rails + BLDC drive inside it carry the widest error bars. If Subsystem 3 accepts a closed-loop NEMA-34 stepper instead of a true BLDC gearmotor, this bucket drops ~$150-200.
2. **Custom-fab lines (carriage plate, deck, latch sub-plate, harness)** are shop-quote-dependent; salvaging a scrapped 82-70 cabinet shell and a lane-end deck panel could cut $200-400. These are the lines most likely to move.
3. **Pins** are a clean ±$120 swing (new drilled string pins ~$15-20 ea vs. used ~$8).
4. **Ball return** is descopable to a gravity ramp (−$140 to −$300) for a bench mule.
5. Everything electrical/control is **cheap and well-bounded** — it's the team's strength and it's already owned. Cash risk lives entirely on the mechanical side, consistent with the project framing.

---

### Risks
- **Carriage fab cost is the loosest line** — a single custom weldment can come back at 2× my estimate from a one-off shop; I budgeted mid-range and added a $250 rework contingency, but a bad fab quote could push the total toward the $7.5k ceiling.
- **String-latch actuator choice is unsettled (Subsystem 2's call):** 10 individual solenoids (~$200 + a driver board the reused PCB may not have channels for) vs. a shared declutch mechanism. I costed the expensive case; the interface to the 6-relay reused board is a real gap (10 fast string actuators > 6 G5LE outputs) and may add a ~$40 driver board not currently in the controller design.
- **"Reused" control cost is understated if a rev-C respin is needed** — re-populating the cells for a new channel mix is cheap to fab (~$200) but the difference between "owned as-is" and "needs a new board run" is a real fork I flagged but can't resolve from subsystem 9.
- **Salvage assumptions** (cabinet shell, deck panel ≈ free/cheap) could evaporate if no scrap 82-70 is available, adding ~$300-500.
- **Consumable burn during the 10k test** (string abrasion, pin coating wear, belt) is partly in the BOM as spares, but a tangle-failure-and-rebuild loop could consume more cord/pins than budgeted — the durability test itself has a consumables cost I've only roughly carried.
- **Single-unit retail pricing throughout** — every line is small-qty/retail; none of this reflects volume pricing, so it is the *worst-case* cash for one lane, not a per-lane figure for 32.

### Open questions
- **Is a scrap AMF 82-70 cabinet/deck available to salvage?** This swings the frame + deck buckets by $300-500 and is the highest-leverage cost unknown. (WSL is actively running 82-70s and has a noted "spare cabinet" for the bench track — likely yes, which would pull the total toward the low end.)
- **Does the reused rev-C board carry the 10 string-latch outputs, or do we add a dedicated solenoid driver?** Resolves a ~$40 line and a real Subsystem 2↔6↔7 interface gap.
- **Powered ball return in scope for the mule, or gravity-only?** −$140 to −$300 either way; depends on whether "up-lane ball return" is part of the cycle being durability-tested.
- **New vs. used pins, new vs. salvaged synthetic deck** — ~$200 combined swing; acceptable for a mule to go used?
- **BLDC vs. closed-loop stepper for the lift** — Subsystem 3 spec'd BLDC; confirming whether a NEMA-34 stepper is acceptable saves ~$150-200 and simplifies the driver/safety-rail interface.
- **Does the 10k-cycle test budget need a second full set of consumables (cord, pins, belt) up front?** If the tangle risk materializes, rebuild-loop consumables could add a few hundred dollars I've only partially carried.

**Grounding pulled from web (flagged):** commercial string per-lane pricing $8-20k machine + $1-3k install, ~$14.5k bulk-unit, QubicaAMF EDGE String top-of-range — [flybowling 2026 cost guide](https://www.flybowling.com/blog/string-pinsetter-cost-2026-pricing-guide.html), [Brunswick GS NXT](https://brunswickbowling.com/bowling-centers/equipment-parts-supplies/center-operations/pinsetters/gs-nxt-pinsetters), [QubicaAMF EDGE String](https://www.qubicaamf.com/bowling-products/pinspotters/edge-string); string-pinsetter mechanism (frame + sliding carriage + per-string holders + frame/carriage motors) confirmed via patents [EP3107631A1](https://patents.google.com/patent/EP3107631A1/en) and [US10569158B2](https://patents.google.com/patent/US10569158B2/en); extrusion/linear-rail pricing from [8020/OpenBuilds/VEVOR listings](https://us.openbuilds.com/v-slot-40x40-linear-rail/). Control-stack costs taken from the team's own JLCPCB order history (20 boards fully-assembled ~$160-190) in `wsl-lane-nodes/docs/phase8b_pcb_revB_BOM_power.md` and memory `project_phase8a_pcb_ordered.md`. Mechanical catalog parts (BLDC gearmotor, HGR20 rails, solenoids, reels) priced from standard small-qty industrial-supply ranges (knowledge-based, not freshly quoted — flag for a real RFQ before committing).

---

## Subsystem 10 — FMEA, Build Plan & the 10,000-Cycle Durability Experiment

**Framing.** This is the go/no-go subsystem. The electronics/software/camera are the team's proven strength — the existing controller stack (`wsl-lane-nodes`) is already bench-validated for the AMF 82-70 *free-fall* retrofit: a per-pair Raspberry Pi running the cycle FSM, an RP2040 fast/safety co-processor that owns latency-critical inputs and drives a non-bypassable rail-permission line, three MCP23017 I²C expanders, an NE555 hardware watchdog, a 6-condition relay-enable safety rail, an isolated field-wetting supply, and a camera "Track A" detector that already emits a calibrated 10-bit standing-pin mask (`lane_node/pin_detect.py`, 0/120 errors on the real deck). **The new mountain is mechanical**, so this section is deliberately weighted toward (a) where the *mechanism* fails, (b) a build order that defers every mechanical risk until it can be bench-isolated, and (c) a quantitative experiment whose pass/fail numbers are anchored to how real string machines actually behave.

I scoped this against the real prior art (QubicaAMF EDGE String, Brunswick StringPin, U.S. Bowling, Funk). Three numbers from that research anchor everything below and are flagged where pulled:

- **String life ≈ 10,000–15,000 frames** before proactive replacement (Flying Bowling commercial maintenance guide). *This is why the durability target is exactly 10k cycles — one string-life interval. A "pass" means we survived one consumable cycle of the #1 wear item.*
- **≥ 65 in of unobstructed slack per string** is the design minimum that keeps deadwood-on-strings from binding (U.S. Bowling). Drives Subsystem 2's take-up travel; I treat it as a hard interface input, not a thing I redesign.
- **Tangle rate < 1 per 1,000 frames** in a *well-maintained* commercial install (multiple sources). This becomes my headline PASS threshold — but see the calibration note: a first prototype that merely *matches* commercial is a strong result; I set the gate at a deliberately looser-than-commercial bar and treat beating commercial as the stretch goal.

A fourth qualitative finding shapes the FMEA: **slow/kids' balls leave pins flat on the deck where they roll over neighbors' strings → the dominant tangle generator** (U.S. Bowling). The test plan must therefore *deliberately inject* low-energy, off-axis pin scatter, not just clean rack-and-strike cycles, or it will under-count the failure mode that actually matters.

---

### (a) FMEA

Scoring: **Severity (S)** and **Likelihood (L)** on 1–5 (5 = worst). **RPN = S × L** (detection is folded into L, since the camera makes almost everything *detectable* — the question is whether the mechanism *causes* it). "Camera-detectable" in the mitigation column means Track A already gives us ground-truth observation of the outcome for free, which is a real advantage this team has over a from-scratch builder.

| # | Failure mode | S | L | RPN | Cause(s) | Mitigation (mechanical / control / detection) | Owner subsystem |
|---|---|---|---|---|---|---|---|
| F1 | **String tangle** (the #1 risk) | 4 | 5 | 20 | Insufficient slack; slow/off-axis pin scatter laying pins across neighbor strings; uneven take-up tension; strings crossing at the comb; pin-spot pitch too tight at re-set | Adequate slack (≥65 in, Subsys 2); per-pin string comb + tray to keep strings parallel (EDGE String uses exactly this); per-pin tension consistency; **camera flags a mis-set rack → auto re-cycle (lift-and-drop) before next ball**; FSM cycle-count + jam-log every auto-recover; manual-intervention state on repeat | 2, 3, 4 |
| F2 | **Off-spot / mis-spot landing** (pin sets but not on the 12" spot, or leaning) | 3 | 4 | 12 | String length drift; take-up not returning pin to true vertical; spot cup/locator worn or absent; pin swinging at release | Mechanical spot locators/cups at each of 10 positions (Subsys 3/4); controlled lower speed near touchdown; settle dwell before "ready"; **camera measures actual spot position vs the calibrated `PIN_SPOTS_PX` → quantified on-spot error every cycle** (we already have sub-3px spot calibration) | 3, 4 |
| F3 | **Pin jam / hang-up** (pin caught on table, shackle, or another pin during lift) | 4 | 3 | 12 | Deadwood not clearing; pin string wrapped; setting-table tong/holder fouls a pin; ball + pins in pit simultaneously | Generous lift clearance; sweep/guard clears deadwood (held aloft by its own string, lighter than free-fall); **FSM motion-max-run FAULT (8 s) already exists** → motor de-energizes, rail drops, operator alert; no blind retry | 1, 3 |
| F4 | **String break / abrasion wear** | 3 | 4 | 12 | Normal fatigue at the head-hole grommet + take-up sheave; abrasion at comb; ball impact shock load; UV/heat embrittlement | Bonded/coated string (acts as its own lubricant — U.S. Bowling); radiused grommet + sheave; **treat string as a scheduled consumable (replace ≤10k frames)**; per-pin slack-detect at home position flags a *broken* string (pin missing from camera + string slack) | 2, 4 |
| F5 | **Motor / drive failure** (setting-table motor, take-up motor/drive, sweep drive) | 4 | 2 | 8 | Bearing/gearbox wear; belt slip/break; brake fails to hold table; stall/overcurrent | Commercial-duty gearmotor sized with margin; self-locking brake on the lift axis (Brunswick StringPin uses a ½ hp table motor with an internal holding brake); current-sense or stall-timeout → **FSM FAULT + NE555 watchdog drops the rail**; spare motor on the shelf for the test | 3, 5 |
| F6 | **Ball-return jam** (ball stuck in pit, on the up-lane, or not lifted) | 2 | 3 | 6 | Ball wedged with deadwood; lift wheel slip; track misalign; two balls (prototype rarely, but possible) | Pit geometry to settle ball clear of pins; ball-detect (the existing DIELL-equivalent beam) gates the cycle; return-motor stall-timeout FAULT; for the prototype, a **manual ball-feed bypass is acceptable** (de-risks the cycle test from the return mechanism) | 5 |
| F7 | **Detection error** (camera reports wrong standing mask → wrong pins set/cleared, or false "tangle") | 3 | 2 | 6 | Exposure drift; lighting change; deck occlusion; capture-dongle dropout; pin swinging during capture | Track A already handles exposure drift (drift-corrected cap-ROI, validated band [19,53]); capture *after* settle dwell; **frame-to-frame agreement check (require 2 stable frames)**; on capture failure → FAULT not guess; periodic empty-frame recalibration | 7 |
| F8 | **Electronics / safety fault** (Pi hang, RP2040 dead, relay weld, I²C bus error, power loss mid-cycle) | 5 | 1 | 5 | SW deadlock; SD corruption; coil weld; brownout; kernel panic | **Already solved + bench-proven in the stack**: NE555 watchdog drops *all* coil power on missed kick (kill-9 → relays drop ~11 s, validated); RP2040_OK fail-safe-low gates the rail; FSM comes up disarmed (power-down rule, requires First-Ball-Zero); motion-max-run FAULT; arm-GPIO gate. **Residual: a *welded* contact — rail can't open it; the upstream breaker is the final stop** (documented limitation §4.5) | 6, 8 |
| F9 | **Operator / intervention hazard** (hand in machine during a cycle) | 5 | 2 | 10 | Manual tangle clearing mid-game (real string machines invite this — patrons reach in); maintenance with power on | Hardware E-stop in the coil rail; guarded access; FSM `MANUAL_INTERVENTION` latch requires deliberate re-arm (no silent auto-resume — already enforced, and the daemon self-test covers the "health blip must not silently re-arm with a stale latch" case); lockout/tagout for service | 8 |
| F10 | **Cumulative drift / settle creep** (string slowly lengthens/shortens, spots wander over thousands of cycles) | 2 | 4 | 8 | Knot creep; sheave wear; mounting flex | Mechanical hard-stops define home, not the motor count; **camera trend-logs on-spot error over the whole 10k run → drift is graphed, not discovered at failure**; mid-test re-tension checkpoints | 2, 3 |

**Top of the heap by RPN:** F1 tangle (20), then a four-way tie at 12 (F2 off-spot, F3 jam, F4 string wear), then F9 operator hazard (10). The build plan and the test instrumentation below are organized to attack **F1/F2/F4 first and hardest**, because those are (a) the highest combined risk and (b) the ones the existing electronics *cannot* fix for us — they are pure mechanism.

**What the existing stack already de-risks (don't re-litigate these):** F8 and most of F9 are effectively retired by the proven safety architecture — the watchdog, RP2040_OK fail-safe rail, power-down rule, motion-timeout FAULT, and the no-silent-re-arm latch are all bench-validated in this repo. F7 is largely retired by Track A's drift-corrected detector. The prototype's risk budget is therefore almost entirely mechanical, which is the correct place for it to be.

---

### (b) Build Plan — staged path to a working 1-lane bench prototype

**Principle: integrate the *proven* (electronics + camera) last and against a *known-good mechanism*, so that any failure during integration is unambiguously mechanical.** Build the mechanism in sub-assemblies, bench-characterize each in isolation, then drop in the rev-C board + camera exactly as they drop into the 82-70 cutover — same FSM, same Track A, same safety rail — with only the channel mix remapped.

**Stage 0 — Rig & instrumentation skeleton (before any pinsetter motion).**
- Spare pinsetter cabinet (or bench frame) + regulation pin-deck section with the 10 spots at true 12" pitch.
- Bring up the **rev-C board bare** (no machine attached): power, I²C enumerates 3× MCP23017, RP2040 heartbeats over UART, NE555 watchdog kick/timeout proven (replicate the existing bench test: kill the kicker → coil rail drops within timeout; verified pattern in `hardware_watchdog_design.md`).
- Stand up the **camera + Track A** against the empty deck: capture an empty frame, confirm `DualDeckDetector` runs, recalibrate `PIN_SPOTS_PX` for the prototype's single deck and camera placement (the calibration recipe is already documented; sub-3px residual achievable from 4 labeled leave-frames).
- *Exit:* every electronic subsystem proven against a *dead* machine. No mechanical risk has touched the electronics yet.

**Stage 1 — String + take-up sub-assembly (F1/F4 isolation rig).**
- Build the take-up/lift for **2–3 pins first**, not all 10 — cheaper to iterate the comb/tray/sheave geometry.
- Bench-test *open-loop* (hand-trigger the take-up motor, no FSM): verify ≥65" slack, consistent tension, clean string return, no comb cross. **Hand-throw pins to scatter them flat and off-axis** and watch for tangle — this is the cheapest place on the whole project to find the #1 failure mode.
- *Exit:* the highest-RPN mechanism (F1) characterized on a 2–3 pin rig before committing the full deck. Go/no-go on the take-up concept here, before spending on 10× of it.

**Stage 2 — Setting table + on-spot landing (F2/F3 isolation rig).**
- Build the lift/set table and the 10 spot locators. Bench-test the lower-and-set cycle *open-loop*: does a held pin land on-spot, vertical, every time?
- Use the **camera as the metrology tool here** (not yet in the control loop): drop pins, measure actual spot error vs `PIN_SPOTS_PX`. This turns "looks about right" into a number before integration.
- *Exit:* on-spot landing characterized and quantified, full 10-pin deck.

**Stage 3 — Ball handling (F6, lowest priority — parallelizable / deferrable).**
- Up-lane return + pit. **Acceptable to stub with a manual ball feed for the cycle-reliability test** so the return mechanism doesn't gate the durability experiment. Build/integrate it *after* F1/F2 are passing, or in parallel by a second person.

**Stage 4 — rev-C board channel mapping (the electronics drop-in).**
The existing board is a parameterized KiCad cell library; rev-C = repopulate the same proven cells (PC817 opto-in, G5LE/relay dry-contact out, RP2040, MCP23017, NE555, field-wetting) against the string machine's channel mix. The remap from the 82-70's channels:

| Existing (82-70 free-fall) | rev-C (string prototype) | Cell reused |
|---|---|---|
| S = sweep motor contactor cmd | Sweep/guard drive (clear deadwood) | relay-out, safety-railed |
| T = table motor contactor cmd | **Lift/set table drive** | relay-out, safety-railed |
| SP = spot solenoid | **String take-up / spot release** | relay-out, safety-railed |
| M1 = ball return | Ball-return motor (or DNP for v1) | relay-out (DNP-optional) |
| GS1–10 grippers (standing mask) | **Unused — camera supplies mask** (or optional per-pin string-slack switch as a cross-check) | opto-in (depopulate or repurpose) |
| 6 cams (SA/SB/SC/TA1/TA2/TB) | **Home/limit + position switches** for table + take-up | RP2040 fast opto-in |
| DIELL ball beam | Ball-thrown beam (cycle trigger) | RP2040 fast opto-in |
| Status lamps, foul, PBZ | Same (status, foul, First-Ball-Zero) | relay/opto |

*Key interface change to flag loudly:* on the 82-70 the board **commands existing OEM contactors** and "the machine's iron switches the motors" — the board never carries motor current. **A from-scratch string prototype has no OEM contactor to hide behind.** Either (a) add a contactor/SSR tier between the rev-C dry contacts and the prototype's motors (preserves the proven "drive coils, not motors" safety property — *strongly recommended*), or (b) accept that rev-C relays now switch motor loads directly (changes contact ratings, snubber/MOV population, and the whole inductive-load safety story). **This is an open question for Subsystems 3/5/6 and must be resolved before the rev-C BOM is frozen** — see open questions.

**Stage 5 — Integration & dry-cycle.**
- Mount rev-C, wire the remapped channels, **keep the upstream E-stop + breaker + watchdog rail in hardware** exactly as the contract demands (`phase8b_pcb_revB_spec.md` non-negotiable rule: board is never the only safety device).
- Bring up the FSM in `--selftest`/sim first (the `controller_daemon.py` off-hardware self-test already drives a full strike cycle and the mid-cycle health-loss safety trip — adapt its cycle map to the string sequence from Subsystem 1).
- First live motion **disarmed-by-default** (power-down rule), single-step the cycle by hand-feeding events, then close the camera into the loop (Track A mask → FSM set/clear decision).
- *Exit gate:* 100 supervised manual cycles with zero unrecovered jams and on-spot error within spec → only then start the durability experiment.

---

### (c) The 10,000-Cycle Durability Experiment

**Why 10k:** it is exactly **one string-life interval** (10–15k frames, per the maintenance research). Surviving it means the prototype completed one full consumable cycle of its #1 wear item without a mechanism redesign — the minimum credible claim of "proof of mechanism." It is also ~enough cycles for tangle/off-spot rates to be statistically meaningful against the <1/1000 commercial benchmark (10k cycles → expect <10 tangles if we match commercial; that's a countable, distinguishable number).

**Automated test harness (mostly free — the control stack already produces it):**

1. **Auto-cycle driver.** A test mode that runs set→(simulated ball)→clear→set on a loop unattended. Inject ball events programmatically (no human throwing for 10k cycles). **Critically, vary the leave pattern** — script realistic mixes including the F1 generator: low-energy/off-axis scatters that leave pins flat on the deck, plus full racks, strikes, and corner leaves. A pure strike-loop would under-test tangle by design.
2. **Cycle counter + jam log.** The FSM already has the state machine and the motion-max-run FAULT; extend it to persist (it already has SQLite state persistence in the stack): every cycle timestamped, every FAULT/auto-recover/manual-intervention logged with state + cause. Free instrumentation falling out of the existing architecture.
3. **Camera as ground-truth, every cycle.** After each set, Track A records: the standing mask, **measured on-spot error per pin** (px deviation from `PIN_SPOTS_PX` → mm), and a **mis-set/tangle flag** (rack doesn't match commanded set). This is the experiment's primary sensor and it already exists and is calibrated. Store the frame on any flagged event for later human review.
4. **Wear-inspection cadence** (manual, scheduled — mirrors commercial practice): **daily** visual string-fray + safety check; **every ~1,000 cycles** measure per-pin string tension + on-spot error distribution + photograph grommet/sheave/comb wear; **mid-test (≈5,000)** full teardown inspection of the take-up and table. Sensor/camera lens wipe weekly (dust → misread is a documented failure).

**Quantitative PASS / FAIL criteria:**

| Metric | PASS (prototype target) | Stretch (matches commercial) | FAIL → back to mechanism |
|---|---|---|---|
| **Tangle / mis-set rate** | < 1 per 200 cycles (≤50 in 10k) requiring no human hand-in-machine; auto-lift-recover counts as a pass if the *next* set is correct | < 1 per 1,000 (commercial) | > 1 per 100, **or** any tangle needing a hand in the machine more than ~1 per 1,000 |
| **On-spot accuracy** | ≥ 95% of pins within regulation spot tolerance; no systematic drift trend over the run | ≥ 99% | < 90%, or measurable monotonic spot drift (F10) |
| **String life** | zero string breaks before 8,000 cycles; ≤ a few before 10k | no breaks to 10k | break before ~3,000 cycles (grommet/sheave radius wrong — design fault, not wear) |
| **Unrecovered jam (F3)** | ≤ 1 per 1,000 cycles requiring manual clear | ≤ 1 per 5,000 | > 1 per 250 |
| **Motor/drive (F5)** | survives 10k with no failure; no thermal/current trend toward limit | — | any drive/brake failure before 10k = under-sized |
| **Safety events** | **zero** uncommanded motion; every FAULT failed *safe* (rail dropped, no injury path) | — | **any** unsafe event = hard stop, full safety re-review |
| **Mean cycles between intervention (MCBI)** | ≥ 500 | ≥ 5,000 | < 100 (not viable) |

*Calibration note on the tangle gate:* a brand-new, single-prototype mechanism that hits **<1/200** is a genuinely strong result and a clear greenlight; demanding commercial's <1/1000 on a first build would be moving the goalposts. The stretch column is the aspiration, the PASS column is the decision threshold.

**Decision gates (the actual go/no-go):**

- **GREENLIGHT a second lane** if: tangle/jam/on-spot all in the PASS column, MCBI ≥ 500, zero unsafe events, and **string is the only thing that hit end-of-life** (i.e., failures were wear, not design). This proves the mechanism and the consumable model. Next step = build lane 2 to validate repeatability and the cross-lane control (the stack already has cross-lane scoring tests).
- **ITERATE-IN-PLACE** (fix and re-run, don't abandon) if: one metric (most likely F1 tangle or F2 off-spot) is between PASS and FAIL, and the root cause is a *tunable* geometry/tension/locator issue with an obvious mechanical fix. Re-run from the relevant Stage-1/2 isolation rig, not the whole machine.
- **BACK TO THE MECHANISM** (fundamental redesign) if: tangle needs human hands-in-machine at commercial-unacceptable rates *despite* slack/comb/tension being correct; **or** strings break early from a shock-load/radius problem that tuning can't fix; **or** on-spot can't be held without per-cycle camera correction (means the mechanism can't self-locate). These say the *concept* of this particular take-up/set design is wrong, not the build.
- **HARD STOP regardless of other metrics:** any single uncommanded-motion or injury-path event. The mechanism doesn't get a durability score until it's safe.

**What a clean pass licenses (and what it does NOT):** a 10k pass greenlights *a second prototype lane*, full stop. It explicitly does **not** license 32 lanes, USBC certification, or a product — those need multi-lane soak, certification testing, and a real reliability program. This experiment answers exactly one question: *did our own string mechanism, driven by our already-proven brain, survive one string-life interval reliably and safely enough to be worth building a second one?*
