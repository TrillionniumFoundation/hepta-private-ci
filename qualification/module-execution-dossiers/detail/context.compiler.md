# context.compiler: implementation design

Parent: `docs/modules/context.compiler/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: verified V2 source closure implemented for typed current admission, attach-time revalidation, exact final-payload tokenization/realization and provider/transport evidence; product composition, target-host qualification and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-context-compiler`.
Packages: `CTX-1-CONTEXT-COMPILER`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compile_context(objective, validated_evidence, prompt_portfolio, model_profile, budget) -> ContextCompilationReceiptV1`; `revalidate_attachment(receipt, current_snapshot) -> ContextAttachment | Stale`. The compilation result binds actual payload/tokenizer/template/tool-schema digests, placement, truncation, source revisions and cost. Compilation alone is not delivery; the Codex consumer emits a separate observation.

## 3. State records and transaction design

No authoritative store or model-call handle. The local compilation object contains immutable references to selected evidence and admitted prompt realizations, plus bounded structured payload and omission metadata. Raw assets are attached only through the owner-approved redaction/purpose gate. Cache keys include every source and model/template generation and current revocation cutoff.

## 4. Deterministic algorithm and scheduling

Reserve non-tradable instruction/schema/evidence floors; revalidate sources in a coherent snapshot; tokenize with the exact tokenizer; select the bounded portfolio order; pack evidence using deterministic value-per-cost with stable ties while preserving mandatory provenance/contradiction groups; stop before exceeding the budget; emit omitted-count and uncertainty. If mandatory floors cannot fit, return insufficient_context/abstain rather than truncate authority or fabricate citations. Record the heuristic and lack of global optimality.

## 5. Capacity and performance profile

Pilot <=128 prompt factors, <=512 evidence candidates, bounded media spans and total tokens from the exact model profile. At most one tokenizer pass per immutable segment plus bounded composition overhead. Measure final token count, truncation, placement, allocations and p99 compilation.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- CTX-01: external evidence cannot occupy a trusted instruction role without registry admission.
- CTX-02: a tiny context budget preserves mandatory fields or explicitly refuses compilation.
- CTX-03: changed source/tombstone/model tuple invalidates a cached compilation.
- CTX-04: final delivered payload digest equals the compilation digest; a delivery mismatch receives no causal factor credit.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Native Codex attachment is the consumer contract; no direct provider path. C1 tests stale citation and contradiction preservation under maximum context pressure. Rollback restores compatible profiles and invalidates caches instead of reusing a stale compiled prompt.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Normative verified V2 entrypoints:** `compile_verified_v2`, `record_verified_serialization_v2`, `build_revalidated_attachment_v2`, and `observe_verified_delivery_v2` in [codex-rs/hepta-context-compiler/src/verified.rs](../../../codex-rs/hepta-context-compiler/src/verified.rs). They require injected current admission/revocation owner verification, actual serialized bytes with exact segment realization, exact final tokenizer accounting, and provider/transport evidence.\n- **Compatibility entrypoints:** `compile`, `compile_with_requirements`, `compile_candidate_bound`, plus the weaker legacy V2 helper chain remain available for existing callers but are not the normative security proof path.
- **State and recovery:** Stateless compilation separates trusted instructions from untrusted evidence and binds objective/snapshot/items. Explicit mandatory groups validate exact items before budget selection and cannot be silently omitted.
- **Source tests:** [codex-rs/hepta-context-compiler/src/verified_tests.rs](../../../codex-rs/hepta-context-compiler/src/verified_tests.rs), [codex-rs/hepta-context-compiler/src/v2_tests.rs](../../../codex-rs/hepta-context-compiler/src/v2_tests.rs), [codex-rs/hepta-context-compiler/src/requirements_tests.rs](../../../codex-rs/hepta-context-compiler/src/requirements_tests.rs), [codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs](../../../codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md](../../../codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work:** Compose real admission/revocation owner adapters, the selected exact tokenizer implementation and the real runtime.codex/provider transport evidence adapter in the named product caller; then qualify exact-head/merge-candidate behavior and target-host delivery. The legacy helper chain must be retired after all callers migrate.
