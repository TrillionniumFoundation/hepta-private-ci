# `neuron.runtime` documentation entry point

Use these documents in order. This page is the canonical navigation entry; it
prevents design notes, execution dossiers and historical qualification records
from being mistaken for the current implementation contract.

1. [`V2_CONTROL_PLANE.md`](V2_CONTROL_PLANE.md) — current product contract for
   the four permission boundaries, preserving versus quiesce-closing recovery,
   invocation epoch fencing, daemon restart reconstruction, generation handoff
   and actionable signals.
2. [`V2_DURABLE_CONTROL_STATE.md`](V2_DURABLE_CONTROL_STATE.md) — checksummed
   Agentd lifecycle/topology state, atomic publication ordering and interrupted
   generation-handoff restart resolution.
3. [`V2_DEVELOPMENT.md`](V2_DEVELOPMENT.md) — durable operation lifecycle,
   filesystem boundary, measurement model and backend qualification details.
4. [`V2_RUNBOOK.md`](V2_RUNBOOK.md) — operation-state handling, capacity actions,
   incident recovery and safe generation handoff without history deletion.
5. [`TECHNICAL.md`](TECHNICAL.md) — Sparse Q24 mechanism, core data structures,
   model/body binding and the broader technical reference.
6. [`../../../qualification/module-execution-dossiers/detail/neuron.runtime.md`](../../../qualification/module-execution-dossiers/detail/neuron.runtime.md)
   — qualification scope and claim boundary.

`V2_CONTROL_PLANE.md` is authoritative where an older lifecycle paragraph in a
broader development note is less specific. `V2_DURABLE_CONTROL_STATE.md` is
authoritative for Agentd state-file publication and restart resolution.
`GAP_ANALYSIS.md` was a historical working ledger and is not present on the
current convergence head. Do not treat links or checkboxes from an earlier head
as current implementation or execution evidence.

## Current authority boundary

Source code defines the implemented behavior. The fixed source commit, fixed
integration base and completed read-only workflow define what was actually
compiled and executed. Documentation, queued or skipped jobs, generated artifacts
and historical commits are not pass receipts.

The runtime and its status/capacity APIs grant no model selection, effect,
promotion, release or activation authority. `productionImplementation`, target
host qualification, independent acceptance, canary, promotion and rollback
remain separate evidence and decision gates.

## Operational API map

- `tick_guarded`: admits new work, preserves observed provider truth, then applies
  a final current-use fence before returning the result;
- `recover_operation`: converges one exact reserved operation without creating a
  reservation or calling provider `execute`; in serving/startup mode it preserves
  a proven-unexecuted operation for a later live-admitted resume;
- `close_unexecuted_operation`: quiesce-only administrative closure for a proven
  unexecuted reservation or authoritative provider `NotStarted` result;
- `query_input_operation` / `query_operation`: determine exact operation state;
- `query_result_guarded`: applies current-use authorization to an immutable local
  result without provider work;
- `NeuronOperationStatusV2::stable_code`: low-cardinality state for logs/metrics;
- `NeuronRuntimeV2Error::stable_code`: diagnostic error family, never operation truth;
- `capacity_snapshot`: retained-record, byte-reservation and witness headroom;
- `NeuronRuntimeCapacityV2::action_code`: `serve`,
  `schedule_generation_handoff` or `backpressure`;
- `last_measurement`: provider, transition, encoding, store, index, witness and
  final-use phase diagnostics, including measured sync/non-sync separation;
- `AgentdNeuronGenerationControllerV2`: `Starting -> Serving -> Quiescing ->
  Sealed -> Reloading -> Serving`, with old generations retained for queries;
- prepared invocations capture a live execution epoch and revalidate it while
  entering the owner; quiesce invalidates stale invocations and seal requires an
  exclusive drain proof;
- `AgentdNeuronGenerationControllerV2::from_recovered_generations`: rebuilds the
  active and sealed historical topology after daemon restart and rejects
  duplicate, active or future retained generations;
- `new_with_state_path` and `from_recovered_generations_with_state_path`: publish
  and recover the checksummed lifecycle/topology record without changing runtime
  operation formats;
- `generation_state`, `read_agentd_neuron_generation_state_v2` and
  `write_agentd_neuron_generation_state_v2`: read-only projection and validated
  atomic control-state persistence; none grants execution or result-use authority;
- `AgentdNeuronGenerationControllerSnapshotV2`: lifecycle, active generation,
  retained-generation topology, live admission state, execution epoch and the
  active operational snapshot;
- `AgentdNeuronOperationalSnapshotV2`: pending-state age lower bounds, witness
  backlog age, owner rejection counters, preserving-versus-closing recovery
  counters and capacity trends.

## Qualification ownership

The Neuron qualification lanes compile and lint all Agentd targets, but execute
only Agentd tests owned by `neuron_runtime_v2`. This prevents an unrelated shared
Agentd owner from falsifying the Neuron module result. Repository-wide CI still
owns the complete Agentd test suite. Every pass claim remains bound to the exact
source SHA, integration base, candidate tree and retained logs.

For any ambiguous result, start with the exact operation key and follow the
runbook. Never recover capacity by deleting or reinterpreting V2 history.
