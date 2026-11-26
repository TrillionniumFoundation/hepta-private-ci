# Starlark derive maintenance

## Repository formatting provenance

`HEPTA-maintenance.patch` records the functional changes before formatting.
It applies to the recorded official source (or, for the existing Starlark
backport, the recorded repository base).
`HEPTA-formatting.patch` records the subsequent mechanical changes from
`just fmt`; it does not belong to the functional maintenance patch.
The source metadata records both pre-format and final hashes. Targeted tests
were run before the required final fix/format step, in the order specified by
the repository instructions.

For these recorded patches, recover the original bytes before applying: `HEPTA-BLAKE3.patch`, `HEPTA-formatting.patch`, `HEPTA-maintenance.patch`.
See the [patch restoration instructions](../../../qa/repository-consolidation/20261125/vendor-maintenance-patches/README.md).
