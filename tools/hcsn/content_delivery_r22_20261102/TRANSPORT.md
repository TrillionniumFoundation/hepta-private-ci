# Exact evidence restoration

Before running existing audits, restore the bundled `calibration_01, confirmation_01, development_fit, development_fit_final, development_v1, development_v2_failure, engineering_io_fixture, inputs, masked_development_01, robust_development_01` trees from the component directory:

```sh
python tools/hcsn/content_delivery_r22_20261102/restore_evidence.py --destination experiments/hcsn_unknown_generator_r22_20261102
```

Run that command from the repository root. Parts, compressed archive, every tar object and every restored file are checked by size and SHA256. The restorer rejects path traversal, linked members, symlink paths and any existing file with different bytes. Identical files are retained, so the command is idempotent. Original artifact manifests become directly checkable after restoration. The archive stores one `objects/<sha256>` payload per distinct byte string; duplicate evidence paths are restored separately. The separately compressed file map is verified before bounded object extraction; file count is capped at 65,536 and restored bytes at 512 MiB. Actual native ELF aliases, when present, are restored separately using the component exact-binary instructions. No scientific source, original report, original manifest or original evidence bytes were modified. Packaging is a transport operation and supplies no new scientific or cost claim.

The carrier is separate from the scientific component and supplies no additional scientific samples or adoption claim. Restore explicitly into the original component path shown above.
