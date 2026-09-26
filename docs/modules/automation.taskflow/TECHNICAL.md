# automation.taskflow technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `automation.taskflow`  
**Owner:** `automation-platform`  
**Deputy:** `agent-runtime`  
**Lifecycle:** `existing`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `TASKFLOW-1-EXECUTION-BOUNDARY`

This stable document is the implementation guide for `automation.taskflow`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation/source closure never implies deployment, independent acceptance, activation, promotion or release.

## 1. Identity, mission and ownership

Current implementation: own schedules and occurrences while routing orchestration through the existing Agentd/Codex spine and routing external effects through their registered owners. `automation-platform` owns `codex-rs/hepta-automation`; `agent-runtime` owns the existing Agentd composition caller. Cross-owner facts remain in their owner stores.

The module is a stateful domain service/execution plant. It may coordinate an operation but does not become the authority issuer, downstream domain writer, provider terminality oracle or fleet owner.

### Target positioning: Neural Circuit execution within the existing CNS

TaskFlow's general orchestration model evolves into reusable Neural Circuits, not
a monolithic owner of the Nervous System. The existing CNS is the system-level
architecture. Automation retains timer/calendar wake-up; the existing TaskFlow
owner supplies durable circuit/run progression. Cells make decisions, organ ports
encapsulate capabilities, and registered effect owners execute them. The technical
module ID and existing database ownership remain unchanged during migration.
This target is planned and is not included in the native-source claims below.

## 2. Source binding and implementation status

Declared primary target root:

- `codex-rs/hepta-automation`

Existing owning runtime composition:

- `codex-rs/hepta-agentd/src/automation.rs`
- `codex-rs/hepta-agentd/src/automation_recovery.rs`
- `codex-rs/hepta-agentd/src/state_control.rs` / `src/client.rs`
- `codex-rs/hepta-agent-protocol` for capability-negotiated Calendar V2 control

The durable causal-chain implementation is described in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/automation.taskflow.md). The legacy local execution-boundary calculator in `src/taskflow_execution_boundary.rs` remains a deny-all structural assessment and is **not** the positive provider dispatcher. Positive external effect dispatch is the separately bounded `src/authorized_effect.rs` seam consuming kernel-owned final-use authority.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `runtime.codex`
- `kernel.operations`

Authoritative write domains:

- `automation_schedule`
- `automation_occurrence`

Explicitly denied capabilities:

- `direct_session_store_write`
- `blind_effect_retry`

The module accepts registered, bounded, versioned inputs, freezes schedule/occurrence identity before provider contact, persists pre-dispatch intent, and never converts queue acceptance into external success. Unknown/ambiguous provider outcomes remain durable and block unsafe retry. Automation does not mint the final-use authority consumed by an external effect adapter.

## 4. Internal architecture and component decomposition

The active implementation is one composed owner path, not parallel engines:

```text
AutomationScheduler (existing wake-up owner)
  -> AutomationStore timer lease
  -> schedule revision + deterministic occurrence
  -> existing TaskFlow run/event ledger
  -> durable taskflow_step_outbox
  -> Agentd App Server thread/queue/reconcile for Codex activity
  -> persisted turn terminal observer
  -> TaskFlow reconciliation
  -> automation occurrence terminalization

External TaskFlow effect
  -> durable claimed step
  -> kernel FinalUseAuthority exact intent/payload binding
  -> synchronous driver OR async final-use/provider-effect bridge
  -> exact wire bytes hashed inside automation before grant consumption
  -> provider-stable logical key derived from destination + TaskFlow run/step
  -> durable succeeded/failed/indeterminate observation
  -> provider-specific status reconciliation when required
```

The old `effect_executor.rs` is now compiled only under `cfg(test)` as a legacy reducer fixture; it is not a public/product surface and cannot become a second runtime owner.

### 4.1 Neural Circuit target and legacy boundary

A circuit definition is a reusable, versioned control program; a run is one actual
event/decision trace. Different conditions should activate different allowed
paths of the same program, not require duplicated workflows for every situation.
An organ can hide local circuits; parent circuits call its stable ports rather
than flattening or taking ownership of private cells and stores.

Current `TaskFlowNodeKind` has Activity, Wait, Effect and success/failure terminal
nodes; `TaskFlowEdgeSpec` contains from/to. V1 validates an acyclic graph and is a
bounded durable ledger, not an implemented neural-circuit interpreter. Preserve
these enums, encoded digests, namespace and cycle rejection. Existing V1 runs
remain legacy DAG runs. A new admitted version/profile may translate V1 into a
restricted circuit representation while retaining the original definition digest,
policy, action meaning, outcomes and effect identities. Unsupported input rejects;
no old decoder silently accepts a richer graph or receives new fields in place.

