# platform.wire current implementation

## Current executable contract

The current library implements two immutable HPTA envelope versions plus
transport-neutral protocol admission helpers.

| Capability | Current executable state |
| --- | --- |
| HPTA V1 | frozen payload-digest codec; bytes and semantics unchanged |
| HPTA V2 | additive full-semantic-frame digest codec |
| Version negotiation | highest explicitly common V1/V2; required capabilities fail closed |
| Downgrade prevention | a required `FullFrameDigest` cannot negotiate V1 |
| Schema admission | bounded registry with exact schema IDs, per-schema payload limits and validators |
| Typed payloads | `TypedPayload` encode/decode helpers for both V1 and V2 |
| Incremental framing | 54-byte header admission before body buffering; at most one partial frame retained |
| Cross-runtime evidence | Rust V2 producer to independent Python parser over loopback TCP |
| Property coverage | generated valid round trips plus arbitrary-byte no-panic/buffer-bound checks |
| Production activation | not claimed |

HPTA V1 remains specified by `WIRE_V1.md`. HPTA V2 is specified by
`WIRE_V2.md`. Unknown versions reject; no decoder guesses compatibility.

## Public symbols and source bindings

Primary public surfaces are exported by `codex-rs/hepta-wire/src/lib.rs`:

- `WireEnvelope`, `WireError`, `MAX_WIRE_PAYLOAD_BYTES`
- `WireEnvelopeV2`, `WireV2Error`
- `WireVersion`, `WireFeature`, `WireOffer`, `NegotiatedWire`, `negotiate`
- `SchemaRegistry`, `SchemaRule`, `SchemaAdmissionError`, `TypedPayload`
- `encode_typed_v1`, `decode_typed_v1`, `encode_typed_v2`, `decode_typed_v2`
- `WireStreamDecoder`, `StreamProgress`, `DecodedEnvelope`, `MAX_WIRE_FRAME_BYTES`

The frozen V1 and V2 vectors are
`HPTA_V1_CONFORMANCE.json` and `HPTA_V2_CONFORMANCE.json`.

## Durability and activation

All current protocol state is process-local. `WireStreamDecoder` owns only a
partial frame buffer and expected length; completing a frame resets that state.
`SchemaRegistry` is an in-process admission table. Neither is a durable store
or an authority source.

No production caller, deployment activation, operator acceptance, promotion or
release is asserted by this document.

## Target-only design

The following remain outside the current executable contract:

- authenticated transport/session binding or an independently verified frame signature/MAC;
- externally governed/distributed schema registry publication and revocation;
- product-specific production caller composition and rollout;
- operator acceptance, promotion and release evidence.

These are intentionally not simulated by the codec.

## Known limits and non-claims

The V2 frame digest is SHA-256 integrity evidence, not authentication. V1 still
binds only payload bytes and must not be used where metadata integrity is
required unless an owning authenticated layer binds the complete V1 frame.

Schema admission validates a registered schema identifier, payload size and
caller-supplied validator. It does not make arbitrary payload bytes safe and
does not convert serialized data into permission-bearing in-process objects.

The incremental decoder bounds its own allocation; the transport still owns
timeouts, connection lifetime, rate limiting and peer authentication.

## Verification

Native package tests exercise V1 compatibility, V2 frozen bytes and metadata
tamper rejection, negotiation/downgrade failure, schema and typed-codec
admission, one-byte streaming, exact frame-boundary consumption, header-first
oversize rejection, generated round trips and arbitrary bytes.

`codex-rs/hepta-wire/tests/cross_runtime.rs` launches a separate Python
runtime, transfers raw V2 bytes over TCP and requires Python to independently
reconstruct the digest preimage before accepting the frame.

Run from `codex-rs`:

`cargo test --locked -p codex-hepta-wire`

`cargo clippy --locked -p codex-hepta-wire --all-targets -- -D warnings`

Repository CI remains the executed receipt; command text alone is not a pass.

## Integration prerequisites

A session owner must construct local/remote `WireOffer` values from reviewed
capabilities, call `negotiate`, and pin the resulting version for the
connection. Required features must never be silently dropped.

After frame decoding, the consumer must run `SchemaRegistry::admit_v1` or
`SchemaRegistry::admit_v2` (or an equivalent product registry) before domain
use, then invoke the matching typed/domain decoder.

Production composition remains a separate gate and must name its actual caller,
transport authentication, schema registry source, resource profile and rollback.
