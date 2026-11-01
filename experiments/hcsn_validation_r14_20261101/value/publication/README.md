# Byte-preserving publication transport

This bundle retains all 24 inherited checkpoint files and 17 frozen historical
training/data records, every original actual-Qpi episode and full continuation
tree, all 112 repair worker records (including full-clock details), and the
original-tape replay inputs/results. It archives 665 members (37,097,767 original
bytes) into a deterministic tar, carried by 80 independent gzip containers.
Every shipped file is at most 480,000 bytes; the largest transport is 470,163.
Each `.tarpart.gz` is a complete valid gzip stream. Decompress its payload before
concatenating the tar fragments. Original scientific `.jsonl.gz` byte streams
are tar member payloads and are not recompressed or rewritten as member data.

## Restore and verify

From the repository root:

```bash
python experiments/hcsn_validation_r14_20261101/value/publication/pack.py restore
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -c 'from experiments.hcsn_validation_r14_20261101.value import run; from experiments.hcsn_validation_r14_20261101.value.rollout_repair import run as repair; run.verify(); repair.verify()'
```

Use `restore --destination /absolute/path` to unpack the original members to a
different **value directory**. Run the script from a complete published value
tree: both source freezes are checked before restoration. Restore verifies each
compressed/decompressed part, the full tar identity, the exact member inventory,
and every member size/hash before writing. It rejects unsafe paths, non-regular
members, escapes through symlinks, duplicate members and differing existing files.
Repeated restoration into an intact tree preserves existing identical files.

`MANIFEST.json` contains every original member SHA256 and exact byte length,
plus both immutable scientific source freeze hashes. `PUBLISH_FILES.json` in the
parent directory names every repository-relative file to upload and the raw
members intentionally excluded from direct upload. The top-level summaries,
protocols, source, independent audit reports/scripts, receipts and this transport
are published directly; models and nested raw evidence restore from the archive.

## Completed fresh-tree check and cost

Only files from the published list were copied to a new tree. All 665 original
members restored with identical SHA256, then both scientific source freezes and
all their required inputs verified there. Details are in `RESTORE_CHECK.json`.
The build, restore and verification each have full fresh-process receipts. Their
CPU times are 1.173258, 0.358197 and 0.672073 seconds, respectively (2.203528 in
total). These are publication operations, not online inference measurements.
The normal reports and receipts added after that reconstruction do not change
any source freeze, archived bytes, original evidence or restored model inputs.
