# platform.wire current implementation

## Current executable contract

`platform.wire` implements two immutable HPTA envelope versions plus bounded
protocol admission helpers.

- **HPTA V1** remains byte-for-byte frozen. It carries a payload-only SHA-256
  digest and rejects every version other than 1 in the V1 decoder.
- **HPTA V2** is a distinct wire version. It preserves the payload digest and
  adds a domain-separated complete semantic frame digest covering magic,
  version, identity lengths, generation, payload digest, payload length,
  schema, producer and payload. V2 never reinterprets V1 bytes.
- **Negotiation** selects the highest explicitly common implemented version
  from V1/V2 and fails closed when a caller-declared critical capability would
  be lost by fallback.
- **Schema admission** is explicit and registry-backed. Registered JSON schemas
  bound payload bytes, require declared fields, apply an unknown-field policy,
  and enforce nesting <= 32 and total map fields <= 1024 before typed decode.
- **Streaming framing** reads the fixed header first, validates version and
  advertised bounds, then allocates only the admitted body and invokes the
  corresponding immutable decoder.

The payload limit remains 1,048,576 bytes. Schema and producer identities remain
bounded `StableId` values of 1 through 128 ASCII bytes.

## Public symbols and source bindings

The immutable V1 codec remains in
`codex-rs/hepta-wire/src/envelope.rs` as `WireEnvelope`, `WireError` and
`MAX_WIRE_PAYLOAD_BYTES`.

V2 and protocol capabilities are implemented in:

- `codex-rs/hepta-wire/src/v2.rs`: `WireEnvelopeV2`, `WireV2Error`,
  `HPTA_V2_HEADER_BYTES`.
- `codex-rs/hepta-wire/src/negotiation.rs`: `negotiate`,
  `NegotiatedProtocol`, critical capability identifiers.
- `codex-rs/hepta-wire/src/schema.rs`: `SchemaRegistry`,
  `SchemaDefinition`, `TypedWirePayload`, `encode_typed`.
- `codex-rs/hepta-wire/src/stream.rs`: `FramedReader`, `FramedWriter`,
  `VersionedEnvelope`.

Source-level consumers are present in
`codex-rs/hepta-context-compiler/src/wire.rs` and
`codex-rs/hepta-codex-adapter/src/wire.rs`. These callsites prove composition
only; they do not by themselves prove deployment or production activation.

Frozen independent vectors are recorded in `HPTA_V1_CONFORMANCE.json` and
`HPTA_V2_CONFORMANCE.json`.

## Durability and activation

The codec, negotiation, schema registry and stream helpers are stateless
libraries. They own no durable domain state, network daemon, authority token or
effect acknowledgement.

`context.compiler` and `runtime.codex` now have source-level V2 composition.
A live Rust↔Python TCP qualification test exercises separate runtimes and real
socket framing. Production activation, target-host rollout, operator acceptance,
promotion and release remain separate gates and are not granted by this
document.

## Target-only design

The following remain outside the current executable claim:

- authenticated session establishment, key exchange and identity;
- cryptographic signatures or MACs created by `platform.wire`;
- generated bindings for every supported implementation language;
- a durable/distributed schema registry;
- transport deadlines, reconnect policy and effect retry semantics;
- production rollout and independent external acceptance.

A future V3 must use a new version value and independent frozen vectors. V1 and
V2 bytes and meanings cannot be changed in place.

## Known limits and non-claims

The V2 `frame_digest` covers protocol metadata and payload, but a digest carried
inside the same unauthenticated frame is **not** a signature or MAC. An attacker
who can rewrite the entire frame can recompute an ordinary SHA-256 digest.
Adversarial tamper resistance therefore requires an authenticated transport or
an authenticated out-of-band copy of the V2 frame digest.
`WireEnvelopeV2::decode_bound` supports the latter binding check.

Schema admission validates the registered transport payload shape and bounds; it
does not grant domain authority. Public DTOs remain distinct from
permission-bearing in-process tokens. Successful encode/decode, schema
admission or socket delivery is never an external-effect acknowledgement.

## Verification

Focused verification includes:

- every-prefix truncation rejection and frozen V1 vector;
- frozen independent 91-byte V2 vector;
- payload and metadata tamper rejection;
- critical-capability downgrade rejection;
- missing/unknown/unregistered schema rejection;
- fixed-header-first streaming admission and oversize rejection;
- deterministic property corpus for V1/V2 round trips and arbitrary-byte
  no-panic decoding;
- a `cargo-fuzz` target covering V1, V2 and streaming decoders;
- source-composition tests in `context.compiler` and `runtime.codex`;
- live Rust↔Python TCP V2 parsing, digest verification and schema admission.

Run the native package checks from `codex-rs` and the Lane A qualification
workflow for the exact candidate. Test source is not a substitute for an
exact-head execution receipt.

## Integration prerequisites

A transport owner must negotiate an implemented version before accepting a
frame, declare every critical capability that cannot be downgraded, configure
read deadlines outside this crate, and authenticate the session or bind the V2
frame digest out of band when adversarial integrity is required.

Consumers must register the exact schema revision before typed decode and must
keep domain authorization separate from serialized DTOs. Unknown versions,
unknown required fields, invalid bounds and digest mismatches fail closed.
