# automation.taskflow technical development guide

Current executable behavior, owner boundaries and release gates are defined by
this guide together with [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md),
[the schema v19 migration runbook](MIGRATION_V19_RUNBOOK.md),
[the runtime SLO contract](SLO.md), and
[release qualification](RELEASE_QUALIFICATION.md).

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Lane:** `LANE-B-RUNTIME`  
**Durable store schema:** **v19**  
**TaskFlow definition schema:** v1  
**Neural Circuit candidate schema:** v1  
**Neural Circuit runtime-adapter schema:** v1  
**Status:** V1 durable owner and Agentd product composition implemented; selected-host
qualification and independent acceptance remain separate release gates.

## 1. Module responsibility

`automation.taskflow` is the per-Agent durable owner of:

- legacy and Calendar V2 schedule revisions;
- deterministic occurrence identity and stable App Server client identity;
- occurrence lease, generation and timer-writer fencing;
- TaskFlow definition, run, step and durable outbox state;
- provider-attempt and reconciliation evidence for authorized effects;
- terminal projection after the owning observer has supplied trusted evidence;
- bounded Neural Circuit choice/organ/wait execution up to an existing TaskFlow
  wait or final-use-authorized effect boundary.

It does **not** own model inference, organ implementations, provider credentials,
final-use grant issuance, topology activation, deployment, or release authority.
There is one scheduler owner, one TaskFlow ledger and one external-effect seam.
The inert `hepta-taskflow-runtime` command is not a second daemon.

## 2. Executable source topology

| Responsibility | Source owner | Product composition |
|---|---|---|
| Schedule registration and Calendar V2 | `schedule_v2.rs`, `store.rs` | Agentd typed control method and client |
| Due occurrence claim | `store.rs`, `lifecycle.rs` | Agentd automation service |
| Bounded admission batch | `scheduler.rs` | Agentd scheduler loop |
| App Server queue admission | `hepta-agentd/src/automation.rs` | `thread/queue/reconcile(AllowIfAbsent)` |
| Queue/turn reconciliation | `hepta-agentd/src/automation_recovery.rs` | same stable client and payload digest |
| TaskFlow run/step ledger | `taskflow.rs`, `taskflow_step.rs` | owner-local SQLite transaction path |
| Authorized downstream effect | `authorized_effect.rs` | `AgentdAutomationEffectHost` and typed control API |
| Timer quiesce/handoff | `timer_lifecycle.rs` | Agentd drain and owner management |
| Neural Circuit candidate compiler | `neural_circuit.rs` | compiles to the existing TaskFlow definition owner |
| Neural Circuit activation adapter | `neural_circuit_runtime.rs` | returns wait/effect boundaries; creates no authority |
| Cross-host recovery contract | `cross_host_recovery.rs` | deployment controller must supply external fence receipt |

The implementation map is the machine-readable inventory. Source presence is not
selected-host execution proof; execution proof is retained as a workflow receipt
bound to an exact commit and command set.

## 3. Durable schema v19

The canonical SQLite file remains `automation_1.sqlite3`. `AutomationStore::open`
runs the SQLx migrator, reconciles only the explicitly admitted historical
migration IDs, verifies the exact schema and owner, protects the database file,
and reads the durable timer writer epoch.

Schema v19 is the convergence head:

| Migration | Durable addition | Compatibility rule |
|---|---|---|
| 17 | destination-owned kernel operation dedupe receipt | immutable and non-deletable receipt in the same transaction as the destination effect |
| 18 | timer lifecycle, writer epoch and drain guard | `active → draining → active`, or fenced epoch advance from `draining`; unresolved dispatches prohibit handoff |
| 19 | converged owner schema | preserves both displaced migration histories and maps only recognized legacy version/checksum pairs before normal SQLx validation |

No migration deletes V1 schedule, occurrence, TaskFlow, dispatch or terminal
history. An older binary that does not understand schema v19 must not replace or
open the writer. Rollback is a new, compatible writer epoch over the same v19
store, not restoration of an old database image over a live owner.

### 3.1 Migration invariants

1. Backup and checkpoint evidence are captured before mutation.
2. The owner Agent ID is immutable.
3. A recognized legacy checksum remap is metadata convergence, not arbitrary
   acceptance of unknown SQL.
4. Migrations run to completion before the timer or control plane becomes ready.
5. Startup verifies tables, indexes, triggers, owner metadata and timer epoch.
6. Unknown checksum, missing object, invalid trigger or lower schema fails closed.
7. A partially copied database is never promoted by filename alone.

The complete operator procedure is in `MIGRATION_V19_RUNBOOK.md`.

## 4. Execution model

A schedule revision freezes recurrence, timezone profile, tzdb digest, local-time
policy and bounded recurrence. Claiming a due instant creates or reclaims one
stable occurrence and one stable App Server client identity. The TaskFlow run and
step intent are persisted before any queue or provider contact.

