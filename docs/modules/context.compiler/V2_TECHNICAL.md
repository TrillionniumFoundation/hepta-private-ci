# context.compiler proof-closed V2.1 technical reference

Status: source API implemented; product composition and independent qualification remain external.

Normative public API marker: `NORMATIVE_CONTEXT_COMPILER_API = "v2.1-proof-closed"`.

Primary source:

- `codex-rs/hepta-context-compiler/src/proof_v2.rs`
- deterministic selection engine: `codex-rs/hepta-context-compiler/src/v2.rs` (private implementation detail)
- hostile-boundary tests: `codex-rs/hepta-context-compiler/src/proof_v2_tests.rs`

This reference describes the current public V2 execution-context contract. V1
entrypoints remain available for compatibility but are not the normative
provider-facing execution-context proof path.

## 1. Security objective

The V2.1 path exists to make the following statements mechanically distinct:

1. a context item was admitted by an authenticated upstream owner and remains
   usable in a coherent snapshot;
2. the deterministic compiler selected a bounded set under an exact model
   profile and canonical mandatory-group policy;
3. the bytes realized for every selected item are the bytes whose content
   digests were compiled;
4. the actual final serialized payload was tokenized under the exact tokenizer
   selected by the model profile and fits the provider-facing budget;
5. the selected trusted instruction/schema records were checked again against a
   current admission/revocation snapshot immediately before attachment; and
6. a `Delivered` receipt exists only after a transport adapter returned an
   exact-payload attempt identity plus provider request and acknowledgement
   evidence.

No receipt in this module grants model, provider, tool, filesystem, network, or
other effect authority.

## 2. Trust boundaries

### 2.1 Compiler-verified facts

The module itself verifies:

- nonzero and internally consistent digest bindings;
- content bytes against candidate content digests;
- trusted role against a typed `VerifiedContextAdmissionV2`;
- admission item, role, content, source, expiry and revocation state relative to
  the supplied coherent `ContextAdmissionSnapshotV2`;
- exact candidate token counts by invoking `ExactContextTokenizerV2` over
  actual candidate bytes before the receipt exists;
- exact final payload token count by invoking the same selected tokenizer over
  final serialized payload bytes;
- model/tokenizer/template/tool-schema/serializer profile identity;
- deterministic candidate selection through the existing private V2 engine;
- canonical mandatory-group provenance;
- selected item identity/content/source/tokenization/admission bindings;
- final serialization realization and payload digest;
- attachment-time current admission/revocation revalidation;
- exact payload handoff to a delivery adapter;
- equality between transport-evidence payload digest and attached payload digest;
- provider request plus acknowledgement evidence before a result can be called
  `Delivered`;
- zero authority on compilation, serialization, attachment and delivery
  receipts.

### 2.2 Host-authenticated facts

The compiler does not implement an upstream signature scheme, TLS channel,
provider identity system, or durable latest-head store by itself. Instead, raw
admission state enters as `ContextAdmissionSnapshotEvidenceV2` and must pass a
host-owned `ContextAdmissionVerifierV2` before the module can construct the
private-field `ContextAdmissionSnapshotV2`. The verifier identity and returned
nonzero verification digest are bound into the snapshot and downstream proofs.

The selected host must provide an authenticator that verifies:

- the admission issuer represented by `issuer_digest`;
- the latest-head/witness represented by `witness_digest`;
- the freshness and durability of the revocation frontier;
- the relationship between the raw evidence and the authoritative owner state.

The selected host must also authenticate/qualify:

- the implementation behind `ExactContextTokenizerV2`;
- the implementation behind `ContextSerializerV2`;
- the implementation behind `ContextDeliveryAdapterV2`;
- the semantic meaning of provider acknowledgement evidence returned by that
  adapter.

A self-consistent but unauthenticated snapshot is not proof of the newest
upstream state. Product qualification must bind these host facts independently.

## 3. Lifecycle and state machine

The normative lifecycle is:

```text
authenticated admission owner snapshot
        |
        v
ContextAdmissionSnapshotV2
        |
        +--> verify_trusted_binding(...)
        |        |
        |        v
        |   VerifiedContextAdmissionV2
        |
actual candidate bytes + ExactContextTokenizerV2
        |
        v
TokenizationReceiptV2::measure(...)
        |
        v
ContextCandidateV2::new(...)
        |
        v
compile_v2(...)
        |
        v
CompiledContextV2 + ContextCompilationReceiptV2
        |
actual selected item bytes
        |
        v
ContextSerializerV2::serialize(...)
        |
        v
ExactContextTokenizerV2::count_tokens(final_payload)
        |
        v
SerializedContextV2 + ContextSerializationReceiptV2
        |
current authenticated admission/revocation snapshot
        |
        v
build_attachment(...)
        |
        v
ContextAttachmentV2
        |
exact attachment payload bytes
        |
        v
ContextDeliveryAdapterV2::deliver(...)
        |
        v
ContextDeliveryReceiptV2
```

Skipping a stage is not equivalent to completing the later stage.

