# Deploying lane_node_server to WSL-SRV

> ⚠️ **SERVER IP (updated 2026-06-10):** WSL-SRV moved to **`192.168.4.103`** in the 2026-06-03 eero router swap (the old `192.168.86.36` is **DEAD**). URLs below have been updated, but the DHCP reservation is still TODO — **confirm the live IP before deploying** and set `WSL_LANE_SERVER_URL` to match.

**Scope:** moves the Phase 8 server from the dev Pi (where it currently runs alongside lane_node.py for development convenience) to WSL-SRV (Windows 11, the production server). Phase 8 then matches its eventual production architecture: one server on WSL-SRV, N Pi nodes in the lanes.

**This does NOT replace any production Phase 4 service.** lane_node_server runs on different ports (8765 WS + 8766 HTTP) than wsl_api.py (5000) or wsl_analytics_server.py (5002). It coexists.

**Estimated time:** 30-60 minutes including AnyDesk session.

---

## Prerequisites

- WSL-SRV is reachable via AnyDesk (LAN at `192.168.4.103`)
- Python 3 on WSL-SRV (already there for wsl_api.py)
- Phase 4 production code working — DON'T break it during this deployment
- Network: dev Pi must be able to reach WSL-SRV at port 8765 (LAN, no firewall in the way)

---

## Phase 1 — Get the code onto WSL-SRV

WSL-SRV doesn't have git/SSH-key access to GitHub. Two options:

**Option A (recommended): clone via HTTPS read-only.** Public clone of `dylan24483/wsl-lane-nodes` works without credentials since the repo is public.

On WSL-SRV via AnyDesk, open PowerShell:

```powershell
cd C:\QDesk
git clone https://github.com/dylan24483/wsl-lane-nodes.git
cd wsl-lane-nodes
```

For future updates, just `git pull`.

**Option B: AnyDesk file transfer.** Drag-and-drop the laptop's `C:\Users\Dylan DeYoung\wsl-lane-nodes\` folder into AnyDesk's file transfer dialog, drop into `C:\QDesk\wsl-lane-nodes\`. Manual but doesn't depend on git on WSL-SRV.

---

## Phase 2 — Python venv + dependencies

In `C:\QDesk\wsl-lane-nodes` PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install websockets
```

The Pi's `requirements.txt` includes a lot of Pi-specific packages (gpiozero, lgpio, etc.) that the server doesn't need. The server only needs:
- `websockets` — for WS client connections from Pi nodes
- (Built-in) `sqlite3` — for state persistence
- (Built-in) `http.server` — for the desk simulator UI

If `pip install websockets` fails because WSL-SRV doesn't have outbound internet on port 443: download the wheel manually on the laptop, transfer via AnyDesk, install via `pip install <wheelfile>`.

---

## Phase 3 — Smoke test on WSL-SRV

In the activated venv, with no Pi connected yet:

```powershell
$env:WSL_MACHINE_LANES = "21,22"
$env:WSL_SCORING_NODE_TOPOLOGY = "pi-lane21-22=21,22"
$env:LANE_NODE_TOKEN = "<shared HTTP and server-command secret>"
$env:WSL_SCORING_NODE_TOKENS = "pi-lane21-22=<unique Pi secret>"
python server\lane_node_server.py
```

Expected output:

```
[INFO] HTTP display + desk simulator: http://0.0.0.0:8766
[INFO] WebSocket: ws://0.0.0.0:8765
[INFO] server listening on 0.0.0.0:8765
[INFO] No saved state found at ...; starting fresh.
```

Open `http://192.168.4.103:8766/` in any browser on the LAN. The desk simulator UI should load. No Pi nodes connected yet, so clicks on Open Lane / etc. send to 0 nodes.

If the browser can't reach `192.168.4.103:8766`, check Windows Defender Firewall — add an inbound rule for ports 8765-8766 if needed.

Stop the server (Ctrl+C in PowerShell) before continuing.

---

## Phase 4 — Point the Pi at WSL-SRV

On the dev Pi:

