# Native mandatory context profile

The crate now has two deliberately different source API classes.

## Normative proof-closed V2.1

The public V2 surface is `NORMATIVE_CONTEXT_COMPILER_API =
"v2.1-proof-closed"` and is implemented in `src/proof_v2.rs`. The existing
`src/v2.rs` implementation remains private and supplies only the deterministic
selection engine.

The normative path requires typed, authenticated, snapshot-bound admission
evidence for every candidate, including untrusted evidence. Admission does not
change role: evidence remains evidence and cannot satisfy an instruction/schema
binding. Raw `ContextAdmissionSnapshotEvidenceV2` must pass
`verify_admission_snapshot_v2(..., ContextAdmissionVerifierV2)`; the verified
snapshot has private fields and cannot be directly assembled from caller
digests. `ContextAdmissionSnapshotV2::verify_trusted_binding` is then the only
constructor path for `VerifiedContextAdmissionV2`. No candidate can satisfy the public V2 contract with a naked caller-supplied
admission digest or a self-assembled snapshot. The verified
snapshot binds issuer, source snapshot, revocation frontier, witness, verifier
identity, verifier-produced verification digest, observation time and canonical
admission records.

Candidate token receipts are measured from actual bytes through
`ExactContextTokenizerV2`. The public token receipt does not accept a
caller-provided token count.

`compile_v2` preserves the existing deterministic V2 selection algorithm after
the proof layer has verified typed admission, exact candidate tokenization and
profile bindings. Trusted instructions/schemas remain non-tradable floors.
Explicit `MandatoryContextGroupV2` records remain atomic and are additionally
canonicalized and bound into `mandatory_groups_digest`; changing group reason
or membership changes the public receipt even when the selected IDs happen to
remain the same.

`serialize_context_v2` requires the actual bytes for every selected item,
recomputes their content digests, invokes the selected serializer, and requires
one verified `ContextPayloadPlacementV2` per selected item. The compiler checks
that every declared final-payload slice is byte-for-byte equal to the selected
item and binds the placement digest into the serialization receipt before
invoking the selected exact tokenizer over the actual final serialized payload. The
provider-facing token budget is enforced against this final measurement, not
against the sum of candidate token counts.

`build_attachment` consumes that serialized payload and a current
`ContextAdmissionSnapshotV2`. It revalidates every selected candidate,
including untrusted evidence, against the current snapshot, rejects issuer drift, stale
snapshot time, missing admission, source/content/role drift, expiry and
revocation, and binds the current revocation frontier and witness into the
attachment.

`deliver_attachment` passes the exact attachment payload bytes to a
`ContextDeliveryAdapterV2`. A `Delivered` receipt is valid only when the
adapter reports the same payload digest, a terminal attempt, a stable provider
request ID and provider acknowledgement digest. Indeterminate attempts cannot
be promoted to delivered by a caller-supplied status flag.

Compilation, serialization, attachment and delivery receipts all carry
`AuthorityPosture::DENY_ALL`. This crate does not grant provider or other
effect authority.

The detailed V2 source contract, trust boundaries and product-composition
obligations are documented in
`docs/modules/context.compiler/V2_TECHNICAL.md`.

## V1 compatibility profile

`compile(CompilationRequest)` treats every `TrustedInstruction` item as a
non-tradable floor. If those instructions cannot fit, it returns
`Error::InsufficientContext` with the exact required cost and available budget.
The existing request and receipt shapes remain unchanged. Successful legacy
compilations retain the original digest format.

`compile_with_requirements(request, CompilationRequirementsV1)` additionally
binds mandatory provenance or contradiction groups. Requirements carry the
expected run snapshot and objective, a stable identity for each group, and exact
`ContextItem` bindings. Unknown item identities, changed role, source/content
digest, secret flag or token count cannot satisfy a requirement. An indivisible
mandatory group is included in full or the entire compilation fails. Shared
members across groups are included and charged once.

The additive owner-local `compile_candidate_bound` and
`compile_candidate_bound_with_requirements` entrypoints preserve V1 semantics
while binding the complete bounded set supplied by the caller, including omitted
items. Their `caller_candidate_set_digest` is caller-relative: it is not proof
that the caller supplied every eligible item and is not a freshness,
revocation, delivery or selection credential.

V1 callers still authenticate instructions and supply token counts. V1 must not
be interpreted as having V2.1 exact-tokenizer, current-revocation, final-payload
or delivery-proof guarantees.

## Verification

Native compatibility cases remain in `src/lib_tests.rs`,
`src/requirements_tests.rs`, `src/candidate_bound_tests.rs` and
`src/v2_tests.rs`.

Proof-boundary cases are in `src/proof_v2_tests.rs`, including admission
binding drift, revoked admission, compile-to-attach revocation, final serialization overhead, selected-content substitution, serializer item
drop/placement mismatch, mandatory-group provenance, provider acknowledgement, payload mismatch and indeterminate
delivery.

Run from `codex-rs`:

```text
just test --locked -p codex-hepta-context-compiler
cargo clippy --locked -p codex-hepta-context-compiler --all-targets -- -D warnings
```

Those are test commands, not stored execution receipts. Exact-head CI and
synthetic-merge evidence remain the execution proof. A real product host must
still authenticate admission witnesses and compose real tokenizer, serializer
and delivery adapters. No runtime activation, independent acceptance, promotion
or release is asserted by this source profile.
