## 2. System Architecture & Signal Chain

This section describes how a Westside Lanes Phase 8 lane pair is wired and how a
signal flows from the pinsetter, through the controller electronics, up to the
overhead display and back down as a motion command. Read it before touching any
board: it defines what every wire, board, and chip does and — just as important —
what each one is *not* allowed to do.

Scope reminder: a **lane pair** (e.g. lanes 21 + 22) is the unit. The pair shares
**one Raspberry Pi** and **one overhead camera**, but each lane gets its **own
controller board** and its own machine harness. Everything in this section is
"per pair" except where a table is explicitly marked "per board / per lane."

The whole replacement runs in two functional tracks, on the same hardware:

- **Track A — camera scoring.** Detect which pins are standing after each ball
  from an overhead camera, and report the score to the server. Code-complete; see
  Section 18 (Camera Scoring Subsystem) for the optics and detection math.
- **Track B — controller replacement.** Replace the AMF 82-70 pinsetter's
  control brain (cycle the machine, run the safety interlocks). The rev-B board
  in Sections 3 (Hardware / PCB) and 4 (Firmware & Control FSM) is the Track-B
  hardware. As of this writing the bare PCB is fab-ready but **not yet built or
  cut over** — the existing OEM controller still runs the machines.

The two tracks are deliberately decoupled: scoring must never be able to stop the
machine, and the machine controller must never depend on the camera to cycle. See
§2.6.

---

### 2.1 End-to-End Block Diagram

```
                        ┌──────────────────────────────────────────────────────────┐
                        │                    WSL-SRV  (server PC)                    │
                        │  lane_node_server (ws://…:8765)  ·  wsl_api.py (:5000)     │
                        │  scoring store + desk UI + overhead-display feed           │
                        │  IP 192.168.4.103  (eero subnet 192.168.4.0/22)            │
                        └───────────────▲──────────────────────────┬────────────────┘
                                        │  WebSocket (JSON)         │  HTTP
                                        │  ball/foul/heartbeat ▲    │ display feed ▼
                                        │  open/close/cycle    ▼    │
                    ┌───────────────────┴───────────────────┐   ┌──┴───────────────┐
                    │        Raspberry Pi  (one per pair)    │   │ Overhead monitor │
                    │  ─ lane_node.py  (Track A scoring)     │   │  (per pair, HDMI/ │
                    │  ─ controller_daemon.py (Track B FSM)  │   │   network feed)   │
                    │  ─ camera.py / pin_detect.py           │   └───────────────────┘
                    │                                        │
                    │  USB ◄── VIXLW capture dongle ◄── T-Camera (1 per pair,
                    │           (composite→USB)              behind the pins, sees
                    │                                        BOTH decks, 720x576 PAL)
                    │                                        │
                    │  I2C bus-1 ──┐        I2C bus-2 ──┐    │  (i2c-gpio)
                    │  UART0 ──────┤        UART1 ───────┤   │
                    │  GPIO arm/INT/wdog (per board) ────┤   │
                    └───────┬──────┴────────────┬─────────┴──┘
                            │ board harness      │ board harness
                ┌───────────▼──────────┐  ┌──────▼───────────────┐
                │  rev-B board — LANE 21│  │  rev-B board — LANE 22│   (identical boards)
                │  RP2040 + 3×MCP23017  │  │  RP2040 + 3×MCP23017  │
                │  PC817 opto-in bank   │  │  PC817 opto-in bank   │
                │  G5LE relay-out bank  │  │  G5LE relay-out bank  │
                │  NE555 watchdog       │  │  NE555 watchdog        │
                │  relay-enable rail    │  │  relay-enable rail     │
                └───┬─────────────┬─────┘  └───┬─────────────┬──────┘
       J3/J4/J5     │             │ J6–J12     │             │
       field inputs │             │ motion out │             │
       J14 safety   │             │ J13 LEDs   │             │
                ┌───▼─────────────▼───┐    ┌───▼─────────────▼───┐
                │  AMF 82-70 machine   │    │  AMF 82-70 machine   │
                │  LANE 21             │    │  LANE 22             │
                │  via C1 + C2A conns  │    │  via C1 + C2A conns  │
                │  cams/grippers/DIELL │    │  cams/grippers/DIELL │
                │  S/T/SP contactors   │    │  S/T/SP contactors   │
                │  mask LEDs (ours)    │    │  mask LEDs (ours)    │
                └──────────────────────┘    └──────────────────────┘
```

