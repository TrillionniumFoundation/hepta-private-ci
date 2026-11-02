# Exact evidence restoration

Before running existing audits, restore the bundled `source_v1, exact_run, exact_run_v2, generic_run, generic_run_v2` trees from the component directory:

```sh
python tools/hcsn/continuous_task_r20_20261101/restore_evidence.py
```

Run that command from the repository root. Parts, compressed archive, every tar object and every restored file are checked by size and SHA256. The restorer rejects path traversal, linked members, symlink paths and any existing file with different bytes. Identical files are retained, so the command is idempotent. Original artifact manifests become directly checkable after restoration. The archive stores one `objects/<sha256>` payload per distinct byte string; duplicate evidence paths are restored separately. The separately compressed file map is verified before bounded object extraction; file count is capped at 65,536 and restored bytes at 512 MiB. Actual native ELF aliases, when present, are restored separately using the component exact-binary instructions. No scientific source, original report, original manifest or original evidence bytes were modified. Packaging is a transport operation and supplies no new scientific or cost claim.
