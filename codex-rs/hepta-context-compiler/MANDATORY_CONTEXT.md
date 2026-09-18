# Context compiler V2 proof-chain profile

V2 is the normative path for new context.compiler integrations. The legacy
compile, compile_with_requirements, and candidate-bound V1 surfaces remain
available for compatibility, but they do not claim current admission,
revocation freshness, exact final-payload tokenization, or provider delivery.

## Verified admission is a construction boundary

Callers do not construct ContextCandidateV2 directly. They provide a
ContextCandidateDraftV2 and the candidate bytes to verify_context_candidate_v2.

The constructor requires two owner-supplied adapters:

- ContextAdmissionSnapshotVerifierV2 validates the candidate against one
  coherent admission/revocation snapshot and returns the source admission
  digest plus expiry.
- ExactContextTokenizerV2 counts the exact candidate bytes under the tokenizer
  identity bound by the selected model profile.

The resulting candidate is opaque outside the crate. Its admission receipt binds
item identity, role, content digest, source digest, Lane C generation vector,
admission-verifier identity, admission snapshot, revocation frontier, source
admission, verification time, and expiry. The receipt is deny-all authority.

This removes the V2 path that previously accepted a caller-populated
trusted_admission_digest. A syntactically valid digest is no longer sufficient
to create a trusted instruction, schema, or evidence candidate.

The verifier remains an owner boundary, not a new authority source.
Production composition must supply an independently qualified verifier backed by
the authoritative admission/revocation owner. A malicious or misconfigured
verifier cannot be made trustworthy by hashing its answer.

## Compilation and mandatory provenance

compile_v2 requires every candidate to bind the same:

- admission verifier identity;
- admission snapshot;
- revocation frontier;
- generation vector;
- exact tokenizer profile.

It also requires every candidate admission to remain live at
compiled_at_unix_ms.

Trusted instructions and schemas are non-tradable floors. Explicit mandatory
groups add provenance, citation, contradiction, or other indivisible evidence
requirements. Group IDs and item IDs are canonically sorted; duplicate/empty
groups, duplicate members, unknown members, and zero reason digests reject.

The compilation receipt includes mandatory_groups_digest. Changing a group
reason, group membership, or group identity therefore changes the compilation
receipt even if the selected item set happens to be identical.

Mandatory cost is reserved before optional evidence. Optional evidence uses the
deterministic value-per-token order with stable item-ID ties. This is a bounded
heuristic, not a global-optimality claim.

## Exact serialization and final token budget

V2 does not accept a caller-supplied serialized payload digest.

serialize_context_exact receives the exact bytes for every selected item and
first proves that:

- item count and order exactly match the compiled selection;
- every materialized item ID matches the corresponding candidate;
- every materialized content digest equals the admitted candidate digest;
- item byte limits are respected.

The registered ContextSerializerV2 then produces the actual final provider
payload bytes. Its serializer, template, and tool-schema digests must exactly
match ContextModelProfileV2.

After serialization, the same exact tokenizer profile is run over the complete
final payload bytes. The final token count is stored in
ContextSerializationReceiptV2 and is checked against the compilation budget.
Serializer framing, separators, role wrappers, tool-schema placement, and
token-boundary effects therefore cannot hide behind the sum of per-item counts.
If the final payload exceeds the budget, serialization fails closed; V2 does not
silently truncate a mandatory item or automatically repack under a different
policy.

The serialization receipt binds the materialization digest, serializer,
template, tool schema, tokenizer, selected IDs, exact payload digest, final
token count, and serialization time.

SerializedContextV2 retains the exact payload for the attachment boundary.
Its Debug implementation prints only digest and length, never raw payload bytes.

## Attachment-time current revalidation

build_attachment is the final context-use gate before a provider adapter may
consume the payload.

It requires a current ContextAdmissionSnapshotVerifierV2. The verifier identity
must match the compilation trust anchor, but its snapshot and revocation
frontier may have advanced. Every selected candidate is revalidated against that
current snapshot at attached_at_unix_ms.

