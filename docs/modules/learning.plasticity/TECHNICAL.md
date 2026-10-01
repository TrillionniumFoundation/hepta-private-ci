# learning.plasticity technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.plasticity`

**Owner:** `learning-platform`

**Deputy:** `architecture`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `PLS-1-PARAMETER-PLASTICITY`

This stable document is the implementation guide for `learning.plasticity`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Generate governed parameter and topology proposals without runtime topology mutation or self-promotion.

The primary owner `learning-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `architecture` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `qualification`, kind `proposal_engine`, state model `stateful_shadow` and architecture role `slow_learner` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-plasticity`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-plasticity`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `learning.plasticity`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

### Source composition and position in the learning loop

Plasticity is the slow proposal stage after immutable experience, selected-artifact
lineage and independent evaluation exist. It produces a possible next snapshot;
the currently serving artifact and topology remain owned by their existing
selectors and execution owners. `learning.operator` supplies slow value-learning
artifacts, `utility.ndu` supplies modulation, and `neuron.runtime` supplies local
eligibility. None of those inputs is permission to install a generated update.

| Boundary | Current source responsibility | Evidence ceiling |
| --- | --- | --- |
| `hepta-plasticity` | Deterministic bounded parameter/topology proposals, mutation-policy checks, durable proposal registries and canary observations | Integrity and proposal mechanics; no owner authentication or application |
| `hepta-intelligence` | Authenticate Generator/Observer/Evaluator evidence, compose independent evaluation and append through the anchored adapter | Authenticated source composition; no selection or activation |
| `hepta-agentd` | Reconstruct explicit owner stores, retain the sole long-lived writer, revalidate current frontiers and serialize bounded submissions | Host composition and repository process/lifetime qualification |
| `control.engineering` / self-iteration coordinator | Target caller that consumes a frozen envelope and independently evaluated requests | Upstream production trigger remains uncomposed; a forwarding façade is insufficient |
| `hepta-runtime` | Separately authorized topology migration, live replacement and stopped/quarantined recovery | External execution owner; its source tests are not deployment acceptance |

The implemented submission route is `AgentdState` →
`AgentdLearningPlasticityProducerV1` → bounded `PlasticityRuntimeHandleV1` →
`PlasticityRuntimeOwnerV1` → parameter/topology host adapter → authenticated
product adapter → durable registry and external anchor commit. The producer holds
only the channel handle. It cannot access writers, owner stores or trust roots.
The state submission methods are currently exercised by lifetime qualification;
the presence of those methods does not prove an upstream product caller invokes
them. `CURRENT_IMPLEMENTATION.md` and `IMPLEMENTATION_MAP.json` retain that gap.

The process bootstrap recovers an ArtifactRegistry snapshot, anchored ledger and
neuron state, NDU projection journal and learning-evidence trust configuration for
one Agentd generation. Recomputing their current in-process heads is not evidence
of a subscription to changes made by an external owner. No hot-refresh or
revocation subscription is implied by this bootstrap. A selected host must keep
the admitted generation synchronized through an explicit owner integration or
reconstruct it from fresh independent witnesses before admitting changed source,
selected-artifact, trust/revocation, objective or dynamic-owner state.

Before composing the target coordinator, bind the exact envelope/base, objective,
mutation grammar, candidate budget and frozen request to independently verified
evidence. A native `IterationEnvelopeV1` record or caller-provided digest alone is
not an authenticated source observation or evaluation. The coordinator must not
create the evidence it consumes, reopen a second writer, turn a turn/automation
request into an implicit learning trigger, or authorize selection.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `learning.eval`
- `learning.artifacts`
- `kernel.evidence`

Authoritative write domains:

- `iteration_candidate_v1`
- `plasticity_proposal_registry`
- `plasticity_proposal_v1`
- `topology_proposal_v1`

These are canonical logical ownership declarations. Current native durable writes
are parameter/topology proposal registry records; the declaration of
`iteration_candidate_v1` does not imply the upstream iteration coordinator is
implemented.

Explicitly denied capabilities:

- `runtime_topology_mutation`
- `authority_mutation`
- `self_promotion`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `evidence loader`
- `candidate generator`
- `constraint filter`
- `proposal registry writer`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Propose bounded cell-parameter and organ-structure candidates, including no-change, reuse, distillation and retirement. Require data-supported specialization and include state/optimizer transformations, affected bundle, cost and rollback. Avoid unconstrained node multiplication and arbitrary weight averaging as knowledge transfer.

Classify routing-policy changes separately from new circuit structure. Typed add/split/merge/rewire/retire candidates preserve outstanding operations, compatible states and stable organ ports. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: local norm limits, unsupported large-delta transport, split/merge state mapping, retirement and current-revocation rollback.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Compare increasing depth, width, information capacity or adapter freedom as different candidate classes. Keep no-change and fixed-update baselines. Changing representation/field dimension requires explicit dependent-state transport; learned adaptation is tested on held-out task families.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Generate scoped parameter or skill/Circuit candidates from supported experience. Broader consolidation is a new permitted use, not automatic common-weight averaging. Record prerequisites, failure/recovery and old-task retention; recalled skill never grants its own execution.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::plasticity_proposal_registryV1`
- `IterationCandidateV1`
- `PlasticityProposalV1`
- `TopologyProposalV1`

