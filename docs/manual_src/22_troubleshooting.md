## 22. Troubleshooting, Maintenance & Spares

> **Read §22.0 (safe handling) before touching anything.** This system commands AC
> motors that move heavy mechanism near people. Almost every fault below can be
> diagnosed at the bench or from a log; the few that require reaching into the
> machine require lockout first. When in doubt, the safe state is **manual desk
> scoring + the original controller still cycling the pinsetter** — Track A is
> read-only and Track B is not yet cleared for live machines, so you can always
> fall back without any machine risk.

This section is the field-service guide: **symptom → likely cause → fix**, plus
the maintenance routine, the spares list, and the safe-handling rules. It assumes
the architecture from the earlier sections. Cross-references point to:

- **§2, System Architecture & Signal Chain** — the end-to-end picture.
- **§5, Rev-B Controller Board: Overview, Domains & Isolation** and **§6, Rev-B Power Architecture** — board layout, the three electrical domains, power rails.
- **§7, Rev-B Logic: RP2040 Co-processor + MCP23017 Expanders + I2C** and **§8, Rev-B Field Inputs: PC817 Opto-isolators** — the logic + input front-ends.
- **§9, Rev-B Machine Outputs: G5LE Relays** — the relay output stage.
- **§10, Rev-B Safety Hardware: NE555 Watchdog + Relay-Enable Rail** — the
  board-side permissions, Candidate-C source jumper, and test pads (the single most
  important section for "relays won't energize").
- **§11, Rev-B Connector Pinouts (J1–J14)** and **§12, Rev-B Channel Maps** — connector pinouts and the GPIO/MCP bit maps.
- **§14, Machine Interface: C1/C2A Connectors & the Adapter Harness** — machine-side wiring.

Every fact here is grounded in the live files: `firmware/rp2040/config.h` +
`firmware/rp2040/README.md` (RP2040 pins/timing/protocol), `lane_node/controller_daemon.py`
+ `lane_node/controller_io.py` + `lane_node/rp2040_link.py` + `lane_node/cycle_control_8270.py`
(the Pi-side control software), `docs/phase8b_pcb_revB_spec.md` §4 (the safety-rail
contract), `docs/phase8_trackA_golive_runbook.md` (scoring go-live + failure
cheat-sheet), and the assembly BOM
(`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`).

---

### 22.0 Safe handling — read before every job

These are non-negotiable. They come straight from the design contract
(`docs/phase8b_pcb_revB_spec.md` "Non-negotiable safety rule", §4.5) and the
firmware safety model.

1. **The controller board is never the only safety device.** The machine's
   upstream **Stop switch + C.I.S. (cover interlock) → master circuit breaker**
   chain, the **TB/SC collision interlock**, and the motors' **regenerative
   braking** all stay in hardware, independent of any software. Do not defeat,
   jumper-out, or "temporarily bypass" any of them.

2. **Lockout/tagout before touching the machine mechanism or its wiring.** The
   relay-enable rail removes *coil drive*; it **cannot open a relay contact that
   has welded closed** (§10.6, spec §4.5). The only guaranteed kill is the
   **rear-panel master circuit breaker** (cut by the Stop/C.I.S. chain). Cut and
   lock the master breaker before reaching into the pinsetter. Track-B bench and
   cutover work is explicitly **"on a LOCKED-OUT / off machine only"**
   (`firmware/rp2040/README.md` §"Bench bring-up"; spec §12.9).

3. **GPIO is 3.3 V only.** The RP2040 and the MCP23017s run at **3.3 V** (the
   MCP23017s are on 3.3 V specifically for Pi-safe I²C — spec §6.1, §8.1). **Never
   wire a machine voltage (24 VAC, 15 VDC, etc.) to a Pi/RP2040/MCP pin.** Every
   machine input must cross a **PC817B opto** first (§8); every machine output
   crosses a **G5LE relay contact** (§9). The opto logic sides and MCP inputs are
   already 3.3 V and Pi-safe by design — keep them that way. If you add a test
   front-end, use opto isolation or a contact-to-a-reference scheme, never a
   direct tap.

4. **Logic ground (GND) and field ground (FIELD_GND) are intentionally
   separate** and share **zero nodes** (the isolation barrier — §5, §6). Do not
   bond them with a probe clip, a scope ground, or a "temporary" jumper. The
   isolated field-wetting supply (TRACO TMA-0505S, ref **U37**) exists precisely
   to keep a machine-side fault from backfeeding the Pi.

5. **Bring up power before signals, and bring up the rail last.** The documented
   bench order (§10.8, spec §12.9, firmware README) is: power rails → I²C
   enumerate → RP2040 boot + heartbeat → **watchdog drop** → **arm drop** →
   **J14 source-position drops** → each relay with a *dummy load* → input
   front-ends → motion-timeout / qualified cam-stop drop → **only then** the
   machine harness. Candidate-C TB/SC protection is proven separately at G3 by
   commanding S and T and forcing both OEM levers BACK/open.

6. **The board fails open by construction.** On loss of logic power, watchdog
   kick, RP2040 health, arm permission, or an implemented source loop, its relay
   coils go dead. Separately, the preserved OEM TB/SC ladder must block S/T when
   both levers are BACK/open. If you are unsure of a board's state, the *correct*
   default is motion-dead — so a "dead" rail during diagnosis is the safe
   condition, not necessarily a fault.

---

### 22.1 Fast triage — which subsystem is failing?

Decide which of the three independent subsystems is misbehaving before you dig in.
They fail independently and have different fixes:

