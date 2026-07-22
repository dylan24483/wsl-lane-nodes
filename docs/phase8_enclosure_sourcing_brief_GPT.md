# Research Brief: Budget Industrial Enclosures ×16 — Find the Cheapest Compliant Option

> **⚠ REISSUED 2026-07-21 (rev-D board growth, Codex H8): hard requirement #1 is now
> ≥ 310 mm × 670 mm usable panel** (the rev-D board is 250×240, panel stack
> 20+240+150+240+20 = 670 — see `phase8_pair_enclosure_spec.md` §1/§1.1). Any candidate
> already evaluated against the old 640 mm figure must be re-checked. **Nominal
> 700-mm-class panels are MARGINAL** (≤ 30 mm headroom): report the TRUE usable panel
> height (after stud/flange intrusions), not the nominal box size, and flag anything
> under 690 mm usable as marginal. Boards inside are 250×240 mm (the "What goes inside"
> text below is updated accordingly), and the eventual backplate/lip design carries the
> row-39 bottom-edge copper keep-clear (`phase8_pair_enclosure_spec.md` §1.2).

## Mission

Find the lowest total-cost way to buy **16 (+2 spare) wall-mount industrial enclosures** in the
US that meet the hard requirements below. The incumbent pick is a **Saginaw SCE-30EL2408LP**
(30×24×8 in, NEMA 12, hinged door) at **$397–467 each** plus **$72–82** for its steel subpanel —
roughly **$470–540 per unit, ~$7,500–8,600 for the fleet**. The goal is to cut that meaningfully
— target **≤ $250/unit including a mounting panel**, without violating a hard requirement.
Rank everything by landed cost ×16.

## What goes inside (context only)

Each box mounts on a wall in the equipment area behind bowling pinsetters and houses two custom
250×240 mm control PCBs on standoffs, a Raspberry Pi 4 on DIN rail, a PoE splitter, a DIN
DC-DC converter, and fuse terminal blocks. Total heat ~20 W (sealed box is fine). Total mounted
equipment weight ~8–10 kg. Low-voltage only (48 V PoE in, 5 V logic; no mains inside the box).

## HARD requirements (a candidate failing any one is disqualified)

1. **Usable flat mounting-panel area ≥ 310 mm wide × 670 mm tall** (12.2 × 26.4 in), either
   orientation (box may hang portrait or landscape). **[REISSUED 2026-07-21 — was 640 mm;
   the rev-D board grew to 250×240.]** Nominal 30-inch-class boxes (762 mm) still satisfy
   this; **metric 700-mm-class boxes (700×500 etc.) are now MARGINAL** — a nominal 700 box
   often nets < 690 mm usable after flanges/studs, leaving ≤ 30 mm of headroom; report
   TRUE usable panel height and flag them. **Narrower-than-24-in boxes are explicitly
   welcome if the panel clears 310 mm; that is a cost lever.**
   Prefer ~60 mm of extra width beyond the 310 for wire duct, but 310–330 mm is acceptable.
2. **Interior depth ≥ 80 mm clear above the mounting panel** (DIN gear is 62 mm proud; 6-in or
   8-in nominal depth is comfortable).
3. **Accepts a flat mounting panel**: either a manufacturer subpanel (include its price) or
   obvious provision (studs/bosses) to fit a **DIY backplate** (11-ga steel or 3 mm aluminum
   sheet, ~$20–30 cut — price this option per candidate; it is allowed and encouraged).
4. **Dust protection: NEMA 12 / IP54 or better**, i.e., gasketed door/cover, no vents or louvers.
   Indoor only — no washdown, no outdoor/UV requirement. Environment is fine wood/pin dust and
   light oil mist, ambient to ~35 °C.
   - Gray area worth researching: a **NEMA 1 hinged or screw-cover box + aftermarket foam door
     gasket** at a fraction of the price. Report these separately with an honest assessment of
     the dust-seal compromise — do NOT silently count them as compliant.
5. **Hinged door strongly preferred** (routine service access; a document card is taped inside
   the door). Gasketed screw-cover/lift-off acceptable at a big enough discount, flagged as such.
6. **Material**: steel, polycarbonate, ABS, or fiberglass all acceptable. Non-metallic is
   actually mildly preferred electrically. 14–16 ga steel is fine (no heavy gear).
7. **Drillable** for ~9× M20 cable glands on the bottom face plus wall-mount holes/feet.
8. **Availability**: 16–18 identical units purchasable in the US within ~8 weeks. All 16 must be
   the SAME model (one spare-parts story). State current stock/lead time per candidate.

## Research avenues to cover (all of them)

1. **Budget industrial brands**: Wiegmann (N12 + Ultimate series), Yuco, Vevor, BUD Industries,
   Hammond commercial (EN4SD series), Integra, AttaBox, Polycase, Fibox ARCA/CAB, Adalet,
   Hubbell-Wiegmann, Global Industrial house brand, Tecnomatic, Eaton B-Line, Milbank. Check
   AutomationDirect, Zoro, Grainger (list vs street), Amazon, eBay-new, Solutions Direct,
   Blackhawk Supply, Wolf Automation, ControlsPartDepot, Wistex, Kele, Galco, Surplus Sales.
2. **Surplus / refurb**: eBay lots, Radwell/PLCCenter surplus, HGR, electrical surplus houses —
   16 identical used NEMA 12 boxes is rare but a partial fleet (e.g., 8+8 of two models) is
   acceptable ONLY if both models meet all hard specs; note this compromise explicitly.
3. **Direct import**: Alibaba/Made-in-China custom or catalog steel/poly enclosures at MOQ 16
   (typical $60–120/unit class) — include realistic freight, duty, and 6–10 week lead time in
   the landed cost, and flag quality/tolerance risk.
4. **Adjacent form factors** (evaluate honestly against the hard specs):
   - Hinged-cover polycarbonate/fiberglass "junction boxes" ≥ 700 mm class (AttaBox, Integra,
     Polycase, Stahlin).
   - Electrical **screw-cover pull boxes / CT cabinets** (Square D, Eaton, Milbank, nVent) —
     very cheap in 24×30×8, but typically NEMA 1 (see the gasket gray-area above).
   - Telecom/security wall cabinets — usually VENTED (fails dust) — only report if a gasketed,
     unvented variant exists.

## Output wanted

1. A ranked table: brand · model/PN · nominal size · panel size (and whether subpanel is
   included/extra/DIY) · rating · door type · price/unit · panel price · landed cost ×16 ·
   vendor + link · stock/lead time · compromises (if any).
2. A clear **top recommendation** at each of three tiers: (a) fully compliant cheapest,
   (b) best value if the NEMA-1-plus-gasket compromise is accepted, (c) import/MOQ play.
3. Anything within 10% of the Saginaw benchmark is not worth listing — the incumbent already
   has stock and a known supply chain; only meaningful savings justify switching.
