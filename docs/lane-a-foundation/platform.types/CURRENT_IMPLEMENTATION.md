# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is an authority-free Rust primitive library. It owns
bounded byte/text values, stable identifiers, digests, nonzero monotonic
generation/revision/sequence values, checked Q32 values and registered numeric
signal conversion. The crate forbids unsafe code and owns no clock, network,
filesystem, credential, process-global registry or durable writer.

## Public symbols and source bindings

- `BoundedBytes`, `BoundedText`, `BoundedValueError`:
  `src/bounded.rs`.
- `StableId`, `Generation`, `Revision`, `LogicalSequence`,
  `AuthorityPosture`, `IdentityError`: `src/identity.rs`.
- `Digest32`, `DigestParseError`: `src/digest.rs`.
- `FixedQ32`, `ProbabilityQ32`: `src/fixed.rs`.
- `NumericProfileV1`, `NumericSignalV1`, `rescale_signal` and conversion
  receipts: `src/numeric_profile.rs` and `src/numeric_conversion.rs`.

`IdentityError` is exported from the crate root so consumers can name the
constructor error without depending on a private module path.

## Durability and activation

The module is stateless and has no durability. It is a library-only dependency;
its values grant no runtime or effect authority.

## Target-only design

Generated cross-language bindings, a broader unit/profile registry and a
runtime schema registry are target-only. Any external representation requires a
separately versioned encoding and independent vectors.

## Known limits and non-claims

Rust type equality is not a frozen wire representation. `Digest32::of_bytes`
performs raw SHA-256; protocol owners must provide domain separation and
canonical framing. Generic bounded values are not secret containers, and their
debug representations must not be used for credentials.

## Verification

Native tests cover bounds, invalid identifiers, digest parsing/stability,
monotonic overflow, Q32 errors, profile mismatch, numeric overflow, rounding and
error bounds. `CAPABILITY_EVIDENCE_MAP.json` binds each current capability to
its exact source and positive/negative tests.

## Integration prerequisites

A consumer must name the semantic type and version, preserve exact values for
authority/fence fields, define domain-separated digests and add a frozen wire
contract before making cross-language compatibility claims.
