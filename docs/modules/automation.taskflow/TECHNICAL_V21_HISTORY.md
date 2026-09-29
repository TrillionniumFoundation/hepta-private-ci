# automation.taskflow technical development guide

Current capability declarations and unresolved work are generated in
[CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) and `CURRENT_STATE.json`
from `IMPLEMENTATION_MAP.json` and `SCHEMA_CONTRACT.json`. This guide explains
implementation semantics; neither prose nor source navigation proves execution.
See also [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md),
[the migration runbook](MIGRATION_V19_RUNBOOK.md), [runtime SLOs](SLO.md) and
[release qualification](RELEASE_QUALIFICATION.md).

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Lane:** `LANE-B-RUNTIME`  
**Durable store schema:** **v21**  
**TaskFlow definition schema:** v1  
**Neural Circuit candidate schema:** v1  
**Neural Circuit runtime-adapter schema:** v1  
**Status:** V1 durable owner and configured Agentd product composition are
source-present. Exact-head/native/merged-tree execution, durable Circuit product
integration, cross-host operation and selected-runtime evidence remain distinct
unfinished work. No deployment or independent acceptance is asserted.

## 1. Module responsibility

`automation.taskflow` is the per-Agent durable owner of:

- legacy and Calendar V2 schedule revisions;
- deterministic occurrence identity and stable App Server client identity;
- occurrence lease, generation and timer-writer fencing;
- TaskFlow definition, run, step and durable outbox state;
- provider-attempt and reconciliation evidence for authorized effects;
- terminal projection after the owning observer supplies trusted evidence;
- two persistent bounded recovery-sweep records, separate from business state.

The bounded Neural Circuit library adapter produces choice/organ/wait traces up
to a wait or effect boundary. It is not yet the durable product interpreter.
TaskFlow does not own model inference, organ implementations, provider credentials,
final-use grant issuance, topology activation, deployment or release authority.
There is one scheduler owner, one TaskFlow ledger and one authorized-effect seam.
The inert `hepta-taskflow-runtime` command is not a second daemon.

## 2. Executable source topology

| Responsibility | Source owner | Composition boundary |
|---|---|---|
| Schedule registration and Calendar V2 | `schedule_v2.rs`, `store.rs` | Agentd typed control method and client |
| Due occurrence claim | `store.rs`, `lifecycle.rs` | Agentd automation service |
| Cancellation-aware bounded admission | `scheduler.rs` | Agentd scheduler loop |
| App Server queue admission | `hepta-agentd/src/automation.rs` | `thread/queue/reconcile(AllowIfAbsent)` |
| Queue/turn reconciliation | `hepta-agentd/src/automation_recovery.rs` | exact client/payload identity; bounded read-only requests |
| Persistent fair polling | `recovery_sweeps.rs` | timer-fenced key reservation and exact owner reads |
| TaskFlow run/step ledger | `taskflow.rs`, `taskflow_step.rs` | existing owner-local SQLite transactions |
| Authorized downstream effect | `authorized_effect.rs` | `AgentdAutomationEffectHost` and typed control API |
| Timer quiesce/handoff | `timer_lifecycle.rs` | existing owner management |
| Neural Circuit candidate compiler | `neural_circuit.rs` | compiles to the existing TaskFlow definition format |
| Neural Circuit activation adapter | `neural_circuit_runtime/` | library trace/boundary output; durable product continuation remains open |
| Cross-host recovery contract | `cross_host_recovery.rs` | manifest validation; real external-fence controller remains open |
| Backup and staged restore | `scripts/automation_taskflow_checkpoint.py` | operator-invoked, create-only; never changes authority or writer epoch |

The implementation map is the machine-readable source inventory. Source presence
is not selected-host execution. Qualification receipts bind the actual candidate,
command, working directory, toolchain output, result and retained log.

## 3. Durable schema v21 and retained history

The SQLite file remains `automation_1.sqlite3`. `AutomationStore::open` runs the
SQLx migrator, reconciles only explicitly admitted historical migration IDs,
verifies the owner/schema, protects the database file and reads the timer epoch.