## 4. Admission model

### 4.1 `ContextAdmissionRecordV2`

Every context candidate, including untrusted evidence, requires an admission
record. Admission and trust role are separate concepts: admitting evidence makes
it eligible context; it does not turn evidence into an instruction.

Each record binds:

- `item_id`;
- exact `role` (trusted instruction, schema, or untrusted evidence);
- `content_digest`;
- `source_digest`;
- upstream `admission_digest`;
- admission time;
- optional expiry;
- optional revocation time plus revocation digest.

A proof issued for `UntrustedEvidence` cannot satisfy a trusted-instruction or
schema candidate because role equality is verified and bound into the proof.

### 4.2 Snapshot evidence and authentication

Callers first supply `ContextAdmissionSnapshotEvidenceV2`: issuer, source
snapshot, revocation frontier, witness, observation time and records.
`verify_admission_snapshot_v2` validates record shape and then invokes
`ContextAdmissionVerifierV2::verify_snapshot`. If authentication fails or the
verifier returns a zero verification digest, no typed snapshot can exist.

The resulting private-field `ContextAdmissionSnapshotV2` binds:

- authenticated issuer identity digest;
- upstream source snapshot digest;
- current revocation frontier digest;
- upstream witness digest;
- verifier implementation identity digest;
- verifier-produced authentication/verification digest;
- observation time;
- canonical admission records.

Records are canonicalized by `StableId`; duplicate records fail closed.

### 4.3 `VerifiedContextAdmissionV2`

Callers cannot construct this proof by filling a public digest field. It is
returned only by `ContextAdmissionSnapshotV2::verify_binding`, which checks:

- exact item identity;
- exact trusted role;
- exact content digest;
- exact source digest;
- admission not in the future;
- admission not expired at snapshot time;
- admission not revoked;
- proof binding to the same issuer, snapshot, frontier and witness.

The proof remains snapshot-relative. Every selected candidate, trusted or
untrusted, is revalidated against a current authenticated snapshot before
attachment. This closes compile-to-attach tombstone/revocation windows for
evidence as well as trusted instruction/schema inputs.

## 5. Exact tokenization

### 5.1 Candidate measurement

The public V2 token receipt has no constructor that accepts a caller-supplied
token count. `TokenizationReceiptV2::measure` invokes
`ExactContextTokenizerV2::count_tokens` over the actual candidate bytes.

The receipt binds:

- item ID;
- content digest of the measured bytes;
- tokenizer implementation digest;
- measured token count.

The profile tokenizer digest must equal the tokenizer receipt digest.

### 5.2 Final payload measurement

Candidate-token sums are selection estimates only. They are not treated as the
final provider token count.

`serialize_context_v2`:

1. matches supplied payload items exactly to the selected item IDs;
2. recomputes every item content digest from actual bytes;
3. invokes the selected serializer over ordered selected items;
4. hashes the actual serialized payload;
5. invokes the selected exact tokenizer over those final bytes; and
6. rejects if the actual final token count exceeds the compilation budget or
   model maximum.

Serializer framing, separators, roles, templates, and tokenizer boundary effects
therefore cannot be hidden behind a copied candidate-token sum.

## 6. Deterministic selection and mandatory provenance

The existing V2 value-per-token selection algorithm is retained privately. The
proof layer validates security evidence first, converts verified candidates to
the internal selection representation, then calls the deterministic engine.

All candidates must carry a verified admission proof. Trusted
instruction/schema items additionally remain mandatory floors. Explicit
`MandatoryContextGroupV2` records are canonicalized by group ID and item ID.
The public compilation receipt additionally binds
`mandatory_groups_digest`, including:

- group identity;
- exact member identities;
- reason digest.

Changing mandatory-group semantics changes the public receipt even when the
selected item set happens to remain identical.

The public receipt also binds `selected_binding_digest`, covering every
selected item's role, content/source digest, measured tokenization receipt and
trusted-admission proof when applicable.

## 7. Serialization proof

`ContextSerializationReceiptV2` is created only by
`serialize_context_v2`; there is no public operation that accepts a naked
payload digest and declares serialization complete.

It binds:

- compilation receipt;
- selected binding;
- model profile;
- serializer identity;
- selected item order;
- realization digest;
- actual final payload digest;
- actual final token count.

`SerializedContextV2` retains the exact payload bytes privately and exposes
read-only bytes for the subsequent attachment/delivery boundary.

## 8. Attachment-time revocation revalidation

`build_attachment` consumes the serialized context and a current
`ContextAdmissionSnapshotV2`.

It rejects:

- admission issuer drift;
- a snapshot older than the compilation admission observation;
- any selected candidate missing from current admission state;
- role/content/source drift for trusted or untrusted inputs;
- expiry;
- revocation.

The resulting attachment binds:

- compilation and serialization receipt digests;
- model/generation identity;
- current admission snapshot;
- current revocation frontier;
- current witness;
- revalidation time and revalidation proof digest;
- exact payload digest and token count;
- exact selected item IDs.

