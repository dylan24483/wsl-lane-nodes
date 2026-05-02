# wsl-lane-nodes

Phase 8 prototype for Westside Lanes. Pi 4 per VDB pair, replaces Qubica
BCU II + VDB-99 with direct GPIO control of the AMF 8270 cabinet I/O.
Connects to WSL-SRV via WebSocket and feeds events into the existing
wsl_scoring_engine.LaneScoring.

## Status: night-1 prototype (2026-05-01)

- [x] Pi GPIO button + LED round-trip
- [x] Bidirectional WebSocket Pi to server
- [x] Real wsl_scoring_engine integrated server-side
- [x] Live HTML display at 2Hz polling
- [x] Full chain: button to JSON to server to LaneScoring to browser
- [ ] WSL-SRV-side integration
- [ ] OpenCV vision pipeline (replace simulated pin_mask)
- [ ] OpenLane / CloseLane / Foul command messages
- [ ] Wire to real 8270 BCU II at lane 21+22

## Layout

- lane_node/ — Pi-side daemon
- server/ — server-side WebSocket + HTTP display
- prototypes/ — scaffolding scripts that proved individual pieces
- wsl_scoring_engine.py — copied from wsl-systems

## Run on the Pi

Two SSH sessions:

    cd ~/wsl-lane-nodes && source .venv/bin/activate && python3 server/lane_node_server.py
    cd ~/wsl-lane-nodes && source .venv/bin/activate && python3 lane_node/lane_node.py

Then open http://lane-node-dev.local:8766/ in a browser.
