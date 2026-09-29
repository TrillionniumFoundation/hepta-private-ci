# intelligence.control technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `intelligence.control`

**Owner:** `intelligence-platform`

**Deputy:** `qualification-plane`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `INTELLIGENCE-A0-Q0.63`

This is the effective implementation guide. Canonical JSON registries retain
ownership of module, contract, data-authority and delivery facts. This guide,
[product composition](PRODUCT_CLOSURE.md),
[restart semantics](RESTART_RECONCILIATION.md), the
[durable-operation ADR](ADR-001-DURABLE-OPERATION-RECOVERY.md),
[operations runbook](OPERATIONS_RUNBOOK.md) and
[compatibility contract](COMPATIBILITY.md) describe the same current source,
not competing historical amendments. Git history preserves earlier designs.
Source presence, native execution, complete product composition, independent
acceptance and activation are separate claims.

## 1. Identity, mission and ownership

Compose objective, utility, neuron, intuition, prompt, context and evaluation
owners without taking ownership of their facts. Placement is plane `domain`,
kind and architecture role `composition_facade`, state model `ephemeral`.
The facade grants no global optimality, execution or mutation authority.

The primary owner controls the declared source root. The deputy independently
reviews contracts, authority, persistence, concurrency and qualification.
Agentd owns product lifetime; kernel.operations owns operation/outbox state;
learning.ledger owns learning records and its independent witness. Cross-owner
changes use explicit integration ownership, not a second intelligence store.

## 2. Source binding and implementation status

Declared and existing exclusive root: `codex-rs/hepta-intelligence`.
No missing declared root or alternative authoritative implementation root exists.
`existing_bound` records location, not product completion.

The pure canonical API lives in `src/canonical.rs`, with mutable-DTO checks in
`src/canonical_invariants.rs`. Agentd's named implementation is split into
`intelligence_product.rs`, `intelligence_product_ports.rs`,
`intelligence_product_runner.rs` and `intelligence_prepared_integrity.rs`.
Input admission is `intelligence_ingress.rs`; durable learning is
`intelligence_learning.rs` with payload, clock and scheduling companions.

The authenticated `ObjectiveStart` route invokes the runner only for an
explicitly configured runner/provider profile. Ordinary CLI bootstrap does not
construct an authorized seven-owner factory. `ContextAttached` is not proof that
Decision publication, physical App Server execution and Outcome recovery form
one complete product episode. Those edges remain acceptance work.

Historical `compose`, read-only vertical and shadow/evaluated-shadow entrypoints
remain compatibility or qualification APIs, not parallel product choices.

## 3. Boundary, responsibilities and non-goals

Direct dependencies are `objective.compiler`, `utility.ndu`, `neuron.runtime`,
`intuition.policy`, `prompt.optimizer`, `context.compiler` and `learning.eval`.
Authoritative write domains: none. Explicitly denied capabilities are
`production_write`, `model_authority` and `physical_effect`.

Inputs and receipts are bounded, versioned and identity-bound. A digest is not
an authenticated producer or a permission. Missing authority, source drift,
unknown critical fields, invalid scope and invalid canonical identity fail
closed. Cross-owner mutation uses the existing local transaction, durable
intent, outbox, destination deduplication and fenced reconciliation protocol.

Do not introduce a second App Server executor, intelligence database, central
all-Agent context, arbitrary self-issued trust, model-prose authorization or a
parallel Laya/meta-RL control loop. Facts and inference remain with their owners.

## 4. Internal architecture and component decomposition

The current canonical execution order is:

```text
objective validation -> NDU -> neuron -> prompt optimization
-> calibrated intuition -> context compilation -> signed evaluation
-> authority-free envelope -> Agentd context attachment
```

Intuition abstention/slow-path ends before context/evaluation/dispatch. Every
stage checks its frozen owner binding before and after its call. The canonical
facade and Agentd each perform a final currentness check.