The serialized payload is consumed into the attachment so delivery cannot
accidentally use an unrelated payload object.

## 9. Delivery proof

`deliver_attachment` is the only public V2 operation that can create a
`ContextDeliveryReceiptV2`.

It invokes `ContextDeliveryAdapterV2::deliver` with the exact payload bytes
held by the attachment. Transport evidence binds:

- stable attempt ID;
- observed payload digest;
- optional provider request ID;
- optional provider acknowledgement digest;
- terminal observation state;
- delivered/rejected/indeterminate disposition;
- observation time.

For `Delivered`, all of the following are required:

- terminal observation;
- payload digest equals the attached payload digest;
- provider request ID is present;
- provider acknowledgement digest is present.

An indeterminate transport attempt cannot be upgraded to delivered merely by
setting a boolean. A rejected result must be terminal.

The provider acknowledgement remains adapter evidence; product qualification
must independently show that the real adapter's acknowledgement semantics mean
what the product claims.

## 10. Public API policy

`lib.rs` exports proof-closed V2.1 as the normative V2 surface.

The old V2 engine remains a private module so existing deterministic selection
tests and implementation logic can be reused without exposing the weak
caller-assertion seams.

The following former public patterns are intentionally not exported:

```text
TokenizationReceiptV2::new(... caller_token_count ...)
record_serialization(... payload_digest ...)
observe_delivery(... caller_observed_digest/status ...)
```

The normative replacements are:

```text
verify_admission_snapshot_v2(raw_snapshot_evidence, admission_verifier)
TokenizationReceiptV2::measure(actual_bytes, tokenizer)
serialize_context_v2(actual_selected_bytes, serializer, tokenizer)
build_attachment(serialized, current_verified_admission_snapshot)
deliver_attachment(attachment, delivery_adapter)
```

V1 `compile`, `compile_with_requirements`,
`compile_candidate_bound`, and
`compile_candidate_bound_with_requirements` remain compatibility-only source
APIs. They do not imply proof-closed V2 semantics.

## 11. Failure semantics

Security-relevant failures are fail closed. Important classes include:

- admission missing/binding mismatch/revoked/expired;
- stale admission snapshot or issuer drift;
- tokenizer/serializer identity mismatch;
- tokenizer or serializer runtime failure;
- candidate token receipt mismatch;
- mandatory-group inconsistency;
- actual payload content mismatch;
- actual serialized token-budget overflow;
- attachment digest/revalidation mismatch;
- delivery adapter failure;
- transport payload mismatch;
- missing provider acknowledgement;
- invalid terminal/disposition combination;
- any nonzero authority grant in a compiler receipt.

Selection-engine errors are wrapped as `ContextCompilerV2Error::SelectionEngine`
rather than reinterpreted.

## 12. Verification matrix

`src/proof_v2_tests.rs` includes source-level cases for:

- deterministic selection with a typed trusted floor;
- rejection when a verified admission proof is reused with a changed source;
- revoked trusted admission rejection;
- revocation introduced between compilation and attachment for trusted context;
- revocation/tombstone introduced for selected untrusted evidence;
- final serialized payload retokenization including serializer overhead;
- selected content-byte substitution;
- mandatory-group provenance changing the receipt even when selected IDs do not;
- exact payload -> attachment -> provider-ack digest chain;
- refusal to call an attempt delivered without provider acknowledgement;
- transport payload mismatch;
- indeterminate nonterminal delivery.

Legacy selection tests in `src/v2_tests.rs` continue to guard deterministic
packing behavior. V1 tests continue to guard compatibility semantics.

Run the package checks from `codex-rs`:

```text
just test --locked -p codex-hepta-context-compiler
cargo clippy --locked -p codex-hepta-context-compiler --all-targets -- -D warnings
```

These are invocation instructions, not stored proof that a particular commit
passed. Exact-head CI results remain the execution evidence.

## 13. Product-composition obligations

Source closure does not by itself establish product completion. A selected host
must still demonstrate, at an exact commit:

- a real `ContextAdmissionVerifierV2` authenticating issuer/latest-head witness and revocation state from the actual owner;
- a real tokenizer implementation matching the selected model profile;
- a real serializer matching actual Codex/provider request assembly;
- current revocation-frontier reads at the attachment boundary;
- a real delivery adapter that sends the exact attachment bytes;
- durable provider attempt correlation and acknowledgement semantics;
- cancellation/retry/idempotency behavior under provider faults;
- actual product caller composition;
- independent semantic/host qualification.

Until those are proven, this module remains source-implemented but not
production-composed or independently accepted.

## 14. Rollback and compatibility

Rollback may restore the prior public API only as an explicit compatibility
rollback. A rollback must not reinterpret older weak receipts as V2.1
proof-closed receipts.

Digest domains in this file are versioned `proof-v2.1`; new bound semantic
fields require a new domain/version rather than silently changing the meaning of
existing receipts.

No cache may reuse a compilation across changed admission snapshot, revocation
frontier, mandatory-group policy, selected binding, model profile, serializer,
or tokenizer identity.
