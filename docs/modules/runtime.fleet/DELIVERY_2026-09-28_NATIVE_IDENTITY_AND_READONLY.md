# runtime.fleet delivery: native incarnation and read-only diagnostics

This is a bounded implementation delivery record, not a qualification receipt or production acceptance. The requested three-phase remediation is not complete.

## Immutable implementation reference

Repository: `TrillionniumFoundation/hepta-private-ci`.

PR: #1060, branch `codex/runtime-fleet-durable-owner-v1-2026-09-27`.

Implementation source commit: `b17d26fb8860ae842c2ef6911218ea557598ceaa`.

This document is a later documentation commit. The implementation reference above must not be relabelled as the current branch head or as a successful exact-head check. Any subsequent source, workflow, or documentation change requires its own applicable qualification. PR #1060 remains draft; no merge or production approval is recorded here.

## Changes actually pushed in this delivery

| Commit | Change |
| --- | --- |
| `35d195c68f1754c3b8ab0de6e7e6ba3c68772662` | Wire `hepta-supervisord` native identity discovery to the existing durable host-incarnation allocator. |
| `aab55aaaaab47759815dbaac46ddcf6c5609418b` | Add an integration-test target that compiles the actual native product module, whose binary target disables its own test harness. |
| `ebb411e97a2b9eedf0b838a24d53c504183a4a43` | Use the read-only snapshot API in `hepta-fleet-status`, reject ambiguous CLI arguments, and distinguish unavailable process counters from measured zero. |
| `b17d26fb8860ae842c2ef6911218ea557598ceaa` | Add built-binary CLI tests for documented root aliases, invalid arguments, absent/damaged state, writer contention, and file-content/mtime non-mutation. |

### Native host identity

Changed source: `codex-rs/hepta-supervisor/src/fleet_runtime_product.rs`.

The boot-ID digest is an opaque identity, not a numerically ordered generation. `DurableFleetOwner::resolve_host_incarnation` allocates the ordered generation. Explicit operator generations go through the same durable fence and independently observed boot identity. Missing or invalid boot identity does not fall back to wall-clock seconds. Capacity refresh operation IDs include the host/incarnation identity so a reboot inside the same maintenance slot cannot replay the previous incarnation's refresh receipt.

Added test target: `codex-rs/hepta-supervisor/tests/runtime_fleet_product_identity.rs`. It includes the actual product module. Cases cover same-boot owner reopen, a new boot identity with a lower hash value, predecessor identity rejection, invalid identity inputs, actual Linux identity reads, and symlink rejection.

These are tests added to source, not a claim that a real host reboot or all tests passed. Reading the actual Linux boot ID twice is not equivalent to performing and verifying a host reboot.

### Read-only diagnostics and CLI contract

Changed source: `codex-rs/hepta-fleet/src/bin/hepta-fleet-status.rs`.

The status command calls `read_fleet_snapshot` rather than opening a mutable owner. It must not create an owner, repair a frontier, change permissions, or advance durable state. Missing or invalid state and writer contention are errors, not healthy empty snapshots.

From `codex-rs`, the supported command is:

```sh
cargo run -p codex-hepta-fleet --bin hepta-fleet-status -- \
  status --supervisor-state-root /absolute/fleet-root/state --format json
```

`status` is optional. `--state-root` and `--state-dir` are compatibility aliases for the supervisor state root, not a journal filename. The path must be absolute. JSON is the only supported format. Optional arguments are `--operation-id ID` and `--fail-on-alert`. Duplicate options, unknown commands, missing values, and flags used as values are errors. `preflight`, `dry-run`, and `open --allow-create` are not implemented commands and must not be used as recovery instructions.

Exit status: 0 for successful output unless an alert-triggered exit is requested; 1 for configuration or state-read errors; 2 when `--fail-on-alert` is set and the returned alert list is nonempty. Exit 2 is not limited to critical alerts.

