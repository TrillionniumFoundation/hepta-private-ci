# learning.artifacts technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.artifacts`

**Owner:** `learning-platform`

**Deputy:** `durability-kernel`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `ART-1-LEARNING-ARTIFACT-REGISTRY`

This stable document is the implementation guide for `learning.artifacts`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own immutable create-only learning artifacts, sensor cores, lineage and rollback predecessors.

The primary owner `learning-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `durability-kernel` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `store`, state model `stateful_create_only` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-learning-artifacts`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-learning-artifacts`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `learning.artifacts`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

### Current implementation and completion evidence

The native store implements complete V3 admission persistence, V1 compatibility
snapshots, authenticated CURRENT verification, full provenance eligibility and
fenced publication/recovery. `LearningArtifactOwnerService` is the named source
writer; Agentd consumes authenticated current views through explicit read
adapters. These are concrete implementation and composition facts. Their tests,
all-target build and lint results must be recorded for the exact candidate before
claiming qualification.

Publication time is caller-supplied logical `request.now`. Preflight rejects bad
payloads/signatures/projections before `Prepared`, and later phases revalidate
against that request time. There is no authoritative clock callback in this API;
it cannot establish elapsed wall-clock freshness after a long computation or I/O
stall. Deployment composition must supply/enforce current time at the final
mutation/use boundary. A logical-clock test is not a measured real-time lease
expiry qualification.

The deployment supplies public trust, signed writer/selector/head evidence,
independently retained restart floors and an authoritative newest-head channel.
Those are necessary inputs to implemented verification APIs. Supplying them does
not require this store to own private signing keys or mint its own acceptance.
Target filesystem qualification, production routing, operator acceptance and
release remain separate evidence states. The planned tensor/DecisionCell and
self-iteration targets below retain their own scope and are not inferred from
artifact storage completion.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `kernel.operations`

Authoritative write domains:

- `learning_artifact_registry`
- `operator_sensor_core_registry`

Explicitly denied capabilities:

- `self_promotion`
- `mutable_artifact_bytes`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `schema and migration owner`
- `transactional writer`
- `snapshot read port`
- `integrity and lineage verifier`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Reviewed implementation limits

The owner is a Rust service composition, not an executable deployment or signing
service. A caller must retain the exact publication request across interruption;
the early checkpoint does not contain the complete admission/payload. Recovery
never invents that request from a V1 projection. Partial final-path files remain
fail-closed and require separately authorized reconciliation. CURRENT expiry
renewal and host-protected independent frontier distribution are not supplied by
this crate. These are open composition/operating requirements, not implied passes.

The built-in `PlasticityCurrentArtifactFilesV1` adapter authenticates a frozen V1
snapshot and CURRENT head. It does not load V3 admission sidecars or authenticate
a live dataset-withdrawal frontier, so it cannot establish complete provenance or
manifest/ancestor expiry. A strict provider is still required for that product
profile. When a provider does return a strict view, the frozen-generation guard
checks its exact use time, the eligibility of every initially eligible frozen
artifact, and forbids later downgrade to V1. This conservative generation-wide
check may require rebootstrap when an otherwise unused frozen candidate expires.
Ranker providers also remain responsible for obtaining current evidence at each
use; an opaque previously issued view is not an independent live clock or latest-
frontier oracle. Production/acceptance/release states remain unchanged.

### Multiscale DecisionCell integration target

Persist immutable base/organ/cell parameter bundles with complete tensor inventories and compatibility/deletion lineage. Preserve scalar ParameterProposalV2 semantics; larger updates require a versioned artifact-reference adapter. Reference-aware GC must retain shared bases still in use; the registry neither trains nor selects its own artifacts.

Bind circuit routing/termination policy to compatible cell, definition and state versions. TaskFlow continues to own immutable operational definitions; artifact storage is not a second body/run registry. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: base replacement, adapter shape/order mismatch, revoked source reload, optimizer lineage and shared-reference GC.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Retain capacity, parameter-field and adaptation profiles under existing manifests. Bind tensor sharing, probe/anchor/coordinate epochs, optimizer lineage, representation precision and compatibility. Factor norms are not effective-operator distance; field projections do not replace original artifacts.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Retain permitted-source and derived-consumer scope through datasets, optimizers, adapters, normalizers, distillation and descendants. Revocation withdraws affected bundles; unsupported unlearning requires truthful quarantine/retrain. Shared metadata/hash equality does not authorize cross-scope access.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::learning_artifact_registryV1`
- `DomainRead::operator_sensor_core_registryV1`
- `LearningArtifactManifestV1`
- `ModulePort::learning.artifacts::intuition.policy`
- `ModulePort::learning.artifacts::learning.eval`
- `ModulePort::learning.artifacts::learning.operator`
- `ModulePort::learning.artifacts::learning.plasticity`
- `ModulePort::learning.artifacts::neuron.runtime`
- `ModulePort::learning.artifacts::prompt.optimizer`
- `ModulePort::learning.artifacts::utility.ndu`
- `OperatorSensorCoreManifestV1`

