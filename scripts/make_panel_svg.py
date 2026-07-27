"""Generate a to-scale SVG of the PANEL-W2 plywood backing panel.

Placements are parsed from docs/phase8_custom_panel_layout_2026-07-26.md so the
drawing can never silently drift from the spec table.
"""
import pathlib, re, html

REPO = pathlib.Path(r"C:\Users\Dylan DeYoung\wsl-lane-nodes")
SRC = REPO / "docs" / "phase8_custom_panel_layout_2026-07-26.md"
OUT = REPO / "docs" / "phase8_panel_W2_layout.svg"

PANEL_W, PANEL_H = 1100.0, 570.0
LAND = 25.0  # perimeter box-wall land

rows = []
for line in SRC.read_text(encoding="utf-8").split("\n"):
    if not line.startswith("| P"):
        continue
    c = [x.strip() for x in line.strip().strip("|").split("|")]
    if len(c) < 7:
        continue
    def num(s):
        m = re.search(r"-?\d+(?:\.\d+)?", s.replace("**", ""))
        return float(m.group()) if m else None
    x, y, w, h = num(c[2]), num(c[3]), num(c[4]), num(c[5])
    if None in (x, y, w, h):
        continue
    name = re.sub(r"\*\*|`", "", c[1])
    name = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    rows.append(dict(id=c[0].strip("* "), name=name, x=x, y=y, w=w, h=h,
                     tbd="MEASURE" in c[4].upper()))

# classify for colour
def kind(r):
    n = r["name"].lower()
    if "board a" in n or "board b" in n:
        return "board"
    if "duct" in n or "lacing" in n:
        return "duct"
    if "corridor" in n or "keep-clear" in n or "keep clear" in n or "band" in n or "gland" in n:
        return "zone"
    if "rail" in n:
        return "rail"
    return "module"

FILL = {"board": "#cfe3f7", "duct": "#e8e0cf", "zone": "#f4f4f4",
        "rail": "#d9d9d9", "module": "#dff0d8"}
STROKE = {"board": "#245a8d", "duct": "#8a7a48", "zone": "#b0b0b0",
          "rail": "#8a8a8a", "module": "#4a7c3f"}

S = 1.0           # 1 mm -> 1 unit
M = 70            # margin for dimensions
W = PANEL_W + 2 * M
H = PANEL_H + 2 * M

o = []
o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" '
         f'width="{W:.0f}" height="{H:.0f}" font-family="Segoe UI,Arial,sans-serif">')
o.append('<rect width="100%" height="100%" fill="#ffffff"/>')
o.append(f'<g transform="translate({M},{M})">')

# panel + land
o.append(f'<rect x="0" y="0" width="{PANEL_W}" height="{PANEL_H}" fill="#fdfaf3" '
         f'stroke="#333" stroke-width="2"/>')
o.append(f'<rect x="{LAND}" y="{LAND}" width="{PANEL_W-2*LAND}" height="{PANEL_H-2*LAND}" '
         f'fill="none" stroke="#c00" stroke-width="1" stroke-dasharray="6,4"/>')

# zones first (behind)
for r in sorted(rows, key=lambda r: 0 if kind(r) == "zone" else 1):
    k = kind(r)
    dash = ' stroke-dasharray="5,3"' if (k == "zone" or r["tbd"]) else ""
    fill = "#ffe9e9" if r["tbd"] else FILL[k]
    stroke = "#c00" if r["tbd"] else STROKE[k]
    o.append(f'<rect x="{r["x"]}" y="{r["y"]}" width="{r["w"]}" height="{r["h"]}" '
             f'fill="{fill}" fill-opacity="0.85" stroke="{stroke}" stroke-width="1.2"{dash}/>')
    label = html.escape(r["name"])[:34]
    fs = 11 if r["w"] > 150 else 9
    if r["w"] > 55 and r["h"] > 18:
        o.append(f'<text x="{r["x"]+r["w"]/2}" y="{r["y"]+r["h"]/2-2}" font-size="{fs}" '
                 f'text-anchor="middle" fill="#111">{html.escape(r["id"])}</text>')
        o.append(f'<text x="{r["x"]+r["w"]/2}" y="{r["y"]+r["h"]/2+11}" font-size="{fs-1}" '
                 f'text-anchor="middle" fill="#444">{label}</text>')
    else:
        o.append(f'<text x="{r["x"]+r["w"]/2}" y="{r["y"]-3}" font-size="8" '
                 f'text-anchor="middle" fill="#333">{html.escape(r["id"])}</text>')

