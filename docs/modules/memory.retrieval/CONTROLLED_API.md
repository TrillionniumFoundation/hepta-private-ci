# memory.retrieval controlled API boundary

Status: source contract; production qualification remains false.

## Default dependency surface

`codex-hepta-memory-retrieval` has no default Cargo features. A normal product dependency exposes the host-controlled recall operations:

- `recall_generated_with_engram_controlled`;
- `recall_with_engram_controlled`;
- `settle_engram_controlled`;
- `RecallWorkControlV1::bounded`;
- `product::recall_product_with_engram_v1`.

The SQLite owner adapter in `codex-hepta-memory` also requires a caller-supplied `RecallWorkControlV1`. Its historical `execute_owner_observation` name is only a deprecated bounded alias; it no longer constructs unlimited work control.

## Migration-only feature

The non-default `legacy-uncontrolled-retrieval` feature re-exports historical helpers that internally synthesize compatibility work control:

- `recall`;
- `recall_generated`;
- `recall_generated_with_engram`;
- `recall_with_engram`;
- `settle_engram`;
- V1 `retrieve`.

This feature is for controlled migration and differential testing only. Product crates, release builds, and Agentd composition must not enable it. Cargo feature unification means any dependency enabling it exposes the migration surface to the whole build, so qualification checks both the dependency declarations and the final feature graph.

## Work-control semantics

A `RecallWorkControlV1` binds one host deadline, one shared cancellation flag, and one monotonically decreasing checkpoint budget. Cloning shares the same state and cannot renew the deadline or work allowance. Interruption returns an error; it never publishes a successful partial packet.

The product caller owns the control and passes it through every adapter. Wrappers must preserve the same absolute deadline rather than creating a fresh duration. A completed wait does not imply that an operating-system blocking call has been preempted; blocking SQLite, file, vector-index, network, or FFI work still requires an interruptible primitive or an isolated worker whose late result is rejected.

## Qualification

The memory-retrieval maintenance workflow compiles and tests both contracts:

```text
cargo check --locked -p codex-hepta-memory-retrieval --no-default-features
cargo test  --locked -p codex-hepta-memory-retrieval --no-default-features --test controlled_api
cargo check --locked -p codex-hepta-memory-retrieval --no-default-features --features legacy-uncontrolled-retrieval
cargo test  --locked -p codex-hepta-memory-retrieval --no-default-features --features legacy-uncontrolled-retrieval --test controlled_api
```

The first pair is the product-facing contract. The second pair proves that the explicitly requested migration surface remains buildable without making it a default or production-approved capability.

## Claim boundary

This boundary proves source-level API admission only. It does not establish hard preemption, target-host resource isolation, a production encoder/index owner, external frontier or revocation authority, WORM evidence retention, independent acceptance, canary activation, or release approval.
