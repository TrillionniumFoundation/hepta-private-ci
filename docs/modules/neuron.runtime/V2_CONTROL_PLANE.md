# Neuron Runtime V2 control plane and recovery contract

This document defines the product control boundary around the durable V2 runtime.
It does not change the `HPTNGS02` generation-store format or the `HPTNGI02`
ordered-index format. The full checkpoint payload and full receipt remain the
canonical historical contract; optimization must not reinterpret or discard
those bytes.

## 1. Four distinct permission boundaries

| Boundary | API | May create work? | May contact provider? | May return a result for use? |
| --- | --- | ---: | ---: | ---: |
| New-work admission | `tick_guarded` | Yes, after live admission | `execute` or exact-operation `reconcile` | Only after the final live guard |
| Existing-operation recovery | `recover_operation` | No | Exact-operation `reconcile` only | No; returns administrative status/report |
| Terminal truth query | `query_operation` / `query_input_operation` | No | No | No; status is not authority |
| Result-use authorization | `query_result_guarded` | No | No | Yes, only after the live guard |

A host must not translate every error into “call `tick_guarded` again.” In
particular, `OutcomeUnknown` requires exact-operation recovery; `Failed` is a
terminal negative result; `Committed` requires a separate current-use check;
and owner poisoning requires owner reconstruction rather than a business retry.

## 2. Observed provider results are durable truth

The runtime writes a dispatch fence before provider execution. If the provider
result is later observed, the runtime persists the exact result before applying
the final current-use fence. Revocation or maintenance can therefore prevent
release, but cannot turn an observed result into an `AdmissionDenied` tombstone
or cause the same operation to be executed again.

The recovery-only path has stricter powers:

1. It requires the exact immutable input and operation identity.
2. It never prepares a new operation.
3. It never marks a new dispatch.
4. It never calls provider `execute`.
5. `Observed` is committed locally and then reported as administrative status.
6. `Unknown`, unavailable or indeterminate provider state preserves the pending
   operation.
7. A durable `NotStarted` observation, or a reservation that never crossed the
   dispatch fence, can be closed as `AdmissionDenied` while quiescing.

## 3. Agentd owner errors and required actions

| Stable code | Meaning | Required host action |
| --- | --- | --- |
| `owner_busy` | The serialized owner is currently executing or reconciling | Back off; do not create a second owner |
| `owner_poisoned` | The owner mutex was poisoned by a panic | Stop serving, reconstruct from durable stores, then resume only after reconciliation |
| `model_outcome_unknown` | Provider outcome cannot yet be proven | Call recovery with the exact operation input; never change the key |
| `pending_recovery` | Quiesce/seal, recovered-history startup or reload found unfinished obligations | Keep the generation non-writable and continue exact recovery or restore the missing historical evidence |
| `not_serving` | New-work entry was called outside `Serving` | Do not bypass the lifecycle controller |
| `generation_conflict` | Reload/recovery did not strictly advance generation or reused a generation | Correct the handoff plan; never overwrite retained history |

Compatibility methods still map owner contention to admission-unavailable and
owner poisoning to an index-poisoned runtime error. New control-plane callers
should use the classified APIs and stable control codes.

## 4. Daemon lifecycle, restart and generation handoff

`AgentdNeuronGenerationControllerV2` owns the active handle and retains sealed
historical handles for exact queries.

```text
Starting --start/reconcile--> Serving
Serving --begin_quiesce--> Quiescing
Quiescing --exact recovery + local reconcile--> Sealed
Sealed --reload strictly newer recovered generation--> Reloading --> Serving
Sealed/Quiescing --shutdown after closure--> Stopped
```

Rules:

- `prepare` is accepted only in `Serving`.
- Exact recovery is accepted in `Serving` and `Quiescing`.
- `seal` requires no pending operation and no pending witness acknowledgement.
- `reload` first verifies the successor owner can recover cleanly. On failure,
  the old generation remains sealed and active.
- A successor generation must be strictly newer.
- The previous handle is retained for historical query routing and is never used
  for new work through the controller.
- The controller does not invent recovery inputs. The durable host replay layer
  must supply the original `NeuronTickInputV1` for each pending operation.

