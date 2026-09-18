# context.compiler: implementation design

Parent: docs/modules/context.compiler/TECHNICAL.md. Lane: LANE-C-MEMORY.
Status: the V2 source candidate implements an admission-verified,
exact-serialization, current-revalidation and provider-evidence proof chain.
Product composition, target-host qualification and independent acceptance remain
separate gates. Common requirements: ../EXECUTION_SEMANTICS.md and
../TECHNICAL.md. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: codex-rs/hepta-context-compiler.
Package: CTX-1-CONTEXT-COMPILER.

The module remains stateless for authoritative domain facts. It owns no
admission store, revocation store, tokenizer registry, provider socket, provider
credentials or external-effect authority. It consumes owner-supplied verified
adapters and emits deny-all receipts.

V2 is normative for new integrations. V1 entrypoints remain compatibility-only
and retain their historical semantics.

## 2. Public operations and contract details

Implemented V2 operations are:

- verify_context_candidate_v2(draft, bytes, admission_snapshot, tokenizer, time)
  -> opaque ContextCandidateV2;
- compile_v2(request) -> opaque CompiledContextV2;
- serialize_context_exact(compiled, id, materialized_items, serializer,
  tokenizer, time) -> opaque SerializedContextV2;
- build_attachment(compiled, serialized, id, current_admission_snapshot,
  tokenizer, time) -> opaque ContextAttachmentV2;
- observe_delivery(attachment, id, provider_receipt,
  independent_delivery_verifier, time) -> ContextDeliveryReceiptV2.

Compatibility operations remain compile, compile_with_requirements,
compile_candidate_bound and compile_candidate_bound_with_requirements.

The V2 chain is:

admission verification
-> exact candidate tokenization
-> deterministic compilation
-> exact byte materialization
-> registered serialization
-> exact final-payload tokenization
-> current admission/revocation revalidation
-> attachment
-> validated provider receipt
-> independent provider-delivery evidence
-> delivery receipt.

Compilation is never provider authority and a delivery receipt is never a
success/quality label for learning.

## 3. State records and transaction design

There is no authoritative context.compiler store.

ContextCandidateV2 is opaque outside the crate and contains a private
ContextAdmissionReceiptV2. The receipt binds item, role, content/source digest,
generation vector, admission verifier, admission snapshot, revocation frontier,
source admission, verification time and expiry.

ContextCompilationReceiptV2 additionally binds objective, prompt portfolio,
exact model profile, candidate set, canonical mandatory-group policy, selected
and omitted IDs, compilation budget/time and context digest.

ContextSerializationReceiptV2 binds the exact materialization, serializer,
template, tool schema, tokenizer, final payload digest, final payload token
count and serialization time.

ContextAttachmentV2 binds the current admission snapshot/revocation frontier,
provider/model profile, exact final payload and attachment time.

ContextDeliveryReceiptV2 binds provider request/attempt/terminal evidence and a
separate evidence-verifier result. All receipts are deny-all authority.

Raw context bytes exist only in the explicit candidate verification and
serialization/attachment objects. Debug output for raw materialization and
payload holders is digest/length-only.

## 4. Deterministic algorithm and scheduling

Candidate construction first verifies current admission and tokenizes exact
candidate bytes. compile_v2 then requires a coherent verifier/snapshot/frontier,
generation vector and tokenizer profile across the entire candidate set.

Trusted instructions and schemas are non-tradable floors. Canonically normalized
mandatory groups add indivisible evidence obligations. Their complete group
structure and reason digests are included in mandatory_groups_digest, so a
policy change invalidates the receipt even if the selected IDs do not change.

After mandatory reservation, optional evidence is sorted by deterministic
expected-value-per-token with stable item-ID ties. The heuristic makes no
global-optimality claim. Insufficient mandatory budget fails instead of silently
truncating trusted/schema/group content.

Per-item token counts are selection costs. They are not treated as the final
provider payload count. serialize_context_exact runs the exact tokenizer again
over the actual complete serialized payload and fails closed if framing,
separators, role wrappers or tokenizer-boundary effects push it over budget.

## 5. Admission, revocation and TOCTOU boundary

V2 no longer accepts an arbitrary trusted_admission_digest.

ContextAdmissionSnapshotVerifierV2 is the owner adapter responsible for
authenticating admission and revocation state. The candidate type is private to
the module construction path, so callers cannot populate an admission receipt
by assigning a digest field.

Compilation binds the exact admission snapshot/frontier used at compile time.

Attachment requires the same admission verifier trust anchor and re-runs
verification for every selected candidate against the current snapshot at the
attachment timestamp. The current snapshot/frontier may advance, but each
candidate must remain admitted and its source-admission digest must remain
consistent. Revocation, expiry, verifier replacement or admission drift rejects.

This closes the compile-to-attach stale-context window inside the module
contract. Production trust still depends on composing the verifier with the
authoritative admission/revocation owner; the module cannot authenticate a
malicious verifier implementation by hashing it.

