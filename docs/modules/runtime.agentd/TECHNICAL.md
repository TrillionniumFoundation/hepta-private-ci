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

The daemon-owned run lifecycle is implemented by [codex-rs/hepta-agentd/src/lane_b_runtime.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime.rs), held by [codex-rs/hepta-agentd/src/state.rs](../../../codex-rs/hepta-agentd/src/state.rs), dispatched through [codex-rs/hepta-agentd/src/state_control.rs](../../../codex-rs/hepta-agentd/src/state_control.rs), and consumed through the typed [codex-rs/hepta-agentd/src/client.rs](../../../codex-rs/hepta-agentd/src/client.rs). The additive local protocol advertises `run.lifecycle/1.1` before clients use these methods. The optional named TaskFlow provider-effect host is [automation_effect_host.rs](../../../codex-rs/hepta-agentd/src/automation_effect_host.rs), backed by [authority_trust_host.rs](../../../codex-rs/hepta-agentd/src/authority_trust_host.rs); `runtime.rs` attaches it only when the explicit host file is supplied. The explicit durable cognitive writer seam remains [production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs); it is not installed by normal daemon startup. These are source navigation bindings, not proof that deployment qualification has passed. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/runtime.agentd.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.agentd.md).

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

When `--automation-effect-host-file` is present, startup parses strict host schema V2, loads a rotating FinalUse issuer ring, independently signed revocation-distributor ring/feed, exact provider attestation and an absolute external trust root. It opens `AgentdFinalUseTrustStore` outside Agent home and constructs `FinalUseAuthority::open_state_dir_with_issuer_keys`; compatibility authority construction is not used on this path. The host is attached once to `AgentdState`, advertises effect capability only after successful construction, and routes typed effect/reconciliation requests through the existing control plane.

Typed owner attachments in `AgentdState` remain explicit fields. `RuntimeTasks` does not load plugins, issue authority, select topology, migrate a schema or hand off a durable writer. The typed runtime catalog and the standalone Supervisor module-lifecycle source are not evidence that default Agentd implements arbitrary live topology replacement. Canonical intelligence is now routed through the existing authenticated `ObjectiveStart` control ingress only when both the bounded runner and a host-owned seven-owner invocation provider are installed. That all-or-none profile advertises `intelligence.canonical_v1`; a runner by itself advertises nothing, compatibility `RunStart` remains distinct, and unsigned evaluation input remains rejected.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

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

The run map is intentionally ephemeral and is not a second durable execution ledger. After process loss an external durable execution owner may supply the exact prior snapshot/revision/context/receipt identity through the recovery method; Agentd rehydrates it only as `Indeterminate`. No restart path may infer completion or redispatch from an absent local record.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

### Durable run-start projection

The daemon coordinator exposes the owner-internal `start_revalidated_run_start` bridge for a `RunStartRecordV1` that has already been revalidated by the product owner against current trust. The bridge fixes the durable-owner → daemon-owner mapping: `admission.admitted_source_digest` is the runtime request identity, and objective/body/artifact/authority/generation/fence/deadline are copied from the durable record. `ExplicitAbstain` is terminal at objective admission and is never inserted as an executable run. A retained journal record is not, by itself, proof that its signer remains current; raw-record authentication is intentionally outside this bridge.

## 8. Failure semantics, recovery and rollback

Run deadlines remain live after admission: expiration before dispatch becomes a local terminal cancellation; expiration after dispatch moves the run to `Cancelling` and still requires owner terminal observation. Shutdown closes new admission before teardown, converts pre-dispatch work to local cancellation, moves dispatched work to cancelling, and keeps the control path running for a bounded drain. After the drain deadline, unresolved dispatched/cancelling work becomes `Indeterminate`; a second bounded reconciliation window accepts exact terminal observations. If uncertainty remains, shutdown reports recovery-required rather than fabricating success/failure.

Recovery after process loss is explicit and non-authoritative: a durable external owner must provide the exact prior operation identity, and the new Agentd process can only rehydrate it as `Indeterminate`; the recovery API cannot redispatch. For TaskFlow provider effects, the automation owner persists the attempt and canonical non-authorizing authority witness before provider contact; Agentd restart reopens that same row and performs provider-owned lookup/reconciliation. A lost response cannot create a second provider attempt. The external authority store enforces single-writer handoff and rejects a local FinalUse snapshot restored behind its frontier. The local control server also distinguishes saturation from disappearance by returning a typed overload/retry frame instead of dropping the connection. `run.lifecycle/1.1` adds explicit closed-record release and exposes the pending cancellation-ack deadline in receipts so callers can reconcile rather than guess.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.agentd.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