| Migration | Durable addition | Compatibility rule |
|---|---|---|
| 17 | destination-owned kernel operation dedupe | immutable receipt committed with the destination effect; published SQL is retained |
| 18 | timer lifecycle, epoch and drain guard | epoch advance only from draining; unresolved timer dispatch prohibits handoff |
| 19 | converged owner schema | only recognized legacy version/checksum pairs are remapped before normal SQLx checks |
| 20 | two permanent recovery keyset sweeps | polling progress is not occurrence state, absence evidence or dispatch authority |
| 21 | indexed sparse unknown frontier | preserves migration 20's checksum and selects the indexed dispatch key |

The historical SQL in migrations 17 and 18 retains its earlier intermediate
metadata updates; migration 19 converges them, followed by 20 and 21. Do not
rewrite published migration bytes to make their filename and intermediate update
look alike. `SCHEMA_CONTRACT.json` pins their Git blob identities.

No migration deletes V1 schedules, occurrences, TaskFlow runs, provider attempts,
terminal history or recorded identities. An older binary that cannot interpret
schema 21 must not open the upgraded writer. Compatible rollback uses a fresh
writer epoch over the current compatible store, not an old live database image.

### 3.1 Migration invariants

1. Capture a consistent backup and independently retain its digest before mutation.
2. The owner Agent ID and historical effect identities remain immutable.
3. Recognized checksum remapping is reviewed metadata convergence, not permission
   to accept unknown SQL or hand-edit `_sqlx_migrations`.
4. Native migration and integrity verification complete before admission is ready.
5. Missing lifecycle/sweep rows are corruption, not a fresh initialization request.
6. A copied filename or checkpoint digest alone never authorizes another writer.
7. Old binaries remain stopped; backup retention does not permit resurrection.

The operator procedure and executable backup/staging commands are in
`MIGRATION_V19_RUNBOOK.md`; that historical filename is retained for navigation.

## 4. Execution model

A schedule revision freezes recurrence, timezone profile, tzdb digest, local-time
policy and bounded recurrence. Claiming creates or reclaims one stable occurrence
and App Server client identity. TaskFlow run/step intent and dispatch uncertainty
are durable before crossing the queue boundary.

Queue admission is not terminal execution. `AutomationTick::Submitted` means a
verified Core admission receipt, not successful task execution. Terminal state
follows owning-observer evidence and TaskFlow reconciliation.

### 4.1 Neural Circuit target and legacy boundary

V1 TaskFlow definitions remain bounded acyclic graphs with Activity, Wait, Effect
and success/failure terminal nodes. Their namespace, digests and persisted
interpretation are not silently changed by the Circuit extension.

A Neural Circuit candidate binds the exact predecessor, routing policy, parameter
bundle, resource-profile digest, declared capabilities, roles, edges and compiled
TaskFlow definition digest. The library adapter implements this limited slice:

```text
event digest validation
→ DecisionCell request and in-memory recorded choice
→ organ port
→ wait/join adapter
→ local step/depth/cost/feedback checks
→ terminal / wait / effect boundary output
```

Feedback is bounded inside a DecisionCell and does not introduce a cycle into
V1 definitions. A route must choose an admitted outgoing edge. Structural or
capability changes remain separately governed next-generation candidates.

Runtime v1 recomputes the event digest from event ID, payload digest and causal
parent before invoking a port. Traces bind that digest, the circuit digest and
the exact local runtime profile. These bindings prevent relabeling a returned
trace under different input/limits; they do not authenticate an external source,
persist an activation or establish a model/organ execution receipt by themselves.

An Effect returns `CircuitEffectBoundaryV1` and does not dispatch a provider.
Wait Pending also returns a boundary. Durable checkpoint/continuation through
the existing TaskFlow owner, and actual product consumers of those boundaries,
remain repository implementation work rather than external acceptance paperwork.

### 4.2 Recorded-choice identity and durability requirement

A DecisionCell request binds circuit, event, node, activation number, feedback
round and remaining cost. The returned choice binds the successor or feedback
and source-decision digest; the trace also binds the runtime profile.

The current adapter initializes an in-memory accumulator for each invocation.
It does not load historical choices, conserve reservations across reboot or resume
a pending Wait/Effect. Port cost is checked after a port returns. Consequently,
returned trace bounds are not proof of pre-call physical resource reservation.

The required product chain remains:

```text
durable ingress and activation identity
→ conserved reservation before owner work
→ exact DecisionCell/organ owner result
→ durable recorded choice and next-step intent
→ Wait/Effect continuation through existing TaskFlow ownership
→ terminal observation, reconciliation and budget settlement
```

