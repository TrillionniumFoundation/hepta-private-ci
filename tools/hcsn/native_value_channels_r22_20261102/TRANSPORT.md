# Exact evidence restoration

Before running existing audits, restore the bundled `development_01, development_02, confirmation_01` trees from the component directory:

```sh
python tools/hcsn/native_value_channels_r22_20261102/restore_evidence.py
```

Run that command from the repository root. Parts, compressed archive, every tar object and every restored file are checked by size and SHA256. The restorer rejects path traversal, linked members, symlink paths and any existing file with different bytes. Identical files are retained, so the command is idempotent. Original artifact manifests become directly checkable after restoration. The archive stores one `objects/<sha256>` payload per distinct byte string; duplicate evidence paths are restored separately. The separately compressed file map is verified before bounded object extraction; file count is capped at 65,536 and restored bytes at 512 MiB. Actual native ELF aliases, when present, are restored separately using the component exact-binary instructions. No scientific source, original report, original manifest or original evidence bytes were modified. Packaging is a transport operation and supplies no new scientific or cost claim.

The three ELF paths excluded here are explicitly rebuildable products listed in BUILD_PRODUCTS.json. No retained numerical output binds a resumable state to those bytes; no separate binary restoration is needed. This differs from the R20 live-runtime essential-ELF contract.