Read the diagram top-to-bottom for a **motion command** (server → Pi FSM →
board → machine), and bottom-to-top for **scoring** (machine ball-detect →
board → Pi → server → display). The two flows share the board and the Pi but use
different chips and different links — see §2.4 and §2.5.

---

### 2.2 Components of the Signal Chain

| Element | Count | Where it lives | Role |
|---|---|---|---|
| WSL-SRV server | 1 site-wide | Back office, IP **192.168.4.103** | Runs `lane_node_server` (WebSocket :8765) + `wsl_api.py` (:5000). Holds the scoring store, the desk UI, and the overhead-display feed. Sends high-level commands (open/close/cycle); receives ball/foul/heartbeat. |
| Raspberry Pi | 1 per pair | Lane-pair enclosure | Runs the cycle FSM, scoring, and all comms. The "slow brain." See §2.3. |
| rev-B controller board | 1 per lane (2 per pair) | Lane-pair enclosure | Self-contained per-lane controller: RP2040 + 3× MCP23017 + opto inputs + relay outputs + NE555 watchdog + relay-enable rail. The "fast/safe hands." See Section 5. |
| AMF 82-70 pinsetter | 1 per lane | At the lane | The mechanism being controlled. Cams, grippers, DIELL ball detector, sweep/table motor contactors, mask housings. Interfaced via connectors **C1** (motor/relay/power) and **C2A** (switches/control). See Section 3 (Machine Overview). |
| T-Camera (QubicaAMF) | 1 per pair | Behind the pins, looking toward the bowler | Single PAL camera that sees **both** decks of the pair in one 720×576 frame. Scoring optic only. See Section 18. |
| VIXLW USB capture dongle | 1 per pair | Plugged into the Pi USB | Converts the T-Camera's composite/PAL video into a USB frame source for OpenCV/PyAV. Owned and on hand. |
| Overhead display | 1 per pair | Above the lanes | Shows the live score. Driven from the server's display feed, not from the board. |
| 5 V PSU | 1 (sized per pair) | Lane-pair enclosure | External regulated 5 V for board input power, the RP2040/Pico (VSYS), the NE555 watchdog rail, the opto logic-side pull-ups, and the relay coils. The **MCP23017s + I²C bus run on Pico-derived 3.3 V, not 5 V.** **Off-board.** See §2.7 and Section 6 (Power). |
| Machine adapter harness | 1 per lane | Between board and C1/C2A | Maps the board's function-named connectors to the chassis-specific C1/C2A cavities at cutover. Keeps uncertain cavity bindings out of copper. See Section 14 (Connectors & Harness). |

---

### 2.3 The Compute Split — why a Pi *and* an RP2040 per lane

The controller intelligence is split across three tiers. This split is the single
most important architectural decision in Phase 8; do not collapse it.

| Tier | Hardware | Responsibilities | Why here |
|---|---|---|---|
| **Server** | WSL-SRV PC | Scoring store, desk/operator UI, overhead-display feed, high-level lane commands (open/close/cycle/reset/power). | Centralized, not real-time, not safety-critical. A server outage must **not** stop a running machine. |
| **Slow brain** | Raspberry Pi (1 per pair) | The cycle **FSM** (`cycle_control_8270.py`), camera **scoring** (`camera.py` / `pin_detect.py`), all **comms** (WebSocket to server, UART to each RP2040, I2C to each board). Two independent control loops: `controller_daemon.py` (Track B) and `lane_node.py` (Track A). | Runs Python, has the camera and the network. The FSM logic and scoring math are complex but tolerate ~10–20 ms scheduling jitter. |
| **Fast/safe hands** | RP2040 (1 per board / per lane) | Eight board fast-input positions, `RP2040_OK`, the 8 s max-run backstop, and UART events. Lane 21/22 has no independent TB lead and leaves SC/U unlanded. | The controlled v1.2.3 release provides health + max-run; its measured-cam enforcement code ships with all flags OFF pending polarity capture and a new controlled release. |

Each lane's board also carries **three MCP23017 I2C I/O expanders** that handle the
non-latency-critical I/O — the grippers, the slow switches, and the relay/lamp
command bits. They sit on the Pi's I2C bus, not the RP2040.

