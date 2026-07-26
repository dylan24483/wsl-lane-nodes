# Deprecating the OEM DIELL interface board — decision + architecture

**Decided 2026-07-26 (Dylan).** Triggered by a DIELL sensor failure and the discovery that the
exact part has no North American distribution.

**Confirmed at the machine (Dylan, 2026-07-26): the DIELL interface board feeds and outputs for
the DIELL sensors and the camera, and nothing else.** That is what makes this clean — removing
it cannot break any other machine function.

---

## 1. What is being removed, and why

The ball-detect path today is:

```
DIELL sensor ──► OEM DIELL interface board ──► ~16 V signal ──► C1/C2A ──► controller
                 (powered at 42 VAC from the machine)
```

Two legacy QubicaAMF-era parts sit in that path, and **both** are sourcing dead-ends:

| Part | Qty fleet | Sourcing status |
|---|---|---|
| DIELL `LSC/AN-2C6J` sensor | **64** (2/lane) | Discontinued. **No NA distribution.** Only used German surplus (~€34–42). |
| DIELL interface board | **32** | No sourcing story at all. Carries **42 VAC**. |

Phase 8 replaces the controller, so nothing downstream requires Qubica compatibility any more.
The only real requirement is that a ball event reaches a J3 FAST opto channel. That makes the
interface board pure legacy risk with no remaining function.

**This is the same "quarantine the legacy part" pattern already approved for the C1/C2A machine
connectors** — confine what cannot be sourced, make everything else commodity. Here we can go
further and delete it outright rather than quarantine it.

## 2. The replacement path

```
commodity NPN-NO sensor ──► sinks field pin to FIELD_GND ──► J3 FAST opto channel
        ▲
        └── isolated +12 V from our enclosure
```

The board's input channel is
`FIELD_WET_V → Rin(2k2) → Dser → PC817 LED → field pin → [contact] → FIELD_GND`.
An NPN open-collector sensor drives that **directly** by sinking the field pin — it is
electrically the same event as the dry-contact closure the channel was designed for. No signal
conditioning, no interface board, no 42 VAC.

### WSL sensor specification (buy anything that meets this)

| Parameter | Requirement |
|---|---|
| Sensing method | **Retroreflective** (or through-beam if the geometry allows both sides) |
| Body | M18 threaded barrel |
| Supply | 10–30 VDC |
| Output | **NPN, normally open** |
| Protection | IP67 |
| Range | ≥ 1 m (the ST02 geometry is far shorter) |

⛔ **Do NOT use diffuse-reflective sensors** (e.g. the Amazon `E3F-DS30C4`). A bowling ball is
dark and glossy; diffuse reflectance off it is unreliable. Retroreflective is a **beam-break**
and is indifferent to ball colour and finish. Through-beam is better still.

**First replacement to buy:** Datasensing / Micro Detectors **`SSC/AN-0C`** — the documented
successor to the discontinued `LSC/AN-2C`, retroreflective, M18, 10–30 VDC, NPN-NO, IP67.
Rankin USA, ~$64.40. Buy one, prove it, then it becomes the reference part — not because it is
special, but because it is the first part to satisfy the spec above.

## 3. ⚠️ The one thing that must not be got wrong: TWO ground domains

**Sensors are field-referenced. The camera is logic-referenced. They must never share a supply.**

- **Sensors** must sink to `FIELD_GND`, so their 0 V *is* `FIELD_GND`. If they are powered from
  the PoE 12 V rail — whose 0 V is common with logic ground through the DDR-60G-5 — then
  `FIELD_GND` gets bonded to logic ground and **the TMA-0505S isolation the entire input design
  rests on is defeated.** Sensors therefore need an **isolated** 12 V supply.
- **The camera** cannot use that isolated supply. Its composite ground and power ground are
  common inside the camera, and the video path runs to the capture dongle → Pi USB → logic
  ground. Powering it from the isolated supply merely re-bonds that supply to logic through the
  video shield — the same defeat by a longer route.

```
PoE splitter 12 V ──┬── DDR-60G-5 ──► 5 V logic
                    │
                    ├── F5 ──────────► CAMERA 12 V        (logic-referenced — correct)
                    │
                    └── isolated 12 V DC-DC ── F6 ──► SENSOR 12 V
                                                      sensor 0 V = FIELD_GND
```

One isolated DC-DC module per pair, ~$15. The isolation contract survives intact.

## 4. Harness impact — smaller than expected

**+12 V never lands on J3**, because J3 is an opto-input connector, not a power connector.
**W06–W09 are unchanged** — still 2 SIG + 2 GND into J3-7/8/9/10.

What is added is **two loose-lead power pairs** out the same gland, exactly like the existing
W35–W37 J2 power leads. Wire list **Rev 4**, lead count 49 → 53:

| Lead | Colour | Class | Length | Label |
|---|---|---|---|---|
| W50 | **Violet** | L2 | 3700 | `SENSOR +12V ISO` |
| W51 | **Grey** | L2 | 3700 | `SENSOR 0V ISO` |
| W52 | **Brown** | L3 | 4700 | `CAMERA +12V` |
| W53 | **Pink** | L3 | 4700 | `CAMERA 0V` |

Four colours used on **no other lead**, so the two domains stay distinguishable through
installation and for the next technician. The RFQ instructs the vendor to keep them in separate
bundles and not lace them together.

## 5. BOM deltas

| Line | Change |
|---|---|
| **D3** fuse terminal blocks | **4 → 6 per pair** (adds F5 camera, F6 isolated sensor) · 64 → **96** fleet |
| **D4** fuses | +2 per pair — size at commissioning once sensor and camera draw are measured |
| **NEW D7** | Isolated 12 V DC-DC, ≥5 W, ~$15 · **16** (+2) |
| **E7** glands | +1 per pair for the power run, or share the sensor gland |
| **G9** (new) | Commodity retroreflective sensors — **64** (+8 spares) at ~$40–65 |
| — | **Audit finding M-21 CLOSES** — it asked for exactly this camera branch |

## 6. What this retires

- 64 sensors of no-NA-distribution exposure → commodity, any industrial distributor
- 32 interface boards with no sourcing story → **deleted**
- 42 VAC out of the ball-detect signal path
- The T-VISION dependency the pilot was still leaning on (M-21)

## 7. Still open

1. **Mechanical.** The `SSC/AN-0C` is M18 and should fit the ST02 arrangement, but the OEM
   `6J` suffix is undecoded and may indicate a custom optic, cable or calibration. Expect to
   fabricate a bracket or thread adapter; reuse the existing ST02 support and reflector where
   possible.
2. **Aim and sensitivity** must be set per lane and recorded. Retroreflective needs the
   reflector aligned; this is a commissioning step, not a bench step.
3. **Fuse sizing** for F5/F6 — measure real sensor and camera draw at the pilot first.
4. **Sensor draw vs the isolated DC-DC** — 2 sensors is trivial, but size the module once the
   chosen sensor's consumption is known.