A historical committed choice must be replayed without asking a changed policy
again. Cross-owner crash cuts must reconcile the same activation/result, never
repeat a possibly completed cell update or effect. Implement this on the existing
owner, not a second store, daemon or scheduler. The scope is not reduced to the
present in-memory adapter.

### 4.3 Bounded admission and recovery

Agentd uses separate recovery and admission budgets. Recovery first reserves a
bounded set of exact keys through `AutomationStore::reserve_recovery_selection`.
The two permanent sweeps advance under timer fencing/CAS and retain a frozen upper
key for each sweep. Business `updated_at_ms` is not repurposed as polling progress.

Unknown work keeps priority. With both lanes populated and budget greater than
one, capacity is reserved for terminal observation. A one-item budget explicitly
retains unknown-first behavior. Each lane rotates independently across reopen;
a long-running oldest task does not continually hide all newer selected keys.

Selected keys are re-read through `uncertain_dispatch_exact` and
`pending_occurrence_work_exact`, never intersected with an unrelated bounded
prefix. A key that settled since reservation is simply no longer work; it does
not become a new absence proof. A crash after reservation delays an observation
until another sweep but does not change occurrence or provider state.

Transient unknown-query failures are retained while the reserved terminal lane
is attempted. The batch still fails, and no new admission occurs that cycle.
Fatal identity/corruption/fence errors stop immediately. Read-only queue/turn RPCs
have deadlines; timeout never proves absence. Terminal-history pagination retains
its durable exact-CAS continuation.

This is finite-frontier progress, not a latency guarantee under arbitrary overload,
backdated identities or unlimited arrivals within a frozen key interval. Target
capacity and long-running operational liveness still need measured qualification.

Admission remains ordered by scheduled instant and stable occurrence identity.
`tick_batch_cancellable` samples cancellation before every new claim and samples
a fresh host clock per occurrence. An already-started tick retains its durable
acknowledgment or exact uncertainty. The first proven pre-admission failure yields
to cross-cycle host backoff; unknown dispatch stops the batch for reconciliation.

### 4.4 External-effect product path

The configured `AgentdAutomationEffectHost` loads protected provider/authority and
revocation configuration, checks owning scope, binds exact payload bytes to the
signed final-use grant, persists attempt evidence, executes the HTTP adapter and
reconciles a pending outcome by its stable provider identity.

Host schema v1 retains its original provider-visible key: provider scope,
destination, run and step. The generic bridge's key profile is not silently
substituted for it. Local step attempt and payload bytes are excluded from the
logical key; changed payload under the same logical effect must conflict, not
become a new effect. Unknown outcome never grants redispatch permission.

Product-source composition is established by the named host, not by declaring that
every reusable bridge has a direct caller. Independently provisioned issuer trust,
provider contract and terminal observer plus actual selected-host execution remain
required. The host's configurable provider timeout is distinct from the scheduler's
App Server admission timeout.

### 4.5 Design records and failure semantics

| Class | Examples | Runtime action |
|---|---|---|
| Fence | stale generation/epoch, access denial | stop at the owning boundary; preserve uncertain evidence |
| Fail-stop | corrupt schema, invalid policy/invariant | make automation unavailable; no new work |
| Retry | proven pre-admission storage/transport failure | yield to bounded exponential host backoff |
| Reconcile | queue/provider contact may have happened | retain exact identity; query, never blind redispatch |
| Isolate | occurrence-local state conflict | preserve evidence and stop the batch; bounded recurrence may fail-stop |

TaskFlow errors retain their categories through the scheduler and recovery path;
corruption/fencing must not be erased by a wildcard conversion to ordinary retry.
The current retry policy is capped deterministic exponential backoff, not jittered
backoff. Lease expiry, parent cancellation and missing replies are not absence
proofs. Compensation remains a separately authorized action, not an undo operation.

## 5. Runtime policy and SLOs

The default `AutomationRuntimePolicyV1` has an eight-key recovery budget, sixteen
new admissions, serialized scheduler contact, three consecutive pre-admission
failures and 250–5000 ms retry backoff. Agentd uses the policy's dispatch/lease
values. This local serialization is not a claim that all independently invoked
external-effect control calls share a global one-call semaphore.