| You observe… | Subsystem | Go to |
|---|---|---|
| A lane stops scoring, or scores wrong, but the pinsetter still cycles normally | **Track A — camera scoring** (read-only; never affects the machine) | §22.2 |
| The lane "went dark" after a power blip / reboot — no scoring node at all | **Pi service / provisioning** | §22.3 |
| (Track B, bench/cutover) relays won't energize / the rail is dead | **Safety rail** (an implemented permission/source position is open) | §22.4 |
| (Track B) a motor runs and then the whole board faults; relays drop | **Motion-timeout / cam-stop** | §22.5 |
| (Track B) cam/ball events missing, RP2040 reported unhealthy | **RP2040 link / UART** | §22.6 |

> **Track A vs Track B blast radius.** A Track-A (scoring) fault can never move the
> machine — the existing controller is still cycling the pinsetter and the code
> auto-falls-back to manual desk scoring (`docs/phase8_trackA_golive_runbook.md`,
> "Safety/blast-radius"; `lane_node/lane_node.py` `_init_camera()` /
> `_settle_capture_emit()`). Track-B faults are about *machine control* and are why
> the layered safety architecture exists.

---

### 22.2 Track A — camera scoring faults (read-only, safe)

Track A taps the QubicaAMF **T-Camera** composite video through the **VIXLW USB
dongle** into the Pi, and detects standing pins by **difference-from-empty**
(§2, §18/Track A). It is read-only with respect to the machine and auto-falls back
to manual on any failure. The authoritative procedure for all of this is
`docs/phase8_trackA_golive_runbook.md`; this is the service-desk condensation of
its failure cheat-sheet plus the exact code paths.

#### 22.2.1 "detector NOT ready" / lane silently falls back to manual

**Symptom (in `journalctl -u lane-node`):**
```
Camera mode but detector NOT ready (no empty ref / cv2).
Balls will fall back to manual desk scoring until fixed.
```
(emitted by `lane_node/lane_node.py` `_init_camera()` when `PairCamera.ready` is
false). You will also see `_settle_capture_emit()` log `camera yielded no mask ->
awaiting_manual (desk score)` per ball.

| Likely cause | Fix |
|---|---|
| **`empty_ref.png` missing or unreadable.** The detector compares each ball's frame to a stored cleared-deck reference; with none, it cannot detect. The file is gitignored — **each Pi captures its own** (it is *not* pulled by `git pull`). | Clear **both** decks (cycle 21 and 22 so all pins are swept), then on the Pi: `cd /home/pi/wsl-lane-nodes` → `.venv/bin/python3 lane_node/camera.py --capture-empty` (add `--device 1` if the dongle is `/dev/video1`). Saves `lane_node/empty_ref.png` (720×576). Verify non-zero size; ideally scp it off and eyeball that it really is an empty deck under normal lighting. Restart: `sudo systemctl restart lane-node`. Confirm the log now shows `Camera ready for lanes [21, 22] (settle=2.5s).` |
| **OpenCV/PyAV import failed (`cv2`).** `PairCamera` needs a capture backend. | `.venv/bin/python3 -c "import numpy, PIL, av; print('deps ok')"` — if `av` fails, `.venv/bin/pip install av` (or `pip install opencv-python`; either backend works). |

> **This is not dangerous.** "Detector not ready" means the lane simply scores
> manually at the desk via `POST /api/lane/N/score` — the pinsetter still runs.

#### 22.2.2 Black frame / `--test` always reads 0 or 1023 (mask never changes)

**Symptom:** `.venv/bin/python3 lane_node/camera.py --test` prints all-black, or the
per-deck mask is stuck at `0` (empty) or `0b1111111111` = `1023` (full rack)
regardless of what's actually standing.

| Likely cause | Fix |
|---|---|
| **Missing video ground on the camera tap** — the single most common hardware trap, identical to the original QubicaAMF tap. The composite tap is **Brown = video / Blue = ground**; the RCA shell must reach Blue (pin-8 ground). | Reseat the tap **ground** (RCA shell → Blue / pin-8). This is wiring, **not** a code bug. |
| **Dongle not enumerated** (no `/dev/video0`) | `ls -l /dev/video*` (expect ≥ `/dev/video0`); `v4l2-ctl --list-devices` should show a USB Video/UVC device. Reseat USB; check `dmesg`. If it enumerates as `/dev/video1`, set `WSL_LANE_CAMERA_DEVICE=1` on the service. |

#### 22.2.3 Scores are wrong but consistent

**Symptom:** detection runs, but a particular pin/spot is repeatedly misread (the
*same* error every time), not random flakiness.

| Likely cause | Fix |
|---|---|
| **Per-spot calibration** — that pin's region coordinate (`PIN_SPOTS_PX`) or the per-frame threshold is slightly off. Pins **2 & 3** are the homography-predicted spots (watch these first); the **right deck** is more oblique, so its margins are tighter. | This is a tuning item, not a redesign. Keep a tally of **detected vs actual** standing pins per ball; capture a couple of misread frames. The fix is a `PIN_SPOTS_PX` coordinate nudge or a `DET_THR` adjustment (calibration lives in `lane_node/pin_detect.py`). Send the tallies + frames to whoever owns the detector calibration. |
| **Whole-frame flakiness that tracks the house lighting** (lights on/off, sun) | Re-measure / bump `DET_THR`. The detector already drift-corrects for exposure, so this should be rare; last resort is an IR illuminator + IR-pass filter. |

#### 22.2.4 Nothing happens on a ball

| Likely cause | Fix |
|---|---|
| **DIELL ball detector not firing**, or the node is in the wrong mode | Watch the log for `GPIO: ball detected on lane N, mode=camera`. If that line never appears, the DIELL beam isn't tripping the input. If it appears but no score, confirm the mode is `camera` (see below). |
| **Wrong scoring mode** | `WSL_LANE_SCORING_MODE` must be `camera` for auto-scoring. `manual` = desk scores (ball event emitted with no `pin_mask`); `disabled` = log only. Default is `manual` (`lane_node/lane_node.py`). |

#### 22.2.5 Track A mode/tuning knobs (env vars on the `lane-node` service)