# P20 placeholder - the Pi/F-1019 carrier, dimensions NOT measured
px,py,pw,ph = 502.0, 100.0, 110.0, 75.0
o.append(f'<defs><pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" '
         f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="8" '
         f'stroke="#c00" stroke-width="2" opacity="0.35"/></pattern></defs>')
o.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="url(#hatch)" '
         f'stroke="#c00" stroke-width="2" stroke-dasharray="7,4"/>')
o.append(f'<text x="{px+pw/2}" y="{py+ph/2-8}" font-size="11" text-anchor="middle" fill="#900">P20</text>')
o.append(f'<text x="{px+pw/2}" y="{py+ph/2+5}" font-size="9" text-anchor="middle" fill="#900">Pi 4B + F-1019</text>')
o.append(f'<text x="{px+pw/2}" y="{py+ph/2+17}" font-size="8.5" text-anchor="middle" fill="#c00">SIZE NOT MEASURED</text>')

# MK holes - the only precision drilling
# derive MK holes from the PARSED board positions - never hardcode, the layout has moved once already
MK = []
for r in rows:
    if r["name"].upper().startswith("BOARD "):
        for dx, dy in ((4, 4), (246, 4), (4, 236), (246, 236)):
            MK.append((r["x"] + dx, r["y"] + dy))
assert len(MK) == 8, f"expected 8 MK holes, derived {len(MK)}"
for (hx, hy) in MK:
    o.append(f'<circle cx="{hx}" cy="{hy}" r="4" fill="none" stroke="#c00" stroke-width="2"/>')
    o.append(f'<line x1="{hx-7}" y1="{hy}" x2="{hx+7}" y2="{hy}" stroke="#c00" stroke-width="0.8"/>')
    o.append(f'<line x1="{hx}" y1="{hy-7}" x2="{hx}" y2="{hy+7}" stroke="#c00" stroke-width="0.8"/>')

# overall dimensions
o.append(f'<line x1="0" y1="-22" x2="{PANEL_W}" y2="-22" stroke="#333" stroke-width="1"/>')
o.append(f'<text x="{PANEL_W/2}" y="-28" font-size="15" text-anchor="middle" fill="#111">'
         f'{PANEL_W:.0f} mm</text>')
o.append(f'<line x1="-22" y1="0" x2="-22" y2="{PANEL_H}" stroke="#333" stroke-width="1"/>')
o.append(f'<text x="-28" y="{PANEL_H/2}" font-size="15" text-anchor="middle" fill="#111" '
         f'transform="rotate(-90 -28 {PANEL_H/2})">{PANEL_H:.0f} mm</text>')

o.append('</g>')
o.append(f'<text x="{M}" y="{H-22}" font-size="15" fill="#111">'
         f'PANEL-W2 &#183; plywood backing panel &#183; 1100 &#215; 570 &#215; 19.05 mm (3/4in)'
         f' &#183; origin top-left, +x right, +y down</text>')
o.append(f'<text x="{M}" y="{H-6}" font-size="11" fill="#666">'
         f'Red dashed = 25 mm box-wall land &#183; red crosses = 8 MK board holes (242 &#215; 232, the only '
         f'precision drilling) &#183; red-filled = DIMENSION NOT YET MEASURED</text>')
o.append('</svg>')

OUT.write_text("\n".join(o), encoding="utf-8")
print(f"wrote {OUT}  ({len(rows)} placements)")
print("MK holes (M3, derived from board origins):")
for h in MK: print(f"    ({h[0]:.1f}, {h[1]:.1f})")
for r in rows:
    flag = "  <-- TBD" if r["tbd"] else ""
    print(f'  {r["id"]:<5} {r["name"][:40]:<42} x{r["x"]:>7.1f} y{r["y"]:>6.1f} '
          f'{r["w"]:>6.1f}x{r["h"]:<6.1f}{flag}')
