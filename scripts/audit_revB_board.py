#!/usr/bin/env python3
"""
Claude's independent topological audit of the routed Rev-B board (the Claude<->Codex
loop: verify against the LIVE board, not the report). Checks the things KiCad DRC
does NOT prove on its own:
  - the 5 net classes are actually ASSIGNED on THIS board (else the .dru
    hasNetclass() isolation rules are vacuous and "0 violations" is meaningless),
  - the safety rail reaches all 7 relay coils + pass-FET,
  - no machine OUT_* net touches the Pico,
  - GND / FIELD_GND are distinct, SAFE_* + RAIL_GATE present,
  - power-plane zones poured, M1 channel still DNP.

Run:  & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" scripts\\audit_revB_board.py kicad\\wsl-phase8b.routed-manual.kicad_pcb
"""
import sys
import collections
import pcbnew

path = sys.argv[1] if len(sys.argv) > 1 else "kicad/wsl-phase8b.routed-manual.kicad_pcb"
board = pcbnew.LoadBoard(path)

def MM(iu):
    try: return round(pcbnew.ToMM(iu), 2)
    except Exception: return iu

fails = []
def need(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond: fails.append(msg)

# ---- board stats ----
bb = board.GetBoardEdgesBoundingBox()
print(f"[board] {MM(bb.GetWidth())} x {MM(bb.GetHeight())} mm, "
      f"{board.GetCopperLayerCount()} cu layers, nets={board.GetNetCount()}")
fps = list(board.GetFootprints())
print(f"[board] footprints={len(fps)}")

# ---- net -> pads, find Pico ----
net_pads = collections.defaultdict(list)
pico = None
for fp in fps:
    ref = fp.GetReference()
    try: fpid = fp.GetFPID().GetLibItemName().wx_str()
    except Exception: fpid = ""
    if "Pico" in fpid or "Pico" in fp.GetValue():
        pico = ref
    for pad in fp.Pads():
        net_pads[pad.GetNetname()].append((ref, pad.GetPadName()))
print(f"[board] Pico ref = {pico}")

# ---- netclass assignments on THIS board (the critical check) ----
settings = board.GetDesignSettings().m_NetSettings
try: settings.RecomputeEffectiveNetclasses()
except Exception: pass
names = [str(n) for n in board.GetNetsByName().keys() if str(n)]
cls = collections.Counter()
anon = []
for n in names:
    if n.startswith("N$"): anon.append(n)
    try: c = settings.GetEffectiveNetClass(n).GetName()
    except Exception: c = "?"
    cls[c] += 1
expected = {"Logic_Signal": 80, "Logic_Power": 4, "Safety_Rail": 13,
            "Field_Sense": 66, "Machine_Output": 21}
print(f"[netclass] {dict(cls)}")
print(f"[netclass] expected {expected}")
need(cls.get("Default", 0) == 0, f"no named net fell to Default class (found {cls.get('Default', 0)})")
need(len(anon) == 0, f"no anonymous N$ nets (found {len(anon)})")
custom_total = sum(cls.get(k, 0) for k in expected)
need(custom_total == len(names),
     f"every named net ({len(names)}) is in a custom class (got {custom_total})")
for k, v in expected.items():
    need(cls.get(k, 0) == v, f"  class {k} = {v} (got {cls.get(k, 0)})")

# ---- safety rail reaches all 7 relay coils + pass-FET ----
rail = net_pads.get("RELAY_ENABLE_RAIL", [])
rail_refs = sorted(set(r for r, _ in rail))
krelays = sorted(r for r in rail_refs if r.startswith("K"))
print(f"[rail] RELAY_ENABLE_RAIL pads={len(rail)} relays={krelays}")
print(f"[rail] all refs on rail: {rail_refs}")
need(len(krelays) == 7, f"safety rail reaches 7 relay coils (got {len(krelays)}: {krelays})")
need(any(r.startswith("Q") for r in rail_refs), "safety rail reaches a pass-FET (Q*)")

# ---- no machine output on the Pico ----
out_on_pico = [(n, r, p) for n, pads in net_pads.items() if n.startswith("OUT_")
               for r, p in pads if r == pico]
need(not out_on_pico, f"no OUT_* net touches the Pico (violations: {out_on_pico})")

# ---- isolation: GND vs FIELD_GND distinct ----
need("GND" in net_pads and "FIELD_GND" in net_pads, "GND and FIELD_GND both present + distinct")
print(f"[iso] GND pads={len(net_pads.get('GND', []))} FIELD_GND pads={len(net_pads.get('FIELD_GND', []))}")

# ---- safety nets present ----
for n in ("SAFE_STOP_RETURN", "SAFE_TBSC_RETURN", "RAIL_GATE", "ARM_PERMIT", "RP2040_OK"):
    print(f"[safety] {n}: {net_pads.get(n, [])}")
need(all(n in net_pads for n in ("SAFE_STOP_RETURN", "SAFE_TBSC_RETURN", "RAIL_GATE")),
     "SAFE_STOP_RETURN + SAFE_TBSC_RETURN + RAIL_GATE present")

# ---- zones (power planes) ----
zones = list(board.Zones())
print(f"[zones] count={len(zones)}")
filled_ok = True
filled_copper_zones = 0
keepout_rule_areas = 0
for z in zones:
    try: filled = z.IsFilled()
    except Exception: filled = "?"
    try: layer = board.GetLayerName(z.GetLayer())
    except Exception: layer = z.GetLayer()
    try: area = MM(z.GetFilledArea())
    except Exception: area = "?"
    net = z.GetNetname()
    is_rule_area = not net
    print(f"  net={net!r} layer={layer} filled={filled} area_mm2={area} rule_area={is_rule_area}")
    if is_rule_area:
        keepout_rule_areas += 1
        continue
    filled_copper_zones += 1
    if filled is False:
        filled_ok = False
need(filled_copper_zones >= 1 and filled_ok, f"netted copper zones are filled ({filled_copper_zones})")
need(keepout_rule_areas >= 2, f"isolation keepout rule areas present ({keepout_rule_areas})")

# ---- M1 channel DNP intact ----
dnp = sorted(fp.GetReference() for fp in fps if (fp.IsDNP() if hasattr(fp, "IsDNP") else False))
print(f"[dnp] count={len(dnp)} {dnp}")
need(len(dnp) >= 8, f"M1 channel still DNP (>=8 DNP footprints, found {len(dnp)})")

# ---- connectivity (independent of the DRC report) ----
try:
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    for meth in ("GetUnconnectedCount", "GetRatsnestCount"):
        if hasattr(conn, meth):
            print(f"[conn] {meth}={getattr(conn, meth)()}")
            break
except Exception as e:
    print(f"[conn] {e}")

print("\nAUDIT RESULT: " + ("ALL PASS" if not fails else f"{len(fails)} FAILURE(S)"))
for f in fails:
    print("  - " + f)
sys.exit(1 if fails else 0)
