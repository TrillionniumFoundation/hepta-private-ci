# Exact evidence restoration

Before running existing audits, restore the bundled `development_01, development_02_layout_failure, development_03_layout_fixed, confirmation_01` trees from the component directory:

```sh
python tools/hcsn/planner_r19_20261101/restore_evidence.py
```

Run that command from the repository root. Parts, compressed archive, every tar object and every restored file are checked by size and SHA256. The restorer rejects path traversal, linked members, symlink paths and any existing file with different bytes. Identical files are retained, so the command is idempotent. Original artifact manifests become directly checkable after restoration. The archive stores one `objects/<sha256>` payload per distinct byte string; duplicate evidence paths are restored separately. No scientific source, original report, original manifest or original evidence bytes were modified. Packaging is a transport operation and supplies no new scientific or cost claim.