Fresh process startup must reconstruct both sides of the topology:

```rust
let controller =
    AgentdNeuronGenerationControllerV2::from_recovered_generations(
        active_handle,
        sealed_historical_handles,
    )?;
controller.start()?;
```

`from_recovered_generations` rejects duplicate generations, the active generation
appearing in retained history, and any retained generation newer than the active
generation. `start` reconciles every retained handle before enabling service and
fails closed if a supposedly sealed generation contains a pending operation or
pending witness. It then reconciles the active handle. This preserves historical
query reachability across daemon restart instead of rebuilding only the active
owner and orphaning old generations.

`retained_generations()` and `controller_snapshot()` expose the reconstructed
topology for operations. They do not grant execution or result-release authority.

## 5. Actionable operational signals

`AgentdNeuronOperationalSnapshotV2` exposes:

- current generation and body-bundle digest;
- exact pending operation code and identity;
- process-local lower-bound age of the current `OutcomeUnknown` operation;
- pending witness count and process-local lower-bound backlog age;
- generation/index record and byte headroom;
- deltas since the previous snapshot for generation, index and witness capacity;
- owner-busy, owner-poisoned, pre-runtime rejection, runtime admission-denial and
  recovery outcome counters;
- the last runtime phase measurement.

`AgentdNeuronGenerationControllerSnapshotV2` adds lifecycle state, the active
generation and the sorted retained-generation set. This answers whether a daemon
is serving, quiescing or sealed and whether historical generations were restored,
without exposing a mutable owner.

Age values deliberately reset when the daemon owner is rebuilt. The durable
source of truth is the pending operation/witness record; the age is an
operational lower bound, not protocol evidence.

Requests rejected by `prepare` or invocation binding checks increment
`entry_rejections_before_runtime`. They are not included in `tick_guarded`
latency because they never entered the runtime.

## 6. Storage cost measurement without changing history

`NeuronRuntimeMeasurementV2` separates:

- local reconciliation;
- live admission;
- provider execution/reconciliation;
- Sparse transition and output construction;
- receipt extension, canonical encoding and payload sizing;
- generation-store commit;
- ordered-index reservation/dispatch/completion;
- witness work;
- final-use authorization.

The store and index observations retain measured sync calls and sync duration.
`store_non_sync_micros` therefore captures framing, checksums, immutable payload
copies and in-memory bookkeeping without pretending those costs are physical
sync time. This is the evidence required before considering shared immutable
payloads, segment manifests or a new format version.

No current optimization removes the full receipt-to-checkpoint payload copy or
changes recovery meaning. Any future representation change requires a new format
version, migration tests, crash-cut tests and retained historical queries.

## 7. Exact-source qualification

`.github/workflows/neuron-runtime-closure.yml` is read-only. It binds both the
source head and the prospective merge tree, then runs locked metadata/check,
strict Clippy, formatting, the diagnostic benchmark and the measurement parser.
Full logs and diagnostic JSON are retained as artifacts.

`codex-hepta-agentd` is a shared package. The Neuron lane still compiles and
lints all Agentd targets, but executes only tests whose fully-qualified names are
owned by `neuron_runtime_v2`. Full Neuron and directly owned inference suites are
executed. Unrelated Agentd owners remain the responsibility of repository-wide
CI and cannot make a Neuron-owned qualification falsely fail after all Neuron
tests have passed. The standalone `scripts/neuron/qualify.sh`, Linux x86_64,
Linux ARM and macOS lanes use the same ownership boundary.

A workflow run is evidence only for the exact source SHA and exact integration
base shown in that run. Patch application, source rewriting and validation are
not combined in the same job.

## 8. Remaining external qualification boundary

The repository diagnostics use deterministic fixtures and real files, but they
are not a production model SLA. Target-host qualification must still exercise:

- real provider latency and unknown-result behavior;
- storage-full and sync-failure injection;
- process termination at every durable cut;
- owner panic and reconstruction;
- quiesce/reload interruption;
- long-horizon generation/index/witness growth;
- backup/restore with retained success and failure history.
