# Lane B source contracts and implementation closure — schema v19

**Lane:** `LANE-B-RUNTIME`  
**Candidate:** derived from Git at verification time  
**Source claim:** repository-controlled closure, not deployment or release

## Native operation inventory

| Operation | Class | Owner entrypoint |
|---|---|---|
| `register_schedule` | `owner_native` | `schedule_v2.rs` / Calendar V2 store API |
| `materialize_due_batch` | `owner_native` | `AutomationScheduler::tick_batch` |
| `claim_occurrence` | `owner_native` | lifecycle/store claim APIs |
| `reconcile_occurrence` | `owner_native_composed` | Agentd recovery + TaskFlow recovery |
| `execute_step` | `owner_native_composed` | TaskFlow step/outbox + Agentd effect host |
| `handoff_timer` | `owner_native` | timer lifecycle APIs |
| `execute_circuit_boundary` | `owner_native_adapter` | `run_neural_circuit_v1` |
| `admit_cross_host_recovery` | `owner_native_contract` | cross-host manifest target admission |

## Source invariants

1. Store schema constant, highest migration and documentation all equal 19.
2. V1 schedule/TaskFlow records remain compatible.
3. Batching repeats the same durable tick; provider calls remain serialized.
4. Unknown outcomes preserve stable identities and enter reconciliation.
5. External effects require the final-use authority and provider owner.
6. Neural Circuit effects stop at the existing effect boundary.
7. Cross-host start requires checkpoint, external fence and next epoch.
8. Implementation maps bind exact source observations but do not qualify
   deployment execution.

## Verification

`.github/workflows/automation-taskflow-focused.yml` is triggered for relevant
pull requests and `main` pushes. The workflow verifies generated/source truth,
format, compile, strict Clippy, Cargo tests, migration convergence, Agentd product
paths and Bazel TaskFlow qualification. A retained receipt binds the command set
to the exact Git commit and tree.

## External evidence gates

Selected-host tzdb/DST/multi-scheduler/restore/capacity receipts, independently
provisioned authority/provider configuration, independent acceptance, activation,
promotion and release are not converted into source claims. They remain false
until their own signed evidence is attached.
