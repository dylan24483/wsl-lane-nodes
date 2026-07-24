## 20. Operations: Network, Deployment, Build & Fab

This section is the operate-and-reproduce reference for the Phase 8 system as a whole:
how the running software is laid out across the network and how it is brought up,
followed by how the lane-controller PCB is generated, audited, and held behind its
fabrication-release gates from a bare repository checkout. It is written to be self-contained — an engineer with no
prior context should be able to (a) bring a node back online after a power event,
(b) re-point the fleet after a network change, and (c) verify the controlled fab
package without mistaking package generation for authorization to order.

Cross-references:
- Hardware topology and the FSM that consumes the I/O are covered in the controller
  sections; this section covers the *operational envelope* around them.
- The on-board GPIO/MCP/relay maps are reproduced here only where they bear on
  bring-up; the authoritative electrical contract is **§ (PCB Schematic Contract)**
  and `docs/phase8b_pcb_revB_spec.md`.

---

### 20.1 Runtime architecture at a glance

Phase 8 is a **one-server / N-node** system that runs *alongside* the existing
Westside Lanes Phase 4 stack — it does **not** replace any Phase 4 service. The two
stacks coexist on the same WSL-SRV host on non-overlapping ports.

| Role | Where it runs | Process / entry point | Listens on | Talks to |
|---|---|---|---|---|
| Lane-node server | WSL-SRV (Windows 11, production server) | `server/lane_node_server.py` | **WS `0.0.0.0:8765`** + **HTTP `0.0.0.0:8766`** | Pi nodes (WS), browsers (HTTP) |
| Lane node (daemon) | Raspberry Pi at the lane pair | `lane_node/lane_node.py` (systemd `lane-node.service`) | — (outbound WS client) | the server at `:8765`; local GPIO/camera |
| Scoring display / desk simulator | any LAN browser | served by the server | `http://<WSL-SRV>:8766/` | the server |
| Phase 4 ops API (separate stack) | WSL-SRV | `wsl_api.py` | `:5000` | proxies Phase 8 scoring via `localhost:8766` |
| Phase 4 analytics (separate stack) | WSL-SRV | `wsl_analytics_server.py` | `:5002` | — |

Key facts (all grounded in the live code):

- The server binds `0.0.0.0` on **8765 (WebSocket)** and **8766 (HTTP)**
  (`server/lane_node_server.py` — `serve(handle_node, "0.0.0.0", 8765)` and
  `HTTPServer(('0.0.0.0', 8766), HttpHandler)`). Those two ports are the entire
  server surface.
- The node is a **WebSocket client**: it dials *out* to the server, so the node
  needs no inbound firewall holes. One Pi controls **one pair** of lanes
  (`LANES = [21, 22]` in `lane_node.py`).