Consumed contracts:

- `BellmanOperatorArtifactV1`
- `DatasetSnapshotV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `EvaluationReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::kernel.operations::learning.artifacts`
- `ModulePort::platform.types::learning.artifacts`
- `PlasticityProposalV1`
- `RegularityProfileV1`
- `UnlearningComplianceReceiptV1`

Critical protocol schemas:

- `DatasetSnapshotV1`
- `EvaluationReceiptV1`
- `LearningArtifactManifestV1`
- `LongitudinalEvaluationReceiptV1`
- `OperatorSensorCoreManifestV1`
- `RegularityProfileV1`
- `UnlearningComplianceReceiptV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains remain:

- `learning_artifact_registry`
- `operator_sensor_core_registry`

Read-only dependencies remain `cross_owner_outbox` and `operation_ledger`.

`operator_sensor_core_registry` is physically owned by the same immutable writer as `learning_artifact_registry`: sensor cores are first-class `ArtifactKind::SensorCore` records in `ArtifactRegistry`. `project_operator_sensor_core_registry_v1` is only the typed read view over that history, bound to the exact source registry head; it is not a second journal or writer. Revocation and quarantine therefore propagate without cross-store reconciliation.

The stable V1 `ArtifactRegistry` is an append-only compatibility registry with canonical create-only snapshots. A V1 `ArtifactManifest` intentionally remains readable, but it cannot represent every V2 field: V2 supports multiple source datasets, multiple lineage digests and multiple predecessors. The implementation therefore does **not** flatten the complete V2 closure into one V1 predecessor or support field.

The complete V2 authority-free admission is retained by `WithdrawalBoundArtifactAdmissionV3` and physically stored by `admission_storage.rs` at `admissions/{manifest_digest}.admission`. Its additive `HEPTAA03` encoding preserves every dataset, lineage digest, predecessor, rollback predecessor, runtime/training/device/schema/normalization binding, producer, byte count and creation/expiry field. A sidecar receipt binds storage binding, withdrawal scope, manifest/admission digests, complete file digest and byte count. The owner checks every V1 projection field, including objective and `support_digest = manifest_digest`; one V2 parent is represented by that V1 parent, while zero or multiple parents remain an exact V1 `None` projection with the complete parent set in the sidecar.

`read_artifact_admission_snapshot_bound` can recover from independently pinned
storage binding, withdrawal scope, manifest digest and admission digest. The
manifest pin comes from the witnessed registry; the admission pin comes from the
original publication checkpoint matched to the immutable registration intent.
Bounded parsing, semantic digest verification and exact canonical re-encoding
precede issuance of a file receipt. The file's observed length is only a read
budget. Recovery validates at `admitted_at`, so later expiry does not erase
historical provenance; current eligibility separately checks the use time.