### 4.2 Typed control program and admissible feedback

The following are target node roles, not new variants already present in Rust:

| Role | Required behavior |
| --- | --- |
| Observe | Admit a source-bound event with scope, schema, sequence and freshness; no fabricated evidence |
| Decide | Invoke a declared DecisionCell through existing inference/Intuition owners; expose complete candidates, actual policy and selected branch |
| Transform/Guard | Pure bounded computation or deterministic eligibility/authority check; a model cannot override a hard rejection |
| OrganCall/Subcircuit | Bind typed external ports, child identity, initiation/termination, inherited budget and returned summary; no private-store access |
| Wait/Join | Suspend on a registered event/deadline or combine named branches under explicit all/any/quorum/timeout semantics |
| Effect | Prepare intent in the existing outbox, then invoke the registered authorized owner; acknowledgment is not terminal success |
| Exit | Produce explicit success/failure/abstain/cancel disposition with unresolved-work information; no positive terminal claim over unknown effects |

Edges name source/output and destination/input ports, schema/version, activation
condition, delivery/dedup semantics, causal generation and capacity policy. Signals
are typed data, not executable instructions or capabilities. Observational,
control-completion and derived learning feedback are distinct edge roles. Unknown
critical roles/fields reject before registration. Public capability expansion
requires its actual authority boundary; an edge cannot grant it by existence.

Initialization/fallback dependencies stay DAGs. Admitted runtime feedback can
reactivate a node at a later round, subject to bounded event count, queue bytes,
wall/monotonic horizon profile, activation depth and no-progress policy. A cycle
cannot reference a future result from the same activation. A feedback component
must declare state/delay, exit condition and fallback; a naked graph cycle rejects.
No polling spin, zero-delay unbounded re-entry or unbounded subcircuit recursion.

Every activation selects only declared legal alternatives. Branch choice or
termination under the frozen policy is runtime adaptation; adding edges, changing
ports, replacing parameters or changing state/effect semantics is a next-generation
candidate. Old unknown effects reconcile first. Feedback that requests a new
observation is not permission to retry a possibly completed effect.

### 4.3 Event scheduling, joins and hierarchical budgets

Timer/calendar events use the existing AutomationScheduler. Source, user and organ
events enter an authenticated, bounded ingress adapter of their existing owner;
they do not each start another scheduler. An ingress record binds a stable event
ID and payload digest before a durable run can consume it. At-least-once delivery
is expected; deduplication rejects reused IDs with changed semantics. Late or
out-of-order events follow the declared watermark/window rule rather than silently
changing a previously recorded branch. Cross-host transport is not implied.

A ready frontier contains only causally eligible activations with available
resources. Fair per-run/per-organ quotas and maximum work per scheduling quantum
prevent one looping circuit from starving others. Defer or reject before mutation
when capacity/deadline is exhausted. A logical run is not necessarily a resident
OS task. Execution can be partitioned with one fenced writer per run; it must not
require a global lock, all-neuron barrier or central NDU call for each signal.

A Join binds branch IDs, accepted outcome classes and deterministic tie/order
policy. Arrival-dependent choices record the observed order. Any/quorum success
requests cancellation of surplus branches but retains their unresolved effects;
stop request or timeout is not proof they did nothing. The parent cannot erase a
child outcome or declare successful completion while required effects are unknown.
Race/timeout semantics must not treat a late successful effect as safely repeatable.

Parent/child circuits share a conserved budget: reserve before activation, charge
actual physical work once, release unused reservations through the owner and carry
uncertainty forward. Include inference, queueing, training, evaluation and migration
cost; a local retry does not reset the budget. Persist durable deadline policy and
remaining horizon; process-local monotonic instants are not replayable timestamps
across reboot. Reopen re-admits time/expiry conservatively under the chosen profile.

Direct user/source-event starts bind a durable ingress/run identity without
fabricating a calendar schedule or timer occurrence. Existing scheduled runs retain
their occurrence linkage. Registration of a new trigger type defines its single
wakeup/dedup owner and public contract; it does not create hidden polling workers.

### 4.4 Durable choice, checkpoint and effect ordering

The target causal chain is:

```text
admitted event + frozen circuit/policy/parameter bundle
  -> eligible activation + resource reservation
  -> existing model/DecisionCell/organ call
  -> exact result and state-owner receipt
  -> durable chosen branch + referenced receipt + step outbox
  -> downstream authorized operation
  -> independent terminal observation/reconciliation
  -> run advancement and idempotent learning-ledger handoff
```

