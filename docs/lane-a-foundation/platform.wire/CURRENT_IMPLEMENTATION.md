# platform.wire current implementation

## Claim boundary

The current source implements HPTA V1 and V2 framing, deterministic
version/capability negotiation, bounded stream decoding, bounded schema/producer
admission, and a generic typed-payload codec boundary. V1 remains byte-for-byte
frozen. V2 binds protocol metadata and payload into one domain-separated
unkeyed SHA-256 frame digest.

The V2 digest and negotiation binding are integrity/transcript digests, **not
authentication**. An active peer can recompute an unkeyed digest. A selected
session or transport that claims tamper or downgrade resistance must
authenticate the complete frame and negotiation binding.

## Implemented source surfaces

- `WireEnvelope`: immutable HPTA V1 codec.
- `WireEnvelopeV2`: metadata-and-payload-bound HPTA V2 codec.
- `negotiate`: highest-common version selection with required capabilities
  and a role-ordered transcript binding digest.
- `read_envelope`: one-frame bounded blocking reader that validates the fixed
  header before allocating the body.
- `SchemaRegistry`, `ProducerAdmission`, `AdmissionPolicy`: bounded
  post-framing admission.
- `PayloadCodec`, `encode_typed`, `decode_typed`: schema-bound typed
  serialization seam without effect authority.

## Composed caller

The live read-only Hepta runtime wraps one exact status-organ observation in
HPTA V2 and the loopback native gateway exposes it at
`GET /api/hepta/runtime.hpta`. The existing JSON status route remains
unchanged. The HPTA envelope generation is the status wire-contract generation;
runtime snapshot generations remain inside the payload.

This is a non-test source caller, not proof of deployment, remote transport
authentication, production activation, external effect authority, operator
acceptance, promotion or release.

## Cross-runtime qualification

The shadow qualification suite contains a bidirectional Rust↔Python V2 test.
Rust negotiates V2 and emits a typed request; an independent Python parser
checks the complete V2 digest and strict request schema, emits a V2 reply, and
Rust then applies producer/schema admission and typed decoding.

## Remaining gates

- authenticate the V2 frame and negotiation binding in a selected session or
  transport before claiming active-tamper or downgrade resistance;
- bind production domain schemas and compatibility policy at their owning
  consumers;
- provide async transport framing/deadline behavior where the selected host
  requires it;
- pass exact-head/synthetic-merge qualification and all external activation,
  independent acceptance, promotion and release gates.
