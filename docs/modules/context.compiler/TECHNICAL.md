# context.compiler technical development guide

**Plan:** HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN v8.0.0

**Module:** context.compiler

**Owner:** intelligence-platform

**Deputy:** security-authority

**Lifecycle:** target

**Source status:** existing_bound

**Bootstrap work package:** CTX-1-CONTEXT-COMPILER

This is the developer reference for the current context.compiler source. V2 is
the normative path for new integrations. V1 remains a compatibility surface.
This guide describes source behavior and trust boundaries; it does not claim
product composition, target-host qualification, independent acceptance,
activation, promotion, merge or release.

## 1. Mission and capability ceiling

context.compiler compiles a bounded execution context from admitted inputs while
preserving the distinction between trusted instruction/schema material and
untrusted evidence.

The module is deliberately stateless with respect to authoritative domain facts.
It does not own:

- the admission or revocation database;
- cognitive source records;
- prompt-factor lifecycle;
- tokenizer registration;
- provider configuration or credentials;
- network transport;
- provider invocation;
- external-effect authority;
- acceptance, promotion or release authority.

Every emitted V2 receipt carries AuthorityPosture::DENY_ALL. A successful
compilation, serialization, attachment or delivery observation cannot grant
model-call authority or authorize a write.

The module may consume verified facts from their owners and can reject stale,
inconsistent or unprovable input. It must not convert a caller assertion into an
authoritative fact merely by hashing it.

## 2. Source layout and current public surface

Primary root:

- codex-rs/hepta-context-compiler

Current implementation files:

- src/lib.rs: public exports and compatibility V1 compiler;
- src/requirements.rs: V1 mandatory requirement groups;
- src/candidate_bound.rs: V1 complete-caller-candidate-set binding;
- src/v2.rs: normative V2 admission/compile/serialize/attach/deliver proof chain;
- src/v2_tests.rs: V2 adversarial and acceptance tests;
- MANDATORY_CONTEXT.md: concise native security/profile description.

V2 public operations:

- verify_context_candidate_v2
- compile_v2
- serialize_context_exact
- build_attachment
- observe_delivery

V1 compatibility operations:

- compile
- compile_with_requirements
- compile_candidate_bound
- compile_candidate_bound_with_requirements

New integrations must not treat V1 receipts as equivalent to V2 proof-chain
receipts.

## 3. V2 lifecycle

The intended source-level lifecycle is:

    raw candidate bytes
      -> authoritative admission/revocation verifier
      -> exact candidate tokenizer
      -> opaque ContextCandidateV2
      -> compile_v2
      -> opaque CompiledContextV2
      -> exact selected-byte materialization
      -> registered ContextSerializerV2
      -> exact tokenizer over the complete final payload
      -> opaque SerializedContextV2
      -> current admission/revocation revalidation
      -> opaque ContextAttachmentV2
      -> provider adapter outside this crate
      -> ProviderInvocationReceipt
      -> independent delivery-evidence verifier
      -> ContextDeliveryReceiptV2

Each transition is fail-closed. The receipt at one phase is not sufficient to
skip a later phase.

## 4. Trust seams: verified facts versus external responsibilities

The most important design rule is to separate what the compiler proves from
what an owner adapter must authenticate.

| Boundary | What context.compiler verifies | What the external owner must establish |
| --- | --- | --- |
| Candidate admission | claim/receipt identity, coherent snapshot/frontier, source-admission digest, time/expiry, deny-all posture | that the verifier is the authoritative admission/revocation adapter and its snapshot is authentic/current |
| Tokenization | actual bytes are passed to the adapter; tokenizer digest matches the profile; returned count is bounded and receipt-bound | that the registered tokenizer implementation exactly matches the provider/model tokenizer revision |
| Serialization | exact selected bytes match admitted content digests; registered serializer/profile identity matches; actual output bytes are hashed | that the serializer implementation is the approved provider wire realization for this profile |
| Attachment | every selected candidate is reverified against current admission/revocation state; current snapshot/frontier are bound | that the supplied verifier reads the current authoritative state |
| Provider delivery | provider contract validates; exact ephemeral input digest matches attachment; provider/model identity matches; independent evidence result is bound | that the delivery verifier is backed by kernel.evidence or another authenticated terminal observer and represents the real physical attempt |