Consumed contracts:

- `DomainRead::learning_artifact_registryV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `IterationEnvelopeV1`
- `ModulePort::kernel.evidence::learning.plasticity`
- `ModulePort::learning.artifacts::learning.plasticity`
- `ModulePort::learning.eval::learning.plasticity`
- `NeuronCheckpointV1`
- `RandomStreamManifestV1`

Critical protocol schemas:

- `IterationCandidateV1`
- `IterationEnvelopeV1`
- `NeuronCheckpointV1`
- `PlasticityProposalV1`
- `RandomStreamManifestV1`
- `TopologyProposalV1`

These lists match the generated exact registry projection below. They describe
registered target contracts, not a claim that every native Rust type implements
the canonical wire schema. Source APIs and operation-level state are separately
mapped in `IMPLEMENTATION_MAP.json`.

### Internal proposal version boundary

The crate's historical `hepta.plasticity.proposal.v1` record is not the canonical JSON `PlasticityProposalV1`. Explicit version dispatch preserves it for bounded read-only inspection only. Its stored shape omitted a value that participated in its digest, so readers cannot claim full digest reconstruction. Legacy proposal creation, registry append and automatic migration fail closed. Version/payload mismatch and unknown versions are rejected; no V1 record is relabeled or synthesized as V2.

All new writes use the internal, parameter-only `ParameterProposalV2` profile registered in `docs/learning/LEARNING_SYSTEM.json` and specified in `docs/learning/NEURAL_BIOMIMICRY_SPEC.md`. It binds proposal/proposer/evaluator ID strings, the selected artifact digest, window ID and digest, exact-successor generations, dataset, update rule, modulator, modulator broadcast, eligibility, evaluation and rollback-predecessor digests, the artifact-bound norm profile, every caller-supplied candidate and computed metric. These are deterministic integrity bindings over supplied values, not authentication of the external facts those values name. The record contains no topology delta, chosen-candidate field, activation, selection or promotion claim.

Each bounded caller-supplied candidate set contains `1..32` candidates, at most 4,096 total deltas and exactly one explicit no-change candidate. The crate proves only structural completeness of that supplied set; it cannot prove that the set is complete relative to a generator or search space. The set is one proposal envelope, not several final proposals. Parameter IDs are unique within a candidate, updates are nonzero and bounded, and candidate/delta/layer order is canonical. Norm profiles contain `1..256` layers. The registry reserves one slot per `(selected_artifact_digest, window_id)` and caps configured capacity at 4,096 records; a changed window digest or other semantic drift in an occupied slot conflicts, while an identical replay is idempotent and consumes no additional capacity.

The norm profile uses squared L2 Q64 numerators and nonzero per-layer baseline squared L2 Q64 denominators. The checked sum of every declared layer denominator is the global denominator. Per-layer relative norm is limited to `5000 ppm` and aggregate relative norm to `2500 ppm`, using exact squared-ratio comparisons. Because the aggregate is energy-weighted across the complete profile, a small layer may pass the global gate while failing its own gate; both checks are required. The raw V2 crate binds but cannot authenticate the caller-supplied artifact profile; artifact/window/dataset/update/modulator/eligibility/evaluation/per-delta evidence digest provenance, freshness or completeness; or independent identities merely from unequal proposer/evaluator ID strings. The governed V3/product path therefore adds deterministic regeneration, a typed parameter-specific `ParameterMutationPolicyV1` allowlist/protected-surface view, pairwise signed Generator/Observer/Evaluator admission, current owner-frontier recomputation plus context-bound owner-evidence resolution in Agentd (including exact signal values and the parameter mutation-policy digest), a long-lived generation-fenced Agentd plasticity owner, and external anchor/fence persistence. The canonical readiness protocol `MutationGrammarManifestV1` remains owned by `control.engineering`; this module consumes its governance intent but does not redefine or claim wire-equivalence with that protocol. Dataset receipts are concretely verified against the live DurableLedger head and immutable update/mutation Policy artifacts against the live ArtifactRegistry head. Dynamic evidence is also source-bound to its authoritative owner surfaces: NDU supplies the current modulator projection, the immutable broadcast-policy artifact binds the broadcast mapping, neuron.runtime supplies the anchored eligibility checkpoint, and ParameterSignal evidence recomputes the exact consumed eligibility/modulator/learning-rate/bounds. These adapters reject stale, rolled-back, unavailable, wrong-owner and value-substituted state; target-host opening/placement of those owner stores remains deployment evidence. A deterministic no-update result is not treated as an ordinary error: an independent Evaluator must attest the exact `NoAdmissibleUpdate` terminal payload before the no-change-only proposal is durably recorded. None of those steps authorizes selection or activation.

Golden fixtures `PLASTICITY-V1-GV-001` and `PLASTICITY-V2-GV-001` fix, respectively, the 307-byte legacy digest `a143a54a94d60d2734237612f1c2e0af4b4d986ea52efa6099765b83442dedb4` and the 898-byte V2 digest `e2ecdc9e0fd3278865665a2b0b168a3048919e86e8979e2e90bc6e5db9ab357c`. The V2 artifact norm-profile digest is `d31bd6f69d36817557272d747e5209d431e3ef3058e6f415dc57da4f8f98fb97`. Tests use these as hard-coded independent oracles and assert deny-all authority.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Native Rust proposal types use deterministic canonical byte encodings and tests cover maximum bounds, canonical ordering, trust-region arithmetic, digest stability, durable recovery and fail-closed authority behavior. Canonical JSON protocol semantics remain defined by the registered contract/readiness schemas; a module-local native type is not claimed to be a JSON round-trip implementation unless a registered adapter explicitly provides that mapping. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

### Implemented API and admission sequence

| API | Required input / validation | Result |
| --- | --- | --- |
| `generate_parameter_candidates_v3` / `verify_generated_parameter_candidates_v3` | Artifact/window-bound profile, exact signal identities/values, protected-surface policy, declared scales, trust regions and checked arithmetic | Deterministically regenerated set including no-change; generator-relative completeness only |
| `propose_v2` / `verify_parameter_proposal_v2` | Canonical bounded envelope, exact successor generation, artifact norm profile and every candidate metric | Integrity-checked authority-free parameter proposal |
| `propose_authenticated_parameter_plasticity_v1` | Verified Generator/Observer signatures, current admission context and independent signed evaluation of every update, or exact Evaluator-signed no-update terminal payload | Durable parameter receipt only after external anchor commit |
| `propose_topology_v2` / `admit_governed_topology_v1` | Typed changes, exact predecessor, migration/rollback/evidence bindings and one exact advancing writer-handoff plan per update | Authority-free governed topology proposal |
| `propose_authenticated_topology_plasticity_v1` | Current Generator/Observer/Evaluator signatures over the exact generation/admission/evaluation context | Governed topology registry append; no application |
| `build_structural_canary_plan_v1` / `observe_authenticated_structural_canary_v1` | Stored durable proposal/append receipt, exact candidate/plan and Observer-signed observation facts | Bounded observation state and terminal receipt; no topology authority |

At the host boundary, validate the live Agentd generation/readiness, re-read the
ArtifactRegistry and DurableLedger heads, resolve typed evidence from its
allowlisted owner, verify signed admission and all evaluation roles, regenerate
and validate the candidate, append with the exact registry predecessor, and commit
the current anchor before returning success. A changed head or stale owner value
requires newly frozen evidence rather than digest-only fallback. Missing update
evaluation, signed-role collision and protected-surface mutation are semantic
rejections. Only deterministic generation with no admissible update enters the
independently attested no-change terminal path.

The runtime owner samples its Unix-millisecond clock after dequeue, before the
host adapter validates evidence. The submission API's historical `now` argument
is retained for compatibility and cannot control verification time. Clock failure
rejects admission. Every successful sample, at dequeue or final admission,
advances an owner-lifetime time high-water mark even when the request is later
rejected. A later sample below that mark rejects; rejecting an expired or revoked
request cannot reset the floor and revive its evidence on the next request.
This floor belongs to the current owner lifetime and is not a persisted or
distributed clock authority. Queue capacity is configured within `1..64`; waiting
in that queue does not extend a signature's validity period.

Generation, evaluation and proposal preparation run before final admission. The
guarded registry append also completes its applicable full-history integrity
scan, semantic preflight and frame encoding before invoking the product callback.
That callback samples the host clock again and rechecks signed evidence, principal
validity, scheduled revocation and trust context. Parameter admission additionally
requires that time to lie within the intersection of every initially
authenticated owner receipt's validity interval. The callback precedes writer
poison/write transitions and both a new physical append and an identical-retry
positive receipt. Its rejection leaves the writer and durable registry unchanged.
The native entrypoints are `DurableProposalRegistry::append_v2_with_final_admission`
and `DurableTopologyProposalRegistryV1::append_with_final_admission`; each invokes
its callback once for a prepared new append or unchanged retry. The raw registry
does not create clock, signature or lifecycle authority for that callback.
This includes time spent on expensive registry preparation in final temporal
admission; it does not imply hot refresh of the generation's externally selected
owner/trust snapshots. Native fixed-time proposal APIs remain compatibility
surfaces, not the live host clock.

Final admission also rechecks cancellation and obtains the local Agentd runtime
mutex guard for the owner's exact Running generation. That guard remains held
through the synchronous registry append and external-anchor commit, serializing
local draining, fencing and readiness changes with the already admitted
transaction. Cancellation observed before this gate rejects. Cancellation,
signature expiry or an external supervisor publication after the gate does not
roll back an in-flight append/anchor transaction. Its outcome must be reconciled
from the durable registry and independent anchor if the response is lost. This
gate leaves only the admitted synchronous durable transaction, post-write
integrity confirmation and anchor commit. It does not resample signatures for
each physical byte written. The operation is bounded by the configured history,
not a hard wall-clock deadline or distributed atomicity with Fleet or other
owners.

Topology updates are alternatives, each containing one typed operation; several
alternatives may target the same module. Admission and canary construction match
the selected change by both module identity and exact writer-handoff plan digest,
so another alternative for that module cannot supply its handoff or rollback.
Canary regression counts are cumulative, cannot decrease and cannot exceed the
observation sequence. The Observer signs these counts with the exact plan and
other observation facts; `finish()` remains a separate terminal transition.

The plan uses the `hepta.plasticity.structural-canary-plan.v3` digest domain and
binds the durable registry scope and writer fence as well as the original
sequence/frame, exact candidate, handoff set, rollback, health and thresholds.
Identical proposal bytes in another scope or writer generation therefore produce
a different plan. Observer evidence signed against an older plan digest must be
regenerated and independently signed; no legacy plan signature is relabeled as a
V3 observation.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `iteration_candidate_v1`
- `plasticity_proposal_registry`
- `plasticity_proposal_v1`
- `topology_proposal_v1`

Read-only data dependencies:

- `iteration_envelope_v1`
- `learning_artifact_registry`
- `neuron_checkpoint_v1`
- `operator_sensor_core_registry`
- `qualification_evidence`
- `random_stream_manifest_v1`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Both live proposal registries verify their open file against the exact enrolled
header, trusted frame digests and expected physical EOF before cached record/count
or anchor results, identical retries, topology canary binding and appends. They
check every frame's bounds, prefix, complete body digest and footer. After a
successful write they repeat the check before returning a positive append
receipt. An integrity or read-I/O failure poisons that live handle; cached
proposal objects cannot substitute for its current file bytes. Recovery requires
explicit anchored reopen rather than repair through the live handle.

This check performs `O(history bytes)` I/O with a fixed 32 KiB streaming scratch
buffer and bounded header/frame metadata; it neither clones nor decodes the full
proposal history on each call. Physical history is capped at 512 MiB for the
parameter registry and 256 MiB for the topology registry, independently of record
count limits. Registry access serializes the verification cursor. The host still
owns immutable path/inode enrollment and must honor the
exclusive file-descriptor contract: a competing host mutation or seek through a
shared descriptor is outside that contract. Header scope/fence getters describe
immutable enrolled metadata and do not themselves certify current file history.
Byte verification is not distributed storage atomicity or evidence of physically
independent rollback domains.

The registry poison getter reports a cached sticky failure latch without scanning
the file. `AnchoredPlasticityWriterV1::state()` combines its own state with that
latch, so an integrity failure detected by a read-only registry query is also
reported as `Poisoned` by the writer. A cached `Healthy` state or false poison
latch does not authenticate current bytes; the checked operation performs that
verification. These health getters do not add a full scan to every poll.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

`PlasticityRuntimeOwnerV1` is the source-selected long-lived Agentd owner. It exclusively retains the parameter/topology writers, anchor stores, current ArtifactRegistry/DurableLedger handles, trust verifier and owner-evidence resolver behind a bounded typed channel. `runtime.rs` supervises the owner as part of the Agentd task set, and each proposal checks the current Running/ready generation before admission. The owner is opt-in and there is no public wire method or ambient fallback writer.

The owner pins its one Running generation to `identity.spawn_generation + 1`
using checked arithmetic; overflow rejects. It never adopts a newly observed
generation from a queued request. Dequeue and final admission both require that
exact generation and current readiness. Draining is a one-way process latch:
once local or supervisor-driven drain begins, a late App Server readiness probe
or stale Running observation cannot reopen admission. A new lifetime requires
explicit supervisor/bootstrap reconstruction.

The [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

The adapter writer transitions `Healthy → AppendPendingAnchor → Healthy` only
after a durable external anchor acknowledgement. Anchor failure transitions to
`Poisoned` even if registry bytes were written; subsequent operations on that
handle reject. Anchored reopen validates the independently retained acknowledged
prefix before repair. Identical semantic replay returns the original record;
reuse of an occupied artifact/window slot with changed semantics conflicts.

Generation rollover is explicit and monotonic. An interrupted bootstrap may
resume only with zero complete proposal frames; an incomplete first frame can be
repaired, but a complete unacknowledged proposal is preserved for reconciliation.
The append-only anchor journal repairs only an incomplete final crash tail after
all complete predecessors validate. Complete corrupt frames, missing acknowledged
history and fence/anchor mismatches require recovery and never trigger a fresh
unanchored bootstrap.

The external `AdaptiveAnchorJournalV1` also verifies its complete online file
against the retained 72-byte header, trusted digests of every 81-byte frame and
exact expected EOF before issuing a writer fence or persisting an anchor. An
identical anchor acknowledgement crosses the same check rather than succeeding
from cached state alone. A new synchronized journal write is checked again before
the handle clears its poison state and returns success. Detected corruption or
journal I/O uncertainty poisons that handle: the frame may already be durable, so
neither anchor acknowledgement nor another writer fence may be issued until
explicit reopen/reconciliation. Cached `state()`, fence, anchor and
previous-anchor snapshots describe retained metadata and do not authenticate the
current journal bytes.

The journal caps history at 1,000,000 frames, or 81,000,072 bytes including its
header. Verification uses fixed header/frame scratch and retains one trusted
digest per complete frame plus a fixed 32 KiB read buffer: `O(frames)` metadata
memory and `O(history bytes)` I/O,
without a full-history byte copy. The host's immutable enrollment and cooperative
exclusive file-description contract still applies. Initializing a zero-length
journal resets the file cursor before writing its header. Journal failure after a
proposal append does not undo that proposal's durable bytes or make the two files
an atomic storage transaction.

The trusted online frame list belongs to the live journal handle. Dropping that
handle loses this particular observation; ordinary journal reopen verifies
checksums and transition grammar without an independent journal-head witness.
It cannot alone distinguish the former acknowledged history from a restored
header-only image or an older valid complete prefix. Recovery must reconcile
independently retained fence/anchor history and the selected host's attested
rollback-domain assumptions. Reopen success alone is not proof that an earlier
acknowledgement survived. Physical independence of journal and registry rollback
domains remains target-host evidence. The concrete steps are in `OPERATIONS.md`.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `topology_self_activation`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The native plasticity crate remains candidate-only with durable parameter/topology proposal registries. Preserve the proposal version and exact predecessor; V1 read compatibility is not permission to emit new V1 writes. Structural split/merge/rewire is consumed only by the separate `codex-hepta-runtime` execution owner after governed writer-handoff validation and a single-use FinalUse grant. Healthy replacement and stopped/quarantined recovery are separate runtime transitions with distinct FinalUse destinations; neither gives `learning.plasticity` topology-apply authority.

Current operating and state-format references:

- [codex-rs/hepta-plasticity/src/parameter_v2.rs](../../../codex-rs/hepta-plasticity/src/parameter_v2.rs).
- [codex-rs/hepta-plasticity/src/durable_registry.rs](../../../codex-rs/hepta-plasticity/src/durable_registry.rs).
- [docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md).
- [docs/modules/learning.plasticity/OPERATIONS.md](OPERATIONS.md).
- [docs/readiness/SELF_ITERATION_EXECUTION.md](../../readiness/SELF_ITERATION_EXECUTION.md).
- [codex-rs/hepta-runtime/src/topology_execution.rs](../../../codex-rs/hepta-runtime/src/topology_execution.rs) — external FinalUse-authorized consumer for an independently accepted governed topology candidate.

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-plasticity/src/durable_registry_tests.rs](../../../codex-rs/hepta-plasticity/src/durable_registry_tests.rs); named case: `append_reopen_and_anchor_preserve_exact_record`.
- [codex-rs/hepta-plasticity/src/lib_tests.rs](../../../codex-rs/hepta-plasticity/src/lib_tests.rs); named case: `legacy_v1_is_explicit_read_only_and_never_upconverted`.
- [codex-rs/hepta-agentd/src/plasticity_runtime.rs](../../../codex-rs/hepta-agentd/src/plasticity_runtime.rs); named case: `runtime_queue_capacity_is_bounded`.
- [codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs](../../../codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs); named cases cover live dataset/policy owner binding and rollback-frontier rejection.
- [codex-rs/hepta-intelligence/src/plasticity_product_tests.rs](../../../codex-rs/hepta-intelligence/src/plasticity_product_tests.rs); named case: `no_admissible_update_is_independently_attested_and_durably_recorded`.
- [codex-rs/hepta-intelligence/src/topology_canary_product.rs](../../../codex-rs/hepta-intelligence/src/topology_canary_product.rs); named case: `payload_binds_every_caller_asserted_canary_fact`.
- [docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json) is the machine trace from every current operation to its focused source tests; `scripts/hepta-implementation-maps.py verify` also checks the generated status block in `CURRENT_IMPLEMENTATION.md`.

In `codex-rs`, run `just test -p codex-hepta-plasticity`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.plasticity.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `PLS-1-PARAMETER-PLASTICITY`
- `PLS-2-TOPOLOGY-PROPOSAL`
- `PLS-3-BOUNDED-STRUCTURAL-CANARY`

The bootstrap package is `PLS-1-PARAMETER-PLASTICITY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `learning.plasticity`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

