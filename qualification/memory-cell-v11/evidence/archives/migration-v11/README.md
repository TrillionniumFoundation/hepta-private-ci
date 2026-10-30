# migration-v11 immutable evidence package

This directory contains the complete original archive as base64 text parts.
Each full part decodes to 131072 bytes (128 KiB); its text is 174,765 bytes.
The original tar.xz is **not** duplicated in Git. Optimizer states, SQLite files,
checkpoints, source snapshots, and all failed or negative results present in the
declared archive are retained. No external pretrained model is fetched, and
directory packaging refuses symlinks and special files.

- Archive: `v11-migration-functional-01-sealed.tar.xz`
- Archive bytes: 31428
- Archive SHA-256: `d71e89de06e67094e68fa44acce863620298462fa45aea2ec6b70f3cc38982a3`
- Files: 38; total file bytes: 826269
- Parts: 1; tar metadata: lexical order; uid=gid=mtime=0; modes=0644/0755

From `qualification/memory-cell-v11/evidence`:

```bash
python restore.py --package archives/migration-v11 --verify-only
python restore.py --package archives/migration-v11 --output restored/migration-v11
```

The output directory must not exist. Add `--archive-output path/to/v11-migration-functional-01-sealed.tar.xz`
to retain the reconstructed tar.xz as well. Restore verifies every text part,
decoded part, whole archive, member file byte count and SHA-256 before publishing
the restored directory. It rejects absolute paths, traversal, duplicate paths,
symlinks, hardlinks, devices, and file/directory conflicts. It never uses
`tar.extractall`. The default uncompressed bound is 512 MiB.

`INVENTORY.json` is the complete member inventory. `SHA256SUMS` checks all uploaded
text files except itself; `ARCHIVE.sha256` applies to the reconstructed archive.
Original manifests inside the tar are preserved byte-for-byte. Any explicitly
supplied side manifests are copied into `source-manifests/` without modification.
The checksums establish integrity relative to this package; the Git commit or an
independently retained archive SHA is the identity anchor.

For directory inputs, file order is lexical and tar uid/gid/mtime are zero,
user/group names empty, and modes 0644/0755. Repacking unchanged files with these
scripts produces identical tar.xz bytes. Existing tar.xz inputs are never
recompressed or rewritten.
