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

The registered primary source is [codex-rs/hepta-context-compiler/src/lib.rs](../../../codex-rs/hepta-context-compiler/src/lib.rs). V1 compatibility surfaces include `CompilationRequest`, `ContextCompilationReceipt`, `CompilationRequirementsV1`, `compile`, `compile_candidate_bound` and `compile_with_requirements`. The normative verified V2 surface is implemented in [src/v2.rs](../../../codex-rs/hepta-context-compiler/src/v2.rs) and includes `verify_admission_snapshot_v2`, `verify_admission_v2`, `compile_v2`, `record_serialization`, `build_attachment`, `deliver_context_v2`, typed admission snapshots/evidence, exact-tokenizer and serializer adapters, and transport-bound delivery receipts. Source presence still does not prove product composition, independent qualification or provider execution. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/context.compiler.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/context.compiler.md).

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
- `transport invocation and terminal delivery receipt emitter`
- `digest and receipt emitter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Normative verified V2 execution path

The V2 source path is deliberately stronger than a digest-only receipt chain:

1. `ContextAdmissionSnapshotV2` is authenticated by a `ContextAdmissionVerifierV2`, producing a non-forgeable-by-struct-literal `VerifiedAdmissionSnapshotV2`.
2. Every candidate, including evidence, carries `VerifiedAdmissionV2` bound to item id, role, content/source/generation digests, verifier identity, expiry and the snapshot/revocation epoch at which it was verified. A trusted instruction is not represented by a caller-supplied admission digest.
3. `TokenizationReceiptV2::from_exact_bytes` invokes an `ExactTokenizerV2` over actual candidate bytes and binds the tokenizer identity from the exact model profile.
4. `compile_v2` requires one admission-verifier digest for the request, preserves non-tradable trusted/schema floors, canonicalizes mandatory groups and includes `mandatory_groups_digest` in the compilation receipt.
5. `record_serialization` consumes the actual selected item bytes, verifies every byte sequence against the selected content digest, invokes the profile-bound serializer, hashes the resulting final payload and then invokes the exact tokenizer over those final payload bytes. Final framing/tool/template overhead therefore counts against the real token budget.
6. `build_attachment` requires a freshly verified admission snapshot and rechecks every selected admission for verifier identity, monotonic snapshot/epoch, expiry and revocation before attachment.
7. `deliver_context_v2` revalidates again immediately before send, passes the exact serialized payload bytes to a `ContextTransportV2`, requires the transport to report the digest of the bytes it transmitted, and emits `ContextDeliveryReceiptV2` binding transport identity, provider request id, acknowledgement digest, terminal disposition, observed time, and the exact verified admission snapshot/revocation epoch used at send time. `ContextCompilationReceiptV2`, `CompiledContextV2`, `SerializedContextV2`, `ContextSerializationReceiptV2`, `ContextAttachmentV2` and `ContextDeliveryReceiptV2` are construction-closed outside this module; callers receive read-only accessors and cannot bypass `compile_v2`, exact serialization/tokenization, revocation revalidation or delivery by synthesizing proof structs. A `Delivered` receipt additionally requires the provider/transport acknowledgement to identify the same payload digest that was actually transmitted.

The verifier, serializer, tokenizer and transport implementations are explicit trusted adapters. Their digest identities are evidence inputs, not authority grants. A malicious or incorrectly configured adapter is outside the compiler's pure-algorithm proof and must be qualified by the owning integration. V1 APIs remain compatibility source surfaces and do not satisfy this V2 proof chain.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ContextCompilationReceiptV1` (compatibility surface)
- `ContextCompilationReceiptV2`
- `ContextSerializationReceiptV2`
- `ContextAttachmentV2`
- `ContextDeliveryReceiptV2`
- `ModulePort::context.compiler::intelligence.control`

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

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/context.compiler.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-context-compiler/src/lib.rs](../../../codex-rs/hepta-context-compiler/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Stateless context compiler, embedded before the physical App Server request. The verified V2 path reserves mandatory groups, binds their canonical provenance, rejects insufficient candidate or final serialized budgets, validates the exact selected bytes used for realization, tokenizes the actual final payload, revalidates current admission/revocation at attachment and immediately before send, and emits a transport/provider-evidence-bound delivery receipt. A compilation receipt alone is still not a provider send receipt; only the delivery stage invokes a transport adapter, and production qualification must independently establish that adapter's provider semantics.

Current operating and state-format references:

- [codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md](../../../codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-context-compiler/src/v2_tests.rs](../../../codex-rs/hepta-context-compiler/src/v2_tests.rs); cases cover verifier rejection of otherwise well-formed admission records, role-binding confusion, compile-to-attach revocation TOCTOU, actual realization-byte mismatch, exact final-payload tokenization including framing overhead, mandatory-group provenance binding, transport payload mismatch, and revocation after attachment but before delivery.
- [codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs](../../../codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs); compatibility case: `omitted_content_is_bound_without_changing_legacy_compilation`.
- [codex-rs/hepta-context-compiler/src/lib_tests.rs](../../../codex-rs/hepta-context-compiler/src/lib_tests.rs); compatibility case: `evidence_never_becomes_instruction`.

In `codex-rs`, run `just test -p codex-hepta-context-compiler`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/context.compiler.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `CTX-1-CONTEXT-COMPILER`

The bootstrap package is `CTX-1-CONTEXT-COMPILER`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. For the verified V2 path this includes authenticated admission evidence, canonical mandatory-group provenance, selected-byte realization checks, final-payload exact tokenization, attach/send-time revocation checks and transport-bound delivery receipts. Product caller composition, concrete admission/tokenizer/serializer/transport adapter qualification, independent acceptance, activation and release remain separate evidence gates.

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
