<!-- GENERATED FILE: edit MODULE_MANIFEST.json and run scripts/generate_context_compiler_module_docs.py --write. -->
# `context.compiler` technical development guide

## 1. Provenance and implementation state

- Module: `context.compiler`
- Reviewed base SHA: `a126987b84737dbc2ee2592442a314117bddb4a2`
- Working branch: `codex/context-compiler-v2-full-closure-20260927`
- Source manifest: `docs/modules/context.compiler/MODULE_MANIFEST.json`
- Canonical manifest SHA-256: `b7cf4f925ed5f11df464e0aa1014ba76249d001412c264a63c5c0ecff13069c0`
- Source fingerprint SHA-256: `51f436b386117226d4fe87f6b91b78ff821ac0d6f0d6b93190ba3b9ff7663896`
- Work package: `CTX-1-CONTEXT-COMPILER` / `integration_in_progress`
- Generator: `scripts/generate_context_compiler_module_docs.py`

| Dimension | State | Evidence-based interpretation |
|---|---|---|
| Core implementation | **complete** | V2 compilation, verified admission, canonical byte coverage, typed snapshot successor, attachment, delivery preparation and provider evidence observation are implemented. |
| Product composition | **partial** | The named registry/intelligence/Agentd path, durable stage owner and Core exact-encoded-body observer are composed in source. Strict preparation and V2 terminal accounting are not yet the sole default serving path. |
| V2 provider closure | **incomplete** | Core can now fail closed on the exact encoded request body, while the strict compiler owns canonical serialization and exact-tokenizer attestations. A qualified concrete tokenizer, authoritative admission owner and sole-path preparation/terminal composition remain open. |
| Current-head qualification | **absent** | No immutable qualification receipt for the exact branch head may be claimed before the qualification workflow completes. |

The state words above are deliberately independent. A complete core library does not imply that
the product host has supplied exact final-request bytes, a qualified tokenizer, durable terminal
composition, or a successful receipt for the current Git SHA.

## 2. Scope and trust boundary

`context.compiler` selects admitted context under a deterministic budget, verifies the realized
selected bytes, emits a canonical context payload, rechecks a monotonic admission snapshot
immediately before dispatch, and authenticates provider terminal evidence. It does not own network
I/O, provider credentials, model execution, or the provider-specific request encoder.

The strict V2 boundary treats admission verifiers, provider framing policies, exact tokenizers and
provider evidence verifiers as qualified host capabilities. Missing capabilities and identity
mismatches fail closed. Candidate-level registered token costs may guide preselection, but they are
not accepted as proof of the final provider request token count.

## 3. Authoritative source locations

- `codex-rs/hepta-context-compiler`
- `codex-rs/hepta-intelligence/src/prompt_pipeline.rs`
- `codex-rs/hepta-intelligence/src/prompt_delivery.rs`
- `codex-rs/hepta-agentd/src/prompt_runtime.rs`
- `codex-rs/ext/hepta-prompt/src/lib.rs`
- `codex-rs/core/src/model_provider_policy`
- `codex-rs/hepta-context-compiler/src/provider_bound.rs`
- `codex-rs/hepta-context-compiler/src/provider_delivery.rs`
- `codex-rs/hepta-intelligence/src/provider_bound_prompt.rs`
- `codex-rs/hepta-agentd/src/provider_bound_prompt_runtime.rs`
- `codex-rs/codex-api/src/dispatch_metadata.rs`
- `codex-rs/codex-api/src/endpoint/responses.rs`
- `codex-rs/core/src/model_provider_policy/attempt_owner.rs`
- `codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs`

Public strict-path surface:

- `compile_v2`
- `record_canonical_serialization_v2`
- `build_attachment`
- `verify_typed_admission_snapshot_successor_v2`
- `prepare_delivery_from_successor_v2`
- `verify_provider_request_coverage_v2`
- `tokenize_verified_provider_request_v2`
- `observe_delivery`

