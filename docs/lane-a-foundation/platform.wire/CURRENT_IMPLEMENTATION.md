# platform.wire current implementation

This document is the current executable contract for `platform.wire`. It separates
implemented library behavior from target architecture and production activation.

## Current executable contract

The source crate `codex-rs/hepta-wire` currently implements two explicit HPTA
wire versions and four protocol-boundary layers.

| Surface | Current state | Executable meaning |
|---|---|---|
| HPTA V1 | implemented and byte-frozen | payload-only SHA-256 fault-detection digest; unknown versions reject |
| HPTA V2 | implemented | same bounded header shape with version `2`; SHA-256 digest binds schema, producer, generation and payload |
| Multi-version decode | implemented | `WireFrame::decode` dispatches only V1/V2 and rejects every unknown version |
| Version negotiation | implemented | `negotiate` chooses the highest explicitly common version satisfying minimum-version and critical-feature policy |
| Schema admission | implemented | `SchemaRegistry` accepts only registered schemas and runs the registered payload validator before typed decode |
| Typed serialization boundary | implemented | `PayloadCodec` binds one typed codec to one stable schema ID |
| Streaming frame read | implemented | `read_frame` reads and validates the fixed 54-byte header before allocating the bounded variable body |
| Cross-runtime loading | qualification evidence present | Rust V2 bytes are validated and answered by a live Python process, then decoded back in Rust |
| Registered product source consumers | source-composed | `runtime.codex::adapt_wire` and `context.compiler::compile_wire` consume negotiated, schema-admitted HPTA frames |
| Deployed production activation | not established | no deployed authenticated transport, production effect, acceptance, promotion or release is claimed |

V1 bytes and meanings remain governed by
[WIRE_V1.md](WIRE_V1.md) and
[HPTA_V1_CONFORMANCE.json](HPTA_V1_CONFORMANCE.json).
V2 bytes and digest scope are governed by
[WIRE_V2.md](WIRE_V2.md) and
[HPTA_V2_CONFORMANCE.json](HPTA_V2_CONFORMANCE.json).

## Public symbols and source bindings

- V1 framing: `WireEnvelope`, `WireError`, `MAX_WIRE_PAYLOAD_BYTES` in
  `codex-rs/hepta-wire/src/envelope.rs`.
- V2 and explicit multi-version dispatch: `WireEnvelopeV2`, `WireFrame`,
  `complete_frame_digest`, `HPTA_V1`, `HPTA_V2` in
  `codex-rs/hepta-wire/src/integrity.rs`.
- Negotiation: `WireOffer`, `WireVersion`, `WireFeature`,
  `NegotiationPolicy`, `NegotiatedWire`, `negotiate` in
  `codex-rs/hepta-wire/src/negotiation.rs`.
- Schema admission and typed serialization: `SchemaRegistry`,
  `SchemaAdmission`, `StaticSchemaAdmission`, `PayloadCodec` in
  `codex-rs/hepta-wire/src/schema.rs`.
- Incremental stream boundary: `read_frame`, `StreamWireError` in
  `codex-rs/hepta-wire/src/stream.rs`.

The crate root exports these surfaces from `codex-rs/hepta-wire/src/lib.rs`.

Two registered consumers now exercise the actual source contract:

- `codex-rs/hepta-codex-adapter/src/wire.rs` binds negotiated version,
  expected producer/generation and `runtime.codex.operation-intent.v1` before
  entering `adapt`;
- `codex-rs/hepta-context-compiler/src/wire.rs` binds the same ingress fences
  and `context.compiler.compilation-request.v1` before entering `compile`.

These are product-source callsites, not deployment receipts.

## Durability and activation

All current wire components are stateless library code. The streaming reader has
only caller-owned `Read` state for one invocation and creates no durable record.
Schema registrations are process-local objects supplied by the embedding owner.

Successful decode, schema admission, typed decode, negotiation or cross-runtime
qualification is not transport authentication, authorization, domain dispatch
acknowledgement, operator acceptance or production activation.

## Target-only design

The following remain outside the current executable claim:

- authenticated or keyed protection against an adversary that can rewrite a
  frame and recompute an unkeyed digest;
- deployment of the source-composed consumers through their selected
  authenticated transports and target hosts;
- future HPTA versions beyond V2 and their migration/drain policy;
- transport-specific asynchronous deadlines, connection lifecycle and retry
  semantics.

Those capabilities must be owned by their corresponding transport, authority or
integration boundary rather than silently added to the codec.

## Known limits and non-claims

V1 deliberately hashes payload bytes only. The regression
`v1_payload_digest_does_not_claim_metadata_integrity` freezes that non-claim so
future callers cannot infer metadata integrity from a successful V1 decode.

V2 hashes canonical metadata plus payload, but the digest is unkeyed SHA-256.
It detects accidental or unauthorized-in-place mutation when the attacker
cannot recompute the digest; it is not a MAC, signature, identity proof or
authority token. Adversarial source authentication still requires an
authenticated transport or an owning signature/MAC layer that binds the frame.

`SchemaRegistry` provides admission mechanics, not a universal schema language.
Each registered schema owns its validator and `PayloadCodec`; the wire layer
does not invent business semantics. `read_frame` is synchronous and leaves
deadlines/cancellation to the transport profile.

## Verification

Focused V1 tests remain in `envelope_tests.rs` and `boundary_tests.rs`.
Protocol-layer tests in `protocol_tests.rs` cover:

- V2 metadata/payload mutation rejection;
- highest-common negotiation and critical-feature downgrade rejection;
- registered-schema admission, missing required-field rejection and unknown
  field rejection through a concrete strict validator;
- header-before-body streaming admission and oversize rejection before body
  allocation;
- deterministic fuzz/property smoke over arbitrary byte inputs plus valid V2
  round trips.

The independent frozen V1 vector remains unchanged. The V2 conformance file
contains an independently computed 59-byte vector and `protocol_tests.rs`
freezes the same 59 bytes independently of the encoder. The product-boundary
test `codex-rs/hepta-shadow-qualification/tests/cross_language_wire_fault.rs`
performs live Rust↔Python V2 verification and reply-frame loading.

The registered source consumers add product-callsite tests in
`hepta-codex-adapter/src/wire_tests.rs` and
`hepta-context-compiler/src/wire_tests.rs`. Both reject negotiated-version
downgrade, producer mismatch, generation mismatch, schema mismatch and malformed
registered payloads before entering their existing domain operations.

Repository qualification still decides whether exact-head, merge-candidate,
lint and wider product suites pass for the candidate.

## Integration prerequisites

An embedding producer/consumer must negotiate before selecting a version when a
session can support more than one version. A policy requiring complete-frame
digest must require V2 and `WireFeature::CompleteFrameDigest`; failure to meet
that policy rejects rather than downgrades.

After framing decode, the consumer must admit the stable schema through its
registered `SchemaRegistry` and decode with the matching `PayloadCodec`.
Authority and domain validation occur after those steps at their owning
boundaries. `runtime.codex` and `context.compiler` now provide concrete
source-composed examples of this sequence. Production activation still requires
their named authenticated transport/caller, exact-candidate qualification and
the repository's separate activation/acceptance gates.
