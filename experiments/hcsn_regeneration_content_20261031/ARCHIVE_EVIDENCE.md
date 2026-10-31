# Evidence archive and verified restoration

Run only after all measured processes and evidence writers have finished.
Creation and verified restoration for this study were performed after the
measured experiments; they are excluded from model and actor timing. From the
experiment directory:

```sh
python3 archive_evidence.py create --out archives/evidence_v1
```

This archives every regular file below `evidence/`, including zero-byte stderr
and failure records, model checkpoints, and controller payloads. `__pycache__`
directories are excluded. Symlinks and special files are rejected. The output
cannot be inside `evidence/`. Source, top-level reports, and the repository's Git
metadata remain in Git at their normal locations; they are outside this package.
Directly committed checkpoints/controllers may also appear in the archive.

The new output directory contains only ordered 1 MiB parts (the last may be
shorter) and `MANIFEST.json`. The manifest records every member's relative path,
byte count and SHA-256; every part's size and SHA-256; and the combined gzip
archive's size and SHA-256. It also records the restore command and toolchain.
Upload all parts and the manifest together. No permanent duplicate aggregate
archive is required.

Member order, owner fields, mode, tar/gzip times, and gzip filename are normalized.
With identical source bytes, paths and Python/zlib toolchain, archive bytes are
deterministic. Compression may differ across toolchain versions, which are
recorded. Original filesystem timestamps and modes are not preserved. Input
size/inode/timestamps are checked while reading, and the inventory is checked
again before packaging succeeds. Do not run against a changing evidence tree.

Creation refuses an existing output directory, even an empty one. A failed
attempt may leave a partial output directory; preserve it and use a new version
directory instead of overwriting it. Temporary aggregate data lives on disk,
and file copying uses bounded chunks rather than loading the archive into RAM.
Paths must be valid UTF-8. Restore caps the JSON manifest at 64 MiB and each PAX
path/size metadata record at 1 MiB before reading it; unsupported GNU/global-PAX
and sparse extensions are rejected. Payloads remain streamed from disk.

To restore after obtaining the parts and manifest, run from the experiment root:

```sh
python3 archive_evidence.py restore --manifest archives/evidence_v1/MANIFEST.json
```

Restoration verifies every part, the aggregate archive, and every member before
restoring any evidence file. It accepts only canonical relative `evidence/`
paths and regular tar members; symlinks, hardlinks, sparse and special members
are rejected. Parent directories are opened without following symlinks. Existing
files with identical content are skipped; different content is rejected without
overwrite. New files use temporary disk files and an atomic no-replace install.
The entire existing destination is preflighted before installation. A concurrent
destination change or later I/O failure can still leave a partial restore of
previously missing files; existing files are never deliberately replaced.

Paths are relative to the script's project directory by default; either command
accepts `--root PATH` to name another existing project directory.

The manifest is an integrity inventory, not a separate authority. The published
Git commit binds the manifest and part identities. The utility requires POSIX
directory-descriptor and no-follow support, as available in the declared Linux
environment. `ARCHIVE_VERIFICATION.json` records the actual verification, and
`ARCHIVE_VERIFICATION_ATTEMPT_01.json` retains an initial invocation that correctly
rejected an absolute manifest path. Use the documented relative manifest path.