Historical V1 files are still readable through explicit compatibility APIs.
Strict owner reads require a complete sidecar for every registration. Missing
provenance never becomes an empty dataset/parent list. The fenced
`LearningArtifactOwnerHost::backfill_artifact_admission` accepts only the original
exact admission matched to its historical checkpoint, scope, head and projection.
It creates missing immutable evidence without selecting or resurrecting an
artifact; unsupported legacy histories require explicit migration rather than
guessing their full provenance.

Dataset withdrawal is a separate append-only digest chain. New V3 admission requires a `DatasetWithdrawalScopeV1` binding `authority_domain_id`, `registry_id` and `scope_id`. The scope participates in the scoped genesis/head derivation and the V3 admission digest, so an equal-looking event history in another namespace cannot satisfy the current admission.

Withdrawal and lifecycle state both have canonical create-only durable snapshot adapters with independently retained receipts binding namespace/scope, chain head, file digest, record count and encoded byte count. Recovery rebuilds the semantic state and rejects non-canonical bytes, digest mismatch, scope mismatch, record-count mismatch or chain mismatch.

Historical lifecycle replay validates actor evidence at `event.occurred_at`. Recovery time is not reused as mutation authorization time: an actor credential that expired after a valid historical append does not make the journal unrecoverable, while a new mutation after expiry still fails.

All artifact-registry, withdrawal and lifecycle state machines share `MAX_DURABLE_ARTIFACT_RECORDS = 4096`. This is a source-enforced capacity invariant, not a target-host throughput claim.

Historical V1 snapshots remain interpretable. New V2/V3/scoped records are additive surfaces; they do not reinterpret an old V1 file as carrying fields it never encoded. Any future schema migration must preserve this distinction and provide checksum-bound deterministic replay.

## 7. Runtime, concurrency and transaction model

Artifact publication is an ordered durability protocol, not an assumed multi-file filesystem transaction.

`ArtifactPublicationTransactionV1` enforces:

`Prepared -> PayloadDurable -> RegistryDurable -> WitnessDurable -> Acknowledged`.

Preparation validates the current scoped withdrawal registry and binds the exact predecessor registry head. `PayloadDurable` requires the exact V2 payload digest and byte count. `RegistryDurable` requires a durable registry receipt whose current last record extends the expected predecessor and matches every V2 field representable by V1; it also revalidates the live scoped withdrawal frontier. `WitnessDurable` requires an independently validated head witness for that exact registry head and predecessor and revalidates the withdrawal frontier again. Final acknowledgement revalidates the current withdrawal frontier once more, so a withdrawal arriving during crash recovery or publication cannot be hidden by an older admission. Acknowledgement before witness durability is rejected.

The transaction exposes a digest-bound snapshot and replay constructor. Crash tests recover after prepared, payload-durable and registry-durable boundaries and prove that a partial publication cannot be relabelled acknowledged. The host that composes this contract must persist the returned transaction snapshot in its fenced transaction store before treating a phase as durable; a host that does not persist/replay the contract is outside this source qualification boundary.

Create-only file writers hold an exclusive advisory file lock through the empty-file check, write and `sync_all`. Readers hold shared locks for bounded reads. Zero-length orphan cleanup takes a nonblocking exclusive lock and rechecks the opened file before removal; an active reader or writer returns `Busy`.

`LearningArtifactOwnerHost` owns the local OS writer fence, signed writer-lease verification, authenticated CURRENT discovery and publication checkpoints. `LearningArtifactOwnerService` composes that host as the one registered product writer. The host synchronizes files and, on Unix, their parent directories before advancing a checkpoint, including exact retries. Other platforms still require target-host directory-durability composition and qualification. The deployment host also owns trusted ancestor protection, independent restart anchors, key provisioning, external newest-head distribution, publication/use serialization, the product process and final route changes.

New artifact admission is serialized by a host-local mutex as well as the OS
writer fence. It rejects another unfinished artifact/state operation and requires
the actual CURRENT predecessor before creating `Prepared`. Exact-operation
recovery remains permitted after its CURRENT side effect. Every resumed phase
re-reads the claimed payload bytes; registry/admission and witness bytes are also
checked once their phases claim durability. An unfinished missing or corrupted
payload therefore cannot advance a signed CURRENT or acknowledgement. Terminal
service retries return historical receipts and are not claims of current payload
availability.

