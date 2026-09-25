# platform.wire current implementation

This document is the entry point for the **current executable** `platform.wire`
contract. The broader target architecture remains in
`docs/modules/platform.wire/TECHNICAL.md`.

## Current executable contract

| Capability | Source state | Current evidence |
| --- | --- | --- |
| Frozen HPTA V1 framing | implemented | `WIRE_V1.md`, V1 boundary tests and frozen vector |
| HPTA V2 metadata-bound digest | implemented | `WIRE_V2.md`, V2 mutation tests and frozen vector |
| HPTN version/capability negotiation | implemented | `NEGOTIATION_V1.md`; effective capabilities are restricted to the selected version |
| Negotiated session decode | implemented | `NegotiatedStreamingDecoder` rejects a different version at the fixed header, before allocating or accepting body bytes |
| Multi-version offline frame dispatch | implemented | `codex-rs/hepta-wire/src/frame.rs` |
| Schema admission | implemented framework | `SchemaRegistry` admits stable IDs/version/payload bounds; registered adapters pin producer identity |
| Typed payload serialization | implemented interface | `PayloadCodec`; each product schema supplies its strict canonical codec |
| Bounded streaming decode | implemented | header-first admission, valid-prefix/error batch reporting, poisoned terminal state and ownership-transfer buffering |
| Property testing and fuzz target | implemented source evidence | `src/property_tests.rs`, `fuzz/fuzz_targets/decode_frames.rs` |
| Bidirectional cross-runtime loading | implemented qualification source | Rust→Python and Python→Rust raw HPTN/HPTA V2 session test with strict critical-field rejection |
| Read-only runtime status caller | source-composed | explicit V2 `Accept` on the existing native-gateway runtime status route |
| Product-bound runtime.codex caller | source-composed | `hepta-infer-worker-host` admits its normal bound `turn/start` intent through HPTA V2 plus `hepta.codex-operation-intent.v3` before final-use claim |
| Production activation / external acceptance | not granted | requires separate exact-candidate, target-host, authenticated-transport and operator gates |

V1 continues to use its frozen payload-only digest. V2 binds schema, producer,
generation, encoded lengths and payload into a domain-separated SHA-256 frame
digest. Neither digest is a MAC or signature.

## Public symbols and source bindings

- V1 envelope: `codex-rs/hepta-wire/src/envelope.rs` — `WireEnvelope`.
- V2 envelope: `codex-rs/hepta-wire/src/envelope_v2.rs` — `WireEnvelopeV2`.
- negotiation: `codex-rs/hepta-wire/src/version.rs` — `NegotiationOffer`,
  `WireCapabilities`, `NegotiatedWire`, `negotiate`.
- negotiated connection decode: `codex-rs/hepta-wire/src/session.rs` —
  `NegotiatedStreamingDecoder`, `NegotiatedDecodeBatch`.
- multi-version offline dispatch: `codex-rs/hepta-wire/src/frame.rs` —
  `DecodedEnvelope`, `decode_frame`.
- schema admission / typed codec boundary: `codex-rs/hepta-wire/src/schema.rs`
  — `SchemaRegistry`, `PayloadCodec`.
- streaming decoder: `codex-rs/hepta-wire/src/stream.rs` —
  `StreamingDecoder`, `StreamDecodeBatch`.
- read-only caller: `codex-rs/hepta-runtime/src/lib.rs` —
  `HeptaRuntime::status_wire_v2`.
- read-only transport surface: `codex-rs/hepta-native-gateway/src/lib.rs`.
- registered `context.compiler` adapter:
  `codex-rs/hepta-context-compiler/src/wire.rs`.
- compatibility runtime.codex V2 adapter and product-bound V3 adapter:
  `codex-rs/hepta-codex-adapter/src/wire.rs`.
- normal product caller:
  `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` —
  `adapt_product_wire_v3` before final-use authorization and physical
  `turn/start`.

The existing JSON response from `GET /api/hepta/runtime` remains the default.
An explicit `Accept: application/x-hepta-wire; version=2` requests the V2
representation. Unknown wire media-version requests return
`406 Not Acceptable`.