## 4. End-to-end target sequence

```mermaid
flowchart TD
    N0["authoritative registry/admission snapshot"]
    N1["verify_admission_snapshot_v2 + verify_admission_v2"]
    N0 --> N1
    N2["compile_v2"]
    N1 --> N2
    N3["compiler-owned canonical serialization over realized bytes"]
    N2 --> N3
    N4["exact tokenizer over canonical context"]
    N3 --> N4
    N5["build_attachment"]
    N4 --> N5
    N6["typed current snapshot successor"]
    N5 --> N6
    N7["prepare_delivery_from_successor_v2"]
    N6 --> N7
    N8["host materializes and byte-covers the provider request"]
    N7 --> N8
    N9["exact tokenizer over final provider request bytes"]
    N8 --> N9
    N10["Core observes the exact encoded body"]
    N9 --> N10
    N11["durable dispatch claim before transport"]
    N10 --> N11
    N12["physical provider effect"]
    N11 --> N12
    N13["canonical provider terminal receipt"]
    N12 --> N13
    N14["independent delivery verifier + observe_provider_bound_delivery_v2"]
    N13 --> N14
    N15["durable ContextDeliveryReceiptV2"]
    N14 --> N15
```

The current product source reaches compilation, durable staging and the physical exact-encoded-body
provider-policy gate. The strict path intentionally remains marked **partial/incomplete** until
current authoritative admission is refreshed in that same pre-transport ceremony and Agentd makes
the resulting `ContextDeliveryReceiptV2` the sole durable terminal record.

## 5. Byte and digest identity model

| Object | Owner | Exact material | Digest / witness | Security meaning |
|---|---|---|---|---|
| canonical context bundle | context.compiler | Selected realized context items plus canonical envelope and item headers. | `CanonicalContextCoverageV2.payload_digest` | Every byte is covered; selected item bytes are exact and framing is compiler-owned. |
| prompt fragments | hepta-intelligence / ext.hepta-prompt | Developer-policy fragments projected from the canonical context for host composition. | `PromptRuntimeAttachmentV1.source_binding_digest` | Binds the product projection, but is not itself the complete provider request. |
| provider final request | provider host | Exact bytes submitted after all provider/model framing and request construction. | `VerifiedProviderRequestV2.request_digest` | Exact-tokenizer input; must contain one canonical context segment and only approved typed framing. |
| provider wire semantic digest | core model-provider policy | Secret-free canonical semantics of the physical provider send, excluding credentials and timing. | `ModelProviderInvocationInput.wire_semantic_sha256` | Binds transport semantics; it is not interchangeable with the final-request byte digest. |

These four identities must never be collapsed:

1. The canonical context bundle is a compiler-owned binary payload with complete segment coverage.
2. Prompt fragments are a product projection used during host composition.
3. The provider final request is the exact byte string submitted to the provider and tokenized.
4. The wire semantic digest binds canonical send semantics and is not a byte-for-byte request hash.

`verify_provider_request_coverage_v2` requires one and only one canonical-context segment. Every
other byte must belong to an approved typed-framing segment; offsets must be contiguous, nonempty
and cover the request exactly, and every segment digest is recomputed.

## 6. Core invariants

### 6.1 Admission and snapshot succession

- Admission records and snapshots are accepted only through a verifier identity.
- `VerifiedAdmissionSnapshotSuccessorV2` binds its predecessor digest and current verification
  digest.
- Reset snapshots, stale observation times, revocation-epoch rollback, revocation resurrection and
  authority-domain changes are rejected.
- `prepare_delivery_from_successor_v2` accepts the typed successor, not an unrelated independently
  verified snapshot.

### 6.2 Canonical serialization

- `CanonicalContextSerializerV2` is compiler-owned and deterministic.
- Its identity is derived from the canonical serializer domain, template digest and tool-schema
  digest.