Queue admission is not terminal execution. `AutomationTick::Submitted` means only
that Core queue admission has a verified stable receipt. Terminal state is
published after queue/turn reconciliation and TaskFlow reconciliation.

### 4.1 Neural Circuit target and legacy boundary

Existing V1 TaskFlow definitions remain bounded acyclic graphs with Activity,
Wait, Effect and success/failure terminal nodes. Their namespace, definition
digests, state transitions and persisted runs are unchanged.

A Neural Circuit candidate is a versioned bounded control program compiled onto
that existing definition owner. The candidate binds:

- exact predecessor digest;
- route-policy, parameter-bundle and resource-profile digests;
- declared capabilities;
- node roles and admitted edges;
- a canonical circuit digest and compiled TaskFlow definition digest.

The runtime adapter adds the smallest executable vertical slice without creating
a second ledger:

```text
event ingress
→ DecisionCell request
→ durable-choice-compatible recorded choice
→ organ port
→ wait/join
→ budget and depth enforcement
→ bounded in-cell feedback or cancellation
→ terminal receipt / existing effect boundary
```

Feedback does not add a structural cycle to the V1 graph. It is a bounded round
inside one DecisionCell activation and is included in the trace digest. A route
must select an already admitted outgoing edge. Capability widening still
requires separately governed topology and authority admission.

Before any DecisionCell or organ sees an event, runtime v1 recomputes the
canonical event-ingress digest from the event ID, payload digest and causal
parent. Every trace then binds that event digest, the admitted circuit digest and
a canonical digest of the exact step, depth, feedback and cost profile. Terminal,
wait and effect-boundary receipts therefore cannot be relabeled as executions
under different event identity or runtime limits.

An Effect node returns `CircuitEffectBoundaryV1`; it never calls a provider. The
existing TaskFlow authorized-effect path owns grant verification, provider
identity, dispatch evidence and reconciliation. A pending Wait node similarly
returns a boundary for the existing durable run owner to checkpoint.

### 4.2 Recorded-choice identity

Each DecisionCell request binds circuit, event, node, activation number, feedback
round and remaining cost. The receipt binds the selected successor or feedback
digest and the source decision digest. The enclosing trace also binds the exact
runtime-profile digest. Route replay uses the recorded choice; it does not ask a
changed policy to reinterpret historical execution.

### 4.3 Bounded admission and recovery

Agentd uses separate per-cycle budgets:

- recovery budget: historical unknown or admitted work;
- admission budget: new due occurrences;
- provider in-flight limit: one, preserving the existing serial provider seam.

Recovery snapshots a bounded set of distinct frontier rows once per cycle.
Unknown dispatches are selected first by oldest `observed_at_ms`; admitted,
running or indeterminate occurrences are selected by oldest `updated_at_ms`.
When both frontiers are non-empty and the budget exceeds one, one slot is
reserved for terminal observation and every remaining slot continues to favor
unknown dispatch. With a one-item budget, unknown dispatch retains priority.
Each selected row is contacted at most once in that cycle, so neither one
in-progress turn nor a sustained unknown backlog can consume all terminal
observation capacity. A retryable recovery failure consumes an independent
backoff budget and blocks new admission for that cycle.

New due admission remains ordered by canonical `scheduled_for_ms`, task ID and
occurrence. The scheduler samples a fresh host clock for every occurrence in a
batch and stops immediately on an unknown dispatch so the next cycle reconciles
the same identity. Separate recovery and admission budgets prevent either lane
from permanently starving the other while retaining old-work priority within
each lane.

### 4.4 External-effect product path

The repository contains a real Agentd external-effect host. When configured, the
host:

1. loads protected host, authority-key and revocation configuration;
2. verifies owner Agent and generation;
3. constructs the provider request and exact payload digest;
4. claims a signed final-use grant against destination, scope and payload;
5. persists provider-attempt evidence before contact;
6. executes through the registered HTTP provider adapter;
7. returns a typed Agentd receipt;
8. reconciles pending outcomes by the stable provider key after restart.

The async `ProviderEffectTaskFlowDriver` remains a reusable bridge. Product
closure is established by the Agentd host's authorized-effect entrypoint, not by
pretending every reusable bridge has a direct caller. Deployment still requires
an independently provisioned authority, provider endpoint and trusted terminal
observer.

### 4.5 Design records and failure semantics

Errors are classified separately from their durable evidence:

| Class | Examples | Runtime action |
|---|---|---|
| Fence | generation mismatch, timer writer epoch mismatch, access denial | mark generation fenced and stop |
| Fail-stop | corrupt schema, invalid runtime policy, impossible invariant | make automation unavailable; no new work |
| Retry | storage or transport temporarily unavailable before admission | bounded exponential backoff with jitter supplied by the host policy |
| Reconcile | provider or queue outcome may be unknown | preserve identity and query; never blind redispatch |
| Isolate | occurrence-local state conflict | stop the current batch, back off, retain evidence; fail-stop after bounded recurrence |