An effect-relevant branch decision commits before its downstream dispatch. Record
run/activation/round, causal events, circuit definition, legal candidate set/order,
actual policy/propensity or deterministic-policy identity, selected result, effective
model bundle, input provenance and budget. Recovery reads that committed choice;
it must not rerun a newer Laya or routing policy to reinterpret history. A random
seed alone is not a durable choice or external-effect receipt. Inference retry also
follows its owner's reconciliation/cost rules; a model call is not assumed free.

Cell state and circuit progression belong to different owners. Do not pretend one
SQLite transaction commits both. Use existing intent/outbox/idempotent destination
apply/acknowledgment: a cell result binds its predecessor and successor checkpoint,
then the circuit records the exact receipt and route. A crash between owners resumes
or reconciles the same activation; no second cell update or effect is inferred.
The circuit owner never writes Neuron state or the learning ledger directly.

Not every transient activation needs a global synchronous write. A declared
rebuildable, effect-free local region may checkpoint bounded progress and causal
inputs under its owner. At a durable/effect-relevant boundary, commit the selected
choice and sufficient predecessor state before an effect can begin. A persistent
run must not depend on an unrecoverable transient output. Losing local computation
is permissible only within the stated replay/latency/resource contract; unknown
external effects never become rebuildable pure work.

Cancellation stops new admission and classifies already admitted work. Unknown
results remain open for current-fence reconciliation. Compensation is a separately
authorized action, not mathematical undo. Record original operation identity across
retries and generations; namespace changes or topology replacement cannot reset
idempotency. Retain failure and unresolved-child information through run retirement.

### 4.5 Design records and failure semantics

These are proposed record shapes to register with actual producers/consumers,
not wire IDs, exports or current database tables. Reuse existing types where their
semantics match; an incompatible serialized contract requires a new version.

| Design record | Minimum bound semantics | Owner |
| --- | --- | --- |
| circuit definition | scoped identity/version; typed roles/ports; legal edges; feedback/termination; external contract; resource profile; immutable policy and compatibility references | existing TaskFlow definition owner; organ registry remains separate |
| run/activation | run and parent IDs; admitted trigger; round; causal predecessor; ready/wait frontier; event cursor; bundle; lease/fence; remaining budgets and deadline profile | TaskFlow run owner |
| recorded choice | exact input/result refs; candidate/order digest; route/termination policy; behavior law; committed choice; model/cell receipt; observation and validity bounds | TaskFlow operational record; learning.ledger owns learning facts |
| child/effect binding | child or operation ID; port/destination; payload; final-use reference; durable status; cancellation and reconciliation cursor | run owner references authoritative downstream receipts |

InvalidDefinition, UnsupportedVersion, ScopeMismatch, StaleEvent,
IncompatibleBundle, IncompleteCandidates and CapacityExceeded reject before the
relevant mutation. BackendUnavailable and DeadlineExceeded take the declared
abstain/defer/fallback branch without inventing a result. CommitUncertain,
EffectIndeterminate and ChildUnresolved remain recoverable open states. These are
target categories to map into owner errors, not unregistered additions to V1.
Design success predicates must specify what evidence closes each outcome.

### 4.6 Computational depth and gradient boundaries

For the Neural Circuit target, retain causal parents, activation round and the
Cell/transform/wait kind in the existing run trace. A depth reducer can compute
`d_cell(v)=is_cell(v)+max_parent d_cell(parent)` over that unrolled trace. Parallel
siblings add work but not sequential depth; feedback reactivation adds depth, not
new independent weights. Report wait, transport retry, environment horizon and
censoring separately. Do not infer depth from org hierarchy or a static cycle.

Representation edges preserve approved tensor/structured information with bounded
shape, precision, normalization, source scope and compression/omission metadata.
Action edges carry admitted choices. An incompatible representation is not repaired
by silently serializing it into a label or prompt. A source reread remains an
owner-authorized operation, not an invisible bypass of the circuit input budget.
Declare whether a region is tensor-connected, detached, serialized or externally
observed; operational execution is not proof of a differentiable tape. Existing
owners record receipts and learning.ledger references them; TaskFlow does not
compute or apply cross-owner gradients itself.

Adaptive depth selects continue/subcircuit/stop inside the frozen allowed graph,
policy and budget. A local no-progress loop or failed gradient estimate cannot
extend the deadline, reset resource accounting or retry an unknown effect. Recorded
choices remain historical facts on restart even when the learned depth policy
changes. The conditional expressivity/error model is in
`../../learning/NEURAL_BIOMIMICRY_SPEC.md`; no UAT or scaling claim changes V1.

### Shared-experience and isolated-Agent integration target

