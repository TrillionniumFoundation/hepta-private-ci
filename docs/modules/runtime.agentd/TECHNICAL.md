# runtime.agentd technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `runtime.agentd`

**Owner:** `agent-runtime`

**Deputy:** `runtime-control`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.8B-READINESS`

This stable document is the implementation guide for `runtime.agentd`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Compose one agent runtime as a thin lifecycle host and never become a product-domain store.

The primary owner `agent-runtime` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `runtime-control` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `composition`, kind `daemon`, state model `ephemeral` and architecture role `execution_plant` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-agentd`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-agentd`

Non-authoritative implementation evidence roots:

- `codex-rs/hepta-agentd`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The daemon-owned run lifecycle is implemented by [codex-rs/hepta-agentd/src/lane_b_runtime.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime.rs), held by [codex-rs/hepta-agentd/src/state.rs](../../../codex-rs/hepta-agentd/src/state.rs), dispatched through [codex-rs/hepta-agentd/src/state_control.rs](../../../codex-rs/hepta-agentd/src/state_control.rs), and consumed through the typed [codex-rs/hepta-agentd/src/client.rs](../../../codex-rs/hepta-agentd/src/client.rs). The additive local protocol advertises `run.lifecycle/1.1` before clients use these methods. The explicit durable cognitive writer seam remains [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs); it is not installed by normal daemon startup. These are source navigation bindings, not proof that a canonical product caller supplies every authoritative run identity or that deployment qualification has passed. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/runtime.agentd.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.agentd.md).

Detailed development documentation exists across this guide, the implementation
dossier, [runtime service extensions](../../../codex-rs/hepta-agentd/RUNTIME_EXTENSIONS.md),
and [signed ingress and trust configuration](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md).
The implementation map inventories the selected lifecycle, objective-admission,
Neuron and shared Replay boundaries. It is not a closed-world inventory of every
exported method or integration in this crate. Complete rows mean that the listed
symbols have source mappings, not that every module operation is covered or that
their product paths have executed successfully.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `runtime.supervisor`
- `runtime.codex`

Authoritative write domains:

- `runtime_health_observation`

Explicitly denied capabilities:

- `product_domain_durable_fact`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bootstrap and configuration loader`
- `supervision loop`
- `daemon-owned bounded run lifecycle coordinator`
- `local typed control protocol and client`
- `durable state projection`
- `readiness, bounded drain and shutdown controller`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

The default daemon in `codex-rs/hepta-agentd/src/runtime.rs` supervises its tasks through the existing `RuntimeTasks` host. The composition registers required tasks and invokes the automation-owned constructor; adding a normal optional task no longer adds a central completion enum or cleanup branch. Optional failure invokes its owner-local quarantine callback, while a failed quarantine, writer error or generation fence stops the host. Retirement uses cooperative cancellation and acknowledged owner cleanup, not a timeout relabeled as success.

Typed owner attachments in `AgentdState` remain explicit fields. `RuntimeTasks` does not load plugins, issue authority, select topology, migrate a schema or hand off a durable writer. The typed runtime catalog and the standalone Supervisor module-lifecycle source are not evidence that default Agentd implements arbitrary live topology replacement. Canonical intelligence is now routed through the existing authenticated `ObjectiveStart` control ingress only when both the bounded runner and a host-owned seven-owner invocation provider are installed. That all-or-none profile advertises `intelligence.canonical_v1`; a runner by itself advertises nothing, compatibility `RunStart` remains distinct, and unsigned evaluation input remains rejected. The canonical evaluation input is
`AgentdQualifiedEvaluationV1`: a sealed `learning.eval::ProductQualificationReceiptV1`
from the fenced product runner plus the current evaluator's exact use attestation.
Agentd checks the receipt seal, current trust and owner key/epoch, original signed-evidence
lifetimes and scheduled revocations through the receipt owner, candidate/objective and run/snapshot/context/candidate-set bindings.
It cannot qualify caller-supplied metric intervals. The typed host input changed
from `signed_evaluation` to `qualified_evaluation`; evaluators must sign
`intelligence_evaluation_binding_payload_v2`. This does not implement a durable
product-qualification recovery store or establish full runtime activation.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Executable composition profiles

| Profile or attachment | Existing owner and entrypoint | Current boundary |
|---|---|---|
| Ordinary daemon | `main.rs` → `runtime::run` → `RuntimeTasks` | Embeds the existing App Server and attaches available owner stores; no canonical invocation provider or production cognitive writer is constructed implicitly. |
| Signed Objective admission | `state_control.rs::ObjectiveStart` → `objective_runtime.rs::ObjectiveRuntimeHost::submit` | Publishes `RunStartRecordV1` through the learning-ledger journal, revalidates current AuthBus trust and Fleet generation/fence, then admits the run. |
| Canonical preparation | Explicit runner plus `AgentdIntelligenceInvocationProviderV1` → `state.rs::start_canonical_intelligence` | Calls the seven existing owners and attaches the prepared context to the sole run coordinator. This preparation does not start a physical Codex turn. |
| Durable cognitive writer | Explicit `AgentdProductionWriterHost` attachment | Uses the cognitive-store owner and independently verified writer lease; ordinary startup does not establish this attachment. |
| Neuron and shared Replay | Explicit `AgentdNeuronOwner` / `AgentdSharedReplayHostV1` | Owner APIs are implemented; neither is an automatically activated daemon decision loop or production model-selection authority. |