Concrete owner adapters now retain the actual NDU evaluation digest and actual
neuron result. Neuron receives that NDU digest; intuition's state identity is
bound to the actual neuron output. A host template may leave these derived
fields zero before the owner call; a nonzero conflicting value is rejected.
The owner never receives zero as an admitted predecessor. NDU contributions
must cover the canonical candidates, with only the owner's reserved `abstain`
entry permitted additionally. Intuition may not mark an NDU-infeasible candidate
as legal and unvetoed. These checks do not manufacture calibrated scores.

The physical canonical profile now consumes a privately source-bound
`PreparedPromptDeliveryV1`, revalidates the actual serialization proof and
retains the exact context attachment and payload. Prompt output and neural output
jointly condition intuition; conflicting precomputed state fails. Physical send
uses only `PreparedAgentdIntelligenceRunV1::physical_prompt`, not arbitrary prompt
text. Compatibility preparation without this delivery cannot execute the physical
product path. Live selected-action semantics and quality remain acceptance gates.

### Multiscale DecisionCell integration target

Use the existing objective, NDU, cell/organ inference, calibrated policy,
context and learning owners. Keep backend-specific Laya APIs behind inference
and Neuron adapters. Circuit-triggered calls retain the existing
[Neural Circuit contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).
The [DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md) and
[organ composition](../../cns/TECHNICAL.md) define scope, capacity and depth.
Coherent bundles, required-owner outage, source/parameter drift and downstream
outcome linkage need actual tests; these targets do not change product status.

### Shared-experience and isolated-Agent integration target

Permitted shared evidence flows through existing owners, with local task/context
isolation and independent feedback. Preserve the [HNMF contract](../../hnmf/TECHNICAL.md)
and [migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners).
Capacity/depth claims and learning gains require the scoped experiments in
[causal longitudinal learning](../../learning/CAUSAL_LONGITUDINAL_SPEC.md), not
an interpretation of hierarchy as gradient depth.

## 5. Contracts, ports and compatibility

Produced contracts: `IntelligenceHostEnvelopeV1`, `LegalActionCandidateSetV1`.
Consumed ports, protocols and read domains are enumerated in the unchanged
registry projection below. No wire meaning is silently redefined.

Canonical candidate IDs are sorted and duplicate-free. Selection must belong
to the admitted set and have positive propensity. A mutable retained outcome
is revalidated against the original request: nested run identity, decision
content/digest, context binding and envelope dependencies are rehashed.
Changing to another legal candidate or another positive propensity still changes
the decision and cannot retain the old digest.

The Agentd prepared object additionally retains a private frozen attachment.
Learning publication rechecks mutable public fields against that attachment and
the exact dispatch-proposal digest. Rehashing substituted public fields cannot
change the original attachment. Pure DTO checks do not authenticate arbitrary
callers or prove a physical provider observation.

Compatibility is additive only where registered. Serialization, duplicate,
unknown/missing-field, enum, size and canonical-order tests are required for
wire surfaces. Native-only helpers are not automatically wire implementations.

## 6. Data authority, persistence and migrations

Owned authoritative/rebuildable domains: none. Read domains include NDU and
neuron projections and the additional registered support/coefficient records.
The facade must never directly replace those stores.

Formal default-build Decision/Outcome adapters call only `LedgerWriter`.
The product learning host first writes an immutable V2 payload sidecar and syncs
it and its directory, then publishes the existing kernel.operations intent.
The sidecar retains the original operation identity, predecessor, evidence,
principal/controller/key/credential/scope/epoch bindings and event time.
V2 serialization and digest grammars remain unchanged by the code split.

Sidecar publication uses a same-directory temporary file and no-replace hard
link, not overwrite rename. Reads check the opened handle and limit actual bytes.
Full parent-anchored no-follow open, orphan retention and process-loss boundary
qualification remain separate obligations. Migration must preserve old V2 bytes
and the ability to identify acknowledged, rejected, quarantined and unresolved
operations. Never clear a journal to regain capacity or erase uncertainty.

## 7. Runtime, concurrency and transaction model