- The Phase 4 `wsl_api.py` reaches the Phase 8 score store through a
  `localhost:8766` proxy (so the Phase 8b score-read/correct path survives even
  when the server's external IP changes — see § 20.4).

> **Safety reminder (carried from the controller sections):** none of the software
> in this section is a safety device. The on-board rail gates watchdog + ARM +
> RP2040_OK/cam-stop + Stop/CIS; Candidate C closes J_SAFE1-2 with the controlled
> jumper and keeps the primary TB/SC guard in the OEM S/T coil ladder, proven per
> lane at G3. The default-off SC∧TB software model is unvalidated. See
> `docs/phase8b_pcb_revB_spec.md` § 4.

---

### 20.2 The Raspberry Pi lane node

#### 20.2.1 What it is

One Pi per lane pair. At startup it iterates `LANES` and instantiates `gpiozero`
devices per lane from the `LANE_GPIO` table, registers callbacks, opens (in camera
mode) a single shared T-Camera for both decks, and connects to the server over
WebSocket. The node forwards ball/foul/heartbeat events up and executes
open/close/reset/power/cycle commands coming down.

#### 20.2.2 Pi GPIO map (BCM numbering)

These are the **Pi header GPIOs** the daemon drives/reads directly via `gpiozero`
(`LANE_GPIO` + the board-level watchdog pin in `lane_node.py`). **This is distinct
from the RP2040 co-processor GPIO map** (§ 20.6.3) and from the MCP23017 bit maps
(§ 20.6.4) — three different parts, three different pin namespaces. Do not conflate
them.

| Function | Lane 21 (BCM) | Lane 22 (BCM) | gpiozero device | Notes |
|---|---|---|---|---|
| Foul-lamp input | 5 | 17 | `Button(pull_up=False, bounce=0.05)` | Named `BALL_DETECT` for back-compat; fires `FOUL_EVENT` |
| 2nd-ball-lamp input | 6 | 22 | `Button(pull_up=False, bounce=0.05)` | Wired, state-only (no callback yet) |
| Pinsetter cycle (out) | 24 | 27 | `LED` (momentary pulse) | Relay closes briefly |
| Pinsetter power (out) | 25 | 23 | `LED` (latched on/off) | Relay holds until told otherwise |
| DIELL left beam (in) | 13 | 19 | `Button(pull_up=False, bounce=0.02)` | Ball detect; `when_released` fires `BALL_EVENT` |
| DIELL right beam (in) | 16 | 20 | `Button(pull_up=False, bounce=0.02)` | Ball detect (second beam) |
| **Watchdog kick (out)** | **12 (board-level, not per-lane)** | | `LED` | One NE555 per PCB/pair; petted ~1 Hz |

Operating theory worth keeping in mind:

- **The actual ball is detected by the DIELL beams, not by `BALL_DETECT`.** The
  `BALL_DETECT`/`BALL2_DETECT` names are historical (foul/2nd-ball lamp inputs);
  the comment block in `lane_node.py` is explicit about this. When a DIELL beam
  releases, the daemon emits a `BALL_EVENT`.
- **`WATCHDOG_KICK_PIN = 12` is board-level**, not per-lane, because there is one
  NE555 monostable per PCB. `watchdog_kick_loop()` pulses it at ~1 Hz; the NE555
  drops the relay-coil rail (all relays open) if it is not pulsed at least every
  **~11 s**. On shutdown the daemon forces this pin **LOW** in `_cleanup_gpio()` —
  a retained-HIGH kick pin would keep the watchdog alive and defeat it. The
  separate `relay_cleanup.py` must also force GPIO 12 LOW on SIGKILL, and its
  `RELAY_PINS` must stay in sync with the cycle/power values above.

> **Pi GPIO is 3.3 V only.** Never wire a 5 V (or higher) machine signal to a Pi
> input. Field signals reach the Pi only through the PCB's opto front-ends
> (PC817 / RP2040 / MCP23017), never directly. Use button-to-GND with the pull
> configured in firmware; opto-isolate anything higher than 3.3 V.

#### 20.2.3 Scoring modes

`WSL_LANE_SCORING_MODE` (§ 20.3) selects how DIELL ball events turn into scores:

| Mode | DIELL behavior | Use when |
|---|---|---|
| `manual` *(default)* | Emits `BALL_EVENT` with `pin_mask=None`; the desk enters pins via `POST /api/lane/<N>/score` | The safe Phase 8a cutover default until the camera is calibrated |
| `camera` | After a ball, waits `WSL_LANE_CAMERA_SETTLE_S`, captures a frame off-loop (`asyncio.to_thread`), detects standing pins, emits `BALL_EVENT` with the `pin_mask` | Only after the T-Camera + `pin_detect.PIN_SPOTS` are calibrated against real frames |
| `disabled` | DIELL logged on the Pi, **no** message sent to the server | Bench-testing with no scoring side effects |

An unknown value falls back to `manual` with a warning. In `camera` mode with no
real camera/empty-reference present, the daemon emits "awaiting manual" rather than
fabricating pins — unless `WSL_LANE_CAMERA_STUB=1` is set (bench only; never on a
live lane).

#### 20.2.4 Protocol version

`PROTOCOL_VERSION = 2` (multi-lane `LANES`). v1 was single-lane (`LANE_ID`). The
server compares its own version on the `HELLO` handshake and logs a warning on
mismatch — it does not hard-fail, so a version skew is visible in the log, not in a
crash.

---

### 20.3 `WSL_LANE_*` environment variables

Every node-side knob is an environment variable, read in `lane_node/lane_node.py`
(and `lane_node/camera.py`). In production they are set on the systemd
`lane-node.service` via a drop-in (§ 20.5). This is the complete list.

| Variable | Default | Read in | Meaning |
|---|---|---|---|
| `WSL_LANE_SERVER_URL` | `ws://localhost:8765` | `lane_node.py` | The server WS URL. **Production must override this to the live WSL-SRV IP** (§ 20.4). |
| `WSL_LANE_NODE_ID` | **required** | `lane_node.py` | Stable production identity sent on `HELLO`; must equal `WSL_DIAG_SOURCE_ID` and the WSL-SRV topology manifest key. |
| `WSL_LANES` | **required** | `lane_node.py` | Exactly one consecutive odd/even physical pair, such as `21,22`. |
| `WSL_SCORING_NODE_TOKEN` | **required** | `lane_node.py` | Unique per-Pi HELLO credential; its server map key must equal `WSL_LANE_NODE_ID`. Never reuse `LANE_NODE_TOKEN`. |
| `WSL_LANE_SCORING_MODE` | `manual` | `lane_node.py` | `camera` \| `manual` \| `disabled` (§ 20.2.3). |
| `WSL_LANE_CAMERA_SETTLE_S` | `2.5` | `camera.py` | Seconds after DIELL before grabbing the frame (let pins stop rocking, before the sweep clears them). |
| `WSL_LANE_CAMERA_DEVICE` | `0` | `camera.py` | Capture device index → `/dev/videoN`. |
| `WSL_LANE_EMPTY_REF` | *(path)* | `camera.py` | Path to the captured empty-deck reference frame the detector diffs against. |
| `WSL_LANE_CAMERA_STUB` | `0` | `lane_node.py` | `1` = rotate synthetic masks (bench only; never on a live lane). |

> The URL and scoring-mode defaults are for a bench only. Physical identity and
> lane assignment have no fallback: missing/mismatched IDs or a non-pair
> `WSL_LANES` value stops Track-A before physical authority is enabled.

---

### 20.4 Network: the 2026-06-03 eero re-IP (READ THIS)

**On 2026-06-03 the shop router was replaced with an eero.** This changed the entire
subnet, and several facts in older docs are now wrong.

| Item | Old (DEAD) | Current |
|---|---|---|
| Subnet / mask | `192.168.86.0/24` | **`192.168.4.0/22`** (mask `255.255.252.0`) |
| Gateway + DNS | `192.168.86.1` | **`192.168.4.1`** |
| **WSL-SRV address** | **`192.168.86.36` (static — now DEAD)** | **`192.168.4.103`** (DHCP lease) |
| WSL-SRV NIC | static | DHCP (interface idx 5, MAC `10-B6-76-51-EC-5D`) |

What happened: WSL-SRV's stale static `192.168.86.36` left it islanded under the new
eero subnet (no gateway → no internet, unreachable, AnyDesk down). The fix was to
revert the WSL-SRV Ethernet NIC from static to DHCP; it leased `192.168.4.103` and
came back. **No code changes were needed** — `wsl_api`, analytics, and
`lane_node_server` all bind `0.0.0.0`, and the Phase 4→Phase 8 proxy uses
`localhost:8766`.

**Decision (Dylan):** track the eero subnet and re-IP the fleet — do **not**
reconfigure the eero back to the old `192.168.86.0/24`.

**Open TODOs (not yet done — treat any `.86.x` address in any doc as stale):**

1. **Reserve `192.168.4.103`** for MAC `10-B6-76-51-EC-5D` on the eero (app → device
   → Reserve IP) so the DHCP lease can't drift. The NIC stays on DHCP. **Until this
   reservation exists, the WSL-SRV address can move again** — always confirm the
   current IP before a go-live and set `WSL_LANE_SERVER_URL` to match.
2. **Re-point every client** still dialing `192.168.86.36` → `192.168.4.103`, and
   confirm each client is itself on `.4.x`:
   - Pi lane node: `WSL_LANE_SERVER_URL` in
     `/etc/systemd/system/lane-node.service.d/override.conf` (port `:8765`).
   - Display/kiosk: the scoring-display URL (port `:8766`).
   - Desk / POS / KDS bookmarks (`:5000`) and analytics (`:5002`).

> **Stale-doc warning (updated 2026-06-10):** `HANDOFF.md`, the `phase_8a_*` docs, the
> deploy doc in § 20.5, and the Track-A go-live runbook have been corrected to
> `.4.103` (or banner-annotated where historical) in the 2026-06-10 doc sweep, but
> several memories and any docx/PDF exports still cite `192.168.86.36`. When you see
> `.86.36` anywhere, mentally substitute the current reserved WSL-SRV IP. The old `.71.x` ETHost bridge stays dead (BACKOFFICE1 `.86.31`
> is also islanded) — acceptable per the subnet-retirement plan.

---

### 20.5 Server deployment + the systemd lane-node service

#### 20.5.1 Server deployment to WSL-SRV (summary)

The full procedure is `docs/deploy_server_to_wsl_srv.md`. The shape of it:

1. **Get the code onto WSL-SRV.** Either `git clone https://github.com/dylan24483/wsl-lane-nodes.git`
   into `C:\QDesk\` (HTTPS read-only; the repo was made public for deploy), or
   AnyDesk file-transfer the laptop folder into `C:\QDesk\wsl-lane-nodes\`. WSL-SRV
   has no git/SSH key for GitHub.
2. **Python venv + deps.** `py -3 -m venv .venv`, activate, `pip install websockets`.
   The server needs only `websockets` (plus built-in `sqlite3` and `http.server`);
   the Pi-only packages (`gpiozero`, `lgpio`, …) are **not** needed on the server. If
   WSL-SRV has no outbound 443, transfer the `websockets` wheel via AnyDesk and
   `pip install <wheel>`.
3. **Smoke test.** `python server\lane_node_server.py` should print the
   HTTP + WS listen lines and "No saved state found … starting fresh", and
   `http://<WSL-SRV>:8766/` should load the desk simulator. If the browser can't
   reach it, add a Windows Defender Firewall inbound rule for **8765-8766**.
4. **Point the Pi at WSL-SRV** by setting `WSL_LANE_SERVER_URL` (§ 20.3, § 20.5.2).
5. **Auto-start (production):** wrap the server as a Windows service. The repo doc
   suggests **Task Scheduler** (run `…\.venv\Scripts\python.exe …\server\lane_node_server.py`
   at boot, restart-on-failure) or **NSSM**. Per the deployment-progress memory the
   live server currently runs on WSL-SRV via **Task Scheduler**.

> **Windows Task Scheduler trap (from the Phase 4 side, applies here):** the
> `:5000`/`:5002` scheduled tasks were auto-killed every 3 days by a default
> `PT72H` `ExecutionTimeLimit` (fixed to `PT0S`). If you create a Task Scheduler
> entry for `lane_node_server.py`, set `ExecutionTimeLimit` to `PT0S` (run
> indefinitely) and enable restart-on-failure.

The server's state lives in `<repo_root>/lane_state.db` (SQLite). Migrating
dev-server → WSL-SRV-server starts from a fresh empty DB; `cp lane_state.db` between
hosts only if score continuity matters (it does not for a clean cutover).

#### 20.5.2 The systemd `lane-node` service (Pi side) — MUST be enabled

On each Pi the daemon runs as a systemd service named **`lane-node.service`**.
Production environment overrides go in a drop-in:

```
/etc/systemd/system/lane-node.service.d/override.conf
```

Example drop-in (camera mode, pointed at the current WSL-SRV IP):

```ini
[Service]
Environment=WSL_LANE_SERVER_URL=ws://192.168.4.103:8765
Environment=WSL_LANE_SCORING_MODE=camera
Environment=WSL_LANE_CAMERA_SETTLE_S=2.5
# Environment=WSL_LANE_CAMERA_DEVICE=0   # set only if the dongle isn't /dev/video0
```

Apply changes:

```bash
sudo systemctl edit lane-node       # opens the drop-in
sudo systemctl daemon-reload        # after a hand-edit of the unit/drop-in
sudo systemctl restart lane-node
journalctl -u lane-node -f          # watch the log live
```

> **CRITICAL — the service MUST be `systemctl enable`d on every node.** A node can be
> *loaded* and *active* without being *enabled*. An enabled-less node survives only
> until the next reboot/power event, then comes up dead. This actually bit the bench
> rig: the service was loaded/active but not enabled, and survived 6 days only
> because the Pi hadn't rebooted. **Symptom of the bug: "the lane goes dark after any
> power event."** The production provisioning runbook must include:

```bash
sudo systemctl enable lane-node      # <-- the step that is easy to forget
sudo systemctl enable --now lane-node   # enable + start in one go
systemctl is-enabled lane-node       # verify: must print "enabled"
```

#### 20.5.3 Health checks and the end-to-end "is it alive" test

| Check | Command / action | Expect |
|---|---|---|
| Node connected (Pi log) | `journalctl -u lane-node -n 50` | `Connecting to ws://<WSL-SRV>:8765 …` then `Connected. Sending hello (lanes=[21, 22], protocol_version=2).` |
| Node registered (server log) | watch the server console / log | `New connection from (…)` then `Node '<id>' registered (lanes=[21, 22], protocol_version=2)` |
| Server up (HTTP) | `curl http://<WSL-SRV>:8766/api/health` | healthy response (also used for the overnight soak check) |
| Display | open `http://<WSL-SRV>:8766/display?lane=21` (and `?lane=22`) | scoring display loads and updates on a ball |
| Full chain | click "Open Lane" on lane 22 in the desk simulator | the lane's cycle relay clicks (bench: relay 1 clicks 3×) |

> **Camera-mode startup tell:** on restart you want `Camera ready for lanes [21, 22]
> (settle=2.5s).` If you instead see `Camera mode but detector NOT ready`, the empty
> reference didn't load — **the lane still runs, it just falls back to manual
> scoring.** Not dangerous; just not auto-scoring yet.

#### 20.5.4 Instant abort to manual

If detection is flaky, flip the node back to manual without any machine impact:

```bash
sudo systemctl edit lane-node   # change WSL_LANE_SCORING_MODE=camera → manual
sudo systemctl restart lane-node
```

Manual mode emits the ball event with no `pin_mask`; the desk scores via the
existing `/api/lane/<N>/score` flow. There is **no machine impact** either way —
scoring mode never changes what the controller does at the lane.

---

### 20.6 The lane-controller PCB — build & fab

This is the from-scratch reproduction path for the Phase 8b Rev-B board: one
identical four-layer PCB controls **one** lane; a lane pair uses two boards on one
Pi (the camera may be shared, but all machine-control wiring is per lane). The
board integrates what used to be discrete AEDIKO relay + AL-ZARD opto-input modules
into a single board with on-board PC817 optos, G5LE relays, three MCP23017
expanders, an RP2040 co-processor (hand-soldered Pico), an NE555 hardware watchdog,
and an isolated field-wetting DC/DC.

> **Board status:** **PCB-fab-ready** under a conservative DRC contract. It is **not**
> assembly/cutover-ready: relay-contact ratings, input population defaults
> (dry-contact vs 24 VAC sense), the TB/SC/Stop-CIS connector form, status-LED
> sizing, the M1 population decision, and on-hardware bench bring-up all still gate a
> *populated, live-machine* controller. See `docs/phase8b_pcb_revB_spec.md` § 11.

#### 20.6.1 Toolchain

| Tool | Version / path | Role |
|---|---|---|
| KiCad | **10.0** at `C:\Program Files\KiCad\10.0\` | Footprint library, `pcbnew` Python API, `kicad-cli.exe` |
| KiCad bundled Python | `C:\Program Files\KiCad\10.0\bin\python.exe` | **Must** run any script that `import pcbnew` |
| SKiDL | (in that Python env) | Netlist generation from `generate_kicad_netlist_revB.py` |
| FreeRouting | — | **Rejected for this board** (see below) |

Two hard toolchain rules, both load-bearing:

1. **Run board scripts with KiCad's bundled Python**, not the system Python — the
   `pcbnew` module only exists there. Scripts that only manipulate CSVs
   (`prepare_*`) run under the ordinary `sys.executable` and are invoked that way by
   the export driver.
2. **FreeRouting does not produce an acceptable board here.** Full-board autoroute
   attempts produced hundreds of DRC violations (4-layer = 473 violations + 3
   unconnected; F/B-only = 625 + 3), and re-band attempts produced no `.ses` after
   long runs. **Manual deterministic routing is the accepted path.** Do not "just
   autoroute it."

#### 20.6.2 The generate → place → netclass → route → export pipeline

All five scripts live in `scripts/`. They form an ordered, repeatable pipeline; the
artifacts each one writes are the input to the next.

| Step | Script | Run with | Reads → Writes |
|---|---|---|---|
| 1. Netlist | `generate_kicad_netlist_revB.py` | KiCad python | (SKiDL source) → `kicad/wsl-phase8b.net` |
| 2. Place | `place_components_revB.py` | KiCad python | netlist → `kicad/wsl-phase8b.kicad_pcb` (250×225 mm, 4-layer, domain bands) |
| 3. Net classes | `apply_netclasses_revB.py --write` | KiCad python | `…kicad_pcb` → same board with all named nets bound to one of 5 classes |
| 4. Route | `manual_route_revB.py` | KiCad python | `kicad/wsl-phase8b.kicad_pcb` → `kicad/wsl-phase8b.routed-manual.kicad_pcb` |
| 5. Export fab | `export_fab_revB.py` | KiCad python | `…routed-manual.kicad_pcb` → `kicad/fab_revB_routed_manual/…` (full package) |

Supporting scripts: `export_specctra_revB.py` (Specctra `.dsn` for any external
routing experiment) and the CSV preparers `prepare_pcba_parts_revB.py`,
`prepare_jlc_standard_pcba_revB.py`, `prepare_hand_solder_procurement_revB.py`
(invoked automatically by `export_fab_revB.py`).

**The five net classes** (assigned in step 3, enforced by the custom `.kicad_dru`
in step 4/5). These are the isolation backbone of the board; if they are not
actually assigned on the routed board, the `.dru` `hasNetclass()` isolation rules
become vacuous and a "0 violations" result is meaningless. The board carries
**184 named nets**, partitioned exactly as:

| Net class | Count | Trace width | Clearance | Carries |
|---|---:|---|---|---|
| `Logic_Signal` | 80 | 0.25 mm | 0.20 mm | Logic-side signals (UART, I2C, drive locals) |
| `Logic_Power` | 4 | 0.50 mm | 0.20 mm | VCC_5V / VCC_3V3 distribution |
| `Safety_Rail` | 13 | 0.60 mm | 0.30 mm | `RELAY_ENABLE_RAIL`, ARM/RP_OK/watchdog chain, `SAFE_*` |
| `Field_Sense` | 66 | 0.30 mm | 0.40 mm | Field side of every opto (machine-referenced) |
| `Machine_Output` | 21 | 0.50 mm | 0.35 mm (base) | Relay contact nets `OUT_*` |

Beyond the per-class base clearance, the custom rules enforce the *real* isolation
barriers: **LOGIC↔MACHINE ≥ 3.2 mm**, **LOGIC↔FIELD ≥ 2.5 mm**, and
**independent output-channel ≥ 1.5 mm**, sized conservatively for 250 VAC working
even though the measured field voltage is only ~24 VAC. (The current fab package
achieves isolation with copper spacing + all-layer keepouts only — there are **no
milled opto/relay slots**; slots are an optional future mechanical-hardening pass
that would require a re-DRC/re-export. A formal relaxation to 24 V numbers is a
later policy/DRC edit, not a topology change.)

#### 20.6.3 RP2040 co-processor pin map (KNOWN-CORRECT ANCHOR)

The RP2040 (a hand-soldered Raspberry Pi Pico, ref **A1**) owns the fast cam/ball
inputs and the rail-permission output. **The authoritative pin source is
`scripts/generate_kicad_netlist_revB.py` `block_rp2040()`, mirrored in
`firmware/rp2040/config.h`.** The GPIO column in
`docs/phase8_channel_allocation.md` is **STALE** (it assigns the fast inputs to
GP0-GP7) — **ignore it**; the as-built board uses **GP6..GP13**.

| Signal | GPIO | Pico phys. pin | Direction / sense | Function |
|---|---|---|---|---|
| `PI_UART_TX` (Pico RX) | GP1 | 2 | in (from Pi TX) | UART link to Pi |
| `PI_UART_RX` (Pico TX) | GP0 | 1 | out (to Pi RX) | UART link to Pi |
| **`RP2040_OK`** | **GP2** | 4 | out | Rail permission: **HIGH = permit motion, LOW = drop rail** |
| `SA` | GP6 | 9 | in, **active-low** | Sweep cam (270 run-through / 360 zero) |
| `SB` | GP7 | 10 | in, **active-low** | Sweep guard cam (66 guard / 186 table-spot init) |
| `SC` | GP8 | 11 | in, **active-low** | Sweep-under-table interlock window (86-243) |
| `TA1` | GP9 | 12 | in, **active-low** | Table cam (355 zero stop / 185 delay reset) |
| `TA2` | GP10 | 14 | in, **active-low** | Table cam (260 run-through / pin-latch) |
| `TB` | GP11 | 15 | in, **active-low** | Board position only; no independent lane-21/22 field lead |
| `DIELL_L` | GP12 | 16 | in, **active-low** | Ball detect, left beam (cushion SS trigger) |
| `DIELL_R` | GP13 | 17 | in, **active-low** | Ball detect, right beam |

Electrical sense (from `opto_input()`): every fast input is opto-isolated and
**active-low at the Pico** — machine contact closed pulls the GPIO LOW; idle is HIGH
through external `Rpu_*` to 3V3 (Rev-B 10 kΩ; current Rev-D/R5 **47 kΩ**).
Current firmware disables GP6–GP13 internal pulls. `RP2040_OK`/GP2 drives an NPN
in the relay-enable AND chain; a 100 k base pull-down makes the rail
**fail-safe-dead** whenever GP2 is Hi-Z (unpowered / in reset / pre-init). Current
controlled firmware identifies as `phase8b-rp2040 v1.2.3` and UART remains
`115200`; require the manifest-bound Rev-D identity, not the version string alone.

Firmware timing/backstop constants (`config.h`):

| Constant | Value | Purpose |
|---|---|---|
| `DEBOUNCE_CAM_US` | 2000 µs | Cam microswitch debounce (12 RPM machine → 2 ms ample) |
| `DEBOUNCE_DIELL_US` | 500 µs | Ball beam-break de-glitch |
| `BALL_LOCKOUT_MS` | 300 ms | One thrown ball → one ball event |
| `HB_INTERVAL_MS` | 250 ms | Heartbeat cadence to the Pi |
| `BOOT_SETTLE_MS` | 200 ms | `RP_OK` held LOW at least this long after boot before permit |
| `WDT_TIMEOUT_MS` | 250 ms | RP2040 internal watchdog: loop hang → chip reset → rail drop |
| `MAX_MOTION_MS` | 8000 ms | UART-independent cam timeout (matches `cycle_control_8270.MAX_MOTION_S = 8.0`); a guarded motor RUNNING longer latches a fault + drops `RP_OK`. BE and M are **not** guarded. |

#### 20.6.4 MCP23017 banks + on-board bit maps (KNOWN-CORRECT ANCHORS)

Three **MCP23017** expanders (**I2C** — *not* the SPI MCP23S17) handle the slow
inputs and the relay/lamp outputs, on the board's own I2C bus. Addresses and the
software bit maps are in `lane_node/controller_io.py`; the maps are kept in lockstep
with the netlist generator by a regression assert in that file's `__main__` (it
re-derives the maps from `OUTPUT_PINS`/`SLOW_INPUT_PINS` and fails on drift — this
caught the historical BS/OS, M1/M2, and strike/foul swaps).

| MCP role | I2C addr | A2A1A0 strap | Direction | Carries |
|---|---|---|---|---|
| IN-A | `0x20` | 0,0,0 | all inputs | Grippers GS1-10 + GP/OS/BS/PBZ/PBC/Foul |
| IN-B | `0x21` | 1,0,0 | all inputs | 10th-frame + manual + spare/AUX (configured, not yet read by the FSM) |
| OUT-A | `0x22` | 0,1,0 | all outputs | 7 relay-coil drives + 4 status-lamp LED drives |
| OUT-B | `0x23` | — | (outputs) | **Optional** physical pin lamps + neon; **omitted in baseline** (camera supplies pin state) |

> `(port, bit)`: port 0 = GPIOA (MCP pins 21-28 = GPA0-7), port 1 = GPIOB (MCP pins
> 1-8 = GPB0-7). Optos are **active-low at the MCP pin** (`INPUT_ACTIVE_LOW = True`):
> switch closed → pin reads 0.

**OUT-A output bit map** (`OUT_A_MAP`, chip `0x22`):

| Output | (port, bit) | Gen pin | Function | On safety rail? |
|---|---|---|---|---|
| `S` | (0, 0) | 21 | Sweep relay | yes |
| `T` | (0, 1) | 22 | Table relay | yes |
| `SP` | (0, 2) | 23 | Spot solenoid | yes |
| `BE` | (0, 3) | 24 | Back-end (future) | yes |
| `M` | (0, 4) | 25 | Master (future) | yes |
| `M2` | (0, 5) | 26 | Sweep reverse (M2 **before** M1 — per generator) | yes |
| `M1` | (0, 6) | 27 | Ball return — **DNP** | yes |
| `first_ball` | (0, 7) | 28 (`L_FIRST`) | 1st-ball lamp | no |
| `second_ball` | (1, 0) | 1 (`L_SECOND`) | 2nd-ball lamp | no |
| `strike` | (1, 1) | 2 (`L_STRIKE`) | strike lamp | no |
| `foul` | (1, 2) | 3 (`L_FOUL`) | foul lamp | no |

**IN-A slow-input bit map** (`IN_A_MAP`, chip `0x20`):

| Input | (port, bit) | Input | (port, bit) |
|---|---|---|---|
| GS1 | (0, 0) | GS6 | (0, 5) |
| GS2 | (0, 1) | GS7 | (0, 6) |
| GS3 | (0, 2) | GS8 | (0, 7) |
| GS4 | (0, 3) | GS9 | (1, 0) |
| GS5 | (0, 4) | GS10 | (1, 1) |
| GP | (1, 2) | OS | (1, 3) |
| BS | (1, 4) | PBZ | (1, 5) |
| PBC | (1, 6) | Foul | (1, 7) |

Motion relays (`MOTION_RELAYS = S, T, SP, BE, M, M1, M2`) get RUN/STOP forwarded to
the RP2040 over UART so the firmware's max-run backstop knows what is energized;
lamps are not motors and are not forwarded.

#### 20.6.5 Historical Rev-B JLCPCB Standard-PCBA order

> **HISTORICAL REV-B ONLY — DO NOT ORDER FROM THIS SECTION.** The current
> Rev-D/R5 immutable package is `kicad/fab_revD_2026-07-23_r5/`, with forty
> 47 kΩ `Rpu_*` parts and the binding internal-pulls-off runtime gate. The
> Rev-D board is **NO-GO and not authorized for upload or purchase** until the
> recorded sign-offs, JLC preview, first-article, FA-9, powered, and bench gates
> close. Never substitute these Rev-B files for the current package.

The historical Rev-B board flow used JLCPCB **Standard PCBA**: JLC fabricated the
bare 4-layer board *and* placed all SMD parts plus the through-hole PC817 optos and
G5LE relays (wave-soldered); a short list of parts was hand-soldered after the
boards arrived (§ 20.6.6).

**Historical Rev-B upload record** — that flow used the three files from
`kicad/fab_revB_routed_manual/JLC_UPLOAD_READY/` in this order:

| Historical order step | File | Role |
|---|---|---|
| 1 | `01_wsl-phase8b-revB_gerbers.zip` | the PCB Gerber/drill upload |
| 2 | choose **Standard PCBA**, assembly **top side only** | — |
| 3 | `02_wsl-phase8b-revB_BOM_JLC.csv` | BOM (20 part lines) |
| 4 | `03_wsl-phase8b-revB_CPL_JLC.csv` | position/CPL (174 placed designators) |
| 5 | `04_…_part-lock-audit.csv` | use during part-match review (audit only) |

> In that historical flow, the transport zip
> (`wsl-phase8b-revB-JLC_UPLOAD_READY.zip`) was not itself the Gerber input; the
> three files above were extracted from it. Files `05`/`06`/`07` were
> exclusion/hand-solder/harness audits, not order inputs.

**Historical Rev-B PCB settings** (record only; not current order instructions):

| Setting | Value |
|---|---|
| Layers | **4** |
| Dimensions | **250 mm × 225 mm** |
| Thickness | 1.6 mm |
| Material | FR-4 |
| Solder mask | green |
| Silkscreen | white |
| **Surface finish** | **ENIG** (lead-free) |
| Outer copper | 1 oz |
| Inner copper | 0.5 oz |
| Vias | standard through vias only |
| Castellated / impedance control / edge plating / panelization | no (panelize only if JLC requires it for assembly handling) |

**Historical Rev-B PCBA settings / placement contract** (the generator
`prepare_jlc_standard_pcba_revB.py` *aborts* unless these hold):

- JLC-placed refs: **174**. JLC BOM unique lines: **20**. Filtered CPL rows: **174**.
- Relay locked to **`C116963 / G5LE-14 5VDC`**; I/O expander locked to
  **`C47023 / MCP23017-E/SO`**. If either lock fails, the generator aborts.
- Hand-solder refs **excluded** from JLC placement (15 refs):
  **A1, J1-J11, J13, J14, U37.**
- Existing **DNP** refs stay excluded — the **M1** optional channel
  (J12/K7/Q7 + M1 support passives) is **not populated**.

**Historical Rev-B locked JLC part map** (the as-built `02_…_BOM_JLC.csv`; this
is authoritative only for Rev-B and must not be used for a Rev-D/R5 order):

| Comment (value) | Qty | Designators | LCSC # | MFR part | Footprint |
|---|---:|---|---|---|---|
| 100nF 50V X7R 0805 | 4 | C1,C2,C3,C12 | C49678 | CC0805KRX7R9BB104 | 0805 |
| 100µF 16V SMD aluminum electrolytic (D6.3×L5.4) | 1 | C11 | C19184134 | CK1C101M-CRE54 | CP_Elec_6.3x5.4 |
| 10nF 50V X7R 0805 | 1 | C13 | C17702767 | C0805B103K500NT | 0805 |
| 10µF 16V X5R 0805 | 1 | C14 | C89827 | CC0805KKX5R7BB106 | 0805 |
| 1N4148WS switching diode | 8 | D1,D3,D5,D7,D9,D11,D15,D16 | C118873 | 1N4148WS | SOD-323 |
| SS14 Schottky | 1 | D17 | C2480 | SS14 | SMA/DO-214AC |
| **G5LE-14 5VDC SPDT relay** (wave solder) | 6 | **K1-K6** | **C116963** | **G5LE-14 5VDC** | Omron G5LE-1 |
| MMBT3904 NPN BJT | 8 | Q1-Q6,Q15,Q16 | C909754 | MMBT3904 | SOT-23 |
| 2N7002 N-ch MOSFET | 4 | Q8,Q9,Q10,Q11 | C916396 | 2N7002 | SOT-23 |
| AO3400A N-ch logic MOSFET | 2 | Q12,Q13 | C20917 | AO3400A | SOT-23 |
| AO3401A P-ch MOSFET | 1 | Q14 | C347476 | AO3401A | SOT-23 |
| 4.7k 1% 0805 | 2 | R1,R2 | C17673 | 0805W8F4701T5E | 0805 |
| 2.2k 1% 0805 | 32 | R3..R65 (odd) | C17520 | 0805W8F2201T5E | 0805 |
| 10k 1% 0805 | 37 | R4..R66 (even) + R101-R109 | C17414 | 0805W8F1002T5E | 0805 (historical Rev-B; its 32 `Rpu_*` refs are 47 kΩ in Rev-D/R5) |
| 1k 1% 0805 | 12 | R67..R104 (subset) | C17513 | 0805W8F1001T5E | 0805 |
| 100k 1% 0805 | 14 | R68..R110 (subset) | C149504 | 0805W8F1003T5E | 0805 |
| 330R 1% 0805 | 4 | R90,R93,R96,R99 | C17630 | 0805W8F3300T5E | 0805 |
| **MCP23017 I2C I/O expander** | 3 | **U1,U2,U3** | **C47023** | **MCP23017-E/SO** | SOIC-28W |
| **PC817B optocoupler** (DIP-4, wave solder) | 32 | **U4-U35** | **C5692981** | **PC817B** | DIP-4 W7.62mm |
| **NE555 bipolar timer** | 1 | **U36** | **C7593** | **NE555DR** | SOIC-8 |

> The `00_README_UPLOAD.txt` inside the upload folder restates the four critical
> part-match checks (K1-K6 relay coil = 5 VDC; the three MCP23017s = I2C, not
> MCP23S17; U4-U35 = PC817B DIP-4; U36 = NE555DR). The README's designator
> *examples* for the MCP/NE555 (U33-U35/U36) reflect an earlier numbering; **the
> authoritative current designators are in the BOM CSV above (U1-U3 / U36)** — trust
> the CSV.

**Historical Rev-B preview checks** (record only; not authorization to upload or pay):

- Relay row is `C116963 / G5LE-14 5VDC` — **reject any 9 V / 12 V / 24 V coil
  substitution.** The coil is **5 VDC**, not 12/24 V.
- I/O expander row is `C47023 / MCP23017-E/SO` — **reject MCP23S17** (SPI).
- PC817 row is `C5692981 / PC817B`, DIP-4 / through-hole / wave solder.
- NE555 row is `C7593 / NE555DR` (bipolar 555 — don't silently swap a CMOS/TLC555,
  the watchdog timing assumes bipolar behavior).
- C11 electrolytic polarity matches the board; all PC817 and all G5LE orientations
  match the board preview.
- **No** A1, J1-J11, J13, J14, U37 refs appear in the JLC placement list; J12, K7,
  Q7, and the M1 support passives remain unpopulated.
- Board outline is 250 × 225 mm with four mounting holes visible.

**If JLC rejects a through-hole part** (no redesign needed): move U4-U35 (PC817)
and/or K1-K6 (G5LE) from JLC placement to the hand-solder BOM and assemble them by
hand; the PCB is unchanged. If C11's part/polarity is questionable, pick another
100 µF/16 V SMD electrolytic matching the `6.3×5.4` footprint and re-run the BOM
generator after updating the part lock.

#### 20.6.6 Hand-soldered parts (installed after the assembled boards arrive)

These refs stay on the board but are omitted from the JLC placement BOM/CPL and are
installed at the bench. Procurement lists:
`assembly/wsl-phase8b-revB-hand-solder-bom.csv` and
`…-harness-mating-parts.csv`.

| Ref(s) | Part | Notes |
|---|---|---|
| **A1** | **Raspberry Pi Pico** (RP2040 module), SC0915 | JLC may not place the castellated module; assume it arrives **unprogrammed** unless programming is explicitly quoted. |
| **J1** | Pi IDC/header (2×10) | Candidate pending final body/keying/pin-1 verification against the board + cable plan. |
| **J2-J11, J13, J14** | **Phoenix / terminal connectors** (MKDS 5.08 mm + MCV 3.5 mm headers) | Most board-side Phoenix parts are locked; verify wire-entry direction against the board render before ordering. |
| **U37** | **TRACO TMA-0505S** isolated DC/DC (5 V→5 V) | Supplies the isolated field-wetting rail. Treat as exact or pinout-audited substitute only — verify isolation rating, output current, SIP pinout, body clearance. |

`J12` is already DNP and is **not** part of the hand-solder set. The 3.5 mm MCV
headers need matching off-board mating plugs (for J3, J4, J5, J13, J14); those plugs
are not PCB placements and are listed in
`assembly/wsl-phase8b-revB-offboard-hardware.csv` /
`…-harness-mating-parts.csv`. After installing the hand-solder parts, do a
continuity/visual inspection **before applying power**.

#### 20.6.7 The DRC + topology audit gate (`audit_revB_board.py`)

The fab export is **gated**: `export_fab_revB.py` will not produce a package unless
both of these pass, and it re-runs both *inside* the export so the gate cannot be
bypassed:

1. **KiCad DRC** (`kicad-cli pcb drc --severity-all`) must report exactly:
   `Found 0 DRC violations`, `Found 0 unconnected pads`, `Found 0 Footprint errors`.
   A missing line aborts the export.
2. **`scripts/audit_revB_board.py`** must print `AUDIT RESULT: ALL PASS`.

**Why a separate audit when DRC already passed:** KiCad DRC proves geometry but
**not** that the net classes are actually assigned, that the safety rail truly
reaches every coil, or that no machine output ever touches the Pico. The audit
checks exactly the things DRC cannot — it verifies against the *live board file*,
not the DRC report (the Claude↔Codex review loop caught a "false-green" route where
the routed `.kicad_pro` had lost its netclass assignments, making the `.dru`
`hasNetclass()` rules inert and "0 violations" meaningless). The audit asserts:

| Audit check | What it proves |
|---|---|
| 5 net classes assigned with exact counts `{Logic_Signal:80, Logic_Power:4, Safety_Rail:13, Field_Sense:66, Machine_Output:21}` | The `.dru` isolation rules are *not* vacuous |
| No named net fell to `Default`; zero anonymous `N$` nets | Every net is policy-classified |
| `RELAY_ENABLE_RAIL` reaches **7** relay coils (`K*`) **+** a pass-FET (`Q*`) | The safety rail enables every motion relay incl. M1 DNP |
| **No `OUT_*` net touches the Pico** | Machine output can't reach the logic MCU |
| `GND` and `FIELD_GND` both present **and distinct** | Field isolation barrier intact |
| `SAFE_STOP_RETURN` + `SAFE_TBSC_RETURN` + `RAIL_GATE` present | Interlock loops are first-class rail conditions |
| Netted copper zones filled; ≥ 2 isolation keepout rule-areas present | Power planes poured + barrier keepouts exist |
| ≥ 8 DNP footprints | The M1 optional channel is still DNP |

Run the audit standalone with KiCad's Python:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\audit_revB_board.py kicad\wsl-phase8b.routed-manual.kicad_pcb
```

#### 20.6.8 Historical Rev-B fab-package regeneration

This was the Rev-B regeneration command after a Rev-B board edit. It re-ran the
DRC + audit gate, re-exported gerbers/drill/CPL/PDF/IPC-D-356/stats, regenerated
the BOM/CPL CSV variants, rebuilt the old upload-ready folder, and wrote a
`manifest.json` with SHA-256s. **Do not run it to create, replace, or authorize a
Rev-D package:**

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" scripts\export_fab_revB.py
```

Output lands in `kicad/fab_revB_routed_manual/`. The package gate also checks that
at least one Excellon `.drl` and ≥ 11 Gerber layer files were produced, that the
JLC upload pair exists, and (again) DRC `0/0/0` + audit `ALL PASS`. The package is
**historical Rev-B fab-ready, not cutover-ready**. Current live-machine gates still
include v1.2.3 first-article/on-hardware bring-up and a new controlled release with
only measured cam polarities enabled; stock measured-cam flags remain OFF.

---

### 20.7 Per-pair field deployment (infrastructure)

For physically installing a node at a lane pair, the procurement BOM + install
procedure is `docs/phase_8a_infrastructure_plan.md`. The shape:

- **Network:** one managed **PoE+** switch (planned baseline: TP-Link TL-SG2428P,
  24×PoE+) in the existing closet, one Cat6 run per pair, a single subnet/VLAN. The
  Pi nodes are first-class LAN citizens (they ping WSL-SRV directly). The plan's IP
  block and the `192.168.86.x` topology diagram are **pre-eero and now stale** —
  re-read § 20.4 for the live subnet (`192.168.4.0/22`) before assigning addresses.
- **Power:** **PoE+** to the Pi via a PoE+ HAT (official RPi PoE+ HAT recommended);
  the HAT's 5 V feeds the Pi and the board's logic rail. PoE+ wins on TCO because
  there is no AC outlet at the equipment area today.
- **Enclosure:** a DIN-rail enclosure (Hammond 1597BSGY baseline) with a window over
  the indicator-LED zone (watchdog "WD", power "PWR", Pi status), and cable glands
  for Cat6 + the machine wire bundle.
- **Sequence:** pre-install survey → infrastructure install (cabling + switch +
  enclosure, **no** machine wiring) → 24 h soak → cutover visit. The cutover plan
  (`docs/phase_8a_cutover_plan.md`) depends on this infrastructure being in place
  first.

> Per-pair material cost runs ~$285; shared one-time infrastructure ~$785; full
> 16-pair rollout ~$5,050 — roughly $11k cheaper than refurbishing the EOL
> QubicaAMF hardware, and with lifetime parts independence.

---

### 20.8 Operations quick reference

| I need to… | Do this |
|---|---|
| Find the current server IP | It's a DHCP lease on WSL-SRV (MAC `10-B6-76-51-EC-5D`). **Confirm on the eero; reservation is still TODO.** As of 2026-06-03: `192.168.4.103`. |
| Bring a dark node back | `journalctl -u lane-node -n 50`; verify `systemctl is-enabled lane-node` says **enabled**; check `WSL_LANE_SERVER_URL` in the drop-in points at the live IP. |
| Re-point a node after a network change | `sudo systemctl edit lane-node` → set `WSL_LANE_SERVER_URL=ws://<new-IP>:8765` → `daemon-reload` → `restart`. |
| Stop auto-scoring now | `systemctl edit lane-node` → `WSL_LANE_SCORING_MODE=manual` → `restart`. No machine impact. |
| Check the server is up | `curl http://<WSL-SRV>:8766/api/health`. |
| Open the scoring display | `http://<WSL-SRV>:8766/display?lane=21` (and `?lane=22`). |
| Verify the current fab package | Use the immutable `kicad/fab_revD_2026-07-23_r5/` manifest and README; do not regenerate or substitute a Rev-B package. |
| Order the board | **NO-GO. Do not upload or purchase** until every current Rev-D release gate closes; then use only the approved R5 package and its recorded JLC preview. |
| Verify the on-board pin maps before trusting hardware | Run `controller_io.py` as a script (KiCad python not needed) — its `__main__` asserts `OUT_A_MAP`/`IN_A_MAP` match the netlist generator and fails on drift. |
