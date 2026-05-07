# wsl-lane-nodes

Phase 8 of the Westside Lanes Conqueror replacement project. Each Pi 4 controls one lane pair, replacing the QubicaAMF stack (BCU II + QBK-SIx + T-VISION + VDB-99) with direct GPIO control of the AMF 8270 cabinet I/O. Pi nodes connect to WSL-SRV via WebSocket and feed events into the existing wsl_scoring_engine.

## Status: bench rig fully validated (2026-05-06)

**What runs end-to-end on the bench:**

- [x] Pi GPIO + WebSocket + scoring engine + browser display (night-1 prototype, 2026-05-01)
- [x] AEDIKO 8-channel relay HAT + AL-ZARD DST-1R8P-P opto-input bench rig validated
- [x] Per-pair (lanes 21 + 22): 4 inputs (foul × 2 + 2nd-ball × 2) + 4 outputs (cycle × 2 + power × 2)
- [x] Both control modes proven: pulsed cycle + latched power on/off
- [x] Production safety: SIGTERM handler + `try/finally` on `pulse()` + systemd `ExecStopPost=` cleanup (3 of 4 K-mitigations; hardware watchdog is the 4th)
- [x] Foul-event vs ball-detect semantic separation (BALL_EVENT carries pin_mask + foul flag)
- [x] OpenCV pin-detect pipeline skeleton (synthetic-image self-test passes)
- [x] SQLite state persistence — server restarts don't wipe in-progress games
- [x] WebSocket protocol versioning
- [x] Server portable to WSL-SRV (Windows) or stays on Pi for dev

**Active gates before Phase 8a cutover:**

- [ ] Lane 22 characterization visit — see [docs/lane_visit_checklist.md](docs/lane_visit_checklist.md)
- [ ] T-Camera + USB capture dongle on bench — calibrate `pin_detect.PIN_SPOTS` against real frames
- [ ] Hardware watchdog perfboard build — see [docs/hardware_watchdog_design.md](docs/hardware_watchdog_design.md)

## Layout

| Path | What |
|---|---|
| `lane_node/lane_node.py` | Pi-side daemon — multi-lane GPIO, WebSocket client, signal handlers |
| `lane_node/relay_cleanup.py` | Standalone GPIO cleanup script run by systemd `ExecStopPost=` |
| `lane_node/pin_detect.py` | OpenCV pipeline skeleton + synthetic-image self-test |
| `server/lane_node_server.py` | Server — WebSocket + HTTP display + desk simulator UI + `/api/health` |
| `server/state_store.py` | SQLite persistence helpers + CLI for state inspection |
| `systemd/lane-node.service` | systemd unit for production deployment |
| `prototypes/` | Scaffolding scripts that proved individual pieces during night-1 |
| `wsl_scoring_engine.py` | Copied from wsl-systems — handles bowling logic |
| `docs/lane_visit_checklist.md` | On-site procedure for the lane characterization visit |
| `docs/hardware_watchdog_design.md` | CD4538B + MOSFET watchdog circuit spec for the 4th K-pillar |
| `docs/deploy_server_to_wsl_srv.md` | Step-by-step for moving the server to WSL-SRV |

## Run on the Pi

Two SSH sessions, server in one + lane node in the other:

```bash
# Session 1 — server
cd ~/wsl-lane-nodes && source .venv/bin/activate && python3 server/lane_node_server.py

# Session 2 — lane node daemon
cd ~/wsl-lane-nodes && source .venv/bin/activate && python3 lane_node/lane_node.py
```

Browser at `http://lane-node-dev.local:8766/` — Open Lane / Close Lane / Reset Pins / Power On/Off / Trigger Ball buttons per lane.

## Run server on WSL-SRV instead of Pi

```bash
# On WSL-SRV (Windows): see docs/deploy_server_to_wsl_srv.md
# On the Pi:
WSL_LANE_SERVER_URL=ws://192.168.86.36:8765 python3 lane_node/lane_node.py
```

## Health check

```bash
curl http://lane-node-dev.local:8766/api/health
```

Returns server uptime, connected node summary, per-lane state, pending foul flags, state DB path.

## State inspection

```bash
python3 server/state_store.py            # print current saved state
python3 server/state_store.py clear      # wipe saved state
```

## Test pin detection on synthetic frames

```bash
python3 lane_node/pin_detect.py
```

Runs 7 synthetic-image test cases (strike, gutter, head pin only down, 7-10 split, etc.) and reports pass/fail. Validates the pipeline shape; real-camera calibration of `PIN_SPOTS` is a separate step.
