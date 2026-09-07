# platform.wire: implementation design

Parent: `docs/modules/platform.wire/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-wire`.
Packages: `P0.7E-DEPENDENCY-INVERSION`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