The transaction validates the complete V1 projection, including objective,
manifest support digest and predecessor, and the canonical registration event ID
`artifact-publication:{intent_digest}`. Registry and witness receipts must match
canonical byte digest and length, not merely semantic heads. The signed-head
retry check independently derives the complete witness receipt from the signed
canonical witness. Correct historical encodings are unchanged; fabricated or
incompletely bound receipts now fail closed.

Retained signed predecessors are checked with their historical signing time and
per-signer epoch/key/revocation bounds. Raised CURRENT generation/epoch floors are
applied to the terminal live head and public current-view verification, not to
older authentic ancestry. Independent restart anchors may be older than the live
floor but must occur in the recovered chain. Historical verification never makes
an old head current or accepts a signature issued after its key was revoked.

Each publication phase validates a cloned transaction before creating its durable effect. A bad signed head or changed withdrawal frontier therefore cannot publish a rejected CURRENT. Recovery accepts only canonical checkpoint paths and encodings, complete ordered phases and consistent operation, admission, original lease and receipt identities. A renewed valid lease can finish the exact original transaction without rewriting its historical lease binding. Startup scans are bounded to 4,096 operations and five checkpoints per operation.

Restrictions use a separate additive owner-state saga in `owner_state.rs` and
`owner_state_storage.rs`: `Prepared -> SnapshotsDurable -> WitnessDurable ->
Acknowledged`. `LearningArtifactStatePublishRequestV1` binds the operation,
restriction/withdrawal intent, evaluator/reason, registry and withdrawal
predecessors, exact next withdrawal frontier and externally signed CURRENT.
Its `authorization_signing_bytes()` additionally binds the whole intent and
frontier under `hepta.learning-artifacts.state-authorization.v1`; the external
trusted head signer signs that payload with an explicit
`authorized_at`/`authorization_expires_at` interval. This independent state
signature is mandatory even when no artifact is affected and CURRENT stays at
the same registry head. A signed unchanged head alone cannot authorize a new
withdrawal frontier.
Registry and withdrawal snapshots become durable before the witness and terminal
checkpoint. Restart recovers the exact pending operation and withdrawal frontier;
unrelated writes remain fenced during reconciliation. Revoke, quarantine and
withdrawal publication do not overwrite artifact payloads or select a replacement.

Strict CURRENT reads join the durable sidecars with the independently authenticated
withdrawal frontier through
`ArtifactOwnerVerifierV1::verify_current_registry_view_with_admission_closure`.
`admission_closure.rs` checks each parent was registered earlier with an advancing
generation and matching kind/objective. Eligibility requires an unexpired current
candidate, no withdrawn source and eligibility of every V2 parent. This applies to
all parents, including those the V1 compatibility projection cannot express.

Lifecycle history fixes each artifact's producer from its first accepted record. Retries must retain the complete actor evidence and producer; new events cannot be in the future or precede that artifact's previous event. Historical recovery continues to validate credentials at occurrence time. Iteration transitions validate the resulting candidate before committing state, and evidence must stay within the envelope expiry and candidate timestamp order. Verified selection recording binds the exact manifest producer and retains the selector's known expiry and revocation limits.

Iteration bookkeeping is separately bounded and authority-free. `IterationLedgerV1` can record typed externally produced evidence and replay candidate state, but it does not execute a sandbox, evaluate code, select a candidate, merge source or release an artifact.

## 8. Failure semantics, recovery and rollback

The module fails closed on digest mismatch, scope mismatch, predecessor mismatch, stale withdrawal head, invalid lifecycle transition, expired mutation credentials, invalid current-head witness, non-canonical durable bytes, capacity exhaustion and publication phase skips.