- The payload contains a canonical envelope, typed item headers and exact selected item bytes.
- `CanonicalContextCoverageV2` covers byte zero through the final byte with no gaps or overlaps.
- Each selected item appears exactly once and carries its item ID, role and content digest.
- The low-level arbitrary prepared-payload pattern is not used by the strict API.

### 6.3 Exact final-request tokenization

`ProviderTokenizerIdentityV2` binds:

- provider identity;
- provider model identity;
- tokenizer binary digest;
- tokenizer version digest;
- vocabulary digest;
- normalization-policy digest.

`FinalProviderRequestTokenizationV2` additionally binds the final request digest, request coverage,
wire-semantic digest, model-profile digest, exact token count and exact request byte length. The
tokenizer identity digest must equal the profile tokenizer digest. A missing tokenizer, a digest
mismatch, zero tokens or a count above the model limit blocks dispatch.

### 6.4 Provider evidence and durability

The existing V2 observer validates `ProviderInvocationReceipt`, provider/model identity, exact
ephemeral input binding, provider witness and terminal disposition before minting
`ContextDeliveryReceiptV2`. Product completion requires Agentd to persist the preparation and
receipt as the sole serving/terminal path. A parallel V1 runtime digest may remain for migration,
but it is not sufficient to mark V2 provider closure complete.

## 7. Failure model

All strict APIs are fail-closed. Representative rejection classes are:

- unverified, stale, reset or rollback admission snapshots;
- selected-byte mismatch, duplicate realization or oversized content;
- noncanonical serializer identity;
- segment gaps, overlaps, digest mismatches or unapproved framing;
- provider/model/tokenizer identity mismatch;
- tokenizer failure, zero count or final-request budget overflow;
- provider receipt without an exact input binding or terminal evidence;
- any proof object carrying non-deny authority.

No error path silently falls back to approximate token counting.

## 8. Test strategy

The focused suite includes:

- canonical serializer golden behavior;
- Unicode, embedded control-byte and large-input cases;
- mutation-based adversarial payload and segment-map rejection;
- framing gap, overlap, duplicate-context and unapproved-kind rejection;
- tokenizer binary/version/vocabulary/normalization identity mismatch;
- final-request budget overflow;
- typed snapshot reset, rollback and revocation-frontier checks;
- deterministic generated-corpus property coverage;
- existing compile, attachment, delivery and provider-evidence tests.

## 9. Qualification and immutable receipt

Workflow: `.github/workflows/context-compiler-qualification.yml`

Artifact: `context-compiler-qualification-receipt`

Qualification commands:

1. `python3 scripts/generate_context_compiler_module_docs.py --check`
2. `cargo fmt --all -- --check`
3. `cargo test --locked -p codex-hepta-context-compiler`
4. `cargo clippy --locked -p codex-hepta-context-compiler --all-targets -- -D warnings`
5. `cargo deny --locked check bans licenses sources`
6. `cargo deny --locked check advisories (recorded non-blocking repository audit)`
7. `bazel test //codex-rs/hepta-context-compiler:all`
8. `python3 scripts/hepta-readiness.py verify`
9. `python3 scripts/hepta-docs.py verify`

The workflow writes a JSON receipt that is bound to `GITHUB_SHA`, records every command and exit
status, hashes the generated truth set, and uploads the receipt even on failure. Documentation must
continue to say `currentHeadQualification: absent` until an exact-head artifact shows every required
command succeeded.

## 10. Known open product items

- Move admission issuance and current revocation snapshots to a construction-closed registry authority owner.
- Select and independently qualify the concrete provider/model tokenizer executable and artifacts.
- Run prepare_delivery_from_successor_v2 from the exact-body pre-transport callback, not only before staging.
- Make ContextDeliveryReceiptV2 the sole durable terminal accounting path and reconcile Indeterminate attempts.
- Feature-gate the V1 runtime path after strict-path product qualification.
- Produce exact-head, synthetic-merge, target-host benchmark and independent security-review evidence.