Orchestrate contribution, Recall, Replay and candidate training as distinct admitted activities with stable source/operation IDs. Replay of records cannot dispatch their historical effects. Lost publication acknowledgements reconcile; retired runs retain unresolved outcomes and lineage.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::automation_occurrenceV1`
- `DomainRead::automation_scheduleV1`

Consumed contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `DomainRead::thread_sessionV1`
- `ModulePort::kernel.operations::automation.taskflow`
- `ModulePort::runtime.codex::automation.taskflow`
- `OperationIntentV1` (producer-owned `kernel.operations` contract; this candidate composes it at the external-effect boundary)
- kernel final-use authority/grant binding at the registered effect seam

The current external-effect source path uses automation-owned `AuthorizedEffectIntent` only for TaskFlow orchestration identity (run/step/attempt/dependencies/compensation). `AuthorizedEffectIntent::operation_intent_v1()` constructs the producer-owned `kernel.operations::OperationIntentV1` for operation/subject/destination/payload/scope/policy/predecessor semantics, and the TaskFlow digest layers its orchestration fields over that canonical semantic digest. Neither type grants authority.

The synchronous seam remains available. The additive async seam uses `FinalUseAuthority::with_verified_use_async` plus `ProviderEffectTaskFlowDriver`: automation hashes the exact caller-supplied wire bytes before consuming the grant, requires that digest to equal the durable TaskFlow payload digest, and derives a provider logical-effect key from the final-use-bound destination plus TaskFlow run/step. The local step attempt is deliberately excluded from that provider key, so a new local attempt after provider-proven absence cannot silently create a new external effect identity; a changed payload under the same logical effect becomes a provider key/payload conflict. Restart lookup re-derives the provider intent from the durable `AuthorizedEffectPending` record rather than accepting a caller-supplied key.

These source seams do not constitute product activation. `CALLERS.toml` intentionally leaves the async final-use fence, TaskFlow/provider-effect bridge and HTTP provider adapter without product callers until a named host loads independently provisioned final-use trust/revocation state and an independently attested provider configuration/terminal observer.

The compatibility timer API keeps `AutomationTick::Submitted`; its meaning is explicitly narrowed to **durable Core queue admission**, not occurrence or effect completion. Existing `Once`/`FixedInterval` callers keep their historical overlap behavior through an explicit default `overlap=allow`. Calendar V2 is additive: it stores an immutable versioned schedule with timezone ID, tzdb digest, bounded transition profile, start/end, local civil time, cadence and explicit DST gap/overlap policy. The Agentd control plane advertises `automation.calendar_v2@1.0`; clients negotiate that capability before using the typed `AutomationCreateCalendarV2` request, which dispatches to the same per-Agent `AutomationStore` and existing scheduler. The compatibility `automation_tasks.schedule_kind='once'` marker for a Calendar V2 task is not the authoritative calendar definition; callers read `calendar_schedule_v2()`.

## 6. Data authority, persistence and migrations

Schema v16 retains the original `automation_tasks`, `automation_runs` and dispatch-outcome tables and adds:

- `automation_schedule_metadata`: revision, missed-run policy, bounded catch-up state and overlap policy.
- `automation_occurrence_lifecycle`: deterministic occurrence identity, frozen schedule revision, claim generation/token, TaskFlow run ID, queue/turn identity, bounded terminal-observer continuation cursor, recovery phase and terminal receipt.
- `automation_occurrence_events`: append-only hash-chained occurrence history.
- `taskflow_step_outbox`: normal-schema durable `prepared -> claimed -> recorded -> reconciled` per-step receipt chain.
- `taskflow_effect_dispatch_attempts`: immutable pre-provider attempt identity including intent/payload/binding/destination/grant lineage.
- `taskflow_effect_dispatch_observations`: immutable first provider observation.
- `taskflow_effect_dispatch_reconciliations`: immutable terminal reconciliation after a first `indeterminate` observation.
- `automation_calendar_schedule_versions`: append-only Calendar V2 bytes and digest per schedule revision.
- `automation_schedule` / `automation_occurrence` read views for canonical domain naming.

`taskflow_definitions`, `taskflow_runs` and `taskflow_events` remain the durable TaskFlow ledger. A materialized occurrence freezes its schedule revision until it becomes terminal. Safe generation reclaim preserves occurrence/client identity and allocates a new step attempt; an indeterminate provider outcome does not.

Migrations are additive from v3 through v16. Migration v12 adds Calendar V2 history; v13 adds terminal reconciliation after an initial indeterminate external-effect observation; v14 freezes the schedule revision on claimed legacy runs so an in-flight claim cannot float to a later schedule revision; v15 adds append-only reconciliation evidence for legacy dispatch-unknown rows whose historical schedule revision was never frozen; v16 persists the opaque App Server `next_cursor` used by terminal observation so each recovery pass remains bounded while older known turns remain eventually reachable. Such legacy ambiguity can open a new claim only after an exact provider-side proven-absent receipt, and the retired occurrence/client identity is never reused. A binary that does not understand schema v19 must not replace the current owner against an upgraded store.

## 7. Runtime, concurrency and transaction model

One Agent generation owns the per-Agent writer. Scheduler lease generation/token becomes the TaskFlow run/step fence. Pre-dispatch intent is durable before App Server contact. App Server admission uses `thread/queue/reconcile` with stable `client_user_message_id` and canonical payload digest, eliminating a separate lookup/add race.

`DispatchUnknown` no longer authorizes retry or permanently kills the scheduler. The next tick first performs bounded `ReconcileOnly` recovery for the same identity. Only an explicit `Missing` result may append `requeued_proven_absent`, release that same occurrence/client identity, and allocate a new durable step attempt on reclaim.

For external effects, automation computes `AuthorizedEffectIntent` itself over run/step/attempt/operation/subject/destination/payload/final-use-scope/policy-generation/dependency-state/compensation identity. `FinalUseAuthority::claim` durably consumes the signed grant nonce. The synchronous path uses `with_verified_use`; the async path uses an active-dispatch fence entered after live revalidation and before the provider future is created. No mutex guard is held across `await`. A concurrent trusted revocation update returns explicit `DispatchInProgress` and may commit only after the bounded provider future completes or is cancelled, preserving the same before-or-after linearization without blocking a runtime thread. The immutable dispatch attempt separately records the concrete grant ID, authority epoch and nonce digest. Driver errors are allowed only before provider contact; ambiguous contact or a non-terminal provider acknowledgement returns `Indeterminate` and is later closed only by append-only provider reconciliation.

## 8. Failure semantics, recovery and rollback

Crash boundaries are explicit:

- before durable intent: no provider claim exists;
- after intent/claim but before proven provider contact: an exact provider-absence proof requeues the same TaskFlow run, preserves occurrence/client identity, and allocates a new step attempt before any retry;
- after possible App Server admission: stable-id `ReconcileOnly`; no blind duplicate;
- after persisted turn: store turn identity, then observe terminal status from persisted turn history;
- after terminal provider observation but before run projection settlement: reconcile the historical step first, then a newer Agent generation may re-fence only the TaskFlow run projection for `Indeterminate -> Reconcile`; it does not replay the effect;
- indeterminate external effect: dependent mutation remains blocked; restart scanning returns both never-observed attempts and attempts whose first observation is `indeterminate`. A later terminal/proven-absent owner receipt is appended as separate reconciliation evidence and never overwrites or redispatches the first attempt.

Rollback preserves schedule revision, deterministic occurrence identity, stable queue identity and provider reconciliation state.

## 9. Security, privacy and threat controls

Authority is operation-bound, subject-bound, scope-bound, payload-bound, destination-bound, short-lived and revocation-aware. `authorized_effect.rs` computes the canonical effect-intent digest inside the owner and verifies that the signed final-use binding's subject, destination, request digest, scope digest and payload digest all match that exact intent before the effect driver can run. Automation never owns the signing key.

Credentials and provider secrets remain outside general TaskFlow receipts; durable records carry stable identifiers and digests. Stale generation, changed payload, changed stable-client input, reused final-use nonce and revoked grant fail closed.

## 10. Performance, capacity and hot-path policy

Current source bounds include:

- schedule catch-up ceiling <=1024 occurrences;
- Calendar V2 timezone transition profile <=512 transitions and bounded calendar search <=1032 candidate days;
- occurrence recovery query <=1024 rows;
- Agentd terminal observation is bounded to <=16 pages × 100 persisted turns per recovery pass; when more history remains, the opaque `next_cursor` is persisted under exact-CAS and the next pass resumes there. A known turn can therefore age beyond 1600 recent turns without permanent invisibility or unbounded full-history materialization;
- one historical occurrence reconciliation plus at most one new scheduler admission per Agentd tick;
- TaskFlow graph/step bounds inherited from the existing TaskFlow ledger/outbox.

These are source limits, not deployment measurements. Target-host latency, backlog and restore evidence remain activation gates.

### Circuit capacity targets to measure

Do not extend the current 256-node/1024-edge V1 graph ceiling by documentation or
claim neural-inference latency from pure ledger tests. Measure logical definitions,
active runs, ready activations, fan-out/fan-in, bounded feedback depth, event backlog,
retained history and active inference separately. Report p50/p95/p99 end-to-end
latency, queue age, starvation/rejections, peak RSS/GPU, bytes written per durable
choice, recovery scan work and horizon exhaustion. Growth/restore tests increase
history while keeping active workload fixed. History compaction preserves original
choice/operation identities, revocation and unresolved effects; no whole-history
replay or unbounded event retention is assumed to scale indefinitely.

Local sensory/reflex controllers do not route millisecond safety decisions through
a durable cognitive TaskFlow or Laya service. They keep their existing qualified
local mechanisms. Circuit scheduling is event-driven, bounded and partitionable;
its uniform protocol does not imply a common latency class or one global queue.

## 11. Observability and operations

Operate the existing Agentd `AutomationScheduler` and `AutomationStore`. Treat the compatibility task state as schedule-control state, not execution terminality. The authoritative execution status is the durable occurrence/TaskFlow chain.

Important operator classes include aged `indeterminate`, queue-reconcile mismatch, terminal-scan cursor rejection/repetition, authoritative pagination exhaustion without the bound turn, schedule parked by `overlap=forbid`, catch-up saturation and run-recovery re-fencing. An unknown effect is not safely rerunnable by default.

## 12. Verification and qualification

Focused source tests include:

- `codex-rs/hepta-automation/tests/durable_causal_chain.rs`
- `codex-rs/hepta-automation/tests/automation.rs`
- `codex-rs/hepta-automation/tests/taskflow.rs`
- `codex-rs/hepta-automation/tests/taskflow_kernel.rs`
- `codex-rs/hepta-automation/tests/taskflow_step.rs`
- `codex-rs/hepta-automation/src/schedule_v2.rs`
- `codex-rs/hepta-automation/src/authorized_effect.rs`
- `codex-rs/hepta-automation/tests/authorized_effect.rs`
- `codex-rs/hepta-automation/src/effect_dispatch_ledger.rs`
- legacy `src/effect_executor_tests.rs` only through the test-only reducer
- Agentd automation/recovery unit and process qualification paths.

In `codex-rs`, exact-head CI runs the full `codex-hepta-automation` package, repeats it with `taskflow-structural-qualification`, and executes the explicit TaskFlow kernel/step Bazel targets. The deterministic synthetic merge runs the same TaskFlow qualification set. Documentation, source mapping and fixture presence are not substitutes for those receipts or for provider/host qualification.

### Neural Circuit test plan (not executed-test receipts)

| Case | Required observation |
| --- | --- |
| NC-01 legacy embedding | V1 definition/receipt digests, cycle rejection and persisted run interpretation remain unchanged |
| NC-02 context-dependent paths | one circuit handles simple, conflicting, unavailable-organ and exhausted-budget cases through different admitted traces |
| NC-03 event ingress | duplicate identical events dedupe; changed payload, stale scope and unsupported version reject; manual starts need no fake schedule |
| NC-04 joins and feedback | all/any/quorum, arrival ties, late outcomes, no-progress and feedback horizon are explicit and bounded |
| NC-05 decision crash cuts | before choice commit no downstream dispatch; after commit recovery uses the recorded choice despite a changed model/policy |
| NC-06 cross-owner checkpoint | crash between cell commit and run acknowledgment reconciles original receipt without duplicate cell update |
| NC-07 effect ambiguity | lost response, timeout and parent cancellation never imply absence; no duplicate effect after restart |
| NC-08 nested budget/fairness | parent/child reservations do not double spend, loops do not starve siblings, rejected admission has no side effect |
| NC-09 reusable organ | replacing internal cells leaves the declared external port usable; incompatible public semantics require a new version |
| NC-10 evolutionary separation | cell-only, routing-only and structure changes are evaluated separately with no-change and matched total costs |

Write these tests in the existing owning packages/product path. Do not add a
per-circuit global gate or count test definitions as model/host qualification.
The first cooperation experiment remains the read-only retrieval organ.

## 13. Implementation sequence and work packages

Applicable package: `TASKFLOW-1-EXECUTION-BOUNDARY` (`source_implemented_execution_pending`).

Implemented convergence sequence:

1. preserve existing scheduler/store;
2. add schedule revision and deterministic occurrence identity;
3. compose occurrence into existing durable TaskFlow run/events;
4. promote the qualified step outbox into normal schema;
5. replace ordinary queue-add with stable-id reconcile semantics;
6. add bounded lost-reply and persisted-turn terminal reconciliation;
7. propagate TaskFlow terminal state before occurrence terminal state;
8. expose the final-use-authorized external-effect driver seam with owner-computed canonical intent identity;
9. add append-only restart reconciliation for initially indeterminate provider attempts;
10. add Calendar V2 with explicit timezone/tzdb and DST gap/overlap semantics without changing legacy schedule meaning;
11. expose Calendar V2 through the existing generation-fenced Agentd control plane with additive capability negotiation;
12. preserve bounded terminal observation when a known turn ages out of the recent window by durably CAS-advancing the App Server continuation cursor; each pass stays bounded and only full pagination exhaustion may convert the missing known turn to indeterminate;
13. keep concrete provider activation, target-host qualification and independent evidence gates separate.

No second TaskFlow engine or scheduler is admitted by this work package.

### Circuit extension sequence

The first source slice is now implemented in `codex-rs/hepta-automation/src/neural_circuit.rs`.
`NeuralCircuitCandidateV1` freezes a circuit version, exact predecessor, routing-policy
digest, parameter-bundle digest, resource-profile digest and bounded typed roles. It
compiles onto the existing TaskFlow definition owner and returns a receipt binding both
digests; it creates no executor, store or authority. `validate_circuit_successor_v1`
requires version+1 and the exact predecessor digest and rejects capability widening, so
a circuit cannot silently turn a routing/parameter update into a new authority surface.
The V1 compiler deliberately reuses TaskFlow's acyclic/reachability/terminal checks.

Remaining circuit work is narrower and stays on the existing owners:

1. Bind actual DecisionCells and organ ports through the existing product/inference
   path; persist effect-relevant choices and exercise cross-owner crash recovery.
2. Add declared bounded feedback, subcircuits, cancellation and resource fairness;
   never enable general cycles by removing V1 checks.
3. Evaluate shared reusable retrieval circuits under the four task conditions;
   compare cell-only, routing/termination and joint updates against no-change.
4. Admit next-generation structural changes only after state/operation migration,
   current revocation, compatible bundle and independent outcome qualification.

The source-level candidate/compilation slice is not runtime activation: `OrganCall` and
`WaitJoin` remain restricted roles mapped onto the existing TaskFlow execution model,
and no external effect is enabled merely because a candidate compiles.

Circuit Runtime is a responsibility evolution, not an instruction to create a
second crate/daemon/store. Keep TaskFlow names/legacy APIs until real consumers
justify extraction or rename; preserve version dispatch and historical readers.
Source coding can proceed by affected owner scopes; deployment/effect/learning
qualification is required only where the corresponding boundary is exercised.

## 14. Activation, compatibility and retirement

The existing Agentd -> App Server automation activity now has a repository source composition path, and Calendar V2 creation is product-addressable through the same generation-fenced Agentd control plane after `automation.calendar_v2@1.0` capability negotiation. This does not activate arbitrary external effects: the repository contains an attestation-gated HTTP provider-effect transport, but `CALLERS.toml` still has no product caller for that adapter/coordinator and Agentd has no independently provisioned `FinalUseAuthority` host configuration for TaskFlow effects. Each activated concrete effect owner/terminal observer therefore still requires its own registered product caller, authority configuration, target-host qualification and acceptance evidence.

Compatibility adapters and the legacy `Submitted` tick can be retired only after all callers move to occurrence-terminal semantics. Historical causal-chain records remain interpretable during retirement.

### Circuit adoption and historical interpretation

A circuit upgrade freezes definition, routing/termination policy, cell parameters,
public ports and state compatibility for a run. Existing runs continue on their
admitted definition or undergo an explicit current-fence migration; new definitions
cannot reinterpret prior choices. Retirement stops admission, drains/classifies
work, migrates or seals state, preserves unresolved child/effect records and then
removes routes. Rollback creates a fresh generation under current revocation.
Cancelling a circuit never deletes an already executed operation. Learned future
policy adoption is not permission to rewrite old run histories or widen authority.

## 15. Definition of module completion

For this source candidate, the Agentd/Codex causal state chain, Calendar V2 owner plus capability-negotiated Agentd creation surface, durable TaskFlow step/outcome chain, producer-owned `kernel.operations::OperationIntentV1` composition and final-use effect seam are present and bounded. Repository-controlled Calendar V2 product control is composed. External-effect product composition is **not** closed merely by the seam: a real registered caller must bind an independently provisioned `FinalUseAuthority` and an independently attested provider contract/terminal observer. Product completion also requires selected-host execution evidence, authentic/current timezone-profile provenance, deployment qualification, independent acceptance and activation evidence. Promotion/release remain separate externally governed states.

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `automation.taskflow` to `LANE-B-RUNTIME` and continues to require:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Consumed readiness protocol:

- `ActuatorReconciliationReceiptV1`

This overlay changes no acceptance, activation, promotion or release authority.

## 17. Source implementation receipt

| Operation | Native source | Composition / observation |
|---|---|---|
| `register_schedule` | `codex-rs/hepta-automation/src/schedule_v2.rs`, `src/store.rs`, `src/lifecycle.rs`; `codex-rs/hepta-agent-protocol`; Agentd `state_control.rs` / `client.rs` | append-only Calendar V2/legacy schedule revision and policy metadata; capability-negotiated generation-fenced product control |
| `materialize_due` | `codex-rs/hepta-automation/src/scheduler.rs` | deterministic occurrence before provider contact |
| `claim_occurrence` | `src/lifecycle.rs` | Agent generation/token + durable occurrence event |
| `taskflow_run` | `src/automation_taskflow.rs`, `src/taskflow.rs` | deterministic durable run and transition ledger |
| `step_outbox` | `src/taskflow_step.rs` | durable prepare/claim/observe/reconcile chain |
| `queue_dispatch` | `codex-rs/hepta-agentd/src/automation.rs` | App Server `thread/queue/reconcile(AllowIfAbsent)` |
| `queue_recovery` | `codex-rs/hepta-agentd/src/automation_recovery.rs`, schema v19 occurrence cursor | `ReconcileOnly`; <=16×100 per-pass scan with durable exact-CAS continuation across passes; only full pagination exhaustion becomes indeterminate |
| `run_recovery` | `src/taskflow_recovery.rs` | historical-step-first, projection-only re-fence |
| `external_effect` | `src/authorized_effect.rs`, `src/effect_dispatch_ledger.rs`; `hepta-contracts::FinalUseAuthority` / provider-effect contract | owner-computed canonical intent; synchronous or async final-use fence; exact wire-payload digest; provider-stable logical key; immutable attempt/observation/reconciliation; named product host still pending |
| `occurrence_terminal` | `src/lifecycle.rs` | occurs after TaskFlow reconciliation; advances forbidden-overlap recurrence |

Current repository source implements bounded Calendar V2 semantics from an explicitly supplied timezone/tzdb transition profile; it does **not** prove that a selected host supplied a current authentic IANA tzdb profile, nor does it prove multi-scheduler/DST target behavior. The Agentd/App Server Codex automation activity has a real source composition path. A concrete arbitrary downstream effect provider/terminal observer, deployment, independent acceptance, activation, promotion and release remain separate evidence gates and stay false.

## 19. Store schema v19 and product-effect composition

**Automation store schema: v19.** The executable owner opens migrations
through `0019_converged_owner_schema.sql`.  Schema v17 adds immutable
destination-operation deduplication, v18 adds the single timer-writer
lifecycle/epoch, and v19 converges the formerly displaced v17/v18
migration histories without deleting either owner's records.  The
reviewed migration and recovery procedure is
[MIGRATION_AND_RECOVERY_RUNBOOK.md](MIGRATION_AND_RECOVERY_RUNBOOK.md).

Agentd is the named product caller for external TaskFlow effects.  Its
`AutomationExecuteEffect` control method loads an independently
configured, attestation-checked provider host and a persistent
`FinalUseAuthority`, then calls `ProviderEffectTaskFlowDriver` through
`execute_authorized_taskflow_effect_async`.  Exact provider bytes are
hashed before grant consumption; the provider key is derived from the
durable destination plus TaskFlow run/step, and reconciliation performs
lookup only.  This closes the repository-controlled caller gap.  It does
not self-issue provider credentials, final-use signatures, a current
IANA tzdb profile, selected-host measurements or independent acceptance.

Older binaries that do not understand schema v19 must not replace the
writer or open a copied database.  A rollback is a restore of a complete
pre-upgrade snapshot plus its matching binary/configuration, never an
in-place schema decrement.  Same-store timer epoch handoff is supported;
cross-host database transfer remains fail-closed until the runbook's
snapshot, exclusive-writer and digest requirements are independently
satisfied.


## 20. Bounded admission and recovery budgets

The product host uses separate budgets: four historical reconciliations
and eight sequential new admissions per 250-ms wake. The public library
rejects zero and caps a caller at 64 admissions. Every item still crosses
the original occurrence transaction, durable dispatch-intent boundary and
queue/provider acknowledgement before the next item, so batching does not
create unbounded provider concurrency.

Due selection remains ordered by scheduled instant, task ID and occurrence.
`AutomationBacklogSnapshot` exposes a bounded oldest-due/oldest-uncertain
age, pending counts and truncation without claiming work. Stable failure
dispositions distinguish fail-stop, bounded retry, isolated invalid/conflict
input and reconcile-only unknown outcomes. Source constants and target-host
qualification requirements are in [SLO.md](SLO.md).
