# automation.taskflow: schema v19 implementation design

Parent: `docs/modules/automation.taskflow/TECHNICAL.md`.  
Lane: `LANE-B-RUNTIME`.  
Candidate identity: derived from Git by verification; never hard-coded as a
self-qualifying claim.

## 1. Status

The repository source implements the schema v19 durable owner, deterministic
schedule/occurrence identity, TaskFlow run/step ledger, App Server admission and
terminal reconciliation, Calendar V2 Agentd control, bounded admission/recovery
budgets, timer lifecycle, authorized external-effect host, cross-host recovery
manifest and the minimal Neural Circuit runtime adapter.

Source composition is not release authority. Current authentic IANA tzdb,
selected-host execution, independently provisioned final-use/provider
configuration, independent acceptance, activation, promotion and release remain
separate evidence gates.

## 2. Public operations and owner mapping

| Design operation | Native entrypoint | Product caller |
|---|---|---|
| `register_schedule` | `AutomationStore::create_calendar_task_v2` | Agentd typed Calendar V2 control |
| `claim_occurrence` | `AutomationStore::claim_due` / `materialize_occurrence` | Agentd automation service |
| `materialize_due_batch` | `AutomationScheduler::tick_batch` | Agentd scheduler loop |
| `reconcile_occurrence` | App Server recovery helpers and TaskFlow recovery | Agentd recovery lane |
| `execute_step` | TaskFlow step/outbox and authorized-effect methods | Agentd external-effect host |
| `handoff_timer` | timer lifecycle APIs | Agentd drain/owner management |
| `compile_circuit` | `NeuralCircuitCandidateV1::compile_taskflow` | admitted control-plane candidate |
| `execute_circuit_boundary` | `run_neural_circuit_v1` | existing TaskFlow owner/ports |
| `admit_cross_host_recovery` | `AutomationCrossHostRecoveryManifestV1::admit_target` | deployment controller |

No second scheduler, TaskFlow engine, queue writer, authority issuer or
terminality oracle is introduced.

## 3. Durable schema

`AUTOMATION_SCHEMA_VERSION` is 19. Migration 17 adds immutable destination
operation dedupe; migration 18 adds timer lifecycle and writer epoch; migration
19 converges the reviewed displaced histories. The loader remaps only known
legacy version/checksum pairs and then delegates to normal SQLx validation.

Rollback must preserve schema v19 records and use a binary that understands:

- Calendar V2 and frozen schedule revisions;
- dispatch-unknown evidence;
- provider reconciliation history;
- terminal observer cursor progress;
- destination dedupe receipts;
- timer writer epoch and phase;
- the converged migration history.

An older binary must not become writer over this store.

## 4. Causal execution

For every occurrence:

1. claim under the current generation and timer epoch;
2. freeze schedule revision and canonical instant;
3. derive stable occurrence and client identities;
4. create/bind the TaskFlow run and step intent;
5. record dispatch uncertainty before external contact;
6. cross App Server or authorized-effect seam;
7. verify exact receipt identity;
8. reconcile persisted turn/provider outcome;
9. reconcile TaskFlow step/run;
10. publish occurrence terminal state.

Queue submission is non-terminal. Missing replies are not absence proofs.

## 5. Capacity and fairness

The default runtime policy budgets eight distinct recovery items and sixteen new
admissions per Agentd cycle. Recovery snapshots both frontiers once: unknown
dispatches have priority and are ordered by oldest observation time;
admitted/running/indeterminate occurrences are ordered by oldest durable update
time. When both frontiers are non-empty and the budget exceeds one, at least one
slot is reserved for terminal observation and all remaining capacity continues
to favor unknown dispatch. With a one-item budget, unknown dispatch retains
priority. Each selected row is contacted at most once in the cycle, so neither
one in-progress turn nor sustained unknown pressure can consume all terminal
observation capacity. New admission remains ordered by scheduled instant, task
and occurrence identity. Provider contact is serialized and a fresh clock is
sampled per admission item. Unknown dispatch stops the admission batch and
returns the next cycle to reconciliation.

Errors are classified as fence, fail-stop, retry, reconcile or isolate. Temporary
pre-admission and recovery-transport failure uses independent capped exponential
backoff budgets; a failed recovery cycle admits no new work. Corruption and fence
violation stop admission; unknown result is never blind-retried.

## 6. Neural Circuit vertical slice

Candidate v1 remains an acyclic bounded TaskFlow compilation. Runtime v1 first
recomputes the canonical event-ingress digest, then calls a DecisionCell, records
exact route/feedback choices, invokes an admitted organ port, processes
wait/join, enforces step/depth/cost/feedback budgets, observes cancellation and
emits a terminal receipt.

Every runtime trace binds the exact event digest, circuit digest and a canonical
digest of the runtime profile (`max_steps`, `max_depth`, feedback limit and cost
budget). Terminal, wait and effect-boundary receipts therefore cannot be
relabeled as executions under different limits.

Feedback is bounded inside the DecisionCell and does not mutate the persisted
graph. Effect nodes emit a `CircuitEffectBoundaryV1` for the existing
final-use-authorized effect seam. Historical V1 definitions and runs are
unchanged.

## 7. External-effect product composition

`AgentdAutomationEffectHost` is the concrete repository product host. It loads
protected configuration, opens the final-use authority, constructs the provider
adapter, verifies current generation/revocation state, executes the durable
TaskFlow effect entrypoint and reconciles by stable provider identity. Typed
Agentd protocol and client methods expose execute/reconcile status.

The reusable async `ProviderEffectTaskFlowDriver` is not falsely promoted as the
only possible product caller. Independent issuer/provider provisioning and
selected-host acceptance remain required.

## 8. Cross-host recovery

The module defines a fail-closed manifest but does not claim distributed storage
or consensus. A source must be draining and handoff-safe, with no leased or
unknown provider result. The manifest binds checkpoint and external host-fence
receipts and requires the target to observe schema 19, exactly the next writer
epoch and the same owner Agent read from the copied store. A deserialized
manifest also revalidates the canonical owner Agent ID; a recomputed manifest
digest cannot legitimize a malformed or different owner identity.

## 9. Verification commands

The focused workflow runs schema/document drift verification, formatting,
compile, strict Clippy, package tests, migration convergence, structural
qualification, Agentd product tests and Bazel qualification. It retains a JSON
receipt bound to commit, tree, runner and commands.

## 10. Claim boundary

Repository-controlled source and documentation may be marked complete only when
the implementation map and exact source observations match. The following stay
false until externally supplied evidence exists:

- deployment qualification;
- independent acceptance;
- activation;
- promotion;
- release.