# Phase 8 — Raspberry Pi Lane-Node Provisioning

**Status:** prep doc, 2026-06-04. Brings a fresh Pi image to either role: a
Track-A / Phase-8a scoring pilot Pi (`lane_node.py`, safe to enable now) **or** a
Track-B controller-only bench/cutover Pi (`controller_daemon.py`, **bench-gated —
enable only after spec §12.9 validation**). These services are mutually exclusive
until the unified scoring+control node exists (§7). One controller Pi serves one
lane **pair**; the controller drives two identical boards (one per lane) on **two
independent I²C buses + two UARTs**.

> Why this doc exists: `controller_daemon.DEFAULT_BOARDS` names `/dev/i2c-3` and a
> second UART. **Those devices do not exist until the boot overlays below are
> applied.** This is the connective tissue between the daemon's pin plan and a Pi
> that actually has those buses.

---

## 1. Base OS
- Raspberry Pi OS (Bookworm or later), 64-bit. Pi 4 or 5 (needs ≥2 hardware UARTs for the per-board RP2040 links).
- `sudo apt update && sudo apt full-upgrade`, set hostname (e.g. `lane-21-22`), enable SSH.
- User `pi`, home `/home/pi` (the unit files assume this).

## 2. Boot interfaces — `config.txt` (the part that makes the devices exist)
Edit `/boot/firmware/config.txt` (older Pi OS: `/boot/config.txt`):

```ini
# --- I2C bus-1 -> board-21's 3x MCP23017 (0x20/0x21/0x22)  [FIRM] ---
dtparam=i2c_arm=on

# --- 2nd I2C bus -> board-22's MCP23017s (software/bit-banged)  [CONFIRM pins] ---
# Pick two FREE GPIOs not already used by THIS controller (avoid 2,3,6,12,13,14,15,16,23,24,25,26).
# NOTE: this is a controller-only Pi — it does NOT coexist with the live Track-A node (see §7).
dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=20,i2c_gpio_scl=21,i2c_gpio_delay_us=2

# --- UART0 -> board-21 RP2040 (primary PL011 -> /dev/ttyAMA0)  [FIRM*] ---
enable_uart=1

# --- 2nd UART -> board-22 RP2040 (Pi 4/5 extra PL011)  [CONFIRM device name] ---
dtoverlay=uart3        # GPIO4=TXD3 / GPIO5=RXD3   (or uart4 = GPIO8/9, etc.)
```

**Disable the serial login console on the board-21 UART** or a `getty` will fight the
RP2040 protocol on `/dev/ttyAMA0`:
- `sudo raspi-config` → *Interface Options* → *Serial Port* → login shell **NO**, hardware **YES**, **or**
- `sudo systemctl disable --now serial-getty@ttyAMA0.service` and remove `console=serial0,115200` from `/boot/firmware/cmdline.txt`.

Reboot, then confirm in §6.

\* `ttyAMA0` is the primary UART, but device-name mapping can shuffle once overlays are
added — **verify the actual names and set `uart_port` in `DEFAULT_BOARDS` to match.**

## 3. Pin plan (controller-internal) — set `controller_daemon.DEFAULT_BOARDS` to the *confirmed* values

> ⚠️ **Deconflicted among the controller's OWN functions only — NOT compatible with the live Track-A `lane_node.py` on the same Pi.** The two GPIO maps overlap on **5, 6, 12, 13, 16, 20, 23, 24, 25** (see §7), and that overlap includes scoring *input* pins (DIELL/foul/ball2), not just cycle/power. Use this plan on a **controller-only Pi** (the bench Pi now, or a post-cutover unified node). `lane-node-controller.service` enforces the exclusion with `Conflicts=lane-node.service`.

Source of truth: `phase8_channel_allocation.md` §4. **FIRM** = settled; **CONFIRM** = verify on the wired Pi at bench bring-up.

| BCM GPIO | Function | Board | Confidence |
|---|---|---|---|
| 2, 3 | I²C bus-1 SDA/SCL → MCPs 0x20/0x21/0x22 | 21 | **FIRM** |
| 14, 15 | UART0 TXD/RXD → `/dev/ttyAMA0` (RP2040) | 21 | FIRM\* |
| 12 | NE555 watchdog kick | 21 | **FIRM** (existing bench-validated pin) |
| 26 | relay-enable ARM | 21 | CONFIRM (planned free pin) |
| 23, 24 | IN-A/IN-B MCP change-INT | 21 | reserved/unused† |
| 20, 21 | I²C bus-3 SDA/SCL (`i2c-gpio`) → MCPs | 22 | **CONFIRM** (pins TBD) |
| 4, 5 | UART3 TXD/RXD → `/dev/ttyAMA1` (RP2040) | 22 | **CONFIRM** (overlay + name) |
| 6 | NE555 watchdog kick | 22 | CONFIRM (per-board kick) |
| 13 | relay-enable ARM | 22 | CONFIRM (planned free pin) |
| 25, 16 | IN-A/IN-B MCP change-INT | 22 | reserved/unused† |

