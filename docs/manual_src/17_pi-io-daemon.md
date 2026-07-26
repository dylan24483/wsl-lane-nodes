## 17. Pi Software: IO Layer, RP2040 Link & Controller Daemon

This section documents the three Python modules that run **on the Raspberry Pi** and turn the rev-B controller board into a working AMF 82-70 lane controller:

| File (in `lane_node/`) | Class(es) | Job |
|---|---|---|
| `controller_io.py` | `MachineIO`, `RecordingIO` | The hardware `io` object the cycle FSM drives: 3× MCP23017 over I²C (relays, lamps, slow inputs), gripper-mask read, watchdog kick, arm-relay control. `RecordingIO` is the no-hardware test fake. |
| `rp2040_link.py` | `RP2040Link` (+ `dispatch_cam`) | Parses fast cam/ball events, dispatches them to the FSM, contains a **default-off/unvalidated SC∧TB software-model path**, tracks RP2040 health, and sends `RUN`/`STOP`/`CLEAR`/`PING`. |
| `controller_daemon.py` | `BoardController`, `run()` | Assembles `RP2040Link` + `MachineIO` + the cycle FSM per lane and runs the real-time control loop, including the health-loss safety trip and the SIGTERM safe-off. |

These modules sit **above** the rev-B board hardware (Sections 5–13) and **beside** the RP2040 firmware (Section 15 — RP2040 Firmware & Cam Timing). They are driven by, and drive, the cycle finite-state machine in `lane_node/cycle_control_8270.py` (`CycleController`), whose state sequence is described in Section 3 — *The AMF 82-70 Machine: Assemblies, Sequence of Operation & Cam Timing*.

> **Where this fits in the safety architecture.** Everything here is software. The
> authoritative TB/SC guard is Candidate C's powered-proven OEM parallel-safe S/T
> coil ladder, with a controlled J_SAFE1-2 jumper and per-lane G3 proof — not a J14
> NC machine loop. Other hardware layers include the implemented relay-enable gates,
> fail-safe `RP2040_OK`, the external installed Stop/master-breaker chain, and regenerative
> braking. J_SAFE3-4 is currently OPEN/unlanded and receives no field-protection
> credit. The software SC∧TB path is default-off, secondary, and unvalidated.

---

### 17.1 The FSM `io` Contract (what both IO classes implement)

`CycleController` is written entirely against an abstract `io` interface — it never touches a GPIO or an I²C register directly. Both `MachineIO` (real hardware) and `RecordingIO` (test fake) implement the same method set, which is why the exact same FSM code runs on the bench laptop and on the Pi. The contract:

| Method | Direction | Meaning |
|---|---|---|
| `set_sweep(on)` | output | Energize/de-energize the **S** (sweep) relay. |
| `set_table(on)` | output | Energize/de-energize the **T** (table) relay. |
| `set_spot(on)` | output | Energize/de-energize the **SP** (spot solenoid) relay. |
| `set_light(name, on)` | output | Drive a status lamp: `first_ball` / `second_ball` / `strike` / `foul`. |
| `set_pin_lamps(mask)` | output | Drive the optional 10-bit physical pin mask (OUT-B). No-op in the camera-scoring baseline. |
| `read_grippers()` | input | Return a 10-bit standing-pin mask (bit *n*−1 = GS*n* standing). |
| `gp_closed()` | input | Gripper-protect switch state. |
| `bs_closed()` | input | Bin/#9 switch state. |
| `read_input(name)` | input | Generic slow-input read used by the daemon (`PBZ`, `PBC`, `Foul`, `OS`, …). |
| `interlock_ok()` | input | Default-true/default-off **secondary, unvalidated** SC∧TB software model (see §17.3, §17.4). |
| `watchdog_kick()` | housekeeping | Pet the NE555 watchdog. Called by `CycleController.poll()`. |
| `arm(on)` | housekeeping | Assert/deassert the relay-enable **arm** GPIO (power-down rule). |
| `now()` | housekeeping | Monotonic clock (injectable, for delay tests). |
| `log(msg)` | housekeeping | Log a line. |

Two behaviours of this contract are load-bearing for safety and are easy to get wrong when extending the code:

- **`poll()` kicks the watchdog.** The NE555 is petted *only* from inside the FSM's `poll()` (via `io.watchdog_kick()`), which the daemon calls once per tick. If the control loop stalls, the kicks stop, and the NE555 drops the rail in hardware (Section 10). This coupling is deliberate and must be preserved (contrast with the Track-A scoring node, where scoring must **never** be able to stop the machine).
- **`arm(on)` only *gates* the rail.** Asserting arm does not energize anything by itself; on-board gates still include watchdog, RP2040-OK/cam-stop, and J_SAFE source continuity. Candidate C supplies the controlled J_SAFE1-2 jumper. The lane-21/22 J_SAFE3-4 external-source position is currently OPEN/unlanded, so the field rail cannot arm until a validated external energize-to-prove control-power relay dry-contact interface exists. S/T additionally require the OEM TB/SC ladder to permit their coils. De-asserting arm is a real disable.

---

### 17.2 `controller_io.py` — `MachineIO` (real hardware)

`MachineIO` is the concrete `io` for **one lane / one board**. Construction opens that board's own I²C bus and the three MCP23017 expanders, and accepts the RP2040 link and the two safety GPIO callables by dependency injection so the transport stays testable and pluggable.

#### 17.2.1 Constructor

```python
MachineIO(lane_id, bus_id, *, watchdog_kick=None, arm_relays=None,
          now=None, enable_pin_lamps=False, rp2040=None)
```

