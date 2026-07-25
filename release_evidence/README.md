# Release evidence

`revC_design_snapshot_2026-07-19.zip` is the immutable, self-contained copy of
the 189-file Rev-C safety baseline. It contains the original `MANIFEST.json`
and every manifest member byte-for-byte. The adjacent SHA-256 sidecar is also
pinned in `scripts/verify_revC_snapshot.py`.

Run:

```powershell
py -3 scripts/verify_revC_snapshot.py --compare-checkout
```

The default gate verifies the archive digest, member topology, sizes, hashes,
CRC, and path safety. `--compare-checkout` is a separate comparison of the 173
release-tracked Rev-C paths; it ignores only checkout line-ending conversion
and the one exact frozen-record safety notice. The 16 historical tool logs are
retained inside the archive but are not source-release inputs.

To validate an expanded recovery copy, provide it explicitly:

```powershell
py -3 scripts/verify_revC_snapshot.py `
  --expanded-root C:\path\to\revC_design_snapshot_2026-07-19
```

There is no implicit dependency on the ignored local `backups/` tree.
