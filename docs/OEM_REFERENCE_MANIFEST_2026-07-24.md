# OEM reference manifest — external controlled storage

Date: 2026-07-24

The following third-party OEM manuals are intentionally excluded from this
public source repository and from the published `fable-audit-fixes` history.
They are not runtime dependencies. The 8270 service-parts manual was also a
GitHub hard-limit violation at 168,696,814 bytes.

The verified working copies are retained outside Git at:

`C:\Users\Dylan DeYoung\Documents\Codex\phase8-publication-backup-20260724\oem-manuals`

| Repository-relative filename | Bytes | SHA-256 |
|---|---:|---|
| `docs/8270-service-parts-manual.pdf` | 168,696,814 | `bc7c6adc1e1ecbf0a81d01f94278e4c7a6d7dd76fb6445ecf30b59a0f0599a3c` |
| `docs/8270-pinspotter-operation-training-manual.pdf` | 9,955,127 | `5683ba07cadfccd7ee4c7333a2f1d93db53ba3995409ce527e94104c716072a7` |
| `docs/610-007-030, 8270 PC Board Components Manual.PDF` | 6,724,638 | `06bc8d435ec1cea6014a4eb36acc452f46a8a7996bdbb516a26f0c6a5d692273` |
| `docs/OmegaTek_Expander_Card.pdf` | 2,070,794 | `44f365aa89e97fdaff30e163eb93b6278841bbdbc6c2530363229a540bf8eb12` |
| `docs/OmegaTek_Omniboard.pdf` | 2,452,017 | `da2b6b5c16b00324ca2034d933e409591b34895aa11b85ea393ecb800d812c04` |

## Recovery and history provenance

- Preserved pre-sanitization tip: `52aec67f945c180bfaffca0ea83d2306dd92b7a5`
- Rewritten equivalent before this metadata commit:
  `ea163cd4eadb7f6c75b0586950b485c9bcb76dfe`
- Verified recovery bundle:
  `C:\Users\Dylan DeYoung\Documents\Codex\phase8-publication-backup-20260724\wsl-lane-nodes-pre-sanitize.bundle`
- Bundle SHA-256:
  `8e322e284fa78e208a905707eb1fee2dad15e0388bf376585071ac88a92f11ed`
- Full old-to-new commit translation:
  `docs/history/phase8_fable_commit_map_20260724.txt`

The bundle was verified with `git bundle verify`, cloned independently, and
checked with `git fsck --full --strict` before publication filtering. It is the
recovery authority for the unpublished original lineage and is not pushed to
GitHub.

`tools/java25/` was also removed from the unpublished feature-branch history
because it is a reproducible local toolchain cache containing large runtime
images. It was already ignored and is not required by deployed lane software.