## 6. Exact tokenizer, serialization and provider delivery

ContextModelProfileV2 binds model artifact, provider ID, provider model,
tokenizer, serializer, template, tool schema and maximum context tokens.

ExactContextTokenizerV2 receives the real candidate bytes during candidate
construction and the real final serialized bytes during serialization.
ContextSerializerV2 receives the exact selected materialized items and returns
the actual payload bytes. The serializer/template/tool-schema identities must
match the model profile.

observe_delivery does not accept caller booleans such as delivered=true. It
requires a valid codex-hepta-contracts ProviderInvocationReceipt whose
ephemeral_input_sha256 equals the exact attachment payload digest and whose
ephemeral-input witness is present. Provider ID and model must match the bound
model profile.

Because ProviderInvocationReceipt is itself constructible contract data,
ContextProviderDeliveryVerifierV2 is separately required. The intended product
adapter is kernel.evidence or another authenticated terminal-observer/evidence
owner. Its evidence digest, verifier identity and recorded time are included in
the delivery receipt.

Completed/CompletedUnary, Rejected, NotDispatched and Indeterminate remain
distinct. Indeterminate never aliases Delivered.

## 7. Capacity, failure semantics and verification cases

Current source ceilings are:

- maximum 4,096 candidates;
- maximum 256 mandatory groups;
- maximum 1,000,000 context tokens;
- maximum 4 MiB per materialized item;
- maximum 16 MiB final serialized payload.

Representative source tests in src/v2_tests.rs cover:

- candidate admission is required before opaque candidate creation;
- a candidate from another admission snapshot fails compilation;
- mandatory instructions/schemas refuse insufficient budgets;
- changing mandatory-group reason changes receipt provenance even with the same
  selection;
- serializer framing that makes the final payload exceed budget fails after
  actual final-payload tokenization;
- materialized byte drift from the admitted content digest fails;
- revocation between compile and attach fails;
- a still-valid candidate may attach under a newer current snapshot/frontier;
- provider payload mismatch and provider/model mismatch fail;
- missing independent delivery evidence fails;
- provider indeterminate remains indeterminate;
- Debug output does not emit raw payload text.

CTX-01 through CTX-06 are therefore represented by native V2 source mechanisms,
but product acceptance still requires the named production adapters, product
caller, exact-candidate runs and independent evidence.

## 8. Current native implementation

- **Implemented entrypoints:** verify_context_candidate_v2 in [codex-rs/hepta-context-compiler/src/v2.rs](../../../codex-rs/hepta-context-compiler/src/v2.rs); compile_v2 in [codex-rs/hepta-context-compiler/src/v2.rs](../../../codex-rs/hepta-context-compiler/src/v2.rs); serialize_context_exact in [codex-rs/hepta-context-compiler/src/v2.rs](../../../codex-rs/hepta-context-compiler/src/v2.rs); build_attachment in [codex-rs/hepta-context-compiler/src/v2.rs](../../../codex-rs/hepta-context-compiler/src/v2.rs); observe_delivery in [codex-rs/hepta-context-compiler/src/v2.rs](../../../codex-rs/hepta-context-compiler/src/v2.rs); compile in [codex-rs/hepta-context-compiler/src/lib.rs](../../../codex-rs/hepta-context-compiler/src/lib.rs); compile_with_requirements in [codex-rs/hepta-context-compiler/src/requirements.rs](../../../codex-rs/hepta-context-compiler/src/requirements.rs); compile_candidate_bound in [codex-rs/hepta-context-compiler/src/candidate_bound.rs](../../../codex-rs/hepta-context-compiler/src/candidate_bound.rs).
- **State and recovery:** no authoritative store. V2 receipts bind verified admission, exact model/serializer/tokenizer identity, canonical mandatory policy, final payload, current attachment snapshot/frontier and provider evidence. Recovery/retry responsibility stays with the owning admission/evidence/provider adapters.
- **Source tests:** [codex-rs/hepta-context-compiler/src/v2_tests.rs](../../../codex-rs/hepta-context-compiler/src/v2_tests.rs), [codex-rs/hepta-context-compiler/src/requirements_tests.rs](../../../codex-rs/hepta-context-compiler/src/requirements_tests.rs), [codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs](../../../codex-rs/hepta-context-compiler/src/candidate_bound_tests.rs). These are test identities, not independent acceptance receipts.
- **Implementation and operating references:** [codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md](../../../codex-rs/hepta-context-compiler/MANDATORY_CONTEXT.md), [docs/modules/context.compiler/TECHNICAL.md](../../../docs/modules/context.compiler/TECHNICAL.md).
- **Remaining work:** compose a named product caller with the authoritative admission/revocation adapter, qualified exact tokenizer and registered serializer; back ContextProviderDeliveryVerifierV2 with kernel.evidence or another authenticated terminal observer; run exact-head and deterministic merge-candidate qualification; collect target-host resource measurements and independent semantic/security acceptance. None of these remaining gates may be inferred from source presence or unit tests.
