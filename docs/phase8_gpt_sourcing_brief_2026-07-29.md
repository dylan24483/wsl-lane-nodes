# GPT sourcing briefs — 2026-07-29 (capture device + remaining Amazon-class parts)

Written for hand-off to GPT. Two independent briefs. Both: US-stock sellers only,
delivery ≤ 2 weeks, prefer one seller per line, links required.

---

## BRIEF 1 — USB composite-video capture device, Linux-proven, ×18

**Context.** 18 Raspberry Pi 4 Model B nodes each need to capture analog composite video
(NTSC, yellow RCA, from a bowling T-Camera) over USB. Single still frames are the workload
(scoring uses stills; latency and audio are irrelevant; 720×480 is plenty). A VIXLW-brand
unit (~$46) worked, but it was only ever tested on **Windows** — its Linux behavior is
unknown, and cheap capture sticks routinely ship Windows-only chipsets.

**Hard requirements — a candidate fails unless ALL are met:**
1. Composite (CVBS) NTSC input via RCA; USB 2.0 output.
2. Works on **Raspberry Pi OS (Debian Bookworm, 64-bit) out of the box**: enumerates as a
   V4L2 device (`/dev/video0`) with NO vendor driver install. That means either
   (a) a true **UVC-class** device, or (b) a chipset with a **mainline Linux kernel
   driver** — known-good chipsets: **UTV007 (`usbtv` driver)**, **STK1160**, **CX231xx**.
3. Purchasable today: **18+ units** from one US seller (Amazon/B&H/etc.), ≤ $50/unit
   (prefer ≤ $20).

**Evidence bar.** For each candidate, cite at least TWO independent sources showing Linux /
Raspberry Pi use (forum thread, review, Reddit, blog, `lsusb` output naming the chipset) —
OR a listing that names the chipset outright. "Plug and play" in an Amazon listing is NOT
evidence; those claims usually mean Windows.

**Deliverable.** 2–3 ranked candidates: listing URL, price, stock signal, chipset (with the
evidence quoted/linked), and any known NTSC quirks. We will still bench-test ONE unit on a
Pi before buying the fleet quantity — rank by probability of passing that test.

---

## BRIEF 2 — remaining parts, exact specs (find one US listing each, qty in bold)

| # | Item | Spec — every clause is an acceptance criterion |
|---|---|---|
| 1 | USB-C power pigtail ×**18** | USB-C male plug → 2-wire bare/tinned open end (we crimp our own ferrules). Length **450–700 mm** (600 ideal; up to 1 m ONLY if ≥ 20 AWG). Conductors **≥ 20 AWG preferred** (24 AWG acceptable only ≤ 600 mm). 5 V / 3 A rated. Power-only is fine — no data, no e-marker. Powers a Raspberry Pi 4B from a DIN-rail 5 V supply. |
| 2 | Composite video cable ×**36** | Single RCA male–male, **75 Ω video coax** (RG59 or mini-RG59 construction — NOT thin "A/V audio" cable), **20 ft** (16–20 ft acceptable), moulded plugs. One seller must hold 36+. |
| 3 | Cable glands ×**108 M20** + ×**90 M16** | Nylon PA66, **IP68**, dome nut, WITH locknuts + sealing O-rings. M20 clamp range ~6–12 mm; M16 ~4–8 mm. Black or grey. |
| 4 | Fans ×**18** | **40 × 40 × 10 mm, 5 VDC, BALL bearing** (not sleeve), ~0.5–1 W, 2-wire, continuous duty. Quiet preferred. |
| 5 | Breather plugs ×**16** | **M12 Gore-type membrane vent plug**, nylon, IP67+, with locknut. |
| 6 | Cat6 patch ×**18** | ~**0.5 m** (0.3–0.6 m), snagless boot, stranded OK (in-enclosure patch, splitter → Pi). |
| 7 | Split loom ×**~136 m** | **10 mm (3/8") ID**, slit polyethylene loom. Bulk spools fine. |
| 8 | Adhesive tie mounts ×**400** + cable ties ×**500** | Mounts ~19–28 mm square, adhesive-backed, screw-hole preferred; ties 4 in nylon. |
| 9 | ESD bleed studs ×**16** | M4 brass stud/bolt + nut hardware, PLUS ×20 **1 MΩ 1 W** axial resistors (metal film fine). (Assembled on site — just find the two components.) |
| 10 | Hook-up wire, UL1007 **22 AWG** | Spools (≥100 ft each) in **VIOLET, GREY, BROWN, PINK** — these exact colors are a wiring-code requirement (isolated-sensor pair and camera pair). Remington Industries (Amazon) is known to carry all UL1007 colors — confirm current listings. Add black/red/white if cheap. |

**Out of scope** (already ordered elsewhere): DIN rail, duct, terminal blocks, fuses,
sensors, reflectors, M12 cordsets, ferrules, 18 AWG wire, SD cards, IDC ribbon, heatsinks.


---

# RESULTS — GPT audit returned 2026-07-29, dispositioned same day

**Capture:** DO NOT fleet-order yet. Sample = **Diamond VC500 (non-SE, NOT VC500SE)** ~$39.99
— historically Geniatech OTG102 (1f4d:0102) on mainline `cx231xx`, revision-sensitive; Amazon/FBA
exposes qty ≥30. Runners-up: AVerMedia C039 (07ca:c039, cx231xx — strongest driver evidence,
over $50/OOS) · TR Video-2-Pi (UVC, exact Pi still-frame evidence, no US qty). REJECTED: VIXLW
(Windows-only evidence), generic EasyCAP (chipset roulette), current Hauppauge USB-Live2
(revision drift), Sabrent AVCPT (discontinued). **Acceptance = GPT's script:** clean Bookworm
64-bit, driver must resolve to uvcvideo/cx231xx/usbtv/stk1160, NTSC 720×480 still, **100
open/capture/close cycles** (no black/green/stale frames), dmesg clean of URB/reset/timeout,
**5 cold boots**, then the seller same-revision/VID:PID letter BEFORE the 17-unit follow-on.
If the $11 clone test unit arrives, test it with the same script — first pass wins.

**Brief-2 picks (GPT):** uxcell USB-C 22 AWG 0.5 m ×20 (RELEASE — with the undervolt gate AND
the DDR-60G-5 output-trim mitigation: set rail ~5.15–5.2 V at commissioning, watch
`vcgencmd get_throttled` on the first pair) · Calrad **55-877-20** RCA/RG59 20 ft ×36 (HOLD:
36-qty confirmation from Calrad) · Beisit **M2012B ×108 + M1608B ×90** + locknuts via Aim
Dynamics (**PA66 hold WAIVED by Claude 2026-07-29** — indoor duty, any PA at IP68 acceptable;
ORDER) · Qualtek **FAD1-04010BBMW11** ×20 (Mouser) · Amphenol LTW **VENT-PS1YBK-N8001** ×16
(Mouser, ePTFE M12) · QSFPTEK 0.5 m Cat6 ×18 · ElecDirect 3/8" loom ×2×250 ft · CM75-0C
mounts ×400 · 4" ties ×500 · M4 brass screws+nuts ×25 + Yageo **FMF1WSFTE52-1M** 1 MΩ 1 W ×25
· Remington 10-color 22 AWG kit (**has NO PINK** — GPT corrected the brief; pink 100 ft spool
from Holland Computers eBay ~$9.99). Planning subtotal ~$803 + 18×VC500 $720.

**Outstanding before full release:** Calrad qty letter · Remington variant ETA · ZIP-date
check on CHECKOUT rows · VC500 sample pass + revision letter.
