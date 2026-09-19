# platform.wire: implementation design

Parent: `docs/modules/platform.wire/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: HPTA V1 remains immutable; HPTA V2 framing, negotiation, schema admission, bounded streaming and source composition are implemented. Execution receipts, authenticated transport qualification, production activation and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

The source implementation now supplies native tests for WIRE-01 through WIRE-04, including a frozen V2 vector, property corpus, source-composed adapters and a live Rust↔Python TCP oracle. Test source is still not an exact-head execution receipt or independent external acceptance.

## 7. Integration, rollback and capability ceiling

Every affected producer/consumer executes a contract test against one frozen schema. Domain logic and SQL stay outside this crate. Rollback requires the preceding wire version to remain readable or a documented protocol drain; no dual semantic interpretation of one version.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **V1:** `WireEnvelope` in `codex-rs/hepta-wire/src/envelope.rs` remains the immutable fixed HPTA V1 codec.
- **V2:** `WireEnvelopeV2` in `src/v2.rs` adds payload digest plus a domain-separated complete semantic frame digest. `decode_bound` can require an expected digest delivered through an authenticated out-of-band channel.
- **Negotiation:** `negotiate` in `src/negotiation.rs` selects the highest explicitly common implemented version and refuses fallback that loses a caller-declared critical capability.
- **Schema admission:** `SchemaRegistry` in `src/schema.rs` binds exact schema IDs, required/optional fields, unknown-field policy, byte limits, nesting <= 32 and object-field count <= 1024 before typed JSON decode.
- **Streaming:** `FramedReader` in `src/stream.rs` admits the fixed header and advertised limits before allocating the body, then dispatches to the immutable V1/V2 decoder.
- **Source composition:** `hepta-context-compiler/src/wire.rs` produces a V2 transport DTO after real compilation; `hepta-codex-adapter/src/wire.rs` admits a V2 DTO before the existing runtime.codex binding/deadline/terminal checks. Serialized DTOs carry no authority.
- **Cross-runtime evidence source:** `hepta-shadow-qualification/tests/cross_runtime_wire_v2.rs` runs a separate Python process over TCP and verifies HPTA V2 framing, both digests and strict schema admission.
- **Property/fuzz:** `protocol_tests.rs` includes a deterministic round-trip/arbitrary-byte corpus; `hepta-wire/fuzz/fuzz_targets/decode.rs` provides a cargo-fuzz target.
- **Normative current references:** `docs/lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md`, `WIRE_V1.md`, `WIRE_V2.md`, and both conformance JSON vectors.
- **Remaining gates:** authenticated session establishment is owned by the selected transport/security boundary; exact-head and merge-candidate execution receipts, target-host product qualification, operator acceptance, production activation, promotion and release are not claimed by source implementation.
