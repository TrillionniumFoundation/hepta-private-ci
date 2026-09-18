# platform.wire: implementation design

Parent: `docs/modules/platform.wire/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: HPTA V1/V2 protocol stack implemented in source, including integrity-bound V2, negotiation, schema admission, typed payload codecs and bounded stream decoding; production composition and independent acceptance remain outside the claim boundary. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-wire`.
Packages: `P0.7E-DEPENDENCY-INVERSION`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`WireFrame::decode` dispatches only frozen V1 and integrity-bound V2. `negotiate(local_versions, remote_versions, critical_features)` is implemented as the `negotiate` API and selects the highest explicitly common version satisfying required capabilities; requiring `FullFrameIntegrity` prevents downgrade to V1. `SchemaRegistry::admit` enforces registered schema/version/payload-validator policy before `PayloadCodec` typed loading. `read_frame` and `WireStreamDecoder` provide bounded transport-neutral framing. These APIs do not invent a framing format for Codex JSON-RPC or reinterpret unknown critical fields.

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

- **V1 compatibility:** \`WireEnvelope\` in [envelope.rs](../../../codex-rs/hepta-wire/src/envelope.rs) preserves the frozen HPTA V1 bytes and payload-only digest semantics.
- **V2 integrity:** \`WireEnvelopeV2\` in [v2.rs](../../../codex-rs/hepta-wire/src/v2.rs) uses version 2 and a domain-separated digest binding version, lengths, generation, schema, producer and payload.
- **Version dispatch and negotiation:** \`WireFrame::decode\` rejects unknown versions; \`negotiate\` selects the highest common known version and enforces required critical capabilities.
- **Schema and typed serialization:** \`SchemaRegistry::admit\` requires exact registered schema/version/bounds/validator policy before a matching \`PayloadCodec\` may load a typed value. \`encode_typed_v2\` binds a codec schema directly to V2 production.
- **Streaming:** \`read_frame\` validates the fixed 54-byte header before body allocation. \`WireStreamDecoder\` caps connection-local buffering at two maximum frames and clears state on protocol failure.
- **Source tests:** V1 boundary/golden tests, V2 integrity/golden tests, negotiation/schema/stream tests, deterministic property-style decoder tests, and the cargo-fuzz harness are source evidence. [cross_runtime_wire_transport.rs](../../../codex-rs/hepta-shadow-qualification/tests/cross_runtime_wire_transport.rs) adds live Python -> TCP -> Rust V2 framing, schema admission and typed loading.
- **Normative references:** [CURRENT_IMPLEMENTATION.md](../../../docs/lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md), [WIRE_V1.md](../../../docs/lane-a-foundation/platform.wire/WIRE_V1.md), [WIRE_V2.md](../../../docs/lane-a-foundation/platform.wire/WIRE_V2.md), and both frozen conformance vectors.
- **Remaining work:** authenticated binding of the negotiation transcript to the selected production transport/session; product-owned schema catalog composition; target-host execution evidence; production caller activation; independent acceptance, canary, promotion and release. The source implementation does not claim any of those gates.
