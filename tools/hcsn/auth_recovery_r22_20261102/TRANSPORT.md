# Exact evidence restoration

Before running existing audits, restore the bundled `development01, development02, confirmation01, independent_slow_peer_01` trees from the component directory:

```sh
python tools/hcsn/auth_recovery_r22_20261102/restore_evidence.py
```

Run that command from the repository root. Parts, compressed archive, every tar object and every restored file are checked by size and SHA256. The restorer rejects path traversal, linked members, symlink paths and any existing file with different bytes. Identical files are retained, so the command is idempotent. Original artifact manifests become directly checkable after restoration. The archive stores one `objects/<sha256>` payload per distinct byte string; duplicate evidence paths are restored separately. The separately compressed file map is verified before bounded object extraction; file count is capped at 65,536 and restored bytes at 512 MiB. Actual native ELF aliases, when present, are restored separately using the component exact-binary instructions. No scientific source, original report, original manifest or original evidence bytes were modified. Packaging is a transport operation and supplies no new scientific or cost claim.
