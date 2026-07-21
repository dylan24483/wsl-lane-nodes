# Hardware Independence Project — Exhaustive Technical Audit

**Audit date:** 2026-07-09  
**Decision:** **NO-GO for live Track-B cutover or unattended hardware operation**  
**Repositories reviewed:**

- wsl-lane-nodes — branch fable-audit-fixes, commit 82feed6
- WSL Systems — branch fable-audit-fixes, commit 4732e3b

The audit was read-only with respect to source, firmware, PCB, configuration, and deployment
files. Existing working-tree changes in both repositories were preserved. This report is the
only file added.

| Severity | Count | Release meaning |
|---|---:|---|
| Critical | 11 | Any one blocks live cutover. |
| High | 27 | Must be closed or explicitly dispositioned with objective evidence before release. |
| Medium / hardening | 20 | Correct before fleet rollout; several are defense-in-depth dependencies. |
| **Total findings** | **58** | Open physical gates and checklist items are additionally tracked in Sections 7 and 11. |

## 1. Executive verdict

The project has several good safety-oriented building blocks, and the current Rev-C PCB is
substantially better than its historical Rev-B predecessor. The current board passes fresh
KiCad DRC, its relay copper is correct, its logic/field domains are separated, and the design
intends to retain the OEM contactors and collision ladder. Retention through each actual
board-contact insertion point remains a per-lane proof, not an as-built cutover fact.

Those facts do **not** make the complete system safe to cut over.

The present stack contains multiple independent paths to unintended or insufficiently bounded
motion:

1. The ordinary RP2040 build ships with its new cam-stop, interlock-echo, and
   motion-without-RUN protections disabled or unconfirmed.
2. A failed MCP23017 de-energize write can consume the only cam-stop event, leave a motor
   energized, preserve ARM, and make the software cache disagree with the physical latch.
3. The Pi-to-NE555 watchdog can fail permissive if execution freezes while the kick GPIO is
   high.
4. WSL startup reconciliation misclassifies a closed lane as live and can issue a real
   one-second CLOSE pulse on service restart.
5. Closed-lane, stale, retried, or duplicated ball events can produce physical CYCLE commands
   because there is no durable event/command identity or acknowledgement boundary.
6. The control plane is unauthenticated by default, permits duplicate lane ownership, and the
   display served by the hardware-control server contains stored-XSS sinks.
7. Important machine facts remain physical release gates: cam edge/lobe meaning, actual
   Stop/CIS landing, Candidate-C insertion-point proof, per-channel input class, relay load and
   suppression, and first-article operation.

Any one of findings C-01 through C-11 is sufficient to hold cutover. Several combine into
common-cause chains, so merely fixing the highest-profile bug is not enough.

### Required decision

Keep Track B in shadow/bench mode. Do not permit automatic startup into live outputs, do not
land unclassified field inputs, and do not treat a clean DRC or a passing simulator as a
release authorization. Release only after every gate in Section 11 has objective evidence and
an independent reviewer has signed the resulting safety configuration.

## 2. Scope and audit method

### 2.1 In scope

- Track-A Pi lane node, camera/manual ball-event path, cycle and power relay control.
- Lane-node WebSocket and HTTP server, scoring state, persistence, display, and correction.
- Track-B controller daemon, finite-state machine, MCP23017 I/O, RP2040 link and firmware.
- Rev-C routed PCB, preserved order ZIPs, post-order loose fab tree, generator, netlist,
  BOM/CPL, harness, and cutover docs.
- WSL Systems Phase-8 bridge, WSL API lifecycle operations, transfer, startup reconciliation,
  legacy VDB coexistence, deployment, provisioning, and monitoring.
- Cross-repository version, ownership, protocol, and operational failure behavior.

### 2.2 Evidence classifications

| Label | Meaning |
|---|---|
| Reproduced | A focused executable probe demonstrated the behavior. |
| Build-confirmed | Compiler, build output, DRC, or generated artifact directly established it. |
| Code-proven | The complete relevant branch is deterministic from source inspection. |
| Hardware-conditional | The software/circuit risk is real, but final physical behavior must be measured. |
| Open release gate | Project documentation itself records the required proof as incomplete. |

### 2.3 Limitations

This was not an energized-machine certification test. No live 82-70 was operated, and no
oscilloscope, current probe, insulation tester, contact-weld test, or destructive component
fault injection was performed. Hardware-conditional findings therefore remain mandatory bench
or machine tests; they are not waived by the software results.

This audit is an engineering risk assessment, not a claim of compliance with a functional
safety standard. The current control board should be treated as prototype equipment unless a
separate standards-based hazard analysis establishes otherwise.

## 3. Current architecture and control authority

    Front desk / WSL API / database
       |
       +---- legacy VDB bridge ----------------------> historical controller path
       |
       +---- Phase-8 HTTP mirror --------------------> lane_node_server :8766
                                                        |
                                                        +-- scoring state / display
                                                        |
                                                        +-- WebSocket commands :8765
                                                             |
                                                             v
                                                     Track-A lane_node.py
                                                     camera + cycle/power GPIO

    Track-B controller_daemon.py   [not integrated with the server above]
       |
       +---- MCP23017 outputs/inputs ----> Rev-C relay board ----> OEM 24-VAC ladder
       |
       +---- RP2040 UART -------------> max-run / cam supervision / RP_OK
       |
       +---- Pi watchdog kick --------> NE555 / relay-enable rail

The most important architectural problem is that the project does not yet have one explicit,
transactional owner of physical motion:

- Track A owns scoring connectivity and cycle/power relay commands.
- Track B owns the replacement mechanism FSM and direct motion outputs.
- The two systemd services intentionally conflict because both can own GPIO.
- WSL API can invoke both legacy VDB and Phase-8 paths for the same lifecycle event.
- State transitions are committed before hardware delivery is known.

The target architecture should have one local mechanism controller as the sole actuator owner.
WSL should submit authenticated, idempotent intents. The local controller should accept or
reject each intent against its physical state, apply it once, and return a durable result.
Scoring should consume accepted local events; it should not itself be the motion authority.

## 4. Release-blocking critical findings

### C-01 — Stock RP2040 firmware does not enforce the intended safety posture

**Evidence:** Build-confirmed and code-proven.

- firmware/rp2040/config.h:87-171 defaults SA/TA1 cam-stop, interlock echo, and
  motion-without-RUN protections to disabled or unconfirmed.
- firmware/rp2040/CMakeLists.txt:18-43 defines no production safety-profile target.
- The generated build contains none of the required safety feature definitions.
- firmware/rp2040/README.md:175-180 states the v1.1.1 posture is not flashed, bench-run, or
  cutover-ready.
- The ordinary host build passed 64/64 tests while proving the v1.1 protection branches were
  inert. A separately forced-on build passed 32/32 tests.
- firmware/rp2040/main.c:589 pauses the MCU watchdog under debugger halt.

**Failure mechanism:** After OEM logic removal, a missed Pi stop or failed relay write may
continue through multiple cam revolutions. The generic eight-second maximum is the remaining
firmware bound only if the RP2040 received and retained the matching RUN. A lost RUN, RP reboot,
or relay/UART divergence removes that protection because it is based on UART intent rather than
physical contact state. An unknown or old firmware image can still be accepted for ARM.

**Required correction:**

- Create a distinct production firmware target with the measured per-lane edge/lobe posture.
- Add compile-time assertions that reject disabled or unknown production safety fields.
- Emit immutable image hash, build mode, maximum-run value, feature mask, edge configuration,
  boot/session ID, and debugger posture in every attestation.
- Make the daemon refuse ARM unless the attestation exactly matches a signed, lane-specific
  approved configuration.
- Use pause-on-debug false in the production image.

**Acceptance test:** No boot record, old firmware, missing fields, unknown edge, disabled
feature, debug image, wrong hash, wrong lane configuration, or stale boot metadata must keep ARM
low. Only the exact approved image and posture may arm.

### C-02 — A failed output write can consume a stop and leave a motor energized

**Evidence:** Reproduced.

- lane_node/controller_io.py:120-124 updates the MCP OLAT cache before the physical bus write.
- controller_io.py:185-203 updates the high-level output state before the bus write and sends
  RP2040 STOP only after a successful write.
- lane_node/cycle_control_8270.py:259-263 consumes the SB event with one stop call.
- lane_node/controller_daemon.py:457-475 logs/tolerates an exception; a later successful tick
  resets the error count.

