# Complete V11 evidence packages

The original scientific evidence directories remain local. Git publication uses
the text packages below, without duplicating the original binary files.

| Package | Original tar.xz bytes | Files restored | Uncompressed file bytes | 128 KiB binary parts |
| --- | ---: | ---: | ---: | ---: |
| [Maintenance](archives/maintenance-v11/README.md) | 2,381,992 | 645 | 17,234,150 | 19 |
| [WP1 model development](archives/wp1-model-development/README.md) | 1,287,748 | 53 | 4,714,197 | 10 |
| [Content formal experiment](archives/content-v11/README.md) | 2,037,732 | 147 | 4,404,903 | 16 |
| [Structure formal experiment](archives/structure-v11/README.md) | 2,727,064 | 588 | 8,167,175 | 21 |
| [Task formal experiment](archives/tasks-v11/README.md) | 2,081,164 | 1,320 | 7,346,729 | 16 |
| [Independent task cost replay](archives/task-cost-replay-v11/README.md) | 111,700 | 57 | 621,867 | 1 |
| [Two-process migration verification](archives/migration-v11/README.md) | 31,428 | 38 | 826,269 | 1 |
| [First two native CI failures](archives/native-attempts-v11-early/README.md) | 349,728 | 29 | 2,904,796 | 3 |
| [Successful scoped native CI](archives/native-success-v11/README.md) | 443,032 | 27 | 3,590,216 | 4 |

Each package contains `MANIFEST.json`, a complete `INVENTORY.json` with every file
size and SHA-256, the base64 parts, `ARCHIVE.sha256`, `SHA256SUMS`, and restoration
instructions. A full part represents 131,072 binary bytes and occupies 174,765
UTF-8 text bytes including its newline.

No result is selected by sign or success when packaging. Optimizer states,
SQLite evidence ledgers, source snapshots, original manifests, checkpoints,
failed runs, and negative results present in each declared archive are retained.
No external pretrained model is fetched or followed. Directory packaging rejects
symlinks and special files; referenced external model assets remain external.

## Restore and verify

From this directory:

```bash
python restore.py --package archives/maintenance-v11 --verify-only
python restore.py --package archives/maintenance-v11 --output restored/v11-maintenance-formal-01
python restore.py --package archives/wp1-model-development --output restored/wp1-model-development
python restore.py --package archives/content-v11 --output restored/content-v11
python restore.py --package archives/structure-v11 --output restored/structure-v11
python restore.py --package archives/tasks-v11 --output restored/tasks-v11
python restore.py --package archives/task-cost-replay-v11 --output restored/task-cost-replay-v11
python restore.py --package archives/migration-v11 --output restored/migration-v11
python restore.py --package archives/native-attempts-v11-early --output restored/native-attempts-v11-early
python restore.py --package archives/native-success-v11 --output restored/native-success-v11
```

Outputs must not already exist. `--archive-output PATH` additionally preserves
the reconstructed original tar.xz. The WP1 archive contains several diagnostic
directories at its root; the content archive contains its original
`v11-content-formal-01/` root. Maintenance paths are relative to its evidence
directory, without an extra prefix.

The restorer checks every text and decoded part, the whole archive SHA-256, and
the full member inventory before extracting anything. It rejects absolute
paths, `..`, Windows drive paths, duplicate or conflicting paths, symlinks,
hardlinks, and devices. Extraction is manual into a new temporary directory,
without `tar.extractall`. Every restored file is checked again for exact bytes
and SHA-256 before the completed directory is published. The default limit is
512 MiB of uncompressed file contents and 100,000 members.

The checksums protect integrity relative to the package. The Git commit or an
independently retained archive SHA provides the identity anchor; the checksums
are not a separate signature.

## Package another evidence set

For a completed directory, keep the archive outside both its source and text
package:

```bash
python pack.py --source v11-maintenance-formal-01 --archive-out /tmp/v11-maintenance-repeat.tar.xz --output archives/maintenance-repeat
```

For an already frozen archive:

```bash
python pack.py --archive /path/to/frozen-evidence.tar.xz --output archives/new-evidence
```

Existing archives are never recompressed or rewritten. An optional
`--source-manifest PATH` copies a separate existing manifest byte-for-byte into
the package. Manifests already inside the archive remain there unchanged.

New directory archives use sorted paths, zero uid/gid/mtime, empty owner names,
0644 file modes, 0755 directory modes, and fixed XZ settings. Source contents are
hashed again after archival to detect concurrent modification. Repacking the
maintenance directory produced byte-identical tar.xz bytes in the recorded
verification.

## Verification performed

All listed packages were restored into temporary directories and every file was
checked. The reconstructed tar.xz files were also compared byte-for-byte with
their original archives. Maintenance additionally passed a direct byte comparison
of all 645 restored files against the original directory and a second deterministic
archive build. Only those temporary verification directories were removed;
original evidence and tar.xz files remain available locally.

See [ARCHIVE_VERIFICATION.json](ARCHIVE_VERIFICATION.json) for the identities and
counts of the first five research packages. The independent task-cost replay
and sealed two-process migration run have their own
[supplemental verification receipt](SUPPLEMENTAL_ARCHIVE_VERIFICATION.json).
The migration package preserves the documented sealing observations; it does
not assert cross-machine transport or optimizer migration. The native failures have a separate
[verification receipt](NATIVE_EARLY_ARCHIVE_VERIFICATION.json). Their original ZIP
hashes, stable GitHub run/job/artifact metadata, original failure logs, original
receipts, and corrections are preserved. The raw second-run receipt's incorrect
`tests_executed=false` remains unchanged and is explained by its retained
`CORRECTION.json`; these early attempts are not relabeled as success.

The later successful scoped native run has its own
[verification receipt](NATIVE_SUCCESS_ARCHIVE_VERIFICATION.json). It applies to
exact commit `1bc02cb33a380cf53bb58333b2ee8b3d1a70f175`, GitHub run
`41062425475`: 517 executed cases passed, including all eight V11 cases; 24
nextest skips are recorded separately. The retained test/fix/format status and
diff files are empty. The package preserves all 24 original artifact and metadata
files and adds stable origin and packaging receipts. The original ZIP SHA-256 is
`059eb9563458675dabddbcb0e3c12ec198bf5d2acf06836511afd544d570a585`.
This is scoped lifecycle/regression validation, not trained-model quality,
production activation, or an equivalence claim for a later publication commit.

The four automated tests cover archive reproducibility and multi-part
round-trip, corrupted part rejection, path escape rejection, and link/device
rejection:

```bash
python -m unittest -v test_archive_tools.py
```