`SLO.md` defines operational objectives, evidence and known limits. A configured
threshold or test definition is not measured compliance. Breaches retain evidence
and trigger operations work; they do not relax identity, revocation or authority.

## 6. Timer lifecycle and cross-host recovery

The local lifecycle is `active`, `draining`, `retired`, with monotone writer epoch.
A same-store handoff advances the epoch; the successor remains draining until its
consumer is installed. Historical unresolved effects must not be erased.

`AutomationCrossHostRecoveryManifestV1` binds source/target hosts, owner Agent,
checkpoint, external fence digest, schema and exactly the next epoch. Target
validation compares the owner Agent read from the copied target store, not a
self-attested manifest owner. Invalid owner/schema/epoch/checkpoint rejects.

The manifest does not copy bytes, authenticate an external fence or establish
physical source-host isolation. A real controller must verify current external
fencing, transport the exact checkpoint and drive native target admission. That
product integration and a two-host fault/recovery exercise remain open.

The Python checkpoint utility supplies a consistent WAL-aware backup and a
create-only staged copy. It keeps source schema and epoch unchanged, requires
an independently retained manifest digest and never starts a target. Its output
is not `admit_target`, a writer lease or an external-fence receipt.

## 7. Calendar V2 and selected-runtime evidence

Calendar V2 persists timezone ID, tzdb digest, transition profile, start/end,
DST gap/overlap policies and recurrence bounds. Source tests cover these semantics.

Selected-host proof must bind the profile actually consumed by the native run to
the verified IANA source, deployed zones and runtime configuration. Merely hashing
a host tzdb directory or copying environment identity strings into an artifact
does not prove the run used them. Provider endpoint/contract, loaded final-use
trust, live revocation frontier, terminal observer and native Rust/SQLx SQLite
identity require the same actual-use binding.

The checkpoint inspector reports its Python SQLite identity explicitly; that is
not the native Agentd SQLite identity. Synthetic DST vectors and owner fixtures
remain distinct from selected-runtime execution and independent acceptance.

## 8. Verification and reproducible evidence

The focused workflow remains read-only on relevant PR/main candidates and is
included in `CI required`. It invokes `automation_taskflow_commands.py` and the
existing `hepta_ci_exec.py` recorder, retaining actual argv/cwd, source commit/tree,
time interval, exit result, log digest, toolchain output and observed test counts.
Not reached or compile-dependent commands remain `not_run`; interrupted/running
records never count as passed. Formatting is check-only and native tests stay
locked. Native, structural, migration, product and Bazel gates are retained.

The contract checker verifies schema/migration bytes, current status projections,
source navigation and exact observed-source identity. It deliberately does not
report an algorithm, native run or product as verified from source markers alone.

Developer updates use two ordinary commits: commit source/semantic declarations,
then `python3 scripts/automation_taskflow_contract.py observe` to refresh existing
source objects without changing capability flags. `render` updates only derived
status files. Neither writer command is part of read-only qualification.

The new checkpoint tests execute real SQLite backup/staging, an abrupt Python
child-process cut and retained-history inspection. They do not execute native
AutomationStore restart or fix its still-unbounded full-history startup verifiers.
Current source-head and deterministic-merge native receipts are both required.

## 9. Release truth

Use the generated [current implementation](CURRENT_IMPLEMENTATION.md), not a
hand-maintained checklist that combines source presence with test execution.
Native source-head, native deterministic merge, selected-runtime execution,
independent acceptance, activation, promotion and release are separate states.
See `RELEASE_QUALIFICATION.md` for the evidence chain and remaining source work.

## 10. Compatibility rules

V1 definitions and records are never rewritten as richer circuits. Existing tick
variants retain their meaning; batching repeats the same durable tick boundary.
Capability widening requires separate admission. Historical occurrence, client,
provider, grant and reconciliation identities survive binary/policy updates.
No old binary becomes writer over schema 21, and no backup replaces a live owner.

## 11. Completion criteria

Completion requires agreement between source, generated declarations, native tests,
product callers and successful exact-head/merged-tree receipts. The durable Circuit,
cross-host controller, actual selected-runtime bindings and native startup capacity
work remain part of the requested implementation scope. They are not reclassified
as mere external signatures. Deployment and independent acceptance add further
requirements and cannot be self-issued by these source changes.