Supplying the CLI's three intelligence-authority options constructs the runner
only. Canonical capability advertisement also requires a host-owned invocation
provider. Wire requests cannot provide the seven owners' profiles, artifacts or
trust objects. The existing compatibility `RunStart` path remains a trusted local
host lifecycle API, separate from signed Objective admission.

Canonical generation domains remain distinct. `AgentdIntelligenceInvocationV1::validate`
requires Body's process generation to equal `identity.spawn_generation`, while the
durable RunStart names the Fleet Running generation and exact Agent fence.
`AgentdIntelligenceProductRunnerV1::prepare_for_run_start` checks the run/objective,
body digest, artifact-set digest and authority epoch against that authenticated
durable tuple before and after existing owner preparation. It then projects only
the physical run/context request identity, lifecycle generation, fence and deadline
to the durable values; canonical Body and owner receipt domains are preserved.
This source binding does not prove physical execution or a successful signed
seven-owner `ObjectiveStart` regression. Capability advertisement and component
preparation tests remain separate from exact-candidate Running-path evidence.

### Multiscale DecisionCell integration target

Compose cells through existing organ/Neuron/inference owners, not one service or database per node. Preserve cancellation, bounded task lifetime, generation fencing and terminal reconciliation. Attach the same product decision path rather than extending several bespoke main-loop branches per new backend.

Compose the evolved TaskFlow owner, event ingress and existing cell/organ ports. Calendar wake-up and direct-event admission remain distinct; no fake occurrences or standalone duplicate runtime. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: optional organ outage, task retirement, in-flight unknown effects and no duplicate executor.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Independent workspaces with authorized shared experience

A common Nervous System means reusable knowledge/parameters and coordinated
collection, not one mutable context. Agentd owns each Agent's current objective,
session linkage, workspace handle, live Circuit identity and lifecycle. Keep file
writes, credentials, environment, sockets, Cell hidden state, KV/context caches,
execution leases and in-flight effects in their existing private owner boundaries.
A directory layout is not sufficient isolation: bind canonical workspace/project
and base revision, handle symlink/path substitution, protect shared caches and
separate process-wide mutable state. Shared physical serving is allowed only with
per-request scoped state and tested cleanup; replicas do not grant cross-access.

The context compiler selects an allowed projection of shared Memory for this run.
No publication is broadcast into all sessions, and another Agent's objective or
prose cannot become a system instruction. Explicit handoff carries bounded typed
source references and task-state facts, not the sender's full private context or
credential-bearing environment. An authorized patch/artifact is transferred with
its base/lease/predecessor through the owning workflow, never by editing a peer's
working directory. Worktrees alone do not isolate writable repo metadata or caches.

Load a coherent immutable common/domain/Agent parameter bundle per admitted run.
Each Agent retains its own recurrent/adaptation state. Training jobs use isolated
candidate workspaces and cannot mutate active shared tensors or optimizer state.
Adoption waits for the existing snapshot/lifecycle boundary with state/cache/
calibration compatibility; a stale actor is logged or readmitted, never relabelled
as the current policy. Private adapters cannot enter common training by default.

An Agent generation is not a Memory shard's durable identity. On shutdown/retirement,
reconcile outstanding contributions and preserve owner-routable source IDs; move
responsibility only through a fenced owner handoff. Offline source/permission state
cannot silently renew on restart. Existing source and wire APIs are unchanged by
this target. [HNMF](../../hnmf/TECHNICAL.md) owns contribution/learning semantics;
[causal evaluation](../../learning/CAUSAL_LONGITUDINAL_SPEC.md) owns clean-Agent tests.

### Same-host shared Replay composition

[AgentdSharedReplayHostV1](../../../codex-rs/hepta-agentd/src/shared_terminal_cell.rs)
consumes existing Memory, ledger and artifact owners. It binds Replay to the
consumer/workspace/parameter scope, and binds each training decision to the exact
owner/Memory/revision support rather than equal text. Train, load and prediction
revalidate source use and frozen ledger. Load/prediction also check the supplied
artifact-owner registry and exact bytes. The embedding owner must supply the
current registry; this candidate API does not mint signed production CURRENT.

The integration test uses separate source/receiver stores and covers no sharing,
Recall-only, Replay-only, both, altered bytes/targets/workspaces, independent
artifact revocation and support withdrawal after loading. This is an owner-path
behavioral test, not a real-task transfer study, process-isolation proof or
production Laya service. Selected model state and effect authority are unchanged.

## 5. Contracts, ports and compatibility

Produced contracts:

- `CodexContextAttachmentV1`
- `DomainRead::runtime_health_observationV1`
- `ModulePort::runtime.agentd::browser.servo`
- `ModulePort::runtime.agentd::channel.matrix`
- `ModulePort::runtime.agentd::ui.control`
- `ModulePort::runtime.agentd::ui.native`

