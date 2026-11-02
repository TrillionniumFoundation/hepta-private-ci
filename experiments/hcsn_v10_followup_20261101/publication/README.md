# Original-byte frontend evidence transport

The frontend has 1,626 NPZ files (46,161,565 original bytes), including every
candidate, failed-attempt artifact and prediction file. The original NPZ bytes
are stored as regular members of a deterministic tar container, then split into
850,000-byte slices. Each slice is separately gzip wrapped with mtime zero.
The gzip layer wraps tar bytes; no original NPZ archive is decoded or rewritten.

`MANIFEST.json` binds every original path, byte length, SHA256 and Git blob SHA,
the complete tar identity, and every compressed/uncompressed transport slice.
Fifty-six parts total 44,028,913 bytes; the largest is 835,654 bytes, below the
900,000-byte publication bound. The manifest also marks 24 original files as
`direct_copy=true`: selected weights and selected historical-test predictions.
These remain at their original paths for convenient inspection and are also
included unchanged in the full transport. All other transported NPZ files remain
locally available but need not be committed a second time as individual blobs.

From a complete checkout, reconstruct every original under its original
repository-relative path with the standard library:

```bash
python experiments/hcsn_v10_followup_20261101/publication/transport.py restore \
  --manifest experiments/hcsn_v10_followup_20261101/publication/MANIFEST.json \
  --destination .
```

Identical direct copies are reused. Conflicting existing originals are refused;
the helper never overwrites them. Paths containing traversal or symlinks are
rejected, and all slices, tar members and existing destinations are checked
before any original is installed. Atomic no-overwrite installation is used on a
controlled local filesystem. This is not a hostile concurrent-filesystem proof.

`RESTORE_VERIFICATION.json` records an actual fresh reconstruction of all 1,626
members, direct comparisons to every original, and a full identical-byte reuse
pass. All 1,628 byte/reuse checks passed. Ten negative controls rejected unsafe
paths, symlink roots/sources, conflicting destinations, changed tar inventory
and a corrupted compressed part; no original was installed by the archive
corruption controls. The original source files and transport parts were not
modified by those controls.

The pack and first fresh-restore processes have separate complete outer-worker
CPU receipts: 2.105824 and 1.020884 seconds. Further integrity/reuse controls and
development are not fully metered. This validates evidence transport only,
without changing any frontend, scientific or production acceptance decision.

The 235-line transport implementation is independent of model dependencies.
Final repository formatting is left to the root integration stage after all
component tests and audits finish.