codex-hepta-agentd starts from `AgentdConfig::from_process_environment`; optional `--authbus-trust-file` and `--automation-effect-host-file` values are protected host configuration. The effect-host file is strict and bounded; it names the trust root, issuer/distributor keys and windows, signed revocation feed, provider attestation and exact endpoint/policy. The external trust root must be absolute and outside Agent home. `HEPTA_COGNITIVE_RETRIEVAL_MODE` is a strict product-profile selector: absent/`compatibility` selects the compatibility path, `hnmf-required` selects HNMF-required mode, and any other value is rejected. The ordinary binary does not mint a `CurrentMemoryRetrievalContext`, so HNMF-required startup without an externally composed current context fails closed. The supervisor supplies the owner identity/generation and existing memory store. Stop new admissions before owner drain; an App Server interruption acknowledgement alone is not terminal task completion.
The local control capability endpoint advertises the additive run lifecycle surface. SIGINT, SIGTERM, and supervisor Draining close run admission before teardown; terminal observation remains possible during the bounded drain/reconciliation window. An App Server interruption acknowledgement alone is never terminal task completion.

Current operating and state-format references:

- [codex-rs/hepta-agentd/src/main.rs](../../../codex-rs/hepta-agentd/src/main.rs).
- [codex-rs/hepta-agentd/src/config.rs](../../../codex-rs/hepta-agentd/src/config.rs).
- [codex-rs/hepta-agentd/AUTHBUS_TEXT.md](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs) covers complete frozen-tuple binding, post-admission deadlines, reasoned cancellation, drain and explicit indeterminate recovery.
- `automation_effect_host.rs` and `authority_trust_host.rs` cover strict host configuration, signed feed admission, single-writer trust ownership, clock rollback, exact frontier CAS, restored-local-snapshot rejection and typed dispatch/reconciliation routing.
- `codex-rs/hepta-automation/tests/authorized_effect.rs` covers revocation pending, durable authority witness, provider response loss, restart reconciliation and no blind redispatch for the attached host path.
- [codex-rs/hepta-agentd/src/state_isolation_tests.rs](../../../codex-rs/hepta-agentd/src/state_isolation_tests.rs) exercises the lifecycle methods through the real daemon control dispatch and verifies capability advertisement and terminal reconciliation during drain.
- [codex-rs/hepta-agentd/src/runtime_tests.rs](../../../codex-rs/hepta-agentd/src/runtime_tests.rs) verifies that bounded shutdown keeps reconciliation live until terminal observation.
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

The configured product profile routes authenticated `ObjectiveStart` through the canonical runner and a host-owned invocation provider, then freezes the exact prepared envelope into the existing Agentd run/context lifecycle. Separately, the explicit automation-effect host profile attaches a named FinalUse/HTTP provider boundary with durable TaskFlow witness/recovery. Bare/compatibility profiles install neither capability. Repository source composition does not qualify the selected clock/frontier volume, issuer custody, provider attestation/terminal observation, network behavior or operator activation.

## 17. Source implementation receipt

This receipt records repository source bindings for the current documentation candidate. It is navigation evidence only; it does not claim product composition, deployment, or external effect authority.

| Operation | Native symbol | Source path | Tests |
|---|---|---|---|
| `compose_runtime` | `pub fn compose_runtime(` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs` |
| `start_run` | `pub fn start_run(` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs` |
| `cancel_run` | `pub fn cancel_run(` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs` |
| `attach_context` | `pub fn attach_context(` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` | `codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs` |

- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json`.
- Exact module-local source/test provenance is recorded as `currentSourceEvidence` and is verified by the Agentd process qualification workflow; the legacy repository-wide `sourceBase` remains a separate common baseline until the repository-wide migration.
- Consumer callsites and durable owner stores remain an explicit follow-up when not listed above.
- Production implementation, runtime composition, independent acceptance, activation, and release remain false until their separate evidence gates pass.
