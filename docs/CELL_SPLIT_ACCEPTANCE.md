# DecisionCell split acceptance matrix

This matrix is the strict acceptance boundary for the typed `CellSplitV1`
implementation. A source owner seam is evidence that the repository rejects
incomplete transitions; it is not evidence that a production target host ran
the transition.

| Criterion                       | Repository owner now present                                                                                                                                                                                                                                                                                                        | Evidence still required for full 8/8                                                                                                    |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Replicate parameter inheritance | `CellParameterBundleManifestV1`, component-level materialization receipt, create-only CAS payload receipt, cloned registry commit, predecessor and rollback binding                                                                                                                                                                 | Signed writer lease, durable `CURRENT`, directory sync, and restart/reopen receipts from the deployment host                            |
| Copy/partition cell state       | Q24 sparse/population projection plus `CellStateMigrationV1`; all children must match one committed parent anchor and one batch fence                                                                                                                                                                                               | A real child journal/CAS owner must atomically commit all children and publish an independently retained witness                        |
| Give children identity          | `CellSplitV1` binds child identity, generation, scope, lineage, objective, bundle and route predicate                                                                                                                                                                                                                               | The target host must reload and compare those fields after restart                                                                      |
| Division of labor and routing   | Dataset/task partitions, route predicates, fallback revisions, CNS route selection and concrete port/ABI digests                                                                                                                                                                                                                    | A live router must emit retained dispatch receipts for the deployed circuit                                                             |
| Nutrition and energy            | Resource budget contract, target-host-only resource evidence gate, and ten-metric long-horizon adapter                                                                                                                                                                                                                              | Independently signed measurements from the actual CPU/GPU/NPU, including communication and migration cost                               |
| Death and rollback              | Quarantine, rollback, tombstone, terminal lifecycle replay, old-route fence and no-resurrection checks                                                                                                                                                                                                                              | Power-loss/restart and fault-injection evidence proving the parent cannot return                                                        |
| Tissue coordination             | CNS generation cutover, child activation ordering, parent-route rejection, route fence receipt and replay payload                                                                                                                                                                                                                   | Durable route/registry persistence and a production runtime callsite after governance admission                                         |
| Survival selection              | Signed no-change baseline, retention, coverage, negative-transfer, cost, failure and rollback evaluation; deterministic `CellSplitProposalSourceV1` plus `run_cell_split_automation_v1` driver; telemetry-triggered `CellSplitProposalSignalV1` and governed `CellSplitV1` planner; fenced `CellSplitTaskFlowJournalOwnerV1` replay | Independent future-window observations plus a target-host commit/restart evidence chain and externally retained learning-ledger witness |

The role-contract roadmap for Representation, MemoryRead, Predictor, Value,
Evaluator and the later Planner/Router/ActionProposal/Plasticity profiles is
maintained in [`learning/CELL_ROLE_CONTRACTS.md`](learning/CELL_ROLE_CONTRACTS.md).
That document defines the P0/P1 source gates and keeps source qualification
separate from target-host production activation.

The implementation deliberately rejects `LocalSimulation` resource evidence at
the production evaluation entrypoint. The target-host harness is therefore a
source qualification fixture and sets `productionEvidence` and
`productionActivationAuthorized` to `false`.

## New source qualification owners

The repository now contains the following replayable source owners. They make
the missing production boundary explicit; they do not turn a local test into a
deployment receipt.

- `CellSplitTelemetryObservationV1` validates unit-bearing utility, coverage,
  latency, resident-memory, communication, training and migration counters.
  `cell_split_signal_from_telemetry_v1` applies a deterministic, governed
  trigger priority (utility regression, task-coverage opportunity, then
  resource pressure).
- `CellSplitGovernedPlannerV1` binds the signal to an immutable policy and
  parent registry context, derives child identity/generation/lineage,
  inheritance modes, state transforms, route ports, resource budgets and
  rollback references, and runs the complete `CellSplitV1` validator.
- `CellSplitTaskFlowJournalOwnerV1` registers an immutable TaskFlow definition,
  creates and fences a run, writes each lifecycle event as a TaskFlow
  `Wait`/`Resume` pair, persists terminal disposition, and reconstructs the
  lifecycle journal from the verified event chain after reopen. A stale owner
  generation or a rewritten prefix is rejected.
- `CellSplitTargetHostEvidenceAdapterV1` verifies a host-signed and
  independently observed canonical JSON envelope. Its production receipt is
  issued only after artifact load, route cutover, restart, power-loss
  recovery, rollback, tombstone, no-resurrection, and non-simulated
  CPU/GPU/NPU resource events are present and replay cleanly.

The target-host envelope is an ingestion protocol, not a claim that this
repository has already run on the deployment device. The deployment owner
must still supply the host and observer keys, actual artifact/router calls,
fault-injection receipts, hardware counters, and an independent future-window
evaluation; those values cannot be derived from the planner digest or a unit
test.

## Strict conclusion

At repository source level, all eight contracts have typed owner boundaries,
including a deterministic machine-driven proposal/evaluation/canary driver, and
negative-path tests. Under the user's strict rule that every item must also
have real target-host evidence and durable automatic long-horizon selection,
the production result remains **0/8 fully complete** until the external
evidence column is supplied. The missing evidence is intentionally represented
as typed gates rather than inferred from a digest or a unit test.
