# platform.wire: implementation design

Parent: `docs/modules/platform.wire/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: HPTA V1 remains frozen; V2 metadata binding, HPTN negotiation, schema admission, streaming decode and a named read-only product source caller are implemented. Remaining evidence and acceptance gates are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-wire`.
Packages: `P0.7E-DEPENDENCY-INVERSION`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`decode_envelope(bytes, negotiated_version, limits) -> TypedEnvelope | DecodeError` accepts only the registered transport's framing and canonical payload schema. `encode_envelope(value, version) -> bytes` is the inverse on supported values. `negotiate(local_versions, remote_versions, critical_features) -> CompatibleVersion | Incompatible` selects the highest explicitly common version. It must not invent a new framing format for Codex JSON-RPC or reinterpret unknown critical fields.

## 3. State records and transaction design

No domain state or durable writer. Connection-local decoder state consists of frame length, bytes received, schema version and deadline; it is discarded on disconnect. A connection restart negotiates again. Public DTOs are distinct from permission-bearing in-process objects; serialized witnesses cannot be cast into VerifiedUse tokens.

## 4. Deterministic algorithm and scheduling

Apply size/depth/count admission before recursively decoding. Resolve message discriminator and version, validate bounded fields, then hand a typed object to the domain owner. Keep transport errors separate from rejected domain commands and unknown external-effect outcomes. Never infer a retry-safe effect from a successful re-encode.

## 5. Capacity and performance profile

Pilot envelope <= 1 MiB subject to stricter protocol bounds; nesting <= 32; at most 1024 map fields; decoder buffer <= 2 maximum frames per connection; incomplete-frame deadline is supplied by the transport profile.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- WIRE-01: truncation at every frame boundary returns incomplete/rejected without domain invocation.
- WIRE-02: unknown critical version/field rejects; additive optional fields follow the registered compatibility policy.
- WIRE-03: maximum-size round trip and cross-language golden encodings are exact.
- WIRE-04: a serialized authority witness never constructs a consumable token.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Every affected producer/consumer executes a contract test against one frozen schema. Domain logic and SQL stay outside this crate. Rollback requires the preceding wire version to remain readable or a documented protocol drain; no dual semantic interpretation of one version.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `WireEnvelope` in [codex-rs/hepta-wire/src/envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs); `WireEnvelopeV2` in [codex-rs/hepta-wire/src/envelope_v2.rs](../../../codex-rs/hepta-wire/src/envelope_v2.rs); `negotiate` in [codex-rs/hepta-wire/src/version.rs](../../../codex-rs/hepta-wire/src/version.rs); `SchemaRegistry` in [codex-rs/hepta-wire/src/schema.rs](../../../codex-rs/hepta-wire/src/schema.rs); `StreamingDecoder` in [codex-rs/hepta-wire/src/stream.rs](../../../codex-rs/hepta-wire/src/stream.rs). Multi-version dispatch is provided by `decode_frame` in `src/frame.rs`.
- **Negotiation:** `NegotiationOffer`, `WireCapabilities` and `negotiate` in `src/version.rs` implement the bounded HPTN V1 hello and select only an explicitly common locally implemented version. Required capability pinning prevents a caller that requires V2 metadata binding from silently falling back to V1.
- **Schema admission and typed serialization:** `SchemaRegistry`, `SchemaDescriptor` and `PayloadCodec` in `src/schema.rs` separate framing from product schema validation. Unknown schemas, incompatible wire versions and payload-bound violations reject before typed decode; codecs own required/unknown-field semantics.
- **Streaming:** `StreamingDecoder` in `src/stream.rs` validates the fixed 54-byte header before accepting the advertised body and caps connection-local buffering at two maximum-size frames.
- **Integrity:** V1 retains the historical payload-only digest. V2 computes a domain-separated unkeyed SHA-256 over magic, version, lengths, generation, schema, producer and payload. Neither digest is a MAC/signature; authenticated transcript/frame binding remains the transport/session owner's responsibility.
- **Source composition:** `hepta-runtime::HeptaRuntime::status_wire_v2` encodes the existing read-only status payload, and `hepta-native-gateway` returns it only when the existing runtime route receives `Accept: application/x-hepta-wire; version=2`; the default JSON representation is unchanged and unknown wire media versions return 406.
- **Verification sources:** V1/V2 boundary and frozen-vector tests, negotiation downgrade tests, schema tests, stream tests, deterministic property tests, a cargo-fuzz target, a raw-binary Rust↔Python HPTN+V2 session test, and gateway content-negotiation tests. These are source/test identities until exact-candidate workflow receipts are current.
- **Current references:** `docs/lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md`, `WIRE_V1.md`, `WIRE_V2.md`, `NEGOTIATION_V1.md`, `HPTA_V1_CONFORMANCE.json`, `HPTA_V2_CONFORMANCE.json` and `HPTN_V1_CONFORMANCE.json`.
- **Remaining work/evidence:** authenticate negotiation+frame at the selected untrusted transport/session boundary; register each additional production domain schema/codec; run exact-head plus synthetic-merge qualification and target-host product execution; obtain independent semantic review, operator acceptance, activation, promotion and release. Source composition alone does not grant those states.
