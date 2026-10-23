# Checked digest reuse and consumer handoff review — 2026-09-29

This supplement records an implementation increment, not completion, deployment authority, or an independent acceptance receipt. `IMPLEMENTATION_MAP.json` remains the sole module status authority. Read this with `TECHNICAL.md`, `QUALIFICATION.md`, and the existing invariant inventory; none is replaced or deleted.

## Reviewed source and changes

The reviewed pre-optimization source is commit `a6131709a86fd10057b5a53739dfc37cd6520eb4`. The code revision containing the changes below is `1bfbf7d4213a3be3dd840ebe8b2fd22647a439a0`, tree `b309ab36f4406bbe4f551f3cbbc58ee88e95c0ca`. Later documentation commits are not substitutes for exact-final-head qualification.

- `203a04a39796b1fecce9c13634cc3d179826341e`: factor the existing frozen and schema-bound digest calculations through private checked-payload helpers; add a crate-private paired operation and a serialization-count regression.
- `f5a78f25bc1eb4b63eb69b0fb2e3708c43299726`: use that paired operation in the existing `CanonicalConsumerBindingV1::compare_canonical_projection_v1` implementation.
- `1bfbf7d4213a3be3dd840ebe8b2fd22647a439a0`: check profile equivalence in both real payload families across all five consumer variants; expand resealed substitution coverage to include the canonical payload digest.

The source under review uses `ContractViolationV1`, `CanonicalConsumerBindingError`, canonical JSON wire envelopes, `MemoryEventV1` and `RecallPacketV1`. Earlier review references to a different rejection structure or unrelated consumers must not be used as repair instructions for this source. This increment does not claim to have reproduced or repaired a `RejectionInfo::cascade_id` build failure.

## Preserved boundary and exact digest semantics

The public wire encoding and both digest domains are unchanged. The frozen V1 profile remains historically interpretable. The schema-bound profile retains schema identity, wire version, contract identity and canonicalization algorithm. The two profiles are not interchangeable and are never compared as if they belonged to the same domain.

`canonical_contract_digests_v1` is crate-private. It calls the existing bounded, validating `encode_payload_canonical_v1` once, then derives both digests from those exact bytes. Its byte-level helpers are private. It introduces no global cache, owner capability, persistence, write path, transport or alternative product executor.

Reuse lasts only for this synchronous call and is tied to its actual payload and generic contract type. There is no cross-operation, cross-scope or cross-epoch authorization cache to invalidate. The independently projected expected value is still validated and hashed independently; it is not synthesized from the received wire bytes to manufacture parity.

The ordinary handoff still checks the current migration registry through `binding.validate()`, verifies the consumer/payload family, strictly decodes the wire, compares its frozen digest to the bound digest, and compares the actual typed values. `require_match_for_current_binding` still validates the supplied current binding and compares the entire binding before exposing a matching result. The owner must provide that observation immediately before physical use. A cloned historical binding is not evidence of freshness, revocation status or authority.

Historical validation and current-use validation remain distinct. No registry state or compatibility posture has been promoted by these changes.

## Regression inventory and what it establishes

### Correct payload families

The all-consumer positive fixture retains all five consumers:

| Consumers | Canonical projection fixture |
| --- | --- |
| `cognitive.read`, `cognitive.store`, `compact.engine` | `MemoryEventV1` |
| `memory.retrieval`, `intelligence.control` | `RecallPacketV1` |

A positive fixture must not force an event into either recall consumer. The payload-family refusal remains active. These are contract fixtures using the production codec and handoff, not authenticated product-owner integration evidence.

### Resealed substitutions

`all_five_handoffs_reject_resealed_current_binding_substitution` now covers six independent changes for every consumer: operation, same-family consumer identity, source identity, source snapshot, compatibility payload digest and canonical payload digest. There are 30 adversarial subcases.

Each alternative is explicitly different, is resealed with `compute_binding_sha256`, and must pass current binding validation before the handoff refuses it at `handoff.currentBinding`. This prevents a broken checksum from standing in for a meaningful identity-substitution test. The original binding must remain accepted after the negative checks.

Existing mismatched semantic-projection, forbidden payload-family, contextual span, contextual binding and distinct-profile cases are retained.

### Serialization work, not a claimed latency improvement

`paired_digests_preserve_profiles_and_halve_payload_serializations` instruments calls to the serializer of a deterministic test contract at 0, 1 and `u64::MAX`. It compares the paired operation with the two public single-profile operations, requires identical digests, distinct domains, nonzero observed work and a 2:1 serialization-call ratio.

This counts work in the digest operation. It does not assert a 2x end-to-end speedup, allocation bound, throughput improvement or host latency result. The normal handoff also performs decoding, validation, independent expected projection work and final-use checks. Those costs remain and require measurement on the selected host.

## Verification and acceptance status

At the time this supplement was authored, the code revision triggered these existing remote workflows:

- `cognitive-types-qualification`: run `36509311951`, observed pending.
- `hnmf-qualification`: run `36509312103`, observed pending.

Pending, queued, skipped, cancelled, failed or missing results are not passing results. Requalify the final documentation head as well as its fixed-base merge candidate under the existing workflow. This note does not elevate source, product execution, consumer convergence, independent acceptance, activation or release flags.

The editing environment had no `cargo`, `rustc` or `rustfmt`, and its shell could not resolve `static.rust-lang.org`. Native compilation, the new Rust regressions, strict Clippy and formatting have therefore not been executed locally. No benchmark result or source-mutant kill is asserted here.

Targeted commands for an environment with the repository toolchain, from `codex-rs`:

```sh
cargo test -p codex-hepta-cognitive-types paired_digests_preserve_profiles_and_halve_payload_serializations
cargo test -p codex-hepta-cognitive-types common_semantic_comparison_never_compares_legacy_and_canonical_digest_domains
cargo test -p codex-hepta-cognitive-types all_five_handoffs_reject_resealed_current_binding_substitution
cargo test -p codex-hepta-cognitive-types semantic_comparison_records_and_rejects_a_real_payload_mismatch
cargo test -p codex-hepta-cognitive-types
cargo clippy -p codex-hepta-cognitive-types --all-targets -- -D warnings
cargo fmt --all -- --check
```

These commands are a reproduction list, not an execution transcript. Full existing exact-head and fixed-base merge qualification, cross-language vectors, negative codec cases, mutation sensitivity and owner/consumer checks remain required. Preserve command outcomes, source and tree identities, runner/toolchain identity, logs, artifact digests and failures under the existing qualification owner.

## Remaining obligations

The entire closure request is not finished by this increment. Authenticated default-profile composition for all five consumers, compatibility retirement, exact-final-head native/merge qualification, and selected-host performance/allocation evidence remain separate obligations. FFI/WASM completion is not inferred from native contract fixtures. No second status ledger or test-only success path has been created to label those obligations complete.

Further modularization of `wire.rs` must preserve the existing mutation anchors, source traceability, public APIs and frozen digest bytes. The current refactoring is intentionally limited to shared private digest helpers; it is not a wholesale protocol or type-system rewrite.