† The daemon currently **polls** slow inputs at ~50 Hz, so the MCP INT lines aren't
wired into it yet — they're reserved in the budget for a future IRQ optimization.

## 4. Repo + venv + deps
```bash
git clone https://github.com/dylan24483/wsl-lane-nodes /home/pi/wsl-lane-nodes
cd /home/pi/wsl-lane-nodes
python3 -m venv .venv
.venv/bin/pip install -r requirements-lane-node.txt    # focused pinned set
# no-hardware sanity check of the controller assembly:
.venv/bin/python3 lane_node/controller_daemon.py --selftest   # expect 22/22
```

## 5. Install the services
Both unit files live in `systemd/`. Copy to the system dir and reload:
```bash
sudo cp systemd/lane-node.service            /etc/systemd/system/
sudo cp systemd/lane-node-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
```

- **Track-A / Phase-8a pilot service (`lane-node`):** the camera *scoring* is read-only, **but this service also carries the Phase-8a remote cycle/power relay outputs** — it can pulse the machine on desk/server command (`lane_node.py` `pulse()`), so it is **not** purely read-only. Enable it on a **scoring Pi** (not one also running the controller — see §7):
  ```bash
  sudo systemctl enable --now lane-node
  ```
- **Track-B controller — DO NOT ENABLE until spec §12.9 bench validation passes.**
  It DRIVES THE PINSETTER. Provision the file (done above) but leave it disabled.
  After validation: `sudo systemctl enable --now lane-node-controller`.
  **TODO (one-board bench Pi / D3):** the unit's stock `ExecStart` runs BOTH boards — add `--lanes 21` to `ExecStart` (or a drop-in with `Environment=WSL_LANES=21`) so the absent board-22 I²C bus/UART is never opened.

> ⚠️ **The `systemctl enable` trap (learned the hard way):** `enable` is what survives
> a reboot/power-event. A unit that's only `start`ed (active but not enabled) comes
> back **dead** after the next power blip → "the lane goes dark after a power event."
> Always `enable`, and verify with `systemctl is-enabled` (§6) — not just `is-active`.

## 6. Verify
```bash
i2cdetect -y 1            # board-21 bus: expect 20 21 22
i2cdetect -y 3            # board-22 bus (i2c-gpio): expect 20 21 22
ls -l /dev/ttyAMA*        # both RP2040 UARTs present -> set uart_port to match
systemctl is-enabled lane-node     # -> enabled  (MUST say enabled, not just active)
journalctl -u lane-node -f         # scoring node logs (DIELL/score/WS)
```

## 7. Coexistence with the Track-A pilot — they CANNOT share a Pi yet
`lane_node.py` (the live Track-A / Phase-8a pilot) claims a **fixed GPIO set** for its per-lane I/O (`LANE_GPIO`, `WATCHDOG_KICK_PIN`):

- **inputs:** foul (L21 **5**, L22 **17**), ball2 (L21 **6**, L22 **22**), DIELL-L (L21 **13**, L22 **19**), DIELL-R (L21 **16**, L22 **20**)
- **outputs:** cycle (L21 **24**, L22 **27**), power (L21 **25**, L22 **23**); watchdog kick **12**

This controller pin plan **overlaps that set on GPIO 5, 6, 12, 13, 16, 20, 23, 24, 25** — and the overlap includes scoring **input** pins (DIELL/foul/ball2), not just the cycle/power outputs. So the two **cannot run on the same Pi** with these maps. Resolution:

- Run the controller daemon only on a **controller-only Pi**: the **bench Pi** (spare cabinet) now, or a **post-cutover unified node** later.
- `lane-node-controller.service` carries **`Conflicts=lane-node.service`** so systemd refuses to run both at once.
- The end state is a **unified scoring+control node** (the `TODO(server)` in `controller_daemon.py`): once the board reads DIELL/foul through the RP2040/opto front-ends and the controller drives cycle/power through the relays, `lane_node.py`'s **direct-GPIO machine I/O retires entirely**, freeing those pins. Until that unification is built, treat the controller pin plan as **bench-Pi-only**.

> **Correction (2026-06-04, Codex audit):** earlier drafts of this doc called the plan "deconflicted" and said Track-A scoring inputs could "stay" on the same Pi. That was wrong — the scoring input pins collide too. The plan is deconflicted *internally*, not against the live Track-A node.

## 8. Per-Pi environment file — `/etc/wsl-lane-node.env` (R2-9, 2026-07-21)

