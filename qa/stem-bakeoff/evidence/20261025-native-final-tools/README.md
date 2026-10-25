# Final scoped `just fix` / `just fmt`: immutable execution evidence

This package retains two already completed repository tool phases. It does not
rerun tests, models, training, a formatter, or the installer. Root owns publication.

## Actual execution

| Phase | Exit | Wall seconds | Actual changed paths | Retained log |
|---|---:|---:|---:|---:|
| scoped `just fix` | 0 | 467.168378405000 | 3 | 85,421 bytes |
| `just fmt --base 429894ac8e0818102cfdea4ad47a56e4583b2902` | 0 | 2.377556843000 | 32 | 0 bytes |

The fix command is retained verbatim in its receipt and wrapper. It uses the six
named crates, `--locked`, examples, and the qualification feature; `cargo clippy
--fix --tests` checks test targets without executing their tests. Its full log
contains warnings. Exit zero is not represented as a zero-warning result.

The formatter deliberately returns an empty buffered output on success, as shown
by the retained `scripts/format.py`. The empty log is preserved with its actual
SHA-256, receipt, source changes, and exit status.

## Source identity and patches

Both phases record HEAD `3a1431c5879d084bf49b9df67f9792af8f3acbc7` and inventories
of 9,729 entries. Entries include file bytes and modes; symlink entries hash link
text. All four original inventories are retained without rewriting.

The three fix edits contain +5/-6 lines. The formatter changes 32 paths, two of
which overlap the fix. The final cumulative diff is 33 files, +2,077/-815 lines.
`format/before-tracked.patch` is byte-identical to `fix/after-tracked.patch`.
The format after-patch is relative to the original HEAD and includes the fix;
it is not mislabeled as a formatter-only patch.

The archive contains the three original post-fix snapshots, all 33 immutable
HEAD blobs, all 33 actual post-format files, logs, receipts, statistics, wrapper,
and formatter/config sources. Each snapshot matches its recorded byte/mode hash.
Both cumulative patches were applied only to isolated evidence copies; all 33
reconstructed files match the corresponding phase inventory. Original captured
inputs remained unchanged in bytes and modes. Read access time is not claimed
unchanged. Archive metadata is normalized; retained raw receipts remain exact.

## Tool identity and independent review

Retain the original DotSlash 0.5.8 archive, install receipt and install script.
Its archive digest is `3905bd406a0b4cc5fbe69843dca96fc7937fed6109164a6d56335fbf61187120`; the archive's
binary matches the actual installed binary digest
`ff444143d03355b14fc52c473f5423d7c52ac188f1f984c167f6ebad0145ba93`. No installation was repeated.
Installation time was not recorded and remains null. This is not a hermetic
attestation of every transitive formatter/compiler dependency.

The independent mechanical-diff review and its methods are included as original
files under `independent-review/`; their hashes are in the manifest. This review
does not substitute for executing the changed source in the final independent CI.
Six Python ASTs match strictly. All 26 Rust files retain their scoped imports,
cfg and visibility; 23 retain normalized nondeclaration tokens, with three
tail-expression closure-brace changes reviewed explicitly. Trailing commas and
Bazel named-keyword ordering were reviewed. Ninety-five critical source, data,
recipe, control and contract files remain byte-identical. Rust review is lexical
plus targeted manual inspection, not compiler execution or a formal AST proof.

## Qualification boundary

The actual local v1/v2 model success belongs to source head
`3a1431c5879d084bf49b9df67f9792af8f3acbc7`; its reused 96-update training belongs
to `8a47cdd26574a85cd314fabce65cc395dbe316a8`. Those runs preceded these edits.
The [immutable program status snapshot](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f92ddcacbe21267514f5040c1df6c380a96f0643/qa/stem-bakeoff/evidence/20261025-memory-program-status)
preserves that distinction. Formatting success does not requalify model execution
on the changed source. The final exact-source CI remains **pending** in this
package and will be reported separately. No local tests were rerun after fix/fmt.
The final source was published as [PR3828](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3828),
head `33c741cb0abe5faac1d92abe5d0ac90bee4abb51`. Its 33 file SHA-256, Git blob and mode identities match
the captured post-format bytes. Root observed [CI run40149732280](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40149732280)
queued; this package contains no completed CI receipt and makes no CI-pass claim.
Python formatting changes byte-based runtime pins, so final execution must
register its current runtime digest rather than reuse the old successful pins.

All eight complete research blockers remain open; production acceptance is false.

## Archive

`native-final-tools-complete-raw.tar.xz`: **1,339,240 bytes**,
**100 regular files / 51 directories**.

SHA-256: `e8762b3ee13dc49904fb1fb740a7276a83e1eaef966503c54828c2c270bf8ac6`.

Every archive member was read back and compared against the complete payload,
including exact bytes and modes. `payload-inventory.json` inside the archive
lists every other member; its own digest is retained in the external manifest.
The capture and sealing scripts are retained for review and reproduction.