The contained high-level storage APIs validate snapshot/witness/payload semantics **before** creating the final path, avoiding zero-length files for ordinary validation failures. A write or `sync_all` failure after final-path creation remains `Indeterminate`; the host must reconcile that path and may not infer success or reuse its identity.

`CreateOnlyArtifactFile::create_beneath_trusted_root` rejects absolute paths, `..`, non-normal components and symlink ancestors under the canonical trusted root. This is lexical and ordinary symlink containment, not an `openat2` substitute. Because the crate forbids unsafe code and the standard library does not expose a directory-handle no-follow transaction, the host must prevent concurrent hostile replacement of trusted ancestors and must fsync the containing directory when the target platform requires it.

Withdrawal recovery requires the same scope digest. Lifecycle recovery replays historical actor evidence at occurrence time. Publication recovery preserves the last durable phase and never upgrades an unknown/partial effect into success. Restoring an older registry, withdrawal snapshot or route marker cannot override a current independently authenticated head or current revocation/withdrawal frontier.

Rollback is a new authorized transition to an exact compatible predecessor. It is never implicit reuse of an expired grant, stale backup, old witness or previously selected state.

## 9. Security, privacy and threat controls

Owned threat entries:

- `artifact_lineage_break`
- `current_run_artifact_swap`
- `operator_sensor_clustering`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

Source-enforced ceilings relevant to this module include:

- candidate payload: 64 MiB;
- canonical V1 registry snapshot: 8 MiB;
- complete canonical V3 admission sidecar: 128 KiB, with 128-byte field lines;
- artifact-registry / withdrawal / lifecycle durable record ceiling: 4,096 records;
- V2 source datasets per manifest: 64;
- V2 lineage digests per manifest: 1,024;
- V2 predecessor IDs per manifest: 64;
- iteration candidates: 32;
- iteration files per candidate envelope: 100;
- iteration semantic diff budget: 1 MiB;
- parallel iteration sandboxes named by an envelope: 8;
- iteration ledger events: 384.

These bounds are safety/resource limits, not benchmark claims. Measure payload write + fsync, snapshot encode/write/reopen, withdrawal and lifecycle replay, current-head witness publication, pinned cold read/hash, current-view revalidation, crash recovery, parent-directory synchronization and orphan reconciliation on the selected target host.

Owner admission additionally counts every existing namespace entry, including
orphans and unrelated files. A new artifact operation reserves its five checkpoint
names, one payload/admission/snapshot/witness/head before `Prepared`. Limits are
4,096 payloads, admissions and heads; 8,192 registry and witness files; 12,288
withdrawal snapshots; 20,480 artifact checkpoints; and 16,384 state checkpoints.
State publication reserves its four phases and snapshot/head needs; unchanged
CURRENT reuses its head at the head limit. Exact existing-operation retries do
not reserve new names. These are conservative entry budgets, not a free-space
reservation or a claim that filling the theoretical byte maximum is operationally
safe. Disk-full and failed synchronization remain indeterminate and require exact
reconciliation. The deployment must enforce its tighter disk and retention policy.

The V1 compatibility registry remains intentionally bounded. A product that needs a larger history must introduce a new durable format or compaction/checkpoint design; it must not silently raise the in-memory limit beyond what the supported durable representation can carry.

## 11. Observability and operations

Operate create-only artifact storage under one writer owner, with independently retained receipts and current revocation/withdrawal/head witnesses. Do not derive an expected receipt from the file currently under inspection.

For safer filesystem integration prefer the contained prevalidated writers:

- `write_candidate_payload_beneath`;
- `write_registry_snapshot_beneath`;
- `write_registry_head_witness_beneath`;
- `write_dataset_withdrawal_snapshot_beneath`;
- `write_artifact_lifecycle_snapshot_beneath`.
- `write_artifact_admission_snapshot_beneath`.

The lower-level `CreateOnlyArtifactFile` APIs remain for compatibility and capability-based composition. A host using them must reconcile empty files caused by creating a capability before later semantic validation.

