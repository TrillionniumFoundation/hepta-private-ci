# prompt.registry: implementation design

Parent: `docs/modules/prompt.registry/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: durable factor/realization ownership, signed admission, immutable lifecycle lineage, exact context-profile lookup and payload-backed source composition are implemented; runtime host activation, terminal model-delivery evidence and independent acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-prompt-registry`.
Packages: `PIM-0-PROMPT-INTERVENTION-CONTRACTS`, `PIM-1-PROMPT-FACTOR-REGISTRY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`verify_admission(signed_grant, factor, reviewed_scope, now) -> VerifiedAdmission`; `admit_factor_verified(verified, now) -> FactorRevision`; `register_realization_payload_v2(binding, payload, supersedes) -> RealizationRevision`; `revoke_factor(id, actor, reason, cutoff) -> LifecycleReceipt`; `read_compatible(snapshot, model_tuple, required_factors) -> FactorSet`; `dereference_realization(snapshot, realization, model_tuple, now) -> RealizationDelivery`. Factor semantics and model-specific realization bytes are separate identities. External content must undergo governed admission before becoming an instruction factor.

## 3. State records and transaction design

`prompt_factor_registry` stores semantic factor identity and revision state. `prompt_realization_registry` binds model/tokenizer/template/tool schema/context profile, locale, role, payload digest, bounded payload bytes, token cost, expiry and explicit realization supersession. `prompt_factor_lifecycle` is an append-only lineage journal for registration/admission/retirement/revocation/import events, including reviewer/grant/evidence/scope or reason/cutoff where applicable. `DurablePromptRegistry` serializes one writer, clones the deterministic core, persists the next state with file and directory fsync, and publishes only after the durable rename succeeds. Optimizer access is read-only.

## 4. Deterministic algorithm and scheduling

Validate source trust and owner authorization; dedupe semantic factors without merging incompatible realizations; validate model/template compatibility and payload bounds; append immutable revisions; publish lifecycle. Readers freeze one registry generation and reject expired or revoked realizations at delivery revalidation. No registry insertion automatically selects a factor in a running request.

## 5. Capacity and performance profile

Pilot candidate read <=128 factors, realization payload <=64 KiB subject to model-context limits, support references <=64 per factor. Count tokenizer cost under the exact selected tokenizer rather than character length. Measure lookup, lifecycle propagation and model-version fanout.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- PREG-01: same factor with incompatible tokenizer/template is not delivered by implicit fallback.
- PREG-02: untrusted page text cannot self-register as system instruction.
- PREG-03: revocation between optimization and delivery invalidates the selected realization.
- PREG-04: duplicate revision semantics are idempotent; changed payload under the same identity conflicts.
- PREG-05: two required factors remain represented when another factor has multiple compatible roles and the result cap equals the number of required factors.
- PREG-06: restart after revocation preserves terminal lifecycle, payload lineage and revocation frontier; a pre-revocation snapshot remains stale.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

KG holds rebuildable factor interactions; learning.ledger owns causal exposure/outcome, not this registry. Rollback may choose a compatible non-revoked predecessor, but never restore an old lifecycle snapshot before a revocation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `PromptRegistry` in [codex-rs/hepta-prompt-registry/src/lib.rs](../../../codex-rs/hepta-prompt-registry/src/lib.rs); `AdmissionAuthority::verify` in [codex-rs/hepta-prompt-registry/src/admission.rs](../../../codex-rs/hepta-prompt-registry/src/admission.rs); `DurablePromptRegistry` in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs); `register_realization_payload_v2` and `dereference_realization_v2` in [codex-rs/hepta-prompt-registry/src/delivery.rs](../../../codex-rs/hepta-prompt-registry/src/delivery.rs); `read_compatible_v2` in [codex-rs/hepta-prompt-registry/src/v2.rs](../../../codex-rs/hepta-prompt-registry/src/v2.rs); canonical V1 codecs in [codex-rs/hepta-prompt-registry/src/protocol.rs](../../../codex-rs/hepta-prompt-registry/src/protocol.rs).
- **Authenticated admission:** a signed grant binds signer, reviewer, factor ID and content digest, expected reviewed-scope digest, evidence digest and a short validity interval. Verification yields an opaque `VerifiedAdmission`; the mutation path rechecks expiry and journals grant/reviewer/scope/evidence lineage. The legacy unauthenticated mutation helpers are test-only.
- **State and recovery:** `PromptRegistry` remains the deterministic core. `DurablePromptRegistry` is the source-level authoritative writer, holds one writer lock, verifies state-file ownership/mode/link count, persists a schema-versioned owner image by fsync + atomic rename + directory fsync, reopens with relationship/event/registry-digest validation, and includes a deterministic v1 compatibility migration. Revocation and realization disablement survive reopen.
- **Realization delivery:** V2 bindings include context profile and exact model/tokenizer/template/tool-schema/locale/role identity. Authoritative registration requires actual payload bytes whose digest matches the binding. One active realization per exact factor/profile/role is enforced unless the new revision explicitly supersedes the active predecessor. Dereference revalidates snapshot, lifecycle, expiry, exact profile and payload digest.
- **Selection and canonicalization:** required-factor IDs are canonicalized before digesting; required factors receive one compatible realization before the remaining result budget is filled, preventing truncation starvation.
- **Source composition:** [codex-rs/hepta-intelligence/src/prompt_delivery.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery.rs) is a named source-level consumer. It dereferences the exact stored bytes, binds the admission-event digest and tokenizer receipt, and passes those candidates into `context.compiler::compile_v2`. This proves source composition, not running-product or provider delivery.
- **Source tests:** [codex-rs/hepta-prompt-registry/src/lib_tests.rs](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs), [codex-rs/hepta-prompt-registry/src/v2_tests.rs](../../../codex-rs/hepta-prompt-registry/src/v2_tests.rs), durable tests in [codex-rs/hepta-prompt-registry/src/durable.rs](../../../codex-rs/hepta-prompt-registry/src/durable.rs), codec tests in [codex-rs/hepta-prompt-registry/src/protocol.rs](../../../codex-rs/hepta-prompt-registry/src/protocol.rs), and cross-crate source-composition tests in [codex-rs/hepta-intelligence/src/prompt_delivery_tests.rs](../../../codex-rs/hepta-intelligence/src/prompt_delivery_tests.rs). These remain test identities until exact-candidate CI supplies execution receipts.
- **Implementation and operating references:** [docs/modules/prompt.registry/TECHNICAL.md](../../../docs/modules/prompt.registry/TECHNICAL.md).
- **Remaining work:** bind the durable owner and source-composition bridge into an activated named runtime host; carry the selected bytes through context serialization/attachment and obtain terminal model/provider delivery observation; run target-host/fault/load qualification and independent semantic/operator acceptance. No source-only change can self-certify those gates.