The detailed product payload contract is in
[`RUNTIME_CODEX_V3.md`](RUNTIME_CODEX_V3.md). The historical
`hepta.codex-operation-intent.v2` payload schema remains closed and
product-unbound. It still rejects an App Server binding. The new
`hepta.codex-operation-intent.v3` schema requires the complete App Server
binding and preserves every field used by the domain request digest. Both use
HPTA frame version 2; the payload schema revision is independent of the frame
version.

## Durability and activation

The wire library is stateless. Streaming and negotiation state is
connection-local. A protocol/resource error poisons the decoder; bytes are not
accepted again until the previous connection is discarded. A new untrusted
connection must negotiate again rather than clearing and reusing old trust.

The normal inference-worker caller and read-only gateway caller are
source-composed. This document grants no effect authority, deployment
activation, operator acceptance, promotion or release. The V3 DTO carries
binding facts and digests, not `VerifiedUseToken` or another consumable grant.
The existing final-use owner still claims and enters authority immediately
before physical `turn/start`.

## Target-only design

The following remain outside the current `platform.wire` implementation or
require their owning integration:

- authenticated negotiation-transcript and encoded-frame binding at an
  untrusted production transport/session boundary;
- admission and qualification of additional product-domain schema codecs;
- current exact-head and deterministic synthetic-merge workflow receipts;
- independent target-host qualification, activation and external acceptance.

A MAC/signature layer belongs to the selected transport/session or security
owner. V2 deliberately does not turn the codec into an authority issuer.

## Known limits and non-claims

V1 payload integrity does not bind metadata. V2's frame digest binds metadata
but is unkeyed and therefore does not authenticate a peer. `decode_frame` is a
multi-version offline parser and intentionally does not represent connection
negotiation; live connections use `NegotiatedStreamingDecoder` to bind the
selected version. Version mismatch is terminal at the 54-byte header; it does not
wait for the advertised body, and poisoned sessions retain no partial frame.

`StreamingDecoder::push_batch` is the lossless incremental API: it can report a
valid completed prefix and a later terminal error from the same chunk.
`StreamingDecoder::push` remains a compatibility wrapper; if it returns a valid
prefix while recording a later error, the decoder's `terminal_error` must be
observed before continuing. A terminal decoder is poisoned and cannot be used
as a retry/recovery mechanism for the same stream.

Schema admission is a framework; each product schema supplies strict semantic
validation. Successful negotiation, decode, re-encode or product DTO admission
is not dispatch acknowledgement, terminal external success or authorization.
The owning transport still enforces read deadlines, connection limits and peer
authentication.

## Verification

Current source evidence includes:

- V1 and V2 unit, boundary and frozen-vector tests;
- effective-capability, downgrade and negotiation canonicality tests;
- negotiated-session header-only rejection, every-split valid-prefix delivery
  and partial-buffer release after a version mismatch;
- schema admission tests for missing and unknown critical fields;
- stream tests for chunking-invariant prefix delivery, true header-first
  rejection, poison state, buffer bounds and many-small-frame processing;
- deterministic property tests and a cargo-fuzz target;
- bidirectional raw-binary Rust↔Python HPTN/HPTA V2 tests, including duplicate
  JSON key and boolean-as-integer rejection;
- native-gateway content-negotiation tests;
- `context.compiler` strict schema/producer tests;
- runtime.codex V2 compatibility tests and V3 complete-binding
  round-trip/mutation tests;
- the existing runtime.codex product E2E, whose normal inference-worker path
  now calls `adapt_product_wire_v3`.

These paths are source/test identities until the exact candidate and required
merge/target-host workflows pass. The conformance vectors are additionally
machine-checked by the Lane A foundation verifier.

## Integration prerequisites

An untrusted producer/consumer pair authenticates the HPTN transcript and the
encoded HPTA frame using the selected transport/session security boundary.
Consumers register the exact schema descriptor and matching strict codec before
typed decode. Security-sensitive callers pin required capabilities during
negotiation and pass subsequent bytes through a decoder bound to the selected
version.

Normal runtime.codex product requests use payload schema V3 and canonical
producer `runtime.agentd`; V2 remains compatibility-only and unbound. Product
success still requires the existing durable dispatch, live owner revalidation,
final-use claim, physical App Server call and terminal observation chain.

Production claims additionally require exact-head and deterministic
synthetic-merge execution, target-host product execution, independent semantic
and security review, operator acceptance and the repository's activation,
promotion and release gates.