One durable RunStart supplies the physical run identity. Running generation is
`spawn_generation + 1`; the canonical fence constructor is shared by admission,
invocation and coordinator checks. Configuration changes create a new profile
or generation rather than modifying a current run.

The runner uses four slots. Actual blocking work retains its permit even if the
request times out or is dropped. A worker-owned completion guard starts an
independent OS-thread watchdog; request-future cancellation cannot disarm it.
The guard joins its watchdog before releasing the worker permit. Explicit
hard-timeout policy may exit Agentd with code 70; a fresh Supervisor generation
and durable reconciliation are still required afterward.

Signed-evaluation manifest reads and final all-owner revalidation run inside
supervised work and share the remaining monotonic cognition budget. Owner call
latency is recorded before propagating either success or failure.

**Not yet a complete end-to-end bound:** the synchronous invocation factory and
synchronous learning grant/file/writer work still need a separately bounded,
supervised owner lifetime. A thread timeout is not safe cancellation of an
arbitrary synchronous instruction. Do not advertise complete hard isolation.

[Shared concurrency requirements](../README.md#shared-concurrency-and-transactions)
remain mandatory at every owner boundary.

## 8. Failure semantics, recovery and rollback

`kernel.operations` owns durable identity, operation/outbox state and recovery.
`DurableFailureClass` preserves identity, capacity, lease, authority, clock,
corruption and unknown-outcome distinctions. `RecoveryDisposition` restricts
callers to reject, same-identity retry, capacity backoff, reconcile-only,
successor-owner replacement or clock/store repair. `Prepared` and a proven
`NotDispatched` effect are the only generic same-identity retry cases.

Durable Unix timestamps are obtained from an injected `DurableOperationClock`
after SQLite grants the immediate writer transaction. Monotonic elapsed budgets
remain owner-local and absolute. See the
[decision record](ADR-001-DURABLE-OPERATION-RECOVERY.md) and
[runbook](OPERATIONS_RUNBOOK.md).

See [the effective restart contract](RESTART_RECONCILIATION.md). Event time is
historical Unix milliseconds; current evidence validation reads the host clock
at enqueue and actual application. A future historical timestamp/clock rollback
is not normalized into an old valid instant. Expired evidence cannot authorize
its first application merely because it was valid when enqueued.

Recovery observes the exact destination event before requesting a new grant.
A missing event can be applied only with fresh final-use authority, current
verified evidence and the original immutable predecessor. Historical observation
is delegated to `LedgerWriter::reconcile_exact_event_v1`, which requires complete
event and predecessor equality and the independent witness. It can repair only
the exact already-committed last record; it never creates a missing event. Full
daemon restart qualification is still separate.

Stable keyset traversal prevents a timestamp-ordered poison prefix from owning
every recovery page. Recovery and fresh dispatch receive separate bounded
shares; batch size one alternates them. Transient grant failure before dispatch
can defer only an exact, live Prepared claim. A dispatching/unknown operation
cannot re-enter the ordinary queue. Transient failures back off without
silently changing their logical identity.

Physical lost acknowledgement, uncertain interruption and absent terminal
provider evidence remain `Indeterminate`. Never retry a physical effect under
a new ID to make uncertainty disappear. Recovery, drain, cancellation and
release are not interchangeable states.

## 9. Security, privacy and threat controls

Owned registry threat entries: none. Applicable controls still include authority,
replay, file replacement, source substitution and privacy boundaries.

The manifest is verified with an externally configured Ed25519 key, strict
signature checks and weak-key rejection. It has exactly seven owner rows;
actual file reads are capped at 64 KiB and Unix opened-object identity and
write permissions are checked. A signed old file is still old: the current
oracle does not establish an independently durable anti-rollback floor.
Atomic no-follow/nonblocking open and trusted parent-directory identity also
remain required before complete file-boundary qualification.

No secrets or credentials belong in ordinary logs, prompt factors or learning
datasets. Runtime grants remain short-lived, payload-bound and revocation-aware.
Independent security review is mandatory for physical and durable boundaries.

## 10. Performance, capacity and hot-path policy

The pure facade accepts at most 128 candidates and exactly seven owner bindings.
NDU's own 128-candidate bound includes its required reserved abstain entry;
combined inputs must satisfy both owners, not add an unaccounted 129th entry.
Stage budgets are positive and their checked sum fits the total budget.

Learning payloads are capped at 1 MiB. Reconciliation cadence is 10 ms to one
hour and each iteration visits at most 256 scheduled operations. Work is not
unbounded merely because a request detached. These are code bounds, not RSS,
latency or throughput measurements.

Further optimization should reuse one authenticated manifest per validation
boundary and owner-local exact ledger indexes without weakening between-stage
freshness or exact authenticated event equality. Current historical observation
still clones/scans ledger history; no index-speedup claim is made.

[Shared performance requirements](../README.md#shared-performance-and-capacity)
and selected-host measurements remain applicable.

## 11. Observability and operations

Telemetry includes worker activity/peak/busy, timeout/late completion/crash,
stage latency/failure class, currentness/identity rejection, advisory outcomes
and run-phase dwell. Kernel.operations exposes queued, leased, acknowledged,
indeterminate and terminal backlog counts.

`capability_profile_digest` now uses the versioned v2 domain, length-delimited
path/signer and full hard-timeout precision. It identifies configuration, not
an activation grant. Old profile digests are historical qualification identities.

Operators must distinguish source declaration, ContextAttached, physical
Dispatching, observed terminal, ledger commit and witness acknowledgement.
The compatibility runbook remains [EVALUATED_SHADOW.md](../../../codex-rs/hepta-intelligence/EVALUATED_SHADOW.md);
[Lane B host](../../readiness/LANE_B_NATIVE_HOST.md) describes the runtime owner.
[Shared operations requirements](../README.md#shared-observability-and-operations)
apply; no default CLI fabricates owner/evidence sources.

## 12. Verification and qualification

`IMPLEMENTATION_MAP.json` and `TEST_TRACEABILITY.json` are reviewed source/test
declarations. They explicitly identify requirement support scope, package,
source file and test, including integration tests outside `src`. They are not
an automatically promoted count of functions or a complete repository inventory.

`scripts/hepta-intelligence-control-status.py --check-tracked` validates them.
The companion Python tests reject wrong-head, failed/queued, changed-checkout,
missing-log and missing/ambiguous-test evidence. Native workflow projection
requires exact command arrays, exit codes, source/lane identity, unchanged log
hashes and each explicitly mapped test observed passing. All package tests,
including unrelated tests within those packages, still run.

The independent workflow runs source-head and deterministic base-merge lanes:
formatting; intelligence and operations package tests; default Agentd library
tests; separately labelled legacy tests; all-target compilation; strict Clippy.
Read-only macOS diagnostics may retain additional failures and a formatter patch
from a separate worktree, but do not replace those qualification lanes.

Real-child watchdog test source is not an executed result. Default-profile
process restart, App Server E2E, every durable crash cut and performance/quality
baselines remain required. No queued, skipped or prior-head result qualifies the
current tree. [Shared qualification requirements](../README.md#shared-verification-and-qualification)
remain in force.

## 13. Implementation sequence and work packages

Packages are `INTELLIGENCE-A0-Q0.63`, `C1-PROMPTED-MEMORY-RETRIEVAL-RANK` and
`INT-2-AGENTD-CODEX-COMPOSITION`. Keep their separate development, activation and
evidence DAGs. Ordinary owner-authorized implementation does not require a
handwritten deployment grant. Cross-owner changes retain explicit owners.

Finish actual stage data and time semantics, compose one executable product
host, close concurrency/recovery/file boundaries, then qualify one exact
candidate. Do not substitute another facade or a larger intelligence plane.

## 14. Activation, compatibility and retirement

Runner/provider configuration advertises only the configured capability.
Default CLI composition, physical provider execution, accepted owner trust,
operator approval, activation, promotion and release remain separate. Legacy
learning writes remain feature-gated and cannot qualify the default writer.

Retire a compatibility path only after all its named callers migrate, applicable
oracle parity and rollback are rehearsed, and independent acceptance exists.
Preserve historical records and digest interpretation.

## 15. Definition of module completion

Documentation needs consistent effective contracts and registry validation.
Source needs reachable implementations and native checks. Product completion
needs actual owner inputs, Decision-before-dispatch, the exact physical request,
independent terminal evidence and durable Outcome/witness recovery. Qualification
needs current source/merge results; acceptance and release are separately issued.
`allRequirementsClosed`, product E2E, target-host and release remain false until
those conditions are observed, not merely declared.

### Work-package execution envelopes

#### `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `qualification-plane`.
- Allowed write paths: `codex-rs/hepta-intelligence/**`, `qa/learning/prompted-memory-retrieval/**`.
- Development and activation predecessors: `CTX-1-CONTEXT-COMPILER`, `HBO-2-BELLMAN-OPERATOR-SHADOW`, `P0.8D-VERTICAL-SLICE`, `INTELLIGENCE-A0-Q0.63`.
- Required deliverables: `exact_source_identity`, `source_inventory`, `static_verification`, `focused_tests`, `package_tests`, `all_target_check`, `strict_lint`, `clean_worktree`, `exact_head_execution`, `merge_candidate_execution`, `read_only_action_domain`, `complete_candidate_set`, `logged_propensity`, `no_prompt_baseline`, `factor_and_timing_ablation`, `zero_memory_kg_effect`.
- Stop conditions: `authority_violation`, `base_drift`, `claim_evidence_mismatch`, `cross_owner_write`, `unbounded_resource_or_retry`.

#### `INTELLIGENCE-A0-Q0.63`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `independent_qualification_source`.
- Owner/deputy: `intelligence-platform` / `qualification-plane`.
- Allowed write paths: `codex-rs/hepta-intelligence/**`, `scripts/hepta-intelligence-*.py`, `.github/workflows/hepta-intelligence-*.yml`.
- Development predecessor: `DOC-1-V8-SEMANTIC-UPGRADE`; activation predecessor: `P0.7B-B0-VERIFIED-USE`.
- Required deliverables: `exact_source_identity`, `source_inventory`, `static_verification`, `focused_tests`, `package_tests`, `all_target_check`, `strict_lint`, `clean_worktree`, `exact_head_execution`, `merge_candidate_execution`.
- Stop conditions: `authority_violation`, `base_drift`, `claim_evidence_mismatch`, `cross_owner_write`, `unbounded_resource_or_retry`.

#### `INT-2-AGENTD-CODEX-COMPOSITION`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `qualification-plane`.
- Allowed write paths: `codex-rs/hepta-intelligence/**`.
- Development and activation predecessors: `CTX-1-CONTEXT-COMPILER`, `INT-1-CALIBRATED-INTUITION-POLICY`, `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`, `INTELLIGENCE-A0-Q0.63`.
- Required deliverables: `exact_source_identity`, `static_verification`, `focused_tests`, `clean_worktree`.
- Stop conditions: `authority_violation`, `base_drift`, `claim_evidence_mismatch`, `cross_owner_write`, `unbounded_resource_or_retry`.

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `intelligence.control` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `IntelligenceHostEnvelopeV1`
- `LegalActionCandidateSetV1`

**Consumed contracts:**
- `DomainRead::eligibility_trace_checkpointV1`
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `DomainRead::neuron_state_checkpointV1`
- `LearningArtifactManifestV1`
- `ModulePort::context.compiler::intelligence.control`
- `ModulePort::intuition.policy::intelligence.control`
- `ModulePort::learning.eval::intelligence.control`
- `ModulePort::neuron.runtime::intelligence.control`
- `ModulePort::objective.compiler::intelligence.control`
- `ModulePort::prompt.optimizer::intelligence.control`
- `ModulePort::utility.ndu::intelligence.control`
- `NduCoefficientManifestV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `SupportAuditReceiptV1`

**Typed protocols:**
- `IntelligenceHostEnvelopeV1`
- `LearningArtifactManifestV1`
- `LegalActionCandidateSetV1`
- `NduCoefficientManifestV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `SupportAuditReceiptV1`

**Owned data domains:**
- None.

**Read data domains:**
- `eligibility_trace_checkpoint`
- `ndu_coefficient_manifest_v1`
- `ndu_preference_projection`
- `ndu_update_receipt_v1`
- `ndu_utility_projection`
- `ndu_well_posedness_certificate_v1`
- `neuron_state_checkpoint`
- `support_audit_receipt_v1`

**Work packages:**
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `INT-2-AGENTD-CODEX-COMPOSITION`
- `INTELLIGENCE-A0-Q0.63`

**Owned threats:**
- None.

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

Primary lane: `LANE-F-ADAPTIVE-POLICY`. Mandatory specifications:
[`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md),
[`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md),
[`RDY-OBJ`](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md),
[`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md),
[`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md).
Owned readiness protocols: none. Consumed protocols:
`ObjectiveCompileReceiptV1`, `ObjectiveConflictReceiptV1`, `ObjectiveSourceEnvelopeV1`.

Ordinary authorized coding identifies Git baseline, contracts, owned paths,
fixtures, fallback and rollback. A runtime coordinator verifies the actual
`CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero
authority delta at its boundary; that is not additional permission for ordinary
source work. This overlay grants no selection, activation, acceptance or release.

## 17. Source implementation receipt

Current immutable identity is obtained from Git and actual workflow records,
not cached branch names or prior passes. The named authenticated daemon route,
canonical owner adapters, formal writer/outbox and watchdog have source.
The [implementation map](IMPLEMENTATION_MAP.json) and
[test traceability](TEST_TRACEABILITY.json) retain pending execution in tracked
files. Exact workflow projections may certify only their executed lane.

## 18. Product acceptance boundary

The source now includes normal authenticated ObjectiveStart completion through
`AgentdIntelligenceExecutionHostV1` and the existing-driver
`NativeIntelligenceProductEmbeddingV1`. An authorized embedding installs it after
the guarded runner/provider profile. Decision plus witness acknowledgement
precedes model send; terminal Outcome support is checked against the observed run
and physical output. Errors after a terminal observation preserve it for recovery.
The default binary still supplies no owner factory, execution host or evidence.
The effective source, setup and remaining evidence contract is
[PRODUCT_CLOSURE.md](PRODUCT_CLOSURE.md), including Section 12.

The following obligations describe live conformance/qualification, not absence
of the source mechanisms just described.

Remaining obligations are actual prompt/context/request materialization;
authorized executable host factory; durable Decision and physical terminal
Outcome wiring; complete factory/learning-I/O supervision; trusted no-follow
file access and rollback floor; witness-aware historical acknowledgement;
process crash/recovery, current native checks, target-host performance, quality
baselines and independent acceptance. Do not relabel these as external paperwork
or infer their completion from the presence of an interface.

### Independent authority-manifest rollback floor

The configured canonical profile is fail-closed unless the runner carries an independently
retained `IntelligenceAuthorityRollbackGuardV1`. The witness path must be canonical and outside
both Agent home and run roots. Each signature-verified authority manifest is then checked against
the durable maximum epoch and exact same-epoch digest before its owner bindings can satisfy a
currentness read. Compatibility-only runner construction may omit the witness, but such a runner
cannot be advertised or entered as `intelligence.canonical_v1`.

### Blocking work and no-follow reads

The invocation factory is inside an independent supervised worker lifetime.
Learning file/grant/writer operations use bounded blocking workers whose slots
remain owned until actual completion, even when the awaiting request disappears.
Unix authority/sidecar reads walk no-follow parent handles and use a nonblocking
leaf open plus same-handle regular-file, permissions, hard-link and byte checks.
Non-Unix hosts require their own qualified handle implementation. Arbitrary
learning I/O is not claimed to be forcibly terminable; host-root write-side
replacement and complete crash/backup matrices remain explicit acceptance work.
