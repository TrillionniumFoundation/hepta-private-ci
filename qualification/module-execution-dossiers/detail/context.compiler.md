<!-- GENERATED FILE: edit MODULE_MANIFEST.json and run scripts/generate_context_compiler_module_docs.py --write. -->
# Execution dossier: `context.compiler`

## 1. Evidence identity

- Reviewed base: `a126987b84737dbc2ee2592442a314117bddb4a2`
- Working branch: `codex/context-compiler-v2-full-closure-20260927`
- Manifest SHA-256: `b7cf4f925ed5f11df464e0aa1014ba76249d001412c264a63c5c0ecff13069c0`
- Generator: `scripts/generate_context_compiler_module_docs.py`
- Qualification workflow: `.github/workflows/context-compiler-qualification.yml`
- Receipt artifact: `context-compiler-qualification-receipt`

## 2. Current truth matrix

| Dimension | State | Evidence-based interpretation |
|---|---|---|
| Core implementation | **complete** | V2 compilation, verified admission, canonical byte coverage, typed snapshot successor, attachment, delivery preparation and provider evidence observation are implemented. |
| Product composition | **partial** | The named registry/intelligence/Agentd path, durable stage owner and Core exact-encoded-body observer are composed in source. Strict preparation and V2 terminal accounting are not yet the sole default serving path. |
| V2 provider closure | **incomplete** | Core can now fail closed on the exact encoded request body, while the strict compiler owns canonical serialization and exact-tokenizer attestations. A qualified concrete tokenizer, authoritative admission owner and sole-path preparation/terminal composition remain open. |
| Current-head qualification | **absent** | No immutable qualification receipt for the exact branch head may be claimed before the qualification workflow completes. |

This dossier does not infer release qualification from source presence or a historical workflow.
Only a successful receipt whose `headSha` equals the reviewed commit may change the fourth state.

## 3. Implemented controls

- Verified admission records and complete revocation snapshots.
- Deterministic context selection with mandatory trusted/schema floors.
- Compiler-owned canonical serialization and complete byte coverage.
- Typed snapshot succession for the immediate pre-dispatch recheck.
- Exact provider-request coverage with one canonical context segment and approved typed framing.
- Tokenizer attestation bound to provider, model, binary, version, vocabulary and normalization.
- Existing provider-receipt validation and terminal disposition mapping.
- Deny-all authority on every newly minted proof.

## 4. Product composition finding

The source product path is real rather than hypothetical: prompt registry compilation feeds
`hepta-intelligence`, Agentd owns durable staging, and Core now observes the exact encoded body before
transport. Composition remains **partial** because the authoritative admission owner, qualified
concrete tokenizer and sole-path V2 terminal persistence are not yet all active in one effect-bound
ceremony. The strict API fails closed rather than falling back to registry token costs.

## 5. Byte-identity audit

| Object | Owner | Exact material | Digest / witness | Security meaning |
|---|---|---|---|---|
| canonical context bundle | context.compiler | Selected realized context items plus canonical envelope and item headers. | `CanonicalContextCoverageV2.payload_digest` | Every byte is covered; selected item bytes are exact and framing is compiler-owned. |
| prompt fragments | hepta-intelligence / ext.hepta-prompt | Developer-policy fragments projected from the canonical context for host composition. | `PromptRuntimeAttachmentV1.source_binding_digest` | Binds the product projection, but is not itself the complete provider request. |
| provider final request | provider host | Exact bytes submitted after all provider/model framing and request construction. | `VerifiedProviderRequestV2.request_digest` | Exact-tokenizer input; must contain one canonical context segment and only approved typed framing. |
| provider wire semantic digest | core model-provider policy | Secret-free canonical semantics of the physical provider send, excluding credentials and timing. | `ModelProviderInvocationInput.wire_semantic_sha256` | Binds transport semantics; it is not interchangeable with the final-request byte digest. |

The acceptance criterion is byte identity, not merely semantic similarity. The provider send must
consume the request represented by `VerifiedProviderRequestV2`; rebuilding from fragments after
tokenization invalidates the attestation.

## 6. Required execution order

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

## 7. Test evidence expected from the exact head

The qualification receipt must show successful formatting, focused compilation, strict clippy,
unit/adversarial/generated-corpus tests, cargo-deny, Bazel and repository source/readiness checks.
The workflow records failures instead of deleting or rewriting them and uploads the receipt with
`if: always()` semantics.

## 8. Remaining closure items

1. Move admission issuance and current revocation snapshots to a construction-closed registry authority owner.
2. Select and independently qualify the concrete provider/model tokenizer executable and artifacts.
3. Run prepare_delivery_from_successor_v2 from the exact-body pre-transport callback, not only before staging.
4. Make ContextDeliveryReceiptV2 the sole durable terminal accounting path and reconcile Indeterminate attempts.
5. Feature-gate the V1 runtime path after strict-path product qualification.
6. Produce exact-head, synthetic-merge, target-host benchmark and independent security-review evidence.

## 9. Reviewer decision

The core design is complete and materially stronger than the prior trusted-serializer/registered-
count path. Product release remains blocked on host exact-tokenizer composition, sole-path durable
V2 terminal accounting and an all-green receipt for the exact reviewed SHA.