| Arg | Meaning |
|---|---|
| `lane_id` | Lane number this board controls (one board per lane — Section 5). |
| `bus_id` | Pi I²C bus number for **this** board (per-board bus — Section 7). |
| `watchdog_kick` | `callable()` that pets the NE555 (e.g. the daemon's GPIO pulse). Defaults to a no-op. |
| `arm_relays` | `callable(bool)` that drives the board's **arm** GPIO (the `ARM_PERMIT` rail condition). Defaults to a no-op. |
| `now` | Monotonic clock, injectable; defaults to `time.monotonic`. |
| `enable_pin_lamps` | If `True`, also open OUT-B (0x23) for the optional physical pin mask. Default `False` — the camera supplies pin state in the baseline. |
| `rp2040` | An `RP2040Link` (or `None`). When present, `MachineIO` contains the default-off/unvalidated SC/TB software model and sends `RUN`/`STOP`. Lane 21/22 has no independent TB lead, so the echo is not a field guard or credited diagnostic. |

The constructor imports `smbus2` (falling back to `smbus`) **lazily** so the module — and the `RecordingIO` test path — load on any machine without I²C hardware. It then configures the MCPs (all-inputs for IN-A/IN-B with **internal pulls off**, all-outputs for OUT-A) and logs the bus + addresses. On Rev-D, the external 47 kΩ `Rpu_*` network is the sole input bias.

> **Pi-only dependency:** `MachineIO` needs `smbus2` (or `smbus`) on the Pi for the MCP23017s. The library import is deferred to construction time, not module import time.

#### 17.2.2 The three MCP23017 expanders and their I²C addresses

Each board carries three MCP23017 I²C I/O expanders (part **MCP23017-E/SO**, LCSC **C47023** — see Section 9/Section 14; this is the **I²C** MCP23017, *not* the SPI MCP23S17). They sit on the board's **own** I²C bus, and every board repeats the same address set, because each board has its own bus (so there is no address collision across a lane pair). A fourth address, 0x23, is reserved for the optional pin-lamp expander.

| Constant | Address | Role | `dir_mask_a` / `dir_mask_b` | Pull-ups | Populated in baseline? |
|---|---|---|---|---|---|
| `ADDR_IN_A` | **0x20** | Grippers GS1–10 + GP/OS/BS/PBZ/PBC/Foul | `0xFF` / `0xFF` (all inputs) | **`0x00` / `0x00` (all off, read back)** | Yes |
| `ADDR_IN_B` | **0x21** | 10th-frame + manual + spare inputs | `0xFF` / `0xFF` (all inputs) | **`0x00` / `0x00` (all off, read back)** | Yes (initialized; **not yet read** by the FSM) |
| `ADDR_OUT_A` | **0x22** | 7 relay drives + 4 status-lamp drives | `0x00` / `0x00` (all outputs) | — | Yes |
| `ADDR_OUT_B` | **0x23** | Optional physical pin lamps + neon | `0x00` / `0x00` (all outputs) | — | **No** (only opened if `enable_pin_lamps=True`) |

In the MCP23017 IODIR convention used here, **`1` = input, `0` = output**. IN-A and IN-B are therefore `0xFF` on both ports (all inputs), while OUT-A is `0x00` (all outputs). Historical Rev-B software enabled input GPPU, but current Rev-D commands and reads back **`GPPUA=GPPUB=0x00`** on U1/U2; any mismatch is STOP-SHIP because it invalidates the external-47 kΩ qualification and can mask an open `Rpu_*`. The expander A2/A1/A0 address-strap wiring that produces these addresses lives in the netlist `block_mcp()` calls — `MCP_IN_A` straps `(0,0,0)`→0x20, `MCP_IN_B` straps `(1,0,0)`→0x21, `MCP_OUT_A` straps `(0,1,0)`→0x22 (see Section 7).

> **3.3 V, not 5 V.** All three MCP23017s and every opto logic-side pull-up run on the **3.3 V** rail (`VCC_3V3`, the Pico's 3V3 output), specifically so the I²C bus and all logic highs stay Pi-safe (Section 6 — *Rev-B Power Architecture*). Do not move them to 5 V.

#### 17.2.3 The `_MCP23017` driver

`_MCP23017` is a minimal smbus driver. The register constants are the **bank-0 / IOCON.BANK=0 default** mapping:

| Register | Address (port A / port B) |
|---|---|
| `IODIR` (direction) | `0x00` / `0x01` |
| `GPPU` (pull-up enable) | `0x0C` / `0x0D` |
| `GPIO` (read) | `0x12` / `0x13` |
| `OLAT` (output latch) | `0x14` / `0x15` |

Key behaviours:

- **Latch caching.** The driver caches `OLATA`/`OLATB` (`self._olat`) so a per-bit `write_bit(port, bit, value)` does not have to read-modify-write the bus — it updates the cached byte and writes it. This matters because the FSM toggles individual relay/lamp bits frequently inside a cycle.
- **`read_port(port)`** reads `GPIOA` (port 0) or `GPIOB` (port 1) and returns the raw byte.
- **`all_off()`** zeros both output latches in one pair of writes — used on fault/shutdown.
- **Port convention used throughout:** **port 0 = GPIOA / OLATA**, **port 1 = GPIOB / OLATB**.

#### 17.2.4 Output bit map — `OUT_A_MAP` (chip 0x22)

> **SOURCE OF TRUTH.** `OUT_A_MAP` is the Pi-side mirror of `OUTPUT_PINS` in `scripts/generate_kicad_netlist_revB.py`. **The routed rev-B board is wired from the generator, so these MUST match it.** A self-test at the bottom of `controller_io.py` re-derives the expected map from the generator's AST and `assert`s equality on every run — this exists specifically because Codex caught BS/OS, M1/M2, and strike/foul swaps on 2026-06-03. The values below are the current, correct, regression-locked map.

MCP pin numbering: **GPA0–7 = MCP pins 21–28**, **GPB0–7 = MCP pins 1–8**. So `_pin_to_portbit`: pin 21–28 → `(0, pin−21)`; pin 1–8 → `(1, pin−1)`.

| FSM name | (port, bit) | MCP pin / GP line | Generator key | Function |
|---|---|---|---|---|
| `S` | (0, 0) | pin 21 / GPA0 | `S` | Sweep relay |
| `T` | (0, 1) | pin 22 / GPA1 | `T` | Table relay |
| `SP` | (0, 2) | pin 23 / GPA2 | `SP` | Spot solenoid |
| `BE` | (0, 3) | pin 24 / GPA3 | `BE` | Back-end (future) |
| `M` | (0, 4) | pin 25 / GPA4 | `M` | Master (future) |
| `M2` | (0, 5) | pin 26 / GPA5 | `M2` | Sweep reverse — **M2 sits before M1** (per generator order) |
| `M1` | (0, 6) | pin 27 / GPA6 | `M1` | Ball return — **DNP / populate-optional** (not bench-confirmed; FSM doesn't drive it) |
| `first_ball` | (0, 7) | pin 28 / GPA7 | `L_FIRST` | 1st-ball lamp |
| `second_ball` | (1, 0) | pin 1 / GPB0 | `L_SECOND` | 2nd-ball lamp |
| `strike` | (1, 1) | pin 2 / GPB1 | `L_STRIKE` | Strike lamp |
| `foul` | (1, 2) | pin 3 / GPB2 | `L_FOUL` | Foul lamp |

The generator-key column shows the name translation the self-test applies: the lamp outputs are `L_FIRST`/`L_SECOND`/`L_STRIKE`/`L_FOUL` in the netlist but `first_ball`/`second_ball`/`strike`/`foul` in the FSM. The relay drives carry the same names in both.

> **M1 is DNP.** The M1 (ball-return) channel — relay, driver, snubber/MOV, and connector — is present as copper but **Do Not Populate** until ball-return is confirmed to exist as a separate command on this chassis. The FSM does not drive M1. See Section 9/Section 14 §3.2.

#### 17.2.5 `MOTION_RELAYS` vs lamps

```python
MOTION_RELAYS = ("S", "T", "SP", "BE", "M", "M1", "M2")
```

This tuple distinguishes the seven **motion relays** from the four status **lamps** (`first_ball`/`second_ball`/`foul`/`strike`). Its only job: in `_set_out()`, when an RP2040 link is wired and a *motion relay* toggles, `MachineIO` also sends the firmware a `RUN <name>` (on) or `STOP <name>` (off) so the RP2040's motion max-run backstop knows what is energized. **Lamps are never sent to the firmware** — they aren't motors and aren't on the safety rail.

> Note the asymmetry between `MOTION_RELAYS` (includes `BE` and `M`) and which of those motors the **firmware** actually time-guards. Per Section 15 / `firmware/rp2040/main.c`, `BE` (continuous back-end) and `M` (master/power) are **not** max-run-guarded — they are tracked but never time out. So `MachineIO` will send `RUN BE` / `RUN M`, and the firmware accepts them but does not apply the 8 s backstop to them.

#### 17.2.6 Output methods

- `set_sweep(on)` → `_set_out("S", on)`, `set_table(on)` → `_set_out("T", on)`, `set_spot(on)` → `_set_out("SP", on)`.
- `_set_out(name, on)` writes the OUT-A bit per `OUT_A_MAP`, then — if `rp2040` is wired and `name in MOTION_RELAYS` — calls `self._rp2040.run(name)` / `.stop(name)`.
- `set_light(name, on)` validates `name ∈ {first_ball, second_ball, foul, strike}` (warns and returns on an unknown lamp) and routes through `_set_out` (so lamps share the OUT-A write path but are excluded from the RUN/STOP sidechannel).
- `set_pin_lamps(mask)` is a **no-op unless** `enable_pin_lamps` is true *and* OUT-B exists. When active, it writes 10 bits across OUT-B: bits 0–7 → port 0, bits 8–9 → port 1 (`(0, i)` for `i < 8`, else `(1, i−8)`). In the camera-scoring baseline the physical mask is omitted and this method does nothing.

#### 17.2.7 Input methods, polarity, and the gripper mask

```python
INPUT_ACTIVE_LOW = True
```

The PC817 optos (part **PC817B**, LCSC **C5692981** — Section 8/Section 14) are **active-low at the MCP pin**: a closed field contact pulls the opto, which pulls the MCP pin **LOW**. So **"asserted / closed / standing" = pin reads 0**. `INPUT_ACTIVE_LOW = True` encodes that globally; the comment notes you would only set a channel active-high if a particular front-end were wired the other way.

- `_read_in(name)` reads the IN-A bit per `IN_A_MAP` and returns `raw == 0` (when active-low). Used by `gp_closed()`, `bs_closed()`, and `read_input(name)`.
- `read_grippers()` reads **both ports of IN-A once each** (`p0`, `p1`), then slices the ten gripper bits in `GRIPPER_ORDER` and builds the standing-pin mask, where **bit *i* = GS(*i*+1) standing** (a pin reads 0 when standing, which sets its mask bit). Reading each port once — rather than per-bit — keeps the gripper snapshot atomic and cheap.
- `read_input(name)` is the generic slow-input read the daemon uses for `PBZ`, `PBC`, `Foul`, `OS`, etc.

```python
GRIPPER_ORDER = [f"GS{i}" for i in range(1, 11)]   # GS1=bit0 ... GS10=bit9
```

#### 17.2.8 Slow-input bit map — `IN_A_MAP` (chip 0x20)

> **SOURCE OF TRUTH.** `IN_A_MAP` mirrors the `MCP_IN_A` entries of `SLOW_INPUT_PINS` in the netlist generator and is regression-locked by the same self-test (`FOUL`→`Foul` is the only name translation). Same MCP pin numbering as §17.2.4 (GPA0–7 = pins 21–28, GPB0–7 = pins 1–8).

| FSM name | (port, bit) | MCP pin / GP line | Meaning |
|---|---|---|---|
| `GS1` | (0, 0) | 21 / GPA0 | Gripper 1 |
| `GS2` | (0, 1) | 22 / GPA1 | Gripper 2 |
| `GS3` | (0, 2) | 23 / GPA2 | Gripper 3 |
| `GS4` | (0, 3) | 24 / GPA3 | Gripper 4 |
| `GS5` | (0, 4) | 25 / GPA4 | Gripper 5 |
| `GS6` | (0, 5) | 26 / GPA5 | Gripper 6 |
| `GS7` | (0, 6) | 27 / GPA6 | Gripper 7 |
| `GS8` | (0, 7) | 28 / GPA7 | Gripper 8 |
| `GS9` | (1, 0) | 1 / GPB0 | Gripper 9 |
| `GS10` | (1, 1) | 2 / GPB1 | Gripper 10 |
| `GP` | (1, 2) | 3 / GPB2 | Gripper protect |
| `OS` | (1, 3) | 4 / GPB3 | Off-spot |
| `BS` | (1, 4) | 5 / GPB4 | Bin / #9 switch |
| `PBZ` | (1, 5) | 6 / GPB5 | First-ball / zero / manual-intervention pushbutton |
| `PBC` | (1, 6) | 7 / GPB6 | Cycle pushbutton |
| `Foul` | (1, 7) | 8 / GPB7 | Foul (Radaray beam) |

(The IN-B bank at 0x21 — 10th-frame, manual T/S/SWS/SWSR, AUX1–3 — is configured by the constructor but has no FSM reader yet; see Section 12 — *Channel Maps* — and Section 14 §IN-B for its connector landing on `J_SLOW_IN_B`/J5.)

#### 17.2.9 Interlock echo, watchdog, arm, and shutdown

- `interlock_ok()` — default-true software model only. It is **default-off as a firmware safety feature, secondary, and unvalidated** because lanes 21/22 have no independent TB field input. The authoritative guard is the OEM S/T coil ladder accepted by Candidate-C G3, not J_SAFETY.
- `watchdog_kick()` calls the injected `watchdog_kick` callable (the NE555 pet).
- `arm(on)` calls the injected `arm_relays` callable — the `ARM_PERMIT` rail condition.
- `all_off()` drives every output LOW (OUT-A, and OUT-B if present). Used on fault/shutdown.
- `close()` calls `all_off()`, de-asserts arm, then closes the I²C bus (each step guarded so shutdown can't throw).

---

### 17.3 `rp2040_link.py` — `RP2040Link`

`RP2040Link` is the Pi side of the UART link to the on-board RP2040. The PCB allocates eight fast inputs, but the lane-21/22 harness has no TB lead and leaves SC/U unlanded absent a reviewed observe-only input. This class parses valid events, feeds cam/ball events to the FSM, contains the unvalidated SC/TB software model, tracks health, and sends commands back.

#### 17.3.1 Wire protocol

Newline-delimited JSON, **115200 baud, 8N1** (see `firmware/rp2040/README.md`, Section 15):

**RP2040 → Pi (events):**

| Line (example) | Meaning |
|---|---|
| `{"ev":"boot","fw":"…","wdt_reset":0,"rp_ok":0}` | RP2040 booted; `wdt_reset:1` means a watchdog reset just happened. |
| `{"ev":"cam","id":"SA","e":"f","t":…}` | Cam edge; `e`: `f`=asserted(fall), `r`=released(rise). |
| `{"ev":"ball","src":"L","t":…}` | One ball detected (DIELL beam), lockout-deduped; `src` = `L`/`R`. |
| `{"ev":"rp_ok","v":1,"t":…}` | Rail-permission changed. |
| `{"ev":"hb","ok":1,"flt":"","up":…,"drp":…}` | Heartbeat (~4 Hz); `ok` mirrors `rp_ok`, `drp` = dropped TX lines. |
| `{"ev":"flt","code":"motion_timeout","m":"S","t":…}` | Firmware latched a fault. |
| `{"ev":"ack","cmd":"CLEAR","t":…}` | Command acknowledged. |

**Pi → RP2040 (commands):** `RUN <m>` · `STOP <m>` / `STOP *` · `CLEAR` · `PING`.

#### 17.3.2 The cam → FSM dispatch map

Two module constants split cam IDs by role:

```python
CAM_DISPATCH   = ("SA", "SB", "TA1", "TA2")    # mapped to FSM cam methods
INTERLOCK_CAMS = ("SC", "TB")                   # interlock-only; NOT dispatched to the FSM
MOTORS         = ("S", "T", "SP", "BE", "M", "M1", "M2")
```

`SC` and `TB` have **no** `cam_SC`/`cam_TB` FSM method — they exist only to feed `interlock_ok()` (§17.3.4). The other four cams map to FSM calls via `dispatch_cam(controller, cam_id)`:

| Cam event `id` | FSM call(s) | Why two calls for SA/TA1 |
|---|---|---|
| `SB` | `controller.cam_SB_guard()` | Single handler. |
| `TA2` | `controller.cam_TA2_runthrough()` | Single handler; this is the pin-latch / strike-decision cam. |
| `SA` | `controller.cam_SA_runthrough()` **then** `controller.cam_SA_zero()` | SA is a **dual-trip** cam (270° run-through vs 360° zero). The FSM guards each handler by state, so calling both is safe — only the state-matching one acts. |
| `TA1` | `controller.cam_TA1_delayreset()` **then** `controller.cam_TA1_zero()` | TA1 is dual-trip (185° delay-reset vs 355° zero). Same state-guard rationale. |

The design note here is important for anyone extending the map: **the FSM, not the link, decides which angular variant of a dual-trip cam acts**, by guarding each handler on the current state. The link simply fires both candidate methods on a trip; the FSM ignores the one that doesn't match its state. This is why the firmware does not need to know each cam's per-angle polarity to forward events (that polarity is a deferred cutover item — Section 21, Section 15).

#### 17.3.3 Concurrency model — the thread-safe event queue

This is the single most important thing to understand before touching this module. **The serial reader runs on a background thread, but the FSM is touched from one thread only.** The split:

- The **reader thread** (`_read_loop` → `feed_line` → `_handle`) only ever (a) **updates state** (health, SC/TB danger) under `self._lock`, or (b) **queues** cam/ball events under `self._evlock` into a `collections.deque`. It never calls into the FSM.
- The **daemon's main loop** drains the queue via `apply_events(controller)`, which is the *only* place cam/ball events reach the FSM. Because `CycleController` is **not** thread-safe, this keeps all FSM access single-threaded.

```python
self._lock   = threading.Lock()    # guards _sc_danger, _tb_danger, _rp_ok, _last_hb, _fault
self._evlock = threading.Lock()    # guards the _events deque
self._events = deque()             # queued ("cam", id) / ("ball", src), drained by apply_events()
```

`apply_events(controller)` snapshots and clears the deque under `_evlock`, then replays each event: `("cam", id)` → `dispatch_cam`, `("ball", src)` → `controller.on_ball()`. It returns the count applied. **Call it from the main loop immediately before `controller.poll()`** so the FSM advances on fresh events.

> **Rule for maintainers:** never call an FSM method from the reader thread, and never read the FSM from it. If you need the reader to influence the FSM, queue an event or set a `_lock`-guarded flag and let the main loop act on it.

#### 17.3.4 Inbound parsing (`feed_line` / `_handle`)

- `feed_line(line)` strips, ignores blanks, `json.loads` it (logging and ignoring unparseable lines — a malformed line **never** throws), ignores non-dict payloads, then dispatches by `ev`.
- **`cam`:** if `id ∈ INTERLOCK_CAMS`, set `_sc_danger`/`_tb_danger = (e == trip_edge)` under `_lock`. Otherwise, if it's a **trip edge** and `id ∈ CAM_DISPATCH`, queue `("cam", id)`. (Non-trip edges of dispatch cams are dropped — they are not queued.)
- **`ball`:** queue `("ball", src)`.
- **`hb` / `boot` / `rp_ok` / `flt` / `ack`:** under `_lock`, refresh `_last_hb = now()` (any of these counts as a sign of life), then update health (see §17.3.6). After releasing the lock, fire the optional `on_health(ev)` callback (the daemon may set this for logging/alerts).

#### 17.3.5 Outbound commands (`run` / `stop` / `stop_all` / `clear` / `ping`)

`_send(line)` always appends to `self.sent` (so tests and the bench can assert on what was sent) and, if a serial object is present, writes `line + "\n"`. A write failure is caught and logged — **a comms hiccup never crashes the caller** (telemetry must not break control). The public commands: `run(motor)`→`RUN <m>`, `stop(motor)`→`STOP <m>`, `stop_all()`→`STOP *`, `clear()`→`CLEAR`, `ping()`→`PING`.

#### 17.3.6 Health tracking — `rp_ok`, `is_alive`, `health_ok`, `fault`

The firmware's `RP2040_OK` is a **hardware** rail line (Section 15); a dead or `!ok` RP2040 drops the rail regardless of this module. This module **additionally** surfaces health so the daemon can fault the FSM and drop arm.

| Query | True when |
|---|---|
| `rp_ok()` | The last health update reported rail-permit OK (`_rp_ok`). |
| `is_alive()` | A heartbeat has been seen **and** `now() − _last_hb ≤ hb_timeout` (default `hb_timeout = 1.0 s`). |
| `health_ok()` | **alive AND `_rp_ok` AND no latched `_fault`.** This is the gate the daemon uses. |
| `fault()` | The latched fault code string (`""` if none). |

Health-update rules inside `_handle` (all under `_lock`):

- An explicit **`flt`** event sets `_fault = ev["code"]` and `_rp_ok = False` **immediately** — even if the paired `rp_ok:0` line is delayed or dropped on a lossy UART. This was a deliberate P2 fix: a bare fault must mark the link unhealthy on its own.
- Otherwise, `_rp_ok` is updated from whichever of `v` / `ok` / `rp_ok` is present (checked in that order), and `_fault` is updated from `flt` if present. A heartbeat carrying `flt:""` (which the firmware sends after a `CLEAR`) is what clears the fault and restores `health_ok()`.

#### 17.3.7 The interlock echo (`interlock_ok`)

```python
def interlock_ok(self):
    with self._lock:
        return not (self._sc_danger and self._tb_danger)
```

This implements an SC∧TB software model, but it is **not a field-validated echo**:
lane 21/22 has no independent TB observation and C2A-U is not a dry input. It
therefore remains default-off/secondary and cannot be credited as protection or
diagnostics. Powered truth is the OEM parallel closed-when-safe ladder; both levers
BACK/open block both S and T coils, re-proven per lane at G3.

#### 17.3.8 Reader thread lifecycle (`start` / `_read_loop` / `close`)

- `start()` spawns the daemon-thread reader (`name="rp2040-rx"`), but only if a serial object exists.
- `_read_loop()` reads up to 256 bytes, accumulates into `self._rx`, and splits on `\n`, feeding each complete line to `feed_line` (decoding ASCII, replacing errors). A serial read error is logged and the loop sleeps 0.5 s and retries — it does not die.
- `close()` sets the stop flag and closes the serial port (guarded).

#### 17.3.9 Construction options

```python
RP2040Link(port=None, baud=115200, *, serial_obj=None,
           hb_timeout=1.0, trip_edge="f", now=None)
```

Three ways to instantiate: a real `port` (opens `serial.Serial(port, baud, timeout=0.1)` — pyserial imported lazily), an injected `serial_obj` (anything with `read()`/`write()`/`close()`), or neither (feed lines by hand via `feed_line()` — used by the host tests and the daemon's `sim` mode). `trip_edge` selects which edge (`f`/`r`) is a landed motion cam's angular trip. **Do not assume one normally-closed polarity for every cam:** measure each edge→angle relationship. Stock v1.2.3 enforcement flags remain OFF until those results are bound into a new controlled release.

---

### 17.4 `controller_daemon.py` — the per-board control loop

> **SKELETON / BENCH-GATED.** This file is explicitly a skeleton. **Do not run it against a live machine** until the full hardware safety chain is validated per `docs/phase8b_pcb_revB_spec.md` §12.9 and the Track-B controller cutover runbook (Section 21). Every field marked `# CONFIRM` in the source (pin numbers, I²C bus IDs, UART ports, slow-input polarity/debounce) is set at bench/cutover, not now. The scoring/server reporting path (Track A camera + `lane_node.py` websocket) is **not yet wired in** — see the `TODO(server)` note; the controller loop is deliberately a tight synchronous loop, while scoring/IO-to-server is async and lives elsewhere.

#### 17.4.1 `BoardConfig` and `DEFAULT_BOARDS`

```python
@dataclass
class BoardConfig:
    lane: int        # lane this board controls
    i2c_bus: int     # per-board I2C bus
    uart_port: str   # serial device to THIS board's RP2040
    arm_pin: int     # Pi GPIO -> relay-enable ARM for this board
    wdog_pin: int    # Pi GPIO -> this board's NE555 kick
```

```python
DEFAULT_BOARDS = [
    BoardConfig(lane=21, i2c_bus=1, uart_port="/dev/ttyAMA0", arm_pin=26, wdog_pin=12),
    BoardConfig(lane=22, i2c_bus=3, uart_port="/dev/ttyAMA1", arm_pin=13, wdog_pin=6),
]
```

> **(VERIFY: most fields in `DEFAULT_BOARDS` are bench-confirm placeholders.)** Per-field confidence (updated source + **`docs/phase8_pi_provisioning.md`**, which gives the `config.txt` boot overlays that make the 2nd I²C bus + 2nd UART *exist* and a deconflicted Pi-GPIO pin table): **FIRM** — board-21 `i2c_bus=1` (Pi hardware I²C, GPIO2/3) and `wdog_pin=12` (the existing, bench-validated watchdog-kick pin). **CONFIRM at bench** — the 2nd I²C bus number + its `i2c-gpio` SDA/SCL pins, both RP2040 UART device names (`/dev/ttyAMA0`, `/dev/ttyAMA1`), and the arm GPIOs (26/13). Those second-bus/second-UART devices only exist once the provisioning-doc overlays are applied. The board's `J_PI`/J1 carries dedicated `WDOG_KICK` and `ARM_PERMIT` lines (Section 11), but **which Pi GPIO drives each is not fixed in the design sources** — confirm at bench before trusting these numbers.

The daemon disarms in three FSM states:

```python
DISARMED_STATES = (State.POWER_OFF, State.MANUAL_INTERVENTION, State.FAULT)
```

In any of these, the arm GPIO must stay de-asserted (the power-down rule — Section 10 / SYSTEM_REFERENCE §5).

#### 17.4.2 Slow-input → FSM action map

The daemon edge-detects a subset of slow MCP inputs and turns a **rising (asserted) edge** into an FSM method call (cams + ball arrive via the RP2040 link; grippers/GP are polled inside the FSM):

| Slow input | Action on rising edge | Notes |
|---|---|---|
| `PBZ` | `fsm.first_ball_zero()` **and** `link.clear()` | Operator re-arm. Also sends `CLEAR` so the firmware's fault latch clears in lock-step. |
| `BS` | `fsm.bin_full()` | 10th pin to the bin → spot a fresh rack. |
| `Foul` | `fsm.on_foul()` | Radaray foul beam. |

`PBC`, `OS`, `TENTH`, and the `MAN_*` inputs are routed on the board but have **no FSM handler yet** (future work).

#### 17.4.3 `BoardController` assembly

`BoardController(cfg, *, sim=False)` wires the three pieces together for one lane:

- **`sim=True`** (off-Pi / self-test): `RP2040Link()` with no serial (feed via `feed_line()`) + `RecordingIO(rp2040=link)`. No GPIO.
- **`sim=False`** (on the Pi): lazily imports `gpiozero.LED`; creates `LED(arm_pin)` (the arm GPIO, de-asserted by default) and `LED(wdog_pin)` (the NE555 kick); opens `RP2040Link(port=uart_port)`; builds `MachineIO(lane, i2c_bus, rp2040=link, watchdog_kick=self._kick_wdog, arm_relays=self._set_arm)`; and calls `link.start()` to launch the background reader.

In both modes it then builds `CycleController(lane, io)` and calls **`fsm.power_restore()`** so the controller **comes up disarmed** (power-down rule) — it boots into `MANUAL_INTERVENTION` and requires a deliberate First-Ball-Zero before it will arm. It also snapshots the slow-input actions and initializes `_prev_slow` (all `False`) and `_was_healthy = True`.

GPIO callbacks:

- `_kick_wdog()` → `self._wdog.toggle()` — an **edge each poll** keeps the NE555 alive. *(The exact required kick waveform is marked `# CONFIRM`; see §17.4.6. (VERIFY: whether a level-toggle per poll satisfies the NE555 retrigger timing, or whether a defined pulse is required — bench item.))*
- `_set_arm(on)` → `self._arm_led.value = 1 if on else 0` — drives `ARM_PERMIT`.

#### 17.4.4 The tick loop (`tick()`)

The healthy-path tick, in order:

```python
def tick(self):
    healthy = self.link.health_ok()
    if not healthy:
        ... SAFETY TRIP (see §17.4.5) ...
        return
    if not self._was_healthy:
        self.io.log("... RP2040 link recovered -> awaiting First-Ball-Zero")
    self._was_healthy = True

    self.link.apply_events(self.fsm)   # 1) cam/ball edges -> FSM (single-threaded here)
    self._slow_edges()                 # 2) PBZ/BS/Foul rising edges -> FSM
    self.fsm.poll()                    # 3) advance FSM + KICK the NE555 (poll() kicks via io)
    self.io.arm(self.fsm.state not in DISARMED_STATES)   # 4) arm policy
```

The four ordered steps each tick:

1. **`apply_events`** drains the RP2040 cam/ball queue into the FSM (the only single-threaded FSM-touch point).
2. **`_slow_edges`** reads each mapped slow input via `io.read_input(name)`, and on a `False → True` transition fires its action, updating `_prev_slow`. *(Debounce on these edges is `# CONFIRM` — see §17.4.6.)*
3. **`fsm.poll()`** advances the FSM **and pets the NE555** (the kick is inside `poll()` via `io.watchdog_kick()`). This is the watchdog-coupling described in §17.1.
4. **Arm policy:** assert arm iff the FSM state is **not** in `DISARMED_STATES`. Note the rail still needs all the other hardware conditions; this only manages the `ARM_PERMIT` term.

#### 17.4.5 The health-loss SAFETY TRIP

This is the critical safety branch and exists because of a real Codex-found defect: a mid-cycle heartbeat blip dropped arm while sweep was still latched, then the controller **silently re-armed with the stale latch**, causing uncommanded motion. The fix makes a health loss a **full software safety trip**:

When `link.health_ok()` is false (dead/stale heartbeat, `rp_ok:0`, or a latched firmware fault), `tick()`:

1. If this is the **transition** into unhealthy (`_was_healthy` was true), logs the loss (with `fault()`, `is_alive()`, `rp_ok()`) and calls **`self.fsm.power_restore()`**, which runs the FSM's all-motors-off (clearing the relay latches) and latches the FSM into **`MANUAL_INTERVENTION`**.
2. Sets `_was_healthy = False`.
3. **Drops arm** (`io.arm(False)`).
4. Still **drains the event queue** (`apply_events`) — the FSM ignores events when not `READY`, but this keeps the queue from growing unbounded.
5. Still **calls `fsm.poll()`** — *the Pi itself is alive, so it keeps kicking the NE555.* (If the Pi instead stalls, the kicks stop and the NE555 drops the rail — that is the separate Pi-watchdog path.)
6. **Returns** — none of the healthy-path steps run.

Recovery is **not automatic**: when the heartbeat returns OK, the FSM stays in `MANUAL_INTERVENTION` and arm stays low. Only a deliberate **PBZ (First-Ball-Zero)** — which both calls `fsm.first_ball_zero()` and sends the firmware a `CLEAR` — brings it back to `READY` and re-arms. The self-test (`--selftest`) explicitly verifies this whole sequence: mid-cycle `rp_ok:0` forces sweep OFF, latches `MANUAL_INTERVENTION`, drops arm; an OK heartbeat does **not** re-arm; and only PBZ recovers to `READY` + armed.

> **Why force motors off in software when the hardware rail already dropped?** Dropping the rail de-energizes the coils, but the *FSM's* output latches (and the MCP OLAT bits) would still say "sweep on." Without the software trip, the next re-arm would re-assert that stale latch the instant the rail came back. Forcing `all_motors_off()` clears those latches so recovery starts from a known-safe state. This is belt-and-suspenders on top of the hardware rail, not a replacement for it.

#### 17.4.6 `# CONFIRM` items in this file

The source flags these as bench/cutover-time decisions. They are **not** guesses to be trusted as-is:

| Item | Location | Status |
|---|---|---|
| Per-board I²C bus IDs | `BoardConfig.i2c_bus` / `DEFAULT_BOARDS` | (VERIFY: board-A=hw i2c-1, board-B=software "i2c-gpio" bus; the literal `3` is a placeholder.) |
| UART device per board | `uart_port` | (VERIFY: `/dev/ttyAMA0` / `/dev/ttyAMA1` are placeholders.) |
| Arm GPIO per board | `arm_pin` | (VERIFY: 26 / 13 are placeholders — confirm against Pi↔J1 wiring.) |
| Watchdog-kick GPIO per board | `wdog_pin` | (VERIFY: 12 / 6 are placeholders.) |
| Watchdog kick **waveform** | `_kick_wdog` | (VERIFY: toggle-per-poll vs a defined NE555 retrigger pulse — bench.) |
| Slow-input **debounce** | `_slow_edges` | (VERIFY: PBZ/BS/Foul rising-edge debounce strategy — bench.) |
| Slow-input **polarity** | the slow-input path generally | (VERIFY: per-channel active-high/low at cutover.) |

#### 17.4.7 `run()` — the scheduler and SIGTERM safe-off

```python
def run(boards, hz=50.0):
    period = 1.0 / hz
    ... install SIGTERM + SIGINT handlers that set stop["flag"] ...
    while not stop["flag"]:
        t0 = time.monotonic()
        for b in boards: b.tick()
        dt = time.monotonic() - t0
        if dt < period: time.sleep(period - dt)
    finally:
        for b in boards: b.safe_off()
```

- **Rate:** default **50 Hz** (`period = 1/hz`). Each pass ticks every board, then sleeps the remainder of the period (no sleep if the tick overran).
- **Signals:** `SIGTERM` and `SIGINT` both set the stop flag, so the loop exits cleanly at the next iteration boundary. This is the systemd-friendly shutdown path (matches the Pi-side `lane-node`/controller service model — see Section 15).
- **Safe-off on exit (the `finally`):** two things stop motion on shutdown. First, the loop exiting means **the kicks stop → the NE555 drops the rail** in hardware. Second, `safe_off()` is called on every board explicitly.

`BoardController.safe_off()` runs four steps, each guarded so one failure doesn't abort the rest:

1. `io.arm(False)` — drop arm.
2. `io.all_off()` (if present) — drive all outputs LOW / clear relay latches.
3. `link.stop_all()` — send `STOP *` to the firmware.
4. `link.close()` — close the serial port / stop the reader.

#### 17.4.8 `main()` and the off-hardware self-test

`main()` parses `--selftest` and `--hz`, sets up logging, and either runs `_selftest()` or constructs the **real-hardware** boards from `DEFAULT_BOARDS` and calls `run()`. `python controller_daemon.py --selftest` assembles everything in `sim` mode and drives a **full strike cycle entirely through `tick()`** (RP2040 events fed via `feed_line`, slow inputs via `io.slow[...]`), then exercises the mid-cycle health-loss safety trip and PBZ recovery described in §17.4.5. Exit code is `0` only if every check passes. This is the gate that proves the IO layer, the link, and the FSM assemble and interlock correctly off-Pi before any hardware exists.

---

### 17.5 How the three layers fit together (one tick, end to end)

For a healthy lane, one ~20 ms tick on the Pi does this:

1. The RP2040 has, asynchronously, debounced its cams/DIELL and pushed JSON events; `RP2040Link`'s reader thread parsed them and **queued** cam/ball events (and updated SC/TB + health under lock).
2. `BoardController.tick()` checks `link.health_ok()`. Assuming healthy:
3. `link.apply_events(fsm)` replays the queued cam/ball events into the FSM (`dispatch_cam` / `on_ball`).
4. `_slow_edges()` reads PBZ/BS/Foul off **MCP IN-A (0x20)** via `MachineIO.read_input` and fires `first_ball_zero+CLEAR` / `bin_full` / `on_foul` on a rising edge.
5. `fsm.poll()` advances the state machine; inside it, any relay change calls `MachineIO.set_*` → an **OUT-A (0x22)** bit write **and** a `RUN`/`STOP <motor>` to the firmware; `poll()` also calls `io.watchdog_kick()` → the daemon toggles the **NE555 kick GPIO**.
6. `io.arm(state not in DISARMED_STATES)` sets the **ARM_PERMIT** GPIO.
7. Meanwhile the FSM reads pin state via `MachineIO.read_grippers()` and calls `interlock_ok()`; on lanes 21/22 that default-off/default-true software model is unvalidated and adds no credited protection.

At no point can this software energize a board relay unless the implemented on-board
gates permit it. For S/T, correct Candidate-C insertion also leaves the OEM ladder
in series with each machine coil. The software's job is to drive the right outputs
and fail closed; G3, not `interlock_ok()`, proves the physical TB/SC path.

---

### 17.6 Cross-references

- **Section 3 — The AMF 82-70 Machine: Assemblies, Sequence of Operation & Cam Timing** — what the cams/relays/states *mean* mechanically; the FSM this IO layer drives.
- **Section 5 — Rev-B Controller Board: Overview, Domains & Isolation** — one board per lane; logic/field/output domains.
- **Section 6 — Rev-B Power Architecture** — the 3.3 V rail the MCP23017s and opto logic sides run on.
- **Section 7 — Rev-B Logic: RP2040 + MCP23017 + I²C** — the chips, addresses, and bus this software talks to.
- **Section 8 — Rev-B Field Inputs: PC817 Opto-isolators** — the active-low front-ends behind `INPUT_ACTIVE_LOW`.
- **Section 9 — Rev-B Machine Outputs: G5LE Relays** — the relays `OUT_A_MAP` drives (and the M1 DNP decision).
- **Section 10 — Rev-B Safety Hardware: NE555 Watchdog + Relay-Enable Rail** — implemented on-board gates plus Candidate-C OEM-ladder boundary.
- **Section 11 — Rev-B Connector Pinouts (J1–J14)** — `J_PI`/J1, `J_SAFETY`/J14 (controlled pins-1/2 jumper + currently OPEN/unlanded reserved external-source pins 3/4), `J_FAST_IN`/J3, `J_SLOW_IN_A`/J4.
- **Section 12 — Rev-B Channel Maps: RP2040 GPIO + MCP23017 Bit Maps** — the canonical channel/bit tables (`OUT_A_MAP`/`IN_A_MAP`/fast-input GPIO) this section mirrors.
- **Section 14 — Machine Interface: C1/C2A Connectors & the Adapter Harness** — where each signal lands on the machine, and the exact LCSC part numbers.
- **Section 21 — Cutover Procedure (Track B)** — where the `# CONFIRM` bench items get nailed down.
- **Section 15 — RP2040 Firmware & Cam Timing** — the other side of the UART:
  fast-input board positions, the fail-safe `RP2040_OK` line, the motion max-run
  backstop, and v1.2.3's measured-cam enforcement paths, which remain OFF pending
  polarity capture and a new controlled release.
