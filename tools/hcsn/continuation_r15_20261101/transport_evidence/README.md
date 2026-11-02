# Lossless R14 evidence transport

This package changes storage containers only. It reconstructs the original ZIP
bytes from commit `ad32ceac6972e811ce74802ab5c44dc63b40bd4b`; it does not retrain a
model, change a frozen scientific source file, or change an original evidence
manifest. The eight training ZIPs retain all 120 member hashes. The development
ZIP `training_141001.zip` retains its 14 member hashes.

Each original ZIP is split into raw pieces of at most 450,000 bytes. Every piece
is stored as a complete gzip file, including its own header, checksum and footer.
The 26 containers are each smaller than 500,000 bytes, below the repository's
512,000-byte blob limit. `MANIFEST.json` records the original repository path,
original Git blob, complete ZIP SHA256, original member hashes, frozen index
identity, and compressed and decompressed hashes for every container.

## Reconstruct and verify

Run from the repository root, choosing a temporary output directory:

```bash
transport_root=$(mktemp -d)
python -m tools.hcsn.continuation_r15_20261101.transport restore \
  --manifest tools/hcsn/continuation_r15_20261101/transport_evidence/MANIFEST.json \
  --destination "$transport_root"
```

This verifies all nine ZIP identities and all 134 member identities before
writing the reconstructed ZIP files under their original relative paths. It
refuses path traversal, existing symlink components, damaged containers, and
replacement of a file containing different bytes. Repeating restoration into an
already identical destination is supported. The transport operation does not
extract ZIP members.

To extract the eight training archives with the unchanged R14 implementation:

```bash
cp tools/hcsn/task_aligned_r14_20261101/archives/TRAINING_ARCHIVES.json \
  "$transport_root/tools/hcsn/task_aligned_r14_20261101/archives/"
python -m tools.hcsn.task_aligned_r14_20261101.evidence_pack restore \
  --index "$transport_root/tools/hcsn/task_aligned_r14_20261101/archives/TRAINING_ARCHIVES.json" \
  --destination "$transport_root/extracted_training"
```

The frozen development index also lists `training_141000.zip`, which is already
below the blob limit and remains at its original repository path. Full
development extraction requires copying that retained ZIP and the unchanged
development index beside the reconstructed `training_141001.zip` first.

## Reproduce packaging from original bytes

With the original ZIPs present, write to a fresh destination:

```bash
python -m tools.hcsn.continuation_r15_20261101.transport pack \
  --repository-root . \
  --index tools/hcsn/task_aligned_r14_20261101/archives/TRAINING_ARCHIVES.json \
  --index tools/hcsn/task_aligned_r14_20261101/development_archives/TRAINING_ARCHIVES.json \
  --source-commit ad32ceac6972e811ce74802ab5c44dc63b40bd4b \
  --destination /tmp/hcsn-r14-transport-rebuilt
```

Compressed bytes can depend on the Python and zlib implementation. The shipped
manifest authenticates the exact shipped containers; the recovered original ZIP
identities are independent of compression implementation.

`MANIFEST.json` contains `removal_paths`, the nine original large ZIP paths to
remove from the published tree after transport verification. Neither the pack
command nor the restore command removes any original file. Original manifests
and scientific source bytes must remain unchanged. No blob allowlist or spelling
ignore rule is required for these containers.

The R14/R15 research workflow runs the transport regressions, including a full
reconstruction of these shipped archives. Passing these checks establishes
evidence transport integrity only; it does not establish a scientific advantage
or close unrelated inherited repository failures.
