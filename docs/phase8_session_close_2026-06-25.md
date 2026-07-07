# WSL Phase 8 — rev-B Board #1 Bring-Up Handoff (2026-06-25)

> **⚡ NEXT SESSION: this is the live state. The ribbon has arrived — the task is to wire J1↔Pi and finish the bench bring-up (Steps 2→3→4).** Companion memory: `project_phase8_revB_board1_bringup`. Full maps/test list: `docs/phase8_revB_board1_BENCH_TEST_PACKET.pdf`. Authoritative connector pinouts: `docs/manual_src/11_connector-pinouts.md` §11.

---

## TL;DR
Both halves are **built and proven independently**; they just haven't been connected. The **F/F 20-pin IDC ribbon is now in hand**. Wire 3 conductors (I²C), confirm the 3 MCPs answer, then bring up the relay-enable rail, then click-test the relays. Roughly an hour of bench work.

**Collaboration reminder:** Dylan is the hands (he's at the bench, new to electronics — give concrete, copy-paste, photo-driven steps). Claude researches/guides. Dylan deploys; no remote access to the board.

---

## 0. Entry state (what's already true)

**Board #1 (the controller PCB), powered on the bench via J2 (5 V):**
- Full pre-power ohm-out **PASS**. Powered, all rails correct: **TP1 ≈ 4.6 V** (5 V − SS14/D17 drop, expected), **TP3 = 3.3 V**, isolation **TP5↔TP2 OPEN** held live, nothing hot.
- **`FIELD_WET_V` (TP4→TP5) = 14 V is EXPECTED** — unloaded no-load rise of the unregulated **TMA-0505S** (U37 confirmed genuine; drops under field load). Do **not** chase it.
- **Pico (A1) flashed** (`firmware/rp2040/build/wsl_phase8b_rp2040.uf2`) and running → **RP2040_OK = TP14 = 3.3 V** (one of the rail's AND-conditions already satisfied).

**Pi (`lane-node-dev`) — fully staged:**
- `ssh pi@lane-node-dev.local` (password auth; 192.168.4.x). Repurposed Phase-8a bench Pi, Bookworm.
- Old `lane-node.service` **disabled**; 8a discrete rig (NE555 watchdog, 2× AL-ZARD, relay board) disconnected + bagged.
- **I²C `/dev/i2c-1` enabled + empty** (`i2c-20/21` are HDMI — ignore).
- 10 controller modules in `~/wsl-lane-nodes/lane_node/`; **`controller_daemon.py --selftest` = 28/28 PASS**.

---

## 1. STEP 2 — J1 ↔ Pi I²C harness (do this first)

**Goal:** `i2cdetect -y 1` on the Pi shows **0x20, 0x21, 0x22** (the three MCP23017s) = the I²C path + the 3 MCP joints are good.

### 1a. Prep the ribbon
- **Cut one F/F ribbon in half.** One half keeps a female IDC socket (→ J1); the cut end exposes bare conductors. (6-pack ordered — sacrifice one.)

### 1b. Plug onto J1 and CONFIRM ORIENTATION (critical — don't skip)
- Plug the socket onto **J1** (the 2×10 box header). The ribbon's **red stripe = conductor 1 = J1 pin 1** (J1 pin 1 = the corner **nearest J2**).
- **Board powered via J2**, then **meter the red conductor at the cut end → expect ~4.6 V** (`VCC_5V`).
  - **~4.6 V → orientation correct, proceed.**
  - **0 V / some other conductor reads 5 V → ribbon is flipped 180° → re-seat before wiring the Pi.** (A flip would feed signals backwards and could put 5 V where you don't want it.)

### 1c. Wire 3 conductors to the Pi (count from the red stripe)
| Ribbon conductor | Net | → Raspberry Pi **physical pin** |
|---|---|---|
| **2** | GND | **pin 6** |
| **3** | I2C_SDA | **pin 3** (GPIO2/SDA1) |
| **4** | I2C_SCL | **pin 5** (GPIO3/SCL1) |

### 1d. ⛔ HARD RULE — do NOT connect these to the Pi
- **Conductor 1 = `VCC_5V` (J1 pin 1)** and **conductor 11 = `VCC_3V3` (J1 pin 11)** must stay **OFF** the Pi. The board self-powers via J2; tying those rails to the Pi's 5 V / 3.3 V = two supplies fighting = damage. (We used conductor 1 only as the 4.6 V orientation probe — never wire it onward.)

### 1e. Run the check (on the Pi, board powered)
```bash
ssh pi@lane-node-dev.local
i2cdetect -y 1
```
**Expect 0x20, 0x21, 0x22** in the grid.

### 1f. If the MCPs DON'T show — troubleshoot in this order
1. **Common ground** — is conductor 2 actually on Pi pin 6 and continuous to board GND/TP2? No shared ground = nothing works.
2. **Orientation** — re-confirm the red-conductor-=-4.6 V check; a flipped ribbon puts SDA/SCL on the wrong pins.
3. **Board powered?** TP3 = 3.3 V (the MCPs run off the Pico-sourced 3V3; no 3V3 = dead MCPs).
4. **SDA/SCL continuity** — ribbon conductor 3 → board TP6, conductor 4 → board TP7 (ring them out).
5. **Solder joints** — reflow/inspect the 3 MCP joints if only some addresses appear (e.g., 0x20 + 0x21 but not 0x22 → check U3).
6. I²C is 3.3 V both sides (board pulls SDA/SCL up to its 3V3 via R1/R2); no level-shifter needed.

✅ **0x20/0x21/0x22 visible = Step 2 done.**

---

## 2. STEP 3 — bring up the relay-enable rail (`RELAY_ENABLE_RAIL`, TP16)

**The rail is a hardware AND of all of these — every one must be true or TP16 stays at 0 V (fail-safe):**
- NE555 watchdog being **kicked** (Pi pulses GPIO12 / `WDOG_KICK` / TP8),
- **ARM_PERMIT high** (Pi drives GPIO26 / J1 pin 8 / TP13),
- **RP2040_OK high** (already true — TP14 = 3.3 V),
- **J14 safety loop closed**, and the cam-stop / Stop-CIS safety inputs satisfied.

### 2a. Close the bench safety loop
- **Jumper J14 pin 1↔2 and pin 3↔4** (closes the two external NC interlock loops: `VCC_5V → loop1 → loop2 → PMOS source`). Without this the rail can't arm.
- (Optional: also confirm the other hardware safety inputs the rail gates on aren't holding it low — see §11.9 of the connector doc / the safety-rail section of the manual.)

### 2b. Drive ARM + watchdog kick
Two approaches:
- **Bench-isolate the rail (recommended first):** a tiny gpiozero snippet that holds **GPIO26 high** and **toggles GPIO12** continuously, so you test the *rail hardware* independent of the FSM. With J14 closed → **TP16 should go HIGH.**
- **Via the controller:** `cd ~/wsl-lane-nodes/lane_node && source ../.venv/bin/activate && python3 controller_daemon.py`. Note it **boots into `MANUAL_INTERVENTION`, disarmed** (power-down safety rule) and won't ARM until it sees First-Ball-Zero — so for a pure rail check the manual snippet is cleaner; for the integrated path you'll walk the FSM to ARMED.

### 2c. Verify + SAFETY
- **TP16 ≈ rail voltage when all conditions met; back to 0 V the instant you stop kicking the watchdog** (~10 s timeout) or drop ARM — confirm that fail-safe.
- ⚠️ **Once the rail is live, the relays CAN energize.** Keep the motion outputs (J6–J11) disconnected from anything that matters during bench testing — they'll just click.

---

## 3. STEP 4 — relay / motion click test (J6–J11)

Each is one relay's dry contact: **pin 2 = COM, pin 1 = NO** (open at rest). J6=S/K1, J7=T/K2, J8=SP/K3, J9=BE/K4, J10=M/K5, J11=M2/K6 (J12=DNP).

With the rail enabled, assert each channel via its MCP output (per-channel command in the daemon / a bench command):
- Relay should **audibly click**.
- Meter across that connector's two pins: **OPEN → ~0 Ω when energized**, back to OPEN when released = COM↔NO makes/breaks.
- Do all six. That validates the MCP→FET→relay→output chain end-to-end.

✅ **All six click + make/break = board #1 bench bring-up COMPLETE.** Next milestone after that is field-input testing (wet J3/J4/J5 inputs) and then the lane-pair cutover plan — separate effort.

---

## 4. Quick reference

**Pi pin map** (source `lane_node/controller_daemon.py` DEFAULT_BOARDS, board-21):
| Function | Pi BCM | Pi physical pin | Board net / J1 pin |
|---|---|---|---|
| I²C SDA | GPIO2 | 3 | `I2C_SDA` / J1 pin 3 |
| I²C SCL | GPIO3 | 5 | `I2C_SCL` / J1 pin 4 |
| GND | — | 6 | `GND` / J1 pin 2 |
| UART TX | GPIO14 | 8 | `PI_UART_TX` / J1 pin 5 (straight — crossover on-board) |
| UART RX | GPIO15 | 10 | `PI_UART_RX` / J1 pin 6 |
| WDOG_KICK | GPIO12 | 32 | `WDOG_KICK` / J1 pin 7 |
| ARM_PERMIT | GPIO26 | 37 | `ARM_PERMIT` / J1 pin 8 |
- I²C bus = **1** (`/dev/i2c-1`). UART = `ttyAMA0`. MCPs at **0x20 / 0x21 / 0x22**.

**Key test points** (logic → reference TP2; field → reference TP5):
| TP | Net | | TP | Net |
|---|---|---|---|---|
| TP1 | VCC_5V (4.6 V) | | TP8 | WDOG_KICK |
| TP2 | GND | | TP13 | ARM_PERMIT |
| TP3 | VCC_3V3 (3.3 V) | | TP14 | RP2040_OK (3.3 V) |
| TP6/TP7 | I2C_SDA / SCL | | TP16 | RELAY_ENABLE_RAIL |
| TP4/TP5 | FIELD_WET_V / FIELD_GND | | | |

Full probe-location map + connector pin-number map + the tick-box test list: **`docs/phase8_revB_board1_BENCH_TEST_PACKET.pdf`**.

---

## 5. Non-blockers + follow-ups (none stop the bring-up)
- **`requirements-lane-node.txt` not on the Pi** (deps already in `.venv`, selftest passed). Land for completeness: `scp requirements-lane-node.txt pi@lane-node-dev.local:wsl-lane-nodes/`.
- **`/var/log/lane-node` unwritable** → `sudo mkdir -p /var/log/lane-node && sudo chown pi:pi /var/log/lane-node` (flight-recorder dumps).
- **GIT PUSH BLOCKED:** laptop `fable-audit-fixes` can't push — a **160 MB `docs/8270-service-parts-manual.pdf` in history exceeds GitHub's 100 MB limit**. Purge from history (git-filter-repo / BFG) + `.gitignore` the manuals; then the Pi can `git pull` instead of the scp workaround. Local commit **`e6e3653`** holds requirements + rev-B docs, waiting to push.
- **rev-C board fixes:** break **SWD to a 3-pin header** (Pico USB is the ONLY flash path and it's jammed against J1 — this time flashed via a hand-shaved right-angle micro-B cable); give the USB end clearance; add the **J1 mating socket** to the assembly BOM; consider a **min-load/bleed resistor on `FIELD_WET_V`**.

## 6. Hard safety rules (recap)
1. **Never wire J1 pin 1 (`VCC_5V`) or pin 11 (`VCC_3V3`) to the Pi.**
2. **Never bridge a meter/scope ground across TP2 (GND) and TP5 (FIELD_GND)** — that defeats the U37 isolation barrier.
3. **The relay-enable rail is never the sole safety device** — preserve the machine's hardware safety chain; bench-test with motion outputs disconnected.
4. Confirm ribbon orientation (red conductor = 4.6 V) **before** the Pi connects.