The crate deliberately exposes no mutable “admin override”, force-select, force-promote or force-repair API. `ArtifactPublicationTransactionV1::status` provides a deny-all read-only service/admin projection containing operation, phase, admission/withdrawal bindings, registry head, witness, acknowledgement time and transaction state digest. Repair still requires a separately authenticated/fenced host operation. This keeps operational tooling from becoming an undeclared authority bypass.

Current operating and state-format references:

- [codex-rs/hepta-learning-artifacts/STORAGE.md](../../../codex-rs/hepta-learning-artifacts/STORAGE.md);
- [codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md](../../../codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md);
- [codex-rs/hepta-learning-artifacts/PINNED_LOAD.md](../../../codex-rs/hepta-learning-artifacts/PINNED_LOAD.md);
- [codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md](../../../codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md);
- [codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md](../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md).

Target-host alerting should distinguish rejected input, capacity exhaustion, busy lock, stale/scope-mismatched evidence, corrupt durable bytes and indeterminate I/O. Concrete thresholds require the selected deployment profile.

The product writer opens `LearningArtifactOwnerService::open_v2` with
`LearningArtifactOwnerServiceConfigV2 { owner: ConfigV1,
required_withdrawal_head_digest }`. The inner V1 configuration carries public
trust, a signed writer lease, storage binding, scoped withdrawal registry and
the independently retained signed CURRENT floor. V2 additionally requires an
independently retained nonzero withdrawal floor and proves both histories on
restart; a self-consistent restored backup is insufficient. An unfinished
operation fences unrelated publication until the exact operation is reconciled.
A terminal retry must retain the original admission, payload and signed head.
`install_withdrawal_frontier` accepts an identical frontier only; advancement
returns `DurableStatePublicationRequired` and must use `prepare_state_registry`
then externally signed `publish_state`. Renew trust or the lease by constructing
a new host; do not mutate them inside a running generation.

Before enabling a strict reader on an older store, inspect original registration
checkpoints and perform exact sidecar backfill. Retain the current registry and
withdrawal floors outside the rollback domain. Treat missing sidecars, mismatched
projection, expired current artifacts and incomplete state-saga recovery as
distinct operational failures; none authorizes an old-snapshot fallback.

## 12. Verification and qualification

Run the affected package through the repository runner from `codex-rs`:

```sh
just test -p codex-hepta-learning-artifacts
cargo check --locked -p codex-hepta-learning-artifacts --all-targets
just fix -p codex-hepta-learning-artifacts
just fmt
```

For ordinary development, run `python3 scripts/hepta-docs.py verify --profile development` from the repository root. An implementation-map test reference names a real source test, not a test pass or production receipt. Rebind only the changed module after committing source changes with `python3 scripts/hepta-implementation-maps.py migrate --module learning.artifacts`; qualification validates those exact Git identities separately.

Focused native coverage includes:

- V2 manifest normalization and lineage rejection in `closure_v2_tests.rs`;
- persistent withdrawal replay and future-admission denial;
- scoped V3 admission, including unscoped fail-closed and cross-scope publication rejection;
- lifecycle transition separation plus historical replay after actor credential expiry;
- create-only storage, lock/read budgets, path escape and symlink-ancestor rejection;
- validation-before-create proof that a rejected payload does not leave a final-path orphan;
- canonical durable withdrawal and lifecycle snapshot round trips with digest/scope checks;
- complete multi-source/multi-parent admission sidecar recovery, hostile collection counts, canonical-form rejection and historical expiry;
- strict closure rejection for missing provenance, withdrawn secondary datasets, expired artifacts and unavailable non-V1 parents;
- publication phase ordering, crash snapshot replay and V1/V2 projection mismatch rejection;
- exact pinned load/current-view revalidation and dataset revocation propagation;
- bounded iteration and iteration-ledger transition/replay tests.

Dedicated adversarial regressions also cover producer substitution, actor-role replay drift, future/backdated lifecycle evidence, invalid iteration rollback state, expired iteration evidence, recomputed withdrawal admission, selector expiry, rejected-head side effects, missing checkpoint phases, renewed leases, current-head forks, active orphan locks and consumer panic. They live beside the implementation in `*_adversarial_tests.rs`, `pinned_tests.rs` and `storage_hygiene.rs`.