Set these via `sudo systemctl edit lane-node` (a drop-in survives reboot), then
`sudo systemctl restart lane-node`:

| Var | Default | Meaning |
|---|---|---|
| `WSL_LANE_SCORING_MODE` | `manual` | `camera` = auto-score; `manual` = desk scores; `disabled` = log only |
| `WSL_LANE_CAMERA_SETTLE_S` | `2.5` | seconds after DIELL fires before grabbing the frame (tune if catching the sweep or pins still rocking) |
| `WSL_LANE_CAMERA_DEVICE` | `0` | capture device index (`/dev/videoN`) |
| `WSL_LANE_CAMERA_STUB` | `0` | `1` = synthetic masks — **bench only, never on a live lane** |
| `WSL_LANE_SERVER_URL` | `ws://localhost:8765` | the WSL-SRV server (currently `ws://192.168.4.103:8765`) |

> **To abort Track A to manual instantly:** flip `WSL_LANE_SCORING_MODE=camera →
> manual` and `sudo systemctl restart lane-node` (or Ctrl-C the foreground daemon
> and relaunch without the env var). **No machine impact** — the lane keeps
> running; the desk scores via the existing flow.

#### 22.2.6 Server-side check (WSL-SRV)

The scoring **server** (`lane_node_server.py`) runs on WSL-SRV at **ports 8765
(WebSocket) + 8766 (HTTP)**. Health from any LAN machine:
```
curl http://192.168.4.103:8766/api/health
```
returns JSON with the connected node. The per-lane scoring display is
`http://192.168.4.103:8766/display?lane=N`. A manual correction is always available:
`POST /api/lane/N/score {pin_mask, foul?}`.

> **(VERIFY: WSL-SRV IP.)** The server IP is **192.168.4.103** as of the 2026-06-03
> eero router swap (the old `192.168.86.36` is dead), but the DHCP reservation was
> still a TODO in the runbook — **confirm the current WSL-SRV IP and that it is
> reserved on the eero** before relying on these URLs. (`docs/phase8_trackA_golive_runbook.md` banner.)

---

### 22.3 "Lane went dark after a power event" — service not enabled

**Symptom:** a lane (or the whole node) has **no scoring at all** after a power
blip, UPS event, or reboot — not "wrong score," but *gone*. Health check shows the
node disconnected.

**Likely cause:** the systemd `lane-node` service is **loaded/active but not
`enabled`**, so it does **not** start on boot. This is a real trap that was hit on
the bench rig: the service ran fine for days only because the Pi had not rebooted.

**Fix:**
```bash
sudo systemctl enable lane-node      # make it start on boot (the missing step)
sudo systemctl restart lane-node     # start it now
systemctl is-enabled lane-node       # must print: enabled
journalctl -u lane-node -f           # confirm it comes up
```

> **Provisioning rule:** `systemctl enable lane-node` **must** be part of every
> node's provisioning runbook. The symptom of a missing enable is exactly "lane
> goes dark after any power event." (`docs/phase8_trackA_golive_runbook.md`
> failure cheat-sheet; project provisioning note.)

