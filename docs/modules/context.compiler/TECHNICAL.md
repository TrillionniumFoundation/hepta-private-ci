# context.compiler technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `context.compiler`

**Owner:** `intelligence-platform`

**Deputy:** `security-authority`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `CTX-1-CONTEXT-COMPILER`

This stable document is the implementation guide for `context.compiler`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Compile bounded, source-aware model context while keeping untrusted evidence distinct from trusted instruction.

The primary owner `intelligence-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `compiler`, state model `stateless_runtime` and architecture role `intervention_policy` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-context-compiler`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-context-compiler`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-context-compiler/src/lib.rs](../../../codex-rs/hepta-context-compiler/src/lib.rs). V1 compatibility surfaces include `CompilationRequest`, `ContextCompilationReceipt`, `CompilationRequirementsV1`, `compile`, `compile_candidate_bound` and `compile_with_requirements`. The normative verified V2 surface is implemented in [src/v2.rs](../../../codex-rs/hepta-context-compiler/src/v2.rs) and includes `verify_admission_snapshot_v2`, `verify_admission_snapshot_successor_v2`, `verify_admission_v2`, `compile_v2`, `record_serialization`, `build_attachment`, `prepare_delivery_v2` and `observe_delivery`, typed admission snapshots/evidence, exact-tokenizer and serializer adapters, an opaque pre-dispatch safety witness, and provider-invocation evidence validation. The implementation map uses strict module-local source provenance anchored at commit `1ab65444213e47617d16b7fd03f6e141c4a8a400` / tree `ce640923f09262b664856da31369ae6b3d5fbc1c`; verification checks that anchor identity, ancestry and mapped-source/test drift. Source presence still does not prove product composition, independent qualification or provider execution. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/context.compiler.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/context.compiler.md).

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `platform.wire`
- `cognitive.read`
- `prompt.optimizer`
- `intuition.policy`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `raw_secret`
- `unverified_fact_as_instruction`
- `model_call`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `admission record/snapshot verifier boundary`
- `input normalizer`
- `constraint validator`
- `deterministic compiler`
- `mandatory-group provenance binder`
- `selected-byte realization validator`
- `profile-bound serializer and exact tokenizer boundary`
- `attachment revocation revalidator`
- `provider-invocation evidence validator and terminal delivery receipt emitter`
- `digest and receipt emitter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Normative verified V2 execution path

The V2 source path is deliberately stronger than a digest-only receipt chain:

1. `ContextAdmissionSnapshotV2` is authenticated by a `ContextAdmissionVerifierV2`, producing a non-forgeable-by-struct-literal `VerifiedAdmissionSnapshotV2`. The snapshot is bound to request scope and authority domain, declares a complete cumulative revocation set and is bounded to 4096 revoked admission ids. `verify_admission_snapshot_successor_v2` binds the predecessor snapshot and rejects scope/domain drift, frontier rollback and removal of any previously revoked admission; an oversized cumulative set fails closed rather than pruning history.
2. Every candidate, including evidence, carries `VerifiedAdmissionV2` bound to item id, role, content/source/generation digests, request scope, authority domain, verifier-authenticated secret classification, verifier identity, expiry and the snapshot/revocation epoch at which it was verified. Secret status is not a candidate-side caller boolean, and a verified admission classified as secret is rejected before compilation. A trusted instruction is not represented by a caller-supplied admission digest.
3. `TokenizationReceiptV2::from_exact_bytes` invokes an `ExactTokenizerV2` over actual candidate bytes and binds the tokenizer identity from the exact model profile.
4. `compile_v2` requires one scope, authority-domain and admission-verifier identity for the request, preserves non-tradable trusted/schema floors, canonicalizes mandatory groups and includes `mandatory_groups_digest` in the compilation receipt. Mandatory-group references are bounded to 4096 in aggregate.
5. `record_serialization` consumes the actual selected item bytes, verifies every byte sequence against the selected content digest, invokes the profile-bound serializer, hashes the resulting final payload and then invokes the exact tokenizer over those final payload bytes. Final framing/tool/template overhead therefore counts against the real token budget.
6. `build_attachment` requires a freshly verified admission snapshot and rechecks every selected admission for verifier identity, monotonic snapshot/epoch, expiry and revocation before attachment. Admission expiry is exclusive: a snapshot observed exactly at `expires_unix_ms` is already expired.
7. `prepare_delivery_v2` revalidates again at the pre-dispatch boundary, rejects snapshot epoch or observation-time rollback relative to attachment, and emits a construction-closed `ContextDeliveryPreparationV2` binding the exact payload, provider/model profile and current admission snapshot. The runtime/provider owner performs the physical request and must bind the exact payload SHA-256 into `ProviderRequestBinding.ephemeral_input_sha256`. The existing `ephemeral_input_witness_sha256` remains a provider-owned exact-attempt witness; it is not redefined as `SHA256(ContextDeliveryPreparationV2)`. `observe_delivery` requires that witness to be present and passes the canonical `ProviderInvocationReceipt` together with the current preparation to an independent `ContextProviderDeliveryVerifierV2`, which must authenticate the provider-owned witness/preparation linkage. The compiler directly checks exact payload, provider/model, attempt/terminal and evidence lineage before emitting `ContextDeliveryReceiptV2`. The compiler itself never opens a provider/network/model effect boundary. `ContextCompilationReceiptV2`, `CompiledContextV2`, `SerializedContextV2`, `ContextSerializationReceiptV2`, `ContextAttachmentV2`, `ContextDeliveryPreparationV2` and `ContextDeliveryReceiptV2` are construction-closed outside this module; callers cannot bypass `compile_v2`, exact serialization/tokenization or current-revocation checks by synthesizing proof structs.