Both units require `EnvironmentFile=/etc/wsl-lane-node.env`. **The default
deployment ships the HTTP diagnostics leg configured — JSONL-only is a
degraded mode, not the norm** (Codex round-2 R2-9): without
`WSL_DIAG_SERVER_URL` + `LANE_NODE_TOKEN` every diagnostics event stays on
the SD card and nothing reaches the :8766 machine_events store, the desk, or
mechanic SMS.

```bash
sudo cp systemd/wsl-lane-node.env.example /etc/wsl-lane-node.env
sudo chmod 600 /etc/wsl-lane-node.env    # it carries the lane token
sudo nano /etc/wsl-lane-node.env         # set at minimum:
#   WSL_DIAG_SERVER_URL=http://192.168.4.103:8766
#   LANE_NODE_TOKEN=<the server's token>
#   WSL_SCORING_NODE_TOKEN=<unique random secret for this Pi>
#   WSL_LANE_NODE_ID=pi-lane21-22
#   WSL_LANES=21,22
#   WSL_DIAG_SOURCE_ID=pi-lane21-22       # MUST equal WSL_LANE_NODE_ID
#   WSL_BOARD_REVS=21=revD,22=revD       # REQUIRED for the controller
#   WSL_RP2040_BUILD_ALLOWLIST=<release manifest build_id>
#   WSL_RP2040_CFG_ALLOWLIST=<release manifest config hash>
#   WSL_RP2040_UIDS=21=<Pico UID>,22=<Pico UID>
sudo systemctl daemon-reload
sudo systemctl restart lane-node         # or lane-node-controller
```

Verify after restart:

```bash
journalctl -u lane-node-controller -n 20   # expect "board_rev=revD" per lane,
                                           # NOT "UNPROVISIONED (will be refused)"
ls ~/wsl-lane-nodes/diag_logs/outbox_cursor.json   # outbox cursor advancing
curl -s http://192.168.4.103:8766/api/machine/health | head   # events landing
```

**R2-6 note:** the controller daemon has **no default board revision** — a
lane without `WSL_BOARD_REVS` (or `--board-revs`) is refused at startup and
skipped fail-safe (never ticked, NE555 never kicked, rail stays down). This
is deliberate: a silent `revC` default would swallow every AUX4-11 role on a
rev-D board with zero log lines.

**Rev-D identity note:** a declared board revision is not sufficient to ARM.
The controller requires the live firmware `id.build` and `id.cfg` to match the
two release allowlists above. The fleet also pins each Pico UID to its lane;
enroll those UIDs during the controlled bench flash and keep the same mapping
in WSL-SRV's machine-scoped environment. A missing/mismatched identity is
reported as `DEGRADED` and the Rev-D controller remains disarmed.

**R2-12 note:** events ship via the JSONL outbox (`diag_events.OutboxReplayer`)
with a persisted cursor advanced only on a 2xx ack; the server dedupes on
`(source_id, boot_id, seq)`, so outages/drops replay idempotently. Keep
`WSL_LANE_NODE_ID` and `WSL_DIAG_SOURCE_ID` identical and stable across
re-images. Track-A refuses to start if the identity is absent/development-like,
the IDs disagree, or `WSL_LANES` is not one consecutive odd/even pair.

On WSL-SRV, the same release must set
`WSL_SCORING_NODE_TOPOLOGY=pi-lane21-22=21,22` (extend with
`;pi-lane23-24=23,24` as pairs are enrolled). Its lane union must exactly match
`WSL_MACHINE_LANES`; a missing/malformed manifest, an unexpected HELLO, a
partial pair, a duplicate live node, or an overlapping claimant disables
physical command authority and turns machine health red.
Set `WSL_SCORING_NODE_TOKENS=pi-lane21-22=<that Pi's unique secret>` on
WSL-SRV. Its key set must exactly match the topology. Never write token values
to logs, reports, or the release manifest.

## 9. Wall-clock anomaly recovery

Wall-clock rollback latches command refusal durably on each Pi, WSL-SRV, and
the WSL bridge. Never clear only one layer.

1. Stop `lane-node.service` on every affected Pi and confirm it is inactive.
2. Restore NTP and require `timedatectl show -p NTPSynchronized --value` to
   print `yes`.
3. Run `sudo .venv/bin/python3 lane_node/reset_clock_guard.py --actor-id <id>
   --note "<ticket and NTP evidence>"` on each Pi. The helper refuses non-Linux,
   an active service, or unsynchronized time and appends an audit record.
4. Keep scoring sessions closed and no command in flight. Start the Pi services
   and wait for every exact manifest node to report a fresh, healthy clock.
5. POST the current UTC epoch, actor, and note to the authenticated
   `/api/system/clock-guard/reset` endpoint on WSL-SRV.
6. Clear the WSL bridge guard last using its audited recovery command. Confirm
   all three health surfaces agree before re-enabling command workers.

Previously refused command receipts remain terminal after a reset. Correct the
physical state manually, then create a new audited operation; never replay a
stale command ID.