Focused fault injection on the SB sweep-off call produced:

    state=sweep_to_guard, sweep=True, armed=True

The following tick remained in the same state with sweep still reported on. A lower-level
cache probe also demonstrated:

    after_failed_set: cached_olat=1 physical_olat=0
    after_unrelated_set: physical_olat=3

The unrelated second write asserted the bit whose earlier write had failed.

**Failure mechanism:** A transient I2C/NACK fault on de-energize loses the one physical stop
event. The cache records a state that was never written. A later write can unexpectedly assert
that cached bit. The daemon remains armed, and the RP2040 model can remain consistent with the
wrong state.

**Required correction:**

- Drop ARM on the first control/output exception.
- Keep desired state, confirmed OLAT state, and firmware run state separate.
- Update caches only after a confirmed bus transaction; read back OLAT.
- Reconcile the entire desired output vector every bounded control tick while disarmed.
- Make all-motors-off independent per channel and continue attempting every output even if one
  write fails.
- Persist the causal fault and require deliberate recovery.

**Acceptance test:** Inject failure before, during, and after every energize/de-energize write.
Every case must drop the physical rail within the damage-limited bound, preserve the stop
request, avoid asserting unrelated outputs, and require a separate recovery action.

### C-03 — The watchdog can fail high and hold the safety rail permissive

**Evidence:** Code/circuit-proven; physical timing requires bench confirmation.

- scripts/generate_kicad_netlist_revB.py:317-364 drives Q12 from the Pi kick signal and can hold
  the NE555 timing/trigger node asserted.
- lane_node/controller_daemon.py:286-292 performs on, sleeps 2 ms, then performs off.
- Track-A lane_node/lane_node.py:388-406 uses the same software-pulse pattern.
- lane_node/controller_cleanup.py:11-15 explicitly notes that retained HIGH holds the watchdog
  alive.