Consumed contracts:

- `DomainRead::agent_lifecycleV1`
- `DomainRead::fleet_registryV1`
- `DomainRead::release_selectionV1`
- `DomainRead::runtime_instance_projectionV1`
- `DomainRead::thread_sessionV1`
- `IntelligenceHostEnvelopeV1`
- `ModulePort::runtime.codex::runtime.agentd`
- `ModulePort::runtime.supervisor::runtime.agentd`

Critical protocol schemas:

- `AgentRunSnapshot` / `AgentContextAttachment` / `AgentRunReceipt` on the local `run.lifecycle/1.1` capability. These are Agentd-local transport types and do not replace canonical cross-module contracts such as `RunStartSnapshotV1`.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

### Local lifecycle operation surface

The transport types and method variants are defined by
[hepta-agent-protocol](../../../codex-rs/hepta-agent-protocol/src/lib.rs).
The socket is a trusted host control surface; capability advertisement identifies
the API version and does not grant a caller effect authority.

| Operation | Daemon method or embedding API | Implemented meaning |
|---|---|---|
| Start | `RunStart` | Validates the current Agent generation/fence and freezes a supplied tuple; it does not authenticate a signed Objective or dispatch a turn. |
| Signed start | `ObjectiveStart` | Validates the signed structured input, publishes the owner journal record and uses current trust before lifecycle admission. |
| Attach | `RunAttachContext` | Requires the entire frozen tuple and compilation/context identities to match. |
| Dispatch marker | `RunMarkDispatched` | Marks the local boundary; the caller still owns the real turn invocation. |
| Cancel | `RunCancel` | Cancels before dispatch or records a pending post-dispatch cancellation; it does not itself send App Server interrupt. |
| Observe | `RunObserveTerminal` | Accepts the trusted host caller's phase/observation and preserves post-dispatch uncertainty; it is not a signed provider receipt. |
| Inspect / release | `RunStatus` / `RunReleaseClosed` | Reads the local receipt / removes a closed record at its exact revision. `Indeterminate` is unresolved and cannot be released as closed. |
| Recover | `AgentRunCoordinator::recover_indeterminate` | Explicit component API only. No recovery method is advertised by the daemon wire or typed client. Authentication of the external durable owner and daemon composition remain required work. |

The current lifecycle error path maps `AgentRunError` to a protocol rejection
message. Consumers must read the returned receipt and its revision, cancellation
deadline and phase; neither an RPC reply nor a locally supplied terminal flag
establishes an external effect result independently.

#### Recipient identity and transport compatibility

New `AgentdClient` requests include `target_agent_id=Some(expected_agent_id)`;
the receiver rejects a mismatch before method dispatch. An absolute custom socket
path remains supported by the client, including a path alias: it is the receiver
identity check, not the pathname, that prevents an A-targeted request from mutating
B. The server itself binds only its registered owner-layout control socket.
Unix clients and servers check the kernel-reported peer OS user in addition to
private socket permissions. This authenticates the OS user, not an individual
Agent or a hostile process running under that same user.

The target field is additive and optional for legacy requests. A legacy request
without it retains the trusted-local compatibility semantics and does not prove
recipient isolation. A new client connecting to an older strict decoder fails
closed on the unknown field; there is no automatic identity-free downgrade.
The current Windows transport retains its existing profile until equivalent peer
identity is available. Server connection tasks belong to one `JoinSet` and are
stopped and joined when control ingress retires. Aborting a connection does not
cancel or settle a durable effect already owned by another task.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `runtime_health_observation`

Read-only data dependencies:

- `agent_lifecycle`
- `fleet_registry`
- `release_selection`
- `runtime_instance_projection`
- `thread_session`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

`AgentdState` owns exactly one mutex-protected `AgentRunCoordinator` for the process generation. Its active-run ceiling is the supervisor/Fleet `ResourceBudget.max_concurrent_turns` for this Agent (within the supported local bound), and it retains at most 1024 records until the terminal consumer explicitly releases a closed record. The coordinator freezes request/objective/body/artifact digests together with authority epoch and deadline; context attachment must repeat that complete tuple exactly. Attachment and dispatch re-check the deadline, cancellation records a bounded reason, and the runtime monitor continuously advances deadlines. Post-dispatch cancellation has a 3-second acknowledgement deadline; if no terminal owner observation arrives, the run becomes `Indeterminate`. Terminal observations preserve the dispatch-boundary distinction, and `RunReleaseClosed` removes a closed record only with its exact expected revision. Existing identical operations are idempotent; reused identities with changed semantics conflict.

The run map is intentionally ephemeral and is not a second durable execution ledger.
The component recovery method accepts an exact prior snapshot/revision/context/receipt
identity and rehydrates it only as `Indeterminate`. That method validates structure
and identity; it does not authenticate the external durable execution owner and is
not composed into daemon ingress. A product recovery caller must establish that
trust and preserve the prior dispatch identity. An absent local record cannot prove
completion or authorize redispatch.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

### Durable run-start projection

