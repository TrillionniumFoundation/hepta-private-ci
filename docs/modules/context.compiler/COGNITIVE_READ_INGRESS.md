# Revision-bound cognitive read and exact tokenizer integration

This supplement describes source integration boundaries, not product execution,
provider acceptance or release. The implementation map records the exact source
identity; no execution claim follows from the API names below.

## Source ingress

`verify_cognitive_read_ingress_v2` accepts a complete revision-bound canonical
shadow with 1..4096 rows. It checks the cheap envelope before canonical event and
provenance validation. Every accepted row is active and verified.
`compile_cognitive_read_v2` then requires the exact candidate set, source digest,
generation vector and the `UntrustedEvidence` role. V2 admission remains an
independent check over actual rendered bytes, secret classification, scope and
authority domain. A shadow integrity digest does not authenticate an owner or
make a memory record a trusted instruction.

The existing Agentd intelligence port still invokes V1 `compile`; the native
cognitive context publication/final-use path has its own owner revalidation and
planning boundary. Neither is an ordinary provider-bound V2 ingress caller.
Compaction's exact-read candidate API is also separate from normal checkpoint
publication, reconstruction qualification and reload.

## Exact tokenizer capability

The prompt portfolio adapter previously treated registry `token_cost` bounds as
exact counts and reported their sum for the final serialized payload. A current
source probe accepted both 9 bytes and 100009 bytes as 4 tokens with a 4-token
budget. The latter contains the same selected prompt plus additional framing.
This violated the V2 final-payload budget boundary.

The adapter now exposes explicit capability APIs:

- `compile_exercised_prompt_context_with_tokenizer_v1` counts actual selected
  registry bytes using a supplied `ExactTokenizerV2`.
- `prepare_prompt_delivery_with_tokenizer_v1` supplies that backend to V2
  `record_serialization`, so the complete serialized payload, including framing,
  counts against the compilation budget.
- `compile_prompt_registry_with_tokenizer_v2` composes those two steps against
  the existing registry owner. Its tokenizer identity must match the frozen
  model profile.

The earlier signatures remain available for compatibility, but return typed
`ExactTokenizerUnavailable` rather than fabricating an exact proof from cost
metadata. This includes the ordinary Agentd prompt pipeline while no qualified
backend is supplied. It does not silently substitute a unit-fixture tokenizer.
The companion APIs are explicit integration surfaces; their unit fixtures do
not establish ordinary provider composition.

## Remaining product work and verification

An owning integration must supply the real model tokenizer, admission authority,
serializer and provider evidence verifier. It must bind the actually submitted
provider payload, revalidate owner generations and revocation immediately before
physical dispatch, and authenticate the exact attempt and terminal evidence.
Adding a fixture backend or a metadata estimate does not close these obligations.

The added adversarial tests cover framing over budget and missing capability.
Other fixtures continue to cover source/materialization drift and revocation,
with explicit deterministic tokenizers supplied only inside unit tests. Full
crate, ordinary product and target-host execution remain separate gates.