| MCP23017 | I2C addr | Direction | What it carries |
|---|---|---|---|
| IN-A (U1) | **0x20** | all inputs | GS1–GS10 grippers + GP, OS, BS, PBZ, PBC, Foul (16/16 pins used) |
| IN-B (U2) | **0x21** | all inputs | 10th-frame + manual T/S/SWS/SWSR + spare/AUX (5 used, 11 spare) |
| OUT-A (U3) | **0x22** | all outputs | 7 relay-drive bits (S/T/SP/BE/M/M2/M1) + 4 status-LED bits |
| OUT-B (0x23) | not populated | — | Optional physical pin-lamp pindicator. **Omitted** in baseline because the camera supplies pin state. |

The three expanders are MCP23017 (**I2C**, LCSC **C47023**, `MCP23017-E/SO`) — **not**
the SPI MCP23S17. Confusing the two will not enumerate on the bus.

**Division of labor in one sentence:** the Pi *decides* (FSM + scoring), the
RP2040 *guards* (fast inputs + hardware stop), and the MCP23017s *fan out* the
Pi's slow reads and writes.

---

### 2.4 Per-board Independent I2C and UART Buses

The two boards on a pair are **electrically identical** ("design one, clone it").
This is achieved by giving each board its **own I2C bus** and its **own UART**, so
each board can use the same fixed MCP23017 addresses (**0x20/0x21/0x22**; 0x23 reserved, unpopulated) and the same
firmware without address collisions.

| Pi resource | Board 21 (example) | Board 22 (example) | Notes |
|---|---|---|---|
| I2C bus | hardware `i2c-1` (GPIO2/3) | second bus via `dtoverlay=i2c-gpio` | Each board repeats the same three addresses (0x20/0x21/0x22; 0x23 reserved) on its own bus. (VERIFY: the exact GPIO pins for the i2c-gpio second bus — `# assign` in `phase8_channel_allocation.md` §4 and `# CONFIRM` in `controller_daemon.DEFAULT_BOARDS`.) |
| UART to RP2040 | one PL011/mini-UART | a second UART | Point-to-point, 115200 8N1, newline-JSON. (VERIFY: production maps lane 21→`/dev/ttyAMA0`, lane 22→`/dev/ttyAMA1` in `DEFAULT_BOARDS`, but those are placeholders flagged `# CONFIRM`.) |
| Watchdog kick | one GPIO per board | one GPIO per board | (VERIFY: `DEFAULT_BOARDS` placeholders lane 21 = GPIO12, lane 22 = GPIO6; the legacy Phase-8a node used GPIO12 board-level.) |
| ARM (relay-enable permit) | one GPIO per board | one GPIO per board | (VERIFY: `DEFAULT_BOARDS` placeholders lane 21 = GPIO26, lane 22 = GPIO13.) |
| MCP INT lines | IN-A INT, IN-B INT | IN-A INT, IN-B INT | Change-interrupt to the Pi (not polling). (VERIFY: exact GPIOs `# assign` in §4.) |

Why a dedicated UART instead of putting the RP2040 on the I2C bus: the RP2040 must
**push** cam/ball events the instant an edge fires — an I2C slave can only respond
when polled, which would add latency to the safety-critical path and contend with
the three MCP23017s. SPI was rejected for the same poll-only reason plus extra
pins. See `phase8_channel_allocation.md` §7 for the full link trade study.

---

### 2.5 The Two Live Signal Flows

#### 2.5.1 Scoring flow (machine → display) — Track A, runs today

```
ball thrown ─► DIELL beam breaks ─► PC817 opto (active-low) ─► RP2040 GP12/GP13
   │                                                            │
   │  (in the camera-driven model, the DIELL break is also the trigger to
   │   wait the settle window, then capture)
   ▼
RP2040 pushes {"ev":"ball","src":"L"} over UART  ──►  Pi
   │                                                   │
   ▼                                                   ▼
Pi (lane_node.py) waits SETTLE_S (~2.5 s) ──► grabs a frame from the T-Camera
   via the VIXLW USB dongle ──► pin_detect.py: difference-from-empty over 20 fixed
   pin-cap ROIs ──► 10-bit standing-pin mask per deck ──► map deck→lane
   │
   ▼
Pi sends BALL_EVENT (with pin_mask, or awaiting_manual=True on no/failed capture)
   over WebSocket ──► WSL-SRV scoring store ──► overhead display updates
```