The `State` values below are canonical delivery/work-package states projected from the delivery registry. They do not override current source-capability facts. Use `IMPLEMENTATION_MAP.json` and the generated status block in `CURRENT_IMPLEMENTATION.md` for implemented-source truth; activation, independent acceptance and release remain separate evidence states.

#### `PLS-1-PARAMETER-PLASTICITY`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `architecture`.
- Allowed write paths:
- `codex-rs/hepta-plasticity/**`
- Development predecessors:
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR`
- Activation predecessors:
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR`
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
- `bounded_parameter_delta`
- `trust_region`
- `no_current_run_mutation`
- `signed_artifact`
- `rollback`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `PLS-2-TOPOLOGY-PROPOSAL`

- State: `planned`; priority: `4`; parallel class: `serial_governance`.
- Owner/deputy: `learning-platform` / `architecture`.
- Allowed write paths:
- `codex-rs/hepta-plasticity/**`
- `qa/learning/topology/**`
- Development predecessors:
- `PLS-1-PARAMETER-PLASTICITY`
- `PIM-3-FACTOR-EVOLUTION`
- `ECP-1-ENGINEERING-CONTROL-PLANE`
- Activation predecessors:
- `PLS-1-PARAMETER-PLASTICITY`
- `PIM-3-FACTOR-EVOLUTION`
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
- `add_split_merge_retire_rewire`
- `capability_typing`
- `lesion_and_ablation`
- `resource_and_security_review`
- `no_runtime_graph_mutation`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `PLS-3-BOUNDED-STRUCTURAL-CANARY`

