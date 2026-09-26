# context.compiler current product path

This document records the product path that is actually present in the repository. It is deliberately narrower than the target architecture in `TECHNICAL.md` and the native V2 proof surface in `codex-rs/hepta-context-compiler/src/v2.rs`.

**Observed source baseline:** commit `a126987b84737dbc2ee2592442a314117bddb4a2`, tree `a22fd0074c45ae6f3cef2092cd6e273bf9c26c30`.

**Work-package state:** source complete; product integration in progress; independent qualification, activation, acceptance, promotion and release remain false.

## 1. Actual product call graph

```text
AgentdPromptPipelineOwner::enumerate_candidates
  -> DurablePromptRegistry::registry
  -> prompt.optimizer::enumerate_factors_v1

AgentdPromptPipelineOwner::compile_and_stage
  -> hepta-intelligence::compile_prompt_registry_v2
     -> compile_exercised_prompt_context_v1
        -> prompt.optimizer::exercise_v1
        -> registry payload dereference
        -> context.compiler::verify_admission_snapshot_v2
        -> context.compiler::verify_admission_v2
        -> context.compiler::compile_v2
     -> prepare_prompt_delivery_v1
        -> context.compiler::record_serialization
        -> context.compiler::build_attachment
  -> AgentdPromptRuntimeOwner::stage_compiled_prompt_context
  -> PromptRuntimeHost
  -> App Server context contributor
  -> physical ModelProviderPolicyContributor
     -> durable dispatch claim before send
     -> physical provider effect
     -> durable terminal record
```

The path above is real source composition. It does **not** yet include `prepare_delivery_v2` at the physical pre-send boundary or `observe_delivery` after canonical provider evidence resolution. Consequently the current runtime terminal record is operational evidence, not a completed `ContextDeliveryReceiptV2` proof chain.

## 2. Current role support

The native compiler supports:

- `TrustedInstruction`;
- `Schema`;
- `UntrustedEvidence`.

The current prompt-registry product adapter maps prompt roles into trusted instruction/schema candidates, but the physical prompt runtime intentionally stages only `PromptRoleV2::DeveloperInstruction`. `SystemInstruction`, `UserTemplate`, `ToolSchemaFragment` and untrusted-evidence delivery remain fail-closed until Codex exposes an exact typed provider slot and the slot is bound into the provider-visible request digest.

This restricted runtime profile must not be described as full role-contract completion.

## 3. Current trust adapters

### Admission verifier

The product adapter currently constructs registry-scoped admission records and verifies them with an in-process `RegistryAdmissionVerifier`. It checks scope, authority domain, secret classification and structural validity. It is not an independent issuer/verifier split and is not a production admission authority.

The production path must consume signed, current admission records and a signed cumulative revocation snapshot from an independently owned authority. The verifier must possess verification capability only; signing capability must not be linked into Agentd or the compiler process.

### Tokenizer

The current adapter uses registry-declared token costs through a digest-indexed lookup. That is provisional compatibility behavior. It is not an exact model tokenizer over the final provider-visible bytes and must not be used to raise `productionImplementation` or `productExecutionProved`.

The replacement contract must bind provider, model, tokenizer implementation/version, vocabulary digest, normalization policy and final request digest, and must execute the tokenizer over the exact serialized bytes.

### Serializer

The current adapter accepts a prepared byte vector and proves that selected realization bytes occur in order. This is a useful anti-omission check but is not a canonical serializer proof: extra prefixes, interstitial bytes or suffixes are not excluded by occurrence proof alone.

The replacement serializer must be compiler-owned or return an exact segment map for every selected item and every allowed typed framing segment. Re-serialization from typed inputs must produce byte-for-byte equality with the provider-visible context segment.

### Provider evidence

The physical runtime already records a durable pre-send dispatch claim and a terminal classification bound to the exact provider request digest. The canonical V2 delivery preparation and independent `ContextProviderDeliveryVerifierV2` are not yet composed into this callback.

## 4. Proof-chain status

| Stage | Native source | Named product caller | Physical effect-bound | Independently qualified |
|---|---:|---:|---:|---:|
| admission snapshot verification | yes | provisional adapter | no | no |
| admission record verification | yes | provisional adapter | no | no |
| `compile_v2` | yes | yes | not applicable | no |
| `record_serialization` | yes | yes, provisional codec | no | no |
| `build_attachment` | yes | yes | no | no |
| `prepare_delivery_v2` | yes | no | no | no |
| durable dispatch-before-send | runtime source | yes | yes | no |
| physical provider effect | runtime source | yes | yes | no |
| canonical `ProviderInvocationReceipt` for this path | contract source | no | no | no |
| independent delivery evidence verification | yes | no | no | no |
| `observe_delivery` / `ContextDeliveryReceiptV2` | yes | no | no | no |

## 5. Required closure path

The only production-complete path is:

```text
authoritative current snapshot
  -> verify_admission_snapshot_successor_v2
  -> verify_admission_v2
  -> compile_v2
  -> record_serialization(real canonical serializer, real tokenizer)
  -> build_attachment
  -> prepare_delivery_v2 in the physical pre-send callback
  -> consume current final-use authority
  -> durable dispatch claim
  -> physical provider effect
  -> canonical ProviderInvocationReceipt
  -> independent ContextProviderDeliveryVerifierV2
  -> observe_delivery
  -> durable ContextDeliveryReceiptV2
```

A queue acknowledgement, compilation result, attachment, provider-policy allow decision or runtime terminal callback alone is not delivery proof.

## 6. Legacy path status

The following remain compatibility APIs only:

- `compile`;
- `compile_with_requirements`;
- `compile_candidate_bound`;
- registered wire V2 framing that transports legacy V1 receipt semantics;
- `observe_prompt_delivery_v1` and prompt-runtime terminal records.

They must not be promoted into V2 proof objects or interpreted as exact tokenizer, current revocation or independently verified provider-delivery evidence. Product builds must eventually select one canonical V2 ingress behind an explicit feature gate; enabling both legacy and canonical authority paths in one production process is forbidden.

## 7. Current completion claim

The current defensible claim is:

> Native V2 context compilation is source-complete and partially product-composed through serialization, attachment and a real durable provider runtime. Exact production tokenizer/serializer adapters, independent admission authority, effect-bound `prepare_delivery_v2`, canonical provider receipt resolution, `observe_delivery`, target-host qualification and independent acceptance remain open.

This document grants no model, provider, filesystem, network, activation, acceptance, promotion, merge or release authority.