Safe-degradation rule: if the camera is not ready or a capture fails,
`detect_current_pins()` returns `None` and the Pi emits `awaiting_manual=True`,
so the desk operator scores the ball by hand. A real ball **never** records a
bogus auto-score. (Source: `lane_node.py` `detect_current_pins` / `_settle_capture_emit`.)

#### 2.5.2 Control flow (server/sensors → machine) — Track B, bench-gated

```
cam edge (e.g. SB guard at 66°) ─► PC817 opto ─► RP2040 GPx (debounced)
   │
   ▼
RP2040 pushes {"ev":"cam","id":"SB","e":"f"} over UART ──► Pi
   │
   ▼
Pi controller_daemon.py: link.apply_events(fsm) ──► cycle_control_8270 FSM advances
   ──► fsm.poll() sets the next motor/solenoid/lamp outputs AND kicks the NE555
   │
   ▼
Pi writes the relay-command bit over I2C ──► MCP23017 OUT-A (0x22) ──► MMBT3904
   driver ──► G5LE relay coil ──► relay CONTACT closes the EXISTING machine
   control circuit (e.g. the sweep contactor coil) at J6–J12
   │
   ▼
the machine's OWN contactor switches the 115 VAC motor (NOT the board)
```

Grippers, GP, BS, PBZ, Foul (the "slow" inputs) take a parallel path: machine
contact → PC817 opto → MCP23017 IN-A/IN-B (I2C) → Pi reads them inside the FSM
(`read_grippers`, `gp_closed`, `bs_closed`) or as edge events in the daemon
(`read_input` for PBZ/BS/Foul).

---

### 2.6 Track Decoupling and the Safety Rail (overview)

Two non-negotiable couplings define the safety architecture. Both are covered in
depth in Section 16 (Control FSM) and Section 19 (Safety System); here is the
architectural summary.

1. **Scoring must not be able to stop the machine.** Track A (`lane_node.py`) and
   Track B (`controller_daemon.py`) are separate processes/loops on the Pi. The
   camera and the WebSocket can fail without affecting machine motion. In the
   Phase-8a scoring pilot the server replies to a ball with a CYCLE command, but
   that pilot drives a *pulse* relay on the existing controller, not the live
   motors. At Track-B cutover the cycle runs on **cam timing**, fully decoupled
   from camera capture (`_settle_capture_emit` docstring warns about this exact
   timing coupling).

2. **The machine controller must fail safe without the Pi.** Every motion-relay
   coil (S, T, SP, BE, M, M1, M2) is powered through a single series
   **relay-enable rail** (`RELAY_ENABLE_RAIL`). The rail drops — all motors stop —
   if **any** of these go false:

   | Rail condition | Source | Fail-safe default |
   |---|---|---|
   | Watchdog OK | NE555 monostable (U36), kicked by the Pi (`WDOG_KICK`) | false (drop) |
   | ARM OK | Pi `ARM_PERMIT` GPIO, asserted only in a safe state | false |
   | RP2040 OK | RP2040 `RP2040_OK` (GP2) heartbeat/permission | false |
   | Cam-stop OK | RP2040 immediate cam-stop drop path | false on reset/fault |
   | TB/SC interlock OK | **Candidate C:** OEM parallel closed-when-safe contacts in the S/T coil ladder; J14 pins 1–2 carry the controlled jumper | both levers BACK/open; or G3 insertion proof fails |
   | External control-power proof / optional approved pit interlock OK | future externally mounted energize-to-prove relay dry contact, optionally in series with a newly installed pit-entry-interlock contact, at J14 pins 3–4; **currently OPEN/unlanded** | open/false; field rail cannot arm |

   The Pi **cannot** bypass these in software. The rail can only de-energize a
   coil; it cannot open a *welded* contact — so the installed master breaker /
   Stop chain remains the pilot's final physical stop (see Section 19, "welded
   contact limitation"). OEM machines with a real C.I.S. retain and test that
   device; lanes 21/22 record it as N/A. Live motor current always stays on the machine
   contactors; the board only opens/closes isolated dry contacts in the existing
   control circuits.