Attachment rejects when:

- a selected candidate is revoked or otherwise no longer admitted;
- the source admission digest changes;
- admission has expired;
- the admission verifier identity changes;
- serialization/tokenizer/payload bindings no longer validate.

The attachment receipt binds the current admission snapshot and revocation
frontier in addition to compilation, serialization, generation, provider/model
profile, exact payload digest, final token count, selected IDs, and attach time.

This closes the compile-to-attach revocation window. A successful old
compilation is not sufficient to attach stale context.

ContextAttachmentV2 contains the exact payload bytes required by the downstream
provider boundary and uses a redacted Debug representation.

## Provider delivery evidence

The compiler does not call a provider and does not acquire model-invocation
authority. Delivery proof is consumed, not generated, by observe_delivery.

The function requires:

1. a validated codex-hepta-contracts ProviderInvocationReceipt; and
2. a separate ContextProviderDeliveryVerifierV2 result from the responsible
   evidence/terminal-observer boundary.

The provider request must bind:

- ephemeral_input_sha256 equal to the attachment exact final payload digest;
- a non-empty ephemeral-input witness;
- provider identity matching the model profile;
- provider model identity matching the model profile.

The delivery receipt additionally binds provider request-binding identity,
attempt identity, canonical provider receipt digest, canonical terminal digest,
delivery-evidence verifier identity, independently supplied evidence digest and
recorded time.

A Completed or CompletedUnary provider terminal maps to Delivered.
Rejected, NotDispatched, and Indeterminate remain distinct. An indeterminate
terminal never becomes delivered.

ProviderInvocationReceipt is itself a contract object and can exist in memory,
so the second verifier is mandatory: production composition should back it with
the independent kernel evidence store or another authenticated terminal
observer. The compiler intentionally does not infer physical delivery from a
caller boolean or from queue acceptance.

## Model profile and provider identity

ContextModelProfileV2 binds:

- model artifact digest;
- provider ID digest;
- provider model digest;
- tokenizer digest;
- serializer digest;
- template digest;
- tool-schema digest;
- maximum context tokens.

Changing any of these changes the model-profile and compilation receipts.
Provider delivery is rejected when its provider/model identity does not match
the bound profile, even when the payload digest matches.

## V1 compatibility boundary

V1 remains source-compatible for existing callers:

- compile
- compile_with_requirements
- compile_candidate_bound
- compile_candidate_bound_with_requirements

V1 is compatibility-only. It continues to rely on caller-supplied token counts
and caller-side admission/freshness. It does not produce the V2
compile/serialize/attach/deliver proof chain. New product integration must use
V2 rather than treating a V1 receipt as equivalent evidence.

## Security and resource limits

V2 rejects raw candidates marked contains_secret. Raw content exists only at
the explicit candidate-verification and materialization/serialization
boundaries. Receipt structures contain digests and metadata, not raw context.

Current source ceilings include:

- at most 4,096 candidates;
- at most 256 mandatory groups;
- at most 1,000,000 context tokens;
- at most 4 MiB per materialized context item;
- at most 16 MiB serialized payload.

All V2 receipts carry AuthorityPosture::DENY_ALL.

## Native verification

Focused V2 acceptance and adversarial cases are in src/v2_tests.rs. They cover
verified candidate construction, snapshot mismatch, deterministic selection,
mandatory-floor refusal, mandatory-policy provenance, final-payload
retokenization, materialization drift, attach-time revocation, current-snapshot
binding, exact provider payload binding, provider/model drift, independent
delivery evidence, indeterminate terminal handling, and Debug redaction.

The legacy tests remain in src/lib_tests.rs, src/requirements_tests.rs, and
src/candidate_bound_tests.rs.

Run from codex-rs:

    just test --locked -p codex-hepta-context-compiler

Repository qualification also runs exact-head and synthetic-merge checks. A
source-test pass does not establish product composition, target-host
qualification, independent acceptance, activation, promotion, merge, or release.
