# platform.wire: implementation design

Parent: `docs/modules/platform.wire/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: immutable HPTA V1 remains the promoted current contract; the HPTA V2 protocol-layer candidate now implements full-frame integrity, explicit negotiation, schema admission/typed payloads, bounded incremental decoding and named product-source composition. Exact-candidate qualification and externally governed activation/acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Owner root: `codex-rs/hepta-wire`.
Integration source: `codex-rs/hepta-codex-adapter/src/wire.rs`.
Qualification source: `codex-rs/hepta-shadow-qualification/tests/cross_language_wire_fault.rs`.
Package: `P0.7E-DEPENDENCY-INVERSION` plus cross-owner integration review for the named runtime caller.

Preserve V1 bytes and semantics. New semantics use a new version value and never create another authority or execution spine.

## 2. Public operations and contract details

Current candidate native operations are:

- `WireEnvelope::encode/decode` — immutable HPTA V1 payload-digest framing.
- `WireEnvelopeV2::encode/decode` — HPTA V2 digest over versioned metadata, identities, generation, declared lengths and payload.
- `negotiate(local, remote)` — highest explicitly common version whose capability intersection satisfies both sides' required capabilities.
- `SchemaRegistry::{register, admit_v1, admit_v2, encode_v2, decode_v1, decode_v2}` — exact schema/version/bound admission and typed payload loading.
- `WireFrameDecoder::push` — incremental single-frame decoding with fixed-header admission before body buffering.

Unknown versions and unknown schemas reject. V1 is never reinterpreted as V2. A successful decode/encode is never an effect acknowledgement.

## 3. State records and transaction design

No domain state or durable writer. `WireFrameDecoder` owns only connection-local buffered bytes and expected frame length; it is reset on disconnect/protocol failure. `SchemaRegistry` is explicitly caller-owned and introduces no hidden global mutable state.

Negotiation produces a canonical transcript digest. When downgrade resistance matters, the owning secure session authenticates that digest. Serialized DTOs never become permission-bearing in-process tokens.

## 4. Deterministic algorithm and scheduling

V1 decodes its frozen layout exactly. V2 first validates header bounds and exact frame length, parses canonical identities, then recomputes a domain-separated SHA-256 preimage containing magic, version, lengths, generation, schema, producer and payload. The embedded digest detects stale/accidental whole-frame mutation but is not an authenticator; active-attacker resistance requires a MAC/signature/secure channel over the complete frame or `transport_binding_digest()`.

Incremental decoding buffers 54 header bytes first, validates version/identity/generation/payload bounds, then consumes only the exact remaining body for one frame. If a caller supplies multiple concatenated frames, `consumed` stops at the first frame and leaves the remainder with the caller.

Schema admission is above framing. Domain owners implement `WirePayload` and are responsible for required-field, unknown-critical-field and canonical-value validation.

## 5. Capacity and performance profile

Global payload <= 1,048,576 bytes; schema and producer identities are each 1..128 bytes. Schema registrations may impose stricter payload ceilings. The incremental decoder never buffers an unbounded queue and does not reserve the body before header admission.

Incomplete-frame deadlines, throughput measurements and selected-host resource budgets remain transport/host responsibilities and are not inferred from source limits.

## 6. Concrete verification cases

- WIRE-01: every V1 truncation rejects; incremental V2 header/body chunking completes exactly one bounded frame and rejects oversized advertised payloads before body buffering.
- WIRE-02: unknown versions reject; required V2 integrity prevents downgrade to V1; unknown/disallowed schemas and non-canonical typed payloads reject.
- WIRE-03: V1 frozen vector remains exact; V2 has an independent frozen vector and deterministic property round trips; raw Rust→Python process IPC independently recomputes V2 digest and loads the registered typed JSON schema.
- WIRE-04: wire DTOs remain non-authoritative; no wire type constructs a consumable authority token.
- WIRE-05: V2 schema/producer/generation/payload mutations fail whole-frame integrity unless the unkeyed digest is recomputed; secure transport authentication is therefore still mandatory against an active attacker.

Source tests are identities, not pass receipts. Exact-head and deterministic merge-candidate executions remain required before claim promotion.

## 7. Integration, rollback and capability ceiling

`codex-rs/hepta-codex-adapter/src/wire.rs` is the first named product-source composition. It registers the exact `runtime.codex.operation-intent.v1` typed schema and requires negotiated V2 `FULL_FRAME_INTEGRITY` plus `SCHEMA_ADMISSION` before encode/decode.

`codex-rs/hepta-shadow-qualification/tests/cross_language_wire_fault.rs` is a real cross-runtime process-pipe test, not merely two Rust functions agreeing: Python consumes raw binary V2 bytes, independently verifies the digest, admits the exact schema, loads typed JSON and rejects metadata/payload faults.

Rollback retains readable immutable V1. No V1 byte meaning changes. Production deployment, operator acceptance, promotion and release remain separate gates.

## 8. Current native implementation

- **Promoted current contract:** `WireEnvelope` V1 in `codex-rs/hepta-wire/src/envelope.rs`, specified by `docs/lane-a-foundation/platform.wire/WIRE_V1.md` and `HPTA_V1_CONFORMANCE.json`.
- **Source-complete V2 candidate:** `WireEnvelopeV2` in `v2.rs`, specified by `WIRE_V2.md` and `HPTA_V2_CONFORMANCE.json`.
- **Negotiation:** `negotiation.rs` implements explicit version/capability selection, required-capability downgrade prevention and canonical transcript binding.
- **Schema admission:** `schema.rs` implements explicit schema registry, per-schema wire versions/bounds and typed `WirePayload` codecs.
- **Streaming:** `stream.rs` implements fixed-header-first bounded incremental decoding for V1/V2.
- **Robustness:** `property_tests.rs` covers generated round trips, arbitrary-byte no-panic regression, metadata mutation and chunk-size variation.
- **Named integration:** `hepta-codex-adapter/src/wire.rs` composes a typed runtime schema on V2.
- **Cross-runtime evidence source:** `hepta-shadow-qualification/tests/cross_language_wire_fault.rs` loads V2 across Rust/Python process boundaries.
- **Remaining work at this claim boundary:** execute exact-head and merge-candidate tests/lints, preserve independent review, and bind an authenticated deployed transport/session before production activation. No unimplemented core codec/negotiation/schema/stream API remains in the candidate scope.