The RP2040 firmware additionally enforces a **motion max-run backstop**: a guarded
motor (S/T/SP/M1/M2) marked RUNNING for longer than `MAX_MOTION_MS` (8 s, matching
the FSM's `MAX_MOTION_S = 8.0`) latches a fault and drops `RP2040_OK` — UART-
independent, so a hung Pi cannot leave a motor running. (Source: firmware
`main.c` `supervise()`, `config.h`.) The v1.2.3 code also contains cam-stop
overrun paths, but the controlled release leaves every measured-cam flag OFF.
Per-cam edge→angle polarity must be captured, bound into a new release, and proven
before that protection is credited.

---

### 2.7 Power and Signal Domains

The board enforces **three electrical domains** kept explicit in net names,
layout rooms (physically banded left/center/right with no-copper gutters), DRC
classes, and silkscreen. Crossing a domain boundary happens **only inside an
optocoupler or relay package** — never on a plain trace.

| Domain | Layout band | Contents | Reference net | Powered from |
|---|---|---|---|---|
| **Logic** | center | Pi link, RP2040, 3× MCP23017, I2C, UART, NE555 trigger, relay-coil drive logic, status-LED FET drivers | `GND` | external 5 V (`VCC_5V`); MCP/I2C run on `VCC_3V3` (from the Pico 3V3 out), **not** 5 V |
| **Machine Sense (Field)** | left | Field side of every PC817 opto (cams, grippers, DIELL, foul, pushbuttons) | `FIELD_GND` | isolated wetting `FIELD_WET_V` from the TMA-0505S DC/DC |
| **Machine Output** | right | Isolated G5LE relay contacts that open/close existing machine control circuits | (machine-side, harness) | **not** sourced by the board — the machine provides 24 VAC / 12 VDC control voltages |

Key isolation facts (verified against the routed board):

- **`GND` and `FIELD_GND` share zero nodes.** Field wetting is generated by a
  **TMA-0505S** isolated 5 V→5 V DC/DC converter (U37), so a dry-contact closure
  on the field side cannot inject into logic ground. (`block_supplies()` in the
  netlist generator; spec §8.3 option 1.)
- **Dry-contact default.** Each input front end is: `FIELD_WET_V → 2.2 kΩ → PC817
  LED → field pin`; the machine contact closes that pin to `FIELD_GND`. Optos are
  **active-low at the logic pin** (contact closed → opto pulls the GPIO/MCP pin
  LOW; idle HIGH via an external `Rpu_*` to 3V3). The historical Rev-B value was
  10 kΩ; the current Rev-D value is **47 kΩ**, with RP2040 internal pulls
  disabled and U1/U2 MCP23017 `GPPUA/GPPUB=0x00` commanded and read back.
  Firmware and `controller_io.py` both assume `INPUT_ACTIVE_LOW`.
  (`opto_input()`; `config.h` electrical-sense note.)
- **Per-channel population option.** Each field input can be populated as
  dry-contact wetting *or* 24 VAC/voltage-sense. The default per channel is set
  after at-machine measurement; field A1 measured the machine control voltage at
  **24 VAC** (not 250 VAC) (VERIFY: the routed/fab package intentionally keeps the
  *conservative* 250 VAC creepage rules — LOGIC↔FIELD ≥2.5 mm, LOGIC↔MACHINE
  ≥3.2 mm, output↔output ≥1.5 mm — so the 24 VAC relaxation is an optional future
  shrink, not yet applied).
- **No motor power on the board, ever.** 115 VAC motor current never touches PCB
  copper. The board only commands existing contactors through isolated contacts.
- **Status mask LEDs are in the LOGIC domain.** Dylan's rev-B decision replaced
  the machine's 15 VDC mask-lamp supply with our own LEDs in the mask housings,
  driven from `VCC_5V` through 2N7002 low-side FETs (Q8–Q11) and 330 Ω limit
  resistors. There is **no** isolation barrier on the status-LED path. (Spec §3.3.)

---

### 2.8 On-board vs Off-board

Knowing what is on the PCB versus what plugs into it is essential for service and
spares. The board is **one lane**; the figures below are per board unless noted.

#### On-board (populated on the rev-B PCB)

| On-board element | Designator(s) | Part / value | LCSC | Notes |
|---|---|---|---|---|
| RP2040 module | A1 | Raspberry Pi Pico (SMD footprint) | — | Hand-placed module; the firmware co-processor. |
| I/O expanders ×3 | U1, U2, U3 | MCP23017-E/SO (I2C, SOIC-28W) | **C47023** | IN-A 0x20, IN-B 0x21, OUT-A 0x22. **I2C, not SPI MCP23S17.** |
| Opto-isolators ×32 | U4–U35 | **PC817B** (DIP-4) | **C5692981** | 8 fast (U4–U11) + 24 slow (U12–U35) input channels. |
| Motion relays ×6 | K1–K6 | **Omron G5LE-14, 5 VDC coil**, SPDT | **C116963** | S/T/SP/BE/M/M2. **5 VDC coil — do NOT substitute 9/12/24 V.** |
| Relay M1 (ball return) | K7 | G5LE-14 5VDC | — | **DNP** (not populated) until ball-return is confirmed on the chassis. |
| Relay-coil drivers ×6 | Q1–Q6 | MMBT3904 NPN (SOT-23) | C909754 | Low-side coil drive; flyback diode (1N4148) per coil. |
| Status-LED drivers ×4 | Q8–Q11 | 2N7002 N-MOSFET (SOT-23) | C916396 | L_FIRST/L_SECOND/L_STRIKE/L_FOUL, 330 Ω limit (R90/93/96/99). |
| Watchdog timer | U36 | **NE555DR — bipolar** (SOIC-8) | **C7593** | Monostable; drop rail if not kicked. Bipolar, **not** CMOS/TLC555. |
| Watchdog FETs | Q12, Q13 | AO3400A N-MOSFET | C20917 | Kick gate + watchdog-OK pulldown. |
| Rail pass-FET | Q14 | AO3401A P-MOSFET | C347476 | Series pass device for `RELAY_ENABLE_RAIL`. |
| Rail AND-chain BJTs | Q15, Q16 | MMBT3904 | C909754 | ARM and RP2040_OK series pulldown gate. |
| Isolated field-wetting supply | U37 | **TRACO TMA-0505S** 5→5 V iso DC/DC | — | Generates `FIELD_WET_V` / `FIELD_GND`. |
| Reverse-polarity protect | D17 | SS14 Schottky (SMA) | C2480 | On the 5 V input. |
| Flyback diodes | D1,D3,D5,D7,D9,D11,D15,D16 | 1N4148WS (SOD-323) | C118873 | Across each populated relay coil. |
| Snubber/MOV per motion output | C4–C10, D2,D4,D6,D8,D10,D12,D14 | RC snubber + MOV footprints | — | **All DNP** — fit per output only after load characterization. |
| Test points | TP1–TP16 | pads | — | VCC_5V, GND, VCC_3V3, FIELD_WET_V, FIELD_GND, I2C, watchdog (TRIG/OUT/timing/kick/OK-pulldown), ARM_PERMIT, RP2040_OK, SAFE_STOP_RETURN, RELAY_ENABLE_RAIL. |
| Mounting holes | MK1–MK4 | M3 | — | Excluded from BOM/POS. |

Board physicals: **250 × 225 mm, 4 copper layers.** Board-wide totals: 216
schematic components / 236 board footprints (incl. test pads + mounting holes) /
184 named nets. The current fab package counts **189 non-DNP** assembly refs and
**27 DNP** refs.

#### Off-board (plugs into the board's connectors, or is shared by the pair)

| Off-board element | Connects at | Notes |
|---|---|---|
| **5 V PSU** | J2 (J_PWR, 3-pos 5.08 mm) | External regulated 5 V; sized for worst-case relay-coil load + logic + margin. No PoE in rev-B v1. |
| **Raspberry Pi** | J1 (J_PI, 2×10 IDC) | Carries I2C (SDA/SCL), UART (TX/RX), watchdog kick, ARM permit, MCP INT-A/INT-B, RP2040_OK, 5 V, 3V3, GND. Shared by the pair (one Pi, two J1 ribbons). |
| **T-Camera** | (not on the board) | Composite/PAL → VIXLW dongle → Pi USB. One per pair. Scoring only. |
| **VIXLW USB dongle** | Pi USB | One per pair. |
| **Overhead display** | (not on the board) | Driven from the server. |
| **Mask status LEDs** | J13 (J_LAMP_LED, 6-pos) | Our LEDs in the existing mask housings: VCC_5V, GND, and four LED returns. |
| **Machine field inputs** | J3/J4/J5 | J3 (J_FAST_IN, 10-pos): SA/SB/SC/TA1/TA2/TB/DIELL-L/DIELL-R + 2× FIELD_GND. J4 (J_SLOW_IN_A, 14-pos): GS1–GS10, GP, OS, BS + FIELD_GND. J5 (J_SLOW_IN_B, 12-pos): PBZ, PBC, Foul, 10th, manual T/S/SWS/SWSR, AUX1–3 + FIELD_GND. |
| **Machine motion outputs** | J6–J12 | One isolated 2-pin contact pair per output: J6=S, J7=T, J8=SP, J9=BE, J10=M, J11=M2, **J12=M1 (DNP)**. (5.08 mm MKDS terminal blocks.) |
| **Safety loop** | J14 (J_SAFETY, 4-pos) | Board-side provision for two series source positions. **Current lane-21/22 harness:** J14-1/2 = controlled Candidate-C jumper (no machine landing); J14-3/4 = physically OPEN/CUT+LABEL-ONLY. The field rail cannot arm until a reviewed external energize-to-prove control-power relay supplies an isolated N.O. dry contact, optionally in series with an approved new pit-entry-interlock contact. Never jumper 3–4 at the machine, and never route sensed machine voltage or mains to Rev-D. Primary TB/SC protection stays in the OEM S/T coil ladder and is re-proven per lane at G3. |
| **Machine adapter harness** | J3–J14 ↔ C1/C2A | Per-chassis. Maps the board's function-named pins to the real C1 (34-pin motor/relay/power) and C2A (50-pin switch/control) cavities. See Section 14. |
| **Harness mating plugs** | J3/J4/J5/J13/J14 | Phoenix MC 1,5-ST-3,5 screw plugs (10/14/12/6/4-pos, MFR 1840447/1840489/1840463/1840405/1840382). Ordered with the harness, not placed on the PCB. |

> **Connector designator note (important for service):** the **board** silkscreen
> uses J-numbers (J1=Pi, J2=power, J3=fast in, J4=slow-A, J5=slow-B, J6–J12=motion
> S/T/SP/BE/M/M2/M1, J13=LED, J14=safety). The **netlist-generator source** tags
> the same parts by function name (`J_PI`, `J_FAST`, `J_SLOWA`, etc.). They are the
> same connectors. Go by the J-number on the physical board and the assembly BOM.

---

### 2.9 Why Live Motor Current Never Touches the Board (operating theory)

A recurring question from electricians: "if the board controls the sweep and
table motors, why isn't there a fat motor trace on it?" Because the board never
*switches* motor current — it switches the **coil** of the machine's existing
contactor.

The AMF 82-70 already has heavy contactors that switch the 115 VAC sweep and
table motors, with the OEM's start/run windings, capacitors, centrifugal switches,
and **regenerative braking on the relay normally-closed contacts**. Rev-B replaces
only the *logic that decides when to close those contactors* — it drops a small,
isolated dry contact (a G5LE rated for the coil/control load) into the existing
control circuit. The machine's own iron still slams the motor on and brakes it on
release, exactly as it did under the OEM brain.

This buys two things at once: (1) the board's relays only carry tiny coil
currents, so a common small relay footprint works across all outputs; and (2) the
machine keeps its proven motor-start and braking behavior, so we are not
re-engineering a safety-critical AC power path. The historical AMF MP-chassis
upgrade did exactly this — it replaced the 5-board solid-state logic with a
microprocessor using the *same* machine inputs/outputs. Our Pi-plus-RP2040 board
is, electrically, a modern MP chassis. (Sources: `phase8_8270_SYSTEM_REFERENCE.md`
§0/§4/§5; `phase8b_pcb_revB_spec.md` §3.1.) For the full machine-side description
of contactors, cams, grippers, and the C1/C2A interface, see Section 3 (Machine
Overview) and Section 14 (Connectors & Harness).

The upstream mains installation remains outside this architecture. Before
commissioning and periodically thereafter, a qualified electrician must use an
appropriately listed external tester to verify protective-earth continuity/bonding
and correct hot/neutral polarity. Never route hot, neutral, or protective earth
through Rev-D or J14.
