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

Terminal truth queries, exact-operation recovery and result-use authorization
first reconcile the local generation store and ordered index only. An independent
witness outage must not hide a result already committed to `HPTNGS02`, prevent an
exact provider query for an already fenced operation, or turn that result into a
negative terminal record. `query_operation` exposes whether the witness has
acknowledged the commit. Startup, new-work execution, sealing and explicit full
`reconcile()` remain strict: they require the external witness frontier to close
and fail closed while it is unavailable or inconsistent.

A host must not translate every error into “call `tick_guarded` again.” In
particular, `OutcomeUnknown` requires exact-operation recovery; `Failed` is a
terminal negative result; `Committed` requires a separate current-use check;
and owner poisoning requires owner reconstruction rather than a business retry.

Recovery itself has two explicit policies. Ordinary/startup recovery preserves a
proven-unexecuted reservation so that the same operation can later resume under
live admission. Only a controller already in `Quiescing` may call
`close_unexecuted_operation` and write the terminal `AdmissionDenied` history
needed to seal a generation. Neither recovery policy may call provider `execute`.

## 2. Observed provider results are durable truth

The runtime writes a dispatch fence before provider execution. If the provider
result is later observed, the runtime persists the exact result before applying
the final current-use fence. Revocation or maintenance can therefore prevent
release, but cannot turn an observed result into an `AdmissionDenied` tombstone
or cause the same operation to be executed again.

The ordinary recovery path has deliberately narrow powers:

1. It requires the exact immutable input and operation identity.
2. It never prepares a new operation.
3. It never marks a new dispatch.
4. It never calls provider `execute`.
5. `Observed` is committed locally and then reported as administrative status.
6. `Unknown`, unavailable or indeterminate provider state preserves the pending
   operation.
7. A reservation without a dispatch fence remains `NotExecuted`.
8. A dispatched operation whose durable provider reports `NotStarted` remains
   recoverable under the same key and returns `OutcomeUnknown`; a later
   `tick_guarded` call must obtain live admission before resuming it.

If witness publication fails after an observed result is locally committed, the
recovery call may return a witness error while `query_operation` reports
`Committed { witness_acknowledged: false }`. This is not permission to bypass the
live result-use guard. It is the durable distinction between local terminal truth
and external anti-rollback acknowledgement; full reconciliation, daemon start
and generation seal continue to require the latter.

The quiesce-only closure path has the same restrictions, but it may convert a
proven-unexecuted reservation or authoritative provider `NotStarted` result into
an `AdmissionDenied` terminal record. It cannot close an unknown provider outcome.

## 3. Agentd owner errors and required actions

| Stable code | Meaning | Required host action |
| --- | --- | --- |
| `owner_busy` | The serialized owner is currently executing or reconciling | Back off; do not create a second owner |
| `owner_poisoned` | The owner mutex was poisoned by a panic | Stop serving, reconstruct from durable stores, then resume only after reconciliation |
| `controller_busy` | Lifecycle transition or seal cannot yet obtain its exclusive fence | Keep admission closed and retry the control action after in-flight work drains |
| `controller_poisoned` | The lifecycle or execution fence was poisoned | Stop serving and reconstruct the controller from durable handles |
| `model_outcome_unknown` | Provider outcome cannot yet be proven | Call recovery with the exact operation input; never change the key |
| `pending_recovery` | Quiesce/seal, recovered-history startup or reload found unfinished obligations | Keep the generation non-writable and continue exact recovery or restore the missing historical evidence |
| `not_serving` | New-work entry was called outside `Serving` | Do not bypass the lifecycle controller |
| `generation_conflict` | Reload/recovery did not strictly advance generation or reused a generation | Correct the handoff plan; never overwrite retained history |

A prepared invocation rejected after an epoch change returns live admission
`Revoked` and increments the dedicated stale-invocation counter. Compatibility
methods still map owner contention to admission-unavailable and owner poisoning
to an index-poisoned runtime error. New control-plane callers should use the
classified APIs and stable control codes.

## 4. Daemon lifecycle, invocation fencing and generation handoff

`AgentdNeuronGenerationControllerV2` owns the active handle and retains sealed
historical handles for exact queries.

```text
Starting --start/reconcile--> Serving
Serving --begin_quiesce/fence epoch--> Quiescing
Quiescing --exact recovery + drain + local reconcile--> Sealed
Sealed --reload strictly newer recovered generation--> Reloading --> Serving
Sealed/Quiescing --shutdown after closure--> Stopped
```

Rules:

