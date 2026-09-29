# automation.taskflow schema-22 technical development guide

This is the canonical current technical guide for the schema-22 continuation on
`work/automation-taskflow-full-closure-2026-09-27`. Historical design detail in
[TECHNICAL.md](TECHNICAL.md) remains useful, but any schema-21 or "in-memory-only"
statement there is superseded by this guide. Machine-readable capability truth is
in [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md), `CURRENT_STATE.json`,
`IMPLEMENTATION_MAP.json`, and `SCHEMA_CONTRACT.json`.

Source presence, build-tree inclusion, product-caller source, exact-head execution,
deterministic-merge execution, selected-host behavior, and independent acceptance
are separate delivery layers. Checked-in source cannot self-issue the final four.

## 1. Owner and compatibility boundary

`automation.taskflow` remains the single per-Agent SQLite owner for schedules,
occurrences, TaskFlow definitions/runs/steps/events, provider-attempt evidence,
timer epochs, recovery sweeps, and schema-22 Neural Circuit activation state. It
does not create a second scheduler, provider authority, topology selector,
deployment controller, or release authority.

V1 TaskFlow identities and records retain their original meaning. Migration 22 is
additive: it stores durable circuit runs, immutable activation intents and
receipts, recorded choices, conserved cost reservations, and resumable Wait/Effect
checkpoints. Older binaries that cannot interpret schema 22 must not reopen the
writer. Compatible rollback is a fresh writer generation over current compatible
history, never resurrection of an older database image.

## 2. Current native source topology

| Responsibility | Source | Current boundary |
|---|---|---|
| Schedule/occurrence owner | `schedule_v2.rs`, `lifecycle_bounded.rs`, `store.rs` | Agentd automation service; occurrence startup audit uses fixed keyset pages |
| Bounded admission/recovery | `scheduler.rs`, `recovery_sweeps.rs` | separate recovery/admission budgets; exact-ID reads; unknown outcomes are not replay permission |
| TaskFlow ledger | `taskflow.rs`, `taskflow_bounded.rs`, `taskflow_step.rs` | one owner-local transaction model; startup definitions, runs, and event chains use fixed keyset pages in one read snapshot |
| Authorized provider effects | `authorized_effect.rs`, `effect_dispatch_ledger.rs` | configured `AgentdAutomationEffectHost`; final-use trust and provider credentials remain external inputs |
| Durable Neural Circuit | `durable_neural_circuit.rs`, `durable_neural_circuit_recovery.rs`, migration 22 | pre-call intent/reservation, immutable result, checkpoint and recovery-required state on the existing TaskFlow run |
| Cross-host contract | `external_host_fence.rs`, `cross_host_recovery.rs` | signed current fence and exact target tuple validation; no physical fencing or byte transport authority |
| Backup/staged restore | `scripts/automation_taskflow_checkpoint.py` | WAL-aware create-only staging; no migrate, epoch advance, start, resume, or promotion command |

The new `taskflow_bounded.rs` wrapper changes only the automation-store opener
audit. Runtime TaskFlow mutation methods remain in `taskflow.rs`. Definition,
run, and event corruption is still checked completely; only materialization is
bounded. All pages are read through one SQLite transaction so a writer cannot
produce a projection/event combination that never existed in one durable snapshot.

## 3. Durable Circuit execution and recovery

Before a DecisionCell, organ, or Wait owner is contacted, the store verifies the
current timer epoch and exact TaskFlow fence, writes an immutable activation intent,
and reserves the remaining conserved cost budget. A committed result appends an
immutable receipt and any newly recorded choices before advancing the run state.
A Wait or Effect boundary stores a checkpoint. A historical committed choice is
replayed from the checkpoint rather than asking a changed policy again.

An activation in `executing` or `recovery_required` blocks ordinary re-entry.
The owner-recovery observer must bind the exact run, activation sequence, semantic
input digest, predecessor checkpoint, and reservation. No observation means the
activation remains quarantined. Recovery does not create a fresh activation or
call the owner again. Terminal projection verifies that the existing TaskFlow
terminal state matches the Circuit receipt before acknowledging projection.

These source properties do not yet establish the normal Agentd product port. The
remaining product work is to compose real DecisionCell, organ, Wait, Effect, and
recovery-observer owners through the existing Agentd lifecycle and authority
boundaries, then execute process-cut tests without recomputing an outcome in the
test harness.

## 4. Cross-host recovery

A verified Ed25519 fence receipt binds controller identity/epoch, owner Agent,
source and target hosts, source and required target writer epochs, checkpoint
digest, issue time, and expiry. The recovery manifest additionally binds the
schema and pending-work count. Target admission compares those claims with values
read from the copied target store.

The contract is fail-closed but is not the controller. Completion still requires
an authorized controller to quiesce and physically fence the source host, capture
and transfer the exact checkpoint, advance the target writer epoch, install the
consumer, and demonstrate that the predecessor cannot write. A signed manifest or
unit test is not a two-host exercise.

## 5. Selected-host evidence

The selected-host lane must prove actual consumption, not merely hash environment
labels. One immutable receipt chain must bind:

- exact candidate commit/tree and toolchain;
- the timezone profile and IANA source consumed by Calendar V2;
- the native SQLx/SQLite implementation used by the run;
- loaded provider endpoint/contract and terminal observer;
- final-use trust and the current revocation frontier;
- actual provider dispatch, terminal observation, restart/reconciliation, and
  durable Circuit continuation;
- target-host latency, peak RSS, SQLite work, backlog age, and recovery behavior.

Loading a configuration constructor is source-composition evidence, not proof that
an authorized effect occurred. Python SQLite backup tests are not native runtime
identity or physical power-loss qualification.

## 6. Capacity and startup audit

Occurrence rows, TaskFlow definitions, TaskFlow runs, and each run's event chain
are now verified with fixed-size keyset pages. The TaskFlow pages share one read
snapshot and still reject corruption after the first page. This bounds peak row
materialization; it does not make total startup work constant and does not issue a
latency, RSS, I/O, or long-retention acceptance result.

Qualification must retain exact history and measure at multiple retained scales,
including sparse unknown work, long event chains, WAL recovery, concurrent reader
pressure, reopen after abrupt termination, and repeated writer generations. Any
future checkpointing or archival optimization must preserve an authenticated
anchor and complete corruption detection; it must not delete unresolved effects
or reinterpret unknown as absent.

## 7. Qualification and claim boundary

The focused workflow is read-only and records each actual command, working
directory, candidate/tree, timestamps, exit status, observed test count, retained
log digest, and toolchain output. `not_run`, zero-test filtering, timeout, missing
output, and historical receipts cannot count as success. Both exact source-head
and deterministic synthetic-merge executions are required.

The checked-in implementation map may declare the first three delivery layers
only when exact source navigation supports them. Exact-head execution,
deterministic-merge execution, selected-host behavior, and independent acceptance
stay false until separate immutable receipts for the same candidate are verified.
Activation, promotion, and release remain independent decisions.

## 8. Remaining closure order

1. Obtain exact-head and deterministic-merge format, compile, strict-Clippy,
   native/product, migration, and Bazel receipts for the schema-22 source.
2. Compose the real Agentd Circuit owner ports and process-cut recovery observer,
   preserving the existing TaskFlow and final-use owners.
3. Execute an operated two-host fence/transfer/epoch-handoff/reject-old-writer test.
4. Run selected-host actual-use and long-retention capacity qualification.
5. Verify independent acceptance; do not infer activation, promotion, or release.