The daemon coordinator exposes the owner-internal `start_revalidated_run_start` bridge for a `RunStartRecordV1` that has already been revalidated by the product owner against current trust. The bridge fixes the durable-owner → daemon-owner mapping: `admission.admitted_source_digest` is the runtime request identity, and objective/body/artifact/authority/generation/fence/deadline are copied from the durable record. `ExplicitAbstain` is terminal at objective admission and is never inserted as an executable run. A retained journal record is not, by itself, proof that its signer remains current; raw-record authentication is intentionally outside this bridge.

The current caller is implemented: `AgentdState::start_current_run_start_record`
rechecks current AuthBus trust, Fleet generation and the Agent's exact fence twice
before projection. `ObjectiveRuntimeHost::submit` uses it in compatibility mode;
canonical preparation revalidates the same durable input after asynchronous owner
work. `ObjectiveRuntimeHost::reconcile` skips stale, expired, abstained or revoked
records. In a configured canonical profile, startup waits for the authenticated
Objective retry instead of silently admitting a legacy compatibility record.
The journal proves Objective publication, not a physical turn's dispatch or
terminal state; complete product Decision/Outcome recovery remains separate.

Admission additionally requires the live `Running` lifecycle, App Server readiness,
critical owner stores, revocation readiness, required ports, open admission and no
generation fence. The final lifecycle mutation holds the runtime admission lock
through the run-coordinator mutation, so a stale readiness snapshot cannot admit
a run after local drain closes admission. Reconciliation remains a distinct path
for existing runs. These local locks do not freeze an external trust file or
provide cross-owner atomicity.

The runtime-to-run lock order serializes local admission with drain; it does not
make asynchronous owner preparation plus run/context insertion one transaction.
The prepared immutable tuple uses one admission time for local start and attachment,
while prior durable Objective publication and owner preparation retain their own
transaction boundaries. An admission or changed-context retry error does not roll
back those owners' facts and must remain an explicit incomplete outcome. It cannot
be relabelled completed preparation or external dispatch; an exact retry preserves
the original run identity and any existing local context.

### Bounded synchronous effect-owner bridge

The existing HTTP effect host in `automation_effect_host.rs` runs its complete
synchronous owner/authority/provider bridge inside `spawn_blocking`, with at most
four admitted provider workers. The worker retains its permit and final-use
dispatch guard after its control caller stops awaiting; cancellation of that
caller does not undo a dispatched provider effect. Trust is reread after worker
scheduling and a fresh dispatch clock is used before acquiring authority. Lookup
uses the same bound and keeps the effect `Indeterminate` when capacity or a trusted
observation is unavailable. Provider observation is checked against the owner
fence at observation time.

Before its first durable/provider await, `reserve_automation_effect_worker`
rechecks the complete live readiness predicate while holding the same runtime lock
used by drain observations and synchronously reserves an attached host worker
slot. The reservation is a non-cloneable, host-bound owned value consumed by
`execute_reserved` or `reconcile_reserved`; direct host wrappers are test-only.
Its occupied slot is visible before durable admission and stays visible while
awaiting or running provider work. Drain therefore cannot observe zero workers
and then admit a late worker through a stale copied readiness state.

The host binds the full revocation head, rejects changed contents at an unchanged
frontier, and bounds reads of the opened protected configuration/revocation files
while checking object identity. This keeps synchronous I/O off the Tokio control
executor and preserves durable uncertainty. It is not cancellation-safe external
effect rollback, cross-owner atomic shutdown or independently provisioned trust.
The current host drain snapshot requires no local effect workers, no durable armed
or indeterminate effects, no automation blockers and actual App Server drain
acknowledgement. The reservation closes this registered HTTP host's late-admission
window. Normal App Server drain still closes all RPC admission. Its original
`AppServerDrainHandle` now retains an embedding-only historical observation
capability, enabled only after request/thread-start background tasks and every
thread writer successfully join. A timeout leaves the acknowledgement false.
`observe_exact_submission` uses the original `StateRuntime` and pure queue
SELECTs, rechecks the selected rollout pointer before and after the read, and
cannot repair metadata, reopen a store, reserve a message or start a turn.

The historical scanner binds the owning thread, exact client ID and payload.
Only matching `TurnComplete` / `TurnAborted` records prove a terminal outcome;
recovery-unready and restart records clear an older terminal observation. Plain
and compressed scans require a complete record stream and are bounded at 1 MiB
per record, 32 MiB of scanned bytes, 65,536 lines and four seconds. A partial or
over-limit scan returns `Unknown` instead of trusting a terminal record from a
prefix. Agentd uses this capability for settlement while Draining, rechecks
Running admission before each subsequent dispatch, and never requeues an unknown
effect. Unresolved history does not starve later admitted drain blockers.

This closes the missing source observation path after normal RPC shutdown.
Native and full socket/daemon drain execution evidence remain separate;
target-host shutdown and additional downstream-owner drain/recovery contracts
still require their own qualification.

## 8. Failure semantics, recovery and rollback