> **(VERIFY: the Track-B controller daemon's own service unit.)** The
> `lane-node` service above is the **scoring** node (`lane_node/lane_node.py`). The
> Track-B **controller** daemon (`lane_node/controller_daemon.py`) is a *separate*
> tight synchronous control loop and is **not yet unified** with the scoring/server
> path (the file's `TODO(server)`); its production service unit / `systemctl enable`
> step is a cutover item not fixed in the files read here. The same enable-on-boot
> rule will apply.

---

### 22.4 Relays will not energize / the rail dropped (Track B, bench/cutover)

> **Context:** This applies to the **Track-B controller board** during bench
> bring-up or cutover — Track B is **not yet cleared for live machines**. Do this
> on a **locked-out / off** machine (§22.0).

A motion relay (S/T/SP/BE/M/M2) energizes **only if both** of two independent gates
are satisfied (§9, §10.5):

- **(a)** the Pi sets that relay's bit on **MCP23017 OUT-A** (chip `0x22`) — turns
  on the per-relay NPN driver that grounds the coil low side; **and**
- **(b)** the **relay-enable rail** (`RELAY_ENABLE_RAIL`) is live — supplying +5 V
  to the coil high side through the pass-FET **Q14 (AO3401A)**.

Software alone can never fire a coil. If relays won't energize, first determine
whether the **rail** is dead or the **command** is missing.

#### 22.4.1 First measurement: is the rail live?

Probe **`RELAY_ENABLE_RAIL` at TP16** (the rail test pad; §10.8):

- **≈ +5 V** → the rail is up; the problem is the command path (jump to §22.4.3).
- **≈ 0 V** (or pulled toward the coil-low side through the coils) → the rail is
  dead; an implemented gate/source position is open (continue below).

#### 22.4.2 Board permissions and the separate Candidate-C OEM guard

The PCB contract names six conditions, but lane 21/22's Candidate-C field
implementation does **not** put TB/SC on J14. Pins 1–2 carry the controlled,
labeled jumper; pins 3–4 carry Stop/CIS. The OEM parallel closed-when-safe TB/SC
contacts remain separately in the S/T coil ladder. Read the board permissions in
this order, then run the separate G3 coil proof:

| # | Condition | How to read it | "Permit" state | Common cause of a false |
|---|---|---|---|---|
| 2 | **Arm OK** | `ARM_PERMIT` at **J1 (J_PI) pin 8** | HIGH | Pi hasn't armed: FSM not in a runnable state, or it latched into MANUAL_INTERVENTION/FAULT (§22.5). Default false via R108 100 k base pulldown. |
| 1 | **Watchdog OK** | `WDOG_KICK` at **J1 pin 7** should show periodic pulses; `NE555_OUT` (U36 pin 3) toggles; `WDOG_OK_PULLDOWN` (Q13 drain) pulled to GND while OK | kicks present | Pi process hung/stopped → no kicks → NE555 times out → Q13 off. Or the kick GPIO isn't wired/asserted. |
| 3 | **RP2040 OK** | `RP2040_OK` = **GP2**, at **J1 pin 13** | HIGH | RP2040 unpowered / in reset / BOOTSEL / firmware crash / cam-stop or motion-timeout fault. GP2 is Hi-Z when unpowered → R110 100 k holds Q16 off. |
| 4 | **Enabled cam-stop OK** | *(not a separate transistor)* — folds into condition 3 | (see #3) | An enabled enforcement fault or the active motion timeout drives **GP2 LOW**. Stock v1.2.3 measured-cam flags are OFF. |
| 5 | **J_SAFE1-2 board source position** | controlled Candidate-C jumper on **J14 pins 1↔2**; `SAFE_TBSC_RETURN` | keyed/labeled jumper present | Missing/loose controlled jumper. This is **not** a TB/SC field sensor and opening it proves only PCB/source continuity. |
| 6 | **Stop/CIS/master chain** | measured external loop on **J14 pins 3↔4**; `SAFE_STOP_RETURN` (Q14 source) | loop closed | Stop/C.I.S. loop open, or J14 Stop/CIS wiring broken. |

**Structural facts** (so you know what to expect on a meter):

- **J_SAFE1-2 and J_SAFE3-4 are in series with the FET source.** +5 V enters
  J14.1, traverses the Candidate-C jumper to J14.2, crosses the on-board
  J14.2/J14.3 net, then traverses Stop/CIS to J14.4 and the pass-FET source.
  Opening either connector position kills the rail, but only 3–4 is a machine
  loop on lanes 21/22.
- **Conditions 1, 2, 3(=4) are a series transistor stack on the FET *gate***
  (`RAIL_GATE`, held up to the source by R106 100 k = off by default):
  **Q15 (ARM) · Q16 (RP2040_OK) · Q13 (watchdog) must all conduct** to pull the
  gate low and turn the P-FET on. Any one off → gate stays up → rail dead.

> **Candidate-C diagnostic boundary:** if J_SAFE1-2 is open, the rail should be
> dead; restore only the documented keyed/labeled jumper. Never search C2A-U or a
> ~21 Ω cold-continuity path for a replacement field loop. The authoritative
> collision test is live/per-lane under the runbook's guarded procedure: command S,
> then T, force both levers BACK/open, and require each machine coil to remain dead.
> A failure means the board output bypassed the OEM ladder: abort and roll back.

#### 22.4.3 Rail is live but a specific relay won't fire

If TP16 is ≈ +5 V but one output doesn't actuate, the **command** path or that
**channel** is the problem:

| Likely cause | Check / fix |
|---|---|
| **Pi isn't setting the OUT-A bit** | The FSM drives relays via `MachineIO._set_out()` over I²C to MCP23017 `0x22`. Confirm the FSM is actually in a state that commands that motor (§22.5 / §3). |
| **Wrong bit ↔ relay mapping** | `controller_io.OUT_A_MAP` is the source of truth and is regression-checked against the netlist generator. S=(0,0), T=(0,1), SP=(0,2), BE=(0,3), M=(0,4), **M2=(0,5)**, **M1=(0,6)**; lamps first_ball=(0,7), second_ball=(1,0), strike=(1,1), foul=(1,2). (M2 is bit 5, **before** M1 bit 6 — per the generator. BS/OS, M1/M2, strike/foul were once swapped and have been corrected to match the netlist — see §12.) |
| **M1 (ball return) won't fire — by design** | **K7/M1 is DNP** (do-not-populate): not bench-confirmed on these chassis and the FSM doesn't drive it. The coil/driver/flyback footprints exist on the rail but are not assembled. Do not expect M1 to work until it is verified at-machine and populated (spec §3.2, §11 item 6). |
| **I²C bus not enumerating** | All three board MCP23017s must come up: **IN-A `0x20`, IN-B `0x21`, OUT-A `0x22`** on the board's own bus. If `MachineIO` can't open the bus or a chip NAKs, no outputs (or no slow inputs) work. Confirm with `i2cdetect` on the board's bus and check the 3.3 V rail + the two 4.7 k I²C pull-ups. |
| **Coil driver / relay fault** | Probe the per-relay NPN (Q1–Q6 for S/T/SP/BE/M/M2; Q7 is M1 DNP) and the coil. The flyback diodes are D1,D3,D5,D7,D9,D11 (1N4148WS) across the coils. |

#### 22.4.4 A relay coil drops but the machine circuit stays made (welded contact)

**The rail de-energizes coils; it cannot open a welded-closed contact** (§10.6,
spec §4.5). If a contact welds, dropping the rail removes coil drive but the welded
contact — and the machine control circuit it feeds — stays made.

- The **final physical stop is the rear-panel master breaker** (Stop/C.I.S. chain),
  not the rail. Cut it.
- This is why **relay contact rating + arc suppression are safety-relevant.** Each
  motion output has **DNP** footprints for an RC snubber (`Rsnub_*` 100 R +
  `Csnub_*` 10 nF X2) and a **MOV** across the contact — populate per output after
  measuring the actual inductive AC control load (spec §2.3, §3.2, §11 item 1).

---

### 22.5 Motion-timeout / cam-stop faults (Track B)

**Symptom:** a motor starts, runs longer than expected, then **everything stops and
the rail drops**; the FSM/firmware reports a fault.

There are **two independent timeout backstops**, both at the same 8-second budget,
which together fail the motion safe:

1. **FSM software backstop — `MAX_MOTION_S = 8.0 s`** (`cycle_control_8270.py`).
   In `poll()`, if any motion state (`SWEEP_TO_GUARD`, `TABLE_DETECT`,
   `RUNTHROUGH`, `SPOTTING`, `TABLE_FINISH`) is held longer than `MAX_MOTION_S`,
   the FSM logs `FAULT — <state> > 8.0s; motors OFF`, drives all motors off, and
   enters `State.FAULT`.
2. **RP2040 firmware backstop — `MAX_MOTION_MS = 8000` ("cam timeout", spec §4.2;
   `firmware/rp2040/config.h`).** If the Pi marks a *guarded* motor `RUN` over UART
   and never `STOP`s it within 8 s, the firmware **latches a fault and drops
   `RP2040_OK` (GP2) LOW** → rail dead. It emits `{"ev":"flt","code":"motion_timeout","m":"S"}`.
   (BE and M are **not** max-run-guarded — BE is continuous, M is master/power.)

| Likely cause | Fix |
|---|---|
| **A motor genuinely never reached its cam-stop angle** (mechanical bind, slipping cam, motor not turning, or a cam switch not tripping) | This is the backstop doing its job. Lock out and inspect the mechanism / the relevant cam switch (§3, §4). The cam that should have stopped the motion: SA (sweep 270 run-through / 360 zero), SB (sweep 66 guard), TA1 (table 355 zero / 185 delay reset), TA2 (table 260). |
| **`MAX_MOTION_S` / `MAX_MOTION_MS` set too tight** for the real machine | The field rule is "set = measured + margin" (`cycle_control_8270.py` comment). If a *healthy* motion legitimately takes longer than 8 s on this machine, the budget needs raising — but **measure first**; do not loosen a safety backstop without data. |
| **Cam edge polarity / cam-stop overrun** | v1.2.3 contains the enforcement code, but all measured-cam flags ship **OFF**. Capture each independently landed motion-cam edge→angle polarity, bind only confirmed values into a **new controlled release**, and pass its bench gate. Stock v1.2.3 provides health + max-run only. |

**To recover from a latched fault** (firmware side):
- The Pi sends **`CLEAR`** to the RP2040 **only from a known-safe zero/ready
  state**; the firmware then re-permits (GP2 back HIGH). In the daemon, `CLEAR` is
  sent together with the operator's **First-Ball-Zero (PBZ)** re-arm
  (`controller_daemon._slow_actions`: PBZ → `fsm.first_ball_zero()` **and**
  `link.clear()`).
- The FSM's own `FAULT`/`MANUAL_INTERVENTION` states require a **deliberate
  First-Ball-Zero (PBZ)** to return to `READY` — there is **no auto-rearm**
  (`controller_daemon.py` health-loss safety trip; self-test "recovery does NOT
  auto-rearm"). This is intentional: a stale relay latch must never silently
  resume motion.

> **Power-restore behavior is the same idea:** the FSM comes up in
> **MANUAL_INTERVENTION** and drives nothing until the operator presses PBZ
> (`power_restore()`; the MP "Power-Down" rule, spec §5). A board that just powered
> on and "won't move" is behaving correctly.

---

### 22.6 RP2040 link dead / cam & ball events missing (UART)

**Symptom:** cam/ball events stop reaching the FSM; the daemon logs the RP2040 link
**LOST** and trips safe; `RP2040_OK`/the rail drops.

The RP2040 owns the **8 fast inputs** (6 cams + 2 DIELL ball beams) and pushes edge
events to the Pi over **UART0, 115200 8N1, newline-delimited JSON** (`GP0`=TX→Pi RX,
`GP1`=RX←Pi TX; firmware README, `rp2040_link.py`). The Pi tracks RP2040 health and
trips the FSM safe if it goes unhealthy.

**How the Pi judges health** (`rp2040_link.health_ok()`): healthy **only if** the
RP2040 is heartbeating (a `boot`/`hb`/`rp_ok`/`flt`/`ack` line within the
**`hb_timeout` = 1.0 s** window) **AND** reports `rp_ok` true **AND** has no latched
fault. A bare `flt` event marks it unhealthy immediately, even without a paired
`rp_ok:0` (lossy-UART robustness). The firmware heartbeats at **`HB_INTERVAL_MS` =
250 ms** (~4 Hz).

**What the daemon does on health loss** (`controller_daemon.BoardController.tick()`):
forces motion outputs **off** (clears the relay latches), latches the FSM into
**MANUAL_INTERVENTION** (recovery requires a deliberate PBZ), drops **ARM**, and
keeps kicking the NE555 (the *Pi* is still alive). Note that `RP2040_OK` has
**already** dropped the rail in hardware regardless — the daemon's action is the
software belt-and-suspenders so the FSM/desk see it.

| Likely cause | Fix |
|---|---|
| **UART not wired / wrong port** | Confirm the Pi's serial device for this board (`controller_daemon.DEFAULT_BOARDS` `uart_port`, e.g. `/dev/ttyAMA0` — **all `# CONFIRM` placeholders set at bench/cutover**). TX/RX must be **crossed**: Pi TX → Pico `GP1`/RX, Pico `GP0`/TX → Pi RX. Baud **115200 8N1**. |
| **RP2040 unpowered / not flashed / crashed** | Confirm a `boot` line then ~4 Hz `hb` with `ok:1`. If the firmware hung, its **internal hardware watchdog** (`WDT_TIMEOUT_MS` = 250 ms) resets the chip — you'll see a `boot` with `wdt_reset:1`. After reset, GP2 is held LOW for `BOOT_SETTLE_MS` = 200 ms, then HIGH only if healthy. |
| **Stale heartbeat (link "alive" but quiet)** | If no line arrives for > 1.0 s, `is_alive()`/`health_ok()` go false → daemon trips safe. Check the cable, the Pico power, and that the reader thread is running (`RP2040Link.start()`). |
| **Latched firmware fault** | `health_ok()` stays false until an `hb` with `flt:""` arrives — i.e. after a `CLEAR` from a safe state (§22.5). |
| **Cam events arrive but the FSM ignores them** | The FSM only acts on a configured, measured trip edge and in the matching state. SC/TB are not FSM motion-cam calls; their code path is only the default-off/unvalidated software echo. Lane 21/22 has no independent TB lead and SC/U is unlanded, so do not expect or credit that echo. |

**To verify the fast inputs at the bench** (firmware README §"Bench bring-up"
step 2): hand-actuate each cam / break each DIELL beam and confirm the matching
`{"ev":"cam","id":...}` / `{"ev":"ball","src":...}` line (correct `id`). All fast
inputs are **active-low** at the Pico (machine contact closed ⇒ GPIO LOW; on-board
external `Rpu_*` holds idle at 3.3 V: Rev-B 10 kΩ, current Rev-D/R5 **47 kΩ**).
On Rev-D, verify GP6–GP13 PUE/PDE are off; an internal pull can hide an open
external `Rpu_*` and invalidates the qualified input margin. The GP↔signal map
(`config.h` / §12):

| GPIO | Pico pin | Signal |
|---|---|---|
| GP6 | 9 | SA (sweep cam) |
| GP7 | 10 | SB (sweep cam) |
| GP8 | 11 | SC (sweep interlock cam) |
| GP9 | 12 | TA1 (table cam) |
| GP10 | 14 | TA2 (table cam) |
| GP11 | 15 | TB (table interlock cam) |
| GP12 | 16 | DIELL-L (ball) |
| GP13 | 17 | DIELL-R (ball) |
| GP2 | 4 | RP2040_OK (rail permission) |
| GP0 / GP1 | 1 / 2 | UART0 TX / RX to Pi |

> ⚠️ **Do not use the GPIO column in `docs/phase8_channel_allocation.md` §2** — it
> assigns the fast inputs to GP0–GP7 and is **stale**. The as-built board uses
> **GP6–GP13**; `firmware/rp2040/config.h` and the netlist generator are correct
> (see §12).

**Re-flashing the RP2040 firmware** (firmware README §"Flash"):
- **USB BOOTSEL (preferred):** hold BOOTSEL on the Pico while connecting USB → it
  mounts as `RPI-RP2` → drag-drop `wsl_phase8b_rp2040.uf2`.
- **SWD (if USB inaccessible once soldered):** `picotool load -x build/wsl_phase8b_rp2040.uf2`,
  or OpenOCD via the board's SWD test points.
- Rebuild on the Westside laptop with `pwsh -File build.ps1` (auto-discovers the
  bootstrapped toolchain → `build/wsl_phase8b_rp2040.uf2`, ~40 KB).

---

### 22.7 The watchdog & health behavior (what "healthy" looks like)

Two **independent** watchdogs guard two different things — **do not confuse them**
(§10.2):

| Watchdog | Watches | Timeout | What it does on timeout |
|---|---|---|---|
| **NE555 monostable** (U36, on the board) | the **Raspberry Pi** | (monostable RC; bench-measured) | Pi stops kicking → NE555 reverts → Q13 off → rail AND opens → **all relay coils drop** |
| **RP2040 internal HW watchdog** | the **Pico firmware** | `WDT_TIMEOUT_MS` = 250 ms | firmware loop hangs → chip resets → GP2 → Hi-Z → R110 holds Q16 off → **rail drops**; auto-recovers on reboot (`boot` with `wdt_reset:1`) |

The Pi **kicks the NE555 only from `fsm.poll()`** inside the control loop
(`controller_io.MachineIO.watchdog_kick()`, called every `poll()`). This coupling is
**intentional**: if the Track-B control loop stalls, kicks stop and the rail drops.
(Contrast Track A, where scoring must **never** be able to stop the machine.)

A healthy RP2040 at the bench:
- a `boot` line on power-up, then `{"ev":"hb",...,"ok":1}` at ~4 Hz after ~200 ms;
- `GP2` reads **HIGH** on a meter/test-pad once healthy;
- the daemon's `link.health_ok()` returns true.

> **(VERIFY: NE555 monostable timeout period and the Pi kick GPIO number.)** The
> watchdog RC is R100 = 100 k + C11 = 100 µF, but the kick is wired into both the
> timing and trigger nodes (retrigger topology) and the design doc states the drop
> behavior **qualitatively** without a number (spec §4.3). The effective drop time
> is a **bench measurement** (§10.8 / spec §12.9 "watchdog drop") — **do not assume
> ~11 s.** Likewise the Pi-side **kick GPIO number** (and the per-board **ARM** GPIO)
> are `# CONFIRM` placeholders in `controller_daemon.DEFAULT_BOARDS` set at bench/
> cutover — the *board* side is fixed at J1 pin 7 (`WDOG_KICK`) and J1 pin 8
> (`ARM_PERMIT`).

---

### 22.8 Periodic maintenance

Most of this system is solid-state with no wear parts; the maintenance load is
light. Recommended checks:

**Track A — scoring (per-pair, ongoing):**
- **Accuracy spot-check.** Keep a casual detected-vs-actual tally during play; a
  drift toward a particular pin/spot is a calibration nudge (§22.2.3), not a
  failure.
- **Empty-reference refresh** if the camera is moved/reseated, the dongle changes,
  or lighting changes materially: recapture `empty_ref.png` (§22.2.1). The detector
  drift-corrects exposure, so routine lighting swings should not need it.
- **Confirm `systemctl is-enabled lane-node` = enabled** after any maintenance that
  touched the Pi or its OS (§22.3) — the most common way a lane silently goes dark.
- **Camera tap ground integrity** — a marginal RCA-shell→Blue ground shows up as
  intermittent black frames (§22.2.2).

**Track B — controller (per-board; once cleared for live):**
- **Re-run the bench safety drops periodically** on a locked-out machine: watchdog
  drop, ARM drop, J_SAFE1-2 source-position drop, Stop/CIS drop, and motion-timeout
  drop (§10.8). Opening 1–2 proves only board continuity. Under the current
  runbook's guarded live procedure, also re-prove Candidate C per lane: command S
  and T separately; both levers BACK/open must leave each machine coil dead.
- **Inspect motion-relay contacts + suppression** on inductive outputs (S/T/SP/BE/M/M2)
  for arcing/pitting; verify the populated snubber/MOV per output (§22.4.4).
- **Verify test-point readings** against §10.8 (TP16 rail, `RAIL_GATE`, `NE555_TRIG`/
  `NE555_OUT`, `SAFE_STOP_RETURN`, `RP2040_OK`, `ARM_PERMIT`, `WDOG_KICK`).
- **Confirm the per-cam trip edges** are still as captured before any newly
  controlled release enables cam-stop overrun; stock v1.2.3 leaves them OFF.

**Software hygiene:**
- On the Pi: `git pull` only deliberately (it brings `camera.py` / `lane_node.py` /
  calibrated `pin_detect.py`); **`empty_ref.png` is per-Pi and gitignored** — never
  expect a pull to provide it.
- Watch `journalctl -u lane-node -f` after any change; the runbook log strings
  (§22.2) are your go/no-go.

---

### 22.9 Spares to keep on hand

The strategic goal of Phase 8 is **zero EOL hardware** — every active part is a
commodity, in-stock device chosen so the center is not hostage to a defunct vendor.
That said, keep a small spares kit so a failure is a swap, not a fab order.

#### 22.9.1 Whole-unit / module spares (highest priority)

| Spare | Why | Notes |
|---|---|---|
| **A complete spare controller board (PCBA)** | Fastest recovery is board swap, not component-level repair, on a 250 × 225 mm board | The board is a single, identical, per-lane design — one spare fits any 82-70 lane. Fab/assemble a couple of extras with each batch. |
| **Raspberry Pi (per-pair host)** | Runs scoring + control; commodity, cheap | Keep the OS image + the node config so a swap is reflash-and-go. **Remember `systemctl enable lane-node`** on any fresh Pi (§22.3). |
| **Raspberry Pi Pico (RP2040 stamp module), ref A1 / RP_PICO** | The fast/safety co-processor; socketed-module choice was deliberate to make it swappable | **DigiKey 2648-SC0915CT-ND / Raspberry Pi SC0915.** Use the **plain Pico (castellated, no headers)** — **NOT** the Pico H/WH with header pins. Flash `wsl_phase8b_rp2040.uf2` after fitting (§22.6). |
| **VIXLW USB capture dongle** | The only thing between the camera and the Pi for Track A | UVC-class; enumerates as "USB Video." |

#### 22.9.2 Board-level component spares (for hand repair)

Confirmed, fab-locked parts from the assembly BOM
(`kicad/fab_revB_routed_manual/assembly/wsl-phase8b-revB-jlc-standard-pcba-bom.csv`).
**Use these exact parts** — the critical-substitution notes are load-bearing:

| Part | Role | Designators | LCSC | Critical note |
|---|---|---|---|---|
| **Omron G5LE-14, 5 VDC coil**, SPDT relay (THT) | Motion-output relays | K1–K6 (K7/M1 = **DNP**) | **C116963** | **5 VDC coil — DO NOT substitute a 9 V / 12 V / 24 V coil.** Carries no motor current; switches dry contacts only. |
| **MCP23017-E/SO** I²C 16-bit I/O expander (SOIC-28W) | Slow inputs + relay/lamp outputs | U1, U2, U3 | **C47023** | **I²C part — NOT the SPI `MCP23S17`.** Runs at **3.3 V** for Pi-safe I²C. (IN-A `0x20`, IN-B `0x21`, OUT-A `0x22`.) |
| **PC817B** optocoupler (DIP-4) | Isolates every machine input | U4–U35 (32 pcs) | **C5692981** | Logic side at 3.3 V, **active-low** at the MCU. Keep CTR bin consistent with the Rev-B field resistors. |
| **NE555DR** (TI), **bipolar** 555 (SOIC-8) | Hardware watchdog monostable | U36 | **C7593** | **Bipolar NE555 — avoid CMOS/TLC555**; the timing/threshold behavior would change. |
| **AO3401A** P-ch MOSFET (SOT-23) | Relay-enable-**rail pass-FET** | Q14 | C347476 | High-side rail switch. Don't confuse with the N-ch parts below. |
| **AO3400A** N-ch MOSFET (SOT-23) | Watchdog kick (Q12) + watchdog-OK (Q13) | Q12, Q13 | C20917 | **Q12/Q13/Q14 are visually similar SOT-23 parts — do not swap N-ch and P-ch during hand placement.** |
| **MMBT3904** NPN BJT (SOT-23) | Relay-coil drivers (Q1–Q6) + safety-chain AND transistors (Q15, Q16) | Q1–Q6, Q15, Q16 | C909754 | One grouped BOM line for all 8; confirm by role/position. |
| **2N7002** N-ch MOSFET (SOT-23) | Low-side status-LED drivers | Q8–Q11 | C916396 | The 4 mask-LED channels. |
| **SS14** Schottky (SMA) | Reverse-polarity / input protection on the 5 V input | D17 | C2480 | |
| **1N4148WS** (SOD-323) | Relay-coil flybacks + watchdog steering diodes | D1,D3,D5,D7,D9,D11,D15,D16 | C118873 | |
| **TRACO TMA-0505S** isolated 5 V→5 V DC/DC (THT) | Isolated **field-wetting** supply (keeps FIELD_GND off logic ground) | U37 (ISO_WET) | *(see note)* | DigiKey 1951-1003-ND. **Do not substitute without a pinout + isolation review.** Not in the JLC SMT BOM — placed/hand-fitted. |
| 0805 R/C passives (4.7 k, 2.2 k, 10 k, 1 k, 100 k, 330 R; 100 nF, 10 nF, 10 µF; 100 µF/16 V electrolytic C11) | Pull-ups/-downs, gate Rs, decoupling, watchdog RC | many | (grouped) | Confirm passives **by value**, not by assuming a unique BOM line per RefDes. |

> **(VERIFY: LCSC/MFR number for the TMA-0505S.)** The isolated wetting supply is
> **TMA-0505S** in the as-built netlist (`block_supplies()`, ref ISO_WET → board ref
> **U37**) and the hand-solder BOM (TRACO `TMA 0505S`, "Locked exact part"). An
> earlier draft (`docs/phase8b_pcb_revB_BOM_power.md` §3.2) *recommended* a
> `B0505S-1W` — **the netlist (source of truth) wins: use the TRACO TMA-0505S.** It
> is not in the JLC SMT upload BOM, so it has no LCSC line in that file; order from
> DigiKey/TME/Mouser and verify the pinout before fitting.

#### 22.9.3 Connector / mating-part spares

Field-input and machine-output connectors are **Phoenix Contact MCV/MKDS** series
(from the hand-solder/off-board BOM). Keep the **mating plugs** as spares — the PCB
headers are soldered, the plugs are field-wiring and get reworked:

| Board connector | Part (header on PCB) | Mating plug to stock |
|---|---|---|
| J3 (J_FAST_IN, 10-pos, 3.5 mm) | Phoenix MCV 1,5/10-G-3,5 (1843680) | MC 1,5/10-ST-3,5 |
| J4 (J_SLOW_IN_A, 14-pos) | MCV 1,5/14-G-3,5 (1843729) | MC 1,5/14-ST-3,5 |
| J5 (J_SLOW_IN_B, 12-pos) | MCV 1,5/12-G-3,5 (1843703) | MC 1,5/12-ST-3,5 |
| J13 (J_LAMP_LED, 6-pos) | MCV 1,5/6-G-3,5 (1843648) | MC 1,5/6-ST-3,5 |
| J14 (J_SAFETY, 4-pos) | MCV 1,5/4-G-3,5 (1843622) | MC 1,5/4-ST-3,5 |
| J2 (J_PWR 5 V, 3-pos, 5.08 mm) | Phoenix MKDS 1,5/3-5,08 (1715734) | fixed screw terminal (no off-board plug) |
| J6–J11 (J_MOTION_*, 2-pos, 5.08 mm) | Phoenix MKDS 1,5/2-5,08 (1715721) | fixed screw terminal (no off-board plug) |
| J1 (J_PI, 2×10 IDC) | 20-pos 2×10 2.54 mm header | ribbon/IDC socket to the Pi |

#### 22.9.4 EOL-risk machine parts (the parts Phase 8 exists to escape)

These are **legacy** parts on the machine/scoring side that are end-of-life with no
viable supply chain. Where the original is being **retired** by Phase 8, the "spare"
is the Phase 8 replacement, not the EOL part. Stock the few that are still in the
loop:

| EOL part | Status under Phase 8 | Spares stance |
|---|---|---|
| **QubicaAMF T-Camera** (one per pair) | **Reused** by Track A (its composite video is tapped) | The camera is still in the live path — keep any spare T-Cameras you have; they are EOL from QubicaAMF. |
| **QubicaAMF VDB** (per-lane scoring computer), **ETHost** gateway, **T-VISION** board | **Retired** — replaced by the Pi + camera scoring | Don't invest in spares; the Pi-per-pair build *is* the replacement. Keep enough only to cover lanes not yet cut over. |
| **Omega-Tek "Omniboard"** retrofit controller (lanes 21/22) + Expander/ZOT | **Being replaced** by the rev-B controller (Track B) | **Vendor appears defunct** → highest continuity risk and a primary motivation for Phase 8. Keep whatever spares exist for lanes not yet cut over; the long-term answer is the Phase 8 board. |
| **Active "Ultra 98 Plus" MP controller** (lanes 11/12) | Being replaced by Track B over time | Mixed fleet; keep until that pair is cut over. |
| **AMF 82-70 machine mechanism, motors, cams, grippers, mask** | **KEPT** — unchanged on every lane | Standard pinsetter wear parts (cam microswitches, gripper switches GS1–GS10, motor contactors, drive components) per normal AMF 82-70 service stock. The Phase 8 board reads/commands these; it does not replace them. `(VERIFY: specific AMF 82-70 mechanical part numbers — outside the named live files; use the AMF 82-70 Service & Parts manual.)` |

---

### 22.10 When to stop and escalate

- **Any time the safe fallback is available, take it.** Flip Track A to `manual`
  (§22.2.5) — the lane runs and the desk scores. There is no machine risk.
- **Do not run Track B against a live machine** until the full hardware safety
  chain is bench-proven per §10.8 / spec §12.9 and the cutover runbook
  (`docs/phase8_trackB_controller_cutover_runbook.md`). The controlled v1.2.3
  bundle is **NOT flashed or cutover-ready**; its measured-cam enforcement flags
  are OFF, and first-article/bench gates remain open.
- **A dead rail during diagnosis is the safe state**, not necessarily a fault
  (§22.0 item 6). Confirm which implemented gate/source position is open (§22.4.2) before
  assuming a board failure.
- **If a relay contact may have welded**, the rail will not save you — cut the
  master breaker (§22.4.4, §10.6).

> **Cross-references:** machine theory and the cycle/cam timing in **§3**; the I/O
> inventory in **§4**; the board domains/isolation in **§5**; power rails in **§6**;
> RP2040/MCP/I²C logic in **§7**; opto front-ends in **§8**; relay outputs in **§9**;
> the watchdog + relay-enable rail (and its test points + bench-drop procedure) in
> **§10**; connector pinouts in **§11**; the GPIO/MCP bit maps in **§12**; and the
> machine-side C1/C2A harness in **§14**.
