# `neuron.runtime` documentation entry point

Use these documents in order. This page is the canonical navigation entry; it
prevents design notes, execution dossiers and historical qualification records
from being mistaken for the current implementation contract.

1. [`V2_CONTROL_PLANE.md`](V2_CONTROL_PLANE.md) — current product contract for
   the four permission boundaries, preserving versus quiesce-closing recovery,
   invocation epoch fencing, daemon restart reconstruction, generation handoff
   and actionable signals.
2. [`V2_STARTUP_RECOVERY.md`](V2_STARTUP_RECOVERY.md) — exact startup readiness
   postcondition, lifecycle-aware recovery policy, explicit fenced closure and
   cross-platform evidence identity.
3. [`V2_DURABLE_CONTROL_STATE.md`](V2_DURABLE_CONTROL_STATE.md) — checksummed
   Agentd lifecycle/topology state, atomic publication ordering and interrupted
   generation-handoff restart resolution.
4. [`V2_SECURITY_BOUNDARY.md`](V2_SECURITY_BOUNDARY.md) — formal threat boundary,
   joint admission/provider rollback gap and acceptable closure evidence.
5. [`V2_DEVELOPMENT.md`](V2_DEVELOPMENT.md) — durable operation lifecycle,
   filesystem boundary, measurement model and backend qualification details.
6. [`V2_RUNBOOK.md`](V2_RUNBOOK.md) — operation-state handling, capacity actions,
   incident recovery and safe generation handoff without history deletion.
7. [`TECHNICAL.md`](TECHNICAL.md) — Sparse Q24 mechanism, core data structures,
   model/body binding and the broader technical reference.
8. [`../../../qualification/module-execution-dossiers/detail/neuron.runtime.md`](../../../qualification/module-execution-dossiers/detail/neuron.runtime.md)
   — qualification scope and claim boundary.

`V2_CONTROL_PLANE.md` is authoritative where an older lifecycle paragraph in a
broader development note is less specific. `V2_STARTUP_RECOVERY.md` is
authoritative for startup readiness and recovery while the execution gate is
closed. `V2_DURABLE_CONTROL_STATE.md` is authoritative for Agentd state-file
publication and restart resolution. `V2_SECURITY_BOUNDARY.md` is authoritative
for `NR-SEC-ROLLBACK-001` and its blocked claims. `GAP_ANALYSIS.md` was a
historical working ledger and is not present on the current convergence head. Do
not treat links or checkboxes from an earlier head as current implementation or
execution evidence.

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
- `prepare_decision_cell`: retains complete typed context in the existing Agentd
  invocation and canonical V2 runner, with the same owner and execution epoch;
