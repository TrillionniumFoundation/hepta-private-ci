# Hepta bounded runtime optimization — source implementation and qualification

Audit base: `audit/cell-role-production-integrity-20261009` at `dd3fa3eba66501ff7884a44b6187b6bdfa063555`.

This branch is intentionally stacked on the reachable GitHub source branch.
It does **not** assume the locally authored (but currently unavailable) later
`runtime_api.rs`, `canonical_bootstrap.rs` or `hepta-agentd::metrics` files
are present. Do not merge this onto main without first reconciling the
intervening P0/P1 integration work.

## Implemented source changes

| Area | Source change | Actual production caller |
|---|---|---|
| Durable inference index | `DurableInferenceControl::commit` validates/commits one record instead of cloning the full `BTreeMap` | Existing `durable_control` caller |
| Bounded microbatch admission | `BoundedBatchSchedulerV1` with identical scope/model/generation/fence/authority/revocation, deadlines, per-batch and global byte caps; peek is stable until exact durable-ack call | **Not yet wired** to a durable batch-intent owner |
| Immutable feature buffers | `SharedFeaturesQ24V1` owns `Arc<[i64]>` and canonical length-bound digest | Scheduler only; native `NeuronTickInputV1` is unchanged |
| Generation-scoped caches | `GenerationScopedCacheV1<T>` for authority/NDU/worker/retrieval snapshots | **Not yet wired** to actual owner registry |
| NDU ref | `NduSnapshotRefV1`, payload digest/size/locator, owner generation, epoch, fence and revocation binding | **Not yet wired** to `NduAuthenticatedOwnerV1` |
| Neuron stage reference | `NeuronStageBindingV1`, digest-only context/NDU/model/feature/checkpoint | **Not yet wired** to `NeuronRuntime::tick` |
| Group-commit metrics | `BatchedMetricJournalV1`: one checksum-chained binary frame, one sync per flush, single-writer lock, replay/corrupt-frame refusal | Host must replace per-sample sink; not installed in Agentd |
| CAS/signature/CNS latency | `BatchedMetricJournalV1::measure` wraps a real synchronous operation and preserves its result separately from telemetry | **Not yet wired** to corresponding domain owners |
| 64/256/1024/4096 matrix | `ScopeMatrixTargetV1` and explicit synthetic scheduler microbenchmark | Real target-host runner/observer NOT available |

**A digest, a typed interface or a local benchmark never constitutes power-loss,
independent-host or production acceptance evidence.**

## Durability boundary for batch dispatch

The scheduler itself is strictly authority-free. The host must:

1. Persist each request intent under the canonical inference owner.
2. Peek a batch intent with `next_ready(now_ms)`, without removing requests.
3. Persist and sync the **exact** `BatchIntentV1::intent_digest` in the
   request ledger (same generation, fence and authority epoch).
4. Invoke `confirm_durable` **only after** verifying the ledger's durable ack.
5. Dispatch through the admitted worker backend. An unknown intent/terminal
   outcome must enter reconciliation, not a second invocation.

The source API does not verify the host's durable acknowledgement or
authorize model execution. The final production integration needs an
authenticated batch-ack port and a restart/replay test.

## Run source checks

```sh
cd codex-rs
just fmt
just test -p codex-hepta-infer-core
just test -p codex-hepta-ndu
just test -p codex-hepta-neuron
just fix -p codex-hepta-infer-core
```

To run the **explicitly synthetic** scope matrix (not host evidence):

```sh
cd codex-rs
cargo test -p codex-hepta-infer-core synthetic_scope_matrix -- --ignored --nocapture
```

The target-host matrix must inject a `ScopeMatrixTargetV1` implementation
that actually boots 64, 256, 1024 and 4096 scope/cell runtimes and produces
readings for:

- completion, indeterminate, duplicate and reconciliation counts;
- queue age, model and end-to-end p50/p95/p99;
- journal/witness/CAS/signature/CNS latency and bytes;
- RSS, CPU, communication bytes, fsyncs, replay throughput and write amplification;
- restart/kill/power-loss, old-generation rejection, tombstone/no-resurrection;
- signed independent observer evidence bound to exact source and host.

`run_scope_matrix_v1` refuses a self-asserted TargetHost sample unless the
injected trusted runner explicitly verifies it. The reference tests use
`SourceFixture`, never a production acceptance marker.

## Remaining P1/P2/P3

- Replace scheduler's O(active lanes) readiness scan with a measured
  deadline-aware lane heap/index **if** the matrix demonstrates a bottleneck.
- Wire batch intents/acks to the only durable inference ledger; do not
  introduce a second execution state machine.
- Bind caches and `NduSnapshotRefV1` to authenticated owner registries.
- Expose immutable feature views through the real worker ABI; do not change
  golden digest/wire semantics unintentionally.
- Place CAS/signature/CNS timing calls outside global locks and make
  metrics batches bounded, loss-aware and non-authoritative.
- After owner callsites and regression tests pass, isolate reference-only
  modules and remove stale aliases.
- Run real process kill and power-loss tests on the selected target host, with
  independent key material and observed resource metrics.

Current strict status:

```
source performance primitives: implemented on this branch, uncompiled here
canonical Agentd wiring: not implemented by this patch
target host load matrix: not executed
production evidence: not retained
Hepta/Codex production replacement: not proven
```
