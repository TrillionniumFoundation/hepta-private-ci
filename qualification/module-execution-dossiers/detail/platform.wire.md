# platform.wire: implementation design

Parent: `docs/modules/platform.wire/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: HPTA V1/V2 framing, negotiation, bounded streaming, schema admission and typed payload seams are source-implemented; remaining authenticated-transport and independent-acceptance gates are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented framing:** `WireEnvelope` preserves the frozen HPTA V1 contract and `WireEnvelopeV2` adds a separately versioned metadata-and-payload frame digest. V2 does not reinterpret V1.
- **Negotiation:** `negotiate` selects the highest explicitly common version satisfying required capabilities. Requiring `MetadataBoundIntegrity` excludes V1. The returned transcript digest is a binding value for an owning authenticated session; it is not authentication by itself.
- **Bounded decode:** whole-frame decoding remains available and `read_envelope` validates the 54-byte fixed header, version, identity lengths, generation and payload bound before allocating the body.
- **Schema/typed boundary:** `SchemaRegistry`, `ProducerAdmission`, `AdmissionPolicy` and `PayloadCodec` keep schema admission and typed decoding above the framing layer. Unknown schemas and denied producers fail closed.
- **Product caller source:** `HeptaRuntime::status_wire_v2` wraps one exact read-only status observation and the loopback native gateway exposes `GET /api/hepta/runtime.hpta`. This proves source composition only; it does not prove deployment or production activation.
- **Cross-runtime qualification:** `codex-rs/hepta-shadow-qualification/tests/cross_language_wire_v2.rs` performs a bidirectional Rust↔Python V2 exchange with independent Python digest/framing validation and Rust schema/producer admission.
- **Source tests:** V1 boundary/frozen-vector tests plus `envelope_v2_tests.rs`, `version_tests.rs`, `framed_tests.rs`, `property_tests.rs` and `schema_tests.rs`. These remain source test identities until exact-candidate receipts pass.
- **Implementation references:** [WIRE_V1.md](../../../docs/lane-a-foundation/platform.wire/WIRE_V1.md), [WIRE_V2.md](../../../docs/lane-a-foundation/platform.wire/WIRE_V2.md) and [CURRENT_IMPLEMENTATION.md](../../../docs/lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md).
- **Remaining work/gates:** authenticate complete V2 frame and negotiation binding in the selected non-loopback session/transport before active-tamper/downgrade claims; register production domain schemas at their owners; add host-specific async framing/deadline behavior where required; obtain exact-head/synthetic-merge, deployment, independent acceptance, promotion and release evidence.
