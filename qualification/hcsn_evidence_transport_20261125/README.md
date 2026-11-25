# Immutable evidence in bounded gzip objects

This package changes transport only. It preserves the exact bytes of eleven evidence objects from commit [`14cfd44ab6d9da581bad5363495266424c661eb4`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/14cfd44ab6d9da581bad5363495266424c661eb4). That commit remains the original publication record. No experiment, checkpoint, metric, threshold, or frozen model dependency is changed.

The repository's blob-size gate rejected ten archives and the main machine-readable summary. The current v2 format stores them in **44 genuine independent gzip members**, with decoded pieces at most **479,000 bytes** and each encoded Git object at most **480,000 bytes**. The measured largest encoded object is **478,141 bytes**. The 17,814,021 encoded bytes recover **18,389,255 original bytes**. Original archives are reconstructed byte for byte; they are not regenerated, and JSON values are not reserialized or rounded.

## Format and original identities

- [SOURCE_OBJECTS.json](SOURCE_OBJECTS.json) pins eleven original logical paths, lengths, SHA256 and original Git blob SHA1 hashes.
- [INDEX.json](INDEX.json) maps every original logical path to `<original-path>.parts.json` and binds that manifest's length and SHA256.
- Each manifest records the original whole-file identities and ordered parts with contiguous **decoded** offsets. Each part has `encoded_bytes`, `encoded_sha256`, its encoded Git blob SHA1, `decoded_bytes`, `decoded_sha256`, and `encoding: gzip-single-member`.
- Parts use `<original-path>.parts/00000.bin.gz`, and so on. Each is a valid gzip file containing exactly one member, written with timestamp zero. Encoded byte reproducibility also depends on the Python/zlib implementation; the recorded hashes define the actual published objects.
- Existing `ARCHIVE_INDEX.json`, `GIT_PUBLICATION_MANIFEST.json`, seals and publication receipts retain their historical bytes and logical filenames. Their hashes apply to the **reassembled original**, not an individual encoded part. They still describe the original 82 main archives and the separate signed-only archive.

The nine adaptation archives, the signed-only raw archive, and `hcsn_smallnet_20261124/evidence/summary/SUMMARY.json` require reassembly. Other main archives remain at their original paths. [VERIFICATION.json](VERIFICATION.json) records whole-byte equality for all eleven originals and all **403** members of the ten affected tar archives: nine × 28 plus 151 signed members, including the signed archive's own manifest.

## Verify and restore

Run from the repository root with Python 3 and the standard library:

```bash
python qualification/hcsn_evidence_transport_20261125/reassemble.py --repo-root "$PWD"
python -m unittest discover -s qualification/hcsn_evidence_transport_20261125 -p transport_tests.py -v
```

Recover the eleven originals under their repository-relative paths in a **new** directory outside the checkout:

```bash
python qualification/hcsn_evidence_transport_20261125/reassemble.py \
  --repo-root "$PWD" --output-root "$PWD/../hcsn-evidence-restored-20261125"
```

Every manifest, encoded part, decoded payload and whole-file identity is validated **before output is created**. Decoding is bounded by the declared decoded length. The verifier rejects malformed gzip, a second concatenated member, trailing encoded data, inconsistent lengths or hashes, missing/reordered parts, invalid paths, source symlinks and an existing restore directory. Output is create-only and checked again while writing. `TRANSPORT_RESTORE_RECEIPT.json` is written only after success. If inputs change between validation and writing, partial output may remain without a success receipt; preserve and inspect that failure.

To replay the main run, combine the nine restored adaptation archives with the 72 directly stored training archives and `run-metadata-and-source.tar.gz`, then extract into one new run directory according to the unchanged archive index. The signed archive remains a separate supplemental run with the `signed-control-v1/` member prefix. Reassembly and extraction do not initiate training or selection.

`create_chunks.py` checks all originals against the immutable inventory before creating a fresh output directory. It refuses an existing output namespace and enforces the encoded bound after compression. The **nine distinct** standard-library tests cover byte round trips, encoded and decoded corruption, order/path/whole-file errors, rejection of a second gzip member, and refusal to overwrite output or reuse the packing namespace.

## Retained format history and failures

[FORMAT_HISTORY.json](FORMAT_HISTORY.json) binds the original raw-part format at [`b1cc060d`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/b1cc060d617735628eab5bc396d3b829bf6f22bc). That version restored all eleven originals exactly, but Codespell treated four standalone compressed-stream fragments as text and emitted 48 diagnostics. The current version uses valid independent gzip files and explicit decoded identities. It does not add spelling exclusions, fabricate binary headers, or relax either CI gate. The original failure log, helpers and receipts are retained under `versions/raw-v1/`; use the complete old commit to replay its old format.

The first v1 preparation also failed an additional member-audit wrapper after byte restoration: it assumed 150 unprefixed signed members instead of the actual 151 prefixed files including the manifest. The unchanged retained artifacts subsequently passed the exact 403-member check. [FAILED_PREPARATION.json](FAILED_PREPARATION.json) preserves that original exit 1. The v2 preparation includes the corrected exact roster from the start and exited 0. Neither correction replays an experiment.

[DISPLAY_NORMALIZATION.json](DISPLAY_NORMALIZATION.json) preserves original/normalized identities for the nine live presentation/test copies whose extra EOF blank line failed the deterministic-merge whitespace check. Parsed JSON values and the Python AST are identical; immutable source and original archives retain the historical bytes. Live documentation also receives transport links. These copies do not replace sealed historical byte records.

[CI_SCOPE.md](CI_SCOPE.md) records the original SDK/Rust/Windows failures separately. Passing transport tests and byte replay does not establish complete current-head CI, scientific superiority, or repository-wide closure.
