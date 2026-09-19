# platform.wire current implementation

This document is the entry point for the **current executable** `platform.wire`
contract. The broader target architecture remains in
`docs/modules/platform.wire/TECHNICAL.md`.

## Current executable contract

| Capability | Source state | Current evidence |
| --- | --- | --- |
| Frozen HPTA V1 framing | implemented | `WIRE_V1.md`, V1 boundary tests and frozen vector |
| HPTA V2 metadata-bound digest | implemented | `WIRE_V2.md`, V2 mutation tests and frozen vector |
| HPTN version/capability negotiation | implemented | `NEGOTIATION_V1.md` and downgrade tests |
| Multi-version frame dispatch | implemented | `codex-rs/hepta-wire/src/frame.rs` |
| Schema admission | implemented framework | `SchemaRegistry` admits stable IDs, version range and payload bounds |
| Typed payload serialization | implemented interface | `PayloadCodec`; each product schema supplies its canonical codec |
| Bounded streaming decode | implemented | validates 54-byte header before advertised body, max two frames buffered |
| Property testing | implemented | deterministic randomized round-trip and arbitrary-byte decoder tests |
| Fuzz target | implemented | `codex-rs/hepta-wire/fuzz/fuzz_targets/decode_frames.rs` |
| Live cross-runtime loading | implemented qualification path | Rust↔Python raw binary HPTN + HPTA V2 session test |
| Named product source caller | source-composed | read-only runtime status can be returned as V2 by the native gateway when explicitly requested |
| Production activation / external acceptance | not granted | requires separate exact-candidate, target-host and operator gates |

V1 continues to use its frozen payload-only digest. V2 binds schema, producer,
generation, encoded lengths and payload into a domain-separated SHA-256 frame
digest. Neither digest is a MAC or signature.

## Public symbols and source bindings

- V1 envelope: `codex-rs/hepta-wire/src/envelope.rs` — `WireEnvelope`
- V2 envelope: `codex-rs/hepta-wire/src/envelope_v2.rs` — `WireEnvelopeV2`
- negotiation: `codex-rs/hepta-wire/src/version.rs` — `NegotiationOffer`, `WireCapabilities`, `negotiate`
- multi-version dispatch: `codex-rs/hepta-wire/src/frame.rs` — `DecodedEnvelope`, `decode_frame`
- schema admission / typed codec boundary: `codex-rs/hepta-wire/src/schema.rs` — `SchemaRegistry`, `PayloadCodec`
- streaming decoder: `codex-rs/hepta-wire/src/stream.rs` — `StreamingDecoder`
- product source caller: `codex-rs/hepta-runtime/src/lib.rs` — `HeptaRuntime::status_wire_v2`
- product transport surface: `codex-rs/hepta-native-gateway/src/lib.rs`

The existing JSON response from `GET /api/hepta/runtime` remains the default.
An explicit `Accept: application/x-hepta-wire; version=2` requests the V2
representation. Unknown wire media-version requests return
`406 Not Acceptable`.

## Durability and activation

The wire library is stateless. Streaming/negotiation state is connection-local
and is discarded on disconnect. The read-only gateway caller is source-composed
but this document grants no production activation, effect authority, operator
acceptance, promotion or release.

## Target-only design

The following remain outside the current `platform.wire` implementation or
require their owning integration:

- authenticated negotiation-transcript and encoded-frame binding at an
  untrusted production transport/session boundary;
- admission and qualification of additional product-domain schema codecs;
- independent target-host qualification, activation and external acceptance.

A cryptographic MAC/signature layer must belong to the transport/session or
security owner; V2 deliberately does not turn the codec into an authority
issuer.

## Known limits and non-claims

V1 payload integrity does not bind metadata. V2's frame digest binds metadata
but is still unkeyed and therefore does not authenticate a peer. Schema
admission is a framework; each product schema must supply a strict
`PayloadCodec`. Successful negotiation/decode/re-encode is not dispatch
acknowledgement, terminal external success or authorization.

The streaming decoder bounds its own connection-local buffer. The owning
transport must still enforce read deadlines, connection limits and
authentication.

## Verification

Current source evidence includes:

- V1 and V2 unit/boundary/frozen-vector tests;
- negotiation capability and downgrade tests;
- schema admission tests for missing/unknown critical fields;
- incremental stream and buffer-bound tests;
- deterministic property tests and a cargo-fuzz target;
- a raw-binary Rust↔Python HPTN + HPTA V2 session test;
- native gateway content-negotiation tests.

The vectors are machine-checked by the Lane A foundation verifier. Source tests
are not independent acceptance receipts until the exact candidate and required
merge/target-host workflows pass.

## Integration prerequisites

An untrusted producer/consumer pair must authenticate the HPTN transcript and
the encoded HPTA frame using the selected transport/session security boundary.
Consumers must register the exact schema descriptor and matching strict codec
before typed decode. Security-sensitive callers must pin required capabilities
during negotiation so required V2 integrity/schema properties cannot silently
downgrade to V1.

Production claims additionally require exact-head and deterministic
synthetic-merge execution, target-host product execution, independent semantic
and security review, operator acceptance and the repository's activation,
promotion and release gates.
