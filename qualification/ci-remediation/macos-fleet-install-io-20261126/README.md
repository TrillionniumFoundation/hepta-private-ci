# Fleet release I/O failure witness

This is a diagnostic candidate, not a permission or durability fix. No new Rust
compilation, native execution, or CI retry has qualified this candidate.

## Original evidence

The macOS Intel job `139214394580` in run `45616349339` checked out merge
`4eebcef0c284da9a1964d6c01c15c0f219f7aff9`. Its tree
`28a74dbbf9b668c4691a93c8fd15c5ae2b4c92e9` equals the complete tree of source
`4be2e45d4c90fe539abf61814fa9b362d8922881`. The original job log is 1,876,725
bytes, SHA-256 `e63d41ea1043566e4e1de91bbdfb55d3f7bdfe925be71d962d63ffc0187a2ade`.

The console contains 30 visible `PermissionDenied` / OS error 13 occurrences
across seven target labels. These are log occurrences, not 30 independent
experiments; the cancelled job did not upload complete per-test artifacts.

| Target suffix under `//codex-rs/` | Occurrences | Original error lines |
| --- | ---: | --- |
| `hepta-fleet:hepta-fleet-unit-tests` | 4 | 1503, 1506, 1509, 1512 |
| `hepta-supervisor:hepta-supervisor-unit-tests` | 19 | 2180–2234 |
| `hepta-supervisor:hepta-supervisor-restart_budget_recovery-test` | 1 | 2378 |
| `hepta-supervisor:hepta-supervisor-signed_intent_recovery-test` | 1 | 5351 |
| `hepta-supervisor:hepta-supervisor-paired_process_product-test` | 2 | 8198, 8201 |
| `hepta-agentd:hepta-agentd-five_agent_rolling_upgrade-test` | 2 | 10365, 10369 |
| `hepta-agentd:hepta-agentd-supervisord_product_e2e-test` | 1 | 10390 |

The four Fleet cases are `readonly_source_is_copied_synced_and_preserved_on_duplicate_install`,
`catalog_resolves_only_digest_bound_per_agent_allowances`,
`program_mutation_is_detected_and_release_state_survives_reopen`, and
`schema_v2_bundle_binds_both_exact_programs_and_closed_world`. Their binary
reported 37 passed and four failed. Each failure only exposed the original
`FleetRegistryError::Io`; it did not identify the failed filesystem operation.
The consumer fixtures also call `install_release` or `install_release_bundle`,
but the bare errors do not prove a shared failing syscall.

Separately, the unmodified Fleet sources previously passed 41/41 tests, zero
skips and retries, on macOS ARM64 in an isolated 70-package graph. That result
does not qualify the Intel Bazel environment. The release implementation before
this candidate has the same SHA-256 in both cuts:
`5cc3c0e86b1e5d9bd1c3e76a6b35a9c3649fb7b01ef544cd32e9fd26dbac2d49`.

## Candidate boundary

The private `release_io` module returns the exact original `Result`, without
wrapping, replacing, or reconstructing its error. In this crate's `cfg(test)`
build only, an I/O error emits a fixed operation label, `ErrorKind`, and
`raw_os_error`. The write is best effort so an unavailable stderr does not
replace the original failure. No path, program bytes, or error display text is
recorded. Successful operations produce no new output.

Witnesses cover fixture initialization/registration, source metadata, staging
and bin creation, copying, digest reads, manifest creation/write/sync, mode
changes, directory open/sync, final rename, and published catalog inspection.
Fixed outer phase labels distinguish the agentd/matrixd copy and the directory
sync roles. Existing cleanup may also emit its own failed mode operation;
interpret it after the original failed phase, not as the initiating error.

All source/destination validation, mode values, syscall order, retained writing
handle, durability operations, cleanup, and test assertions remain unchanged.
Normal library builds add no diagnostic output. In particular, Fleet compiled
as a dependency of Supervisor or Agentd does not inherit `cfg(test)` from those
crates; this candidate targets the four Fleet unit failures and does not claim
to instrument every consumer failure. There are no dependency or lock changes.

`just fmt` and `git diff --check` pass. Native diagnosis remains pending on the
same original gates; no timeout, retry, runner, or failure status is changed.
