# Packaging and provenance

This package is an immutable local snapshot. Its generated records summarize existing evidence; they do not create a new native, source or caller run. All copied originals retain their physical bytes, including any CRLF. Historical manifests, reports and statuses are not edited to match later events. Their original absolute paths and relative references may refer to the originating scratch/desktop directories; `PACKAGE_MAP.json` maps the packaged copies.

## Original, derived and unavailable material

The complete focused log, complete GDB log and complete GDB runner log were recovered from contiguous original h.view output with duplicate/gap checks, then matched to independently recorded full original byte counts and SHA-256 values. They are indexed as exact recovered originals, with their transport receipts. Classification JSON and reconstructed assertion byte arrays are derived analyses; their raw byte ranges and hashes remain linked to the full log. The JUnit XML was read in bounded chunks from one immutable version and verified as a whole.

The original helper build JSONL (1,037,121 bytes), helper executable and original test binary are not included. Available original hashes and metadata are retained, along with full helper stderr and build/verify results. The GDB single-case XML itself was not recovered; its original hash, testcase attributes and failed result are in the original result JSON. No replacement XML is generated.

The remote six-file formatter explicitly listed `six-file-prefmt.patch` (20,396 bytes) and `complete-postimages.json.gz` as not downloaded. The local draft patch with the same basename is a different 18,862-byte object and is not substituted. The complete final 20,314-byte formatted patch and 2,148-byte formatting-only patch are included. `UNPACKAGED_REFERENCES.json` records the original remote identities.

## Source is represented by immutable blobs and patches

No standalone `.rs` files are copied. Full source-bearing formatter input/readback envelopes, compressed postimages, and the provider three-way stdout (which is a whole Rust source file) are deliberately excluded. Manifests and full patches preserve exact base/postimage Git blob identities, byte counts and SHA-256 values. Reports or checks that refer to `base/`, `work/`, `postimages/`, or `source/` require fetching those exact blobs before replay; those directories are not part of this repository evidence package. Local structural/patch checks are not Rust or native tests.

Original transport receipts can contain diagnostic source snippets or error text, but they are not used as standalone source copies. Every packaged physical artifact is strictly below 512,000 bytes. The index excludes itself to avoid a circular hash; the handoff separately gives its exact hash. Any future results must be stored in a new snapshot rather than appended to this frozen index.

## Execution attribution

The focused suite, GDB diagnosis and full Rust-index single-boundary proof executed against cc22. The single-boundary registry overlay later became the metadata-only 521 commit; that publication does not change the original execution source. The six-plus-one formatter inputs are based on exact 521 blobs, and their postimages match the later 4ab publication. Formatting is not a whole-tree 4ab test.

The static attempt names cc22 as its intended binary source but failed at the first stat operation. It did not admit/re-hash the binary or revalidate the source. The earlier GDB admission remains an independent historical original.

Native, source and caller inventories use different driver algorithms; compare each original before/after pair within that driver only. A recorded count is not promoted into a claim that an unrelated entire checkout was materialized or tested.

The prior 93-file package is published in b29869e856d08db1bfb066116a9c443376ccc57d. The prior 153-file package is published in 639f894e088cdc5b30b65ed3732dcaa0a2fbe004. Their original pending native state reflects their earlier evidence cut. This new package preserves the later failed native terminal without editing either earlier snapshot. The 397/0 full source gate remains bound only to cc22.