A timeout after the admission seam is always `DispatchUnknown`. Lease expiry is
not proof that a provider did not execute. A terminal receipt cannot be inferred
from absence of a response.

## 5. Runtime policy and SLOs

`AutomationRuntimePolicyV1` is bounded and versioned. The default policy uses an
8-item recovery budget, 16-item admission budget, one provider in flight, three
consecutive pre-admission failures, and 250–5000 ms exponential backoff.

The normative service objectives are in `SLO.md`. They bind dispatch timeout,
unknown-result reconciliation, lease expiry and writer-epoch fencing. SLO misses
produce evidence and operational alerts; they never weaken identity or authority
checks.

## 6. Timer lifecycle and cross-host recovery

The local timer lifecycle remains `active`, `draining`, `retired` with a monotone
writer epoch. Same-store handoff advances the epoch and returns a successor that
remains draining until its consumer is installed.

Cross-host recovery is now explicitly specified by
`AutomationCrossHostRecoveryManifestV1`. Export is admitted only when:

- the source timer is draining and `can_handoff()`;
- no leased or unknown provider outcome remains;
- an exact SQLite checkpoint digest exists;
- an externally enforced host-fence receipt is bound;
- source and target hosts differ;
- the target opens schema v19 at exactly source epoch + 1;
- the owner Agent read from the copied target store exactly matches the manifest owner.

A deserialized manifest re-parses the canonical owner Agent ID and recomputes the
manifest digest, so a caller cannot legitimize a malformed owner merely by
recomputing the outer hash. Target admission compares the owner read from the
copied v19 store rather than trusting the manifest to attest to itself. The
module does not claim to provide storage transport or distributed consensus. The
deployment controller owns byte transfer and the external host lease. A target
host, owner, schema, epoch or checkpoint mismatch returns `TimerFenced`.

## 7. Calendar V2 and timezone evidence

Calendar V2 persists the timezone ID, tzdb digest, transition profile, start/end,
DST gap policy, DST overlap policy and bounded recurrence. Source tests cover gap
and overlap behavior and schedule-revision identity.

A selected deployment must additionally retain:

- operating-system and tzdata package identity;
- IANA release or source digest used to build the supplied transition profile;
- gap/overlap vectors for the deployed zones;
- multi-scheduler race results under the selected SQLite/filesystem host;
- restore and capacity results.

A synthetic digest named “tzdb” is test evidence, not proof of a current authentic
IANA database.

## 8. Verification and CI

The focused workflow runs on relevant pull requests and pushes to `main`. It
performs:

- schema/document drift verification and unit tests;
- `cargo fmt --check`;
- `cargo check` and strict Clippy;
- automation package tests, migration convergence, structural qualification and
  Neural Circuit runtime tests;
- Agentd library and product-control tests;
- TaskFlow Bazel qualification targets;
- exact commit/tree and command receipt retention.

The workflow is a repository-controlled gate. Branch protection must name its
result if the hosting platform requires explicit required-check registration;
workflow source alone cannot mutate that administrative setting.

## 9. Release truth table

| Claim | Current status |
|---|---|
| Schema v19 source and migration convergence | implemented |
| V1 durable schedules, occurrences, TaskFlow and recovery | implemented |
| Bounded batch admission and separate recovery budget | implemented |
| Agentd Calendar V2 product control | implemented |
| Agentd authorized external-effect product host | implemented when configured |
| Minimal Neural Circuit vertical slice | implemented to wait/effect boundary |
| Cross-host recovery manifest and fail-closed target admission | implemented |
| Cross-host byte transport / distributed lease | external deployment owner |
| Selected-host current IANA tzdb qualification | required evidence |
| Independently accepted provider and authority configuration | required evidence |
| Activation, promotion and release | externally governed; not asserted here |

## 10. Compatibility rules

- V1 TaskFlow definitions and database records are never rewritten as circuits.
- Existing `AutomationTick` variants retain their public meaning.
- The batch API is a bounded repetition of the same V1 `tick` operation.
- Neural Circuit Effect nodes return to the existing authorized-effect seam.
- A structural successor cannot widen capabilities.
- Historical choices, provider keys and occurrence identities survive policy and
  binary upgrades.
- No old binary may become writer over schema v19.

## 11. Completion criteria

Repository-controlled implementation is complete only when source, mapping,
documentation, tests and exact-head receipts agree. Deployment completion also
requires the selected-host and independent evidence listed in
`RELEASE_QUALIFICATION.md`. No self-authored document or CI run may substitute
for an independent acceptance signature.