# Phase 8a Infrastructure Plan — Network, Power, Mounting

> ⚠️ **NETWORK CHANGED (2026-06-10 note):** this plan was drafted on the pre-eero `192.168.86.0/24` LAN. The **2026-06-03 eero router swap** moved the site to **`192.168.4.0/22`** (gw `192.168.4.1`); WSL-SRV is now **`192.168.4.103`** (DHCP — reservation still TODO) and **every `192.168.86.x` address is dead**. WSL-SRV references below have been updated; the *planned* device addresses (switch mgmt `.86.10`, Pi nodes `.86.21+`) were never assigned and must be **re-derived on the live `192.168.4.0/22` subnet** (eero reservations) at install time.

**Status:** draft 2026-05-15. Pre-cutover infrastructure work for Phase 8a at lanes 21+22, sized for eventual 16-pair full rollout.
**Goal:** procurement BOM + physical install procedure to bring lanes 21+22 (and eventually all 16 pairs) onto the Phase 8 network with PoE+ powered Pi nodes.
**Greenfield assumption:** per the 2026-05-06 lane visit, there's no existing Cat6, no PoE switch, and no DC rail at the lane equipment areas. Everything below assumes from-scratch install.

This document is the input to procurement and to the actual install visit(s). The **cutover plan** (`docs/phase_8a_cutover_plan.md`) depends on this infrastructure being in place.

---

## 1. Topology

```
   [WSL-SRV @ 192.168.4.103]
              │
              │ Gigabit copper, existing
              ▼
   [Existing LAN switch / router] ─── [Cloudflare Tunnel (future)]
              │
              │ Gigabit copper trunk (existing or new run)
              ▼
   ┌──────────────────────────────────────────┐
   │  NEW: PoE+ access switch (24-port)        │  ← in existing network closet
   │  IP 192.168.86.10  (mgmt VLAN if any)     │     alongside WSL-SRV
   │                                           │
   │  Ports 1-16:  Cat6 PoE+ to each lane pair │
   │  Port  17:    spare (laptop / mgmt)       │
   │  Port  18:    spare (future expansion)    │
   │  Port  19+:   reserved                    │
   │  SFP / uplink: to existing LAN switch     │
   └──────────────────────────────────────────┘
        │     │      │           │
        │     │      │           │
        ▼     ▼      ▼           ▼
     pair1 pair2  pair3  ...   pair16   (each = one Cat6 with PoE+ delivering ~12.5W)
        │
        │ Cat6 run (~30-70m depending on lane #)
        ▼
   ┌──────────────────────────────┐
   │  DIN-rail enclosure at lane   │
   │  pair N (mounted near 8270    │
   │  cabinet)                     │
   │                               │
   │  - Pi 4 + PoE+ HAT            │ ◄── Cat6 in (data + 48V PoE)
   │  - AEDIKO 8-ch relay HAT      │
   │  - AL-ZARD 8-ch opto-input    │
   │  - Phase 8a PCB (NE555 wd     │
   │    + 4-ch AC interposer)      │
   │  - Phoenix terminals to/from  │
   │    8270 cabinet wiring        │
   │  - Status LEDs visible        │
   │    through enclosure window   │
   └──────────────────────────────┘
        │
        │ short low-voltage runs (<2m)
        ▼
   8270 pinsetter cabinet (existing — same as today, just receiving cycle/power
   from AEDIKO relays instead of QBK-SIx, and reading foul/2nd-ball lamps via
   the Phase 8a AC interposer instead of QBK-SIx +FOL/+2ND inputs)
```

Network architecture is intentionally simple: one switch, one subnet (`192.168.86.x`, the WSL-SRV LAN), one VLAN (default). No NAT, no per-pair routing. The Pi nodes are first-class citizens on the main LAN — they can `ping 192.168.4.103` (WSL-SRV) directly.

---

## 2. Network architecture

### Switch selection

**Required spec:**
- ≥16 PoE+ ports (802.3at, 25.5W per port)
- Gigabit Ethernet on all ports
- Managed (so we can do per-port reboot, telemetry, future VLAN if needed)
- Quiet / fanless preferred (will live in the wiring closet)
- Budget: $250-400

**Recommended options (any of these work):**

