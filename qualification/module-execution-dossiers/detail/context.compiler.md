# context.compiler: implementation design

Parent: `docs/modules/context.compiler/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: verified V2 admission, exact final-payload tokenization, attach/send-time revocation revalidation, canonical mandatory-group provenance and transport-bound delivery receipts are implemented in native source. Production caller composition, concrete adapter qualification and independent acceptance remain separate and are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-context-compiler`.
Packages: `CTX-1-CONTEXT-COMPILER`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

Normative V2 native flow: `verify_admission_snapshot_v2(snapshot, verifier) -> VerifiedAdmissionSnapshotV2`; `verify_admission_v2(record, verified_snapshot, verifier) -> VerifiedAdmissionV2`; `compile_v2(request) -> CompiledContextV2`; `record_serialization(compiled, model_profile, realizations, serializer, tokenizer) -> SerializedContextV2`; `build_attachment(compiled, serialization, model_profile, current_snapshot) -> ContextAttachmentV2`; `deliver_context_v2(compiled, serialization, attachment, model_profile, current_snapshot, transport) -> ContextDeliveryReceiptV2`. The compilation receipt binds candidate/admission/model/group/truncation provenance. Serialization binds actual selected bytes, final payload bytes and exact tokenizer count. Attachment and delivery each revalidate current admission/revocation state. Delivery invokes the transport adapter with the exact payload and binds provider-request and acknowledgement evidence. V1 compilation entrypoints remain compatibility surfaces; compilation alone is never physical delivery.

## 3. State records and transaction design

No authoritative store or model-call handle. `VerifiedAdmissionV2` is produced only through the verifier boundary and binds item id, role, content/source/generation digests, verifier identity, expiry and the snapshot/revocation epoch at verification. `SerializedContextV2` contains the actual final payload bytes plus a receipt binding the realization manifest, serializer/template/tool-schema identity and exact tokenizer result. `ContextAttachmentV2` binds the current verified admission snapshot used for attachment. `ContextDeliveryReceiptV2` binds the transport identity, exact transmitted payload digest, provider request id, acknowledgement digest and terminal observation. Raw assets are realized only after digest/admission checks; no receipt grants authority to call a provider outside the explicit transport adapter boundary.

## 4. Deterministic algorithm and scheduling

Verify the admission snapshot and every admission record through one request-bound verifier identity; reserve non-tradable instruction/schema/evidence floors; canonicalize and digest mandatory groups; select optional evidence by deterministic value-per-token with stable ties; stop before the candidate budget is exceeded. Then verify the actual bytes for every selected item, serialize them through the exact profile-bound serializer, run the exact tokenizer over the final serialized payload bytes, and fail closed if framing/template/tool overhead exceeds the token budget. Revalidate current admission/revocation state at attachment and immediately before transport send. If mandatory floors cannot fit, any realized bytes drift, current revocation is newer, or the transmitted payload digest differs, refuse rather than truncate authority or fabricate delivery. Record the heuristic and lack of global optimality.

## 5. Capacity and performance profile

Pilot <=128 prompt factors, <=512 evidence candidates, bounded media spans and total tokens from the exact model profile. At most one tokenizer pass per immutable segment plus bounded composition overhead. Measure final token count, truncation, placement, allocations and p99 compilation.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- CTX-01: a well-formed admission record is insufficient unless the configured verifier accepts it, and role/content/source/generation bindings cannot be rewritten after verification.
- CTX-02: a tiny context budget preserves mandatory fields or explicitly refuses compilation; final serializer framing overhead is also checked against the real token budget.
- CTX-03: compile-to-attach and attach-to-send revocation changes fail closed against a newer verified snapshot.
- CTX-04: actual selected bytes must match compiled content digests, the final payload is tokenized after serialization, and a transport claiming a different transmitted payload digest cannot receive a delivered receipt.
- CTX-05: canonical mandatory-group definitions are digest-bound even when two policies happen to select the same item set.
- CTX-06: a delivered receipt requires terminal provider/transport acknowledgement evidence bound to the exact payload and transport identity.

Native unit tests exercise these source-level oracles. Product execution, concrete adapter authenticity and independent target-host evidence remain separate qualification requirements.

## 7. Integration, rollback and capability ceiling

Native Codex attachment is the consumer contract; no direct provider path. C1 tests stale citation and contradiction preservation under maximum context pressure. Rollback restores compatible profiles and invalidates caches instead of reusing a stale compiled prompt.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Normative V2 entrypoints:** `verify_admission_snapshot_v2`, `verify_admission_v2`, `compile_v2`, `record_serialization`, `build_attachment` and `deliver_context_v2` in [codex-rs/hepta-context-compiler/src/v2.rs](../../../codex-rs/hepta-context-compiler/src/v2.rs). V2 requires verifier-produced typed admission evidence for every candidate, exact-byte tokenization receipts, canonical mandatory-group provenance, selected-byte realization checks, final-payload exact tokenization, attachment/send-time revocation revalidation, and a transport-invoked delivery receipt. Compilation, serialization, attachment and delivery proof artifacts are construction-closed to external callers, so the verified V2 path cannot be skipped by synthesizing receipts. The delivery receipt additionally binds the verified admission snapshot and revocation epoch used immediately before transport send and, for `Delivered`, requires provider/transport acknowledgement of the exact transmitted payload digest.
- **Compatibility entrypoints:** `compile` in [src/lib.rs](../../../codex-rs/hepta-context-compiler/src/lib.rs), `compile_with_requirements` in [src/requirements.rs](../../../codex-rs/hepta-context-compiler/src/requirements.rs), and `compile_candidate_bound` in [src/candidate_bound.rs](../../../codex-rs/hepta-context-compiler/src/candidate_bound.rs). These preserve earlier source consumers but are not the normative V2 proof chain.
- **State and recovery:** The compiler remains stateless. Authenticity and current revocation are represented by verified snapshots/evidence supplied through the admission verifier boundary. Serialization and delivery retain actual payload bytes only in the caller-owned in-memory object; receipts retain digests, counts and adapter/provider evidence. Any stale/expired/revoked admission, realization drift, final token overflow or transmitted-payload mismatch fails closed.
- **Trusted adapter boundary:** `ContextAdmissionVerifierV2`, `ExactTokenizerV2`, `ContextSerializerV2` and `ContextTransportV2` are explicit integration trust seams. Their identities are digest-bound into the request/receipts, but this library does not independently prove a malicious adapter honest. Product qualification must bind concrete implementations to the authoritative admission service, exact provider tokenizer/template/tool schema and transport acknowledgement semantics.
- **Source tests:** [src/v2_tests.rs](../../../codex-rs/hepta-context-compiler/src/v2_tests.rs), [src/requirements_tests.rs](../../../codex-rs/hepta-context-compiler/src/requirements_tests.rs), and [src/candidate_bound_tests.rs](../../../codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs). V2 tests cover verifier rejection, role binding, revocation TOCTOU, mandatory-group provenance, realization-byte drift, exact final token counts, serializer overhead overflow, transport payload mismatch and revocation after attachment.
- **Implementation and operating references:** [codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md](../../../codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md), [docs/modules/context.compiler/TECHNICAL.md](../../../docs/modules/context.compiler/TECHNICAL.md), and [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md).
- **Remaining work:** Compose and qualify the concrete product caller plus authenticated admission verifier, exact provider tokenizer/serializer and transport adapter; collect exact-head/synthetic-merge and independent target-host evidence; then separately perform activation, operator acceptance, promotion and release. A source-level delivery receipt proves what the selected transport adapter reported after receiving the exact payload bytes, not independent provider truth absent adapter qualification.