```bash
sudo systemctl stop lane-node.service 2>/dev/null
sudo pkill -f python3
```

Override the SERVER_URL via env var. Either inline:

```bash
WSL_LANE_SERVER_URL=ws://192.168.4.103:8765 \
WSL_LANE_NODE_ID=pi-lane21-22 WSL_DIAG_SOURCE_ID=pi-lane21-22 \
WSL_LANES=21,22 LANE_NODE_TOKEN='<shared secret>' \
WSL_SCORING_NODE_TOKEN='<unique Pi secret>' \
python3 lane_node/lane_node.py
```

Or as a permanent change in the systemd unit at `/etc/systemd/system/lane-node.service`:

```
[Service]
Environment="WSL_LANE_SERVER_URL=ws://192.168.4.103:8765"
EnvironmentFile=/etc/wsl-lane-node.env
```

After editing the unit, `sudo systemctl daemon-reload` then `sudo systemctl start lane-node.service`.

---

## Phase 5 — End-to-end test

With the WSL-SRV server running and the Pi node pointed at it:

1. Pi terminal should show:
   ```
   [INFO] Connecting to ws://192.168.4.103:8765 ...
   [INFO] Connected. Sending hello (lanes=[21, 22], protocol_version=3).
   ```
2. WSL-SRV terminal should show:
   ```
   [INFO] New connection from ('192.168.4.XXX', YYYY)
   [INFO] Node 'pi-lane21-22' registered (lanes=[21, 22], protocol_version=3)
   ```
3. Browser at `http://192.168.4.103:8766/` — click Open Lane on lane 22. Relay 1 on the Pi's bench rig clicks 3 times. Confirms the full chain across the network boundary.

---

## Phase 6 — Auto-start on WSL-SRV (optional, defer)

For tonight, just leave the server running in a PowerShell window. Long-term, set up auto-start via either:

- **Windows Task Scheduler:** create a task that runs `C:\QDesk\wsl-lane-nodes\.venv\Scripts\python.exe C:\QDesk\wsl-lane-nodes\server\lane_node_server.py` at boot, with restart-on-failure.
- **NSSM (Non-Sucking Service Manager):** wraps the Python process as a proper Windows service. `choco install nssm`, then `nssm install lane-node-server`. NSSM gives systemd-like service management on Windows.
- **Run inside a `pythonw.exe` background process via the Startup folder:** simplest but no automatic restart.

Defer this until Phase 8a is going live. For tonight's E2 validation, manual launch is fine.

---

## Rollback

If anything breaks during testing and we need to revert to dev-Pi-server:

1. Stop WSL-SRV server: Ctrl+C in its PowerShell.
2. On the Pi, unset the env var (or comment out the systemd Environment= line):
   ```bash
   unset WSL_LANE_SERVER_URL
   python3 lane_node/lane_node.py  # back to ws://localhost:8765
   ```
3. Start the server on the Pi again as before:
   ```bash
   python3 server/lane_node_server.py
   ```

Rollback is non-destructive — code, repo, and Pi state are unchanged. Only the server location and the Pi's SERVER_URL env var differ between the two modes.

---

## State migration consideration

The server's SQLite state DB lives at `<repo_root>/lane_state.db`. When migrating dev-server → WSL-SRV-server:

- Dev Pi has its own `lane_state.db` with whatever scoring state was last saved
- WSL-SRV has a fresh empty `lane_state.db`
- After migration, scores from any in-progress games on the dev Pi are lost (they were dev test data anyway)

For Phase 8a production cutover, this is moot — we'll be starting from a clean state at lane 22 anyway. If state continuity ever matters during a migration, just `cp lane_state.db` between hosts before starting the server on the new host.

---

## Status

- Code-side portability: complete (this deployment expects the SERVER_URL env var path + the new sys.path discovery via __file__)
- Documentation: complete (this doc)
- Actual deployment to WSL-SRV: NOT YET EXECUTED — gated by AnyDesk session and willingness to run another Python process on the production server

The code change is committed; deployment is the manual step that lands when you have AnyDesk open.
