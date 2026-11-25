# WASM listener derive maintenance

This is the full published wasm_evt_listener 0.1.0 package. The official crate
checksum and all original file hashes are recorded in HEPTA_SOURCE.json.

The functional runtime-source edits replace derivative-generated trait implementations
with their standard equivalents. Listener and AttachedListener Debug preserve
field order. ListenerBuilder Clone/Debug/PartialEq/Eq preserve the original empty
event-type bounds and omit PhantomData from Debug/equality. Event registration,
unregistration, callbacks, queues, stream support, and Drop behavior are unchanged.

This closes the Matrix IndexedDB WASM dependency path as well as the native
Starlark path; the advisory policy has no new target exclusion or ignore.

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