Durable snapshot metrics and process-local counters have different provenance. Unavailable issue/renew/revoke result counters, registry-conflict counts, and indeterminate-commit counts are represented as unavailable/null, not as zero. `sampled_at_ms` identifies the snapshot sample time; it does not prove every upstream observation is fresh. An operation missing from the bounded receipt window is not proof of nonexecution.

Added test target: `codex-rs/hepta-fleet/tests/status_readonly_cli.rs`. Tests launch the built executable and compare file bytes and modification times. They also delete fixture lock/frontier files and require an error without recreation, exercise unknown arguments, and hold a writer lock while invoking diagnostics. This is not an exhaustive filesystem metadata or access-time non-mutation proof.

## Execution evidence actually observed

No local Cargo, rustfmt, or Clippy execution was performed for these changes. The editing environment did not provide a Rust toolchain or a working repository clone connection. GitHub API writes succeeded; that is not build evidence.

Historical run: `36353900589`, exact-source job `108717690980`, source `4c381df4fede72a3fbc0341131c82e969e92a031`.

The retrieved historical log reports that fleet Clippy and fleet tests passed, but Supervisor testing stopped in a shared dependency with unresolved `decode_intervention_queue_index_strict` references in `hepta-artifacts/src/intervention_index.rs`. These historical passes do not qualify `b17d26fb8860ae842c2ef6911218ea557598ceaa`. Attempts to fetch that dependency path and directory at the new source returned Not Found; the dependency was not patched in this delivery and the historical failure has not been demonstrated closed.

For implementation source `b17d26fb8860ae842c2ef6911218ea557598ceaa`, the last observed focused run was `36371339160`:

| Job | Name | Last observed status | Acceptance |
| --- | --- | --- | --- |
| `108780834112` | exact-source | queued | Not accepted; no successful receipt observed. |
| `108780834113` | synthetic-merge | queued | Not accepted; no successful receipt observed. |

These are observations made during this delivery, not live status. No merge commit/tree is claimed verified. No historical success, queued job, or added test is counted as a successful current-source execution.

## Remaining requested work

1. Resolve and re-run the full Supervisor dependency/build path on the final immutable candidate. Obtain successful exact-source and fixed-base synthetic-merge receipts, including source/merge identity, commands, exit codes, logs and artifact digests. Canonical state, implementation map, technical status and execution dossier have not been regenerated as a verified set by this delivery.
2. Replace grant-derived start requirements with an independently established actual execution context. The existing `FleetStartAdmission::verify_agent_start` still derives host identity from the grant and resource amounts from ledger state. The actual spawn/resume/adopt path must consume the same checked execution object; merely adding an unused context type is insufficient.
3. Wire durable execution holds into the real process lifecycle. Lease expiry or revocation alone is not proof of process or descendant quiescence. Retain capacity until independently established termination/recovery evidence permits release, and prove subsequent re-admission with real execution, interruption and restart tests. The earlier core hold primitives are not counted here as completed native integration.
4. Define and test degraded operation for ordinary capacity loss or temporary observation failure, separately from integrity failures. This delivery does not establish all such errors are classified correctly.
5. Measure and then improve start/recovery lock, journal, and state-read performance without weakening rollback protection or retained operation semantics. No benchmark or performance-improvement claim is made here.
6. Execute the documented CLI tests, native identity tests and complete qualification gates. Broader operator preflight/dry-run tooling, real reboot tests, full native lifecycle tests, selected-host acceptance and production approval remain unproven or unimplemented as described above.

## Completion boundary

- Source changes and test additions: pushed, scoped to this PR.
- Current-source compile/test/strict lint: not demonstrated passed.
- Fixed synthetic-merge qualification: not demonstrated passed.
- Independent native execution/termination/resource-release loop: not completed by this delivery.
- Real host reboot, selected-host and release acceptance: not demonstrated.
- Production completion: no claim.

This record must not be used to change `execution_proven`, production-readiness or independent-acceptance fields to true.
