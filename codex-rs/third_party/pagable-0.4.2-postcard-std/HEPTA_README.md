# pagable maintenance patch

Source: [pagable 0.4.2](https://github.com/facebook/starlark-rust).
`HEPTA_SOURCE.json` records the official crate checksum, original source hashes,
changed paths, and resulting hashes. All upstream files and license notices are retained.

Declare the Postcard std/CRC features actually used by custom pagable flavors, without the unused heapless CAS backend.

The original published manifest is retained for provenance. The normalized
Cargo manifest is the manifest used by this standalone vendored package.
No public feature or runtime entry point is removed.

## Repository formatting provenance

`HEPTA-maintenance.patch` records the functional changes before formatting.
It applies to the recorded official source (or, for the existing Starlark
backport, the recorded repository base).
`HEPTA-formatting.patch` records the subsequent mechanical changes from
`just fmt`; it does not belong to the functional maintenance patch.
The source metadata records both pre-format and final hashes. Targeted tests
were run before the required final fix/format step, in the order specified by
the repository instructions.

For these recorded patches, recover the original bytes before applying: `HEPTA-maintenance.patch`.
See the [patch restoration instructions](../../../qa/repository-consolidation/20261125/vendor-maintenance-patches/README.md).