Run deadlines remain live after admission: expiration before dispatch becomes a local terminal cancellation; expiration after dispatch moves the run to `Cancelling` and still requires owner terminal observation. Shutdown closes new admission before teardown, converts pre-dispatch work to local cancellation, moves dispatched work to cancelling, and keeps the control path running for a bounded drain. After the drain deadline, unresolved dispatched/cancelling work becomes `Indeterminate`; a second bounded reconciliation window accepts exact terminal observations. If uncertainty remains, shutdown reports recovery-required rather than fabricating success/failure.

Recovery after process loss is an explicit component seam: a trusted embedding
caller must provide the exact prior operation identity, and the coordinator can
only rehydrate it as `Indeterminate`. The daemon has no authenticated recovery
ingress or automatic execution-owner reconstruction yet; the component API cannot
redispatch. The local control server distinguishes saturation from disappearance
by returning a typed overload/retry frame instead of dropping the connection.
`run.lifecycle/1.1` adds explicit closed-record release and exposes the pending
cancellation-ack deadline in receipts so callers can reconcile rather than guess.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

This registry fact does not mean the module has no threats. Its concrete host
boundaries require the following controls and review:

| Boundary | Current control | Remaining trust or composition requirement |
|---|---|---|
| Local control socket | Private owner socket, bounded frame/connections, exact Agent generation/fence | Treat socket writers as trusted host code. Owner-only Unix permissions do not isolate hostile code running as the same OS user. |
| Signed Objective publication | Current issuer signature/expiry, replay frontier, durable journal and final-use trust/fence checks | Configure the real issuer/profile and retain their owner state across recovery; the publication grants no effect authority. |
| Local terminal observation | Exact run/revision and permitted lifecycle transition | The caller must be the trusted execution owner; the supplied boolean is not independently authenticated provider evidence. |
| Component recovery | Exact frozen tuple, prior revision, context identities and `Indeterminate` only | Compose an authenticated durable-owner recovery path before using it for daemon restart recovery. |
| Private workspace / stores | Canonical manifest workspace, generation checks and existing owner stores | Test the selected OS/process profile; shared UID, worktrees and reusable caches alone do not prove hostile-Agent isolation. |

The canonical intelligence freshness reader in `intelligence_authority_file.rs`
reads at most 64 KiB plus one overflow-sentinel byte from the same opened handle.
On Unix it validates file identity/version and the canonical namespace chain
before and after reading; an immediate writable parent is rejected, and an upper
writable ancestor is accepted only under the trusted sticky-directory policy.
Stable canonical aliases remain compatible, but alias or parent-object replacement
during the read fails closed. The runner rejects weak Ed25519 verifier keys and
uses strict signature verification before returning current owner state.

The private `OperatorNamespace` policy is also applied at file-open boundaries for
AuthBus and Evidence trust, recovery frontiers, replay checkpoints, Objective
journals, explicit effect configuration and plasticity bootstrap files. Startup
checks the Fleet root and the selected home/run writer namespace. Plasticity
mutable bootstrap opens additionally require one link and prohibit group/world
writes on Unix, checking the path before open and the handle/path after open;
newly created mutable handles receive the same check. Read-only bootstrap inputs
retain their existing permissions and link contract. These open-time checks do
not replace the native owner's receipt, anchor, signature or recovery checks.
Prompt state
uses descriptor-bound, private regular files before truncation or publication.
The optional Browser/Servo profile hashes artifacts incrementally with an 8 KiB
buffer and a size-limited handle, then launches the verified canonical paths.
These checks reject unsafe writable ancestors; trusted sticky ancestors remain
compatible. They do not attest a child process's loaded image.

Fleet's owner now checks every registered peer subtree before legacy migration
or control-file reads. Its private `control_file.rs` binds custody to the Fleet
root owner (and root on Unix), rather than the reader's effective UID or the
individual file's self-declared owner. It rechecks ancestor directory and opened
file identity, permissions and bounded bytes; Unix nonblocking/no-follow opens
reject a regular-file replacement by a FIFO or final symlink. Directory link
counts may change normally, and Fleet's existing hard-link publication/recovery
remains supported. Text control reads are capped at 1 MiB; release-manifest JSON
reads retain their 32 KiB bound. Catalog hashing streams the same inspected handle against
its initial length. Unsafe peer namespaces now fail before migration side
effects, closing the prior whole-catalog source gap. Selected-platform execution
and custody qualification remain separate.

This is a bounded freshness observation within the trusted operator-UID/root
boundary. It neither isolates malicious same-UID/root code nor holds a namespace
lock or prevents an authority update after the observation. Non-Unix targets keep
their existing regular-file/alias profile and available version checks; Unix inode
and namespace guarantees are not claimed there. Reader and signature source tests
must still execute for the selected candidate before these controls are qualified.

The independently retained AuthBus replay checkpoint also revalidates private file
and parent ownership/protection for every read/publication, checks the opened file
against the path object, bounds read bytes, and rejects hard-link or namespace
substitution. Replacement writes and syncs a create-only private temporary file,
rechecks the exact predecessor, renames it and syncs the parent. A failed temporary
creation does not remove another publisher's file. The checkpoint remains a
Unix-specific owner boundary; a failed or ambiguous publication requires exact
reconciliation rather than a new replay identity.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.agentd.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs) and the linked implementation components.