| Model | Ports | PoE+ budget | Mgmt | Approx price | Notes |
|---|---|---|---|---|---|
| **Ubiquiti USW-Lite-16-PoE** | 16 (8 PoE+) | 45W total | UniFi UI | ~$200 | **Only 8 PoE+ ports — too few for 16 pairs. Skip.** |
| **Ubiquiti USW-Pro-Max-24-PoE** | 24 (16 PoE+) | 400W total | UniFi UI | ~$650 | Overkill but very nice; UniFi management is excellent |
| **Mikrotik CRS328-24P-4S+RM** | 24 (24 PoE+) | 500W total | RouterOS/SwOS | ~$400 | Strong value; CLI-driven |
| **TP-Link TL-SG2428P (JetStream)** | 24 (24 PoE+) | 250W total | TP-Link Omada | ~$250 | **Recommended baseline.** 24×PoE+, fanless option, web UI, decent budget |
| **Netgear GS324TP** | 24 (16 PoE+) | 190W total | NetGear Insight | ~$300 | Acceptable, but 16-port PoE limit means we'd run at exactly capacity |

**Decision: TP-Link TL-SG2428P** for budget + 24×PoE+ headroom (eventually we'll add a "display Pi" per pair too, then a "kiosk Pi" per league night, etc. — 16 ports of PoE will fill up). If Dylan already prefers a different ecosystem (UniFi), substitute. ~$250.

Power budget sanity check:
- Pi 4 + HAT load per pair: ~10W (Pi ~5W + AEDIKO coils ~3W + AL-ZARD <1W + PCB <1W)
- 16 pairs × 10W = 160W
- Switch PoE+ budget: 250W (TL-SG2428P) — 56% headroom ✓

### IP plan

| Device | IP | Notes |
|---|---|---|
| TP-Link switch | 192.168.86.10 | Management |
| Pi node, lane pair 1-2 | 192.168.86.21 (or DHCP-reserved on MAC) | Hostname `lane-node-01-02.local` |
| Pi node, lane pair 3-4 | 192.168.86.22 | `lane-node-03-04.local` |
| … | … | … |
| Pi node, lane pair 21-22 | **192.168.86.31** (or 192.168.86.111 — TBD; .31 was BACKOFFICE1 historically) | `lane-node-21-22.local` |
| … | … | … |
| Pi node, lane pair 31-32 | 192.168.4.103 — **wait, that's WSL-SRV; pick different** | adjust block |

**TODO:** carve out an IP block for Pi nodes. Suggest `.86.100-115` to avoid conflict with `.86.31` (BACKOFFICE1, soon-retired) and `.86.36` (WSL-SRV). DHCP reservation on the existing router based on each Pi's MAC, OR static IPs configured per-Pi in `/etc/dhcpcd.conf`. DHCP is easier — pin the MACs at the router level.

Hostname convention: `lane-node-NN-NN.local` where NN-NN is the lane pair (low-high). mDNS handles discovery; the Pi advertises via Avahi automatically once configured with `hostname` set.

### VLAN (deferred, single-VLAN for Phase 8a)

For Phase 8a + 8b, keep everything on the default VLAN. Phase 8 traffic is all internal — Pi ↔ WSL-SRV WebSocket. No internet-facing exposure (Cloudflare Tunnel will route specific paths only). If isolation becomes desirable later (e.g., Pi nodes should not be able to reach `desk.html` directly), set up a dedicated VLAN 86 and trunk the uplink. Not required now.

---

## 3. Power

### PoE+ from the switch (recommended)

Single Cat6 cable carries data + 48V power. At the Pi, a PoE+ HAT splits power: 5V regulated rail to Pi GPIO header pin 2 (5V) + ground, with the rest of the 25W budget available on the HAT's pass-through pins.

**Pi 4 PoE+ HAT options:**

| Product | Output | Cooling | Price | Notes |
|---|---|---|---|---|
| **Official Raspberry Pi PoE+ HAT** | 5V/2.5A (12.5W) | small fan | ~$25 | Official, well-supported. Fan is slightly audible. |
| **Waveshare PoE HAT (B)** | 5V/2.5A | passive | ~$20 | Fanless, slightly larger footprint. |
| **GeeekPi PoE+ HAT** | 5V/3A | passive | ~$18 | Cheap clone, mixed reviews on stability |

**Recommended: Official RPi PoE+ HAT.** Fan noise is acceptable in an enclosure that's in the equipment area (not the dining area), and "official" means firmware/driver support is upstream-maintained.

Power distribution from HAT:
- HAT outputs 5V/2.5A → Pi 4 (~5W typical, leaves ~7.5W headroom)
- Pi GPIO 5V pin → daisy-chain to AEDIKO HAT VCC, AL-ZARD VCC, Phase 8a PCB J1.1 (+5V IN)
- All grounds tied common at the Pi GPIO header

**Concern:** AEDIKO coils inrush at relay-close can briefly spike to ~2× steady current (~140mA × 8 = 1.1A momentary). PoE HAT's 2.5A output should handle this, but if we see brownouts on the Pi during relay activity, add a 1000µF bulk cap on the AEDIKO 5V rail to buffer.

### Alternative: external 5V PSU + Cat6 data-only

If PoE+ doesn't work for some reason (HAT incompatibility, switch budget tight, etc.):

- Single Cat6 run for data only (cheaper switch — non-PoE GigE 16-port ~$50)
- Per-pair: 5V/3A switching PSU (Mean Well RS-15-5, ~$15) wired to an AC outlet at the equipment area

Problem: there's no AC outlet at the equipment area today (per the lane visit). Need to either:
- Install a new outlet per pair (electrician, ~$150 × 16 = $2400 — kills the cost advantage)
- Run a long DC home-run from a central 5V PSU in the closet (DC voltage drop over 50m × 5V is significant; not viable without a much higher source voltage)

PoE+ wins on TCO. Stick with PoE+.

### AEDIKO coil supply isolation (open consideration)

The Phase 8a PCB's NE555 watchdog gates the AEDIKO coil supply's GND return via Q2. As-built, the +5V to AEDIKO comes from J2.1 (which is wired directly to VCC_5V) and the −5V returns via J2.2 (which is COIL_GND_RETURN, gated by Q2). If the AEDIKO coil supply is the SAME 5V rail as the Pi, then Q2 opening kills the Pi-side 5V supply too (because Pi GND is shared with COIL_GND_RETURN).

**Wait — that's wrong, re-read the netlist:** GND (Pi side) is connected to J1.2, U1.1, etc. — it's the SUPPLY ground, NOT COIL_GND_RETURN. COIL_GND_RETURN is the AEDIKO V- return, gated by Q2 (which connects COIL_GND_RETURN to GND when conducting). So when Q2 opens, AEDIKO V- floats (no path to ground), AEDIKO coils have no return current path — but Pi GND is unaffected because Pi runs off the protected VCC_5V rail with its own GND tie.

OK, the topology works. The Pi remains powered even when the watchdog cuts AEDIKO. Confirmed by re-reading `docs/pcb_design_spec.md` Section 3b. Note added for future-me clarity.

---

## 4. Physical mounting — DIN-rail enclosure

### Enclosure spec

- DIN-rail mountable (35mm rail standard)
- IP54+ ingress (the equipment area is dusty)
- Internal dimensions: ≥200mm wide × 150mm tall × 80mm deep (fits Pi + 2 HATs + Phase 8a PCB + Phoenix terminals with cable bend radius)
- Hinged door with latch
- Clear or smoke-tinted window over the indicator-LED zone (so D7 "WD" + D8 "PWR" + Pi green/red status can be seen with the door closed)
- 4× cable glands (PG13.5 or M20): 1× for Cat6, 1× for the 8270 cabinet wire bundle (4 wires per lane × 2 lanes = 8 wires), 1× for foul/2nd-ball lamp wires (4 pairs), 1× spare

**Recommended options:**

| Product | Dimensions (mm) | Material | Price | Source |
|---|---|---|---|---|
| Hammond 1597BSGY (DIN-mount) | 220 × 175 × 90 | ABS | ~$45 | Mouser, Digikey |
| Schneider NSYMR43 (Spacial) | 250 × 150 × 80 | steel | ~$80 | Schneider distributor |
| Allen-Bradley 8000-1AC | 250 × 150 × 75 | polycarbonate | ~$60 | Rockwell distributor |
| Phoenix ME 22.5 generic DIN box | 200 × 150 × 75 | ABS | ~$35 | Phoenix distributor |

**Recommended: Hammond 1597BSGY** for cost + availability. ABS is fine for the equipment area (no direct sunlight, no extreme temp).

### DIN rail (mounted inside the enclosure)

- 35mm steel DIN rail, slotted, ~200mm length per enclosure
- Mounts to the enclosure back-plate with 2× M4 screws
- Hold modules: Pi-DIN-rail clip (3D-printed or off-the-shelf), AEDIKO-AL-ZARD-Phase 8a-board mounts (each likely needs a 3D-printed DIN clip with mounting holes matching the board)

**DIN-mount accessories needed per pair:**

- 1× Pi 4 DIN clip (3D-printable, e.g., Thingiverse "Pi 4 DIN rail mount")
- 1× DIN base-plate for AEDIKO (no off-the-shelf for the 8-channel SongLe board; 3D-print a sliding base)
- 1× DIN base-plate for AL-ZARD (same — 3D-print)
- 1× DIN base-plate for Phase 8a PCB (uses MK1-MK4 holes — 3D-print a 4×M3-stud DIN clip)

3D printing 16 sets of these is ~8h of print time on a Bambu A1 / Prusa Mk4. ~$10 of filament per pair.

### Mounting location at each lane pair

Per the 2026-05-06 lane visit:
> No existing Cat6 / PoE switch / DC rail at the lane equipment areas. Everything will be greenfield.

The equipment area is behind the pinsetters, accessible via a service door. Likely candidate spots:
- **Right side of the 8270 cabinet** at chest height — easy access for service. Wires routing to the existing QBK-SIx location are <1m.
- **Above the 8270 cabinet** on the wall — keeps it out of the way but requires a step-stool for service.

**Recommended: chest-height mount on the cabinet side or on a wall stud nearby.** Photograph candidate spots during the pre-install survey.

---

## 5. Cabling

### Cat6 from switch to each lane pair

- Cat6 (or Cat6A — overkill for GigE+PoE+ but only 10% pricier and futureproofs to 10G)
- Stranded for routing flex through conduit bends, OR solid-core if running in cable tray
- Length per pair: ~30-70m depending on lane position (lane 1 closest to closet, lane 32 farthest)
- Cable spec: ETL-listed, riser-rated (CMR) if running through walls

**Bulk roll:** 1000ft (305m) box of Cat6 stranded ≈ $80-120 from Monoprice / Cable Matters / Amazon. One box covers all 16 pairs with margin.

**Termination:** RJ45 connectors + crimping tool. Better practice: keystone jacks at the wall plate side, patch panels in the closet. For Phase 8a (single pair), crimped RJ45 on both ends is fine. For full 16-pair install: 24-port keystone patch panel (~$30) + 16 keystone jacks (~$20) + 16 short patch cables in the closet.

**Routing options:**

| Option | Effort | Looks | Notes |
|---|---|---|---|
| Overhead in cable tray | High install (drill, hangers) | Clean | Best for permanent. Run tray along the back wall above lanes 1-32, drop down to each pair. |
| In existing conduit (if any) | Medium (fish-tape) | Hidden | Depends on conduit availability — survey during pre-install |
| Surface-mount with raceway | Low | Visible but tidy | Plastic raceway from Wiremold / Legrand. ~$2/ft. Easy DIY. |
| Loose along the back wall | Lowest effort | Messy | Functional but unprofessional. Acceptable only for Phase 8a #1. |

**For Phase 8a #1:** surface-mount raceway along the back wall is the lowest-effort + still-tidy option. Defer cable-tray install to Phase 8b once Phase 8a soaks clean.

### Patch cables in the closet

- 16× Cat6 patch cables, 0.5-1m each, between the switch and the patch panel (or wall jacks)
- Color-code: e.g., red for Phase 8 traffic, distinguishing from yellow/blue for existing LAN

---

## 6. Per-pair BOM (procurement for 1 pair)

For Phase 8a unit #1 (lane 21+22), procure:

| Item | Qty | Unit price | Subtotal | Source |
|---|---|---|---|---|
| Raspberry Pi 4 Model B (4GB) | 1 | $65 | $65 | RPi distributor / Adafruit |
| Official Raspberry Pi PoE+ HAT | 1 | $25 | $25 | RPi distributor |
| 32GB MicroSD (Sandisk Industrial or equivalent) | 1 | $20 | $20 | Mouser / Digikey |
| AEDIKO 8-channel relay HAT | 1 | $15 | $15 | Amazon |
| AL-ZARD DST-1R8P-P 8-channel opto-input | 1 | $25 | $25 | Amazon / AliExpress |
| Phase 8a PCB (1 of 20 from JLC order) | 1 | $9 | $9 | already ordered 2026-05-15 |
| Hammond 1597BSGY enclosure (or equivalent) | 1 | $45 | $45 | Mouser / Digikey |
| 35mm × 200mm DIN rail | 1 | $5 | $5 | Mouser |
| 3D-printed DIN clips set (Pi + AEDIKO + AL-ZARD + Phase 8a) | 1 set | $10 (filament) | $10 | self-print |
| Cat6 cable (stranded, ~50m run + 5m patch) | 1 | $20 | $20 | Monoprice |
| RJ45 connectors (qty 10 to allow re-termination) | 10 | $0.50 | $5 | Amazon |
| Cable glands (PG13.5 × 4) | 4 | $2 | $8 | Amazon |
| 18AWG hookup wire (red/black/blue/green, 10m each) | 4 rolls | $5 | $20 | Amazon |
| Phoenix MKDS terminal block (5.08mm 2-pos) for Phase 8a PCB | 11 | $0.30 | $4 | already accounted in PCB BOM |
| Misc: screws, cable ties, heat-shrink, label tape | — | — | $15 | Home Depot / Amazon |
| **Per-pair subtotal** | | | **~$285** | |

**Shared infrastructure (one-time, install during Phase 8a):**

| Item | Qty | Unit price | Subtotal | Source |
|---|---|---|---|---|
| TP-Link TL-SG2428P PoE+ switch | 1 | $250 | $250 | Amazon / B&H |
| 1000ft Cat6 stranded bulk box | 1 | $100 | $100 | Monoprice |
| RJ45 crimp tool + tester | 1 | $40 | $40 | Amazon |
| 24-port keystone patch panel (rack mount) | 1 | $30 | $30 | Monoprice |
| Cable raceway / hangers (~50ft) | — | — | $80 | Home Depot |
| Spare unit #2 enclosure assembly (full Pi + HATs + PCB ready to swap in if #1 fails) | 1 | $285 | $285 | (matches per-pair BOM) |
| **Phase 8a one-time install subtotal** | | | **~$785** | |

**Phase 8a total: ~$1,070** (one pair + shared infrastructure + spare).

### Phase 8b-c (replicate to remaining 15 pairs)

| Item | Qty | Per-unit | Subtotal |
|---|---|---|---|
| Per-pair BOM (Pi + HATs + Phase 8a PCB + enclosure + Cat6 + cables) | 15 | $285 | $4,275 |
| Bulk Cat6 already covered above; subtract Cat6 cost from per-pair BOM for #2-16 | -15 | -$20 | -$300 |
| **Phase 8b-c subtotal** | | | **~$3,975** |

**Grand total for full 16-pair Phase 8 rollout: ~$5,050.** Matches the order-of-magnitude estimate in `project_phase8_full_hardware_replacement` memory.

### Cost comparison

| Scenario | Cost |
|---|---|
| Refurbished QubicaAMF for failing VDBs / SIX BOX / etc. | ~$16,000 + EOL risk + part scarcity |
| Phase 8 full rollout (Pi-per-pair, this plan) | ~$5,050 + ongoing maintainability |
| **Savings:** ~$11,000 + lifetime parts independence | |

---

## 7. Procurement timeline

Aligned with the Phase 8a calendar (boards arrive ~2026-05-22 to 05-24):

**Order immediately (lead times 1-2 weeks):**
- [ ] Pi 4 + PoE+ HAT + SD card (RPi distributor — sometimes backordered)
- [ ] TP-Link switch (Amazon Prime — ~1 day)
- [ ] Hammond enclosure (Mouser — usually in stock)
- [ ] DIN rail + raw materials (Mouser)
- [ ] Cat6 bulk box (Monoprice — ~3-5 day)
- [ ] AEDIKO + AL-ZARD (Amazon)
- [ ] Phoenix terminal blocks for hand-soldering on Phase 8a boards (Mouser — order with the boards ETA)

**3D print after boards specs are locked:**
- [ ] DIN clips for Phase 8a PCB (uses MK1-MK4 hole pattern — print after first board is in hand to verify fit)
- [ ] DIN clips for Pi / AEDIKO / AL-ZARD (Thingiverse / Printables existing designs)

**Defer until after Phase 8a soaks clean:**
- [ ] Bulk procurement for Phase 8b-c (don't tie up cash in 15 more sets of parts until #1 is proven)
- [ ] Cable tray / overhead raceway for full install (use surface-mount raceway for #1)

---

## 8. Pre-install survey (one ~1h visit before infrastructure install)

Goal: verify the closet has room for the switch, the routing path to lanes 21+22 is feasible, and the equipment area has mount space + ingress points for cable glands.

1. **Photograph the existing wiring closet** where WSL-SRV lives. Identify:
   - Free wall space for the new switch (or rack U-space if there's a rack)
   - Power outlet within 1m of where the switch will mount
   - Existing patch panel / wall jacks
   - Cable entry/exit points to the lane area
2. **Walk the candidate routing path** from closet to lane 21+22 (and visualize how it'd extend to other pairs). Note:
   - Existing conduit (any?)
   - Wall types (drywall vs masonry — affects fasteners)
   - Ceiling height + accessibility (for cable tray decision)
   - Approximate run length (laser measure)
3. **At lane 21+22 equipment area:** photograph candidate enclosure mounting spots. Verify:
   - Cat6 can reach the spot from the chosen routing path
   - Existing 8270 wiring is accessible (the cutover plan will need 8 wire pairs lifted from QBK-SIx and re-landed inside the new enclosure — needs enough slack)
   - Door clearance for accessing the enclosure during service
4. **Photograph the existing network closet's switch ports.** Confirm:
   - Free port for the new switch's uplink
   - Available 110VAC outlet
   - VLAN / management config visible (or grab a screenshot of the existing switch's port assignments)

Output: short markdown doc `docs/phase_8a_site_survey_2026-MM-DD.md` with photos + decisions, then schedule the infrastructure install.

---

## 9. Infrastructure install procedure (one ~3-4h visit before Phase 8a cutover)

This is the visit that lays the cabling + mounts the switch + the lane 21+22 enclosure, but does NOT touch the QubicaAMF wiring (that's the cutover visit).

### Closet work (~1 hour)

1. **Mount the TP-Link switch** in the closet. Power it via existing AC outlet. Configure management IP `192.168.86.10`, set admin password, enable PoE+ on ports 1-16.
2. **Run uplink** from switch port 24 (or SFP) to the existing LAN switch. Test: laptop on the new switch can ping `192.168.4.103` (WSL-SRV).
3. **Mount the patch panel** (if using one) above the switch in the rack. Don't punch down anything yet — keystone jacks get added as cables arrive.
4. **Label the switch ports 1-16** with their intended pair: `L1-2, L3-4, L5-6, ..., L31-32`. Use a Brother label maker or printed labels.

### Cable pull to lanes 21+22 (~1 hour)

5. **Run a single Cat6** from the closet to the lane 21+22 equipment area. Use surface-mount raceway or fish through existing conduit per the survey.
6. **Terminate** the closet end on either the patch panel (port labeled `L21-22`) or with a crimped RJ45 to the switch's port 11 (or whichever number maps to lane 21+22 in your numbering).
7. **Leave 2m of slack** at the lane end for routing into the enclosure.

### Enclosure install at lane 21+22 (~1 hour)

8. **Mount the Hammond enclosure** at the chosen spot from the survey. Use anchors appropriate for the wall material.
9. **Install the DIN rail** inside the enclosure.
10. **Install cable glands** in the enclosure walls per the layout: top for Cat6, bottom for 8270 wires, side for power if PoE isn't used.
11. **Route the Cat6 through its gland**, terminate the lane end with a crimped RJ45 (or keystone jack into a Pi-side patch cable — keystones are tidier).
12. **Snap the Pi/HAT/PCB assembly onto the DIN rail.** All modules wired internally per the pre-bench assembly.
13. **Plug the Cat6 into the Pi's PoE+ HAT.** Pi boots (~30 sec). LED activity on the HAT confirms PoE+ negotiated.
14. **Verify from a laptop:** SSH to `lane-node-21-22.local`, run `journalctl -u lane-node -n 50` — see "Connected to ws://192.168.4.103:8765" or similar.

### Verify end-to-end (~1 hour, lots of slack here for first-time gotchas)

15. **On WSL-SRV (AnyDesk):** confirm `lane_node_server.py` shows the new Pi connected: `Node 'lane-node-21-22' registered`.
16. **Open `http://192.168.4.103:8766/`** on the laptop. Click Power On for lane 22. The AEDIKO R1 indicator should light. (Same dry-run as cutover plan Step 1 — but with all wires still NOT connected to the 8270 cabinet, so nothing physical happens at the lane.)
17. **Leave everything powered up** to soak overnight. Next day, verify Pi has been continuously connected via `curl http://192.168.4.103:8766/api/health`.

If 24h soak is clean → ready to schedule the cutover visit.
If anything is flapping → debug network / power / config before scheduling.

---

## 10. Open questions

- **Pre-install electrician?** If the wiring closet doesn't have a free outlet or rack U-space, may need a small electrical / cabinet job before infrastructure install can proceed. Survey will tell us.
- **Backup power?** WSL-SRV is on a UPS today (assumed — verify). Should the new switch also be on the same UPS? Recommend yes — total switch idle draw is ~40W, plus ~160W of PoE+ delivery, well within a 1500VA UPS budget.
- **HVAC / heat in the equipment area?** Pi 4 idle is fine in ambient up to ~40°C, but enclosed in an ABS box with no ventilation, internal temp can climb 10-15°C above ambient. If the equipment area runs hot (>30°C ambient), the enclosure may need active ventilation — add a 12V fan (powered from PoE HAT 5V via a step-up, or a small 5V fan directly) controlled by Pi temperature. Defer until soak shows whether there's a thermal issue.
- **Display strategy.** Today the overhead score monitors at each pair are driven by VDB-99 (VGA). After Phase 8 cutover, the display source needs to be Pi-based. Options:
  - **Option A:** Pi at the lane drives HDMI directly to the monitor (requires monitor to accept HDMI; many older lane monitors are VGA only — verify per pair)
  - **Option B:** Separate "display Pi" per pair, networked, browser-based — adds cost per pair (~$80 in Pi + Cat6 + PoE port)
  - **Option C:** Tablet/Chromecast/Fire TV at each pair — adds cost + non-PoE infrastructure
  - **Option D:** Centralized digital signage broadcasting all 16 pairs from one server, with per-pair playback via a thin client. Too much engineering for Phase 8a.
  - **Recommended for Phase 8a:** Option A if HDMI works (most likely; verify during site survey); else fall back to a small lane-side tablet for #1, decide before Phase 8b.
- **NTP source.** Pi nodes need accurate time for log correlation. Today they sync to public NTP (`pool.ntp.org`) via the existing internet uplink. After WSL-SRV becomes a more isolated host, may want to designate WSL-SRV as the local NTP server. Defer.

---

## Appendix A — Quick-reference part numbers

For one-click ordering during the procurement push:

| Part | Likely product page |
|---|---|
| Pi 4 4GB | rpilocator.com or Adafruit 4296 |
| Official Pi PoE+ HAT | Adafruit 4760 or DigiKey 4760 |
| TP-Link TL-SG2428P | Amazon / B&H Photo |
| Hammond 1597BSGY | Mouser 546-1597BSGY |
| 32GB SanDisk Industrial MicroSD | Mouser 698-SDSDQAF3-032G-I |
| Phoenix MKDS 5.08mm 2-pos | Mouser 651-1729128 |
| AEDIKO 8-ch relay HAT | Amazon B07Z3F3LJ8 (or current SKU) |
| AL-ZARD DST-1R8P-P | Amazon B0876NJDM3 (or current SKU) |
| Monoprice Cat6 1000ft stranded box | Monoprice 9817 (or current SKU) |
| 35mm × 200mm DIN rail | Mouser 651-1201442 (or any 35mm DIN) |

(Verify part numbers at order time — Amazon/Mouser SKUs change.)

## Appendix B — Survey deliverable template

After the pre-install survey (Section 8), create `docs/phase_8a_site_survey_2026-MM-DD.md` with:
- Photos: closet (existing rack), candidate uplink port, routing path (overhead/conduit/wall), candidate enclosure mount spots at lane 21+22, existing 8270 wire bundle, lamp circuit termination
- Decisions: switch mount location, cable routing method, enclosure mount location, cable gland positions
- Open issues: anything that needs to be resolved before scheduling the infrastructure install visit