The Lane E workflow executes locked all-target compilation, owner tests, cross-crate causal closure, the Rust↔Python wire-fault test, strict Clippy, rustfmt and an ordered-parent synthetic merge. The synthetic merge uses the pull-request base on PR events and `github.event.before` on normal pushes; initial pushes with a zero predecessor do not pretend to have a valid merge base.

A green workflow is execution evidence for its exact commit only. It is not product activation, operator acceptance, selection, promotion or release. The repository cannot self-produce external filesystem trust, newest-head distribution, signing-key authentication or production route evidence.

## 13. Implementation sequence and work packages

The `State:` values inside the execution envelopes below are canonical planning metadata imported from the global work-package plan; they are not a live substitute for the source status in sections 2 and 12. A package may still display `planned` here while its source candidate exists and awaits exact-commit qualification or external activation evidence.

Applicable work packages:

- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `HBO-1-OPERATOR-SENSOR-CORE`

The bootstrap package is `ART-1-LEARNING-ARTIFACT-REGISTRY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

### Current product composition and deployment inputs

The owner retains complete V3 sidecars and publishes registration and restriction
state through distinct crash-recoverable sagas. Strict CURRENT views join every
sidecar, all parents, current expiry and the authenticated withdrawal frontier.
`prepare_dataset_revocation` remains an explicitly snapshot-local V1 compatibility
helper; the product owner does not infer multi-source membership from that helper's
single support digest.

Agentd's cognitive ranker and the NDU stochastic admission path consume opaque
authenticated CURRENT views. Plasticity bootstrap and the long-lived parameter/
topology owner require an independent CURRENT provider before each proposal,
bound to their exact frozen artifact receipt. A changed head, unavailable provider
or failed authentication fences the generation until explicit refresh/rebootstrap.
The source proposal path returns DENY_ALL and does not grant installation authority.

Legacy V1 inspection remains available as an explicit compatibility mode. It cannot
stand in for a strict V2/V3 consumer or reconstruct missing provenance. The
remaining external facts are target-host execution, signing-authority enrollment,
newest-head and withdrawal-frontier distribution, independent rollback domains,
operator acceptance and release. They include deployment inputs/evidence and the explicit consumer/recovery
composition limits listed in Section 4; no source-completion claim hides them.

For `learning.artifacts`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `ART-1-LEARNING-ARTIFACT-REGISTRY`

- State: `source_implemented`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-learning-artifacts/**`
- `codex-rs/hepta-shadow-qualification/tests/durable_learning_roundtrip.rs`
- Development predecessors:
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `MEM-1-STORE`
- Activation predecessors:
- `MEM-1-STORE`
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

#### `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`

