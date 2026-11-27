# context.compiler current product path

This document records the exact product composition candidate for
`context.compiler`. It is deliberately narrower than the target architecture:
source composition is not target-host qualification, independent acceptance,
activation, promotion or release.

## Status

- Core verified-V2 compiler: implemented.
- Registry-owned context admission authority: composed in source.
- Exact-tokenizer adapter seam: composed; a concrete qualified executable is
  still a deployment input and must match its declared binary, vocabulary and
  normalization identities.
- Canonical serializer: composed in `prompt_product_v3`.
- Named product owner: `AgentdPromptProductOwnerV3`.
- App Server provider bridge: composed in source through
  `PromptRuntimeExtensionV3`.
- Exact-head and synthetic-merge execution receipts: supplied by CI for the
  candidate, not asserted by this prose document.
- Independent security acceptance: not yet granted.
- Activation and release: false.

## Actual call graph

```text
Agentd orchestration / optimizer selection
  -> AgentdPromptProductOwnerV3::compile_and_stage
       -> compile_prompt_registry_v3
            -> DurablePromptRegistry current realization bytes
            -> PromptContextAuthoritySnapshotV3
            -> verify_admission_snapshot_v2
            -> verify_admission_v2
            -> compile_v2
            -> CanonicalPromptSerializerV3
            -> ProcessExactTokenizerV3 or another qualified exact tokenizer
            -> record_serialization
            -> build_attachment
       -> durable source-bound stage metadata
       -> PromptRuntimeContextV3

embedded App Server turn assembly
  -> PromptRuntimeExtensionV3::contribute_turn_context
       -> one typed DeveloperPolicy or DeveloperCapabilities fragment

Core provider request finalization
  -> ModelProviderContextFinalUseContributor::prepare
       -> AgentdPromptProductOwnerV3::prepare_final_use
            -> current registry context-authority successor
            -> verify_admission_snapshot_successor_with_lineage_v2
            -> prepare_delivery_v2
            -> PromptRuntimeFinalUseProofV3
       -> ModelProviderContextFinalUseProposal
       -> Core binds exact context payload SHA-256 and attempt witness

physical provider effect
  -> PromptRuntimeExtensionV3::begin
       -> canonical ProviderInvocationIntent
       -> Agentd durable dispatch claim
       -> provider transport only after durable claim succeeds

provider terminal
  -> canonical ProviderInvocationReceipt
       -> AgentdProviderDeliveryVerifierV3
       -> observe_delivery
       -> ContextDeliveryReceiptV2
       -> durable terminal evidence
```

The compiler never performs the network/model effect. Agentd owns the durable
pre-send and terminal evidence lifecycle; Core owns request finalization and the
physical provider transport.

## Admission authority

The product path no longer constructs and accepts its own ad-hoc admission
records through the provisional compatibility verifier. The durable prompt
registry issues opaque `PromptContextAuthoritySnapshotV3` and admission objects.
The context compiler receives only the translated, verifier-authenticated
snapshot and admission records.

The authority snapshot binds:

- registry snapshot identity;
- scope and authority-domain digests;
- observed time and revocation frontier;
- complete admitted realization set;
- predecessor snapshot identity for successor verification;
- deny-all authority posture.

`VerifiedAdmissionSnapshotLineageV2` is construction-closed and records the
exact predecessor/current relationship. A caller cannot substitute a merely
newer-looking fork without passing the registered authority verifier and direct
successor checks.

## Tokenizer

`PromptExactTokenizerV3` is the only tokenizer interface accepted by the V3
product compiler. Implementations receive the actual candidate or final
serialized bytes. A lookup table keyed by a pre-recorded digest is explicitly
outside the contract.

`ProcessExactTokenizerV3` is the production adapter supplied by Agentd. Before
each invocation it verifies:

- tokenizer executable SHA-256;
- vocabulary artifact SHA-256;
- normalization-policy artifact SHA-256;
- configured tokenizer/version identity.

The exact bytes are written only to the child process stdin. The child must
return one bounded canonical decimal token count on stdout. Timeouts, excess
output, malformed counts, artifact drift and non-zero exit status fail closed.
No raw prompt bytes are included in its `Debug` or error text.

The tokenizer binary itself, its vocabulary and its normalization policy remain
operator-supplied deployment artifacts. Their independent qualification is not
manufactured by this repository source.

## Serializer and provider-visible bytes

`CanonicalPromptSerializerV3` is crate-owned. It serializes typed selected
realizations into one deterministic UTF-8 JSON document. The serializer does
not accept caller-provided final bytes and does not prove inclusion by substring
search.

The serialized payload is then passed to the exact tokenizer. Consequently the
recorded token count includes canonical framing, item identities, roles and
payload text. The same payload digest is carried through:

- `ContextSerializationReceiptV2`;
- `ContextAttachmentV2`;
- `ContextDeliveryPreparationV2`;
- Core's final provider-input binding;
- `ProviderInvocationReceipt`;
- `ContextDeliveryReceiptV2`.

## Supported provider slots

The current Extension API exposes two real typed developer slots:

- `DeveloperPolicy`;
- `DeveloperCapabilities`.

`PromptExecutionProfileV3.provider_slot` is digest-bound and maps one canonical
bundle to exactly one of those slots. The current registry role admitted by the
product compiler is `DeveloperInstruction`.

The following roles remain fail-closed because Core does not yet expose exact,
typed provider slots for them:

- `SystemInstruction`;
- `UserTemplate`;
- `ToolSchemaFragment`.

Adding one of those roles requires an Extension API and provider-assembly
protocol revision. It must not be emulated by silently placing the bytes in a
different slot.

## Execution profile

`PromptExecutionProfileV3` binds all interpretation-sensitive identities:

- provider ID and provider revision;
- provider model and model revision;
- tokenizer label, binary digest, vocabulary digest, normalization digest and
  version;
- canonical serializer revision;
- template digest and revision;
- tool-schema digest and revision;
- provider prompt slot;
- maximum context tokens.

Changing any field changes the profile digest and invalidates reuse of the
compiled context or final-use proof.

## Durable behavior and retry safety

Before transport, Agentd persists:

- the canonical provider intent;
- the final-use proof;
- the construction-closed delivery-preparation archive;
- exact thread/turn and canonical provider-attempt identity.

A crash after that commit and before terminal observation remains unresolved.
The same turn is blocked from blind retry until reconciliation produces a
canonical provider receipt. `Indeterminate` does not become success.

Raw canonical context bytes stay in process memory. Durable state and diagnostic
output retain identities, lengths, digests and construction-closed evidence,
not prompt text.

## Legacy status

The former `PromptRuntimeHost` / `PromptRuntimeExtension` V1 path remains source
compatibility only. Agentd installs it solely when compiled with the explicit
`legacy-prompt-runtime-v1` feature. The default Agentd product composition
installs V3 and does not install the V1 runtime terminal path.

Legacy compilation APIs (`compile`, `compile_with_requirements`,
`compile_candidate_bound`) remain callable compatibility surfaces. Their
receipts are never promoted to the verified V2/V3 proof chain.

## Remaining gates

The following are intentionally unresolved outside this source candidate:

1. select and qualify the concrete provider tokenizer executable and artifacts;
2. exact-head and deterministic synthetic-merge execution receipts for the
   final candidate;
3. target-host crash/reopen, revoke-race, capacity and latency qualification;
4. independent security review of authority, tokenizer, provider and durable
   evidence boundaries;
5. operator acceptance, canary, activation, promotion and release.

Until those gates close, `productionImplementation`, `productExecutionProved`,
`independentAcceptance`, `activation` and `release` remain false in the
implementation map.
