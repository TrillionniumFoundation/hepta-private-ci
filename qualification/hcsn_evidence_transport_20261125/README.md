# Immutable evidence in bounded Git objects

This package changes transport only. It preserves the exact bytes of eleven evidence objects from commit [`14cfd44ab6d9da581bad5363495266424c661eb4`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/14cfd44ab6d9da581bad5363495266424c661eb4). That commit remains the original publication record. No experiment, checkpoint, metric, threshold, or frozen model dependency is changed.

The repository's blob-size gate rejected ten archives and the main machine-readable summary. The live tree replaces those eleven oversized files with **44 raw binary parts, each at most 480,000 bytes**, plus small manifests. Their combined original length is **18,389,255 bytes**. This is byte slicing: no recompression, JSON reserialization, numerical rounding, or evidence omission.

## Format and original identities

- [SOURCE_OBJECTS.json](SOURCE_OBJECTS.json) pins all eleven original logical paths, byte lengths, SHA256 hashes, and original Git blob SHA1 hashes.
- [INDEX.json](INDEX.json) is the complete live mapping from original logical path to its `<original-path>.parts.json` manifest. The index also binds each manifest's byte length and SHA256.
- Each manifest records the source commit, original whole-file identities, and the ordered parts with contiguous offsets, lengths, SHA256 and Git blob SHA1 hashes. Parts are stored at `<original-path>.parts/00000.bin`, and so on.
- Existing `ARCHIVE_INDEX.json`, `GIT_PUBLICATION_MANIFEST.json`, seals, and publication receipts retain their historical bytes and logical filenames. Their hashes apply to the **reassembled original**, not to an individual part. They still describe the original 82 main archives and the separate signed-only archive.

The nine adaptation archives, the signed-only raw archive, and `hcsn_smallnet_20261124/evidence/summary/SUMMARY.json` require reassembly. The other main archives remain directly available at their original paths. [VERIFICATION.json](VERIFICATION.json) records whole-byte equality for all eleven originals and hashes for all **403** members of the ten affected tar archives (nine × 28 plus 151 signed members, including the signed archive's own manifest).

## Verify and restore

Run from the repository root with Python 3 and the standard library. Verification reads only the tracked parts and manifests:

```bash
python qualification/hcsn_evidence_transport_20261125/reassemble.py --repo-root "$PWD"
python -m unittest discover -s qualification/hcsn_evidence_transport_20261125 -p transport_tests.py -v
```

To recover the eleven original files under their original repository-relative paths, choose a new output directory outside the checkout:

```bash
python qualification/hcsn_evidence_transport_20261125/reassemble.py \
  --repo-root "$PWD" --output-root "$PWD/../hcsn-evidence-restored-20261125"
```

The reassembler validates every manifest, part, and whole-file identity **before creating output**. It rejects reordered or missing parts, invalid paths, source symlinks, inconsistent sizes/hashes, and any preexisting output directory. Output is create-only. It verifies the content again while writing and creates `TRANSPORT_RESTORE_RECEIPT.json` only after success. If inputs change between validation and writing, partial output may remain without a success receipt; inspect and retain that failure instead of treating it as a valid restore.

For replay of the main run, combine the nine restored adaptation archives with the 72 directly stored training archives and the directly stored `run-metadata-and-source.tar.gz`, then extract them into one new run directory according to the unchanged archive index. The signed archive is a separate supplemental run and retains its `signed-control-v1/` directory prefix. Reassembly and extraction do not initiate training or test selection.

`create_chunks.py` is the deterministic publication helper. Its caller must provide an exclusively owned fresh output namespace; the actual preparation created a new directory before staging the helper and writing parts. It checks all source files against the immutable inventory before writing. The six standard-library tests cover binary/JSON-byte round trips, corrupt parts, order changes, path escape, incorrect whole-object hashes, and refusal to overwrite an existing restore directory.

## Retained failures and display normalization

The first preparation job successfully created and restored all eleven objects, then failed an **additional archive-member audit** because that wrapper assumed the signed tar had 150 unprefixed members. It actually contains 151 prefixed regular files, including its own manifest. [FAILED_PREPARATION.json](FAILED_PREPARATION.json) retains the original exit 1 and the already-completed restore receipt hash. A separate follow-up checked the unchanged retained artifacts against the exact 403-member roster and exited 0. This was a correction to the transport audit, with no experiment retry or artifact rewrite.

[DISPLAY_NORMALIZATION.json](DISPLAY_NORMALIZATION.json) records the nine live documentation/test/audit display copies whose trailing blank line caused `git diff --cached --check` to fail. JSON values and the test's Python AST are unchanged; original bytes remain in the immutable source commit and the original evidence capsule. The README also receives transport links. These live display copies are not replacements for the sealed historical byte records.

Transport and whitespace fixes address two concrete PR integration failures. They do not by themselves certify the unrelated Rust, Windows, SDK timing, or aggregate CI jobs; current-head hosted checks remain authoritative for integration status.
