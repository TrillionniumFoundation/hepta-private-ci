# bm25 maintenance patch

Source: [bm25 2.3.2](https://github.com/Michael-JB/bm25).
`HEPTA_SOURCE.json` records the official crate checksum, original source hashes,
changed paths, and resulting hashes. All upstream files and license notices are retained.

Preserve public 32-bit, 64-bit and native-width token IDs using maintained local stable hashing.

The original published manifest is retained for provenance. The normalized
Cargo manifest is the manifest used by this standalone vendored package.
No public feature or runtime entry point is removed.

The published crate omits its CSV fixtures and its upstream repository did not
commit the six insta snapshots required by the unchanged tests. The CSV inputs
and license are recovered byte-for-byte from the crate's recorded upstream commit
8ef726045b41702e148d8996d344f3500844fde1. The retained snapshots are generated
separately with the unmodified official BM25 2.3.2 / fxhash 0.2.1 implementation.
Candidate tests run with INSTA_UPDATE=no, so the new implementation cannot rewrite
its expected outputs. HEPTA_SOURCE.json records both sources and every digest.

## Repository formatting provenance

`HEPTA-maintenance.patch` records the functional changes before formatting.
It applies to the recorded official source (or, for the existing Starlark
backport, the recorded repository base).
`HEPTA-formatting.patch` records the subsequent mechanical changes from
`just fmt`; it does not belong to the functional maintenance patch.
The source metadata records both pre-format and final hashes. Targeted tests
were run before the required final fix/format step, in the order specified by
the repository instructions.

For these recorded patches, recover the original bytes before applying: `HEPTA-formatting.patch`, `HEPTA-maintenance.patch`.
See the [patch restoration instructions](../../../qa/repository-consolidation/20261125/vendor-maintenance-patches/README.md).
