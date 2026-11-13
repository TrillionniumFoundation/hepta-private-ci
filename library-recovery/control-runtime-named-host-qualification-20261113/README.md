# Historical named-host qualification source

Status: **SOURCE_ONLY_HOLD**. This directory preserves an unfinished research
program and its exact source identity. It is outside Cargo binary discovery.

The original program at
`codex-rs/hepta-control-plane/src/bin/control-runtime-named-host-qualification.rs`
imports `PlannerStoreOptionsV1`, `PlannerStoreRecordKindV1`, and `PlannerStoreV1`.
Those APIs are not exported by the selected candidate's control-plane library.
The earlier PlannerStore research also has unresolved lifecycle and persistence
contracts. Adding exports solely to make this binary compile would not resolve
those contracts.

The Rust file is preserved byte for byte, including mode `100644`, from the
selected source head and final mechanical candidate recorded in `manifest.json`.
The original branch history remains the provenance source. This relocation does
not change Cargo configuration, automatic discovery settings, or other binaries.

## Generator reference

The only external text references in the exact candidate are in
`scripts/control_runtime_stage3_bootstrap.py`: the generated workflow template
sets `HEPTA_CONTROL_RUNTIME_RECEIPT_PATH` and invokes this binary with `cargo run`.
That generator is unchanged here. Its separate historical-automation disposition
must be tracked; this archive neither disables it nor makes its generated command
valid. It must not be treated as a tested restoration path.

## Restoration boundary

Reintroducing an active binary requires completing and reviewing the real
PlannerStore owner contract and running normal package and build validation.
The archived bytes do not establish current compilability, a successful named-host
measurement, model execution, production activation, or release authority.
