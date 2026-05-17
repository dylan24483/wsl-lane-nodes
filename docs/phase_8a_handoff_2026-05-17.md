# Phase 8a Handoff — 2026-05-17 evening

**For:** next session (Mon 5/18 onward) — fresh Claude session or Dylan after a break.
**Context:** All prep work for cutover at lanes 21+22 is in flight. Boards arrive ~Fri 5/22 to Sun 5/24. This doc captures everything to pick up tomorrow.

---

## One-paragraph orientation

WSL Conqueror Replacement — Phase 8a is the first lane-pair cutover from the legacy QubicaAMF stack (BCU II + QBK-SIx + T-VISION + VDB-99) at lanes 21+22 to a Raspberry Pi 4 running `lane_node.py`. The Pi reads DIELL sensors + foul/2nd-ball lamps via a DONGKER opto-input board, drives the AMF 8270 pinsetter via NOYITO relays, all gated by a custom NE555 hardware watchdog on a Phase 8a PCB ordered 2026-05-15 (boards arriving Fri 5/22 to Sun 5/24). Phase 7 cross-lane league scoring shipped to prod 2026-05-15 (commits `31a4f52` + `836e3fc` on wsl-systems). Lane-node server runs on WSL-SRV as of today; dev Pi connected and soaking through Tue 5/19 minimum.

---

## Where we are — Sun 5/17 evening

### Deployments

| Component | State | Notes |
|---|---|---|
| Phase 7 cross-lane scoring (wsl-systems) | ✅ Live on WSL-SRV since Friday | Commit `31a4f52`. Verified via `/api/lanes` returning all 32 lanes. |
| Phase 7 follow-ups + Codex audit fixes (wsl-systems) | ⏳ Pending AnyDesk deploy | Commits `ec50cb7`, `8c0dfc4`, `4780c2d`, `4fc1cf2`. Display cross-lane filter, Phase 8 mirror bridge, HTTP r.ok checks, transfer + visit-settle + rehydrate mirror. ~5 min file-copy + Operations API restart. |
| lane_node_server.py (wsl-lane-nodes) | ✅ Live on WSL-SRV as of today | Windows Task Scheduler `"WSL Lane Node Server"` running as SYSTEM. Listens `:8765` (WebSocket) + `:8766` (HTTP). Auto-restart on failure + at boot. Logs to `C:\QDesk\wsl-lane-nodes\lane_node_server.log` via Python `-u` unbuffered redirect through `run_server.bat`. |
| Dev Pi (`lane-node-dev.local`) | ✅ Connected to WSL-SRV | systemd override at `/etc/systemd/system/lane-node.service.d/override.conf` sets `WSL_LANE_SERVER_URL=ws://192.168.86.36:8765` + `WSL_LANE_SCORING_MODE=manual`. Handshake confirmed 14:46:33 local time. |

### NSSM substitution

`nssm.cc` was returning 503 today. Pivoted from NSSM to **Windows Task Scheduler** (matches the existing `WSL Operations API` and `WSL Analytics Server` task pattern Dylan already uses). Wrapper batch file at `C:\QDesk\wsl-lane-nodes\run_server.bat`:

```bat
@echo off
cd /d C:\QDesk\wsl-lane-nodes
".venv\Scripts\python.exe" -u "server\lane_node_server.py" >> lane_node_server.log 2>&1
```

Task registered via `Register-ScheduledTask -UserId "SYSTEM" -RunLevel Highest -RestartCount 3` — see the PowerShell history in chat for the full block.

### Soak

48h soak clock started **2026-05-17 14:46:33** (local time). Through Tue 5/19 minimum. Monitor from laptop with:

```powershell
Invoke-RestMethod http://192.168.86.36:8766/api/health | Select-Object uptime_human, nodes_connected
```

Expect `nodes_connected: 1` and `uptime_human` climbing monotonically. If `nodes_connected: 0`, the Pi dropped — SSH and check `journalctl -u lane-node -n 50`.

### Hardware orders

