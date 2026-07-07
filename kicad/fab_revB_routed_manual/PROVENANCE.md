# PROVENANCE — read before trusting any filename in this tree

**This tree is the REV-C-as-ordered fab package** (JLCPCB order placed **2026-06-26**, qty **5**,
containing the G5LE-14 relay coil/contact pad remap of `phase8_revC_change_list.md` item 1 —
rail→pad 2, driver collector→pad 5, COM→pad 1, NO→pad 3, K1–K6). The board silkscreen on these
boards reads **REV-C**.

**The filenames lie:** every artifact retains the historical **`revB`** stem
(`wsl-phase8b-revB-*.zip`, `02_wsl-phase8b-revB_BOM_JLC.csv`, README headers, `manifest.json`)
because `scripts/export_fab_revB.py` hardcodes the prefix and `ensure_safe_output_dir()`
**rmtree's this directory in place on every run**.

**The true rev-B-as-ordered gerbers/BOM/CPL were overwritten by the 2026-06-26 re-export and are
unrecoverable locally** — they exist only in JLCPCB's order record for the original rev-B order.
There is no diffable as-built record of the rev-B bring-up board #1; the Jun-26 re-route means
this tree differs from that board in more than the documented relay remap.

**Rules going forward:**
- **Future spins MUST export to a NEW directory** (e.g. `kicad/fab_revC1_.../`), never regenerate
  into this one. Treat this tree as a frozen as-ordered record.
- Any stale copy of the pre-fix (dead-relay) rev-B upload zip is **name-identical** to the zips
  here — verify by generation timestamp (2026-06-26T17:31:57 in `00_README_UPLOAD.txt` /
  `manifest.json`), not by filename.

Post-order corrections applied to LOOSE files in this tree (the `.zip` archives are untouched
as-ordered artifacts):
- 2026-07-07: `JLC_UPLOAD_READY/00_README_UPLOAD.txt` "Mandatory preview checks" diode/cap line
  corrected against the BOM (was: nonexistent D18–D30 + DNP C5/C6; now: placed diodes + C11
  polarity). Same fix in `export_fab_revB.py`. Review finding #60.
