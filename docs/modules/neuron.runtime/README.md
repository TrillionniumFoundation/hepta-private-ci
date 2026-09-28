# `neuron.runtime` documentation entry point

Use these documents in order. This page is the canonical navigation entry; it
prevents design notes, execution dossiers and historical qualification records
from being mistaken for the current implementation contract.

1. [`V2_DEVELOPMENT.md`](V2_DEVELOPMENT.md) — current V2 operation lifecycle,
   durable recovery semantics, filesystem boundary, diagnostics and exact-source
   qualification requirements.
2. [`V2_CONTROL_PLANE.md`](V2_CONTROL_PLANE.md) — the four permission boundaries,
   recovery-only API, Agentd lifecycle, generation handoff and actionable signals.
3. [`V2_RUNBOOK.md`](V2_RUNBOOK.md) — operation-state handling, capacity actions,
   incident recovery and safe generation handoff without history deletion.
4. [`TECHNICAL.md`](TECHNICAL.md) — Sparse Q24 mechanism, core data structures,
   model/body binding and the broader technical reference.
5. [`GAP_ANALYSIS.md`](GAP_ANALYSIS.md) — historical gap ledger. A checked item is
   not current execution evidence; verify it against source and workflow results.
6. [`../../../qualification/module-execution-dossiers/detail/neuron.runtime.md`](../../../qualification/module-execution-dossiers/detail/neuron.runtime.md)
   — qualification scope and claim boundary.

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
  reservation or calling provider `execute`;
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
- `AgentdNeuronOperationalSnapshotV2`: pending-state age lower bounds, witness
  backlog age, owner rejection counters and capacity trends.

For any ambiguous result, start with the exact operation key and follow the
runbook. Never recover capacity by deleting or reinterpreting V2 history.
