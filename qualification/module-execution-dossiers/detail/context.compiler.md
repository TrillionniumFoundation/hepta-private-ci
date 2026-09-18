# context.compiler: implementation design

Parent: `docs/modules/context.compiler/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: proof-closed V2.1 source API plus V1 compatibility paths implemented; real host composition, authenticated external witnesses/adapters and independent acceptance remain listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-context-compiler`.
Packages: `CTX-1-CONTEXT-COMPILER`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`verify_admission_snapshot_v2(raw_snapshot_evidence, admission_verifier) -> ContextAdmissionSnapshotV2`; `compile_v2(request_with_typed_admission_snapshot) -> CompiledContextV2`; `serialize_context_v2(compiled, actual_selected_bytes, serializer, exact_tokenizer) -> SerializedContextV2`; `build_attachment(compiled, serialized, current_admission_snapshot) -> ContextAttachmentV2 | Stale`; `deliver_attachment(attachment, delivery_adapter) -> ContextDeliveryReceiptV2`. The V2.1 path binds typed admission evidence, exact candidate and final-payload tokenization, mandatory-group provenance, current attachment-time revocation state and provider-attempt acknowledgement evidence. V1 operations remain compatibility-only. Compilation alone is not serialization, attachment or delivery.

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

- **Normative V2.1 source entrypoints:** `compile_v2`, `serialize_context_v2`, `build_attachment` and `deliver_attachment` are implemented in [codex-rs/hepta-context-compiler/src/proof_v2.rs](../../../codex-rs/hepta-context-compiler/src/proof_v2.rs). `lib.rs` exports these as the public V2 surface and retains the prior V2 implementation privately as the deterministic selection engine.
- **Admission and revalidation:** raw `ContextAdmissionSnapshotEvidenceV2` must pass a host-owned `ContextAdmissionVerifierV2` before the private-field `ContextAdmissionSnapshotV2` can be constructed. Trusted instruction/schema candidates consume `VerifiedContextAdmissionV2` from that authenticated snapshot; source/content/role/expiry/revocation are checked at compilation and every selected candidate is checked again against a current authenticated snapshot immediately before attachment. Snapshot issuer/frontier/witness/verifier/verification/time are bound into public receipts.
- **Exact bytes and tokenizer:** the public candidate token receipt is measured over actual bytes via `ExactContextTokenizerV2`. Serialization receives actual selected bytes, verifies content digests, constructs the actual final payload via `ContextSerializerV2`, and retokenizes those final bytes before accepting the provider-facing budget.
- **Delivery evidence:** `deliver_attachment` passes the exact attachment payload bytes to `ContextDeliveryAdapterV2`; `Delivered` requires terminal transport evidence, matching payload digest, provider request ID and provider acknowledgement digest.
- **Mandatory provenance:** canonical group ID/member/reason semantics are bound into `mandatory_groups_digest`, so policy drift changes the compilation receipt even when selected IDs are unchanged.
- **V1 compatibility entrypoints:** `compile`, `compile_with_requirements`, `compile_candidate_bound` and `compile_candidate_bound_with_requirements` remain source-compatible but do not imply V2.1 proof guarantees.
- **Source tests:** [codex-rs/hepta-context-compiler/src/proof_v2_tests.rs](../../../codex-rs/hepta-context-compiler/src/proof_v2_tests.rs) covers admission binding drift, revocation at compilation and attachment, exact final-payload tokenization, content substitution, mandatory provenance, provider acknowledgement and delivery mismatch. Existing V1 and private-selection tests remain regression tests. These are test identities, not exact-head execution receipts.
- **Implementation references:** [docs/modules/context.compiler/V2_TECHNICAL.md](../../../docs/modules/context.compiler/V2_TECHNICAL.md), [codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md](../../../codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work / claim boundary:** a product host must implement `ContextAdmissionVerifierV2` against the actual admission/latest-head authority and compose real exact-tokenizer, serializer and provider-delivery adapters with durable attempt correlation. Source-level typed proof seams do not themselves prove product execution, latest-head external authenticity, independent acceptance, activation, promotion or release.