Hashing an untrusted adapter answer does not make it authoritative. Production
composition must register and qualify these owner adapters independently.

## 5. Candidate admission and opaque construction

The old V2 design exposed trusted_admission_digest as a caller-populated field.
That is no longer the normative source path.

Callers now begin with ContextCandidateDraftV2 plus exact content bytes.
verify_context_candidate_v2 requires:

- a ContextAdmissionSnapshotVerifierV2;
- an ExactContextTokenizerV2;
- a non-zero verification timestamp.

The admission verifier receives ContextAdmissionClaimV2 containing:

- item ID;
- semantic role;
- content digest computed from the actual bytes;
- source digest;
- Lane C generation-vector digest;
- secret marker.

On success it returns ContextAdmissionDecisionV2 with the authoritative
source-admission digest and expiry.

The compiler creates a private ContextAdmissionReceiptV2 that additionally binds:

- verifier identity digest;
- admission snapshot digest;
- revocation-frontier digest;
- verification time;
- deny-all authority.

ContextCandidateV2 fields are private outside the crate. A consumer cannot
construct one by assigning a plausible digest string.

Candidates marked contains_secret are rejected before successful construction.
The content itself is not stored in the candidate receipt; only its digest is
retained.

## 6. Exact candidate tokenization

ExactContextTokenizerV2 receives the actual candidate bytes. Candidate
TokenizationReceiptV2 is not publicly constructible.

The receipt binds:

- item ID;
- actual content digest;
- exact tokenizer digest;
- returned token count;
- receipt digest.

The count must be non-zero and at most MAX_CONTEXT_TOKENS_V2. compile_v2 rejects
a candidate when its tokenizer digest does not match the model profile.

Candidate token counts are selection costs only. They are not interpreted as
the token count of the final provider payload.

## 7. Model profile

ContextModelProfileV2 binds all execution-relevant identities needed by this
module:

- model artifact digest;
- provider ID digest;
- provider model digest;
- tokenizer digest;
- serializer digest;
- template digest;
- tool-schema digest;
- maximum context tokens.

Every digest must be non-zero. maximum_context_tokens must be within the
canonical context ceiling.

Changing any of these fields changes the model-profile digest and therefore the
compilation receipt. Provider delivery later rechecks provider ID and model
against the same profile.

The provider ID digest is SHA-256 of the exact provider ID string used by the
provider contract. The provider-model digest is SHA-256 of the exact provider
model string. Product adapters must use the same canonical strings when
building the profile.

## 8. Compilation request and coherent admission snapshot

ContextCompilationRequestV2 contains:

- compilation ID;
- objective digest;
- prompt-portfolio digest;
- Lane C generation-vector digest;
- admission-verifier digest;
- admission-snapshot digest;
- revocation-frontier digest;
- exact model profile;
- token budget;
- truncation-policy digest;
- compiled_at_unix_ms;
- candidate set;
- mandatory groups.

compile_v2 validates every candidate against the same verifier/snapshot/frontier
declared by the request. A candidate produced from another admission snapshot
cannot silently enter the compilation.

Every selected candidate admission must still be unexpired at compilation time.

The request token budget must be non-zero and no greater than the profile
maximum.

## 9. Mandatory groups and provenance

TrustedInstruction and Schema roles are always non-tradable floors.

MandatoryContextGroupV2 adds an indivisible set of evidence items with:

- stable group ID;
- member item IDs;
- reason digest.

Before packing, groups are canonically sorted by group ID and each member list
is canonically sorted by item ID. The compiler rejects:

- too many groups;
- duplicate group IDs;
- empty groups;
- duplicate members inside a group;
- unknown members;
- zero reason digests.

The canonical full group structure is hashed into mandatory_groups_digest and
included in ContextCompilationReceiptV2.

This matters even when two policies happen to select the same item set. A
changed reason, membership or group identity changes the receipt and therefore
cannot masquerade as the old policy.

Shared members across mandatory groups are charged once through the union of
mandatory item IDs.

## 10. Deterministic packing algorithm

After validating all candidates and groups:

1. reserve all TrustedInstruction and Schema candidates;
2. reserve the union of all mandatory-group members;
3. compute exact mandatory token cost from candidate tokenization receipts;
4. fail with InsufficientMandatoryBudget if the mandatory floor exceeds budget;
5. sort remaining optional candidates by expected-value-per-token;
6. use stable item-ID tie breaking;
7. include an optional candidate only when its candidate token count fits the
   remaining selection budget;
