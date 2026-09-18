# platform.wire current implementation

## Current executable contract

platform.wire currently exposes two immutable HPTA envelope formats plus
transport-neutral protocol helpers.

- HPTA V1 remains byte-for-byte frozen. Its embedded SHA-256 digest binds only
  payload bytes. V1 bytes and meanings are not reinterpreted.
- HPTA V2 keeps the same 54-byte fixed header layout but uses version 2 and an
  integrity digest over a domain-separated canonical preimage containing magic,
  version, schema length, producer length, generation, payload length, schema,
  producer and payload. The on-wire digest field itself is excluded from the
  preimage.
- WireFrame::decode dispatches only versions 1 and 2. Unknown versions reject.
- negotiate selects the highest explicitly common known version satisfying all
  required capabilities. Requiring FullFrameIntegrity rejects downgrade to V1.
- SchemaRegistry admits only explicitly registered schema IDs, allowed wire
  versions, payload bounds and schema validators. Admitted payloads may then be
  decoded by a matching typed PayloadCodec.
- read_frame reads and validates the fixed 54-byte header before allocating the
  advertised body. WireStreamDecoder caps buffered bytes at two maximum frames
  and clears connection-local state on malformed or unsupported input.

The library remains authority-free. Successful decode, negotiation, admission
or typed loading is not authorization, dispatch acknowledgement or external
terminal success.

## Public symbols and source bindings

- V1 framing: codex-rs/hepta-wire/src/envelope.rs
  - WireEnvelope, WireError, WIRE_VERSION_V1, MAX_WIRE_PAYLOAD_BYTES
- V2 integrity framing: codex-rs/hepta-wire/src/v2.rs
  - WireEnvelopeV2, WIRE_VERSION_V2
- Version dispatch: codex-rs/hepta-wire/src/protocol.rs
  - WireFrame, EnvelopeView
- Negotiation: codex-rs/hepta-wire/src/negotiation.rs
  - WireVersion, WireCapability, NegotiatedWire, negotiate
- Schema admission and typed serialization:
  codex-rs/hepta-wire/src/schema.rs
  - SchemaRegistry, SchemaDefinition, AdmittedPayload, PayloadCodec,
    encode_typed_v2
- Bounded stream decoding: codex-rs/hepta-wire/src/stream.rs
  - read_frame, WireStreamDecoder, MAX_WIRE_FRAME_BYTES,
    MAX_STREAM_BUFFER_BYTES

Normative byte-level references are WIRE_V1.md, WIRE_V2.md,
HPTA_V1_CONFORMANCE.json and HPTA_V2_CONFORMANCE.json.

## Durability and activation

The crate is stateless and owns no durable domain store. Schema registration is
process-local configuration. Stream decoder buffering is connection-local and
must be discarded on disconnect or protocol failure.

The current source does not establish a production caller, production transport
or release activation. The live Rust-Python TCP test is qualification evidence,
not deployment evidence.

## Target-only design

The following remain outside the current executable claim:

- binding the negotiation transcript to an authenticated production session;
- product-owned schema catalog population and lifecycle policy;
- transport-specific deadlines, cancellation and asynchronous I/O adapters;
- generated SDK bindings for non-Rust product runtimes;
- production caller composition, canary, operator acceptance and release.

## Known limits and non-claims

V2 full-frame integrity is an integrity commitment, not authentication,
authorization, encryption or a digital signature. An active attacker that can
replace both bytes and digest is stopped only when the owning transport or
session authenticates the frame or transcript.

SchemaRegistry does not infer schemas. Each schema owner supplies an exact
StableId, allowed wire-version range, payload limit and validator. Typed codecs
must reject unknown critical or required fields according to that schema.

The blocking read_frame helper does not own a timeout. The selected transport
must supply deadlines. WireStreamDecoder caps memory but does not itself own a
socket or event loop.

## Verification

Current source tests cover:

- V1 frozen vectors, every truncation, boundary lengths, invalid identities,
  unknown version and payload corruption;
- V2 independent 59-byte golden vector and metadata/payload tamper rejection;
- highest-common negotiation and integrity-required downgrade prevention;
- schema registration, unknown schema rejection, validator rejection and typed
  encode/admit/decode;
- bounded blocking and incremental stream decoding;
- deterministic property-style round trips across V1/V2 and arbitrary-byte
  no-panic decoding;
- a cargo-fuzz target for WireFrame and WireStreamDecoder;
- a live Python -> TCP -> Rust V2 qualification path that performs bounded
  framing, integrity verification, schema admission and typed JSON loading, plus
  a metadata-tamper negative connection.

Source test presence is not an execution receipt. Exact-head and merge-candidate
CI results remain the evidence boundary.

## Integration prerequisites

A product integration must:

1. negotiate only explicitly supported versions and require
   FullFrameIntegrity when metadata integrity is required;
2. authenticate or otherwise bind the negotiation/session transcript when
   downgrade or tamper resistance matters;
3. register the exact schema before accepting payloads and apply the matching
   typed codec only after admission;
4. use read_frame or an equivalently bounded transport reader so advertised
   lengths are checked before body allocation;
5. keep V1 compatibility semantics frozen and use V2 rather than changing V1;
6. preserve the rule that protocol success grants no execution authority or
   external-effect acknowledgement.
