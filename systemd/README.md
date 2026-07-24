# Lane-node systemd units — topology & health hand-off

Two units, **mutually exclusive** (`lane-node-controller.service`
`Conflicts=lane-node.service`), one Pi:

| Unit | Track | Role | Health class it emits |
|---|---|---|---|
| `lane-node.service` | A | camera scoring (`lane_node.py`) | `camera_health`, `camera_ref_drift`, `gs_camera_disagree` |
| `lane-node-controller.service` | B | 82-70 controller replacement (`controller_daemon.py`) | `service_restart*`, `pi_thermal`, `pi_disk_low`, `pi_fs_readonly`, `pi_undervoltage`, `uart_drops`, FSM/firmware faults, `fw_identity*` |

Both require the shared per-Pi env (`EnvironmentFile=/etc/wsl-lane-node.env`,
see `wsl-lane-node.env.example`): `WSL_DIAG_SERVER_URL`, `LANE_NODE_TOKEN`,
the distinct `WSL_SCORING_NODE_TOKEN`, `WSL_LANE_NODE_ID`, matching
`WSL_DIAG_SOURCE_ID`, `WSL_BOARD_REVS`, and the exact paired `WSL_LANES`.

## R3-2 — controller heartbeat / lease renewal (why a quiet controller stays HEALTHY)

The :8766 server derives each machine lane's board state from a **lease**
(`machine_leases.last_seen`): fresh → HEALTHY/FAULT, stale (> `WSL_MACHINE_LEASE_S`,
default 90 s) → OFFLINE, never-heard → UNKNOWN. Track A refreshes the lease
through the scoring **WS heartbeat**. **Track B sends no scoring WS**, so a
healthy-but-quiet controller used to expire OFFLINE at 90 s (Codex R3-2
wrong-topology bug).

`controller_daemon`'s `PlatformHealth` thread now POSTs
`/api/machine/heartbeat` per board every `WSL_MACHINE_HEARTBEAT_S` (default
20 s — well under the 90 s window), carrying board revision + firmware
build/config hashes + the machine-contract digest + outbox health. The server
touches the lease identically to the WS/ingest path. Requires
`WSL_DIAG_SERVER_URL` set; behind `LANE_NODE_TOKEN` when armed.

## R3-11 — shared health-drop hand-off (why both health classes reach the desk)

Because the two units are mutually exclusive, whichever one is running would
otherwise be the only health class the desk ever sees. The **shared drop file**
`${WSL_DIAG_DIR:-./diag_logs}/health_drop.json` (`lane_node/health_drop.py`,
atomic tmp+`os.replace`) bridges the hand-off:

- Each service writes its **own** last-known health block to the drop file.
- The service that is running (it has transport) also **reads the other
  service's** drop and ships it to the store as an info event flagged with its
  age (`age_s`) — a last-known snapshot, not live.

So on a Track-B (controller) box the desk still sees the camera service's
last-known health, and vice-versa. A read-only filesystem (R3-10) makes the
drop write a counted no-op; the reader simply finds no fresh foreign drop, and
the controller's own platform health still reaches the desk via the network
heartbeat.

## R3-5 — firmware identity ARM gate (controller only)

A rev-D board reports a firmware **identity** line (revision straps, build +
config.h hashes, FI-1 posture). A reboot **invalidates** the cached identity;
the daemon re-requests it. Missing identity (after retries, on a strapped
board) or a mismatch (wrong pcb revision / an FI-1 bench image) **inhibits
ARM**. Bench escape: `WSL_ALLOW_IDENTITY_MISMATCH=1` (loudly logged). rev-B/C
boards and pre-v1.2.2 firmware never report identity and are unaffected.
