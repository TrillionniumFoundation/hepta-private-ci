# context.compiler current product path

This document records the exact source-composed product candidate on branch
`codex/context-compiler-provider-closure-final-20260927`. It deliberately
separates source composition from exact-head execution, independent acceptance,
activation, promotion, and release.

## Current status

- Core verified-V2 compiler: implemented in source.
- Compiler-owned canonical context serialization: implemented in source.
- Typed snapshot-successor and pre-dispatch preparation: implemented in source.
- Exact final provider-request framing and tokenization seams: implemented in
  source; the concrete tokenizer executable and its vocabulary/normalization
  artifacts remain deployment inputs that require independent qualification.
- Durable pre-send and terminal evidence owner:
  `AgentdExactContextDeliveryOwner`.
- Physical provider-body observation: composed at the `codex-api` encoded-body
  boundary.
- Exact-head and deterministic synthetic-merge qualification: not asserted by
  source; only an immutable passing workflow receipt for the exact SHA can close
  either gate.
- Independent security acceptance: absent.
- Activation, promotion, and release: false.

## Actual source-composed call graph

```text
prompt registry / optimizer selection
  -> compile_prompt_registry_v2
       -> current durable registry realizations
       -> provisional request-scoped admission snapshot and records
       -> verify_admission_snapshot_v2
       -> verify_admission_v2
       -> compile_v2
       -> record_canonical_context_bundle_v2
       -> build_attachment

Agentd turn staging
  -> PromptRuntimeAttachmentV1
  -> AgentdExactContextDeliveryOwner stages source-bound delivery state

provider request finalization
  -> current verified snapshot successor
  -> verify_admission_snapshot_successor_typed_v2
  -> prepare_delivery_from_successor_v2
  -> host constructs the exact encoded provider body
  -> qualified FinalRequestFramingVerifierV2
  -> ExactFinalRequestTokenizerV2 over those exact bytes
  -> prove_final_provider_request_v2

physical provider effect
  -> durable pre-send claim in Agentd
  -> release the already-attested encoded body to transport

provider terminal
  -> canonical provider intent / attempt / terminal evidence
  -> observe_final_provider_delivery_v2
  -> ContextDeliveryReceiptV2
  -> durable Agentd terminal record
```

The compiler does not perform the network or model effect. The provider owner
must not reconstruct the body after proof generation: the bytes observed,
tokenized, durably claimed, and submitted are one identity.

## Byte identities

The path distinguishes four identities rather than treating them as synonyms:

1. **Canonical context bundle** — compiler-owned deterministic serialization of
   the selected typed realizations. Its digest is carried by
   `ContextSerializationReceiptV2`.
2. **Prompt fragments** — product-facing typed projections used during request
   assembly. Their attachment digest is useful composition evidence but is not
   proof of the final provider body.
3. **Final provider request** — the exact encoded body after provider/model
   framing and before transport encoding such as compression or signing. It is
   the input to `ExactFinalRequestTokenizerV2` and the subject of
   `FinalProviderRequestProofV2`.
4. **Provider wire-semantic digest** — the secret-free canonical semantic
   identity of the physical provider attempt. It binds provider, endpoint,
   model, request kind, transport semantics, and logical input, but is not a
   byte-for-byte substitute for the final-request digest.

## Admission authority

The current branch still constructs a request-scoped admission verifier,
snapshot, and admission records inside the prompt-product composition layer.
Those records are bound to the selected durable registry realizations, scope,
authority domain, generation vector, expiry, and deny-all posture, but the
issuer and verifier have not yet been split into independently controlled
capabilities.

Accordingly, source composition does **not** yet establish an independently
qualified admission authority. The production cutover requires a registry-owned
or separately owned authority that:

- issues opaque authenticated admission records and current snapshots;
- exposes verification without exposing signing/issuing capability;
- binds key/verifier identity, schema revision, scope, authority domain,
  generation, expiry, and the complete revocation frontier;
- produces a construction-closed direct-successor proof for the snapshot bound
  into the attachment;
- fails closed on missing, stale, forked, rolled-back, or unauthenticated state.

`VerifiedAdmissionSnapshotSuccessorV2` closes the compiler-side lineage shape,
but it does not by itself qualify the concrete authority implementation.

## Serializer

`record_canonical_context_bundle_v2` owns the strict serializer. Product callers
supply typed realized items, not arbitrary final payload bytes. The serializer
constructs a deterministic envelope containing stable item identities, roles,
content digests, and exact content. A caller-supplied prepared payload or a
substring-occurrence proof is not accepted on the strict path.

The resulting payload digest flows through compilation serialization,
attachment, delivery preparation, exact final-request framing, provider attempt
evidence, and the terminal delivery receipt.

## Tokenizer and interpretation profile

The final-request tokenizer receives the actual encoded provider body. Its
identity binds at least:

- provider and provider revision;
- provider model and model revision;
- tokenizer label and version;
- tokenizer executable digest;
- vocabulary digest;
- normalization-policy digest;
- declared model-profile tokenizer identity.

A digest-keyed lookup table or a pre-recorded sum of item token costs is outside
the strict final-request contract. Missing executables, artifact drift,
timeouts, malformed output, excess output, non-zero exit status, or identity
mismatch fail closed.

The repository supplies the interface and proof chain; selection and independent
qualification of concrete tokenizer artifacts remain deployment gates.

## Provider framing and supported roles

The framing verifier must prove that the final request contains exactly one
canonical context segment and that every remaining byte belongs to a
provider/model-qualified framing segment. Segment maps must be total,
non-overlapping, gap-free, ordered, and bound to the exact request digest.

The currently composed runtime profile projects only
`PromptRoleV2::DeveloperInstruction` into a real developer-policy slot.
`SystemInstruction`, `UserTemplate`, and `ToolSchemaFragment` remain fail-closed
until Core and the Extension API expose exact typed slots for them. They must not
be silently relabeled as developer policy.

## Durable behavior and retry safety

Before transport, Agentd persists the exact preparation, final-request proof,
provider attempt identity, and pre-send claim. A crash after that commit and
before terminal observation remains unresolved after reopen and blocks blind
retry. `Indeterminate` is not converted into success; terminal replacement is
accepted only under the documented monotone reconciliation rule and for the
same exact attempt identity.

Raw context and final-request bytes must remain outside diagnostic formatting
and durable evidence records. Debug and error surfaces may expose identities,
lengths, digests, status, and bounded reason codes only.

## Legacy status

The V1 compilation entry points (`compile`, `compile_with_requirements`, and
`compile_candidate_bound`) and the earlier prompt-runtime terminal receipt remain
compatibility surfaces. Their receipts are never promoted into the verified V2
provider-closure proof chain.

The branch has not yet completed a default-off feature cutover for all V1
product composition. Until that gate is implemented and verified, the
implementation map must report legacy cutover as incomplete even when the V2
source path is composed.

## Open proof and release gates

The following remain open until evidenced on the final exact SHA:

1. independently controlled admission authority and authenticated current
   revocation frontier;
2. direct-source fixes compiling without a self-modifying CI workflow;
3. redacted `Debug` coverage for every raw context/request holder;
4. explicit default-off V1 product feature gate;
5. exact typed provider slots beyond developer policy;
6. property, fuzz, model-based, crash/reopen, revoke-race, capacity, and
   target-host latency evidence;
7. exact-head and deterministic synthetic-merge receipts;
8. independent security review;
9. operator acceptance, canary, activation, promotion, and release.

Until those gates close, `productExecutionProved`, `independentAcceptance`,
`activation`, and `release` remain false. Source composition must not be used as
a synonym for any of them.
