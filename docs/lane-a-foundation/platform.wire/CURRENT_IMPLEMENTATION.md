# platform.wire current implementation

This document is the entry point for the **current executable** `platform.wire`
contract. The broader target architecture remains in
`docs/modules/platform.wire/TECHNICAL.md`.

## Current capability status

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

## Executable source map

- V1 envelope: `codex-rs/hepta-wire/src/envelope.rs`
- V2 envelope: `codex-rs/hepta-wire/src/envelope_v2.rs`
- negotiation: `codex-rs/hepta-wire/src/version.rs`
- multi-version dispatch: `codex-rs/hepta-wire/src/frame.rs`
- schema admission / typed codec boundary: `codex-rs/hepta-wire/src/schema.rs`
- streaming decoder: `codex-rs/hepta-wire/src/stream.rs`
- product source caller: `codex-rs/hepta-runtime/src/lib.rs`
- product transport surface: `codex-rs/hepta-native-gateway/src/lib.rs`

The existing JSON response from `GET /api/hepta/runtime` remains the default.
An explicit
`Accept: application/x-hepta-wire; version=2`
requests the V2 representation. Unknown wire media-version requests return
`406 Not Acceptable`.

## Integrity boundary

V1 retains its historical payload-only digest exactly. V2 binds schema,
producer, generation, encoded lengths and payload into a domain-separated
SHA-256 frame digest. Neither digest is a MAC or signature. Untrusted
transports must authenticate the HPTN negotiation transcript and encoded frame
at the owning transport/session layer.

## Schema boundary

A frame schema ID is not sufficient to admit a payload. A consumer registers a
`SchemaDescriptor`, then admission checks the exact schema ID, compatible
wire version and payload bound before the matching `PayloadCodec` performs
typed semantic decode. Codecs must reject missing required fields, unknown
critical fields and non-canonical representations.

## Qualification boundary

The repository now contains native unit/boundary/property tests, a cargo-fuzz
target, a Rust↔Python live binary-session test and a real read-only gateway
source callsite. These facts do **not** grant deployment, production effect
authority, independent semantic acceptance, canary promotion or release.