The admission verifier, serializer, tokenizer and provider-evidence verifier are explicit trusted adapter seams. Their digest identities are evidence inputs, not authority grants. A malicious or incorrectly configured adapter is outside the compiler's pure-algorithm proof and must be qualified by the owning integration. The actual runtime/provider adapter must independently satisfy the repository's final-use authority contract; this module never mints or consumes provider authority. V1 APIs remain compatibility source surfaces and do not satisfy this V2 proof chain.

### Multiscale DecisionCell integration target

Compile approved cell/organ observations with source and truncation provenance under the same tokenizer and context budget. Treat model messages as evidence/advice, never new authority. Bind the actually delivered content and effective model bundle so training cannot attribute an undelivered intervention to an outcome.

Required targeted tests: truncation accounting, stale evidence, tokenizer mismatch and compiled-versus-delivered identity.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Preserve task-relevant approved representations or owner-readable references rather than silently collapsing all information into labels. Bound and record truncation, tokenizer equivalence, compression and reread costs. Typed/scoped inputs do not by themselves imply sufficient information.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Construct context independently from the local objective, local state and purpose-authorized shared evidence. Bind actual delivered records and truncation; another Agent context, instructions, credential environment or stale cache is not a permissible implicit input. Artifact-only experiments exclude hidden retrieval paths.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced registered contracts:

- `ContextCompilationReceiptV1` (compatibility surface)
- `ModulePort::context.compiler::intelligence.control`

Source-local V2 proof types such as `ContextCompilationReceiptV2`, `ContextSerializationReceiptV2`, `ContextAttachmentV2`, `ContextDeliveryPreparationV2` and `ContextDeliveryReceiptV2` are Rust API artifacts, not separately registered wire contracts in `docs/contracts/CONTRACTS.json`. The normative verified V2 compiler-to-runtime handoff is deliberately in-process and typed; V2 proof objects and payload bytes do not cross `platform.wire`. The registered `hepta.context-compilation-receipt.v2` framing remains a compatibility transport for legacy V1 receipt semantics and now admits only canonical producer `context.compiler`; it must not be interpreted as the verified V2 proof chain.

Consumed contracts:

- `IntuitionDecisionReceiptV1`
- `ModulePort::cognitive.read::context.compiler`
- `ModulePort::intuition.policy::context.compiler`
- `ModulePort::platform.types::context.compiler`
- `ModulePort::platform.wire::context.compiler`
- `ModulePort::prompt.optimizer::context.compiler`
- `ObjectiveFunctionV1`
- `PromptExerciseDecisionV1`
- `PromptPortfolioReceiptV1`
- `PromptPricingReceiptV1`
- `PromptRealizationV1`
- `RunStartSnapshotV1`

Critical protocol schemas:

- `ContextCompilationReceiptV1`
- `IntuitionDecisionReceiptV1`
- `ObjectiveFunctionV1`
- `PromptExerciseDecisionV1`
- `PromptPortfolioReceiptV1`
- `PromptPricingReceiptV1`
- `PromptRealizationV1`
- `RunStartSnapshotV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

None.

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/context.compiler.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/context.compiler.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/context.compiler.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/context.compiler.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `context_secret_leak`
- `prompt_position_truncation`
- `untrusted_content_role_escalation`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/context.compiler.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Native verified-V2 hard ceilings are 4096 candidates, 256 mandatory groups, 4096 aggregate mandatory references, 4096 cumulative revoked admission ids, 1 MiB raw bytes per candidate/realization, 16 MiB aggregate realized bytes, 1,000,000 context tokens and 16 MiB final serialized payload. Exceeding a hard ceiling fails closed. Those ceilings are not target-host measurements; stricter product profiles may lower them. Current native limits belong to [codex-rs/hepta-context-compiler/src/lib.rs](../../../codex-rs/hepta-context-compiler/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Stateless context compiler, embedded before the physical App Server request. The verified V2 path reserves mandatory groups, binds their canonical provenance, rejects insufficient candidate or final serialized budgets, validates the exact selected bytes used for realization, tokenizes the actual final payload, revalidates current admission/revocation at attachment and again when creating the pre-dispatch safety witness, and validates canonical provider invocation/terminal evidence after the runtime owner performs the request. A compilation, attachment or preparation receipt alone is not a provider-send receipt. Production qualification must prove that the runtime/provider owner consumes current final-use authority, carries the exact payload into its provider binding, derives the provider-owned exact-attempt witness under the real provider policy, and lets the independent delivery verifier authenticate that witness against the current preparation plus persisted provider observation.

Current operating and state-format references:

- [codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md](../../../codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-context-compiler/src/v2_tests.rs](../../../codex-rs/hepta-context-compiler/src/v2_tests.rs); cases cover verifier rejection of otherwise well-formed admission records, scope/authority-domain binding, cumulative revocation no-resurrection, revocation/mandatory/raw-byte ceiling rejection, role-binding confusion, compile-to-attach revocation TOCTOU, actual realization-byte mismatch, exact final-payload tokenization including framing overhead, mandatory-group provenance binding, transport payload mismatch, and revocation after attachment but before delivery.
- [codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs](../../../codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs); compatibility case: `omitted_content_is_bound_without_changing_legacy_compilation`.
- [codex-rs/hepta-context-compiler/src/lib_tests.rs](../../../codex-rs/hepta-context-compiler/src/lib_tests.rs); compatibility case: `evidence_never_becomes_instruction`.

In `codex-rs`, run `just test -p codex-hepta-context-compiler`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/context.compiler.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `CTX-1-CONTEXT-COMPILER`

The bootstrap package is `CTX-1-CONTEXT-COMPILER`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. For the verified V2 path this includes verifier-produced typed admission evidence, scope/authority-domain-bound complete cumulative revocation snapshots with no-resurrection successor checks, bounded mandatory/revocation/raw-byte inputs, canonical mandatory-group provenance, selected-byte realization checks, final-payload exact tokenization, attach/pre-dispatch revocation checks, an opaque dispatch witness, canonical producer admission on the compatibility wire surface and canonical provider-invocation evidence validation. Product caller composition, authoritative admission-verifier qualification, exact tokenizer/serializer qualification, runtime provider-owner authority wiring, provider-owned attempt-witness/preparation verification, independent provider-evidence verification, independent acceptance, activation and release remain separate evidence gates.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `context.compiler`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `CTX-1-CONTEXT-COMPILER`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-context-compiler/**`
- Development predecessors:
- `OBJ-1-OBJECTIVE-COMPILER`
- `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`
- `INT-1-CALIBRATED-INTUITION-POLICY`
- Activation predecessors:
- `OBJ-1-OBJECTIVE-COMPILER`
- `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`
- `INT-1-CALIBRATED-INTUITION-POLICY`
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

The canonical readiness overlay binds `context.compiler` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `context.compiler` is implemented by work package `CTX-1-CONTEXT-COMPILER` in:

- `codex-rs/hepta-context-compiler`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