- typed `recover_existing_decision_cell_operation`,
  `close_unexecuted_decision_cell_operation`, `query_decision_cell_operation` and
  `query_decision_cell_result_guarded`: preserve the same four permission
  boundaries with full typed request identity; see
  [`V2_DEVELOPMENT.md`](V2_DEVELOPMENT.md#typed-decisioncell-through-the-same-agentd-owner)
  for the implemented path and the still-unconnected concrete model backend;
- runtime `recover_operation`: converges one exact reserved operation without
  creating a reservation or calling provider `execute`;
- controller `recover_existing_operation`: applies one explicit lifecycle policy:
  preserve in `Starting`/`Serving`, close only proven-unexecuted work in
  `Quiescing`, and reject unrelated lifecycle states;
- controller `close_unexecuted_operation`: explicit fenced closure available only
  in `Starting` or `Quiescing`; unknown provider outcomes remain pending;
- `AgentdNeuronHandleV2::reconcile_control`: requires local reconciliation plus no
  pending operation and no pending witness acknowledgement before lifecycle
  readiness is reported;
- `query_input_operation` / `query_operation`: determine exact operation state;
- `query_result_guarded`: applies current-use authorization to an immutable local
  result without provider work;
- `NeuronOperationStatusV2::stable_code`: low-cardinality state for logs/metrics;
- `NeuronRuntimeV2Error::stable_code`: diagnostic error family, never operation truth;
- `AgentdNeuronControlErrorV2::retry_class` and `operator_action`: stable machine
  and operator advice without changing the error's authority;
- `AgentdNeuronControlFailureV2`: optional exact operation identity at the
  logging/CLI boundary while preserving the nested error source chain;
- `capacity_snapshot`: retained-record, byte-reservation and witness headroom;
- `NeuronRuntimeCapacityV2::action_code`: `serve`,
  `schedule_generation_handoff` or `backpressure`;
- `last_measurement`: provider, transition, encoding, store, index, witness and
  final-use phase diagnostics, including measured sync/non-sync separation;
- diagnostic summaries expose independent basis-point shares of request time for
  encoding, full-receipt materialization and measured sync boundaries; nested
  shares overlap and are not additive;
- `AgentdNeuronGenerationControllerV2`: `Starting -> Serving -> Quiescing ->
  Sealed -> Reloading -> Serving`, with old generations retained for queries;
- `start` keeps every gate closed and returns `pending_recovery` while the active
  or any retained generation has unresolved operation or witness work;
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
Agentd owner from falsifying the Neuron module result. Worker-host tests build and
bind the actual same-candidate Codex executable. Repository-wide CI still owns the
complete Agentd test suite.

Every lane rejects both tracked and untracked source mutation. Diagnostic samples
are bound to the actual tested commit, so a deterministic synthetic merge is not
mislabelled as the source-branch SHA. Every pass claim remains bound to the exact
source SHA, integration base, tested commit, candidate tree and retained logs.

For any ambiguous result, start with the exact operation key and follow the
runbook. Never recover capacity by deleting or reinterpreting V2 history.

## DecisionCell qualification contracts

[`SUPPORT_CALIBRATION.md`](SUPPORT_CALIBRATION.md) defines the v2 joint threshold
frontier, preserved empirical caps, artifact compatibility and frozen independent
and prospective evaluation design. It supersedes v1 sequential-search descriptions
for newly fitted artifacts, never the recorded meaning of historical receipts.

[`TEACHER_QUALIFICATION.md`](TEACHER_QUALIFICATION.md) separates retained Gateway
diagnostics from native Codex transport identity, isolation and account-specific
teacher-data rights. Neither guide adds a runtime owner or grants selection,
training admission, product qualification or activation.

## Readiness evidence is not experiment acceptance

`MODULE_SPEC.json` is the sole handwritten module-status specification. It
configures the readiness workflow and generates
`IMPLEMENTATION_MAP.generated.json`, `REQUIREMENT_TEST_MATRIX.json`,
`READINESS_DASHBOARD.md`, `PRODUCTION_ACTIVATION.json` and `DOCS_INDEX.md`.
No compatibility or historical file carries independent current implementation,
readiness or activation facts.

The minimum receipts for all eleven DecisionCell/provider/motor/training
boundaries are in
[the existing experiment contract](SUPPORT_CALIBRATION.md#minimum-acceptance-receipts-for-the-remaining-boundaries).

Provenance v2 binds exact source/base commits and the deterministic tested lane,
actual compiler release/target, platform metadata, one workflow run and attempt,
and every required prerequisite/test stage outcome. Content hashes bind the exact
lane's documentation, workflow, validator and generated map. Missing documents,
modified/untracked source, stale projections, malformed JSON, duplicate gates,
failed/skipped prerequisites and inconsistent identities cannot establish readiness.
Historical v1 records remain historical input; they are not upgraded in place.

Capture and aggregation publish new private evidence files outside the source
checkout, never overwrite an earlier receipt, and retain input evidence hashes.
`--allow-incomplete` controls diagnostic exit handling only; blockers still keep
`qualificationReady=false`. Aggregation consumes the current matrix and download
outcomes too; even complete successful per-gate records cannot make the manifest
ready after a matrix failure. The workflow's final result additionally requires
all matrix jobs, artifact download and aggregation to succeed, including
post-capture cleanup.

A metadata fingerprint is not remote attestation: local fixture records do not
prove a hosted run. The manifest explicitly leaves hosted execution independently
unverified; trusted workflow/job records and retained command logs are required.

None of these checks selects a model, grants teacher-data rights, proves independent
OOD calibration, qualifies a motor, trains a model or establishes future-window
efficacy. Production activation, independent acceptance and release stay separate.