- State: `planned`; priority: `4`; parallel class: `external_evidence_coordinated`.
- Owner/deputy: `learning-platform` / `architecture`.
- Allowed write paths:
- `codex-rs/hepta-plasticity/**`
- `qa/learning/structural-canary/**`
- Development predecessors:
- `PLS-2-TOPOLOGY-PROPOSAL`
- `P0.9-EXTERNAL-GATES`
- `PLS-1-PARAMETER-PLASTICITY`
- Activation predecessors:
- `PLS-2-TOPOLOGY-PROPOSAL`
- `P0.9-EXTERNAL-GATES`
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
- `signed_topology_snapshot`
- `shadow`
- `bounded_canary`
- `kill_switch`
- `operator_acceptance`
- `rollback_rehearsal`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `learning.plasticity` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `DomainRead::plasticity_proposal_registryV1`
- `IterationCandidateV1`
- `PlasticityProposalV1`
- `TopologyProposalV1`

**Consumed contracts:**
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `IterationEnvelopeV1`
- `ModulePort::kernel.evidence::learning.plasticity`
- `ModulePort::learning.artifacts::learning.plasticity`
- `ModulePort::learning.eval::learning.plasticity`
- `NeuronCheckpointV1`
- `RandomStreamManifestV1`

**Typed protocols:**
- `IterationCandidateV1`
- `IterationEnvelopeV1`
- `NeuronCheckpointV1`
- `PlasticityProposalV1`
- `RandomStreamManifestV1`
- `TopologyProposalV1`

**Owned data domains:**
- `iteration_candidate_v1`
- `plasticity_proposal_registry`
- `plasticity_proposal_v1`
- `topology_proposal_v1`

**Read data domains:**
- `iteration_envelope_v1`
- `learning_artifact_registry`
- `neuron_checkpoint_v1`
- `operator_sensor_core_registry`
- `qualification_evidence`
- `random_stream_manifest_v1`

**Work packages:**
- `PLS-1-PARAMETER-PLASTICITY`
- `PLS-2-TOPOLOGY-PROPOSAL`
- `PLS-3-BOUNDED-STRUCTURAL-CANARY`

**Owned threats:**
- `topology_self_activation`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.plasticity` to primary lane `LANE-F-ADAPTIVE-POLICY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)
- [`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `CandidateLineageV1`
- `MutationGrammarManifestV1`
- `RetentionSliceReceiptV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.plasticity` is implemented by work package `PLS-1-PARAMETER-PLASTICITY` in:

- `codex-rs/hepta-plasticity`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