| Enforced local bound | Current value | Owning source |
|---|---|---|
| Daemon active runs | Fleet `max_concurrent_turns`, validated in `1..=32` | `state.rs`, Fleet `ResourceBudget` |
| Retained run records | 1024; closed records require explicit release | `lane_b_runtime.rs` |
| Run identity / cancellation reason | 128 / 512 bytes | `lane_b_runtime.rs` |
| Control connections / serialized frame | 32 / 65,536 bytes | `control.rs`, `hepta-agent-protocol` |
| Control exchange / overload-write timeout | 2 seconds / 50 milliseconds | `control.rs` |
| Cancellation acknowledgement | 3 seconds after dispatched cancellation | `lane_b_runtime.rs` |
| Deadline/generation monitor | 50 millisecond polling | `runtime.rs` |
| Run drain / later reconciliation window | 5 seconds / 2 seconds | `runtime.rs` |
| Task shutdown acknowledgement | 3 seconds | `runtime.rs` |
| Synchronous HTTP effect dispatch / lookup workers | 4 | `automation_effect_host.rs` |

The reusable coordinator supports up to 256 active runs; the daemon uses the
stricter Fleet budget. `Indeterminate` runs continue consuming active capacity.
These constants describe enforcement, not throughput, fairness or target-host SLO
measurements. A dropped client response after a durable publication requires an
exact identity retry/reconciliation rather than a new run identity.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

codex-hepta-agentd starts from AgentdConfig::from_process_environment; the optional --authbus-trust-file is protected host configuration. `HEPTA_COGNITIVE_RETRIEVAL_MODE` is a strict product-profile selector: absent/`compatibility` selects the compatibility path, `hnmf-required` selects HNMF-required mode, and any other value is rejected. The ordinary binary does not mint a `CurrentMemoryRetrievalContext`, so HNMF-required startup without an externally composed current context fails closed. The supervisor supplies the owner identity/generation and existing memory store. Stop new admissions before owner drain; an App Server interruption acknowledgement alone is not terminal task completion.
The local control capability endpoint advertises the additive run lifecycle surface. SIGINT, SIGTERM, and supervisor Draining close run admission before teardown; terminal observation remains possible during the bounded drain/reconciliation window. An App Server interruption acknowledgement alone is never terminal task completion.

Recipient identity, absolute custom-path compatibility, additive target-field
rollout and Unix peer-user limits are specified in Section 5. The server validates
the target before mutation; a response-only identity check would be too late.

Control ingress retirement cancels and joins its admitted connection tasks before
removing the socket. A dispatched effect's blocking worker can outlive that awaiter
and retain cloned owner state, its permit and dispatch guard; connection retirement
does not prove every durable-owner worker has stopped. Existing-socket probing has
a bounded timeout. The live admission and runtime-to-runs lock conditions in
Section 7 apply to run start, context attachment and dispatch marking; status,
cancellation and terminal reconciliation retain their distinct drain-time
availability. Error responses report the owner's lifecycle generation instead of
copying a request-supplied generation.

Supervisor bootstrap supplies `HEPTA_FLEET_ROOT`, `HEPTA_AGENT_ID`,
`HEPTA_AGENT_GENERATION`, `HEPTA_AGENT_HOME`, `HEPTA_AGENT_RUN_ROOT` and
`CODEX_HOME`. The process must start in the manifest's canonical workspace and at
the expected `Starting` generation, with the exclusive writer lock available.
AuthBus trust and external replay-checkpoint files are configured together.
An Objective profile requires AuthBus configuration. Intelligence authority
file/signer/verifying-key options are all-or-none; they construct a runner, while
the host still supplies the invocation provider. HNMF-required mode requires its
current retrieval-context attachment. Startup rejects inconsistent configuration
instead of manufacturing trust, current context or writer authority.

`main.rs` dispatches helper re-execs through `arg0_dispatch_or_else` before loading
the daemon configuration, validating the Fleet startup state or acquiring the
daemon writer lock. Ordinary daemon startup performs those checks inside its
continuation; a helper must not be mistaken for a second daemon owner.

Inspect `Capabilities`, `Health` and `Readiness` before admission. For post-dispatch
shutdown, retain the run identity and exact receipt revision, deliver only actual
owner terminal observations during reconciliation, and preserve recovery-required
outcomes after the bounded windows. Do not use `RunReleaseClosed` to discard an
unknown effect, erase a journal to free capacity, or infer turn completion from an
interrupt acknowledgement. The selected execution owner must supply restart
reconciliation; the local lifecycle map is not a durable dispatch ledger.

Current operating and state-format references:

- [codex-rs/hepta-agentd/src/main.rs](../../../codex-rs/hepta-agentd/src/main.rs).
- [codex-rs/hepta-agentd/src/config.rs](../../../codex-rs/hepta-agentd/src/config.rs).
- [codex-rs/hepta-agentd/AUTHBUS_TEXT.md](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs) covers complete frozen-tuple binding, post-admission deadlines, reasoned cancellation, drain and explicit indeterminate recovery.
- [codex-rs/hepta-agentd/src/state_isolation_tests.rs](../../../codex-rs/hepta-agentd/src/state_isolation_tests.rs) exercises the lifecycle methods through the real daemon control dispatch and verifies capability advertisement and terminal reconciliation during drain.
- [codex-rs/hepta-agentd/src/runtime_tests.rs](../../../codex-rs/hepta-agentd/src/runtime_tests.rs) verifies that bounded shutdown keeps reconciliation live until terminal observation.
- [codex-rs/hepta-agentd/src/objective_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/objective_runtime_tests.rs) covers durable exact replay, protocol identity, and revoked/stale trust; `state_isolation_tests.rs` covers current-trust projection into the daemon coordinator.
- [codex-rs/hepta-agentd/src/intelligence_product_signed_tests.rs](../../../codex-rs/hepta-agentd/src/intelligence_product_signed_tests.rs) covers signed evaluation and owner preparation; it does not by itself establish a configured ObjectiveStart-to-provider process path.
- [codex-rs/hepta-agentd/src/intelligence_objective_ingress_tests.rs](../../../codex-rs/hepta-agentd/src/intelligence_objective_ingress_tests.rs) defines `configured_running_objective_reaches_seven_owners_and_exact_durable_context_receipt` using actual Config/Fleet/writer lock, signed AuthBus input, durable Objective journal and the seven owner algorithms. It compares the complete `ContextAttached` receipt to the durable Running-generation tuple while Body retains its process generation. `objective_binding_rejects_mixed_lifecycle_body_epoch_and_artifacts` covers tuple substitution. These are source test identities, not pass receipts or physical provider execution.
- [codex-rs/hepta-agentd/src/control_tests.rs](../../../codex-rs/hepta-agentd/src/control_tests.rs) covers receiver target rejection, owner-generation errors, connection retirement and backpressure; endpoint identity remains subject to the stated OS-user trust boundary.
- [codex-rs/hepta-agentd/src/intelligence_authority_file_tests.rs](../../../codex-rs/hepta-agentd/src/intelligence_authority_file_tests.rs) covers bounded same-handle reads, namespace/version drift and weak-key/signature rejection.
- [codex-rs/hepta-agentd/src/authbus_checkpoint_tests.rs](../../../codex-rs/hepta-agentd/src/authbus_checkpoint_tests.rs) covers permission/link/directory drift, exact predecessor replacement and conflicting temporary-file ownership.
- [codex-rs/hepta-agentd/src/plasticity_process_file_tests.rs](../../../codex-rs/hepta-agentd/src/plasticity_process_file_tests.rs) covers unsafe ancestor/parent rejection, native snapshot substitution and namespace rechecks, plus `mutable_bootstrap_files_reject_group_or_world_write_before_owner_callback` and `hardlinked_mutable_bootstrap_file_is_rejected_before_owner_callback`. Mutable owner callbacks are rejected before unsafe input reaches them; read-only permission/link compatibility remains covered. Source cases require exact-candidate execution.
- [codex-rs/hepta-agentd/src/automation_effect_host_worker_tests.rs](../../../codex-rs/hepta-agentd/src/automation_effect_host_worker_tests.rs) includes `effect_reservation_is_visible_before_durable_admission_and_drain_closes_the_gate`, exercising the actual Fleet/Agentd/Cognitive readiness gate, pre-durable worker visibility, rejected admission during drain and retained old reservation. It never fabricates a physical App Server drain acknowledgement.
- [codex-rs/hepta-agentd/src/automation_drain_recovery_tests.rs](../../../codex-rs/hepta-agentd/src/automation_drain_recovery_tests.rs), [App Server owner tests](../../../codex-rs/app-server/src/historical_observation_tests.rs), [queue history tests](../../../codex-rs/ext/queue/src/historical_observation_tests.rs) and [StateRuntime read-only binding tests](../../../codex-rs/state/src/runtime/queued_client_binding_observation_tests.rs) cover exact historical settlement, incomplete-history uncertainty, original-owner custody, no metadata repair, and progress past indeterminate history. They are owner/DB/history cases rather than a complete socket/daemon drain receipt.
- [Fleet peer namespace tests](../../../codex-rs/hepta-fleet/src/registry_namespace_tests.rs) and [control-file tests](../../../codex-rs/hepta-fleet/src/control_file_tests.rs) cover unsafe peers before migration, root/nonroot custody, final FIFO/symlink replacement, bounded reads and retained hard-link recovery. Root/nonroot execution requires the stated Unix privilege fixture; source presence is not target-platform qualification.
- [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs); named case: `context_reads_real_owner_content_and_removes_committed_tombstones`.
- [codex-rs/hepta-agentd/src/authbus_dispatch_tests.rs](../../../codex-rs/hepta-agentd/src/authbus_dispatch_tests.rs); named case: `lost_queue_reply_recovers_from_sqlite_using_lookup_only_and_exact_receipt`.

