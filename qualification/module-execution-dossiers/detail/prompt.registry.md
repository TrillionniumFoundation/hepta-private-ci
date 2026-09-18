# prompt.registry: implementation design

Parent: `docs/modules/prompt.registry/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: durable single-writer registry source, authenticated admission, immutable lifecycle lineage, exact-profile payload realization and read-only optimizer consumption are implemented; product/runtime composition and independent acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-prompt-registry`.
Packages: `PIM-0-PROMPT-INTERVENTION-CONTRACTS`, `PIM-1-PROMPT-FACTOR-REGISTRY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`admit_factor(factor, reviewed_scope) -> FactorRevision`; `register_realization(factor_revision, model_profile, payload_digest) -> RealizationRevision`; `revoke_factor(id, reason, cutoff) -> LifecycleReceipt`; `read_compatible(snapshot, model_tuple, context_profile) -> FactorSet`. Factor semantics and model-specific realization text are separate identities. External content must undergo governed admission before becoming an instruction factor.

## 3. State records and transaction design

`prompt_factor_registry` stores semantic factor ID, supported task classes, provenance and revision. `prompt_realization_registry` binds model/version/tokenizer/template/tool schema, locale, role, payload digest, token cost and expiry. `prompt_factor_lifecycle` stores proposed/admitted/revoked/retired transitions and supersession. Registry append and lifecycle publication are atomic for one owner revision; optimizer access is read-only.

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

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

KG holds rebuildable factor interactions; learning.ledger owns causal exposure/outcome, not this registry. Rollback may choose a compatible non-revoked predecessor, but never restore an old lifecycle snapshot before a revocation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `PromptRegistry` in [codex-rs/hepta-prompt-registry/src/registry.rs](../../../codex-rs/hepta-prompt-registry/src/registry.rs); `admit_factor_authorized` in [codex-rs/hepta-prompt-registry/src/registry_mutation.rs](../../../codex-rs/hepta-prompt-registry/src/registry_mutation.rs); `DurablePromptRegistry` in [codex-rs/hepta-prompt-registry/src/store.rs](../../../codex-rs/hepta-prompt-registry/src/store.rs); `register_realization_v2` in [codex-rs/hepta-prompt-registry/src/v2_registry.rs](../../../codex-rs/hepta-prompt-registry/src/v2_registry.rs); `read_compatible_v2` in [codex-rs/hepta-prompt-registry/src/v2_registry.rs](../../../codex-rs/hepta-prompt-registry/src/v2_registry.rs); `resolve_payload_v2` in [codex-rs/hepta-prompt-registry/src/v2_registry.rs](../../../codex-rs/hepta-prompt-registry/src/v2_registry.rs).
- **Durable state owner:** [`store.rs`](../../../codex-rs/hepta-prompt-registry/src/store.rs) provides a single-writer durable adapter with reopen validation, deterministic V0-to-V1 migration, current/temporary/backup interrupted-write recovery and a persisted-generation fence that rejects stale writers.
- **Realization and delivery source:** [`v2_registry.rs`](../../../codex-rs/hepta-prompt-registry/src/v2_registry.rs) registers bounded payload bytes, enforces exact-profile active uniqueness and predecessor supersession, reserves required factors before result truncation, canonicalizes filter order and resolves bytes only after snapshot/profile/lifecycle/expiry/digest revalidation. `context_profile_digest` is part of the V2 model tuple and realization identity.
- **Protocol surface:** [`protocol.rs`](../../../codex-rs/hepta-prompt-registry/src/protocol.rs) implements canonical `PromptFactorV1` and `PromptRealizationV1` JSON codecs with unknown-field rejection and canonical re-encoding checks, plus the durable registry state codec.
- **Read-only consumer:** [`hepta-prompt-optimizer/src/registry_source.rs`](../../../codex-rs/hepta-prompt-optimizer/src/registry_source.rs) consumes one frozen registry snapshot and maps compatible registered realizations into optimizer candidates. This is source composition, not production runtime activation.
- **Delivery-chain evidence:** [`integration_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/integration_tests.rs) binds registry-resolved payload bytes through context compilation, serialization, attachment and terminal delivery-observation digests. It does not prove a real provider/model consumed the payload.
- **Focused source tests:** [`lib_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/lib_tests.rs), [`v2_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/v2_tests.rs), [`protocol_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/protocol_tests.rs), [`store_tests.rs`](../../../codex-rs/hepta-prompt-registry/src/store_tests.rs) and the optimizer registry-source tests. Test paths are identities, not pass receipts.
- **Remaining repository/product work:** compose a named product/runtime caller across the registered `intelligence.control -> prompt.optimizer -> context.compiler` path and obtain current exact-candidate execution evidence. Production writer binding, real model/provider terminal observation, independent semantic review, operator acceptance, activation, promotion and release remain separate gates.
