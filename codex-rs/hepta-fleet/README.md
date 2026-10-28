# Fleet: technical and development guide

`codex-hepta-fleet` supplies supervisor-owned Agent registration, lifecycle and
release state plus bounded allocation/revocation helpers. It executes no model
turn, forwards no message and installs no second runtime queue. Baseline: `7673ea62`.

## Technical contract

| API | Responsibility and source |
| --- | --- |
| `FleetRegistry::{initialize,open_existing,register}` | Physical fleet/Agent directories, private registration staging, synced publication and validated owner manifests. `open_existing` may migrate legacy Matrix private directories; it is not a purely observational open. [registry.rs:56](src/registry.rs#L56), [72](src/registry.rs#L72), [119](src/registry.rs#L119). |
| `load` / `load_agent` | Global load validates every Agent and workspace isolation. Local load avoids making an unrelated corrupt peer part of this Agent's authority decision, while still validating its own state. [registry.rs:94](src/registry.rs#L94), [256](src/registry.rs#L256). |
| `compare_and_transition` | Compare the original Agent generation, validate one legal successor, and publish that generation or reject stale state. [registry.rs:183](src/registry.rs#L183). |
| Release installation/binding | Copy and sync digest-bound programs, preserve per-Agent allowance/revocation state, detect modified programs on resolution. It does not itself start an Agent. [release.rs:230](src/release.rs#L230), [395](src/release.rs#L395). |
| `calculate_local_allocation_v1` | Deterministic local candidate/share calculation with an explicitly unverified/deny-all claim boundary; not a physical capacity observer or OS resource applier. [allocation_model.rs:86](src/allocation_model.rs#L86), [allocation.rs](src/allocation.rs). |
| `LeaseLedger` / `FleetAuthorityPort` | In-memory host/grant accounting. The concrete issue port computes the allocation binding, verifies the live generic authority lease at final use, then calls `LeaseLedger::issue`. [lease_ledger.rs:119](src/lease_ledger.rs#L119), [authority_port.rs:37](src/authority_port.rs#L37). |
| `FleetRevocationCoordinator` | Track one authenticated update and a closed enrolled-node set, exact acknowledgements and convergence deadline. Missing/stale knowledge never becomes authority. [revocation_control.rs:49](src/revocation_control.rs#L49). |

Lifecycle starts at stopped/generation0. Legal transitions are stopped→starting;
starting→running/failed/stopped; running→draining/failed;
draining→stopped/failed; failed→starting/stopped. Generation overflow and invalid
transitions fail ([model.rs:131](src/model.rs#L131)). An expected-generation
comparison is not a credential and does not authorize process launch.

Registry/release records are filesystem-backed; `LeaseLedger` uses `BTreeMap`
state and is not a durable cross-process allocation service. Identical grants
can return an unchanged receipt; changed identities, stale host/lease generation,
expiry, overflow and capacity excess are rejected. Declared `ResourceBudget`
values do not prove cgroup scheduling, memory charging or DMA isolation.

| Resource/failure boundary | Baseline limit or behavior |
| --- | --- |
| Local allocation | 256 host candidates, 4,096 allocation candidates, weight at most 1,000,000. [allocation_model.rs:12](src/allocation_model.rs#L12). |
| In-memory lease ledger | 256 hosts; 16,384 grant identities. [lease_ledger.rs:7](src/lease_ledger.rs#L7). |
| Release metadata | 32 KiB manifest; 128 arguments and 65,536 argument bytes; at most 256 allowed releases. [release.rs:38](src/release.rs#L38). |
| Module catalogue | 128 modules, 64 dependencies/domains per validated list, 128-byte IDs, 4 MiB encoded catalogue; cycles and conflicting domain owners fail. [module_catalog.rs:16](src/module_catalog.rs#L16). |
| Revocation | At most 256 enrolled nodes; missing acknowledgement is catching up before the deadline and quarantined afterwards; stale feed is not ready. [revocation_control.rs:22](src/revocation_control.rs#L22). |
| Filesystem boundary | Registry/control/release paths must satisfy their physical/private checks; symlinked control files and corrupt generation chains are rejected. This is not a hostile-host or same-UID process isolation proof. |

The `hepta-fleet-leased` binary currently prints that no independent production
host/capacity observer/lease authority is configured and exits with status 64
([src/bin/hepta-fleet-leased.rs:1](src/bin/hepta-fleet-leased.rs#L1)).
Do not document it as a working fleet daemon or infer hardware allocation from
the library calculator or its tests.

## Development and verification

Start at [Cargo.toml](Cargo.toml) and [src/lib.rs](src/lib.rs), then the owning
registry, release, allocation, authority or revocation module above. Preserve
Agent/workspace isolation, independent program copies, generation comparisons
and distinct observation/authority types. Platform installation and actual
process lifecycle integration belong to the supervisor/host composition.

From repository root, with an external `CARGO_TARGET_DIR`, the original flags are:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline -p codex-hepta-fleet \
  --test-threads 2 --retries 0 --cargo-profile dev-small
```

Exact test IDs in binary `codex-hepta-fleet`:

- `registry::tests::stale_generation_is_rejected_without_appending_state` — [registry_tests.rs:103](src/registry_tests.rs#L103).
- `registry::isolation_tests::local_read_rejects_a_symlinked_control_file` — [registry_isolation_tests.rs:82](src/registry_isolation_tests.rs#L82).
- `lease_ledger::tests::conserves_capacity_and_reuses_identical_grant` — [lease_ledger_tests.rs:40](src/lease_ledger_tests.rs#L40).
- `authority_port::tests::allocation_issue_consumes_exact_live_kernel_authority_lease` — [authority_port.rs:216](src/authority_port.rs#L216).
- `release::copy_tests::readonly_source_is_copied_synced_and_preserved_on_duplicate_install` — [release_copy_tests.rs:6](src/release_copy_tests.rs#L6).

Fixtures use temporary fleet roots and controlled manifests/leases/signatures;
local calculator tests remain unverified observations. They do not establish a
deployed lease service, durable ledger restart, physical resource enforcement or
fleet daemon availability. No Rust command ran for this docs-only successor;
the package command cannot replace full 19-owner/pair qualification.