- Controller construction closes the active handle and every retained handle.
  `start` opens only the active generation after recovery checks.
- `prepare` is accepted only in `Serving`. It captures the current execution
  epoch; invocation entry rechecks that epoch and holds a shared fence for the
  entire owner call.
- `begin_quiesce` first closes new-work admission and advances the epoch. This
  invalidates invocations prepared before maintenance, including invocations and
  handle clones retained outside the controller.
- Exact recovery in `Serving` preserves proven-unexecuted work. Exact recovery in
  `Quiescing` may close proven-unexecuted work as terminal `AdmissionDenied`.
- `seal` obtains an exclusive execution fence. If an invocation admitted by the
  prior epoch is still running, seal returns `controller_busy`; it never marks a
  generation sealed while that invocation remains in flight.
- `seal` additionally requires no pending operation and no pending witness
  acknowledgement.
- `reload` closes and drains the successor before recovery validation. On failure,
  the old generation remains sealed and active. On success, only the successor
  opens a new epoch.
- A successor generation must be strictly newer.
- The previous handle is retained for historical query routing and remains
  non-writable even through pre-existing handle clones.
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

`from_recovered_generations` validates the complete generation set before it
changes any handle gate. It rejects duplicate generations, the active generation
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
- owner-busy, owner-poisoned, pre-runtime rejection, stale-invocation rejection,
  runtime admission-denial and recovery outcome counters;
- separate counts for preserving recovery and quiesce-closing recovery;
- the last runtime phase measurement.

`AgentdNeuronGenerationControllerSnapshotV2` adds lifecycle state, active and
retained generations, whether the execution gate currently accepts new work and
the current execution epoch. This answers whether a daemon is serving, quiescing
or sealed, whether historical generations were restored, and whether an observed
invocation belongs to the current admission epoch, without exposing a mutable
owner.

Age values deliberately reset when the daemon owner is rebuilt. The durable
source of truth is the pending operation/witness record; the age is an
operational lower bound, not protocol evidence.

Requests rejected by `prepare`, invocation binding checks or a stale lifecycle
epoch increment `entry_rejections_before_runtime`. Stale epoch failures also
increment `stale_invocation_rejections`. They are not included in `tick_guarded`
latency because they never entered the runtime.

## 6. Storage cost measurement without changing history

`NeuronRuntimeMeasurementV2` separates:

- local reconciliation;
- live admission;
- provider execution/reconciliation;
- Sparse transition and output construction;
- receipt extension, canonical encoding and payload sizing;
- immutable full-receipt materialization, including the required checkpoint
  payload copy, as a nested subinterval of receipt encoding;
- generation-store commit, split into measured sync and non-sync work;
- ordered-index reservation/dispatch/completion, split into measured sync and
  non-sync work;
- witness work and measured witness sync;
- final-use authorization.

The diagnostic summary emits p50/p95/p99 for receipt encoding, full-receipt
materialization/copy, encoding excluding materialization, generation-store
non-sync work, index non-sync work, each sync boundary and total request time.
The nested materialization interval is not added twice when calculating
unclassified time. Remaining store-side clones stay visible in
`store_non_sync_micros`; they are not mislabeled as physical sync cost. This is
the evidence required before considering shared immutable payloads, segment
manifests or a new format version.

No current optimization removes the full receipt-to-checkpoint payload copy or
changes recovery meaning. Any future representation change requires a new format
version, migration tests, crash-cut tests and retained historical queries.

## 7. Exact-source qualification

`.github/workflows/neuron-runtime-closure.yml` is read-only. It binds both the
source head and the prospective merge tree, then runs locked metadata/check,
related tests, strict Clippy, formatting, the diagnostic benchmark and the
measurement parser. Full logs and diagnostic JSON are retained as artifacts.

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

The Neuron suite includes witness-isolation regressions. They require exact
provider reconciliation to remain reachable during witness read outages, require
locally durable committed truth to remain queryable after witness publication
failure, and simultaneously require explicit full reconciliation to stay
fail-closed until the witness recovers.

## 8. Remaining external qualification boundary

The repository diagnostics use deterministic fixtures and real files, but they
are not a production model SLA. Target-host qualification must still exercise:

- real provider latency and unknown-result behavior;
- storage-full and sync-failure injection;
- process termination at every durable cut;
- owner panic and reconstruction;
- stale invocation rejection and quiesce drain under real concurrent calls;
- quiesce/reload interruption;
- long-horizon generation/index/witness growth;
- backup/restore with retained success and failure history.