- State: `source_implemented`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-learning-artifacts/**`
- `qa/learning/reload-rollback/**`
- Development predecessors:
- `LRN-2-CAUSAL-EVALUATION`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- Activation predecessors:
- `LRN-2-CAUSAL-EVALUATION`
- `HBO-1-OPERATOR-SENSOR-CORE`
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
- `current_snapshot_immutable`
- `signed_next_snapshot`
- `exact_reload`
- `rollback_predecessor`
- `crash_reopen`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `HBO-1-OPERATOR-SENSOR-CORE`

- State: `source_implemented`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-learning-artifacts/**`
- `codex-rs/hepta-bellman-operator/**`
- Development predecessors:
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- Activation predecessors:
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
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

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `learning.artifacts` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::operator_sensor_core_registryV1`
- `LearningArtifactManifestV1`
- `ModulePort::learning.artifacts::intuition.policy`
- `ModulePort::learning.artifacts::learning.eval`
- `ModulePort::learning.artifacts::learning.operator`
- `ModulePort::learning.artifacts::learning.plasticity`
- `ModulePort::learning.artifacts::neuron.runtime`
- `ModulePort::learning.artifacts::prompt.optimizer`
- `ModulePort::learning.artifacts::utility.ndu`
- `OperatorSensorCoreManifestV1`

**Consumed contracts:**
- `AlgorithmFaultReceiptV1`
- `BellmanOperatorArtifactV1`
- `CandidateEvaluationReceiptV1`
- `ConformanceReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `EvaluationReceiptV1`
- `IndependentDecisionReceiptV1`
- `IterationCandidateV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::kernel.operations::learning.artifacts`
- `ModulePort::platform.types::learning.artifacts`
- `NduCoefficientManifestV1`
- `NduWellPosednessCertificateV1`
- `OperatorApplicabilityCertificateV1`
- `PlasticityProposalV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`
- `TopologyProposalV1`
- `UnlearningComplianceReceiptV1`

**Typed protocols:**
- `AlgorithmFaultReceiptV1`
- `CandidateEvaluationReceiptV1`
- `ConformanceReceiptV1`
- `DatasetSnapshotV1`
- `EvaluationReceiptV1`
- `IndependentDecisionReceiptV1`
- `IterationCandidateV1`
- `LearningArtifactManifestV1`
- `LongitudinalEvaluationReceiptV1`
- `NduCoefficientManifestV1`
- `NduWellPosednessCertificateV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `PlasticityProposalV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`
- `TopologyProposalV1`
- `UnlearningComplianceReceiptV1`

**Owned data domains:**
- `learning_artifact_registry`
- `operator_sensor_core_manifest_v1`
- `operator_sensor_core_registry`

**Read data domains:**
- `algorithm_fault_receipt_v1`
- `candidate_evaluation_receipt_v1`
- `conformance_receipt_v1`
- `cross_owner_outbox`
- `independent_decision_receipt_v1`
- `iteration_candidate_v1`
- `ndu_coefficient_manifest_v1`
- `ndu_well_posedness_certificate_v1`
- `operation_ledger`
- `operator_applicability_certificate_v1`
- `plasticity_proposal_v1`
- `regularity_profile_v1`
- `support_audit_receipt_v1`
- `topology_proposal_v1`

**Work packages:**
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `HBO-1-OPERATOR-SENSOR-CORE`

**Owned threats:**
- `artifact_lineage_break`
- `current_run_artifact_swap`
- `operator_sensor_clustering`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.artifacts` to primary lane `LANE-E-LEARNING`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-NEU`](../../readiness/NEURON_RUNTIME_EXECUTION.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)
- [`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md)

Owned readiness protocols:

- `CandidateLineageV1`

Consumed readiness protocols:

- `EvaluationPlanV1`
- `NduConvergenceCertificateV1`
- `RetentionSliceReceiptV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.artifacts` is implemented by work package `ART-1-LEARNING-ARTIFACT-REGISTRY` in:

- `codex-rs/hepta-learning-artifacts`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.

### First-publication withdrawal bootstrap

Before any artifact CURRENT exists, `LearningArtifactOwnerService::publish_withdrawal_bootstrap`
accepts `LearningArtifactWithdrawalBootstrapRequestV1` signed by an externally configured
head signer in the separate `hepta.learning-artifacts.withdrawal-bootstrap.v1` domain.
The authorization binds operation, registry, storage binding, scoped predecessor and
successor withdrawal heads, signer, epoch and validity interval. It grants no artifact
selection or registry head. New bootstrap operations are rejected after CURRENT exists.
The exact withdrawal snapshot is persisted and synchronized before the immutable signed
`withdrawal-bootstrap/{operation-hash}.receipt`. Orphan snapshots do not advance recovery;
acknowledged records require their exact snapshot and signature. Recovery joins only
compatible prefix extensions. Exact retries cannot roll the live frontier backwards.
`open_v2` also applies the independently retained withdrawal head floor to this frontier.
Tests in `owner_state_tests.rs` cover unsigned mutation, stale authorization, first-publication
admission denial, exact retry, restart and missing acknowledged snapshot.