8. record omitted IDs explicitly;
9. sort selected candidates into stable role/item placement order;
10. compute context and compilation receipt digests.

The value-per-token comparison uses cross multiplication over fixed-point value
and integer token cost. It does not use floating-point arithmetic.

This is a deterministic bounded heuristic, not a global knapsack optimum claim.

## 11. Compilation receipt

ContextCompilationReceiptV2 binds:

- compilation ID;
- objective digest;
- prompt-portfolio digest;
- generation vector;
- admission verifier;
- compile-time admission snapshot;
- compile-time revocation frontier;
- model-profile digest;
- complete candidate-set digest;
- mandatory-groups digest;
- selected IDs;
- omitted IDs;
- selected candidate-token sum;
- compilation token upper bound;
- truncation-policy digest;
- compilation time;
- context digest;
- receipt digest;
- deny-all authority.

CompiledContextV2 is opaque and retains both the exact model profile and selected
verified candidates for later validation.

## 12. Exact materialization and serialization

A compilation receipt alone does not identify final provider bytes.

serialize_context_exact receives ContextMaterializedItemV2 values for every
selected item. Before calling the serializer, the compiler proves:

- materialized item count equals selected candidate count;
- item order equals selected placement order;
- every item ID equals the corresponding selected candidate ID;
- every content byte vector is non-empty and within the item-byte limit;
- SHA-256 of each actual byte vector equals the admitted candidate content
  digest.

A changed byte, even with the same item ID, fails as MaterializedContentMismatch.

ContextSerializerV2 exposes:

- serializer digest;
- template digest;
- tool-schema digest;
- serialize(compiled, items).

All three identity digests must match ContextModelProfileV2 before serialization.

The serializer returns the real final payload bytes. The module computes the
payload digest itself; callers no longer pass an arbitrary payload digest.

## 13. Exact final-payload tokenization

After serialization, ExactContextTokenizerV2 is run again over the complete
final payload bytes.

The final count includes all bytes introduced by the serializer: wrappers,
separators, roles, templates and other provider framing represented by the
registered serializer.

ContextSerializationReceiptV2 binds:

- compilation receipt;
- context;
- model profile;
- serializer/template/tool-schema identities;
- tokenizer identity;
- selected IDs;
- materialization digest;
- exact final payload digest;
- exact final payload token count;
- serialization time;
- receipt digest;
- deny-all authority.

The final count, not the candidate-token sum, is the hard dispatch budget gate.
If final serialized tokens are zero or exceed the compilation budget,
serialization fails closed with SerializedTokenBudgetExceeded.

The compiler currently does not automatically rerun selection to compensate for
serializer overhead. A caller may issue a new compilation under an explicitly
reviewed policy/budget; it may not silently mutate the old receipt.

SerializedContextV2 owns the exact payload bytes for the next boundary. Its
Debug implementation prints only payload digest and length.

## 14. Attachment-time revocation revalidation

The critical TOCTOU boundary is compile -> serialize -> attach.

build_attachment requires:

- the compiled context;
- the exact serialized context;
- a current ContextAdmissionSnapshotVerifierV2;
- the exact tokenizer;
- attachment ID and time.

It first revalidates serialization and exact final tokenization.

The current admission verifier identity must equal the compile-time trust anchor.
The current snapshot and revocation frontier may have advanced.

Every selected candidate is then rechecked against current state. Attachment
fails when:

- the verifier says the candidate is revoked/not admitted;
- the source-admission digest has changed;
- the current admission has expired;
- verifier identity changed;
- any compiled/serialized/tokenizer binding is inconsistent.

A newer still-valid snapshot is accepted and its current snapshot/frontier are
bound into ContextAttachmentV2.

This means a successful compile at T0 cannot be used at T2 after a T1
revocation.

ContextAttachmentV2 retains exact payload bytes for the provider boundary and
uses a digest/length-only Debug implementation.

## 15. Provider/model and delivery proof

context.compiler never performs the provider send.

The transport/provider owner produces a
codex-hepta-contracts ProviderInvocationReceipt. observe_delivery first runs the
contract's own validation, including intent/request/attempt identity checks.

The provider request must contain both:

- ephemeral_input_sha256;
- ephemeral_input_witness_sha256.

ephemeral_input_sha256 must equal the attachment exact payload digest.

The exact provider ID and model string in the provider binding are hashed and
must equal the provider/model identities in ContextModelProfileV2.

A valid provider contract alone is not sufficient evidence of a real physical
attempt because the contract object can be constructed in memory. Therefore
observe_delivery also requires ContextProviderDeliveryVerifierV2.

That verifier returns an independently sourced evidence digest and recorded
timestamp. In production this adapter should read kernel.evidence
StoredProviderAttemptEvidence/StoredProviderReceipt or another authenticated
terminal-observer source. The compiler binds the verifier identity, evidence
digest and observation time into its delivery receipt.

The delivery receipt also binds:

- attachment digest;
- expected payload digest;
- provider input witness;
- provider ID/model;
- request-binding identity;
- attempt identity;
- canonical ProviderInvocationReceipt digest;
- canonical ProviderTerminal digest;
- model-profile digest;
- terminal/disposition;
- observation time;
- deny-all authority.

Terminal mapping is exact:

- Completed -> Delivered;
- CompletedUnary -> Delivered;
- Rejected -> Rejected;
- NotDispatched -> NotDispatched;
- Indeterminate -> Indeterminate.

Indeterminate is never upgraded to Delivered.

This receipt proves the exact context payload was bound to the observed provider
attempt according to the supplied independent evidence owner. It does not prove
model answer quality, business success, a physical side effect, exactly-once
external execution, or causal learning credit.

## 16. Raw-data and logging policy

Receipts contain digests and bounded metadata, not raw context.

Raw bytes appear only in:

- verify_context_candidate_v2 input;
- ContextMaterializedItemV2;
- serializer input/output;
- SerializedContextV2;
- ContextAttachmentV2.

ContextMaterializedItemV2, SerializedContextV2 and ContextAttachmentV2 use custom
Debug implementations that omit raw bytes and expose only IDs/digests/lengths.

Callers must not wrap these objects in a custom logger that separately prints
payload() or content fields. Credentials and raw secrets remain prohibited.

## 17. Limits and resource behavior

Current source ceilings:

- MAX_CONTEXT_CANDIDATES_V2 = 4,096;
- MAX_CONTEXT_GROUPS_V2 = 256;
- MAX_CONTEXT_TOKENS_V2 = 1,000,000;
- MAX_CONTEXT_ITEM_BYTES_V2 = 4 MiB;
- MAX_CONTEXT_SERIALIZED_BYTES_V2 = 16 MiB.

These are source enforcement limits, not target-host p99 measurements.

Admission, tokenizer, serializer and delivery-verifier adapters must themselves
be bounded by their owning profiles. context.compiler does not introduce retry
loops or hidden network calls.

## 18. Failure semantics

Representative fail-closed error classes include:

Admission:
- AdmissionVerifierFailed
- AdmissionBindingMismatch
- AdmissionSnapshotMismatch
- AdmissionVerifierChanged
- InvalidAdmissionWindow
- AdmissionExpired
- AdmissionRevalidationFailed
- AdmissionRevalidationMismatch

Tokenization/profile:
- TokenizerMismatch
- TokenizerFailure
- InvalidTokenCount
- SerializerProfileMismatch
- SerializationTokenizerMismatch
- SerializationTokenCountMismatch
- SerializedTokenBudgetExceeded

Compilation/materialization:
- CandidateLimitExceeded
- GroupLimitExceeded
- DuplicateCandidate
- duplicate/empty/unknown mandatory-group failures
- GenerationVectorMismatch
- SecretRejected
- InsufficientMandatoryBudget
- MaterializationMismatch
- MaterializedContentMismatch

Attachment/delivery:
- AttachmentMismatch
- ProviderReceiptInvalid
- ProviderEvidenceInvalid
- MissingProviderInputBinding
- MissingProviderInputWitness
- ProviderModelProfileMismatch
- DeliveryMismatch
- MissingTerminalObservation
- InvalidDeliveryDisposition

Digest/time/authority failures are also explicit. No error path widens
authority or silently falls back to an unverified V1 interpretation.

## 19. V1 compatibility and migration

V1 exists to preserve existing source callers and historic receipt semantics.
Its limitations are intentional and documented:

- token counts are caller supplied;
- admission/freshness is caller responsibility;
- no exact final-payload serialization proof;
- no attachment-time current revocation proof;
- no provider-delivery proof chain.

V1 code should not be extended with partial replicas of V2 checks. New product
work should migrate to V2.

Migration sequence for a consumer:

1. implement/register authoritative ContextAdmissionSnapshotVerifierV2;
2. implement/register the exact tokenizer adapter for the selected model profile;
3. implement/register ContextSerializerV2;
4. create candidates only through verify_context_candidate_v2;
5. compile with a coherent snapshot/frontier and exact model profile;
6. materialize selected bytes and call serialize_context_exact;
7. immediately before provider use call build_attachment with current admission
   state;
8. pass attachment.payload() to the provider adapter;
9. ensure the provider request binds that payload as ephemeral_input_sha256 plus
   a host witness;
10. persist/reconcile provider evidence with the responsible evidence owner;
11. feed the validated provider receipt plus independent evidence verifier into
   observe_delivery;
12. treat the resulting delivery receipt as transport/context evidence only.

Do not transform an old V1 receipt into a V2 receipt by copying digests.

## 20. Verification matrix

Focused V2 source tests are in
codex-rs/hepta-context-compiler/src/v2_tests.rs.

They cover:

- deterministic value-per-token packing under trusted/schema floors;
- verified candidate construction;
- revoked-candidate construction failure;
- compile-time admission-snapshot mismatch;
- mandatory-budget refusal;
- mandatory-group policy provenance;
- final serialized framing overhead exceeding budget;
- materialized content-byte drift;
- compile-to-attach revocation;
- current newer snapshot/frontier attachment;
- exact provider payload delivery;
- provider payload mismatch;
- provider model drift;
- required independent delivery evidence;
- provider Indeterminate terminal preservation;
- raw payload Debug redaction.

Legacy tests remain in lib_tests.rs, requirements_tests.rs and
candidate_bound_tests.rs.

Focused command from codex-rs:

    just test --locked -p codex-hepta-context-compiler

Repository-level verification additionally owns format, Clippy, all-target,
closed-world documentation/source-map, exact-head and merge-candidate checks.
A skipped or unavailable external qualification is not a pass.

## 21. Production composition that remains outside this source candidate

Source implementation now provides the V2 proof-chain mechanics, but the module
must remain productionImplementation=false until a named product caller is
composed and qualified.

Remaining integration evidence includes:

- authoritative admission/revocation adapter identity and current-snapshot
  behavior;
- exact tokenizer implementation/revision for every admitted model profile;
- registered provider serializer implementation and wire semantics;
- physical provider caller using the attachment exact payload;
- ContextProviderDeliveryVerifierV2 backed by kernel.evidence or another
  authenticated terminal observer;
- product tests proving real compile -> attach -> physical provider attempt ->
  independent terminal observation;
- target-host capacity/latency measurements;
- exact-head and deterministic synthetic-merge qualification;
- independent security/semantic review;
- operator acceptance/canary/promotion/release where applicable.

No source comment, receipt digest or unit test can substitute for those gates.

## 22. Ownership, rollback and stop conditions

Primary owner: intelligence-platform.
Independent deputy/security review: security-authority.

The module owns no authoritative durable state, so rollback restores a compatible
binary/profile and invalidates incompatible cached V2 objects rather than
rewriting domain history.

Any change to admission semantics, tokenizer identity, serializer identity,
provider/model identity, digest domains, mandatory-group semantics or receipt
meaning requires explicit compatibility review. Never reinterpret old receipt
bytes under new semantics.

Stop conditions include:

- authority violation;
- stale or unauthenticated admission source;
- tokenizer/profile ambiguity;
- serializer/profile ambiguity;
- current revocation cannot be checked;
- provider payload cannot be proven equal to attachment payload;
- independent delivery evidence is unavailable when delivery proof is required;
- unbounded resource behavior;
- source/claim evidence mismatch.

## 23. Claim boundary

The declared root exists and the V2 source candidate now contains native
mechanisms for the CTX admission, budget, deterministic receipt, current
revalidation, zero-authority and final-delivery binding requirements.

That is a source implementation claim only.

This guide grants no runtime, production-writer, model-provider, tool, network,
filesystem, secret, Matrix, fleet, independent-acceptance, selection, promotion,
merge or release authority.
