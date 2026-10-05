# platform.types normative protocol source V2

Current topology boundary: historical V1 retains exact legacy V3 verification; current V2 has a distinct HPTC schema-2 commitment and requires fresh selection. V1 effect admission is refused. Authenticated upgrade/restart/rollback qualification remains open. See `docs/modules/platform.types/TOPOLOGY_VERSION_MIGRATION_V2.md`.

The normative field/version/identity catalog for the current `platform.types`
protocol surface is the typed Rust value
`PLATFORM_TYPES_PROTOCOL_CATALOG_V2` in
`codex-rs/hepta-types/src/protocol_catalog_v2.rs`.

The exact-candidate qualification job compiles the Rust catalog and verifies
every referenced executable JSON Schema structurally. For each transport it
requires the exact declared property set, exact required set, deterministic
`kind` discriminator, a closed top-level object, and closed nested objects.
Simple string occurrence is not accepted as schema evidence. The job emits
three candidate-bound projections:

- `protocol-catalog.json` for machine consumption;
- `protocol-catalog.md` for reviewers;
- `schema-catalog-report.json` with schema byte digests and parity outcomes.

The projections are evidence artifacts, not separately editable normative
sources. Public Rust API compatibility is independently derived from rustdoc
JSON; the legacy exact-`pub use` inventory remains a narrow ownership projection
and is not described as the complete Rust API.

## Compatibility rules

`PromptDeliveryObservationV1` remains byte-for-byte frozen under its historical
custom commitment. It is never relabeled as HPTC. New publication uses
`PromptDeliveryObservationV2`, whose HPTC commitment may carry the exact V1
digest as an explicit migration witness.

`RegisteredNumericConversionReceiptV1` remains readable as content-addressed
compatibility evidence. New generation-sensitive admission uses V2, which binds
an explicit registry generation, registry digest, source and target profile
definition digests, normalization definition digest, and base conversion
receipt digest. V2 fields are private and the verifier reconstructs the entire
receipt from the source signal, target schema and immutable registry.

Existing V1 topology DTO fields remain public for source compatibility. Product
transport returns separate validated V1 historical and V2 current wrappers; consumers do not
receive an unvalidated topology from the product-owned codec.

## Ownership

Semantic contract ownership remains in `platform.types`. Strict JSON transport
and raw parser limits belong to `platform.wire`. Product-specific admission
belongs to the consuming owner: NDU for deterministic random streams and the
runtime supervisor for external-system and sensor calibration manifests.

The NDU random-stream owner pins the exact root-seed digest in its policy and
receipt in addition to namespace, generator/version, episode, decision and
counter window. This prevents a syntactically valid manifest from substituting
a different deterministic stream root under the same owner context.

Coverage-guided product-wire qualification invokes all six strict decoders;
its summary names the decoder set so Prompt/Topology-only fuzz execution cannot
be mistaken for complete manifest transport coverage.
