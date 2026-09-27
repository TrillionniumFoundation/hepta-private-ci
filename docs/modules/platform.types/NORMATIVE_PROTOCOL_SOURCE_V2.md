# platform.types normative protocol source V2

The normative field/version/identity catalog for the current `platform.types`
protocol surface is the typed Rust value
`PLATFORM_TYPES_PROTOCOL_CATALOG_V2` in
`codex-rs/hepta-types/src/protocol_catalog_v2.rs`.

The exact-candidate qualification job compiles the Rust catalog, verifies that
every referenced executable JSON Schema exists and contains every declared
field, and emits two candidate-bound projections:

- `protocol-catalog.json` for machine consumption;
- `protocol-catalog.md` for reviewers.

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
transport returns `ValidatedRuntimeTopologyCandidateV1`; consumers do not
receive an unvalidated topology from the product-owned codec.

## Ownership

Semantic contract ownership remains in `platform.types`. Strict JSON transport
and raw parser limits belong to `platform.wire`. Product-specific admission
belongs to the consuming owner: NDU for deterministic random streams and the
runtime supervisor for external-system and sensor calibration manifests.