**Failure mechanism:** SIGSTOP, kernel/scheduler freeze, process wedge, or GPIO failure between
the on and off operations leaves the pin high. Software no longer bounds pulse width. The exact
failure that should remove permission can instead maintain it. The nominal RC interval is about
11 seconds, already much longer than a cam-stop deadline. TI's
[NA555 monostable description](https://www.ti.com/lit/ds/symlink/na555.pdf) states that the
trigger must return high before the interval can end.

**Required correction:** Make DC high and DC low both incapable of maintaining permission.
Use AC/edge coupling, a windowed hardware watchdog, or an independently timed hardware one-shot
whose pulse ends without process execution. Set its maximum interval from measured mechanical
damage limits rather than service restart convenience.

**Acceptance test:** Freeze the process precisely after GPIO-high, then hold the input high,
low, open, and shorted. TP16 and every motion coil must drop within the declared maximum in
every case.

### C-04 — One TA1 edge cannot safely represent a dual-lobe cam

**Evidence:** Code-proven; final motion outcome is hardware-conditional on pending lobe capture.

- lane_node/rp2040_link.py:99-112 maps one TA1 trip to both delay-reset and zero.
- rp2040_link.py:130-133 keeps one global trip edge and discards the opposite edge.
- lane_node/cycle_control_8270.py:308-318 treats a TA1 trip during SPOTTING as table zero,
  releases SP, stops the table, and completes the cycle.
- Existing tests inject only the desired endpoint and do not inject the 185-degree lobe or both
  polarities in sequence.

**Failure mechanism:** If the selected edge occurs at the 185-degree lobe, the controller can
stop the table mid-cycle and report READY. If zero is the opposite edge, it can be discarded and
the table can overrun.

**Required correction:** Queue both edge direction and resulting level with monotonic
timestamps. Define expected edge, phase window, and lobe per state and per cam. Reject missing,
out-of-order, or physically impossible transitions.

**Acceptance test:** Oscilloscope/logic-analyzer capture of every lobe for every revolution
type, followed by replay tests including both TA1 lobes, bounce, missing edges, inverted
polarity, and out-of-order edges.

### C-05 — WSL restart reconciliation can actuate closed lanes

**Evidence:** Reproduced and code-proven.

- WSL Systems/wsl_phase8_bridge.py:93-106 returns true for any HTTP 200.
- wsl-lane-nodes/server/lane_node_server.py:597-624 deliberately returns HTTP 200 with
  open=false for a closed/missing lane.
- WSL Systems/wsl_api.py:3490-3523 therefore skips needed active-session rehydration.
- wsl_api.py:3530-3541 reverse-reconciles each DB-closed lane by POSTing CLOSE.
- lane_node_server.py:968-999 forwards CLOSE to hardware.
- lane_node/lane_node.py:484-486 implements CLOSE as a one-second relay pulse.

A direct probe confirmed that HTTP 200 with open=false is classified as live.

**Failure mechanism:** When HAS_VDB_BRIDGE is true, a WSL API restart can send CLOSE to both
closed pilot lanes. The state-repair path therefore has a physical side effect. A malformed
HTTP-200 body is also misclassified as live. Non-200 responses are incorrectly collapsed to
closed rather than unknown; for an active lane this can trigger an unnecessary state-only
rehydrate, although send_open_command=false prevents that path from pulsing hardware.

**Required correction:** Parse the JSON body and return a strict tri-state: open, closed, or
unknown. Unknown must never cause destructive reconciliation. Separate state reconciliation
from physical OPEN/CLOSE actions, and make process startup side-effect free.

**Acceptance test:** Start/restart every service in every ordering with open, closed, stale,
unreachable, unauthorized, malformed, and partially restored state. The invariant is:

    process restart emits zero hardware commands

### C-06 — Ball and command delivery lacks durable identity, ordering, and exactly-once behavior

**Evidence:** Code-proven; closed-lane cycle reproduced.

- lane_node/lane_node.py:408-425 requeues uncertain sends at the tail, allowing duplication and
  FOUL/BALL reordering.
- The event queue is unbounded at lane_node.py:749 and retains outage-era events.
- Events have timestamps but no durable event ID or session generation.
- server/lane_node_server.py:180-187 makes time-window deduplication optional and disabled by
  default.
- lane_node_server.py:284-325 sends CYCLE after BALL_EVENT even when scoring state is absent.
- POWER_OFF does not invalidate queued or in-flight pulse commands at lane_node.py:475-495,
  515-541, and 585-606.
- Commands have no command ID, TTL, session, applied ACK, or replay cache.

A focused closed-lane event probe produced a CYCLE outbound frame with no lane-scoring object.

**Failure mechanism:** An event captured for one party can be replayed after reconnect into a
new party; a response-loss ambiguity can duplicate a physical pulse; a foul can move behind its
ball; POWER_OFF can be followed by an old queued pulse after POWER_ON.

**Required correction:**

- Add persistent monotonically increasing event IDs per node/lane/boot and explicit session
  generations.
- Retain events in order until a durable EVENT_ACK following state commit.
- Add command IDs, command epochs, TTLs, node replay journals, and APPLIED/REJECTED ACKs.
- Reject stale-session events and commands.
- Only a successfully accepted ball in an active local FSM/session may create a cycle intent.
- POWER_OFF must cancel workers, invalidate the command epoch, force the pulse GPIO low, flush
  that lane's queue, and require a new session to re-enable.

**Acceptance test:** Disconnect at every send/receive/commit/ACK boundary, restart both ends,
reorder frames, duplicate frames, and advance the session. Each accepted ball scores and cycles
at most once; stale events never actuate.

### C-07 — Hardware control is unauthenticated by default and node ownership can be stolen

**Evidence:** Code-proven.

- lane_node_server.py:32-44 and 1134-1164 default authentication off and bind all interfaces.
- WSL Systems/wsl_phase8_bridge.py:47-54 and lane_node/lane_node.py:68-77 make tokens optional.
- systemd/lane-node.service supplies no production environment file.
- lane_node.py defaults include a development identity, lanes 21/22, localhost URL, manual
  mode, and a 0.2-second lockout.
- lane_node_server.py:224-266 only warns about duplicate lane claims and explicitly gives the
  newest claimant ownership.
- send_to_lane at lane_node_server.py:402-442 falls back to broadcast when no owner exists.
- Protocol mismatch is only logged at lane_node_server.py:267-272; the node may still actuate.
- The token traverses plaintext HTTP and ws:// by default, so a passive LAN observer can recover
  the shared credential. Read-only scoring/state/display GET endpoints also remain public.
- WSL Systems/provision_wsl_tasks.ps1:41-49 invokes bare Python instead of the environment
  wrapper used by _autostart_api.bat:2-5. A reprovisioned server therefore does not reliably
  receive token, deduplication, URL, or monitoring settings.

**Failure mechanism:** Any LAN client can claim lanes 21/22 and receive or blackhole commands.
HTTP can report a successful WebSocket enqueue while the real node receives nothing. Even with
a shared token, a misprovisioned node can steal authority.

**Required correction:** Mandatory per-node identity, per-node credential, node-to-lane
allowlist, duplicate-owner rejection, exact protocol/capability gate, TLS/mTLS or an isolated
control VLAN, firewall allowlisting, command MAC/sequence/expiry, and startup refusal on any
development default. Separate public read-only display traffic from control APIs.

**Acceptance test:** Unknown identity, wrong lane claim, duplicate claim, replay, stale
heartbeat, wrong protocol, expired command, and wrong credential must all fail closed and make
health red.

### C-08 — The live lane display enables same-origin stored script execution

**Evidence:** Code-proven and copy-drift confirmed.

- WSL Systems/wsl_scoring_display.html:199-202 includes an escaping function.
- The copy actually served from wsl-lane-nodes/wsl_scoring_display.html lacks it and inserts
  raw bowl text at line 305 and raw player names at line 325 into innerHTML. The team value at
  line 371 is a URL/config-driven DOM-XSS sink rather than stored scorer data.
- server/lane_node_server.py:528-534 also inserts raw player names into its embedded simulator.
- lane_node_server.py:585-596 serves the vulnerable lane-node artifact.

**Failure mechanism:** A crafted bowler/team name can execute same-origin JavaScript. Because
the same origin exposes reset, correction, power, open, close, and cycle operations—and auth is
off by default—the display becomes a hardware-control attack path.

**Required correction:** One generated display artifact; DOM textContent for all dynamic text;
strict input length/content validation; Content-Security-Policy; control endpoints on a
separate authenticated origin; simulator disabled in production.

**Acceptance test:** Browser tests using HTML/script payloads in every name/team/metadata field,
plus a byte/hash parity gate for all deployed display copies.

### C-09 — Live outputs are the default while key board configuration remains provisional

**Evidence:** Code-proven and open release gate.

- lane_node/controller_daemon.py:60-73 and 528-542 make shadow mode opt-in; a bare start is live.
- WSL_LIVE_OUTPUTS is informational rather than a hard authorization.
- controller_daemon.py:186-205 labels UARTs, ARM pins, lane-22 I2C/watchdog fields, and other
  values as planned or bench-confirm placeholders.
- systemd/lane-node-controller.service:39 starts the bare live command.

**Failure mechanism:** A service installation, reboot, or operator typo can move real hardware
using unverified pin assignments or firmware posture.

**Required correction:** Default to shadow. Require an explicit --live action plus a
lane-specific signed configuration, exact firmware attestation, physical enable/key, completed
preflight, and single active hardware-owner lock.

**Acceptance test:** Default service start, missing environment, placeholder value, wrong board,
wrong lane, absent attestation, or competing owner must leave ARM and every output low.

### C-10 — The current board has no safe direct-24-VAC input front end

**Evidence:** Open release gate and circuit-proven.

- scripts/generate_kicad_netlist_revB.py:235-255 implements only
  FIELD_WET_V → 2.2 kΩ → PC817 LED → field input.
- docs/manual_src/08_opto-inputs.md:145-172 admits the proposed half-wave 1N4007 rectifier,
  10 µF filter, and 100 kΩ bleed have no placed footprints.
- docs/manual_src/06_board-power.md:218-226 describes the option more strongly than the copper
  supports.
- The selected PC817 LED has a 6 V reverse breakdown rating in the
  [UMW PC817 datasheet](https://www.umw-ic.com/static/pdf/56c3a4f58af79c3608299bd9810e59e0.pdf);
  direct 24 VAC exceeds it on every negative half-cycle.
- docs/phase8_lane21_harness_build_sheet.md:89-91 correctly leaves uncertain channels unlanded.

**Failure mechanism:** Treating a wet 24-VAC signal as a dry contact can damage the optocoupler,
produce unreliable sensing, or create an unsafe false state.

**Required correction:** Forbid direct AC landing. Classify every input at the powered machine,
then use a qualified rectifier/protection interposer or respin with an engineered AC input.

**Acceptance test:** Capture voltage, reference, RMS/peak, source impedance, transient, and
dropout for every channel. Test open, short, lead/reference reversal, minimum/maximum 24 VAC,
and brownout; the controller must produce a conservative known/unknown result.

### C-11 — Production FSM defaults preserve behavior described as mechanically wrong

**Evidence:** Code-proven and open physical-validation gate.

- lane_node/cycle_control_8270.py:71-88 defaults
  SKIP_TABLE_DESCENT_ON_SECOND_BALL to false even though the adjacent source says second-ball
  and foul cycles should not lower the table onto the deck.
- The same block defaults POLL_BS_LEVEL_IN_TABLE_FINISH to false even though its source says an
  already-full bin is the common case and no new edge will arrive after TABLE_FINISH begins.
- The simulator changes both globals only for its focused corrected-path checks at
  cycle_control_8270.py:600-619; the production defaults remain unchanged.

**Failure mechanism:** The controller can make the wrong second-ball table motion and can wait
for a ball-storage edge that already occurred, falling into timeout/manual recovery instead of
spotting a fresh rack. A simulator that temporarily flips the flags gives false confidence
about the shipped behavior.

**Required correction:** Resolve both sequences on the instrumented mule, remove mutable
module-global ambiguity, make the physically validated behavior the only production profile,
and include it in configuration attestation.

**Acceptance test:** Replay first ball, second ball, foul, full-bin-before-entry,
full-bin-after-entry, missing edge, and bounce against captured machine timing. Production and
test builds must execute the same configuration.

## 5. High-severity findings

### H-01 — Persistent RP2040 run mismatch is not a health fault

rp2040_link.py:412-457 retries three times and then logs. run_mismatch is excluded from
health_ok at lines 489-497 and is not consumed by the daemon. A reproduced case held T stopped
in the heartbeat while T was commanded RUN for four heartbeats; run_mismatch reported T while
health_ok remained true.

**Recommendation:** Disarm after one bounded mismatch interval. Use sequenced ACKs and physical
output/rail feedback. A lost RUN must never remove the independent maximum-run backstop.

### H-02 — Motion timeout is per FSM state, not per continuously energized actuator

cycle_control_8270.py:216-219 resets the timer on every state transition. A reproduced table
sequence remained energized 23.7 seconds across TABLE_DETECT, RUNTHROUGH, and TABLE_FINISH
without the claimed eight-second FSM timeout.

**Recommendation:** Track independent energized-since timestamps for every output, never reset
them on FSM transition, and use measured actuator-specific limits for S, T, SP, BE, M, and M2.

### H-03 — Motion-without-RUN supervision fails during another motor's legitimate run

firmware/rp2040/main.c:346-358 faults only if no guarded motor is running. A reproduced case with
T marked running and an unexpected S/SA motion produced no fault.

**Recommendation:** Compare each cam to its own motor state and test every cross-motor
combination.

### H-04 — Firmware-fault recovery is unreachable

PBZ/CLEAR handling is in controller_daemon.py:150-168, but the unhealthy branch at lines
306-326 returns before slow-edge handling. A reproduced firmware motion-timeout entered manual
intervention; PBZ emitted no CLEAR and could not recover.

**Recommendation:** Add a disarmed recovery state: force STOP all, accept one debounced recovery
request, send sequenced CLEAR, wait for a clean acknowledged heartbeat, then require a separate
press to arm.

### H-05 — PBZ has no debounce and does not prove physical zero

controller_daemon.py:299-304 detects raw edges. cycle_control_8270.py:159-184 makes successive
presses state-dependent. A True/False/True bounce ended READY, SECOND, and armed. The PBZ
precondition also checks only a partial interlock, not stable SA/TA1 zero.

**Recommendation:** Monotonic debounce, release qualification, minimum inter-press interval,
and stable fresh zero evidence—or a controlled disarmed homing procedure—before ARM.

### H-06 — Firmware attestation is stale across boots and legacy firmware is accepted

rp2040_link.py:313-347 does not clear all boot-scoped v1.1/max-run fields on a later boot that
omits them. maxrun_ok returns true for unknown legacy posture at lines 545-565. Tests explicitly
permit v0.1 to arm. A reproduced legacy boot retained the prior boot's maximum-run and v1.1
posture.

**Recommendation:** Clear every boot-scoped field on boot/session change and require an exact
fresh attestation.

### H-07 — RP2040 supervises UART intent, not physical relay state

controller_io.py:185-203 writes the MCP before sending RUN/STOP. Firmware state in
main.c:261-299 and 320-425 is driven by UART commands. There is no relay contact/current
feedback. A lost RUN can leave a physical relay on while the RP2040 thinks it is stopped,
removing max-run/cam-stop credit. A lost STOP normally leaves the RP2040 conservatively
believing RUN and should time out; it becomes hazardous when combined with a write, reset, or
physical-state divergence. A welded contact is not opened by either UART state.

**Recommendation:** Treat persistent state mismatch as fatal, add physical rail/output
feedback, and test lost/corrupt RUN and STOP independently.

### H-08 — The safety rail has unmonitored single-point bypasses

scripts/generate_kicad_netlist_revB.py:472-511 uses one Q14 pass device and single permit
transistors. A Q14 drain-source short bypasses watchdog, ARM, and RP_OK gating; no controller
input monitors RELAY_ENABLE_RAIL.

**Recommendation:** Do not claim safety-rated redundancy. Add independent rail feedback and, if
the hazard analysis requires it, an external dual-channel safety-rated device with guided
feedback. Keep feedback independent of the same Pi/MCP command path where practical. Inject
pass-FET and every permit-transistor short in validation.

### H-09 — RP2040_OK is exposed directly on J1

scripts/generate_kicad_netlist_revB.py:401-412 exports RP_OK on J1.13 without a buffer, series
resistor, or enforced open-drain boundary. A Pi configuration error, ribbon short, or miswire
can contend with the Pico and interfere with the permit. J1 also exposes direct board 5 V on
pin 1 and 3V3 on pin 11, creating avoidable rail-tie/backfeed risk.

**Recommendation:** Omit J1.1, J1.11, and J1.13 conductors on current harnesses and continuity
prove no Pi-to-board rail tie. Remove or one-way isolate these boundaries on the next board and
key the cable.

### H-10 — The SC/TB software echo models hardware that does not exist

rp2040_link.py:474-479 and firmware main.c:431-437 require independent SC and TB inputs. The
measured machine has one effective ladder node, no independent TB input, and opposite polarity
from the earlier assumption. Candidate C delegates collision protection to the OEM ladder, but
the software single-node redesign remains open in docs/phase8_interlock_redesign.md:126-127.

**Recommendation:** Implement the measured single-node model with independent configured
polarity, or explicitly remove all software safety credit. Preserve the mandatory per-lane OEM
S/T coil-drop proof.

### H-11 — Two lanes share one synchronous software control loop and blocking I2C

controller_daemon.py:447-483 ticks boards sequentially. controller_io.py:117-124 and 225-242
perform blocking I2C with no application deadline. A lane-21 bus hang stalls lane-22 cam
dispatch, watchdog kick, and motion timeout.

**Recommendation:** One isolated controller process/loop per board, independent watchdog
channel, bounded bus transactions, and a latency deadline that drops permission before a
mechanical stop can be missed.

### H-12 — Track A and Track B remain mutually exclusive

controller_daemon.py:21-24 states that server/scoring integration is not wired.
systemd/lane-node-controller.service:9-14 conflicts with lane-node.service. Track-B cutover
therefore removes automatic scoring/control connectivity, while a naive merge could cycle the
machine but suppress or duplicate scoring.

**Recommendation:** One local hardware-owner daemon with a durable internal event bus. The FSM's
accepted ball event should be the source for scoring and motion; camera, storage, and network
work must remain off the motion deadline path.

### H-13 — WSL commits state before knowing whether hardware accepted it

WSL Systems/wsl_phase8_bridge.py:63-153 returns only a Boolean and discards delivery detail.
wsl_api.py:845-895 and 956-1023 commits DB state and reports success independently of node
delivery. lane_node_server.py:986-1000 says hardware_command_sent=true even when sent_to=0.

**Recommendation:** A durable outbox/saga in the same DB transaction, idempotent command IDs,
local accepted/applied ACKs, and visible pending/degraded state. Rename the current field to
hardware_command_requested until that exists.

### H-14 — Blind retry duplicates non-idempotent actions

wsl_phase8_bridge.py:63-78 retries after any exception. OPEN/CLOSE/league operations reset
scorer state or pulse relays. A response-lost probe caused two POSTs.

**Recommendation:** Do not retry actuation until idempotency keys are persisted at server and
node. Split state synchronization from physical action.

### H-15 — Lane transfer is non-atomic and destroys Phase-8 score state

wsl_api.py:1098-1105 commits pair/main changes separately. Lines 1145-1155 implement transfer
as close-old/open-new. lane_node_server.py:968-984 deletes the source scorer on CLOSE, while
lines 944-959 reset the destination or its existing pair on OPEN.

**Recommendation:** One immediate DB transaction/CAS for all affected rows plus a lane-server
transfer operation that rekeys the existing scorer under the same session generation.

### H-16 — Legacy VDB and Phase 8 can both command the same lane

wsl_api.py:845-870, 1002-1023, and 1113-1155 invokes both backends. vdb.py:48-60 supplies a
nonempty legacy-controller default when no endpoint is configured. If that host is available,
the system has dual physical authority.

**Recommendation:** One explicit, mutually exclusive backend per lane. An unset endpoint must
disable legacy control, not select a historical address.

### H-17 — Phase-8 reconciliation depends on the legacy VDB module

The full Phase-8 startup rehydrate/reverse-sync block is nested under HAS_VDB_BRIDGE at
wsl_api.py:3435-3556. Removing the legacy bridge can disable Phase-8 recovery.

**Recommendation:** Extract Phase-8 reconciliation into an independent component; gate only
legacy actions on VDB availability.

### H-18 — No WSL session generation exists end to end

Mirror payloads carry rosters but no WSL session ID/generation. Open/closed is the only
reconciliation identity, and there is no periodic/reconnect reconciliation.

**Recommendation:** Put one immutable session generation into DB rows, scorer state, events,
commands, ACKs, and logs. Periodically reconcile identities, not just Boolean state.

### H-19 — Deployment can install a nonexistent lane server and still pass smoke tests

- WSL Systems/provision_wsl_tasks.ps1:22-23 and 41-49 defaults WslOps to
  C:/QDesk/wsl_ops and launches the nonexistent flat
  C:/QDesk/wsl_ops/lane_node_server.py with global Python.
- The canonical deployed program is C:/QDesk/wsl-lane-nodes/server/lane_node_server.py and
  needs its sibling modules and websockets dependency.
- WSL Systems/requirements.txt does not install websockets.
- Provisioning bypasses _autostart_api.bat, the wrapper that loads wsl_env.bat, and provides no
  equivalent lane-server environment.
- WSL Systems/deploy.ps1:98 force-kills every python/pythonw process.
- Its smoke test at lines 180-188 checks WSL API endpoints, not lane server port 8766 or lane
  ownership.
- Lines 87-91 and 190-195 attest only the WSL Systems revision. There is no atomic
  pinning/deployment or live-version proof for the wsl-lane-nodes commit, lane server, scoring
  engine copy, display copy, or active lane-server configuration.

**Recommendation:** One deployment manifest containing both commits, venvs, paths,
dependencies, environment, task definitions, migrations, and rollback. Stop only owned
processes. Smoke-test semantic lane health and actual owner identity.

### H-20 — Monitoring is falsely green

WSL Systems/wsl_monitor.py:55-59 requires only DB by default; lines 77-89 accept any 2xx without
parsing semantic JSON, and line 110 silently ignores unknown component names.
lane_node_server.py:651-674 always returns HTTP 200 with ok=true even with zero nodes, stale
heartbeats, incompatible protocol, disabled auth, or persistence failure.
deploy.ps1:180-188 checks only WSL API endpoints, and provision_wsl_tasks.ps1:40-46 does not
create the WSL Watchdog task documented separately in DEPLOY_RUNBOOK.md:52-56.

**Recommendation:** Explicit production requirement enumeration; fail on unknown names; set
and validate WSL_MONITOR_REQUIRE=db,analytics,lane_node; parse semantic health; return 503 when
any required lane is unowned, stale, mismatched, unauthenticated, or unable to persist.
Provision and test the WSL Watchdog scheduled task.

### H-21 — Relay manuals preserve the original dangerous pad map

docs/manual_src/09_relay-outputs.md:91-118 and 130-138 and
docs/manual_src/12_channel-maps.md:239-243 describe the old, wrong coil/contact pads. The
current correct G5LE-14 map is coil 2/5, COM 1, NO 3, NC 4.
docs/manual_src/13_layout-mfg.md:380-389 also calls G5LE-14 SPST-NO even though that exact
suffix is the fully sealed SPDT form.

**Recommendation:** Stop distributing the compiled manual until regenerated from one topology
source. Add exact MPN-derived pad assertions. The existing board audit only checks that a relay
reference touches the rail and would have passed the historical defect.

### H-22 — Relay load, contact life, and suppression are unqualified

docs/phase8_revC_change_list.md:73-76 keeps load/suppression open. The generic DNP
100-ohm/10-nF/MOV footprints do not specify qualified pulse, X2, or MOV parts. A guide suggests
the 10 A headline rating makes measurement optional, but contactor-coil inrush, power factor,
and opening energy cannot be inferred from DC resistance or the resistive rating. Omron's
[G5LE datasheet](https://components.omron.com/eu-en/system/files/2025-01/datasheet_pdf/K100-E1.pdf)
distinguishes 10 A resistive from 5 A inductive at 120 VAC; the actual low-voltage contactor
coils still require their own measured utilization/life assessment.

**Recommendation:** Keep suppression DNP until engineered. Measure current waveform and opening
transient for S/T/SP/BE/M/M2, calculate contact-life margin, test arcing/weld behavior, and
select exact rated suppression parts or an external suppressor.

### H-23 — Five-volt entry lacks branch protection and has an unresolved budget

scripts/generate_kicad_netlist_revB.py:414-419 shows only J2 plus a series SS14. There is no
fuse/PTC, TVS, or input bulk. Documentation alternates between at least 1 A and 1.5/3 A supply
guidance. With a multi-amp source, the diode or copper can become the fuse.

**Recommendation:** Lock the PSU, add branch fuse/PTC, transient/OV/reverse protection and bulk,
then test inrush, all-relays-on hot/low-line, brownout, short, reverse, and overvoltage.

### H-24 — Isolation claims exceed the selected converter's rating

The TMA0505S is specified for 1000 VDC functional insulation, not protective 1.5 kV isolation.
It is 5 V/200 mA, permits only 0.5 seconds of short circuit, and has material no-load/minimum-load
behavior. docs/manual_src/06_board-power.md:170-193 overstates the isolation. See the manufacturer's
[TMA series datasheet](https://www.tracopower.com/sites/default/files/products/datasheets/tma_datasheet.pdf).

**Recommendation:** Correct the declared safety boundary and working-voltage category. If
protective isolation is required, select a certified basic/reinforced converter and repeat the
creepage/dielectric review.

### H-25 — Fabrication provenance is mutable and internally inconsistent

- scripts/export_fab_revB.py hardcodes Rev-B names and recursively replaces its output.
- kicad/fab_revB_routed_manual/PROVENANCE.md:3-29 records that the routed board/order ZIPs are
  Rev-C-as-ordered, but the loose tree was edited after ordering and true local Rev-B evidence
  was overwritten.
- The loose upload README no longer matches manifest.json: expected 2067 bytes and SHA prefix
  fbcd7214; current loose file is 2107 bytes with SHA prefix b0e32644.
- WSL Systems retains stale competing generator/report copies.
- Export audits an existing PCB; it does not prove generator → netlist → board → fab
  equivalence.
- No current reviewable .kicad_sch is present under kicad, and the SKiDL/library/tool versions
  needed to regenerate the design are not locked.

**Recommendation:** Immutable revisioned packages; refuse overwrite; pin toolchain and exact
parts; deterministic clean-room generation; topology diff at every stage; manifest of all
nested archive contents; order/serial/hash record.

### H-26 — UART commands and events lack end-to-end integrity

firmware/rp2040/main.c:454-479 accepts bare RUN, STOP, CLEAR, and PING commands. CLEAR resets
faults without proving that the board is disarmed or physically stopped. Lines 486-503 have no
CRC, sequence, character whitelist, boot/session binding, or partial-line idle timeout.
rp2040_link.py:245-291 applies weak schema validation and drops firmware event timestamps when
queueing events.

**Recommendation:** Use a length-delimited framed protocol with CRC, boot/session ID, monotonic
sequence, strict types/ranges, command ACKs, and an idle timeout. Permit CLEAR only through the
dedicated disarmed recovery state after confirmed STOP-all and safe inputs.

### H-27 — Removing relay-coil permission cannot open a welded board contact

ARM, RP_OK, watchdog, and relay-enable-rail removal de-energize each G5LE coil. None can force a
welded G5LE machine contact open. A welded S/T/SP/BE/M/M2 board contact can therefore continue
completing its 24-VAC coil circuit until an independent upstream element interrupts it.

**Recommendation:** Deliberately bridge each board contact in a controlled test and prove the
expected upstream Stop/CIS, master breaker, OEM contactor, and collision-ladder response for
every channel. If the hazard cannot be independently removed and detected, add redundant
safety-rated series switching with guided feedback.

**Acceptance test:** Define the safe result for S, T, SP, BE, M, and M2; inject a welded-contact
equivalent; actuate each independent stop; and capture that the hazardous coil/current is
removed within its declared bound.

## 6. Medium-severity and hardening findings

### M-01 — MCP initialization exposes retained latch state

controller_io.py:105-115 programs IODIR before clearing OLAT. On a warm restart with retained
high latches this can briefly expose outputs. Clear OLAT first, set IOCON explicitly, then set
direction and verify all registers.

### M-02 — Gripper reads are non-atomic and open wires look like no pin

controller_io.py:230-242 combines two port reads. Active-low open circuits can be interpreted
as clear/no-pin, affecting strike and rack decisions. Require repeated identical samples,
plausibility, continuity diagnostics, and an explicit unknown state.

### M-03 — Event draining can lose the remainder after one exception

The daemon drains/clears queued events before dispatch. An exception while handling one event
can discard later cam or input events. Use a sequenced queue, acknowledge only after successful
state transition, and retain the failing event in the flight recorder.

### M-04 — Ball debounce uses wall time and an unsynchronized check/set

The Track-A callback uses time.time and does not atomically protect the last-event update. Use
time.monotonic and a lock or single-owner event loop.

### M-05 — HTTP control is single-threaded and accepts unbounded request bodies

lane_node_server uses HTTPServer and reads caller-provided Content-Length without a global
bound. One slow/large request can delay POWER_OFF and all other APIs. Use a bounded async or
threaded server, body/time limits, and separate control capacity.

### M-06 — Runtime legacy pickle loading is a code-execution path

server/state_store.py:404-420 automatically unpickles non-JSON legacy blobs. A replaceable DB
can execute code in the hardware-control process. Remove runtime pickle support; use a one-time
offline, signed migration.

### M-07 — Track-A service can restart before the watchdog expires

systemd/lane-node.service uses RestartSec=5 while the watchdog interval is about 11 seconds.
Failed cleanup can let a restarted service resume kicks without a true rail-drop/relatch.
Require a verified rail-low interval, StartLimit protection, and explicit relatch.

### M-08 — Cleanup pin maps and firmware pin maps have manual drift points

relay_cleanup.py and controller_cleanup.py duplicate pin assignments. The existing pin-map test
covers MCP maps but not RP2040/UART/RP_OK GPIOs against generator data. Generate all maps from
one source and test every safety pin.

### M-09 — An empty WSL roster opens DB state but skips Phase-8 hardware mirroring

wsl_api.py:700 permits an empty player list while mirroring at lines 859-870 is guarded by
if players. Reject empty rosters before commit or separate physical session open from roster
content.

### M-10 — Synchronous bridge calls can block requests and startup

Multi-second sequential timeouts/retries can stall a pair open for roughly 16 seconds when the
lane server is down. Move work to a durable asynchronous worker with short differentiated
timeouts, circuit breaking, and bounded parallel reconciliation.

### M-11 — Production correction route is not exercised by its contract test

Production maps the WSL correction route to lane-node /correct at
WSL Systems/wsl_api.py:1198-1216. tests/test_phase8_bridge_contract.py:14-15 and 90-96 directly
call the helper with /scoring/correct, which the actual server route at
lane_node_server.py:700-703 and 789-834 does not implement. The test bypasses the real Flask
route. Replace it with an end-to-end route contract.

### M-12 — Display max-possible math is wrong in the tenth frame

wsl_scoring_display.html:280-290 allows ten third-ball pins after every first-ball strike.
For X,6 it displays 26 where the engine correctly yields 20. Serve authoritative max_possible
from the engine or port its exact algorithm and add golden JavaScript tests.

### M-13 — Display series math double-counts cumulative totals

The browser stores prog_scratch, which is already cumulative, then adds a later cumulative
prog_scratch again at lines 254-274, 309-311, and 334-340. Return explicit current-game and
series totals from the server; do not reconstruct history in the browser.

### M-14 — Lane SQLite storage is operationally unmanaged

state_store.py defaults the live DB into the repository, outside the WSL backup process and
without an explicit data lifecycle. The repository .gitignore does not ignore *.db, and
STATE_DB_PATH is not provisioned, so live state can dirty a deployment or be committed.
Move it to a managed data directory, back it up with the SQLite backup API, and run restore
tests.

### M-15 — DRC rules omit two declared constraints

Current rules enforce logic-field, logic-machine, and independent machine-channel spacing, but
there is no explicit FIELD-to-MACHINE rule. Documentation claims 1.0 mm machine-copper edge
clearance while the project rule is 0.5 mm. Encode both and add negative fixtures.

### M-16 — Compiled documentation is stale

docs/phase8_revC_readiness_checklist.md:65-83 records that corrected J5 mapping has not been
regenerated into the compiled manual. Relay and interlock prose also contradict current
decisions. Build manuals from sources in CI and verify topology-linked tables.

### M-17 — Revision naming obscures the authoritative board

The authoritative board and fab directory still say Rev-B in filenames, while PCB silkscreen
and provenance identify Rev-C. This invites ordering, service, and audit mistakes. Assign a
new unambiguous revision/package identity without rewriting historical artifacts.

### M-18 — Pair and league configuration validation is incomplete

Arbitrary paired_with relationships are accepted, and normalizing a league pair by sorting lane
numbers can reverse the intended team-to-lane meaning. Validate only canonical physical partner
pairs. If lane order is normalized, swap all team/session semantics in the same transaction and
cover it with end-to-end tests.

### M-19 — Ordinary paired-lane open is not transactionally atomic

WSL Systems/wsl_api.py:753-785 commits the primary session, its players, the paired session, and
paired players through separate database commits. A process failure between them can leave a
half-created pair or partial roster.

**Recommendation:** One transaction for both sessions, all players, visit linkage, session
generation, and the durable command outbox.

### M-20 — Token normalization differs between components

The server and Pi strip surrounding token whitespace; WSL Systems/wsl_phase8_bridge.py:54 does
not. A trailing character from the Windows environment can create a difficult authentication
split. Normalize once at configuration load and reject empty/whitespace-only secrets.

## 7. PCB, harness, and physical safety assessment

### 7.1 What was verified

The authoritative current artifact is:

    kicad/wsl-phase8b.routed-manual.kicad_pcb

Its SHA-256 during this audit was:

    7E7ACFAAB75B827F5A98040A54D7574280F0C302F12D3BECDCD32BEA891EC97C

The board silk identifies REV-C. kicad/fab_revB_routed_manual/PROVENANCE.md explains that the
routed PCB and preserved order ZIPs represent Rev-C as ordered on 2026-06-26 despite legacy
Rev-B names. The present loose fab directory is not byte-for-byte as ordered because advisory
files were edited later.

Fresh KiCad 10 DRC on 2026-07-09 used:

    kicad-cli.exe pcb drc --severity-all --exit-code-violations --units mm
      --output <temporary-report> kicad/wsl-phase8b.routed-manual.kicad_pcb

It reported:

- 0 violations
- 0 unconnected pads
- 0 footprint errors

The project currently ignores footprints without courtyards, track endpoints not centered on
vias, tuning-profile geometry, footprint-filter mismatch, and footprint component-type/pad
mismatch categories. None produced a current routed-copper violation. Manual compensation in
this audit was limited to topology/pad/net checks and fab review; the ignore policy still needs
explicit disposition before the next board revision.

The topology audit reported:

- 250.15 × 225.15 mm, four layers
- 185 nets, 184 named
- 236 footprints
- no named net left in the Default class
- LogicSignal 80, Safety 13, Field 66, Power 4, Machine 21
- K1-K7 and Q14 on RELAY_ENABLE_RAIL
- GND and FIELD_GND distinct
- one filled GND zone and nine keepout rule areas
- 27 DNP references

BOM/CPL correlation was exact: 174 JLC-placed references plus 15 hand-solder references cover
all 189 non-DNP references. This proves reference-set correlation only; it does not prove part
suitability, allowed substitution, orientation, placement geometry, solderability, or
assembled-board operation. Vendor preview and first-article inspection remain mandatory.

K7/M1 and every suppression network remain DNP. They must not be populated without a new
engineering release.

The current relay copper is correct:

- G5LE-14 coil pads 2 and 5
- COM pad 1
- NO pad 3
- NC/unused pad 4

The part form and pin interpretation were checked against Omron's
[G5LE datasheet](https://components.omron.com/eu-en/system/files/2025-01/datasheet_pdf/K100-E1.pdf);
G5LE-14 is the fully sealed SPDT variant, not the similarly named SPST-NO model.

The historical Rev-B dead-relay mapping is **not** a defect in the current Rev-C copper.

### 7.2 What clean DRC does not prove

DRC cannot prove:

- correct firmware feature posture or pin polarity;
- mechanical cam/lobe semantics;
- watchdog behavior when software freezes high;
- relay contact life, weld behavior, or inductive suppression;
- correct field voltage classification;
- Stop/CIS or Candidate-C insertion-point landing;
- safe response to I2C/UART/network ambiguity;
- generator/netlist/PCB/fab semantic equivalence;
- system-level ownership, identity, or exactly-once command delivery.

### 7.3 Open board and harness gates

1. **First article:** all rails, I2C addresses 0x20/0x21/0x22, one relay, one LED, then all six
   relay make/break tests remain open.
2. **USB/SWD:** Rev-C did not clear the Pico USB obstruction and has no SWD. Flash and verify
   before soldering. The documented shaved-cable workaround must itself pass connect, BOOTSEL,
   flash, reboot, and version-readback testing; correct the next spin.
3. **FIELD_WET bleed:** not implemented. The provisional external 1 kΩ–2.2 kΩ, at least
   1/4-watt workaround must be measured across zero/minimum/maximum input loading; it is not by
   itself proof of five-volt regulation.
4. **Input classification:** every used/landed channel on each chassis needs recorded voltage,
   reference, contact form, and debounce. Several dry channels have evidence; cam/foul and other
   still-open channels must be closed before landing.
5. **Contact/suppression:** load current, inrush, opening transient, contact margin, and exact
   suppression remain open.
6. **Five-volt protection/budget:** exact supply, fuse/PTC, transient, brownout, and thermal
   evidence remain open.
7. **M2 Expander/shorting plug:** conceptually preserved in the harness but still requires
   cutover proof.
8. **Candidate C:** the OEM ladder was physically shown to kill both S and T coils, and
   Candidate C is formally selected. The actual board-contact insertion point must still be
   proved on every lane. J14 pins 1-2 use the sole documented, labeled Candidate-C engineered
   jumper.
9. **Stop/CIS:** J14 pins 3-4 remain unlanded/open. The rail intentionally cannot arm until a
   validated fail-safe interface exists; pins 3-4 must never be jumpered at cutover. If no
   suitable dry pair exists, stop and make a new engineering decision/interposer rather than
   landing an unsuitable tap.
10. **Cam windows:** powered edge, level, angle, lobe, and polarity capture is not complete.

## 8. Architecture assessment

### 8.1 Safety layers are present but not independent enough

| Layer | Intended protection | Current weakness |
|---|---|---|
| OEM S/T ladder | Collision prevention | Candidate-C proof is not complete at each board insertion point. |
| Stop/CIS chain | Remove permission | Real J14 3-4 landing is unknown/open. |
| ARM / RP_OK / watchdog rail | De-energize all relays | Stuck-high kick, single pass device, no rail feedback, RP_OK exported. |
| RP2040 | Cam stop and maximum run | Production posture off/unknown; UART-intent model; mismatch not fatal. |
| Pi FSM | Sequence and time limits | One-shot stop, state-reset timeout, ambiguous cam model, live default. |
| Server/node protocol | Deliver valid motion intent | Optional auth; no durable identity, TTL, ACK, or exactly-once semantics. |
| WSL lifecycle | Coordinate sessions | State-before-hardware, dual backends, destructive retry/reconcile. |

Several layers share the same Pi, configuration, UART intent, or sequential loop. They should
not be credited as independent safety barriers until common-cause failures are explicitly
analyzed and tested.

### 8.2 Recommended target architecture

1. **One actuator owner per physical board.** A local isolated controller process owns all
   motion GPIO/I2C and the rail.
2. **Fail-closed hardware boundary.** Independent windowed watchdog, physical rail feedback,
   safety-rated external chain where required, and no software-start default.
3. **Measured local state machine.** Both cam edges/levels/timestamps, per-output duration,
   conservative unknown states, and state-specific physical plausibility.
4. **Authenticated intent protocol.** Per-node identity, session generation, command ID,
   sequence, TTL, MAC, accepted/applied ACK, replay journal.
5. **Durable scoring event bus.** The local FSM publishes an accepted ball/foul event once;
   scoring persists and acknowledges it. Network/storage cannot sit on the stop deadline.
6. **Transactional WSL orchestration.** DB outbox/saga and visible pending/degraded status;
   process restart never pulses hardware.
7. **Immutable configuration/release.** Exact firmware, board, harness, deployment, and WSL
   commits form one signed release manifest.

### 8.3 Non-negotiable invariants

- Boot, restart, deploy, rehydrate, and reconnect cause zero physical motion.
- Loss, duplication, delay, or reordering of any network frame cannot produce extra motion.
- A single I2C/UART/process fault removes permission within the measured safe bound.
- Unknown input, unknown firmware, unknown owner, and unknown session are unsafe states.
- POWER_OFF invalidates every prior command.
- A motor's maximum energized duration is independent of FSM state transitions.
- No lane can have two actuator owners.
- A state change is never described as applied until the local controller confirms it.

## 9. Security and adjacent operational risk

### 9.1 Credential exposure

A live-mode payment credential pattern is present in a local ignored environment file and was
also found in repository history. The secret value is intentionally omitted from this report.

**Action:** Rotate/revoke it immediately, audit provider access, remove it from all hosts and
backups, and scrub or invalidate the repository history/remote exposure. Replace shared files
with a managed secret store and least-privilege deploy identity.

This is adjacent to the hardware project, but compromise of WSL-SRV can reach the unauthenticated
lane control plane, so it materially affects the safety case.

### 9.2 Network segmentation

Until the application protocol is fixed, restrict ports 8765/8766 to explicit management and
node addresses, block guest/public LAN access, and disable control endpoints not required for
bench work. A firewall is defense in depth, not a substitute for per-node identity and
application-layer replay protection.

## 10. Verification performed

### 10.1 Successful checks

- All 16 wsl-lane-nodes test files passed when isolated by file.
- All 68 WSL Systems test files passed when isolated by file.
- Relevant Python compilation passed in both repositories.
- RP2040 ARM cross-build completed successfully.
- Default firmware host safety suite: 64/64 passed with -Wall -Wextra -Werror.
- Forced-on v1.1 firmware host suite: 32/32 passed with -Wall -Wextra -Werror.
- Fresh KiCad 10 DRC: 0 violations, 0 unconnected pads, 0 footprint errors.
- Board topology audit: ALL PASS.
- Pin-map drift test: 2 passed.
- BOM/CPL/reference correlation: complete.
- The two scoring-engine copies have identical SHA-256 content.

### 10.2 Focused fault reproductions

| Probe | Result |
|---|---|
| MCP write fails, unrelated bit later written | Failed cached bit was asserted on the later write. |
| SB stop write raises | FSM stayed armed with sweep on and stop event consumed. |
| RP heartbeat disagrees with RUN | run_mismatch populated; health remained true. |
| Table spans multiple FSM states | Continuous table-on reached 23.7 s without FSM timeout. |
| S motion while T marked running | motion-without-RUN did not fault. |
| Firmware fault then PBZ | CLEAR was never sent. |
| PBZ bounce | Ended armed in SECOND ball. |
| New legacy boot after v1.1 boot | Old safety posture remained cached/accepted. |
| BALL_EVENT on closed lane | Server emitted CYCLE. |
| HTTP 200 with open=false | WSL bridge returned live=true. |
| Lost response on mirrored POST | Non-idempotent action was called twice. |
| Display copy comparison | Served copy lacks escaping present in WSL Systems copy. |
| Tenth-frame X,6 max | Browser calculation produced 26; engine result is 20. |

### 10.3 Test infrastructure weaknesses

A normal repository-wide invocation is not reliable:

    py -3 -m pytest -q

Collection aborts because script-style tests call sys.exit(0) at import, including
tests/test_cursor_resync.py. There is no CI workflow or pytest configuration to isolate these
scripts. Passing files therefore does not imply that a standard CI/test command is green.

**Recommendation:** Convert script tests to ordinary pytest tests or keep them outside
collection; add one documented runner; run Windows/Linux matrices; add cross-repository
contract, firmware profile, board-generation, browser security/math, and fault-injection jobs.

## 11. Mandatory remediation and release gates

### Gate 0 — Immediate containment

- [ ] Keep Track B shadow-only and prevent bare service starts from enabling outputs.
- [ ] Keep machine power disconnected during software/logic testing.
- [ ] Do not land any unclassified or potentially wet input.
- [ ] Restrict lane-control ports to approved hosts.
- [ ] Rotate the exposed credential and audit access.
- [ ] Freeze the current board/firmware/deployment identities for evidence.

### Gate 0A — No next PCB order

- [ ] Assign a unique Rev-C1-or-later source/fab identity; preserve every prior order artifact
  immutably and refuse overwrite.
- [ ] Prove generator → netlist → routed PCB → Gerber equivalence with exact critical-pad/net
  assertions, including relay, flyback, J1/J14, rail, and safety pins.
- [ ] Verify every recursive manifest hash/length and every nested ZIP member.
- [ ] Pin KiCad, Python, SKiDL, libraries, exact MPNs, and the clean-room build environment.
- [ ] Encode FIELD↔MACHINE and 1.0-mm machine-copper-to-edge rules; negative fixtures must fail
  every critical DRC barrier.
- [ ] Complete vendor layer/drill/orientation/pad preview and independent relay-pad inspection.
- [ ] Close USB access, FIELD_WET bleed/input front ends, watchdog stuck-high behavior,
  J1 isolation/keying, 5-V protection, contact loading, and suppression design.

### Gate 1 — Establish one source and one actuator owner

- [ ] Declare wsl-lane-nodes the canonical hardware/control source.
- [ ] Mark/remove stale competing WSL Systems hardware generators and reports.
- [ ] Define mutually exclusive per-lane backend ownership; disable legacy fallback.
- [ ] Integrate Track-B FSM with scoring without giving scoring direct actuator ownership.
- [ ] Enforce a process/OS hardware-owner lock and one controller process per board.

### Gate 2 — Production firmware and configuration

- [ ] Production safety firmware target with all approved features compiled on.
- [ ] Exact per-lane cam edges/lobes, pin map, maximum times, and polarity captured.
- [ ] Fresh boot/session attestation including hash, profile, debug, feature mask, and limits.
- [ ] ARM refuses every unknown, stale, legacy, debug, or mismatched posture.
- [ ] Persistent RUN/STOP mismatch drops ARM.
- [ ] UART protocol has framing, CRC, sequence, session, strict schema, ACK, and idle timeout.
- [ ] CLEAR is accepted only while disarmed and physically stopped.

### Gate 3 — Output and FSM fault safety

- [ ] Cache-after-success and OLAT readback/reconciliation implemented.
- [ ] First I/O/control exception drops ARM and persists a fault.
- [ ] Both cam edges and levels are queued with timestamps and state-specific phase checks.
- [ ] Per-actuator continuous-on timers and limits are independent of FSM state.
- [ ] Cross-motor motion-without-RUN logic corrected.
- [ ] PBZ debounce, release qualification, zero proof, and two-stage recovery implemented.
- [ ] POWER_OFF cancels every queued/in-flight prior command.
- [ ] All documented production FSM defaults match the physically validated sequence.

### Gate 4 — Hardware safety boundary

- [ ] Watchdog is safe for stuck-high, stuck-low, open, process freeze, and kernel halt.
- [ ] Watchdog interval is derived from mechanical damage limits.
- [ ] Physical relay-enable rail feedback is monitored.
- [ ] Current harness omits/unlands J1.1 (5 V), J1.11 (3V3), and J1.13 (RP_OK), and continuity
  proves no Pi-to-board power-rail tie; the next board isolates/keys these boundaries.
- [ ] J14.1-2 contains only the documented, labeled Candidate-C engineered jumper.
- [ ] J14.3-4 has an engineered fail-safe Stop/CIS interface, is never jumpered at cutover, and
  opening it drops the rail. If no suitable dry interface exists, redesign rather than improvise.
- [ ] Candidate-C S and T coil-drop is proved at the actual inserted board contacts on every lane.
- [ ] With each board contact deliberately bridged, independent upstream protection removes the
  hazardous S/T/SP/BE/M/M2 motion; otherwise redundant safety-rated switching is added.
- [ ] Required safety-rated external device/feedback is selected from a formal hazard analysis.

### Gate 5 — First article, inputs, power, and contacts

- [ ] First-article rails, I2C, all relay make/break, outputs, lamps, and defaults pass.
- [ ] Before machine coupling, a dummy-loaded safety truth table proves watchdog timeout/stuck
  input, ARM low, RP reset/fault, J14 design state, Stop/CIS open, brownout, and power loss each
  drops TP16 and the relay within the declared limit.
- [ ] Every used/landed input voltage/reference/form/debounce is recorded per chassis.
- [ ] No 24 VAC reaches the dry PC817 front end.
- [ ] Exact 5 V PSU, fuse/PTC, transient, reverse, inrush, brownout, and thermal budget pass.
- [ ] FIELD_WET bleed/minimum load is engineered and tested.
- [ ] S/T/SP/BE/M/M2 current, inrush, opening transient, contact margin, and life are measured.
- [ ] Suppression choice and exact components are qualified.
- [ ] Declared working-voltage/fault category and isolation requirement are reviewed; converter
  functional insulation, 0.5-second short behavior, no/minimum load, dielectric, and creepage
  are acceptable or a certified basic/reinforced part is substituted.
- [ ] Harness continuity proves logic GND to FIELD_GND/chassis open, only the intended
  FIELD_GND return exists, and every output remains isolated from logic and field.
- [ ] K7/M1 and all unqualified suppression components remain DNP.
- [ ] Enclosure, grounding, shielding, strain relief, connector keying, and cable labels pass.

### Gate 6 — Durable and authenticated control protocol

- [ ] Mandatory per-node credentials and node/lane allowlist.
- [ ] Duplicate owners and incompatible protocols are rejected.
- [ ] TLS/mTLS or a dedicated firewalled control network.
- [ ] Session generations on WSL state, scorer state, events, and commands.
- [ ] Persistent event/command IDs, ordered journals, TTL, replay protection, and ACKs.
- [ ] Closed/stale-session events cannot cycle.
- [ ] Startup/restart/reconcile is state-only and produces zero commands.
- [ ] WSL uses an outbox/saga and reports pending/applied/degraded honestly.

### Gate 7 — Deployment, monitoring, and recovery

- [ ] One immutable two-repository release manifest and atomic deploy/rollback.
- [ ] Correct lane server path, venv, dependency set, environment, and task definition.
- [ ] Deployment stops only owned services.
- [ ] Semantic health requires correct fresh owner for every production lane.
- [ ] WSL Watchdog task is provisioned with validated db,analytics,lane_node requirements.
- [ ] Health returns non-2xx for unsafe config, stale heartbeat, protocol mismatch, or persistence
  failure.
- [ ] Managed SQLite location, online backup, and tested restore.
- [ ] Clean power-loss, WSL restart, Pi restart, RP reset, network partition, and rollback tests.

### Gate 8 — Full fault matrix and staged rollout

- [ ] Fault-inject watchdog high/low/open; I2C NACK/hang; UART loss/corruption/reorder; RP reset;
  Pi freeze; state DB loss; network duplication; relay weld; Q13/Q14/Q15/Q16 shorts or bridges;
  brownout; Stop/CIS; OEM breaker and contactor.
- [ ] Record physical coil/rail waveforms and maximum stop latency for every case.
- [ ] Independent review signs the test evidence and configuration hash.
- [ ] Run one mechanically isolated mule, then one lane under attended operation.
- [ ] Require a defined clean-cycle count and zero unexplained timeout/overrun events before the
  second lane.
- [ ] Preserve immediate rollback to the OEM controller.

## 12. Prioritized implementation order

### First 48 hours

1. Enforce shadow/live opt-in and prevent automatic live Track-B startup.
2. Fix the restart open/closed classifier or disable destructive reverse reconciliation.
3. Firewall control ports; require token/identity in all provisioned environments.
4. Rotate the exposed credential.
5. Put a formal NO-CUTOVER marker on the current firmware and harness.

### First engineering sprint

1. Correct MCP write/cache semantics and disarm-on-I/O-fault behavior.
2. Implement exact firmware posture attestation and production build profile.
3. Replace the stuck-high-permissive watchdog interface.
4. Implement state-specific dual-edge cam modeling and continuous per-output timeouts.
5. Add durable event/command/session identity and accepted/applied ACKs.
6. Make restart/reconciliation strictly side-effect free.

### Before mechanically coupled or live-machine motion

1. Progress in controlled stages: logic-only; energized board with dummy loads; machine coil
   circuits with motors unplugged; isolated mule; then one attended lane.
2. Close Stop/CIS and Candidate-C insertion proof.
3. Classify all used inputs and qualify the AC interposer/respin.
4. Close power, fuse, isolation, thermal, relay-contact, and suppression evidence.
5. Correct manuals, exact relay assertions, DRC policy, fab provenance, and manifests.
6. Execute the complete fault matrix with measured rail/coil traces.

## 13. Strengths worth preserving

- Current Rev-C relay pads are correct.
- Fresh DRC/topology/BOM/CPL results are clean.
- GND and FIELD_GND are distinct; named netclasses and keepouts are active.
- PCB topology keeps machine motor current off-board; final dry-contact harness insertion is
  still a cutover gate.
- The architecture intends to retain OEM contactors, braking, master breaker, and Candidate-C
  ladder; each lane still requires insertion-point proof.
- Outputs and ARM have early-low/pulldown intent.
- Firmware has bounded line buffers, watchdog/chatter mechanisms, and duplicate-RUN timer
  protection.
- Daemon cleanup, systemd post-stop cleanup, bounded command queues, manual relatch after health
  loss, and asynchronous flight recording are useful foundations.
- Scoring-engine copies currently match and core scoring/state tests are extensive.
- send_open_command=false is a good state-only primitive once reconciliation is fixed.
- State serialization is explicit/versioned and preserves cross-lane identity.
- Server locking, heartbeat metadata, constant-time token comparison, and token redaction should
  be retained.
- Project documentation candidly records many open physical gates. Preserve that honesty and
  convert it into machine-enforced release criteria.

## 14. Final recommendation

The hardware-independence design is coherent as a prototype and contains enough good structure
to continue. It is not yet a safe unattended controller.

The next milestone should not be “make the full machine cycle.” It should be a controlled
safety mule proving three things with captured waveforms and injected faults:

1. every single software, bus, UART, and watchdog failure removes motion permission within the
   measured safe time;
2. every physical input and cam transition has an unambiguous, state-specific meaning; and
3. restart, retry, reconnect, and duplicated messages can never create a physical pulse.

Only after those properties are demonstrated should scoring integration, UI polish, or fleet
deployment become the critical path.