| Item | Status | ETA |
|---|---|---|
| Phase 8a PCB ×20 (JLC, assembled) | In fab | Fri 5/22 to Sun 5/24 |
| Phoenix MKDS 1,5/2-5,08 terminals ×220 (Mouser) | UPS Ground in transit | Mon-Wed |
| Pi 4 4GB ×2 (CanaKit Starter PRO) | Amazon, Prime | Mon-Tue |
| UCTRONICS PoE HAT ×2 | Amazon, Prime | Mon-Tue |
| TP-Link TL-SG2428P PoE+ switch | Amazon | Mon-Wed |
| NOYITO 8-Channel 5V Relay Module ×2 | Amazon, Prime | Mon-Tue |
| DONGKER 8-Channel 24V→3.3V Optocoupler ×2 | Amazon | May 20-23 (tight — watch this one) |
| Ogrmar IP65 enclosure (8×6×4") ×2 | Amazon, Prime | Mon-Tue |
| YOLCAR DIN rail 200mm ×1 (2-pack) | Amazon, Prime | Mon-Tue |
| Saysurey ST2-2.5 DIN terminal blocks (56pc) | Amazon, Prime | Mon-Tue |
| 12V 1A wall adapter (DIELL Vcc) | Amazon, Prime | Mon-Tue |
| EDGELEC 100pcs 10kΩ resistors | Amazon, Prime | Mon-Tue |
| Knipex 97 53 14 ferrule crimper | Amazon, Prime | Mon-Tue |
| Knipex 98 20 35 3.5mm slotted screwdriver (swap from 98 20 25) | Amazon, Prime | Mon-Tue |
| Hookup wire (18AWG + 22AWG kits) | Amazon, Prime | Mon-Tue |
| Ferrules, heat shrink, zip ties, label maker | Amazon, Prime | Mon-Tue |
| Taiss E3F-DS30C4 photoelectric (DIELL bench sim) | Amazon, Prime | Mon 5/18 |
| Beelink MINI S12 thin client | On hand (prior order) | n/a |
| Samsung 32" UJ59 4K monitor | On hand (prior order) | n/a |

### Decisions locked

- **DIELL ball-detect**: INCLUDED in Phase 8a #1 cutover. 4 sensors (left/right beam per lane × 2 lanes) → DONGKER inputs 5-8 with 10kΩ external pull-up to +12V (replacing T-VISION's internal pull-up after T-VISION retires).
- **Scoring mode**: `manual`. DIELL fires `BALL_EVENT` with `pin_mask=null` and `awaiting_manual=true`; server cycles the pinsetter but does NOT auto-score. Desk operator types pin count via `POST /api/lane/<N>/score {"pin_mask": int, "foul": bool}`. T-Camera + auto pin_detect deferred to follow-up after Phase 8a soaks clean.
- **QubicaAMF stack**: full disassembly during cutover window — QBK-SIx + BCU II + T-VISION-98 + VDB-99 all come out. Must wire new 12V supply for DIELL Vcc **before** T-VISION power-down (T-VISION currently powers DIELL).
- **Customer display**: HDMI from Beelink MINI S12 thin client → existing Samsung 32" overhead monitor at lane 21+22. Beelink runs Chromium kiosk pointed at `http://192.168.86.36:8766/display?lane=21&mode=league`.
- **GitHub repo `wsl-lane-nodes`**: temporarily **PUBLIC** to ease deployment. Plan: flip back to private after Phase 8a soaks clean (~2 weeks). Future post-flip deploys via SSH deploy key on WSL-SRV (not yet generated; do during the public window for clean post-flip access).

### Still-open question

- **Foul lamp self-light test**. Verify Mon during site survey with multimeter on J1.5-6 (lane 21) and J2.5-6 (lane 22) while the entire QubicaAMF stack is powered off. Walk over the foul line.
  - If the lamp still lights → Phase 8a just observes via AC interposer. No extra work.
  - If the lamp depends on QBK-SIx → reserve a 5th NOYITO relay channel to drive the lamp during cutover. Cheap, but needs to be planned before Wednesday's infrastructure install.

Every other Section 1 question in `phase_8a_cutover_plan.md` is locked.

---

## Tomorrow's plan — Mon 5/18

### Morning (anytime before bench DIELL test) — deploy outstanding wsl_api.py updates (~5 min)

AnyDesk file-copy:

| Source (laptop) | Destination (WSL-SRV) |
|---|---|
| `C:\Users\Dylan DeYoung\WSL Systems\wsl_api.py` | `C:\QDesk\wsl_ops\wsl_api.py` |
| `C:\Users\Dylan DeYoung\WSL Systems\wsl_scoring_display.html` | `C:\QDesk\wsl_ops\wsl_scoring_display.html` |

Then in any PowerShell on WSL-SRV (admin not needed):

```powershell
Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force
schtasks /End /TN "WSL Operations API"; Start-Sleep 2
schtasks /Run /TN "WSL Operations API"; Start-Sleep 5
netstat -an | Select-String ":5000 "
```

Verify: `http://192.168.86.36:5000/api/lanes` returns 32 lanes. **DO NOT** restart `WSL Lane Node Server` — that's a different task, leave it running.

### Mid-day — site survey #1 at Westside (~1h)

Kit:
- Multimeter
- Alligator-clip test leads (hands-free probing)
- Phone for photos
- Headlamp / flashlight
- Tape measure or laser distance tool
- Bowling ball (for foul + ball-detect tests)
- Sharpie + masking tape

Four things to resolve:

1. **Foul lamp self-light** (see Open Questions above). Multimeter on J1.5-6 + J2.5-6 with QubicaAMF stack fully powered down.
2. **Overhead monitor input** — does lane 21+22's monitor accept HDMI? Or VGA-only? Photograph the back of the monitor.
3. **Routing path** — closet → lane 21+22 equipment area. Surface raceway / existing conduit / overhead tray. Measure length.
4. **Mount spot** — photograph candidate Phase 8a enclosure positions at lane 21+22 (chest-height on cabinet side preferred).

Output (in the evening): `docs/phase_8a_site_survey_2026-05-18.md` with photos + decisions.

### Afternoon — bench DIELL chain test

When the Taiss E3F-DS30C4 + 12V wall adapter + resistor kit arrive (Mon-Tue):

Wiring per channel:
- Brown wire (sensor Vcc) → +12V from wall adapter
- Blue wire (sensor GND) → GND (shared with adapter GND)
- Black wire (sensor signal, NPN open-collector) → DONGKER input `5+`
  - Also tie 10kΩ resistor between black wire and +12V (external pull-up replacing T-VISION's internal pull-up)
- DONGKER input `5-` → GND
- DONGKER output O5 → Pi GPIO 13 (matches `LANE_GPIO[21]['diell_left']` in `lane_node.py`)

DONGKER selector jumpers: input side at 24V, output side at 3.3V (per `project_phase8_bench_rig_validated` memory).

Test:
- Wave a hand in front of the sensor (diffuse type — triggers on reflection from anything close).
- Pi journal should log `GPIO: ball detected on lane 21, mode=manual (awaiting desk score)`.
- WSL-SRV log should log `Lane 21: BALL detected (manual mode — awaiting /score POST from desk). Cycling pinsetter.`
- `POST http://192.168.86.36:8766/api/lane/21/score -H "Content-Type: application/json" -d "{\"pin_mask\": 0}"` should record the ball.
- Display at `http://192.168.86.36:8766/display?lane=21&mode=open` should show frame 1 with X for the bowler (need to open the lane first via `POST /api/lane/21/open` with `{"bowlers": ["TEST"]}`).

If working: wire the remaining 3 DIELL channels (GPIOs 16, 19, 20) and validate cross-lane scoring with a simulated league night via `POST /api/pair/21-22/open-league`.

If the sensor doesn't arrive: fall back to the push-button simulator (DMWD 2pcs in Amazon order) — same NPN open-collector behavior, just manual trigger instead of optical.

---

## Calendar through cutover

| Day | Tasks |
|---|---|
| **Mon 5/18** | wsl_api.py deploy. Site survey #1. Mouser + most Amazon parts arrive. Bench DIELL chain test begin. |
| **Tue 5/19** | Full bench DIELL test across all 4 channels. Cross-lane league simulation via /open-league. Cutover-enclosure bench assembly starts. 3D-print DIN clips. Site survey writeup. |
| **Wed 5/20** | Infrastructure install at Westside (~3-4h): mount PoE+ switch in closet, run Cat6, mount empty Ogrmar enclosure at lane 21+22, install Beelink + HDMI to overhead monitor. Start 24h infrastructure soak. |
| **Thu 5/21** | Bench dry-run of full cutover procedure with placeholder PCB. Pre-pack on-site kit. WSL-SRV pre-checks (clear `lane_state.db`, verify firewall, confirm `/api/health`). |
| **Fri 5/22 (target)** | Boards arrive. Hand-solder Phoenix terminals on unit #1 + spare (~1h). Bench validation per `pcb_design_spec.md` §10 (~1h). Drive to Westside. Cutover after close (~60-90 min). |
| **Sat-Sun 5/23-24** | First-weekend soak. Daily `/api/health` + one walk-by per day. |
| **Mon-Sun 5/26-6/1** | Full first-week soak with regular customer traffic + a league night. |
| **Mon 6/2+** | If clean: Phase 8b — pair #2 at lanes 19+20. |

---

## Risk callouts

- **Boards arrive late** — if Fri 5/22 slips to Sat 5/23 or Sun 5/24, cutover slides correspondingly. Don't compress bench validation to make a target date.
- **DONGKER delivery window May 20-23** — could collide with PCB day. If Amazon shows ship slipping past 5/20, upgrade shipping or back-ordered a second source.
- **Site survey surprises** — foul lamp not self-lighting / VGA-only monitor / no usable mount spot / blocked routing path. Each is manageable but adds Wed/Thu work. Resolve on Mon.
- **48h soak surprise** — if Pi disconnects, watchdog timeout fires, or protocol mismatch warnings appear before Tue, investigate root cause before proceeding. Soak is meant to surface latent issues; don't ignore them.
- **GitHub flip-back timing** — wsl-lane-nodes is publicly visible. Before flipping back to private (~2 weeks), set up SSH deploy key on WSL-SRV so post-flip pulls don't require re-flipping. Optional but cleaner long-term.

---

## Authoritative reference

In `wsl-lane-nodes/docs/`:
- `phase_8a_cutover_plan.md` — run-of-show for the cutover window. The wire-by-wire channel map is the single most important table on cutover day.
- `phase_8a_infrastructure_plan.md` — network architecture, BOM, install procedure, site survey checklist.
- `pcb_design_spec.md` — PCB rev A as-built, BOM, bench validation §10.
- `deploy_server_to_wsl_srv.md` — original WSL-SRV deployment notes. Slightly stale — today we used Task Scheduler instead of NSSM, see this handoff for the as-deployed config.
- `hardware_watchdog_design.md` — NE555 + MOSFET watchdog spec.
- `lane_visit_checklist.md` — original 2026-05-06 lane visit procedure (still useful as a template for Monday's survey).

In `wsl-systems/`:
- `CLAUDE.md` — project state, conventions, gotchas.
- `tests/test_cross_lane.py` — Phase 7 regression harness, 8/8 passing.
- `unified_checkout_plan.md` — Phase 1-6 plan.

Project memories worth re-reading:
- `project_phase8a_pcb_ordered` — PCB rev A status and toolchain
- `project_phase8a_pcb_toolchain` — KiCad 10 + SKiDL + FreeRouting gotchas
- `project_phase8_bench_rig_validated` — bench validation arc through 2026-05-11
- `project_phase8_full_hardware_replacement` — Phase 8 strategic plan
- `feedback_codex_audits` — categorize Codex findings as real-electrical / cosmetic / defer-to-rev-B
- `project_desk_html_static_trap` — `/desk` reads `static\desk.html`, not the root
- `project_schtasks_restart_trap` — kill python.exe before `schtasks /Run` to avoid orphan
- `project_check_constraints` — prod DB has CHECK constraints on status columns

---

## Where to start tomorrow's session

1. **Health check from laptop** (~30 sec):
   ```powershell
   Invoke-RestMethod http://192.168.86.36:8766/api/health
   ```
   Confirm `nodes_connected: 1` and `uptime_human` reasonable (~16-18h overnight).
2. **Deploy outstanding wsl_api.py + wsl_scoring_display.html** to WSL-SRV (~5 min AnyDesk).
3. **Site survey at Westside** (~1h). Bring the kit listed above.
4. **Bench DIELL chain** when parts arrive. Start with one channel, verify end-to-end, then expand to all 4.

## Status: green for cutover Fri 5/22

All software is on track. Hardware is in transit. No unresolved blockers. Tomorrow's site survey is the only major variable — and the foul-lamp question is the only thing that could meaningfully reshape the cutover plan, and that's a 2-minute multimeter check.