In `codex-rs`, run `just test -p codex-hepta-agentd`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.agentd.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-READ-1-SNAPSHOT-PORT` (co-owned `cognitive.read` final-use integration)
- `P0.8B-READINESS`
- `P0.8D-VERTICAL-SLICE`

The bootstrap package is `P0.8B-READINESS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `runtime.agentd`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `P0.8B-READINESS`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `runtime-control` / `fleet-runtime`.
- Allowed write paths:
- `codex-rs/hepta-supervisor/**`
- `codex-rs/hepta-agentd/**`
- Development predecessors:
- `P0.8A-AST-RATCHET`
- `P0.7A-RUNTIME-BOOTSTRAP`
- Activation predecessors:
- `P0.8A-AST-RATCHET`
- `P0.7A-RUNTIME-BOOTSTRAP`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `P0.8D-VERTICAL-SLICE`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `agent-runtime` / `runtime-control`.
- Allowed write paths:
- `codex-rs/hepta-agentd/**`
- `qa/vertical-slice/**`
- Development predecessors:
- `P0.7D-FAULT-MATRIX`
- `P0.8C-RESOURCE-BUDGETS`
- `P0.8B-READINESS`
- Activation predecessors:
- `P0.7D-FAULT-MATRIX`
- `P0.8C-RESOURCE-BUDGETS`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `runtime.agentd` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `CapabilityBoundaryV1`
- `MigrationPlanV1`
- `ParallelLaneEnvelopeV1`
- `ServiceGraphV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-2-DEBIAN-BRIDGE-SANDBOX`
- `ASM-3-STATE-MIGRATION-QUALIFICATION`
- `EMB-2-REFLEX-MOTOR-ACTUATION`

### Default lifecycle composition and retirement

The default `runtime.rs` path registers long-lived components through the existing `RuntimeTasks` host. Required component exit, generation fencing and rejected quarantine remain host-fatal; an optional scheduler failure removes its owner-local routes while unrelated App Server traffic remains available. Service retirement uses a child cancellation token, owner drain acknowledgement and a monotone service generation. Ordinary host shutdown must not permanently retire the durable timer. The real-process regression is `codex-rs/hepta-agentd/tests/optional_module_restart.rs`; shutdown outcome regressions are in `tests/runtime_shutdown_outcomes.rs`. These tests do not establish general dynamic code loading or authorize writer transfer.

The configured product profile routes authenticated `ObjectiveStart` through the
canonical runner and a host-owned invocation provider, then admits the prepared
envelope and context through the existing Agentd lifecycle. Bare/compatibility
profiles do not install that provider, do not advertise `intelligence.canonical_v1`,
and compatibility `RunStart` is never counted as canonical execution. Real provider
dispatch, an authenticated durable execution-owner recovery caller, durable product
Decision/Outcome recovery and target-host qualification remain separate boundaries.

## 17. Source implementation receipt

This receipt records repository source bindings for the current documentation candidate. It is navigation evidence only; it does not claim product composition, deployment, or external effect authority.

| Operation | Native symbol | Source path | Tests |
|---|---|---|---|
| `compose_runtime` | `pub fn compose_runtime(` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs` |
| `start_run` | `pub fn start_run(` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs` |
| `cancel_run` | `pub fn cancel_run(` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs` |
| `attach_context` | `pub fn attach_context(` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs` |
| `mark_dispatched`, `observe_terminal`, `recover_indeterminate`, `release_closed` | Corresponding `AgentRunCoordinator` methods | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `lane_b_runtime_tests.rs`; daemon control cases exclude component-only recovery |
| Current-trust durable projection | `start_current_run_start_record` | `codex-rs/hepta-agentd/src/state.rs` | `codex-rs/hepta-agentd/src/state_isolation_tests.rs` |
| Signed Objective submit/reconcile | `ObjectiveRuntimeHost::submit`, `reconcile` | `codex-rs/hepta-agentd/src/objective_runtime.rs` | `codex-rs/hepta-agentd/src/objective_runtime_tests.rs` |
| Configured canonical admission / durable binding | `start_canonical_intelligence`, `prepare_for_run_start` | `codex-rs/hepta-agentd/src/state.rs`, `intelligence_product_runner.rs` | `intelligence_objective_ingress_tests.rs` defines signed Running admission and mixed-tuple rejection; execution receipts and physical provider qualification remain separate |

- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json`.
- `currentSourceEvidence` retains the historical lifecycle/projection provenance anchor. It is not an exact-head execution receipt or a claim that later Objective/canonical source is included in that anchor. Current `sourceObjects` and the qualification workflow's actual candidate identity must be checked separately; the legacy repository-wide `sourceBase` remains a common baseline until repository-wide migration.
- The map's `implementedOperationMappingComplete` refers only to its explicit inventory. `nativeSourceMappingComplete=false` and `closedWorldPublicFunctions=false` avoid asserting whole-crate API coverage.
- Consumer callsites and durable owner stores remain an explicit follow-up when not listed above.
- Daemon composition and the explicitly configured preparation path have source callsites. Full canonical product execution, production implementation, deployment qualification, independent acceptance, activation and release remain unestablished until their separate evidence gates pass.
